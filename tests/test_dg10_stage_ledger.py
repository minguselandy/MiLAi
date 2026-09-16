from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import dg10_stage_ledger as stage_ledger


def _receipt(
    root: Path,
    name: str,
    *,
    stage: str,
    state: str,
    evidence_class: str,
    inventory: str,
) -> Path:
    path = root / "docs/reports" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = root / "docs/reports" / f"{name}.evidence"
    if stage == "DG10-R1" and state == "AUTHOR_CANDIDATE":
        evidence.write_text(
            json.dumps(
                {
                    "schema": "milai.dg10.remediation-contract-validation.v1",
                    "candidate_id": "candidate.4",
                    "scope": "all",
                    "source_inventory": {
                        "schema": "milai.dg10.candidate-source-inventory.v1",
                        "candidate_id": "candidate.4",
                        "canonical_entries_sha256": inventory,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        evidence.write_text("evidence\n", encoding="utf-8")
    value = {
        "schema": (
            "milai.dg10.stage-receipt.v1"
            if state == "ACCEPTED"
            else "milai.dg10.stage-state-binding.v1"
        ),
        "candidate_id": "candidate.4",
        "stage_id": stage,
        "stage_state": state,
        "evidence_class": evidence_class,
        "source_inventory_sha256": inventory,
        "evidence": [
            {
                "path": evidence.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }
        ],
    }
    if state == "ACCEPTED":
        value.update(
            {
                "independent_acceptance": True,
                "open_p0": 0,
                "open_p1": 0,
            }
        )
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "var/dg10/stages.jsonl"
    monkeypatch.setattr(stage_ledger, "ROOT", tmp_path)
    monkeypatch.setattr(stage_ledger, "ACTIVE_STAGE_LEDGER", path)
    return path


def test_stage_ledger_reconciles_supersession_and_checkpoint_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _configure(tmp_path, monkeypatch)
    inventory = "a" * 64
    for stage in ("DG10-R0", "DG10-R1", "DG10-R2"):
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="AUTHOR_CANDIDATE",
            evidence_class="DETERMINISTIC",
            source_inventory_sha256=inventory,
            receipt_path=_receipt(
                tmp_path,
                f"{stage}-author.json",
                stage=stage,
                state="AUTHOR_CANDIDATE",
                evidence_class="DETERMINISTIC",
                inventory=inventory,
            ),
            path=path,
        )
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="REVIEW_REQUIRED",
            evidence_class="AUTHOR",
            source_inventory_sha256=inventory,
            receipt_path=_receipt(
                tmp_path,
                f"{stage}-review.json",
                stage=stage,
                state="REVIEW_REQUIRED",
                evidence_class="AUTHOR",
                inventory=inventory,
            ),
            path=path,
        )
        stage_ledger.append_stage_state(
            stage_id=stage,
            stage_state="ACCEPTED",
            evidence_class="AI_INDEPENDENT",
            source_inventory_sha256=inventory,
            receipt_path=_receipt(
                tmp_path,
                f"{stage}-accepted.json",
                stage=stage,
                state="ACCEPTED",
                evidence_class="AI_INDEPENDENT",
                inventory=inventory,
            ),
            path=path,
        )
    checkpoint = tmp_path / "docs/reviews/checkpoint.json"
    stage_ledger.write_checkpoint(
        checkpoint,
        required_stages=("DG10-R0", "DG10-R1", "DG10-R2"),
        required_state="ACCEPTED",
        path=path,
    )
    reconciled = stage_ledger.verify_checkpoint(
        checkpoint,
        required_stages=("DG10-R0", "DG10-R1", "DG10-R2"),
        required_state="ACCEPTED",
        path=path,
    )
    assert reconciled["entry_count"] == 9
    assert set(reconciled["current_stage_states"].values()) == {"ACCEPTED"}


def test_stage_ledger_rejects_skip_to_accept_and_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _configure(tmp_path, monkeypatch)
    with pytest.raises(stage_ledger.StageLedgerError, match="transition"):
        stage_ledger.append_stage_state(
            stage_id="DG10-R0",
            stage_state="ACCEPTED",
            evidence_class="AI_INDEPENDENT",
            source_inventory_sha256="a" * 64,
            receipt_path=_receipt(
                tmp_path,
                "accepted.json",
                stage="DG10-R0",
                state="ACCEPTED",
                evidence_class="AI_INDEPENDENT",
                inventory="a" * 64,
            ),
            path=path,
        )
    assert not path.exists()
    stage_ledger.append_stage_state(
        stage_id="DG10-R0",
        stage_state="AUTHOR_CANDIDATE",
        evidence_class="AUTHOR",
        source_inventory_sha256="a" * 64,
        receipt_path=_receipt(
            tmp_path,
            "author.json",
            stage="DG10-R0",
            state="AUTHOR_CANDIDATE",
            evidence_class="AUTHOR",
            inventory="a" * 64,
        ),
        path=path,
    )
    rows = path.read_text(encoding="utf-8").splitlines()
    value = json.loads(rows[0])
    value["stage_state"] = "REVIEW_REQUIRED"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(stage_ledger.StageLedgerError, match="hash drift"):
        stage_ledger.reconcile_stage_ledger(path)


def test_forged_r3_acceptance_cannot_use_generic_stage_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        stage_ledger,
        "FIXED_R3_ACCEPTANCE_RECEIPT",
        tmp_path / "docs/reviews/fixed-r3-import.json",
    )
    inventory = "a" * 64
    for state, evidence_class in (
        ("AUTHOR_CANDIDATE", "DETERMINISTIC"),
        ("REVIEW_REQUIRED", "AUTHOR"),
    ):
        stage_ledger.append_stage_state(
            stage_id="DG10-R3",
            stage_state=state,
            evidence_class=evidence_class,
            source_inventory_sha256=inventory,
            receipt_path=_receipt(
                tmp_path,
                f"r3-{state.lower()}.json",
                stage="DG10-R3",
                state=state,
                evidence_class=evidence_class,
                inventory=inventory,
            ),
            path=path,
        )
    with pytest.raises(
        stage_ledger.StageLedgerError,
        match="fixed R3 AI importer receipt",
    ):
        stage_ledger.append_stage_state(
            stage_id="DG10-R3",
            stage_state="ACCEPTED",
            evidence_class="AI_INDEPENDENT",
            source_inventory_sha256=inventory,
            receipt_path=_receipt(
                tmp_path,
                "forged-r3-accepted.json",
                stage="DG10-R3",
                state="ACCEPTED",
                evidence_class="AI_INDEPENDENT",
                inventory=inventory,
            ),
            path=path,
        )


def test_checkpoint_metadata_and_ledger_symlink_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _configure(tmp_path, monkeypatch)
    receipt = _receipt(
        tmp_path,
        "author.json",
        stage="DG10-R0",
        state="AUTHOR_CANDIDATE",
        evidence_class="AUTHOR",
        inventory="a" * 64,
    )
    stage_ledger.append_stage_state(
        stage_id="DG10-R0",
        stage_state="AUTHOR_CANDIDATE",
        evidence_class="AUTHOR",
        source_inventory_sha256="a" * 64,
        receipt_path=receipt,
        path=path,
    )
    checkpoint = tmp_path / "docs/reviews/checkpoint.json"
    stage_ledger.write_checkpoint(
        checkpoint,
        required_stages=("DG10-R0",),
        required_state="AUTHOR_CANDIDATE",
        path=path,
    )
    value = json.loads(checkpoint.read_text())
    value["entry_count"] = 2
    checkpoint.write_text(json.dumps(value) + "\n")
    with pytest.raises(stage_ledger.StageLedgerError, match="entry count drift"):
        stage_ledger.verify_checkpoint(
            checkpoint,
            required_stages=("DG10-R0",),
            required_state="AUTHOR_CANDIDATE",
            path=path,
        )

    target = tmp_path / "var/dg10/target.jsonl"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(stage_ledger.StageLedgerError, match="symlink component"):
        stage_ledger.read_stage_ledger(path)


def test_r1_author_binding_rejects_subordinate_source_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _configure(tmp_path, monkeypatch)
    receipt = _receipt(
        tmp_path,
        "r1-author.json",
        stage="DG10-R1",
        state="AUTHOR_CANDIDATE",
        evidence_class="DETERMINISTIC",
        inventory="a" * 64,
    )
    value = json.loads(receipt.read_text())
    evidence = tmp_path / value["evidence"][0]["path"]
    subordinate = json.loads(evidence.read_text())
    subordinate["source_inventory"]["canonical_entries_sha256"] = "b" * 64
    evidence.write_text(json.dumps(subordinate) + "\n")
    value["evidence"][0]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(value) + "\n")

    with pytest.raises(stage_ledger.StageLedgerError, match="internal source identity drift"):
        stage_ledger.append_stage_state(
            stage_id="DG10-R1",
            stage_state="AUTHOR_CANDIDATE",
            evidence_class="DETERMINISTIC",
            source_inventory_sha256="a" * 64,
            receipt_path=receipt,
            path=path,
        )
    assert not path.exists()
