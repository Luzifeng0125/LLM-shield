"""Whole email tokens must not be relabelled as numeric fragments."""
from llm_shield.m2_detect.pipeline import detect_all, merge_spans
from llm_shield.m2_detect.regex_rules import RegexDetector
from llm_shield.schema import Span


def test_numeric_email_local_parts_keep_complete_email_category():
    text = "邮箱13800001111@example.test；邮箱2026123456@example.test。"
    found = detect_all(text, detectors=[RegexDetector()])
    assert [(span.category, span.text) for span in found] == [
        ("EMAIL", "13800001111@example.test"), ("EMAIL", "2026123456@example.test")]


def test_model_fragment_does_not_override_email_or_hide_adjacent_phone():
    text = "123456789@qq.example 电话13800001111"
    email_end = text.index(" ")
    start = text.index("13800001111")
    spans = [Span(0, email_end, text[:email_end], "EMAIL", .97, "regex"),
             Span(0, 8, text[:8], "PHONE", .99, "reviewed_ner"),
             Span(start, len(text), text[start:], "PHONE", .98, "regex")]
    merged = merge_spans(spans, text)
    assert [(span.category, span.start, span.end) for span in merged] == [
        ("EMAIL", 0, email_end), ("PHONE", start, len(text))]
    assert spans[1].category == "PHONE"  # Inputs stay unchanged.


def test_secret_detection_and_spans_crossing_email_boundary_are_preserved():
    text = "0123456789@example.testABC"
    email = Span(0, 22, text[:22], "EMAIL", .97, "regex")
    secret = Span(0, 10, text[:10], "API_KEY", .99, "reviewed_ner")
    merged = merge_spans([email, secret], text)
    assert merged[0].category == "API_KEY" and merged[0].end == email.end
    crossing = Span(20, len(text), text[20:], "PHONE", .99, "reviewed_ner")
    merged = merge_spans([email, crossing], text)
    assert merged[0].start == 0 and merged[0].end == len(text)
