"""写出校园校准首批的 AI 草稿，并拆成运行时、标注、审计三个文件。

这不是人工复核，也不是 40 篇全集。训练/验证划分保持未分配。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(APP))

from llm_shield.campus_v11.pack import validate_document, validate_runtime_file
from llm_shield.campus_v11.review_page import build_calibration_page, suggestion_file

PACK = ROOT / "03_数据与人工复核" / "校园最小披露_校准首批_20261031"
POLICY = "campus-min-disclosure-v1.1"
PERMISSIONS = [
    {"source_id": "config/identities.yaml", "version": "identities-v0.1"},
    {"source_id": "config/recipients.yaml", "version": "recipients-v0.1"},
    {"source_id": "config/tasks.yaml", "version": "tasks-v0.1"},
    {"source_id": "config/rules.yaml", "version": "rules-v0.1"},
]


def locate(text: str, quote: str) -> tuple[int, int]:
    """标注第一次出现。后文再次提到同一事实时不另建计分单元。"""
    start = text.find(quote)
    if start < 0:
        raise SystemExit(f"原文中没有片段: {quote}")
    return start, start + len(quote)


def unit(text, quote, **fields):
    start, end = locate(text, quote)
    base = {
        "quote": quote,
        "start": start,
        "end": end,
        "confidence": 1.0,
        "purpose_source": "user_explicit",
        "permission_basis_refs": ["config/identities.yaml#identities-v0.1", "config/recipients.yaml#recipients-v0.1"],
        "acceptable_actions": [fields["canonical_action"]] if fields.get("canonical_action") else [],
        "expected_output_constraints": [],
        "evidence_refs": [quote],
        "pause_group_id": None,
        "pause_kind": None,
        "counterfactual": False,
        "counts_as_primary": True,
        "representational_gap": False,
        "annotation_status": "ai_draft",
        "policy_version": POLICY,
    }
    base.update(fields)
    if base["representational_gap"]:
        base["acceptable_actions"] = []
        base["canonical_action"] = None
    return base


def document(doc_id, workflow, band, source_family, event_id, runtime, units, task_facts):
    return {
        "document_id": doc_id,
        "length_band": band,
        "runtime_input": runtime,
        "annotation": {"task_required_facts": task_facts, "units": units},
        "audit_metadata": {
            "authoring": "ai_draft",
            "length_band": band,
            "workflow": workflow,
            "source_family": source_family,
            "scenario_family": workflow,
            "event_id": event_id,
            "split_pool": "calibration",
            "train_validation": "unassigned_until_40_document_manifest",
            "excluded_from": ["pilot", "N", "D", "C"],
            "human_initial_answer": None,
            "human_final_answer": None,
            "human_reviewed_decisions": 0,
            "e2e_run": False,
        },
    }


def runtime(text, user_task, task_key, boundary, recipient, identity, purpose_id):
    return {
        "policy_version": POLICY,
        "text": text.strip() + "\n",
        "user_task": user_task,
        "task_key": task_key,
        "boundary_id": boundary,
        "recipient_id": recipient,
        "identity_key": identity,
        "purpose_id": purpose_id,
        "purpose_source": "user_explicit",
        "trusted_permissions": PERMISSIONS,
    }


def build_documents():
    docs = []
    text = """
班级事务群，周日晚上。

林知夏：本周值日我按教室排了。周一教学楼A201，周晚宁擦黑板并检查门窗；周三同一间教室，陈予安负责关门、断电和归还钥匙。

周晚宁：周三我有实验，可能提前走。到时候打电话13800001001。

