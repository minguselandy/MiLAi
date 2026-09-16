from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any, Self

import pytest

from scripts.dg13u_u1_fixture import seed_u1_canonical_fixture
from scripts.dg13u_u1_runtime_writer import (
    LoopbackRuntimeFixtureWriter,
    RuntimeWriterContractError,
    RuntimeWriterError,
)

EVIDENCE_ID = "00000000-0000-4000-8000-000000000001"
PROPOSAL_ID = "00000000-0000-4000-8000-000000000002"
CLAIM_ID = "00000000-0000-4000-8000-000000000003"
VERSION_ID = "00000000-0000-4000-8000-000000000004"
OUTBOX_ID = "00000000-0000-4000-8000-000000000005"
DELETION_ID = "00000000-0000-4000-8000-000000000006"


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._raw = json.dumps(payload, separators=(",", ":")).encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._raw if amount < 0 else self._raw[:amount]


class _Opener:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, *, timeout: float) -> _Response:
        self.calls.append((request, timeout))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, _Response)
        return outcome


def _writer(opener: _Opener, **options: Any) -> LoopbackRuntimeFixtureWriter:
    return LoopbackRuntimeFixtureWriter(
        "http://127.0.0.1:18080",
        submitter_token="submitter-secret",
        reviewer_token="reviewer-secret",
        operator_token="operator-secret",
        opener=opener,
        **options,
    )


def _decoded(request: urllib.request.Request) -> dict[str, Any]:
    value = json.loads(request.data or b"null")
    assert isinstance(value, dict)
    return value


def _capture_payload(operation_id: str) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "confirmation": "CAPTURE",
        "source_type": "RUNTIME_OBSERVATION",
        "source_ref": "synthetic://source",
        "subject_id": "orchid-release",
        "observed_at": "2026-08-25T23:30:00+08:00",
        "content": "synthetic body",
        "data_classification": "SYNTHETIC",
        "permission_snapshot": {"readable": True},
        "retention_state": "READABLE",
    }


def _proposal_payload(operation_id: str) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "confirmation": "SUBMIT",
        "proposal": {
            "operation": "CREATE",
            "proposed_patch": {
                "subject_id": "orchid-release",
                "predicate": "release.target",
                "claim_type": "PROJECT_STATE",
                "payload": {"state_key": "release.target", "value": "synthetic"},
                "authority": "INFORMATIONAL",
                "confidence": 1.0,
            },
            "supporting_evidence_refs": [EVIDENCE_ID],
            "contradicting_evidence_refs": [],
            "scope_predicate": {"project_ids": ["orchid-release"]},
            "requested_authority": "INFORMATIONAL",
            "derivation_policy_id": "dg13u-u1-deterministic-fixture-v1",
            "model_id": "deterministic-synthetic-fixture",
            "template_id": "v1",
            "derivation_snapshot": {"input_snapshot_sha256": "a" * 64},
        },
    }


