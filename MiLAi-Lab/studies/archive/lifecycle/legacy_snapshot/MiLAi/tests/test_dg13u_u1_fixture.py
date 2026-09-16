from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from milai.domain import (
    EvidenceIngestRequest,
    EvidenceRevocationRequest,
    ProposalCreateRequest,
    ProposalReviewRequest,
)

from scripts import dg13u_u1_fixture as fixture


class _Writer:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_at = fail_at
        self.sequence = 0

    def _record(self, method: str, payload: Mapping[str, Any]) -> int:
        self.calls.append((method, dict(payload)))
        if self.fail_at == method:
            raise RuntimeError(f"synthetic {method} failure")
        self.sequence += 1
        return self.sequence

    def capture_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        sequence = self._record("capture_as_submitter", payload)
        return {
            "evidence_id": f"00000000-0000-0000-0000-{sequence:012d}",
            "outbox_id": f"outbox-evidence-{sequence}",
            "replayed": False,
        }

    def propose_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        sequence = self._record("propose_as_submitter", payload)
        return {
            "proposal_id": f"10000000-0000-0000-0000-{sequence:012d}",
            "replayed": False,
        }

    def review_as_steward(
        self, proposal_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        sequence = self._record(
            "review_as_steward", {"proposal_id": proposal_id, **payload}
        )
        result: dict[str, Any] = {
            "claim_id": f"20000000-0000-0000-0000-{sequence:012d}",
            "claim_version_id": f"30000000-0000-0000-0000-{sequence:012d}",
            "outbox_id": f"outbox-review-{sequence}",
            "replayed": False,
        }
        proposal_call = next(
            value
            for method, value in reversed(self.calls)
            if method == "propose_as_submitter"
        )
        if proposal_call["proposal"]["operation"] == "CONTRADICT":
            result["open_issue_id"] = f"40000000-0000-0000-0000-{sequence:012d}"
            result["claim_version_id"] = None
        return result

    def revoke_as_operator(
        self, evidence_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        sequence = self._record(
            "revoke_as_operator", {"evidence_id": evidence_id, **payload}
        )
        return {
            "deletion_request_id": f"deletion-{sequence}",
            "canonical_block_status": "APPLIED",
            "replayed": False,
        }


def test_exact_candidate_fixture_is_hard_validated_in_frozen_order() -> None:
    families = fixture.load_candidate_families()

    assert [family.state_key for family in families] == [
        "release.target",
        "release.database",
        "release.decision",
    ]
    assert [family.claim_type for family in families] == [
        "PROJECT_STATE",
        "PROJECT_CONFIG",
        "PROJECT_DECISION",
    ]
    assert all(family.project == "orchid-release" for family in families)
    assert fixture._sha256_file(fixture.CANDIDATE_FIXTURE) == fixture.CANDIDATE_SHA256


def test_candidate_fixture_drift_fails_before_any_writer_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drifted = tmp_path / "fixture.json"
    drifted.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(fixture, "CANDIDATE_FIXTURE", drifted)
    writer = _Writer()

    with pytest.raises(fixture.FixtureContractError, match="candidate fixture SHA-256"):
        fixture.seed_u1_canonical_fixture(
            writer,
            run_id="fixture-drift",
            observed_at="2026-08-25T23:30:00+08:00",
        )
    assert writer.calls == []


def test_positive_seed_uses_three_controlled_write_chains_and_redacted_receipt() -> (
    None
):
    writer = _Writer()
    receipt = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-positive",
        observed_at="2026-08-25T23:30:00+08:00",
    )

    assert [method for method, _payload in writer.calls] == [
        "capture_as_submitter",
        "propose_as_submitter",
        "review_as_steward",
    ] * 3
    assert receipt["status"] == "SEEDED"
    assert receipt["candidate_fixture_sha256"] == fixture.CANDIDATE_SHA256
    assert receipt["data_boundary"] == "SYNTHETIC"
    assert receipt["formal_evaluation_input"] is False
    assert receipt["writer_roles"] == ["submitter", "steward"]
    assert [item["state_key"] for item in receipt["families"]] == [
        "release.target",
        "release.database",
        "release.decision",
    ]
    assert all(len(item["payload_sha256"]) == 64 for item in receipt["families"])
    encoded = json.dumps(receipt, sort_keys=True)
    assert "tool reports" not in encoded
    assert "rc-2026.08-u1" not in encoded
    assert "postgresql-18-u1" not in encoded
    assert "proceed-after-governance-pass" not in encoded
    assert all(
        call[1].get("confirmation") in {"CAPTURE", "SUBMIT"}
        for call in writer.calls
        if call[0] != "review_as_steward"
    )
    create_proposals = [
        payload["proposal"]
        for method, payload in writer.calls
        if method == "propose_as_submitter"
    ]
    assert all(
        ProposalCreateRequest.model_validate(proposal) for proposal in create_proposals
    )
    assert all(
        EvidenceIngestRequest.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"operation_id", "confirmation"}
            }
        )
        for method, payload in writer.calls
        if method == "capture_as_submitter"
    )
    assert all(
        ProposalReviewRequest.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"operation_id", "proposal_id"}
            }
        )
        for method, payload in writer.calls
        if method == "review_as_steward"
    )
    assert all(
        proposal["requested_authority"] == "INFORMATIONAL"
        and proposal["proposed_patch"]["authority"] == "INFORMATIONAL"
        for proposal in create_proposals
    )


