#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.context_preflight import (  # noqa: E402
    select_outcome_blind_context_cases,
    selection_digest,
    source_session_instance_keys,
)
from milai_lab.datasets.registry import load_dataset_manifest  # noqa: E402
from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.longmemeval_gate import (  # noqa: E402
    ArmMetrics,
    admission_checks,
    answer_messages,
    canonical_sha256,
    evidence_budget,
    judge_messages,
    paired_bootstrap_interval,
    percentile,
    ranked_session_metrics,
    reader_visible_gold_session_metrics,
    strict_json_answer,
    strict_json_judgment,
)
from milai_lab.product_adapter.manifest import (  # noqa: E402
    load_product_lock,
    verify_product_lock,
)
from run_product01_s1_context_preflight import (  # noqa: E402
    RuntimeHttpClient,
    _capture_case,
    _case_project,
    _history_events,
    _load_env,
    _observed_at,
    _sha256_bytes,
    _sha256_file,
    _wait_projection,
)

ARMS = ("B0_REPAIRED_UNTREATED", "B1_SIMPLE_RECALL")
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
MODEL_CONTEXT_LIMIT = 65_536
PRODUCT_CONTEXT_CAP = 8_192
ANSWER_RESERVE_TOKENS = 1_024
SAFETY_MARGIN_TOKENS = 256
ANSWER_MAX_TOKENS = 512
JUDGE_MAX_TOKENS = 32
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260901
EXPECTED_PRODUCT_COMMIT = "1b5e4a7122da2b38b9a57bba143215cc0afa3387"
EXPECTED_PRODUCT_LOCK_DIGEST = "44f191ca9ea75d697266f42a11a4b22483d5cf7fe470fb84b33eb7656fa2ac5c"


class S4Error(RuntimeError):
    pass


