from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from autogen_core.model_context import BufferedChatCompletionContext
from autogen_core.models import UserMessage
from milai_autogen import MilaiMemory
from milai_client import AgentRecallPolicy, RecallEnvelope


class _Client:
    async def recall(self, query: str, **options: Any) -> RecallEnvelope:
        return RecallEnvelope.from_api(
            {
                "results": [],
                "open_issue_ids": ["issue-synthetic"],
                "abstained": True,
                "abstention_reason": "CANONICAL_GATE_REJECTED",
                "retrieval_trace_id": "trace-synthetic",
                "consistency": options["consistency"],
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

    async def close(self) -> None:
        return None


async def run() -> None:
    memory = MilaiMemory(  # type: ignore[arg-type]
        _Client(),
        recall_policy=AgentRecallPolicy(scope={"project_ids": ["milai"]}),
    )
    context = BufferedChatCompletionContext(buffer_size=4)
    await context.add_message(
        UserMessage(content="please recall synthetic memory", source="user")
    )
    result = await memory.update_context(context)
    assert result.memories is not None
    metadata = result.memories.results[0].metadata
    assert metadata is not None
    assert metadata["open_issue_ids"] == ["issue-synthetic"]
    message = (await context.get_messages())[-1]
    assert isinstance(message, UserMessage)
    assert message.source == "milai-memory-data"
    print("autogen smoke: PASS")


if __name__ == "__main__":
    asyncio.run(run())