def test_optional_negative_setups_are_governed_and_typed() -> None:
    writer = _Writer()
    receipt = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-negatives",
        observed_at="2026-08-25T23:30:00+08:00",
        options=fixture.FixtureOptions(
            wrong_scope=True,
            open_issue=True,
            revoke=True,
            state_change=True,
        ),
    )

    methods = [method for method, _payload in writer.calls]
    assert methods.count("capture_as_submitter") == 6
    assert methods.count("propose_as_submitter") == 6
    assert methods.count("review_as_steward") == 6
    assert methods.count("revoke_as_operator") == 1
    assert set(receipt["negative_setups"]) == {
        "wrong_scope",
        "open_issue",
        "revoke",
        "state_change",
    }
    assert receipt["negative_setups"]["open_issue"]["open_issue_id"].startswith(
        "40000000-"
    )
    assert all(
        ProposalCreateRequest.model_validate(payload["proposal"])
        for method, payload in writer.calls
        if method == "propose_as_submitter"
    )
    assert all(
        EvidenceRevocationRequest.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"evidence_id", "operation_id"}
            }
        )
        for method, payload in writer.calls
        if method == "revoke_as_operator"
    )
    assert receipt["negative_setups"]["revoke"]["canonical_block_status"] == "APPLIED"
    assert (
        receipt["negative_setups"]["state_change"]["prior_claim_version_id"]
        != receipt["negative_setups"]["state_change"]["current_claim_version_id"]
    )
    assert receipt["writer_roles"] == ["submitter", "steward", "operator"]
    assert "reader" not in json.dumps(receipt, sort_keys=True).casefold()


def test_post_warm_state_change_returns_new_cleanup_complete_receipt() -> None:
    writer = _Writer()
    seeded = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-post-warm",
        observed_at="2026-08-25T23:30:00+08:00",
    )
    frozen_before = json.loads(json.dumps(seeded))
    calls_before = len(writer.calls)

    updated = fixture.apply_u1_state_change(
        writer,
        seeded,
        run_id="fixture-post-warm",
        observed_at="2026-08-25T23:31:00+08:00",
    )

    assert seeded == frozen_before
    assert [method for method, _payload in writer.calls[calls_before:]] == [
        "capture_as_submitter",
        "propose_as_submitter",
        "review_as_steward",
    ]
    change = updated["negative_setups"]["state_change"]
    assert change["prior_claim_version_id"] != change["current_claim_version_id"]
    assert len(updated["mutations"]) == len(seeded["mutations"]) + 3

    cleanup = fixture.cleanup_u1_canonical_fixture(
        writer,
        updated,
        run_id="fixture-post-warm",
    )
    assert cleanup["evidence_revocations"] == 4