def _git_head(root: Path) -> str:
    head = (root / ".git/HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        value = (root / ".git" / head.removeprefix("ref: ")).read_text(encoding="utf-8")
        return value.strip()
    if not head:
        raise S4Error("Lab Git identity is unavailable")
    return head


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Product-01 matched S4 LongMemEval gate")
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-lock", type=Path, default=ROOT / "product.lock.json")
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument("--b0-env-file", type=Path, required=True)
    parser.add_argument("--b1-env-file", type=Path, required=True)
    parser.add_argument("--b0-base-url", required=True)
    parser.add_argument("--b1-base-url", required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-count", type=int, choices=(128, 500), required=True)
    parser.add_argument("--capture-concurrency-per-arm", type=int, default=8)
    parser.add_argument("--answer-concurrency", type=int, default=8)
    parser.add_argument("--judge-concurrency", type=int, default=8)
    return parser


def _dataset_path(manifest_path: Path) -> tuple[Path, str]:
    manifest = load_dataset_manifest(manifest_path)
    errors = manifest.verify()
    if errors:
        raise S4Error("dataset pin failed: " + "; ".join(errors))
    relative = manifest.split_files.get("population_500")
    if relative is None:
        raise S4Error("dataset manifest has no population_500 split")
    return Path(manifest.external_root) / relative, manifest.file_sha256[relative]


def _load_population(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, list)
        or len(raw) != 500
        or any(not isinstance(item, dict) for item in raw)
    ):
        raise S4Error("LongMemEval-S population must contain exactly 500 objects")
    return raw


def _select(records: Sequence[Mapping[str, Any]], count: int) -> list[Mapping[str, Any]]:
    if count == 500:
        return list(records)
    selected = select_outcome_blind_context_cases(records, case_count=count)
    selected_ids = {item.question_id for item in selected}
    result = [record for record in records if str(record.get("question_id")) in selected_ids]
    if len(result) != count:
        raise S4Error("outcome-blind repaired slice denominator drifted")
    return result


def _selection_identity(records: Sequence[Mapping[str, Any]], count: int) -> str:
    if count == 500:
        return canonical_sha256([str(record["question_id"]) for record in records])
    return selection_digest(select_outcome_blind_context_cases(records, case_count=count))


def _runtime_session_ids(record: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    question_id = str(record["question_id"])
    raw_ids = record.get("haystack_session_ids")
    gold_ids = record.get("answer_session_ids")
    if not isinstance(raw_ids, list) or not isinstance(gold_ids, list):
        raise S4Error("LongMemEval session labels are invalid")
    instance_keys = source_session_instance_keys(raw_ids)
    runtime = tuple(
        f"lme:{hashlib.sha256(question_id.encode()).hexdigest()[:12]}:"
        f"{hashlib.sha256(key.encode()).hexdigest()[:20]}"
        for key in instance_keys
    )
    relevant = tuple(
        runtime[index] for index, raw_id in enumerate(raw_ids) if raw_id in set(gold_ids)
    )
    if not relevant:
        raise S4Error("LongMemEval evidence labels identify no history session")
    return runtime, relevant


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise S4Error(f"{name} is missing or invalid")
    return value


def _sequence(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise S4Error("trace sequence is missing or invalid")
    return list(value)


def _offset(value: object) -> tuple[int, int]:
    mapping = _mapping(value, "serialized offset")
    start, end = mapping.get("start"), mapping.get("end")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise S4Error("serialized offset is not an exact range")
    return start, end


def _trace_context(
    result: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    identities: Mapping[str, Mapping[str, str]],
    tokenizer: Any,
    evidence_token_budget: int,
) -> dict[str, Any]:
    memory_context = _mapping(result.get("memory_context"), "MemoryContext")
    compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
    raw = _mapping(compile_trace.get("raw_retrieval_trace"), "raw retrieval trace")
    visible = _mapping(compile_trace.get("reader_visible_trace"), "Reader-visible trace")
    context = memory_context.get("text")
    if not isinstance(context, str):
        raise S4Error("MemoryContext text is invalid")
    digest = _sha256_bytes(context.encode())
    parts = _sequence(visible.get("serialization_parts")) if context else []
    replay: list[str] = []
    exact = (
        visible.get("reader_context_sha256") == digest
        and memory_context.get("reader_context_digest") == digest
        and visible.get("serialization_replay_sha256") == digest
        and visible.get("serialization_replay_equivalent") is True
    )
    for part in parts:
        start, end = _offset(part.get("serialized_char_offset"))
        byte_start, byte_end = _offset(part.get("serialized_utf8_byte_offset"))
        char_value = context[start:end]
        byte_value = context.encode()[byte_start:byte_end]
        exact = exact and byte_value.decode() == char_value
        exact = exact and _sha256_bytes(byte_value) == part.get("serialized_part_sha256")
        replay.append(char_value)
    exact = exact and ("\n\n".join(replay) == context if context else not parts)

    rendered = _sequence(visible.get("rendered_units")) if context else []
    visible_evidence: list[str] = []
    unit_char_ranges: list[tuple[str, int, int]] = []
    for unit in rendered:
        start, end = _offset(unit.get("serialized_char_offset"))
        byte_start, byte_end = _offset(unit.get("serialized_utf8_byte_offset"))
        char_value = context[start:end]
        byte_value = context.encode()[byte_start:byte_end]
        exact = exact and byte_value.decode() == char_value
        exact = exact and _sha256_bytes(byte_value) == unit.get("serialized_unit_sha256")
        evidence_ids = unit.get("evidence_ids")
        if not isinstance(evidence_ids, list) or any(
            not isinstance(item, str) for item in evidence_ids
        ):
            raise S4Error("rendered unit evidence identity is invalid")
        visible_evidence.extend(evidence_ids)
        unit_char_ranges.append((str(unit.get("unit_id")), start, end))

    messages = answer_messages(str(record["question"]), str(record["question_date"]), context)
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    if not isinstance(prompt, str):
        raise S4Error("Qwen chat template failed")
    encoded = tokenizer(
        prompt,
        add_special_tokens=False,
        return_offsets_mapping=True,
    )
    token_ids = encoded.get("input_ids")
    offsets = encoded.get("offset_mapping")
    if not isinstance(token_ids, list) or not isinstance(offsets, list):
        raise S4Error("Qwen tokenizer did not expose exact prompt offsets")
    prompt_tokens = len(token_ids)
    unit_token_ranges: list[dict[str, int | str]] = []
    if context:
        context_start = prompt.rfind(context)
        if context_start < 0 or prompt.count(context) != 1:
            raise S4Error("MemoryContext is not a unique Reader prompt span")
        for unit_id, char_start, char_end in unit_char_ranges:
            prompt_start = context_start + char_start
            prompt_end = context_start + char_end
            indexes = [
                index
                for index, value in enumerate(offsets)
                if isinstance(value, (list, tuple))
                and len(value) == 2
                and int(value[1]) > prompt_start
                and int(value[0]) < prompt_end
                and int(value[1]) > int(value[0])
            ]
            if not indexes:
                raise S4Error("Reader-visible Evidence unit has no prompt token range")
            unit_token_ranges.append(
                {
                    "unit_id": unit_id,
                    "reader_prompt_token_start": indexes[0],
                    "reader_prompt_token_end": indexes[-1] + 1,
                }
            )
    exact = (
        exact
        and prompt_tokens + ANSWER_RESERVE_TOKENS + SAFETY_MARGIN_TOKENS <= MODEL_CONTEXT_LIMIT
    )

    candidates = _sequence(raw.get("candidates"))
    ranked_sessions: list[str] = []
    unknown_evidence = 0
    for candidate in candidates:
        evidence_id = candidate.get("evidence_id")
        expected = identities.get(str(evidence_id))
        if expected is None:
            unknown_evidence += 1
            continue
        if (
            any(
                candidate.get(field) != expected[field]
                for field in ("subject_id", "session_id", "turn_id")
            )
            or candidate.get("source_turn_ref") != expected["source_ref"]
        ):
            unknown_evidence += 1
        ranked_sessions.append(expected["session_id"])
    visible_sessions = [
        identities[evidence_id]["session_id"]
        for evidence_id in visible_evidence
        if evidence_id in identities
    ]
    unknown_evidence += sum(evidence_id not in identities for evidence_id in visible_evidence)
    accepted_raw = result.get("accepted_binding_evidence_refs")
    if not isinstance(accepted_raw, list) or any(
        not isinstance(item, str) for item in accepted_raw
    ):
        raise S4Error("accepted binding identity is invalid")
    accepted_sessions = [
        identities[evidence_id]["session_id"]
        for evidence_id in accepted_raw
        if evidence_id in identities
    ]
    unknown_evidence += sum(evidence_id not in identities for evidence_id in accepted_raw)
    sufficiency = _mapping(result.get("sufficiency_decision"), "sufficiency decision")
    runtime_sessions, relevant_sessions = _runtime_session_ids(record)
    contamination = unknown_evidence + sum(
        session_id not in set(runtime_sessions)
        for session_id in ranked_sessions + visible_sessions + accepted_sessions
    )
    retrieval = ranked_session_metrics(ranked_sessions, relevant_sessions)
    coverage = reader_visible_gold_session_metrics(visible_sessions, relevant_sessions)
    wrong_complete = int(
        sufficiency.get("status") == "COMPLETE"
        and not set(relevant_sessions).issubset(accepted_sessions)
    )
    return {
        "context_text": context,
        "context_sha256": digest,
        "reader_prompt_sha256": _sha256_bytes(prompt.encode()),
        "reader_prompt_tokens": prompt_tokens,
        "reader_prompt_unit_token_ranges": unit_token_ranges,
        "evidence_token_budget": evidence_token_budget,
        "reader_visible_trace_exact": exact,
        "ranked_session_ids": ranked_sessions[:5],
        "visible_session_ids": list(dict.fromkeys(visible_sessions)),
        "accepted_session_ids": list(dict.fromkeys(accepted_sessions)),
        "retrieval": retrieval,
        "coverage": coverage,
        "strict_wrong_complete": wrong_complete,
        "contamination_count": contamination,
        "product_status": result.get("status"),
        "sufficiency_status": sufficiency.get("status"),
        "raw_trace_sha256": raw.get("trace_sha256"),
        "admitted_trace_sha256": _mapping(
            compile_trace.get("admitted_evidence_trace"), "admitted trace"
        ).get("trace_sha256"),
        "canonical_mutation_count": int(compile_trace.get("canonical_mutation") is not False),
    }


class VllmClient:
    def __init__(self, base_url: str, concurrency: int) -> None:
        normalized = base_url.rstrip("/").removesuffix("/v1")
        if normalized not in {"http://127.0.0.1:7860", "http://localhost:7860"}:
            raise S4Error("S4 provider must be the frozen loopback vLLM")
        self.base_url = normalized
        self.client = httpx.AsyncClient(
            base_url=normalized,
            timeout=httpx.Timeout(180.0),
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
            trust_env=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def verify(self) -> dict[str, Any]:
        response = await self.client.get("/v1/models")
        response.raise_for_status()
        value = response.json()
        models = value.get("data") if isinstance(value, Mapping) else None
        if not isinstance(models, list) or len(models) != 1 or models[0].get("id") != MODEL_ID:
            raise S4Error("frozen local provider identity drifted")
        return dict(models[0])

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        schema_name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        seed: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.perf_counter()
        response = await self.client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL_ID,
                "messages": list(messages),
                "temperature": 0,
                "top_p": 1,
                "seed": seed,
                "max_tokens": max_tokens,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
            },
        )
        elapsed = (time.perf_counter() - started) * 1_000
        response.raise_for_status()
        value = response.json()
        choices = value.get("choices") if isinstance(value, Mapping) else None
        if not isinstance(choices, list) or len(choices) != 1:
            raise S4Error("provider response choice cardinality drifted")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise S4Error("provider response content is missing")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise S4Error("provider response violated strict JSON") from exc
        if not isinstance(parsed, dict):
            raise S4Error("provider response JSON is not an object")
        usage = value.get("usage") if isinstance(value.get("usage"), Mapping) else {}
        metadata = {
            "provider_request_id": value.get("id"),
            "finish_reason": choice.get("finish_reason"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "elapsed_ms": round(elapsed, 6),
            "response_sha256": _sha256_bytes(content.encode()),
        }
        return parsed, metadata


def _seed(case_id: str, lane: str) -> int:
    digest = hashlib.sha256(f"product01-s4\0{case_id}\0{lane}".encode()).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _answers(record: Mapping[str, Any]) -> list[str]:
    raw = record.get("answer")
    if isinstance(raw, str) and raw.strip():
        return [raw]
    if isinstance(raw, int) and not isinstance(raw, bool):
        return [str(raw)]
    if isinstance(raw, list) and raw and all(isinstance(item, str) and item for item in raw):
        return list(raw)
    raise S4Error("LongMemEval answer label is invalid")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise S4Error("checkpoint row is not an object")
        rows.append(value)
    return rows


async def _context_cell(
    arm: str,
    record: Mapping[str, Any],
    *,
    submitter: RuntimeHttpClient,
    reader: RuntimeHttpClient,
    tokenizer: Any,
    evidence_token_budget: int,
    capture_concurrency: int,
) -> dict[str, Any]:
    case_id = str(record["question_id"])
    started = time.perf_counter()
    try:
        events = _history_events(record)
        outbox_ids, identities = await _capture_case(
            submitter, events, concurrency=capture_concurrency
        )
        await _wait_projection(reader, outbox_ids)
        resolve_started = time.perf_counter()
        result = await reader.request(
            "POST",
            "/v1/memory/resolve",
            {
                "query": record["question"],
                "requested_scope": {"project_ids": [_case_project(case_id)]},
                "required_authority": "INFORMATIONAL",
                "required_freshness": "CURRENT",
                "consistency_mode": "CANONICAL_REQUIRED",
                "reference_time": _observed_at(record["question_date"]),
                "budget": {
                    "max_results": 50,
                    "max_candidates": 120,
                    "max_context_tokens": evidence_token_budget,
                    "max_latency_ms": 2_000,
                },
            },
        )
        resolve_ms = (time.perf_counter() - resolve_started) * 1_000
        trace = _trace_context(
            result,
            record=record,
            identities=identities,
            tokenizer=tokenizer,
            evidence_token_budget=evidence_token_budget,
        )
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "SUCCEEDED",
            "capture_count": len(events),
            "resolve_latency_ms": round(resolve_ms, 6),
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            **trace,
        }
    except Exception as exc:
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "FAILED",
            "failure_class": type(exc).__name__,
            "failure_message": str(exc)[:500],
            "resolve_latency_ms": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_visible_trace_exact": False,
            "strict_wrong_complete": 0,
            "contamination_count": 0,
            "canonical_mutation_count": 0,
        }


async def _run(args: argparse.Namespace) -> int:
    if not 1 <= args.capture_concurrency_per_arm <= 8:
        raise S4Error("context concurrency must be 1..8 per arm and <=16 globally")
    if not 1 <= args.answer_concurrency <= 16 or not 1 <= args.judge_concurrency <= 16:
        raise S4Error("provider lane concurrency must be 1..16")
    if args.output.exists():
        raise S4Error("run output already exists; never overwrite a formal run")

    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise S4Error("Product pin failed: " + "; ".join(verification.errors))
    if lock.git_commit != EXPECTED_PRODUCT_COMMIT or lock.digest != EXPECTED_PRODUCT_LOCK_DIGEST:
        raise S4Error("Product commit or lock digest is outside the frozen S4 contract")

    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    population = _load_population(dataset_path)
    selected = _select(population, args.case_count)
    selection_sha256 = _selection_identity(population, args.case_count)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_root, local_files_only=True, use_fast=True
    )
    if not isinstance(tokenizer.chat_template, str) or not tokenizer.chat_template:
        raise S4Error("local Qwen tokenizer has no chat template")
    fixed_prompt_tokens = max(
        len(
            tokenizer.encode(
                tokenizer.apply_chat_template(
                    answer_messages(str(record["question"]), str(record["question_date"]), ""),
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                ),
                add_special_tokens=False,
            )
        )
        for record in population
    )
    budget = evidence_budget(
        usable_model_context=MODEL_CONTEXT_LIMIT,
        fixed_prompt_tokens=fixed_prompt_tokens,
        answer_reserve_tokens=ANSWER_RESERVE_TOKENS,
        safety_margin_tokens=SAFETY_MARGIN_TOKENS,
        product_cap=PRODUCT_CONTEXT_CAP,
    )
    tokenizer_identity = {
        "root": str(args.tokenizer_root.resolve()),
        "tokenizer_json_sha256": _sha256_file(args.tokenizer_root / "tokenizer.json"),
        "tokenizer_config_sha256": _sha256_file(args.tokenizer_root / "tokenizer_config.json"),
        "chat_template_sha256": _sha256_bytes(tokenizer.chat_template.encode()),
    }

    b0_env, b1_env = _load_env(args.b0_env_file), _load_env(args.b1_env_file)
    candidate_flag = "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED"
    if b0_env.get(candidate_flag, "false").casefold() != "false":
        raise S4Error("B0 is not the repaired untreated configuration")
    if b1_env.get(candidate_flag, "false").casefold() != "true":
        raise S4Error("B1 simple recall flag is not enabled")
    runtimes = {
        ARMS[0]: (
            RuntimeHttpClient(
                args.b0_base_url,
                b0_env["MILAI_AGENT_SUBMITTER_TOKEN"],
                max_connections=args.capture_concurrency_per_arm,
            ),
            RuntimeHttpClient(
                args.b0_base_url, b0_env["MILAI_AGENT_READER_TOKEN"], max_connections=4
            ),
        ),
        ARMS[1]: (
            RuntimeHttpClient(
                args.b1_base_url,
                b1_env["MILAI_AGENT_SUBMITTER_TOKEN"],
                max_connections=args.capture_concurrency_per_arm,
            ),
            RuntimeHttpClient(
                args.b1_base_url, b1_env["MILAI_AGENT_READER_TOKEN"], max_connections=4
            ),
        ),
    }
    provider = VllmClient(args.vllm_base_url, max(args.answer_concurrency, args.judge_concurrency))
    model = await provider.verify()
    for _submitter, reader in runtimes.values():
        capabilities = await reader.request("GET", "/v1/capabilities")
        if capabilities.get("contract_version") != "agent.v1":
            raise S4Error("Runtime agent contract is incompatible")

    artifacts = RunArtifacts(args.output)
    started_at = datetime.now(UTC)
    run_id = f"product01-s4-{args.case_count}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    formal = args.case_count == 500
    run_payload = {
        "schema_version": "milai-product01-s4-run-v1",
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": started_at.isoformat(),
        "case_count": args.case_count,
        "cell_count": args.case_count * 2,
        "arms": list(ARMS),
        "interleaving": "CASE_MAJOR_B0_THEN_B1_CONCURRENT",
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "lab_commit": _git_head(ROOT),
        "harness_sha256": _sha256_file(Path(__file__)),
        "scorer_sha256": _sha256_file(ROOT / "src/milai_lab/longmemeval_gate.py"),
        "dataset_sha256": dataset_sha256,
        "selection_sha256": selection_sha256,
        "formal_holdout_consumed": formal,
        "formal_holdout_authorization": ("USER_REQUEST_FULL_GOAL_2026-09-01" if formal else None),
        "model": {
            "id": MODEL_ID,
            "base_url": args.vllm_base_url,
            "served_model": model,
            "same_model_self_judge": True,
        },
        "tokenizer": tokenizer_identity,
        "budget": {
            "formula": "min(product_cap, usable_context-fixed_prompt-answer_reserve-safety_margin)",
            "usable_model_context": MODEL_CONTEXT_LIMIT,
            "max_fixed_prompt_tokens_population": fixed_prompt_tokens,
            "answer_reserve_tokens": ANSWER_RESERVE_TOKENS,
            "safety_margin_tokens": SAFETY_MARGIN_TOKENS,
            "product_cap": PRODUCT_CONTEXT_CAP,
            "evidence_tokens": budget,
            "whole_evidence_units_only": True,
        },
        "concurrency": {
            "context_per_arm": args.capture_concurrency_per_arm,
            "context_global_ceiling": args.capture_concurrency_per_arm * 2,
            "answer": args.answer_concurrency,
            "judge": args.judge_concurrency,
        },
        "generation": {
            "temperature": 0,
            "top_p": 1,
            "answer_max_tokens": ANSWER_MAX_TOKENS,
            "judge_max_tokens": JUDGE_MAX_TOKENS,
            "semantic_retries": 0,
            "technical_retry_ceiling_after_health_check": 1,
            "technical_retries_used": 0,
            "votes": 0,
        },
        "prompt_contract": {
            "answer_messages_empty_sha256": canonical_sha256(answer_messages("", "", "")),
            "judge_messages_empty_sha256": canonical_sha256(judge_messages("", [""], "")),
            "strict_json_schema": True,
        },
        "labels_opened_for_provider_prompts": False,
        "answers_complete_before_judges": True,
    }
    artifacts.write_json("run.json", run_payload)

    rows: list[dict[str, Any]] = []
    final_runtime_health = False
    try:
        for ordinal, record in enumerate(selected, start=1):
            cells = await asyncio.gather(
                *(
                    _context_cell(
                        arm,
                        record,
                        submitter=runtimes[arm][0],
                        reader=runtimes[arm][1],
                        tokenizer=tokenizer,
                        evidence_token_budget=budget,
                        capture_concurrency=args.capture_concurrency_per_arm,
                    )
                    for arm in ARMS
                )
            )
            for cell in cells:
                artifacts.append_jsonl("cases.jsonl", cell)
                rows.append(cell)
            print(
                json.dumps(
                    {
                        "stage": "context",
                        "case": f"{ordinal}/{args.case_count}",
                        "case_id": record["question_id"],
                        "arms": [cell["status"] for cell in cells],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        context_by_key = {
            (str(row["arm"]), str(row["case_id"])): row for row in rows if row["stage"] == "context"
        }
        answer_semaphore = asyncio.Semaphore(args.answer_concurrency)

        async def answer_one(arm: str, record: Mapping[str, Any]) -> dict[str, Any]:
            case_id = str(record["question_id"])
            context = context_by_key[(arm, case_id)]
            if context["status"] != "SUCCEEDED":
                return {
                    "stage": "answer",
                    "arm": arm,
                    "case_id": case_id,
                    "status": "NOT_CALLED_CONTEXT_FAILED",
                    "provider_called": False,
                    "answer": "",
                }
            async with answer_semaphore:
                try:
                    value, metadata = await provider.complete(
                        answer_messages(
                            str(record["question"]),
                            str(record["question_date"]),
                            str(context["context_text"]),
                        ),
                        schema_name="milai_longmemeval_answer",
                        schema={
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                            "additionalProperties": False,
                        },
                        max_tokens=ANSWER_MAX_TOKENS,
                        seed=_seed(case_id, "answer"),
                    )
                    answer = strict_json_answer(value)
                    return {
                        "stage": "answer",
                        "arm": arm,
                        "case_id": case_id,
                        "status": "SUCCEEDED",
                        "provider_called": True,
                        "answer": answer,
                        "answer_sha256": _sha256_bytes(answer.encode()),
                        **metadata,
                    }
                except Exception as exc:
                    return {
                        "stage": "answer",
                        "arm": arm,
                        "case_id": case_id,
                        "status": "FAILED",
                        "provider_called": True,
                        "answer": "",
                        "failure_class": type(exc).__name__,
                        "failure_message": str(exc)[:500],
                    }

        answers = await asyncio.gather(
            *(answer_one(arm, record) for record in selected for arm in ARMS)
        )
        for row in answers:
            artifacts.append_jsonl("cases.jsonl", row)
            rows.append(row)
        print(json.dumps({"stage": "answers-sealed", "count": len(answers)}), flush=True)

        answer_by_key = {(str(row["arm"]), str(row["case_id"])): row for row in answers}
        judge_semaphore = asyncio.Semaphore(args.judge_concurrency)

        async def judge_one(arm: str, record: Mapping[str, Any]) -> dict[str, Any]:
            case_id = str(record["question_id"])
            answer = answer_by_key[(arm, case_id)]
            if answer["status"] != "SUCCEEDED":
                return {
                    "stage": "judge",
                    "arm": arm,
                    "case_id": case_id,
                    "status": "NOT_CALLED_ANSWER_FAILED",
                    "provider_called": False,
                    "correct": False,
                }
            async with judge_semaphore:
                try:
                    value, metadata = await provider.complete(
                        judge_messages(
                            str(record["question"]), _answers(record), str(answer["answer"])
                        ),
                        schema_name="milai_longmemeval_judgment",
                        schema={
                            "type": "object",
                            "properties": {"correct": {"type": "boolean"}},
                            "required": ["correct"],
                            "additionalProperties": False,
                        },
                        max_tokens=JUDGE_MAX_TOKENS,
                        seed=_seed(case_id, "judge"),
                    )
                    correct = strict_json_judgment(value)
                    return {
                        "stage": "judge",
                        "arm": arm,
                        "case_id": case_id,
                        "status": "SUCCEEDED",
                        "provider_called": True,
                        "correct": correct,
                        **metadata,
                    }
                except Exception as exc:
                    return {
                        "stage": "judge",
                        "arm": arm,
                        "case_id": case_id,
                        "status": "FAILED",
                        "provider_called": True,
                        "correct": False,
                        "failure_class": type(exc).__name__,
                        "failure_message": str(exc)[:500],
                    }

        judges = await asyncio.gather(
            *(judge_one(arm, record) for record in selected for arm in ARMS)
        )
        for row in judges:
            artifacts.append_jsonl("cases.jsonl", row)
            rows.append(row)
        print(json.dumps({"stage": "judges-sealed", "count": len(judges)}), flush=True)
        health_checks: list[bool] = []
        for _submitter, reader in runtimes.values():
            capabilities = await reader.request("GET", "/v1/capabilities")
            health_checks.append(capabilities.get("contract_version") == "agent.v1")
        final_runtime_health = all(health_checks)
    finally:
        for submitter, reader in runtimes.values():
            await submitter.close()
            await reader.close()
        await provider.close()

    context_rows = [row for row in rows if row["stage"] == "context"]
    answer_rows = [row for row in rows if row["stage"] == "answer"]
    judge_rows = [row for row in rows if row["stage"] == "judge"]
    judge_by_key = {(str(row["arm"]), str(row["case_id"])): row for row in judge_rows}
    arm_metrics: dict[str, ArmMetrics] = {}
    arm_payloads: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        contexts = [row for row in context_rows if row["arm"] == arm]
        judgments = [row for row in judge_rows if row["arm"] == arm]
        succeeded = [row for row in contexts if row["status"] == "SUCCEEDED"]
        latencies = [float(row["resolve_latency_ms"]) for row in succeeded]
        if not latencies:
            latencies = [float("inf")]
        metrics = ArmMetrics(
            case_count=args.case_count,
            system_context_success_rate=len(succeeded) / args.case_count,
            session_recall_at_5=sum(
                float(row["retrieval"]["session_recall_at_5"]) for row in succeeded
            )
            / args.case_count,
            session_ndcg_at_5=sum(float(row["retrieval"]["session_ndcg_at_5"]) for row in succeeded)
            / args.case_count,
            all_required_evidence_group_coverage=sum(
                int(row["coverage"]["all_required_evidence_group_coverage"]) for row in succeeded
            )
            / args.case_count,
            reader_visible_gold_session_coverage=sum(
                float(row["coverage"]["reader_visible_gold_session_coverage"])
                for row in succeeded
            )
            / args.case_count,
            qwen_judge_accuracy=sum(bool(row["correct"]) for row in judgments) / args.case_count,
            strict_wrong_complete=sum(int(row["strict_wrong_complete"]) for row in contexts),
            p50_latency_ms=percentile(latencies, 0.50),
            p95_latency_ms=percentile(latencies, 0.95),
            leak_count=sum(int(row["contamination_count"]) for row in contexts),
        )
        arm_metrics[arm] = metrics
        arm_payloads[arm] = {
            **asdict(metrics),
            "reader_visible_trace_exactness": sum(
                row.get("reader_visible_trace_exact") is True for row in contexts
            )
            / args.case_count,
            "canonical_mutation_count": sum(
                int(row.get("canonical_mutation_count", 0)) for row in contexts
            ),
            "context_failure_counts": dict(
                Counter(
                    str(row.get("failure_class"))
                    for row in contexts
                    if row["status"] != "SUCCEEDED"
                )
            ),
            "answer_success_count": sum(
                row["arm"] == arm and row["status"] == "SUCCEEDED" for row in answer_rows
            ),
            "judge_success_count": sum(row["status"] == "SUCCEEDED" for row in judgments),
        }

    b0_judges = [
        bool(judge_by_key[(ARMS[0], str(record["question_id"]))]["correct"]) for record in selected
    ]
    b1_judges = [
        bool(judge_by_key[(ARMS[1], str(record["question_id"]))]["correct"]) for record in selected
    ]
    ci_low, ci_high = paired_bootstrap_interval(
        b0_judges, b1_judges, samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED
    )
    deltas = {
        "evidence_group_coverage": (
            arm_metrics[ARMS[1]].all_required_evidence_group_coverage
            - arm_metrics[ARMS[0]].all_required_evidence_group_coverage
        ),
        "qwen_judge_accuracy": (
            arm_metrics[ARMS[1]].qwen_judge_accuracy - arm_metrics[ARMS[0]].qwen_judge_accuracy
        ),
        "p95_latency_ratio": (
            arm_metrics[ARMS[1]].p95_latency_ms / arm_metrics[ARMS[0]].p95_latency_ms
        ),
        "paired_judge_ci_95": [ci_low, ci_high],
        "paired_wins": sum(
            right and not left for left, right in zip(b0_judges, b1_judges, strict=True)
        ),
        "paired_losses": sum(
            left and not right for left, right in zip(b0_judges, b1_judges, strict=True)
        ),
    }
    entry_checks = {
        "ProductManifestAndLabPin": True,
        "PriorS0IsolatedPostgresWorker": True,
        "PriorS1IdentityVisibility": True,
        "SystemContextSuccessRate": min(
            arm_metrics[arm].system_context_success_rate for arm in ARMS
        )
        >= (0.99 if formal else 0.98),
        "SystemicWorkerExit": final_runtime_health,
        "CrossSessionContamination": all(
            metrics.leak_count == 0 for metrics in arm_metrics.values()
        ),
        "ReaderVisibleTraceExactness": all(
            arm_payloads[arm]["reader_visible_trace_exactness"] == 1.0 for arm in ARMS
        ),
        "StrictWrongComplete": all(
            metrics.strict_wrong_complete == 0 for metrics in arm_metrics.values()
        ),
        "CandidateFeatureDefaultOff": True,
    }
    final_checks = (
        admission_checks(arm_metrics[ARMS[0]], arm_metrics[ARMS[1]], paired_ci_lower=ci_low)
        if formal
        else {}
    )
    passed = all(entry_checks.values()) and (not formal or all(final_checks.values()))
    metrics_payload = {
        "schema_version": "milai-product01-s4-metrics-v1",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "arms": arm_payloads,
        "deltas": deltas,
        "entry_checks": entry_checks,
        "candidate_admission_checks": final_checks,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
        "same_qwen_self_judge": True,
        "leaderboard_equivalence_claimed": False,
        "semantic_retries": 0,
        "technical_retries_used": 0,
        "votes": 0,
    }
    artifacts.write_json("metrics.json", metrics_payload)
    finished_at = datetime.now(UTC)
    terminal = {
        "schema_version": "milai-product01-s4-terminal-v1",
        "run_id": run_id,
        "status": (
            "PASS_S4_LONGMEMEVAL_CONFIRMED"
            if passed and formal
            else "PASS_S4_128_ENTRY_READY_FOR_FORMAL_500"
            if passed
            else "FAIL_S4_REPAIR_OR_KEEP_BASELINE"
        ),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
        "case_count": args.case_count,
        "formal_holdout_consumed": formal,
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "selection_sha256": selection_sha256,
        "run_sha256": canonical_sha256(run_payload),
        "cases_sha256": _sha256_file(args.output / "cases.jsonl"),
        "metrics_sha256": canonical_sha256(metrics_payload),
        "candidate_default_enabled": False,
        "selected_disposition": (
            "B1_SIMPLE_RECALL"
            if passed and formal
            else "PENDING_FORMAL_500"
            if passed
            else "KEEP_BASELINE_OR_REPAIR"
        ),
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if passed else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"S4 failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
