"""把夹具写成 JSON。不计算四态，只冻结 R0 已经生成的注册表。"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.third_stage.cases import materialize_suite

OUT = Path(__file__).resolve().parent / "fixtures" / "t1_t13.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    suite = materialize_suite()
    OUT.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
