"""外发边界回归测试：仅使用虚构材料及本地替身，不调用外部 API。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.m3_decide.constraints import check_hard
from llm_shield.m7_egress import gateway
from llm_shield.m8_audit import observer
from llm_shield.m8_audit.audit import Auditor
from llm_shield.schema import Action, Segment, Span


class EgressSafetyTests(unittest.TestCase):
    def setUp(self):
        self.gateway = gateway.EgressGateway(Auditor())
        self.ner = patch("llm_shield.config.use_campus_ner", return_value=False)
        self.ner.start()
        self.addCleanup(self.ner.stop)

    def test_retained_value_is_rechecked_for_each_recipient(self):
        # 模型输出中不再有“姓名：”上下文，复扫识别不到姓名也不能靠白名单出站。
        span = Span(0, 3, "李晓华", "PERSON_NAME")
        with patch.object(observer, "detect_all", return_value=[]):
            teacher = self.gateway.send_to_viewer(
                "viewer_teacher", span.text, "student_leader", [span], {span.text},
                task_key="meeting_minutes")
            external = self.gateway.precheck(
                "external_model", "student_leader", span.text, [span], {span.text},
                task_key="meeting_minutes")
            public = self.gateway.send_to_tool(
                "egress_tool_public", span.text, "student_leader", [span], {span.text},
                write_file=False, task_key="meeting_minutes")
        self.assertTrue(teacher["allowed"])
        self.assertFalse(external["allowed"])
        self.assertFalse(public["allowed"])
        self.assertIn("PERSON_NAME", public["record"].leaked_categories)
        self.assertEqual(public["text"], "")

    def test_whitelist_cannot_override_task_absolute_ban_or_identity_level(self):
        cases = [
            ("budget", "BUDGET", "project_intro", "student_leader"),
            ("credential", "API_KEY", "meeting_minutes", "student_leader"),
            ("score", "GRADE", "meeting_minutes", "course_member"),
        ]
        with patch.object(observer, "detect_all", return_value=[]):
            for value, category, task, identity in cases:
                with self.subTest(category=category):
                    span = Span(0, len(value), value, category)
                    recipient = "viewer_peer" if identity == "course_member" else "viewer_teacher"
                    result = self.gateway.precheck(
                        recipient, identity, value, [span], {value}, task_key=task)
                    self.assertFalse(result["allowed"])
                    self.assertIn(category, result["inspect"]["leaked_categories"])

    def test_same_value_with_two_categories_keeps_stricter_category(self):
        spans = [Span(0, 5, "value", "LOCATION"), Span(0, 5, "value", "API_KEY")]
        with patch.object(observer, "detect_all", return_value=[]):
            result = observer.inspect_payload(
                "value", "viewer_teacher", spans, {"value"},
                task_key="meeting_minutes", identity_key="student_leader")
        self.assertIn("API_KEY", result["leaked_categories"])

    def test_fresh_output_uses_task_and_absolute_restrictions(self):
        for text, task, category in [
            ("联系邮箱 demo@example.com", "meeting_minutes", "EMAIL"),
            ("政治面貌：中共党员", "meeting_minutes", "SENSITIVE_ATTR"),
            ("预算1万~2万元", "project_intro", "BUDGET"),
        ]:
            with self.subTest(category=category):
                result = self.gateway.precheck(
                    "viewer_teacher", "student_leader", text, task_key=task)
                self.assertFalse(result["allowed"])
                self.assertIn(category, result["inspect"]["leaked_categories"])

    def test_clean_payload_and_pseudonym_are_allowed(self):
        result = self.gateway.send_to_model
        with patch.object(gateway, "chat_with_fallback", return_value={
            "text": "处理成功", "engine": "mock", "error": ""
        }) as call:
            sent = result("meeting_minutes", "人员甲负责整理纪要。", "student_leader")
        self.assertTrue(sent["allowed"])
        call.assert_called_once()

    def test_unknown_missing_and_metadata_task_are_denied(self):
        for task in (None, "unknown_task", "version"):
            with self.subTest(task=task):
                result = self.gateway.precheck(
                    "external_model", "student_leader", "公开资料", task_key=task)
                self.assertFalse(result["allowed"])
        for recipient in ("unknown_recipient", "version"):
            with self.subTest(recipient=recipient):
                result = self.gateway.send_to_viewer(
                    recipient, "公开资料", "student_leader", task_key="activity_stats")
                self.assertFalse(result["allowed"])

    def test_wrong_boundary_recipient_type_is_denied(self):
        result = self.gateway.send_to_tool(
            "viewer_teacher", "公开资料", "student_leader", write_file=False,
            task_key="activity_stats")
        self.assertFalse(result["allowed"])

    def test_model_checks_complete_messages_before_sending_same_content(self):
        body = "公开资料"
        with patch.object(gateway, "inspect_payload", wraps=observer.inspect_payload) as inspect:
            with patch.object(gateway, "chat_with_fallback", return_value={
                "text": "处理成功", "engine": "mock", "error": ""
            }) as send:
                result = self.gateway.send_to_model("activity_stats", body, "student_leader")
        system, user = send.call_args.args
        self.assertEqual(user, body)
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(inspect.call_args.args[0], f"{system}\n\n{user}")
        self.assertEqual(result["record"].payload, inspect.call_args.args[0])

    def test_unsafe_system_message_is_blocked_before_model_call(self):
        with patch.dict(gateway.SYSTEM_PROMPTS, {"activity_stats": "联系电话13812345678"}):
            with patch.object(gateway, "chat_with_fallback") as send:
                result = self.gateway.send_to_model("activity_stats", "公开资料", "student_leader")
        self.assertFalse(result["allowed"])
        self.assertIn("PHONE", result["record"].leaked_categories)
        send.assert_not_called()

    def test_model_error_text_is_not_released(self):
        with patch.object(gateway, "chat_with_fallback", return_value={
            "text": "[错误]", "engine": "error", "error": "unavailable"
        }):
            result = self.gateway.send_to_model("activity_stats", "公开资料", "student_leader")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["text"], "")

    def test_hard_validation_rejects_low_trust_raw_names_and_unknown_context(self):
        span = Span(0, 3, "李晓华", "PERSON_NAME")
        segment = Segment("s1", span.text, 0, 3, [span])
        checks = check_hard(Action.RETAIN, segment, "meeting_minutes",
                            "external_model", "student_leader")
        self.assertFalse(all(check.passed for check in checks))
        self.assertTrue(any(check.rule == "LOW_TRUST_IDENTIFIERS" and not check.passed
                            for check in checks))
        for task, recipient, identity in [
            ("missing", "external_model", "student_leader"),
            ("version", "external_model", "student_leader"),
            ("meeting_minutes", "version", "student_leader"),
            ("meeting_minutes", "external_model", "version"),
            ("meeting_minutes", "viewer_teacher", "external_partner"),
        ]:
            with self.subTest(task=task, recipient=recipient, identity=identity):
                checks = check_hard(Action.DELETE, segment, task, recipient, identity)
                self.assertFalse(all(check.passed for check in checks))


if __name__ == "__main__":
    unittest.main()
