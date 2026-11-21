"""Start the merged GLiNER service using local configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))


def main(argv=None) -> int:
    from llm_shield import config
    config.load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--offline', action='store_true', help='显式使用模拟生成，仍启用 GLiNER')
    parser.add_argument('--port', type=int, default=int(os.getenv('SHIELD_PORT', '8787')))
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('端口须介于 1024 和 65535')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                      SHIELD_USE_GLINER='true')
    if args.offline:
        os.environ['LLM_MODE'] = 'mock'
    else:
        os.environ.setdefault('LLM_MODE', 'real')
    try:
        import torch
        torch.set_num_threads(4)
        from llm_shield.runtime import readiness
        from llm_shield.m2_detect.pipeline import build_detectors
        state = readiness()
        if not state['ready_local']:
            print(json.dumps(state, ensure_ascii=False), flush=True)
            print('本地模型预检失败：请检查 models/gliner_v3 和动作权重。', file=sys.stderr)
            return 1
        detector = next(item for item in build_detectors() if item.name == 'gliner')
        spans = detector.detect('负责人：张三。')
        state.update(gliner_device=detector.device, fixture_spans=len(spans))
        from llm_shield.server import app
        import uvicorn
    except Exception as exc:
        print(f'启动预检失败（{type(exc).__name__}），请按安装文档检查依赖和本机权重。', file=sys.stderr)
        return 1
    print(json.dumps(state, ensure_ascii=False), flush=True)
    if args.check_only:
        return 0
    print(f'隐盾：http://127.0.0.1:{args.port}/；名单核对：/notice', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='info')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
