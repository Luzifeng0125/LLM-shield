"""把隐盾打包成单个 exe（PyInstaller onefile）。

用法：
    python pack.py                # 精简版：只含决策模型，产物 dist/隐盾.exe
    python pack.py --with-models  # 完整版：额外打入可选识别模型权重
    python pack.py --keep-temp    # 保留中间产物，便于排查依赖缺失

体积取舍：
- 「精简版」（默认）**排除 torch / transformers**。识别层用「正则 + 词典」底座，
  零模型依赖；决策模型只有 1MB（necessity_action.joblib），必须打进去
  —— 少了它会「决策模型不可用 → 全部暂停」。
- 「完整版」（--with-models）额外打入可选识别模型权重，可离线跑 GLiNER。
  ⚠ **必须用 CPU 版 torch 打包**：CUDA 版 torch 单包就 4.2GB，会让 exe 膨胀到 5GB+。
  推荐先建独立环境再打包：
      python -m venv .venv-pack
      .venv-pack/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cpu
      .venv-pack/Scripts/pip install -r requirements.txt pyinstaller
      .venv-pack/Scripts/python pack.py --with-models
- 注意 GLiNER 权重默认放在项目外的 D:\\project\\models（sentencepiece 打不开含中文的
  项目路径），因此打包时需要显式把该目录拷进 exe，见 --with-models 的提示。
- data/generated（训练语料）与 outputs/ 不打进去，属于运行时产物。
"""
from __future__ import annotations

import argparse
import os
import shutil  # noqa: F401  （保留，便于后续扩展清理逻辑）
import subprocess  # noqa: F401
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "隐盾"

# 决策模型从**统一模型目录**解析（与运行时同一套逻辑，见 config.necessity_model_path）。
# 打进 exe 后落在 models/ 下；运行时先找统一模型目录、找不到再回退 exe 内 models/，
# 因此开发机与打包后的 exe 都能命中同一份权重。
sys.path.insert(0, str(ROOT))
from llm_shield.config import necessity_model_path  # noqa: E402

_NECESSITY_SRC = str(necessity_model_path())

# ---------------- 只读资源 ----------------
# 基础资源：精简版与完整版都打
BASE_DATA_FILES = [
    ("web", "web"),                              # 控制台 + 对话页
    ("config", "config"),                        # 规则 / 任务 / 身份 / 接收方 / retain_thresholds
    ("data/fixtures", "data/fixtures"),          # 内置虚构演示材料
    # ★ 决策模型（约 1MB）：少了它会「决策模型不可用 → 全部暂停」。
    #   历史上这里写的是 necessity_lr.joblib（旧 schema，代码在 model.py 明确拒绝加载），
    #   又漏了真正在用的 necessity_action.joblib。
    (_NECESSITY_SRC, "models"),
    (".env", "."),                               # 用户选择把当前 .env 打进去
]

# 完整版额外资源：可选的 GLiNER 语义识别模型。
# GLiNER 权重在项目外（默认 D:\project\models\gliner_v3）——sentencepiece 的 C++ 后端
# 打不开含中文的项目路径，所以不能放 models/ 下。要打进 exe 时用环境变量指向源目录：
#     set SHIELD_PACK_GLINER_SRC=D:\project\models\gliner_v3
# 未设置时跳过（精简版行为不变）。
_GLINER_SRC = os.getenv("SHIELD_PACK_GLINER_SRC", "").strip()
MODEL_DATA_FILES = ([(_GLINER_SRC, "models/gliner_v3")] if _GLINER_SRC else [])

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
