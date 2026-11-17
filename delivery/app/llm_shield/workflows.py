"""Local API for task surrogates, partner check-in and private acceptance."""

from __future__ import annotations

import json
import os
import secrets
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, StringConstraints, TypeAdapter

from .config import OUTPUT_DIR, llm_settings, load_env
from .m7_egress.gateway import EgressGateway
from .material_policy import SOURCES
from .private_benchmark import AcceptanceSuite, Candidate, evaluate, manifest_digest
from .task_surrogate import AssignmentSolution, AssignmentTask, Contract, Index, Placement, project, restore, solve
from .workflow_store import WorkflowStore


def disable_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/workflows", tags=["本地项目工作流"],
                   dependencies=[Depends(disable_cache)])
STORE = WorkflowStore(OUTPUT_DIR / "workflows" / "projects.sqlite3")
bearer = HTTPBearer(auto_error=False)
Auth = Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]
Key = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
Secret = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]
ProviderSolution = TypeAdapter(Annotated[list[tuple[Index, Index]], Field(min_length=1, max_length=64)])


def require_enabled() -> str:
    load_env()
    token = os.getenv("SHIELD_WORKFLOW_ADMIN_TOKEN", "")
    if len(token) < 32 or not token.isascii():
        raise HTTPException(503, "本地项目工作流未启用")
    return token


def require_owner(auth: Auth):
    token = require_enabled()
    if not auth or not secrets.compare_digest(auth.credentials.encode(), token.encode()):
        raise HTTPException(401, "需要项目管理员凭证", headers={"WWW-Authenticate": "Bearer"})


owner = [Depends(require_owner)]


def require_project(db, key: str):
    if not db.execute("SELECT 1 FROM projects WHERE id=?", (key,)).fetchone():
        raise HTTPException(404, "项目不存在")


def require_object(db, project_id: str, key: str, kind: str) -> dict:
    obj = STORE.get(db, project_id, key, kind)
    if obj is None:
        raise HTTPException(404, "记录不存在或已撤回")
    return obj


class PassRequest(Contract):
    subject_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    ttl_seconds: int = Field(default=3600, strict=True, ge=1, le=86400)


class CheckIn(Contract):
    pass_token: Secret
    event_id: UUID


class ExternalAssignmentRequest(Contract):
    confirm_structure_disclosure: Literal[True]


@router.post("/projects", dependencies=owner, status_code=201, summary="建立本地项目")
def create_project():
    with STORE.transaction() as db:
        return {"project_id": STORE.create_project(db)}


@router.delete("/projects/{project_id}", dependencies=owner, summary="撤回项目及其下属记录")
def revoke_project(project_id: Key):
    with SOURCES.mutate("workflow:" + project_id), STORE.transaction() as db:
        require_project(db, project_id)
        db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"revoked": True}


@router.post("/projects/{project_id}/assignments", dependencies=owner, status_code=201,
             summary="创建人员与资源分配替身")
def create_assignment(project_id: Key, task: AssignmentTask):
    public, private = project(task)
    try:
        local_solution = solve(public)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    with STORE.transaction() as db:
        require_project(db, project_id)
        key = STORE.put(db, project_id, "assignment", {"public": public, "private": private})
    return {"assignment_id": key, "surrogate": public, "local_solution": local_solution}


@router.post("/projects/{project_id}/assignments/{assignment_id}/propose", dependencies=owner,
             summary="经确认后请求外部生成已验证的替身方案")
def propose_assignment(project_id: Key, assignment_id: Key, request: ExternalAssignmentRequest):
    with SOURCES.use({"workflow:" + project_id: None}):
        return external_assignment(project_id, assignment_id)


def external_assignment(project_id: str, assignment_id: str):
    with STORE.transaction() as db:
        public = require_object(db, project_id, assignment_id, "assignment")["public"]
    if llm_settings()["mode"] not in {"real", "auto"}:
        raise HTTPException(409, "此接口需要启用真实生成服务")
    capacities = [resource["capacity"] for resource in public["resources"]]
    eligibility = [subject["eligible"] for subject in public["subjects"]]
    result = EgressGateway().send_to_model(
        "assignment_planning", json.dumps([capacities, eligibility], separators=(",", ":")), "student_leader"
    )
    if not result["allowed"]:
        raise HTTPException(409, result["record"].blocked_reason)
    reply = result["text"].strip()
    if reply.startswith("```json\n") and reply.endswith("\n```"):
        reply = reply.removeprefix("```json\n").removesuffix("\n```")
    with STORE.transaction() as db:
        entry = require_object(db, project_id, assignment_id, "assignment")
        try:
            if len(reply) > 10000:
                raise ValueError("candidate output too large")
            pairs = ProviderSolution.validate_json(reply)
            solution = AssignmentSolution(placements=[
                Placement(subject=subject, resource=resource) for subject, resource in pairs
            ])
            restore(entry["public"], entry["private"], solution)
        except ValueError as exc:
            raise HTTPException(422, "模型方案未通过结构、资格或容量校验，可使用本机方案") from exc
    return {"verified": True, "solution": solution}


@router.post("/projects/{project_id}/assignments/{assignment_id}/verify", dependencies=owner,
             summary="验证方案并在本机恢复标签")
