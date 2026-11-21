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
from .m2_detect.pipeline import DetectionError, build_detectors, detect_and_segment
from .material_processing import MaterialSizeError, prepare_materials
from .m4_necessity.model import get_model, necessity_scorer
from .m5_utility.estimator import estimate
from .m6_transform.anonymizer import apply_decisions
from .m6_transform.local_completion import (
    boundary_allows_generalized_budget,
    covers_budget_pause,
    plan_meeting_budget,
    present_amount,
    seal_external_text,
    strip_held,
)
from .m6_transform.mapping import MappingTable
from .m6_transform.reversible import (
    CONTACT_NOTICE_TASK, mask_necessary, reversible_categories,
)
from .m7_egress.gateway import EgressGateway
from .m8_audit.audit import get_auditor
from .metrics import observe
from .processing import ProcessingFailure, analyze
from .material_policy import material_scope, SourcePolicyError
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
    observe("total_ms", result.timings["total_ms"])
    return result


def _run_contact_notice(req: ShieldRequest, result: PipelineResult, started: float) -> PipelineResult:
    """姓名和电话换成占位符后暂停。不调用云端，也不把映射表放进请求。"""
    access = check_read(req.identity, list(req.materials))
    if not access.ok or access.denied_docs:
        result.access_ok = False
        result.access_reason = access.reason or "包含无权读取的材料"
        return _pause_request(result, result.access_reason, started)
    allowed, reason = check_provide(req.identity, req.recipient)
    if not allowed:
        result.access_ok = False
        result.access_reason = reason
        return _pause_request(result, reason, started)
    try:
        detectors = build_detectors()
        prepared = prepare_materials(access.allowed_materials, detect=detect_and_segment,
                                     detectors=detectors)
    except (DetectionError, MaterialSizeError) as exc:
        return _pause_request(result, str(exc) if isinstance(exc, DetectionError)
                              else "材料为空或超过容量上限", started)
    viewer = _pick_boundary_recipients(req.recipient)[Boundary.B2_VIEW_DISPLAY.value]
    categories = reversible_categories(req.identity, viewer)
    mapping = MappingTable()
    masked, _issued = mask_necessary(prepared.text, prepared.spans, req.session_id,
                                     mapping, categories)
    result.original_text = prepared.text
    result.sanitized_text = masked
    result.spans = [span.to_dict() for span in prepared.spans]
    result.mapping_table = {key.split("::", 1)[-1]: value
                            for key, value in mapping.export(req.session_id).items()}
    result.decision_lane = "reversible_notice"
    result.decisions = [{
        "action": "PSEUDONYMIZE",
        "categories": [span.category],
        "reason": "联系通知的必要字段使用稳定占位符，原文留在本地映射表",
    } for span in prepared.spans if span.category in categories]
    if C.detector_mode() == "dictionary_test":
        result.recognition_assurance = "dictionary_test_unverified"
        result.warnings.append("词典测试模式的识别未经 GLiNER 验证。")
    return _pause_request(result, "联系通知已完成本地占位，未调用云端模型。", started)


def run_pipeline(req: ShieldRequest, send_model: bool = True) -> PipelineResult:
    try:
        with material_scope(req.materials, req.task):
            return _run_pipeline(req, send_model)
    except SourcePolicyError as exc:
        result = PipelineResult(False, req.session_id, req.task, req.identity, req.recipient)
        return _pause_request(result, str(exc), time.perf_counter())


