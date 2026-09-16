from __future__ import annotations

import argparse
import asyncio
import json
import os

from autogen_core.model_context import BufferedChatCompletionContext
from autogen_core.models import UserMessage
from milai_autogen import MilaiMemory
from milai_client import AgentRecallPolicy, AsyncMilaiClient


async def run(query: str) -> None:
    scope = json.loads(
        os.environ.get("MILAI_AGENT_SCOPE_JSON", '{"project_ids":["milai"]}')
    )
    if not isinstance(scope, dict):
        raise TypeError("MILAI_AGENT_SCOPE_JSON must be an object")
    memory = MilaiMemory(
        AsyncMilaiClient(), recall_policy=AgentRecallPolicy(scope=scope)
    )
    context = BufferedChatCompletionContext(buffer_size=8)
    await context.add_message(UserMessage(content=query, source="user"))
    try:
        await memory.update_context(context)
        message = (await context.get_messages())[-1]
        assert isinstance(message, UserMessage)
        assert message.source == "milai-memory-data"
        print(message.content)
    finally:
        await memory.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.query))
