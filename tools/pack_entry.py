"""隐盾 LLM-Shield · exe 启动入口（PyInstaller onefile）。

双击「隐盾.exe」即可：准备好用户数据目录 → 起本地服务 → 自动打开浏览器。

可选参数（命令行传，双击时不带参数用默认值）：
    --host 127.0.0.1      监听地址，默认 127.0.0.1（只本机可访问）
    --port 8787           端口，被占用时自动顺延到下一个可用端口
    --no-browser          不自动打开浏览器

与源码启动（python run.py）的差别只有两点：
1. 这里用 uvicorn.run(app) 直接起服务，**不开 --reload**（打包后没有源码可监听）；
2. 启动前先 bootstrap_user_files()，把 .env 从 exe 内部铺到 exe 同级目录，
   让用户能改配置，也避免 onefile 每次解压到新临时目录导致配置丢失。
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

# Windows 控制台默认可能是 GBK，中文提示会变成乱码。
# line_buffering 必须开：重定向到管道时 print 默认是块缓冲，
# 不开的话双击 exe 的用户在前 30 秒（解压 + 导入 sklearn）里什么都看不到，以为卡死了。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

print("隐盾正在启动，首次运行需要解压依赖，请稍候…")


def pick_port(host: str, preferred: int, tries: int = 20) -> int:
    """端口被占用时顺延找下一个可用端口，避免直接崩掉。"""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return preferred


def open_when_ready(url: str, timeout: float = 90.0) -> None:
    """轮询到服务真能响应再开浏览器。

    onefile 首次启动要先解压依赖（可能十几秒），立刻开浏览器只会看到
    「无法访问此页面」，所以这里等到 /api/config 有响应再开。
    """
    def worker() -> None:
        import urllib.request
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url + "/api/config", timeout=2):
                    break
            except Exception:
                time.sleep(0.5)
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    # 环境变量必须先加载，后面读 port/host 才拿得到用户配置的值
    from llm_shield.config import USER_DIR, bootstrap_user_files, load_env
    load_env()
    bootstrap_user_files()
    print("配置已就绪，正在加载判别模型…")

    import os
    ap = argparse.ArgumentParser(description="隐盾 LLM-Shield 本地受控服务")
    ap.add_argument("--host", default=os.getenv("SHIELD_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("SHIELD_PORT", "8787")))
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    port = pick_port(args.host, args.port)
    if port != args.port:
        print(f"[提示] 端口 {args.port} 被占用，已改用 {port}")
    url = f"http://{args.host}:{port}"

    print("=" * 62)
    print("  隐盾 LLM-Shield · 本地受控服务")
    print(f"  控制台     {url}")
    print(f"  对话页     {url}/chat")
    print(f"  数据目录   {USER_DIR}")
    print("  所有敏感信息处理均在本机完成，云端模型只接收脱敏后文本")
    print("  关闭本窗口即可停止服务")
    print("=" * 62)

    if not args.no_browser:
        open_when_ready(url)

    import uvicorn
    from llm_shield.server import app
    # 打包后固定用 python 解释器路径会有问题，这里显式给 app 对象而不是字符串
    uvicorn.run(app, host=args.host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
