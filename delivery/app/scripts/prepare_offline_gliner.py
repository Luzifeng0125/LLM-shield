"""Embed the local encoder architecture for fully offline official GLiNER loading."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
DIRECTORY = APP / "models/gliner_official_multi_v2.1"


def main():
    config_file = DIRECTORY / "gliner_config.json"
    upstream_file = DIRECTORY / "gliner_config.upstream.json"
    if not upstream_file.exists():
        upstream_file.write_bytes(config_file.read_bytes())
    config = json.loads(upstream_file.read_text(encoding="utf-8"))
    encoder = json.loads((DIRECTORY / "config.json").read_text(encoding="utf-8"))
    if config["model_name"] != "microsoft/mdeberta-v3-base" or encoder["model_type"] != "deberta-v2":
        raise ValueError("Unexpected encoder architecture")
    config["encoder_config"] = encoder
    with config_file.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(config, output, ensure_ascii=False, indent=2)
        output.write("\n")
    receipt = DIRECTORY / "DOWNLOAD_RECEIPT.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["offline_preparation"] = {
        "upstream_config_file": upstream_file.name,
        "upstream_config_sha256": hashlib.sha256(upstream_file.read_bytes()).hexdigest(),
        "prepared_config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest(),
        "change": "Embed existing local mDeBERTa encoder architecture; weights unchanged",
    }
    with receipt.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print("Prepared offline encoder configuration; original upstream config retained.")


if __name__ == "__main__":
    main()
