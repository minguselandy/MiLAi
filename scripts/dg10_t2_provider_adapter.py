from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.agent_efficiency import vllm_local_identity as local_identity
from scripts import dg10_authorization as authorization
from scripts import dg10_remediation as remediation

ENDPOINT = "http://127.0.0.1:7860/v1/chat/completions"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
MAX_TOKENS = 256
TIMEOUT_SECONDS = 180.0
MAX_RESPONSE_BYTES = 1024 * 1024


class SealedProviderError(remediation.RemediationError):
    pass


@dataclass(frozen=True, slots=True)
class SealedProviderResult:
    provider_response_id: str
    usage: dict[str, int]
    finish_reason: str
    raw_sidecar_digest: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise SealedProviderError(reason)


def request_document(*, request_id: str, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    _require(isinstance(request_id, str) and request_id.startswith("dg10-t2-request-"), "T2 request ID drift")
    _require(1 <= len(messages) <= 64, "T2 message denominator drift")
    normalized: list[dict[str, str]] = []
    for item in messages:
        _require(
            isinstance(item, Mapping)
            and set(item) == {"role", "content"}
            and item.get("role") in {"system", "user", "assistant", "tool"}
            and isinstance(item.get("content"), str)
            and bool(item["content"]),
            "T2 message schema drift",
        )
        normalized.append({"role": str(item["role"]), "content": str(item["content"])})
    return {
        "model": MODEL_ID,
        "messages": normalized,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }


def _validated_request_document(
    *, request_id: str, value: Mapping[str, Any]
) -> dict[str, Any]:
    _require(
        set(value) == {"model", "messages", "temperature", "max_tokens", "stream"},
        "T2 sealed request key set drift",
    )
    messages = value.get("messages")
    _require(
        isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)),
        "T2 sealed request messages drift",
    )
    expected = request_document(request_id=request_id, messages=messages)
    _require(dict(value) == expected, "T2 sealed request policy drift")
    return expected


def _fixed_bootstrap_paths() -> tuple[Path, Path, Path, Path, Path, Path]:
    root = remediation.ROOT
    return (
        root / "var/dg10/t2-bootstrap-candidate.4/attempts.jsonl",
        root / "var/dg10/t2-bootstrap-candidate.4/execution-capability.json",
        root / "var/dg10/t2-bootstrap-candidate.4/provider-requests",
        root / "var/dg10/t2-bootstrap-candidate.4/provider-claims",
        root / "var/dg10/t2-bootstrap-candidate.4/raw-sidecars",
        root / "var/dg10/t2-bootstrap-candidate.4/failure-latch.json",
    )


def _fixed_authorization_receipt() -> Path:
    return remediation.ROOT / (
        "docs/reports/DG-10-model-run-authorization-candidate.4-2026-08-22.json"
    )


