"""Memora native-context runner for a frozen Graphiti OSS installation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

# Graphiti reads both variables while importing its helpers and telemetry module.
os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
os.environ["SEMAPHORE_LIMIT"] = "2"

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
from tokenizers import Tokenizer  # type: ignore[import-not-found]

from evals.paper.contracts import ContextRecord, write_context_archive
from evals.paper.datasets.memora import MemoraCase, MemoraCohort, load_inputs
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/memora-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_BASE_URL = "http://127.0.0.1:7860/v1"
EMBEDDING_BASE_URL = "http://127.0.0.1:7861/v1"
EMBEDDING_MODEL = "bge-m3"
MEMORY_TOKEN_BUDGET = 512
TOP_K = 10


class MemoraGraphitiError(RuntimeError):
    pass


def _require_inputs(path: Path, *, allow_unfrozen_smoke: bool) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MemoraGraphitiError("Memora input artifact is invalid")
    if allow_unfrozen_smoke:
        if (
            value.get("test_data_only") is not True
            or not 1 <= value.get("case_count", 0) <= 10
        ):
            raise MemoraGraphitiError("unfrozen Memora smoke requires synthetic inputs")
    elif value.get("test_data_only") is True:
        raise MemoraGraphitiError("formal Memora run cannot use synthetic inputs")


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session_text(cohort: MemoraCohort, index: int) -> str:
    return "\n".join(
        f"{turn.actor.capitalize()}: {turn.content}"
        for turn in cohort.sessions[index].turns
    )


def _search_config() -> SearchConfig:
    """Use Graphiti's native graph and raw-episode retrieval without answer labels."""
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


def _fit_results(
    search_results: Any,
    *,
    tokenizer: Tokenizer,
    episode_to_session: dict[str, str],
) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...], int]:
    candidates: list[dict[str, Any]] = []
    for rank, edge in enumerate(search_results.edges, start=1):
        fact = getattr(edge, "fact", None)
        if not isinstance(fact, str) or not fact.strip():
            continue
        episode_ids = getattr(edge, "episodes", None)
        session_ids = tuple(
            dict.fromkeys(
                episode_to_session[item]
                for item in episode_ids or []
                if item in episode_to_session
            )
        )
        if not session_ids:
            continue
        score = (
            float(search_results.edge_reranker_scores[rank - 1])
            if rank <= len(search_results.edge_reranker_scores)
            else 1.0 / rank
        )
        observed_at = getattr(edge, "valid_at", None) or getattr(
            edge, "created_at", None
        )
        candidates.append(
            {
                "content": fact.strip(),
                "kind": "DERIVED_EDGE",
                "observed_at": observed_at,
                "rank": rank,
                "score": score,
                "session_ids": session_ids,
                "uuid": str(getattr(edge, "uuid", "")),
            }
        )
    for rank, episode in enumerate(search_results.episodes, start=1):
        content = getattr(episode, "content", None)
        episode_id = str(getattr(episode, "uuid", ""))
        session_id = episode_to_session.get(episode_id)
        if not isinstance(content, str) or not content.strip() or session_id is None:
            continue
        score = (
            float(search_results.episode_reranker_scores[rank - 1])
            if rank <= len(search_results.episode_reranker_scores)
            else 1.0 / rank
        )
        candidates.append(
            {
                "content": content.strip(),
                "kind": "RAW_EPISODE",
                "observed_at": getattr(episode, "valid_at", None),
                "rank": rank,
                "score": score,
                "session_ids": (session_id,),
                "uuid": episode_id,
            }
        )
    # RRF scores are comparable across the two native scopes. Prefer raw provenance
    # on exact ties, then preserve the native per-scope rank.
    candidates.sort(
        key=lambda item: (
            -item["score"],
            0 if item["kind"] == "RAW_EPISODE" else 1,
            item["rank"],
            item["uuid"],
        )
    )
    blocks: list[str] = []
    sources: list[str] = []
    trace: list[dict[str, Any]] = []
    declared_tokens = 0
    for visible_rank, candidate in enumerate(candidates, start=1):
        source_session_ids = candidate["session_ids"]
        observed_at = candidate["observed_at"]
        observed_at_text = (
            observed_at.isoformat()
            if isinstance(observed_at, datetime)
            else str(observed_at or "UNKNOWN")
        )
        content_label = (
            "Session Content"
            if candidate["kind"] == "RAW_EPISODE"
            else "Graphiti Derived Fact"
        )
        block = (
            f"Session Date: {observed_at_text}\n"
            f"{content_label}:\n{candidate['content']}"
        )
        candidate_context = "\n\n".join([*blocks, block])
        candidate_tokens = len(tokenizer.encode(candidate_context).ids)
        if candidate_tokens > MEMORY_TOKEN_BUDGET:
            continue
        blocks.append(block)
        sources.extend(source_session_ids)
        trace.append(
            {
                "graph_object_uuid_sha256": hashlib.sha256(
                    candidate["uuid"].encode()
                ).hexdigest(),
                "native_scope": candidate["kind"],
                "native_scope_rank": candidate["rank"],
                "rank": visible_rank,
                "score": candidate["score"],
                "score_kind": "GRAPHITI_NATIVE_RRF",
                "session_id": source_session_ids[0],
                "source_id": source_session_ids[0],
                "source_session_ids": list(source_session_ids),
            }
        )
        declared_tokens = candidate_tokens
    return (
        "\n\n".join(blocks),
        tuple(dict.fromkeys(sources)),
        tuple(trace),
        declared_tokens,
    )


