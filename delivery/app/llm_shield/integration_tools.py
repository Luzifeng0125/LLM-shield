"""Confirmed webhook calls with fixed destinations and durable duplicate suppression."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field

from .config import OUTPUT_DIR, detector_mode
from .integrations import Contract, load_integrations
from .m7_egress.gateway import EgressGateway
from .schema import RecipientType
from .table_workbench import require_local_request
from .workflows import require_owner

router = APIRouter(prefix="/api/integrations/tools", tags=["受控工具"],
                   dependencies=[Depends(require_local_request), Depends(require_owner)])
_KEY = secrets.token_bytes(32)
DATABASE = OUTPUT_DIR / "integrations" / "tool_events.sqlite3"


class ToolInput(Contract):
    tool_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=12000)
    event_id: UUID


class Execution(ToolInput):
    expires_at: int
    approval: str = Field(pattern=r"^[a-f0-9]{64}$")


def _configured(body):
    try:
        settings, revision = load_integrations()
        tool = settings.tools.get(body.tool_id)
        if tool is None:
            raise ValueError("unknown tool")
        url = urlsplit(tool.endpoint)
        safe_scheme = url.scheme == "https" or (
            url.scheme == "http" and url.hostname in {"127.0.0.1", "::1"})
        if (not safe_scheme or not url.hostname or url.username is not None
                or url.password is not None or url.fragment or url.query or url.port == 0
                or any(c.isspace() for c in tool.endpoint)):
            raise ValueError("invalid destination")
    except Exception:
        raise HTTPException(503, "工具未配置或接收地址无效") from None
    token = os.getenv(tool.token_env, "").strip()
    if len(token) < 16:
        raise HTTPException(503, "工具接收凭证未配置")
    return tool, revision, token


def _check(tool, text):
    if detector_mode() == "dictionary_test":
        raise HTTPException(409, "词典测试模式的识别结果未经验证，已暂停外发")
    result = EgressGateway().precheck(
        tool.recipient, tool.identity, text, task_key=tool.task,
        expected_type=RecipientType.EGRESS_TOOL, operation="tool_egress")
    if not result["allowed"]:
        raise HTTPException(409, result["reason"])


def _stamp(body, revision, expires):
    content = json.dumps([body.tool_id, body.text, str(body.event_id), revision, expires],
                         ensure_ascii=True, separators=(",", ":")).encode()
    return hmac.new(_KEY, content, hashlib.sha256).hexdigest()


@router.post("/preview")
def preview(body: ToolInput, response: Response):
    response.headers["Cache-Control"] = "no-store"
    tool, revision, _ = _configured(body)
    _check(tool, body.text)
    expires = int(time.time()) + 120
    return {"text": body.text, "recipient": tool.recipient, "endpoint": tool.endpoint,
            "expires_at": expires, "approval": _stamp(body, revision, expires)}


def _reserve(body, revision):
    # No text or response bodies are persisted. A pending event is never resent.
    path = Path(DATABASE)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps([body.tool_id, body.text, revision],
                                     ensure_ascii=True).encode()).hexdigest()
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, digest TEXT NOT NULL, state TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT digest,state FROM events WHERE id=?", (str(body.event_id),)).fetchone()
        if previous:
            if previous[0] != digest:
                raise HTTPException(409, "同一操作编号不能用于不同内容或工具配置")
            if previous[1] == "completed":
                return False
            raise HTTPException(409, "该操作已尝试执行，请先在接收端核对结果")
        db.execute("INSERT INTO events VALUES (?,?,?)", (str(body.event_id), digest, "pending"))
    return True


@router.post("/execute")
def execute(body: Execution, response: Response):
    response.headers["Cache-Control"] = "no-store"
    tool, revision, token = _configured(body)
    if (not time.time() <= body.expires_at <= time.time() + 121
            or not secrets.compare_digest(body.approval, _stamp(body, revision, body.expires_at))):
        raise HTTPException(409, "预览已过期或内容变化，请重新检查并确认")
    _check(tool, body.text)
    if not _reserve(body, revision):
        return {"completed": True, "replayed": True}
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            with client.stream("POST", tool.endpoint,
                               headers={"Authorization": "Bearer " + token,
                                        "Idempotency-Key": str(body.event_id)},
                               json={"text": body.text, "event_id": str(body.event_id)}) as upstream:
                upstream.raise_for_status()
                raw = bytearray()
                for chunk in upstream.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 32000:
                        raise ValueError("response too large")
        # The response is untrusted data. Check it before exposing success.
        answer = bytes(raw).decode("utf-8")
        _check(tool, answer)
    except Exception:
        # Preserve pending state because the receiver may have performed the action.
        raise HTTPException(409, "接收结果未通过确认，请在接收端核对；本机不会自动重复执行") from None
    with closing(sqlite3.connect(DATABASE, timeout=5)) as db, db:
        db.execute("UPDATE events SET state='completed' WHERE id=?", (str(body.event_id),))
    return {"completed": True, "replayed": False}
