"""Run the pytest suite and the standalone smoke checks with one command."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-only", action="store_true",
                        help="disable GLiNER for an environment without its dependencies")
    args = parser.parse_args()
    env = os.environ.copy()
    if args.rules_only:
        env["SHIELD_USE_GLINER"] = "false"
    commands = [
        [sys.executable, "-m", "pytest", "-q", "tests", "--ignore=tests/test_smoke.py"],
        [sys.executable, "tests/test_smoke.py"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
