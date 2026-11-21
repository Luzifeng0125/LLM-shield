"""Build natural-document review packs; old templates require an explicit legacy flag."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.research import case_hash, validate_cases, annotation_for

TASK_WORDING = [
    ("只提炼本次讨论的议题，不列任何人员", "整理负责人、工作事项与完成期限的对应清单"),
    ("按主题概括会议内容，忽略人员名单", "保留各负责人与所领工作的关联并整理成纪要"),
    ("我只想知道讨论了什么，不需要知道谁负责", "说明每项安排由谁负责，截止时间是什么"),
    ("输出议题摘要，删除身份线索", "形成可执行分工表，用稳定代号区分执行人"),
    ("归纳会议涉及的主题即可", "按人整理分派任务，保持人员与事项的一一对应"),
    ("只写会议要点，不制作人员分工", "请整理每名负责人的待办事项和交付时间"),
    ("请做不包含人物的议题梳理", "需要任务责任链，人员可用会话内代号替代"),
    ("只要事项分类汇总，无需区分参会者", "提取谁在何时完成什么，人物需要稳定对应"),
    ("按讨论主题生成提纲，参会身份不需要", "把负责人和事项绑定，整理截止期限"),
    ("把会议话题列出来，不保留人员关系", "追踪各项工作的执行者，允许用稳定编号"),
    ("整理讨论方向，不需要任何人的称谓", "以便后续跟进为目的整理责任分配与时限"),
    ("我要主题清单，人员和出席情况都不用", "整理能追踪到同一负责人的工作清单"),
]
SCENES = ["海报设计", "讲座筹备", "设备检修", "展板校对", "资料整理", "会场布置",
          "课程展示", "志愿排班", "阅读分享", "项目演示", "实践总结", "成果汇报"]


def build_legacy_cases(*, context_pairs: bool = True) -> list[dict]:
    cases = []
    for family in range(12):
        split = "train" if family < 8 else "validation" if family < 10 else "test"
        base = {"template_group": f"wording-family-{family:02d}", "split": split,
                "source_kind": "synthetic", "identity": "student_leader", "recipient": "external_model"}

        def add(source, value, category, text, task, instruction, action, representation, facts, reason, variant,
                recipient="external_model", context=None):
            start = text.index(value)
            case = {**base, "case_id": f"f{family:02d}-{source}-{variant}",
                    "source_case_id": f"f{family:02d}-{source}", "task": task, "recipient": recipient,
                    "task_description": instruction,
                    "context": context or f"这是完全虚构的{SCENES[family]}材料。",
                    "text": text, "entities": [{"start": start, "end": start + len(value),
                                                "text": value, "category": category}],
                    "proposal": {"action": action, "allowed_actions": [action],
                                 "minimum_representation": representation, "required_facts": facts,
                                 "reason": reason}, "review": {"status": "machine_draft"}}
            annotation_for(case, allow_drafts=True)
            cases.append(case)

        for person in range(4):
            name = "赵钱孙李周吴郑王冯陈褚卫"[family] + ("知远", "思齐", "若宁", "安和")[person]
            text = f"第{family + 1}场{SCENES[family]}例会：{name}负责第{person + 1}项准备工作，周五前交付。"
            contextual = context_pairs and person >= 2
            if contextual:
                text = f"第{family + 1}场{SCENES[family]}例会记录：{name}参与了本次筹备交流。"
            for variant, (instruction, action, representation, facts) in enumerate([
                (TASK_WORDING[family][0], "DELETE", "none", "讨论议题与公开事项"),
                (TASK_WORDING[family][1], "PSEUDONYMIZE", "pseudonym", "负责人代号—事项—期限对应关系"),
                (f"统计本场{SCENES[family]}活动参与人数，只需要总数", "LOCAL_AGGREGATE", "local_aggregate", "本机计算的参与人数"),
                (f"为{SCENES[family]}写一段主题介绍，不统计人数也不展示个人明细", "DELETE", "none", "活动主题与公开内容"),
            ]):
                context = None
                if contextual and variant < 2:
                    instruction = TASK_WORDING[family][1]
                    context = ("已核实的补充记录：此人只旁听，不承担本次任何工作，责任人另有其人。"
                               if variant == 0 else
                               "已核实的补充记录：此人就是该项工作的负责人，负责场地准备，周五前交付。")
                add(f"person-{person}", name, "PERSON_NAME", text,
                    "meeting_minutes" if variant < 2 else "activity_stats", instruction,
                    action, representation, facts, "任务所需事实与身份原值分开判断；这只是机器建议，待人审。", variant,
                    context=context)
            add(f"person-{person}", name, "PERSON_NAME", text, "meeting_minutes",
                "仅供权限已经核验的指导老师本机核实真实负责人与任务的对应，不调用外部模型",
                "RETAIN", "original", "真实负责人—事项对应关系",
                "该虚构场景明确需要本机身份核实且接收方已获授权，仍待人工确认。", "teacher", "viewer_teacher",
                "已核实：该参与者是该项工作的真实负责人；查看者的权限已经由服务端确认。" if contextual else None)

        org = f"虚构{SCENES[family]}协作社"
        text = f"第{family + 1}份项目材料：{org}提供场地协助，项目目标是公开知识交流。"
        for variant, (instruction, action, representation) in enumerate([
            ("介绍已确认可公开的合作机构，需要保留机构名称", "RETAIN", "original"),
            ("只概括合作机构的类型，不披露具体机构名称", "GENERALIZE", "coarse"),
        ]):
            add("org", org, "ORG", text, "project_intro", instruction, action, representation,
                "已获准公开的合作事实", "机构是否需保留原名取决于具体公开目的。", variant)

        phone = f"1380000{family:02d}00"
        for variant, task in enumerate(("meeting_minutes", "activity_stats")):
            add("phone", phone, "PHONE", f"第{family + 1}份虚构登记材料中的联系电话：{phone}。",
                task, "整理公开事项，不需要联系方式", "DELETE", "none", "公开任务事项",
                "联系方式不应进入外部生成请求。", variant)

        dorm = f"虚构园区{family + 1}栋{family + 101}室"
        for variant, task in enumerate(("meeting_minutes", "project_intro")):
            add("dorm", dorm, "DORM", f"第{family + 1}份内部资料记录住宿位置：{dorm}。",
                task, "只整理可公开的活动内容", "DELETE", "none", "不含住宿位置的公开事实",
                "住宿位置对本次公开任务非必需且接收方禁止。", variant)

        name = f"虚构人员{family + 1}号"
        text = f"第{family + 1}份未确认资料写有{name}的责任安排，记录的来源和职责真实性尚未核实。"
        for variant, instruction in enumerate(("来源与职责冲突尚未解决，请先确认后再整理责任清单",
                                                "请使用目前无法确认归属的材料生成可执行分工")):
            add("uncertain", name, "PERSON_NAME", text, "meeting_minutes", instruction,
                "PAUSE", "uncertain", "经确认的负责人—任务对应关系",
                "事实归属不足以支持可执行分工，应先解决歧义；是否暂停需要人工裁决。", variant)
    validate_cases(cases)
    return cases


def build_cases() -> list[dict]:
    from scripts.natural_action_data import build_natural_cases
    return build_natural_cases()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, help="自然文档 part_*.json 所在目录")
    parser.add_argument("--history", type=Path, action="append", default=[], help="以往批次 documents.jsonl，可重复传入；阻止换编号重复")
    parser.add_argument("--rebuild-frozen", action="store_true", help="显式复现冻结源稿；结果不算新数据")
    parser.add_argument("--legacy-template-pack", action="store_true", help="只复现已退役的336条模板开发材料")
    parser.add_argument("--legacy-no-context", action="store_true", help="仅复现首轮开发实验")
    args = parser.parse_args()
    if args.legacy_no_context and not args.legacy_template_pack:
        parser.error("--legacy-no-context 必须与 --legacy-template-pack 一起使用")
    if not args.legacy_template_pack:
        from scripts.natural_action_data import DEFAULT_SOURCE, write_natural_pack
        try:
            manifest = write_natural_pack(args.out, args.source_dir or DEFAULT_SOURCE, args.history,
                                          rebuild_frozen=args.rebuild_frozen)
        except (ValueError, KeyError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(manifest, ensure_ascii=False))
        return
    if args.source_dir or args.history or args.rebuild_frozen:
        parser.error("自然文档参数不能与旧模板模式混用")
    cases = build_legacy_cases(context_pairs=not args.legacy_no_context)
    if args.out.exists():
        parser.error("输出目录已存在，请使用新的目录")
    args.out.mkdir(parents=True)
    (args.out / "cases.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    task = {"schema": "action-human-review-v1", "cases": [
        {**{k: v for k, v in case.items() if k not in {"proposal", "review", "split"}},
         "case_sha256": case_hash(case)} for case in cases]}
    # The digest binds source + task + split. Reviewers do not see model proposals.
    (args.out / "review-task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    first_family = {**task, "cases": [c for c in task["cases"] if c["template_group"] == "wording-family-00"]}
    (args.out / "review-first-batch.json").write_text(json.dumps(first_family, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {**validate_cases(cases), "supervision": "machine_draft_not_gold",
                "test_scope": "synthetic_template_holdout_not_blind_test"}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the offline reviewer self-contained when the folder is copied elsewhere.
    (args.out / "action_review.html").write_bytes(Path(__file__).with_name("action_review.html").read_bytes())
    (args.out / "打开复核页面.cmd").write_bytes(
        b'@echo off\r\n'
        b'if not exist "%~dp0action_review.html" (\r\n'
        b'  echo Missing action_review.html. Extract the complete review folder first.\r\n'
        b'  pause\r\n'
        b'  exit /b 1\r\n'
        b')\r\n'
        b'start "" "%~dp0action_review.html"\r\n'
    )
    (args.out / "reviews").mkdir()
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
