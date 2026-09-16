from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

from milai.domain.requirement_state import canonical_sha256

from evals.mf02 import four_arm_effect
from evals.mf02.four_arm_effect import (
    ARM_NAMES,
    RawFtsAcquirer,
    build_representation_arms,
    environment_witness,
    evaluate_repair_dev,
    hand_scorer_sanity,
    md01_scorer_sanity,
)

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "evals/mf02/fixtures/repair-dev.v0.1.json"
SEALED = ROOT / "evals/mf02/fixtures/sealed-validation.v0.1.json"
RUN_LOCK = ROOT / "var/mf02/mf02-semantic-episode-four-arm-20260830-001/run-lock.json"


def test_labels_were_sealed_before_scorer_with_required_denominators() -> None:
    lock = _object(RUN_LOCK)
    repair = _object(REPAIR)
    sealed = _object(SEALED)

    material = dict(lock)
    observed_digest = material.pop("run_lock_digest")
    assert observed_digest == canonical_sha256(material)
    assert lock["scorer_present_at_label_seal"] is False
    assert len(repair["conversations"]) == 8
    assert len(sealed["conversations"]) == 24
    assert sum(len(item["turns"]) for item in sealed["conversations"]) == 96
    assert sum(len(item["memory_probes"]) for item in sealed["conversations"]) == 24
    sealed_identity = lock["fixtures"]["sealed_validation"]
    assert sealed_identity["sha256"] == hashlib.sha256(SEALED.read_bytes()).hexdigest()
    assert set(sealed_identity["family_counts"].values()) == {3}
    for conversation in sealed["conversations"]:
        membership = {
            index: episode_index
            for episode_index, episode in enumerate(conversation["expected_episodes"])
            for index in episode["turn_indexes"]
        }
        pairs = [
            membership[left] == membership[right]
            for left in range(len(conversation["turns"]))
            for right in range(left + 1, len(conversation["turns"]))
        ]
        assert any(pairs)
        assert not all(pairs)


def test_hand_scorer_and_md01_historical_replay_are_exact() -> None:
    assert hand_scorer_sanity() == {
        "perfect_pairwise_f1": 1.0,
        "turn_pairwise_f1": 0.0,
        "session_pairwise_f1": 0.5,
    }
    replay = md01_scorer_sanity(ROOT)
    assert replay == {
        "conversation_count": 10,
        "episode_pairwise_f1": 1.0,
        "expected_episode_pairwise_f1": 1.0,
        "passed": True,
        "included_in_mf02_main_denominator": False,
    }


def test_four_arms_preserve_every_complete_raw_turn_once() -> None:
    fixture = _object(REPAIR)
    turns = fixture["conversations"][0]["turns"]

    result = build_representation_arms(turns)

    assert tuple(result.arms) == ARM_NAMES
    expected_ids = [turn["evidence_id"] for turn in turns]
    for arm in result.arms.values():
        spans = [span for unit in arm["units"] for span in unit["source_spans"]]
        assert [span["evidence_id"] for span in spans] == expected_ids
        assert [span["text"] for span in spans] == [turn["content"] for turn in turns]
        assert all(span["start"] == 0 for span in spans)
        assert all(
            span["end"] == len(turn["content"])
            for span, turn in zip(spans, turns, strict=True)
        )
        assert arm["canonical"] is False
        assert arm["canonical_mutation"] is False


def test_fixed_windows_never_cross_session_and_units_are_atomic() -> None:
    turns = [
        _turn(index, "session-a" if index < 3 else "session-b") for index in range(5)
    ]
    result = build_representation_arms(turns)
    fixed = result.arms["B_FIXED_WINDOW_2"]

    assert [unit["turn_indexes"] for unit in fixed["units"]] == [
        [0, 1],
        [2],
        [3, 4],
    ]
    ranking = [turn["evidence_id"] for turn in turns]
    assert four_arm_effect._hydrate(fixed, ranking, 1) == []
    assert four_arm_effect._hydrate(fixed, ranking, 2) == ["unit-0", "unit-1"]


def test_repair_dev_closes_general_rules_without_opening_sealed_effect() -> None:
    result = evaluate_repair_dev(ROOT)
    metrics = result["metrics"]

    assert metrics["direct"]["semantic_pairwise_f1"] == 1.0
    assert metrics["direct"]["paired_macro_delta_vs_strongest_simple"] >= 0.05
    assert metrics["simple_read"]["paired_macro_delta_vs_strongest_simple"] >= 0.05
    assert metrics["simple_read"]["raw_fts_calls_per_probe"] == 1.0
    assert metrics["failure_distribution"] == {
        "over_split": [],
        "over_merge": [],
        "assistant_contamination": [],
        "time_gap_error": [],
        "topic_shift_error": [],
    }
    assert metrics["safety"] == {
        "raw_span_coverage": 1.0,
        "source_order_preservation": 1.0,
        "user_semantic_source_precision": 1.0,
        "artifact_lineage_closure": 1.0,
        "canonical_mutations": 0,
        "database_writes": 0,
        "database_calls": 0,
        "provider_calls": 0,
        "reader_calls": 0,
        "retrieval_calls": 0,
        "model_calls": 0,
        "formal_holdout_used": False,
        "product_feature_flags": "OFF",
        "deterministic_replay": 1.0,
    }


def test_builder_and_raw_fts_interfaces_cannot_receive_gold_labels() -> None:
    signature = inspect.signature(RawFtsAcquirer.rank)
    assert tuple(signature.parameters) == ("self", "query_text", "turns")

    runtime_source = (
        ROOT / "runtime/src/milai/application/memory_formation.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "conversation_id",
        "case_id",
        "gold",
        "expected_episodes",
        "required_support_evidence_ids",
        "distractor_evidence_ids",
    ):
        assert forbidden not in runtime_source.casefold()

    tree = ast.parse(
        (ROOT / "evals/mf02/four_arm_effect.py").read_text(encoding="utf-8")
    )
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported_modules.isdisjoint(
        {
            "milai.persistence",
            "milai.application.retrieval",
            "milai.application.chat",
            "milai.adapters",
        }
    )


def test_environment_witness_is_exact_and_cpu_only() -> None:
    assert environment_witness() == "WITNESS 4 16 0"


def _turn(index: int, session_id: str) -> dict[str, object]:
    return {
        "evidence_id": f"unit-{index}",
        "source_ref": f"memory://mf02/unit/{index}",
        "session_id": session_id,
        "speaker": "assistant" if index in {1, 4} else "user",
        "speaker_source": "STRUCTURED_TURN_METADATA",
        "observed_at": f"2026-08-01T08:0{index}:00+08:00",
        "content": f"Complete raw turn number {index}.",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
        "revoked_at": None,
    }


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
