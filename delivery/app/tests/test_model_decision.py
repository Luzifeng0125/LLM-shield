"""模型确实控制动作、异常暂停及新版权重兼容性的回归测试。"""
from __future__ import annotations
from llm_shield.m4_necessity.model import (
    FEATURE_SPLIT, FEATURE_VERSION, MODEL_PATH, ModelUnavailableError, NecessityModel,
    build_feature_text, build_feature_text_v4, build_feature_text_v5, split_feature_v4, split_feature_v5,
)
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import MODEL_PATH, ModelUnavailableError, NecessityModel, build_feature_text
from llm_shield.schema import Action, Segment, Span

def name_segment():
    return Segment('s', '负责人：张明负责提交报告。', 0, 14, [Span(4, 6, '张明', 'PERSON_NAME')], context='前文要求保留负责人和事项的对应关系。')

class ModelDecisionTests(unittest.TestCase):

    def decide(self, scores, segment=None, **kwargs):
        return decide_segment(segment or name_segment(), 'meeting_minutes', 'external_model', 'student_leader', lambda *args: scores, **kwargs)

    def test_model_changes_action_even_when_rule_cost_prefers_delete(self):
        removed = self.decide({'DELETE': 0.9, 'PSEUDONYMIZE': 0.1})
        replaced = self.decide({'DELETE': 0.1, 'PSEUDONYMIZE': 0.9})
        self.assertEqual(removed.action, Action.DELETE)
        self.assertEqual(replaced.action, Action.PSEUDONYMIZE)

    def test_unsafe_winner_pauses_instead_of_selecting_safe_runner_up(self):
        segment = Segment('p', '13812345678', 0, 11, [Span(0, 11, '13812345678', 'PHONE')])
        result = self.decide({'RETAIN': 0.9, 'DELETE': 0.1}, segment)
        self.assertEqual(result.action, Action.PAUSE)
        self.assertIn('RETAIN', result.reason)
        self.assertTrue(any((not check.passed for check in result.hard_checks)))

    def test_inapplicable_model_action_pauses(self):
        segment = Segment('p', '13812345678', 0, 11, [Span(0, 11, '13812345678', 'PHONE')])
        self.assertEqual(self.decide({'PSEUDONYMIZE': 1.0}, segment).action, Action.PAUSE)

    def test_invalid_predictions_pause(self):
        for scores in (None, {}, {'OTHER': 1.0}, {'DELETE': float('nan')}, {'DELETE': float('inf')}, {'DELETE': -1.0}, {'DELETE': 1.1}, {'DELETE': True}, {'DELETE': '1'}, {'DELETE': 0.1}, {'DELETE': 0.5, 'RETAIN': 0.5}):
            with self.subTest(scores=scores):
                self.assertEqual(self.decide(scores).action, Action.PAUSE)

    def test_model_may_choose_pause(self):
        self.assertEqual(self.decide({'PAUSE': 1.0}).action, Action.PAUSE)

    def test_no_model_pauses_sensitive_segments(self):
        result = decide_segment(name_segment(), 'meeting_minutes', 'external_model', 'student_leader')
        self.assertEqual(result.action, Action.PAUSE)

    def test_plain_text_does_not_require_model(self):
        result = decide_segment(Segment('public', '欢迎参加公开讲座。', 0, 10), 'meeting_minutes', 'external_model', 'student_leader')
        self.assertEqual(result.action, Action.RETAIN)

    def test_model_exception_is_not_retried_or_exposed(self):
        called = []

        def failing(*args, **kwargs):
            called.append(1)
            raise TypeError('private material 13812345678')
        result = decide_segment(name_segment(), 'meeting_minutes', 'external_model', 'student_leader', failing)
        self.assertEqual(called, [1])
        self.assertEqual(result.action, Action.PAUSE)
        self.assertNotIn('13812345678', result.reason)

    def test_task_context_and_identity_reach_model(self):
        captured = {}

        def scorer(segment, task, recipient, **kwargs):
            captured.update(kwargs)
            return {'DELETE': 1.0}
        result = decide_segment(name_segment(), 'meeting_minutes', 'external_model', 'student_leader', scorer, task_description='删除全部人名', context='补充上下文')
        self.assertEqual(result.action, Action.DELETE)
        self.assertEqual(captured, {'task_description': '删除全部人名', 'context': '补充上下文', 'identity_key': 'student_leader'})

    def test_features_include_full_segment_task_and_context(self):
        segment = name_segment()
        segment.text = '公开信息' * 50 + '末尾的重要实体'
        feature = build_feature_text(segment, 'meeting_minutes', 'external_model', task_description='自定义任务', identity_key='student_leader')
        for expected in ('自定义任务', '末尾的重要实体', segment.context, '[IDENTITY]student_leader', '[SCHEMA]3'):
            self.assertIn(expected, feature)

    def test_unknown_entity_category_pauses(self):
        segment = name_segment()
        segment.spans[0].category = 'UNKNOWN_SECRET'
        self.assertEqual(self.decide({'RETAIN': 1.0}, segment).action, Action.PAUSE)

