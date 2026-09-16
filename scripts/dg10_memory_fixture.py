from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from scripts import dg10_memory_quality as quality
from scripts import dg10_remediation as remediation


class FixtureError(quality.MemoryQualityError):
    pass


@dataclass(frozen=True, slots=True)
class SessionTurn:
    speaker: str
    content: str


@dataclass(frozen=True, slots=True)
class CorpusSession:
    session_id: str
    observed_at: str
    turns: tuple[SessionTurn, ...]

    def render(self) -> str:
        lines = [f"session_id={self.session_id}", f"observed_at={self.observed_at}"]
        lines.extend(f"{turn.speaker}: {turn.content}" for turn in self.turns)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class GovernedObject:
    session_id: str
    evidence_id: str
    proposal_id: str
    decision_id: str
    claim_id: str
    claim_version_id: str


@dataclass(frozen=True, slots=True)
class FixtureReceipt:
    case_id: str
    tenant_class: str
    scope: Mapping[str, Any]
    corpus_session_count: int
    governed_objects: tuple[GovernedObject, ...]
    full_session_corpus: bool
    bypassed_governance: bool


@dataclass(frozen=True, slots=True)
class RecallResult:
    request_id: str
    query: str
    consistency: str
    canonical_gate: bool
    results: tuple[Mapping[str, Any], ...]
    abstained: bool


class CanonicalGateway(Protocol):
    def create_evidence(
        self,
        *,
        case_id: str,
        session: CorpusSession,
        scope: Mapping[str, Any],
    ) -> str: ...

    def create_proposal(
        self,
        *,
        case_id: str,
        session: CorpusSession,
        evidence_id: str,
        scope: Mapping[str, Any],
    ) -> str: ...

    def approve_proposal(self, *, proposal_id: str) -> Mapping[str, str]: ...

    def project(self) -> int: ...

    def recall(
        self,
        *,
        case_id: str,
        query: str,
        scope: Mapping[str, Any],
        limit: int,
    ) -> RecallResult: ...

    def cleanup_case(self, *, case_id: str) -> Mapping[str, Any]: ...


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{label} must be a non-empty string")
    return value


def build_longmemeval_corpus(row: Mapping[str, Any]) -> tuple[CorpusSession, ...]:
    session_ids = row.get("haystack_session_ids")
    dates = row.get("haystack_dates")
    sessions = row.get("haystack_sessions")
    if (
        not isinstance(session_ids, list)
        or not isinstance(dates, list)
        or not isinstance(sessions, list)
        or not session_ids
        or len(session_ids) != len(dates)
        or len(session_ids) != len(sessions)
    ):
        raise FixtureError("LongMemEval full-session arrays are invalid")
    result: list[CorpusSession] = []
    seen: set[str] = set()
    for index, (session_id, observed_at, raw_turns) in enumerate(
        zip(session_ids, dates, sessions, strict=True)
    ):
        identifier = _require_string(session_id, f"session {index} ID")
        if identifier in seen:
            raise FixtureError("LongMemEval session ID is duplicated")
        seen.add(identifier)
        if not isinstance(raw_turns, list) or not raw_turns:
            raise FixtureError("LongMemEval session is empty")
        turns: list[SessionTurn] = []
        for turn_index, raw_turn in enumerate(raw_turns):
            if not isinstance(raw_turn, Mapping):
                raise FixtureError("LongMemEval turn is not an object")
            turns.append(
                SessionTurn(
                    speaker=_require_string(
                        raw_turn.get("role"), f"session {index} turn {turn_index} role"
                    ),
                    content=_require_string(
                        raw_turn.get("content"),
                        f"session {index} turn {turn_index} content",
                    ),
                )
            )
        result.append(
            CorpusSession(
                session_id=identifier,
                observed_at=_require_string(observed_at, f"session {index} date"),
                turns=tuple(turns),
            )
        )
    return tuple(result)


def ingest_full_session_corpus(
    *,
    gateway: CanonicalGateway,
    case_id: str,
    sessions: Sequence[CorpusSession],
    scope: Mapping[str, Any],
) -> FixtureReceipt:
    if not sessions:
        raise FixtureError("full session corpus is empty")
    if not scope.get("project_ids"):
        raise FixtureError("evaluation scope is empty")
    objects: list[GovernedObject] = []
    for session in sessions:
        evidence_id = gateway.create_evidence(
            case_id=case_id,
            session=session,
            scope=scope,
        )
        proposal_id = gateway.create_proposal(
            case_id=case_id,
            session=session,
            evidence_id=evidence_id,
            scope=scope,
        )
        decision = gateway.approve_proposal(proposal_id=proposal_id)
        required = {"decision_id", "claim_id", "claim_version_id"}
        if set(decision) != required or any(
            not isinstance(decision[key], str) or not decision[key]
            for key in required
        ):
            raise FixtureError("governed Decision result is incomplete")
        objects.append(
            GovernedObject(
                session_id=session.session_id,
                evidence_id=evidence_id,
                proposal_id=proposal_id,
                decision_id=decision["decision_id"],
                claim_id=decision["claim_id"],
                claim_version_id=decision["claim_version_id"],
            )
        )
    if gateway.project() < len(sessions):
        raise FixtureError("fixture projection did not cover the full corpus")
    return FixtureReceipt(
        case_id=case_id,
        tenant_class="ISOLATED_EVALUATION_TENANT",
        scope=dict(scope),
        corpus_session_count=len(sessions),
        governed_objects=tuple(objects),
        full_session_corpus=len(objects) == len(sessions),
        bypassed_governance=False,
    )


