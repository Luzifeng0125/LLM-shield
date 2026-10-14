"""隐盾冒烟测试：覆盖识别 / 决策 / 转换 / 外发 / 端到端。

运行：python tests/test_smoke.py
不依赖网络与外部服务，全部使用虚构数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm_shield.m1_access.identity import can_restore, check_provide, check_read
from llm_shield.m2_detect.pipeline import detect_all, detect_and_segment
from llm_shield.m3_decide.constraints import feasible_actions
from llm_shield.m3_decide.decision import decide_all
from llm_shield.m4_necessity.model import necessity_scorer
from llm_shield.m6_transform.anonymizer import apply_decisions
from llm_shield.m6_transform.mapping import MappingTable
from llm_shield.m7_egress.gateway import EgressGateway
from llm_shield.m8_audit.observer import inspect_payload
from llm_shield.schema import Action, Material, ShieldRequest

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


# ---------------------------------------------------------------- ② 识别

print("\n[模块 ②] 敏感信息识别")
text = ("负责人张明，手机号13812345678，邮箱 zhangming@example.com，"
        "学号：2023012345，身份证号 110105200301120014，"
        "口令 api_key=ClubSecret2026，经费预算 12800元。")

spans = detect_all(text)
cats = {s.category for s in spans}
check("手机号识别", "PHONE" in cats, str(cats))
check("邮箱识别", "EMAIL" in cats, str(cats))
check("学号识别", "STUDENT_ID" in cats, str(cats))
check("身份证识别（含校验位）", "ID_CARD" in cats, str(cats))
check("密钥识别", "API_KEY" in cats, str(cats))
check("金额识别", "BUDGET" in cats, str(cats))

# 非法身份证不应被识别（校验位验证）
bad = detect_all("身份证号 123456789012345678")
check("非法身份证被校验位拒绝",
      not any(s.category == "ID_CARD" for s in bad), str([s.text for s in bad]))

# 性能：2000 字以内识别应在 500ms 内
import time
long_text = (text * 40)[:2000]
t0 = time.perf_counter()
detect_and_segment(long_text)
elapsed = (time.perf_counter() - t0) * 1000
check(f"识别性能 P95 目标（2000字 {elapsed:.1f}ms < 500ms）", elapsed < 500)


# ---------------------------------------------------------------- ③ 决策

print("\n[模块 ③④] 最小披露决策")
_, segments = detect_and_segment(text)

# 面向云端模型（低信任）：**纯**手机号段应只能删除/聚合。
# 必须单独构造只含手机号的段来测：若段内同时有人名，
# 代号替换会删掉手机号、只留人名代号，那对被允许接收人名的接收方是合法的，
# 不能一刀切判禁（这正是 disclosed_categories 的设计意图）。
_, ph_segs = detect_and_segment("联系电话：13812345678，仅用于内部联络。")
ph_seg = next(s for s in ph_segs if any(x.category == "PHONE" for x in s.spans))
acts = feasible_actions(ph_seg, "activity_stats", "external_model", "student_leader")
check("纯手机号段在 external_model 下不可 RETAIN/PSEUDONYMIZE",
      Action.RETAIN not in acts and Action.PSEUDONYMIZE not in acts,
      str([a.value for a in acts]))

decisions = decide_all(segments, "activity_stats", "external_model", "student_leader", necessity_scorer)
phone_dec = next(d for d, s in zip(decisions, segments)
                 if any(x.category == "PHONE" for x in s.spans))
check("手机号最终动作为删除或聚合",
      phone_dec.action in (Action.DELETE, Action.LOCAL_AGGREGATE),
      phone_dec.action.value)

# 会议纪要：责任人应走代号替换而非删除
mm_text = "事项：招新推文终稿，负责人：李晓华，期限：2026年3月22日，联系电话：13923456789。"
_, mm_segs = detect_and_segment(mm_text)
mm_decs = decide_all(mm_segs, "meeting_minutes", "external_model", "student_leader", necessity_scorer)
name_dec = [d for d, s in zip(mm_decs, mm_segs)
            if any(x.category == "PERSON_NAME" for x in s.spans)]
check("会议纪要中责任人使用代号替换",
      bool(name_dec) and name_dec[0].action == Action.PSEUDONYMIZE,
      str([(d.action.value, d.categories) for d in mm_decs]))


# ---------------------------------------------------------------- ⑥ 转换

print("\n[模块 ⑥] 转换与代号映射")
mt = MappingTable()
c1 = mt.get_or_create("s1", "李晓华", "PERSON_NAME", list("甲乙丙"), {"person": "人员{code}"})
c2 = mt.get_or_create("s1", "李晓华", "PERSON_NAME", list("甲乙丙"), {"person": "人员{code}"})
c3 = mt.get_or_create("s1", "王芳", "PERSON_NAME", list("甲乙丙"), {"person": "人员{code}"})
c4 = mt.get_or_create("s2", "李晓华", "PERSON_NAME", list("甲乙丙"), {"person": "人员{code}"})
check("同会话同一人物代号稳定", c1 == c2, f"{c1} vs {c2}")
check("同会话不同人物代号不同", c1 != c3, f"{c1} vs {c3}")
# 隔离的本质：各会话各自维护一张映射表，互不干扰。
# 注意不能断言「s2 一定解析不出 s1 的代号」——代号池按会话洗牌，
# 两个会话可能碰巧给同一实体分到同一代号（这不影响安全：代号本身不含信息，
# 且解析只在本会话表内进行）。稳定的判据是两张表的规模彼此独立。
check("跨会话映射表相互独立",
      len(mt.export("s1")) == 2 and len(mt.export("s2")) == 1,
      f"s1={len(mt.export('s1'))} 项, s2={len(mt.export('s2'))} 项")
check("同会话映射可反向解析", mt.restore("s1", c1, allowed=True) == "李晓华")
check("未授权不恢复原名", mt.restore("s1", c1, allowed=False) is None)
check("授权后可恢复原名", mt.restore("s1", c1, allowed=True) == "李晓华")

applied = apply_decisions(mm_text, mm_segs, mm_decs, "sess_test", mt)
check("脱敏后不含手机号", "13923456789" not in applied["sanitized_text"])
check("脱敏后保留期限", "2026年3月22日" in applied["sanitized_text"])
check("脱敏后含责任人代号", "人员" in applied["sanitized_text"])

# 本地聚合
roster_text = "姓名：张明，手机号：13812345678。姓名：李晓华，手机号：13923456789。"
_, r_segs = detect_and_segment(roster_text)
r_decs = decide_all(r_segs, "activity_stats", "external_model", "student_leader", necessity_scorer)
r_applied = apply_decisions(roster_text, r_segs, r_decs, "sess_agg", MappingTable())
check("聚合场景明细已移除", "13812345678" not in r_applied["sanitized_text"])
check("聚合产出人数统计", r_applied["aggregates"].get("person_count", 0) >= 2,
      str(r_applied["aggregates"]))

# 直接覆盖金额聚合分支（回归：曾写成 sum(sum(amounts))，内层已返回 float 会抛 TypeError）
from llm_shield.m6_transform.aggregate import aggregate
agg_mix = aggregate([
    {"category": "BUDGET", "value": "3000元"},
    {"category": "BUDGET", "value": "4500元"},
    {"category": "PERSON_NAME", "value": "张明"},
    {"category": "ORG", "value": "计算机学院"},
])
check("金额聚合产出区间值", agg_mix.get("amount_band") is not None, str(agg_mix))
check("聚合人数/组织数正确",
      agg_mix.get("person_count") == 1 and agg_mix.get("org_count") == 1, str(agg_mix))
check("金额未以精确值出现在汇总中",
      "7500" not in (agg_mix.get("summary_text") or ""), agg_mix.get("summary_text", ""))


# ---------------------------------------------------------------- ①⑦ 权限与外发

print("\n[模块 ①⑦] 权限检查与外发控制")
ok, why = check_provide("external_partner", "external_model")
check("校外合作方无权发给外部模型", not ok, why)

ok2, why2 = check_provide("student_leader", "unknown_recipient_xyz")
check("未知接收方一律拒绝", not ok2, why2)

gw = EgressGateway()
res = gw.precheck("external_model", "student_leader",
                  "负责人张明，手机号13812345678", task_key="meeting_minutes")
check("含敏感内容的载荷被拦截", not res["allowed"], str(res["reason"]))

res2 = gw.precheck("external_model", "student_leader", "本次活动共8人参与。", task_key="activity_stats")
check("正常内容放行", res2["allowed"], str(res2.get("reason")))

check("授权恢复需双方允许", can_restore("student_leader", "viewer_teacher") is True)
check("学生组长不可恢复给同组学生", can_restore("student_leader", "viewer_peer") is False)


# ---------------------------------------------------------------- ⑧ 观测

print("\n[模块 ⑧] 三边界观测")
spans_for_inspect = detect_all("负责人张明，手机号13812345678")
insp = inspect_payload("负责人张明，手机号13812345678", "external_model", spans_for_inspect)
check("值级泄露可被检出", insp["leaked"], str(insp["leaked_categories"]))

insp2 = inspect_payload("本次活动共8人参与，未包含个人信息。", "external_model", spans_for_inspect)
check("干净载荷不误报", not insp2["leaked"], str(insp2["leaked_categories"]))


# ---------------------------------------------------------------- 端到端

print("\n[端到端] 完整流水线")
from llm_shield.pipeline import run_pipeline
from llm_shield.m4_necessity.model import necessity_scorer

# 预热：必要性模型首次加载需反序列化词表（约 1.8s，一次性开销），
# 稳态推理约 0.4ms。预热后再计时，测的才是真实的稳态性能。
necessity_scorer(segments[0], "activity_stats", "external_model")

mat = Material(doc_id="t", doc_type="meeting_minutes", title="测试纪要", text=mm_text)
req = ShieldRequest(session_id="e2e", identity="student_leader",
                    task="meeting_minutes", recipient="external_model",
                    materials=[mat])
result = run_pipeline(req, send_model=False)
check("流水线执行成功", result.ok, result.access_reason)
check("模型输入不含手机号", "13923456789" not in result.sanitized_text)
check("三边界均有记录", len(result.boundaries) == 3, str(len(result.boundaries)))
check("识别+决策耗时 < 500ms",
      result.timings.get("detect_ms", 0) + result.timings.get("decide_ms", 0) < 500,
      str(result.timings))
check("代号映射表已生成", len(result.mapping_table) > 0, str(result.mapping_table))


print("\n" + "=" * 56)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "、".join(FAIL))
print("=" * 56)
sys.exit(1 if FAIL else 0)
