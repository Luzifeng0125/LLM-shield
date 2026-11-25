"""规范 JSON 与 SHA-256。只使用标准库。"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(payload: Any) -> bytes:
    """键排序、无多余空白、UTF-8。同一对象始终得到同一字节串。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(payload: Any) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
