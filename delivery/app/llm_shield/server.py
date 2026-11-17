"""隐盾本地受控服务（FastAPI）。

所有决策与执行都在本机完成；云端大模型只接收处理后的文本。
启动：python -m uvicorn llm_shield.server:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets

from typing import List, Optional

from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from . import config as C
from .m1_access.file_loader import (MAX_BYTES, SUPPORTED, ParseError,
                                    delete_upload, maybe_parse_table,
                                    parse_uploads, cleanup_expired_uploads)
from .m1_access.loader import list_materials, load_material
from .material_policy import SourcePolicyError, material_scope
from .m1_access.identity import check_provide, check_read
from .m2_detect.pipeline import DetectionError, build_detectors
from .m4_necessity.model import get_model
from .m8_audit.audit import get_auditor
from .pipeline import preview_only, run_pipeline
from .schema import Material, ShieldRequest
from .chat import STORE, ChatError, send_turn, snapshot
from .notice import notice_request, review_roster
from .metrics import snapshot as metrics_snapshot
from .runtime import readiness
from .evaluation_report import evaluation_summary
from .workflows import router as workflows_router
from .table_workbench import require_local_request, router as table_workbench_router

def _warmup() -> None:
    """启动预热。

    必要性模型首次加载需反序列化 TF-IDF 词表，实测约 1.8s（一次性开销），
    稳态推理只要 ~0.4ms。放在启动时做，避免第一个请求承担冷启动延迟。
    """
    try:
        from .m4_necessity.model import get_model
        from .schema import Segment
        model = get_model()
        model.score(Segment(seg_id="warmup", text="预热", start=0, end=2),
                    "meeting_minutes", "external_model")
        print(f"[预热] 必要性判别模型已就绪：{model.backend}")
    except Exception as exc:
        print(f"[预热] 本地决策模型不可用，将暂停外发：{exc}")
    if C.use_gliner():
        try:
            gliner = next(item for item in build_detectors() if item.name == "gliner")
            gliner.detect("预热")
            print(f"[预热] GLiNER 已就绪：{gliner.device}")
        except Exception as exc:
            print(f"[预热] GLiNER 不可用（{type(exc).__name__}），请求将暂停处理")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_expired_uploads()
    _warmup()
    try:
        yield
    finally:
        STORE.close()


app = FastAPI(title="隐盾 LLM-Shield", version="0.1.0",
              description="面向高校场景的最小披露防护服务（本地受控）",
              lifespan=lifespan)
app.include_router(workflows_router)
app.include_router(table_workbench_router)


@app.exception_handler(SourcePolicyError)
async def source_policy_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

WEB_DIR = C.ROOT / "web"


# ---------------------------------------------------------------- 请求模型


class RunRequest(BaseModel):
    session_id: str = Field(default="demo-session")
    identity: str
    task: str
    recipient: str
    doc_ids: List[str] = Field(default_factory=list)
    custom_text: str = ""
    task_description: str = Field(default="", max_length=4000)
    send_model: bool = True


class PreviewRequest(RunRequest):
    pass


class RosterReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    identity: str = "student_leader"
    text: str = Field(min_length=1, max_length=24000)


class NoticeDraftRequest(BaseModel):
    model_config = {"extra": "forbid"}
    identity: str = "student_leader"
    activity_name: str = Field(min_length=1, max_length=80)
    items: List[Literal["check_in", "join_group", "verify_contact"]] = Field(min_length=1, max_length=3)
    send_model: bool = True


@app.post("/api/notice/review")
def api_roster_review(r: RosterReviewRequest):
    try:
        return review_roster(r.identity, r.text)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except DetectionError:
        raise HTTPException(503, "本机识别暂不可用；名单未发送给生成模型")


@app.post("/api/notice/draft")
def api_notice_draft(r: NoticeDraftRequest):
    if not isinstance(C.identities().get(r.identity), dict):
        raise HTTPException(400, "未知身份")
    try:
        req = notice_request(r.identity, r.activity_name, r.items)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # The normal model-only decision and all egress checks still apply to the
    # separately submitted brief. No roster is loaded or merged at this stage.
    return run_pipeline(req, send_model=r.send_model).to_dict()


class ChatCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    identity: str = "student_leader"
    task: str = "meeting_minutes"
    task_description: str = Field(default="", max_length=4000)


class ChatTurnRequest(BaseModel):
    model_config = {"extra": "forbid"}
    text: str = Field(default="", max_length=12000)
    doc_ids: List[str] = Field(default_factory=list, max_length=10)


@app.post("/api/chat/sessions")
def api_chat_create(r: ChatCreateRequest):
    try:
        return snapshot(STORE.create(r.identity, r.task, r.task_description))
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc))


@app.get("/api/chat/{session_id}")
def api_chat_history(session_id: str):
    try:
        return snapshot(STORE.get(session_id))
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc))


@app.delete("/api/chat/{session_id}")
def api_chat_clear(session_id: str):
    try:
        STORE.delete(session_id)
        return {"ok": True}
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/chat/{session_id}/messages")
def api_chat_turn(session_id: str, r: ChatTurnRequest):
    try:
        session = STORE.get(session_id)
        materials = []
        for doc_id in r.doc_ids:
            try:
                materials.append(load_material(doc_id))
            except FileNotFoundError:
                raise HTTPException(404, "材料不存在")
        if r.text.strip():
            body, columns, rows = maybe_parse_table(r.text)
            materials.append(Material("chat-input", "uploaded", "", body, rows, columns))
        if not materials:
            raise HTTPException(400, "请输入消息或添加材料")
        return send_turn(session, materials)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc))


# ---------------------------------------------------------------- 配置接口


@app.get("/api/health")
def api_health():
    return {**readiness(), **STORE.stats()}


@app.get("/api/metrics")
def api_metrics():
    return {"latency": metrics_snapshot()}


@app.get("/api/evaluation")
def api_evaluation():
    return evaluation_summary()


@app.get("/evaluation")
def evaluation_page():
    return FileResponse(WEB_DIR / "evaluation.html")


@app.get("/api/config")
def api_config(include_builtin: bool = False):
    """返回任务模板 / 身份 / 接收方 / 材料清单，以及当前模型后端状态。

    :param include_builtin: 是否列出内置的虚构演示材料。
        默认 **False** —— 材料列表只显示用户自己上传的内容；
        需要看内置演示材料时显式传 `?include_builtin=true`。
    """
    return {
        "tasks": {k: {"name": v.get("name"), "desc": v.get("desc"),
                      "must_retain": v.get("must_retain", [])}
                  for k, v in C.tasks().items() if k != "version" and v.get("workflow") != "assignment"},
        "identities": {k: {"name": v.get("name"), "desc": v.get("desc"),
                           "max_level": v.get("max_level")}
                       for k, v in C.identities().items() if k != "version"},
        "recipients": {k: {"name": v.get("name"), "type": v.get("type"),
                           "trust": v.get("trust"), "max_level": v.get("max_level")}
                       for k, v in C.recipients().items() if k != "version"},
        "materials": list_materials(include_builtin=include_builtin),
        "models": {
            "necessity_backend": get_model().backend,
            "necessity_reason": get_model().reason,
            "necessity_available": get_model().available,
            "decision_policy": "model_only",
            "recognizer": {
                "detectors": ["regex", "entity"] + (["gliner"] if C.use_gliner() else []),
                "gliner_enabled": C.use_gliner(),
                "note": "格式类由正则验证；GLiNER 负责语义类。就绪情况见 /api/health。",
            },
            "llm": {
                "mode": C.llm_settings()["mode"],
                "provider": C.llm_settings()["provider"],
                "model": C.llm_settings()["model"],
                "has_key": bool(C.llm_settings()["api_key"]),
            },
        },
    }


@app.get("/api/materials")
def api_materials(include_builtin: bool = False):
    cleanup_expired_uploads()
    return {"items": list_materials(include_builtin=include_builtin)}


# ---------------------------------------------------------------- 文件上传


@app.get("/api/upload/formats")
def api_upload_formats():
    """告知前端支持哪些格式与体积上限。"""
    return {"formats": sorted(SUPPORTED), "max_mb": MAX_BYTES // 1024 // 1024}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     task: str = Form("meeting_minutes"),
                     storage_mode: Literal["temporary", "library"] = Form("temporary")):
    """上传并解析文件，返回可直接参与处理的 doc_id。

    解析在本地完成，只保留提取出的文本/表格，不保存原始二进制文件。
    """
    if not isinstance(C.tasks().get(task), dict) or C.tasks()[task].get("workflow") in {"notice", "assignment"}:
        raise HTTPException(400, "请选择有效的材料处理用途")
    cleanup_expired_uploads()
    data = await file.read(MAX_BYTES + 1)
    try:
        materials = parse_uploads(data, file.filename or "upload.txt",
                                 storage_mode=storage_mode, allowed_purposes=[task])
    except ParseError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(500, "上传处理失败，请检查文件格式后重试") from None

    mat = materials[0]
    preview = (mat.text or "")[:200]
    if not preview and mat.rows:
        preview = "表格列：" + "、".join(str(c) for c in (mat.columns or []))
    return {
        "ok": True,
        "doc_id": mat.doc_id,
        "title": mat.title,
        "preview": preview,
        "n_chars": len(mat.text or ""),
        "n_rows": len(mat.rows or []),
        "columns": mat.columns,
        "storage_mode": mat.storage_mode, "expires_at": mat.expires_at,
        "allowed_purposes": mat.allowed_purposes,
        "worksheets": len(materials),
        "documents": [{"doc_id": item.doc_id, "title": item.title,
                       "n_rows": len(item.rows or [])} for item in materials],
    }


@app.delete("/api/upload/{doc_id}")
def api_delete_upload(doc_id: str):
    """删除已上传材料（只删该 JSON，不做任何目录递归操作）。"""
    try:
        deleted = delete_upload(doc_id, before_delete=STORE.invalidate_material)
    except (ChatError, SourcePolicyError) as exc:
        raise HTTPException(exc.status, str(exc))
    return {"ok": deleted}


@app.get("/api/audit")
def api_audit(n: int = 50):
    return {"items": get_auditor().recent(n)}


# ---------------------------------------------------------------- 核心接口


def _build_request(r: RunRequest) -> ShieldRequest:
    for key, value, choices in (("身份", r.identity, C.identities()),
                                ("任务", r.task, C.tasks()),
                                ("接收方", r.recipient, C.recipients())):
        if not isinstance(choices.get(value), dict):
            raise HTTPException(400, f"未知{key}: {value}")
    if C.tasks()[r.task].get("workflow") == "assignment":
        raise HTTPException(400, "替身分配须使用项目工作流接口")
    if C.tasks()[r.task].get("workflow") == "notice":
        raise HTTPException(400, "此任务请使用名单本机核对与通知入口，名单不能提交给通用生成流程")
    materials: List[Material] = []
    for doc_id in r.doc_ids:
        try:
            materials.append(load_material(doc_id))
        except FileNotFoundError:
            raise HTTPException(404, f"材料不存在: {doc_id}")
    if r.custom_text.strip():
        # 两处修正：
        # 1) doc_type 必须是 "uploaded"。早期写成任务名（如 activity_stats），
        #    而身份的 readable 列表里只有材料类型、没有任务名，
        #    权限检查会直接判定「无权读取」——这就是粘贴文本跑不起来的直接原因。
        # 2) 从 Excel 粘贴的表格文本自动解析成结构化数据，
        #    否则列名丢失，姓名等列会一个都识别不出来（等于原样外发）。
        body, cols, rows = maybe_parse_table(r.custom_text)
        materials.append(Material(
            doc_id="custom", doc_type="uploaded", title="自定义输入",
            text=body, columns=cols, rows=rows))
    if not materials:
        raise HTTPException(400, "请至少选择一份材料或输入自定义文本")
    return ShieldRequest(
        session_id=r.session_id, identity=r.identity, task=r.task,
        recipient=r.recipient, materials=materials,
        user_instruction=r.task_description,
    )


@app.post("/api/preview")
def api_preview(r: PreviewRequest):
    """只做识别 + 决策，不调用模型、不外发。用于查看处理方案。"""
    req = _build_request(r)
    return preview_only(req).to_dict()


@app.post("/api/run")
def api_run(r: RunRequest):
    """跑完整流程：识别 → 决策 → 转换 → 调用模型 → 三边界观测。"""
    req = _build_request(r)
    return run_pipeline(req, send_model=r.send_model).to_dict()


class RecipientReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    identity: str = Field(max_length=64)
    task: str = Field(max_length=64)
    doc_ids: List[str] = Field(default_factory=list, max_length=10)
    custom_text: str = Field(default="", max_length=24000)
    task_description: str = Field(default="", max_length=4000)
    recipients: List[str] = Field(min_length=1, max_length=4)
    review_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RecipientExportRequest(RecipientReviewRequest):
    approval: str = Field(pattern=r"^[a-f0-9]{64}$")


_REVIEW_KEY = secrets.token_bytes(32)


def _recipient_version(req, recipient):
    recipient_config = C.recipients().get(recipient)
    kind = recipient_config.get("type") if isinstance(recipient_config, dict) else None
    if kind not in {"VIEWER", "EGRESS_TOOL"}:
        raise HTTPException(400, "请选择展示或外发接收方")
    result = run_pipeline(req, send_model=False)
    boundary = next((item for item in result.boundaries if item["recipient"] == recipient), {})
    text = result.display_text if kind == "VIEWER" else result.egress_text
    if not result.ok or result.paused or not boundary.get("allowed") or not text.strip():
        return {"recipient": recipient, "allowed": False, "text": "", "approval": None,
                "reason": result.pause_reason or boundary.get("blocked_reason") or "没有可交付内容"}
    approval = None
    if kind == "EGRESS_TOOL":
        approval_data = json.dumps([req.session_id, req.identity, req.task, req.user_instruction,
                                    recipient, text, [(m.doc_id, m.source_version) for m in req.materials]],
                                   ensure_ascii=True).encode()
        approval = hashlib.blake2b(approval_data, key=_REVIEW_KEY, digest_size=32).hexdigest()
    return {"recipient": recipient, "allowed": True, "text": text, "approval": approval, "reason": ""}


@app.post("/api/recipient-review")
def api_recipient_review(body: RecipientReviewRequest, request: Request):
    require_local_request(request)
    if len(set(body.recipients)) != len(body.recipients):
        raise HTTPException(422, "接收方不能重复")
    review_id = body.review_id or secrets.token_hex(16)
    req = _build_request(RunRequest(session_id=review_id, recipient=body.recipients[0],
                                    **body.model_dump(exclude={"recipients", "review_id"})))

    with material_scope(req.materials, req.task):
        versions = [_recipient_version(replace(req, recipient=key), key) for key in body.recipients]
        return JSONResponse({"review_id": review_id, "versions": versions},
                            headers={"Cache-Control": "no-store"})


@app.post("/api/recipient-review/export")
def api_recipient_export(body: RecipientExportRequest, request: Request):
    require_local_request(request)
    if not body.review_id or len(body.recipients) != 1:
        raise HTTPException(422, "请选择一份经检查的外发版本")
    key = body.recipients[0]
    req = _build_request(RunRequest(session_id=body.review_id, recipient=key,
                                    **body.model_dump(exclude={"recipients", "review_id", "approval"})))
    from docx import Document

    with material_scope(req.materials, req.task):
        version = _recipient_version(req, key)
        if not version["approval"] or not secrets.compare_digest(version["approval"], body.approval):
            raise HTTPException(409, "内容或权限已变化，请重新生成预览并检查")
        output = Document()
        output.core_properties.author = "隐盾"
        output.core_properties.title = "隐盾外发版本"
        for line in version["text"].split("\n"):
            output.add_paragraph(line)
        stream = io.BytesIO()
        output.save(stream)
        return Response(stream.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": 'attachment; filename="shield-approved-version.docx"',
                                 "Cache-Control": "no-store"})

@app.post("/api/check-access")
def api_check_access(identity: str, recipient: str):
    """单独检查某身份能否向某接收方提供内容（模块 ① 的第二项检查）。"""
    ok, why = check_provide(identity, recipient)
    return {"ok": ok, "reason": why}


# ---------------------------------------------------------------- 前端


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/chat")
    def chat_page():
        return RedirectResponse("/", status_code=307)

    @app.get("/recipient-review")
    def recipient_review_page():
        return FileResponse(WEB_DIR / "recipient_review.html")

    @app.get("/workbench")
    def workbench_page():
        return FileResponse(WEB_DIR / "workbench.html")

    @app.get("/notice")
    def notice_page():
        return FileResponse(WEB_DIR / "notice.html")