def _fit_results(
    results: Sequence[Mapping[str, Any]],
    token_counter: quality.TokenCounter,
) -> tuple[str, int, tuple[str, ...]]:
    selected: list[str] = []
    evidence_ids: list[str] = []
    token_count = 0
    for result in results:
        text = result.get("memory_text")
        evidence_id = result.get("evidence_id")
        if not isinstance(text, str) or not text or not isinstance(evidence_id, str):
            raise FixtureError("recall result is missing text or Evidence identity")
        candidate = "\n\n".join([*selected, text])
        candidate_tokens = token_counter.count(candidate)
        if candidate_tokens > quality.MAX_MEMORY_TOKENS:
            continue
        selected.append(text)
        evidence_ids.append(evidence_id)
        token_count = candidate_tokens
    return "\n\n".join(selected), token_count, tuple(evidence_ids)


class GovernedMemoryProvider:
    def __init__(
        self,
        *,
        gateway: CanonicalGateway,
        receipt: FixtureReceipt,
        token_counter: quality.TokenCounter,
    ) -> None:
        if not receipt.full_session_corpus or receipt.bypassed_governance:
            raise FixtureError("fixture receipt does not prove governed full-corpus ingest")
        self.gateway = gateway
        self.receipt = receipt
        self.token_counter = token_counter

    def retrieve(self, *, case_id: str, question: str) -> quality.MemoryContext:
        if case_id != self.receipt.case_id:
            raise FixtureError("fixture/case identity mismatch")
        recall = self.gateway.recall(
            case_id=case_id,
            query=question,
            scope=self.receipt.scope,
            limit=5,
        )
        if (
            recall.query != question
            or recall.consistency != "CANONICAL_REQUIRED"
            or not recall.canonical_gate
            or recall.abstained
        ):
            raise FixtureError("Runtime recall did not use original question/canonical gate")
        text, token_count, evidence_ids = _fit_results(recall.results, self.token_counter)
        return quality.MemoryContext(
            arm="MILAI_RETRIEVAL",
            text=text,
            target_token_count=token_count,
            evidence_ids=evidence_ids,
            retrieval_request_id=recall.request_id,
            retrieval_receipt_sha256=hashlib.sha256(
                json.dumps(
                    {
                        "request_id": recall.request_id,
                        "query": recall.query,
                        "consistency": recall.consistency,
                        "canonical_gate": recall.canonical_gate,
                        "results": list(recall.results),
                        "abstained": recall.abstained,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            query_sha256=hashlib.sha256(question.encode()).hexdigest(),
            query_equals_original_question=True,
            ranking_source="MILAI_RUNTIME_CANONICAL_GATE",
            governed_ingest=True,
            canonical_gate=True,
            full_session_corpus=True,
            artificial_marker=False,
            shared_naive_ranking=False,
        )


def retrieval_metrics(
    ranked_session_ids: Sequence[str],
    relevant_session_ids: Sequence[str],
) -> dict[str, float]:
    if (
        any(not isinstance(item, str) or not item for item in ranked_session_ids)
        or any(not isinstance(item, str) or not item for item in relevant_session_ids)
        or len(ranked_session_ids) != len(set(ranked_session_ids))
        or len(relevant_session_ids) != len(set(relevant_session_ids))
    ):
        raise FixtureError("retrieval metric identities are invalid or duplicated")
    relevant = set(relevant_session_ids)
    if not relevant:
        raise FixtureError("retrieval metric requires at least one relevant session")
    metrics: dict[str, float] = {}
    for k in (1, 3, 5):
        selected = list(ranked_session_ids[:k])
        hits = sum(item in relevant for item in selected)
        metrics[f"recall_at_{k}"] = hits / len(relevant)
        metrics[f"precision_at_{k}"] = hits / k
    rank = next(
        (index for index, item in enumerate(ranked_session_ids, start=1) if item in relevant),
        None,
    )
    metrics["mrr"] = 0.0 if rank is None else 1.0 / rank
    return metrics


def safe_cleanup(gateway: CanonicalGateway, *, case_id: str) -> dict[str, Any]:
    result = gateway.cleanup_case(case_id=case_id)
    if (
        result.get("canonical_rows_remaining") != 0
        or result.get("projection_rows_remaining") != 0
        or result.get("blob_bytes_remaining") != 0
        or result.get("status") != "PASS_NO_EVALUATION_DATA_REMAINS"
    ):
        raise FixtureError("evaluation tenant cleanup is incomplete")
    return dict(result)


def synthetic_fixture_report() -> dict[str, Any]:
    fixtures = (
        "KNOWLEDGE_UPDATE_LATEST_VALID_STATE",
        "TEMPORAL_SCOPE",
        "OPEN_ISSUE_FALSE_CERTAINTY",
        "REVOKED_EVIDENCE",
        "CANONICAL_UNAVAILABLE_ABSTENTION",
    )
    return {
        "schema": "milai.dg10.memory-fixture-synthetic-contract.v1",
        "candidate_id": remediation.CANDIDATE,
        "fixture_count": len(fixtures),
        "fixtures": list(fixtures),
        "full_session_corpus_required": True,
        "normal_governance_required": True,
        "original_question_query_required": True,
        "marker_allowed": False,
        "shared_naive_ranking_allowed": False,
        "status": "PASS_STATIC_CONTRACT",
    }
