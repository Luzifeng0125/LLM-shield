"""Extra checks run after local authorization and sensitive-payload checks."""
from __future__ import annotations

import os
import re

import httpx

from .integrations import load_integrations
from .material_policy import require_source_access


def boundary_denial(content: str, phrases: tuple[str, ...]) -> str:
    text = content.casefold()
    if any(phrase.casefold() in text for phrase in phrases if phrase):
        return "隐盾本地策略拒绝当前内容，请修订后重试"
    return ""


def extra_denial(content: str, recipient: str, *, local_only: bool = False,
                 stage: str = "model_input") -> str:
    try:
        settings, _ = load_integrations()
        if settings.policies.enabled:
            phrases = tuple(settings.policies.deny_phrases) + tuple(settings.policies.boundaries.get(stage, ()))
            denial = boundary_denial(content, phrases)
            if denial:
                return denial
            for rule in settings.policies.rules:
                if stage in rule.stages and re.search(rule.regex, content):
                    return "隐盾边界策略拒绝当前内容，规则 " + rule.name
        if local_only:
            return ""
        # Authorized viewer content can contain restored names. Never forward it.
        from .config import recipients

        kind = recipients().get(recipient, {}).get("type")
        if not settings.lakera.enabled or kind == "VIEWER":
            return ""
        key = os.getenv("SHIELD_LAKERA_API_KEY", "").strip()
        if not settings.lakera.approved_for_checked_content or not key:
            return "Lakera 接收范围或凭证未配置，已暂停"
        require_source_access()
        with httpx.Client(timeout=5.0, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                settings.lakera.base_url + "/v2/guard",
                headers={"Authorization": "Bearer " + key},
                json={"messages": [{"role": "user", "content": content}]},
            )
            response.raise_for_status()
            data = response.json()
        require_source_access()
        # Detect-only policies explicitly cannot authorize release.
        if data.get("action") != "enforce" or type(data.get("flagged")) is not bool:
            return "Lakera 未返回强制执行策略结果，已暂停"
        if data["flagged"]:
            return "Lakera 策略拒绝当前内容，已暂停"
        return ""
    except Exception:
        return "附加防护服务或配置不可用，已暂停"
