"""Operator-owned integration contracts. Secrets remain in environment variables."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config as C


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pattern(Contract):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    regex: str = Field(min_length=1, max_length=500)
    score: float = Field(default=0.85, ge=0, le=1)
    revision: str = Field(default="1", min_length=1, max_length=40)


class Presidio(Contract):
    enabled: bool = False
    patterns: list[Pattern] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_patterns(self):
        names = [pattern.name for pattern in self.patterns]
        definitions = [(pattern.category, pattern.regex) for pattern in self.patterns]
        if len(set(names)) != len(names) or len(set(definitions)) != len(definitions):
            raise ValueError("识别器名称或类别与正则组合重复")
        return self


class Nemo(Contract):
    enabled: bool = False
    deny_phrases: list[str] = Field(default_factory=list, max_length=100)
    boundaries: dict[Literal["model_input", "model_output", "retrieval", "view_display",
                             "tool_egress", "tool_response"], list[str]] = Field(default_factory=dict)


class Lakera(Contract):
    enabled: bool = False
    # Explicit acceptance of this extra recipient, including approved model text.
    approved_for_checked_content: bool = False
    base_url: Literal["https://api.lakera.ai"] = "https://api.lakera.ai"


class LiteLLM(Contract):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:4000/v1"
    approved_models: list[str] = Field(default_factory=list, max_length=20)


class Knowledge(Contract):
    identity: str
    task: str
    recipient: str = "egress_tool_public"
    token_env: str
    doc_ids: list[str] = Field(min_length=1, max_length=20)


class Tool(Contract):
    endpoint: str
    token_env: str
    identity: str
    task: str
    recipient: str


class Integrations(Contract):
    version: Literal[1] = 1
    presidio: Presidio = Field(default_factory=Presidio)
    nemo: Nemo = Field(default_factory=Nemo)
    lakera: Lakera = Field(default_factory=Lakera)
    litellm: LiteLLM = Field(default_factory=LiteLLM)
    knowledge: dict[str, Knowledge] = Field(default_factory=dict)
    tools: dict[str, Tool] = Field(default_factory=dict)


def load_integrations() -> tuple[Integrations, str]:
    C.load_env()
    path = Path(os.getenv("SHIELD_INTEGRATIONS_CONFIG", str(C.CONFIG_DIR / "integrations.yaml")))
    if not path.is_absolute():
        path = C.ROOT / path
    payload = path.read_bytes()
    settings = Integrations.model_validate(yaml.safe_load(payload))
    return settings, hashlib.sha256(payload).hexdigest()
