from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from milai.application.context import ContextService
from milai.application.errors import EvidenceNotFound, TenantMismatch
from milai.application.evidence import EvidenceService
from milai.application.recollection import RecollectionFacade
from milai.domain.action_identity import action_identity_digest
from milai.domain.chat import ChatRequest, ContextBuildRequest
from milai.domain.retrieval import RetrievalRequest
from milai.persistence import SessionContext
from milai.persistence.context_repository import ContextRepository, RecordChatCommand


@dataclass(frozen=True, slots=True)
class ChatExecution:
    body: dict[str, Any]
    status_code: int = 200


class ChatService:
    def __init__(
        self,
        retrieval_service: RecollectionFacade,
        context_service: ContextService,
        repository: ContextRepository,
        evidence_service: EvidenceService,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._context_service = context_service
        self._repository = repository
        self._evidence_service = evidence_service

    def chat(
        self,
        context: SessionContext,
        request: ChatRequest,
        request_id: str,
    ) -> ChatExecution:
        if request.tenant_id is not None and request.tenant_id != context.tenant_id:
            raise TenantMismatch("body tenant does not match authenticated tenant")
        started = perf_counter()
        fingerprint = _query_fingerprint(context.tenant_id, request.query)
        confirmation_evidence_id = self._live_confirmation(context, request)
        confirmed = confirmation_evidence_id is not None
        if request.action_sensitive and not confirmed:
            answer = "该请求可能改变行动结果; 未收到本次请求的实时确认, 因此已拒绝作答。"
            chat_turn_id = self._record(
                context,
                request,
                request_id,
                fingerprint,
                answer,
                None,
                None,
                [],
                [],
                [],
                "LIVE_CONFIRMATION_REQUIRED",
                started,
            )
            return ChatExecution(
                _chat_body(
                    answer=answer,
                    chat_turn_id=chat_turn_id,
                    capsule_id=None,
                    retrieval_trace_id=None,
                    claims=[],
                    evidence=[],
                    issues=[],
                    authority=request.required_authority,
                    action_sensitive=True,
                    live_confirmation=False,
                    abstained=True,
                    abstention_reason="LIVE_CONFIRMATION_REQUIRED",
                    degraded=[],
                )
            )

        consistency = "CANONICAL_REQUIRED" if request.action_sensitive else request.consistency
        retrieval = self._retrieval_service.retrieve(
            context,
            RetrievalRequest(
                route="L1",
                query=request.query,
                consistency=consistency,
                requested_scope=request.requested_scope,
                required_authority=request.required_authority,
                causal_token=(request.causal_token if consistency == "READ_YOUR_WRITES" else None),
                causal_wait_timeout_ms=request.causal_wait_timeout_ms,
                limit=request.limit,
            ),
            request_id,
            require_user_confirmation=request.action_sensitive,
        )
        if retrieval.status_code == 503:
            body = _chat_body(
                answer="Canonical 存储当前不可用, 无法安全作答。",
                chat_turn_id=None,
                capsule_id=None,
                retrieval_trace_id=None,
                claims=[],
                evidence=[],
                issues=[],
                authority=request.required_authority,
                action_sensitive=request.action_sensitive,
                live_confirmation=confirmed,
                abstained=True,
                abstention_reason="CANONICAL_UNAVAILABLE",
                degraded=list(retrieval.body["degraded_components"]),
            )
            return ChatExecution(body, 503)

        trace_id_value = retrieval.body.get("retrieval_trace_id")
        trace_id = UUID(str(trace_id_value)) if trace_id_value is not None else None
        results = list(retrieval.body["results"])
        if retrieval.body["abstained"] or trace_id is None:
            reason = str(retrieval.body["abstention_reason"])
            answer = "当前没有通过 Canonical Gate 的充分记忆, 已明确弃答。"
            chat_turn_id = self._record(
                context,
                request,
                request_id,
                fingerprint,
                answer,
                None,
                trace_id,
                [],
                [str(confirmation_evidence_id)] if confirmation_evidence_id else [],
                [],
                reason,
                started,
            )
            return ChatExecution(
                _chat_body(
                    answer=answer,
                    chat_turn_id=chat_turn_id,
                    capsule_id=None,
                    retrieval_trace_id=trace_id,
                    claims=[],
                    evidence=([str(confirmation_evidence_id)] if confirmation_evidence_id else []),
                    issues=[],
                    authority=request.required_authority,
                    action_sensitive=request.action_sensitive,
                    live_confirmation=confirmed,
                    abstained=True,
                    abstention_reason=reason,
                    degraded=list(retrieval.body["degraded_components"]),
                )
            )

        capsule = self._context_service.build(
            context,
            ContextBuildRequest(
                retrieval_trace_id=trace_id,
                active_goal=request.active_goal,
                constraints=request.constraints,
                byte_budget=request.byte_budget,
                ttl_seconds=request.ttl_seconds,
            ),
        )
        claims = [str(result["claim_version_id"]) for result in results]
        evidence = sorted(
            {str(item) for result in results for item in result.get("evidence_ids", [])}
            | ({str(confirmation_evidence_id)} if confirmation_evidence_id else set())
        )
        open_issues = cast(list[dict[str, Any]], capsule.sections["OPEN ISSUES"])
        issues = [str(item["issue_id"]) for item in open_issues]
        answer = _compose_answer(results, issues)
        capsule_id = UUID(str(capsule.capsule["capsule_id"]))
        chat_turn_id = self._record(
            context,
            request,
            request_id,
            fingerprint,
            answer,
            capsule_id,
            trace_id,
            claims,
            evidence,
            issues,
            None,
            started,
        )
        body = _chat_body(
            answer=answer,
            chat_turn_id=chat_turn_id,
            capsule_id=capsule_id,
            retrieval_trace_id=trace_id,
            claims=claims,
            evidence=evidence,
            issues=issues,
            authority=request.required_authority,
            action_sensitive=request.action_sensitive,
            live_confirmation=confirmed,
            abstained=False,
            abstention_reason=None,
            degraded=list(retrieval.body["degraded_components"]),
        )
        body["context_compression_level"] = capsule.compression_level
        body["fallback_used"] = retrieval.body["fallback_used"]
        body["fallback_reason"] = retrieval.body["fallback_reason"]
        return ChatExecution(body)

    def _live_confirmation(self, context: SessionContext, request: ChatRequest) -> UUID | None:
        if (
            not request.action_sensitive
            or request.live_confirmation != "CONFIRM_ACTION"
            or request.confirmation_evidence_id is None
            or request.confirmation_nonce is None
        ):
            return None
        try:
            view = self._evidence_service.get(context, request.confirmation_evidence_id)
        except EvidenceNotFound:
            return None
        record = view.record
        now = datetime.now(UTC)
        is_fresh = abs(now - record.observed_at) <= timedelta(minutes=5)
        if request.action_digest is None:
            return None
        binding_digest = action_identity_digest(
            tenant_id=context.tenant_id,
            query=request.query,
            active_goal=request.active_goal,
            requested_scope=request.requested_scope,
            required_authority=request.required_authority,
            action_digest=request.action_digest,
        )
        if (
            record.source_type != "USER_CONFIRMATION"
            or record.source_ref
            != f"chat-confirmation:v2:{request.confirmation_nonce}:{binding_digest}"
            or record.subject_id != "action-sensitive-chat"
            or not is_fresh
            or view.content != "CONFIRM_ACTION"
        ):
            return None
        return record.evidence_id

    def get(self, context: SessionContext, chat_turn_id: UUID) -> dict[str, Any] | None:
        return self._repository.get_chat(context, chat_turn_id)

    def _record(
        self,
        context: SessionContext,
        request: ChatRequest,
        request_id: str,
        fingerprint: str,
        answer: str,
        capsule_id: UUID | None,
        trace_id: UUID | None,
        claims: list[str],
        evidence: list[str],
        issues: list[str],
        abstention_reason: str | None,
        started: float,
    ) -> UUID:
        return self._repository.record_chat(
            context,
            RecordChatCommand(
                request_id=request_id,
                query_fingerprint=fingerprint,
                capsule_id=capsule_id,
                retrieval_trace_id=trace_id,
                answer_text=answer,
                claim_version_ids=claims,
                evidence_refs=evidence,
                issue_refs=issues,
                action_sensitive=request.action_sensitive,
                live_confirmation=(
                    request.action_sensitive
                    and request.confirmation_evidence_id is not None
                    and str(request.confirmation_evidence_id) in evidence
                ),
                abstention_reason=abstention_reason,
                duration_ms=max(0, int((perf_counter() - started) * 1_000)),
            ),
        )


def _query_fingerprint(tenant_id: UUID, query: str) -> str:
    value = json.dumps(
        {"tenant_id": str(tenant_id), "query": query},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _compose_answer(results: list[dict[str, Any]], issue_ids: list[str]) -> str:
    lines = ["基于 Canonical Gate 已验证的当前记忆:"]
    for result in results:
        payload = json.dumps(
            result["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        lines.append(f"- {result['subject_id']} / {result['predicate']}: {payload}")
    if issue_ids:
        lines.append("注意: 当前仍有受保护的 live OpenIssue; 详见关联 issue ID。")
    return "\n".join(lines)


def _chat_body(
    *,
    answer: str,
    chat_turn_id: UUID | None,
    capsule_id: UUID | None,
    retrieval_trace_id: UUID | None,
    claims: list[str],
    evidence: list[str],
    issues: list[str],
    authority: str,
    action_sensitive: bool,
    live_confirmation: bool,
    abstained: bool,
    abstention_reason: str | None,
    degraded: list[str],
) -> dict[str, Any]:
    return {
        "answer": answer,
        "authority_presentation": authority,
        "chat_turn_id": str(chat_turn_id) if chat_turn_id is not None else None,
        "context_capsule_id": str(capsule_id) if capsule_id is not None else None,
        "retrieval_trace_id": (str(retrieval_trace_id) if retrieval_trace_id is not None else None),
        "used_claim_version_ids": claims,
        "evidence_refs": evidence,
        "open_issue_refs": issues,
        "action_sensitive": action_sensitive,
        "live_confirmation": live_confirmation,
        "abstained": abstained,
        "abstention_reason": abstention_reason,
        "degraded_components": degraded,
    }
