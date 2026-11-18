"""Extra checks run after local authorization and sensitive-payload checks."""
from __future__ import annotations

import os
from functools import lru_cache
from threading import Lock

import httpx

from .integrations import load_integrations
from .material_policy import require_source_access


class GuardUnavailable(RuntimeError):
    pass


_NEMO_LOCK = Lock()


@lru_cache(maxsize=4)
def _nemo(phrases: tuple[str, ...]):
    from nemoguardrails import LLMRails, RailsConfig

    config = RailsConfig.from_content(
        config={"models": [], "rails": {"input": {"flows": ["shield input"]}}},
        colang_content="""
define flow shield input
  $allowed = execute shield_phrase_check
  if not $allowed
    bot say "SHIELD_BLOCKED"
    stop
""",
    )
    rails = LLMRails(config)

    async def shield_phrase_check(context):
        text = context.get("user_message", "").casefold()
        return not any(phrase.casefold() in text for phrase in phrases if phrase)

    rails.register_action(shield_phrase_check, name="shield_phrase_check")
    return rails


def nemo_denial(content: str, phrases: tuple[str, ...]) -> str:
    with _NEMO_LOCK:
        rails = _nemo(phrases)
        result = rails.check(messages=[{"role": "user", "content": content}])
    if result.status == "passed":
        return ""
    if result.status == "blocked":
        return "本地 NeMo 策略拒绝当前内容，请修订后重试"
    raise GuardUnavailable("NeMo 未返回有效许可")


def extra_denial(content: str, recipient: str) -> str:
    try:
        settings, _ = load_integrations()
        if settings.nemo.enabled:
            denial = nemo_denial(content, tuple(settings.nemo.deny_phrases))
            if denial:
                return denial
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
