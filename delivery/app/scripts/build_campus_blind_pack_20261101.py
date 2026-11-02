"""写出校园必要性盲标空白包。不调用模型，不调用 R0，不填写动作。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101"
BLOCKED = (
    "林知夏", "周晚宁", "陈予安", "沈知衡", "罗予白", "谭小禾", "许清和", "赵小满",
    "何安石", "梁秋白", "丁夏禾", "高明远", "苏晚晴", "马行止", "江采薇", "叶知年",
    "宋清让", "顾承安", "裴星澜", "赵启明", "钱书宁", "孙望舒", "吴清和", "祁晏清",
    "孟疏桐", "贺清川", "阮星迟", "乔予舟", "纪疏影", "温晚宁", "马听澜",
    "12800", "8600", "2400", "9750", "5300", "17640", "4280", "13800001", "1391111",
)
FORBIDDEN_KEYS = {
    "r0_action", "r0_reason", "model_action", "model_argmax", "probabilities",
    "policy_action", "suggested_action", "gold_action", "expected_action",
}


def blank() -> dict:
    return {
        "canonical_action": "",
        "required_facts": "",
        "adjudication": "",
        "notes": "",
        "annotator": "",
        "annotated_at": "",
    }


def unit(uid, quote, category, boundary, recipient, recipient_name, *,
         identity="student_leader", identity_name="学生组织负责人", user_task=""):
    return {
        "unit_id": uid,
        "quote": quote,
        "category": category,
        "boundary_id": boundary,
        "boundary_name": {
            "external_generation": "发给外部生成",
            "authorized_local_delivery": "授权本机查看",
            "public_release": "公开发布",
        }[boundary],
        "recipient_id": recipient,
        "recipient_name": recipient_name,
        "identity_key": identity,
        "identity_name": identity_name,
        "user_task": user_task,
        "annotation": blank(),
    }


def doc(pool, did, text, user_task, workflow_id, task_key, workflow_name, units):
    return {
        "pool": pool,
        "document_id": did,
        "text": text,
        "user_task": user_task,
        "workflow_id": workflow_id,
        "task_key": task_key,
        "workflow_name": workflow_name,
        "units": units,
    }


def pack() -> list[dict]:
    cal, test = "calibration", "test"
    duty = "class_coordination"
    notice = ("student_events", "activity_notice", "活动公告")
    club = ("club_membership", "activity_stats", "社团统计")
    minutes = ("minutes_reports_statistics", "meeting_minutes", "会议纪要")
    intro = ("", "project_intro", "项目介绍")
    return [
        doc(cal, "c01",
            "周四晚自习柏景行负责收问卷，俞清晏负责关投影。地点在经管楼D104。临时电话15100004001。",
            "帮我整理成发到班群前的值日通知，谁收问卷、谁关投影写清楚。",
            duty, duty, "班级协作", [
                unit("c01-u1", "柏景行", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c01-u2", "俞清晏", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c01-u3", "经管楼D104", "LOCATION", "external_generation", "external_model", "外部生成服务"),
                unit("c01-u4", "15100004001", "PHONE", "external_generation", "external_model", "外部生成服务"),
                unit("c01-u5", "柏景行", "PERSON_NAME", "authorized_local_delivery", "viewer_teacher", "指导老师",
                     user_task="整理成给班主任本机查看的值日表，负责人写明白。"),
            ]),
        doc(cal, "c02",
            "登山分享会由傅晚桐主持，集合在山脚校门，联系邮箱bo@studio.example.edu。",
            "帮我写一条登山分享会的群公告，集合地点说清楚，话少一点。",
            *notice, [
                unit("c02-u1", "傅晚桐", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c02-u2", "山脚校门", "LOCATION", "external_generation", "external_model", "外部生成服务"),
                unit("c02-u3", "bo@studio.example.edu", "EMAIL", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(cal, "c03",
            "校登山社这学期录取了姜书迟和倪星澜。联系电话15100004002。",
            "做一份社团录取统计，对外说明录取人数和社团名称就行。",
            *club, [
                unit("c03-u1", "姜书迟", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c03-u2", "倪星澜", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c03-u3", "校登山社", "ORG", "external_generation", "external_model", "外部生成服务"),
                unit("c03-u4", "15100004002", "PHONE", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(cal, "c04",
            "例会由柏景行对接海报并对花生严重过敏，俞清晏对接场地。海报印刷费7350元。",
            "把例会整理成纪要，负责人和事项要对应，印刷费写出大概范围就可以。",
            *minutes, [
                unit("c04-u1", "柏景行", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c04-u2", "俞清晏", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c04-u3", "7350元", "BUDGET", "external_generation", "external_model", "外部生成服务"),
                unit("c04-u4", "对花生严重过敏", "SENSITIVE_ATTR", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(cal, "c05",
            "山地安全手册项目由傅晚桐起草，合作单位是校登山社，内部印刷预算15280元。",
            "把这个项目说明改成可以放进招新手册的介绍。",
            *intro, [
                unit("c05-u1", "傅晚桐", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("c05-u2", "校登山社", "ORG", "external_generation", "external_model", "外部生成服务"),
                unit("c05-u3", "15280元", "BUDGET", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(cal, "c06",
            "器材清点可以找姜书迟。",
            "帮我整理成一条器材通知。",
            duty, duty, "班级协作", [
                unit("c06-u1", "姜书迟", "PERSON_NAME", "external_generation", "", "未指定"),
            ]),
        doc(test, "t01",
            "周五活动室使用，崔予宁负责收签到表，邵闻舟负责锁门。地点在东区体育馆副馆。电话15200005001。",
            "整理成班群通知，写清谁收签到、谁锁门。",
            duty, duty, "班级协作", [
                unit("t01-u1", "崔予宁", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t01-u2", "邵闻舟", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t01-u3", "东区体育馆副馆", "LOCATION", "external_generation", "external_model", "外部生成服务"),
                unit("t01-u4", "15200005001", "PHONE", "external_generation", "external_model", "外部生成服务"),
                unit("t01-u5", "崔予宁", "PERSON_NAME", "authorized_local_delivery", "viewer_peer", "同班同学",
                     user_task="整理成同班同学本机查看的分工说明。"),
                unit("t01-u6", "崔予宁", "PERSON_NAME", "authorized_local_delivery", "viewer_teacher", "指导老师",
                     user_task="整理成班主任本机查看的分工说明。"),
                unit("t01-u7", "邵闻舟", "PERSON_NAME", "public_release", "egress_tool_public", "公开发布",
                     user_task="整理成可以张贴在活动室门口的分工说明。"),
            ]),
        doc(test, "t02",
            "观鸟行由董南枝召集，集合在实验楼3层会议室，住柳园8号楼112，邮箱cui@studio.example.edu。",
            "写一条观鸟行公告，把集合地点写清楚。",
            *notice, [
                unit("t02-u1", "董南枝", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t02-u2", "实验楼3层会议室", "LOCATION", "external_generation", "external_model", "外部生成服务"),
                unit("t02-u3", "柳园8号楼112", "DORM", "external_generation", "external_model", "外部生成服务"),
                unit("t02-u4", "cui@studio.example.edu", "EMAIL", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(test, "t03",
            "院学术部这学期录取了邹清越和魏晚舟。联系电话15200005002。微信wx_zou_demo。",
            "整理学术部录取情况，公告里保留人数和部门名称。",
            *club, [
                unit("t03-u1", "邹清越", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t03-u2", "魏晚舟", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t03-u3", "院学术部", "ORG", "external_generation", "external_model", "外部生成服务"),
                unit("t03-u4", "15200005002", "PHONE", "external_generation", "external_model", "外部生成服务"),
                unit("t03-u5", "wx_zou_demo", "WECHAT", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(test, "t04",
            "例会决定汤予迟对接印刷并正在接受复健，萧行远对接签到。印刷费24600元。电话15200005003。",
            "整理成会议纪要，人和事对应，印刷费有个粗略印象就行。",
            *minutes, [
                unit("t04-u1", "汤予迟", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t04-u2", "萧行远", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t04-u3", "24600元", "BUDGET", "external_generation", "external_model", "外部生成服务"),
                unit("t04-u4", "正在接受复健", "SENSITIVE_ATTR", "external_generation", "external_model", "外部生成服务"),
                unit("t04-u5", "15200005003", "PHONE", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(test, "t05",
            "康书白对接订餐，尹晚杉对接摄影。订餐费6180元。",
            "整理成纪要交给指导老师核对，订餐花费按收据上的数字留下。",
            *minutes, [
                unit("t05-u1", "康书白", "PERSON_NAME", "authorized_local_delivery", "viewer_teacher", "指导老师"),
                unit("t05-u2", "尹晚杉", "PERSON_NAME", "authorized_local_delivery", "viewer_teacher", "指导老师"),
                unit("t05-u3", "6180元", "BUDGET", "authorized_local_delivery", "viewer_teacher", "指导老师"),
            ]),
        doc(test, "t06",
            "程石川负责采购，万小禾负责报销。采购费9900元。",
            "先交给外部模型起草纪要，采购费按发票上的原数字写上。",
            *minutes, [
                unit("t06-u1", "程石川", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t06-u2", "万小禾", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t06-u3", "9900元", "BUDGET", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(test, "t07",
            "钟知远负责茶歇。茶歇费890元。",
            "写成同班同学本机能看的纪要，茶歇费用按账单原数写上。",
            *minutes, [
                unit("t07-u1", "钟知远", "PERSON_NAME", "authorized_local_delivery", "viewer_peer", "同班同学"),
                unit("t07-u2", "890元", "BUDGET", "authorized_local_delivery", "viewer_peer", "同班同学"),
            ]),
        doc(test, "t08",
            "冯清澜负责纪要归档。资料打印费11220元。",
            "帮我把例会记录整理顺，语气正式一点。",
            *minutes, [
                unit("t08-u1", "冯清澜", "PERSON_NAME", "external_generation", "external_model", "外部生成服务"),
                unit("t08-u2", "11220元", "BUDGET", "external_generation", "external_model", "外部生成服务"),
            ]),
        doc(test, "t09",
            "学院网站的资助介绍稿里写了姚星河对尘螨过敏，资助卡号622200000000009999。",
            "写一段可以挂在学院网站上的资助介绍。",
            "awards_financial_aid", "awards_financial_aid", "奖助说明", [
                unit("t09-u1", "姚星河", "PERSON_NAME", "public_release", "egress_tool_public", "公开发布"),
                unit("t09-u2", "对尘螨过敏", "SENSITIVE_ATTR", "public_release", "egress_tool_public", "公开发布"),
                unit("t09-u3", "622200000000009999", "BANK_CARD", "public_release", "egress_tool_public", "公开发布"),
            ]),
        doc(test, "t10",
            "补交提醒里有陆听白，上次小测71分，学号2023082219。",
            "整理给任课老师看的补交提醒。",
            "coursework_grades", "coursework_grades", "课程沟通", [
                unit("t10-u1", "陆听白", "PERSON_NAME", "authorized_local_delivery", "viewer_teacher", "指导老师"),
                unit("t10-u2", "71分", "GRADE", "authorized_local_delivery", "viewer_teacher", "指导老师"),
                unit("t10-u3", "2023082219", "STUDENT_ID", "authorized_local_delivery", "viewer_teacher", "指导老师"),
            ]),
        doc(test, "t11",
            "报修单写的是枫园9号楼406，联系电话15200005004。",
            "写成可以发到校园论坛的报修进度。",
            "campus_services", "campus_services", "校园报修", [
                unit("t11-u1", "枫园9号楼406", "DORM", "public_release", "egress_tool_public", "公开发布"),
                unit("t11-u2", "15200005004", "PHONE", "public_release", "egress_tool_public", "公开发布"),
            ]),
        doc(test, "t12",
            "外发名单草稿里有秦照川。",
            "把这段名单交给外部模型润色。",
            duty, duty, "班级协作", [
                unit("t12-u1", "秦照川", "PERSON_NAME", "external_generation", "external_model", "外部生成服务",
                     identity="external_partner", identity_name="校外合作方"),
            ]),
    ]


def locate(document: dict) -> None:
    text = document["text"]
    for item in document["units"]:
        quote = item["quote"]
        start = text.find(quote)
        if start < 0 or text.find(quote, start + len(quote)) >= 0:
            raise SystemExit(f"{item['unit_id']} 的引用必须恰好出现一次")
        item["start"] = start
        item["end"] = start + len(quote)
        if not item["user_task"]:
            item["user_task"] = document["user_task"]


def check(documents: list[dict]) -> None:
    blob = json.dumps(documents, ensure_ascii=False)
    for token in BLOCKED:
        if token in blob:
            raise SystemExit(f"盲标材料撞上已用过的片段: {token}")
    ids = []
    for document in documents:
        raw = json.dumps(document, ensure_ascii=False)
        for key in FORBIDDEN_KEYS:
            if key in raw:
                raise SystemExit(f"{document['document_id']} 含有禁止字段 {key}")
        for item in document["units"]:
            ids.append(item["unit_id"])
            if document["text"][item["start"]:item["end"]] != item["quote"]:
                raise SystemExit(item["unit_id"] + " 位置不一致")
            if item["annotation"] != blank():
                raise SystemExit(item["unit_id"] + " 动作已被填写")
    if len(ids) != len(set(ids)):
        raise SystemExit("单元编号重复")
    counts = {"calibration": 0, "test": 0}
    for document in documents:
        counts[document["pool"]] += len(document["units"])
    if counts != {"calibration": 20, "test": 40}:
        raise SystemExit(f"划分数量不对: {counts}")


def main() -> None:
    documents = pack()
    for document in documents:
        locate(document)
    check(documents)
    if OUT.exists():
        for path in OUT.rglob("*.json"):
            path.unlink()
    hashes = {}
    for document in documents:
        folder = OUT / ("校准池" if document["pool"] == "calibration" else "独立测试池")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{document['document_id']}.json"
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hashes[str(target.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(target.read_bytes()).hexdigest()
    template = {
        "unit_id": "",
        "quote": "",
        "category": "",
        "boundary_id": "",
        "recipient_id": "",
        "identity_key": "",
        "user_task": "",
        "annotation": blank(),
        "allowed_actions": ["DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE"],
        "if_uncertain": "动作留空，adjudication 填写待裁定",
    }
    template_path = OUT / "标注模板.json"
    template_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "protocol": "campus-necessity-blind-label-v1",
        "created": "2026-11-01",
        "split_assigned_before_annotation": True,
        "calibration_units": 20,
        "test_units": 40,
        "labels_filled_by_ai": False,
        "model_predictions_included": False,
        "r0_reference_included": False,
        "test_pool_usable_for_tuning": False,
        "file_sha256": hashes,
    }
    manifest_path = OUT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("documents", len(documents), "units", 60)


if __name__ == "__main__":
    main()