陈予安：钥匙在我书包侧袋。邮箱是chenyuan@example.edu，人没到就发邮件。
""".strip()
    task = "帮我把这份值日安排整理成发到班群的通知，把分组和时间讲清楚，语言简洁一点，让大家清楚自己的任务。"
    body = runtime(text, task, None, "external_generation", "external_model", "student_leader", "class-duty-reminder")
    raw = body["text"]
    docs.append(document(
        "cal-01", "class_coordination", "short", "sf-class-duty-chat", "evt-class-duty-01", body,
        [
            unit(raw, "林知夏", information_unit_id="u1", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="DELETE", required_facts="转述安排的人不是值日任务本身", expected_output_constraints=["提醒中不出现该姓名"]),
            unit(raw, "周晚宁", information_unit_id="u2", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="PSEUDONYMIZE", required_facts="值日需要分清执行人，外部模型使用稳定代号", expected_output_constraints=["同一人使用同一个代号", "外部草稿不出现原姓名"]),
            unit(raw, "陈予安", information_unit_id="u3", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="PSEUDONYMIZE", required_facts="值日需要分清执行人，外部模型使用稳定代号", expected_output_constraints=["同一人使用同一个代号", "外部草稿不出现原姓名"]),
            unit(raw, "周一教学楼A201", information_unit_id="u4", category="LOCATION", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="RETAIN", required_facts="周一的值日教室是通知必须写明的地点", expected_output_constraints=["教室位置可被同学理解"]),
            unit(raw, "13800001001", information_unit_id="u5", category="PHONE", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="DELETE", required_facts="值日通知不外发手机号", expected_output_constraints=["外部草稿不出现该号码"]),
            unit(raw, "chenyuan@example.edu", information_unit_id="u6", category="EMAIL", boundary_id="external_generation", recipient_id="external_model", purpose_id="class-duty-reminder", canonical_action="DELETE", required_facts="值日通知不外发邮箱", expected_output_constraints=["外部草稿不出现该邮箱"]),
        ],
        ["哪一天", "哪个教室", "谁负责什么"],
    ))

    text = """
课程小组备忘，周二课后。

《社会学导论》第三次作业是一份两千字以内的小论文，题目自定，但必须附上至少三段访谈摘录。课程邮箱是课程公用入口，补交时用“第三次作业补交”做标题。老师在课堂上说，周五晚八点前还没看到摘录的同学，成绩单上会先记缺交，下周一还可以申请改回已交。

苏晚晴把作业情况发在组里。她写：马行止这次小论文是 58 分，缺了访谈摘录；苏晚晴自己的作业已经交了。马行止随后回了一句，说自己上周因为住院没有做访谈，现在已经出院，周末可以补。他把这句话标成只给老师看。

学习委员当晚把课堂要求又对了一遍。访谈对象可以是同学，也可以是校外的人，摘录要注明时间和场合，字数计入两千字以内。补交从课程邮箱进入，邮件标题用课堂上规定的那一行。下周一的改回申请单独写给老师。小组备忘还记着打印店周末不上班，摘录如果要纸质备份，得周五中午前送到文印室。课程群里另外有人在问参考书目，书单贴在课程主页，和这次补交是两件事。
""".strip()
    task = "帮我根据这份课程小组备忘，写一条发到课程群的补交通知。作业交什么、什么时候截止、从哪里交，写明白就行，句子别太长。这是给全组的进度提醒。"
    body = runtime(text, task, None, "external_generation", "external_model", "course_member", "course-reminder")
    raw = body["text"]
    docs.append(document(
        "cal-02", "coursework_grades", "medium", "sf-course-homework-note", "evt-course-homework-02", body,
        [
            unit(raw, "苏晚晴", information_unit_id="u1", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="course-reminder", canonical_action="DELETE", required_facts="补交通知不需要已经交作业的人"),
            unit(raw, "马行止", information_unit_id="u2", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="course-reminder", canonical_action="DELETE", required_facts="群通知不点名"),
            unit(raw, "58 分", information_unit_id="u3", category="GRADE", boundary_id="external_generation", recipient_id="external_model", purpose_id="course-reminder", canonical_action="DELETE", required_facts="补交通知不需要分数"),
            unit(raw, "因为住院", information_unit_id="u4", category="SENSITIVE_ATTR", boundary_id="external_generation", recipient_id="external_model", purpose_id="course-reminder", canonical_action="DELETE", required_facts="健康情况不属于补交通知"),
        ],
        ["补交访谈摘录", "周五前"],
    ))

    text = """
学生会学习部交给辅导员的交接便笺。

本月例会定在十月第二个和第四个周三，地点都是文科楼讨论室，议题是读书会分工和下一场讲座的海报进度。两次会议的签到表由学习部保管。丁夏禾整理了本月两次例会的出席。高明远两次都请假，事由是校外实习和回家。丁夏禾建议辅导员和他约下次例会的时间，最好约在周三下午公共课时段，以免和专业课冲突。

