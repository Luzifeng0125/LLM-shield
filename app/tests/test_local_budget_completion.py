"""千元量级的会议金额只在本地泛化，并按展示权限补回。"""
import hashlib
from pathlib import Path

import pytest

from llm_shield.config import detector_mode, gliner_model_dir, recipients, use_gliner
from llm_shield.m6_transform.local_completion import (
    boundary_allows_generalized_budget,
    plan_meeting_budget,
    present_amount,
    seal_external_text,
    strip_held,
    thousand_phrase,
)
from llm_shield.m6_transform.mapping import MappingTable
from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.pipeline import run_pipeline
from llm_shield.schema import Material, ShieldRequest, Span

TEXT = "例会上郑清越认领海报，曹明川认领签到。印刷费是6400元。有人正在服用降压药。"
ASK = "整理纪要，人员和事项要能对上，印刷费交代到千元这一档即可。"
EXACT = "交给外部模型起草纪要，采购费按结算单上的金额保留。"
APP = Path(__file__).resolve().parents[1]
ACTIVE = APP / "models" / "necessity_action.joblib"
ACTIVE_SHA = "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f"


def _plan(text=TEXT, ask=ASK):
    spans = [Span(text.index("6400元"), text.index("6400元") + len("6400元"), "6400元", "BUDGET")]
    mapping = MappingTable()
    plan = plan_meeting_budget(text, spans, ask, "meeting_minutes", "session-n04", mapping)
    assert plan is not None and not plan.blocked
    return seal_external_text(plan, text, "session-n04", mapping), mapping


def test_thousand_phrase_is_local_and_not_invented():
    assert thousand_phrase("6400元") == "约六千元"
    assert thousand_phrase("若干") is None
    assert thousand_phrase("12800元") is None


def test_external_payload_has_codes_and_items_only():
    plan, mapping = _plan()
    external = plan.external_text
    assert plan.necessity_action == "GENERALIZE"
    assert plan.boundary_action == "WITHHOLD"
    assert "郑清越" not in external and "曹明川" not in external
    assert "6400" not in external and "约六千元" not in external
    assert "降压" not in external and "服用" not in external
    assert "海报" in external and "签到" in external and "印刷费" in external
    exported = " ".join(mapping.export("session-n04").values())
    assert "6400" not in exported and "约六千元" not in exported
    assert all(code in external for code in mapping.export("session-n04").values())
    assert not boundary_allows_generalized_budget("student_leader", "external_model", "meeting_minutes")


def test_authorized_display_adds_phrase_and_unauthorized_does_not():
    plan, mapping = _plan()
    teacher_allowed = boundary_allows_generalized_budget("student_leader", "viewer_teacher", "meeting_minutes")
    peer_allowed = boundary_allows_generalized_budget("student_leader", "viewer_peer", "meeting_minutes")
    public_allowed = boundary_allows_generalized_budget("student_leader", "egress_tool_public", "meeting_minutes")
    assert teacher_allowed and not peer_allowed and not public_allowed
    restored = mapping.restore_text("session-n04", plan.external_text, True)
    teacher = present_amount(restored, plan, True)
    peer = present_amount(mapping.restore_text("session-n04", plan.external_text, False), plan, False)
    public = strip_held(plan.external_text, plan)
    assert "印刷费：约六千元" in teacher and "6400" not in teacher and "郑清越" in teacher
    assert "约六千元" not in peer and "6400" not in peer and "郑清越" not in peer
    assert "约六千元" not in public and "6400" not in public
    # These egress assertions use the configured recognizer; the display assertions above use local policy.
    if use_gliner() and detector_mode() != "dictionary_test":
        directory = Path(gliner_model_dir())
        if not any((directory / name).is_file() for name in ("pytorch_model.bin", "model.safetensors")):
            pytest.skip("egress assertions require the locally supplied project GLiNER weight")
    spans = [
        Span(0, 3, "郑清越", "PERSON_NAME"),
        Span(0, 3, "曹明川", "PERSON_NAME"),
        Span(0, 5, "6400元", "BUDGET"),
    ]
    codes = set(mapping.export("session-n04").values())
    names = {key.split("::", 1)[-1] for key in mapping.export("session-n04")}
    gateway = EgressGateway(generated_pseudonyms=codes)
    external = gateway.precheck("external_model", "student_leader", plan.external_text, spans,
                                 placeholders=codes, task_key="meeting_minutes")
    shown = gateway.precheck("viewer_teacher", "student_leader", teacher, spans, names,
                             placeholders=codes, task_key="meeting_minutes")
    hidden = gateway.precheck("viewer_peer", "student_leader", peer, spans,
                              placeholders=codes, task_key="meeting_minutes")
    tool = gateway.precheck("egress_tool_public", "student_leader", public, spans,
                            placeholders=codes, task_key="meeting_minutes")
    assert external["allowed"] and shown["allowed"] and hidden["allowed"] and tool["allowed"]
    assert "BUDGET" in recipients()["external_model"]["forbidden"]


def test_unparseable_amount_does_not_count_as_success():
    text = "例会上郑清越认领海报。印刷费随后再定。"
    plan = plan_meeting_budget(text, [], ASK, "meeting_minutes", "session-bad", MappingTable())
    assert plan is not None and plan.blocked
    assert plan.external_text == ""


def test_exact_amount_request_does_not_use_local_completion(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    text = "采购例会上沈疏叶认领会场。采购费是6400元。"
    result = run_pipeline(ShieldRequest(
        "exact", "student_leader", "meeting_minutes", "external_model",
        [Material("n06", "meeting_minutes", "采购", text)], user_instruction=EXACT),
        send_model=False)
    assert result.local_completion is None
    assert result.paused


@pytest.mark.skipif(not ACTIVE.is_file(), reason="requires an available action model to reach the detector boundary")
def test_pipeline_withholds_amount_before_existing_detection_pause(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    result = run_pipeline(ShieldRequest(
        "n04", "student_leader", "meeting_minutes", "external_model",
        [Material("n04", "meeting_minutes", "例会", TEXT)], user_instruction=ASK),
        send_model=False)
    assert result.paused
    assert "未经验证" in result.pause_reason
    assert result.display_text == ""
    assert "郑清越" not in result.sanitized_text and "曹明川" not in result.sanitized_text
    assert "6400" not in result.sanitized_text and "约六千元" not in result.sanitized_text
    assert "降压" not in result.sanitized_text
    assert result.local_completion["necessity_action"] == "GENERALIZE"
    assert result.local_completion["boundary_action"] == "WITHHOLD"
    assert result.local_completion["presented"] is False


@pytest.mark.skipif(not ACTIVE.is_file(), reason="requires the locally supplied active action weight")
def test_locally_supplied_active_action_matches_frozen_digest():
    assert hashlib.sha256(ACTIVE.read_bytes()).hexdigest() == ACTIVE_SHA


def test_missing_action_weight_stops_before_budget_is_disclosed(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    monkeypatch.setenv("SHIELD_ACTION_MODEL_PATH", str(tmp_path / "absent.joblib"))
    result = run_pipeline(ShieldRequest(
        "missing-action", "student_leader", "meeting_minutes", "external_model",
        [Material("n04", "meeting_minutes", "例会", TEXT)], user_instruction=ASK),
        send_model=False)
    assert result.paused and "本地决策模型不可用" in result.pause_reason
    assert not result.display_text
    assert "6400" not in result.sanitized_text and "约六千元" not in result.sanitized_text
