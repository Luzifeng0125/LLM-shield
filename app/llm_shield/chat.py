"""本机多轮对话。历史只存脱敏文本，原值匹配信息与映射独立保存在会话内存。"""
from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass, field, replace

from . import config as C
from .chat_retrieval import CountQuery, select_for_chat, table_turn
from .m1_access.identity import check_provide
from .m1_access.identity import check_read
from .m2_detect.pipeline import build_detectors, detect_and_segment
from .m4_necessity.model import get_model, necessity_scorer
from .m6_transform.anonymizer import apply_decisions
from .m6_transform.mapping import MappingTable
from .m7_egress.gateway import EgressGateway
from .metrics import observe
from .material_policy import is_expired, material_denial, material_scope, SourcePolicyError
from .processing import ProcessingFailure, analyze
from .stage_trace import StageTrace
from .m5_utility.estimator import estimate
from .schema import Action, Material, Span

MAX_SESSIONS = 64
SESSION_TTL_SECONDS = 1800
MAX_TURNS = 20
MAX_TURN_CHARS = 24000
MAX_HISTORY_CHARS = 64000


class ChatError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class ChatSession:
    session_id: str
    identity: str
    task: str
    task_description: str
    messages: list[dict] = field(default_factory=list)
    private_spans: list[Span] = field(default_factory=list)
    allowed_values: set[str] = field(default_factory=set)
    mapping: MappingTable = field(default_factory=MappingTable)
    touched_at: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: bool = True
    local_only_indexes: set[int] = field(default_factory=set)
    count_query: CountQuery | None = None
    material_policies: dict[str, Material] = field(default_factory=dict)


class ChatStore:
    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        self.lock = threading.Lock()

    def _expire(self):
        now = time.monotonic()
        for sid, session in list(self.sessions.items()):
            source_expired = bool(material_denial(list(session.material_policies.values()), session.task))
            if session.active and now - session.touched_at <= SESSION_TTL_SECONDS and not source_expired:
                continue
            if not session.lock.acquire(blocking=False):
                continue
            try:
                self._clear(session)
                del self.sessions[sid]
            finally:
                session.lock.release()

    @staticmethod
    def _clear(session: ChatSession) -> None:
        session.active = False
        session.messages.clear()
        session.private_spans.clear()
        session.allowed_values.clear()
        session.local_only_indexes.clear()
        session.count_query = None
        session.material_policies.clear()
        session.mapping.clear_session(session.session_id)

    def stats(self) -> dict:
        with self.lock:
            self._expire()
            return {"active_sessions": len(self.sessions), "max_sessions": MAX_SESSIONS,
                    "ttl_seconds": SESSION_TTL_SECONDS}

    def close(self) -> None:
        """Clear process-local private state when the server shuts down."""
        with self.lock:
            for session in self.sessions.values():
                with session.lock:
                    self._clear(session)
            self.sessions.clear()

    def create(self, identity: str, task: str, description: str = "") -> ChatSession:
        if not isinstance(C.tasks().get(task), dict) or not isinstance(C.identities().get(identity), dict):
            raise ChatError("未知任务或身份")
        if C.tasks()[task].get("workflow") == "assignment":
            raise ChatError("替身分配须使用项目工作流接口", 400)
        if C.tasks()[task].get("workflow") == "notice":
            raise ChatError("此任务请使用名单本机核对与通知入口")
        allowed, _ = check_provide(identity, "external_model")
        if not allowed:
            raise ChatError("该身份未获授权向外部模型发送内容", 403)
        with self.lock:
            self._expire()
            if len(self.sessions) >= MAX_SESSIONS:
                raise ChatError("会话数量已达上限，请先清除不再使用的会话", 429)
            sid = secrets.token_urlsafe(24)
            session = ChatSession(sid, identity, task, description)
            self.sessions[sid] = session
            return session

    def get(self, sid: str) -> ChatSession:
        with self.lock:
            self._expire()
            session = self.sessions.get(sid)
            if session is None:
                raise ChatError("会话不存在或已过期，请新建会话", 404)
            session.touched_at = time.monotonic()
            return session

    def delete(self, sid: str):
        with self.lock:
            session = self.sessions.get(sid)
            if session is None:
                return
            if not session.lock.acquire(blocking=False):
                raise ChatError("本轮正在处理，请完成后再清除会话", 409)
            try:
                self._clear(session)
                del self.sessions[sid]
            finally:
                session.lock.release()

    def invalidate_material(self, doc_id: str) -> None:
        """Deleting a source also invalidates histories derived from that source."""
        with self.lock:
            affected = [s for s in self.sessions.values() if doc_id in s.material_policies]
            locked = []
            try:
                for session in affected:
                    if not session.lock.acquire(blocking=False):
                        raise ChatError("材料正用于本轮处理，请完成后再删除", 409)
                    locked.append(session)
                for session in affected:
                    self._clear(session)
                    del self.sessions[session.session_id]
            finally:
                for session in locked:
                    session.lock.release()


