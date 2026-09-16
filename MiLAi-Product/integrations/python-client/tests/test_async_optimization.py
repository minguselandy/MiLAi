from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from milai_client import AgentRecallPolicy, AsyncAgentContext, SessionSlotRegistry
from milai_client.models import RecallEnvelope


class _AsyncClient:
    def __init__(self) -> None:
        self.recalls: list[tuple[str, dict[str, Any]]] = []
        self.exact_recalls: list[Any] = []
        self.issue_reads = 0

    async def system_watermarks(self) -> Any:
        return SimpleNamespace(canonical_snapshot=7)

    async def recall(self, query: str, **options: Any) -> RecallEnvelope:
        self.recalls.append((query, options))
        return RecallEnvelope.from_api(
            {
                "results": [
                    {
                        "claim_id": "claim-1",
                        "claim_version_id": "version-1",
                        "payload": {"value": "synthetic"},
                    }
                ],
                "open_issue_ids": ["issue-1"],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-1",
                "consistency": options["consistency"],
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    async def recall_exact(self, request: Any) -> RecallEnvelope:
        self.exact_recalls.append(request)
        return RecallEnvelope.from_api(
            {
                "results": [{"claim_id": request.claim_id, "claim_version_id": "version-1"}],
                "open_issue_ids": [],
                "abstained": False,
                "degraded_components": [],
                "fallback_used": False,
                "retrieval_trace_id": "trace-exact",
                "consistency": request.consistency,
                "snapshot": {"canonical_outbox_sequence": 7},
            }
        )

    async def get_open_issue(self, issue_id: str) -> Any:
        self.issue_reads += 1
        return SimpleNamespace(
            issue_id=issue_id,
            raw={
                "issue_id": issue_id,
                "target_claim_id": "claim-1",
                "issue_type": "CONFLICT",
                "status": "OPEN",
                "revision": 1,
                "scope_predicate": {"project_ids": ["milai"]},
                "discharge_rule": {"review_required": True},
                "required_authority": "ACTION_SAFE",
                "branches": [
                    {"relation_type": "SUPPORT_BRANCH", "evidence_id": "evidence-1"},
                    {"relation_type": "CONTRADICT_BRANCH", "evidence_id": "evidence-2"},
                ],
                "request_id": f"request-{self.issue_reads}",
            },
        )


def _policy(project: str = "milai") -> AgentRecallPolicy:
    return AgentRecallPolicy(
        scope={"project_ids": [project]},
        authority="INFORMATIONAL",
        consistency_floor="EVENTUAL",
    )


def test_async_cache_is_server_validated_and_policy_bound() -> None:
    async def run() -> None:
        client = _AsyncClient()
        registry = SessionSlotRegistry()
        context = AsyncAgentContext(  # type: ignore[arg-type]
            client, recall_policy=_policy(), slot_registry=registry
        )
        first = await context.prepare("project status", session_id="session")
        assert first.routing.route == "L1"
        cached = await context.prepare("project status", session_id="session")
        assert cached.routing.route == "CACHE"
        assert len(client.recalls) == 1

        changed = AsyncAgentContext(  # type: ignore[arg-type]
            client, recall_policy=_policy("other"), slot_registry=registry
        )
        refreshed = await changed.prepare("project status", session_id="session")
        assert refreshed.routing.route == "L1"
        assert len(client.recalls) == 2

        with pytest.raises(TypeError, match="cache_validated"):
            await context.prepare(  # type: ignore[call-arg]
                "project status", session_id="session", cache_validated=True
            )

    asyncio.run(run())


def test_async_query_typed_claim_uuid_uses_exact_transport() -> None:
    async def run() -> None:
        client = _AsyncClient()
        context = AsyncAgentContext(client, recall_policy=_policy())  # type: ignore[arg-type]
        claim_id = "11111111-1111-4111-8111-111111111111"
        prepared = await context.prepare(f"read Claim {claim_id}", session_id="session")
        assert prepared.routing.route == "L0"
        assert client.exact_recalls[0].claim_id == claim_id
        assert client.recalls == []

    asyncio.run(run())