def _validated_bootstrap_binding(
    *,
    slot_id: str,
    attempt_id: str,
    request_id: str,
    request_document_value: Mapping[str, Any],
    ledger: remediation.AttemptLedger,
    ledger_path: Path,
    execution_capability_path: Path,
    request_receipt_path: Path,
    provider_claim_path: Path,
    raw_sidecar_path: Path,
    failure_latch_path: Path,
) -> dict[str, Any]:
    (
        fixed_ledger,
        fixed_capability,
        fixed_request_root,
        fixed_claim_root,
        fixed_raw_root,
        fixed_failure_latch,
    ) = _fixed_bootstrap_paths()
    lexical_paths = (
        ledger_path.absolute(),
        execution_capability_path.absolute(),
        request_receipt_path.absolute(),
        provider_claim_path.absolute(),
        raw_sidecar_path.absolute(),
        failure_latch_path.absolute(),
    )
    _require(
        lexical_paths
        == (
            fixed_ledger.absolute(),
            fixed_capability.absolute(),
            (fixed_request_root / f"{slot_id}.json").absolute(),
            (fixed_claim_root / f"{slot_id}.json").absolute(),
            (fixed_raw_root / f"{slot_id}.json").absolute(),
            fixed_failure_latch.absolute(),
        )
        and all(not remediation.has_symlink_component(path) for path in lexical_paths),
        "T2 provider binding path drift",
    )
    _require(
        isinstance(ledger, remediation.AttemptLedger)
        and ledger.path.absolute() == fixed_ledger.absolute(),
        "T2 provider live ledger binding drift",
    )
    _require(not failure_latch_path.exists(), "T2 provider failure latch is set")
    _require(
        not provider_claim_path.exists() and not raw_sidecar_path.exists(),
        "T2 provider slot artifacts already exist",
    )
    try:
        capability = json.loads(execution_capability_path.read_text(encoding="utf-8"))
        request_receipt = json.loads(request_receipt_path.read_text(encoding="utf-8"))
        authorization_envelope = json.loads(
            _fixed_authorization_receipt().read_text(encoding="utf-8")
        )
        reconciliation = remediation.reconcile_attempt_ledger(ledger_path)
        attempts = remediation.read_attempt_ledger(ledger_path)
    except (OSError, json.JSONDecodeError, remediation.RemediationError) as exc:
        raise SealedProviderError("T2 provider binding artifacts are invalid") from exc
    fixed_authorization = _fixed_authorization_receipt()
    required_capability_keys = {
        "schema",
        "candidate_id",
        "phase",
        "authorization_receipt",
        "authorization_payload_sha256",
        "call_slot_manifest_sha256",
        "authorized_model_call_count",
        "fixed_ledger_path",
        "fixed_failure_latch_path",
        "fixed_request_root",
        "fixed_provider_claim_root",
        "fixed_raw_sidecar_root",
        "remaining_execution_capabilities",
    }
    _require(
        isinstance(capability, Mapping)
        and set(capability) == required_capability_keys
        and capability.get("schema")
        == "milai.dg10.bootstrap-execution-capability.v1"
        and capability.get("candidate_id") == remediation.CANDIDATE
        and capability.get("phase") == "T2_CONTROL_PATH_SMOKE"
        and capability.get("authorized_model_call_count") == 24
        and capability.get("fixed_ledger_path")
        == fixed_ledger.relative_to(remediation.ROOT).as_posix()
        and capability.get("fixed_failure_latch_path")
        == "var/dg10/t2-bootstrap-candidate.4/failure-latch.json"
        and capability.get("fixed_request_root")
        == fixed_request_root.relative_to(remediation.ROOT).as_posix()
        and capability.get("fixed_provider_claim_root")
        == fixed_claim_root.relative_to(remediation.ROOT).as_posix()
        and capability.get("fixed_raw_sidecar_root")
        == fixed_raw_root.relative_to(remediation.ROOT).as_posix()
        and capability.get("remaining_execution_capabilities") == 0,
        "T2 execution capability drift",
    )
    _require(
        isinstance(authorization_envelope, Mapping)
        and authorization_envelope.get("schema")
        == "milai.dg10.remediation-smoke-preflight.v1"
        and authorization_envelope.get("candidate_id") == remediation.CANDIDATE
        and authorization_envelope.get("status")
        == "AUTHORIZED_READY_FOR_T2_EXECUTION"
        and authorization_envelope.get("provider_requests") == 0
        and authorization_envelope.get("model_outputs_opened") is False
        and authorization_envelope.get("test_access_authorized") is False
        and isinstance(authorization_envelope.get("authorization"), Mapping),
        "T2 fixed authorization envelope drift",
    )
    authorization_value = dict(authorization_envelope["authorization"])
    try:
        slots = authorization.authorized_bootstrap_slots(authorization_value)
    except authorization.AuthorizationError as exc:
        raise SealedProviderError("T2 fixed authorization replay failed") from exc
    _require(
        capability.get("authorization_receipt")
        == {
            "path": fixed_authorization.relative_to(remediation.ROOT).as_posix(),
            "sha256": remediation.sha256_file(fixed_authorization),
        }
        and capability.get("authorization_payload_sha256")
        == authorization_value.get("authorization_payload_sha256")
        and capability.get("call_slot_manifest_sha256")
        == authorization_value.get("call_slot_manifest_sha256")
        and slot_id in slots,
        "T2 execution capability authorization binding drift",
    )
    payload_sha256 = remediation.sha256_bytes(
        remediation.encoded_json(dict(request_document_value))
    )
    _require(
        isinstance(request_receipt, Mapping)
        and set(request_receipt)
        == {
            "schema",
            "candidate_id",
            "slot_id",
            "request_id",
            "endpoint",
            "model_id",
            "request_payload_sha256",
            "adapter_sha256",
            "planned_provider_request_count",
        }
        and request_receipt.get("schema") == "milai.dg10.t2-provider-request.v1"
        and request_receipt.get("candidate_id") == remediation.CANDIDATE
        and request_receipt.get("slot_id") == slot_id == attempt_id
        and request_receipt.get("request_id") == request_id
        and request_receipt.get("endpoint") == ENDPOINT
        and request_receipt.get("model_id") == MODEL_ID
        and request_receipt.get("request_payload_sha256") == payload_sha256
        and request_receipt.get("adapter_sha256")
        == remediation.sha256_file(Path(__file__).resolve())
        and request_receipt.get("planned_provider_request_count") == 1,
        "T2 provider request receipt drift",
    )
    _require(
        reconciliation.get("unfinalized_attempt_count", 0) >= 1
        and reconciliation.get("hash_chain_valid") is True,
        "T2 provider attempt ledger replay failed",
    )
    matching = [row for row in attempts if row.get("attempt_id") == attempt_id]
    _require(
        len(matching) == 1
        and matching[0].get("phase") == "T2_CONTROL_PATH_SMOKE"
        and matching[0].get("arm") == "T2_CONTROL_PATH"
        and matching[0].get("attempt_state") == "PLANNED"
        and matching[0].get("planned_model_calls") == 1
        and matching[0].get("native_request_ids") == [],
        "T2 provider attempt is not one fixed unconsumed PLANNED slot",
    )
    return {
        "capability_sha256": remediation.sha256_file(execution_capability_path),
        "authorization_payload_sha256": capability[
            "authorization_payload_sha256"
        ],
        "request_receipt_sha256": remediation.sha256_file(request_receipt_path),
        "ledger_sha256_before_claim": remediation.sha256_file(ledger_path),
        "planned_attempt_entry_sha256": matching[0]["entry_sha256"],
    }


