"""Inspect workbook shapes without printing or saving personal records."""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook


WORKBOOKS = (
    Path(r"F:\JNU\助教\番禺校区实弹射击学生信息表.xlsx"),
    Path(r"F:\JNU\助教\新训All In One.xlsx"),
    Path(r"F:\JNU\助教\2026学生报到信息.xlsx"),
    Path(r"F:\JNU\粤港联\名单公布\13屆粵港聯名單All.xlsx"),
)
HEADER_TERMS = (
    "姓名", "电话", "手机", "学号", "学院", "专业", "校区", "宿舍", "身份证",
    "邮箱", "微信", "班级", "性别", "籍贯", "民族", "住址", "备注", "序号",
)


def profile(path: Path) -> dict:
    if not path.is_file():
        return {"file": path.name, "error": "missing"}
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        return {"file": path.name, "error": type(exc).__name__}
    sheets = []
    for sheet in workbook.worksheets:
        candidate_headers = []
        row_widths = []
        try:
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), 1):
                nonempty = [value for value in row if value is not None and str(value).strip()]
                if row_number <= 10:
                    terms = sorted({term for value in nonempty for term in HEADER_TERMS
                                    if isinstance(value, str) and term in value and len(value) <= 20})
                    if terms:
                        candidate_headers.append({"row": row_number, "terms": terms})
                if row_number <= 30:
                    row_widths.append(len(nonempty))
        except Exception as exc:
            sheets.append({"index": len(sheets) + 1, "rows": sheet.max_row,
                           "columns": sheet.max_column, "error": type(exc).__name__})
            continue
        sheets.append({"index": len(sheets) + 1, "rows": sheet.max_row,
                       "columns": sheet.max_column, "first_rows_nonempty": row_widths[:10],
                       "header_candidates": candidate_headers})
    workbook.close()
    return {"file": path.name, "bytes": path.stat().st_size, "sheets": sheets}


if __name__ == "__main__":
    print(json.dumps([profile(p) for p in WORKBOOKS], ensure_ascii=False, indent=2))
