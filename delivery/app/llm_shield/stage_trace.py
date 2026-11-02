"""Aggregate stage progress; never attach source text, spans, or mapping values."""
from __future__ import annotations

STAGES = (
    ("access", "材料与权限"), ("detect", "实体识别"),
    ("policy", "必要性模型"), ("constraints", "硬约束"),
    ("transform", "脱敏转换"), ("utility", "任务完整性自检"), ("gateway", "外发前复检"),
    ("output", "生成与回答复检"),
)


class StageTrace:
    def __init__(self):
        self.items = [{"id": key, "title": title, "status": "not_run", "detail": "本轮未执行"}
                      for key, title in STAGES]

    def mark(self, key: str, status: str, detail: str, elapsed_ms: float | None = None):
        item = next(item for item in self.items if item["id"] == key)
        item.update(status=status, detail=detail)
        if elapsed_ms is not None:
            item["elapsed_ms"] = round(elapsed_ms, 2)

