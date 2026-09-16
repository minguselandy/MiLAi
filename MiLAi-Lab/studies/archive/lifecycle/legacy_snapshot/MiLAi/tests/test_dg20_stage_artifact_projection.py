from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.project_dg20_stage_artifacts import (
    DG20ArtifactProjectionError,
    project_stage,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "s1": ROOT / "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003",
    "s4": ROOT / "var/dg20/s4/dg20-s4-product-faithful-20260828-002",
}


@pytest.mark.parametrize("stage", ["s1", "s4"])
def test_projection_has_standard_layout_and_one_loss_per_requirement(
    tmp_path: Path, stage: str
) -> None:
    output = tmp_path / stage
    receipt = project_stage(
        stage=stage,
        run_id=f"{stage}-projection-test",
        source=SOURCES[stage],
        output=output,
    )
    assert {path.name for path in output.iterdir()} == {
        "plan.json",
        "sealed-product-trace.json",
        "score.json",
        "receipt.json",
        "acquisition-loss-ledger.json",
    }
    assert receipt["byte_identical_seal"] is True
    assert receipt["byte_identical_score"] is True
    ledger = json.loads((output / "acquisition-loss-ledger.json").read_text())
    keys = [(item["case_id"], item["requirement_id"]) for item in ledger["records"]]
    assert keys
    assert len(keys) == len(set(keys))
    assert all(item["first_loss_stage"] for item in ledger["records"])
    for key in ("plan", "sealed_product_trace", "score", "acquisition_loss_ledger"):
        path = Path(receipt[key]["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt[key]["sha256"]


def test_projection_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "s1"
    output.mkdir()
    with pytest.raises(DG20ArtifactProjectionError, match="output exists"):
        project_stage(
            stage="s1",
            run_id="s1-projection-test",
            source=SOURCES["s1"],
            output=output,
        )