def _usage_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        key: sum(int((row.get("usage") or {}).get(key, 0) or 0) for row in rows)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


async def _run_cohort(
    *,
    graphiti: Graphiti,
    run_id: str,
    cohort: MemoraCohort,
    cases: list[MemoraCase],
    tokenizer: Tokenizer,
    completions: list[dict[str, Any]],
    embeddings: list[dict[str, Any]],
) -> tuple[list[ContextRecord], dict[str, Any]]:
    group_id = (
        "pe05-"
        + hashlib.sha256(f"{run_id}\0{cohort.cohort_id}".encode()).hexdigest()[:24]
    )
    episode_to_session: dict[str, str] = {}
    episode_ids: list[str] = []
    completion_start = len(completions)
    embedding_start = len(embeddings)
    ingest_started = time.perf_counter()
    try:
        for index, session in enumerate(cohort.sessions):
            result = await graphiti.add_episode(
                name=session.session_id,
                episode_body=_session_text(cohort, index),
                source=EpisodeType.text,
                source_description="Memora chronological conversation session",
                reference_time=_timestamp(session.observed_at),
                group_id=group_id,
            )
            episode_id = str(result.episode.uuid)
            episode_ids.append(episode_id)
            episode_to_session[episode_id] = session.session_id
        ingest_ms = (time.perf_counter() - ingest_started) * 1000
        records = []
        for case in cases:
            started = time.perf_counter()
            search_results = await graphiti.search_(
                case.question,
                config=_search_config(),
                group_ids=[group_id],
            )
            context, sources, trace, tokens = _fit_results(
                search_results,
                tokenizer=tokenizer,
                episode_to_session=episode_to_session,
            )
            records.append(
                ContextRecord(
                    case_id=case.case_id,
                    method_id="GRAPHITI-OSS",
                    track="NATIVE",
                    context=context,
                    source_ids=sources,
                    trace=trace,
                    declared_tokens=tokens,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    usage={
                        "memory_query_api_calls": 1,
                        "edge_results_returned": len(search_results.edges),
                        "episode_results_returned": len(search_results.episodes),
                        "results_returned": len(search_results.edges)
                        + len(search_results.episodes),
                    },
                )
            )
        cohort_completions = completions[completion_start:]
        cohort_embeddings = embeddings[embedding_start:]
        records_count, _, _ = await graphiti.driver.execute_query(
            "MATCH (n {group_id: $group_id}) RETURN count(n) AS count",
            group_id=group_id,
            routing_="r",
        )
        return records, {
            "completion_calls": len(cohort_completions),
            "completion_usage": _usage_totals(cohort_completions),
            "cohort_id": cohort.cohort_id,
            "embedding_calls": len(cohort_embeddings),
            "embedding_usage": _usage_totals(cohort_embeddings),
            "graph_node_count": int(records_count[0]["count"]),
            "group_id_sha256": hashlib.sha256(group_id.encode()).hexdigest(),
            "index_time_ms": round(ingest_ms, 3),
            "question_count": len(cases),
            "session_count": len(cohort.sessions),
        }
    finally:
        for episode_id in reversed(episode_ids):
            await graphiti.remove_episode(episode_id)
        nodes, _, _ = await graphiti.driver.execute_query(
            "MATCH (n {group_id: $group_id}) RETURN count(n) AS count",
            group_id=group_id,
            routing_="r",
        )
        edges, _, _ = await graphiti.driver.execute_query(
            "MATCH ()-[r {group_id: $group_id}]->() RETURN count(r) AS count",
            group_id=group_id,
            routing_="r",
        )
        if int(nodes[0]["count"]) or int(edges[0]["count"]):
            raise MemoraGraphitiError("Graphiti cohort cleanup failed")