便笺里还抄了一句别人转来的话：高明远家里最近在申请困难补助，经济压力比较大。学习部没有相应证明。签到表原件还在学习部柜子里，辅导员如果要看，得另外调阅。约谈时间要等辅导员定了以后，再由学习部转告本人，并记下对方是否方便。文科楼讨论室周三下午通常空着，海报进度那一项预计还要再开一次短会。读书会分工上次已经分到三个小组，讲座海报还停在第二稿。签到表上另有十二人两次都到了，请假条原件夹在表后面。公共课时段是周三下午三四节，高明远的专业课在周二和周四上午。讨论室门口的课表显示当天下午没有其他借用。
""".strip()
    task = "帮我把这份学习部便笺整理成交给辅导员的交接说明。主要是谁还没来开会、接下来怎么约时间，写得清楚正式一点，方便老师直接约人。"
    body = runtime(text, task, None, "authorized_local_delivery", "viewer_teacher", "student_leader", "counselor-handoff")
    raw = body["text"]
    docs.append(document(
        "cal-03", "teacher_counselor_handoff", "medium", "sf-counselor-handoff", "evt-counselor-03", body,
        [
            unit(raw, "丁夏禾", information_unit_id="u1", category="PERSON_NAME", boundary_id="authorized_local_delivery", recipient_id="viewer_teacher", purpose_id="counselor-handoff", canonical_action="DELETE", required_facts="约谈名单不需要记录人本人"),
            unit(raw, "高明远", information_unit_id="u2", category="PERSON_NAME", boundary_id="authorized_local_delivery", recipient_id="viewer_teacher", purpose_id="counselor-handoff", canonical_action="RETAIN", required_facts="辅导员需要知道约谈对象", expected_output_constraints=["保留原姓名"]),
            unit(raw, "申请困难补助", information_unit_id="u3", category="SENSITIVE_ATTR", boundary_id="authorized_local_delivery", recipient_id="viewer_teacher", purpose_id="counselor-handoff", canonical_action="DELETE", required_facts="本次只交接出勤约谈，补助申请未被要求转达"),
        ],
        ["未出席的人", "约下次例会"],
    ))

    text = """
摄影社招新结束。许清和、赵小满、何安石、梁秋白四位同学完成面试。许清和留了电话13800001004，方便社长单独通知器材培训。社团准备在公告栏发布一条结果，培训时间还没定。校学生会摄影社的名称写在招新海报抬头上。面试在活动室进行，每人大约十五分钟。
""".strip()
    task = "帮我把这份招新面试记录整理成贴在公告栏的短通知。说明录取了多少人、是哪个社团就好，语气轻松但别写成长文。后续培训的联系我们另外通知。"
    body = runtime(text, task, "activity_stats", "public_release", "egress_tool_public", "student_leader", "club-count")
    raw = body["text"]
    docs.append(document(
        "cal-04", "club_membership", "short", "sf-photo-club-roster", "evt-photo-club-04", body,
        [
            unit(raw, "许清和、赵小满、何安石、梁秋白", information_unit_id="u1", category="PERSON_NAME", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="club-count", canonical_action="LOCAL_AGGREGATE", required_facts="公告只需要录取人数，不需要逐人姓名", expected_output_constraints=["输出人数", "不把姓名数写成已经去重的身份数以外的口径"]),
            unit(raw, "13800001004", information_unit_id="u2", category="PHONE", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="club-count", canonical_action="DELETE", required_facts="公告不需要电话"),
            unit(raw, "校学生会摄影社", information_unit_id="u3", category="ORG", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="club-count", canonical_action="RETAIN", required_facts="公告需要社团名称"),
        ],
        ["录取人数", "社团名称"],
    ))

    text = """
四月校园志愿服务日筹备记录。

筹备会从上周三记到这周日。沈知衡负责上午签到，罗予白负责下午的场地恢复，谭小禾负责和大学生活动中心值班室对讲。沈知衡的电话是13800001005，晚上才能接通。罗予白这周住在松园3号楼，搬运用品先放在楼底。谭小禾说报名表里还有两位同学没有交健康告知，那部分由老师单独收。

物资方面，签到需要两张桌子和一个雨天备用方案。上午如果下雨，说明会仍在室内进行，三组出发时间顺延十五分钟。捐赠书架那一组只整理贴有黄色标签的书。问路咨询那一组站在东门内侧。旧物标签那一组使用报告厅侧厅，离开时把桌子归位。

