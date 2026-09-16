from __future__ import annotations

from pathlib import Path

from scripts.run_mf02_semantic_episode import LEGAL_STATUSES, OUTPUT_DIR, validate


def test_mf02_terminal_artifacts_are_digest_linked_and_protocol_complete() -> None:
    result = validate()

    assert result["valid"] is True
    assert result["status"] in LEGAL_STATUSES
    assert result["safety"]["raw_span_coverage"] == 1.0
    assert result["safety"]["source_order_preservation"] == 1.0
    assert result["safety"]["user_semantic_source_precision"] == 1.0
    assert result["safety"]["artifact_lineage_closure"] == 1.0
    assert result["safety"]["canonical_mutations"] == 0
    assert result["safety"]["database_writes"] == 0
    assert result["safety"]["provider_calls"] == 0
    assert result["safety"]["reader_calls"] == 0
    assert result["safety"]["model_calls"] == 0
    assert result["safety"]["formal_holdout_used"] is False


def test_mf02_effect_keeps_only_the_four_authorized_major_artifacts() -> None:
    artifacts = {path.name for path in Path(OUTPUT_DIR).iterdir() if path.is_file()}

    assert artifacts == {
        "run-lock.json",
        "results.json",
        "terminal.json",
        "receipt.json",
    }
