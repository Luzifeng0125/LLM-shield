"""模块 ⑧ 审计记录。

原则：默认不存原文。只记录 类别 / 动作 / 耗时 / 规则版本 / 失败原因。
如需留存载荷做复现，必须显式开启 store_payload 且仅写入本地 outputs/ 目录。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import OUTPUT_DIR, rules

AUDIT_FILE = OUTPUT_DIR / "audit.jsonl"


class Auditor:
    """轻量审计器：内存保留近期记录 + 可选落盘。"""

    def __init__(self, store_payload: bool = False, path: Optional[Path] = None):
        self.store_payload = store_payload
        self.path = Path(path) if path else AUDIT_FILE
        self.records: List[dict] = []

    def log(self, event: str, **fields: Any) -> dict:
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "rule_version": rules().get("version", "unknown"),
        }
        rec.update(fields)
        # 安全网：任何情况下都不允许把 payload 写进默认审计
        if not self.store_payload:
            rec.pop("payload", None)
            rec.pop("text", None)
        self.records.append(rec)
        if len(self.records) > 500:
            self.records = self.records[-500:]
        return rec

    def dump(self) -> Path:
        """把内存中的审计记录写入本地文件（JSONL）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return self.path

    def recent(self, n: int = 50) -> List[dict]:
        return self.records[-n:]


_AUDITOR: Optional[Auditor] = None


def get_auditor() -> Auditor:
    global _AUDITOR
    if _AUDITOR is None:
        _AUDITOR = Auditor()
    return _AUDITOR
