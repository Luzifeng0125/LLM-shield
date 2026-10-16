"""模型确实控制动作、异常暂停及新版权重兼容性的回归测试。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import (
    MODEL_PATH, ModelUnavailableError, NecessityModel, build_feature_text,
)
from llm_shield.schema import Action, Segment, Span


def name_segment():
    return Segment("s", "负责人：张明负责提交报告。", 0, 14,
                   [Span(4, 6, "张明", "PERSON_NAME")],
                   context="前文要求保留负责人和事项的对应关系。")


class ModelDecisionTests(unittest.TestCase):
    def decide(self, scores, segment=None, **kwargs):
        return decide_segment(segment or name_segment(), "meeting_minutes",
                              "external_model", "student_leader",
                              lambda *args: scores, **kwargs)

    def test_model_changes_action_even_when_rule_cost_prefers_delete(self):
        removed = self.decide({"DELETE": 0.9, "PSEUDONYMIZE": 0.1})
        replaced = self.decide({"DELETE": 0.1, "PSEUDONYMIZE": 0.9})
        self.assertEqual(removed.action, Action.DELETE)
        self.assertEqual(replaced.action, Action.PSEUDONYMIZE)

    def test_unsafe_winner_pauses_instead_of_selecting_safe_runner_up(self):
        segment = Segment("p", "13812345678", 0, 11,
                          [Span(0, 11, "13812345678", "PHONE")])
        result = self.decide({"RETAIN": 0.9, "DELETE": 0.1}, segment)
        self.assertEqual(result.action, Action.PAUSE)
        self.assertIn("RETAIN", result.reason)
        self.assertTrue(any(not check.passed for check in result.hard_checks))

    def test_inapplicable_model_action_pauses(self):
        segment = Segment("p", "13812345678", 0, 11,
                          [Span(0, 11, "13812345678", "PHONE")])
        self.assertEqual(self.decide({"PSEUDONYMIZE": 1.0}, segment).action, Action.PAUSE)

    def test_invalid_predictions_pause(self):
        for scores in (None, {}, {"OTHER": 1.0}, {"DELETE": float("nan")},
                       {"DELETE": float("inf")}, {"DELETE": -1.0},
                       {"DELETE": 1.1}, {"DELETE": True}, {"DELETE": "1"},
                       {"DELETE": 0.1}, {"DELETE": 0.5, "RETAIN": 0.5}):
            with self.subTest(scores=scores):
                self.assertEqual(self.decide(scores).action, Action.PAUSE)

    def test_model_may_choose_pause(self):
        self.assertEqual(self.decide({"PAUSE": 1.0}).action, Action.PAUSE)

    def test_no_model_pauses_sensitive_segments(self):
        result = decide_segment(name_segment(), "meeting_minutes",
                                "external_model", "student_leader")
        self.assertEqual(result.action, Action.PAUSE)

    def test_plain_text_does_not_require_model(self):
        result = decide_segment(Segment("public", "欢迎参加公开讲座。", 0, 10),
                                "meeting_minutes", "external_model", "student_leader")
        self.assertEqual(result.action, Action.RETAIN)

    def test_model_exception_is_not_retried_or_exposed(self):
        called = []
        def failing(*args, **kwargs):
            called.append(1)
            raise TypeError("private material 13812345678")
        result = decide_segment(name_segment(), "meeting_minutes", "external_model",
                                "student_leader", failing)
        self.assertEqual(called, [1])
        self.assertEqual(result.action, Action.PAUSE)
        self.assertNotIn("13812345678", result.reason)

    def test_task_context_and_identity_reach_model(self):
        captured = {}
        def scorer(segment, task, recipient, **kwargs):
            captured.update(kwargs)
            return {"DELETE": 1.0}
        result = decide_segment(name_segment(), "meeting_minutes", "external_model",
                                "student_leader", scorer,
                                task_description="删除全部人名", context="补充上下文")
        self.assertEqual(result.action, Action.DELETE)
        self.assertEqual(captured, {"task_description": "删除全部人名",
                                    "context": "补充上下文", "identity_key": "student_leader"})

    def test_features_include_full_segment_task_and_context(self):
        segment = name_segment()
        segment.text = "公开信息" * 50 + "末尾的重要实体"
        feature = build_feature_text(segment, "meeting_minutes", "external_model",
                                     task_description="自定义任务", identity_key="student_leader")
        for expected in ("自定义任务", "末尾的重要实体", segment.context,
                         "[IDENTITY]student_leader", "[SCHEMA]2"):
            self.assertIn(expected, feature)

    def test_unknown_entity_category_pauses(self):
        segment = name_segment()
        segment.spans[0].category = "UNKNOWN_SECRET"
        self.assertEqual(self.decide({"RETAIN": 1.0}, segment).action, Action.PAUSE)


class ModelArtifactTests(unittest.TestCase):
    def test_missing_weights_never_fall_back_to_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            model = NecessityModel(Path(directory) / "missing.joblib")
            self.assertFalse(model.available)
            self.assertEqual(model.backend, "unavailable")
            with self.assertRaises(ModelUnavailableError):
                model.score(name_segment(), "meeting_minutes", "external_model")
        self.assertEqual(MODEL_PATH.name, "necessity_action.joblib")

    def test_legacy_artifact_rejected(self):
        import joblib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.joblib"
            joblib.dump({"pipeline": "legacy"}, path)
            self.assertFalse(NecessityModel(path).available)

    def test_grouped_training_artifact_roundtrip(self):
        samples = []
        for document in range(8):
            for label in ("DELETE", "PSEUDONYMIZE"):
                for variant in range(2):
                    segment = name_segment()
                    segment.text = f"来源 {document} 的 {label} 示例 {variant}"
                    samples.append({"feature": build_feature_text(segment, "meeting_minutes", "external_model"),
                                    "label": label, "case_id": f"case-{document}", "source": "test"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "action.joblib"
            model = NecessityModel(path)
            result = model.train(samples)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["validation"]["group_overlap"], 0)
            self.assertEqual(result["validation"]["train_groups"] +
                             result["validation"]["validation_groups"], 8)
            loaded = NecessityModel(path)
            self.assertTrue(loaded.available, loaded.reason)
            probabilities = loaded.score(name_segment(), "meeting_minutes", "external_model")
            self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_reject_legacy_features(self):
        samples = [{"feature": "[CAT]PERSON_NAME [TEXT]person", "label": "DELETE",
                    "case_id": str(i)} for i in range(20)]
        with tempfile.TemporaryDirectory() as directory:
            result = NecessityModel(Path(directory) / "unused.joblib").train(samples)
            self.assertFalse(result["ok"])
            self.assertIn("旧版特征", result["reason"])


if __name__ == "__main__":
    unittest.main()
