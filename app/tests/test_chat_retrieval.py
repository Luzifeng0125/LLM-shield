from llm_shield.chat_retrieval import exact_count_for_chat, select_for_chat, project_fields
from llm_shield.m1_access.loader import flatten_material
from llm_shield.schema import Material


def test_large_table_selects_relevant_rows_and_declares_partial_coverage():
    rows = [{"序号": str(i), "课程": f"普通课程{i}"} for i in range(2000)]
    rows[987]["课程"] = "专门课程甲乙丙"
    material = Material("large", "uploaded", "课程表", "", rows, ["序号", "课程"])
    question = Material("chat-input", "uploaded", "", "专门课程甲乙丙在哪一行？")
    selected = select_for_chat([material, question], question.text)
    assert len(flatten_material(selected[0])) + len(flatten_material(selected[1])) <= 24000
    assert rows[987] in selected[0].rows
    assert len(selected[0].rows) < len(rows)
    assert "数据记录共 2000 行（不含表头）" in selected[0].text
    assert "不得据此推断全表统计" in selected[0].text


def test_broad_question_uses_table_metadata_without_private_rows():
    rows = [{"姓名": f"某人{i}", "项目": "通用项目"} for i in range(2000)]
    material = Material("large", "uploaded", "报名表", "", rows, ["姓名", "项目"])
    selected = select_for_chat([material], "请概述这份文件有哪些信息。")
    assert selected[0].rows == []
    assert "数据记录共 2000 行（不含表头）" in selected[0].text
    assert "姓名、项目" in selected[0].text


def test_medium_table_is_trimmed_for_a_broad_question():
    rows = [{"序号": str(i), "职责": "签到"} for i in range(300)]
    material = Material("medium", "uploaded", "报名表", "", rows, ["序号", "职责"])
    selected = select_for_chat([material], "请概述这份文件有哪些信息。")
    assert selected[0].rows == []
    assert len(flatten_material(selected[0])) < len(flatten_material(material))


def test_exact_major_count_uses_all_rows_not_five_retrieved_rows():
    rows = [{"序号": str(i), "专业": "网络空间安全" if i % 25 == 0 else "其他专业"}
            for i in range(310)]
    material = Material("large", "uploaded", "专业表", "", rows, ["序号", "专业"])
    result = exact_count_for_chat([material], "帮我统计网络空间安全专业有多少人")
    assert result is not None
    assert "匹配 13 条记录" in result[1]
    assert "全表 310 条" in result[1]
    assert "序号" not in result[1]


def test_ambiguous_count_question_does_not_guess():
    material = Material("large", "uploaded", "专业表", "",
                        [{"专业": "网络空间安全"}], ["专业"])
    assert exact_count_for_chat([material], "专业有多少人？") is None


def test_computer_major_is_not_split_as_a_calculation_verb():
    material = Material("table", "uploaded", "", "", [{"专业": "计算机"}], ["专业"])
    result = exact_count_for_chat([material], "计算机专业有多少人？")
    assert result is not None and "匹配 1 条记录" in result[1]
    assert "未按身份去重" in result[1]


def test_zero_matches_are_answered_locally_instead_of_sending_rows_to_a_model():
    material = Material("table", "uploaded", "", "", [{"专业": "计算机"}], ["专业"])
    result = exact_count_for_chat([material], "机械工程专业有多少人？")
    assert result is not None and "匹配 0 条记录" in result[1]


def test_small_table_metadata_query_does_not_read_private_rows():
    material = Material("small", "uploaded", "", "原文也有13812345678",
                        [{"姓名": "张明", "电话": "13812345678"}], ["姓名", "电话"])
    selected = select_for_chat([material], "这份表格有哪些字段？")[0]
    assert selected.rows == [] and "张明" not in flatten_material(selected)
    assert "13812345678" not in flatten_material(selected)
    assert "姓名、电话" in selected.text


def test_explicit_projection_and_hard_limits_preserve_source_metadata_without_mutating_source():
    source = Material("table", "uploaded", "", "附带电话13812345678",
                      [{"负责人": "张明", "任务": "布置", "电话": "13812345678", "专业": "无关"}],
                      ["负责人", "任务", "电话", "专业"], allowed_purposes=["meeting_minutes"], expires_at=2000000000)
    view = project_fields(source, "只保留负责人、任务、电话。", task_key="meeting_minutes")
    assert view.columns == ["负责人", "任务"]
    assert view.allowed_purposes == source.allowed_purposes and view.expires_at == source.expires_at
    assert "13812345678" not in flatten_material(view) and "无关" not in flatten_material(view)
    assert source.rows[0]["电话"] == "13812345678" and source.text


def test_ambiguous_semantic_column_request_does_not_guess_a_projection():
    source = Material("table", "uploaded", "", "", [{"甲": "事项", "乙": "日期"}], ["甲", "乙"])
    assert project_fields(source, "只需要重要信息。") is source
