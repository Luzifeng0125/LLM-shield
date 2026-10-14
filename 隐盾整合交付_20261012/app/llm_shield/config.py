"""配置加载：读取 config/*.yaml，并提供全局单例访问。

Windows 下必须显式指定 encoding='utf-8'，否则中文按 cp936 解码会报错。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

# 项目根目录（llm_shield/ 的父目录）
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"


def load_env() -> None:
    """加载 .env（若存在）。优先级：已存在的环境变量 > .env 文件。"""
    env_file = ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)


@lru_cache(maxsize=None)
def _load_yaml(name: str) -> Dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"配置文件缺失: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def rules() -> Dict[str, Any]:
    return _load_yaml("rules.yaml")


def tasks() -> Dict[str, Any]:
    return _load_yaml("tasks.yaml")


def recipients() -> Dict[str, Any]:
    return _load_yaml("recipients.yaml")


def identities() -> Dict[str, Any]:
    return _load_yaml("identities.yaml")


def category_meta(category: str) -> Dict[str, Any]:
    """取某个敏感类别的元信息，未知类别按默认中级处理。"""
    return rules().get("categories", {}).get(category, {"name": category, "level": 2, "hard_ban": False})


def category_level(category: str) -> int:
    return int(category_meta(category).get("level", 2))


def action_cost(action: str) -> float:
    return float(rules().get("actions", {}).get(action, {}).get("disclosure_cost", 5))


def use_campus_ner() -> bool:
    """是否启用 ★ 领域预训练 NER（模块 ② 的可选增强）。

    默认 **关闭**。原因：
    - 规则+词典底座已能满足「P95 ≤ 500ms」，实测 2000 字约 6ms；
    - 领域模型推理更慢（实测 2000 字约 576ms），且当前用合成数据训练的版本
      在分布外文本上泛化有限，可能引入错误片段；
    - 因此作为可选增强，需显式开启（.env: SHIELD_USE_CAMPUS_NER=true）。

    权重存在（models/campus_ner）只是前提，是否启用由本开关决定。
    """
    load_env()
    return os.getenv("SHIELD_USE_CAMPUS_NER", "false").strip().lower() in (
        "1", "true", "yes", "on")


def llm_settings() -> Dict[str, Any]:
    """大模型接入设置（模块 ⑦）。

    LLM_MODE: mock=强制模拟 / real=强制真实 / auto=有 key 走真实，失败回落 mock
    """
    load_env()
    return {
        "mode": os.getenv("LLM_MODE", "auto").lower(),
        "provider": os.getenv("LLM_PROVIDER", "deepseek"),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "model": os.getenv("LLM_MODEL", "deepseek-flash"),
        "timeout": float(os.getenv("LLM_TIMEOUT", "60")),
    }
