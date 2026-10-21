"""Build the optional reviewed Coalent core from already owned runtime providers."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.embeddings import Embeddings

from milai_lab.baselines.coalent_providers import CoalentEmbedder, CoalentGenerationProvider
from milai_lab.baselines.coalent_store import SourceRetriever, StoreCognitionStore
from milai_lab.providers.chat_bridge import VLLMChatModel


def coalent_factory(
    config: dict[str, Any], model: VLLMChatModel, embeddings: Embeddings,
    record: Callable[[dict[str, Any]], None], *, enable_thinking: bool | None = None,
) -> Callable[[SourceRetriever, StoreCognitionStore], Any]:
    """No provider discovery/install; the caller supplies the patched core on PYTHONPATH."""
    from coalent.semantic import LLMSynthesizer, SemanticCache

    provider = CoalentGenerationProvider(model.client,
        admit=lambda: model.reserve_external_request("coalent_synthesis"),
        record=record, enable_thinking=enable_thinking)
    synth = LLMSynthesizer(provider, model=model.client.config.model,
        max_tokens=config.get("synthesis_max_tokens", model.client.config.max_tokens),
        temperature=config.get("synthesis_temperature", model.client.config.temperature), retries=0)
    embedder = CoalentEmbedder(embeddings)

    def build(retriever: SourceRetriever, store: StoreCognitionStore) -> Any:
        return SemanticCache(retriever, synth, embedder=embedder, store=store,
                             on_event=record, read_path="pool", **config.get("cache_options", {}))
    return build