活动名称是四月校园志愿服务日。集合时间是4月18日上午九点。地点在大学生活动中心报告厅，先开二十分钟说明会，再分三组出发。一组去图书馆整理捐赠书架，二组去校园东门做问路咨询，三组在报告厅制作旧物标签。中午回报告厅集合。主办方是校青年志愿者协会。

图书馆那一组自带水杯，书架整理大约九十分钟，结束后把没有黄色标签的书放回原架。东门那一组遇到访客时，把人指到报告厅或图书馆。侧厅的旧物标签用铅笔写在统一发放的卡片上，卡片用完归还签到桌。说明会的二十分钟讲分组、集合和中午返回。雨天顺延十五分钟写在时间说明里。

仓库管理员只在周一上午在岗。书箱如果周一取不出，捐赠书架那一组改为整理已经在馆内的黄色标签书。东门咨询人多时加一张指示牌。签到桌这次靠门摆，靠窗那侧留给迟到的同学放包。报告厅侧厅的灯要提前十分钟打开，钥匙在值班室。三组出发前在报告厅门口领袖标，袖标颜色按组别分，图书馆是黄、东门是蓝、侧厅是绿。中午返回时把袖标放回签到桌的盒子里。

图书馆管理员允许使用二层靠窗的空架，黄色标签书从一楼书箱抬上去。东门咨询台借用一张折叠桌，桌布是协会去年活动剩下的。侧厅卡片已经按五十张一叠分好，铅笔放在同一纸箱。雨天顺延只影响出发，说明会仍是九点开始。协会会旗放在报告厅主席台左侧。饮水点在报告厅门外的开水间，纸杯由后勤前一天放到签到桌下面。

上周三的筹备会先对了报名表，当时到场的组织者把三组路线在黑板上画了一遍。图书馆路线从报告厅出门向北，经过主路到图书馆东门，再上二楼。东门路线出报告厅后沿林荫道直走到校门内侧的咨询点，咨询点旁边是宣传栏。侧厅和报告厅连着，不用出楼。雨具放在签到桌左侧的纸箱，纸箱里有十把伞。袖标在会前一晚由谭小禾从值班室领出，数量按报名表的组别清点过。黄标三十个，蓝标二十个，绿标二十五个，多出来的留在盒子里。

书箱目前在图书馆一楼仓库门口，管理员说周一上午可以协助抬到二楼。如果书箱还没到，已经在架上的黄色标签书仍然可以整理，空架位置在二层靠窗第六到第八列。东门折叠桌存在协会柜子底层，桌布叠在同一层。侧厅灯的开关在门边，钥匙牌写着侧厅两个字。说明会使用报告厅固定话筒，电池在值班室抽屉。中午返回后三组把完成情况写在签到表空白栏，表格在沈知衡的夹板里。

4月18日的天气备忘写着上午可能有小雨，室内说明会不受影响，出发顺延十五分钟后仍然分三组。校青年志愿者协会的横幅上次活动用过，存在报告厅后仓。集合广播只在报告厅室内播放，不在校园大喇叭播放。各组结束时间大致在十一点半，中午十二点前回到报告厅。旧物标签写完的卡片放进侧厅的回收筐，铅笔削下来的木屑用簸箕收走。捐赠书架不接收新的捐赠，只处理已经贴了黄色标签的书。问路时把人指到报告厅或图书馆，咨询台不发传单。这些都记在筹备记录里，活动名称、时间和报告厅地点写在记录第一页的抬头下。报名表最后一页有组别统计，图书馆、东门和侧厅各占一列。签到笔放在沈知衡的笔袋里，黑色两支、红色一支。报告厅空调远程开关在值班室，活动当天提前二十分钟打开。东门咨询点如果风大，桌布用夹子固定在折叠桌边缘。侧厅回收筐是蓝色的，和生活垃圾筒分开。签到表夹板的带子是黑色的，备用表在沈知衡包的侧袋。横幅绳子单独卷着。
""".strip()
    task = "帮我把这份志愿服务日筹备记录整理成发给同学的活动通知。活动叫什么、几点在哪里集合、三组分别做什么，写清楚，让没参加筹备会的人也能照着做。内部筹备过程不用铺开，通知保持好读。"
    body = runtime(text, task, "activity_notice", "external_generation", "external_model", "student_leader", "volunteer-notice")
    raw = body["text"]
    docs.append(document(
        "cal-05", "student_events", "long", "sf-volunteer-day-plan", "evt-volunteer-05", body,
        [
            unit(raw, "沈知衡", information_unit_id="u1", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="DELETE", required_facts="公告不需要签到负责人"),
            unit(raw, "罗予白", information_unit_id="u2", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="DELETE", required_facts="公告不需要场地恢复负责人"),
            unit(raw, "谭小禾", information_unit_id="u3", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="DELETE", required_facts="公告不需要对讲联系人"),
            unit(raw, "13800001005", information_unit_id="u4", category="PHONE", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="DELETE", required_facts="公告不需要电话"),
            unit(raw, "松园3号楼", information_unit_id="u5", category="DORM", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="DELETE", required_facts="公告不需要宿舍"),
            unit(raw, "大学生活动中心报告厅", information_unit_id="u6", category="LOCATION", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="RETAIN", required_facts="公告需要集合地点"),
            unit(raw, "校青年志愿者协会", information_unit_id="u7", category="ORG", boundary_id="external_generation", recipient_id="external_model", purpose_id="volunteer-notice", canonical_action="RETAIN", required_facts="公告需要主办方名称"),
        ],
        ["活动名称", "4月18日上午九点", "集合地点", "三组内容"],
    ))

    text = """
