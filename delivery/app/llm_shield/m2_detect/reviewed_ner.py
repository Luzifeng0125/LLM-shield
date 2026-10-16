"""Local, explicitly enabled BERT NER trained on the reviewed gold dataset.

The trainer and application share offset handling and BIO decoding here. Artifact
metadata records provenance; it cannot independently certify human review.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence

from .base import Detector
from ..schema import Span


ENTITY_CATEGORIES = tuple(sorted({
    "PERSON_NAME", "PHONE", "EMAIL", "ID_CARD", "BANK_CARD", "STUDENT_ID",
    "API_KEY", "WECHAT", "BUDGET", "ORG", "LOCATION", "DORM", "GRADE",
    "SENSITIVE_ATTR",
}))
BIO_LABELS = ("O",) + tuple(
    prefix + category for category in ENTITY_CATEGORIES for prefix in ("B-", "I-")
)

_COMPLETE_ID_CARD = re.compile(r"(?:[0-9]{15}|[0-9]{17}[0-9Xx])\Z")
_PERSON_EDGE_SEPARATORS = frozenset("，。；：、！？,.;:!?—–")


def _complete_id_card_span(text: str, start: int, end: int) -> bool:
    """Reject incomplete number fragments at the application boundary.

    Human-reviewed synthetic ID fields can intentionally fail a real-world
    checksum. Preserve those full-length semantic predictions; reject only
    malformed lengths/content and a slice of a longer uninterrupted ID token.
    Raw model predictions and independent NER scoring remain unchanged.
    """
    if not _COMPLETE_ID_CARD.fullmatch(text[start:end]):
        return False
    adjacent = (text[start - 1] if start > 0 else "", text[end] if end < len(text) else "")
    return not any(character and (character.isdigit() or character in "Xx") for character in adjacent)


def _complete_student_number(text: str, start: int, end: int) -> bool:
    """Numeric student IDs follow the existing 8–12 digit schema, never year fragments."""
    value = text[start:end]
    if not value.isdecimal():
        return True  # Do not discard semantic alphanumeric IDs.
    if not re.fullmatch(r"[0-9]{8,12}", value):
        return False
    return not ((start > 0 and text[start - 1].isdecimal())
                or (end < len(text) and text[end].isdecimal()))


def _label_map(label2id: Mapping) -> dict[str, int]:
    if (not isinstance(label2id, dict) or set(label2id) != set(BIO_LABELS)
            or any(type(value) is not int for value in label2id.values())
            or set(label2id.values()) != set(range(len(BIO_LABELS)))):
        raise ValueError("模型必须包含完整且唯一的 29 类 BIO 标签")
    return dict(label2id)


def _id_map(id2label: Mapping) -> dict[int, str]:
    try:
        result = {int(key): value for key, value in id2label.items()}
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("无效的模型 id2label") from exc
    if len(result) != len(id2label):
        raise ValueError("重复的模型标签编号")
    _label_map({value: key for key, value in result.items()})
    return result


def decode_bio(text: str, offsets: Sequence, label_ids: Sequence,
               confidences: Sequence | None = None, *, id2label: Mapping | None = None) -> list[dict]:
    """Decode raw-text Python character offsets, never token or UTF-16 indices.

    Labels can be BIO strings or integer IDs with an explicit id2label mapping.
    Orphan I labels begin an entity, including at the beginning of a window.
    Whitespace between same-entity tokens is preserved in the source substring.
    """
    if len(offsets) != len(label_ids) or (confidences is not None and len(confidences) != len(offsets)):
        raise ValueError("标签、偏移和置信度的长度不一致")
    entities: list[dict] = []
    active = None
    scores: list[float] = []
    previous_end = 0

    def finish():
        nonlocal active, scores
        if active is not None:
            active["text"] = text[active["start"]:active["end"]]
            active["confidence"] = sum(scores) / len(scores)
            entities.append(active)
        active, scores = None, []

    for index, (offset, raw_label) in enumerate(zip(offsets, label_ids)):
        if len(offset) != 2:
            raise ValueError("无效的 token 偏移")
        start, end = map(int, offset)
        if start == end == 0:  # CLS / SEP / padding have no source location.
            continue
        if not 0 <= start < end <= len(text) or start < previous_end:
            raise ValueError("token 偏移越界、重叠或次序错误")
        previous_end = end
        if isinstance(raw_label, str):
            label = raw_label
        elif id2label is not None:
            try:
                label = id2label[int(raw_label)]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("模型输出未知标签编号") from exc
        else:
            raise ValueError("整数标签必须显式提供 id2label")
        if label not in BIO_LABELS:
            raise ValueError("模型输出未知 BIO 标签")
        score = 1.0 if confidences is None else float(confidences[index])
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("模型输出无效置信度")
        if label == "O":
            finish()
            continue
        prefix, category = label.split("-", 1)
        gap = text[active["end"]:start] if active is not None else ""
        if (prefix == "B" or active is None or active["category"] != category
                or (gap and not gap.isspace())):
            finish()
            active = {"start": start, "end": end, "category": category}
        else:
            active["end"] = end
        scores.append(score)
    finish()
    return entities


def constrained_bio_labels(log_probabilities, id2label):
    """Maximum-score legal BIO sequence; I-X may only follow B-X or I-X."""
    import numpy as np

    emissions = np.asarray(log_probabilities, dtype=np.float64)
    if emissions.size == 0:
        return []
    labels = [id2label[index] for index in range(len(id2label))]
    if emissions.ndim != 2 or emissions.shape[1] != len(labels) or not np.isfinite(emissions).all():
        raise ValueError("BIO decoding requires finite per-label scores")
    transitions = np.zeros((len(labels), len(labels)), dtype=np.float64)
    first = emissions[0].copy()
    for current, label in enumerate(labels):
        if label.startswith("I-"):
            first[current] = -np.inf
            transitions[:, current] = [0.0 if previous in {"B-" + label[2:], label} else -np.inf
                                       for previous in labels]
    scores, backpointers = first, []
    for emission in emissions[1:]:
        candidates = scores[:, None] + transitions
        previous = candidates.argmax(axis=0)
        scores = candidates[previous, np.arange(len(labels))] + emission
        backpointers.append(previous)
    chosen = [int(scores.argmax())]
    for previous in reversed(backpointers):
        chosen.append(int(previous[chosen[-1]]))
    return list(reversed(chosen))


def predict_entities(model, tokenizer, texts: Sequence[str], device,
                     max_length: int = 256, batch_size: int = 8, stride: int = 64,
                     decoding: str = "greedy") -> list[list[dict]]:
    """Predict complete texts using overlapping token windows and original offsets.

    For a token occurring in several windows, use the prediction with the most
    left/right context. Decode once per complete text, so overlap cannot duplicate
    entities and an I sequence can continue across a window boundary.
    """
    import torch

    if decoding not in {"greedy", "bio_viterbi"}:
        raise ValueError("Unknown BIO decoding strategy")
    if isinstance(texts, str) or any(not isinstance(text, str) for text in texts):
        raise TypeError("texts 必须是字符串序列")
    texts = list(texts)
    if not texts:
        return []
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("必须使用支持原文偏移的 fast tokenizer")
    if type(max_length) is not int or type(batch_size) is not int or type(stride) is not int:
        raise ValueError("推理窗口参数必须为整数")
    position_limit = getattr(model.config, "max_position_embeddings", 512)
    if not 4 <= max_length <= position_limit or batch_size < 1:
        raise ValueError("推理长度超出模型位置容量或 batch_size 无效")
    content_size = max_length - tokenizer.num_special_tokens_to_add(pair=False)
    if not 0 <= stride < content_size:
        raise ValueError("滑窗重叠长度无效")
    id2label = _id_map(model.config.id2label)
    encoded = tokenizer(
        texts, truncation=True, max_length=max_length, stride=stride,
        return_overflowing_tokens=True, return_offsets_mapping=True,
        padding=True, return_tensors="pt",
    )
    offsets = encoded.pop("offset_mapping").tolist()
    sample_indices = encoded.pop("overflow_to_sample_mapping").tolist()
    if len(offsets) != len(sample_indices):
        raise ValueError("tokenizer 滑窗映射不完整")
    # One selected prediction per raw token interval and input text.
    selected: list[dict] = [{} for _ in texts]
    model.eval()
    with torch.inference_mode():
        for first in range(0, len(offsets), batch_size):
            inputs = {key: value[first:first + batch_size].to(device)
                      for key, value in encoded.items()}
            logits = model(**inputs).logits
            if (tuple(logits.shape[:2]) != tuple(inputs["input_ids"].shape)
                    or len(logits.shape) != 3 or logits.shape[-1] != len(BIO_LABELS)):
                raise ValueError("模型输出维度与 29 类 BIO 标签不一致")
            probabilities, predictions = torch.softmax(logits, dim=-1).max(dim=-1)
            emissions = torch.log_softmax(logits, dim=-1).cpu().tolist() if decoding == "bio_viterbi" else None
            predictions = predictions.cpu().tolist()
            probabilities = probabilities.cpu().tolist()
            for local_index, (predicted, confidence) in enumerate(zip(predictions, probabilities)):
                window = first + local_index
                sample = sample_indices[window]
                if not 0 <= sample < len(texts):
                    raise ValueError("tokenizer 返回无效样本编号")
                real_tokens = [(index, tuple(map(int, offset)))
                               for index, offset in enumerate(offsets[window])
                               if offset[1] > offset[0]]
                for rank, (index, offset) in enumerate(real_tokens):
                    if not 0 <= offset[0] < offset[1] <= len(texts[sample]):
                        raise ValueError("tokenizer 返回越界原文偏移")
                    quality = (min(rank, len(real_tokens) - rank - 1), confidence[index])
                    existing = selected[sample].get(offset)
                    if existing is None or quality > existing[0]:
                        selected[sample][offset] = (quality, predicted[index], confidence[index],
                                                   emissions[local_index][index] if emissions is not None else None)
    result = []
    for text, tokens in zip(texts, selected):
        ordered = sorted(tokens)
        labels = ([tokens[offset][1] for offset in ordered] if decoding == "greedy" else
                  constrained_bio_labels([tokens[offset][3] for offset in ordered], id2label))
        confidence = ([tokens[offset][2] for offset in ordered] if decoding == "greedy" else
                      [math.exp(tokens[offset][3][label]) for offset, label in zip(ordered, labels)])
        result.append(decode_bio(
            text, ordered, labels, confidence, id2label=id2label,
        ))
    return result


def _read_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("模型元数据包含重复字段")
            result[key] = value
        return result

    result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("模型元数据必须是对象")
    return result


def _validate_artifact(path: Path) -> tuple[Path, dict]:
    root = path.parent if path.name == "model" else path
    manifest = _read_json(root / "artifact_manifest.json")
    if (manifest.get("artifact_type") != "yindun-reviewed-bert-ner"
            or manifest.get("artifact_version") != 1
            or manifest.get("label_schema_version") != 1
            or manifest.get("status") != "complete"
            or manifest.get("training_source") != "human_gold"
            or manifest.get("model_dir") != "model"):
        raise ValueError("模型缺少受支持的人工 gold 来源及标签版本元数据")
    sources = manifest.get("input_manifest")
    if not isinstance(sources, dict) or set(sources) != {"train", "validation"}:
        raise ValueError("缺少训练及验证数据来源记录")
    for source in sources.values():
        if (not isinstance(source, dict) or type(source.get("rows")) is not int
                or source["rows"] < 1 or not _is_sha256(source.get("sha256"))):
            raise ValueError("数据来源记录缺少有效哈希或行数")
    categories = manifest.get("entity_categories")
    if not isinstance(categories, list) or sorted(categories) != list(ENTITY_CATEGORIES):
        raise ValueError("人工 gold 模型必须包含完整 14 类实体")
    label2id = _label_map(manifest.get("label2id"))
    model_dir = root / "model"
    config = _read_json(model_dir / "config.json")
    config_labels = _label_map(config.get("label2id"))
    id2label = _id_map(config.get("id2label"))
    if label2id != config_labels or id2label != {value: key for key, value in label2id.items()}:
        raise ValueError("来源清单与模型 BIO 标签映射不一致")
    if config.get("auto_map"):
        raise ValueError("人工 gold 模型不允许自定义远程代码")
    max_length = manifest.get("max_length")
    if (type(max_length) is not int
            or not 4 <= max_length <= min(config.get("max_position_embeddings", 512), 512)):
        raise ValueError("来源清单推理窗口长度无效")
    stride = manifest.get("stride")
    if type(stride) is not int or not 0 <= stride < max_length - 2:
        raise ValueError("来源清单滑窗重叠长度无效")
    if not (model_dir / "model.safetensors").is_file():
        index = _read_json(model_dir / "model.safetensors.index.json")
        shards = set(index.get("weight_map", {}).values())
        if not shards:
            raise ValueError("缺少 safetensors 模型权重")
        for name in shards:
            shard = (model_dir / name).resolve()
            if (not shard.is_relative_to(model_dir.resolve()) or shard.suffix != ".safetensors"
                    or not shard.is_file()):
                raise ValueError("无效的本地 safetensors 分片")
    file_hashes = manifest.get("artifact_files_sha256")
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise ValueError("缺少候选模型文件完整性记录")
    normalized_hashes = {}
    for name, digest in file_hashes.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root.resolve()) or not _is_sha256(digest):
            raise ValueError("无效的候选模型文件完整性记录")
        if target.is_relative_to(model_dir.resolve()) and not target.is_file():
            raise ValueError("完整性清单中的模型文件缺失")
        if target in normalized_hashes:
            raise ValueError("完整性清单包含重复文件路径")
        normalized_hashes[target] = digest
    for model_file in model_dir.rglob("*"):
        if not model_file.is_file():
            continue
        expected = normalized_hashes.get(model_file.resolve())
        if expected is None:
            raise ValueError("模型文件未记录在完整性清单中")
        digest = hashlib.sha256()
        with model_file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("模型文件哈希与训练产物清单不一致")
    return model_dir, manifest


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


class ReviewedNERDetector(Detector):
    """An unavailable or failed explicitly selected model must stop detection."""

    name = "reviewed_ner"

    def __init__(self, model_dir, device: str = "cpu", *, batch_size: int = 8, decoding: str = "greedy"):
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.device = device
        self.batch_size = batch_size
        self.decoding = decoding
        self.available = False
        self.reason = ""
        self.model = self.tokenizer = None
        self.manifest: dict = {}
        try:
            if decoding not in {"greedy", "bio_viterbi"}:
                raise ValueError("Unknown BIO decoding strategy")
            directory, self.manifest = _validate_artifact(self.model_dir)
            from transformers import AutoModelForTokenClassification, AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(directory), local_files_only=True, trust_remote_code=False, use_fast=True,
            )
            if not self.tokenizer.is_fast:
                raise ValueError("模型 tokenizer 不支持可靠的原文偏移")
            self.model = AutoModelForTokenClassification.from_pretrained(
                str(directory), local_files_only=True, trust_remote_code=False, use_safetensors=True,
            )
            if _id_map(self.model.config.id2label) != {
                value: key for key, value in self.manifest["label2id"].items()
            }:
                raise ValueError("已加载模型与人工 gold 来源清单标签不一致")
            self.model.to(device)
            self.model.eval()
            self.available = True
            self.reason = f"已加载人工 gold NER 候选模型 -> {device}"
        except Exception as exc:
            self.model = self.tokenizer = None
            self.reason = f"人工 gold NER 模型加载失败 ({type(exc).__name__}): {exc}"

    def detect(self, text: str, columns=None, rows=None) -> list[Span]:
        if not self.available:
            raise RuntimeError("已启用的人工 gold NER 模型不可用，已暂停处理")
        if not text:
            return []
        max_length = self.manifest["max_length"]
        entities = predict_entities(
            self.model, self.tokenizer, [text], self.device,
            max_length=max_length, batch_size=self.batch_size,
            stride=self.manifest["stride"],
            decoding=self.decoding,
        )[0]
        spans = []
        for item in entities:
            start, end, category = item["start"], item["end"], item["category"]
            if not 0 <= start < end <= len(text):
                raise ValueError("Invalid model entity offsets")
            if category == "PERSON_NAME":
                # Sentence separators cannot be part of a person's name.
                # Internal hyphens, middle dots, apostrophes and spaces remain.
                while start < end and text[start] in _PERSON_EDGE_SEPARATORS:
                    start += 1
                while start < end and text[end - 1] in _PERSON_EDGE_SEPARATORS:
                    end -= 1
                if start == end:
                    continue
            if category == "ID_CARD" and not _complete_id_card_span(text, start, end):
                continue
            if category == "STUDENT_ID" and not _complete_student_number(text, start, end):
                continue
            spans.append(Span(start, end, text[start:end], category, item["confidence"],
                              self.name, f"reviewed_ner_{category}"))
        return spans
