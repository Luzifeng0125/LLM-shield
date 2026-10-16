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


def use_gliner() -> bool:
    """是否启用 GLiNER v3 语义实体识别（模块 ② / v3 A 层的模型增强）。

    默认 **关闭**。GLiNER 只负责**语义类**（人名/组织/地点/宿舍/敏感属性），
    格式类（电话/邮箱/学号/证件/银行卡/密钥/微信/预算/成绩）仍由正则底座负责。

    启用：.env 设置 SHIELD_USE_GLINER=true；模型路径用 SHIELD_GLINER_MODEL_DIR
    覆盖（默认 D:\\project\\models\\gliner_v3，必须在 ASCII 路径，见 gliner_ner.py）。
    """
    load_env()
    return os.getenv("SHIELD_USE_GLINER", "false").strip().lower() in (
        "1", "true", "yes", "on")


def gliner_model_dir() -> str:
    """GLiNER v3 模型目录（必须在 ASCII 路径，sentencepiece 不支持中文路径）。"""
    load_env()
    return os.getenv("SHIELD_GLINER_MODEL_DIR", r"D:\project\models\gliner_v3")


def reviewed_ner_settings() -> tuple[str, str]:
    """人工 gold NER 候选产物的目录与设备；目录为空表示不启用。

    与 GLiNER 是两条**互相独立**的可选识别增强链路，可分别开启：

    - GLiNER：``SHIELD_USE_GLINER=true`` 开关 + ``SHIELD_GLINER_MODEL_DIR`` 路径；
    - 人工 gold NER：``SHIELD_REVIEWED_NER_MODEL_DIR`` **非空即启用**（默认空）。

    目录内应含 ``artifact_manifest.json``；留空则保持原识别链不变。
    产物元数据只记录来源，**不能**独立证明该数据经过人工复核。
    """
    load_env()
    return (os.getenv("SHIELD_REVIEWED_NER_MODEL_DIR", "").strip(),
            os.getenv("SHIELD_REVIEWED_NER_DEVICE", "cpu").strip().lower())


def reviewed_ner_decoding() -> str:
    """Explicit candidate BIO decoding; default preserves original argmax behavior."""
    load_env()
    return os.getenv("SHIELD_REVIEWED_NER_DECODING", "greedy").strip().lower()


def action_model_path() -> Path:
    """本机动作候选权重；相对路径以 app 为根，留空使用交付权重。"""
    load_env()
    configured = os.getenv("SHIELD_ACTION_MODEL_PATH", "").strip()
    path = Path(configured).expanduser() if configured else ROOT / "models" / "necessity_action.joblib"
    return (path if path.is_absolute() else ROOT / path).resolve()


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
