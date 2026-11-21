#!/usr/bin/env python
"""隐盾 LLM-Shield 一键启动。

用法：
    python run.py                 # 启动本地服务，默认 http://127.0.0.1:8787
    python run.py --port 9000
    python run.py --reload        # 开发模式，代码改动自动重启
"""
from __future__ import annotations

import argparse
import os
import sys

from llm_shield.config import load_env


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(description="隐盾 LLM-Shield 本地受控服务")
    ap.add_argument("--host", default=os.getenv("SHIELD_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("SHIELD_PORT", "8787")))
    ap.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启")
    args = ap.parse_args()

    import uvicorn

    print("=" * 60)
    print("  隐盾 LLM-Shield · 本地受控服务")
    print(f"  地址: http://{args.host}:{args.port}")
    print("  说明: 所有敏感信息处理均在本机完成，云端模型只接收脱敏后文本")
    print("=" * 60)

    uvicorn.run("llm_shield.server:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
