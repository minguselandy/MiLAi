"""Opt-in loopback Runtime harness for bounded cross-layer ownership tests.

This is not a deployment entry point. Existing authenticated HTTP routes and
database roles are unchanged; observations never modify a returned response.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from types import TracebackType
from typing import Any

from flask import Response, g, request
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from milai.api import create_app
from milai.config import RuntimeSettings
from milai.config.settings import prepare_runtime_directories
from milai.domain.retrieval_audit import canonical_sha256
from milai.testkit.runtime_owner_trace import RuntimeOwnerTraceObserver


def _reader_gate(body: Mapping[str, Any], http_status: int) -> str:
    """Project the Runtime's released informational Context, never typed authority.

    Unsupported shapes stay UNKNOWN. This is an observation of the existing
    response, not a new admission decision and never an input to execution.
    """
    if http_status >= 400 or body.get("availability") == "UNAVAILABLE":
        return "ERROR"
    issues = body.get("open_issue_ids")
    if body.get("status") in {"DENIED", "CONTESTED"} or (isinstance(issues, list) and issues):
        return "BLOCKED"
    context = body.get("memory_context")
    if not isinstance(context, Mapping):
        return "UNKNOWN"
    selected = context.get("selected_evidence_ids")
    if selected == [] and body.get("status") in {"ABSENT", "ABSTAINED"}:
        return "ABSTAIN"
    if (body.get("reader_evidence_boundary") == "GOVERNANCE_ADMITTED_SOFT_RANKED"
            and body.get("status") in {"HIT", "PARTIAL", "ABSTAINED"}
            and body.get("availability") in {"AVAILABLE", "DEGRADED"}
            and issues == [] and isinstance(selected, list) and selected):
        return "ADMITTED"
    claims = context.get("claim_versions")
    resolution = body.get("resolution")
    canonical_release = (
        body.get("reader_evidence_boundary") == "DECISION_ACCEPTED_ONLY"
        or (body.get("state_view_schema_version") == "memory-state-view-v0.1"
            and isinstance(resolution, Mapping) and resolution.get("correctly_resolved") is True)
    )
    if (canonical_release
            and body.get("status") == "HIT" and body.get("availability") == "AVAILABLE"
            and issues == []
            and context.get("authority_class") in {"CANONICAL_STATE", "MIXED"}
            and isinstance(claims, list) and claims):
        return "ADMITTED"
    return "UNKNOWN"


def _reuse_validation(body: Mapping[str, Any], request_ref: str) -> dict[str, Any] | None:
    """Observe Runtime's successful online receipt validation, not a fresh retrieval.

    Original versions/decision must be joined from the original execution. The
    receipt's issuance position is not substituted for today's validation position.
    """
    if body.get("receipt_reused") is not True:
        return None
    receipt, trace = body.get("context_receipt"), body.get("access_trace")
    if not isinstance(receipt, Mapping) or not isinstance(trace, Mapping):
        raise RuntimeError("OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED")
    capsule_id, trace_id = receipt.get("context_capsule_id"), body.get("trace_id")
    position = trace.get("canonical_position")
    dependency = receipt.get("dependency_digest")
    if (trace.get("terminal_stage") != "REUSE"
            or trace.get("stop_reason") != "CONTEXT_RECEIPT_VALIDATED"
            or trace.get("attempted_stages") != ["REUSE_VALIDATION"]
            or trace.get("retrieval_trace_id") != trace_id
            or "runtime-request:" + canonical_sha256(trace.get("runtime_request_id")) != request_ref
            or receipt.get("schema_version") != "context-receipt-v0.1"
            or not isinstance(receipt.get("requirement_coverage"), Mapping)
            or not isinstance(dependency, str) or len(dependency) != 64
            or any(char not in "0123456789abcdef" for char in dependency)
            or not isinstance(capsule_id, str) or not isinstance(trace_id, str)
            or isinstance(position, bool) or not isinstance(position, int) or position < 0):
        raise RuntimeError("OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED")
    return {
        "runtime_request_ref": request_ref,
        "origin_retrieval_trace_ref": "retrieval:" + canonical_sha256(trace_id),
        "context_capsule_ref": "context-capsule:" + canonical_sha256(capsule_id),
        "validation_canonical_position": position,
        "requirement_coverage_digest": canonical_sha256(receipt.get("requirement_coverage")),
        "dependency_digest": dependency,
    }


class _RequestObserver:
    def __init__(self) -> None:
        self.current: ContextVar[RuntimeOwnerTraceObserver | None] = ContextVar(
            "owner", default=None,
        )

    def capture_product_execution(self, **values: Any) -> None:
        observer = self.current.get()
        if observer is not None:
            observer.capture_product_execution(**values)

    def observe_repository_call(
        self, method: str, args: Sequence[Any], kwargs: Mapping[str, Any], result: Any,
    ) -> None:
        observer = self.current.get()
        if observer is not None:
            observer.observe_repository_call(method, args, kwargs, result)


class _QuietHandler(WSGIRequestHandler):
    def log(self, type: str, message: str, *args: Any) -> None:
        # Neither request URLs nor failure response bodies belong in owner exports.
        pass


class ObservedRuntime:
    """Serial loopback HTTP testkit, scoped to its context-manager lifetime.

    ``config`` is the existing RuntimeSettings mapping, not a new Runtime API.
    Caller owns finite request/time limits and verified Product identity. No worker,
    model, ingest or migration is started by this harness.
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        settings = RuntimeSettings.model_validate(dict(config))
        if settings.environment != "test" or settings.data_mode != "SYNTHETIC_ONLY":
            raise ValueError("OWNER_HARNESS_REQUIRES_SYNTHETIC_TEST_CONFIG")
        if settings.embedding_provider != "deterministic_hash":
            raise ValueError("OWNER_HARNESS_REQUIRES_DETERMINISTIC_EMBEDDING")
        prepare_runtime_directories(settings)
        observer = _RequestObserver()
        self._app = create_app(
            settings, retrieval_audit_observer=observer,
            record_retrieval_audit_repository_calls=True,
        )
        self._reports: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server: BaseWSGIServer | None = None
        self._thread: threading.Thread | None = None

        @self._app.before_request
        def begin() -> None:
            observer.current.set(
                RuntimeOwnerTraceObserver() if request.path == "/v1/memory/resolve" else None
            )

        @self._app.after_request
        def finish(response: Response) -> Response:
            current = observer.current.get()
            if current is None:
                return response
            body = response.get_json(silent=True)
            body = body if isinstance(body, dict) else {}
            context = body.get("memory_context")
            context = context if isinstance(context, dict) else {}
            text = context.get("text")
            selected = context.get("selected_evidence_ids")
            claim_versions = context.get("claim_versions")
            receipt = body.get("context_receipt")
            capsule_id = receipt.get("context_capsule_id") if isinstance(receipt, dict) else None
            dependency = receipt.get("dependency_digest") if isinstance(receipt, dict) else None
            row: dict[str, Any] = {
                "schema_version": "milai-runtime-http-owner-v1",
                "request_ref": "runtime-request:" + canonical_sha256(g.request_id),
                "http_status": response.status_code,
                "reader_gate": _reader_gate(body, response.status_code),
                "receipt_reused": body.get("receipt_reused") is True,
                "owner_trace": None,
                "reuse_validation": None,
                "context_capsule_ref": (
                    "context-capsule:" + canonical_sha256(capsule_id)
                    if isinstance(capsule_id, str) else None
                ),
                "requirement_coverage_digest": (
                    canonical_sha256(receipt["requirement_coverage"])
                    if isinstance(receipt, dict) and isinstance(capsule_id, str)
                    and isinstance(receipt.get("requirement_coverage"), dict) else None
                ),
                "dependency_digest": dependency if (
                    isinstance(dependency, str) and len(dependency) == 64
                    and all(char in "0123456789abcdef" for char in dependency)
                ) else None,
                "observation_gap": None,
                "reader_context_sha256": (
                    hashlib.sha256(text.encode()).hexdigest() if isinstance(text, str) else None
                ),
                "selected_evidence_refs": (
                    ["evidence:" + canonical_sha256(value) for value in selected]
                    if isinstance(selected, list) and all(isinstance(x, str) for x in selected)
                    else None
                ),
                "selected_claim_version_refs": (
                    ["claim-version:" + canonical_sha256(value) for value in claim_versions]
                    if isinstance(claim_versions, list)
                    and all(isinstance(value, str) for value in claim_versions) else None
                ),
                "outcome_status": body.get("status") if body.get("status") in {
                    "HIT", "ABSENT", "PARTIAL", "ABSTAINED", "DENIED", "UNAVAILABLE", "CONTESTED",
                } else None,
                "availability": body.get("availability") if body.get("availability") in {
                    "AVAILABLE", "DEGRADED", "UNAVAILABLE",
                } else None,
                "reader_evidence_boundary": body.get("reader_evidence_boundary")
                if body.get("reader_evidence_boundary") in {
                    "GOVERNANCE_ADMITTED_SOFT_RANKED", "DECISION_ACCEPTED_ONLY",
                } else None,
                "open_issue_count": len(body["open_issue_ids"])
                if isinstance(body.get("open_issue_ids"), list) else None,
            }
            try:
                row["reuse_validation"] = _reuse_validation(body, row["request_ref"])
                if row["reuse_validation"] is None:
                    row["owner_trace"] = current.owner_trace(body)
            except Exception as exc:
                # Observation failure cannot turn the original HTTP result into an
                # error or generate invented facts. Fixed local codes only.
                reason = str(exc)
                row["observation_gap"] = reason if reason in {
                    "OWNER_TRACE_EXECUTION_NOT_OBSERVED", "OWNER_TRACE_RESPONSE_ID_MISMATCH",
                    "OWNER_TRACE_DECISION_NOT_OBSERVED", "OWNER_TRACE_CONTEXT_IDENTITY_INVALID",
                    "OWNER_TRACE_VERSION_CONTENT_CHANGED",
                    "OWNER_TRACE_REUSE_VALIDATION_NOT_OBSERVED",
                } else "OWNER_TRACE_EXPORT_FAILED"
            trace_id = body.get("trace_id")
            row["retrieval_trace_ref"] = (
                "retrieval:" + canonical_sha256(trace_id) if isinstance(trace_id, str) else None
            )
            with self._lock:
                self._reports.append(row)
            observer.current.set(None)
            return response

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("OWNER_HARNESS_NOT_STARTED")
        return f"http://127.0.0.1:{self._server.server_port}"

    def owner_traces(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._reports)

    def __enter__(self) -> ObservedRuntime:
        if self._server is not None:
            raise RuntimeError("OWNER_HARNESS_ALREADY_STARTED")
        self._server = make_server("127.0.0.1", 0, self._app, request_handler=_QuietHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("OWNER_HARNESS_SHUTDOWN_INCOMPLETE")
        self._app.extensions["milai.database"].close()
        self._app.extensions["milai.steward_database"].close()
