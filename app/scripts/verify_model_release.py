"""Verify published bytes, with optional local model loading and synthetic inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent


def verify(load: bool = False) -> None:
    release = json.loads((APP / "models/MODEL_RELEASE.json").read_text(encoding="utf-8"))
    for entry in release["files"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError(f"Path outside repository: {entry['path']}")
        data = path.read_bytes()
        if len(data) != entry["size_bytes"]:
            raise ValueError(f"Size mismatch: {entry['path']}")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {entry['path']}")
    print(f"Verified {len(release['files'])} published files (size and SHA-256).")

    if not load:
        return
    sys.path.insert(0, str(APP))
    from llm_shield.m4_necessity.model import NecessityModel
    from llm_shield.schema import Action, Segment, Span

    # A synthetic probe checks serialization and feature dispatch, not model quality.
    text = "温书宁负责记录。"
    segment = Segment("release-probe", text, 0, len(text),
                      [Span(0, 3, "温书宁", "PERSON_NAME")], context=text)
    for entry in release["models"]:
        model = NecessityModel(ROOT / entry["path"])
        if not model.available:
            raise ValueError(f"Cannot load {entry['id']}: {model.reason}")
        if model.metadata.get("feature_version") != entry["feature_version"]:
            raise ValueError(f"Feature version mismatch: {entry['id']}")
        scores = model.score(segment, "meeting_minutes", "external_model",
                             task_description="整理分工，保留人员代号。",
                             context=text, identity_key="teacher")
        if set(scores) != {action.value for action in Action}:
            raise ValueError(f"Missing action classes: {entry['id']}")
        if (any(not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values())
                or not math.isclose(sum(scores.values()), 1.0, abs_tol=1e-6)):
            raise ValueError(f"Invalid probabilities: {entry['id']}")
        print(f"Loaded {entry['id']}: feature v{entry['feature_version']}, inference OK.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", action="store_true", help="Load trusted published models and run a synthetic probe.")
    args = parser.parse_args()
    try:
        verify(load=args.load)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
