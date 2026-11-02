"""姓名识别回归：真实姓名、普通动词、标点和上下文歧义。

不把某三个词写成特例。用例只检查姓氏、称谓、发言冒号和停用词这些通用规则。
"""
from llm_shield.m2_detect.entity_rules import EntityDetector

DUTY = (
    "班级事务群，周日晚上。\n\n"
    "林知夏：本周值日我按教室排了。周一教学楼A201，周晚宁擦黑板并检查门窗；"
    "周三同一间教室，陈予安负责关门、断电和归还钥匙。\n\n"
    "周晚宁：周三我有实验，可能提前走。到时候打电话13800001001。\n\n"
    "陈予安：钥匙在我书包侧袋。邮箱是chenyuan@example.edu，人没到就发邮件。\n"
)


def names(text):
    return [span.text for span in EntityDetector().detect(text) if span.category == "PERSON_NAME"]


def test_duty_notice_names_are_found_and_the_verb_is_not():
    found = names(DUTY)
    assert "林知夏" in found
    assert "周晚宁" in found
    assert "陈予安" in found
    assert "关门" not in found
    assert "周一" not in found
    assert "周日" not in found


def test_real_names_with_punctuation_and_titles():
    text = "请通知周晚宁，并抄送陈予安。负责人林知夏同学确认后发出。"
    found = names(text)
    assert found.count("周晚宁") >= 1
    assert "陈予安" in found
    assert "林知夏" in found


def test_ordinary_verbs_after_duty_words_are_not_names():
    text = "陈予安负责关门、开门和关灯，周晚宁负责检查门窗。"
    found = names(text)
    assert "陈予安" in found and "周晚宁" in found
    for word in ("关门", "开门", "关灯", "检查"):
        assert word not in found


def test_context_ambiguity_keeps_weekdays_and_common_words():
    text = "周一开会讨论关于宿舍的问题。负责人尚未确定。明天再说。"
    found = names(text)
    assert found == []
