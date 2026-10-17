"""模块 ⑦ 云端大模型接入（OpenAI 兼容格式，已适配 DeepSeek）。

三种模式（.env 的 LLM_MODE）：
  mock —— 强制本地模拟，完全离线，演示与自动化评测可复现
  real —— 强制真实 API，失败即报错
  auto —— 未配置密钥时离线演示；已配置密钥时真实调用，失败即暂停

安全约定：API Key 从本机配置读取，仅通过认证头发送给配置的服务端，不写日志。
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

import httpx

from ..config import llm_settings


def _public_api_error(exc: Exception) -> str:
    """Expose a useful failure class without leaking upstream bodies or keys."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"真实模型请求失败（HTTP {exc.response.status_code}）"
    if isinstance(exc, httpx.TimeoutException):
        return "真实模型请求超时"
    if isinstance(exc, httpx.RequestError):
        return "真实模型网络连接失败"
    return f"真实模型调用失败（{type(exc).__name__}）"


class BaseLLM:
    name = "base"

    def chat(self, system: str, user: str, **kwargs) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------- Mock


class MockLLM(BaseLLM):
    """本地模拟模型：不联网，按任务模板产出结构化回复，保证演示与评测可复现。"""

    name = "mock"

    _COUNT_RE = __import__("re").compile(r"(\d+)\s*(人|名|位)")
    _CODE_RE = __import__("re").compile(r"(人员[甲乙丙丁戊己庚辛壬癸\d]+|组织[甲乙丙丁戊己庚辛壬癸\d]+)")

    def chat(self, system: str, user: str, **kwargs) -> str:
        if "活动通知助手" in system:
            from ..notice import NOTICE_ITEMS
            title = next((line.removeprefix("活动名称：") for line in user.splitlines()
                          if line.startswith("活动名称：")), "活动")
            items = [item for item in NOTICE_ITEMS.values() if item in user]
            return ("【模拟模型输出 · 通知草稿】\n" + title + "活动通知\n\n"
                    + "各位参与者：\n" + "\n".join(items)
                    + "\n\n活动时间、地点等具体安排将另行通知。"
                    + "\n（本地模拟草稿，未调用外部模型。）")
        task_hint = ""
        for key in ("活动统计", "会议纪要", "项目介绍", "对外介绍"):
            if key in system:
                task_hint = key
                break

        if task_hint == "活动统计":
            n = self._COUNT_RE.search(user)
            count = n.group(1) if n else "若干"
            return (
                "【模拟模型输出】\n"
                f"一、参与情况：本次活动共 {count} 人参与，人员明细已在本地聚合，未上传至本模型。\n"
                "二、活动过程：按既定流程完成场地布置、签到与现场执行，整体秩序良好。\n"
                "三、问题与改进：签到环节存在排队现象，建议下次增设签到通道；宣传覆盖面仍有提升空间。\n"
                "四、总结：活动目标基本达成，建议保留本次经验并形成标准化流程文档。\n"
                "（说明：以上为本地模拟输出，未调用任何外部接口。）"
            )

        if task_hint == "会议纪要":
            codes = sorted(set(self._CODE_RE.findall(user))) or ["人员甲"]
            lines = "\n".join(
                [f"  {i+1}. {c}：按会议分工推进所负责事项，并在约定期限前提交成果。"
                 for i, c in enumerate(codes[:6])])
            return (
                "【模拟模型输出】\n"
                "会议纪要（已做代号化处理）\n"
                f"{lines}\n"
                "待办跟进：各项任务的负责人、事项与期限已在本机保持一一对应，"
                "本模型仅接收到代号化内容，未接触真实姓名与联系方式。\n"
                "（说明：以上为本地模拟输出，未调用任何外部接口。）"
            )

        return (
            "【模拟模型输出】\n"
            "项目简介：本项目面向校园场景，聚焦流程规范化与协作效率提升，"
            "已按披露规则移除内部预算、联系方式等受限信息。\n"
            "核心内容：已完成需求梳理与方案设计，形成可对外介绍的公开事实清单。\n"
            "下一步：推进试点验证并收集反馈。\n"
            "（说明：以上为本地模拟输出，未调用任何外部接口。）"
        )


