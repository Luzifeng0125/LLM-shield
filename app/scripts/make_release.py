#!/usr/bin/env python
"""把项目打包成可分发的 zip。

排除清单（重要，勿随意放宽）：
  - .env / .env.local —— 含真实 API 密钥，绝不能进压缩包
  - data/uploads/     —— 用户上传的真实材料（姓名/手机号等）
  - models/           —— 保留模型清单；本机权重由维护者按授权另行提供
  - outputs/          —— 评测产物与临时文件
  - .workbuddy/       —— 项目工作数据
  - 虚拟环境、__pycache__、日志、已有 zip

用法：
    python scripts/make_release.py
    python scripts/make_release.py --out ../local/exports/llm-shield-source.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DOCUMENTS = {"models/ACTIVE_MODELS.json", "models/MODEL_RELEASE.json", "models/README.md"}


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "."],
                            check=True, capture_output=True)
    return [ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name]


def runtime_files() -> list[Path]:
    scripts = {"start_service.py", "check_runtime.py", "verify_merged_runtime.py"}
    files = []
    for path in tracked_files():
        name = path.relative_to(ROOT).as_posix()
        parts = Path(name).parts
        selected = (
            parts[0] in {"llm_shield", "config", "web"}
            or parts[:2] == ("data", "fixtures")
            or parts[0] == "scripts" and path.name in scripts
            or len(parts) == 1 and (path.name.startswith("requirements") or path.name in {"README.md", ".env.example"})
            or name in MODEL_DOCUMENTS
        )
        if parts[:2] == ("llm_shield", "m9_data") or name == "llm_shield/m4_necessity/train.py":
            selected = False
        if path.name in {"requirements-presidio.txt", "requirements-presidio-eval.txt", "requirements-nemo.txt"}:
            selected = False
        if selected and path.is_file() and (name in MODEL_DOCUMENTS or not should_skip(path)):
            files.append(path)
    return sorted(files)

# 需要排除的目录名（出现在路径任意层级即排除）
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".workbuddy", "outputs", "models", "logs", "uploads",
    ".idea", ".vscode", ".DS_Store",
}
# 需要排除的文件名
EXCLUDE_FILES = {".env", ".env.local", ".env.production"}
# 需要排除的扩展名
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".log", ".zip", ".joblib",
                  ".bin", ".pt", ".pth", ".safetensors"}


def should_skip(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True
    if set(rel.parts) & EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_FILES or (path.name.startswith(".env.") and path.name != ".env.example"):
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIX:
        return True
    return False


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}GB"


def main() -> int:
    ap = argparse.ArgumentParser(description="打包隐盾项目为 zip")
    ap.add_argument("--out", default=None, help="输出路径，默认在项目同级目录")
    ap.add_argument("--version", default="dev")
    ap.add_argument("--profile", choices=["source", "runtime"], default="source")
    args = ap.parse_args()

    out = Path(args.out) if args.out else ROOT.parent / f"隐盾-LLM-Shield-v{args.version}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    files = runtime_files() if args.profile == "runtime" else [
        p for p in sorted(tracked_files()) if p.is_file()
        and (p.relative_to(ROOT).as_posix() in MODEL_DOCUMENTS or not should_skip(p))]
    if not files:
        print("没有可打包的文件")
        return 1

    total_raw = 0
    skipped: list[str] = []

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        manifest = {"profile": args.profile, "version": args.version, "files": []}
        for p in files:
            total_raw += p.stat().st_size
            z.write(p, p.relative_to(ROOT))
            manifest["files"].append({"path": p.relative_to(ROOT).as_posix(),
                                      "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
        if args.profile == "runtime":
            start = '@echo off\r\n"%~dp0.venv\\Scripts\\python.exe" -X utf8 "%~dp0scripts\\start_service.py" %*\r\n'
            z.writestr("start.cmd", start)
            manifest["files"].append({"path": "start.cmd", "sha256": hashlib.sha256(start.encode()).hexdigest()})
            instructions = (
                "# 隐盾运行包\n\n"
                "使用 Python 3.12。在本目录执行以下命令。\n\n"
                "    python -m venv .venv\n"
                "    .venv\\Scripts\\python.exe -m pip install -r requirements-lock.txt -r requirements-gliner.txt\n\n"
                "从团队的受控来源取得活动动作文件 models/necessity_action.joblib 和完整的 GLiNER 目录 models/gliner_v3，包含权重、配置和分词器。"
                "权重 SHA-256 见 models/ACTIVE_MODELS.json。也可用 SHIELD_GLINER_MODEL_DIR 指定已有完整目录。"
                "复制 .env.example 为 .env，填写获准生成服务。\n\n"
                "    start.cmd --check-only\n"
                "    start.cmd\n\n"
                "服务默认地址为 http://127.0.0.1:8787/。启动前核对本机动作权重与 GLiNER 的摘要。"
                "安装 OCR 或集成组件时按对应 requirements 文件安装。"
                "运行包的 RELEASE_MANIFEST.json 列出每个文件的 SHA-256。\n"
            )
            z.writestr("INSTALL.md", instructions)
            manifest["files"].append({"path": "INSTALL.md", "sha256": hashlib.sha256(instructions.encode()).hexdigest()})
        z.writestr("RELEASE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    # 记录被排除的敏感/大体积项，便于人工核对
    for name in (".env",):
        if (ROOT / name).exists():
            skipped.append(f"{name}（含密钥）")
    for d in ("data/uploads", "outputs", ".workbuddy"):
        if (ROOT / d).exists():
            skipped.append(f"{d}/")

    size = out.stat().st_size
    print(f"打包完成: {out}")
    print(f"  文件数 {len(files)}  原始 {human(total_raw)}  压缩后 {human(size)}")
    print("  模型身份见 models/ACTIVE_MODELS.json，实物请从获准的本机来源取得。")
    if skipped:
        print(f"  已排除: {', '.join(skipped)}")
    print("\n前 20 个文件:")
    for p in files[:20]:
        print(f"  {p.relative_to(ROOT)}")
    if len(files) > 20:
        print(f"  ... 其余 {len(files) - 20} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
