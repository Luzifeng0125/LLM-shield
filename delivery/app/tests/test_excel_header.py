from io import BytesIO

from openpyxl import Workbook

from llm_shield.m1_access.file_loader import _parse_excel


def test_excel_merged_title_and_duplicate_headers_preserve_each_cell():
    workbook = Workbook()
    sheet = workbook.active
    sheet.merge_cells("A1:D1")
    sheet["A1"] = "报名统计表"
    sheet.append(["序号", "职责", "职责", ""])
    sheet.append([1, "签到", "引导", "备注"])
    buffer = BytesIO()
    workbook.save(buffer)
    _, columns, rows = _parse_excel(buffer.getvalue(), "报名表.xlsx")
    assert columns == ["序号", "职责", "职责_2", "列4"]
    assert rows == [{"序号": "1", "职责": "签到", "职责_2": "引导", "列4": "备注"}]
