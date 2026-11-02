"""Read versioned aggregate evidence for the local evaluation page."""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C
from .m4_necessity.model import get_model
from .runtime import readiness

REPORT = C.ROOT / "eval/releases/stages_20261102/summary.json"


def evaluation_summary() -> dict:
    current = readiness()
    name = Path(C.gliner_model_dir()).name
    current["gliner_profile"] = {"gliner_v3": "project_gliner_v3", "gliner_official_multi_v2.1": "official_multi_v2.1"}.get(name, "custom_local_model")
    current["action_feature_version"] = get_model().metadata.get("feature_version")
    result = {"runtime": current, "report_available": REPORT.is_file()}
    if not REPORT.is_file():
        return result
    raw = json.loads(REPORT.read_text(encoding="utf-8"))
    # Publish aggregate figures only; source text and per-case predictions stay in evidence files.
    ner = {key: raw["ner"][key] for key in ("dataset", "sha256", "documents", "gold_entities", "scope", "segmentation")}
    ner["configurations"] = {}
    for name, config in raw["ner"]["configurations"].items():
        ner["configurations"][name] = {key: config[key] for key in ("scope", "total_ms", "latency")}
        ner["configurations"][name]["modes"] = {
            mode: {"overall": score["overall"], "macro_f1": score["macro_f1"],
                   "per_category": {cat: {key: data[key] for key in ("precision", "recall", "f1", "tp", "fp", "fn")}
                                    for cat, data in score["per_category"].items()}}
            for mode, score in config["modes"].items()}
    result["report"] = {key: raw[key] for key in ("created_utc", "profile", "cloud_api_called", "default_models_promoted",
                                                   "environment", "parsing", "necessity", "historical_human31", "limitations")}
    result["report"]["ner"] = ner
    result["report"]["safeguards"] = {
        key: {"passed": raw["safeguards"][key]["passed"], "total": raw["safeguards"][key]["total"]}
        for key in ("constraints", "transformation", "utility", "boundaries")}
    return result
