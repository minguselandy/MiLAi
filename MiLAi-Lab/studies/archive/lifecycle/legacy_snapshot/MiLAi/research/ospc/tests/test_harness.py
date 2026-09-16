from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import ClassVar

from research.ospc.compressors import (
    METHODS,
    b_min_tokens,
    full_raw_context,
    ospc,
    ospc_with_candidate,
    typed_state,
    validate_preservation,
)
from research.ospc.models import Fixture, load_fixtures
from research.ospc.scorer import aggregate, score_one

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pilot.jsonl"
ROOT = Path(__file__).resolve().parents[1]


class FixtureTests(unittest.TestCase):
    fixtures: ClassVar[list[Fixture]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures(FIXTURES)

    def test_pilot_has_40_frozen_labels_in_two_domains(self) -> None:
        self.assertEqual(len(self.fixtures), 40)
        self.assertEqual(
            {fixture.domain for fixture in self.fixtures},
            {
                "software_project_memory",
                "personalized_multi_session_assistant",
            },
        )
        self.assertTrue(
            all(
                fixture.annotation_version == "ospc.annotation.v1"
                for fixture in self.fixtures
            )
        )
        self.assertEqual(
            sum(fixture.resolution.admissible for fixture in self.fixtures), 20
        )
        self.assertTrue(all(fixture.constraints for fixture in self.fixtures))

    def test_fixture_manifest_matches_immutable_snapshot(self) -> None:
        manifest = json.loads(
            (ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["fixture_count"], 40)
        self.assertTrue(manifest["synthetic_only"])
        self.assertEqual(
            manifest["pilot_sha256"], hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
        )

    def test_research_source_has_no_runtime_or_external_framework_import(self) -> None:
        forbidden = (
            "from milai",
            "import milai",
            "from reme",
            "import reme",
            "from hindsight",
            "import hindsight",
            "from graphiti",
            "import graphiti",
            "from mem0",
            "import mem0",
            "psycopg",
            "sqlalchemy",
        )
        source_files = list(ROOT.glob("*.py"))
        self.assertGreaterEqual(len(source_files), 5)
        for path in source_files:
            text = path.read_text(encoding="utf-8").lower()
            with self.subTest(path=path.name):
                self.assertFalse(any(marker in text for marker in forbidden))

    def test_every_method_respects_equal_total_budget(self) -> None:
        for fixture in self.fixtures:
            for method, compressor in METHODS.items():
                with self.subTest(fixture=fixture.fixture_id, method=method):
                    self.assertTrue(compressor(fixture).budget_compliant)

    def test_minimum_baseline_and_ablation_set_is_complete(self) -> None:
        self.assertTrue(
            {
                "full_raw_context",
                "naive_recursive",
                "extractive_top_k",
                "hierarchical_summary",
                "structured_eviction",
                "typed_state",
                "static_open_issue",
                "oracle_equal_budget",
                "ospc_no_protected",
                "ospc_no_discharge",
                "ospc_no_branches",
                "ospc_no_validator",
            }
            <= METHODS.keys()
        )

    def test_below_b_min_is_explicitly_infeasible(self) -> None:
        below = [
            fixture
            for fixture in self.fixtures
            if fixture.budget_tokens < b_min_tokens(fixture)
        ]
        self.assertEqual(len(below), 8)
        for fixture in below:
            for method, compressor in METHODS.items():
                with self.subTest(fixture=fixture.fixture_id, method=method):
                    result = compressor(fixture)
                    self.assertTrue(result.infeasible)
                    self.assertEqual(result.failure_code, "INFEASIBLE_UNDER_BUDGET")
                    row = score_one(fixture, result)
                    self.assertNotIn("false_closure", row)

    def test_normalized_output_schema_and_full_raw_reference_are_runnable(self) -> None:
        required = {
            "status",
            "goal",
            "constraints",
            "stable_state",
            "open_issues",
            "evidence_pointers",
            "evicted_recoverable",
            "compression_trace",
        }
        feasible_raw = 0
        for fixture in self.fixtures:
            for compressor in METHODS.values():
                result = compressor(fixture)
                self.assertTrue(required <= result.payload.keys())
            feasible_raw += not full_raw_context(fixture).infeasible
        self.assertEqual(feasible_raw, 16)

    def test_validator_rejects_branch_loss_and_uses_fallback(self) -> None:
        fixture = next(
            item for item in self.fixtures if item.budget_tokens >= b_min_tokens(item)
        )
        candidate = ospc(fixture).payload
        candidate["open_issues"][0].pop("contradict_refs")
        self.assertIn(
            "CONTRADICT_REFS_MISMATCH", validate_preservation(fixture, candidate)
        )
        recovered = ospc_with_candidate(fixture, candidate)
        self.assertEqual(recovered.fallback_count, 1)
        self.assertEqual(validate_preservation(fixture, recovered.payload), ())

    def test_typed_state_absorbs_ospc_primary_result(self) -> None:
        typed_rows = [
            score_one(fixture, typed_state(fixture)) for fixture in self.fixtures
        ]
        ospc_rows = [score_one(fixture, ospc(fixture)) for fixture in self.fixtures]
        typed = aggregate(typed_rows)
        candidate = aggregate(ospc_rows)
        for field in (
            "identity_recall",
            "branch_recall",
            "representation_false_closure_rate",
            "decision_false_closure_rate",
            "legal_resolution_accuracy",
            "later_task_success",
            "unsupported_claim_rate",
            "infeasible_rate",
        ):
            self.assertEqual(typed[field], candidate[field])
        self.assertGreater(
            candidate["validator_checks_total"], typed["validator_checks_total"]
        )


if __name__ == "__main__":
    unittest.main()