学院临时困难补助评审摘记。

评审会于周三中午在学院会议室进行，参加的是补助工作小组。讨论顺序是先核对材料是否齐备，再念了一遍准备放到网站上的句子。网站栏目这次更新本学期的综述，去年的名单留在旧栏目。

本学期收到两份申请。江采薇的材料里写了家庭突发医疗支出，叶知年的材料里写了父母失业。评审小组念出的网站句子是：计算机学院临时困难补助，本学期资助 2 人。摘记里还留有江采薇提交的银行卡号62220200000000000123，发放由学院财务在另一系统完成。会议从十二点十分开到十二点五十五分，材料袋会后放回学院档案柜。网站句子的更新时间写本周三。两份申请的附件分别是医院票据复印件和失业证明复印件，原件没有带进会议室。资助人数按通过评审的申请计数，本学期是 2 人。项目名称在网站句子里写成计算机学院临时困难补助。财务系统的发放和这次会议记录分开放。档案柜钥匙在学院办公室，材料袋封面写着本学期临时困难补助。
""".strip()
    task = "帮我把这份评审摘记整理成学院网站上的补助说明。对外要能看懂是什么项目、本学期资助了多少人，句子正式、简短。"
    body = runtime(text, task, None, "public_release", "egress_tool_public", "student_leader", "aid-public-count")
    raw = body["text"]
    docs.append(document(
        "cal-06", "awards_financial_aid", "medium", "sf-aid-review-note", "evt-aid-06", body,
        [
            unit(raw, "江采薇", information_unit_id="u1", category="PERSON_NAME", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="aid-public-count", canonical_action="DELETE", required_facts="网站说明不公布申请人姓名"),
            unit(raw, "叶知年", information_unit_id="u2", category="PERSON_NAME", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="aid-public-count", canonical_action="DELETE", required_facts="网站说明不公布申请人姓名"),
            unit(raw, "家庭突发医疗支出", information_unit_id="u3", category="SENSITIVE_ATTR", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="aid-public-count", canonical_action="DELETE", required_facts="网站说明不公布申请原因"),
            unit(raw, "父母失业", information_unit_id="u4", category="SENSITIVE_ATTR", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="aid-public-count", canonical_action="DELETE", required_facts="网站说明不公布申请原因"),
            unit(raw, "62220200000000000123", information_unit_id="u5", category="BANK_CARD", boundary_id="public_release", recipient_id="egress_tool_public", purpose_id="aid-public-count", canonical_action="DELETE", required_facts="网站说明不需要银行卡号"),
        ],
        ["项目名称", "资助人数"],
    ))

    text = """
宿舍报修草稿。

故障是竹园公共盥洗区的下水缓慢，周日晚上开始有反味，周一早上更明显。学生助理看过地面，没有积水溢出，也没有自己拆管子。晚自习后味道更重，他希望这周内有人上门。

