"""模块 ① 材料加载：从 data/fixtures 读取虚构演示材料。

首版全部使用虚构数据（假名、假号、假机构），不涉及任何真实个人信息。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ..config import DATA_DIR, uploads_dir
from ..schema import Material
from ..material_policy import is_expired, SOURCES

FIXTURE_DIR = DATA_DIR / "fixtures"
UPLOAD_DIR = uploads_dir()             # 用户上传材料的解析结果


def _safe_path(directory: Path, doc_id: str) -> Optional[Path]:
    """拼接路径并阻挡目录穿越（doc_id 可能来自外部输入）。"""
    if not doc_id or any(value in doc_id for value in ("/", "\\", "..", ":")):
        return None
    return directory / f"{doc_id}.json"


def load_material(doc_id: str) -> Material:
    """按 doc_id 加载单份材料：先查内置材料，再查上传材料。"""
    path = None
    for directory in (FIXTURE_DIR, UPLOAD_DIR):
        p = _safe_path(directory, doc_id)
        if p and p.exists():
            path = p
            break
    if path is None:
        raise FileNotFoundError(f"材料不存在: {doc_id}")
    source_key = str(path.resolve())
    with SOURCES.use({source_key: None}) as versions:
        data = json.loads(path.read_text(encoding="utf-8"))
    if is_expired(data.get("expires_at")):
        raise FileNotFoundError("材料已过期")
    return Material(
        doc_id=data.get("doc_id", doc_id),
        doc_type=data.get("doc_type", ""),
        title=data.get("title", ""),
        text=data.get("text", ""),
        rows=data.get("rows"),
        columns=data.get("columns"),
        allowed_purposes=data.get("allowed_purposes"),
        created_at=data.get("created_at"), expires_at=data.get("expires_at"),
        storage_mode=data.get("storage_mode", "legacy"),
        source_key=source_key, source_version=versions[source_key],
    )


def list_materials(include_builtin: bool = True) -> List[dict]:
    """列出可用材料的概要。

    :param include_builtin: 是否包含内置的虚构演示材料。
        默认 True（保留教程可跑）；前端可传 False 只显示用户自己上传的材料。
    """
    items = []
    sources = []
    if include_builtin:
        sources.append((FIXTURE_DIR, "builtin"))
    sources.append((UPLOAD_DIR, "upload"))

    for directory, source in sources:
        if not directory.exists():
            continue
        for p in sorted(directory.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if is_expired(data.get("expires_at")):
                    continue
                preview = (data.get("text", "") or "")
                if not preview and data.get("rows"):
                    preview = "；".join(str(c) for c in (data.get("columns") or []))
                items.append({
                    "doc_id": data.get("doc_id", p.stem),
                    "title": data.get("title", p.stem),
                    "doc_type": data.get("doc_type", ""),
                    "preview": preview[:60],
                    "source": source,
                    "n_rows": len(data.get("rows") or []),
                    "allowed_purposes": data.get("allowed_purposes"),
                    "expires_at": data.get("expires_at"),
                    "storage_mode": data.get("storage_mode", "legacy"),
                })
            except Exception:
                continue
    return items


def flatten_material(m: Material) -> str:
    """把材料（含表格）摊平成一段可处理的文本。

    表格行按「列名: 值」拼接，这样列名能作为上下文参与识别，
    也便于后续按行做聚合与替换。
    """
    parts = [m.title, m.text]
    if m.rows and m.columns:
        for row in m.rows:
            cells = [f"{col}: {value}" for col in m.columns
                     if (value := str(row.get(col, "") or "").strip())]
            if cells:
                parts.append("；".join(cells))
    return "\n".join(p for p in parts if p)
