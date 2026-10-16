"""Exercise the opt-in model path and fail-closed loading without downloading weights."""
from types import SimpleNamespace

import pytest

from llm_shield.m2_detect import pipeline


def test_disabled_candidate_keeps_existing_detectors(monkeypatch):
    monkeypatch.setattr(pipeline.cfg, 'reviewed_ner_settings', lambda: ('', 'cpu'))
    assert [type(d).__name__ for d in pipeline.build_detectors(False)] == ['RegexDetector', 'EntityDetector']


def test_enabled_candidate_is_loaded_once_and_missing_candidate_blocks(monkeypatch):
    pipeline._reviewed_detector.cache_clear()
    calls = []
    good = SimpleNamespace(available=True)
    monkeypatch.setattr(pipeline.cfg, 'reviewed_ner_settings', lambda: ('fixture-model', 'cuda'))
    def factory(path, device):
        calls.append((path, device))
        return good
    monkeypatch.setattr(pipeline, 'ReviewedNERDetector', factory)
    assert pipeline.build_detectors(False)[-1] is good
    assert pipeline.build_detectors(False)[-1] is good
    assert calls == [('fixture-model', 'cuda')]
    pipeline._reviewed_detector.cache_clear()
    monkeypatch.setattr(pipeline, 'ReviewedNERDetector', lambda *a, **k: SimpleNamespace(available=False))
    with pytest.raises(pipeline.DetectionError):
        pipeline.build_detectors(False)
    pipeline._reviewed_detector.cache_clear()


def test_unknown_device_is_refused(monkeypatch):
    pipeline._reviewed_detector.cache_clear()
    monkeypatch.setattr(pipeline.cfg, 'reviewed_ner_settings', lambda: ('fixture-model', 'unknown'))
    with pytest.raises(pipeline.DetectionError):
        pipeline.build_detectors(False)
