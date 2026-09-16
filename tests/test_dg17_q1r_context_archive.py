from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from evals.dg17.q1r_causality import POLICIES, canonical_sha256
from evals.dg17.q1r_context_archive import (
    Q1RContextArchiveError,
    build_context_record,
    build_evidence_snapshot,
    seal_context_archive,
)

CASE_ID = "case-one"


def _body() -> dict[str, object]:
    context = (
        "memory_status=HIT\n"
        "authority_class=EVIDENCE_ONLY\n"
        "sufficiency_status=COMPLETE\n"
        "[E1 EVIDENCE WINDOW speaker=USER observed_at=2026-08-27]\n"
        "user: tea"
    )
    reader_digest = hashlib.sha256(context.encode()).hexdigest()
    semantic_digest = canonical_sha256({"semantic": "tea"})
    mapping = [
        {
            "alias": "E1",
            "evidence_ids": ["evidence-one"],
            "source_turn_refs": ["memory://case-one/turn/0"],
            "claim_versions": [],
            "issue_revisions": [],
        }
    ]
    return {
        "status": "HIT",
        "trace_id": "trace-one",
        "memory_query_ir": {"requirements": [{"slot_id": "LOOKUP_ANSWER"}]},
        "sufficiency_decision": {
            "status": "COMPLETE",
            "covered_slots": ["LOOKUP_ANSWER"],
            "missing_slots": [],
        },
        "derived_result": None,
        "progressive_l1": {
            "acquisition_plan": {
                "schema_version": "acquisition-plan-v0.1",
                "query_ir_digest": "a" * 64,
            },
            "acquisition_probe_dispositions": [
                {
                    "probe_id": "global:fts-raw",
                    "requirement_slot": None,
                    "channel": "FTS_RAW",
                    "status": "EXECUTED",
                    "candidate_count": 1,
                    "candidate_limit": 10,
                }
            ],
            "candidate_counts": {"evidence_fts": 1, "evidence_slot_union": 1},
        },
        "memory_context": {
            "text": context,
            "reader_context_digest": reader_digest,
            "semantic_context_digest": semantic_digest,
            "estimated_tokens": 48,
            "authority_class": "EVIDENCE_ONLY",
            "selected_source_turn_refs": ["memory://case-one/turn/0"],
            "context_truncated": False,
            "windows": [
                {
                    "text": "user: tea",
                    "speakers": ["USER"],
                    "observed_at": "2026-08-27T00:00:00+00:00",
                    "requirement_priority": True,
                }
            ],
        },
        "context_receipt": {
            "reader_context_digest": reader_digest,
            "semantic_context_digest": semantic_digest,
            "receipt_mapping": mapping,
            "canonical_mutation": False,
        },
        "access_trace": {
            "terminal_stage": "EVIDENCE_FTS",
            "attempted_stages": ["EVIDENCE_FTS"],
            "stop_reason": "REQUIREMENT_SATISFIED",
            "spans": {"runtime_kernel_ms": 7.5},
            "structural_cost": {"embedding_calls": 0},
        },
    }


def _snapshot() -> dict[str, object]:
    return build_evidence_snapshot(
        case_id=CASE_ID,
        events=[
            {
                "event_id": "event-one",
                "case_id": CASE_ID,
                "session_ordinal": 0,
                "original_session_id": "session-one",
                "turn_ordinal": 0,
                "role": "user",
                "content": "tea",
                "observed_at": "2026-08-27T00:00:00+00:00",
            }
        ],
        governance_receipts=[
            {
                "event_id": "event-one",
                "evidence_id": "evidence-one",
                "source_ref": "memory://case-one/turn/0",
                "outbox_id": "outbox-one",
                "canonical_changed": False,
            }
        ],
        runtime_snapshot={
            "schema_version": "runtime-evidence-snapshot-v0.1",
            "projection_state": {"evidence_watermark": 1},
            "start_end_projection_identity_equal": True,
            "capture_mode": "ONE_RETRIEVAL_EXECUTION_PREFIX_REPLAY",
        },
    )


def test_q1r_context_builder_seals_complete_same_snapshot_denominator() -> None:
    snapshot = _snapshot()
    digest = canonical_sha256(snapshot)
    records = [
        build_context_record(
            case_id=CASE_ID,
            token_budget=budget,
            policy=policy,
            execution_body=_body(),
            evidence_snapshot_digest=digest,
            policy_metadata={
                "shared_execution": {
                    "retrieval_execution_count": 1,
                    "evidence_snapshot_digest": canonical_sha256(
                        snapshot["runtime_snapshot"]
                    ),
                }
            },
        )
        for budget in (512, 2048)
        for policy in POLICIES
    ]

    archive = seal_context_archive(
        run_id="q1r-context-test",
        selection={"source_ids": [CASE_ID]},
        snapshots=[snapshot],
        records=records,
    )

    assert archive["record_count"] == 4
    assert archive["label_fields_available"] is False
    assert archive["historical_answer_reuse"] is False
    assert archive["snapshots"][0]["evidence_snapshot_digest"] == digest
    assert {
        (record["token_budget"], record["policy"])
        for record in archive["records"]
    } == {(budget, policy) for budget in (512, 2048) for policy in POLICIES}
    assert all(
        record["context_identity"]["receipt_mapping"][0]["alias"] == "E1"
        for record in archive["records"]
    )
    assert all(
        record["semantic_mediators"]["acquisition_trace"]["plan"]["schema_version"]
        == "acquisition-plan-v0.1"
        for record in archive["records"]
    )


def test_q1r_context_builder_rejects_missing_alias_mapping() -> None:
    body = deepcopy(_body())
    receipt = body["context_receipt"]
    assert isinstance(receipt, dict)
    receipt["receipt_mapping"] = []

    with pytest.raises(Q1RContextArchiveError, match="alias mapping is empty"):
        build_context_record(
            case_id=CASE_ID,
            token_budget=512,
            policy=POLICIES[0],
            execution_body=body,
            evidence_snapshot_digest="a" * 64,
            policy_metadata={},
        )


def test_q1r_evidence_snapshot_rejects_canonical_promotion() -> None:
    with pytest.raises(Q1RContextArchiveError, match="canonical truth"):
        build_evidence_snapshot(
            case_id=CASE_ID,
            events=[{"event_id": "event-one", "case_id": CASE_ID}],
            governance_receipts=[
                {
                    "event_id": "event-one",
                    "evidence_id": "evidence-one",
                    "source_ref": "memory://case-one/turn/0",
                    "outbox_id": "outbox-one",
                    "canonical_changed": True,
                }
            ],
            runtime_snapshot={},
        )
