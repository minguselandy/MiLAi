"""Coalent provider ports using the existing metered generation/embedding clients."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.embeddings import Embeddings

from milai_lab.providers.contextual_vllm import VLLMClient


class CoalentEmbedder:
    """Retain upstream query/claim batching through the existing embedding adapter."""

    def __init__(self, embeddings: Embeddings) -> None:
        self.embeddings = embeddings

    def embed(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_documents(texts)


class CoalentGenerationProvider:
    """Send upstream prompts/settings through the original owned client and ledger.

    The enclosing Host supplies its normal request admission callback. Configure
    the upstream LLMSynthesizer with retries=0 for the declared no-retry run.
    """

    def __init__(self, client: VLLMClient, *, admit: Callable[[], None],
                 record: Callable[[dict[str, Any]], None]) -> None:
        self.client, self.admit, self.record = client, admit, record

    def generate(self, *, model: str, system: str, user: str, max_tokens: int,
                 temperature: float) -> Any:
        from coalent.semantic.ports import Generation, Usage

        self.admit()
        request: dict[str, Any] = {"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": temperature}
        thinking = (self.client.config.enable_thinking
                    if self.client.config.enable_thinking is not None else
                    self.client.capacity.enable_thinking if self.client.capacity else None)
        if thinking is not None:
            request["chat_template_kwargs"] = {"enable_thinking": thinking}
        receipt = self.client.native_post("chat/completions", request)
        choice = receipt["choices"][0]
        usage = receipt.get("usage")
        known = Usage(prompt_tokens=usage["prompt_tokens"],
                      completion_tokens=usage["completion_tokens"], model=model) if usage else None
        self.record({"event": "coalent_generation_result", "model": model,
                     "finish_reason": choice["finish_reason"], "usage": usage,
                     "accounting": "Already charged by the original VLLMClient; do not add again"})
        return Generation(text=choice["message"]["content"], usage=known)