def _run_pipeline(req: ShieldRequest, send_model: bool = True) -> PipelineResult:
    """执行一次完整的受控处理流程。"""
    t_all = time.perf_counter()
    timings: Dict[str, float] = {}
    warnings: List[str] = []

    result = PipelineResult(
        ok=True, session_id=req.session_id, task=req.task,
        identity=req.identity, recipient=req.recipient,
    )
    if req.task == CONTACT_NOTICE_TASK:
        return _run_contact_notice(req, result, t_all)
    try:
        analysis = analyze(req.identity, req.task, req.recipient, req.materials,
                           task_description=req.user_instruction,
                           model_loader=get_model, detector_builder=build_detectors,
                           detect=detect_and_segment, scorer=necessity_scorer)
    except ProcessingFailure as exc:
        if exc.stage in {"access", "provide"}:
            result.access_ok = False
            result.access_reason = str(exc)
        return _pause_request(result, str(exc), t_all)
    text, spans, segments, decisions = (analysis.text, analysis.spans,
                                        analysis.segments, analysis.decisions)
    result.original_text = text
    result.spans = [s.to_dict() for s in spans]
    timings.update(analysis.timings)
    result.decisions = [d.to_dict() for d in decisions]
    result.decision_lane = "online_necessity_model"
    mapping = MappingTable()
    budget_plan = plan_meeting_budget(
        text, spans, req.user_instruction, req.task, req.session_id, mapping)
    if budget_plan is not None and budget_plan.blocked:
        result.local_completion = budget_plan.record()
        result.timings = timings
        return _pause_request(result, budget_plan.reason, t_all)
    paused = analysis.paused
    if paused is not None and not (
            budget_plan is not None and covers_budget_pause(budget_plan, decisions, segments)):
        result.timings = timings
        return _pause_request(result, paused.reason, t_all)

    # ---------------------------------------------------------- ⑥ 转换
    t0 = time.perf_counter()
    applied = apply_decisions(text, segments, decisions, req.session_id, mapping)
    if budget_plan is not None:
        budget_plan = seal_external_text(budget_plan, applied["sanitized_text"], req.session_id, mapping)
        if budget_plan.blocked:
            result.local_completion = budget_plan.record()
            result.timings = timings
            return _pause_request(result, budget_plan.reason, t_all)
        applied["sanitized_text"] = budget_plan.external_text
        applied["paused"] = False
        applied["pause_reason"] = ""
        result.local_completion = budget_plan.record()
        applied["mapping"] = mapping.export(req.session_id)
        result.decisions.append({
            "seg_id": "local-budget",
            "action": budget_plan.necessity_action,
            "boundary_action": budget_plan.boundary_action,
            "categories": ["BUDGET"],
            "reason": "任务必要性是泛化到千元量级；外发边界不接收预算，泛化结果只在授权展示时补回。",
            "hard_checks": [],
            "necessity_scores": {},
            "utility_warning": "",
            "fallback": False,
        })
    timings["transform_ms"] = (time.perf_counter() - t0) * 1000
    observe("transform_ms", timings["transform_ms"])
    result.sanitized_text = applied["sanitized_text"]
    result.aggregates = applied["aggregates"]
    result.mapping_table = {k.split("::", 1)[-1]: v for k, v in applied["mapping"].items()}
    placeholders = set(applied["mapping"].values())
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
    gateway = EgressGateway(get_auditor(), generated_pseudonyms=placeholders)
    bmap = _pick_boundary_recipients(req.recipient)
    # Candidate output stays inside the server until a publication check passes.
    candidate_output = ""

    result.decision_lane = "online_necessity_model"
    if C.detector_mode() == "dictionary_test":
        result.recognition_assurance = "dictionary_test_unverified"
        warnings.append("词典测试模式只使用正则和词典，识别未经 GLiNER 验证，不能视为安全可靠。")
        result.warnings = warnings
        result.timings = timings
        result.boundaries.append({
            "boundary": Boundary.B1_MODEL_INPUT.value,
            "recipient": bmap[Boundary.B1_MODEL_INPUT.value],
            "blocked": True,
            "blocked_reason": "词典测试模式的识别结果未经验证，已暂停外发",
            "allowed": False,
            "leaked_categories": [], "leak_hits": [], "latency_ms": 0.0,
            "recipient_type": "EXTERNAL_MODEL",
        })
        return _pause_request(
            result,
            "词典测试模式的识别结果未经验证，已暂停外发。没有 API 密钥时不会调用云端模型。",
            t_all,
        )

    # 边界 1：发送给模型
    if send_model and result.sanitized_text.strip():
        t0 = time.perf_counter()
        r1 = gateway.send_to_model(req.task, result.sanitized_text, req.identity,
                                   spans, allowed_values, placeholders=placeholders)
        timings["model_ms"] = (time.perf_counter() - t0) * 1000
        observe("model_ms", timings["model_ms"])
        result.boundaries.append(r1["record"].to_dict())
        if r1["allowed"]:
            candidate_output = r1["text"]
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
    display_src = candidate_output or result.sanitized_text
    restore_allowed = can_restore(req.identity, b2_rec)
    result.display_text = mapping.restore_text(req.session_id, display_src, restore_allowed)
    if budget_plan is not None and not budget_plan.blocked:
        amount_allowed = boundary_allows_generalized_budget(req.identity, b2_rec, req.task)
        result.display_text = present_amount(result.display_text, budget_plan, amount_allowed)
        result.local_completion = budget_plan.record()
    if restore_allowed and result.display_text != display_src:
        warnings.append("已按授权将代号恢复为真实姓名（身份与接收方均允许）")

    # 经授权恢复出的真实姓名属于合法披露，必须加入白名单，
    # 否则值级检测会把「按权限恢复的姓名」误判成泄露。
    b2_allowed = set(allowed_values)
    if restore_allowed:
        b2_allowed.update(result.mapping_table.keys())

    r2 = gateway.send_to_viewer(b2_rec, result.display_text, req.identity, spans,
                                b2_allowed, task_key=req.task, placeholders=placeholders)
    result.boundaries.append(r2["record"].to_dict())
    if not r2["allowed"]:
        result.display_text = ""
        warnings.append(f"边界2（结果展示）被拦截：{r2['record'].blocked_reason}")
    # Compatibility field: it now contains only the approved viewer output.
    result.model_output = result.display_text

    # 边界 3：模拟外发
    b3_rec = bmap[Boundary.B3_TOOL_EGRESS.value]
    egress_src = candidate_output or result.sanitized_text
    if budget_plan is not None and not budget_plan.blocked:
        egress_src = strip_held(egress_src, budget_plan)
    r3 = gateway.send_to_tool(b3_rec, egress_src, req.identity, spans,
                              allowed_values, task_key=req.task, placeholders=placeholders)
    result.boundaries.append(r3["record"].to_dict())
    if r3["allowed"]:
        result.egress_text = r3["text"]
    else:
        warnings.append(f"边界3（工具外发）被拦截：{r3['record'].blocked_reason}")

    result.warnings = warnings
    timings["total_ms"] = (time.perf_counter() - t_all) * 1000
    observe("total_ms", timings["total_ms"])
    result.timings = timings
    primary_record = next((b for b in result.boundaries if b["recipient"] == req.recipient), None)
    result.ok = not (primary_record and primary_record["blocked"] and
                     not (not send_model and req.recipient == "external_model"))
    return result


