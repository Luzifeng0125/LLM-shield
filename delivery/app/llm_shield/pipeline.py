"""端到端编排：加载 → 识别 → 决策 → 转换 → 外发 → 观测。

对应架构的数据流：
  提交材料与任务信息 → 身份及权限检查 → 敏感信息识别 → 任务感知最小披露决策
  → 内容转换与代号映射 → 调用外部模型 → 输出检查与授权恢复
  → 受控展示 / 模拟外发 → 三边界观测记录
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from . import config as C
from .m1_access.identity import can_restore, check_provide, check_read
from .m1_access.loader import flatten_material
from .m2_detect.pipeline import DetectionError, build_detectors, detect_and_segment
from .m3_decide.decision import decide_all
from .m4_necessity.model import get_model, necessity_scorer
from .m5_utility.estimator import estimate
from .m6_transform.anonymizer import apply_decisions
from .m6_transform.mapping import get_table
from .m7_egress.gateway import EgressGateway
from .m8_audit.audit import get_auditor
from .schema import Action, Boundary, PipelineResult, ShieldRequest, Span

# 每个边界的默认接收方（当请求指定的接收方不属于该类型时使用）
DEFAULT_BOUNDARY_RECIPIENT = {
    Boundary.B1_MODEL_INPUT: "external_model",
    Boundary.B2_VIEW_DISPLAY: "viewer_teacher",
    Boundary.B3_TOOL_EGRESS: "egress_tool_public",
}


def _recipient_type_of(key: str) -> str:
    return C.recipients().get(key, {}).get("type", "EGRESS_TOOL")


def _pick_boundary_recipients(primary: str) -> Dict[str, str]:
    """决定三个边界各自检查的接收方。

    请求指定的接收方作为「主接收方」参与决策；
    三个边界分别按各自类型取对应的接收方做独立检查，便于对照演示。
    """
    want = {
        Boundary.B1_MODEL_INPUT: "EXTERNAL_MODEL",
        Boundary.B2_VIEW_DISPLAY: "VIEWER",
        Boundary.B3_TOOL_EGRESS: "EGRESS_TOOL",
    }
    out = {}
    for b, t in want.items():
        out[b.value] = primary if _recipient_type_of(primary) == t else DEFAULT_BOUNDARY_RECIPIENT[b]
    return out


def _pause_request(result: PipelineResult, reason: str, started: float) -> PipelineResult:
    """拒绝整个请求；暂停不是删除某段后继续发送剩余内容。"""
    result.ok = False
    result.paused = True
    result.pause_reason = reason
    result.model_output = result.display_text = result.egress_text = ""
    result.warnings.append(reason)
    bmap = _pick_boundary_recipients(result.recipient)
    result.boundaries = [
        {"boundary": boundary.value, "recipient": recipient,
         "recipient_type": _recipient_type_of(recipient), "blocked": True,
         "allowed": False, "blocked_reason": reason,
         "leaked_categories": [], "leak_hits": [], "latency_ms": 0.0}
        for boundary in Boundary for recipient in [bmap[boundary.value]]
    ]
    result.timings["total_ms"] = (time.perf_counter() - started) * 1000
    return result


def run_pipeline(req: ShieldRequest, send_model: bool = True) -> PipelineResult:
    """执行一次完整的受控处理流程。"""
    t_all = time.perf_counter()
    timings: Dict[str, float] = {}
    warnings: List[str] = []

    result = PipelineResult(
        ok=True, session_id=req.session_id, task=req.task,
        identity=req.identity, recipient=req.recipient,
    )
    if not isinstance(C.tasks().get(req.task), dict):
        return _pause_request(result, "未知任务，不能确定外发策略", t_all)

    # ---------------------------------------------------------- ① 身份与权限
    t0 = time.perf_counter()
    access = check_read(req.identity, req.materials)
    result.access_ok, result.access_reason = access.ok, access.reason
    if not access.ok:
        result.ok = False
        timings["access_ms"] = (time.perf_counter() - t0) * 1000
        result.timings = timings
        result.warnings = [f"访问被拒：{access.reason}"]
        return result

    ok_provide, why_provide = check_provide(req.identity, req.recipient)
    if not ok_provide:
        result.ok = False
        result.access_ok = False
        result.access_reason = why_provide
        timings["access_ms"] = (time.perf_counter() - t0) * 1000
        result.timings = timings
        result.warnings = [f"外发授权失败：{why_provide}"]
        return result
    timings["access_ms"] = (time.perf_counter() - t0) * 1000

    if not get_model().available:
        result.timings = timings
        return _pause_request(result, "本地决策模型不可用：" + get_model().reason, t_all)

    # ---------------------------------------------------------- 材料摊平
    text = "\n".join(flatten_material(m) for m in access.allowed_materials)
    result.original_text = text
    columns = access.allowed_materials[0].columns if access.allowed_materials else None
    rows = access.allowed_materials[0].rows if access.allowed_materials else None

    # ---------------------------------------------------------- ② 识别
    t0 = time.perf_counter()
    try:
        detectors = build_detectors()
        spans, segments = detect_and_segment(text, columns=columns, rows=rows, detectors=detectors)
    except DetectionError as exc:
        result.timings = timings
        return _pause_request(result, str(exc), t_all)
    timings["detect_ms"] = (time.perf_counter() - t0) * 1000
    result.spans = [s.to_dict() for s in spans]

    # ---------------------------------------------------------- ③④ 决策
    t0 = time.perf_counter()
    decisions = decide_all(segments, req.task, req.recipient, req.identity,
                           necessity_scorer=necessity_scorer,
                           task_description=req.user_instruction)
    timings["decide_ms"] = (time.perf_counter() - t0) * 1000
    result.decisions = [d.to_dict() for d in decisions]
    paused = next((d for d in decisions if d.action == Action.PAUSE), None)
    if paused is not None:
        result.timings = timings
        return _pause_request(result, paused.reason, t_all)

    # ---------------------------------------------------------- ⑥ 转换
    t0 = time.perf_counter()
    mapping = get_table()
    applied = apply_decisions(text, segments, decisions, req.session_id, mapping)
    timings["transform_ms"] = (time.perf_counter() - t0) * 1000
    result.sanitized_text = applied["sanitized_text"]
    result.aggregates = applied["aggregates"]
    result.mapping_table = {k.split("::", 1)[-1]: v for k, v in applied["mapping"].items()}
    result.paused = applied["paused"]
    result.pause_reason = applied["pause_reason"]

    # 受控保留的值：这些值允许出现在载荷中，不算泄露
    allowed_values: Set[str] = set()
    for seg, dec in zip(segments, decisions):
        if dec.action == Action.RETAIN:
            allowed_values.update(s.text for s in seg.spans)

    # ---------------------------------------------------------- ⑤ 效用估计
    util = estimate(result.sanitized_text, req.task, result.aggregates, decisions)
    warnings.extend(util["warnings"])
    if applied["paused"]:
        warnings.insert(0, f"存在片段被暂停外发：{applied['pause_reason']}")

    # ---------------------------------------------------------- ⑦⑧ 外发与观测
    gateway = EgressGateway(get_auditor(), generated_pseudonyms=set(applied["mapping"].values()))
    bmap = _pick_boundary_recipients(req.recipient)

    # 边界 1：发送给模型
    if send_model and result.sanitized_text.strip():
        t0 = time.perf_counter()
        r1 = gateway.send_to_model(req.task, result.sanitized_text, req.identity,
                                   spans, allowed_values)
        timings["model_ms"] = (time.perf_counter() - t0) * 1000
        result.boundaries.append(r1["record"].to_dict())
        if r1["allowed"]:
            result.model_output = r1["text"]
            if r1.get("error"):
                warnings.append(r1["error"])
            if r1["record"].leaked_categories:
                warnings.append(
                    f"输入侧检测到受限信息 {r1['record'].leaked_categories}，"
                    f"共 {len(r1['record'].leak_hits)} 处（已记为失败）")
        else:
            warnings.append(f"边界1（模型输入）被拦截：{r1['record'].blocked_reason}")
            result.warnings = warnings
            result.timings = timings
            return _pause_request(result, warnings[-1], t_all)
    else:
        # 区分「主动跳过」与「内容为空」，避免审计日志语义含糊
        reason = ("已按设置跳过模型调用（本次仅本地处理）" if not send_model
                  else "转换后无可用内容，未调用模型")
        result.boundaries.append({
            "boundary": Boundary.B1_MODEL_INPUT.value, "recipient": bmap[Boundary.B1_MODEL_INPUT.value],
            "blocked": True, "blocked_reason": reason, "allowed": False,
            "leaked_categories": [], "leak_hits": [], "latency_ms": 0.0, "recipient_type": "EXTERNAL_MODEL",
        })

    # 边界 2：结果展示（含授权恢复）
    b2_rec = bmap[Boundary.B2_VIEW_DISPLAY.value]
    display_src = result.model_output or result.sanitized_text
    restore_allowed = can_restore(req.identity, b2_rec)
    result.display_text = mapping.restore_text(req.session_id, display_src, restore_allowed)
    if restore_allowed and result.display_text != display_src:
        warnings.append("已按授权将代号恢复为真实姓名（身份与接收方均允许）")

    # 经授权恢复出的真实姓名属于合法披露，必须加入白名单，
    # 否则值级检测会把「按权限恢复的姓名」误判成泄露。
    b2_allowed = set(allowed_values)
    if restore_allowed:
        b2_allowed.update(result.mapping_table.keys())

    r2 = gateway.send_to_viewer(b2_rec, result.display_text, req.identity, spans,
                                b2_allowed, task_key=req.task)
    result.boundaries.append(r2["record"].to_dict())
    if not r2["allowed"]:
        result.display_text = ""
        warnings.append(f"边界2（结果展示）被拦截：{r2['record'].blocked_reason}")

    # 边界 3：模拟外发
    b3_rec = bmap[Boundary.B3_TOOL_EGRESS.value]
    egress_src = result.model_output or result.sanitized_text
    r3 = gateway.send_to_tool(b3_rec, egress_src, req.identity, spans,
                              allowed_values, task_key=req.task)
    result.boundaries.append(r3["record"].to_dict())
    if r3["allowed"]:
        result.egress_text = r3["text"]
    else:
        warnings.append(f"边界3（工具外发）被拦截：{r3['record'].blocked_reason}")

    result.warnings = warnings
    timings["total_ms"] = (time.perf_counter() - t_all) * 1000
    result.timings = timings
    primary_record = next((b for b in result.boundaries if b["recipient"] == req.recipient), None)
    result.ok = not (primary_record and primary_record["blocked"] and
                     not (not send_model and req.recipient == "external_model"))
    return result


def preview_only(req: ShieldRequest) -> PipelineResult:
    """只跑到本地模型决策，不调用云端模型、不外发。"""
    started = time.perf_counter()
    if not isinstance(C.tasks().get(req.task), dict):
        return _pause_request(PipelineResult(False, req.session_id, req.task,
                              req.identity, req.recipient), "未知任务", started)
    access = check_read(req.identity, req.materials)
    if not access.ok:
        r = PipelineResult(False, req.session_id, req.task, req.identity, req.recipient)
        r.access_ok, r.access_reason = False, access.reason
        return r

    allowed, reason = check_provide(req.identity, req.recipient)
    if not allowed:
        return _pause_request(PipelineResult(False, req.session_id, req.task,
                              req.identity, req.recipient), reason, started)
    if not get_model().available:
        return _pause_request(PipelineResult(False, req.session_id, req.task,
                              req.identity, req.recipient),
                              "本地决策模型不可用：" + get_model().reason, started)

    text = "\n".join(flatten_material(m) for m in access.allowed_materials)
    columns = access.allowed_materials[0].columns if access.allowed_materials else None
    rows = access.allowed_materials[0].rows if access.allowed_materials else None

    t0 = time.perf_counter()
    try:
        spans, segments = detect_and_segment(text, columns=columns, rows=rows)
    except DetectionError as exc:
        return _pause_request(PipelineResult(False, req.session_id, req.task,
                              req.identity, req.recipient), str(exc), started)
    detect_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    decisions = decide_all(segments, req.task, req.recipient, req.identity,
                           necessity_scorer=necessity_scorer,
                           task_description=req.user_instruction)
    decide_ms = (time.perf_counter() - t0) * 1000

    r = PipelineResult(True, req.session_id, req.task, req.identity, req.recipient)
    r.original_text = text
    r.spans = [s.to_dict() for s in spans]
    r.decisions = [
        {**d.to_dict(), "text": seg.text[:200]}
        for d, seg in zip(decisions, segments)
    ]
    r.timings = {"detect_ms": detect_ms, "decide_ms": decide_ms}
    paused = next((d for d in decisions if d.action == Action.PAUSE), None)
    if paused is not None:
        return _pause_request(r, paused.reason, started)
    return r
