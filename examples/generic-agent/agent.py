from __future__ import annotations

import argparse
import asyncio

from milai_client import AgentRecallPolicy, AsyncAgentContext, AsyncMilaiClient


async def prepare_model_input(user_query: str) -> str:
    """Prepare one governed, replaceable memory slot for a model call."""
    client = AsyncMilaiClient()
    context = AsyncAgentContext(
        client,
        recall_policy=AgentRecallPolicy(
            scope={"project_ids": ["milai"]},
            authority="ACTION_SAFE",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=3,
        ),
    )
    try:
        prepared = await context.prepare(user_query, session_id="generic-example")
        delta = prepared.compiled.delta
        memory_block = delta.rendered_context or ""
        if (
            prepared.recall_envelope is not None
            and prepared.recall_envelope.status == "ABSTAINED"
        ):
            return f"No governed memory is available.\n{memory_block}\nUser query: {user_query}"
        return f"{memory_block}\nUser query: {user_query}"
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic mandatory-recall MiLAi example"
    )
    parser.add_argument("query")
    args = parser.parse_args()
    print(asyncio.run(prepare_model_input(args.query)))


if __name__ == "__main__":
    main()
