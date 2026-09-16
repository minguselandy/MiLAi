from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from scripts import build_dg18_r0_baseline as r0


def test_authoritative_receipt_preserves_predevelopment_baseline() -> None:
    receipt_path = (
        r0.ROOT
        / "var/dg18/r0/dg18-r0-baseline-freeze-20260828-001/receipt.json"
    )
    receipt = cast(dict[str, Any], json.loads(receipt_path.read_bytes()))

    assert receipt["status"] == "PASS"
    assert receipt["verified_artifact_count"] == 33
    assert receipt["gates"] == {
        "all_bound_paths_and_digests_match": True,
        "all_expected_receipt_schemas_and_statuses_match": True,
        "historical_failure_lineage_preserved": True,
        "opened_dev_case_identity_matches": True,
        "formal_source_id_overlap_zero": True,
        "formal_holdout_consumption_markers_absent": True,
        "a6_dense_default_disabled": True,
        "a6_product_default_unchanged": True,
        "ownership_and_successor_mapping_frozen": True,
    }
    assert receipt["execution"] == {
        "automatic_retries": 0,
        "external_model_calls": 0,
        "provider_calls": 0,
        "database_started": False,
        "runtime_started": False,
        "formal_holdout_consumed": False,
    }
    assert receipt["current_identity"]["provider"]["current_live_verified"] is False
    assert (
        receipt["current_identity"]["provider"]["evidence_strength"]
        == "LAST_EXECUTED_FROZEN_CONTRACT"
    )


def test_predevelopment_baseline_is_not_rewritten_after_authorized_target_drift(
    tmp_path: Path,
) -> None:
    with pytest.raises(r0.DG18R0BaselineError, match="sha256 mismatch for dg18_goal"):
        r0.build_receipt(run_id="dg18-r0-test", output_root=tmp_path / "receipt")


def test_manifest_byte_tampering_is_rejected(tmp_path: Path) -> None:
    manifest = cast(dict[str, Any], json.loads(r0.MANIFEST_PATH.read_bytes()))
    manifest["status"] = "PASS"
    tampered = tmp_path / "manifest.json"
    tampered.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(r0.DG18R0BaselineError, match="manifest digest mismatch"):
        r0.validate_manifest(manifest_path=tampered)


def test_dense_default_must_remain_explicitly_disabled(tmp_path: Path) -> None:
    enabled = tmp_path / "settings.py"
    enabled.write_text(
        "retrieval_evidence_dense_enabled: bool = True\n",
        encoding="utf-8",
    )

    with pytest.raises(r0.DG18R0BaselineError, match="not explicitly disabled"):
        r0._validate_dense_default(enabled)


def test_existing_output_directory_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(r0.DG18R0BaselineError, match="fresh run ID"):
        r0.build_receipt(run_id="duplicate", output_root=output)


def test_formal_holdout_consumption_markers_are_absent() -> None:
    manifest = cast(dict[str, Any], json.loads(r0.MANIFEST_PATH.read_bytes()))
    markers = manifest["holdout_boundary"]["consumption_markers_required_absent"]

    assert markers == [
        "var/dg11/splits/v1/paper-test-v1/consumption.json",
        "var/dg11/splits/v1/generalization-v2/consumption.json",
    ]
    assert all(not (r0.ROOT / marker).exists() for marker in markers)
