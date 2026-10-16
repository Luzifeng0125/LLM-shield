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


# ---------------------------------------------------------------- 模型目录
# 全项目**只有一个模型目录**：默认 D:\project\models（纯 ASCII 路径）。
#
# 为什么必须在外面的 ASCII 路径，而不是项目内的 models/：
#   项目根目录名是「隐盾」（含中文），而 sentencepiece 的 C++ 后端**打不开
#   含中文的路径**——GLiNER 的 spm.model 加载会直接 RuntimeError。
#   所以识别模型只能放在 D:\project\models 这类纯 ASCII 目录。
#
# 历史上决策模型放在项目内 models/、识别模型放在 D:\project\models，
# 两个根目录是「搞不清模型到底在哪」的直接原因。现在统一到这一个根：
#   D:\project\models\
#     ├── necessity_action.joblib   决策模型（m4，总是加载）
#     ├── gliner_v3/                识别模型（m2，可选，SHIELD_USE_GLINER=true）
#     ├── gliner_multi_v21/         重训用基座
#     └── gliner_multi/             重训用基座
DEFAULT_MODEL_DIR = r"D:\project\models"


def model_dir() -> Path:
    """所有本地模型的统一根目录（可用 SHIELD_MODEL_DIR 覆盖）。"""
    load_env()
    return Path(os.getenv("SHIELD_MODEL_DIR", DEFAULT_MODEL_DIR))


def necessity_model_path() -> Path:
    """决策模型路径。

    优先取统一模型目录下的 necessity_action.joblib；若那里没有（例如从 Git
    克隆后只带了随包权重的部署方式），回退到项目内 models/ 下的同名文件。
    """
    load_env()
    override = os.getenv("SHIELD_NECESSITY_MODEL", "").strip()
    if override:
        return Path(override)
    primary = model_dir() / "necessity_action.joblib"
    if primary.exists():
        return primary
    return ROOT / "models" / "necessity_action.joblib"


def use_gliner() -> bool:
    """是否启用 GLiNER 语义实体识别（模块 ② 的可选模型增强）。

    GLiNER 只负责**语义类**（人名/组织/地点/宿舍/敏感属性）；格式类
    （电话/邮箱/学号/证件/银行卡/密钥/微信/预算/成绩）由带校验位的正则底座
    权威判定。实测这样分工比让模型覆盖 13 类精度更高（独立集 F1 0.9068 vs 0.8443）。

    启用：.env 设置 ``SHIELD_USE_GLINER=true``；模型路径用
    ``SHIELD_GLINER_MODEL_DIR`` 覆盖（默认 ``<模型目录>/gliner_v3``）。
    """
    load_env()
    return os.getenv("SHIELD_USE_GLINER", "false").strip().lower() in (
        "1", "true", "yes", "on")


def gliner_model_dir() -> str:
    """GLiNER 模型目录（必须在 ASCII 路径，sentencepiece 不支持中文路径）。"""
    load_env()
    override = os.getenv("SHIELD_GLINER_MODEL_DIR", "").strip()
    if override:
        return override
    return str(model_dir() / "gliner_v3")


# ---------------------------------------------------------------- 系统提示词
# 按任务给，避免把敏感原文塞进 system。
#
# ⚠ 措辞是有约束的：这些模板会和脱敏后的材料拼成一个载荷，而外发前会对**整个
# 载荷**重跑识别器。实测两个措辞会被识别器误判并拦掉全部外发：
#   · 「（已脱敏）」   → 被判成 SENSITIVE_ATTR（绝对禁止类别）
#   · 「会议纪要助手」 → 被判成 PERSON_NAME
# 改动本表前请先跑一遍识别器确认干净（tests/test_egress_safety.py 有回归项）。
SYSTEM_PROMPTS = {
    "activity_stats": "你是校园活动总结助手。请基于以下内容撰写活动统计与总结。",
    "meeting_minutes": "你是文本整理助手。请基于以下内容整理会议纪要与任务分派。",
    "project_intro": "你是项目文案助手。请基于以下内容改写为可对外发布的项目介绍。",
}
DEFAULT_SYSTEM_PROMPT = "你是文本处理助手。"


def system_prompt(task_key: str) -> str:
    """取该任务的系统提示词；未知任务回退到通用模板。"""
    return SYSTEM_PROMPTS.get(task_key, DEFAULT_SYSTEM_PROMPT)


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
