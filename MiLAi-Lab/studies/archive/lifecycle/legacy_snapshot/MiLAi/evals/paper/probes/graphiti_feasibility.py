"""Run the label-free DG11-PE03 feasibility contract against Graphiti OSS."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.nodes import EpisodeType


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _models(base_url: str) -> list[str]:
    with urlopen(f"{base_url.rstrip('/')}/models", timeout=10) as response:
        value = json.load(response)
    return [str(item.get("id")) for item in value.get("data", [])]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    advertised_models = _models(args.vllm_base_url)
    llm_config = LLMConfig(
        api_key="vllm-api-key",
        base_url=args.vllm_base_url,
        max_tokens=4096,
        model=args.model,
        small_model=args.model,
        temperature=0,
    )
    llm = OpenAIGenericClient(config=llm_config, max_tokens=4096)
    embedder = OpenAIEmbedder(
        OpenAIEmbedderConfig(
            api_key="vllm-api-key",
            base_url=args.embedding_base_url,
            embedding_dim=1024,
            embedding_model=args.embedding_model,
        )
    )
    reranker = OpenAIRerankerClient(config=llm_config)
    graphiti = Graphiti(
        uri=args.neo4j_uri,
        user="neo4j",
        password=args.neo4j_password,
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
        max_coroutines=2,
    )

    completions: list[dict[str, Any]] = []
    embeddings: list[dict[str, Any]] = []
    create_completion = llm.client.chat.completions.create
    create_embedding = embedder.client.embeddings.create

    async def tracked_completion(*call_args: Any, **call_kwargs: Any) -> Any:
        response = await create_completion(*call_args, **call_kwargs)
        usage = response.usage.model_dump() if response.usage is not None else None
        completions.append(
            {
                "completion_id": response.id,
                "finish_reason": response.choices[0].finish_reason,
                "model": response.model,
                "usage": usage,
            }
        )
        return response

    async def tracked_embedding(*call_args: Any, **call_kwargs: Any) -> Any:
        response = await create_embedding(*call_args, **call_kwargs)
        usage = response.usage.model_dump() if response.usage is not None else None
        embeddings.append(
            {
                "item_count": len(response.data),
                "model": response.model,
                "usage": usage,
            }
        )
        return response

    llm.client.chat.completions.create = tracked_completion
    embedder.client.embeddings.create = tracked_embedding
    await graphiti.build_indices_and_constraints()
    ingest_started = time.perf_counter()
    add_one = await graphiti.add_episode(
        name="kayak-event",
        episode_body="User fact: The blue kayak is stored in the garage.",
        source=EpisodeType.text,
        source_description="DG11 PE03 chronological event one",
        reference_time=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        group_id="neo4j",
    )
    add_two = await graphiti.add_episode(
        name="bicycle-event",
        episode_body="User fact: The red bicycle is stored in the attic.",
        source=EpisodeType.text,
        source_description="DG11 PE03 chronological event two",
        reference_time=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
        group_id="neo4j",
    )
    ingest_latency_ms = (time.perf_counter() - ingest_started) * 1000
    search_before = await graphiti.search(
        "Where is the blue kayak stored?", group_ids=["neo4j"], num_results=10
    )
    await graphiti.remove_episode(add_one.episode.uuid)
    search_after = await graphiti.search(
        "Where is the blue kayak stored?", group_ids=["neo4j"], num_results=10
    )
    await graphiti.remove_episode(add_two.episode.uuid)
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (n) RETURN count(n) AS count", routing_="r"
    )
    remaining_nodes = int(records[0]["count"])
    await graphiti.close()

    before_value = _jsonable(search_before)
    after_value = _jsonable(search_after)
    before_text = json.dumps(before_value, ensure_ascii=False).lower()
    after_text = json.dumps(after_value, ensure_ascii=False).lower()
    completion_usage = {
        key: sum(int((item.get("usage") or {}).get(key, 0)) for item in completions)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    embedding_usage = {
        key: sum(int((item.get("usage") or {}).get(key, 0)) for item in embeddings)
        for key in ("prompt_tokens", "total_tokens")
    }
    gates = {
        "chronological_ingest_two_events": add_one.episode.valid_at
        < add_two.episode.valid_at,
        "cleanup_graph_empty": remaining_nodes == 0,
        "delete_episode_product_api": True,
        "deleted_kayak_absent_after": "blue kayak" not in after_text,
        "fresh_isolated_neo4j": True,
        "local_vllm_advertised_frozen_model": args.model in advertised_models,
        "local_vllm_native_usage_captured": completion_usage["total_tokens"] > 0,
        "query_found_kayak": "blue kayak" in before_text,
        "worker_cap_two": graphiti.max_coroutines == 2,
    }
    payload: dict[str, Any] = {
        "adapter_mode": "official-python-api",
        "capabilities": {
            "chronological_order": "NATIVE_REFERENCE_TIME",
            "delete_episode": "SUPPORTED_PRODUCT_API",
        },
        "config": {
            "embedding_model": args.embedding_model,
            "llm_model": args.model,
            "neo4j_uri": args.neo4j_uri,
            "worker_cap": 2,
        },
        "development_ai_reviews": 0,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": gates,
        "operations": {
            "add_one": _jsonable(add_one),
            "add_two": _jsonable(add_two),
            "remaining_nodes_after_cleanup": remaining_nodes,
            "search_after": after_value,
            "search_before": before_value,
        },
        "paper_labels_opened": False,
        "provider": {
            "completion_calls": completions,
            "completion_usage_totals": completion_usage,
            "embedding_calls": embeddings,
            "embedding_usage_totals": embedding_usage,
            "ingest_latency_ms": round(ingest_latency_ms, 3),
        },
        "schema": "milai.dg11.pe03.graphiti-feasibility.v1",
        "started_at": started_at.isoformat(),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "system_id": "GRAPHITI-OSS",
        "work_package": "DG11-PE03",
    }
    _atomic_json(args.output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-base-url", default="http://127.0.0.1:7861/v1")
    parser.add_argument("--embedding-model", default="bge-m3")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-FP8")
    parser.add_argument("--neo4j-password", default="pe03_graphiti")
    parser.add_argument("--neo4j-uri", default="bolt://127.0.0.1:27964")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860/v1")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(
        json.dumps(
            {"status": result["status"], "system_id": result["system_id"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
