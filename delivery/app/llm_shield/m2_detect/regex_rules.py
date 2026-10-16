"""格式类别识别：正则 + 边界 + 校验位。

对应架构 ② 中的「格式规则：手机号/邮箱/证件号/密钥（正则+边界+校验）」。
带校验位的类别（身份证/银行卡）必须通过校验才算命中，避免把普通长数字误判。
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional

from ..schema import Span
from .base import Detector


# ---------------------------------------------------------------- 校验函数


def valid_id_card(value: str) -> bool:
    """18 位身份证校验位算法（GB 11643）。"""
    if not re.fullmatch(r"\d{17}[\dXx]", value):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"
    total = sum(int(value[i]) * weights[i] for i in range(17))
    return check_codes[total % 11].upper() == value[17].upper()


def valid_luhn(value: str) -> bool:
    """银行卡 Luhn 校验。"""
    if not value.isdigit():
        return False
    total, alt = 0, False
    for ch in reversed(value):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


# ---------------------------------------------------------------- 规则表
# 字段说明：
#   category    敏感类别
#   pattern     正则（已含边界断言，避免匹配到更长数字串的一部分）
#   group       取值分组，None 表示整段
#   confidence  基础置信度
#   validator   额外校验函数（失败则丢弃）
#   ctx         上下文触发词；非空时，命中上下文置信度更高，否则折半
#   ctx_window  上下文窗口字数


RULES: List[dict] = [
    # ---- 手机号 / 固话 ----
    {
        "category": "PHONE", "rule_id": "phone_mobile",
        # 允许段内空格/连字符分组。人工 gold 本身就大量使用 "150 0278 7488" 这种
        # 写法（scripts/field_v1_check.py 可复核），旧 pattern 要求 11 位连续数字，
        # 在旧 gold 的 4 条带空格号码上全部漏检，只能靠 GLiNER 兜底——
        # 这正是"模型看起来很有用"的一部分其实是在补正则的漏洞。
        # 只允许空格/制表符/连字符，不用 \s，避免把跨行数字粘成一个号码。
        "pattern": re.compile(r"(?<!\d)(1[3-9]\d[ \t\-]?\d{4}[ \t\-]?\d{4})(?!\d)"),
        "group": 1, "confidence": 0.98, "validator": None, "ctx": ["手机", "电话", "联系", "联系方式", "拨打"],
    },
    {
        "category": "PHONE", "rule_id": "phone_landline",
        "pattern": re.compile(r"(?<!\d)(0\d{2,3}-?\d{7,8})(?!\d)"),
        "group": 1, "confidence": 0.90, "validator": None, "ctx": ["电话", "座机", "办公", "联系"],
    },
    # ---- 邮箱 ----
    {
        "category": "EMAIL", "rule_id": "email",
        "pattern": re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?![A-Za-z0-9-])"),
        "group": 1, "confidence": 0.97, "validator": None, "ctx": ["邮箱", "邮件", "email", "@"],
    },
    # ---- 身份证（必须过校验位）----
    {
        "category": "ID_CARD", "rule_id": "id_card_18",
        "pattern": re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)"),
        "group": 1, "confidence": 0.99, "validator": valid_id_card, "ctx": ["身份证", "证件", "证件号", "身份"],
    },
    # ---- 银行卡（13~19 位 + Luhn）----
    {
        "category": "BANK_CARD", "rule_id": "bank_card",
        "pattern": re.compile(r"(?<!\d)(\d{13,19})(?!\d)"),
        "group": 1, "confidence": 0.85, "validator": valid_luhn, "ctx": ["银行卡", "卡号", "账户", "打款", "工资卡"],
    },
    # ---- 学号（弱格式，必须依赖上下文）----
    {
        "category": "STUDENT_ID", "rule_id": "student_id_ctx",
        "pattern": re.compile(r"学号\s*[:：]?\s*(\d{8,12})"),
        "group": 1, "confidence": 0.95, "validator": None, "ctx": [], "require_ctx": True,
    },
    {
        "category": "STUDENT_ID", "rule_id": "student_id_bare",
        "pattern": re.compile(r"(?<!\d)(20\d{8})(?!\d)"),
        "group": 1, "confidence": 0.55, "validator": None, "ctx": ["学号", "学籍", "入学", "编号"],
    },
    # ---- 密钥 / 口令 ----
    {
        "category": "API_KEY", "rule_id": "api_key_sk",
        "pattern": re.compile(r"(sk-[A-Za-z0-9]{16,})"),
        "group": 1, "confidence": 0.99, "validator": None, "ctx": [],
    },
    {
        # 赋值式密钥：取整段「键名=值」，与 m9_data/synthesize.py 和人工 gold
        # 的标注口径一致（二者都把 api_key=Club...Secret 整体标为一个实体）。
        # 只取等号右侧会与标注错位，且「键名保留、值脱敏」在这里并无额外价值——
        # 整段替换更能保证没有凭证碎片残留。
        "category": "API_KEY", "rule_id": "api_key_assign",
        "pattern": re.compile(r"(?:api[_-]?key|access[_-]?token|secret|password|passwd|口令|密钥)\s*[=:：]\s*[A-Za-z0-9._\-]{8,}",
                              re.IGNORECASE),
        "group": None, "confidence": 0.96, "validator": None, "ctx": [],
    },
    {
        "category": "API_KEY", "rule_id": "api_key_bearer",
        "pattern": re.compile(r"(Bearer\s+[A-Za-z0-9._\-]{16,})"),
        "group": 1, "confidence": 0.95, "validator": None, "ctx": [],
    },
    # ---- 微信号 / QQ ----
    {
        "category": "WECHAT", "rule_id": "wechat_id",
        "pattern": re.compile(r"(?:微信(?:号)?|wx|WeChat)\s*[:：]?\s*([A-Za-z][-_A-Za-z0-9]{5,19})"),
        "group": 1, "confidence": 0.93, "validator": None, "ctx": [],
    },
    {
        "category": "WECHAT", "rule_id": "qq_id",
        "pattern": re.compile(r"(?:QQ(?:号)?|qq)\s*[:：]?\s*(\d{5,12})"),
        "group": 1, "confidence": 0.92, "validator": None, "ctx": [],
    },
    # ---- 金额 / 预算 ----
    {
        "category": "BUDGET", "rule_id": "budget_money",
        "pattern": re.compile(r"([¥￥]?\s*\d+(?:\.\d+)?\s*(?:元|万元|块|RMB|元整))"),
        "group": 1, "confidence": 0.88, "validator": None,
        "ctx": ["预算", "经费", "金额", "费用", "支出", "成本", "报价", "赞助", "收入", "结余"],
    },
    # ---- 宿舍号 ----
    {
        "category": "DORM", "rule_id": "dorm_cn",
        "pattern": re.compile(r"(\d{1,2}\s*[号楼栋舍]\s*\d{3,4}\s*[室寝室]?)"),
        "group": 1, "confidence": 0.90, "validator": None, "ctx": ["宿舍", "寝室", "住宿", "楼"],
    },
    {
        "category": "DORM", "rule_id": "dorm_alpha",
        "pattern": re.compile(r"(?<![A-Za-z0-9])([A-Z]\s?座\s?\d{3,4})(?![0-9])"),
        "group": 1, "confidence": 0.85, "validator": None, "ctx": ["宿舍", "公寓", "楼"],
    },
    # ---- 成绩 / 绩点 ----
    {
        "category": "GRADE", "rule_id": "gpa",
        "pattern": re.compile(r"(?:绩点|GPA|gpa)\s*[:：]?\s*(\d\.\d{1,2})"),
        "group": 1, "confidence": 0.93, "validator": None, "ctx": [],
    },
    {
        "category": "GRADE", "rule_id": "score",
        "pattern": re.compile(r"(?:成绩|分数|得分|平均分)\s*[:：]?\s*(\d{1,3}(?:\.\d)?)\s*分?"),
        "group": 1, "confidence": 0.88, "validator": None, "ctx": [],
    },
]


class RegexDetector(Detector):
    """格式规则识别器。"""

    name = "regex"

    def detect(self, text: str, columns=None, rows=None) -> List[Span]:
        spans: List[Span] = []
        if not text:
            return spans

        for rule in RULES:
            for m in rule["pattern"].finditer(text):
                raw = m.group(rule["group"]) if rule["group"] else m.group(0)
                value = raw.strip()
                if not value:
                    continue
                # 校验位验证（身份证 / 银行卡）
                validator: Optional[Callable[[str], bool]] = rule.get("validator")
                if validator and not validator(value.replace(" ", "")):
                    continue

                start, end = m.span(rule["group"]) if rule["group"] else m.span(0)
                # 修正 strip 造成的偏移
                if raw != value:
                    start += raw.index(value)

                conf = float(rule["confidence"])
                ctx_words = rule.get("ctx") or []
                if rule.get("require_ctx"):
                    # 必须命中上下文，否则丢弃
                    if not ctx_words or not self._context_hit(text, start, end, ctx_words, 16):
                        continue
                elif ctx_words:
                    if not self._context_hit(text, start, end, ctx_words, 14):
                        conf *= 0.6   # 无上下文 → 降置信度，交给低置信硬约束处理

                spans.append(Span(
                    start=start, end=end, text=value,
                    category=rule["category"], confidence=min(conf, 1.0),
                    detector=self.name, rule_id=rule["rule_id"],
                ))
        return spans
