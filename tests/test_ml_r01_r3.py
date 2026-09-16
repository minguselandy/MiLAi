from __future__ import annotations

import json
from pathlib import Path

from evals.ml_repair.mlr01_r3 import build_r3_report, run_r3


def test_r3_progressive_boundary_passes_every_preregistered_gate() -> None:
    report = build_r3_report()

    assert report["status"] == "PASS"
    assert all(report["gates"].values())
    metrics = report["metrics"]
    assert metrics["AcceptedEvidenceIdentityIntegrity"] == 1.0
    assert metrics["ReaderEvidenceSubsetIntegrity"] == 1.0
    assert (
        metrics["ordinary_ContextEvidenceRecall_progressive"]
        >= metrics["ordinary_ContextEvidenceRecall_historical"]
    )
    assert metrics["StrictAcceptedBindingTotal"] > 0
    assert metrics["StrictAcceptedBindingPrecision"] == 1.0
    assert metrics["WrongCOMPLETE"] == 0
    assert metrics["CorrectCaseRegression"] == 0
    assert metrics["ReaderGroundingViolation"] == 0


def test_r3_report_is_written_as_the_exact_computed_report(tmp_path: Path) -> None:
    output = tmp_path / "r3.json"

    report = run_r3(output)

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert report["scope"]["benchmark_labels_opened"] is False
    assert report["scope"]["product_default_enablement"] is False
