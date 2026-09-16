#!/usr/bin/env python3
"""Produce Graphiti-native contexts for the frozen ten-case public-dev LME lane."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
os.environ["SEMAPHORE_LIMIT"] = "20"

import graphiti_core.telemetry as graphiti_telemetry  # type: ignore[import-not-found]
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import (  # type: ignore[import-not-found]
    OpenAIRerankerClient,
)
from graphiti_core.embedder.openai import (  # type: ignore[import-not-found]
    OpenAIEmbedder,
    OpenAIEmbedderConfig,
)
from graphiti_core.llm_client.config import LLMConfig  # type: ignore[import-not-found]
from graphiti_core.llm_client.openai_generic_client import (  # type: ignore[import-not-found]
    OpenAIGenericClient,
)
from graphiti_core.nodes import EpisodeType  # type: ignore[import-not-found]
from graphiti_core.search.search_config import (  # type: ignore[import-not-found]
    EdgeReranker,
    EdgeSearchConfig,
    EdgeSearchMethod,
    EpisodeReranker,
    EpisodeSearchConfig,
    EpisodeSearchMethod,
    SearchConfig,
)
from graphiti_core.utils.bulk_utils import RawEpisode  # type: ignore[import-not-found]

_COMMON_SPEC = importlib.util.spec_from_file_location(
    "milai_external_lme10", ROOT / "evals/dg16/external_lme10.py"
)
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("external LME10 common module is unavailable")
_COMMON = importlib.util.module_from_spec(_COMMON_SPEC)
sys.modules[_COMMON_SPEC.name] = _COMMON
_COMMON_SPEC.loader.exec_module(_COMMON)
atomic_json = _COMMON.atomic_json
load_cases = _COMMON.load_cases
sha256_file = _COMMON.sha256_file

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860/v1"
EMBEDDING_BASE_URL = "http://127.0.0.1:7861/v1"
EMBEDDING_MODEL = "bge-m3"
TOP_K = 10
MAX_COMPLETION_TOKENS = 49152
CUSTOM_EXTRACTION_INSTRUCTIONS = (
    "This is a long-term conversational memory. Extract at most 12 durable named "
    "entities and at most 24 durable relationships or user facts from each episode. "
    "Prioritize preferences, plans, decisions, biographical facts, dated events, and "
    "state changes. Ignore greetings, filler, transient wording, and repetitions."
)


class GraphitiLME10Error(RuntimeError):
    pass


def _timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y/%m/%d (%a) %H:%M").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise GraphitiLME10Error(f"invalid LongMemEval timestamp: {value}") from exc


def _session_text(session: Any) -> str:
    return "\n".join(
        f"{turn.role.capitalize()}: {turn.content}" for turn in session.turns
    )


def _search_config() -> SearchConfig:
    return SearchConfig(
        edge_config=EdgeSearchConfig(
            search_methods=[
                EdgeSearchMethod.bm25,
                EdgeSearchMethod.cosine_similarity,
            ],
            reranker=EdgeReranker.rrf,
        ),
        episode_config=EpisodeSearchConfig(
            search_methods=[EpisodeSearchMethod.bm25],
            reranker=EpisodeReranker.rrf,
        ),
        limit=TOP_K,
    )


def _contexts(search: Any, episode_to_session: dict[str, str]) -> tuple[str, list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    for rank, edge in enumerate(search.edges, start=1):
        fact = getattr(edge, "fact", None)
        if not isinstance(fact, str) or not fact.strip():
            continue
        sessions = tuple(
            dict.fromkeys(
                episode_to_session[item]
                for item in getattr(edge, "episodes", None) or []
                if item in episode_to_session
            )
        )
        if not sessions:
            continue
        score = (
            float(search.edge_reranker_scores[rank - 1])
            if rank <= len(search.edge_reranker_scores)
            else 1.0 / rank
        )
        candidates.append(
            {
                "content": fact.strip(),
                "kind": "DERIVED_EDGE",
                "observed_at": getattr(edge, "valid_at", None)
                or getattr(edge, "created_at", None),
                "native_rank": rank,
                "score": score,
                "sessions": sessions,
                "uuid": str(getattr(edge, "uuid", "")),
            }
        )
    for rank, episode in enumerate(search.episodes, start=1):
        episode_id = str(getattr(episode, "uuid", ""))
        content = getattr(episode, "content", None)
        session_id = episode_to_session.get(episode_id)
        if not isinstance(content, str) or not content.strip() or session_id is None:
            continue
        score = (
            float(search.episode_reranker_scores[rank - 1])
            if rank <= len(search.episode_reranker_scores)
            else 1.0 / rank
        )
        candidates.append(
            {
                "content": content.strip(),
                "kind": "RAW_EPISODE",
                "observed_at": getattr(episode, "valid_at", None),
                "native_rank": rank,
                "score": score,
                "sessions": (session_id,),
                "uuid": episode_id,
            }
        )
    candidates.sort(
        key=lambda item: (
            -item["score"],
            0 if item["kind"] == "RAW_EPISODE" else 1,
            item["native_rank"],
            item["uuid"],
        )
    )
    blocks: list[str] = []
    trace: list[dict[str, Any]] = []
    sources: list[str] = []
    for candidate_rank, candidate in enumerate(candidates, start=1):
        observed = candidate["observed_at"]
        observed_text = observed.isoformat() if isinstance(observed, datetime) else str(observed or "UNKNOWN")
        label = "Session Content" if candidate["kind"] == "RAW_EPISODE" else "Graphiti Derived Fact"
        blocks.append(f"Session Date: {observed_text}\n{label}:\n{candidate['content']}")
        for session_id in candidate["sessions"]:
            if session_id in sources:
                continue
            sources.append(session_id)
            trace.append(
                {
                    "rank": len(trace) + 1,
                    "candidate_rank": candidate_rank,
                    "session_id": session_id,
                    "native_scope": candidate["kind"],
                    "native_scope_rank": candidate["native_rank"],
                    "score": candidate["score"],
                    "graph_object_uuid_sha256": hashlib.sha256(
                        candidate["uuid"].encode()
                    ).hexdigest(),
                }
            )
    return "\n\n".join(blocks), trace, sources


def _usage(rows: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    return {
        key: sum(int((row.get("usage") or {}).get(key, 0) or 0) for row in rows)
        for key in keys
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if graphiti_telemetry.is_telemetry_enabled():
        raise GraphitiLME10Error("Graphiti telemetry must be disabled")
    if args.workers != 20 or os.environ.get("SEMAPHORE_LIMIT") != "20":
        raise GraphitiLME10Error("Graphiti worker contract drifted")
    if args.output.exists():
        raise GraphitiLME10Error("output exists; use a fresh run")
    cases, selection = load_cases()
    checkpoint_path = args.output.with_suffix(args.output.suffix + ".checkpoint")
    prior_wall_ms = 0.0
    records: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())
        if checkpoint.get("run_id") != args.run_id:
            raise GraphitiLME10Error("checkpoint run_id mismatch")
        records = list(checkpoint.get("records") or [])
        lifecycle = list(checkpoint.get("lifecycle") or [])
        if args.checkpoint_prior_max_completion_tokens is None:
            raise GraphitiLME10Error(
                "resume requires --checkpoint-prior-max-completion-tokens"
            )
        for item in lifecycle:
            item.setdefault(
                "max_completion_tokens",
                args.checkpoint_prior_max_completion_tokens,
            )
        prior_wall_ms = float(checkpoint.get("accumulated_wall_ms", 0.0) or 0.0)
    llm_config = LLMConfig(
        api_key="local-vllm",
        base_url=VLLM_BASE_URL,
        max_tokens=MAX_COMPLETION_TOKENS,
        model=MODEL_ID,
        small_model=MODEL_ID,
        temperature=0,
    )
    llm = OpenAIGenericClient(config=llm_config, max_tokens=MAX_COMPLETION_TOKENS)
    embedder = OpenAIEmbedder(
        OpenAIEmbedderConfig(
            api_key="local-vllm",
            base_url=EMBEDDING_BASE_URL,
            embedding_dim=1024,
            embedding_model=EMBEDDING_MODEL,
        )
    )
    graphiti = Graphiti(
        uri=args.neo4j_uri,
        user="neo4j",
        password=args.neo4j_password,
        llm_client=llm,
        embedder=embedder,
        cross_encoder=OpenAIRerankerClient(config=llm_config, client=llm),
        max_coroutines=args.workers,
    )
    completions: list[dict[str, Any]] = []
    embeddings: list[dict[str, Any]] = []
    original_completion = llm.client.chat.completions.create
    original_embedding = embedder.client.embeddings.create

    async def tracked_completion(*call_args: Any, **call_kwargs: Any) -> Any:
        response = await original_completion(*call_args, **call_kwargs)
        completions.append(
            {
                "model": response.model,
                "usage": response.usage.model_dump() if response.usage else {},
            }
        )
        return response

    async def tracked_embedding(*call_args: Any, **call_kwargs: Any) -> Any:
        response = await original_embedding(*call_args, **call_kwargs)
        embeddings.append(
            {
                "item_count": len(response.data),
                "model": response.model,
                "usage": response.usage.model_dump() if response.usage else {},
            }
        )
        return response

    llm.client.chat.completions.create = tracked_completion
    embedder.client.embeddings.create = tracked_embedding
    started_all = time.perf_counter()
    try:
        await graphiti.build_indices_and_constraints()
        for ordinal, case in enumerate(cases, start=1):
            if case.case_id in {item["case_id"] for item in records}:
                continue
            group_id = "dg16-" + hashlib.sha256(
                f"{args.run_id}\0{case.case_id}".encode()
            ).hexdigest()[:24]
            episode_to_session: dict[str, str] = {}
            completion_start = len(completions)
            embedding_start = len(embeddings)
            ingest_started = time.perf_counter()
            try:
                result = await graphiti.add_episode_bulk(
                    [
                        RawEpisode(
                            name=session.session_id,
                            content=_session_text(session),
                            source=EpisodeType.text,
                            source_description=(
                                "LongMemEval chronological conversation session"
                            ),
                            reference_time=_timestamp(session.observed_at),
                        )
                        for session in case.sessions
                    ],
                    group_id=group_id,
                    custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                )
                session_ids = {session.session_id for session in case.sessions}
                episode_to_session = {
                    str(episode.uuid): episode.name
                    for episode in result.episodes
                    if episode.name in session_ids
                }
                if len(episode_to_session) != len(case.sessions):
                    raise GraphitiLME10Error(
                        f"case {case.case_id} bulk episode denominator drifted"
                    )
                ingest_ms = (time.perf_counter() - ingest_started) * 1000
                query_started = time.perf_counter()
                search = await graphiti.search_(
                    case.question,
                    config=_search_config(),
                    group_ids=[group_id],
                )
                query_ms = (time.perf_counter() - query_started) * 1000
                context, trace, sources = _contexts(search, episode_to_session)
                if not context or not trace:
                    raise GraphitiLME10Error(f"case {case.case_id} returned no context")
                records.append(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "method_id": "GRAPHITI-OSS",
                        "context": context,
                        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                        "query_latency_ms": query_ms,
                        "retrieval_trace": trace,
                        "selected_source_refs": sources,
                        "usage": {
                            "memory_query_api_calls": 1,
                            "edge_results_returned": len(search.edges),
                            "episode_results_returned": len(search.episodes),
                        },
                    }
                )
                case_completions = completions[completion_start:]
                case_embeddings = embeddings[embedding_start:]
                lifecycle.append(
                    {
                        "case_id": case.case_id,
                        "session_count": len(case.sessions),
                        "ingest_ms": ingest_ms,
                        "query_ms": query_ms,
                        "completion_calls": len(case_completions),
                        "completion_usage": _usage(case_completions),
                        "embedding_calls": len(case_embeddings),
                        "embedding_usage": _usage(case_embeddings),
                        "max_completion_tokens": MAX_COMPLETION_TOKENS,
                    }
                )
            finally:
                await graphiti.driver.execute_query(
                    "MATCH (n {group_id: $group_id}) DETACH DELETE n",
                    group_id=group_id,
                )
                remaining, _, _ = await graphiti.driver.execute_query(
                    "MATCH (n {group_id: $group_id}) RETURN count(n) AS count",
                    group_id=group_id,
                    routing_="r",
                )
                if int(remaining[0]["count"]):
                    raise GraphitiLME10Error("case graph cleanup failed")
            print(
                json.dumps(
                    {
                        "stage": "graphiti-context",
                        "case": ordinal,
                        "case_count": len(cases),
                        "case_id": case.case_id,
                        "status": "SUCCEEDED",
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            atomic_json(
                checkpoint_path,
                {
                    "schema": "milai.dg16.external-lme10-graphiti-checkpoint.v1",
                    "run_id": args.run_id,
                    "records": records,
                    "lifecycle": lifecycle,
                    "accumulated_wall_ms": prior_wall_ms
                    + (time.perf_counter() - started_all) * 1000,
                },
            )
    finally:
        await graphiti.close()
    if len(records) != 10:
        raise GraphitiLME10Error("Graphiti context denominator is incomplete")
    artifact = {
        "schema": "milai.dg16.external-lme10-contexts.v1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "run_id": args.run_id,
        "method_id": "GRAPHITI-OSS",
        "record_count": len(records),
        "selection": selection,
        "configuration": {
            "source_commit": args.source_commit,
            "model": MODEL_ID,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimensions": 1024,
            "max_completion_tokens_by_case": {
                item["case_id"]: item["max_completion_tokens"] for item in lifecycle
            },
            "top_k": TOP_K,
            "workers": args.workers,
            "telemetry_disabled": True,
            "native_search": "edge BM25+cosine RRF + episode BM25 RRF",
            "native_ingest": "add_episode_bulk over chronological session episodes",
            "custom_extraction_instructions": CUSTOM_EXTRACTION_INSTRUCTIONS,
        },
        "lifecycle": lifecycle,
        "provider_accounting": {
            "completion_calls": sum(item["completion_calls"] for item in lifecycle),
            "completion_usage": {
                key: sum(item["completion_usage"][key] for item in lifecycle)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "embedding_calls": sum(item["embedding_calls"] for item in lifecycle),
            "embedding_usage": {
                key: sum(item["embedding_usage"][key] for item in lifecycle)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
        },
        "execution": {
            "hostname": platform.node(),
            "python": sys.version,
            "runner_sha256": sha256_file(Path(__file__)),
            "wall_ms": round(
                prior_wall_ms + (time.perf_counter() - started_all) * 1000, 6
            ),
        },
        "records": records,
    }
    atomic_json(args.output, artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--neo4j-uri", default="bolt://127.0.0.1:27964")
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--workers", type=int, choices=(20,), default=20)
    parser.add_argument(
        "--checkpoint-prior-max-completion-tokens",
        type=int,
        choices=(32768,),
    )
    parser.add_argument(
        "--source-commit",
        default="401c59a65bdeb22a44136901ff30231e6998a7fe",
    )
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
