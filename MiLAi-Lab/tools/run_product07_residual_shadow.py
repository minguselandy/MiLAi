#!/usr/bin/env python3
"""Freeze Qwen observation-conditioned residual-query proposals for Product-07."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product05_openworker_lme import (
    MODEL,
    PRODUCT,
    PROVIDER_ENDPOINT,
    _load_inputs,
    _sha256_file,
    _sha256_text,
)
from run_product07_context_replay import (
    DEFAULT_LABELS,
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    DEFAULT_SELECTION,
    DEFAULT_SOURCE_RUN,
    DEFAULT_SOURCE_SELECTION,
    _one_case,
    _write_json,
    _write_jsonl,
)

_FORBIDDEN_QUERY = re.compile(
    r"(?:\b(?:select|insert|update|delete|drop|alter|create)\b|"
    r"\b(?:tenant|scope|candidate\s+cap|tool\s+name|complete)\b)",
    re.IGNORECASE,
)

_POLICY = """You are a bounded memory-retrieval query planner. Inspect the exact
user question and the complete governed Reader-visible Context. Do not answer the
question. Decide whether another memory search could retrieve missing, complementary
evidence. If no useful search remains, return ANSWER with an empty queries list. If
useful evidence may be missing, return SEARCH with one to three short additive
natural-language search queries. Preserve the question's named entities, relation,
time, and units, but use plausible wording from remembered conversations. Do not
repeat the original question. Never emit SQL, code, a tool name, tenant/scope,
budgets, or COMPLETE."""


class ResidualShadowError(RuntimeError):
    pass


def _response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "Product07ResidualDecisionV01",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["ANSWER", "SEARCH"]},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 240},
                        "maxItems": 3,
                    },
                },
                "required": ["action", "queries"],
                "additionalProperties": False,
            },
        },
    }


def _validated_decision(content: str, original_query: str) -> tuple[str, list[str]]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ResidualShadowError("residual decision is not JSON") from exc
    if not isinstance(value, Mapping) or set(value) != {"action", "queries"}:
        raise ResidualShadowError("residual decision shape is invalid")
    action = value.get("action")
    raw_queries = value.get("queries")
    if action not in {"ANSWER", "SEARCH"} or not isinstance(raw_queries, list):
        raise ResidualShadowError("residual decision values are invalid")
    queries: list[str] = []
    original = " ".join(original_query.split()).casefold()
    for raw in raw_queries:
        if not isinstance(raw, str):
            raise ResidualShadowError("residual query is not text")
        query = " ".join(raw.split())
        if (
            not 1 <= len(query) <= 240
            or query.casefold() == original
            or _FORBIDDEN_QUERY.search(query) is not None
        ):
            raise ResidualShadowError("residual query crossed its bounded language")
        if query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
    if action == "ANSWER" and queries:
        raise ResidualShadowError("ANSWER decision supplied residual queries")
    if action == "SEARCH" and not 1 <= len(queries) <= 3:
        raise ResidualShadowError("SEARCH decision did not supply one to three queries")
    return str(action), queries


async def _propose(
    client: httpx.AsyncClient,
    *,
    question: str,
    context: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": _POLICY},
                {
                    "role": "user",
                    "content": (
                        f"EXACT_QUESTION\n{question}\n\n"
                        f"READER_VISIBLE_CONTEXT\n{context}"
                    ),
                },
            ],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 256,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": _response_format(),
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1_000
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, Mapping) else None
    message = (
        choices[0].get("message")
        if isinstance(choices, list)
        and len(choices) == 1
        and isinstance(choices[0], Mapping)
        else None
    )
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise ResidualShadowError("residual decision content is absent")
    action, queries = _validated_decision(content, question)
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    return {
        "action": action,
        "queries": queries,
        "provider": {
            "model": MODEL,
            "calls": 1,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": (
                choices[0].get("finish_reason")
                if isinstance(choices, list) and isinstance(choices[0], Mapping)
                else None
            ),
            "response_sha256": _sha256_text(content),
            "elapsed_ms": round(elapsed_ms, 3),
            "semantic_retries": 0,
        },
    }


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ResidualShadowError("output path already exists")
    args.output.mkdir(mode=0o700, parents=True)
    selected, identities = _load_inputs(
        args.selection,
        args.source_selection,
        args.dataset_manifest,
        "V0",
    )
    baseline_rows = {
        int(value["ordinal"]): value
        for value in (
            json.loads(line)
            for line in (args.baseline_run / "cases.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        )
    }
    requested = (
        {int(value) for value in args.ordinals.split(",") if value.strip()}
        if args.ordinals
        else {
            ordinal
            for ordinal, value in baseline_rows.items()
            if value["retrieval_metrics"]["all_required_evidence_group_recall"]
            is False
        }
    )
    selected_rows = [
        (ordinal, metadata, record)
        for ordinal, (metadata, record) in enumerate(selected, start=1)
        if ordinal in requested
    ]
    if requested != {value[0] for value in selected_rows}:
        raise ResidualShadowError("requested ordinal is outside frozen V0")
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, PRODUCT)
    if not verification.valid:
        raise ResidualShadowError("Product pin failed: " + "; ".join(verification.errors))
    label_payload = json.loads(args.answer_turn_labels.read_text(encoding="utf-8"))
    labels = {
        str(value["case_id"]): value
        for value in label_payload.get("cases", [])
        if isinstance(value, Mapping) and isinstance(value.get("case_id"), str)
    }
    source_payload = json.loads((args.source_run / "run.json").read_text(encoding="utf-8"))
    run_lock = {
        "schema": "milai.product07.residual-shadow.run-lock.v1",
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "stage": "S2_RESIDUAL_SHADOW",
        "product_lock_sha256": _sha256_file(args.product_lock),
        "product_tree_sha256": lock.tree_sha256,
        "source_run_id": source_payload.get("run_id"),
        "source_run_sha256": _sha256_file(args.source_run / "run.json"),
        "baseline_summary_sha256": _sha256_file(args.baseline_run / "summary.json"),
        "selection_sha256": identities["selection_sha256"],
        "dataset_sha256": identities["dataset_sha256"],
        "model": MODEL,
        "ordinals": sorted(requested),
        "answer_calls": 0,
        "judge_calls": 0,
        "residual_execution_calls": 0,
        "semantic_retries": 0,
        "formal_holdout_consumed": False,
    }
    _write_json(args.output / "run-lock.json", run_lock)
    scratch = Path(tempfile.mkdtemp(prefix="m7-residual-shadow-", dir="/tmp"))
    scratch.chmod(0o700)
    semaphore = asyncio.Semaphore(args.case_concurrency)
    client = httpx.AsyncClient(
        base_url=PROVIDER_ENDPOINT,
        timeout=httpx.Timeout(180),
        trust_env=False,
        limits=httpx.Limits(max_connections=args.case_concurrency),
    )

    async def one(
        ordinal: int,
        metadata: dict[str, Any],
        record: dict[str, Any],
    ) -> dict[str, Any]:
        async with semaphore:
            replay = await _one_case(
                ordinal=ordinal,
                metadata=metadata,
                record=record,
                answer_label=labels[str(record["question_id"])],
                source_run=args.source_run,
                scratch=scratch,
                treatment=True,
            )
            decision = await _propose(
                client,
                question=str(record["question"]),
                context=str(replay["_context_text"]),
            )
            return {
                "ordinal": ordinal,
                "case_id_sha256": _sha256_text(str(record["question_id"])),
                "query_type": metadata.get("query_type"),
                "capability_family": metadata.get("capability_family"),
                "initial_context_sha256": replay["context_sha256"],
                "initial_retrieval_metrics": replay["retrieval_metrics"],
                **decision,
            }

    started = time.perf_counter()
    failures: list[dict[str, Any]] = []
    try:
        gathered = await asyncio.gather(
            *(one(*value) for value in selected_rows),
            return_exceptions=True,
        )
    finally:
        await client.aclose()
        shutil.rmtree(scratch)
    rows: list[dict[str, Any]] = []
    for source, value in zip(selected_rows, gathered, strict=True):
        if isinstance(value, BaseException):
            failures.append(
                {
                    "ordinal": source[0],
                    "case_id_sha256": _sha256_text(str(source[2]["question_id"])),
                    "category": "INFRASTRUCTURE_OR_MODEL_CONTRACT",
                    "message": str(value),
                }
            )
        else:
            rows.append(value)
    rows.sort(key=lambda value: int(value["ordinal"]))
    _write_jsonl(args.output / "cases.jsonl", rows)
    _write_jsonl(args.output / "failure-notes.jsonl", failures)
    provider_calls = sum(int(value["provider"]["calls"]) for value in rows)
    query_count = sum(len(value["queries"]) for value in rows)
    summary = {
        "schema": "milai.product07.residual-shadow.summary.v1",
        "run_id": args.run_id,
        "stage": "S2_RESIDUAL_SHADOW",
        "case_count": len(rows),
        "failure_count": len(failures),
        "search_decision_count": sum(value["action"] == "SEARCH" for value in rows),
        "answer_now_decision_count": sum(value["action"] == "ANSWER" for value in rows),
        "proposed_query_count": query_count,
        "provider_calls": provider_calls,
        "answer_calls": 0,
        "judge_calls": 0,
        "residual_execution_calls": 0,
        "semantic_retries": 0,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        "formal_holdout_consumed": False,
    }
    _write_json(args.output / "summary.json", summary)
    terminal = {
        "schema": "milai.product07.residual-shadow.terminal.v1",
        "run_id": args.run_id,
        "terminal": (
            "PASS_RESIDUAL_PROPOSALS_FROZEN"
            if not failures and provider_calls == len(selected_rows)
            else "FAIL_RESIDUAL_SHADOW"
        ),
        "summary_sha256": _sha256_file(args.output / "summary.json"),
        "answer_or_judge_executed": False,
        "formal_holdout_consumed": False,
    }
    _write_json(args.output / "terminal.json", terminal)
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--source-selection", type=Path, default=DEFAULT_SOURCE_SELECTION)
    parser.add_argument("--answer-turn-labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--baseline-run",
        type=Path,
        default=Path("var/product07/s1-v0-simple-r2"),
    )
    parser.add_argument("--ordinals", default="")
    parser.add_argument("--case-concurrency", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in (
        "source_run",
        "selection",
        "source_selection",
        "answer_turn_labels",
        "dataset_manifest",
        "product_lock",
        "baseline_run",
        "output",
    ):
        setattr(args, name, getattr(args, name).resolve(strict=False))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
