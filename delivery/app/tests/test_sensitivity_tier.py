"""敏感度分级回归测试。

产品口径：**公开机构名（ORG）是最低档敏感数据**——仍然识别，但泄露代价低于姓名，
因此对低信任接收方放宽；而姓名（PERSON_NAME）在同场景必须继续被拦住。

这条口径落在 config/rules.yaml 的 `categories.*.level` 上，
由 m3_decide 的「身份 max_level ∩ 接收方 max_level」判定消费。
一旦有人把 ORG 的 level 调回去（或把 LOCATION 调得更低），这里的用例会失败。
"""
import pytest

from llm_shield.config import category_level, category_meta
from llm_shield.m2_detect.pipeline import detect_and_segment
from llm_shield.m3_decide.constraints import check_hard
from llm_shield.schema import Action

# 公开发布端：max_level = 1，是配置里最严格的接收方
STRICT_RECIPIENT = 'egress_tool_public'
IDENTITY = 'student_leader'
TASK = 'project_intro'


def _verdicts(text, recipient=STRICT_RECIPIENT):
    """返回 {动作: (是否通过, 未通过原因)}。"""
    _spans, segs = detect_and_segment(text)
    out = {}
    for seg in segs:
        if not seg.spans:
            continue
        for act in (Action.RETAIN, Action.GENERALIZE, Action.PSEUDONYMIZE):
            checks = check_hard(act, seg, TASK, recipient, IDENTITY)
            failed = [c.detail for c in checks if not c.passed]
            out.setdefault(act, (not failed, failed[0] if failed else ''))
    return out


def test_org_is_lowest_tier():
    assert category_level('ORG') == 1
    assert category_level('ORG') == category_level('LOCATION')   # 与地点同档，都是地板
    assert category_level('ORG') < category_level('PERSON_NAME')


def test_org_not_hard_banned():
    """最低档 ≠ 不敏感：仍然要能被识别、可泛化、可代号替换。"""
    meta = category_meta('ORG')
    assert meta['hard_ban'] is False
    assert meta['name'] == '机构/社团名'


def test_tier_ordering_matches_product_policy():
    """同段文字里，级别必须严格反映「证件/密钥 > 联系方式 > 姓名 > 机构」的泄露代价。"""
    assert (category_level('ID_CARD') > category_level('PHONE')
            > category_level('PERSON_NAME') >= category_level('ORG'))


def test_public_org_name_can_reach_public_channel():
    """「计算机学院」面向公开发布端（L1）放通。改回 L2 后这条会失败。"""
    result = _verdicts('计算机学院承办了本次活动。')
    passed, why = result[Action.RETAIN]
    assert passed, f'机构名对公开发布端应放行，实际被拦：{why}'


def test_person_name_still_blocked_on_public_channel():
    """对照组：姓名（L2）在同一接收方必须继续被拦住——降级不能误伤高敏类别。"""
    result = _verdicts('周涛同学承办了本次活动。')
    for act, (passed, why) in result.items():
        assert not passed, f'姓名对公开发布端应被拦截，动作 {act.value} 却放行了'
        assert 'PERSON_NAME' in why, f'拦截原因应点名 PERSON_NAME，实际：{why}'


def test_person_and_org_in_same_segment_blocks_whole_segment():
    """同段同时含姓名与机构名时，按最严的类别判定，整体拦截。"""
    result = _verdicts('计算机学院的周涛同学承办了本次活动。')
    for act, (passed, _why) in result.items():
        assert not passed, f'含姓名的片段不该因机构名降级而放行（动作 {act.value}）'


@pytest.mark.parametrize('category', ['ID_CARD', 'BANK_CARD', 'API_KEY', 'SENSITIVE_ATTR'])
def test_top_tier_categories_are_level4(category):
    assert category_level(category) == 4, f'{category} 必须是最高档'
