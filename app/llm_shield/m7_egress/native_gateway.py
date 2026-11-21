"""Native model routing with durable admission and content-free usage accounting."""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from ..config import OUTPUT_DIR
from ..integrations import load_integrations
from ..material_policy import require_source_access
from .llm_client import ConfigurationError, OpenAICompatLLM, configuration_status

DATABASE = OUTPUT_DIR / "model_gateway" / "usage.sqlite3"


def configured_route(name):
    try:
        settings, revision = load_integrations()
        config = settings.model_gateway
        if not config.enabled or name not in config.routes:
            raise ValueError("route")
        route = config.routes[name]
        for key in route.targets:
            target = config.targets[key]
            value = {"base_url": target.base_url, "model": target.model,
                     "timeout": target.timeout, "api_key": os.getenv(target.key_env, "").strip()}
            if configuration_status(value) != "configuration_only":
                raise ValueError("target")
        return config, route, revision
    except Exception:
        raise ConfigurationError("隐盾模型路由未启用、未获准或目标配置无效") from None


def connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, currency TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS attempts (
        id TEXT PRIMARY KEY, month TEXT NOT NULL, created REAL NOT NULL,
        route TEXT NOT NULL, target TEXT NOT NULL, revision TEXT NOT NULL,
        amount INTEGER NOT NULL, state TEXT NOT NULL,
        input_tokens INTEGER, output_tokens INTEGER)""")
    return db


def cost(target, input_tokens, output_tokens):
    return (input_tokens * target.input_price + output_tokens * target.output_price + 999999) // 1000000


def reserve(config, revision, route, target, amount):
    now = time.time()
    month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
    event = uuid4().hex
    with closing(connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        currency = db.execute("SELECT currency FROM settings WHERE id=1").fetchone()
        if currency and currency[0] != config.currency:
            raise ConfigurationError("费用账本币种与配置不一致，请先完成账务迁移")
        db.execute("INSERT OR IGNORE INTO settings VALUES (1,?)", (config.currency,))
        count = db.execute("SELECT COUNT(*) FROM attempts WHERE created>?", (now - 60,)).fetchone()[0]
        if count >= config.requests_per_minute:
            raise ConfigurationError("模型请求已达到每分钟限额，请稍后重试")
        used = db.execute("SELECT COALESCE(SUM(amount),0) FROM attempts WHERE month=?", (month,)).fetchone()[0]
        if used + amount > config.monthly_budget:
            raise ConfigurationError("本月模型预算不足，本次未发送")
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,NULL,NULL)",
                   (event, month, now, route, target, revision, amount, "reserved"))
    return event


def settle(event, target, usage):
    valid = (isinstance(usage, dict)
             and type(usage.get("prompt_tokens")) is int
             and type(usage.get("completion_tokens")) is int
             and 0 <= usage["prompt_tokens"] <= 100000000
             and 0 <= usage["completion_tokens"] <= 100000000)
    with closing(connection()) as db, db:
        if valid:
            db.execute("UPDATE attempts SET amount=?,state='reported',input_tokens=?,output_tokens=? WHERE id=?",
                       (cost(target, usage["prompt_tokens"], usage["completion_tokens"]),
                        usage["prompt_tokens"], usage["completion_tokens"], event))
        else:
            db.execute("UPDATE attempts SET state='unconfirmed' WHERE id=?", (event,))


def usage_summary():
    settings, _ = load_integrations()
    config = settings.model_gateway
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with closing(connection()) as db:
        currency = db.execute("SELECT currency FROM settings WHERE id=1").fetchone()
        if currency and currency[0] != config.currency:
            raise ConfigurationError("费用账本币种与配置不一致")
        rows = db.execute("""SELECT target,state,COUNT(*),SUM(amount)
                             FROM attempts WHERE month=? GROUP BY target,state""", (month,)).fetchall()
    return {"month": month, "currency": config.currency, "budget": config.monthly_budget,
            "unit": "millionth_currency",
            "attempts": [{"target": row[0], "state": row[1], "count": row[2], "amount": row[3]} for row in rows]}


class NativeModelGateway:
    name = "real"

    def __init__(self, route):
        self.route = route
        self.attempted_network = False
        configured_route(route)

    def chat(self, system, user, **kwargs):
        return self.chat_messages([{"role": "system", "content": system},
                                   {"role": "user", "content": user}], **kwargs)

    def chat_messages(self, messages, temperature=0.3, max_tokens=2000):
        self.attempted_network = False
        if (not messages or any(not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant"}
                or not isinstance(message.get("content"), str) for message in messages)):
            raise ConfigurationError("模型消息格式无效")
        input_bound = sum(len(message["content"].encode("utf-8")) + 256 for message in messages)
        if input_bound > 96000 or type(max_tokens) is not int or not 1 <= max_tokens <= 16000:
            raise ConfigurationError("模型请求超过本机容量限制")
        config, route, revision = configured_route(self.route)
        for index, key in enumerate(route.targets):
            target = config.targets[key]
            _, _, current_revision = configured_route(self.route)
            if revision != current_revision:
                raise ConfigurationError("模型路由配置已变化，请重新检查")
            require_source_access()
            event = reserve(config, revision, self.route, key, cost(target, input_bound, max_tokens))
            client = OpenAICompatLLM(target.base_url, os.getenv(target.key_env, "").strip(),
                                     target.model, target.timeout)
            try:
                require_source_access()
                self.attempted_network = True
                answer = client.chat_messages(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as exc:
                settle(event, target, None)
                retryable = isinstance(exc, httpx.RequestError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and (exc.response.status_code == 429 or exc.response.status_code >= 500))
                if not retryable or index == len(route.targets) - 1:
                    raise
                continue
            settle(event, target, client.last_usage)
            require_source_access()
            return answer
        raise ConfigurationError("模型路由没有可用目标")
