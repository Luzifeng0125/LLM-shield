"""L3、L4 和 C3 的可重复测试。金标不一致的条目被单独锁住，不改成通过。"""
from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path

from experiments.third_stage.c4_interface import C4Unavailable, propose_assertion, propose_link
from experiments.third_stage.cases import CORE_FOUR_STATE, materialize_suite
from experiments.third_stage.extract import extract_text
from experiments.third_stage.l4 import verify_case
from experiments.third_stage.links import validate_link
from experiments.third_stage.pipeline import assertion_diffs

ROOT = Path(__file__).resolve().parents[3]


def _dim(extraction, name):
    return extraction["dimensions"][name]


class ExtractionTests(unittest.TestCase):
    def test_offsets_point_at_the_quoted_source(self):
        text = "建议将差旅预算调整为 8000 元。"
        extracted = extract_text(text)
        for name in ("status", "attribute", "numeric_value", "unit"):
            item = _dim(extracted, name)
            self.assertEqual(text[item["start"]:item["end"]], {
                "status": "建议",
                "attribute": "差旅预算",
                "numeric_value": "8000",
                "unit": "元",
            }[name])
        dated = "2026年3月全体活动人数为 12 人。"
        dated_extraction = extract_text(dated)
        unit = _dim(dated_extraction, "unit")
        self.assertEqual(dated[unit["start"]:unit["end"]], "人")
        self.assertGreater(unit["start"], dated.index("12"))
        self.assertEqual(_dim(dated_extraction, "numeric_value")["value"], "12")
        self.assertEqual(_dim(dated_extraction, "valid_time")["value"], "2026-03")

    def test_status_lexicon_and_polarity_stay_separate(self):
        self.assertEqual(_dim(extract_text("尚未批准。"), "status")["value"], "not_yet_approved")
        self.assertEqual(_dim(extract_text("已批准。"), "status")["value"], "approved")
        self.assertEqual(_dim(extract_text("已否决。"), "status")["value"], "rejected")
        self.assertEqual(_dim(extract_text("正在审批。"), "status")["value"], "pending")
        self.assertEqual(_dim(extract_text("核准。"), "status")["kind"], "unparsable")
        self.assertEqual(_dim(extract_text("未批准。"), "status")["kind"], "unparsable")
        self.assertEqual(_dim(extract_text("差旅预算为 8000 元。"), "status")["kind"], "unmentioned")
        self.assertEqual(_dim(extract_text("批准，已经批准。"), "status")["value"], "approved")
        self.assertEqual(_dim(extract_text("已批准并且已否决。"), "status")["kind"], "unparsable")
        reached = extract_text("尚未达到 12 人。")
        self.assertEqual(_dim(reached, "polarity")["value"], "neg")
        self.assertEqual(_dim(reached, "status")["kind"], "not_applicable")
        self.assertNotEqual(_dim(reached, "status").get("value"), "not_yet_approved")

    def test_anaphoric_suggestion_is_not_a_second_status(self):
        extracted = extract_text("上述建议已经批准。")
        self.assertEqual(_dim(extracted, "status")["value"], "approved")
        self.assertEqual(_dim(extracted, "numeric_value")["kind"], "unmentioned")

    def test_claim_text_does_not_fill_evidence_numbers(self):
        evidence = extract_text("上述建议已经批准。")
        claim = extract_text("差旅预算已经批准为 8000 元。")
        self.assertEqual(_dim(evidence, "numeric_value")["kind"], "unmentioned")
        self.assertEqual(_dim(claim, "numeric_value")["value"], "8000")
        self.assertNotEqual(evidence["quote_sha256"], claim["quote_sha256"])


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = materialize_suite()
        cls.by_id = {case["case_id"]: case for case in cls.suite["cases"]}
        cls.outcomes = {case["case_id"]: verify_case(case) for case in cls.suite["cases"]}

    def test_core_four_states_match_gold(self):
        for core_id, state in CORE_FOUR_STATE.items():
            self.assertEqual(self.outcomes[core_id]["four_state"], state)
            self.assertFalse(self.outcomes[core_id]["c4_called"])

    def test_joint_support_updates_only_status(self):
        outcome = self.outcomes["T13"]
        self.assertEqual(outcome["four_state"], "still_valid")
        update = outcome["updates"][0]
        self.assertEqual(update["update"]["updated_dimensions"], ["status"])
        self.assertEqual(update["update"]["basis_span"], "已经批准")
        self.assertEqual(update["applied"]["retired_dimensions"], ["status"])
        self.assertEqual(outcome["claim_relation"]["numeric_value"], "match")
        self.assertEqual(outcome["claim_relation"]["status"], "match")
        self.assertEqual(outcome["source_conflict"], "none")

    def test_same_dimension_conflict_and_disjoint_time(self):
        conflict = self.outcomes["T7"]
        self.assertEqual(conflict["four_state"], "paused")
        self.assertEqual(conflict["source_conflict"], "conflict")
        self.assertEqual(conflict["source_conflict_pairs"][0]["dimension"], "numeric_value")
        separated = self.outcomes["T12"]
        self.assertEqual(separated["four_state"], "still_valid")
        self.assertEqual(separated["source_conflict_pairs"], [])
        self.assertIn("block:apr", separated["temporal_slices"])
        self.assertEqual(self.outcomes["T7-c"]["source_conflict"], "none")
        self.assertEqual(self.outcomes["T7-b"]["four_state"], "still_valid")

    def test_identity_link_does_not_become_historical_update(self):
        historical = self.outcomes["T13-hist"]
        self.assertEqual(historical["four_state"], "paused")
        self.assertEqual(historical["reasons"], ["update_unknown"])
        self.assertEqual(historical["updates"][0]["applied"]["retired_dimensions"], [])
        self.assertEqual(historical["updates"][0]["update"]["basis_span"], "曾经获得批准")

    def test_missing_unparsable_and_duplicate_evidence_pause(self):
        self.assertEqual(self.outcomes["T8"]["four_state"], "paused")
        self.assertNotEqual(self.outcomes["T8"]["four_state"], "invalid")
        self.assertEqual(self.outcomes["T3-no-block"]["reasons"], ["location_missing"])
        self.assertEqual(self.outcomes["T10"]["reasons"], ["location_not_unique"])
        self.assertEqual(self.outcomes["T4-claim-unparsable"]["four_state"], "paused")
        self.assertEqual(self.outcomes["T4-claim-unmentioned"]["four_state"], "paused")
        self.assertEqual(self.outcomes["T4"]["reasons"], ["subject_unparsable"])

    def test_adversarial_span_is_not_replaced_by_c3(self):
        outcome = self.outcomes["T13-d"]
        used = next(item for item in outcome["links"] if item["anchor"] == "block:b1")
        self.assertEqual(used["source"], "adversarial_proposal")
        self.assertFalse(used["used"]["gate"]["accepted"])
        self.assertEqual(used["c3"]["gate"]["reason"], "structural_pass")
        self.assertEqual(outcome["four_state"], "paused")
        shifted = self.outcomes["T13-e"]
        shifted_link = next(item for item in shifted["links"] if item["anchor"] == "block:b1")
        self.assertEqual(shifted_link["used"]["gate"]["reason"], "basis_mismatch")

    def test_unique_candidate_without_explicit_word_abstains(self):
        outcome = self.outcomes["T13-b"]
        link = next(item for item in outcome["links"] if item["anchor"] == "block:c1")
        self.assertEqual(link["c3"]["proposal"]["link_type"], "abstain")
        self.assertEqual(outcome["four_state"], "paused")
        self.assertNotEqual(outcome["four_state"], "invalid")

    def test_c4_case_is_not_scored_as_c3_success(self):
        case = self.by_id["T13-f"]
        outcome = self.outcomes["T13-f"]
        self.assertEqual(outcome["disposition"], "c4_pending")
        self.assertIsNone(outcome["four_state"])
        self.assertFalse(outcome["c4_called"])
        link = next(item for item in outcome["links"] if item["anchor"] == "block:b1")
        self.assertEqual(link["c3"]["proposal"]["link_type"], "abstain")
        status = next(
            item["dimensions"]["status"]
            for item in outcome["assertions"]
            if item["evidence_location"]["anchor"] == "block:b1" and item["role"] == "current"
        )
        self.assertEqual(status["kind"], "unparsable")
        proposal = case["expected_links"][0]
        structural = validate_link(
            proposal,
            current_text=proposal["current_text"],
            current_anchor=proposal["current_anchor"],
            candidates=case["expected_registry"]["candidates"],
            parent_scope="sec_1",
        )
        self.assertTrue(structural["accepted"])
        self.assertNotEqual(outcome["four_state"], "still_valid")

    def test_quote_is_traceable(self):
        for outcome in self.outcomes.values():
            for assertion in outcome["assertions"]:
                location = assertion["evidence_location"]
                digest = hashlib.sha256(location["text"].encode("utf-8")).hexdigest()
                self.assertEqual(location["quote_sha256"], digest)
                self.assertTrue(location["anchor"])
                self.assertTrue(location["revision_id"])
                for span in location["spans"].values():
                    self.assertEqual(location["text"][span["start"]:span["end"]], span["text"])

    def test_known_gold_deltas_are_exact_and_not_relabelled(self):
        mismatches = []
        for case in self.suite["cases"]:
            outcome = self.outcomes[case["case_id"]]
            if case["expected_four_state"] == "withheld_pending_human_link_gold":
                continue
            if outcome["four_state"] != case["expected_four_state"]:
                mismatches.append(case["case_id"])
            diffs = assertion_diffs(case, outcome)
            if case["case_id"] in {"T7", "T7-a"}:
                self.assertTrue(diffs)
                self.assertTrue(all("valid_time" in item and "unmentioned" in item for item in diffs))
            else:
                self.assertEqual(diffs, [])
            if case["case_id"] == "T13-c":
                self.assertEqual(outcome["source_conflict"], "conflict")
                self.assertEqual(case["expected_source_conflict"], "none")
            elif case["expected_four_state"] != "withheld_pending_human_link_gold":
                self.assertEqual(outcome["source_conflict"], case["expected_source_conflict"])
        self.assertEqual(mismatches, ["T12-a"])
        withheld = self.by_id["T12-a"]
        actual = self.outcomes["T12-a"]
        self.assertEqual(withheld["expected_four_state"], "still_valid")
        self.assertEqual(actual["four_state"], "paused")
        self.assertEqual(actual["claim_relation"]["status"], "missing")
        self.assertEqual(actual["claim_relation"]["numeric_value"], "match")
        self.assertEqual(withheld["execution"], "pending_l3_l4")

    def test_running_l4_does_not_rewrite_fixture_gold(self):
        for case in self.suite["cases"]:
            verify_case(case)
            self.assertEqual(case["execution"], "pending_l3_l4")
        self.assertEqual(self.by_id["T1"]["expected_four_state"], "invalid")
        self.assertEqual(self.by_id["T5"]["oracle"]["block:n1"]["attribute_id"], "")


class InterfaceTests(unittest.TestCase):
    def test_c4_refuses_instead_of_echoing_rules(self):
        with self.assertRaises(C4Unavailable):
            propose_link({"schema": "yin-dun.context_package.v1"})
        with self.assertRaises(C4Unavailable):
            propose_assertion("上述建议已经批准。")

    def test_experiment_code_does_not_touch_product_modules(self):
        root = ROOT / "experiments" / "third_stage"
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("llm_shield", text)
            self.assertNotIn("import delivery", text)
        status = subprocess.check_output(
            ["git", "status", "--short", "--", "delivery"],
            cwd=ROOT,
            text=True,
        )
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
