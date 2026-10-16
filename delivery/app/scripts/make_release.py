#!/usr/bin/env python
"""把项目打包成可分发的 zip。

排除清单（重要，勿随意放宽）：
  - .env / .env.local —— 含真实 API 密钥，绝不能进压缩包
  - data/uploads/     —— 用户上传的真实材料（姓名/手机号等）
  - models/           —— 仅打包运行必需的 necessity_action.joblib；其他权重不入包
  - outputs/          —— 评测产物与临时文件
  - .workbuddy/       —— 项目工作数据
  - 虚拟环境、__pycache__、日志、已有 zip

用法：
    python scripts/make_release.py
    python scripts/make_release.py --out D:/隐盾-model-only.zip
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_MODEL = Path("models/necessity_action.joblib")

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
    if rel == REQUIRED_MODEL:
        return False
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
    ap.add_argument("--version", default="0.1.0-model-only")
    args = ap.parse_args()

    if not (ROOT / REQUIRED_MODEL).is_file():
        print("缺少本地动作模型，停止打包。请先运行：python -m llm_shield.m4_necessity.train")
        return 1

    out = Path(args.out) if args.out else ROOT.parent / f"隐盾-LLM-Shield-v{args.version}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in sorted(ROOT.rglob("*")) if p.is_file() and not should_skip(p)]
    if not files:
        print("没有可打包的文件")
        return 1

    total_raw = 0
    skipped: list[str] = []

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            total_raw += p.stat().st_size
            z.write(p, p.relative_to(ROOT))

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
    print(f"  已包含必需模型: {REQUIRED_MODEL}（其他模型权重不入包）")
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