def _write_failure_latch(
    *,
    failure_latch_path: Path,
    slot_id: str,
    reason: str,
    authorization_payload_sha256: str,
) -> None:
    remediation._require_sha256(
        authorization_payload_sha256,
        "T2 failure latch authorization payload digest",
    )
    receipt = {
        "schema": "milai.dg10.bootstrap-failure-latch.v1",
        "candidate_id": remediation.CANDIDATE,
        "phase": authorization.BOOTSTRAP_PHASE,
        "reason": reason,
        "failed_slot_id": slot_id,
        "authorization_payload_sha256": authorization_payload_sha256,
        "remaining_calls_authorized": False,
        "new_candidate_required": True,
    }
    if failure_latch_path.exists():
        return
    try:
        remediation.atomic_write_new(
            failure_latch_path, remediation.encoded_json(receipt)
        )
    except (OSError, remediation.RemediationError):
        if not failure_latch_path.exists():
            raise


def _claim_slot(
    *,
    slot_id: str,
    attempt_id: str,
    request_id: str,
    ledger: remediation.AttemptLedger,
    ledger_path: Path,
    execution_capability_path: Path,
    request_receipt_path: Path,
    provider_claim_path: Path,
    binding: Mapping[str, Any],
) -> str:
    claim = {
        "schema": "milai.dg10.t2-provider-slot-claim.v1",
        "candidate_id": remediation.CANDIDATE,
        "phase": authorization.BOOTSTRAP_PHASE,
        "slot_id": slot_id,
        "attempt_id": attempt_id,
        "request_id": request_id,
        "fixed_ledger_path": ledger_path.relative_to(remediation.ROOT).as_posix(),
        "execution_capability_path": execution_capability_path.relative_to(
            remediation.ROOT
        ).as_posix(),
        "request_receipt_path": request_receipt_path.relative_to(
            remediation.ROOT
        ).as_posix(),
        "capability_sha256": binding.get("capability_sha256"),
        "authorization_payload_sha256": binding.get(
            "authorization_payload_sha256"
        ),
        "request_receipt_sha256": binding.get("request_receipt_sha256"),
        "ledger_sha256_before_claim": binding.get("ledger_sha256_before_claim"),
        "planned_attempt_entry_sha256": binding.get(
            "planned_attempt_entry_sha256"
        ),
        "planned_provider_request_count": 1,
    }
    for key in (
        "capability_sha256",
        "authorization_payload_sha256",
        "request_receipt_sha256",
        "ledger_sha256_before_claim",
        "planned_attempt_entry_sha256",
    ):
        remediation._require_sha256(claim[key], f"T2 provider claim {key}")
    try:
        remediation.atomic_write_new(
            provider_claim_path, remediation.encoded_json(claim)
        )
    except (OSError, remediation.RemediationError) as exc:
        raise SealedProviderError(
            "T2 provider slot was already durably claimed"
        ) from exc
    claim_digest = remediation.sha256_file(provider_claim_path)
    try:
        ledger.record_provider_claimed(
            attempt_id, provider_claim_digest=claim_digest
        )
    except (OSError, remediation.RemediationError) as exc:
        raise SealedProviderError(
            "T2 provider claim could not be fsync-journaled"
        ) from exc
    return claim_digest