def verify_assignment(project_id: Key, assignment_id: Key, solution: AssignmentSolution):
    with STORE.transaction() as db:
        entry = require_object(db, project_id, assignment_id, "assignment")
        try:
            placements = restore(entry["public"], entry["private"], solution)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"verified": True, "placements": placements}


@router.delete("/projects/{project_id}/assignments/{assignment_id}", dependencies=owner,
               summary="撤回替身映射")
def revoke_assignment(project_id: Key, assignment_id: Key):
    with SOURCES.mutate("workflow:" + project_id), STORE.transaction() as db:
        require_object(db, project_id, assignment_id, "assignment")
        db.execute("DELETE FROM objects WHERE project=? AND id=?", (project_id, assignment_id))
    return {"revoked": True}


@router.post("/projects/{project_id}/suppliers", dependencies=owner, status_code=201,
             summary="登记供应商并签发身份凭证")
def add_supplier(project_id: Key):
    with STORE.transaction() as db:
        require_project(db, project_id)
        supplier, token = STORE.add_supplier(db, project_id)
    return {"supplier_id": supplier, "supplier_token": token}


@router.delete("/projects/{project_id}/suppliers/{supplier_id}", dependencies=owner,
               summary="撤销供应商身份和未核销凭证")
def revoke_supplier(project_id: Key, supplier_id: Key):
    with STORE.transaction() as db:
        require_project(db, project_id)
        if not db.execute("DELETE FROM suppliers WHERE project=? AND id=?",
                          (project_id, supplier_id)).rowcount:
            raise HTTPException(404, "供应商不存在")
    return {"revoked": True}


@router.post("/projects/{project_id}/suppliers/{supplier_id}/passes", dependencies=owner,
             status_code=201, summary="为指定供应商签发一次性签到凭证")
def issue_pass(project_id: Key, supplier_id: Key, request: PassRequest):
    with STORE.transaction() as db:
        if not db.execute("SELECT 1 FROM suppliers WHERE project=? AND id=?",
                          (project_id, supplier_id)).fetchone():
            raise HTTPException(404, "供应商不存在")
        token = STORE.issue_pass(db, project_id, supplier_id, request.subject_key, request.ttl_seconds)
    return {"pass_token": token, "ttl_seconds": request.ttl_seconds}


@router.post("/check-ins", summary="供应商核销或重传签到事件")
def check_in(request: CheckIn, auth: Auth):
    owner_token = require_enabled()
    if not auth or len(auth.credentials) != 43 or secrets.compare_digest(
        auth.credentials.encode(), owner_token.encode()
    ):
        raise HTTPException(403, "签到凭证无效或不可用")
    with STORE.transaction() as db:
        if not STORE.check_in(db, auth.credentials, request.pass_token, str(request.event_id)):
            raise HTTPException(403, "签到凭证无效或不可用")
    return {"checked_in": True}


@router.get("/projects/{project_id}/check-ins/summary", dependencies=owner, summary="查询项目签到汇总")
def check_in_summary(project_id: Key):
    with STORE.transaction() as db:
        require_project(db, project_id)
        count = db.execute("SELECT COUNT(*) FROM checkins WHERE project=?", (project_id,)).fetchone()[0]
    return {"checked_in_count": count}


@router.post("/projects/{project_id}/benchmarks", dependencies=owner, status_code=201,
             summary="封存买方验收集")
def create_benchmark(project_id: Key, suite: AcceptanceSuite):
    with STORE.transaction() as db:
        require_project(db, project_id)
        key = STORE.put(db, project_id, "benchmark", {"suite": suite.model_dump(), "reports": []})
    return {"benchmark_id": key, "case_count": len(suite.cases), "max_candidates": suite.max_candidates}


@router.post("/projects/{project_id}/benchmarks/{benchmark_id}/candidates", dependencies=owner,
             summary="运行固定版本的候选方案")
def run_candidate(project_id: Key, benchmark_id: Key, candidate: Candidate):
    with STORE.transaction() as db:
        entry = require_object(db, project_id, benchmark_id, "benchmark")
        suite = AcceptanceSuite.model_validate(entry["suite"])
        manifest = manifest_digest(candidate)
        reports = entry["reports"]
        for previous in reports:
            if (previous["name"], previous["version"]) == (candidate.name, candidate.version):
                if previous["manifest_sha256"] != manifest:
                    raise HTTPException(409, "候选版本已封存，请使用新版本号")
                return previous
        if len(reports) >= suite.max_candidates:
            raise HTTPException(409, "已达封存验收的候选额度")
        report = evaluate(suite, candidate, manifest)
        reports.append(report)
        db.execute("UPDATE objects SET payload=? WHERE project=? AND id=?",
                   (json.dumps(entry), project_id, benchmark_id))
    return report


@router.get("/projects/{project_id}/benchmarks/{benchmark_id}/report", dependencies=owner,
            summary="查看候选命中数、报价和执行耗时")
def benchmark_report(project_id: Key, benchmark_id: Key):
    with STORE.transaction() as db:
        return {"reports": require_object(db, project_id, benchmark_id, "benchmark")["reports"]}
