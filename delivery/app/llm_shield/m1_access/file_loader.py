"""模块 ① 上传文件解析：把常见格式转成可处理的 Material。

支持：TXT / Markdown / Word(.docx) / PDF / Excel(.xlsx,.xls) / CSV / JSON

设计取舍：
- 解析结果以 JSON 落到 data/uploads/，格式与 fixtures 一致，
  后续「识别 → 决策 → 转换」链路无需区分来源；
- 不保留上传的原始二进制（只留解析后的文本），减少敏感原文落盘；
- 单文件上限 5MB，避免超大文件拖慢处理。
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Optional, Tuple

from ..config import DATA_DIR
from ..schema import Material

UPLOAD_DIR = DATA_DIR / "uploads"
MAX_BYTES = 5 * 1024 * 1024          # 5MB

TEXT_EXT = {".txt", ".md", ".markdown", ".log", ".text"}
CSV_EXT = {".csv", ".tsv"}
EXCEL_EXT = {".xlsx", ".xls"}
DOC_EXT = {".docx"}
PDF_EXT = {".pdf"}
JSON_EXT = {".json"}

SUPPORTED = TEXT_EXT | CSV_EXT | EXCEL_EXT | DOC_EXT | PDF_EXT | JSON_EXT


class ParseError(Exception):
    """文件解析失败。"""


_seq = 0


def _safe_doc_id(filename: str) -> str:
    """把文件名转成安全的 doc_id（去掉扩展名与非法字符）。

    用「毫秒时间戳 + 进程内自增序号」保证唯一：
    早期版本只用到秒，同一秒内上传多个文件会生成相同 doc_id，后一个覆盖前一个。
    """
    global _seq
    _seq += 1
    stem = Path(filename).stem
    stem = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", stem).strip("_") or "upload"
    return f"up_{stem}_{int(time.time() * 1000) % 1000000}_{_seq}"


def _decode(data: bytes) -> str:
    """文本解码：UTF-8 优先，回退 GBK（国内 Windows 常见）。"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 各格式解析


def _parse_text(data: bytes, title: str) -> Tuple[str, None, None]:
    return _decode(data), None, None


def _parse_json(data: bytes, title: str) -> Tuple[str, Optional[list], Optional[list]]:
    """JSON：若已是本项目的材料格式（含 columns/rows），直接复用结构。"""
    obj = json.loads(_decode(data))
    if isinstance(obj, dict) and "rows" in obj:
        # 有结构化行时正文留空，避免文件名被重复拼进正文
        return obj.get("text", ""), obj.get("columns"), obj.get("rows")
    # 普通 JSON：列表形式尝试当表格，否则当文本
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        cols = list(obj[0].keys())
        return title, cols, obj
    return json.dumps(obj, ensure_ascii=False, indent=2), None, None


def _parse_csv(data: bytes, title: str) -> Tuple[str, Optional[list], Optional[list]]:
    text = _decode(data)
    delim = "\t" if title.lower().endswith(".tsv") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows_raw = [r for r in reader if any(c.strip() for c in r)]
    if len(rows_raw) < 2:
        return text, None, None
    columns = [c.strip() for c in rows_raw[0]]
    rows = []
    for r in rows_raw[1:]:
        rows.append({columns[i]: (r[i].strip() if i < len(r) else "")
                     for i in range(len(columns))})
    return "", columns, rows          # 正文留空，内容全在 rows 里


def _parse_excel(data: bytes, title: str) -> Tuple[str, Optional[list], Optional[list]]:
    sheets = _parse_excel_sheets(data)
    if not sheets:
        return "", None, None
    _, text, columns, rows = sheets[0]
    return text, columns, rows


_SHEET_XML = re.compile(r"xl/worksheets/sheet\d+\.xml\Z")
_VALIDATION_TAG = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?dataValidation\b[^>]*>")
_VALIDATION_ID = re.compile(rb'\s+id="[^"]*"')
_HEADER_NAMES = {
    "序号", "姓名", "名字", "电话", "手机号", "手机号码", "联系电话", "联系方式",
    "学号", "学院", "专业", "校区", "班级", "性别", "民族", "宿舍", "宿舍号",
    "身份证", "身份证号", "邮箱", "微信", "备注", "住址", "家庭住址", "职务",
    "单位", "部门", "年级", "车辆编号", "地区", "地址", "职责",
}


