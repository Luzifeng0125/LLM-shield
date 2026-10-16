"""隐盾本地受控服务（FastAPI）。

所有决策与执行都在本机完成；云端大模型只接收处理后的文本。
启动：python -m uvicorn llm_shield.server:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

from typing import List, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal

from . import config as C
from .m1_access.file_loader import (MAX_BYTES, SUPPORTED, ParseError,
                                    delete_upload, maybe_parse_table,
                                    parse_upload)
from .m1_access.loader import list_materials, load_material
from .m1_access.identity import check_provide, check_read
from .m2_detect.pipeline import DetectionError, build_detectors
from .m4_necessity.model import get_model
from .m8_audit.audit import get_auditor
from .pipeline import preview_only, run_pipeline
from .schema import Material, ShieldRequest
from .chat import STORE, ChatError, send_turn, snapshot
from .notice import notice_request, review_roster

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warmup()
    yield


app = FastAPI(title="隐盾 LLM-Shield", version="0.1.0",
              description="面向高校场景的最小披露防护服务（本地受控）",
              lifespan=lifespan)

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
                  for k, v in C.tasks().items() if k != "version"},
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
            "campus_ner": {
                "available": any(d.name == "campus_ner" for d in build_detectors()),
                "note": "敏感识别使用规则底座；领域 NER 需配置显式启用",
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
    return {"items": list_materials(include_builtin=include_builtin)}


# ---------------------------------------------------------------- 文件上传


@app.get("/api/upload/formats")
def api_upload_formats():
    """告知前端支持哪些格式与体积上限。"""
    return {"formats": sorted(SUPPORTED), "max_mb": MAX_BYTES // 1024 // 1024}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """上传并解析文件，返回可直接参与处理的 doc_id。

    解析在本地完成，只保留提取出的文本/表格，不保存原始二进制文件。
    """
    data = await file.read()
    try:
        mat = parse_upload(data, file.filename or "upload.txt")
    except ParseError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"上传处理失败：{type(e).__name__}: {e}")

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
    }


@app.delete("/api/upload/{doc_id}")
def api_delete_upload(doc_id: str):
    """删除已上传材料（只删该 JSON，不做任何目录递归操作）。"""
    return {"ok": delete_upload(doc_id)}


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

    @app.get("/notice")
    def notice_page():
        return FileResponse(WEB_DIR / "notice.html")
