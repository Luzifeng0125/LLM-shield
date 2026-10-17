"""本机多轮对话。历史只存脱敏文本，原值匹配信息与映射独立保存在会话内存。"""
from __future__ import annotations

import copy
import secrets
import threading
import time
from dataclasses import dataclass, field

from . import config as C
from .chat_retrieval import exact_count_for_chat, select_for_chat
from .m1_access.identity import check_provide
from .m1_access.identity import check_read
from .m2_detect.pipeline import build_detectors, detect_and_segment
from .m4_necessity.model import get_model, necessity_scorer
from .m6_transform.anonymizer import apply_decisions
from .m6_transform.mapping import MappingTable
from .m7_egress.gateway import EgressGateway
from .metrics import observe
from .processing import ProcessingFailure, analyze
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


class ChatStore:
    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        self.lock = threading.Lock()

    def _expire(self):
        now = time.monotonic()
        for sid, session in list(self.sessions.items()):
            if now - session.touched_at <= SESSION_TTL_SECONDS:
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


STORE = ChatStore()


def snapshot(session: ChatSession) -> dict:
    with session.lock:
        return {"session_id": session.session_id, "identity": session.identity,
                "task": session.task, "messages": copy.deepcopy(session.messages),
                "turns": len(session.messages) // 2, "max_turns": MAX_TURNS}


def send_turn(session: ChatSession, materials: list[Material]) -> dict:
    if not session.lock.acquire(blocking=False):
        raise ChatError("上一轮仍在处理，请勿重复提交", 409)
    started = time.perf_counter()
    try:
        if not session.active:
            raise ChatError("会话已清除，请新建会话", 404)
        def paused(reason, decisions=None):
            return {"ok": False, "paused": True, "pause_reason": reason,
                    "messages": copy.deepcopy(session.messages), "decisions": decisions or [],
                    "session_id": session.session_id, "turns": len(session.messages) // 2}

        if len(session.messages) // 2 >= MAX_TURNS:
            return paused("已达单会话轮数上限，请新建会话；历史不会被静默截断")
        context = "\n".join(m["content"] for m in session.messages[-4:])[-2000:]
        question = "\n".join(m.text for m in materials if m.doc_id == "chat-input")
        exact = exact_count_for_chat(materials, question)
        if exact is not None:
            access = check_read(session.identity, materials)
            provided, _ = check_provide(session.identity, "external_model")
            if not access.ok or access.denied_docs or not provided:
                return paused("当前身份无权处理该材料")
            safe_question, answer = exact
            gateway = EgressGateway()
            if not all(gateway.precheck("external_model", session.identity, content,
                                       task_key=session.task)["allowed"]
                       for content in (safe_question, answer)):
                return paused("本机统计结果未通过敏感信息复检")
            messages = session.messages + [{"role": "user", "content": safe_question},
                                           {"role": "assistant", "content": answer}]
            if sum(len(m["content"]) for m in messages) > MAX_HISTORY_CHARS:
                return paused("上下文超过容量上限，请新建会话")
            session.messages = messages
            session.touched_at = time.monotonic()
            return {"ok": True, "paused": False, "session_id": session.session_id,
                    "messages": copy.deepcopy(messages), "turns": len(messages) // 2,
                    "sanitized_user": safe_question, "reply": answer,
                    "engine": "local", "warning": "", "decisions": []}
        materials = select_for_chat(materials, question, max_chars=MAX_TURN_CHARS)
        try:
            analysis = analyze(session.identity, session.task, "external_model", materials,
                               task_description=session.task_description, context=context,
                               max_source_chars=MAX_TURN_CHARS,
                               model_loader=get_model, detector_builder=build_detectors,
                               detect=detect_and_segment, scorer=necessity_scorer)
        except ProcessingFailure as exc:
            if exc.stage == "size":
                return paused("本轮材料为空或超过 24000 字符，请缩短或拆分后重试")
            if exc.stage == "access":
                return paused("包含无权读取的材料，本轮未发送")
            if exc.stage == "model":
                return paused("本地动作模型不可用，本轮未发送")
            if exc.stage == "detect":
                return paused("敏感信息识别失败，本轮未发送")
            if exc.stage == "capacity":
                return paused(str(exc))
            return paused("外发权限已失效，本轮未发送")
        text, spans, segments, decisions = (analysis.text, analysis.spans,
                                            analysis.segments, analysis.decisions)
        descriptions = [d.to_dict() for d in decisions]
        rejected = analysis.paused
        if rejected:
            return paused(rejected.reason, descriptions)
        staged_mapping = copy.deepcopy(session.mapping)
        applied = apply_decisions(text, segments, decisions, session.session_id, staged_mapping)
        safe_user = applied["sanitized_text"].strip()
        if not safe_user:
            return paused("处理后没有可发送内容，请补充非敏感任务信息", descriptions)
        messages = session.messages + [{"role": "user", "content": safe_user}]
        if sum(len(m["content"]) for m in messages) > MAX_HISTORY_CHARS:
            return paused("上下文超过容量上限，请新建会话；历史不会被静默截断", descriptions)
        private_spans = session.private_spans + spans
        retained = session.allowed_values | {
            s.text for segment, decision in zip(segments, decisions)
            if decision.action == Action.RETAIN for s in segment.spans}
        model_started = time.perf_counter()
        response = EgressGateway(generated_pseudonyms=set(
            staged_mapping.export(session.session_id).values())).send_conversation(
                session.task, messages, session.identity, private_spans, retained)
        observe("chat_model_ms", (time.perf_counter() - model_started) * 1000)
        if not response["allowed"]:
            return paused(response.get("error") or "外发检查拒绝，本轮未加入历史", descriptions)
        if sum(len(m["content"]) for m in messages) + len(response["text"]) > MAX_HISTORY_CHARS:
            return paused("回答使上下文超过容量，本轮未写入历史，请新建会话", descriptions)
        session.messages = messages + [{"role": "assistant", "content": response["text"]}]
        session.mapping = staged_mapping
        session.private_spans = private_spans
        session.allowed_values = retained
        session.touched_at = time.monotonic()
        return {"ok": True, "paused": False, "session_id": session.session_id,
                "messages": copy.deepcopy(session.messages), "turns": len(session.messages) // 2,
                "sanitized_user": safe_user, "reply": response["text"], "engine": response["engine"],
                "warning": response.get("error", ""), "decisions": descriptions}
    finally:
        observe("chat_total_ms", (time.perf_counter() - started) * 1000)
        session.lock.release()
