from __future__ import annotations

from pathlib import Path

from scripts.run_md01_memory_formation import OUTPUT_DIR, validate


def test_md01_terminal_artifacts_are_digest_linked_and_complete() -> None:
    result = validate()

    assert result["valid"] is True
    assert result["status"] == "PASS_MD01_MEMORY_FORMATION_CORE"
    assert result["metrics"]["raw_span_coverage"] == 1.0
    assert result["metrics"]["episode_boundary_precision"] == 1.0
    assert result["metrics"]["episode_boundary_recall"] == 1.0
    assert result["metrics"]["episode_pairwise_f1"] == 1.0
    assert result["metrics"]["user_semantic_source_precision"] == 1.0
    assert result["metrics"]["artifact_lineage_closure"] == 1.0
    assert result["metrics"]["deterministic_replay"] == 1.0


def test_md01_effect_keeps_only_the_four_authorized_major_artifacts() -> None:
    artifacts = {path.name for path in Path(OUTPUT_DIR).iterdir() if path.is_file()}

    assert artifacts == {
        "run-lock.json",
        "results.json",
        "terminal.json",
        "receipt.json",
    }
