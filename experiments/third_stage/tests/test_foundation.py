"""R0、上下文包、夹具结构和更新关系分离。不把未实现的 L3/L4/C3 算作通过。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from experiments.third_stage.cases import CORE_FOUR_STATE, materialize_suite
from experiments.third_stage.context import build_context_package, same_candidate_input
from experiments.third_stage.keys import EXAMPLE_VAULT_KEY, KeyPolicyError
from experiments.third_stage.links import apply_update, validate_link
from experiments.third_stage.maps import FORBIDDEN_KEYS
from experiments.third_stage.registry import RegistryInputError, build_registry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "t1_t13.json"
REQUIRED = {
    "case_id",
    "source_documents",
    "revisions",
    "evidence_anchors",
    "claim",
    "expected_registry",
    "expected_links",
    "expected_update_relations",
    "expected_assertions",
    "expected_source_conflict",
    "expected_four_state",
    "rationale",
    "execution",
}


class RegistryTests(unittest.TestCase):
    def test_same_input_same_registry_and_hash(self):
        anchors = [{
            "evidence_anchor": "block:a1",
            "revision_id": "rev",
            "raw_text": "建议将差旅预算调整为 8000 元。",
            "parent_scope": "sec_1",
            "subject_type": "organization",
            "subject_cluster_key": "cluster-014",
            "scope_type": "activity",
            "scope_local_key": "spring-recruit",
        }]
        first = build_registry(anchors, vault_key=EXAMPLE_VAULT_KEY)
        second = build_registry(list(reversed(anchors)), vault_key=EXAMPLE_VAULT_KEY)
        self.assertEqual(first, second)
        self.assertEqual(len(first["registry_sha256"]), 64)

    def test_amount_and_status_words_do_not_change_registry(self):
        def anchor(text):
            return {
                "evidence_anchor": "block:a1",
                "revision_id": "rev",
                "raw_text": text,
                "parent_scope": "sec_1",
                "subject_type": "organization",
                "subject_cluster_key": "cluster-014",
                "scope_type": "activity",
                "scope_local_key": "spring-recruit",
            }
        low = build_registry([anchor("建议将差旅预算调整为 8000 元。")], vault_key=EXAMPLE_VAULT_KEY)
        high = build_registry([anchor("建议将差旅预算调整为 9000 元。")], vault_key=EXAMPLE_VAULT_KEY)
        approved = build_registry([anchor("建议将差旅预算调整为 8000 元，已批准。")], vault_key=EXAMPLE_VAULT_KEY)
        checked = build_registry([anchor("建议将差旅预算调整为 8000 元，核准。")], vault_key=EXAMPLE_VAULT_KEY)
        self.assertEqual(low["registry_sha256"], high["registry_sha256"])
        self.assertEqual(low["registry_sha256"], approved["registry_sha256"])
        self.assertEqual(low["registry_sha256"], checked["registry_sha256"])
        self.assertEqual(low["candidates"][0]["attribute_id"], "budget_amount")
        self.assertNotIn("status", low["candidates"][0])
        self.assertNotIn("numeric_value", low["candidates"][0])

    def test_unknown_attribute_stays_blank_and_multiple_hits_do_not_guess(self):
        blank = build_registry([{
            "evidence_anchor": "block:b1",
            "revision_id": "rev",
            "raw_text": "上述建议已经批准。",
            "parent_scope": "sec_1",
        }], vault_key=EXAMPLE_VAULT_KEY)
        mixed = build_registry([{
            "evidence_anchor": "block:m1",
            "revision_id": "rev",
            "raw_text": "活动人数和差旅预算都要核对。",
            "parent_scope": "sec_1",
        }], vault_key=EXAMPLE_VAULT_KEY)
        self.assertEqual(blank["candidates"][0]["attribute_id"], "")
        self.assertEqual(blank["candidates"][0]["subject_id"], "")
        self.assertEqual(mixed["candidates"][0]["attribute_id"], "")

    def test_name_is_not_hashed_and_duplicate_anchor_is_rejected(self):
        named = build_registry([{
            "evidence_anchor": "block:p1",
            "revision_id": "rev",
            "raw_text": "张三到场。",
            "parent_scope": "sec_1",
            "subject_type": "person",
            "subject_cluster_key": "张三",
        }], vault_key=EXAMPLE_VAULT_KEY)
        self.assertEqual(named["candidates"][0]["subject_id"], "")
        with self.assertRaises(RegistryInputError):
            build_registry([
                {"evidence_anchor": "block:a1", "revision_id": "rev", "raw_text": "甲", "parent_scope": "sec_1"},
                {"evidence_anchor": "block:a1", "revision_id": "rev", "raw_text": "乙", "parent_scope": "sec_1"},
            ], vault_key=EXAMPLE_VAULT_KEY)

    def test_forbidden_fields_and_real_data_key(self):
        with self.assertRaises(RegistryInputError):
            build_registry([{
                "evidence_anchor": "block:a1",
                "revision_id": "rev",
                "raw_text": "差旅预算为 8000 元。",
                "parent_scope": "sec_1",
                "claim": "差旅预算已经批准为 8000 元。",
            }], vault_key=EXAMPLE_VAULT_KEY)
        with self.assertRaises(KeyPolicyError):
            build_registry([], vault_key=EXAMPLE_VAULT_KEY, for_real_data=True)

    def test_changed_parent_changes_hash(self):
        base = {"evidence_anchor": "block:a1", "revision_id": "rev", "raw_text": "活动人数为 12 人。"}
        one = build_registry([{**base, "parent_scope": "sec_1"}], vault_key=EXAMPLE_VAULT_KEY)
        two = build_registry([{**base, "parent_scope": "sec_2"}], vault_key=EXAMPLE_VAULT_KEY)
        self.assertNotEqual(one["registry_sha256"], two["registry_sha256"])


class ContextTests(unittest.TestCase):
    def _registry(self):
        return build_registry([
            {
                "evidence_anchor": "block:a1",
                "revision_id": "rev-t13",
                "raw_text": "建议将差旅预算调整为 8000 元。",
                "parent_scope": "sec_1",
                "subject_type": "organization",
                "subject_cluster_key": "cluster-014",
                "scope_type": "activity",
                "scope_local_key": "spring-recruit",
            },
            {
                "evidence_anchor": "block:b1",
                "revision_id": "rev-t13",
                "raw_text": "上述建议已经批准。",
                "parent_scope": "sec_1",
            },
            {
                "evidence_anchor": "block:z1",
                "revision_id": "rev-t13",
                "raw_text": "全体活动人数为 12 人。",
                "parent_scope": "sec_9",
            },
        ], vault_key=EXAMPLE_VAULT_KEY)

    def test_slice_isolation_and_same_input_for_both_channels(self):
        registry = self._registry()
        package = build_context_package(
            registry,
            current_anchor="block:b1",
            current_text="上述建议已经批准。",
            parent_scope="sec_1",
        )
        other = build_context_package(
            registry,
            current_anchor="block:b1",
            current_text="上述建议已经批准。",
            parent_scope="sec_1",
        )
        self.assertTrue(same_candidate_input(package, other))
        self.assertEqual(package["registry_sha256"], registry["registry_sha256"])
        anchors = {item["evidence_anchor"] for item in package["candidate_facts"]}
        self.assertEqual(anchors, {"block:a1", "block:b1"})
        serialized = json.dumps(package["candidate_facts"], ensure_ascii=False)
        self.assertNotIn("8000", serialized)
        self.assertFalse(set(package) & FORBIDDEN_KEYS)
        for fact in package["candidate_facts"]:
            self.assertFalse(set(fact) & FORBIDDEN_KEYS)
            self.assertEqual(len(fact), 7)

    def test_context_rejects_tampered_registry(self):
        registry = self._registry()
        registry["candidates"][0]["attribute_id"] = "location"
        with self.assertRaises(Exception):
            build_context_package(
                registry,
                current_anchor="block:b1",
                current_text="上述建议已经批准。",
                parent_scope="sec_1",
            )


class RelationTests(unittest.TestCase):
    def test_identity_link_does_not_retire_old_values(self):
        only_identity = apply_update(None, current_text="上述建议已经批准。")
        reference = apply_update(
            {"relation": "reference_only", "updated_dimensions": ["status"], "basis_span": "上述", "basis_start": 0, "basis_end": 2},
            current_text="上述建议已经批准。",
        )
        self.assertEqual(only_identity["retired_dimensions"], [])
        self.assertFalse(only_identity["pause"])
        self.assertEqual(reference["retired_dimensions"], [])
        self.assertNotIn("status", reference["retired_dimensions"])

    def test_update_covers_only_named_dimension_and_history_does_not(self):
        current = apply_update({
            "relation": "updates_dimension",
            "basis_span": "已经批准",
            "basis_start": 4,
            "basis_end": 8,
            "updated_dimensions": ["status"],
        }, current_text="上述建议已经批准。")
        self.assertEqual(current["retired_dimensions"], ["status"])
        self.assertNotIn("numeric_value", current["retired_dimensions"])
        historical = apply_update({
            "relation": "unknown",
            "basis_span": "曾经获得批准",
            "basis_start": 4,
            "basis_end": 10,
            "updated_dimensions": ["status"],
        }, current_text="上述建议曾经获得批准。")
        self.assertEqual(historical["retired_dimensions"], [])
        self.assertTrue(historical["pause"])
        missing = apply_update({
            "relation": "updates_dimension",
            "basis_span": "",
            "basis_start": 0,
            "basis_end": 0,
            "updated_dimensions": ["status"],
        }, current_text="上述建议已经批准。")
        self.assertEqual(missing["retired_dimensions"], [])
        self.assertTrue(missing["pause"])


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_file_matches_generator_and_records_pending_algorithms(self):
        self.assertEqual(self.suite, materialize_suite())
        self.assertIn("L3", self.suite["not_implemented"])
        self.assertIn("L4", self.suite["not_implemented"])
        self.assertIn("C3", self.suite["not_implemented"])
        self.assertIn("C4", self.suite["not_implemented"])

    def test_core_gold_and_required_fields(self):
        by_id = {case["case_id"]: case for case in self.suite["cases"]}
        for core_id, state in CORE_FOUR_STATE.items():
            self.assertEqual(by_id[core_id]["expected_four_state"], state)
            self.assertEqual(by_id[core_id]["execution"], "pending_l3_l4")
        for case_id in ("T13-a",):
            self.assertNotIn(case_id, by_id)
        self.assertEqual(by_id["T13"]["subcase_id"], "T13-a")
        for extra in ("T13-b", "T13-c", "T13-d", "T13-e", "T13-f", "T13-hist", "T7-a", "T7-b", "T7-c", "T7-d", "T12-a"):
            self.assertIn(extra, by_id)
        self.assertEqual(by_id["T13-f"]["expected_four_state"], "withheld_pending_human_link_gold")
        self.assertEqual(by_id["T7"]["expected_source_conflict"], "conflict")
        self.assertEqual(by_id["T7-b"]["expected_source_conflict"], "none")
        self.assertEqual(by_id["T7-c"]["expected_source_conflict"], "none")
        self.assertEqual(by_id["T12"]["expected_source_conflict"], "none")
        self.assertEqual(by_id["T13-hist"]["expected_update_relations"][0]["relation"], "unknown")
        self.assertEqual(by_id["T13"]["expected_update_relations"][0]["updated_dimensions"], ["status"])
        for case in self.suite["cases"]:
            self.assertTrue(REQUIRED <= set(case))
            self.assertEqual(case["execution"], "pending_l3_l4")

    def test_registry_oracle_and_link_gate(self):
        for case in self.suite["cases"]:
            rebuilt = build_registry(case["anchors"], vault_key=EXAMPLE_VAULT_KEY)
            self.assertEqual(rebuilt, case["expected_registry"])
            by_id = {item["candidate_id"]: item for item in rebuilt["candidates"]}
            self.assertEqual(len(rebuilt["candidates"]), len(case["anchors"]))
            for binding in case["registry_binding"]:
                oracle = case["oracle"][binding["oracle_key"]]
                candidate = by_id[binding["candidate_id"]]
                self.assertEqual(candidate["attribute_id"], oracle["attribute_id"])
                self.assertEqual(candidate["grain_id"], oracle["grain_id"])
                self.assertEqual(bool(candidate["subject_id"]), oracle["has_subject"])
                self.assertEqual(bool(candidate["context_scope_id"]), oracle["has_scope"])
                self.assertFalse(set(candidate) & FORBIDDEN_KEYS)
            for proposal in case["expected_links"] + case["negative_proposals"]:
                result = validate_link(
                    proposal,
                    current_text=proposal.get("current_text", ""),
                    current_anchor=proposal.get("current_anchor", ""),
                    candidates=rebuilt["candidates"],
                    parent_scope="sec_1",
                )
                expected = proposal["structural_expectation"]
                if expected == "accept":
                    self.assertTrue(result["accepted"], case["case_id"])
                elif expected == "abstain":
                    self.assertEqual(result["reason"], "abstain", case["case_id"])
                    self.assertFalse(result["structural_failure"])
                else:
                    self.assertFalse(result["accepted"], case["case_id"])
                    self.assertTrue(result["structural_failure"], case["case_id"])
            for update in case["expected_update_relations"]:
                outcome = apply_update(update, current_text=update["current_text"])
                if update["relation"] == "updates_dimension":
                    self.assertEqual(outcome["retired_dimensions"], update["updated_dimensions"])
                else:
                    self.assertEqual(outcome["retired_dimensions"], [])


if __name__ == "__main__":
    unittest.main()