def test_four_methods_use_exact_paths_roles_keys_and_one_request_each() -> None:
    opener = _Opener(
        [
            _Response(201, {"evidence_id": EVIDENCE_ID, "outbox_id": OUTBOX_ID}),
            _Response(201, {"proposal_id": PROPOSAL_ID}),
            _Response(
                200,
                {
                    "claim_id": CLAIM_ID,
                    "claim_version_id": VERSION_ID,
                    "outbox_id": OUTBOX_ID,
                },
            ),
            _Response(
                202,
                {
                    "deletion_request_id": DELETION_ID,
                    "canonical_block_status": "APPLIED",
                },
            ),
        ]
    )
    writer = _writer(opener)

    assert (
        writer.capture_as_submitter(_capture_payload("fixture-evidence-1"))[
            "evidence_id"
        ]
        == EVIDENCE_ID
    )
    assert (
        writer.propose_as_submitter(_proposal_payload("fixture-proposal-1"))[
            "proposal_id"
        ]
        == PROPOSAL_ID
    )
    assert (
        writer.review_as_steward(
            PROPOSAL_ID,
            {
                "operation_id": "fixture-review-1",
                "decision": "APPROVE",
                "policy_version": "fixture-v1",
                "reason_code": "SYNTHETIC_FIXTURE",
            },
        )["claim_id"]
        == CLAIM_ID
    )
    assert (
        writer.revoke_as_operator(
            EVIDENCE_ID,
            {
                "operation_id": "fixture-revoke-1",
                "reason_code": "SOURCE_REMOVED",
                "confirmation": "REVOKE",
            },
        )["deletion_request_id"]
        == DELETION_ID
    )

    assert len(opener.calls) == 4
    requests = [request for request, _timeout in opener.calls]
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:18080/v1/evidence",
        "http://127.0.0.1:18080/v1/proposals",
        f"http://127.0.0.1:18080/v1/proposals/{PROPOSAL_ID}/review",
        f"http://127.0.0.1:18080/v1/evidence/{EVIDENCE_ID}/revoke",
    ]
    assert [request.get_header("Authorization") for request in requests] == [
        "Bearer submitter-secret",
        "Bearer submitter-secret",
        "Bearer reviewer-secret",
        "Bearer operator-secret",
    ]
    assert [request.get_header("Idempotency-key") for request in requests] == [
        "fixture-evidence-1",
        "fixture-proposal-1",
        "fixture-review-1",
        "fixture-revoke-1",
    ]
    assert [timeout for _request, timeout in opener.calls] == [5.0] * 4
    assert "operation_id" not in _decoded(requests[0])
    assert "confirmation" not in _decoded(requests[0])
    assert _decoded(requests[1]) == _proposal_payload("unused")["proposal"]
    assert _decoded(requests[2]) == {
        "decision": "APPROVE",
        "policy_version": "fixture-v1",
        "reason_code": "SYNTHETIC_FIXTURE",
    }
    assert _decoded(requests[3]) == {
        "reason_code": "SOURCE_REMOVED",
        "confirmation": "REVOKE",
    }


def test_fixture_seeder_needs_only_runtime_writer_instantiation() -> None:
    outcomes: list[object] = []
    for index in range(1, 4):
        evidence_id = f"00000000-0000-4000-8000-{index:012d}"
        proposal_id = f"10000000-0000-4000-8000-{index:012d}"
        outcomes.extend(
            [
                _Response(
                    201,
                    {
                        "evidence_id": evidence_id,
                        "outbox_id": f"20000000-0000-4000-8000-{index:012d}",
                    },
                ),
                _Response(201, {"proposal_id": proposal_id}),
                _Response(
                    200,
                    {
                        "claim_id": f"30000000-0000-4000-8000-{index:012d}",
                        "claim_version_id": f"40000000-0000-4000-8000-{index:012d}",
                        "outbox_id": f"50000000-0000-4000-8000-{index:012d}",
                    },
                ),
            ]
        )
    opener = _Opener(outcomes)

    receipt = seed_u1_canonical_fixture(
        _writer(opener),
        run_id="runtime-writer-composition",
        observed_at="2026-08-25T23:30:00+08:00",
    )

    assert receipt["status"] == "SEEDED"
    assert len(receipt["families"]) == 3
    assert len(opener.calls) == 9
    assert [
        request.get_header("Authorization") for request, _timeout in opener.calls
    ] == [
        "Bearer submitter-secret",
        "Bearer submitter-secret",
        "Bearer reviewer-secret",
    ] * 3


