from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx

from milai_client.models import (
    CapabilityDocument,
    CausalToken,
    ClaimEnvelope,
    ContextEnvelope,
    ContextRequest,
    DeletionReceipt,
    EpisodeReceipt,
    EvidenceCaptureRequest,
    EvidenceReceipt,
    ExactRecallRequest,
    HealthStatus,
    MemoryResolveEnvelope,
    MemoryStateViewEnvelope,
    OpenIssueEnvelope,
    PartialProposalOutcome,
    PrepareContextEnvelope,
    PrepareContextRequest,
    ProposalDraft,
    ProposalReceipt,
    ProposalReviewReceipt,
    RecallEnvelope,
    RecallRequest,
    RetrievalTraceEnvelope,
    RevocationRequest,
    SystemWatermarks,
)

_NO_ACCEPTED_HTTP_STATUSES: frozenset[int] = frozenset()
_PREPARE_CONTEXT_TERMINAL_HTTP_STATUSES = frozenset({429, 503})


class MilaiClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "CLIENT_ERROR",
        retryable: bool = False,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.request_id = request_id
        self.details = details or {}


class IncompatibleRuntimeError(MilaiClientError):
    pass


class AuthenticationError(MilaiClientError):
    pass


class AuthorizationError(MilaiClientError):
    pass


class ConflictError(MilaiClientError):
    pass


class UnavailableError(MilaiClientError):
    pass


@dataclass(frozen=True, slots=True)
class _Response:
    status: int
    body: dict[str, Any]


class AsyncTransport(Protocol):
    async def send(
        self,
        method: str,
        path: str,
        data: bytes | None,
        headers: Mapping[str, str],
    ) -> _Response: ...

    async def close(self) -> None: ...


