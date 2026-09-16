from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any

from milai_client import (
    AgentRecallPolicy,
    AsyncAgentContext,
    CallableTokenCounter,
    RecallEnvelope,
    run_agent_turn,
)


class _Client:
    async def recall(self, query: str, **options: Any) -> RecallEnvelope:
        assert query == "please recall synthetic memory"
        assert options["consistency"] == "CANONICAL_REQUIRED"
        return RecallEnvelope.from_api(
            {
                "results": [],
                "open_issue_ids": ["issue-synthetic"],
                "abstained": True,
                "abstention_reason": "CANONICAL_GATE_REJECTED",
                "retrieval_trace_id": "trace-synthetic",
                "consistency": "CANONICAL_REQUIRED",
            }
        )

    async def get_open_issue(self, issue_id: str) -> Any:
        assert issue_id == "issue-synthetic"
        return SimpleNamespace(
            raw={
                "issue_id": issue_id,
                "target_claim_id": "claim-synthetic",
                "issue_type": "CONFLICT",
                "status": "OPEN",
                "revision": 1,
                "scope_predicate": {"project_ids": ["milai"]},
                "branches": [
                    {"relation_type": "SUPPORT_BRANCH", "evidence_id": "evidence-a"},
                    {"relation_type": "CONTRADICT_BRANCH", "evidence_id": "evidence-b"},
                ],
                "discharge_rule": {"review_required": True},
                "required_authority": "ACTION_SAFE",
            }
        )


async def _model(user_query: str, memory_data: str, tools: Any) -> str:
    assert user_query == "please recall synthetic memory"
    assert not tools
    assert 'trust="data-only"' in memory_data
    return "ABSTAIN: live OpenIssue requires discharge"


async def _run() -> None:
    client = _Client()
    policy = AgentRecallPolicy(scope={"project_ids": ["milai"]})
    counter = CallableTokenCounter(
        "synthetic.regex.v1",
        lambda value: len(re.findall(r"[\w]+|[^\w\s]", value, re.UNICODE)),
    )
    context = AsyncAgentContext(  # type: ignore[arg-type]
        client,
        recall_policy=policy,
        token_counter=counter,
    )
    result = await run_agent_turn(
        client=client,  # type: ignore[arg-type]
        user_query="please recall synthetic memory",
        model_call=_model,
        recall_policy=policy,
        context_manager=context,
        session_id="synthetic-session",
    )
    assert result.memory_status == "ABSTAINED"
    assert result.open_issue_ids == ("issue-synthetic",)
    assert result.recall_route == "L1"
    assert result.context_delta_status == "REPLACE"
    assert result.token_budget_verified is True
    print("generic-agent smoke: PASS")


if __name__ == "__main__":
    asyncio.run(_run())
