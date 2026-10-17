from llm_shield.m2_detect.gliner_ner import GLiNERDetector
from unittest.mock import Mock
import pytest
from llm_shield import pipeline
from llm_shield.m2_detect.pipeline import DetectionError, detect_all, detect_and_segment, merge_spans
from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.schema import Material, ShieldRequest, Span

def test_detector_exception_cannot_become_empty_results():
    detector = Mock()
    detector.detect.side_effect = RuntimeError('secret original input')
    with pytest.raises(DetectionError) as raised:
        detect_all('材料', detectors=[detector])
    assert 'secret' not in str(raised.value)

def test_empty_detector_chain_fails_closed():
    with pytest.raises(DetectionError):
        detect_all('材料', detectors=[])

def test_overlapping_spans_cover_both_ends_and_match_source():
    text = 'abc123456'
    source = [Span(0, 5, text[:5], 'ORG'), Span(3, 9, text[3:], 'API_KEY')]
    spans = merge_spans(source, text)
    assert [(s.start, s.end, s.text, s.category) for s in spans] == [(0, 9, text, 'API_KEY')]
    assert source[0].end == 5

def test_cross_sentence_entity_is_never_lost():
    text = '甲。乙\n丙'
    detector = Mock()
    detector.detect.return_value = [Span(0, 5, text, 'API_KEY')]
    spans, segments = detect_and_segment(text, detectors=[detector])
    assert len(segments) == 1 and segments[0].spans == spans

def test_outbound_detector_failure_is_a_block(monkeypatch):
    import llm_shield.m7_egress.gateway as gateway
    monkeypatch.setattr(gateway, 'inspect_payload', Mock(side_effect=DetectionError('failure')))
    result = EgressGateway().precheck('external_model', 'student_leader', '材料', task_key='meeting_minutes')
    assert not result['allowed'] and '识别失败' in result['reason']

def test_pipeline_detector_failure_pauses_before_any_gateway(monkeypatch):
    monkeypatch.setattr(pipeline, 'get_model', lambda: Mock(available=True))
    monkeypatch.setattr(pipeline, 'detect_and_segment', Mock(side_effect=DetectionError('识别失败')))
    gateway = Mock(side_effect=AssertionError('不能发送'))
    monkeypatch.setattr(pipeline, 'EgressGateway', gateway)
    req = ShieldRequest('t', 'student_leader', 'meeting_minutes', 'external_model', [Material('t', 'uploaded', 'test', '材料')])
    result = pipeline.run_pipeline(req)
    assert result.paused and (not result.ok)
    gateway.assert_not_called()

def test_gliner_inference_error_pauses_instead_of_becoming_no_match():
    detector = object.__new__(GLiNERDetector)
    detector.available = True
    detector.semantic_labels = ['person']
    detector.format_labels = []
    detector.threshold = 0.5
    detector.model = Mock()
    detector.model.config.max_len = 384
    detector.model.inference.side_effect = RuntimeError('private input')
    with pytest.raises(DetectionError) as raised:
        detect_all('张明', detectors=[detector])
    assert 'private input' not in str(raised.value)