def test_post_warm_state_change_rejects_replay_or_wrong_seed_identity_before_write() -> (
    None
):
    writer = _Writer()
    seeded = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-post-warm-negative",
        observed_at="2026-08-25T23:30:00+08:00",
    )
    updated = fixture.apply_u1_state_change(
        writer,
        seeded,
        run_id="fixture-post-warm-negative",
        observed_at="2026-08-25T23:31:00+08:00",
    )
    calls_before = len(writer.calls)

    with pytest.raises(
        fixture.FixtureContractError,
        match="STATE_CHANGE_SEEDED_RECEIPT_INVALID",
    ):
        fixture.apply_u1_state_change(
            writer,
            updated,
            run_id="fixture-post-warm-negative",
            observed_at="2026-08-25T23:32:00+08:00",
        )
    with pytest.raises(
        fixture.FixtureContractError,
        match="STATE_CHANGE_SEEDED_RECEIPT_INVALID",
    ):
        fixture.apply_u1_state_change(
            writer,
            seeded,
            run_id="fixture-post-warm-other",
            observed_at="2026-08-25T23:32:00+08:00",
        )
    assert len(writer.calls) == calls_before


def test_post_warm_state_change_failure_exposes_prior_and_new_partial_writes() -> None:
    writer = _Writer()
    seeded = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-post-warm-partial",
        observed_at="2026-08-25T23:30:00+08:00",
    )
    writer.fail_at = "propose_as_submitter"

    with pytest.raises(fixture.FixtureSeedError) as captured:
        fixture.apply_u1_state_change(
            writer,
            seeded,
            run_id="fixture-post-warm-partial",
            observed_at="2026-08-25T23:31:00+08:00",
        )

    partial = captured.value.partial_receipt
    assert partial["status"] == "PARTIAL"
    assert len(partial["mutations"]) == len(seeded["mutations"]) + 1
    assert partial["mutations"][-1]["kind"] == "EVIDENCE_CAPTURE"


def test_mid_chain_failure_exposes_only_redacted_partial_mutation_receipt() -> None:
    writer = _Writer(fail_at="propose_as_submitter")

    with pytest.raises(fixture.FixtureSeedError) as captured:
        fixture.seed_u1_canonical_fixture(
            writer,
            run_id="fixture-partial",
            observed_at="2026-08-25T23:30:00+08:00",
        )

    error = captured.value
    assert error.code == "PROPOSAL_CREATE_FAILED"
    assert error.partial_receipt["status"] == "PARTIAL"
    assert error.partial_receipt["mutations"] == [
        {
            "kind": "EVIDENCE_CAPTURE",
            "role": "submitter",
            "evidence_id": "00000000-0000-0000-0000-000000000001",
            "outbox_id": "outbox-evidence-1",
            "replayed": False,
        }
    ]
    assert "tool reports" not in json.dumps(error.partial_receipt, sort_keys=True)


def test_cleanup_revokes_every_live_seed_evidence_through_operator() -> None:
    writer = _Writer()
    seeded = fixture.seed_u1_canonical_fixture(
        writer,
        run_id="fixture-cleanup",
        observed_at="2026-08-25T23:30:00+08:00",
    )
    before = len(writer.calls)

    cleanup = fixture.cleanup_u1_canonical_fixture(
        writer, seeded, run_id="fixture-cleanup"
    )

    cleanup_calls = writer.calls[before:]
    assert [method for method, _payload in cleanup_calls] == [
        "revoke_as_operator",
        "revoke_as_operator",
        "revoke_as_operator",
    ]
    assert cleanup["status"] == "CLEANUP_REQUESTED"
    assert cleanup["canonical_claims_deleted"] is False
    assert cleanup["evidence_revocations"] == 3
    assert all(
        item["canonical_block_status"] == "APPLIED" for item in cleanup["receipts"]
    )
