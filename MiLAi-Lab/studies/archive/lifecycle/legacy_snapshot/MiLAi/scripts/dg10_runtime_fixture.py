from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.agent_integration import e2e
from scripts import dg10_memory_fixture as fixture
from scripts import dg10_remediation as remediation


class RuntimeCanonicalGateway:
    """CanonicalGateway backed by the real Runtime API, worker, and MCP host."""

    def __init__(
        self,
        *,
        client: e2e._HttpClient,
        worker: e2e.FoundationWorker,
        base_url: str,
        tokens: Mapping[str, str],
        run_id: str,
        expected_scope: Mapping[str, Any],
        ledger: remediation.AttemptLedger | None = None,
    ) -> None:
        self.client = client
        self.worker = worker
        self.base_url = base_url
        self.tokens = tokens
        self.run_id = run_id
        self.expected_scope = dict(expected_scope)
        self.ledger = ledger
        self._proposal_sessions: dict[str, tuple[str, fixture.CorpusSession]] = {}
        self._projected = 0
        self.last_recall_diagnostic: dict[str, Any] = {"status": "NOT_RUN"}

    def _check(self, case_id: str, scope: Mapping[str, Any]) -> None:
        if case_id != self.run_id or dict(scope) != self.expected_scope:
            raise fixture.FixtureError("Runtime fixture case or scope drift")

    def create_evidence(
        self,
        *,
        case_id: str,
        session: fixture.CorpusSession,
        scope: Mapping[str, Any],
    ) -> str:
        self._check(case_id, scope)
        key = hashlib.sha256(f"{case_id}:{session.session_id}".encode()).hexdigest()
        body = e2e._body(
            self.client.post(
                "/v1/evidence",
                headers=e2e._headers(self.tokens["submitter"], f"{key}-evidence"),
                json={
                    "source_type": "BENCHMARK_FIXTURE",
                    "source_ref": f"dg10-synthetic-session://{key}",
                    "subject_id": f"dg10-session-{key[:20]}",
                    "observed_at": session.observed_at,
                    "content": session.render(),
                    "data_classification": "SYNTHETIC",
                    "media_type": "text/plain; charset=utf-8",
                    "permission_snapshot": {
                        "readable": True,
                        "scope": "dg10-isolated-evaluation-tenant",
                    },
                    "retention_state": "READABLE",
                },
            ),
            201,
            "dg10_fixture_evidence",
        )
        evidence_id = body.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise fixture.FixtureError("Runtime Evidence identity is absent")
        return evidence_id

    def create_proposal(
        self,
        *,
        case_id: str,
        session: fixture.CorpusSession,
        evidence_id: str,
        scope: Mapping[str, Any],
    ) -> str:
        self._check(case_id, scope)
        key = hashlib.sha256(f"{case_id}:{session.session_id}".encode()).hexdigest()
        body = e2e._body(
            self.client.post(
                "/v1/proposals",
                headers=e2e._headers(self.tokens["submitter"], f"{key}-proposal"),
                json={
                    "operation": "CREATE",
                    "proposed_patch": {
                        "subject_id": f"dg10-session-{key[:20]}",
                        "predicate": "benchmark.memory.full_session",
                        "claim_type": "BENCHMARK_MEMORY",
                        "payload": {
                            "case_id": case_id,
                            "session_id": session.session_id,
                            "observed_at": session.observed_at,
                            "memory_text": session.render(),
                            "evidence_id": evidence_id,
                        },
                        "authority": "ACTION_SAFE",
                        "confidence": 1.0,
                    },
                    "supporting_evidence_refs": [evidence_id],
                    "scope_predicate": dict(scope),
                    "requested_authority": "ACTION_SAFE",
                    "derivation_policy_id": "dg10-full-session-synthetic-v1",
                    "derivation_snapshot": {
                        "full_session": True,
                        "session_sha256": hashlib.sha256(session.render().encode()).hexdigest(),
                    },
                },
            ),
            201,
            "dg10_fixture_proposal",
        )
        proposal_id = body.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id:
            raise fixture.FixtureError("Runtime Proposal identity is absent")
        self._proposal_sessions[proposal_id] = (evidence_id, session)
        return proposal_id

    def approve_proposal(self, *, proposal_id: str) -> Mapping[str, str]:
        if proposal_id not in self._proposal_sessions:
            raise fixture.FixtureError("Runtime Proposal is not owned by this fixture")
        reviewed = e2e._review(
            self.client,
            self.tokens["reviewer"],
            proposal_id,
            f"{proposal_id}-review",
            "SYNTHETIC_FULL_SESSION_FIXTURE_VERIFIED",
        )
        result = {
            "decision_id": reviewed.get("decision_id"),
            "claim_id": reviewed.get("claim_id"),
            "claim_version_id": reviewed.get("claim_version_id"),
        }
        if any(not isinstance(value, str) or not value for value in result.values()):
            raise fixture.FixtureError("Runtime Decision identity is absent")
        return {key: str(value) for key, value in result.items()}

    def project(self) -> int:
        self._projected += self.worker.run_once()
        return self._projected

    def recall(
        self,
        *,
        case_id: str,
        query: str,
        scope: Mapping[str, Any],
        limit: int,
    ) -> fixture.RecallResult:
        self._check(case_id, scope)
        attempt_id = (
            self.ledger.start_attempt(
                phase="REAL_RUNTIME_MCP_RECALL",
                arm="MILAI_RETRIEVAL",
                case_id=case_id,
                planned_model_calls=0,
                planned_mcp_calls=1,
            )
            if self.ledger is not None
            else None
        )
        try:
            result = e2e._mcp(
                "reader",
                "milai_recall",
                {"query": query, "consistency": "CANONICAL_REQUIRED", "limit": limit},
                base_url=self.base_url,
                token=self.tokens["reader"],
            )
        except Exception:
            if self.ledger is not None and attempt_id is not None:
                self.ledger.finalize(
                    attempt_id,
                    agent_terminal=False,
                    parser_terminal=False,
                    retention_state="failed",
                    failure_reason_code="PROVIDER_REQUEST_FAILED",
                    redacted_public_receipt_digest=remediation.sha256_bytes(
                        f"{attempt_id}:mcp-request-failed".encode()
                    ),
                )
            raise
        if result.get("is_error") is True:
            if self.ledger is not None and attempt_id is not None:
                self.ledger.finalize(
                    attempt_id,
                    agent_terminal=False,
                    parser_terminal=False,
                    retention_state="failed",
                    failure_reason_code="AGENT_POLICY_REJECTED",
                    redacted_public_receipt_digest=remediation.sha256_bytes(
                        f"{attempt_id}:mcp-error-result".encode()
                    ),
                )
            raise fixture.FixtureError("MCP recall returned an error")
        try:
            body = e2e._structured(result)
        except Exception:
            if self.ledger is not None and attempt_id is not None:
                self.ledger.finalize(
                    attempt_id,
                    agent_terminal=True,
                    parser_terminal=False,
                    retention_state="failed",
                    failure_reason_code="AGENT_EVENT_PARSE_FAILED",
                    redacted_public_receipt_digest=remediation.sha256_bytes(
                        f"{attempt_id}:mcp-structured-result-missing".encode()
                    ),
                )
            raise
        trace_id = body.get("trace_id")
        if isinstance(trace_id, str) and trace_id and self.ledger is not None and attempt_id is not None:
            self.ledger.record_mcp_accepted(attempt_id, trace_id)
            self.ledger.record_mcp_terminal(
                attempt_id,
                raw_sidecar_digest=remediation.sha256_bytes(remediation.encoded_json(body)),
            )

        def fail_after_response(message: str) -> None:
            if self.ledger is not None and attempt_id is not None:
                self.ledger.finalize(
                    attempt_id,
                    agent_terminal=True,
                    parser_terminal=False,
                    retention_state="failed",
                    failure_reason_code="AGENT_EVENT_PARSE_FAILED",
                    redacted_public_receipt_digest=remediation.sha256_bytes(
                        f"{attempt_id}:{message}".encode()
                    ),
                )
            raise fixture.FixtureError(message)

        raw_items = body.get("items")
        if not isinstance(raw_items, list):
            fail_after_response("MCP recall items are absent")
        items: list[Mapping[str, Any]] = []
        for raw_item in raw_items:
            payload = raw_item.get("payload") if isinstance(raw_item, Mapping) else None
            if not isinstance(payload, Mapping):
                fail_after_response("MCP recall item payload is absent")
            if payload.get("case_id") != case_id:
                fail_after_response("MCP returned a foreign evaluation case")
            items.append(
                {
                    "session_id": payload.get("session_id"),
                    "evidence_id": payload.get("evidence_id"),
                    "memory_text": payload.get("memory_text"),
                    "claim_id": raw_item.get("claim_id"),
                    "claim_version_id": raw_item.get("claim_version_id"),
                }
            )
        consistency = body.get("consistency")
        status = body.get("status")
        self.last_recall_diagnostic = {
            "status": status,
            "item_count": len(items),
            "consistency": consistency,
            "abstention_reason": body.get("abstention_reason"),
            "degraded_components": body.get("degraded_components"),
            "fallback_used": body.get("fallback_used"),
        }
        if consistency != "CANONICAL_REQUIRED" or not isinstance(trace_id, str) or not trace_id:
            fail_after_response("MCP canonical consistency or trace identity drift")
        if self.ledger is not None and attempt_id is not None:
            self.ledger.finalize(
                attempt_id,
                agent_terminal=True,
                parser_terminal=True,
                retention_state="retained",
                failure_reason_code="SUCCESS",
                redacted_public_receipt_digest=remediation.sha256_bytes(
                    remediation.encoded_json(self.last_recall_diagnostic)
                ),
            )
        return fixture.RecallResult(
            request_id=trace_id,
            query=query,
            consistency=consistency,
            canonical_gate=True,
            results=tuple(items),
            abstained=status == "ABSTAINED",
        )

    def cleanup_case(self, *, case_id: str) -> Mapping[str, Any]:
        del case_id
        raise fixture.FixtureError("case cleanup requires isolated database teardown")
