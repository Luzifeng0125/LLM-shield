"""★ 300 例合成案例生成与分层划分（模块 ⑨）。

设计要点：
- 全部为虚构合成数据，不含任何真实个人信息；
- 生成时同步产出 gold 标注（敏感片段位置 + 类别），无需人工二次标注；
- 按「文档来源」分层划分开发集 / 独立测试集，避免同模板泄漏；
- 同时导出必要性模型的训练样本（feature + label）。

运行：python -m llm_shield.m9_data.synthesize
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

from ..config import DATA_DIR
from ..m4_necessity.model import build_feature_text
from ..schema import Segment, Span

OUT_DIR = DATA_DIR / "generated"

TOTAL_PER_TASK = 100      # 每类任务 100 例，合计 300 例
DEV_RATIO = 0.7

# ---------------------------------------------------------------- 槽库（全部虚构）

SURNAME = ["张", "李", "王", "赵", "陈", "刘", "孙", "周", "吴", "郑",
           "冯", "蒋", "韩", "杨", "朱", "秦", "许", "何", "吕", "施"]
GIVEN = ["明", "晓华", "芳", "磊", "静", "洋", "悦", "涛", "婷", "超",
         "雨桐", "子涵", "欣然", "志远", "嘉怡", "文博", "思远", "梦琪"]

ORG = ["星辰志愿者协会", "计算机学院学生会", "春晖文学社", "启航科创俱乐部",
       "明德法学会", "经济管理学院团委", "校园广播台", "绿野环保协会"]
LOC = ["中心操场", "学生活动中心305会议室", "图书馆报告厅", "第三教学楼401教室",
       "大学生活动中心", "体育馆副馆", "东校区广场"]
EVENT = ["春季校园志愿服务月", "校园读书分享会", "新生编程训练营", "校园歌手大赛",
         "创新创业项目路演", "心理健康主题沙龙", "毕业生经验交流会"]
MODULE = ["后端接口", "前端页面", "测试上线", "运营推广", "数据看板", "用户反馈"]
TASK_ITEM = ["招新推文终稿", "赞助商对接", "志愿者培训手册", "报名人数汇总",
             "场地借用申请", "宣传物料设计", "设备调试", "嘉宾邀请"]


def _phone(rng: random.Random) -> str:
    return "1" + rng.choice("3456789") + "".join(str(rng.randint(0, 9)) for _ in range(9))


def _sid(rng: random.Random) -> str:
    return "2023" + "".join(str(rng.randint(0, 9)) for _ in range(6))


def _name(rng: random.Random) -> str:
    return rng.choice(SURNAME) + rng.choice(GIVEN)


def _email(rng: random.Random) -> str:
    return f"user{rng.randint(1000, 9999)}@example.com"


def _money(rng: random.Random) -> str:
    return f"{rng.randint(2, 90) * 500}元"


def _date(rng: random.Random) -> str:
    return f"2026年{rng.randint(3, 6)}月{rng.randint(1, 28)}日"


def _deadline(rng: random.Random) -> str:
    return f"{rng.randint(3, 6)}月{rng.randint(1, 28)}日前"


# ---------------------------------------------------------------- 生成器


class CaseBuilder:
    """拼接文本并同步记录 gold 片段位置。"""

    def __init__(self):
        self.buf: str = ""
        self.spans: List[dict] = []
        self.rows: List[dict] = []
        self.columns: List[str] = []

    def add(self, text: str) -> "CaseBuilder":
        self.buf += text
        return self

    def add_span(self, text: str, category: str, conf: float = 1.0) -> "CaseBuilder":
        start = len(self.buf)
        self.buf += text
        self.spans.append({"start": start, "end": len(self.buf),
                           "value": text, "category": category, "confidence": conf})
        return self

    def new_row(self, row: dict) -> None:
        self.rows.append(row)

    @property
    def text(self) -> str:
        return self.buf


def build_activity_stats(rng: random.Random) -> dict:
    """任务一：活动统计与总结。"""
    b = CaseBuilder()
    b.add(f"活动名称：{rng.choice(EVENT)}。")
    b.add(f"主办单位：{rng.choice(ORG)}。")
    b.add(f"活动时间：{_date(rng)}。")
    b.add(f"活动地点：{rng.choice(LOC)}。\n\n")

    b.add("报名名单如下：\n")
    b.columns = ["姓名", "学院", "学号", "手机号", "邮箱"]
    n = rng.randint(4, 8)
    for _ in range(n):
        name, sid, phone, email = _name(rng), _sid(rng), _phone(rng), _email(rng)
        row = {"姓名": name, "学院": rng.choice(ORG), "学号": sid,
               "手机号": phone, "邮箱": email}
        b.new_row(row)
        b.add_span(f"姓名：{name}", "PERSON_NAME").add("，")
        b.add(f"学院：{row['学院']}，")
        b.add_span(f"学号：{sid}", "STUDENT_ID").add("，")
        b.add_span(f"手机号：{phone}", "PHONE").add("，")
        b.add_span(f"邮箱：{email}", "EMAIL").add("。\n")

    b.add(f"\n本次活动报名人数共 {n} 人，请据此完成统计与总结。")
    return {
        "task": "activity_stats", "source": "activity_roster",
        "text": b.text, "columns": b.columns, "rows": b.rows,
        "gold_spans": b.spans,
        "expect": {"person_count": n, "must_not_appear": ["PHONE", "EMAIL", "STUDENT_ID"]},
    }


def build_meeting_minutes(rng: random.Random) -> dict:
    """任务二：会议纪要与任务分配。"""
    b = CaseBuilder()
    b.add(f"{rng.choice(ORG)}例会纪要\n")
    b.add(f"会议时间：{_date(rng)}。会议地点：{rng.choice(LOC)}。")
    host = _name(rng)
    b.add("主持人：").add_span(host, "PERSON_NAME").add("。\n\n")

    b.columns = ["事项", "负责人", "期限", "联系电话"]
    n = rng.randint(3, 5)
    for _ in range(n):
        item, owner = rng.choice(TASK_ITEM), _name(rng)
        dl, phone = _deadline(rng), _phone(rng)
        b.new_row({"事项": item, "负责人": owner, "期限": dl, "联系电话": phone})
        b.add(f"事项：{item}，")
        b.add("负责人：").add_span(owner, "PERSON_NAME").add("，")
        b.add(f"期限：{dl}，")
        b.add_span(f"联系电话：{phone}", "PHONE").add("。\n")

    b.add(f"\n经费预算：").add_span(_money(rng), "BUDGET").add("，具体明细另行报送。\n")
    b.add("公用邮箱口令：").add_span(f"api_key=Club{rng.randint(1000,9999)}Secret", "API_KEY").add("，仅限内部知悉。\n")
    b.add("请据此整理会议纪要与任务分派清单。")
    return {
        "task": "meeting_minutes", "source": "meeting_minutes",
        "text": b.text, "columns": b.columns, "rows": b.rows,
        "gold_spans": b.spans,
        "expect": {"must_keep_relation": True,
                   "must_not_appear": ["PHONE", "BUDGET", "API_KEY"]},
    }


def build_project_intro(rng: random.Random) -> dict:
    """任务三：项目对外介绍。"""
    b = CaseBuilder()
    b.add(f"项目名称：{rng.choice(['校园二手书循环平台', '社团活动管理系统', '课程互助问答社区', '校园失物招领小程序'])}。\n")
    b.add(f"项目负责人：").add_span(_name(rng), "PERSON_NAME").add("。")
    b.add(f"所属单位：{rng.choice(ORG)}。\n\n")

    b.columns = ["项目模块", "负责人", "预算", "联系方式"]
    n = rng.randint(3, 5)
    for _ in range(n):
        mod, owner = rng.choice(MODULE), _name(rng)
        money, phone = _money(rng), _phone(rng)
        b.new_row({"项目模块": mod, "负责人": owner, "预算": money, "联系方式": phone})
        b.add(f"模块：{mod}，负责人：").add_span(owner, "PERSON_NAME").add("，")
        b.add_span(f"预算：{money}", "BUDGET").add("，")
        b.add_span(f"联系方式：{phone}", "PHONE").add("。\n")

    b.add(f"\n办公地点：{rng.choice(LOC)}。\n")
    b.add("联系方式：").add_span(_phone(rng), "PHONE").add("，")
    b.add_span(_email(rng), "EMAIL").add("。\n")
    b.add(f"微信：").add_span(f"wxid_proj{rng.randint(1000,9999)}", "WECHAT").add("。\n\n")
    b.add("请改写为可对外发布的项目介绍，仅保留已获准公开的事实。")
    return {
        "task": "project_intro", "source": "project_plan",
        "text": b.text, "columns": b.columns, "rows": b.rows,
        "gold_spans": b.spans,
        "expect": {"must_not_appear": ["PHONE", "EMAIL", "WECHAT", "BUDGET"]},
    }


BUILDERS = {
    "activity_stats": build_activity_stats,
    "meeting_minutes": build_meeting_minutes,
    "project_intro": build_project_intro,
}


# ---------------------------------------------------------------- 主流程


def generate_all(total_per_task: int = TOTAL_PER_TASK, seed: int = 2026) -> Dict[str, list]:
    """生成全部案例，并按来源分层划分 dev / test。"""
    rng = random.Random(seed)
    by_task: Dict[str, list] = {}
    for task, fn in BUILDERS.items():
        cases = []
        for i in range(total_per_task):
            case = fn(rng)
            case["case_id"] = f"{task}_{i:03d}"
            case["identity"] = "student_leader"
            case["recipient"] = "external_model"
            cases.append(case)
        by_task[task] = cases

    # 分层划分：每个任务内部按 7:3 切，保证 dev/test 来源分布一致
    dev, test = [], []
    for task, cases in by_task.items():
        idx = list(range(len(cases)))
        random.Random(seed + 1).shuffle(idx)
        cut = int(len(idx) * DEV_RATIO)
        dev += [cases[i] for i in idx[:cut]]
        test += [cases[i] for i in idx[cut:]]
    return {"dev": dev, "test": test, "all": dev + test}


def export_necessity_samples(cases: List[dict], task_key: str) -> List[dict]:
    """从合成案例派生必要性模型训练样本（feature + label）。

    标签来自「该案例所属任务模板下，各动作对各类别的处理规则」，
    即把 rules/tasks 中的先验转成监督信号（弱监督的起点）。
    """
    from ..config import tasks as tasks_cfg

    prefer = tasks_cfg().get(task_key, {}).get("prefer", {})
    samples = []
    for case in cases:
        if case["task"] != task_key:
            continue
        text = case["text"]
        for span in case["gold_spans"]:
            seg = Segment(seg_id="x", text=text, start=0, end=len(text))
            seg.spans = [Span(span["start"], span["end"], span["value"],
                              span["category"], 1.0)]
            label = prefer.get(span["category"])
            if not label:
                continue
            samples.append({
                "feature": build_feature_text(seg, task_key, "external_model"),
                "label": label,
                "confidence": 1.0,
                "source": "synthetic_rule",
            })
    return samples


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    split = generate_all()

    for name in ("dev", "test"):
        path = OUT_DIR / f"cases_{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for c in split[name]:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"[{name}] {len(split[name])} 例 -> {path}")

    # 必要性训练样本（仅用 dev，test 保持独立）
    samples: List[dict] = []
    for task in BUILDERS:
        samples += export_necessity_samples(split["dev"], task)
    p = OUT_DIR / "necessity_train.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[necessity] {len(samples)} 条训练样本 -> {p}")


if __name__ == "__main__":
    main()
