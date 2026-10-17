"""Check local model and API configuration before starting the UI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.runtime import readiness  # noqa: E402


def main() -> int:
    status = readiness()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if (status["ready_for_real"] if status["llm_mode"] == "real"
                 else status["ready_local"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
