"""GLiNER failures must stop the request instead of producing an empty result."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from llm_shield.m2_detect.gliner_ner import GLiNERDetector
from llm_shield.m2_detect.pipeline import DetectionError, detect_all
from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.m8_audit import observer


def detector(predict):
    instance = object.__new__(GLiNERDetector)
    instance.available = True
    instance.categories = {"PERSON_NAME"}
    instance.semantic_labels = ["人名"]
    instance.format_labels = []
    instance.threshold = 0.5
    instance.model = SimpleNamespace(config=SimpleNamespace(max_len=40),
        inference=lambda batch, labels, **kwargs: [predict(text, labels, **kwargs) for text in batch])
    return instance


def test_inference_exception_blocks_outbound_without_exposing_input(monkeypatch):
    broken = detector(Mock(side_effect=RuntimeError("private material should not appear in errors")))
    with pytest.raises(DetectionError) as error:
        detect_all("软件测试材料", detectors=[broken])
    assert "private" not in str(error.value)
    monkeypatch.setattr(observer, "detect_all", lambda text: detect_all(text, detectors=[broken]))
    result = EgressGateway().precheck("external_model", "student_leader", "软件测试材料",
                                     task_key="meeting_minutes")
    assert not result["allowed"] and "识别失败" in result["reason"]


def test_late_window_failure_discards_partial_success():
    predict = Mock(side_effect=[[{"start": 0, "end": 2, "label": "人名", "score": 0.9}],
                               RuntimeError("later window failed")])
    with pytest.raises(DetectionError):
        detect_all("甲乙" * 40, detectors=[detector(predict)])
    assert predict.call_count == 2


@pytest.mark.parametrize("change", [
    {"start": -1}, {"start": 0.9}, {"start": True}, {"end": 4}, {"end": 0},
    {"score": float("nan")}, {"score": float("inf")}, {"score": -0.1}, {"score": 1.1},
])
def test_malformed_predictions_stop_detection(change):
    prediction = {"start": 0, "end": 2, "label": "人名", "score": 0.9, **change}
    with pytest.raises(DetectionError):
        detect_all("甲乙丙", detectors=[detector(Mock(return_value=[prediction]))])


def test_successful_empty_result_is_still_allowed():
    assert detect_all("普通材料", detectors=[detector(Mock(return_value=[]))]) == []
