"""Run an isolated, reproducible action-model comparison without external calls."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.research import run_experiment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-drafts", action="store_true", help="仅开发实验，不代表人工质量，不发布权重")
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        report = run_experiment(cases, args.out, allow_drafts=args.allow_drafts)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    summary = {key: {k: v for k, v in value.items() if k != "rows"}
               for key, value in report["results"].items()}
    print(json.dumps({"supervision": report["supervision"], "production_promoted": False,
                      "results": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
