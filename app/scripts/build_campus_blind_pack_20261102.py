"""写出 2026-11-02 空白盲标。不调用模型，不填写动作，不按模型对错筛题。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261102"
PRIOR = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261101"
FORBIDDEN_KEYS = {
    "r0_action", "r0_reason", "model_action", "model_argmax", "probabilities",
    "policy_action", "suggested_action", "gold_action", "expected_action", "executable",
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


def locate(text: str, quote: str) -> tuple[int, int]:
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise SystemExit(f"引文无法唯一落位: {quote}")
    return start, start + len(quote)


def unit(uid, text, quote, category, boundary, recipient, recipient_name, user_task, *,
         identity="student_leader", identity_name="学生组织负责人"):
    start, end = locate(text, quote)
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
        "start": start,
        "end": end,
    }


def doc(did, text, user_task, workflow_id, task_key, workflow_name, units):
    return {
        "pool": "blind",
        "document_id": did,
        "text": text,
        "user_task": user_task,
        "workflow_id": workflow_id,
        "task_key": task_key,
        "workflow_name": workflow_name,
        "units": units,
        "label_status": "unlabeled",
        "model_screened": False,
    }


def prior_quotes() -> set[str]:
    found = set()
    for path in PRIOR.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            units = document.get("units")
            if isinstance(units, list):
                for unit_row in units:
                    if isinstance(unit_row, dict) and unit_row.get("quote"):
                        found.add(unit_row["quote"])
    return found


def pack() -> list[dict]:
    ext = ("external_generation", "external_model", "外部生成服务")
    teacher = ("authorized_local_delivery", "viewer_teacher", "指导老师")
    peer = ("authorized_local_delivery", "viewer_peer", "同班同学")
    public = ("public_release", "egress_tool_public", "公开发布")
    duty = "class_coordination"
    notice = ("student_events", "activity_notice", "活动公告")
    minutes = ("minutes_reports_statistics", "meeting_minutes", "会议纪要")
    awards = ("awards_financial_aid", "awards_financial_aid", "奖助说明")
    grades = ("coursework_grades", "coursework_grades", "课程沟通")
    repair = ("campus_services", "campus_services", "校园报修")

    n01 = "周五值日梁疏影负责开门，宋知微负责锁窗。教室在公教楼B201。联系电话13700008008。"
    ask01 = "整理成班群通知，写明谁开门、谁锁窗。"
    n02 = "开门由梁疏影负责。"
    ask02 = "整理成给辅导员本机查看的值日表，开门的人写明白。"
    n03 = "周六观星在西门广场见面。召集人是许晚白。住在桐园3号楼210。"
    ask03 = "写一条观星活动公告，见面的地方写清楚。"
    n04 = "例会上郑清越认领海报，曹明川认领签到。印刷费是6400元。有人正在服用降压药。"
    ask04 = "整理纪要，人员和事项要能对上，印刷费交代到千元这一档即可。"
    n05 = "例会上郑清越认领海报，曹明川认领签到。订餐费是6400元。"
    ask05 = "整理给指导老师核对的纪要，订餐费按结算单上的金额保留。"
    n06 = "采购例会上沈疏叶认领会场，罗清和认领物资。采购费是6400元。"
    ask06 = "交给外部模型起草纪要，采购费按结算单上的金额保留。"
    n07 = "纪要里韩听白负责茶歇。茶歇费是6400元。"
    ask07 = "写成同班同学本机可看的纪要，茶歇费按结算单上的金额保留。"
    n08 = "例会上郑清越做了记录。资料费是6400元。"
    ask08 = "把例会记录整理得顺一些。"
    n09 = "本学期助学项目受助人是韩听澜。家庭正在治疗慢性病。卡号6222020000000000888。"
    ask09 = "写一段可以放在学院主页的项目介绍。"
    n10 = "陆行舟需要补交实验报告，上次测验83分，学号2024008891。"
    ask10 = "写成给任课老师看的补交通知。"
    n11 = "报修地点在榕园6号楼118。联系电话13700008009。"
    ask11 = "写成可以发在校园论坛的维修进度。"
    n12 = "名单上有周疏明。"
    ask12 = "请外部模型把名单改得通顺一些。"
    return [
        doc("n01", n01, ask01, duty, duty, "班级协作", [
            unit("n01-u1", n01, "梁疏影", "PERSON_NAME", *ext, ask01),
            unit("n01-u2", n01, "宋知微", "PERSON_NAME", *ext, ask01),
            unit("n01-u3", n01, "公教楼B201", "LOCATION", *ext, ask01),
            unit("n01-u4", n01, "13700008008", "PHONE", *ext, ask01),
        ]),
        doc("n02", n02, ask02, duty, duty, "班级协作", [
            unit("n02-u1", n02, "梁疏影", "PERSON_NAME", *teacher, ask02),
        ]),
        doc("n03", n03, ask03, *notice, [
            unit("n03-u1", n03, "许晚白", "PERSON_NAME", *ext, ask03),
            unit("n03-u2", n03, "西门广场", "LOCATION", *ext, ask03),
            unit("n03-u3", n03, "桐园3号楼210", "DORM", *ext, ask03),
        ]),
        doc("n04", n04, ask04, *minutes, [
            unit("n04-u1", n04, "郑清越", "PERSON_NAME", *ext, ask04),
            unit("n04-u2", n04, "曹明川", "PERSON_NAME", *ext, ask04),
            unit("n04-u3", n04, "6400元", "BUDGET", *ext, ask04),
            unit("n04-u4", n04, "正在服用降压药", "SENSITIVE_ATTR", *ext, ask04),
        ]),
        doc("n05", n05, ask05, *minutes, [
            unit("n05-u1", n05, "郑清越", "PERSON_NAME", *teacher, ask05),
            unit("n05-u2", n05, "曹明川", "PERSON_NAME", *teacher, ask05),
            unit("n05-u3", n05, "6400元", "BUDGET", *teacher, ask05),
        ]),
        doc("n06", n06, ask06, *minutes, [
            unit("n06-u1", n06, "沈疏叶", "PERSON_NAME", *ext, ask06),
            unit("n06-u2", n06, "罗清和", "PERSON_NAME", *ext, ask06),
            unit("n06-u3", n06, "6400元", "BUDGET", *ext, ask06),
        ]),
        doc("n07", n07, ask07, *minutes, [
            unit("n07-u1", n07, "韩听白", "PERSON_NAME", *peer, ask07),
            unit("n07-u2", n07, "6400元", "BUDGET", *peer, ask07),
        ]),
        doc("n08", n08, ask08, *minutes, [
            unit("n08-u1", n08, "郑清越", "PERSON_NAME", *ext, ask08),
            unit("n08-u2", n08, "6400元", "BUDGET", *ext, ask08),
        ]),
        doc("n09", n09, ask09, *awards, [
            unit("n09-u1", n09, "韩听澜", "PERSON_NAME", *public, ask09),
            unit("n09-u2", n09, "正在治疗慢性病", "SENSITIVE_ATTR", *public, ask09),
            unit("n09-u3", n09, "6222020000000000888", "BANK_CARD", *public, ask09),
        ]),
        doc("n10", n10, ask10, *grades, [
            unit("n10-u1", n10, "陆行舟", "PERSON_NAME", *teacher, ask10),
            unit("n10-u2", n10, "83分", "GRADE", *teacher, ask10),
            unit("n10-u3", n10, "2024008891", "STUDENT_ID", *teacher, ask10),
        ]),
        doc("n11", n11, ask11, *repair, [
            unit("n11-u1", n11, "榕园6号楼118", "DORM", *public, ask11),
            unit("n11-u2", n11, "13700008009", "PHONE", *public, ask11),
        ]),
        doc("n12", n12, ask12, duty, duty, "班级协作", [
            unit("n12-u1", n12, "周疏明", "PERSON_NAME", *ext, ask12,
                 identity="external_partner", identity_name="校外合作方"),
        ]),
    ]


def main() -> None:
    documents = pack()
    known = prior_quotes()
    quotes = [unit["quote"] for document in documents for unit in document["units"]]
    overlap = sorted(set(quotes) & known)
    if overlap:
        raise SystemExit("新盲标撞上已有引文: " + "、".join(overlap))
    ids = [unit["unit_id"] for document in documents for unit in document["units"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("单元编号重复")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for document in documents:
        blob = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        if any(key in json.loads(blob.decode("utf-8")) for key in FORBIDDEN_KEYS):
            raise SystemExit("文档顶层出现模型字段")
        for unit in document["units"]:
            if set(unit) & FORBIDDEN_KEYS:
                raise SystemExit(f"{unit['unit_id']} 出现模型字段")
            if any(unit["annotation"].values()):
                raise SystemExit(f"{unit['unit_id']} 动作不是空白")
        path = OUT / f"{document['document_id']}.json"
        path.write_bytes(blob)
        manifest.append({"file": path.name, "sha256": hashlib.sha256(blob).hexdigest(), "units": len(document["units"])})
    (OUT / "manifest.json").write_text(json.dumps({
        "created": "2026-11-02",
        "purpose": "未经模型筛选的空白盲标，供以后人工标注后做最终验证",
        "model_screened": False,
        "actions_filled": False,
        "not_for_training_until_returned": True,
        "files": manifest,
        "unit_count": len(ids),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(manifest), "units": len(ids)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
