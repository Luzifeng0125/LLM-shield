"""把隐盾打包成单个 exe（PyInstaller onefile）。

用法：
    python pack.py                # 精简版：不含领域 NER 模型，产物 dist/隐盾.exe（约 121MB）
    python pack.py --with-models  # 完整版：把本地 NER 模型一并打包（约 2.5GB+）
    python pack.py --keep-temp    # 保留中间产物，便于排查依赖缺失

体积取舍（见 README / 记忆日志）：
- 「精简版」（默认）**排除 torch / transformers**：领域 NER 权重（models/ 下约 2GB）
  默认不打。代码里 campus_ner 对 ImportError 有降级保护，排除后功能不受影响，
  状态栏会显示「规则底座」。
- 「完整版」（--with-models）把 models/ 下全部本地模型打进 exe，可离线跑领域 NER。
  ⚠ **必须用 CPU 版 torch 打包**：CUDA 版 torch 单包就 4.2GB，会让 exe 膨胀到 5GB+。
  推荐先建独立环境再打包：
      python -m venv .venv-pack
      .venv-pack/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cpu
      .venv-pack/Scripts/pip install -r requirements.txt pyinstaller
      .venv-pack/Scripts/python pack.py --with-models
- data/generated（训练语料）与 outputs/ 不打进去，属于运行时产物。
"""
from __future__ import annotations

import argparse
import shutil  # noqa: F401  （保留，便于后续扩展清理逻辑）
import subprocess  # noqa: F401
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "隐盾"

# ---------------- 只读资源 ----------------
# 基础资源：精简版与完整版都打
BASE_DATA_FILES = [
    ("web", "web"),                              # 控制台 + 对话页
    ("config", "config"),                        # 规则 / 任务 / 身份 / 接收方 / retain_thresholds
    ("data/fixtures", "data/fixtures"),          # 内置虚构演示材料
    ("models/necessity_lr.joblib", "models"),    # 必要性判别模型 v1（缺了会降级到规则）
    (".env", "."),                               # 用户选择把当前 .env 打进去
]

# 完整版额外资源：本地领域模型 + 线上真正加载的 necessity_v2
MODEL_DATA_FILES = [
    ("models/campus_ner", "models/campus_ner"),                # ★ 线上唯一加载的 NER（约 407MB）
    ("models/ner_freeal", "models/ner_freeal"),                # FreeAL 实验产物
    ("models/ner_freeal_llm", "models/ner_freeal_llm"),        # FreeAL+LLM 实验产物
    ("models/ner_weak_baseline", "models/ner_weak_baseline"),  # 弱监督基线
    ("models/roberta_campus", "models/roberta_campus"),        # 领域继续预训练基座
    ("models/necessity_v2.joblib", "models"),                  # 必要性判别模型 v2（当前线上默认）
]

# ---------------- 排除 ----------------
# 与打包目标无关的通用库 + 训练侧依赖（不参与线上推理）
BASE_EXCLUDES = [
    "tkinter", "matplotlib", "PIL", "IPython", "pytest", "notebook",
    "skweak", "spacy", "datasets", "accelerate", "seqeval",  # 训练侧，线上不需要
]

# 精简版：连 torch 生态一起排除
SLIM_EXCLUDES = [
    "torch", "transformers", "tokenizers", "huggingface_hub", "safetensors",
    "nvidia", "triton",
]

# 完整版：只排除 GPU / CUDA 专有包（用 CPU 版 torch，nvidia 包不该进来）
FULL_EXCLUDES = ["nvidia", "triton"]

# ---------------- hidden imports ----------------
# uvicorn 的 loop / protocol / lifespan 都是运行时动态导入的，必须显式声明
BASE_HIDDEN_IMPORTS = [
    "uvicorn.logging", "uvicorn.config", "uvicorn.server",
    "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "multipart",                 # python-multipart：FastAPI 接收文件上传需要
    "httptools", "websockets", "wsproto",
    "docx", "pypdf", "openpyxl", "yaml", "dotenv",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors.typedefs",
    "sklearn.neighbors.quad_tree",
    "sklearn.tree._utils",
    "sklearn.metrics._pairwise_distances_reduction._datasets_pair",
    "sklearn.metrics._pairwise_distances_reduction._middle_term_computer",
]

