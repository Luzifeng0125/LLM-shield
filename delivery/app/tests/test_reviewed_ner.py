"""Regression checks for the human-gold model boundary; no network or model downloads."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from llm_shield.m2_detect import reviewed_ner as ner
from llm_shield.m2_detect.entity_rules import EntityDetector
from llm_shield.m2_detect.pipeline import DetectionError, detect_and_segment
from llm_shield.m2_detect.regex_rules import RegexDetector


def test_decode_unicode_whitespace_and_wordpiece_offsets():
    text = "🙂联系人 Alice Smith 在校"
    offsets = [(0, 0), (0, 1), (1, 2), (2, 3), (3, 4), (5, 7), (7, 10), (11, 16), (17, 18), (18, 19), (0, 0)]
    labels = ["O", "O", "O", "O", "O", "B-PERSON_NAME", "I-PERSON_NAME", "I-PERSON_NAME", "O", "O", "O"]
    result = ner.decode_bio(text, offsets, labels)
    assert result == [{"start": 5, "end": 16, "category": "PERSON_NAME",
                       "text": "Alice Smith", "confidence": 1.0}]


def test_decode_orphan_i_and_adjacent_b_are_separate():
    result = ner.decode_bio("张三李四", [(0, 1), (1, 2), (2, 3), (3, 4)],
                            ["I-PERSON_NAME", "I-PERSON_NAME", "B-PERSON_NAME", "I-PERSON_NAME"])
    assert [(item["start"], item["end"], item["text"]) for item in result] == [
        (0, 2, "张三"), (2, 4, "李四")]


def test_decode_does_not_bridge_unrepresented_nonwhitespace():
    result = ner.decode_bio("张；李", [(0, 1), (2, 3)], ["B-PERSON_NAME", "I-PERSON_NAME"])
    assert [item["text"] for item in result] == ["张", "李"]


@pytest.mark.parametrize("labels", [["B-UNKNOWN"], [999]])
def test_unknown_categories_and_ids_fail_instead_of_becoming_org(labels):
    with pytest.raises(ValueError):
        ner.decode_bio("甲", [(0, 1)], labels, id2label={0: "O"})


@pytest.mark.parametrize("offsets", [[(-1, 1)], [(0, 2)], [(0, 1), (0, 1)]])
def test_invalid_offsets_are_rejected(offsets):
    with pytest.raises(ValueError):
        ner.decode_bio("甲", offsets, ["B-ORG"] * len(offsets))


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_confidence_is_rejected(score):
    with pytest.raises(ValueError):
        ner.decode_bio("甲", [(0, 1)], ["B-ORG"], [score])


def _artifact(tmp_path):
    root = tmp_path / "candidate"
    model = root / "model"
    model.mkdir(parents=True)
    label2id = dict(zip(ner.BIO_LABELS, range(len(ner.BIO_LABELS))))
    manifest = {
        "artifact_type": "yindun-reviewed-bert-ner", "artifact_version": 1,
        "training_source": "human_gold", "label_schema_version": 1,
        "entity_categories": list(ner.ENTITY_CATEGORIES), "label2id": label2id,
        "model_dir": "model", "max_length": 256, "stride": 64,
        "status": "complete", "input_manifest": {
            "train": {"sha256": "a" * 64, "rows": 128},
            "validation": {"sha256": "b" * 64, "rows": 92},
        },
    }
    config = {"label2id": label2id, "id2label": {value: key for key, value in label2id.items()},
              "max_position_embeddings": 512}
    (model / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"test stub; never deserialized")
    manifest["artifact_files_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in model.iterdir()
    }
    (root / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, manifest, config


@pytest.mark.parametrize("field,value", [
    ("training_source", "synthetic"), ("label_schema_version", 0),
    ("entity_categories", ["ORG"]), ("label2id", {"O": 0}),
    ("max_length", 513), ("model_dir", "../remote"),
    ("status", "training"), ("input_manifest", {}),
    ("stride", None), ("stride", -1), ("stride", 254), ("stride", True),
])
def test_invalid_artifact_provenance_or_schema_fails_closed(tmp_path, field, value):
    root, manifest, _ = _artifact(tmp_path)
    manifest[field] = value
    (root / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    detector = ner.ReviewedNERDetector(root)
    assert not detector.available and detector.reason
    with pytest.raises(RuntimeError):
        detector.detect("学生张三")
    with pytest.raises(DetectionError):
        detect_and_segment("学生张三", detectors=[RegexDetector(), EntityDetector(), detector])


def test_config_mapping_mismatch_and_pickle_only_are_rejected(tmp_path):
    root, _, config = _artifact(tmp_path)
    config["id2label"][1], config["id2label"][2] = config["id2label"][2], config["id2label"][1]
    (root / "model" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="不一致"):
        ner._validate_artifact(root)

    config["id2label"][1], config["id2label"][2] = config["id2label"][2], config["id2label"][1]
    (root / "model" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "model" / "model.safetensors").unlink()
    (root / "model" / "pytorch_model.bin").write_bytes(b"must not be loaded")
    detector = ner.ReviewedNERDetector(root)
    assert not detector.available


def test_tampered_model_is_rejected_before_deserialization(tmp_path):
    root, _, _ = _artifact(tmp_path)
    (root / "model" / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="哈希"):
        ner._validate_artifact(root)


def test_missing_manifest_tokenizer_file_is_rejected(tmp_path):
    root, manifest, _ = _artifact(tmp_path)
    deleted_file = root / "model" / "tokenizer.json"
    manifest["artifact_files_sha256"][str(deleted_file.relative_to(root))] = "c" * 64
    (root / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="模型文件缺失"):
        ner._validate_artifact(root)


def test_small_window_manifest_accepts_training_stride(tmp_path):
    root, manifest, _ = _artifact(tmp_path)
    manifest.update(max_length=8, stride=min(64, 8 - 3))
    (root / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _, loaded = ner._validate_artifact(root)
    assert loaded["stride"] == 5


def test_loader_uses_local_safetensors_and_no_remote_code(tmp_path, monkeypatch):
    import sys
    root, _, config = _artifact(tmp_path)
    model = Mock(config=SimpleNamespace(id2label=config["id2label"]))
    tokenizer = Mock(is_fast=True)
    model_loader = Mock(return_value=model)
    tokenizer_loader = Mock(return_value=tokenizer)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoModelForTokenClassification=SimpleNamespace(from_pretrained=model_loader),
        AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer_loader),
    ))
    detector = ner.ReviewedNERDetector(root / "model", device="cpu")
    assert detector.available
    assert model_loader.call_args.kwargs == {
        "local_files_only": True, "trust_remote_code": False, "use_safetensors": True}
    assert tokenizer_loader.call_args.kwargs == {
        "local_files_only": True, "trust_remote_code": False, "use_fast": True}


def test_adapter_integration_preserves_complete_original_span(tmp_path, monkeypatch):
    detector = ner.ReviewedNERDetector(tmp_path / "missing")
    detector.available = True
    detector.manifest = {"max_length": 256, "stride": 64}
    text = "🙂姓名 Alice Smith。"
    monkeypatch.setattr(ner, "predict_entities", lambda *args, **kwargs: [[{
        "start": 4, "end": 15, "text": text[4:15], "category": "PERSON_NAME", "confidence": 0.95,
    }]])
    spans, segments = detect_and_segment(text, detectors=[RegexDetector(), EntityDetector(), detector])
    assert any(span.start <= 4 and span.end >= 15 for span in spans)
    assert all(span.text == text[span.start:span.end] for span in spans)
    assert all(any(span in segment.spans for segment in segments) for span in spans)


def test_adapter_consumes_exact_manifest_stride(tmp_path, monkeypatch):
    detector = ner.ReviewedNERDetector(tmp_path / "missing")
    detector.available = True
    detector.manifest = {"max_length": 32, "stride": 29}
    predictor = Mock(return_value=[[]])
    monkeypatch.setattr(ner, "predict_entities", predictor)
    assert detector.detect("普通材料") == []
    assert predictor.call_args.kwargs["max_length"] == 32
    assert predictor.call_args.kwargs["stride"] == 29


@pytest.mark.parametrize("prefix,value,suffix,accepted", [
    ("身份证：", "11010519491231002X", "。", True),
    ("身份证：", "11010519491231002x", "。", True),
    ("旧证号：", "130503670401001", "。", True),
    # Synthetic field values stay semantically sensitive despite bad checksums.
    ("合成身份证字段：", "123456789012345678", "。", True),
    ("合成身份证字段：", "99999920020703123X", "。", True),
    ("身份证：", "789012345678", "。", False),
    ("身份证：", "12345678901234567", "。", False),
    ("身份证：", "1234567890123456789", "。", False),
    ("身份证：", "11010519491231002A", "。", False),
    ("身份证：123", "456789012345678", "。", False),
    ("身份证：", "123456789012345", "678。", False),
    ("身份证：0", "11010519491231002X", "。", False),
    ("身份证：", "11010519491231002X", "0。", False),
    ("身份证：X", "11010519491231002X", "。", False),
    ("身份证：x", "11010519491231002X", "。", False),
    ("身份证：", "11010519491231002X", "X。", False),
    ("身份证：", "11010519491231002X", "x。", False),
    ("", "11010519491231002X", "", True),
])
def test_adapter_id_card_requires_complete_format(tmp_path, monkeypatch, prefix, value, suffix, accepted):
    detector = ner.ReviewedNERDetector(tmp_path / "missing")
    detector.available = True
    detector.manifest = {"max_length": 256, "stride": 64}
    text = prefix + value + suffix
    start, end = len(prefix), len(prefix) + len(value)
    prediction = {"start": start, "end": end, "text": value, "category": "ID_CARD", "confidence": 0.99}
    monkeypatch.setattr(ner, "predict_entities", Mock(return_value=[[prediction]]))
    result = detector.detect(text)
    assert bool(result) is accepted
    if accepted:
        assert len(result) == 1
        assert (result[0].start, result[0].end, result[0].text) == (start, end, value)
    assert prediction["text"] == value  # Application filtering never rewrites raw predictions.


def test_application_id_format_guard_does_not_change_other_categories(tmp_path, monkeypatch):
    detector = ner.ReviewedNERDetector(tmp_path / "missing")
    detector.available = True
    detector.manifest = {"max_length": 256, "stride": 64}
    value = "2026005535"
    monkeypatch.setattr(ner, "predict_entities", Mock(return_value=[[{
        "start": 0, "end": len(value), "text": value, "category": "STUDENT_ID", "confidence": 0.99,
    }]]))
    result = detector.detect(value)
    assert len(result) == 1 and result[0].category == "STUDENT_ID"


def test_overflow_reassembles_entity_once_and_covers_late_text():
    torch = pytest.importorskip("torch")
    labels = {name: index for index, name in enumerate(ner.BIO_LABELS)}
    # Two windows overlap tokens 3..6. Entity begins in window 1 and ends in
    # window 2; another entity exists beyond the first window's coverage.
    expected = ["O", "O", "B-ORG", "I-ORG", "I-ORG", "I-ORG", "I-ORG", "O", "B-GRADE", "I-GRADE"]
    windows = [list(range(0, 6)), list(range(3, 9)), list(range(6, 10))]

    class Tokenizer:
        is_fast = True

        @staticmethod
        def num_special_tokens_to_add(pair=False):
            return 2

        def __call__(self, texts, **kwargs):
            assert texts == ["甲乙丙丁戊己庚辛壬癸", ""]
            assert kwargs["return_overflowing_tokens"] and kwargs["return_offsets_mapping"]
            assert kwargs["stride"] == 3 and kwargs["max_length"] == 8
            offsets, ids = [], []
            for window in windows:
                offsets.append([(0, 0)] + [(i, i + 1) for i in window] + [(0, 0)] * (7 - len(window)))
                ids.append([0] + [labels[expected[i]] for i in window] + [0] * (7 - len(window)))
            offsets.append([(0, 0)] * 8)
            ids.append([0] * 8)
            return {"input_ids": torch.tensor(ids), "attention_mask": torch.ones(4, 8, dtype=torch.long),
                    "offset_mapping": torch.tensor(offsets), "overflow_to_sample_mapping": torch.tensor([0, 0, 0, 1])}

    class Model:
        config = SimpleNamespace(id2label={index: name for name, index in labels.items()}, max_position_embeddings=512)

        def eval(self):
            return self

        def __call__(self, input_ids, attention_mask):
            logits = torch.full((*input_ids.shape, len(labels)), -9.0)
            logits.scatter_(2, input_ids.unsqueeze(-1), 9.0)
            return SimpleNamespace(logits=logits)

    predictions = ner.predict_entities(Model(), Tokenizer(), ["甲乙丙丁戊己庚辛壬癸", ""], "cpu",
                                       max_length=8, batch_size=2, stride=3)
    assert [(item["start"], item["end"], item["category"]) for item in predictions[0]] == [
        (2, 7, "ORG"), (8, 10, "GRADE")]
    assert predictions[1] == []
