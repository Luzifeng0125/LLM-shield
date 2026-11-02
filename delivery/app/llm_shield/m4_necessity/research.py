"""Offline action research: frozen source/template splits and explicit supervision.

No detector, API client or active-model writer is used here. Entity annotations
are supplied with the cases, so these experiments isolate the action classifier.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from .. import config as C
from ..m3_decide.constraints import action_applicable, check_hard
from ..m3_decide.decision import decide_segment
from ..schema import Action, Segment, Span
from .model import NecessityModel, build_feature_text

REPRESENTATIONS = {"none", "local_aggregate", "pseudonym", "coarse", "original", "uncertain"}
ACTION_REPRESENTATION = {"DELETE":"none", "LOCAL_AGGREGATE":"local_aggregate",
                         "GENERALIZE":"coarse", "PSEUDONYMIZE":"pseudonym",
                         "RETAIN":"original", "PAUSE":"uncertain"}
REVIEWED_STATUSES = {"human_reviewed", "human_assisted_second_reviewed"}


def annotation_hash(annotation: dict) -> str:
    return hashlib.sha256(json.dumps(annotation,ensure_ascii=False,sort_keys=True,
                                     separators=(',', ':')).encode('utf8')).hexdigest()


def validate_review_provenance(case: dict) -> None:
    """Keep independent A/B and one-person AI-assisted confirmation distinct."""
    review = case.get('review', {})
    status = review.get('status')
    reviewers = review.get('reviewers', [])
    if status == 'human_reviewed':
        if (len(reviewers) != 2 or any(not isinstance(r,str) or not r.strip() for r in reviewers)
                or reviewers[0].strip() == reviewers[1].strip()
                or review.get('case_sha256') != case_hash(case)):
            raise ValueError('人工来源证据不完整，请使用A/B复核导入工具')
    elif status == 'human_assisted_second_reviewed':
        if (len(reviewers) != 1 or not isinstance(reviewers[0],str) or not reviewers[0].strip()
                or review.get('case_sha256') != case_hash(case)
                or review.get('human_confirmed') is not True
                or review.get('independent_blind_review') is not False
                or review.get('machine_suggestions_consulted_before_decisions') is not True
                or review.get('annotation_sha256') != annotation_hash(case.get('annotation', {}))):
            raise ValueError('人工辅助二审来源或标注哈希不完整')
        path = Path(review.get('review_export_path', ''))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != review.get('review_export_sha256'):
            raise ValueError('人工二审原始导出缺失或文件哈希不匹配')
    else:
        raise ValueError('缺少已确认的人工复核来源')


def case_hash(case: dict) -> str:
    public = {k: v for k, v in case.items() if k not in {"proposal", "annotation", "review"}}
    return hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def segment_for(case: dict) -> Segment:
    text = case["text"]
    spans = []
    for raw in case["entities"]:
        start, end = raw["start"], raw["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or text[start:end] != raw["text"] or raw["category"] not in C.rules()["categories"]):
            raise ValueError("实体边界或类别无效")
        spans.append(Span(start, end, raw["text"], raw["category"], detector="provided_annotation"))
    if not spans:
        raise ValueError("动作研究案例必须提供实体标注")
    return Segment(case["case_id"], text, 0, len(text), spans, context=case["context"])


def validate_cases(cases: list[dict]) -> dict:
    ids, groups, sources, hashes = set(), {}, {}, {}
    splits = Counter()
    for case in cases:
        case_id = case["case_id"]
        if case_id in ids or not case_id:
            raise ValueError("案例编号重复或为空")
        ids.add(case_id)
        split = case["split"]
        if split not in {"train", "validation", "test"}:
            raise ValueError("未知拆分")
        splits[split] += 1
        for values, key in ((groups, "template_group"), (sources, "source_case_id")):
            group = case[key]
            if not group or (group in values and values[group] != split):
                raise ValueError("同源或同模板案例跨拆分")
            values[group] = split
        if case["source_kind"] != "synthetic":
            raise ValueError("本执行包只接收明确标记的虚构材料；真实材料须先建立授权来源流程")
        segment_for(case)
        for key, options in (("task", C.tasks()), ("recipient", C.recipients()), ("identity", C.identities())):
            if not isinstance(options.get(case[key]), dict):
                raise ValueError("案例包含未知任务、接收方或身份")
        # Exact duplicates may occur as task variants, never across partitions.
        fingerprint = hashlib.sha256(case["text"].encode()).hexdigest()
        if fingerprint in hashes and hashes[fingerprint] != split:
            raise ValueError("重复源文本跨拆分")
        hashes[fingerprint] = split
    if set(splits) != {"train", "validation", "test"}:
        raise ValueError("必须同时提供训练、验证与测试拆分")
    return {"cases": len(cases), "sources": len(sources), "template_groups": len(groups),
            "splits": dict(splits), "cross_split_source_overlap": 0,
            "cross_split_template_overlap": 0}


def annotation_for(case: dict, *, allow_drafts: bool) -> dict:
    reviewed = case.get("review", {}).get("status") in REVIEWED_STATUSES
    if not reviewed and not allow_drafts:
        raise ValueError("缺少人工复核；开发试验须显式传入 --allow-drafts，不能当作金标")
    annotation = case.get("annotation") if reviewed else case.get("proposal")
    if not isinstance(annotation, dict):
        raise ValueError("缺少标注")
    canonical = annotation.get("action")
    allowed = annotation.get("allowed_actions")
    if (canonical not in Action._value2member_map_ or not isinstance(allowed, list)
            or not allowed or canonical not in allowed
            or any(value not in Action._value2member_map_ for value in allowed)
            or annotation.get("minimum_representation") not in REPRESENTATIONS
            or not isinstance(annotation.get("required_facts"), str) or not annotation["required_facts"].strip()
            or not isinstance(annotation.get("reason"), str) or not annotation["reason"].strip()):
        raise ValueError("必要性、动作或理由标注不完整")
    if annotation["minimum_representation"] != ACTION_REPRESENTATION[canonical]:
        raise ValueError("首选动作与最小表达形式矛盾，请重新确认标注")
    seg = segment_for(case)
    for value in allowed:
        action = Action(value)
        if action != Action.PAUSE and (not action_applicable(action, seg, case["task"])
                or not all(h.passed for h in check_hard(action, seg, case["task"],
                                                      case["recipient"], case["identity"]))):
            raise ValueError("标注动作违反当前硬约束，请裁决需求或策略冲突")
    return annotation


def training_sample(case: dict, *, allow_drafts: bool) -> dict:
    annotation = annotation_for(case, allow_drafts=allow_drafts)
    if case.get('review',{}).get('status') in REVIEWED_STATUSES:
        validate_review_provenance(case)
    return {"feature": build_feature_text(segment_for(case), case["task"], case["recipient"],
                                          task_description=case["task_description"],
                                          context=case["context"], identity_key=case["identity"]),
            "label": annotation["action"], "source_case_id": case["source_case_id"],
            "split_group_id": case["template_group"],
            "source": case.get("review", {}).get("status") if case.get("review", {}).get("status") in REVIEWED_STATUSES
                      else "machine_draft_not_gold"}


def evaluate(model: NecessityModel, cases: list[dict], *, allow_drafts: bool,
             ablation: str = "full", thresholds: dict | None = None) -> dict:
    from sklearn.metrics import f1_score
    correct, accepted, accepted_errors, hard_blocks = 0, 0, 0, 0
    truth, predictions, durations, rows = [], [], [], []
    for case in cases:
        annotation = annotation_for(case, allow_drafts=allow_drafts)
        seg = segment_for(case)
        description = "" if ablation == "no_task_text" else case["task_description"]
        if ablation == "no_context":
            seg.context = ""
        context = "" if ablation == "no_context" else case["context"]
        started = time.perf_counter()
        scores = model.score(seg, case["task"], case["recipient"], task_description=description,
                             context=context, identity_key=case["identity"])
        decision = decide_segment(seg, case["task"], case["recipient"], case["identity"],
                                  lambda *a, **k: scores, confidence_policy=thresholds)
        durations.append((time.perf_counter() - started) * 1000)
        predicted = decision.action.value
        good = predicted in annotation["allowed_actions"]
        correct += good
        if predicted != "PAUSE":
            accepted += 1
            accepted_errors += not good
        if any(not check.passed for check in decision.hard_checks):
            hard_blocks += 1
        truth.append(annotation["action"])
        predictions.append(predicted)
        probabilities = sorted(scores.values(), reverse=True)
        rows.append({"case_id": case["case_id"], "predicted": predicted,
                     "expected": annotation["action"], "acceptable": good,
                     "scores": scores, "probability": probabilities[0],
                     "margin": probabilities[0] - (probabilities[1] if len(probabilities) > 1 else 0)})
    n = len(cases)
    ordered = sorted(durations)
    return {"n": n, "acceptable_action_rate": correct / n if n else 0,
            "macro_f1": float(f1_score(truth, predictions, average="macro", zero_division=0)) if n else 0,
            "completion_coverage": accepted / n if n else 0,
            "accepted_action_error_rate": accepted_errors / accepted if accepted else None,
            "hard_constraint_blocks": hard_blocks,
            "local_p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * .95))] if ordered else None,
            "rows": rows}


def calibrate(validation: dict, *, max_error: float = .05, min_coverage: float = .25) -> dict | None:
    """Fit abstention on validation only. Action error is NOT a privacy guarantee."""
    rows = validation["rows"]
    candidates = []
    for probability in (0, .35, .5, .6, .7, .8, .9, .95):
        for margin in (0, .05, .1, .2, .3, .4):
            selected = [r for r in rows if r["predicted"] != "PAUSE"
                        and r["probability"] >= probability and r["margin"] >= margin]
            if not selected:
                continue
            coverage = len(selected) / len(rows)
            error = sum(not r["acceptable"] for r in selected) / len(selected)
            if coverage >= min_coverage and error <= max_error:
                candidates.append((coverage, -error, -probability, -margin))
    if not candidates:
        return None
    coverage, negative_error, negative_probability, negative_margin = max(candidates)
    return {"min_probability": -negative_probability, "min_margin": -negative_margin,
            "validation_coverage": coverage, "validation_action_error_rate": -negative_error,
            "scope": "action_label_agreement_on_validation_not_privacy_guarantee"}


class ComparisonPolicy:
    """Offline reference policies only; never imported by online decision code."""
    def __init__(self, name: str):
        self.name = name

    def score(self, seg, task, recipient, **kwargs):
        if self.name == "rule_teacher":
            from .train import synthetic_label
            action = synthetic_label(seg, task, recipient, kwargs.get("identity_key", "student_leader"))
        else:
            categories = {span.category for span in seg.spans}
            action = (Action.PSEUDONYMIZE if "PERSON_NAME" in categories else
                      Action.RETAIN if categories <= {"ORG", "LOCATION"} else Action.DELETE)
        return {action.value: 1.0}


def run_experiment(cases: list[dict], output: Path, *, allow_drafts: bool = False) -> dict:
    import joblib
    manifest = validate_cases(cases)
    for case in cases:
        annotation_for(case, allow_drafts=allow_drafts)
        if case.get("review", {}).get("status") in REVIEWED_STATUSES:
            validate_review_provenance(case)
    if output.exists():
        raise ValueError("输出目录已存在；请使用新的实验目录，不覆盖既有证据")
    output.mkdir(parents=True)
    partitions = {s: [c for c in cases if c["split"] == s] for s in ("train", "validation", "test")}
    train = [training_sample(c, allow_drafts=allow_drafts) for c in partitions["train"]]
    valid = [training_sample(c, allow_drafts=allow_drafts) for c in partitions["validation"]]
    candidates = []
    statuses = {c.get('review', {}).get('status') for c in cases}
    supervision = ('human_reviewed' if statuses == {'human_reviewed'} else
                   'human_assisted_second_reviewed_not_independent_ab' if statuses == {'human_assisted_second_reviewed'} else
                   'mixed_human_review_methods' if statuses <= REVIEWED_STATUSES else 'machine_draft_not_gold')
    digest = hashlib.sha256("\n".join(case_hash(c) for c in cases).encode()).hexdigest()
    for weight in (.35, 1.0, 2.0):
        path = output / f"candidate_content_{weight:g}.joblib"
        model = NecessityModel(path)
        trained = model.train(train, validation_samples=valid, content_weight=weight,
                              training_metadata={"supervision": supervision, "cases_sha256": digest,
                                                 "entity_input": "provided_annotation"})
        if not trained["ok"]:
            raise ValueError(trained["reason"])
        score = evaluate(model, partitions["validation"], allow_drafts=allow_drafts)
        candidates.append((score["acceptable_action_rate"], score["macro_f1"], -weight, model, score))
    _, _, _, selected, validation = max(candidates, key=lambda item: item[:3])
    thresholds = calibrate(validation)
    if thresholds is not None:
        artifact = joblib.load(selected.model_path)
        artifact["decision_thresholds"] = thresholds
        joblib.dump(artifact, selected.model_path)
    baseline = NecessityModel(C.ROOT / "models" / "necessity_action.joblib")
    if not baseline.available:
        raise ValueError("当前动作基线不可用，不能省略比较")
    # Test is evaluated only after candidate and thresholds have been frozen.
    results = {
        "uniform": evaluate(ComparisonPolicy("uniform"), partitions["test"], allow_drafts=allow_drafts),
        "rule_teacher": evaluate(ComparisonPolicy("rule_teacher"), partitions["test"], allow_drafts=allow_drafts),
        "current": evaluate(baseline, partitions["test"], allow_drafts=allow_drafts),
        "candidate": evaluate(selected, partitions["test"], allow_drafts=allow_drafts, thresholds=thresholds),
        "candidate_no_task_text": evaluate(selected, partitions["test"], allow_drafts=allow_drafts,
                                            ablation="no_task_text", thresholds=thresholds),
        "candidate_no_context": evaluate(selected, partitions["test"], allow_drafts=allow_drafts,
                                          ablation="no_context", thresholds=thresholds),
    }
    report = {"manifest": manifest, "supervision": supervision,
              "entity_input": "provided_annotation_not_actual_gliner",
              "test_scope": "synthetic_template_holdout_not_independent_blind_test",
              "selected_candidate": selected.model_path.name,
              "validation_candidates": [{"content_weight": -v[2],
                                         "acceptable_action_rate": v[4]["acceptable_action_rate"],
                                         "macro_f1": v[4]["macro_f1"]} for v in candidates],
              "thresholds": thresholds, "results": results,
              "production_promoted": False,
              "limitations": ["不是人工质量或真实隐私泄漏率", "未调用外部模型或评估生成文案质量",
                              "合成模板留出并非新独立终测", "未替换 ACTIVE_MODELS 或在线权重"]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
