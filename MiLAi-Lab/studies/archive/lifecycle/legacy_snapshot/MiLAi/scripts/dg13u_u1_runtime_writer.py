from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from milai.domain.deletion import EvidenceRevocationRequest
from milai.domain.evidence import EvidenceIngestRequest
from milai.domain.proposals import ProposalCreateRequest, ProposalReviewRequest
from pydantic import BaseModel, ValidationError

_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUNTIME_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class _Opener(Protocol):
    def open(self, request: urllib.request.Request, *, timeout: float) -> Any: ...


class RuntimeWriterError(RuntimeError):
    """Sanitized terminal from one bounded Runtime HTTP attempt."""

    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        runtime_error_code: str | None = None,
        attempt_count: int = 1,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.runtime_error_code = runtime_error_code
        self.attempt_count = attempt_count


class RuntimeWriterContractError(RuntimeWriterError):
    """Local invocation failed before any HTTP request was attempted."""

    def __init__(self, code: str) -> None:
        super().__init__(code, attempt_count=0)


class LoopbackRuntimeFixtureWriter:
    """Thin role-separated adapter for the existing controlled Runtime write APIs."""

    def __init__(
        self,
        base_url: str,
        *,
        submitter_token: str,
        reviewer_token: str,
        operator_token: str,
        timeout_seconds: float = 5.0,
        max_request_bytes: int = 65_536,
        max_response_bytes: int = 1_048_576,
        opener: _Opener | None = None,
    ) -> None:
        self._base_url = _loopback_origin(base_url)
        self._tokens = {
            "submitter": _token(submitter_token),
            "reviewer": _token(reviewer_token),
            "operator": _token(operator_token),
        }
        if len(set(self._tokens.values())) != 3:
            raise RuntimeWriterContractError("ROLE_TOKENS_NOT_SEPARATED")
        if not 0.01 <= timeout_seconds <= 30:
            raise RuntimeWriterContractError("TIMEOUT_BOUND_INVALID")
        if not 1 <= max_request_bytes <= 1_048_576:
            raise RuntimeWriterContractError("REQUEST_BOUND_INVALID")
        if not 1 <= max_response_bytes <= 4_194_304:
            raise RuntimeWriterContractError("RESPONSE_BOUND_INVALID")
        self._timeout_seconds = float(timeout_seconds)
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._opener: _Opener = opener or urllib.request.build_opener()

    def capture_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        value = _mapping(payload, "CAPTURE_PAYLOAD_INVALID")
        if value.get("confirmation") != "CAPTURE":
            raise RuntimeWriterContractError("CAPTURE_CONFIRMATION_INVALID")
        operation_id = _operation_id(value)
        unvalidated_body = {
            key: item
            for key, item in value.items()
            if key not in {"operation_id", "confirmation"}
        }
        body = _validated_body(
            EvidenceIngestRequest, unvalidated_body, "CAPTURE_BODY_INVALID"
        )
        return self._post(
            "/v1/evidence",
            body,
            role="submitter",
            operation_id=operation_id,
            accepted_statuses={200, 201},
        )

    def propose_as_submitter(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        value = _mapping(payload, "PROPOSAL_PAYLOAD_INVALID")
        if value.get("confirmation") != "SUBMIT":
            raise RuntimeWriterContractError("PROPOSAL_CONFIRMATION_INVALID")
        operation_id = _operation_id(value)
        proposal = value.get("proposal")
        if not isinstance(proposal, Mapping):
            raise RuntimeWriterContractError("PROPOSAL_BODY_INVALID")
        body = _validated_body(
            ProposalCreateRequest, dict(proposal), "PROPOSAL_BODY_INVALID"
        )
        return self._post(
            "/v1/proposals",
            body,
            role="submitter",
            operation_id=operation_id,
            accepted_statuses={200, 201},
        )

    def review_as_steward(
        self, proposal_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        proposal_id = _resource_id(proposal_id, "PROPOSAL_ID_INVALID")
        value = _mapping(payload, "REVIEW_PAYLOAD_INVALID")
        operation_id = _operation_id(value)
        body = _validated_body(
            ProposalReviewRequest,
            {key: item for key, item in value.items() if key != "operation_id"},
            "REVIEW_BODY_INVALID",
        )
        return self._post(
            f"/v1/proposals/{proposal_id}/review",
            body,
            role="reviewer",
            operation_id=operation_id,
            accepted_statuses={200},
        )

    def revoke_as_operator(
        self, evidence_id: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        evidence_id = _resource_id(evidence_id, "EVIDENCE_ID_INVALID")
        value = _mapping(payload, "REVOCATION_PAYLOAD_INVALID")
        operation_id = _operation_id(value)
        body = _validated_body(
            EvidenceRevocationRequest,
            {key: item for key, item in value.items() if key != "operation_id"},
            "REVOCATION_BODY_INVALID",
        )
        return self._post(
            f"/v1/evidence/{evidence_id}/revoke",
            body,
            role="operator",
            operation_id=operation_id,
            accepted_statuses={200, 202},
        )

    def _post(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        role: str,
        operation_id: str,
        accepted_statuses: set[int],
    ) -> Mapping[str, Any]:
        try:
            encoded = json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        except (TypeError, ValueError):
            raise RuntimeWriterContractError("REQUEST_JSON_INVALID") from None
        if len(encoded) > self._max_request_bytes:
            raise RuntimeWriterContractError("REQUEST_JSON_TOO_LARGE")
        request = urllib.request.Request(
            self._base_url + path,
            data=encoded,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._tokens[role]}",
                "Content-Type": "application/json",
                "Idempotency-Key": operation_id,
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", None)
                raw = response.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raw = exc.read(self._max_response_bytes + 1)
            runtime_code = _safe_runtime_error_code(raw, self._max_response_bytes)
            raise RuntimeWriterError(
                "RUNTIME_HTTP_ERROR",
                http_status=exc.code,
                runtime_error_code=runtime_code,
            ) from None
        except TimeoutError:
            raise RuntimeWriterError("RUNTIME_TIMEOUT") from None
        except (urllib.error.URLError, OSError):
            raise RuntimeWriterError("RUNTIME_TRANSPORT_ERROR") from None
        if not isinstance(raw, bytes):
            raise RuntimeWriterError("RUNTIME_RESPONSE_INVALID")
        if len(raw) > self._max_response_bytes:
            raise RuntimeWriterError("RUNTIME_RESPONSE_TOO_LARGE")
        if status not in accepted_statuses:
            raise RuntimeWriterError(
                "RUNTIME_HTTP_ERROR",
                http_status=status if isinstance(status, int) else None,
                runtime_error_code=_safe_runtime_error_code(
                    raw, self._max_response_bytes
                ),
            )
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeWriterError("RUNTIME_RESPONSE_INVALID") from None
        if not isinstance(value, dict):
            raise RuntimeWriterError("RUNTIME_RESPONSE_INVALID")
        return value


def _loopback_origin(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        raise RuntimeWriterContractError("LOOPBACK_BASE_URL_INVALID") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeWriterContractError("LOOPBACK_BASE_URL_INVALID")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.casefold() == "localhost"
    if not is_loopback:
        raise RuntimeWriterContractError("LOOPBACK_BASE_URL_INVALID")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"http://{host}:{port}"


def _token(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 4096
        or any(
            character.isspace() or not character.isprintable() for character in value
        )
    ):
        raise RuntimeWriterContractError("ROLE_TOKEN_INVALID")
    return value


def _mapping(value: Mapping[str, Any], code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeWriterContractError(code)
    return dict(value)


def _operation_id(value: Mapping[str, Any]) -> str:
    operation_id = value.get("operation_id")
    if (
        not isinstance(operation_id, str)
        or _OPERATION_ID.fullmatch(operation_id) is None
    ):
        raise RuntimeWriterContractError("OPERATION_ID_INVALID")
    return operation_id


def _resource_id(value: str, code: str) -> str:
    if not isinstance(value, str):
        raise RuntimeWriterContractError(code)
    try:
        parsed = UUID(value)
    except ValueError:
        raise RuntimeWriterContractError(code) from None
    return str(parsed)


def _validated_body(
    model: type[BaseModel], body: Mapping[str, Any], code: str
) -> dict[str, Any]:
    try:
        return model.model_validate(body).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        raise RuntimeWriterContractError(code) from None


def _safe_runtime_error_code(raw: bytes, limit: int) -> str | None:
    if len(raw) > limit:
        return None
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = value.get("error") if isinstance(value, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and _RUNTIME_ERROR_CODE.fullmatch(code) is not None:
        return code
    return None