def preview_only(req: ShieldRequest) -> PipelineResult:
    try:
        with material_scope(req.materials, req.task):
            return _preview_only(req)
    except SourcePolicyError as exc:
        result = PipelineResult(False, req.session_id, req.task, req.identity, req.recipient)
        return _pause_request(result, str(exc), time.perf_counter())


def _preview_only(req: ShieldRequest) -> PipelineResult:
    """只跑到本地模型决策，不调用云端模型、不外发。"""
    started = time.perf_counter()
    r = PipelineResult(True, req.session_id, req.task, req.identity, req.recipient)
    try:
        analysis = analyze(req.identity, req.task, req.recipient, req.materials,
                           task_description=req.user_instruction,
                           model_loader=get_model, detector_builder=build_detectors,
                           detect=detect_and_segment, scorer=necessity_scorer)
    except ProcessingFailure as exc:
        if exc.stage in {"access", "provide"}:
            r.access_ok = False
            r.access_reason = str(exc)
        return _pause_request(r, str(exc), started)
    r.original_text = analysis.text
    r.spans = [s.to_dict() for s in analysis.spans]
    r.decisions = [
        {**d.to_dict(), "text": seg.text[:200]}
        for d, seg in zip(analysis.decisions, analysis.segments)
    ]
    r.decision_lane = "online_necessity_model"
    r.timings = analysis.timings
    paused = analysis.paused
    if paused is not None:
        return _pause_request(r, paused.reason, started)
    return r
