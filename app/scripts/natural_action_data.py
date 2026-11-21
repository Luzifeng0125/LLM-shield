"""Compile independently authored documents; never multiply a wording template.

The supplied spans isolate action research, not detector or end-to-end quality.
All labels remain machine drafts until the existing human-review import flow.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "data" / "action_natural"
REPRESENTATION = {"DELETE": "none", "LOCAL_AGGREGATE": "local_aggregate",
                  "GENERALIZE": "coarse", "PSEUDONYMIZE": "pseudonym",
                  "RETAIN": "original", "PAUSE": "uncertain"}
ANSWER_CUE = re.compile(r"\b(?:DELETE|RETAIN|PSEUDONYMIZE|LOCAL_AGGREGATE|GENERALIZE|PAUSE)\b|"
                        r"(?:标注答案|本题答案|正确动作|建议动作|本题应当|本题应选)")
PUBLIC_FIELDS = {"case_id", "source_case_id", "template_group", "source_kind",
                 "identity", "recipient", "task", "task_description", "context",
                 "text", "entities", "document_id", "document_type"}


def load_documents(source_dir: Path = DEFAULT_SOURCE) -> list[dict]:
    paths = sorted(source_dir.glob("part_*.json"))
    if not paths:
        raise ValueError("缺少独立编写的 part_*.json 文档；不能用模板循环补足数量")
    documents = []
    for path in paths:
        part = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(part, list):
            raise ValueError(f"{path.name} 必须是文档数组")
        documents.extend(part)
    return documents


def normalized_document(document: dict) -> str:
    """Mask supplied entities, numbering and punctuation before similarity checks."""
    text = document["text"]
    entities = {e["text"]: e["category"] for d in document["decisions"] for e in d["entities"]}
    for value in sorted(entities, key=len, reverse=True):
        text = text.replace(value, f"实体{entities[value]}")
    text = re.sub(r"第[一二三四五六七八九十百零〇两\d]+[场份轮次项期号届]", "序号", text)
    text = re.sub(r"\d+", "数字", text)
    return re.sub(r"[\W_]+", "", text).lower()


def _grams(text: str) -> set[str]:
    return {text[i:i + 3] for i in range(max(1, len(text) - 2))}


def _similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def _valid_pair(a: dict, b: dict) -> bool:
    return bool(a.get("context_pair_id") and a.get("context_pair_id") == b.get("context_pair_id")
                and a["scenario_group"] == b["scenario_group"] and a["split"] == b["split"]
                and a["text"] == b["text"] and a["task_description"] == b["task_description"]
                and all(a[k] == b[k] for k in ("task", "recipient", "identity"))
                and [(d["segment"], d["entities"]) for d in a["decisions"]]
                == [(d["segment"], d["entities"]) for d in b["decisions"]]
                and a["context"] != b["context"])


def audit_documents(documents: list[dict], history: list[dict] | None = None) -> dict:
    """Engineering rejection gates, not a claim of human realism or model accuracy."""
    errors, similar, pairs = [], [], []
    ids, group_splits, pair_groups = set(), {}, defaultdict(list)
    lengths, request_lengths, instruction_leaks, answer_leaks = [], [], [], []
    actions, types, splits, phenomena = Counter(), Counter(), Counter(), Counter()
    mixed = 0
    for doc in documents:
        did = doc["document_id"]
        if did in ids:
            errors.append(f"重复文档编号: {did}")
        ids.add(did)
        group, split = doc["scenario_group"], doc["split"]
        if not group or split not in {"train", "validation", "test"}:
            errors.append(f"场景族或拆分无效: {did}")
        if group in group_splits and group_splits[group] != split:
            errors.append(f"语义场景族跨拆分: {group}")
        group_splits[group] = split
        if doc.get("context_pair_id"):
            pair_groups[doc["context_pair_id"]].append(doc)
        types[doc["document_type"]] += 1
        splits[split] += 1
        phenomena.update(doc.get("phenomena", []))
        lengths.append(len(doc["text"]))
        request_lengths.append(len(doc["task_description"]))
        if len(doc["text"]) < 180:
            errors.append(f"材料过短，缺少整篇上下文: {did}")
        if not doc["context"].strip() or not doc["task_description"].strip():
            errors.append(f"任务或上下文为空: {did}")
        for field in ("task_description", "context", "text"):
            if ANSWER_CUE.search(doc[field]):
                answer_leaks.append({"document_id": did, "field": field})
                errors.append(f"模型输入含标注答案提示: {did}/{field}")
        if re.search(r"DELETE|RETAIN|PSEUDONYMIZE|LOCAL_AGGREGATE|GENERALIZE|PAUSE|"
                     r"(删除|保留|去掉|隐藏|脱敏|代号化|泛化).{0,10}(姓名|手机号|联系方式|机构名)",
                     doc["task_description"]):
            instruction_leaks.append(did)
        doc_actions = {d["action"] for d in doc["decisions"]}
        mixed += len(doc_actions) >= 2
        if len(doc["decisions"]) < 3 or len(doc_actions) < 2:
            errors.append(f"需要同篇多处判断、至少两种处置: {did}")
        segments = set()
        for decision in doc["decisions"]:
            segment = decision["segment"]
            if segment not in doc["text"] or segment in segments:
                errors.append(f"决策片段不在原文或重复: {did}")
            segments.add(segment)
            action = decision["action"]
            actions[action] += 1
            if REPRESENTATION.get(action) != decision["minimum_representation"]:
                errors.append(f"动作与表达形式矛盾: {did}")
            if not decision.get("required_facts", "").strip() or not decision.get("reason", "").strip():
                errors.append(f"缺少待复核事实/理由: {did}")
            evidence = decision.get("evidence", [])
            if not evidence or any(not e or (e not in doc["text"] and e not in doc["context"])
                                   for e in evidence):
                errors.append(f"依据必须引用原文或既有上下文: {did}")
            if action == "PAUSE" and not decision.get("clarification_question", "").strip():
                errors.append(f"暂停必须说明具体要追问什么: {did}")
            if not decision["entities"] or any(not e["text"] or e["text"] not in segment
                                                for e in decision["entities"]):
                errors.append(f"实体未落在完整决策片段: {did}")
    for key, docs in pair_groups.items():
        if len(docs) != 2 or not _valid_pair(*docs):
            errors.append(f"上下文对照必须恰为同文同任务同拆分的两份: {key}")
        elif [d["action"] for d in docs[0]["decisions"]] == [d["action"] for d in docs[1]["decisions"]]:
            errors.append(f"上下文对照没有改变任何判断: {key}")
    normalized = [normalized_document(d) for d in documents]
    grams = [_grams(t) for t in normalized]
    for i, a in enumerate(documents):
        for j in range(i):
            b = documents[j]
            score = _similarity(grams[i], grams[j])
            if score < .65:
                continue
            row = {"a": a["document_id"], "b": b["document_id"], "similarity": round(score, 4)}
            if _valid_pair(a, b):
                pairs.append(row)
            else:
                similar.append(row)
                errors.append(f"疑似换实体/换编号重复材料: {row['a']} / {row['b']}")
    historical_overlap = []
    for old in history or []:
        old_grams = _grams(normalized_document(old))
        for doc, fingerprint in zip(documents, grams):
            score = _similarity(fingerprint, old_grams)
            if score >= .65:
                historical_overlap.append({"new": doc["document_id"], "previous": old["document_id"],
                                           "similarity": round(score, 4)})
    if historical_overlap:
        errors.append("与历史批次材料近重复；应写新情境，不能靠新目录声称新数据")
    if len(documents) < 24:
        errors.append("自然材料批次至少需24篇独立/受控对照文档")
    if len(types) < 8:
        errors.append("文体种类不足8种")
    if set(splits) != {"train", "validation", "test"}:
        errors.append("需要训练、验证、测试三个场景族拆分")
    if set(actions) != set(REPRESENTATION):
        errors.append("六类动作覆盖不完整")
    if instruction_leaks and len(instruction_leaks) / max(1, len(documents)) > .2:
        errors.append("过多任务指令直接指定字段处置，模型无须阅读材料")
    ratios = sorted(r / max(1, n) for r, n in zip(request_lengths, lengths))
    if ratios and ratios[len(ratios) // 2] > .2:
        errors.append("任务相对材料过长，需将真实情境放入正文")
    ordered = sorted(lengths)
    return {"passed": not errors, "errors": errors, "documents": len(documents),
            "decisions": sum(actions.values()), "scenario_groups": len(group_splits),
            "document_splits": dict(splits), "document_types": dict(types), "actions": dict(actions),
            "phenomena": dict(phenomena), "mixed_action_documents": mixed,
            "text_characters": {"min": min(lengths, default=0), "median": ordered[len(ordered)//2] if ordered else 0,
                                "max": max(lengths, default=0)},
            "request_characters": {"min": min(request_lengths, default=0), "max": max(request_lengths, default=0)},
            "median_request_document_ratio": round(ratios[len(ratios)//2], 4) if ratios else 0,
            "explicit_field_action_requests": instruction_leaks,
            "answer_cues_in_model_input": answer_leaks,
            "near_duplicate_threshold": .65, "similarity_method": "entity_and_number_masked_character_3gram_jaccard",
            "unapproved_near_duplicates": similar, "controlled_context_pairs": pairs,
            "historical_overlap": historical_overlap,
            "scope": "heuristic_data_quality_checks_not_model_accuracy_or_human_validation"}


def build_natural_cases(documents: list[dict] | None = None, *, history: list[dict] | None = None) -> list[dict]:
    from llm_shield.m4_necessity.research import annotation_for, validate_cases
    documents = load_documents() if documents is None else documents
    audit = audit_documents(documents, history)
    if not audit["passed"]:
        raise ValueError("\n".join(audit["errors"]))
    cases = []
    for doc in documents:
        for index, decision in enumerate(doc["decisions"], 1):
            text = decision["segment"]
            spans = {}
            for entity in decision["entities"]:
                for match in re.finditer(re.escape(entity["text"]), text):
                    start, end = match.span()
                    key = (start, end)
                    if key in spans and spans[key]["category"] != entity["category"]:
                        raise ValueError(f"实体类别冲突: {doc['document_id']}")
                    spans[key] = {"start": start, "end": end, **entity}
            entities = [spans[key] for key in sorted(spans)]
            if any(a["end"] > b["start"] for a, b in zip(entities, entities[1:])):
                raise ValueError(f"实体范围重叠: {doc['document_id']}")
            case = {"case_id": f"{doc['document_id']}-s{index:02d}",
                    "source_case_id": doc["document_id"], "document_id": doc["document_id"],
                    "template_group": doc["scenario_group"], "split": doc["split"],
                    "document_type": doc["document_type"], "source_kind": "synthetic",
                    "identity": doc["identity"], "recipient": doc["recipient"], "task": doc["task"],
                    "task_description": doc["task_description"],
                    "context": doc["context"] + "\n\n【完整原始材料】\n" + doc["text"],
                    "text": text, "entities": entities,
                    "proposal": {k: decision[k] for k in ("action", "minimum_representation", "required_facts", "reason", "evidence")},
                    "review": {"status": "machine_draft"}}
            case["proposal"]["allowed_actions"] = [decision["action"]]
            if decision.get("clarification_question"):
                case["proposal"]["clarification_question"] = decision["clarification_question"]
            annotation_for(case, allow_drafts=True)
            cases.append(case)
    validate_cases(cases)
    return cases


def review_task(cases: list[dict]) -> dict:
    from llm_shield.m4_necessity.research import case_hash
    return {"schema": "action-human-review-v1", "cases": [
        {**{k: v for k, v in case.items() if k in PUBLIC_FIELDS}, "case_sha256": case_hash(case)}
        for case in cases]}


def first_document_batch(documents: list[dict], cases: list[dict], count: int = 6) -> list[dict]:
    """Whole training documents, chosen for different genres and decisions, never 28-template cycles."""
    remaining = [d for d in documents if d["split"] == "train"]
    chosen, seen_actions, seen_types, seen_groups = [], set(), set(), set()
    while remaining and len(chosen) < count:
        best = max(remaining, key=lambda d: (
            len({s["action"] for s in d["decisions"]} - seen_actions),
            d["document_type"] not in seen_types, d["scenario_group"] not in seen_groups))
        remaining.remove(best)
        if best["scenario_group"] in seen_groups:
            continue
        chosen.append(best["document_id"])
        seen_actions.update(s["action"] for s in best["decisions"])
        seen_types.add(best["document_type"])
        seen_groups.add(best["scenario_group"])
    return [c for c in cases if c["document_id"] in chosen]


def write_natural_pack(out: Path, source_dir: Path = DEFAULT_SOURCE, history_paths: list[Path] | None = None,
                       *, rebuild_frozen: bool = False) -> dict:
    from llm_shield.m4_necessity.research import validate_cases
    if out.exists():
        raise ValueError("输出目录已存在，请使用新的目录，不覆盖冻结材料")
    documents = load_documents(source_dir)
    # New rounds automatically compare sibling packs; manual --history adds other locations.
    # Rebuilding a frozen source is explicit and recorded, never counted as fresh data.
    automatic = [] if rebuild_frozen else sorted(out.parent.glob("*/documents.jsonl"))
    history_paths = sorted({p.resolve() for p in [*automatic, *(history_paths or [])]})
    history = [json.loads(line) for p in history_paths or []
               for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    cases = build_natural_cases(documents, history=history)
    audit = audit_documents(documents, history)
    first = first_document_batch(documents, cases)
    manifest = {**validate_cases(cases), "schema": "natural-action-documents-v1",
                "documents": len(documents), "first_batch_documents": len({c['document_id'] for c in first}),
                "first_batch_decisions": len(first), "supervision": "machine_draft_not_gold",
                "generation": "independently_authored_documents_no_template_expansion",
                "build_mode": "frozen_reproduction_not_new_data" if rebuild_frozen else "new_batch_with_history_check",
                "decision_unit": "annotated_segment_with_full_document_context",
                "test_scope": "synthetic_scenario_holdout_not_independent_blind_test",
                "source_files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_dir.glob('part_*.json'))},
                "history_checked": [str(p) for p in history_paths or []]}
    out.mkdir(parents=True)
    for filename, rows in (("cases.jsonl", cases), ("documents.jsonl", documents)):
        (out / filename).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    for filename, value in (("manifest.json", manifest), ("quality_report.json", audit),
                            ("review-task.json", review_task(cases)), ("review-first-batch.json", review_task(first))):
        (out / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "action_review.html").write_bytes(Path(__file__).with_name("action_review.html").read_bytes())
    (out / "打开复核页面.cmd").write_bytes(b'@echo off\r\nstart "" "%~dp0action_review.html"\r\n')
    (out / "reviews").mkdir()
    (out / "开始这里.md").write_text(
        f"# 自然文档复核包\n\n{len(documents)} 份完整虚构材料，{len(cases)} 个片段判断。"
        f"首批是 {manifest['first_batch_documents']} 份完整材料的 {len(first)} 处判断，不是循环28题。\n\n"
        "打开 action_review.html，载入 review-first-batch.json 或完整 review-task.json。"
        "先读任务、来往背景与整篇材料，再判断当前片段；同篇不同片段可以需要不同动作。\n\n"
        "当前执行器的 DELETE 删除片段内标注实体、保留其余文字；LOCAL_AGGREGATE 删除实体明细、保留其余文字并追加汇总。"
        "PSEUDONYMIZE 对支持的实体使用稳定代号，其余标注实体删除。"
        "若某动作无法同时满足片段内各信息的需要，请写明能力缺口，不把它当作正确标注。"
        "短指令不等于必须暂停；只有关键事实缺失且会改变结果时才提出具体追问。\n\n"
        "这是 AI 编写和提议标签的待复核数据。人工题目不含机器建议；documents.jsonl、cases.jsonl"
        "以及 quality_report.json 供开发者检查，不应在独立标注前提供建议答案。"
        "复核结果仍须区分独立人工、看过建议后的确认、AI草稿。\n\n"
        "训练/验证/测试按语义场景族冻结；同文上下文对照同组。当前仍是合成留出集，"
        "质量检查通过不等于模型效果提升。尚未训练或替换活动模型。\n\n"
        "后续新批次先独立写新文档，再运行生成器并用 --history 指向本包 documents.jsonl；"
        "直接重新打包相同源文件只算复现本版，不能报告为新增数据。\n", encoding="utf-8")
    return manifest