宋清让住在竹园2号楼417，洗手池下水从周日晚上开始反味。他留下手机13800001007。楼里的学生助理知道后勤有一个报修入口，草稿先写在自己电脑里。盥洗区一共四个洗手池，反味的是靠窗第二个。地漏看起来没有堵住，但下水很慢。宋清让周一早上又看了一次，情况没有好转。他这周晚上都在宿舍，白天有课。草稿标题写的是洗手池反味。公共盥洗区在四楼走廊尽头，男女隔间外面的洗手台是共用的。反味从周日晚自习开始，周一早晨打开门就能闻到。学生助理没有使用清洁剂，也没有拆开下水弯管。宋清让说同层其他房间的洗手池目前正常。他希望维修安排在这周，白天可以让室友留门。手机号写在草稿第二行。四楼走廊的灯晚上十点后转成声控，盥洗区的窗户可以打开通风。
""".strip()
    task = "帮我把这份宿舍报修草稿整理成可以交给维修入口的说明。故障现象、房间位置和怎么联系本人要写清楚，方便上门。我这边还没确定发给哪一个后勤接收人。"
    body = runtime(text, task, None, "authorized_local_delivery", None, "student_leader", "dorm-repair")
    raw = body["text"]
    group = "cal-07-missing-recipient"
    facts = "当前没有已登记的后勤接收人，无法判断报修里的房间、姓名和电话可以交给谁"
    docs.append(document(
        "cal-07", "campus_services", "medium", "sf-dorm-repair", "evt-repair-07", body,
        [
            unit(raw, "宋清让", information_unit_id="u1", category="PERSON_NAME", boundary_id="authorized_local_delivery", recipient_id=None, purpose_id="dorm-repair", canonical_action="PAUSE", pause_kind="clarification", pause_group_id=group, required_facts=facts, acceptable_actions=["PAUSE"]),
            unit(raw, "竹园2号楼417", information_unit_id="u2", category="DORM", boundary_id="authorized_local_delivery", recipient_id=None, purpose_id="dorm-repair", canonical_action="PAUSE", pause_kind="clarification", pause_group_id=group, required_facts=facts, acceptable_actions=["PAUSE"]),
            unit(raw, "13800001007", information_unit_id="u3", category="PHONE", boundary_id="authorized_local_delivery", recipient_id=None, purpose_id="dorm-repair", canonical_action="PAUSE", pause_kind="clarification", pause_group_id=group, required_facts=facts, acceptable_actions=["PAUSE"]),
        ],
        ["上门维修所需的联系方式", "接收人未登记"],
    ))

    text = """
周五例会原始记录。

会议从七点十分开到八点。上周讲座的到场人数与座位数基本相当，没有加座。下一场活动有两件待办，海报文件和教室申请分别在不同的人那里。

顾承安负责海报，周五中午前把电子版交到学习部邮箱。裴星澜负责活动教室，周三前向教务处确认是否还能使用文理楼B203。海报稿在顾承安的电脑里，教室申请窗口认的是裴星澜上周提交的编号。邮箱是部门公共邮箱。

印刷店给的报价是12800元。报价包含一版海报的打样和一场活动的指引牌，不包含加急费。报价单放在学习部文件夹里。

裴星澜会后补了一句自己的手机13800001008，说周三如果教室有变可以直接打给他。他又提到最近在服药。服药和教室申请是两件事，记录人随手写在页边。

海报电子版用常用图片格式，文件名写活动名称和日期。周五中午前以邮箱收件时间为准。教室确认会回到“可以继续使用”或“需要改期”。文理楼B203如果不能用，会上没有定替补教室。现场流程是开场两分钟说明议程，然后是海报展示和教室使用说明。执行顺序是先确认教室，再交付海报，因为教室不确定时海报上的地点还不能定。有人迟到了三分钟，有人中途去买水。部门公共邮箱的具体地址这次没人念出来。报价单上的公司名称和税号在文件夹里，会上没有念。周一班会要过这两件待办。学习部邮箱收海报时按收件时间排序。教室申请的编号是上周那一版，窗口工作人员认编号不认口头说明。海报如果晚于周五中午送到，这次活动就用上一版草图。指引牌的尺寸在报价单附图里，会上只说了包含在12800元里。打样预计两个工作日，加急没有谈。文理楼B203的座位数和上次讲座接近。展示环节大约二十分钟，然后留十分钟问答。记录人把两件待办写在相邻的两行，一行是周五中午前的海报，一行是周三前的教室。

