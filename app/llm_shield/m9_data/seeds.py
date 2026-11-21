"""模块 ⑨ 关键词种子定义。

对应架构：「法学/经管成员定义各模板下的关键词种子」，
再由领域预训练模型在未标注校园文本中查找语义相近词，扩充标签。

这里的种子按「处理动作」组织：每个动作给出若干高指示性词汇，
弱监督阶段用这些词去未标注语料里捞样本、再找语义相近词扩充。
"""
from __future__ import annotations

from typing import Dict, List

# ------------------------------------------------------------ 动作种子词
# 说明：种子词应尽可能「只在该动作下出现」，避免歧义污染弱标签。

SEEDS: Dict[str, List[str]] = {
    "DELETE": [
        "手机号", "电话号码", "联系方式", "联系电话", "邮箱", "电子邮箱",
        "微信号", "qq号", "身份证号", "证件号", "银行卡号", "卡号",
        "学号", "学籍号", "宿舍号", "家庭住址", "政治面貌", "民族",
        "成绩", "绩点", "口令", "密钥", "密码", "token",
    ],
    "LOCAL_AGGREGATE": [
        "报名人数", "参与人数", "实到人数", "总人数", "合计人数",
        "人数统计", "汇总", "统计人数", "共多少人", "人次",
    ],
    "GENERALIZE": [
        "所在学院", "所属部门", "活动地点", "场地", "会议室", "教室",
        "经费预算", "预算金额", "费用区间", "大致金额",
    ],
    "PSEUDONYMIZE": [
        "负责人姓名", "责任人", "项目负责人", "事项负责人", "对接人",
        "参与同学", "成员姓名", "队长", "组长", "部长",
    ],
    "RETAIN": [
        "活动名称", "项目名称", "已获准公开", "可公开事实", "公开信息",
        "活动主题", "项目简介", "对外发布",
    ],
}

# ------------------------------------------------------------ 任务层种子
# 不同任务模板下，同一动作需要强调的侧重点不同

TASK_SEEDS: Dict[str, Dict[str, List[str]]] = {
    "activity_stats": {
        "LOCAL_AGGREGATE": ["报名人数", "参与人数", "实到人数", "人数"],
        "DELETE": ["手机号", "邮箱", "学号", "微信号"],
        "RETAIN": ["活动名称", "活动类别", "活动时间"],
    },
    "meeting_minutes": {
        "PSEUDONYMIZE": ["负责人", "责任人", "对接人", "成员"],
        "DELETE": ["联系电话", "邮箱", "口令", "密钥"],
        "RETAIN": ["事项", "期限", "截止"],
    },
    "project_intro": {
        "DELETE": ["预算", "经费", "金额", "联系方式", "学号"],
        "RETAIN": ["项目名称", "已获准公开", "公开事实"],
        "GENERALIZE": ["所在学院", "地点"],
    },
}

# ------------------------------------------------------------ 负向种子
# 明确不属于任何敏感动作的词，用于抑制弱标签噪声

NEGATIVE_SEEDS: List[str] = [
    "活动", "会议", "项目", "总结", "计划", "安排", "时间", "地点",
    "内容", "流程", "结果", "问题", "建议", "下一步",
]


def seeds_for(task_key: str) -> Dict[str, List[str]]:
    """合并通用种子与任务专属种子。"""
    merged: Dict[str, List[str]] = {k: list(v) for k, v in SEEDS.items()}
    for action, words in TASK_SEEDS.get(task_key, {}).items():
        merged.setdefault(action, [])
        merged[action] = merged[action] + [w for w in words if w not in merged[action]]
    return merged


def all_seed_words(task_key: str = "") -> List[str]:
    src = seeds_for(task_key) if task_key else SEEDS
    return [w for words in src.values() for w in words]
