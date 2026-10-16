"""Train a local 14-category BERT NER candidate from reviewed gold only.

Unicode character offsets, rather than Python byte offsets or token accuracy,
define the target. The isolated NER validation units select the checkpoint;
test data is never discovered or opened. Inference uses the application's shared
BIO decoder/windowing implementation and never installs candidate weights.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT.parents[1] / "app"
CATEGORIES = tuple(sorted(workflow.CATS))
BIO_LABELS = ["O"] + [prefix + category for category in CATEGORIES for prefix in ("B-", "I-")]
LABEL2ID = {label: index for index, label in enumerate(BIO_LABELS)}
ID2LABEL = dict(enumerate(BIO_LABELS))
ARTIFACT_TYPE = "yindun-reviewed-bert-ner"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def validate_entities(text, entities):
    require(isinstance(text, str) and bool(text.strip()), "Text must be nonempty")
    require(isinstance(entities, list), "Entities must be a list")
    normalized = []
    for entity in entities:
        require(isinstance(entity, dict), "Entity must be an object")
        require(set(entity) == {"start", "end", "text", "category"}, "Invalid entity fields")
        start, end = entity["start"], entity["end"]
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
                "Invalid Unicode character offsets")
        require(entity["category"] in CATEGORIES, "Unknown entity category")
        require(text[start:end] == entity["text"], "Entity text and offsets differ")
        normalized.append(dict(entity))
    normalized.sort(key=lambda entity: (entity["start"], entity["end"]))
    require(all(left["end"] <= right["start"] for left, right in zip(normalized, normalized[1:])),
            "Overlapping/duplicate entities cannot be encoded as BIO")
    return normalized


def align_token_labels(text, entities, offsets, *, truncated=False):
    """Map complete fast-tokenizer character offsets to 29 BIO IDs.

    (0, 0) marks special/padding tokens and receives -100. Tokenization may
    omit whitespace inside an entity, but cannot swallow a boundary, omit a
    non-whitespace entity character, or truncate a sequence. No approximation
    is made when the gold span cannot be represented by this tokenizer.
    """
    require(not truncated, "Truncated sequences cannot be used for supervised NER")
    entities = validate_entities(text, entities)
    labels, hits = [], [[] for _ in entities]
    previous_end = 0
    for index, offset in enumerate(offsets):
        require(isinstance(offset, (list, tuple)) and len(offset) == 2, "Invalid token offset")
        start, end = offset
        require(type(start) is int and type(end) is int, "Offsets must be Unicode integer indices")
        if start == end == 0:
            labels.append(-100)
            continue
        require(0 <= start < end <= len(text), "Token offset outside text")
        require(start >= previous_end, "Token offsets overlap or are unordered")
        previous_end = end
        matches = [i for i, entity in enumerate(entities)
                   if start < entity["end"] and end > entity["start"]]
        require(len(matches) <= 1, "Token crosses more than one gold entity")
        if not matches:
            labels.append(LABEL2ID["O"])
            continue
        entity_index = matches[0]
        entity = entities[entity_index]
        require(entity["start"] <= start < end <= entity["end"],
                f"Token [{start}, {end}) crosses gold boundary [{entity['start']}, {entity['end']})")
        prefix = "B-" if not hits[entity_index] else "I-"
        labels.append(LABEL2ID[prefix + entity["category"]])
        hits[entity_index].append((index, start, end))
    for entity, covered in zip(entities, hits):
        require(bool(covered), f"Entity {entity['category']} has no tokens (dropped/truncated)")
        require(covered[0][1] == entity["start"] and covered[-1][2] == entity["end"],
                f"Entity {entity['category']} boundary is not exactly token-aligned")
        for left, right in zip(covered, covered[1:]):
            require(not text[left[2]:right[1]].strip(), "Tokenizer dropped non-whitespace inside entity")
            require(right[0] == left[0] + 1, "Special token interrupts a gold entity")
    return labels


def load_gold(path, expected_split):
    require(expected_split in {"train", "validation"}, "Only train/validation may be loaded")
    path = Path(path).resolve()
    require("test" not in path.stem.casefold(), "Refusing to open a test-named input")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=unique_object)
            require(isinstance(row, dict), "Row must be an object")
            require(row.get("split") == expected_split, "Unexpected split; test/mixed data forbidden")
            require(row.get("human_reviewed") is True and
                    row.get("label_origin") == "human_dual_review_adjudicated", "Not reviewed human gold")
            for field in ("id", "source_case_id", "source_kind"):
                require(isinstance(row.get(field), str) and row[field].strip(), f"Missing {field}")
            require(row.get("origin_kind") in {"ner", "policy", "dialogue"}, "Unknown origin_kind")
            row["entities"] = validate_entities(row["text"], row["entities"])
            rows.append(row)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"{path.name}:{number}: {exc}") from exc
    require(rows, "Empty input")
    require(len({row["id"] for row in rows}) == len(rows), "Duplicate input IDs")
    return rows, {"path": str(path), "sha256": file_hash(path), "rows": len(rows),
                  "origin_kinds": dict(Counter(row["origin_kind"] for row in rows)),
                  "source_kinds": dict(Counter(row["source_kind"] for row in rows)),
                  "entity_mentions": dict(Counter(entity["category"] for row in rows
                                                   for entity in row["entities"]))}


def check_separation(train, validation):
    require(not {row["id"] for row in train} & {row["id"] for row in validation},
            "ID overlap across train and validation")
    require(not {row["source_case_id"] for row in train} & {row["source_case_id"] for row in validation},
            "source_case_id overlap across train and validation")
    indexes = []
    for rows in (train, validation):
        index = defaultdict(list)
        for row in rows:
            index[row["text"]].append(row)
        indexes.append(index)
    shared = []
    for text in sorted(set(indexes[0]) & set(indexes[1])):
        left, right = indexes[0][text], indexes[1][text]
        generic_turn = all(row["origin_kind"] == "dialogue" and not row["entities"] for row in left + right)
        require(generic_turn, "Identical full NER input across splits; only empty generic dialogue repeats allowed")
        shared.append({"text_sha256": text_hash(text), "train_ids": [row["id"] for row in left],
                       "validation_ids": [row["id"] for row in right], "generic_dialogue_repeat": True})
    return {"id_overlap": 0, "source_case_id_overlap": 0,
            "exact_text_overlap_count": len(shared), "exact_text_overlaps": shared,
            "within_split_duplicate_text_rows": {
                name: sum(len(group) - 1 for group in index.values())
                for name, index in zip(("train", "validation"), indexes)},
            "limitation": "Declared-source/text checks do not establish semantic or template independence."}


def encode_rows(tokenizer, rows, max_length):
    require(getattr(tokenizer, "is_fast", False), "Fast tokenizer with character offsets required")
    encoded = []
    for row in rows:
        item = tokenizer(row["text"], return_offsets_mapping=True, truncation=False,
                         add_special_tokens=True, padding=False)
        require(len(item["input_ids"]) <= max_length,
                f"{row['id']}: {len(item['input_ids'])} tokens exceeds max_length={max_length}; refusing truncation")
        offsets = item.pop("offset_mapping")
        try:
            item["labels"] = align_token_labels(row["text"], row["entities"], offsets)
        except ValueError as exc:
            raise ValueError(f"{row['id']}: {exc}") from exc
        encoded.append(dict(item))
    return encoded


def balanced_sample_weights(rows, power):
    """Train-only document sampling; labels/text and source IDs stay unchanged.

    Rarer categories receive more draws, capped implicitly by the support ratio.
    Negative examples retain unit weight. Power zero preserves uniform sampling.
    """
    require(math.isfinite(power) and 0 <= power <= 1, "balance_power must be between 0 and 1")
    categories = [{entity["category"] for entity in row["entities"]} for row in rows]
    support = Counter(category for row_categories in categories for category in row_categories)
    highest = max(support.values(), default=1)
    weights = [max(((highest / support[category]) ** power for category in row_categories), default=1.0)
               for row_categories in categories]
    return weights, dict(sorted(support.items()))


def metric(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn, "gold_entities": tp + fn,
            "predicted_entities": tp + fp, "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def score_predictions(rows, predictions):
    require(len(rows) == len(predictions), "Prediction row count mismatch")
    tp, fp, fn = Counter(), Counter(), Counter()
    prediction_rows, errors = [], []
    exact = negatives = negative_fp = 0
    for row, predicted in zip(rows, predictions):
        gold = row["entities"]
        key = lambda entity: (entity["start"], entity["end"], entity["category"])
        gold_set, pred_set = {key(entity) for entity in gold}, {key(entity) for entity in predicted}
        matched, extra, missing = gold_set & pred_set, pred_set - gold_set, gold_set - pred_set
        tp.update(item[2] for item in matched)
        fp.update(item[2] for item in extra)
        fn.update(item[2] for item in missing)
        exact += int(gold_set == pred_set)
        negatives += int(not gold)
        negative_fp += int(not gold and bool(predicted))
        prediction_rows.append({"id": row["id"], "split": "validation", "text_sha256": text_hash(row["text"]),
                                "entities": predicted})
        if extra or missing:
            errors.append({"id": row["id"], "origin_kind": row["origin_kind"], "text": row["text"],
                           "gold_entities": gold, "predicted_entities": predicted,
                           "false_positives": [entity for entity in predicted if key(entity) in extra],
                           "false_negatives": [entity for entity in gold if key(entity) in missing]})
    report = {"documents": len(rows), "micro": metric(sum(tp.values()), sum(fp.values()), sum(fn.values())),
              "per_category": {category: {**metric(tp[category], fp[category], fn[category]),
                                           "has_gold_support": tp[category] + fn[category] > 0}
                               for category in CATEGORIES},
              "exact_document_match": {"numerator": exact, "denominator": len(rows),
                                       "rate": exact / len(rows) if rows else None},
              "negative_false_positive": {"numerator": negative_fp, "denominator": negatives,
                                          "rate": negative_fp / negatives if negatives else None}}
    return report, prediction_rows, errors


def dump_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def get_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True, type=Path)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--min-epochs", type=int, default=4)
    parser.add_argument("--torch-threads", type=int, default=4)
    parser.add_argument("--balance-power", type=float, default=0.0,
                        help="Train-only rare-category oversampling power in [0,1]; zero preserves original sampling")
    return parser


def train(args):
    require(args.epochs >= args.min_epochs >= 4, "At least four training epochs are required")
    require(args.patience >= 1 and args.batch_size >= 1 and args.max_length >= 8 and args.torch_threads >= 1,
            "Invalid training limits")
    require(math.isfinite(args.lr) and args.lr > 0, "Learning rate must be positive")
    base_model, out = args.base_model.resolve(), args.out.resolve()
    require(base_model.is_dir(), "--base-model must be a local directory")
    require(not out.exists(), "--out must be a new directory; previous artifacts are never overwritten")
    live_models = (APP / "models").resolve()
    require(out != live_models and live_models not in out.parents, "Refusing to train into live app models")
    require((base_model / "model.safetensors").is_file() or
            (base_model / "model.safetensors.index.json").is_file(), "Safe local model weights required")
    train_rows, train_meta = load_gold(args.train, "train")
    balance_power = getattr(args, "balance_power", 0.0)
    sample_weights, category_support = balanced_sample_weights(train_rows, balance_power)
    validation_rows, validation_meta = load_gold(args.validation, "validation")
    separation = check_separation(train_rows, validation_rows)
    main_rows = [row for row in validation_rows if row["origin_kind"] == "ner"]
    require(main_rows, "No origin_kind=ner validation samples")

    import numpy as np
    import torch
    import transformers
    from transformers import AutoModelForTokenClassification, AutoTokenizer, DataCollatorForTokenClassification
    sys.path.insert(0, str(APP))
    from llm_shield.m2_detect.reviewed_ner import predict_entities
    import llm_shield.m2_detect.reviewed_ner as shared_inference

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.torch_threads)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    require(args.device != "cuda" or torch.cuda.is_available(), "CUDA requested but unavailable")
    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device == "auto":
        device = "cpu"
    if device == "cuda":
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    tokenizer = AutoTokenizer.from_pretrained(str(base_model), local_files_only=True,
                                               trust_remote_code=False, use_fast=True)
    train_encoded = encode_rows(tokenizer, train_rows, args.max_length)
    # Validate every validation target before training; no hidden truncation is
    # accepted merely because a particular sample is outside the primary metric.
    encode_rows(tokenizer, validation_rows, args.max_length)
    model = AutoModelForTokenClassification.from_pretrained(
        str(base_model), local_files_only=True, trust_remote_code=False, use_safetensors=True,
        num_labels=len(BIO_LABELS), id2label=ID2LABEL, label2id=LABEL2ID)
    require(args.max_length <= model.config.max_position_embeddings, "max_length exceeds model context")
    model.to(device)
    collate = DataCollatorForTokenClassification(tokenizer, padding=True, label_pad_token_id=-100)
    generator = torch.Generator().manual_seed(args.seed)
    sampler = (torch.utils.data.WeightedRandomSampler(sample_weights, len(train_encoded),
                                                     replacement=True, generator=generator)
               if balance_power else None)
    loader = torch.utils.data.DataLoader(train_encoded, batch_size=args.batch_size, shuffle=sampler is None,
                                        sampler=sampler, collate_fn=collate, generator=generator, num_workers=0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = len(loader) * args.epochs
    warmup = max(1, int(total_steps * 0.1))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda step: step / warmup if step < warmup else
        max(0.0, (total_steps - step) / max(1, total_steps - warmup)))
    out.mkdir(parents=True, exist_ok=False)
    model_path = out / "model"
    inference_stride = min(64, args.max_length - 3)
    history, best_predictions = [], None
    best_f1, best_epoch, stale = -1.0, 0, 0
    started = time.monotonic()
    base_files = [path for path in base_model.rglob("*") if path.is_file()
                  and (path.suffix in {".json", ".txt", ".safetensors"})]
    manifest = {
        "artifact_type": ARTIFACT_TYPE, "artifact_version": 1, "label_schema_version": 1,
        "training_source": "human_gold", "status": "training", "model_dir": "model",
        "entity_categories": list(CATEGORIES), "label2id": LABEL2ID,
        "max_length": args.max_length, "stride": inference_stride,
        "input_manifest": {"train": train_meta, "validation": validation_meta},
        "split_separation": separation, "created_utc": datetime.now(timezone.utc).isoformat(),
        "training_sampling": {"method": "weighted_with_replacement" if sampler is not None else "uniform_shuffle",
                              "balance_power": balance_power, "category_document_support": category_support,
                              "draws_per_epoch": len(train_rows), "unique_source_rows": len(train_rows),
                              "min_weight": min(sample_weights), "max_weight": max(sample_weights),
                              "label_or_text_augmentation": False},
        "base_model": {"path": str(base_model), "files_sha256": {
            str(path.relative_to(base_model)): file_hash(path) for path in sorted(base_files)}},
        "code_sha256": {str(Path(path).resolve()): file_hash(path)
                        for path in (__file__, workflow.__file__, shared_inference.__file__)},
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "transformers": transformers.__version__, "numpy": np.__version__,
                        "device": device, "cuda_available": torch.cuda.is_available(),
                        "torch_threads": args.torch_threads},
        "hyperparameters": {key: value for key, value in vars(args).items() if not isinstance(value, Path)},
        "selection": {"split": "validation", "origin_kind": "ner", "units": len(main_rows),
                      "metric": "strict_entity_span_micro_f1", "tie_break": "earliest_epoch"},
        "test_read": False, "weak_labels_used": False, "application_weights_replaced": False,
        "limitations": ["Human-adjudicated source text is still synthetic.",
                        "Validation selects checkpoints and is a development set, not a sealed final test.",
                        "No real-world safety or production readiness is established by this experiment.",
                        "Declared source IDs cannot prove template independence."]}
    dump_json(out / "artifact_manifest.json", manifest)
    for epoch in range(1, args.epochs + 1):
        model.train()
        loss_sum = token_count = 0
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            result = model(**batch)
            require(bool(torch.isfinite(result.loss).item()), "Non-finite training loss")
            result.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            count = int((batch["labels"] != -100).sum().item())
            loss_sum += float(result.loss.detach().cpu()) * count
            token_count += count
        predictions = predict_entities(model, tokenizer, [row["text"] for row in main_rows], device,
                                       max_length=args.max_length, batch_size=args.batch_size,
                                       stride=inference_stride)
        report, _, _ = score_predictions(main_rows, predictions)
        f1 = report["micro"]["f1"]
        entry = {"epoch": epoch, "train_loss": loss_sum / token_count, "train_tokens": token_count,
                 "learning_rate": scheduler.get_last_lr()[0], "validation_ner": report,
                 "elapsed_seconds": round(time.monotonic() - started, 2)}
        history.append(entry)
        if f1 > best_f1:
            best_f1, best_epoch, stale, best_predictions = f1, epoch, 0, predictions
            model.save_pretrained(str(model_path), safe_serialization=True)
            tokenizer.save_pretrained(str(model_path))
        else:
            stale += 1
        dump_json(out / "history.json", history)
        print(json.dumps({"epoch": epoch, "loss": entry["train_loss"], "ner_strict_f1": f1,
                          "best_epoch": best_epoch, "elapsed_seconds": entry["elapsed_seconds"]}), flush=True)
        if epoch >= args.min_epochs and stale >= args.patience:
            break
    # Free the optimizer's full model-sized state before loading a second copy.
    del optimizer, scheduler, loader, model, result, batch
    if device == "cuda":
        torch.cuda.empty_cache()
    reloaded = AutoModelForTokenClassification.from_pretrained(
        str(model_path), local_files_only=True, trust_remote_code=False, use_safetensors=True).to(device)
    reloaded_tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True,
                                                       trust_remote_code=False, use_fast=True)
    predictions = predict_entities(reloaded, reloaded_tokenizer, [row["text"] for row in main_rows], device,
                                   max_length=args.max_length, batch_size=args.batch_size,
                                   stride=inference_stride)
    span_keys = lambda collection: [[(e["start"], e["end"], e["category"], e["text"]) for e in row]
                                    for row in collection]
    require(span_keys(predictions) == span_keys(best_predictions), "Saved model reload changed entity predictions")
    report, prediction_rows, errors = score_predictions(main_rows, predictions)
    dump_json(out / "validation_metrics.json", report)
    dump_jsonl(out / "predictions.jsonl", prediction_rows)
    dump_jsonl(out / "errors.jsonl", errors)
    all_predictions = predict_entities(reloaded, reloaded_tokenizer, [row["text"] for row in validation_rows],
                                       device, max_length=args.max_length, batch_size=args.batch_size,
                                       stride=inference_stride)
    all_report, all_prediction_rows, all_errors = score_predictions(validation_rows, all_predictions)
    dump_json(out / "validation_all_metrics.json", all_report)
    dump_jsonl(out / "validation_all_predictions.jsonl", all_prediction_rows)
    dump_jsonl(out / "validation_all_errors.jsonl", all_errors)
    dump_json(out / "label_map.json", {"label2id": LABEL2ID, "id2label": ID2LABEL})
    manifest.update(status="complete", best_epoch=best_epoch, best_validation_f1=best_f1,
                    completed_epochs=len(history), elapsed_seconds=round(time.monotonic() - started, 2),
                    reload_prediction_check={"identical_entity_spans": True, "units": len(main_rows)},
                    artifact_files_sha256={str(path.relative_to(out)): file_hash(path)
                                           for path in sorted(out.rglob("*")) if path.is_file()
                                           and path.name != "artifact_manifest.json"})
    dump_json(out / "artifact_manifest.json", manifest)
    print(json.dumps({"status": "complete", "out": str(out), "best_epoch": best_epoch,
                      "validation_ner_micro": report["micro"]}, ensure_ascii=False), flush=True)
    return manifest


if __name__ == "__main__":
    train(get_parser().parse_args())
