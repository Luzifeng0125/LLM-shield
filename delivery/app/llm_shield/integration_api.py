"""Local diagnostics and authenticated Dify external knowledge retrieval."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from .integrations import Contract, load_integrations
from .m1_access.loader import load_material
from .m6_transform.anonymizer import apply_decisions
from .m6_transform.mapping import MappingTable
from .m7_egress.gateway import EgressGateway
from .material_policy import material_scope
from .processing import ProcessingFailure, analyze
from .schema import Action, Material, RecipientType
from .table_workbench import require_local_request

router = APIRouter(tags=["集成与识别诊断"])
bearer = HTTPBearer(auto_error=False)
_REFERENCE_KEY = secrets.token_bytes(32)


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


@router.get("/api/integrations", dependencies=[Depends(require_local_request), Depends(no_cache)])
def status():
    try:
        settings, revision = load_integrations()
    except Exception:
        raise HTTPException(503, "集成配置无效，请检查本机配置文件") from None
    packages = {}
    for package in ("presidio-analyzer", "nemoguardrails"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {"revision": revision, "packages": packages,
            "presidio": settings.presidio.enabled, "nemo": settings.nemo.enabled,
            "litellm": settings.litellm.enabled, "lakera": settings.lakera.enabled,
            "knowledge_sources": len(settings.knowledge)}


class Diagnostic(Contract):
    identity: str = Field(max_length=64)
    task: str = Field(max_length=64)
    recipient: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=24000)
    task_description: str = Field(default="", max_length=4000)


@router.post("/api/integrations/diagnose", dependencies=[Depends(require_local_request), Depends(no_cache)])
def diagnose(body: Diagnostic):
    material = Material("diagnostic-input", "uploaded", "", body.text)
    try:
        analysis = analyze(body.identity, body.task, body.recipient, [material],
                           task_description=body.task_description)
        _, revision = load_integrations()
    except ProcessingFailure as exc:
        raise HTTPException(409, {"stage": exc.stage, "reason": str(exc)}) from None
    except Exception:
        raise HTTPException(503, "集成配置不可用") from None
    return {"revision": revision, "entities": [span.to_dict() for span in analysis.spans],
            "segments": [{"start": part.start, "end": part.end, **decision.to_dict()}
                         for part, decision in zip(analysis.segments, analysis.decisions)],
            "paused": analysis.paused is not None,
            "reason": analysis.paused.reason if analysis.paused else "",
            "external_model_called": False}


class RetrievalSettings(Contract):
    top_k: int = Field(strict=True, ge=1, le=5)
    score_threshold: float = Field(ge=0, le=1)


class Retrieval(Contract):
    knowledge_id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=1000)
    retrieval_setting: RetrievalSettings
    # Optional in Dify. Refuse unsupported filters instead of silently ignoring them.
    metadata_condition: dict | None = None


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2}", text.casefold()))


def _chunks(content: str):
    current = ""
    for line in content.splitlines():
        if not line.strip():
            continue
        for start in range(0, len(line), 1200):
            piece = line[start:start + 1200]
            if current and len(current) + len(piece) + 1 > 1200:
                yield current
                current = ""
            current = current + "\n" + piece if current else piece
    if current:
        yield current


def _approved_content(material, binding):
    # A knowledge excerpt may reach every user and model of the bound Dify app.
    # Never restore names using the local viewer's permissions here.
    analysis = analyze(binding.identity, binding.task, binding.recipient, [material],
                       max_source_chars=24000)
    if analysis.paused:
        raise HTTPException(409, "知识材料需要本机复核，本次未返回片段")
    mapping = MappingTable()
    session = secrets.token_hex(16)
    applied = apply_decisions(analysis.text, analysis.segments, analysis.decisions, session, mapping)
    if applied["paused"]:
        raise HTTPException(409, "知识材料转换暂停，本次未返回片段")
    codes = set(mapping.export(session).values())
    allowed = {span.text for part, decision in zip(analysis.segments, analysis.decisions)
               if decision.action == Action.RETAIN for span in part.spans}
    content = applied["sanitized_text"]
    checked = EgressGateway(generated_pseudonyms=codes).precheck(
        binding.recipient, binding.identity, content, analysis.spans, allowed,
        task_key=binding.task, expected_type=RecipientType.EGRESS_TOOL, operation="tool_egress")
    if not checked["allowed"]:
        raise HTTPException(409, "知识片段未通过接收方检查")
    return content


@router.post("/api/integrations/dify/retrieval", dependencies=[Depends(no_cache)])
def retrieval(body: Retrieval, auth: HTTPAuthorizationCredentials | None = Depends(bearer)):
    try:
        settings, revision = load_integrations()
    except Exception:
        raise HTTPException(503, "知识服务配置不可用") from None
    binding = settings.knowledge.get(body.knowledge_id)
    secret = os.getenv(binding.token_env, "") if binding else ""
    if (not binding or len(secret) < 32 or not auth
            or not secrets.compare_digest(auth.credentials.encode(), secret.encode())):
        raise HTTPException(401, "知识服务凭证无效")
    if body.metadata_condition:
        raise HTTPException(422, "当前连接器尚不支持元数据过滤条件")
    from .config import recipients

    if recipients().get(binding.recipient, {}).get("type") != "EGRESS_TOOL":
        raise HTTPException(503, "知识源需要配置外发接收方")
    try:
        materials = [load_material(key) for key in dict.fromkeys(binding.doc_ids)]
    except FileNotFoundError:
        raise HTTPException(410, "知识材料已删除或过期，请在本机更新绑定") from None
    records = []
    terms = _terms(body.query)
    with material_scope(materials, binding.task):
        for material in materials:
            try:
                content = _approved_content(material, binding)
            except ProcessingFailure:
                raise HTTPException(409, "知识材料未通过本机处理检查") from None
            if not content.strip():
                continue
            # Public reference binds to source content and policy version, without filenames.
            stamp = repr((material.doc_id, material.created_at, material.source_version,
                          material.text, material.rows, revision)).encode()
            for index, chunk in enumerate(_chunks(content)):
                score = len(terms & _terms(chunk)) / len(terms) if terms else 0.0
                if score == 0 or score < body.retrieval_setting.score_threshold:
                    continue
                checked = EgressGateway().precheck(
                    binding.recipient, binding.identity, chunk, task_key=binding.task,
                    expected_type=RecipientType.EGRESS_TOOL, operation="tool_egress")
                if not checked["allowed"]:
                    raise HTTPException(409, "知识片段未通过接收方检查")
                reference = hmac.new(_REFERENCE_KEY, stamp + str(index).encode(), hashlib.sha256).hexdigest()
                records.append({"content": chunk, "score": score, "title": "获准知识片段",
                                "metadata": {"reference": reference, "policy_version": revision}})
        records.sort(key=lambda record: record["score"], reverse=True)
        try:
            _, current_revision = load_integrations()
        except Exception:
            raise HTTPException(503, "知识服务配置不可用") from None
        if current_revision != revision:
            raise HTTPException(409, "知识授权配置已变化，请重试")
        return {"records": records[:body.retrieval_setting.top_k]}
