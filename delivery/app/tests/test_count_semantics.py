from llm_shield.chat_retrieval import exact_count_for_chat, project_fields
from llm_shield.schema import Material


def table(rows, columns=None, doc_id='table'):
    return Material(doc_id,'uploaded','','附带私人备注，不属于列投影',rows,columns or ['姓名','专业'])


def test_duplicate_and_same_name_rows_are_records_not_verified_people():
    result = exact_count_for_chat([table([{'姓名':'甲','专业':'计算机'},{'姓名':'甲','专业':'计算机'}])], '计算机专业有多少人？')
    assert '匹配 2 条记录' in result[1]
    assert '不能据此确认人数' in result[1]
    assert '共有 2 人' not in result[1]


def test_normalized_column_and_values_keep_zero_and_fullwidth_text():
    result = exact_count_for_chat([table([{' 专业 ':'ＣＳ'},{' 专业 ':'其他'}],[' 专业 '])], 'CS专业有多少人？')
    assert '匹配 1 条记录' in result[1]


def test_multiple_tables_and_ambiguous_headers_return_local_explanation():
    a = table([{'专业':'计算机'}])
    multi = exact_count_for_chat([a,table([{'专业':'计算机'}],doc_id='other')], '计算机专业有多少人？')
    assert multi is not None and '多张表' in multi[1]
    ambiguous = exact_count_for_chat([table([{'专业':'计算机',' 专业 ':'其他'}],['专业',' 专业 '])], '计算机专业有多少人？')
    assert ambiguous is not None and '无法唯一' in ambiguous[1]


def test_requesting_all_columns_does_not_reintroduce_unrequested_body():
    original = table([{'姓名':'甲','专业':'计算机'}])
    projected = project_fields(original,'只保留姓名、专业。')
    assert '私人备注' not in projected.text and original.text
