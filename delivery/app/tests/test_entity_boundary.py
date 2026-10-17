"""机构 / 地点 / 人名 / 密钥 的边界回归测试。

这批用例全部来自人工 gold 评测暴露的真实错例，改动识别规则前请先跑：
    python -m pytest tests/test_entity_boundary.py -q
"""
from llm_shield.m2_detect.pipeline import build_detectors, detect_all
import pytest
from llm_shield.m2_detect.pipeline import detect_all
from llm_shield.m2_detect.entity_rules import EntityDetector

def spans(text, category=None):
    out = [(s.text, s.category) for s in detect_all(text)]
    return out if category is None else [t for t, c in out if c == category]

@pytest.mark.parametrize('text,orgs', [('实际系统不得明文存储。', []), ('王芳负责联系三家赞助商，截止日期为3月25日。', []), ('覆盖计算机学院、经济管理学院等主要院系。', ['计算机学院', '经济管理学院']), ('校团委志愿服务中心主办本次活动。', ['校团委志愿服务中心']), ('计算机系与物理系联合举办了讲座。', ['计算机系', '物理系'])])
def test_org_boundary(text, orgs):
    assert spans(text, 'ORG') == orgs

def test_org_strips_leadin_verbs():
    """动词引导词不是机构名的一部分：「覆盖计算机学院」实为「计算机学院」。"""
    assert EntityDetector()._trim_org('覆盖计算机学院') == '计算机学院'
    assert EntityDetector()._trim_org('经济管理学院等主要院系') == '经济管理学院'

@pytest.mark.parametrize('text,locs', [('场地借用申请由赵磊提交至后勤处，目前待审批。', ['后勤处']), ('会议地点：学生活动中心305会议室。', ['学生活动中心305会议室']), ('活动地点：中心操场。', ['中心操场']), ('这个问题处理起来很麻烦。', []), ('到处都找不到负责人。', [])])
def test_location_boundary(text, locs):
    assert spans(text, 'LOCATION') == locs

@pytest.mark.parametrize('text,names', [('参会人员：李晓华、王芳、赵磊、陈静共5人。', ['李晓华', '王芳', '赵磊', '陈静']), ('周涛负责后端接口，孙悦负责前端页面，刘洋负责测试与上线。', ['周涛', '孙悦', '刘洋']), ('本周五前完成海报，负责人尚未确定。', []), ('计算机学院的周涛同学负责本次活动的招新海报。', ['周涛']), ('他就是赵磊部长。', ['赵磊']), ('我的中学同学最近很忙。', []), ('新的高层任命尚未公布。', []), ('李白的诗歌很美。', [])])
def test_person_boundary(text, names):
    assert sorted(spans(text, 'PERSON_NAME')) == sorted(names)

def test_person_name_never_ends_with_function_word():
    assert EntityDetector()._trim_name_tail('陈静共') == '陈静'
    assert EntityDetector()._trim_name_tail('欧阳修') == '欧阳修'

def test_api_key_covers_whole_assignment():
    """与 m9_data/synthesize.py 及人工 gold 一致：整段「键名=值」是一个实体。"""
    assert spans('新口令为 api_key=ClubSecret2026March ，仅限内部。', 'API_KEY') == ['api_key=ClubSecret2026March']

def test_detection_still_fast():
    import time
    text = '会议地点：学生活动中心305会议室。主持人：张明。覆盖计算机学院、经济管理学院等主要院系。' * 30
    t0 = time.perf_counter()
    detect_all(text)
    assert (time.perf_counter() - t0) * 1000 < 500
