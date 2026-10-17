"""Document boundaries and table context are shared by all application flows."""
from llm_shield.material_processing import prepare_materials
from llm_shield.schema import Material, Segment, Span


def test_each_material_keeps_its_own_table_context_and_global_offsets():
    materials = [
        Material("first", "uploaded", "", "甲", columns=["姓名"], rows=[{"姓名": "甲"}]),
        Material("second", "uploaded", "", "乙", columns=["电话"], rows=[{"电话": "乙"}]),
    ]
    calls = []

    def detect(text, columns=None, rows=None, detectors=None):
        calls.append((text, columns, rows, detectors))
        value = text[0]
        span = Span(0, 1, value, "PERSON_NAME", column=columns[0])
        return [span], [Segment("local", text, 0, len(text), [span], context=text)]

    prepared = prepare_materials(materials, detect=detect, detectors=["shared"])
    assert [call[1] for call in calls] == [["姓名"], ["电话"]]
    assert all(call[3] == ["shared"] for call in calls)
    assert prepared.text == "\n".join(call[0] for call in calls)
    second_start = len(calls[0][0]) + 1
    assert [(span.start, span.end, span.column) for span in prepared.spans] == [
        (0, 1, "姓名"), (second_start, second_start + 1, "电话")]
    assert [seg.seg_id for seg in prepared.segments] == ["seg_0", "seg_1"]
    assert prepared.segments[1].start == second_start
    assert prepared.segments[1].spans == [prepared.spans[1]]


def test_upload_error_does_not_echo_parser_exception(monkeypatch):
    from fastapi.testclient import TestClient
    import llm_shield.server as server

    def fail(*args, **kwargs):
        raise RuntimeError("private source text")

    monkeypatch.setattr(server, "parse_uploads", fail)
    response = TestClient(server.app).post(
        "/api/upload", files={"file": ("sample.txt", b"sample", "text/plain")})
    assert response.status_code == 500
    assert "private source text" not in response.text


def test_upload_rejects_file_above_size_limit():
    from fastapi.testclient import TestClient
    from llm_shield.m1_access.file_loader import MAX_BYTES
    from llm_shield.server import app

    response = TestClient(app).post(
        "/api/upload", files={"file": ("large.txt", b"a" * (MAX_BYTES + 1), "text/plain")})
    assert response.status_code == 400


def test_mixed_sentence_gets_independent_safe_actions():
    from types import SimpleNamespace
    from llm_shield.processing import analyze
    from llm_shield.m6_transform.anonymizer import apply_decisions
    from llm_shield.m6_transform.mapping import MappingTable

    source = "负责人张明，电话13812345678。周五交稿。"

    def detect(text, columns=None, rows=None, detectors=None):
        name = Span(text.index("张明"), text.index("张明") + 2, "张明", "PERSON_NAME")
        phone = Span(text.index("13812345678"), text.index("13812345678") + 11,
                     "13812345678", "PHONE")
        return [name, phone], [Segment("sentence", text, 0, len(text), [name, phone],
                                      context=text)]

    def scorer(segment, *args, **kwargs):
        return {"PSEUDONYMIZE": 1.0} if segment.spans[0].category == "PERSON_NAME" else {"DELETE": 1.0}

    analysis = analyze("student_leader", "meeting_minutes", "external_model",
                       [Material("x", "uploaded", "", source)],
                       model_loader=lambda: SimpleNamespace(available=True),
                       detector_builder=lambda: ["stub"], detect=detect, scorer=scorer)
    assert not analysis.paused
    assert [decision.action.value for decision in analysis.decisions] == ["PSEUDONYMIZE", "DELETE"]
    result = apply_decisions(analysis.text, analysis.segments, analysis.decisions,
                             "test-session", MappingTable())
    assert "张明" not in result["sanitized_text"]
    assert "13812345678" not in result["sanitized_text"]
    assert "周五交稿" in result["sanitized_text"]


def test_multiple_materials_share_one_gliner_inference_batch():
    from unittest.mock import Mock
    from llm_shield.m2_detect.gliner_ner import GLiNERDetector

    detector = object.__new__(GLiNERDetector)
    detector.available = True
    detector.semantic_labels = ["人名"]
    detector.format_labels = []
    detector.categories = {"PERSON_NAME"}
    detector.threshold = .5
    detector.model = Mock()
    detector.model.config.max_len = 384
    detector.model.inference.side_effect = lambda windows, labels, threshold: [
        [{"label": "人名", "start": 0, "end": 2, "score": .9}] for _ in windows]

    prepared = prepare_materials([
        Material("a", "uploaded", "", "张明"),
        Material("b", "uploaded", "", "李四"),
    ], detectors=[detector])
    assert detector.model.inference.call_count == 1
    assert [span.text for span in prepared.spans] == ["张明", "李四"]
    assert prepared.text[prepared.spans[1].start:prepared.spans[1].end] == "李四"
