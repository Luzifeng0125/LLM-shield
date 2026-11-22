"""Download the pinned official GLiNER comparison model; action weights are supplied locally."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import requests

APP = Path(__file__).resolve().parents[1]
REVISION = "443d26d654e0324125a96bebd8e796c14ff2efe6"
MODEL_REPO = "urchade/gliner_multi-v2.1"
WEIGHT_SHA = "2100142f31627531497850659dcb3821c99d5e71c08a8e01a98e4b11ef32a199"
WEIGHT_SIZE = 1155830112


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, size: int | None = None, expected: str | None = None) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (size is None or target.stat().st_size == size) and expected and sha(target) == expected:
        print(f"Already verified: {target.name}", flush=True)
        return {"file": target.name, "sha256": expected, "size_bytes": target.stat().st_size}
    partial = target.with_name(target.name + ".download")
    if not partial.exists() and size and target.exists() and 0 < target.stat().st_size < size:
        shutil.copyfile(target, partial)
    previous_report = time.monotonic()
    errors = 0
    while not partial.exists() or (size is not None and partial.stat().st_size < size):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(20, 45)) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    raise ValueError("Server did not honor resume; existing partial retained")
                if offset and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Resume offset mismatch")
                mode = "ab" if offset else "wb"
                with partial.open(mode) as output:
                    for chunk in response.iter_content(2 * 1024 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        if size is not None and output.tell() > size:
                            raise ValueError("Received more bytes than the pinned artifact")
                        if time.monotonic() - previous_report > 15:
                            print(f"{target.name}: {output.tell()/1024**2:.1f} / {(size or output.tell())/1024**2:.1f} MiB", flush=True)
                            previous_report = time.monotonic()
            if size is None:
                break
        except requests.RequestException as exc:
            errors += 1
            print(f"Download retry {errors}: {type(exc).__name__}", flush=True)
            if errors >= 8:
                raise RuntimeError("Repeated download failure; partial file is retained") from None
            time.sleep(min(errors * 2, 10))
    if size is not None and partial.stat().st_size != size:
        raise ValueError(f"Size mismatch: {target.name}")
    actual = sha(partial)
    if expected and actual != expected:
        raise ValueError(f"SHA-256 mismatch: {target.name}; existing file retained")
    if target.exists() and size and target.stat().st_size != size:
        backup = target.with_name(target.name + ".incomplete-20261102")
        if not backup.exists():
            shutil.copyfile(target, backup)
    os.replace(partial, target)
    print(f"Verified download: {target.name}, {target.stat().st_size} bytes, SHA-256 {actual}", flush=True)
    return {"file": target.name, "sha256": actual, "size_bytes": target.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    args = parser.parse_args()
    directory = APP / "models/gliner_official_multi_v2.1"
    receipt = {"repository": MODEL_REPO, "revision": REVISION,
               "canonical_source": f"https://huggingface.co/{MODEL_REPO}",
               "download_endpoint": args.endpoint, "is_original_project_finetune": False, "files": []}
    # Resolve the metadata at the pinned revision, rather than following moving main.
    response = requests.get(f"{args.endpoint}/api/models/{MODEL_REPO}/revision/{REVISION}?blobs=true", timeout=30)
    response.raise_for_status()
    metadata = response.json()
    if metadata["sha"] != REVISION:
        raise ValueError("Unexpected model revision")
    siblings = {entry["rfilename"]: entry for entry in metadata["siblings"]}
    remote = siblings["model.safetensors"]
    if remote["size"] != WEIGHT_SIZE or remote["lfs"]["sha256"] != WEIGHT_SHA:
        raise ValueError("Weight metadata does not match the pinned artifact")
    for name in ("gliner_config.json", "README.md"):
        receipt["files"].append(download(f"{args.endpoint}/{MODEL_REPO}/resolve/{REVISION}/{name}", directory / name, siblings[name]["size"]))
    receipt["files"].append(download(f"{args.endpoint}/{MODEL_REPO}/resolve/{REVISION}/model.safetensors?download=true", directory / "model.safetensors", WEIGHT_SIZE, WEIGHT_SHA))
    from safetensors import safe_open
    with safe_open(directory / "model.safetensors", framework="pt", device="cpu") as weights:
        receipt["tensor_count"] = len(weights.keys())
    # The upstream GLiNER repo does not bundle its encoder tokenizer/config.
    # The project's existing mDeBERTa tokenizer/config are copied, with their provenance retained.
    assets = []
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "spm.model"):
        source = APP / "models/gliner_v3" / name
        destination = directory / name
        if not source.exists():
            continue
        if not destination.exists() or sha(destination) != sha(source):
            shutil.copyfile(source, destination)
        assets.append({"file": name, "sha256": sha(destination), "source": "existing_project_mdeberta_assets"})
    receipt["encoder_assets"] = assets

    with (directory / "DOWNLOAD_RECEIPT.json").open("w", encoding="utf-8", newline="\n") as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2)
        output.write("\n")
    from prepare_offline_gliner import main as prepare_offline
    prepare_offline()
    print("Official GLiNER downloaded and verified. Use verify_model_release.py for locally supplied action weights.", flush=True)


if __name__ == "__main__":
    main()