def test_http_error_is_typed_one_attempt_and_does_not_leak_token_or_body() -> None:
    raw = b'{"error":{"code":"VERSION_CONFLICT","message":"private body"}}'
    error = urllib.error.HTTPError(
        "http://127.0.0.1:18080/v1/proposals",
        409,
        "Conflict",
        {},
        io.BytesIO(raw),
    )
    opener = _Opener([error])
    writer = _writer(opener)

    with pytest.raises(RuntimeWriterError) as captured:
        writer.propose_as_submitter(_proposal_payload("fixture-proposal-conflict"))

    failure = captured.value
    assert failure.code == "RUNTIME_HTTP_ERROR"
    assert failure.http_status == 409
    assert failure.runtime_error_code == "VERSION_CONFLICT"
    assert failure.attempt_count == 1
    assert len(opener.calls) == 1
    encoded = repr(failure) + str(failure)
    assert "submitter-secret" not in encoded
    assert "private body" not in encoded


def test_transport_error_has_no_retry_and_no_secret_leak() -> None:
    opener = _Opener([urllib.error.URLError("synthetic transport failure")])
    writer = _writer(opener)

    with pytest.raises(RuntimeWriterError) as captured:
        writer.capture_as_submitter(_capture_payload("fixture-evidence-down"))

    assert captured.value.code == "RUNTIME_TRANSPORT_ERROR"
    assert captured.value.attempt_count == 1
    assert len(opener.calls) == 1
    encoded = repr(captured.value) + str(captured.value)
    assert "submitter-secret" not in encoded
    assert "private body" not in encoded


def test_response_size_and_json_shape_are_bounded_without_retry() -> None:
    too_large = _Opener([_Response(201, {"value": "x" * 200})])
    writer = _writer(too_large, max_response_bytes=64)
    with pytest.raises(RuntimeWriterError, match="RUNTIME_RESPONSE_TOO_LARGE"):
        writer.capture_as_submitter(_capture_payload("fixture-large"))
    assert len(too_large.calls) == 1

    malformed = _Opener([_Response(201, ["not", "an", "object"])])
    writer = _writer(malformed)
    with pytest.raises(RuntimeWriterError, match="RUNTIME_RESPONSE_INVALID"):
        writer.capture_as_submitter(_capture_payload("fixture-invalid"))
    assert len(malformed.calls) == 1


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:18080",
        "http://runtime.internal:18080",
        "http://127.0.0.1:18080/path",
        "http://user:password@127.0.0.1:18080",
    ],
)
def test_non_exact_loopback_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(RuntimeWriterContractError, match="LOOPBACK_BASE_URL_INVALID"):
        LoopbackRuntimeFixtureWriter(
            base_url,
            submitter_token="submitter-secret",
            reviewer_token="reviewer-secret",
            operator_token="operator-secret",
            opener=_Opener([]),
        )


def test_invalid_confirmation_or_operation_id_fails_before_http() -> None:
    opener = _Opener([])
    writer = _writer(opener)

    with pytest.raises(
        RuntimeWriterContractError, match="CAPTURE_CONFIRMATION_INVALID"
    ):
        writer.capture_as_submitter(
            {"operation_id": "fixture-invalid-confirmation", "confirmation": "SUBMIT"}
        )
    with pytest.raises(RuntimeWriterContractError, match="OPERATION_ID_INVALID"):
        writer.propose_as_submitter(
            {"operation_id": "contains whitespace", "confirmation": "SUBMIT"}
        )
    with pytest.raises(RuntimeWriterContractError, match="PROPOSAL_ID_INVALID"):
        writer.review_as_steward(
            "p-1",
            {
                "operation_id": "fixture-review-invalid-id",
                "decision": "APPROVE",
                "policy_version": "fixture-v1",
                "reason_code": "SYNTHETIC_FIXTURE",
            },
        )
    with pytest.raises(RuntimeWriterContractError, match="EVIDENCE_ID_INVALID"):
        writer.revoke_as_operator(
            "e-1",
            {
                "operation_id": "fixture-revoke-invalid-id",
                "reason_code": "SOURCE_REMOVED",
                "confirmation": "REVOKE",
            },
        )
    with pytest.raises(RuntimeWriterContractError, match="CAPTURE_BODY_INVALID"):
        writer.capture_as_submitter(
            {"operation_id": "fixture-invalid-body", "confirmation": "CAPTURE"}
        )
    assert opener.calls == []