# 完整版：领域 NER 推理链的动态导入
MODEL_HIDDEN_IMPORTS = ["torch", "transformers", "safetensors", "tokenizers", "numpy"]


def os_sep() -> str:
    """PyInstaller 的 --add-data 在 Windows 用 ';' 分隔，其他平台用 ':'。"""
    return ";" if sys.platform.startswith("win") else ":"


def build_args(with_models: bool, keep_temp: bool) -> list:
    args = [
        str(ROOT / "pack_entry.py"),
        f"--name={APP_NAME}",
        "--onefile",
        "--console",                 # 需要控制台窗口显示地址与日志
        "--noconfirm",
        "--clean",
        f"--paths={ROOT}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build' / 'pack'}",
        f"--specpath={ROOT / 'build'}",
    ]

    data_files = list(BASE_DATA_FILES) + (MODEL_DATA_FILES if with_models else [])
    for src, dst in data_files:
        p = ROOT / src
        if not p.exists():
            print(f"[警告] 缺失资源，跳过：{src}")
            continue
        args.append(f"--add-data={p}{os_sep()}{dst}")

    excludes = BASE_EXCLUDES + (FULL_EXCLUDES if with_models else SLIM_EXCLUDES)
    for mod in excludes:
        args.append(f"--exclude-module={mod}")

    hidden = list(BASE_HIDDEN_IMPORTS) + (MODEL_HIDDEN_IMPORTS if with_models else [])
    for mod in hidden:
        args.append(f"--hidden-import={mod}")

    # sklearn 子模块很多且动态加载，逐个列容易漏，整体收集更稳
    args.append("--collect-submodules=sklearn")
    args.append("--collect-submodules=docx")

    if with_models:
        # torch / transformers 的数据与二进制（dll / 词表 / 配置）必须一并收集，
        # 否则运行时 import 或模型加载会报错。torch 用 CPU 版，collect-all 体积可控。
        args += ["--collect-all", "torch"]
        args += ["--collect-all", "transformers"]
        args += ["--collect-all", "tokenizers"]
        args += ["--collect-all", "safetensors"]
    return args


def main() -> int:
    ap = argparse.ArgumentParser(description="打包隐盾为单个 exe")
    ap.add_argument("--with-models", action="store_true",
                    help="完整版：把本地 NER 模型一并打包（约 2.5GB+，需 CPU 版 torch）")
    ap.add_argument("--keep-temp", action="store_true", help="保留中间产物")
    args = ap.parse_args()

    data_files = list(BASE_DATA_FILES) + (MODEL_DATA_FILES if args.with_models else [])
    missing = [s for s, _ in data_files if not (ROOT / s).exists()]
    if missing:
        print("[错误] 以下必需资源不存在，无法打包：" + "、".join(missing))
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[错误] 未安装 PyInstaller，请先执行 pip install pyinstaller")
        return 1

    mode = "完整版（含本地 NER 模型）" if args.with_models else "精简版（不含领域 NER 模型）"
    print("=" * 62)
    print(f"  开始打包 · {mode}")
    print(f"  产物：dist/{APP_NAME}.exe")
    if args.with_models:
        print("  ⚠ 已按 CPU 版 torch 打包；若环境误装 CUDA 版，exe 会膨胀到 5GB+")
    print("=" * 62)

    t0 = time.time()
    import PyInstaller.__main__
    PyInstaller.__main__.run(build_args(args.with_models, args.keep_temp))

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print("=" * 62)
        print(f"  打包完成：{exe}")
        print(f"  体积：{size_mb:.1f} MB    耗时：{time.time() - t0:.0f}s")
        print("  双击即可运行；首次启动需解压依赖，请稍候。")
        print("=" * 62)
        return 0
    print("[错误] 未找到产物，请查看上方 PyInstaller 输出")
    return 1


if __name__ == "__main__":
    sys.exit(main())
