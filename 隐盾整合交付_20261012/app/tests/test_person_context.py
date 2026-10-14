import pytest

from llm_shield.m2_detect.entity_rules import EntityDetector


@pytest.mark.parametrize('text,names', [
    ('负责人：张明，周五前完成海报。', ['张明']),
    ('负责人张明，完成策划；联系人：李晓华。', ['张明', '李晓华']),
    ('参会人员：张明、李晓华、欧阳修。周五提交。', ['张明', '李晓华', '欧阳修']),
    ('由张明同学负责海报，李晓华老师指导。', ['张明', '李晓华']),
    ('姓名：成海报。', ['成海报']),
    ('张明（负责人），联系人为李晓华。', ['张明', '李晓华']),
    ('负责人：张明。张明需要在周五前完成海报。', ['张明', '张明']),
    ('负责人：张明，周五，完成海报。', ['张明']),
    ('本周五前完成海报，负责人尚未确定。', []),
])
def test_name_is_bound_to_title_and_offsets_cover_only_name(text, names):
    spans = sorted(EntityDetector()._detect_person(text), key=lambda s: s.start)
    assert [s.text for s in spans] == names
    assert all(text[s.start:s.end] == s.text for s in spans)


def test_column_detection_still_covers_names_outside_dictionary():
    text = '姓名\n阿布都'
    spans = EntityDetector().detect(text, ['姓名'], [{'姓名': '阿布都'}])
    assert any(s.text == '阿布都' and s.category == 'PERSON_NAME' for s in spans)
