from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from milai.application.semantic_episode_boundary_v02 import (
    MemoryFormationBundleServiceV02,
)
from milai.application.semantic_episode_shadow import SemanticEpisodeShadowHook
from milai.domain.requirement_state import canonical_sha256

from evals.md02 import boundary_shadow_effect
from evals.md02.boundary_shadow_effect import (
    environment_witness,
    evaluate_repair_dev,
    hand_contract_sanity,
)

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "evals/md02/fixtures/boundary-repair-dev.v0.1.json"
SEALED = ROOT / "evals/md02/fixtures/shadow-validation.v0.1.json"
FRESHNESS = ROOT / "evals/md02/fixtures/freshness-contract.v0.1.json"
RUN_LOCK = ROOT / "var/md02/md02-boundary-product-shadow-20260830-001/run-lock.json"


def test_md02_labels_were_sealed_before_implementation_with_exact_denominators() -> (
    None
):
    lock = _object(RUN_LOCK)
    material = dict(lock)
    observed_digest = material.pop("run_lock_digest")
    assert observed_digest == canonical_sha256(material)
    assert lock["scorer_present_at_label_seal"] is False
    assert lock["boundary_v02_present_at_label_seal"] is False
    assert lock["shadow_hook_present_at_label_seal"] is False

    fixtures = lock["fixtures"]
    for name, path in (
        ("boundary_repair_dev", REPAIR),
        ("shadow_validation", SEALED),
        ("freshness_contract", FRESHNESS),
    ):
        identity = fixtures[name]
        assert identity["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert identity["size"] == path.stat().st_size
    repair = _object(REPAIR)
    sealed = _object(SEALED)
    assert len(repair["conversations"]) == 8
    assert len(sealed["conversations"]) == 24
    assert sum(len(item["turns"]) for item in sealed["conversations"]) == 96
    assert sum(len(item["memory_probes"]) for item in sealed["conversations"]) == 24
    assert fixtures["shadow_validation"]["family_counts"] == {
        "CONTINUATION_PRESSURE": 6,
        "MIXED_ASSISTANT_BRIDGE": 1,
        "MIXED_CORRECTION": 2,
        "MIXED_EXPLICIT_SHIFT": 1,
        "MIXED_LONG_GAP_CONTINUATION": 1,
        "MIXED_SESSION_BOUNDARY": 1,
        "OVER_MERGE_PRESSURE": 12,
    }


def test_repair_dev_closes_v02_rules_without_running_a_sealed_effect() -> None:
    result = evaluate_repair_dev(ROOT)

    assert result["deltas"]["over_merge_pair_rate_absolute_reduction"] >= 0.05
    assert result["deltas"]["over_split_pair_rate_increase"] <= 0.02
    assert result["deltas"]["episode_pairwise_f1_delta"] >= -0.02
    assert result["deltas"]["support_closure_auc_delta"] >= -0.02
    assert result["failure_distribution"] == {
        "v02_over_merge": [],
        "v02_over_split": [],
    }
    assert result["h1_supported"] is True


def test_official_repair_dev_probe_is_immutable_under_observation_only_shadow() -> None:
    conversation = _object(REPAIR)["conversations"][0]
    turns = conversation["turns"]
    query = conversation["memory_probes"][0]["query_text"]
    behavior, anchors, baseline_calls, repository = (
        boundary_shadow_effect._official_baseline_behavior(turns, query)
    )
    behavior_before = canonical_sha256(behavior)
    bundle = MemoryFormationBundleServiceV02().build(turns).bundle
    calls_before = repository.calls

    observation = SemanticEpisodeShadowHook(enabled=True).observe(
        request_identity="repair-official-probe",
        baseline_behavior=behavior,
        current_sources=turns,
        official_anchor_evidence_ids=anchors,
        bundle=bundle,
    )

    assert observation is not None and observation.disposition == "OBSERVED"
    assert baseline_calls > 0
    assert repository.calls == calls_before
    assert canonical_sha256(behavior) == behavior_before
    assert observation.additional_official_acquisition_calls == 0
    assert observation.additional_reader_calls == 0
    assert observation.additional_provider_calls == 0
    assert observation.additional_model_calls == 0


def test_effect_prediction_is_sealed_before_label_scoring_and_uses_official_ranker() -> (
    None
):
    source_path = ROOT / "evals/md02/boundary_shadow_effect.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    execute = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_boundary_effect"
    )
    assignments = {
        target.id: node.lineno
        for node in ast.walk(execute)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert (
        assignments["predictions"]
        < assignments["prediction_digest"]
        < assignments["score"]
    )
    assert "rank_evidence_turns" in source
    assert "RawFtsAcquirer" not in source


def test_md02_hand_contract_and_environment_witness_are_exact() -> None:
    assert hand_contract_sanity() == {
        "perfect_pairwise_f1": 1.0,
        "merged_over_merge_pair_rate": 1.0,
        "split_over_split_pair_rate": 1.0,
        "freshness_scenario_count": 6,
    }
    assert environment_witness() == "WITNESS 2 6 0"


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
