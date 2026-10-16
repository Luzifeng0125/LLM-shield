"""Generated codes may suppress only their own category false positives."""
import pytest

from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.m8_audit import observer
from llm_shield.schema import Span


def inspect(payload, originals=None, codes=None):
    return observer.inspect_payload(payload, "external_model", originals or [],
                                    task_key="meeting_minutes", identity_key="student_leader",
                                    generated_pseudonyms=codes)


def test_only_current_session_generated_code_suppresses_false_positive(monkeypatch):
    monkeypatch.setattr(observer, "detect_all", lambda text: [Span(2, 3, "丁", "PERSON_NAME")])
    assert inspect("人员丁负责记录。", codes={"人员丁"})["leaked"] is False
    assert inspect("人员丁负责记录。")["leaked"] is True
    assert inspect("人员丁负责记录。", codes={"人员甲"})["leaked"] is True


def test_generated_code_never_suppresses_original_value_match(monkeypatch):
    monkeypatch.setattr(observer, "detect_all", lambda text: [Span(0, 3, "人员丁", "PERSON_NAME")])
    original = Span(0, 3, "人员丁", "PERSON_NAME")
    report = inspect("人员丁负责记录。", [original], {"人员丁"})
    assert report["leaked"] and report["leak_hits"][0]["type"] == "VALUE"


@pytest.mark.parametrize("payload,span,codes", [
    ("人员丁张三", Span(3, 5, "张三", "PERSON_NAME"), {"人员丁"}),
    ("人员丁张三", Span(2, 5, "丁张三", "PERSON_NAME"), {"人员丁"}),
    ("人员11", Span(2, 3, "1", "PERSON_NAME"), {"人员1"}),
    ("人员甲乙", Span(2, 3, "甲", "PERSON_NAME"), {"人员甲"}),
    ("人员13812345678", Span(2, 13, "13812345678", "PHONE"), {"人员13812345678"}),
    ("张三", Span(0, 2, "张三", "PERSON_NAME"), {"张三"}),
])
def test_adjacent_extended_wrong_category_and_noncode_values_remain_blocked(monkeypatch, payload, span, codes):
    monkeypatch.setattr(observer, "detect_all", lambda text: [span])
    assert inspect(payload, codes=codes)["leaked"]


def test_gateway_keeps_its_own_copy_of_current_session_codes(monkeypatch):
    codes = {"人员丁"}
    gateway = EgressGateway(generated_pseudonyms=codes)
    codes.add("人员甲")
    monkeypatch.setattr(observer, "detect_all", lambda text: [Span(2, 3, text[2], "PERSON_NAME")])
    assert gateway.precheck("external_model", "student_leader", "人员丁负责记录。",
                            task_key="meeting_minutes")["allowed"]
    assert not gateway.precheck("external_model", "student_leader", "人员甲负责记录。",
                                task_key="meeting_minutes")["allowed"]
