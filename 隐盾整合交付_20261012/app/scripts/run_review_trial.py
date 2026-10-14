"""运行固定合成试标集并生成离线复核页面；默认为 mock，真实调用必须指定 --real。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))


def run_cases(cases: list[dict], *, real=False) -> list[dict]:
    from llm_shield.chat import ChatStore, send_turn
    from llm_shield.schema import Material
    import llm_shield.m7_egress.gateway as gateway

    records = []
    store = ChatStore()
    actual_generator = gateway.chat_messages_with_fallback
    with patch.dict(os.environ, {'LLM_MODE': 'real' if real else 'mock'}):
        for case in cases:
            session = store.create('student_leader', case['task'])
            for index, turn in enumerate(case['turns'], 1):
                calls = []

                def capture(messages):
                    # This hook is reached only after the complete outgoing conversation passes precheck.
                    captured = {'messages': copy.deepcopy(messages)}
                    calls.append(captured)
                    result = actual_generator(messages)
                    captured['result'] = copy.deepcopy(result)
                    return result

                with patch.object(gateway, 'chat_messages_with_fallback', capture):
                    response = send_turn(session, [Material(
                        doc_id='trial', doc_type='uploaded', title='合成试标材料', text=turn)])
                records.append({'unit_id': f"{case['id']}-{index}", 'task': case['task'],
                                'original_turn': turn, 'original_history': case['turns'][:index],
                                'generator_called': bool(calls),
                                'network_requested': real and bool(calls),
                                'outgoing': calls, 'response': response})
            store.delete(session.session_id)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', help='允许将通过检查的固定合成样例发送给配置的 API，最多 9 次请求')
    parser.add_argument('--out', type=Path, default=APP.parent / '人工复核/试标运行')
    args = parser.parse_args()
    from llm_shield.config import llm_settings
    settings = llm_settings()
    if args.real and not settings.get('api_key'):
        parser.error('本机密钥为空；没有发起请求。')
    # Trial inputs are fixed synthetic materials supplied with this tool, never uploaded user documents.
    case_path = APP / 'data/review/trial_cases.json'
    cases = json.loads(case_path.read_text(encoding='utf-8'))
    records = run_cases(cases, real=args.real)
    weights = APP / 'models/necessity_action.joblib'
    if not weights.exists():
        weights = next((APP / 'models').rglob('necessity_action.joblib'))
    evidence = {'schema': 1, 'dataset': 'synthetic_trial_not_human_gold',
                'mode': 'real' if args.real else 'mock',
                'provider': settings['provider'], 'model': settings['model'],
                'weights_sha256': hashlib.sha256(weights.read_bytes()).hexdigest(),
                'cases_sha256': hashlib.sha256(case_path.read_bytes()).hexdigest(), 'records': records}
    tracked = sorted([*(APP / 'llm_shield').rglob('*.py'), *(APP / 'config').glob('*.yaml')])
    evidence['code_config_sha256'] = hashlib.sha256(b''.join(
        p.relative_to(APP).as_posix().encode('utf-8') + b'\0' + p.read_bytes() for p in tracked)).hexdigest()
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    # Unique folders avoid overwriting existing annotations or frozen evidence.
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / digest[:12]
    out.mkdir(exist_ok=False)
    (out / 'evidence.json').write_text(serialized, encoding='utf-8')
    template = (APP / 'scripts/review_template.html').read_text(encoding='utf-8')
    embedded = json.dumps({'evidence_hash': digest, **evidence}, ensure_ascii=False).replace('<', '\\u003c')
    (out / '独立复核.html').write_text(template.replace('__EVIDENCE_JSON__', embedded), encoding='utf-8')
    print(json.dumps({'mode': evidence['mode'], 'units': len(records), 'human_reviewed': False,
                      'paused': sum(bool(r['response'].get('paused')) for r in records),
                      'output': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
