from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evals.md01.formation_bundle_effect import execute_md01_effect

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals/md01/fixtures/contrasting-episodes.v0.1.json"
RUN_LOCK = ROOT / "var/md01/md01-memory-formation-bundle-20260830-001/run-lock.json"


def test_contrasting_labels_are_sealed_before_effect() -> None:
    fixture = _object(FIXTURE)
    run_lock = _object(RUN_LOCK)

    assert len(fixture["conversations"]) == 10
    assert run_lock["fixture"]["conversation_count"] == 10
    assert run_lock["fixture"]["turn_count"] == 35
    assert run_lock["fixture"]["episode_count"] == 16
    assert (
        run_lock["fixture"]["sha256"]
        == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )
    reasons = {
        episode["boundary_reason"]
        for conversation in fixture["conversations"]
        for episode in conversation["expected_episodes"]
    }
    assert reasons == {
        "CONVERSATION_START",
        "EXPLICIT_TOPIC_SHIFT",
        "SEMANTIC_TOPIC_SHIFT",
        "SESSION_CHANGE",
        "TIME_GAP",
    }


def test_md01_effect_passes_all_preregistered_direct_metrics() -> None:
    result = execute_md01_effect(ROOT)

    assert result["status"] == "PASS_MD01_MEMORY_FORMATION_CORE_PENDING_REGRESSION"
    assert result["metrics"]["raw_span_coverage"] == 1.0
    assert result["metrics"]["episode_boundary_precision"] == 1.0
    assert result["metrics"]["episode_boundary_recall"] == 1.0
    assert result["metrics"]["episode_pairwise_f1"] == 1.0
    assert result["metrics"]["episode_boundary_reason_accuracy"] == 1.0
    assert result["metrics"]["user_semantic_source_precision"] == 1.0
    assert result["metrics"]["artifact_lineage_closure"] == 1.0
    assert result["metrics"]["deterministic_replay"] == 1.0
    assert result["metrics"]["boundary_counts"] == {
        "true_positive": 6,
        "false_positive": 0,
        "false_negative": 0,
    }
    assert result["metrics"]["raw_char_counts"] == {
        "covered": 1457,
        "total": 1457,
    }
    assert result["metrics"]["artifact_lineage_counts"] == {
        "closed": 31,
        "total": 31,
    }
    assert result["safety"] == {
        "raw_fallback_required": True,
        "provider_calls": 0,
        "reader_calls": 0,
        "retrieval_calls": 0,
        "database_calls": 0,
        "canonical_mutations": 0,
    }
    assert all(result["checks"].values())


def test_runtime_builder_has_no_fixture_or_gold_identity_dependency() -> None:
    source = (ROOT / "runtime/src/milai/application/memory_formation.py").read_text(
        encoding="utf-8"
    )

    assert "expected_episodes" not in source
    assert "conversation_id" not in source
    assert "case_id" not in source
    assert "gold" not in source.casefold()


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
