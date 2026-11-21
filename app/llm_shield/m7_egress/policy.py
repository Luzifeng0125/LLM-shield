"""Optional local OPA authorization for egress operations."""

from __future__ import annotations

import os

import httpx

from ..config import load_env


def policy_mode() -> str:
    load_env()
    return os.getenv("SHIELD_EGRESS_POLICY", "off").strip().lower()


def policy_denial(identity: str, task: str, recipient: str, operation: str) -> str:
    """Send policy identifiers only. All local access and payload checks still apply."""
    mode = policy_mode()
    if mode == "off":
        return ""
    if mode != "opa":
        return "外发策略配置无效，已暂停"

    try:
        port = int(os.getenv("SHIELD_OPA_PORT", "8181"))
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
        with httpx.Client(timeout=1.0, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                f"http://127.0.0.1:{port}/v1/data/shield/egress/allow",
                json={"input": {"identity": identity, "task": task,
                                "recipient": recipient, "operation": operation}},
            )
            response.raise_for_status()
            decision = response.json()
    except (httpx.HTTPError, ValueError):
        return "本地外发策略服务不可用，已暂停"

    if isinstance(decision, dict):
        if decision.get("result") is True:
            return ""
        if decision.get("result") is False:
            return "本地外发策略未授权当前操作，已暂停"
    return "本地外发策略没有返回有效许可，已暂停"
