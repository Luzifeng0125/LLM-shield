"""Publish existing inference evidence plus additional local execution/tokenizer checks."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import os

from evaluate_model_stages import APP, ROOT, digest, write, transformation_and_utility_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=APP / "eval/releases/stages_20261102")
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Publication directory already exists; use a new version")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    from transformers import AutoTokenizer
    model_dir = APP / "models/gliner_official_multi_v2.1"
    fast = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    slow = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, use_fast=False)
    benchmark = [json.loads(line)["text"] for line in (APP / "data/field_v1/field_v1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    diagnostics = json.loads((APP / "data/stage_diagnostics_20261102/cases.json").read_text(encoding="utf-8"))["cases"]
    texts = benchmark + [row["text"] for row in diagnostics] + [row["ask"] for row in diagnostics]
    mismatches = [index for index, text in enumerate(texts) if fast.encode(text) != slow.encode(text)]
    tokenizer = {"fast_class": type(fast).__name__, "slow_class": type(slow).__name__,
                 "strings_compared": len(texts), "token_id_mismatches": len(mismatches),
                 "mismatch_indices": mismatches, "scope": "Parity on benchmark and diagnostic strings; does not prove parity for all inputs."}
    report = json.loads((args.source / "summary.json").read_text(encoding="utf-8"))
    report["safeguards"].update(transformation_and_utility_checks())
    report["supplemental_checks"] = {"created_utc": datetime.now(timezone.utc).isoformat(),
                                      "primary_report_sha256": digest(args.source / "summary.json"),
                                      "model_inference_rerun": False, "tokenizer": tokenizer}
    files = ["llm_shield/m2_detect/gliner_ner.py", "llm_shield/m2_detect/pipeline.py", "llm_shield/m2_detect/regex_rules.py",
             "llm_shield/m2_detect/entity_rules.py", "llm_shield/m4_necessity/model.py", "llm_shield/m3_decide/decision.py",
             "config/rules.yaml", "config/tasks.yaml", "config/recipients.yaml", "config/identities.yaml"]
    report["source_files_at_publication"] = {name: digest(APP / name) for name in files}
    if mismatches:
        report["limitations"].append("快慢分词器在本次输入上存在差异，须核对分词兼容性。")
    args.out.mkdir(parents=True)
    for name in ("protocol.json", "diagnostic_predictions.json"):
        shutil.copyfile(args.source / name, args.out / name)
    shutil.copyfile(args.source / "summary.json", args.out / "summary.primary.json")
    shutil.copyfile(model_dir / "DOWNLOAD_RECEIPT.json", args.out / "model_download_receipt.json")
    write(args.out / "tokenizer_validation.json", tokenizer)
    write(args.out / "summary.json", report)
    manifest = [{"file": path.name, "sha256": digest(path), "size_bytes": path.stat().st_size}
                for path in sorted(args.out.iterdir()) if path.is_file()]
    write(args.out / "evidence_manifest.json", {"files": manifest})
    print(json.dumps({"tokenizer": tokenizer, "supplements": report["safeguards"]["utility"], "published": str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