class ModelArtifactTests(unittest.TestCase):

    def test_missing_weights_never_fall_back_to_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            model = NecessityModel(Path(directory) / 'missing.joblib')
            self.assertFalse(model.available)
            self.assertEqual(model.backend, 'unavailable')
            with self.assertRaises(ModelUnavailableError):
                model.score(name_segment(), 'meeting_minutes', 'external_model')
        self.assertEqual(MODEL_PATH.name, 'necessity_action.joblib')

    def test_legacy_artifact_rejected(self):
        import joblib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.joblib'
            joblib.dump({'pipeline': 'legacy'}, path)
            self.assertFalse(NecessityModel(path).available)

    def test_grouped_training_artifact_roundtrip(self):
        samples = []
        for document in range(8):
            for label in ('DELETE', 'PSEUDONYMIZE'):
                for variant in range(2):
                    segment = name_segment()
                    segment.text = f'来源 {document} 的 {label} 示例 {variant}'
                    samples.append({'feature': build_feature_text(segment, 'meeting_minutes', 'external_model'), 'label': label, 'case_id': f'case-{document}', 'source': 'test'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'action.joblib'
            model = NecessityModel(path)
            result = model.train(samples)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['validation']['group_overlap'], 0)
            self.assertEqual(result['validation']['train_groups'] + result['validation']['validation_groups'], 8)
            loaded = NecessityModel(path)
            self.assertTrue(loaded.available, loaded.reason)
            probabilities = loaded.score(name_segment(), 'meeting_minutes', 'external_model')
            self.assertAlmostEqual(sum(probabilities.values()), 1.0)

    def test_reject_legacy_features(self):
        samples = [{'feature': '[CAT]PERSON_NAME [TEXT]person', 'label': 'DELETE', 'case_id': str(i)} for i in range(20)]
        with tempfile.TemporaryDirectory() as directory:
            result = NecessityModel(Path(directory) / 'unused.joblib').train(samples)
            self.assertFalse(result['ok'])
            self.assertIn('旧版特征', result['reason'])


class TaskDemandFeatureTests(unittest.TestCase):

    def test_same_amount_three_demands_change_only_the_demand_channel(self):
        text = '费用是8600元。'
        segment = Segment('b', text, 0, len(text), [Span(0, len(text), text, 'BUDGET')])
        asks = ('这笔开支按核准数额保留。', '这笔开支只说明量级。', '这笔开支不要写。')
        built = [build_feature_text_v4(segment, 'meeting_minutes', 'external_model', task_description=ask, identity_key='student_leader') for ask in asks]
        parts = [split_feature_v4(feature) for feature in built]
        self.assertEqual(len({item[0] for item in parts}), 1)
        self.assertEqual(len({item[1] for item in parts}), 3)
        self.assertEqual(len({item[2] for item in parts}), 1)
        structured = parts[0][0]
        for token in ('[SCHEMA]4', '[BOUNDARY]external_generation', '[RECIPIENT]external_model', '[SEND]1', '[RESTORE]0', '[BANNED]1'):
            self.assertIn(token, structured)
        old = [build_feature_text(segment, 'meeting_minutes', 'external_model', task_description=ask, identity_key='student_leader') for ask in asks]
        self.assertEqual(len({item.partition(FEATURE_SPLIT)[0] for item in old}), 1)
        self.assertNotIn('[BOUNDARY]', old[0])
        self.assertTrue(old[0].startswith(f'[SCHEMA]{FEATURE_VERSION} '))

    def test_v5_keeps_raw_task_text_distinct_from_span(self):
        text = '费用是8600元。'
        segment = Segment('b', text, 0, len(text), [Span(0, len(text), text, 'BUDGET')])
        asks = ('花费按精确原样留下。', '费用给一个大概范围。', '不要把金额写进去。')
        parts = [split_feature_v5(build_feature_text_v5(
            segment, 'meeting_minutes', 'viewer_teacher', task_description=ask, identity_key='student_leader')) for ask in asks]
        self.assertEqual(len({item[0] for item in parts}), 1)
        self.assertEqual(len({item[1] for item in parts}), 3)
        self.assertEqual(len({item[2] for item in parts}), 3)
        self.assertTrue(all(text in item[3] for item in parts))
        self.assertIn('[SCHEMA]5', parts[0][0])
        self.assertIn('精确', parts[0][1])
        name = Segment('n', '赵启明负责签到。', 0, 8, [Span(0, 3, '赵启明', 'PERSON_NAME')])
        budget_cross = parts[0][2]
        name_cross = split_feature_v5(build_feature_text_v5(
            name, 'meeting_minutes', 'viewer_teacher', task_description=asks[0], identity_key='student_leader'))[2]
        self.assertNotEqual(budget_cross, name_cross)

if __name__ == '__main__':
    unittest.main()