def _compatible_excel_bytes(data: bytes) -> bytes:
    """Ignore WPS's unsupported validation ID, keeping source cells unchanged."""
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("Excel 文件不是有效的 xlsx 压缩包") from exc
    with source:
        entries = source.infolist()
        if sum(item.file_size for item in entries) > 100 * 1024 * 1024:
            raise ParseError("Excel 解压后内容过大")
        patches = {}
        for item in entries:
            if not _SHEET_XML.fullmatch(item.filename):
                continue
            payload = source.read(item)
            fixed = _VALIDATION_TAG.sub(
                lambda match: _VALIDATION_ID.sub(b"", match.group()), payload)
            if fixed != payload:
                patches[item.filename] = fixed
        if not patches:
            return data
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            target.comment = source.comment
            for item in entries:
                target.writestr(item, patches.get(item.filename, source.read(item)))
        return output.getvalue()


def _excel_header_index(rows: list[list[str]]) -> int:
    candidates = list(range(min(10, len(rows))))
    scores = [sum(cell.replace(" ", "") in _HEADER_NAMES for cell in rows[i] if cell)
              for i in candidates]
    if scores and max(scores) >= 2:
        return max(candidates, key=lambda i: (scores[i], -i))
    return next((i for i in candidates if sum(bool(cell) for cell in rows[i]) >= 2), 0)


def _parse_excel_sheets(data: bytes) -> list[tuple[str, str, Optional[list], Optional[list]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise ParseError("未安装 openpyxl，无法解析 Excel：pip install openpyxl") from e
    wb = load_workbook(io.BytesIO(_compatible_excel_bytes(data)),
                       data_only=True, read_only=True)
    result = []
    try:
        for ws in wb.worksheets:
            rows_raw = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c).strip() for c in row]
                if any(cells):
                    rows_raw.append(cells)
            if not rows_raw:
                continue
            if len(rows_raw) < 2:
                result.append((ws.title, " ".join(rows_raw[0]), None, None))
                continue
            header_index = _excel_header_index(rows_raw)
            raw_columns = rows_raw[header_index]
            columns, used = [], set()
            for i, raw in enumerate(raw_columns):
                base = raw or f"列{i + 1}"
                name, suffix = base, 2
                while name in used:
                    name = f"{base}_{suffix}"
                    suffix += 1
                columns.append(name)
                used.add(name)
            rows = [{columns[i]: (row[i] if i < len(row) else "")
                     for i in range(len(columns))}
                    for row in rows_raw[header_index + 1:]
                    if any(row)]
            result.append((ws.title, "", columns, rows))
    finally:
        wb.close()
    return result


def _parse_docx(data: bytes, title: str) -> Tuple[str, Optional[list], Optional[list]]:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise ParseError("未安装 python-docx，无法解析 Word：pip install python-docx") from e

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # 若文档内含表格，取第一个表格作为结构化数据
    columns = rows = None
    if doc.tables:
        t = doc.tables[0]
        grid = [[c.text.strip() for c in row.cells] for row in t.rows]
        if len(grid) >= 2:
            columns = grid[0]
            rows = [{columns[i]: (r[i] if i < len(r) else "") for i in range(len(columns))}
                    for r in grid[1:]]
    return "\n".join(parts), columns, rows


def _parse_pdf(data: bytes, title: str) -> Tuple[str, None, None]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ParseError("未安装 pypdf，无法解析 PDF：pip install pypdf") from e

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages).strip()
    if not text:
        # 扫描件/图片型 PDF 没有文本层
        raise ParseError("该 PDF 未提取到文本（可能是扫描件或图片型 PDF），请先做 OCR")
    return text, None, None


_PARSERS = {
    **{e: _parse_text for e in TEXT_EXT},
    **{e: _parse_json for e in JSON_EXT},
    **{e: _parse_csv for e in CSV_EXT},
    **{e: _parse_excel for e in EXCEL_EXT},
    **{e: _parse_docx for e in DOC_EXT},
    **{e: _parse_pdf for e in PDF_EXT},
}


# ---------------------------------------------------------------- 入口