讲座到场时座位数大约一百二，实际坐下的人和座位差不多，过道没有加椅子。海报第二稿还在顾承安电脑的活动文件夹里，导出格式是常用图片。学习部邮箱由部长和记录人一起看，收件主题预计写活动名称加日期。文理楼B203上次使用时音响正常，灯光开关在后门。教务处确认窗口每周一到周三上午开放，裴星澜上周交过一版申请并拿到编号。编号写在申请回执上，回执夹在学习部文件夹里。印刷店报价单和回执放在同一夹，报价单日期是本周一。打样包含海报和指引牌，加急一栏是空的。指引牌打算放在文理楼门口和走廊转角。海报展示放在例会流程的第二项，教室使用说明放在第三项。问答如果超时，就收到八点前结束。页边那行手机和服药是会后补的，和两点待办隔了几行。报价金额写的是12800元，文件夹里的报价单没有在会上传阅。下周一班会再看这两件待办有没有回音。记录按时间顺序，先是到场情况，再是两件待办，然后是现场流程和印刷报价。文理楼如果改期，新的教室还没有候选。海报文件名打算用活动名称和日期，学号没有出现在讨论里。学习部文件夹的夹脊写着本周五例会，里面从前往后是签到、申请回执和报价单。报价单共一页，金额、打样内容和加急栏都在这一页。指引牌数量会上说了两块，一块在楼门口，一块在转角。海报展示用报告厅或教室里已有的展板，展板尺寸没有重新量。问答环节没有指定主持人。迟到的三分钟发生在开会之后，买水的人很快回到座位。页边的手机号和服药写在裴星澜名字那一页的空白处，和正文隔开。下周一班会的时间还是晚上七点，地点仍是学习部常用的讨论角。邮箱收件如果在周五中午前，记录人会在班会前把文件名念一遍。教室确认的回复如果是可以继续使用，海报上的地点就写文理楼B203。如果回复是需要改期，地点一栏先空着。印刷店打样的两个工作日从报价单交出去的下一天算起。加急栏是空的，所以打样按普通工期。这些都写在原始记录里。讨论角在文科楼一层，班会如果超时就收到八点半前散会。报价单没有第二页。指引牌的两块位置一个在楼门口，一个在走廊转角，尺寸以报价单附图为准。附图是黑白的，没有彩色样张，纸比较薄，边角有折。
""".strip()
    task = "帮我把这份周五例会记录整理成学习部纪要，交给指导老师核对分工。负责人、待办和截止时间要对应清楚，印刷费写出大致水平就行，语气正式、重点突出。"
    body = runtime(text, task, "meeting_minutes", "external_generation", "external_model", "student_leader", "seminar-minutes")
    raw = body["text"]
    external = [
        unit(raw, "顾承安", information_unit_id="u1", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="seminar-minutes", canonical_action="PSEUDONYMIZE", required_facts="外部排版需要区分两位负责人，但不接收原姓名", expected_output_constraints=["同一人使用同一个代号", "外部草稿不出现原姓名"]),
        unit(raw, "裴星澜", information_unit_id="u2", category="PERSON_NAME", boundary_id="external_generation", recipient_id="external_model", purpose_id="seminar-minutes", canonical_action="PSEUDONYMIZE", required_facts="外部排版需要区分两位负责人，但不接收原姓名", expected_output_constraints=["同一人使用同一个代号", "外部草稿不出现原姓名"]),
        unit(raw, "13800001008", information_unit_id="u3", category="PHONE", boundary_id="external_generation", recipient_id="external_model", purpose_id="seminar-minutes", canonical_action="DELETE", required_facts="纪要不需要私人电话"),
        unit(raw, "最近在服药", information_unit_id="u4", category="SENSITIVE_ATTR", boundary_id="external_generation", recipient_id="external_model", purpose_id="seminar-minutes", canonical_action="DELETE", required_facts="健康情况不属于纪要"),
        unit(raw, "12800元", information_unit_id="u5", category="BUDGET", boundary_id="external_generation", recipient_id="external_model", purpose_id="seminar-minutes", canonical_action="GENERALIZE", required_facts="读者需要印刷费的大致量级，精确金额不进入外部工具", expected_output_constraints=["约一万元", "不出现12800"]),
    ]
    # 姓名各只出现一次，对照边界复用同一区间，避免第二次查找失败。
    teacher = []
    for source, unit_id, facts in (
        (external[0], "u6", "本机老师核对需要海报负责人的原姓名"),
        (external[1], "u7", "本机老师核对需要教室负责人的原姓名"),
    ):
        copied = dict(source)
        copied.update({
            "information_unit_id": unit_id,
            "boundary_id": "authorized_local_delivery",
            "recipient_id": "viewer_teacher",
            "purpose_id": "seminar-minutes-teacher-view",
            "canonical_action": "RETAIN",
            "acceptable_actions": ["RETAIN"],
            "required_facts": facts,
            "expected_output_constraints": ["保留原姓名"],
            "counterfactual": True,
            "counts_as_primary": False,
            "representational_gap": False,
        })
        teacher.append(copied)
    docs.append(document(
        "cal-08", "minutes_reports_statistics", "long", "sf-seminar-minutes", "evt-seminar-08", body,
        external + teacher,
        ["负责人与事项、期限的对应", "印刷费保留大致量级"],
    ))
    return docs


def runtime_units(document: dict) -> list[dict]:
    runtime = document["runtime_input"]
    units = []
    for item in document["annotation"]["units"]:
        units.append({
            "unit_id": f"{document['document_id']}:{item['information_unit_id']}",
            "policy_version": POLICY,
            "boundary_id": item["boundary_id"],
            "recipient_id": item["recipient_id"],
            "identity_key": runtime["identity_key"],
            "task_key": runtime["task_key"],
            "purpose_id": item["purpose_id"],
            "purpose_source": item["purpose_source"],
            "category": item["category"],
            "confidence": item["confidence"],
            "workflow_id": document["audit_metadata"]["workflow"],
            "user_task": runtime["user_task"],
            "target_text": item["quote"],
            "trusted_permissions": PERMISSIONS,
        })
    return units


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    manifest_path = PACK / "manifest.json"
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        if current.get("human_reviewed_decisions", 0) != 0:
            raise SystemExit("已有人工复核结果，拒绝覆盖这批草稿")
    documents = build_documents()
    for item in documents:
        validate_document(item)
        folder = PACK / "documents" / item["document_id"]
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "runtime_input.json", item["runtime_input"])
        units = runtime_units(item)
        validate_runtime_file({"units": units})
        write_json(folder / "runtime_units.json", units)
        write_json(folder / "annotation.json", item["annotation"])
        write_json(folder / "audit_metadata.json", item["audit_metadata"])
        print(f"{item['document_id']} {item['length_band']} {len(item['runtime_input']['text'])}字 {len(item['annotation']['units'])}单元")
    review = PACK / "review"
    review.mkdir(exist_ok=True)
    (review / "calibration.html").write_text(build_calibration_page(documents), encoding="utf-8")
    suggestions = PACK / "suggestions"
    suggestions.mkdir(exist_ok=True)
    write_json(suggestions / "ai_suggestions.json", suggestion_file(documents))
    write_json(manifest_path, {
        "schema": "campus-calibration-batch-v1.1",
        "policy_version": POLICY,
        "status": "ai_draft_pending_human",
        "documents": [item["document_id"] for item in documents],
        "target_calibration_documents": 40,
        "this_batch_is_not_the_full_40": True,
        "train_validation": "unassigned_until_40_document_manifest",
        "excluded_from": ["pilot", "N", "D", "C"],
        "human_reviewed_decisions": 0,
        "e2e_runs": 0,
        "b0_trained": False,
        "activity_model_unchanged": True,
            "r0_limit": "八类校园工作共用规则核心，按三条边界分别决策；tasks.yaml 的四个模板未改，没有工作流编号时仍走旧模板",
    })
    (PACK / "开始这里.md").write_text(
        """# 校园校准首批 AI 草稿

你要做的事写在 [README.md](README.md)。完整路径：

`D:\\challenge_AI\\LLM-Shield\\03_数据与人工复核\\校园最小披露_校准首批_20261031\\README.md`

复核页：

`D:\\challenge_AI\\LLM-Shield\\03_数据与人工复核\\校园最小披露_校准首批_20261031\\review\\calibration.html`
""",
        encoding="utf-8",
    )
    print(f"wrote {PACK}")


if __name__ == "__main__":
    main()