class _HttpStatusError(Exception):
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class HttpxAsyncTransport:
    """Persistent bounded transport; one instance must stay on one event loop."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def send(
        self,
        method: str,
        path: str,
        data: bytes | None,
        headers: Mapping[str, str],
    ) -> _Response:
        response = await self._client.request(method, path, content=data, headers=headers)
        body = _json_object(response.content, allow_invalid=response.status_code >= 400)
        if response.status_code >= 400:
            raise _HttpStatusError(response.status_code, body)
        return _Response(response.status_code, body)

    async def close(self) -> None:
        await self._client.aclose()


class AsyncMilaiClient:
    """The sole implementation of MiLAi Agent HTTP and retry semantics."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        allow_remote: bool = False,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        transport: AsyncTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("MILAI_BASE_URL", "http://127.0.0.1:18080")
        ).rstrip("/")
        self._token = token or os.environ.get("MILAI_AGENT_TOKEN", "")
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._capability_document: CapabilityDocument | None = None
        self._closed = False
        self._validate_endpoint(allow_remote)
        if len(self._token) < 32:
            raise MilaiClientError("MILAI_AGENT_TOKEN is missing or too short")
        legacy_override = type(self)._send_once is not AsyncMilaiClient._send_once
        self._transport = (
            transport
            if transport is not None
            else (None if legacy_override else HttpxAsyncTransport(self.base_url, self._timeout))
        )

    def _validate_endpoint(self, allow_remote: bool) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise MilaiClientError("base_url must be an HTTP(S) origin without credentials")
        try:
            local = (
                parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
            )
        except ValueError:
            local = False
        if not local and not allow_remote:
            raise MilaiClientError("non-loopback MiLAi endpoints are disabled by default")

    async def capabilities(self) -> CapabilityDocument:
        body = (await self._request("GET", "/v1/capabilities", negotiate=False)).body
        document = CapabilityDocument.from_api(body)
        if not document.compatible:
            raise IncompatibleRuntimeError(
                "MiLAi Runtime is not compatible with agent.v1",
                code="INCOMPATIBLE_RUNTIME",
            )
        self._capability_document = document
        return document

    async def _ensure_compatible(self) -> CapabilityDocument:
        return self._capability_document or await self.capabilities()

    async def health(self) -> HealthStatus:
        live, ready = await asyncio.gather(
            self._request("GET", "/health/live", negotiate=False),
            self._request("GET", "/health/ready", negotiate=False),
        )
        dependencies = ready.body.get("dependencies")
        return HealthStatus(
            live=live.body.get("status") == "ok",
            ready=ready.body.get("status") == "ready",
            dependencies=(
                {str(key): str(value) for key, value in dependencies.items()}
                if isinstance(dependencies, dict)
                else {}
            ),
            schema_status=str(live.body.get("schema_status", "")),
            implementation_status=str(live.body.get("implementation_status", "")),
            raw_live=live.body,
            raw_ready=ready.body,
        )

    async def system_watermarks(self) -> SystemWatermarks:
        body = (await self._request("GET", "/v1/system/watermarks")).body
        try:
            return SystemWatermarks.from_api(body)
        except ValueError as exc:
            raise MilaiClientError(
                "MiLAi returned invalid system watermarks",
                code="INVALID_RUNTIME_RESPONSE",
            ) from exc

    async def wait_for_projection_readiness(
        self,
        *,
        target_outbox_id: str | None = None,
        target_outbox_ids: list[str] | None = None,
        required_projections: list[str],
        expected_versions: Mapping[str, str],
        timeout_ms: int = 15_000,
        poll_interval_ms: int = 25,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "required_projections": required_projections,
            "expected_versions": dict(expected_versions),
            "timeout_ms": timeout_ms,
            "poll_interval_ms": poll_interval_ms,
        }
        if target_outbox_id is not None:
            payload["target_outbox_id"] = target_outbox_id
        if target_outbox_ids is not None:
            payload["target_outbox_ids"] = target_outbox_ids
        return (
            await self._request(
                "POST",
                "/v1/system/projection-readiness",
                payload,
                accepted_statuses=frozenset({408, 409}),
            )
        ).body

    async def recall(self, request: RecallRequest | str, **options: Any) -> RecallEnvelope:
        payload = (
            request.to_api()
            if isinstance(request, RecallRequest)
            else {
                "route": "L1",
                "query": request,
                **options,
            }
        )
        return RecallEnvelope.from_api(
            (await self._request("POST", "/v1/memory/query", payload)).body
        )

    async def recall_exact(
        self, request: ExactRecallRequest | None = None, **options: Any
    ) -> RecallEnvelope:
        payload = request.to_api() if request is not None else {"route": "L0", **options}
        payload = {key: value for key, value in payload.items() if value is not None}
        return RecallEnvelope.from_api(
            (await self._request("POST", "/v1/memory/query", payload)).body
        )

    async def resolve_memory(
        self,
        query: str,
        *,
        task_context: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> MemoryResolveEnvelope:
        payload = {"query": query, **options}
        if task_context is not None:
            payload["task_context"] = dict(task_context)
        body = (
            await self._request(
                "POST",
                "/v1/memory/resolve",
                payload,
                accepted_statuses=frozenset({503}),
            )
        ).body
        try:
            return MemoryResolveEnvelope.from_api(body)
        except ValueError as exc:
            raise MilaiClientError(
                "MiLAi returned an invalid memory resolve result",
                code="INVALID_RUNTIME_RESPONSE",
            ) from exc

    async def get_memory(
        self,
        *,
        claim_id: str | None = None,
        state_key: Mapping[str, str] | None = None,
        **options: Any,
    ) -> MemoryStateViewEnvelope:
        payload: dict[str, Any] = dict(options)
        if claim_id is not None:
            payload["claim_id"] = claim_id
        if state_key is not None:
            payload["state_key"] = dict(state_key)
        body = (
            await self._request(
                "POST",
                "/v1/memory/get",
                payload,
                accepted_statuses=frozenset({503}),
            )
        ).body
        try:
            return MemoryStateViewEnvelope.from_api(body)
        except ValueError as exc:
            raise MilaiClientError(
                "MiLAi returned an invalid memory state view",
                code="INVALID_RUNTIME_RESPONSE",
            ) from exc

    async def build_context(self, request: ContextRequest | dict[str, Any]) -> ContextEnvelope:
        payload = request.to_api() if isinstance(request, ContextRequest) else request
        return ContextEnvelope.from_api(
            (await self._request("POST", "/v1/context-capsules", payload)).body
        )

    async def prepare_context(
        self, request: PrepareContextRequest | dict[str, Any]
    ) -> PrepareContextEnvelope:
        payload = request.to_api() if isinstance(request, PrepareContextRequest) else request
        return PrepareContextEnvelope.from_api(
            (
                await self._request(
                    "POST",
                    "/v1/memory/prepare-context",
                    payload,
                    accepted_statuses=_PREPARE_CONTEXT_TERMINAL_HTTP_STATUSES,
                )
            ).body
        )

    async def prepare_memory_context(
        self, request: PrepareContextRequest | dict[str, Any]
    ) -> PrepareContextEnvelope:
        """Semantic alias for the one-wire governed memory context operation."""
        return await self.prepare_context(request)

    async def get_claim(self, claim_id: str) -> ClaimEnvelope:
        return ClaimEnvelope.from_api((await self._request("GET", f"/v1/claims/{claim_id}")).body)

    async def list_open_issues(self, status: str | None = None) -> list[OpenIssueEnvelope]:
        suffix = f"?{urlencode({'status': status})}" if status else ""
        body = (await self._request("GET", f"/v1/open-issues{suffix}")).body
        issues = body.get("issues")
        return (
            [
                OpenIssueEnvelope.from_api(item)
                for item in issues
                if isinstance(issues, list) and isinstance(item, dict)
            ]
            if isinstance(issues, list)
            else []
        )

    async def get_open_issue(self, issue_id: str) -> OpenIssueEnvelope:
        return OpenIssueEnvelope.from_api(
            (await self._request("GET", f"/v1/open-issues/{issue_id}")).body
        )

    async def get_trace(self, trace_id: str) -> RetrievalTraceEnvelope:
        body = (await self._request("GET", f"/v1/retrieval-traces/{trace_id}")).body
        return RetrievalTraceEnvelope.from_api(body)

    async def get_evidence_metadata(self, evidence_id: str) -> dict[str, Any]:
        body = (await self._request("GET", f"/v1/evidence/{evidence_id}")).body
        body.pop("content", None)
        return body

    async def capture_evidence(
        self, payload: EvidenceCaptureRequest | dict[str, Any], *, operation_id: str
    ) -> EvidenceReceipt:
        body_payload = (
            payload.model_dump(mode="json", exclude_none=True)
            if isinstance(payload, EvidenceCaptureRequest)
            else payload
        )
        body = (
            await self._request("POST", "/v1/evidence", body_payload, operation_id=operation_id)
        ).body
        return EvidenceReceipt.from_api(body)

    async def create_proposal(
        self, payload: ProposalDraft | dict[str, Any], *, operation_id: str
    ) -> ProposalReceipt:
        body_payload = payload.to_api() if isinstance(payload, ProposalDraft) else payload
        body = (
            await self._request("POST", "/v1/proposals", body_payload, operation_id=operation_id)
        ).body
        return ProposalReceipt.from_api(body)

    async def list_proposals(
        self,
        status: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = {"limit": str(limit)}
        if status is not None:
            query["status"] = status
        body = (
            await self._request("GET", "/v1/proposals?" + urlencode(query))
        ).body
        proposals = body.get("proposals")
        if not isinstance(proposals, list):
            return []
        return [dict(item) for item in proposals if isinstance(item, dict)]

    async def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        return (
            await self._request("GET", f"/v1/proposals/{proposal_id}")
        ).body

    async def review_proposal(
        self,
        proposal_id: str,
        payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> ProposalReviewReceipt:
        body = (
            await self._request(
                "POST",
                f"/v1/proposals/{proposal_id}/review",
                payload,
                operation_id=operation_id,
            )
        ).body
        return ProposalReviewReceipt.from_api(body)

    async def propose_from_observation(
        self,
        evidence_payload: dict[str, Any],
        proposal_payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> PartialProposalOutcome:
        evidence = await self.capture_evidence(
            evidence_payload, operation_id=_derived_operation_id(operation_id, "evidence")
        )
        proposal = dict(proposal_payload)
        proposal.setdefault("supporting_evidence_refs", [evidence.evidence_id])
        draft = ProposalDraft.model_validate(proposal)
        if draft.target_claim_id is not None:
            current = await self.get_claim(draft.target_claim_id)
            draft.validate_current_head(current.claim_version_id)
        try:
            receipt = await self.create_proposal(
                draft, operation_id=_derived_operation_id(operation_id, "proposal")
            )
        except MilaiClientError as error:
            return PartialProposalOutcome(evidence, None, error.code)
        return PartialProposalOutcome(evidence, receipt, None)

    async def revoke_evidence(
        self,
        evidence_id: str,
        payload: RevocationRequest | dict[str, Any],
        *,
        operation_id: str,
    ) -> DeletionReceipt:
        body_payload = (
            payload.model_dump(mode="json") if isinstance(payload, RevocationRequest) else payload
        )
        body = (
            await self._request(
                "POST",
                f"/v1/evidence/{evidence_id}/revoke",
                body_payload,
                operation_id=operation_id,
            )
        ).body
        return DeletionReceipt.from_api(body)

    async def create_episode(
        self,
        *,
        subject_id: str,
        evidence_refs: list[str] | None = None,
        chat_turn_refs: list[str] | None = None,
        context_capsule_refs: list[str] | None = None,
        operation_id: str,
    ) -> EpisodeReceipt:
        payload = {
            "subject_id": subject_id,
            "evidence_refs": evidence_refs or [],
            "chat_turn_refs": chat_turn_refs or [],
            "context_capsule_refs": context_capsule_refs or [],
        }
        body = (
            await self._request("POST", "/v1/episodes", payload, operation_id=operation_id)
        ).body
        return EpisodeReceipt.from_api(body)

    async def deletion_status(self, evidence_id: str) -> dict[str, Any]:
        return (await self._request("GET", f"/v1/evidence/{evidence_id}/deletion-status")).body

    async def submit_namespace_cleanup(
        self,
        *,
        project_id: str,
        reason_code: str,
        operation_id: str,
    ) -> dict[str, Any]:
        return (
            await self._request(
                "POST",
                "/v1/namespace-cleanups",
                {
                    "project_id": project_id,
                    "reason_code": reason_code,
                    "confirmation": "CLEANUP_NAMESPACE",
                },
                operation_id=operation_id,
            )
        ).body

    async def namespace_cleanup_status(
        self,
        cleanup_job_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urlencode({"offset": str(offset), "limit": str(limit)})
        return (
            await self._request(
                "GET", f"/v1/namespace-cleanups/{cleanup_job_id}?{query}"
            )
        ).body

    async def issue_causal_token(self, outbox_ids: list[str]) -> CausalToken:
        body = (await self._request("POST", "/v1/causal-tokens", {"outbox_ids": outbox_ids})).body
        return CausalToken.from_api(body)

    async def close(self) -> None:
        if self._closed:
            return
        if self._transport is not None:
            await self._transport.close()
        self._closed = True
        self._capability_document = None

    async def __aenter__(self) -> AsyncMilaiClient:
        if self._closed:
            raise MilaiClientError("MiLAi client is closed", code="CLIENT_CLOSED")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        operation_id: str | None = None,
        negotiate: bool = True,
        accepted_statuses: frozenset[int] = _NO_ACCEPTED_HTTP_STATUSES,
    ) -> _Response:
        if self._closed:
            raise MilaiClientError("MiLAi client is closed", code="CLIENT_CLOSED")
        if negotiate:
            await self._ensure_compatible()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "X-Request-ID": str(uuid4()),
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if operation_id is not None:
            if not 1 <= len(operation_id) <= 128:
                raise MilaiClientError(
                    "operation_id must contain between 1 and 128 characters",
                    code="INVALID_OPERATION_ID",
                )
            headers["Idempotency-Key"] = operation_id
        retry_safe = method == "GET" or operation_id is not None
        for attempt in range(self._max_retries + 1):
            try:
                if self._transport is not None:
                    return await self._transport.send(method, path, data, headers)
                return await asyncio.to_thread(self._send_once, method, path, data, headers)
            except _HttpStatusError as exc:
                if exc.status in accepted_statuses:
                    return _Response(exc.status, exc.body)
                raw_error = exc.body.get("error")
                error = raw_error if isinstance(raw_error, dict) else {}
                retryable = (exc.status in {429, 503} or bool(error.get("retryable"))) and (
                    exc.status != 409
                )
                if retry_safe and retryable and attempt < self._max_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                raise _typed_error(exc.status, error, exc.body) from exc
            except HTTPError as exc:
                body = _json_object(exc.read(), allow_invalid=True)
                if exc.code in accepted_statuses:
                    return _Response(exc.code, body)
                raw_error = body.get("error")
                error = raw_error if isinstance(raw_error, dict) else {}
                retryable = (exc.code in {429, 503} or bool(error.get("retryable"))) and (
                    exc.code != 409
                )
                if retry_safe and retryable and attempt < self._max_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                raise _typed_error(exc.code, error, body) from exc
            except (httpx.TransportError, URLError, TimeoutError, OSError) as exc:
                if retry_safe and attempt < self._max_retries:
                    await asyncio.sleep(0.1 * (2**attempt))
                    continue
                raise UnavailableError(
                    "MiLAi endpoint is unavailable", code="ENDPOINT_UNAVAILABLE", retryable=True
                ) from exc
        raise AssertionError("unreachable")

    def _send_once(
        self, method: str, path: str, data: bytes | None, headers: dict[str, str]
    ) -> _Response:
        request = Request(  # noqa: S310 -- constructor validated the origin
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            return _Response(response.status, _json_object(response.read()))


T = TypeVar("T")


class MilaiClient:
    """Thin synchronous facade; all behavior is implemented by AsyncMilaiClient."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        async_client = AsyncMilaiClient(*args, **kwargs)
        self._loop = asyncio.new_event_loop()
        self._loop_lock = RLock()
        self._async = async_client

    def _run(self, coroutine: Coroutine[Any, Any, T]) -> T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            coroutine.close()
            raise MilaiClientError(
                "synchronous MiLAi client cannot run inside an active event loop; "
                "use AsyncMilaiClient",
                code="SYNC_CLIENT_IN_ASYNC_CONTEXT",
            )
        if self._loop.is_closed():
            coroutine.close()
            raise MilaiClientError("MiLAi client is closed", code="CLIENT_CLOSED")
        with self._loop_lock:
            return self._loop.run_until_complete(coroutine)

    @property
    def base_url(self) -> str:
        return self._async.base_url

    def capabilities(self) -> CapabilityDocument:
        return self._run(self._async.capabilities())

    def health(self) -> HealthStatus:
        return self._run(self._async.health())

    def system_watermarks(self) -> SystemWatermarks:
        return self._run(self._async.system_watermarks())

    def wait_for_projection_readiness(
        self,
        *,
        target_outbox_id: str | None = None,
        target_outbox_ids: list[str] | None = None,
        required_projections: list[str],
        expected_versions: Mapping[str, str],
        timeout_ms: int = 15_000,
        poll_interval_ms: int = 25,
    ) -> dict[str, Any]:
        return self._run(
            self._async.wait_for_projection_readiness(
                target_outbox_id=target_outbox_id,
                target_outbox_ids=target_outbox_ids,
                required_projections=required_projections,
                expected_versions=expected_versions,
                timeout_ms=timeout_ms,
                poll_interval_ms=poll_interval_ms,
            )
        )

    def recall(self, request: RecallRequest | str, **options: Any) -> RecallEnvelope:
        return self._run(self._async.recall(request, **options))

    def recall_exact(
        self, request: ExactRecallRequest | None = None, **options: Any
    ) -> RecallEnvelope:
        return self._run(self._async.recall_exact(request, **options))

    def resolve_memory(
        self,
        query: str,
        *,
        task_context: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> MemoryResolveEnvelope:
        return self._run(
            self._async.resolve_memory(
                query,
                task_context=task_context,
                **options,
            )
        )

    def get_memory(
        self,
        *,
        claim_id: str | None = None,
        state_key: Mapping[str, str] | None = None,
        **options: Any,
    ) -> MemoryStateViewEnvelope:
        return self._run(
            self._async.get_memory(claim_id=claim_id, state_key=state_key, **options)
        )

    def build_context(self, request: ContextRequest | dict[str, Any]) -> ContextEnvelope:
        return self._run(self._async.build_context(request))

    def prepare_context(
        self, request: PrepareContextRequest | dict[str, Any]
    ) -> PrepareContextEnvelope:
        return self._run(self._async.prepare_context(request))

    def prepare_memory_context(
        self, request: PrepareContextRequest | dict[str, Any]
    ) -> PrepareContextEnvelope:
        return self._run(self._async.prepare_memory_context(request))

    def get_claim(self, claim_id: str) -> ClaimEnvelope:
        return self._run(self._async.get_claim(claim_id))

    def list_open_issues(self, status: str | None = None) -> list[OpenIssueEnvelope]:
        return self._run(self._async.list_open_issues(status))

    def get_open_issue(self, issue_id: str) -> OpenIssueEnvelope:
        return self._run(self._async.get_open_issue(issue_id))

    def get_trace(self, trace_id: str) -> RetrievalTraceEnvelope:
        return self._run(self._async.get_trace(trace_id))

    def get_evidence_metadata(self, evidence_id: str) -> dict[str, Any]:
        return self._run(self._async.get_evidence_metadata(evidence_id))

    def capture_evidence(
        self, payload: EvidenceCaptureRequest | dict[str, Any], *, operation_id: str
    ) -> EvidenceReceipt:
        return self._run(self._async.capture_evidence(payload, operation_id=operation_id))

    def create_proposal(
        self, payload: ProposalDraft | dict[str, Any], *, operation_id: str
    ) -> ProposalReceipt:
        return self._run(self._async.create_proposal(payload, operation_id=operation_id))

    def list_proposals(
        self,
        status: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._run(self._async.list_proposals(status, limit=limit))

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self._run(self._async.get_proposal(proposal_id))

    def review_proposal(
        self,
        proposal_id: str,
        payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> ProposalReviewReceipt:
        return self._run(
            self._async.review_proposal(
                proposal_id,
                payload,
                operation_id=operation_id,
            )
        )

    def propose_from_observation(
        self,
        evidence_payload: dict[str, Any],
        proposal_payload: dict[str, Any],
        *,
        operation_id: str,
    ) -> PartialProposalOutcome:
        return self._run(
            self._async.propose_from_observation(
                evidence_payload, proposal_payload, operation_id=operation_id
            )
        )

    def revoke_evidence(
        self,
        evidence_id: str,
        payload: RevocationRequest | dict[str, Any],
        *,
        operation_id: str,
    ) -> DeletionReceipt:
        return self._run(
            self._async.revoke_evidence(evidence_id, payload, operation_id=operation_id)
        )

    def create_episode(
        self,
        *,
        subject_id: str,
        evidence_refs: list[str] | None = None,
        chat_turn_refs: list[str] | None = None,
        context_capsule_refs: list[str] | None = None,
        operation_id: str,
    ) -> EpisodeReceipt:
        return self._run(
            self._async.create_episode(
                subject_id=subject_id,
                evidence_refs=evidence_refs,
                chat_turn_refs=chat_turn_refs,
                context_capsule_refs=context_capsule_refs,
                operation_id=operation_id,
            )
        )

    def deletion_status(self, evidence_id: str) -> dict[str, Any]:
        return self._run(self._async.deletion_status(evidence_id))

    def submit_namespace_cleanup(
        self,
        *,
        project_id: str,
        reason_code: str,
        operation_id: str,
    ) -> dict[str, Any]:
        return self._run(
            self._async.submit_namespace_cleanup(
                project_id=project_id,
                reason_code=reason_code,
                operation_id=operation_id,
            )
        )

    def namespace_cleanup_status(
        self,
        cleanup_job_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._run(
            self._async.namespace_cleanup_status(
                cleanup_job_id, offset=offset, limit=limit
            )
        )

    def issue_causal_token(self, outbox_ids: list[str]) -> CausalToken:
        return self._run(self._async.issue_causal_token(outbox_ids))

    def close(self) -> None:
        if self._loop.is_closed():
            return
        self._run(self._async.close())
        self._loop.close()


def _typed_error(status: int, error: dict[str, Any], body: dict[str, Any]) -> MilaiClientError:
    code = str(error.get("code", "HTTP_ERROR"))
    error_type: type[MilaiClientError]
    if status == 401:
        error_type = AuthenticationError
    elif status == 403:
        error_type = AuthorizationError
    elif status == 409:
        error_type = ConflictError
    elif status in {429, 503}:
        error_type = UnavailableError
    else:
        error_type = MilaiClientError
    details = error.get("details")
    return error_type(
        str(error.get("message", "MiLAi request failed")),
        status_code=status,
        code=code,
        retryable=status != 409 and (bool(error.get("retryable", False)) or status in {429, 503}),
        request_id=_string_or_none(body.get("request_id")),
        details=details if isinstance(details, dict) else None,
    )


def _derived_operation_id(value: str, suffix: str) -> str:
    candidate = f"{value}:{suffix}"
    if 1 <= len(candidate) <= 128:
        return candidate
    return "agent-v1-" + hashlib.sha256(candidate.encode()).hexdigest()


def _json_object(raw: bytes, *, allow_invalid: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if allow_invalid:
            return {}
        raise MilaiClientError("MiLAi returned invalid JSON") from None
    if not isinstance(value, dict):
        raise MilaiClientError("MiLAi returned a non-object response")
    return value


def _string_or_none(value: object) -> str | None:
    return str(value) if value is not None else None
