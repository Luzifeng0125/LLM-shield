"""Local, structured analysis over authorized uploaded tables."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import secrets
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .m1_access.identity import check_read
from .m1_access.loader import load_material
from .material_policy import material_scope

router = APIRouter(prefix="/api/workbench", tags=["本机表格工作台"])
TASK = "activity_stats"
MAX_ROWS = 100_000
MAX_GROUPS = 1_000
_VERSION_KEY = secrets.token_bytes(32)
Column = Annotated[str, StringConstraints(min_length=1, max_length=264)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Contract):
    doc_id: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    version: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] | None = None


class SourceRequest(Contract):
    identity: str = Field(max_length=64)
    source: Source


class Join(Contract):
    source: Source
    left_column: Column
    right_column: Column


class Condition(Contract):
    column: Column
    op: Literal["eq", "ne"]
    value: str = Field(max_length=512)


class Query(SourceRequest):
    join: Join | None = None
    conditions: list[Condition] = Field(default_factory=list, max_length=12)
    logic: Literal["all", "any"] = "all"
    group_by: Column | None = None
    distinct_by: Column | None = None


def require_local_request(request: Request) -> None:
    # These views can contain values from the source. Serve them only on the local app.
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "工作台仅供本机访问")
    if request.url.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "请使用本机地址打开工作台")


def _table(source: Source, identity: str):
    try:
        material = load_material(source.doc_id)
    except FileNotFoundError:
        raise HTTPException(404, "表格不存在、已删除或已过期") from None
    access = check_read(identity, [material])
    if not access.ok or access.denied_docs or material.doc_type != "uploaded":
        raise HTTPException(403, "当前身份无权读取此表格")
    columns = material.columns
    if not columns or material.rows is None:
        raise HTTPException(422, "材料没有可查询的表格")
    if (any(not isinstance(col, str) or not 1 <= len(col) <= 256 for col in columns)
            or len(columns) != len(set(columns))):
        raise HTTPException(422, "表头为空、重复或过长，请修正后重新上传")
    if len(material.rows) > MAX_ROWS:
        raise HTTPException(422, "每张表最多支持 10 万条记录，请拆分后处理")
    if any(not isinstance(row, dict) for row in material.rows):
        raise HTTPException(422, "表格记录格式不一致")
    return material


def _version(material) -> str:
    payload = json.dumps(
        [material.source_key, material.source_version, material.created_at,
         material.title, material.columns, material.rows],
        ensure_ascii=True, separators=(",", ":"),
    ).encode()
    return hmac.new(_VERSION_KEY, payload, hashlib.sha256).hexdigest()


@contextmanager
def _open_tables(request: SourceRequest, *, require_version: bool = False):
    sources = [request.source]
    if isinstance(request, Query) and request.join:
        sources.append(request.join.source)
    if len({item.doc_id for item in sources}) != len(sources):
        raise HTTPException(422, "主表和关联表请选择不同的材料")
    tables = [_table(item, request.identity) for item in sources]
    with material_scope(tables, TASK):
        versions = [_version(table) for table in tables]
        for item, version in zip(sources, versions):
            if (require_version and not item.version) or (item.version and item.version != version):
                raise HTTPException(409, "材料版本已变化，请重新选择表格")
        yield tables, versions


@router.post("/source")
def source_schema(body: SourceRequest, request: Request):
    require_local_request(request)
    with _open_tables(body) as (tables, versions):
        table = tables[0]
        return JSONResponse({"title": table.title, "columns": table.columns,
                             "rows": len(table.rows), "version": versions[0]},
                            headers={"Cache-Control": "no-store"})


def _value(row: dict, column: str) -> str:
    value = row.get(column)
    if value is None:
        return ""
    if not isinstance(value, (str, bool, int, float)):
        raise HTTPException(422, "所选字段含嵌套数据，须先整理为单元格值")
    return unicodedata.normalize("NFKC", str(value)).strip()


def _columns_exist(keys, columns) -> None:
    if any(key not in columns for key in keys if key is not None):
        raise HTTPException(422, "所选字段不存在，请核对表头")


def execute(body: Query, tables: list) -> dict:
    main = tables[0]
    columns = set(main.columns)
    rows = main.rows
    unmatched = 0
    if body.join:
        join = body.join
        right = tables[1]
        _columns_exist([join.left_column], columns)
        _columns_exist([join.right_column], right.columns)
        aliases = {col: f"关联表 · {col}" for col in right.columns}
        if columns.intersection(aliases.values()):
            raise HTTPException(422, "主表列名与关联表显示列名冲突")
        columns.update(aliases.values())
        requested = {body.group_by, body.distinct_by, *(condition.column for condition in body.conditions)}
        aliases = {col: alias for col, alias in aliases.items() if alias in requested}
        index = {}
        for row in right.rows:
            key = _value(row, join.right_column)
            if not key:
                continue
            if key in index:
                raise HTTPException(422, "关联表有重复的非空关联键，请先去重，避免放大计数")
            index[key] = row
        rows = []
        for row in main.rows:
            match = index.get(_value(row, join.left_column))
            if match is not None:
                rows.append(row | {alias: match.get(col) for col, alias in aliases.items()})
        unmatched = len(main.rows) - len(rows)

    _columns_exist([body.group_by, body.distinct_by, *(c.column for c in body.conditions)], columns)
    checks = [(c.column, c.op, unicodedata.normalize("NFKC", c.value).strip()) for c in body.conditions]
    combine = all if body.logic == "all" else any
    counts: Counter = Counter()
    seen: dict[str | None, set[str]] = defaultdict(set)
    distinct_keys = set()
    matched = missing_keys = 0
    for row in rows:
        if checks and not combine((_value(row, col) == value) == (op == "eq") for col, op, value in checks):
            continue
        matched += 1
        group = _value(row, body.group_by) if body.group_by is not None else None
        if body.distinct_by is not None:
            key = _value(row, body.distinct_by)
            if not key:
                missing_keys += 1
                continue
            if key in seen[group]:
                continue
            seen[group].add(key)
            distinct_keys.add(key)
        counts[group] += 1
        if len(counts) > MAX_GROUPS:
            raise HTTPException(422, "分组超过 1000 个，请添加筛选条件或更换分组字段")
    return {"source_rows": len(main.rows), "joined_rows": len(rows), "unmatched_rows": unmatched,
            "matched_rows": matched, "missing_keys": missing_keys,
            "total": len(distinct_keys) if body.distinct_by else matched,
            "mode": "distinct" if body.distinct_by else "records",
            "groups": [{"value": key, "count": counts[key]} for key in sorted(counts)]
            if body.group_by is not None else []}


@router.post("/query")
def run_query(body: Query, request: Request):
    require_local_request(request)
    with _open_tables(body, require_version=True) as (tables, _):
        return JSONResponse(execute(body, tables), headers={"Cache-Control": "no-store"})


def _csv_cell(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@")) or any(c in value for c in "\r\n\t"):
        return "'" + value
    return value


@router.post("/export")
def export_summary(body: Query, request: Request):
    require_local_request(request)
    with _open_tables(body, require_version=True) as (tables, _):
        result = execute(body, tables)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["统计项目", "数量"])
        for label, key in [("主表记录", "source_rows"), ("关联后记录", "joined_rows"),
                           ("未关联记录", "unmatched_rows"), ("命中记录", "matched_rows"),
                           ("空去重键", "missing_keys"),
                           ("去重合计" if body.distinct_by else "记录合计", "total")]:
            writer.writerow([label, result[key]])
        if body.group_by:
            writer.writerow([])
            writer.writerow([_csv_cell(body.group_by), "分组数量"])
            writer.writerows((_csv_cell(group["value"]), group["count"]) for group in result["groups"])
        return Response(stream.getvalue().encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="shield-local-summary.csv"',
                                 "Cache-Control": "no-store"})