def parse_upload(data: bytes, filename: str) -> Material:
    """解析上传文件并落盘，返回 Material。

    :raises ParseError: 格式不支持、体积超限或解析失败
    """
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ParseError(f"不支持的文件格式：{ext or '(无扩展名)'}，"
                         f"支持 {', '.join(sorted(SUPPORTED))}")
    if len(data) > MAX_BYTES:
        raise ParseError(f"文件过大（{len(data)/1024/1024:.1f}MB），上限 5MB")
    if not data:
        raise ParseError("文件为空")

    title = Path(filename).name
    try:
        text, columns, rows = _PARSERS[ext](data, filename)
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"解析失败：{type(e).__name__}: {e}") from e

    if not (text and text.strip()) and not rows:
        raise ParseError("未能从文件中提取到任何内容")

    doc_id = _safe_doc_id(filename)
    mat = Material(
        doc_id=doc_id,
        doc_type="uploaded",           # 用户自行上传，视为已授权输入
        title=title,
        text=(text or "").strip(),
        rows=rows,
        columns=columns,
    )
    save_upload(mat)
    return mat


def parse_uploads(data: bytes, filename: str) -> list[Material]:
    """Store each nonempty Excel worksheet as an independently selectable material.

    The chat policy expects one coherent set of columns per material. Keeping
    sheets separate avoids silently dropping tabs or mixing unrelated schemas.
    Other file types retain the single-material upload behavior.
    """
    ext = Path(filename).suffix.lower()
    if ext not in EXCEL_EXT:
        return [parse_upload(data, filename)]
    if len(data) > MAX_BYTES:
        raise ParseError(f"文件过大（{len(data)/1024/1024:.1f}MB），上限 5MB")
    if not data:
        raise ParseError("文件为空")
    try:
        sheets = _parse_excel_sheets(data)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Excel 解析失败：{type(exc).__name__}") from None
    materials = []
    for sheet_name, text, columns, rows in sheets:
        if not text.strip() and not rows:
            continue
        material = Material(
            doc_id=_safe_doc_id(f"{filename}_{sheet_name}"),
            doc_type="uploaded", title=f"{Path(filename).name} / {sheet_name}",
            text=text.strip(), rows=rows, columns=columns,
        )
        materials.append(material)
    if not materials:
        raise ParseError("未能从 Excel 工作表中提取到任何内容")
    for material in materials:
        save_upload(material)
    return materials


def maybe_parse_table(text: str) -> Tuple[str, Optional[list], Optional[list]]:
    """把粘贴进来的表格文本（TSV / CSV）解析成结构化列与行。

    场景：用户从 Excel/WPS 直接复制粘贴到文本框时，拿到的是制表符分隔的纯文本。
    若不解析，列名（姓名 / 学号 / 手机号码）就丢失了，依赖列名的识别会完全失效——
    实测这类粘贴文本里姓名一个都识别不出来，等于姓名原样发给模型。

    :return: (正文, columns, rows)；不是表格时原样返回 (text, None, None)
    """
    if not text or not text.strip():
        return text, None, None

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return text, None, None

    # 选分隔符：制表符优先（Excel 复制），其次逗号
    header = lines[0]
    if "\t" in header:
        delim = "\t"
    elif header.count(",") >= 1 and header.count("，") == 0:
        delim = ","
    else:
        return text, None, None

    columns = [c.strip() for c in header.split(delim)]
    if len(columns) < 2 or not all(columns):
        return text, None, None

    rows = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.split(delim)]
        # 列数不符的行（如末尾的「无」、说明性文字）跳过，不作为数据行
        if len(cells) != len(columns):
            continue
        rows.append({columns[i]: cells[i] for i in range(len(columns))})

    if not rows:
        return text, None, None

    # 正文留空，内容全在 rows 里（与 csv/xlsx 解析保持一致）
    return "", columns, rows


def save_upload(mat: Material) -> Path:
    """把解析结果写入 data/uploads/（仅文本，不存原始二进制）。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{mat.doc_id}.json"
    path.write_text(json.dumps({
        "doc_id": mat.doc_id, "doc_type": mat.doc_type, "title": mat.title,
        "text": mat.text, "columns": mat.columns, "rows": mat.rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_upload(doc_id: str) -> bool:
    """删除已上传材料（不做目录递归，仅删本文件）。"""
    # doc_id 由 _safe_doc_id 生成，已过滤路径分隔符，这里再兜一层底
    if "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        return False
    path = UPLOAD_DIR / f"{doc_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False