def request_once(
    *,
    slot_id: str,
    attempt_id: str,
    request_id: str,
    request_document_value: Mapping[str, Any],
    ledger: remediation.AttemptLedger,
    ledger_path: Path,
    execution_capability_path: Path,
    request_receipt_path: Path,
    provider_claim_path: Path,
    raw_sidecar_path: Path,
    failure_latch_path: Path,
) -> SealedProviderResult:
    """Issue exactly one request to the fixed local vLLM completion endpoint."""

    payload = _validated_request_document(
        request_id=request_id, value=request_document_value
    )
    binding = _validated_bootstrap_binding(
        slot_id=slot_id,
        attempt_id=attempt_id,
        request_id=request_id,
        request_document_value=payload,
        ledger=ledger,
        ledger_path=ledger_path,
        execution_capability_path=execution_capability_path,
        request_receipt_path=request_receipt_path,
        provider_claim_path=provider_claim_path,
        raw_sidecar_path=raw_sidecar_path,
        failure_latch_path=failure_latch_path,
    )
    try:
        _claim_slot(
            slot_id=slot_id,
            attempt_id=attempt_id,
            request_id=request_id,
            ledger=ledger,
            ledger_path=ledger_path,
            execution_capability_path=execution_capability_path,
            request_receipt_path=request_receipt_path,
            provider_claim_path=provider_claim_path,
            binding=binding,
        )
        request = urllib.request.Request(
            ENDPOINT,
            data=remediation.encoded_json(payload),
            headers={"Content-Type": "application/json", "X-Request-ID": request_id},
            method="POST",
        )
        opener = local_identity.local_opener()
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
        _require(
            status == 200 and 0 < len(raw) <= MAX_RESPONSE_BYTES,
            "fixed local provider response invalid",
        )
        remediation.atomic_write_new(raw_sidecar_path, raw)
        raw_sidecar_digest = remediation.sha256_file(raw_sidecar_path)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SealedProviderError(
                "fixed local provider response is not JSON"
            ) from exc
        _require(
            isinstance(value, Mapping),
            "fixed local provider response is not an object",
        )
        response_id = value.get("id")
        _require(
            isinstance(response_id, str) and response_id,
            "provider-native response ID absent",
        )
        ledger.record_provider_accepted(
            attempt_id,
            response_id,
            raw_sidecar_digest=raw_sidecar_digest,
        )

        choices = value.get("choices")
        usage = value.get("usage")
        _require(
            isinstance(choices, list) and len(choices) == 1,
            "provider choice denominator drift",
        )
        choice = choices[0]
        _require(isinstance(choice, Mapping), "provider choice is not an object")
        finish_reason = choice.get("finish_reason")
        message = choice.get("message")
        _require(
            isinstance(finish_reason, str)
            and finish_reason
            and isinstance(message, Mapping)
            and isinstance(message.get("content"), str),
            "provider terminal response drift",
        )
        _require(isinstance(usage, Mapping), "provider usage absent")
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        cached = usage.get("prompt_tokens_details", {})
        cached_tokens = (
            cached.get("cached_tokens", 0) if isinstance(cached, Mapping) else 0
        )
        reasoning = usage.get("completion_tokens_details", {})
        reasoning_tokens = (
            reasoning.get("reasoning_tokens", 0)
            if isinstance(reasoning, Mapping)
            else 0
        )
        normalized_usage = {
            "input_tokens": prompt,
            "output_tokens": completion,
            "cached_input_tokens": cached_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        _require(
            all(
                isinstance(item, int)
                and not isinstance(item, bool)
                and item >= 0
                for item in normalized_usage.values()
            ),
            "provider usage field drift",
        )
        return SealedProviderResult(
            provider_response_id=response_id,
            usage=normalized_usage,
            finish_reason=finish_reason,
            raw_sidecar_digest=raw_sidecar_digest,
        )
    except BaseException as exc:
        try:
            _write_failure_latch(
                failure_latch_path=failure_latch_path,
                slot_id=slot_id,
                reason="T2_ADAPTER_FAILED_AFTER_SLOT_CLAIM",
                authorization_payload_sha256=str(
                    binding["authorization_payload_sha256"]
                ),
            )
        except (OSError, remediation.RemediationError) as latch_exc:
            raise SealedProviderError(
                "T2 provider failed and its fixed failure latch could not be written"
            ) from latch_exc
        if isinstance(exc, SealedProviderError):
            raise
        if isinstance(exc, (OSError, urllib.error.URLError)):
            raise SealedProviderError("fixed local provider request failed") from exc
        raise SealedProviderError("fixed local provider processing failed") from exc