STORE = ChatStore()


def snapshot(session: ChatSession) -> dict:
    with session.lock:
        if not session.active or material_denial(list(session.material_policies.values()), session.task):
            ChatStore._clear(session)
            raise ChatError("会话来源已失效，请新建会话", 410)
        with material_scope(list(session.material_policies.values()), session.task):
            return {"session_id": session.session_id, "identity": session.identity,
                    "task": session.task, "messages": copy.deepcopy(session.messages),
                    "turns": len(session.messages) // 2, "max_turns": MAX_TURNS}


def send_turn(session: ChatSession, materials: list[Material]) -> dict:
    try:
        with material_scope([*session.material_policies.values(), *materials], session.task):
            return _send_turn(session, materials)
    except SourcePolicyError as exc:
        with session.lock:
            if material_denial(list(session.material_policies.values()), session.task):
                ChatStore._clear(session)
        return {"ok": False, "paused": True, "pause_reason": str(exc), "messages": [],
                "decisions": [], "session_id": session.session_id, "turns": 0}


def decision_context(session: ChatSession) -> str:
    """构造传给决策器的对话上下文。

    isolated（默认）：返回空串——历史里既有用户消息也有**外部模型回复**，
    后者可被诱导生成任意文本，一旦进入 m4 的 [CONTEXT] 特征就能小幅改变动作
    概率（P0-3 实测 0.9012→0.9151）。隔离后决策只由「本地材料 + 用户任务 +
    身份/接收方」决定。
    legacy：保留旧行为，仅用于对照实验与回滚。
    """
    if C.decision_context_mode() == "isolated":
        return ""
    return "\n".join(m["content"] for m in session.messages[-4:])[-2000:]


def _send_turn(session: ChatSession, materials: list[Material]) -> dict:
    if not session.lock.acquire(blocking=False):
        raise ChatError("上一轮仍在处理，请勿重复提交", 409)
    started = time.perf_counter()
    trace = StageTrace()
    try:
        if not session.active:
            raise ChatError("会话已清除，请新建会话", 404)
        def paused(reason, decisions=None, stage=None):
            if stage:
                trace.mark(stage, "blocked", "本阶段未通过，本轮已暂停")
            return {"ok": False, "paused": True, "pause_reason": reason,
                    "messages": copy.deepcopy(session.messages), "decisions": decisions or [],
                    "session_id": session.session_id, "turns": len(session.messages) // 2,
                    "stages": trace.items}

        if len(session.messages) // 2 >= MAX_TURNS:
            return paused("已达单会话轮数上限，请新建会话；历史不会被静默截断")
        denial = material_denial([*session.material_policies.values(), *materials], session.task)
        if denial:
            return paused(denial)
        policies = {m.doc_id: replace(m, title="", text="", rows=None, columns=None)
                    for m in materials if m.expires_at is not None or m.allowed_purposes is not None
                    or (m.doc_type == "uploaded" and m.doc_id != "chat-input")}
        context = decision_context(session)
        question = "\n".join(m.text for m in materials if m.doc_id == "chat-input")
        exact = table_turn(materials, question, session.count_query)
        if exact is not None:
            access = check_read(session.identity, materials)
            provided, _ = check_provide(session.identity, "external_model")
            if not access.ok or access.denied_docs or not provided:
                return paused("当前身份无权处理该材料", stage="access")
            trace.mark("access", "passed", "已核对本轮材料读取与处理权限")
            for key in ("detect", "policy", "constraints", "transform", "utility", "gateway"):
                trace.mark(key, "skipped", "本机精确统计路径，本轮不经过此阶段")
            trace.mark("output", "passed", "本机统计完成，未调用生成模型")
            safe_question, answer, count_query, checked_values = exact
            # For follow-ups, inspect each value interpolated into the fixed local result.
            # Fixed field labels, counters and response wording do not come from the file.
            gateway = EgressGateway()
            if not all(gateway.precheck("external_model", session.identity, content,
                                       task_key=session.task)["allowed"]
                       for content in checked_values):
                return paused("本机统计结果未通过敏感信息复检")
            messages = session.messages + [{"role": "user", "content": safe_question},
                                           {"role": "assistant", "content": answer}]
            if sum(len(m["content"]) for m in messages) > MAX_HISTORY_CHARS:
                return paused("上下文超过容量上限，请新建会话")
            session.messages = messages
            session.count_query = count_query
            session.local_only_indexes.update((len(messages) - 2, len(messages) - 1))
            session.material_policies.update(policies)
            session.touched_at = time.monotonic()
            return {"ok": True, "paused": False, "session_id": session.session_id,
                    "messages": copy.deepcopy(messages), "turns": len(messages) // 2,
                    "sanitized_user": safe_question, "reply": answer,
                    "engine": "local", "warning": "本机统计结果仅在本机显示，不随后续历史外发。", "decisions": [],
                    "stages": trace.items}
        materials = select_for_chat(materials, question, max_chars=MAX_TURN_CHARS,
                                    task_key=session.task, task_description=session.task_description)
        try:
            analysis = analyze(session.identity, session.task, "external_model", materials,
                               task_description=session.task_description, context=context,
                               max_source_chars=MAX_TURN_CHARS,
                               model_loader=get_model, detector_builder=build_detectors,
                               detect=detect_and_segment, scorer=necessity_scorer)
        except ProcessingFailure as exc:
            failed = {"model": "policy", "detect": "detect", "access": "access", "provide": "access"}.get(exc.stage, "access")
            if exc.stage in {"model", "detect", "size", "capacity"}:
                trace.mark("access", "passed", "已核对材料读取与接收方权限")
            if exc.stage == "size":
                return paused("本轮材料为空或超过 24000 字符，请缩短或拆分后重试", stage=failed)
            if exc.stage == "access":
                return paused("包含无权读取的材料，本轮未发送", stage=failed)
            if exc.stage == "model":
                return paused("本地动作模型不可用，本轮未发送", stage=failed)
            if exc.stage == "detect":
                return paused("敏感信息识别失败，本轮未发送", stage=failed)
            if exc.stage == "capacity":
                return paused(str(exc))
            return paused("外发权限已失效，本轮未发送")
        text, spans, segments, decisions = (analysis.text, analysis.spans,
                                            analysis.segments, analysis.decisions)
        descriptions = [d.to_dict() for d in decisions]
        trace.mark("access", "passed", "已核对材料读取与接收方权限", analysis.timings.get("access_ms"))
        trace.mark("detect", "passed", f"识别到 {len(spans)} 处敏感实体，形成 {len(segments)} 个处理单元", analysis.timings.get("detect_ms"))
        scored = sum(bool(d.necessity_scores) for d in decisions)
        unscored = sum(bool(d.categories) and not d.necessity_scores for d in decisions)
        trace.mark("policy", "blocked" if unscored else ("passed" if scored else "skipped"),
                   f"{unscored} 个敏感单元未取得有效动作概率" if unscored else
                   (f"{scored} 个敏感单元取得动作概率；概率不是准确率" if scored else "本轮没有需要模型评分的敏感单元"))
        checked = sum(bool(d.hard_checks) for d in decisions)
        trace.mark("constraints", "passed" if checked else "skipped",
                   (f"已对 {checked} 个单元检查动作可执行性、用途与接收方权限；动作评分与约束合计 {analysis.timings.get('decide_ms', 0):.2f} ms"
                    if checked else "本轮没有进入硬约束检查的模型动作"))
        rejected = analysis.paused
        if rejected:
            return paused(rejected.reason, descriptions, stage="constraints" if rejected.hard_checks else "policy")
        staged_mapping = copy.deepcopy(session.mapping)
        applied = apply_decisions(text, segments, decisions, session.session_id, staged_mapping)
        trace.mark("transform", "passed", "已按通过检查的动作生成脱敏内容；原值映射仅留在本机")
        safe_user = applied["sanitized_text"].strip()
        if not safe_user:
            return paused("处理后没有可发送内容，请补充非敏感任务信息", descriptions)
        utility = estimate(safe_user, session.task, applied.get("aggregates"), decisions)
        if not utility["evaluated"]:
            trace.mark("utility", "skipped", "当前任务尚无本地完整性自检规则")
        elif utility["warnings"]:
            trace.mark("utility", "warning", f"规则自检提示 {len(utility['warnings'])} 项待核对；此提示不改变模型动作或权限")
        else:
            trace.mark("utility", "passed", "规则自检未发现已定义的完整性缺项；不代表人工确认任务已完成")
        messages = session.messages + [{"role": "user", "content": safe_user}]
        if sum(len(m["content"]) for m in messages) > MAX_HISTORY_CHARS:
            return paused("上下文超过容量上限，请新建会话；历史不会被静默截断", descriptions)
        private_spans = session.private_spans + spans
        retained = session.allowed_values | {
            s.text for segment, decision in zip(segments, decisions)
            if decision.action == Action.RETAIN for s in segment.spans}
        model_started = time.perf_counter()
        outgoing_messages = [m for index, m in enumerate(messages)
                             if index not in session.local_only_indexes]
        response = EgressGateway(generated_pseudonyms=set(
            staged_mapping.export(session.session_id).values())).send_conversation(
                session.task, outgoing_messages, session.identity, private_spans, retained)
        trace.mark("gateway", "passed" if response.get("input_checked") else "blocked",
                   "完整发送载荷已通过复检" if response.get("input_checked") else "发送链路未完成，未确认通过外发前复检")
        observe("chat_model_ms", (time.perf_counter() - model_started) * 1000)
        if not response["allowed"]:
            if response.get("input_checked"):
                trace.mark("output", "blocked", "生成或回答复检未通过")
            return paused(response.get("error") or "外发检查拒绝，本轮未加入历史", descriptions)
        trace.mark("output", "passed", "模拟生成与回答复检通过，未调用真实 API" if response["engine"] == "mock"
                   else "生成与回答复检通过")
        if sum(len(m["content"]) for m in messages) + len(response["text"]) > MAX_HISTORY_CHARS:
            return paused("回答使上下文超过容量，本轮未写入历史，请新建会话", descriptions)
        session.messages = messages + [{"role": "assistant", "content": response["text"]}]
        session.count_query = None
        session.mapping = staged_mapping
        session.private_spans = private_spans
        session.allowed_values = retained
        session.material_policies.update(policies)
        session.touched_at = time.monotonic()
        return {"ok": True, "paused": False, "session_id": session.session_id,
                "messages": copy.deepcopy(session.messages), "turns": len(session.messages) // 2,
                "sanitized_user": safe_user, "reply": response["text"], "engine": response["engine"],
                "warning": response.get("error", ""), "decisions": descriptions,
                "stages": trace.items}
    finally:
        observe("chat_total_ms", (time.perf_counter() - started) * 1000)
        session.lock.release()
