from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-2026-08-22.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_disposition_binds_local_receipts() -> None:
    report = _report()
    receipts = report["bound_receipts"]
    assert isinstance(receipts, dict)
    for receipt in receipts.values():
        assert isinstance(receipt, dict)
        if "path" not in receipt:
            continue
        path = ROOT / str(receipt["path"])
        assert path.is_file()
        assert _sha256(path) == receipt["sha256"]


def test_every_sol_finding_is_disposed_once() -> None:
    report = _report()
    findings = report["finding_dispositions"]
    assert isinstance(findings, list)
    ids = [finding["id"] for finding in findings]
    assert ids == [f"DG10-SOL-{number:03d}" for number in range(1, 15)]
    assert len(set(ids)) == 14


def test_open_p1_forces_crg02_no_go() -> None:
    report = _report()
    replay = report["mechanical_replay"]
    decision = report["controlled_decision"]
    gates = report["gate_results"]
    assert isinstance(replay, dict)
    assert isinstance(decision, dict)
    assert isinstance(gates, dict)
    assert replay["open_p0_count"] == 0
    assert replay["open_p1_count"] == 2
    assert gates["CRG-02"].startswith("NO_GO")
    assert decision["aggregate_claim_allowed"] is False
    assert decision["run_full_test"] is False
    assert decision["acceptance_authorized"] is False


def test_codex_cost_is_not_inferred_as_zero() -> None:
    report = _report()
    replay = report["substantive_replay"]
    assert isinstance(replay, dict)
    accounting = replay["codex_review_accounting"]
    assert accounting["provider_threads"] == 1
    assert accounting["billing_cost"] == "UNAVAILABLE"
    assert accounting[
        "import_receipt_provider_cost_zero_must_not_be_read_as_codex_billing_evidence"
    ] is True