# ---------------------------------------------------------------- 真实 API


class OpenAICompatLLM(BaseLLM):
    """OpenAI 兼容接口客户端（DeepSeek / 通义 / 智谱 / 本地 vLLM 等）。"""

    name = "real"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.last_error = ""

    def chat(self, system: str, user: str, temperature: float = 0.3,
             max_tokens: int = 2000) -> str:
        return self.chat_messages([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], temperature=temperature, max_tokens=max_tokens)

    def chat_messages(self, messages: List[dict], temperature: float = 0.3,
                      max_tokens: int = 2000) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("生成服务未返回有效回答")

            msg = choices[0].get("message") or {}
            content = (msg.get("content") or "").strip()

            if not content:
                raise ValueError("生成服务没有可展示的最终回答")
            if choices[0].get("finish_reason") == "length":
                content += "\n（回答达到长度上限，可继续追问。）"
            return content
        except Exception as exc:
            # 不打印 payload，避免把已脱敏内容写进日志
            self.last_error = type(exc).__name__
            raise


# ---------------------------------------------------------------- 工厂


_CLIENT: Optional[BaseLLM] = None


def get_llm_client(force: Optional[str] = None) -> BaseLLM:
    """按配置返回客户端实例（模块级缓存）。"""
    global _CLIENT
    if _CLIENT is not None and force is None:
        return _CLIENT

    s = llm_settings()
    mode = (force or s["mode"]).lower()
    if mode == "mock":
        client: BaseLLM = MockLLM()
    elif not s["api_key"] and mode != "real":
        client = MockLLM()
    else:
        client = OpenAICompatLLM(s["base_url"], s["api_key"], s["model"], s["timeout"])

    if force is None:
        _CLIENT = client
    return client


def chat_with_fallback(system: str, user: str, **kwargs) -> Dict[str, str]:
    """Run the real API when configured; never disguise its failure as a reply.

    :return: {"text": ..., "engine": "real"/"mock", "error": ...}
    """
    s = llm_settings()
    mode = s["mode"].lower()

    if mode == "real" or (mode == "auto" and s["api_key"]):
        try:
            if not s['api_key']:
                raise ValueError('尚未配置生成服务密钥')
            client = OpenAICompatLLM(s["base_url"], s["api_key"], s["model"], s["timeout"])
            text = client.chat(system, user, **kwargs)
            return {"text": text, "engine": "real", "error": ""}
        except Exception as exc:
            return {"text": "", "engine": "error", "error": _public_api_error(exc)}

    return {"text": MockLLM().chat(system, user, **kwargs), "engine": "mock", "error": ""}


def chat_messages_with_fallback(messages: List[dict]) -> Dict[str, str]:
    """发送服务端构造且已整体检查的多轮消息；不展示供应商内部推理字段。"""
    settings = llm_settings()
    mode = settings["mode"]
    if mode == "real" or (mode == "auto" and settings["api_key"]):
        try:
            if not settings["api_key"]:
                raise ValueError("尚未配置生成服务密钥")
            client = OpenAICompatLLM(settings["base_url"], settings["api_key"],
                                     settings["model"], settings["timeout"])
            return {"text": client.chat_messages(messages), "engine": "real", "error": ""}
        except Exception as exc:
            # 供应商异常可能含请求体或凭据，不能回传给界面或历史。
            return {"text": "", "engine": "error", "error": _public_api_error(exc)}
    user_messages = [m["content"] for m in messages if m["role"] == "user"]
    reply = (f"【离线演示回复】\n已接收第 {len(user_messages)} 轮处理后的消息。\n\n"
             f"本轮输入：\n{user_messages[-1][:1200]}\n\n"
             "此回复用于验证会话与防护流程。接入真实生成服务后可获得任务回答。")
    return {"text": reply, "engine": "mock", "error": ""}
