from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation
from scripts import dg10_t2_provider_adapter as provider_adapter

ACTIVE_BOOTSTRAP_AUTHORIZATION = remediation.ROOT / (
    "docs/reports/DG-10-model-run-authorization-candidate.4-2026-08-22.json"
)
ACTIVE_BOOTSTRAP_LEDGER = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/attempts.jsonl"
)
ACTIVE_BOOTSTRAP_FAILURE_LATCH = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/failure-latch.json"
)
ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/execution-capability.json"
)
ACTIVE_BOOTSTRAP_REQUEST_ROOT = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/provider-requests"
)
ACTIVE_BOOTSTRAP_CLAIM_ROOT = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/provider-claims"
)
ACTIVE_BOOTSTRAP_RAW_ROOT = remediation.ROOT / (
    "var/dg10/t2-bootstrap-candidate.4/raw-sidecars"
)


class BootstrapExecutionError(remediation.RemediationError):
    pass


def _safe_active_path(path: Path, *, label: str) -> Path:
    lexical = path.absolute()
    root = remediation.ROOT.absolute()
    if (
        not lexical.is_relative_to(root)
        or remediation.has_symlink_component(lexical)
    ):
        raise BootstrapExecutionError(f"unsafe fixed T2 {label} path")
    return lexical


class BootstrapModelExecutor:
    """The only candidate.4 T2 provider-call boundary.

    A fixed authorization is revalidated before every call. The bound slot and a
    caller-allocated native request ID are fsync-journaled before provider code is
    invoked. Any failure or identity drift creates a permanent fail-closed latch.
    """

    def __init__(self) -> None:
        self.authorization_receipt_path = _safe_active_path(
            ACTIVE_BOOTSTRAP_AUTHORIZATION, label="authorization"
        )
        self.ledger_path = _safe_active_path(ACTIVE_BOOTSTRAP_LEDGER, label="ledger")
        self.failure_latch_path = _safe_active_path(
            ACTIVE_BOOTSTRAP_FAILURE_LATCH, label="failure latch"
        )
        self.execution_capability_path = _safe_active_path(
            ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY, label="execution capability"
        )
        self.request_root = _safe_active_path(
            ACTIVE_BOOTSTRAP_REQUEST_ROOT, label="request receipt root"
        )
        self.claim_root = _safe_active_path(
            ACTIVE_BOOTSTRAP_CLAIM_ROOT, label="provider claim root"
        )
        self.raw_root = _safe_active_path(
            ACTIVE_BOOTSTRAP_RAW_ROOT, label="raw receipt root"
        )
        if self.failure_latch_path.exists():
            raise BootstrapExecutionError("T2 bootstrap failure latch is already set")
        self.authorization_receipt = self._authorization()
        self.call_slots = authorization.authorized_bootstrap_slots(
            self.authorization_receipt
        )
        if len(self.call_slots) != authorization.BOOTSTRAP_MODEL_CALLS:
            raise BootstrapExecutionError("T2 bootstrap slot denominator drift")
        self._acquire_execution_capability()
        try:
            self.ledger = remediation.AttemptLedger(
                self.ledger_path,
                authorized_model_call_slots=self.call_slots,
            )
        except (OSError, remediation.RemediationError) as exc:
            self._latch(reason="FIXED_LEDGER_ACQUISITION_FAILED", slot_id=None)
            raise BootstrapExecutionError(
                "fixed T2 ledger could not be acquired after capability consumption"
            ) from exc

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.ledger.close()

    def _authorization(self) -> dict[str, Any]:
        if remediation.has_symlink_component(self.authorization_receipt_path):
            raise BootstrapExecutionError("T2 authorization receipt is unsafe")
        try:
            envelope = json.loads(
                self.authorization_receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapExecutionError("T2 authorization receipt is invalid") from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("schema") != "milai.dg10.remediation-smoke-preflight.v1"
            or envelope.get("candidate_id") != remediation.CANDIDATE
            or envelope.get("status") != "AUTHORIZED_READY_FOR_T2_EXECUTION"
            or envelope.get("provider_requests") != 0
            or envelope.get("model_outputs_opened") is not False
            or envelope.get("test_access_authorized") is not False
            or not isinstance(envelope.get("authorization"), dict)
        ):
            raise BootstrapExecutionError("T2 authorization receipt is not a valid fixed preflight")
        value = dict(envelope["authorization"])
        return value

    def _acquire_execution_capability(self) -> None:
        receipt = {
            "schema": "milai.dg10.bootstrap-execution-capability.v1",
            "candidate_id": remediation.CANDIDATE,
            "phase": authorization.BOOTSTRAP_PHASE,
            "authorization_receipt": {
                "path": self.authorization_receipt_path.relative_to(remediation.ROOT).as_posix(),
                "sha256": remediation.sha256_file(self.authorization_receipt_path),
            },
            "authorization_payload_sha256": self.authorization_receipt.get(
                "authorization_payload_sha256"
            ),
            "call_slot_manifest_sha256": self.authorization_receipt.get(
                "call_slot_manifest_sha256"
            ),
            "authorized_model_call_count": authorization.BOOTSTRAP_MODEL_CALLS,
            "fixed_ledger_path": self.ledger_path.relative_to(remediation.ROOT).as_posix(),
            "fixed_failure_latch_path": self.failure_latch_path.relative_to(
                remediation.ROOT
            ).as_posix(),
            "fixed_request_root": self.request_root.relative_to(
                remediation.ROOT
            ).as_posix(),
            "fixed_provider_claim_root": self.claim_root.relative_to(
                remediation.ROOT
            ).as_posix(),
            "fixed_raw_sidecar_root": self.raw_root.relative_to(
                remediation.ROOT
            ).as_posix(),
            "remaining_execution_capabilities": 0,
        }
        try:
            remediation.atomic_write_new(
                self.execution_capability_path,
                remediation.encoded_json(receipt),
            )
        except remediation.RemediationError as exc:
            raise BootstrapExecutionError(
                "candidate-global T2 execution capability was already consumed"
            ) from exc

    def _latch(self, *, reason: str, slot_id: str | None) -> None:
        receipt = {
            "schema": "milai.dg10.bootstrap-failure-latch.v1",
            "candidate_id": remediation.CANDIDATE,
            "phase": authorization.BOOTSTRAP_PHASE,
            "reason": reason,
            "failed_slot_id": slot_id,
            "authorization_payload_sha256": self.authorization_receipt.get(
                "authorization_payload_sha256"
            ),
            "remaining_calls_authorized": False,
            "new_candidate_required": True,
        }
        if not self.failure_latch_path.exists():
            remediation.atomic_write_new(
                self.failure_latch_path,
                remediation.encoded_json(receipt),
            )

    def _revalidate(self, slot_id: str) -> None:
        if self.failure_latch_path.exists():
            raise BootstrapExecutionError("T2 bootstrap is permanently latched closed")
        try:
            current = self._authorization()
            current_slots = authorization.authorized_bootstrap_slots(current)
        except (authorization.AuthorizationError, BootstrapExecutionError) as exc:
            self._latch(reason="AUTHORIZATION_OR_IDENTITY_DRIFT", slot_id=slot_id)
            raise BootstrapExecutionError(
                "T2 authorization or identity drifted before provider access"
            ) from exc
        if current != self.authorization_receipt or current_slots != self.call_slots:
            self._latch(reason="AUTHORIZATION_OR_SLOT_MANIFEST_DRIFT", slot_id=slot_id)
            raise BootstrapExecutionError("T2 authorization changed before provider access")

    def execute_call(
        self,
        *,
        slot_id: str,
        case_id: str,
        messages: Sequence[Mapping[str, str]],
    ) -> Mapping[str, Any]:
        self._revalidate(slot_id)
        if not re.fullmatch(r"[a-z0-9.-]+", slot_id):
            raise BootstrapExecutionError("T2 slot ID is unsafe for fixed receipts")
        request_id = "dg10-t2-request-" + remediation.sha256_bytes(
            remediation.encoded_json(
                {
                    "slot_id": slot_id,
                    "authorization_payload_sha256": self.authorization_receipt.get(
                        "authorization_payload_sha256"
                    ),
                }
            )
        )[:32]
        request_document = provider_adapter.request_document(
            request_id=request_id,
            messages=messages,
        )
        attempt_id = self.ledger.start_attempt(
            phase=authorization.BOOTSTRAP_PHASE,
            arm="T2_CONTROL_PATH",
            case_id=case_id,
            planned_model_calls=1,
            planned_mcp_calls=0,
            attempt_id=slot_id,
        )
        request_receipt_path = self.request_root / f"{slot_id}.json"
        request_receipt = {
            "schema": "milai.dg10.t2-provider-request.v1",
            "candidate_id": remediation.CANDIDATE,
            "slot_id": slot_id,
            "request_id": request_id,
            "endpoint": provider_adapter.ENDPOINT,
            "model_id": provider_adapter.MODEL_ID,
            "request_payload_sha256": remediation.sha256_bytes(
                remediation.encoded_json(request_document)
            ),
            "adapter_sha256": remediation.sha256_file(Path(provider_adapter.__file__).resolve()),
            "planned_provider_request_count": 1,
        }
        remediation.atomic_write_new(
            request_receipt_path,
            remediation.encoded_json(request_receipt),
        )
        try:
            provider_claim_path = self.claim_root / f"{slot_id}.json"
            raw_sidecar_path = self.raw_root / f"{slot_id}.json"
            outcome = provider_adapter.request_once(
                slot_id=slot_id,
                attempt_id=attempt_id,
                request_id=request_id,
                request_document_value=request_document,
                ledger=self.ledger,
                ledger_path=self.ledger_path,
                execution_capability_path=self.execution_capability_path,
                request_receipt_path=request_receipt_path,
                provider_claim_path=provider_claim_path,
                raw_sidecar_path=raw_sidecar_path,
                failure_latch_path=self.failure_latch_path,
            )
            raw_sidecar_digest = remediation.sha256_file(raw_sidecar_path)
            if raw_sidecar_digest != outcome.raw_sidecar_digest:
                raise BootstrapExecutionError("T2 raw sidecar binding drift")
            acceptance_receipt_path = (
                self.request_root / f"{slot_id}.accepted.json"
            )
            acceptance_receipt = {
                "schema": "milai.dg10.t2-provider-acceptance.v1",
                "candidate_id": remediation.CANDIDATE,
                "slot_id": slot_id,
                "request_id": request_id,
                "provider_response_id": outcome.provider_response_id,
                "request_receipt_sha256": remediation.sha256_file(request_receipt_path),
                "raw_sidecar_sha256": raw_sidecar_digest,
                "finish_reason": outcome.finish_reason,
                "usage": dict(outcome.usage),
                "actual_provider_request_count": 1,
            }
            remediation.atomic_write_new(
                acceptance_receipt_path,
                remediation.encoded_json(acceptance_receipt),
            )
            self.ledger.record_provider_terminal(
                attempt_id,
                usage=outcome.usage,
                raw_sidecar_digest=raw_sidecar_digest,
            )
            self.ledger.finalize(
                attempt_id,
                agent_terminal=True,
                parser_terminal=True,
                retention_state="retained",
                failure_reason_code="SUCCESS",
                redacted_public_receipt_digest=remediation.sha256_file(
                    acceptance_receipt_path
                ),
            )
            return {
                "slot_id": slot_id,
                "request_id": request_id,
                "provider_response_id": outcome.provider_response_id,
                "usage": dict(outcome.usage),
                "finish_reason": outcome.finish_reason,
                "provider_request_count": 1,
            }
        except BaseException as exc:
            provider_accepted = False
            try:
                matching = [
                    row
                    for row in remediation.read_attempt_ledger(self.ledger_path)
                    if row.get("attempt_id") == attempt_id
                ]
                provider_accepted = bool(
                    matching and matching[-1].get("native_request_ids")
                )
            except (OSError, remediation.RemediationError):
                pass
            try:
                self.ledger.finalize(
                    attempt_id,
                    agent_terminal=False,
                    parser_terminal=False,
                    retention_state="failed",
                    failure_reason_code=(
                        "PROVIDER_TERMINAL_MISSING"
                        if provider_accepted
                        else "PROVIDER_REQUEST_FAILED"
                    ),
                    redacted_public_receipt_digest="0" * 64,
                )
            except remediation.RemediationError:
                pass
            self._latch(reason="T2_CALL_FAILED", slot_id=slot_id)
            if isinstance(exc, BootstrapExecutionError):
                raise
            raise BootstrapExecutionError("T2 provider call failed and latched closed") from exc