async def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    tokenizer_path: Path,
    workers: int,
    neo4j_uri: str,
    neo4j_password: str,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if workers != 2:
        raise MemoraGraphitiError(
            "Graphiti runner requires the frozen worker cap of two"
        )
    if graphiti_telemetry.is_telemetry_enabled():
        raise MemoraGraphitiError("Graphiti telemetry must be disabled")
    if os.environ.get("SEMAPHORE_LIMIT") != "2":
        raise MemoraGraphitiError("Graphiti global coroutine cap must be two")
    _require_inputs(input_path, allow_unfrozen_smoke=allow_unfrozen_smoke)
    if not allow_unfrozen_smoke:
        require_paper_evaluation_ready(freeze_manifest)
    cohorts, cases = load_inputs(input_path)
    cases_by_cohort: dict[str, list[MemoraCase]] = {
        cohort.cohort_id: [] for cohort in cohorts
    }
    for case in cases:
        cases_by_cohort[case.cohort_id].append(case)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    llm_config = LLMConfig(
        api_key="vllm-api-key",
        base_url=VLLM_BASE_URL,
        max_tokens=4096,
        model=MODEL_ID,
        small_model=MODEL_ID,
        temperature=0,
    )
    llm = OpenAIGenericClient(config=llm_config, max_tokens=4096)
    embedder = OpenAIEmbedder(
        OpenAIEmbedderConfig(
            api_key="vllm-api-key",
            base_url=EMBEDDING_BASE_URL,
            embedding_dim=1024,
            embedding_model=EMBEDDING_MODEL,
        )
    )
    reranker = OpenAIRerankerClient(config=llm_config, client=llm)
    graphiti = Graphiti(
        uri=neo4j_uri,
        user="neo4j",
        password=neo4j_password,
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
        max_coroutines=workers,
    )
    completions: list[dict[str, Any]] = []
    embeddings: list[dict[str, Any]] = []
    create_completion = llm.client.chat.completions.create
    create_embedding = embedder.client.embeddings.create

    async def tracked_completion(*args: Any, **kwargs: Any) -> Any:
        response = await create_completion(*args, **kwargs)
        completions.append(
            {
                "completion_id": response.id,
                "model": response.model,
                "usage": response.usage.model_dump()
                if response.usage is not None
                else {},
            }
        )
        return response

    async def tracked_embedding(*args: Any, **kwargs: Any) -> Any:
        response = await create_embedding(*args, **kwargs)
        embeddings.append(
            {
                "item_count": len(response.data),
                "model": response.model,
                "usage": response.usage.model_dump()
                if response.usage is not None
                else {},
            }
        )
        return response

    llm.client.chat.completions.create = tracked_completion
    embedder.client.embeddings.create = tracked_embedding
    records: list[ContextRecord] = []
    cohort_stats: list[dict[str, Any]] = []
    try:
        await graphiti.build_indices_and_constraints()
        for cohort in cohorts:
            cohort_records, stats = await _run_cohort(
                graphiti=graphiti,
                run_id=run_id,
                cohort=cohort,
                cases=cases_by_cohort[cohort.cohort_id],
                tokenizer=tokenizer,
                completions=completions,
                embeddings=embeddings,
            )
            records.extend(cohort_records)
            cohort_stats.append(stats)
    finally:
        await graphiti.close()
    by_key = {(record.case_id, record.method_id): record for record in records}
    ordered = [by_key[(case.case_id, "GRAPHITI-OSS")] for case in cases]
    if len(ordered) != len(cases):
        raise MemoraGraphitiError("Graphiti context denominator drifted")
    return cast(
        dict[str, Any],
        write_context_archive(
            output,
            run_id=run_id,
            benchmark_id="MEMORA-PREREGISTERED-60",
            records=ordered,
            metadata={
                "adapter_identity": {
                    "config_sha256": hashlib.sha256(
                        json.dumps(
                            {
                                "embedding_model": EMBEDDING_MODEL,
                                "llm_model": MODEL_ID,
                                "memory_token_budget": MEMORY_TOKEN_BUDGET,
                                "native_search": {
                                    "edge": "BM25_PLUS_COSINE_RRF",
                                    "episode": "BM25_RRF",
                                    "merge": "RRF_SCORE_RAW_EPISODE_FIRST_ON_TIE",
                                },
                                "top_k": TOP_K,
                                "worker_cap": workers,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "runner_sha256": sha256_file(Path(__file__)),
                },
                "cohort_stats": cohort_stats,
                "failure_count": 0,
                "labels_accessed": False,
                "paper_labels_opened": False,
                "status": "PASS",
                "telemetry": {
                    "disabled": True,
                    "mechanism": "GRAPHITI_TELEMETRY_ENABLED=false before import",
                },
                "worker_count": workers,
            },
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--workers", type=int, choices=(2,), default=2)
    parser.add_argument("--neo4j-uri", default="bolt://127.0.0.1:27964")
    parser.add_argument("--neo4j-password", default="pe05_graphiti")
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        run(
            run_id=args.run_id,
            input_path=args.inputs.resolve(),
            output=args.output.resolve(),
            tokenizer_path=args.tokenizer.resolve(),
            workers=args.workers,
            neo4j_uri=args.neo4j_uri,
            neo4j_password=args.neo4j_password,
            freeze_manifest=args.freeze_manifest.resolve(),
            allow_unfrozen_smoke=args.allow_unfrozen_smoke,
        )
    )
    print(
        json.dumps(
            {"record_count": result["record_count"], "status": result["status"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
