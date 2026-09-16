"""Harbor 0.23.0 Terminus-2 policy/loop with the existing accounted transport.

System-level reference, not a pure policy contrast or an unmodified LiteLLM run.
Only backend construction changes. Native prompts, tmux, parsing, completion
confirmation and summarization remain upstream. Every backend call shares one
64-generation Provider ceiling, including native summarization calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from harbor.agents.terminus_2.terminus_2 import Terminus2
from harbor.llms.base import (
    BaseLLM,
    ContextLengthExceededError,
    LLMResponse,
    OutputLengthExceededError,
)
from harbor.models.metric import UsageInfo

from run_workspace_task_a import Counts
from v02_local_provider import accounting, read_events
from v0213_provider import MODEL
from workspace_harbor_agent import WorkspaceAgent
from workspace_task_provider import Provider
from workspace_terminal_session import dump


class AccountedLLM(BaseLLM):
    def __init__(self, provider):
        self.provider = provider
        self.counts = None
        self.context = provider.verify()["max_model_len"]

    def get_model_context_limit(self):
        return self.context

    def get_model_output_limit(self):
        return 4096

    async def call(self, prompt, message_history=None, response_format=None,
                   logging_path=None, **kwargs):
        if response_format is not None:
            raise ValueError("UNIMPLEMENTED_NATIVE_RESPONSE_FORMAT")
        messages = [*(message_history or []), {"role": "user", "content": prompt}]
        body = {"messages": messages, "max_tokens": 4096, "model": MODEL, "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "add_generation_prompt": True, "add_special_tokens": False,
                "temperature": 0, "top_p": 1, "seed": 213}
        if self.counts is None:
            raise ValueError("TOKENIZER_NOT_READY")
        pending = asyncio.create_task(asyncio.to_thread(
            self.provider.generate, "terminus", body,
            expected_prompt_tokens=self.counts.wire(messages)))
        try:
            raw = await asyncio.shield(pending)
        except asyncio.CancelledError:
            await pending  # settle the actual HTTP request before teardown
            raise
        except ValueError as exc:
            if str(exc) == "MODEL_CONTEXT_LIMIT":
                raise ContextLengthExceededError("Provider verified context limit") from exc
            raise
        receipt = read_events(self.provider.ledger)[-1]
        usage = receipt["usage"]
        http = json.loads((self.provider.root / f"{receipt['request_id']}-http.json").read_text())
        response = json.loads(http["body"])
        if response["choices"][0].get("finish_reason") == "length":
            raise OutputLengthExceededError("Provider output limit", truncated_response=raw)
        return LLMResponse(content=raw, model_name=MODEL, response_id=receipt["request_id"],
                           usage=UsageInfo(prompt_tokens=usage["prompt_tokens"],
                                           completion_tokens=usage["completion_tokens"],
                                           cache_tokens=0, cost_usd=0.0))


class AccountedTerminus(Terminus2):
    def __init__(self, *args, run_root, task_timeout=900, wave_cap=64, arm=None,
                 smoke=False, **kwargs):
        self.run_root, self.task_timeout = Path(run_root), task_timeout
        self.provider = Provider(self.run_root / "provider", deadline=time.monotonic() + 900,
                                 max_requests=wave_cap, output_cap=4096)
        self.backend = AccountedLLM(self.provider)
        super().__init__(*args, max_turns=64, temperature=0, enable_summarize=True,
                         store_all_messages=True,
                         trajectory_config={"raw_content": True, "linear_history": True}, **kwargs)

    def _init_llm(self, **kwargs):
        return self.backend

    async def setup(self, environment):
        await asyncio.to_thread(WorkspaceAgent._audit_container, self, environment.session_id)
        self.backend.counts = await asyncio.to_thread(Counts)
        await super().setup(environment)

    async def run(self, instruction, environment, context):
        self.provider.deadline = time.monotonic() + self.task_timeout - 5
        try:
            await super().run(instruction, environment, context)
        finally:
            state = accounting(read_events(self.provider.ledger))
            usage = state["sessions"].get("terminus", {})
            context.n_input_tokens = usage.get("input_tokens", 0)
            context.n_output_tokens = usage.get("output_tokens", 0)
            context.cost_usd = None  # No dollar tariff exists; internal 0 is a schema placeholder.
            metadata = context.metadata or {}
            metadata.update(accounting=state, usd_tariff="UNKNOWN_NOT_FREE",
                            transport="v2: native text and capacity exceptions; accounted Provider")
            context.metadata = metadata
            dump(self.run_root / "terminus-accounting.json", context.model_dump())
            self.provider.close()
