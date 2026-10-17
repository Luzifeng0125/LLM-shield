"""Verify the active local models and, optionally, a public-only API round trip."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connect', action='store_true', help='向配置的生成服务发送固定公开活动短句')
    args = parser.parse_args()
    os.environ.update(SHIELD_USE_GLINER='true', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      TOKENIZERS_PARALLELISM='false', PYTHONDONTWRITEBYTECODE='1')
    import torch
    torch.set_num_threads(4)
    from fastapi.testclient import TestClient
    from llm_shield.server import app
    from llm_shield.chat import STORE, send_turn
    from llm_shield.schema import Material
    with TestClient(app) as client:
        health = client.get('/api/health').json()
        assert health['ready_local'] and health['gliner_enabled'] and 'gliner' in health['detectors']
        assert client.get('/').status_code == client.get('/notice').status_code == 200
        assert 'campus_ner' not in client.get('/api/config').json()['models']
        review = client.post('/api/notice/review', json={
            'text': '负责人：张三，电话13812345678。'}).json()
        assert review['local_only'] and not review['external_model_called']
        assert review['counts'].get('PHONE') == 1
        session = STORE.create('student_leader', 'activity_stats')
        result = send_turn(session, [Material('synthetic-table', 'uploaded', '合成测试表', '',
            [{'专业': '网络空间安全'}, {'专业': '其他'}, {'专业': '网络空间安全'}], ['专业']),
            Material('chat-input', 'uploaded', '', '帮我统计网络空间安全专业有多少人')])
        assert result['ok'] and result['engine'] == 'local' and '共有 2 人' in result['reply']
        report = {'local_models': 'passed', 'gliner_enabled': True, 'local_roster': 'passed',
                  'local_whole_table_count': 'passed', 'real_generation': 'not_requested'}
        if args.connect:
            session = STORE.create('student_leader', 'meeting_minutes')
            started = time.perf_counter()
            result = send_turn(session, [Material('chat-input', 'uploaded', '',
                '校园活动将于周五举行。请把这条公开信息改写成一句简短通知，不要添加其他信息。')])
            assert result['ok'] and result['engine'] == 'real', result.get('pause_reason', 'No real reply')
            report.update(real_generation='passed', response_characters=len(result['reply']),
                          round_trip_ms=round((time.perf_counter() - started) * 1000))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
