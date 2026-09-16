from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar
from urllib.parse import urlsplit

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}")
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_DEV_PHASES = {"functional_f1", "smoke", "dev", "serving", "bfcl"}
_DEV_RUN_SCHEMA = "milai.provider.dev-run.v1"
_CLOSED_TEST_RUN_SCHEMA = "milai.provider.closed-test-run.v1"
_TRANSPORTS = {"json", "stream", "opencode"}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderExecutionError(RuntimeError):
    pass


class CapabilityError(ProviderExecutionError):
    pass


class BudgetError(ProviderExecutionError):
    pass


class ProviderCallError(ProviderExecutionError):
    pass


class ProviderTransportError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        request_started: bool,
        native_request_id: str | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.request_started = request_started
        self.native_request_id = native_request_id


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise CapabilityError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise CapabilityError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CapabilityError(f"{label} must be a positive integer")
    return value


def _endpoint(value: object) -> str:
    if not isinstance(value, str):
        raise CapabilityError("endpoint_identity must be a loopback HTTP origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise CapabilityError("endpoint_identity must be a loopback HTTP origin")
    port = parsed.port
    if port is None or not 1 <= port <= 65535:
        raise CapabilityError("endpoint_identity must include a valid port")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


@dataclass(frozen=True, slots=True)
class DevRunCapability:
    run_id: str
    phase: str
    provider: str
    endpoint_identity: str
    model_id: str
    dataset_manifest_sha256: str
    prompt_template_sha256: str
    max_native_requests: int
    max_prompt_tokens: int
    max_completion_tokens: int
    deadline: datetime
    expires_at: datetime
    synthetic_or_deidentified_only: bool
    closed_test_access: bool
    manifest_sha256: str

    @classmethod
    def load(cls, path: Path, *, now: datetime | None = None) -> DevRunCapability:
        try:
            raw_bytes = path.read_bytes()
            value = json.loads(raw_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityError("DEV_RUN manifest is unreadable") from exc
        required = {
            "schema",
            "run_id",
            "phase",
            "provider",
            "endpoint_identity",
            "model_id",
            "dataset_manifest_sha256",
            "prompt_template_sha256",
            "max_native_requests",
            "max_prompt_tokens",
            "max_completion_tokens",
            "deadline",
            "expires_at",
            "synthetic_or_deidentified_only",
            "closed_test_access",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise CapabilityError("DEV_RUN manifest field set is invalid")
        schema = value["schema"]
        if schema not in {_DEV_RUN_SCHEMA, _CLOSED_TEST_RUN_SCHEMA}:
            raise CapabilityError("provider capability schema is invalid")
        run_id = value["run_id"]
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise CapabilityError("DEV_RUN run_id is invalid")
        phase = value["phase"]
        closed_test = schema == _CLOSED_TEST_RUN_SCHEMA
        if (closed_test and phase != "confirmation") or (
            not closed_test and phase not in _DEV_PHASES
        ):
            raise CapabilityError("provider capability phase is invalid")
        if value["provider"] != "local_vllm":
            raise CapabilityError("DEV_RUN provider is not local_vllm")
        model_id = value["model_id"]
        if not isinstance(model_id, str) or _IDENTIFIER.fullmatch(model_id) is None:
            raise CapabilityError("DEV_RUN model_id is invalid")
        for name in ("dataset_manifest_sha256", "prompt_template_sha256"):
            if not isinstance(value[name], str) or _SHA256.fullmatch(value[name]) is None:
                raise CapabilityError(f"DEV_RUN {name} is invalid")
        deadline = _parse_timestamp(value["deadline"], "deadline")
        expires_at = _parse_timestamp(value["expires_at"], "expires_at")
        current = (now or _now()).astimezone(UTC)
        if current >= deadline or current >= expires_at:
            raise CapabilityError("DEV_RUN capability is expired")
        if deadline > expires_at:
            raise CapabilityError("DEV_RUN deadline exceeds expires_at")
        if value["synthetic_or_deidentified_only"] is not True:
            raise CapabilityError("DEV_RUN requires synthetic/deidentified data")
        if value["closed_test_access"] is not closed_test:
            raise CapabilityError("provider capability closed-test access is invalid")
        return cls(
            run_id=run_id,
            phase=phase,
            provider="local_vllm",
            endpoint_identity=_endpoint(value["endpoint_identity"]),
            model_id=model_id,
            dataset_manifest_sha256=value["dataset_manifest_sha256"],
            prompt_template_sha256=value["prompt_template_sha256"],
            max_native_requests=_positive_int(value["max_native_requests"], "max_native_requests"),
            max_prompt_tokens=_positive_int(value["max_prompt_tokens"], "max_prompt_tokens"),
            max_completion_tokens=_positive_int(
                value["max_completion_tokens"], "max_completion_tokens"
            ),
            deadline=deadline,
            expires_at=expires_at,
            synthetic_or_deidentified_only=True,
            closed_test_access=closed_test,
            manifest_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    logical_request_id: str
    transport: str
    payload: Mapping[str, Any]
    prompt_token_budget: int
    completion_token_budget: int
    timeout_seconds: float

    def validate(self, capability: DevRunCapability) -> None:
        if _IDENTIFIER.fullmatch(self.logical_request_id) is None:
            raise CapabilityError("logical_request_id is invalid")
        if self.transport not in _TRANSPORTS:
            raise CapabilityError("provider transport is invalid")
        if self.payload.get("model") != capability.model_id:
            raise CapabilityError("request model does not match DEV_RUN")
        if not 1 <= self.prompt_token_budget <= capability.max_prompt_tokens:
            raise BudgetError("prompt token reservation is invalid")
        if not 1 <= self.completion_token_budget <= capability.max_completion_tokens:
            raise BudgetError("completion token reservation is invalid")
        max_tokens = self.payload.get("max_tokens")
        if max_tokens is not None and (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or not 1 <= max_tokens <= self.completion_token_budget
        ):
            raise BudgetError("request max_tokens exceeds its reservation")
        if not isinstance(self.timeout_seconds, (int, float)) or not (
            0 < self.timeout_seconds <= 600
        ):
            raise CapabilityError("provider timeout must be between 0 and 600 seconds")
        if self.transport == "stream" and self.payload.get("stream") is not True:
            raise CapabilityError("stream transport requires stream=true")
        if self.transport != "stream" and self.payload.get("stream") is not False:
            raise CapabilityError("non-stream transport requires stream=false")


@dataclass(frozen=True, slots=True)
class NativeProviderResponse:
    native_request_id: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    payload: Mapping[str, Any]


class ProviderTransport(Protocol):
    name: str

    def invoke(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> NativeProviderResponse: ...


class ProviderStreamTransport(Protocol):
    name: str

    def open_stream(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> Iterator[bytes]: ...


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class GatewayResult(Generic[T]):
    logical_request_id: str
    native_request_id: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    value: T


def _provider_response(value: object) -> NativeProviderResponse:
    if not isinstance(value, dict):
        raise ProviderTransportError("PROVIDER_RESPONSE_NOT_OBJECT", request_started=True)
    native_id = value.get("id")
    usage = value.get("usage")
    choices = value.get("choices")
    finish_reason: object = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish_reason = choices[0].get("finish_reason")
    if not isinstance(native_id, str) or _IDENTIFIER.fullmatch(native_id) is None:
        raise ProviderTransportError("NATIVE_REQUEST_ID_MISSING", request_started=True)
    if not isinstance(usage, dict):
        raise ProviderTransportError(
            "PROVIDER_USAGE_MISSING",
            request_started=True,
            native_request_id=native_id,
        )
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if (
        not isinstance(prompt_tokens, int)
        or isinstance(prompt_tokens, bool)
        or prompt_tokens < 0
        or not isinstance(completion_tokens, int)
        or isinstance(completion_tokens, bool)
        or completion_tokens < 0
        or not isinstance(finish_reason, str)
    ):
        raise ProviderTransportError(
            "PROVIDER_USAGE_OR_FINISH_INVALID",
            request_started=True,
            native_request_id=native_id,
        )
    return NativeProviderResponse(
        native_request_id=native_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        finish_reason=finish_reason,
        payload=value,
    )


class JsonCompletionTransport:
    name = "json"

    def invoke(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> NativeProviderResponse:
        encoded = _canonical(dict(request.payload))
        http_request = urllib.request.Request(  # noqa: S310 - capability validates loopback
            capability.endpoint_identity + "/v1/chat/completions",
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": request.logical_request_id,
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(http_request, timeout=request.timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raise ProviderTransportError(f"PROVIDER_HTTP_{exc.code}", request_started=True) from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise ProviderTransportError("PROVIDER_UNAVAILABLE", request_started=True) from exc
        if status != 200 or len(raw) > _MAX_RESPONSE_BYTES:
            raise ProviderTransportError("PROVIDER_RESPONSE_BOUNDS", request_started=True)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderTransportError(
                "PROVIDER_RESPONSE_INVALID_JSON", request_started=True
            ) from exc
        return _provider_response(value)


class StreamCompletionTransport:
    name = "stream"

    def open_stream(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> Iterator[bytes]:
        encoded = _canonical(dict(request.payload))
        http_request = urllib.request.Request(  # noqa: S310 - capability validates loopback
            capability.endpoint_identity + "/v1/chat/completions",
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Request-ID": request.logical_request_id,
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            return opener.open(http_request, timeout=request.timeout_seconds)
        except urllib.error.HTTPError as exc:
            raise ProviderTransportError(f"PROVIDER_HTTP_{exc.code}", request_started=True) from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise ProviderTransportError("PROVIDER_UNAVAILABLE", request_started=False) from exc

    def invoke(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> NativeProviderResponse:
        observer = _SseObserver()
        source = self.open_stream(request, capability)
        try:
            for chunk in source:
                observer.observe(chunk)
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                close()
        return observer.response()


class _SseObserver:
    """Observe accounting fields while leaving upstream SSE bytes untouched."""

    def __init__(self) -> None:
        self.native_id: str | None = None
        self.finish_reason: str | None = None
        self.usage: Mapping[str, Any] | None = None
        self.observed_bytes = 0
        self.done = False

    def observe(self, raw_chunk: bytes) -> None:
        if not isinstance(raw_chunk, bytes):
            raise ProviderTransportError("PROVIDER_STREAM_EVENT_INVALID", request_started=True)
        self.observed_bytes += len(raw_chunk)
        if self.observed_bytes > _MAX_RESPONSE_BYTES:
            raise ProviderTransportError("PROVIDER_RESPONSE_BOUNDS", request_started=True)
        try:
            lines = raw_chunk.decode("utf-8", errors="strict").splitlines()
        except UnicodeError as exc:
            raise ProviderTransportError(
                "PROVIDER_STREAM_FAILED",
                request_started=True,
                native_request_id=self.native_id,
            ) from exc
        for line in lines:
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                self.done = True
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderTransportError(
                    "PROVIDER_STREAM_FAILED",
                    request_started=True,
                    native_request_id=self.native_id,
                ) from exc
            if not isinstance(event, dict):
                raise ProviderTransportError("PROVIDER_STREAM_EVENT_INVALID", request_started=True)
            event_id = event.get("id")
            if isinstance(event_id, str):
                if self.native_id is not None and self.native_id != event_id:
                    raise ProviderTransportError("PROVIDER_STREAM_ID_DRIFT", request_started=True)
                self.native_id = event_id
            if isinstance(event.get("usage"), dict):
                self.usage = event["usage"]
            choices = event.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                finish_reason = choices[0].get("finish_reason")
                if isinstance(finish_reason, str):
                    self.finish_reason = finish_reason

    def response(self) -> NativeProviderResponse:
        if not self.done:
            raise ProviderTransportError(
                "PROVIDER_STREAM_DONE_MISSING",
                request_started=True,
                native_request_id=self.native_id,
            )
        return _provider_response(
            {
                "id": self.native_id,
                "usage": dict(self.usage or {}),
                "choices": [{"finish_reason": self.finish_reason}],
            }
        )


class OpenCodeCompletionTransport:
    name = "opencode"

    def __init__(self, argv: Sequence[str]) -> None:
        if not argv or not Path(argv[0]).is_absolute():
            raise ValueError("OpenCode argv must start with an absolute executable")
        self._argv = tuple(argv)

    def invoke(
        self,
        request: ProviderRequest,
        capability: DevRunCapability,
    ) -> NativeProviderResponse:
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "OPENAI_BASE_URL": capability.endpoint_identity + "/v1",
            "OPENAI_MODEL": capability.model_id,
            "NO_COLOR": "1",
        }
        try:
            completed = subprocess.run(  # noqa: S603 - argv is explicit and shell is disabled
                list(self._argv),
                input=_canonical(dict(request.payload)),
                capture_output=True,
                check=False,
                timeout=request.timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderTransportError("OPENCODE_TIMEOUT", request_started=True) from exc
        except OSError as exc:
            raise ProviderTransportError("OPENCODE_START_FAILED", request_started=False) from exc
        if completed.returncode != 0:
            raise ProviderTransportError("OPENCODE_EXIT_NONZERO", request_started=True)
        if len(completed.stdout) > _MAX_RESPONSE_BYTES:
            raise ProviderTransportError("OPENCODE_RESPONSE_BOUNDS", request_started=True)
        try:
            value = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderTransportError(
                "OPENCODE_RESPONSE_INVALID_JSON", request_started=True
            ) from exc
        return _provider_response(value)


class ProviderExecutionGateway:
    def __init__(self, manifest_path: Path, ledger_path: Path) -> None:
        self._manifest_path = manifest_path
        self._ledger_path = ledger_path

    def _capability(self) -> DevRunCapability:
        return DevRunCapability.load(self._manifest_path)

    def _events(self, handle: Any) -> list[dict[str, Any]]:
        handle.seek(0)
        events: list[dict[str, Any]] = []
        previous = "0" * 64
        for sequence, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderExecutionError("provider ledger contains invalid JSON") from exc
            if not isinstance(event, dict):
                raise ProviderExecutionError("provider ledger event is not an object")
            event_digest = event.get("event_sha256")
            unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
            if (
                event.get("sequence") != sequence
                or event.get("previous_sha256") != previous
                or not isinstance(event_digest, str)
                or _digest(unsigned) != event_digest
            ):
                raise ProviderExecutionError("provider ledger hash chain is invalid")
            events.append(event)
            previous = event_digest
        return events

    def _locked(self) -> Any:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self._ledger_path, os.O_RDWR | os.O_CREAT, 0o600)
        handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _append(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._locked() as handle:
            events = self._events(handle)
            native_request_id = value.get("native_request_id")
            if (
                value.get("event") == "PROVIDER_TERMINAL"
                and isinstance(native_request_id, str)
                and any(
                    event.get("event") == "PROVIDER_TERMINAL"
                    and event.get("native_request_id") == native_request_id
                    for event in events
                )
            ):
                value = {
                    **value,
                    "status": "POLICY_VIOLATION",
                    "reason_code": "DUPLICATE_NATIVE_REQUEST_ID",
                }
            previous = events[-1]["event_sha256"] if events else "0" * 64
            event = {
                "sequence": len(events) + 1,
                "previous_sha256": previous,
                "timestamp": _timestamp(),
                **value,
            }
            event["event_sha256"] = _digest(event)
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return event

    def _reserve(
        self,
        capability: DevRunCapability,
        request: ProviderRequest,
    ) -> None:
        request.validate(capability)
        if request.timeout_seconds > (capability.deadline - _now()).total_seconds():
            raise CapabilityError("provider timeout exceeds the DEV_RUN deadline")
        with self._locked() as handle:
            events = self._events(handle)
            reservations = [event for event in events if event.get("event") == "RESERVED"]
            if any(
                event.get("logical_request_id") == request.logical_request_id
                for event in reservations
            ):
                raise BudgetError("logical_request_id is already reserved")
            if len(reservations) >= capability.max_native_requests:
                raise BudgetError("native request budget is exhausted")
            prompt_reserved = sum(int(event["prompt_token_budget"]) for event in reservations)
            completion_reserved = sum(
                int(event["completion_token_budget"]) for event in reservations
            )
            if prompt_reserved + request.prompt_token_budget > capability.max_prompt_tokens:
                raise BudgetError("prompt token budget is exhausted")
            if (
                completion_reserved + request.completion_token_budget
                > capability.max_completion_tokens
            ):
                raise BudgetError("completion token budget is exhausted")
            previous = events[-1]["event_sha256"] if events else "0" * 64
            event = {
                "sequence": len(events) + 1,
                "previous_sha256": previous,
                "timestamp": _timestamp(),
                "event": "RESERVED",
                "run_id": capability.run_id,
                "manifest_sha256": capability.manifest_sha256,
                "logical_request_id": request.logical_request_id,
                "transport": request.transport,
                "endpoint_identity": capability.endpoint_identity,
                "model_id": capability.model_id,
                "prompt_sha256": _digest(dict(request.payload)),
                "prompt_token_budget": request.prompt_token_budget,
                "completion_token_budget": request.completion_token_budget,
                "deadline": _timestamp(capability.deadline),
            }
            event["event_sha256"] = _digest(event)
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def execute(
        self,
        request: ProviderRequest,
        transport: ProviderTransport,
        parser: Callable[[Mapping[str, Any]], T],
    ) -> GatewayResult[T]:
        capability = self._capability()
        if transport.name != request.transport:
            raise CapabilityError("request/transport identity mismatch")
        self._reserve(capability, request)
        try:
            response = transport.invoke(request, capability)
        except ProviderTransportError as exc:
            self._append(
                {
                    "event": "PROVIDER_TERMINAL",
                    "run_id": capability.run_id,
                    "logical_request_id": request.logical_request_id,
                    "transport": request.transport,
                    "status": "FAILED",
                    "reason_code": exc.reason_code,
                    "request_started": exc.request_started,
                    "native_request_id": exc.native_request_id,
                    "native_request_observed": exc.native_request_id is not None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                }
            )
            raise ProviderCallError(exc.reason_code) from exc
        except Exception as exc:
            self._append(
                {
                    "event": "PROVIDER_TERMINAL",
                    "run_id": capability.run_id,
                    "logical_request_id": request.logical_request_id,
                    "transport": request.transport,
                    "status": "FAILED",
                    "reason_code": "TRANSPORT_ADAPTER_EXCEPTION",
                    "request_started": False,
                    "native_request_id": None,
                    "native_request_observed": False,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "exception_type": type(exc).__name__,
                }
            )
            raise ProviderCallError("TRANSPORT_ADAPTER_EXCEPTION") from exc

        policy_violation: str | None = None
        if response.prompt_tokens > request.prompt_token_budget:
            policy_violation = "PROMPT_USAGE_EXCEEDS_RESERVATION"
        elif response.completion_tokens > request.completion_token_budget:
            policy_violation = "COMPLETION_USAGE_EXCEEDS_RESERVATION"
        terminal = self._append(
            {
                "event": "PROVIDER_TERMINAL",
                "run_id": capability.run_id,
                "logical_request_id": request.logical_request_id,
                "transport": request.transport,
                "status": "SUCCEEDED" if policy_violation is None else "POLICY_VIOLATION",
                "reason_code": policy_violation,
                "request_started": True,
                "native_request_id": response.native_request_id,
                "native_request_observed": True,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "finish_reason": response.finish_reason,
            }
        )
        if terminal["reason_code"] == "DUPLICATE_NATIVE_REQUEST_ID":
            policy_violation = "DUPLICATE_NATIVE_REQUEST_ID"
        if policy_violation is not None:
            raise BudgetError(policy_violation)
        try:
            value = parser(response.payload)
        except Exception as exc:
            self._append(
                {
                    "event": "POST_PROVIDER_TERMINAL",
                    "run_id": capability.run_id,
                    "logical_request_id": request.logical_request_id,
                    "status": "FAILED",
                    "reason_code": "ANSWER_PARSE_FAILED",
                    "exception_type": type(exc).__name__,
                }
            )
            raise ProviderCallError("ANSWER_PARSE_FAILED") from exc
        self._append(
            {
                "event": "POST_PROVIDER_TERMINAL",
                "run_id": capability.run_id,
                "logical_request_id": request.logical_request_id,
                "status": "SUCCEEDED",
                "reason_code": None,
            }
        )
        return GatewayResult(
            logical_request_id=request.logical_request_id,
            native_request_id=response.native_request_id,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            finish_reason=response.finish_reason,
            value=value,
        )

    def execute_stream(
        self,
        request: ProviderRequest,
        transport: ProviderStreamTransport,
    ) -> Iterator[bytes]:
        """Reserve and open exactly one upstream SSE request, then proxy its bytes."""
        capability = self._capability()
        if request.transport != "stream" or transport.name != "stream":
            raise CapabilityError("request/transport identity mismatch")
        self._reserve(capability, request)
        try:
            source = transport.open_stream(request, capability)
        except ProviderTransportError as exc:
            self._append_stream_failure(capability, request, exc)
            raise ProviderCallError(exc.reason_code) from exc
        except Exception as exc:
            failure = ProviderTransportError("TRANSPORT_ADAPTER_EXCEPTION", request_started=False)
            self._append_stream_failure(capability, request, failure)
            raise ProviderCallError("TRANSPORT_ADAPTER_EXCEPTION") from exc

        observer = _SseObserver()

        def chunks() -> Iterator[bytes]:
            try:
                for raw_chunk in source:
                    observer.observe(raw_chunk)
                    yield raw_chunk
                response = observer.response()
            except GeneratorExit:
                failure = ProviderTransportError(
                    "PROVIDER_STREAM_CONSUMER_ABORTED",
                    request_started=True,
                    native_request_id=observer.native_id,
                )
                self._append_stream_failure(capability, request, failure)
                raise
            except ProviderTransportError as exc:
                self._append_stream_failure(capability, request, exc)
                raise ProviderCallError(exc.reason_code) from exc
            except Exception as exc:
                failure = ProviderTransportError(
                    "PROVIDER_STREAM_FAILED",
                    request_started=True,
                    native_request_id=observer.native_id,
                )
                self._append_stream_failure(capability, request, failure)
                raise ProviderCallError(failure.reason_code) from exc
            finally:
                close = getattr(source, "close", None)
                if callable(close):
                    close()

            policy_violation: str | None = None
            if response.prompt_tokens > request.prompt_token_budget:
                policy_violation = "PROMPT_USAGE_EXCEEDS_RESERVATION"
            elif response.completion_tokens > request.completion_token_budget:
                policy_violation = "COMPLETION_USAGE_EXCEEDS_RESERVATION"
            terminal = self._append(
                {
                    "event": "PROVIDER_TERMINAL",
                    "run_id": capability.run_id,
                    "logical_request_id": request.logical_request_id,
                    "transport": request.transport,
                    "status": ("SUCCEEDED" if policy_violation is None else "POLICY_VIOLATION"),
                    "reason_code": policy_violation,
                    "request_started": True,
                    "native_request_id": response.native_request_id,
                    "native_request_observed": True,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "finish_reason": response.finish_reason,
                }
            )
            if terminal["reason_code"] == "DUPLICATE_NATIVE_REQUEST_ID":
                policy_violation = "DUPLICATE_NATIVE_REQUEST_ID"
            if policy_violation is not None:
                raise BudgetError(policy_violation)
            self._append(
                {
                    "event": "POST_PROVIDER_TERMINAL",
                    "run_id": capability.run_id,
                    "logical_request_id": request.logical_request_id,
                    "status": "SUCCEEDED",
                    "reason_code": None,
                }
            )

        return chunks()

    def _append_stream_failure(
        self,
        capability: DevRunCapability,
        request: ProviderRequest,
        failure: ProviderTransportError,
    ) -> None:
        self._append(
            {
                "event": "PROVIDER_TERMINAL",
                "run_id": capability.run_id,
                "logical_request_id": request.logical_request_id,
                "transport": request.transport,
                "status": "FAILED",
                "reason_code": failure.reason_code,
                "request_started": failure.request_started,
                "native_request_id": failure.native_request_id,
                "native_request_observed": failure.native_request_id is not None,
                "prompt_tokens": None,
                "completion_tokens": None,
            }
        )

    def next_logical_request_sequence(self) -> int:
        """Return the next Host request sequence from one completed ledger chain."""

        capability = self._capability()
        events = self.read_ledger()
        states: dict[str, dict[str, bool]] = {}
        reservation_count = 0
        for event in events:
            if event.get("run_id") != capability.run_id:
                raise ProviderExecutionError("provider ledger logical request sequence is invalid")
            event_name = event.get("event")
            logical_request_id = event.get("logical_request_id")
            if not isinstance(logical_request_id, str):
                raise ProviderExecutionError("provider ledger logical request sequence is invalid")
            if event_name == "RESERVED":
                reservation_count += 1
                expected = f"{capability.run_id}-ow-{reservation_count:02d}"
                if (
                    logical_request_id != expected
                    or event.get("manifest_sha256") != capability.manifest_sha256
                    or logical_request_id in states
                ):
                    raise ProviderExecutionError(
                        "provider ledger logical request sequence is invalid"
                    )
                states[logical_request_id] = {"terminal": False, "post_terminal": False}
            elif event_name == "PROVIDER_TERMINAL":
                state = states.get(logical_request_id)
                if state is None or state["terminal"]:
                    raise ProviderExecutionError(
                        "provider ledger logical request sequence is invalid"
                    )
                state["terminal"] = True
            elif event_name == "POST_PROVIDER_TERMINAL":
                state = states.get(logical_request_id)
                if state is None or not state["terminal"] or state["post_terminal"]:
                    raise ProviderExecutionError(
                        "provider ledger logical request sequence is invalid"
                    )
                state["post_terminal"] = True
            else:
                raise ProviderExecutionError("provider ledger logical request sequence is invalid")
        if any(not state["terminal"] for state in states.values()):
            raise ProviderExecutionError("provider ledger logical request sequence is invalid")
        return reservation_count + 1

    def read_ledger(self) -> list[dict[str, Any]]:
        if not self._ledger_path.exists():
            return []
        with self._locked() as handle:
            events = self._events(handle)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return events
