from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.run_dg20_s3_disposition import DG20S3DispositionError, run


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_s3_disposition_is_zero_call_and_has_standard_layout(tmp_path: Path) -> None:
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    _write(s1, {"status": "PASS_S1_OFFICIAL_CHANNEL_ORACLE"})
    _write(
        s2,
        {
            "status": "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY",
            "hard_gate": {"passed": True},
            "metrics": {"missing_requirement_improved_case_count": 3},
            "residual_assist": "DISABLED_NOT_NEEDED",
            "acquisition_loss_ledger": {"sha256": "a" * 64},
        },
    )
    output = tmp_path / "run"
    receipt = run(
        run_id="s3-test",
        output_root=output,
        s1_receipt_path=s1,
        s2_receipt_path=s2,
    )
    expected = {
        "plan.json",
        "sealed-product-trace.json",
        "score.json",
        "receipt.json",
        "acquisition-loss-ledger.json",
    }
    assert {path.name for path in output.iterdir()} == expected
    assert receipt["residual_assist"] == "DISABLED_NOT_NEEDED"
    assert receipt["provider_calls"] == 0
    sealed_text = (output / "sealed-product-trace.json").read_text(encoding="utf-8")
    assert "final answer" not in sealed_text
    for key in ("plan", "sealed_product_trace", "score", "acquisition_loss_ledger"):
        artifact = Path(receipt[key]["path"])
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == receipt[key]["sha256"]


def test_s3_disposition_fails_closed_without_s2_threshold(tmp_path: Path) -> None:
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    _write(s1, {"status": "PASS_S1_OFFICIAL_CHANNEL_ORACLE"})
    _write(
        s2,
        {
            "status": "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY",
            "hard_gate": {"passed": True},
            "metrics": {"missing_requirement_improved_case_count": 1},
            "residual_assist": "DISABLED_NOT_NEEDED",
        },
    )
    with pytest.raises(DG20S3DispositionError, match="core threshold"):
        run(
            run_id="s3-test",
            output_root=tmp_path / "run",
            s1_receipt_path=s1,
            s2_receipt_path=s2,
        )
