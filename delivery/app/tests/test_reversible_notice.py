"""联系通知：姓名和电话换成占位符，授权后才恢复。"""
from llm_shield.m1_access.identity import can_restore
from llm_shield.m2_detect.pipeline import build_detectors, detect_all
from llm_shield.m6_transform.mapping import MappingTable
from llm_shield.m6_transform.reversible import assess_reply, mask_necessary, restore_reply
from llm_shield.pipeline import run_pipeline
from llm_shield.schema import Material, ShieldRequest

NOTICE = "负责人林知夏，电话13800001001。"
MOCK = "【本地模拟，未调用云端】如有问题，请联系[PERSON_1]，电话[CONTACT_1]。"


def _mask(text):
    spans = detect_all(text, detectors=build_detectors(use_gliner=False))
    table = MappingTable()
    masked, issued = mask_necessary(text, spans, "notice", table, ("PERSON_NAME", "PHONE"))
    return table, masked, issued, spans


def test_cloud_payload_hides_name_and_phone_but_not_every_field():
    table, masked, issued, spans = _mask(NOTICE + "邮箱lin@example.edu。")
    assert issued == ["[PERSON_1]", "[CONTACT_1]"]
    assert "林知夏" not in masked and "13800001001" not in masked
    assert "lin@example.edu" not in masked and "[MAIL_" not in masked
    assert "[PERSON_1]" in masked and "[CONTACT_1]" in masked
    assert "负责人" in masked
    assert all(span.category != "PHONE" or span.text == "13800001001" for span in spans)
    again, _issued2 = mask_necessary(NOTICE, spans[:], "notice", table, ("PERSON_NAME", "PHONE"))
    assert "[PERSON_2]" not in again and again.count("[PERSON_1]") >= 1


def test_authorized_restore_and_unauthorized_restore():
    table, _masked, issued, _spans = _mask(NOTICE)
    raw = ["林知夏", "13800001001"]
    teacher, teacher_check = restore_reply(
        table, "notice", MOCK, allowed=can_restore("student_leader", "viewer_teacher"),
        issued=issued, raw_values=raw,
    )
    peer, peer_check = restore_reply(
        table, "notice", MOCK, allowed=can_restore("student_leader", "viewer_peer"),
        issued=issued, raw_values=raw,
    )
    assert teacher_check["ok"] is True
    assert "林知夏" in teacher and "13800001001" in teacher
    assert "[PERSON_1]" not in teacher and "[CONTACT_1]" not in teacher
    assert "本地模拟" in teacher
    assert peer_check["ok"] is True
    assert peer == MOCK
    assert "林知夏" not in peer and "13800001001" not in peer


def test_damaged_or_reordered_placeholder_is_not_restored():
    table, _masked, issued, _spans = _mask(NOTICE)
    raw = ["林知夏", "13800001001"]
    damaged = "【本地模拟，未调用云端】如有问题，请联系[PERSON_1，电话[CONTACT_1]。"
    swapped = "【本地模拟，未调用云端】电话[CONTACT_1]，联系[PERSON_1]。"
    leaked = "【本地模拟，未调用云端】请联系林知夏，电话[CONTACT_1]。"
    missing = "【本地模拟，未调用云端】如有问题，请联系[PERSON_1]。"
    for reply in (damaged, swapped, leaked):
        text, check = restore_reply(
            table, "notice", reply, allowed=True, issued=issued, raw_values=raw,
        )
        assert check["ok"] is False
        assert text == reply
        assert "13800001001" not in text or reply == leaked
    kept, check = restore_reply(
        table, "notice", missing, allowed=True, issued=issued, raw_values=raw,
    )
    assert check["ok"] is True
    assert "林知夏" in kept and "13800001001" not in kept


def test_pipeline_contact_notice_pauses_before_cloud(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    result = run_pipeline(ShieldRequest(
        "notice-1", "student_leader", "contact_notice", "external_model",
        [Material("n1", "uploaded", "通知", NOTICE)],
        "整理成通知，保留负责人和电话。",
    ))
    assert result.paused is True
    assert result.model_output == ""
    assert result.decision_lane == "reversible_notice"
    assert "未调用云端" in result.pause_reason
    assert "林知夏" not in result.sanitized_text
    assert "13800001001" not in result.sanitized_text
    assert "[PERSON_1]" in result.sanitized_text and "[CONTACT_1]" in result.sanitized_text
    assert result.mapping_table["林知夏"] == "[PERSON_1]"
    assert result.mapping_table["13800001001"] == "[CONTACT_1]"


def test_duty_phone_is_not_given_a_contact_token(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "dictionary_test")
    duty = "周晚宁：到时候打电话13800001001。"
    result = run_pipeline(ShieldRequest(
        "duty-phone", "student_leader", "class_coordination", "external_model",
        [Material("d", "uploaded", "值日", duty)],
        "整理值日分组。",
    ))
    assert "[CONTACT_" not in result.sanitized_text
    assert "13800001001" not in result.sanitized_text


def test_default_entry_still_pauses_without_gliner(monkeypatch):
    monkeypatch.setenv("SHIELD_DETECTOR_MODE", "gliner")
    monkeypatch.setenv("SHIELD_USE_GLINER", "true")
    from llm_shield.m2_detect.gliner_ner import GLiNERDetector
    if GLiNERDetector().available:
        return
    result = run_pipeline(ShieldRequest(
        "notice-gliner", "student_leader", "contact_notice", "external_model",
        [Material("n2", "uploaded", "通知", NOTICE)],
    ))
    assert result.paused is True
    assert "GLiNER" in result.pause_reason
    assert result.sanitized_text == ""
    assert result.model_output == ""
