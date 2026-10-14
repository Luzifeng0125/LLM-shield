"""领域预训练工具模块。

基座模型解析：本地路径 → ModelScope → HuggingFace
（HuggingFace 直连在国内常不通，ModelScope 是可用的替代源）
"""
from __future__ import annotations

from pathlib import Path

# HuggingFace 模型 ID -> ModelScope 上对应的模型 ID
MODELSCOPE_ALIAS = {
    "hfl/chinese-roberta-wwm-ext": "dienstag/chinese-roberta-wwm-ext",
    "hfl/chinese-roberta-wwm-ext-large": "hfl/chinese-roberta-wwm-ext-large",
    "hfl/rbt3": "hfl/rbt3",
}


def resolve_base_model(preferred: str) -> str:
    """把模型标识解析成本地可加载的路径。

    顺序：
      1. 已是本地目录 → 直接用
      2. ModelScope 下载（国内可直连，速度快）
      3. 回退原标识交给 transformers 自行处理（HuggingFace）
    """
    if Path(preferred).exists():
        return preferred

    ms_id = MODELSCOPE_ALIAS.get(preferred, preferred)
    try:
        from modelscope import snapshot_download
        path = snapshot_download(ms_id)
        print(f"[基座] 已从 ModelScope 下载：{ms_id} -> {path}")
        return path
    except Exception as exc:
        print(f"[基座] ModelScope 不可用（{type(exc).__name__}），"
              f"回退 HuggingFace：{preferred}")
    return preferred
