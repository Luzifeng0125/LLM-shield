"""Operator-owned integration contracts. Secrets remain in environment variables."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from . import config as C


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pattern(Contract):
    name: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    regex: str = Field(min_length=1, max_length=500)
    score: float = Field(default=0.85, ge=0, le=1)
    revision: str = Field(default="1", min_length=1, max_length=40)


class RecognitionRules(Contract):
    enabled: bool = False
    patterns: list[Pattern] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def unique_patterns(self):
        names = [pattern.name for pattern in self.patterns]
        definitions = [(pattern.category, pattern.regex) for pattern in self.patterns]
        if len(set(names)) != len(names) or len(set(definitions)) != len(definitions):
            raise ValueError("识别器名称或类别与正则组合重复")
        return self


class BoundaryPolicies(Contract):
    enabled: bool = False
    deny_phrases: list[str] = Field(default_factory=list, max_length=100)
    boundaries: dict[Literal["model_input", "model_output", "retrieval", "view_display",
                             "tool_egress", "tool_response"], list[str]] = Field(default_factory=dict)
    rules: list["BoundaryRule"] = Field(default_factory=list, max_length=100)


class BoundaryRule(Contract):
    name: str = Field(min_length=1, max_length=80)
    stages: list[Literal["model_input", "model_output", "retrieval", "view_display",
                         "tool_egress", "tool_response"]] = Field(min_length=1, max_length=6)
    regex: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_expression(self):
        try:
            re.compile(self.regex)
        except re.error:
            raise ValueError("边界策略包含无效正则") from None
        return self


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


class ModelTarget(Contract):
    base_url: str
    model: str = Field(min_length=1, max_length=100)
    key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    disclosure_scope: str = Field(min_length=1, max_length=80)
    timeout: float = Field(default=60, gt=0, le=180, allow_inf_nan=False)
    input_price: int = Field(ge=0, strict=True)
    output_price: int = Field(ge=0, strict=True)


class ModelRoute(Contract):
    targets: list[str] = Field(min_length=1, max_length=5)
    disclosure_scope: str = Field(min_length=1, max_length=80)


class ModelGateway(Contract):
    enabled: bool = False
    currency: Literal["CNY", "USD"] = "CNY"
    monthly_budget: int = Field(default=0, ge=0, strict=True)
    requests_per_minute: int = Field(default=30, ge=1, le=10000, strict=True)
    targets: dict[str, ModelTarget] = Field(default_factory=dict, max_length=20)
    routes: dict[str, ModelRoute] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def approved_routes(self):
        for route in self.routes.values():
            if len(set(route.targets)) != len(route.targets):
                raise ValueError("路由中包含重复目标")
            for key in route.targets:
                if key not in self.targets or self.targets[key].disclosure_scope != route.disclosure_scope:
                    raise ValueError("路由目标不存在或接收范围不一致")
        return self


class Integrations(Contract):
    version: Literal[1] = 1
    recognition: RecognitionRules = Field(default_factory=RecognitionRules,
                                          validation_alias=AliasChoices("recognition", "presidio"))
    policies: BoundaryPolicies = Field(default_factory=BoundaryPolicies,
                                       validation_alias=AliasChoices("policies", "nemo"))
    lakera: Lakera = Field(default_factory=Lakera)
    litellm: LiteLLM = Field(default_factory=LiteLLM)
    knowledge: dict[str, Knowledge] = Field(default_factory=dict)
    tools: dict[str, Tool] = Field(default_factory=dict)
    model_gateway: ModelGateway = Field(default_factory=ModelGateway)

    @property
    def presidio(self):
        return self.recognition

    @property
    def nemo(self):
        return self.policies


Presidio = RecognitionRules
Nemo = BoundaryPolicies


def load_integrations() -> tuple[Integrations, str]:
    C.load_env()
    path = Path(os.getenv("SHIELD_INTEGRATIONS_CONFIG", str(C.CONFIG_DIR / "integrations.yaml")))
    if not path.is_absolute():
        path = C.ROOT / path
    payload = path.read_bytes()
    settings = Integrations.model_validate(yaml.safe_load(payload))
    return settings, hashlib.sha256(payload).hexdigest()
