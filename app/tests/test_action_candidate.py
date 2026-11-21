"""Candidate selection must not silently revert to live weights or mix data splits."""
import pytest

from llm_shield import config
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity import model
from llm_shield.schema import Action, Segment, Span
from scripts.train_segment_coverage_candidate import isolated_segments, reviewed_entity_samples


def test_relative_candidate_path_uses_app_root(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setenv("SHIELD_ACTION_MODEL_PATH", "outputs/candidate.joblib")
    assert config.action_model_path() == (config.ROOT / "outputs/candidate.joblib").resolve()
    monkeypatch.setenv("SHIELD_ACTION_MODEL_PATH", "")
    assert config.action_model_path() == model.MODEL_PATH.resolve()


def test_switching_to_missing_candidate_never_reuses_good_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setenv("SHIELD_ACTION_MODEL_PATH", str(model.MODEL_PATH))
    monkeypatch.setattr(model, "_MODEL", None)
    baseline = model.get_model()
    assert baseline.available
    monkeypatch.setenv("SHIELD_ACTION_MODEL_PATH", str(tmp_path / "missing.joblib"))
    selected = model.get_model()
    assert selected is not baseline and not selected.available
    assert model.get_model() is selected
    segment = Segment("phone", "13812345678", 0, 11, [Span(0, 11, "13812345678", "PHONE")])
    result = decide_segment(segment, "meeting_minutes", "external_model", "student_leader", model.necessity_scorer)
    assert result.action == Action.PAUSE


def entity_row(**overrides):
    return {"text": "成绩为85分。", "entities": [{"start": 3, "end": 6, "text": "85分", "category": "GRADE"}],
            "split": "train", "human_reviewed": True, "origin_kind": "ner",
            "source_case_id": "source-1", **overrides}


@pytest.mark.parametrize("overrides", [{"split": "validation"}, {"split": "test"}, {"human_reviewed": False}])
def test_entity_augmentation_rejects_nontraining_rows(overrides):
    with pytest.raises(ValueError):
        reviewed_entity_samples([entity_row(**overrides)])


def test_entity_augmentation_preserves_group_and_marks_action_labels_weak():
    samples = reviewed_entity_samples([entity_row()])
    assert samples
    assert {row["source_case_id"] for row in samples} == {"reviewed_train:source-1"}
    assert {row["source"] for row in samples} == {"weak_rule_action_on_reviewed_train_entity"}
    assert {row["label"] for row in samples if row["task"] == "meeting_minutes"
            and row["recipient"] == "external_model"} == {"DELETE"}
    assert all("[CAT]GRADE " in row["feature"] for row in samples)


def test_entity_augmentation_rejects_misaligned_annotations():
    row = entity_row()
    row["entities"][0]["end"] = 5
    with pytest.raises(ValueError, match="offsets"):
        reviewed_entity_samples([row])


def test_isolated_views_preserve_offsets_and_include_both_contexts():
    row = {"text": "负责人张三，电话13812345678。"}
    source = Span(8, 19, "13812345678", "PHONE")
    views = list(isolated_segments(row, [source]))
    assert len(views) == 2
    for segment in views:
        span = segment.spans[0]
        assert segment.text[span.start:span.end] == source.text
    assert views[0].context == views[0].text
    assert row["text"] in views[1].context
