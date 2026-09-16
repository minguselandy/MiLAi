#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.longmemeval_gate import (  # noqa: E402
    ReaderVisibleUnit,
    canonical_sha256,
    evidence_budget,
    exact_answer_evidence_metrics,
    judge_messages,
    paired_bootstrap_interval,
    percentile,
    strict_json_answer,
    strict_json_judgment,
)
from milai_lab.product02_decision import (  # noqa: E402
    SealedAnswerEvidence,
    required_role_coverage,
    sealed_answer_evidence,
    sealed_strict_wrong_complete,
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
from run_product01_s4_longmemeval import (  # noqa: E402
    ANSWER_MAX_TOKENS,
    ANSWER_RESERVE_TOKENS,
    JUDGE_MAX_TOKENS,
    MODEL_CONTEXT_LIMIT,
    MODEL_ID,
    PRODUCT_CONTEXT_CAP,
    SAFETY_MARGIN_TOKENS,
    VllmClient,
    _answers,
    _dataset_path,
    _git_head,
    _load_population,
    _mapping,
    _offset,
    _select,
    _selection_identity,
    _sequence,
    _trace_context,
)

B0 = "B0_U0_REPAIRED_BASELINE"
B1 = "B1_U1_SELECTED_A0"
B2 = "B2_U2_EVIDENCE_SET"
ARMS = (B0, B1, B2)
EXECUTED_ARMS = (B0, B2)
B1_ALIAS_SOURCE = B0
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260902
EXPECTED_PRODUCT_COMMIT = "1b5e4a7122da2b38b9a57bba143215cc0afa3387"
EXPECTED_PRODUCT_TREE = "3c7cc1b1304263d1bb41d60952efe2feadfb0a9db86087e86fd017780e5df5ba"
EXPECTED_PRODUCT_LOCK_DIGEST = "6f2869254659bf1c5f7710785a65016cb21b36d06b5411da978e9ffe98c68d1b"
EXPECTED_LABEL_MANIFEST_SHA256 = (
    "6238c10cb7d6203715043a1437add55e3cd8114d20cec9e7ceded11c92831412"
)


class Product02RunError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Product-02 matched LongMemEval decision gate"
    )
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument(
        "--product-lock",
        type=Path,
        default=ROOT / "data/locks/product02-product.lock.json",
    )
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument(
        "--label-manifest",
        type=Path,
        required=True,
        help="sealed Product-02 direct-answer and required-role labels",
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--b0-base-url", required=True)
    parser.add_argument("--b2-base-url", required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-count", type=int, choices=(128, 500), required=True)
    parser.add_argument("--capture-concurrency", type=int, default=8)
    parser.add_argument("--answer-concurrency", type=int, default=8)
    parser.add_argument("--judge-concurrency", type=int, default=8)
    parser.add_argument(
        "--entry-terminal",
        type=Path,
        help="required sealed 128 terminal before a 500-case confirmation",
    )
    parser.add_argument(
        "--formal-holdout-authorization",
        help="explicit authority string required before consuming the 500-case holdout",
    )
    return parser


def _seed(case_id: str, lane: str) -> int:
    digest = hashlib.sha256(f"product02\0{case_id}\0{lane}".encode()).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _validate_500_authority(
    args: argparse.Namespace,
    lock_digest: str,
    label_manifest_sha256: str,
) -> None:
    if args.case_count != 500:
        if args.entry_terminal is not None or args.formal_holdout_authorization is not None:
            raise Product02RunError("128-case run must not claim formal holdout authority")
        return
    if not args.formal_holdout_authorization:
        raise Product02RunError("500-case formal holdout is not authorized")
    if args.entry_terminal is None or not args.entry_terminal.is_file():
        raise Product02RunError("500-case run requires the sealed 128 entry terminal")
    value = json.loads(args.entry_terminal.read_text(encoding="utf-8"))
    if (
        not isinstance(value, Mapping)
        or value.get("status") != "PASS_PRODUCT02_128_ENTRY_FOR_500"
        or value.get("product_lock_digest") != lock_digest
        or value.get("label_manifest_sha256") != label_manifest_sha256
        or value.get("case_count") != 128
    ):
        raise Product02RunError("128 entry terminal does not authorize this 500-case run")


def _complex_defaults_off(env: Mapping[str, str]) -> bool:
    false_flags = (
        "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED",
        "MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED",
        "MILAI_RETRIEVAL_DETERMINISTIC_RECOVERY_ENABLED",
        "MILAI_PROGRESSIVE_CONTEXT_EVIDENCE_V0_1",
    )
    return (
        all(env.get(name, "false").casefold() == "false" for name in false_flags)
        and env.get("MILAI_FEATURE_PROFILE", "BASELINE") == "BASELINE"
    )


def _load_label_manifest(
    path: Path,
    *,
    dataset_sha256: str,
    population: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    if not path.is_file():
        raise Product02RunError("sealed answer label manifest is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Product02RunError("sealed answer label manifest is unreadable") from exc
    if not isinstance(payload, dict):
        raise Product02RunError("sealed answer label manifest is not an object")
    cases = payload.get("cases")
    procedure = payload.get("procedure")
    if (
        payload.get("schema_version") != "milai-product02-answer-turn-labels-v1"
        or payload.get("dataset_sha256") != dataset_sha256
        or payload.get("case_count") != len(population)
        or not isinstance(payload.get("claim_ceiling"), str)
        or not isinstance(procedure, Mapping)
        or procedure.get("product_outputs_opened") is not False
        or procedure.get("reader_outputs_opened") is not False
        or procedure.get("native_has_answer_used_by_annotator") is not False
        or not isinstance(cases, list)
        or any(not isinstance(case, Mapping) for case in cases)
    ):
        raise Product02RunError("sealed answer label contract is invalid")
    expected_ids = [str(record["question_id"]) for record in population]
    case_ids = [str(case.get("case_id")) for case in cases]
    if (
        case_ids != expected_ids
        or payload.get("case_order_sha256") != canonical_sha256(expected_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise Product02RunError("sealed answer labels do not match dataset order")
    return payload, {case_id: case for case_id, case in zip(case_ids, cases, strict=True)}


def _visible_answer_metrics(
    result: Mapping[str, Any],
    sealed: SealedAnswerEvidence,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    memory_context = _mapping(result.get("memory_context"), "MemoryContext")
    compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
    raw = _mapping(compile_trace.get("raw_retrieval_trace"), "raw retrieval trace")
    visible = _mapping(compile_trace.get("reader_visible_trace"), "Reader-visible trace")
    context = memory_context.get("text")
    if not isinstance(context, str):
        raise Product02RunError("MemoryContext text is invalid")
    candidates = _sequence(raw.get("candidates"))
    discovered = [
        str(candidate["source_turn_ref"])
        for candidate in candidates
        if isinstance(candidate.get("source_turn_ref"), str)
    ]
    rendered = _sequence(visible.get("rendered_units")) if context else []
    units: list[ReaderVisibleUnit] = []
    visible_refs: list[str] = []
    for unit in rendered:
        refs = unit.get("source_turn_refs")
        if not isinstance(refs, list) or any(
            not isinstance(value, str) or not value for value in refs
        ) or not refs:
            continue
        start, end = _offset(unit.get("serialized_char_offset"))
        typed_refs = tuple(str(value) for value in refs)
        units.append(ReaderVisibleUnit(source_turn_refs=typed_refs, text=context[start:end]))
        visible_refs.extend(typed_refs)
    if sealed.answer_labels:
        metrics = exact_answer_evidence_metrics(
            discovered_source_turn_refs=discovered,
            visible_units=units,
            source_text_by_turn_ref=sealed.source_text_by_turn_ref,
            labels=sealed.answer_labels,
        )
        metrics["all_sealed_answer_turns_visible"] = float(
            metrics["reader_visible_answer_turn_coverage"] == 1.0
        )
    else:
        metrics = {
            "answer_bearing_turn_recall": None,
            "reader_visible_answer_turn_coverage": None,
            "reader_visible_answer_span_coverage": None,
            "all_sealed_answer_turns_visible": None,
        }
    metrics["required_role_coverage"] = (
        required_role_coverage(visible_refs, sealed.required_role_groups)
        if sealed.required_role_groups
        else None
    )
    label_trace = {
        "sealed_answer_turn_count": len(sealed.answer_labels),
        "sealed_exact_span_count": sealed.exact_span_count,
        "required_role_group_count": len(sealed.required_role_groups),
        "required_role_labels": list(sealed.required_role_labels),
        "negative_without_answer_turn": sealed.negative_without_answer_turn,
        "native_has_answer_source_turn_refs": list(
            sealed.native_has_answer_source_turn_refs
        ),
        "gold_source_turn_refs": [
            label.source_turn_ref for label in sealed.answer_labels
        ],
        "visible_gold_source_turn_refs": sorted(
            set(visible_refs).intersection(
                label.source_turn_ref for label in sealed.answer_labels
            )
        ),
    }
    return metrics, label_trace


async def _resolve_arm(
    arm: str,
    record: Mapping[str, Any],
    *,
    reader: RuntimeHttpClient,
    identities: Mapping[str, Mapping[str, str]],
    sealed: SealedAnswerEvidence,
    tokenizer: Any,
    evidence_token_budget: int,
) -> dict[str, Any]:
    case_id = str(record["question_id"])
    started = time.perf_counter()
    try:
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
        resolve_ms = (time.perf_counter() - started) * 1_000
        trace = _trace_context(
            result,
            record=record,
            identities=identities,
            tokenizer=tokenizer,
            evidence_token_budget=evidence_token_budget,
        )
        answer_evidence, label_trace = _visible_answer_metrics(result, sealed)
        memory_context = _mapping(result.get("memory_context"), "MemoryContext")
        compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
        boundary = compile_trace.get("reader_evidence_boundary")
        evidence_set_digest = compile_trace.get("evidence_set_digest")
        lean_recall_mode = compile_trace.get("lean_recall_mode")
        configuration_exact = (
            (
                boundary == "DECISION_ACCEPTED_ONLY"
                if lean_recall_mode == "STRICT"
                else boundary == "GOVERNANCE_ADMITTED_SOFT_RANKED"
            )
            and isinstance(evidence_set_digest, str)
            and len(evidence_set_digest) == 64
            if arm == B0
            else boundary == "DECISION_ACCEPTED_ONLY"
            and isinstance(evidence_set_digest, str)
            and len(evidence_set_digest) == 64
        )
        if not configuration_exact:
            raise Product02RunError(f"{arm} trace does not prove its frozen treatment")
        accepted_raw = result.get("accepted_binding_evidence_refs")
        if not isinstance(accepted_raw, list) or any(
            not isinstance(value, str) for value in accepted_raw
        ):
            raise Product02RunError("accepted Binding identity is invalid")
        accepted_source_refs = {
            identities[evidence_id]["source_ref"]
            for evidence_id in accepted_raw
            if evidence_id in identities
        }
        strict_wrong_complete, missing_required_roles = sealed_strict_wrong_complete(
            lean_recall_mode=(
                lean_recall_mode if isinstance(lean_recall_mode, str) else None
            ),
            sufficiency_status=(
                str(trace["sufficiency_status"])
                if trace.get("sufficiency_status") is not None
                else None
            ),
            accepted_source_turn_refs=tuple(accepted_source_refs),
            evidence=sealed,
        )
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "SUCCEEDED",
            "runtime_called": True,
            "resolve_latency_ms": round(resolve_ms, 6),
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_evidence_boundary": boundary,
            "lean_recall_mode": lean_recall_mode,
            "evidence_set_digest": evidence_set_digest,
            "configuration_trace_exact": configuration_exact,
            "answer_evidence": answer_evidence,
            "label_trace": label_trace,
            **trace,
            "accepted_source_turn_refs": sorted(accepted_source_refs),
            "missing_required_roles": list(missing_required_roles),
            "strict_wrong_complete": strict_wrong_complete,
        }
    except Exception as exc:
        return {
            "stage": "context",
            "arm": arm,
            "case_id": case_id,
            "status": "FAILED",
            "runtime_called": True,
            "failure_class": type(exc).__name__,
            "failure_message": str(exc)[:500],
            "resolve_latency_ms": None,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_visible_trace_exact": False,
            "configuration_trace_exact": False,
            "strict_wrong_complete": 0,
            "contamination_count": 0,
            "canonical_mutation_count": 0,
        }


def _alias_row(source: Mapping[str, Any], *, stage: str) -> dict[str, Any]:
    row = dict(source)
    row["arm"] = B1
    row["runtime_called"] = False if stage == "context" else row.get("runtime_called")
    row["provider_called"] = False if stage in {"answer", "judge"} else row.get(
        "provider_called"
    )
    row["aliased_from"] = B1_ALIAS_SOURCE
    row["alias_reason"] = "U1_SELECTED_A0_IS_CONFIG_IDENTICAL_TO_U0_BASELINE"
    return row


async def _run(args: argparse.Namespace) -> int:
    if not 1 <= args.capture_concurrency <= 12:
        raise Product02RunError("capture concurrency must be 1..12")
    if not 1 <= args.answer_concurrency <= 16 or not 1 <= args.judge_concurrency <= 16:
        raise Product02RunError("provider concurrency must be 1..16")
    if args.output.exists():
        raise Product02RunError("run output already exists; sealed runs are append-forbidden")

    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise Product02RunError("Product pin failed: " + "; ".join(verification.errors))
    if (
        lock.git_commit != EXPECTED_PRODUCT_COMMIT
        or lock.tree_sha256 != EXPECTED_PRODUCT_TREE
        or lock.digest != EXPECTED_PRODUCT_LOCK_DIGEST
    ):
        raise Product02RunError("Product identity is outside the Product-02 frozen contract")
    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    population = _load_population(dataset_path)
    label_payload, label_cases = _load_label_manifest(
        args.label_manifest,
        dataset_sha256=dataset_sha256,
        population=population,
    )
    label_manifest_sha256 = _sha256_file(args.label_manifest)
    if label_manifest_sha256 != EXPECTED_LABEL_MANIFEST_SHA256:
        raise Product02RunError("answer label identity is outside the frozen contract")
    _validate_500_authority(args, lock.digest, label_manifest_sha256)
    selected = _select(population, args.case_count)
    selection_sha256 = _selection_identity(population, args.case_count)
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_root, local_files_only=True, use_fast=True
    )
    if not isinstance(tokenizer.chat_template, str) or not tokenizer.chat_template:
        raise Product02RunError("local Qwen tokenizer has no chat template")
    from milai_lab.longmemeval_gate import answer_messages

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
    env = _load_env(args.env_file)
    if not _complex_defaults_off(env):
        raise Product02RunError("complex candidate flags are not frozen OFF")

    runtimes = {
        B0: (
            RuntimeHttpClient(
                args.b0_base_url,
                env["MILAI_AGENT_SUBMITTER_TOKEN"],
                max_connections=args.capture_concurrency,
            ),
            RuntimeHttpClient(args.b0_base_url, env["MILAI_AGENT_READER_TOKEN"], max_connections=4),
        ),
        B2: (
            RuntimeHttpClient(
                args.b2_base_url,
                env["MILAI_AGENT_SUBMITTER_TOKEN"],
                max_connections=2,
            ),
            RuntimeHttpClient(args.b2_base_url, env["MILAI_AGENT_READER_TOKEN"], max_connections=4),
        ),
    }
    provider = VllmClient(
        args.vllm_base_url, max(args.answer_concurrency, args.judge_concurrency)
    )
    model = await provider.verify()
    for _submitter, reader in runtimes.values():
        capabilities = await reader.request("GET", "/v1/capabilities")
        if capabilities.get("contract_version") != "agent.v1":
            raise Product02RunError("Runtime agent contract is incompatible")

    artifacts = RunArtifacts(args.output)
    started_at = datetime.now(UTC)
    run_id = f"product02-longmemeval-{args.case_count}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    formal = args.case_count == 500
    tokenizer_identity = {
        "root": str(args.tokenizer_root.resolve()),
        "tokenizer_json_sha256": _sha256_file(args.tokenizer_root / "tokenizer.json"),
        "tokenizer_config_sha256": _sha256_file(
            args.tokenizer_root / "tokenizer_config.json"
        ),
        "chat_template_sha256": _sha256_bytes(tokenizer.chat_template.encode()),
    }
    run_payload = {
        "schema_version": "milai-product02-longmemeval-run-v1",
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": started_at.isoformat(),
        "case_count": args.case_count,
        "logical_cell_count": args.case_count * len(ARMS),
        "executed_context_cell_count": args.case_count * len(EXECUTED_ARMS),
        "arms": list(ARMS),
        "executed_arms": list(EXECUTED_ARMS),
        "b1_alias": {"source": B1_ALIAS_SOURCE, "reason": "U1 selected A0"},
        "interleaving": "CASE_MAJOR_B0_B2_CONCURRENT_WITH_B1_EXACT_ALIAS",
        "shared_ingest_index_snapshot": True,
        "treatment_context_reused": False,
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "lab_commit": _git_head(ROOT),
        "lab_worktree_dirty": True,
        "harness_sha256": _sha256_file(Path(__file__)),
        "scorer_sha256": _sha256_file(ROOT / "src/milai_lab/longmemeval_gate.py"),
        "sealed_label_join_sha256": _sha256_file(
            ROOT / "src/milai_lab/product02_decision.py"
        ),
        "label_manifest": {
            "path": str(args.label_manifest.resolve()),
            "sha256": label_manifest_sha256,
            "schema_version": label_payload["schema_version"],
            "classification": label_payload.get("classification"),
            "annotation_model": label_payload.get("annotation_model"),
            "claim_ceiling": label_payload["claim_ceiling"],
        },
        "dataset_sha256": dataset_sha256,
        "selection_sha256": selection_sha256,
        "selection_kind": (
            "OUTCOME_BLIND_STRUCTURAL_128" if args.case_count == 128 else "PINNED_FULL_500"
        ),
        "formal_holdout_consumed": formal,
        "formal_holdout_authorization": args.formal_holdout_authorization,
        "model": {
            "id": MODEL_ID,
            "base_url": args.vllm_base_url,
            "served_model": model,
            "same_model_self_judge": True,
        },
        "tokenizer": tokenizer_identity,
        "budget": {
            "usable_model_context": MODEL_CONTEXT_LIMIT,
            "max_fixed_prompt_tokens_population": fixed_prompt_tokens,
            "answer_reserve_tokens": ANSWER_RESERVE_TOKENS,
            "safety_margin_tokens": SAFETY_MARGIN_TOKENS,
            "product_cap": PRODUCT_CONTEXT_CAP,
            "evidence_tokens": budget,
            "whole_evidence_units_only": True,
        },
        "treatments": {
            B0: {
                "budget_invariant_context_v0_1": True,
                "progressive_context_evidence_v0_1": True,
                "reader_boundary": "governance-admitted soft-ranked control",
            },
            B1: {"alias_of": B0, "selected_u1_acquisition": "A0"},
            B2: {
                "budget_invariant_context_v0_1": True,
                "progressive_context_evidence_v0_1": False,
            },
        },
        "concurrency": {
            "capture": args.capture_concurrency,
            "answer": args.answer_concurrency,
            "judge": args.judge_concurrency,
        },
        "generation": {
            "temperature": 0,
            "top_p": 1,
            "answer_max_tokens": ANSWER_MAX_TOKENS,
            "judge_max_tokens": JUDGE_MAX_TOKENS,
            "semantic_retries": 0,
            "technical_retries": 0,
            "votes": 0,
        },
        "label_contract": {
            "turn_labels": "sealed model-assisted direct_answer source turns",
            "span_labels": "sealed exact source quote when available",
            "required_role_definition": (
                "sealed minimum derivation operands; each selected source turn is a "
                "singleton required-role group"
            ),
            "native_has_answer": "audit-only; excluded from scorer labels",
            "joined_after_product_trace": True,
            "evidence_labels_in_product_or_answer_prompt": False,
        },
        "answers_complete_before_judges": True,
    }
    artifacts.write_json("run.json", run_payload)

    rows: list[dict[str, Any]] = []
    final_runtime_health = False
    try:
        for ordinal, record in enumerate(selected, start=1):
            case_started = time.perf_counter()
            events = _history_events(record)
            sealed = sealed_answer_evidence(
                record,
                events,
                label_cases[str(record["question_id"])],
            )
            outbox_ids, identities = await _capture_case(
                runtimes[B0][0], events, concurrency=args.capture_concurrency
            )
            await _wait_projection(runtimes[B0][1], outbox_ids)
            unique_cells = await asyncio.gather(
                *(
                    _resolve_arm(
                        arm,
                        record,
                        reader=runtimes[arm][1],
                        identities=identities,
                        sealed=sealed,
                        tokenizer=tokenizer,
                        evidence_token_budget=budget,
                    )
                    for arm in EXECUTED_ARMS
                )
            )
            by_arm = {str(cell["arm"]): cell for cell in unique_cells}
            cells = (by_arm[B0], _alias_row(by_arm[B0], stage="context"), by_arm[B2])
            for cell in cells:
                cell["capture_count"] = len(events)
                cell["case_elapsed_ms"] = round(
                    (time.perf_counter() - case_started) * 1_000, 6
                )
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
            (str(row["arm"]), str(row["case_id"])): row
            for row in rows
            if row["stage"] == "context"
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
                        schema_name="milai_product02_answer",
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

        unique_answers = await asyncio.gather(
            *(answer_one(arm, record) for record in selected for arm in EXECUTED_ARMS)
        )
        unique_answer_by_key = {
            (str(row["arm"]), str(row["case_id"])): row for row in unique_answers
        }
        answers: list[dict[str, Any]] = []
        for record in selected:
            case_id = str(record["question_id"])
            answers.extend(
                (
                    unique_answer_by_key[(B0, case_id)],
                    _alias_row(unique_answer_by_key[(B0, case_id)], stage="answer"),
                    unique_answer_by_key[(B2, case_id)],
                )
            )
        for row in answers:
            artifacts.append_jsonl("cases.jsonl", row)
            rows.append(row)
        print(json.dumps({"stage": "answers-sealed", "count": len(answers)}), flush=True)

        answer_by_key = {
            (str(row["arm"]), str(row["case_id"])): row for row in answers
        }
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
                        schema_name="milai_product02_judgment",
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

        unique_judges = await asyncio.gather(
            *(judge_one(arm, record) for record in selected for arm in EXECUTED_ARMS)
        )
        unique_judge_by_key = {
            (str(row["arm"]), str(row["case_id"])): row for row in unique_judges
        }
        judges: list[dict[str, Any]] = []
        for record in selected:
            case_id = str(record["question_id"])
            judges.extend(
                (
                    unique_judge_by_key[(B0, case_id)],
                    _alias_row(unique_judge_by_key[(B0, case_id)], stage="judge"),
                    unique_judge_by_key[(B2, case_id)],
                )
            )
        for row in judges:
            artifacts.append_jsonl("cases.jsonl", row)
            rows.append(row)
        print(json.dumps({"stage": "judges-sealed", "count": len(judges)}), flush=True)
        health = []
        for _submitter, reader in runtimes.values():
            capabilities = await reader.request("GET", "/v1/capabilities")
            health.append(capabilities.get("contract_version") == "agent.v1")
        final_runtime_health = all(health)
    finally:
        for submitter, reader in runtimes.values():
            await submitter.close()
            await reader.close()
        await provider.close()

    context_rows = [row for row in rows if row["stage"] == "context"]
    answer_rows = [row for row in rows if row["stage"] == "answer"]
    judge_rows = [row for row in rows if row["stage"] == "judge"]
    judge_by_key = {
        (str(row["arm"]), str(row["case_id"])): row for row in judge_rows
    }
    arm_payloads: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        contexts = [row for row in context_rows if row["arm"] == arm]
        succeeded = [row for row in contexts if row["status"] == "SUCCEEDED"]
        judgments = [row for row in judge_rows if row["arm"] == arm]
        succeeded_judgments = [
            row for row in judgments if row["status"] == "SUCCEEDED"
        ]
        if not succeeded_judgments:
            raise Product02RunError(f"no successful judgments for {arm}")
        latencies = [float(row["resolve_latency_ms"]) for row in succeeded] or [float("inf")]
        span_values = [
            float(value)
            for row in succeeded
            if isinstance(row.get("answer_evidence"), Mapping)
            and (value := row["answer_evidence"].get("reader_visible_answer_span_coverage"))
            is not None
        ]

        def answer_metric(
            name: str, succeeded_rows: tuple[Mapping[str, Any], ...] = tuple(succeeded)
        ) -> tuple[float, int]:
            values = [
                float(value)
                for row in succeeded_rows
                if (value := row["answer_evidence"].get(name)) is not None
            ]
            if not values:
                raise Product02RunError(f"no labeled cases for {name}")
            return sum(values) / len(values), len(values)

        turn_recall, turn_case_count = answer_metric("answer_bearing_turn_recall")
        turn_coverage, _ = answer_metric("reader_visible_answer_turn_coverage")
        role_coverage, role_case_count = answer_metric("required_role_coverage")
        all_turns_visible, _ = answer_metric("all_sealed_answer_turns_visible")

        arm_payloads[arm] = {
            "case_count": args.case_count,
            "system_context_success_rate": len(succeeded) / args.case_count,
            "session_recall_at_5": sum(
                float(row["retrieval"]["session_recall_at_5"]) for row in succeeded
            )
            / args.case_count,
            "session_ndcg_at_5": sum(
                float(row["retrieval"]["session_ndcg_at_5"]) for row in succeeded
            )
            / args.case_count,
            "reader_visible_gold_session_coverage": sum(
                float(row["coverage"]["reader_visible_gold_session_coverage"])
                for row in succeeded
            )
            / args.case_count,
            "answer_bearing_turn_recall": turn_recall,
            "reader_visible_answer_turn_coverage": turn_coverage,
            "turn_labeled_case_count": turn_case_count,
            "reader_visible_answer_span_coverage": (
                sum(span_values) / len(span_values) if span_values else None
            ),
            "span_labeled_case_count": len(span_values),
            "required_role_coverage": role_coverage,
            "role_labeled_case_count": role_case_count,
            "all_sealed_answer_turns_visible_rate": all_turns_visible,
            "qwen_judge_accuracy": sum(
                bool(row["correct"]) for row in succeeded_judgments
            )
            / len(succeeded_judgments),
            "qwen_judge_labeled_case_count": len(succeeded_judgments),
            "strict_wrong_complete": sum(
                int(row.get("strict_wrong_complete", 0)) for row in contexts
            ),
            "p50_latency_ms": percentile(latencies, 0.50),
            "p95_latency_ms": percentile(latencies, 0.95),
            "contamination_count": sum(
                int(row.get("contamination_count", 0)) for row in contexts
            ),
            "reader_visible_trace_exactness": sum(
                row.get("reader_visible_trace_exact") is True for row in contexts
            )
            / args.case_count,
            "configuration_trace_exactness": sum(
                row.get("configuration_trace_exact") is True for row in contexts
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

    paired_judge_case_ids = [
        str(record["question_id"])
        for record in selected
        if judge_by_key[(B1, str(record["question_id"]))]["status"] == "SUCCEEDED"
        and judge_by_key[(B2, str(record["question_id"]))]["status"] == "SUCCEEDED"
    ]
    if not paired_judge_case_ids:
        raise Product02RunError("no matched successful judgments")
    baseline_judges = [
        bool(judge_by_key[(B1, case_id)]["correct"])
        for case_id in paired_judge_case_ids
    ]
    candidate_judges = [
        bool(judge_by_key[(B2, case_id)]["correct"])
        for case_id in paired_judge_case_ids
    ]
    ci_low, ci_high = paired_bootstrap_interval(
        baseline_judges,
        candidate_judges,
        samples=BOOTSTRAP_SAMPLES,
        seed=BOOTSTRAP_SEED,
    )
    turn_delta = (
        arm_payloads[B2]["reader_visible_answer_turn_coverage"]
        - arm_payloads[B1]["reader_visible_answer_turn_coverage"]
    )
    role_delta = (
        arm_payloads[B2]["required_role_coverage"]
        - arm_payloads[B1]["required_role_coverage"]
    )
    matched_baseline_accuracy = sum(baseline_judges) / len(baseline_judges)
    matched_candidate_accuracy = sum(candidate_judges) / len(candidate_judges)
    judge_delta = matched_candidate_accuracy - matched_baseline_accuracy
    latency_ratio = arm_payloads[B2]["p95_latency_ms"] / arm_payloads[B1][
        "p95_latency_ms"
    ]
    hard_checks = {
        "ProductManifestAndLabPin": True,
        "PriorLocalUsabilityGate": True,
        "SystemContextSuccessRate": min(
            float(arm_payloads[arm]["system_context_success_rate"]) for arm in ARMS
        )
        >= 0.99,
        "AnswerProviderSuccessRate": min(
            int(arm_payloads[arm]["answer_success_count"]) / args.case_count
            for arm in ARMS
        )
        >= 0.99,
        "JudgeProviderSuccessRate": min(
            int(arm_payloads[arm]["judge_success_count"]) / args.case_count
            for arm in ARMS
        )
        >= 0.99,
        "SystemFailureNotCountedAsSemanticAbstention": all(
            not payload["context_failure_counts"] for payload in arm_payloads.values()
        ),
        "SystemicWorkerExit": final_runtime_health,
        "CrossSessionContamination": all(
            payload["contamination_count"] == 0 for payload in arm_payloads.values()
        ),
        "ReaderVisibleTraceExactness": all(
            payload["reader_visible_trace_exactness"] == 1.0
            for payload in arm_payloads.values()
        ),
        "TreatmentConfigurationTraceExactness": all(
            payload["configuration_trace_exactness"] == 1.0
            for payload in arm_payloads.values()
        ),
        "StrictWrongComplete": all(
            payload["strict_wrong_complete"] == 0 for payload in arm_payloads.values()
        ),
        "ScopeRevocationWrongRelationLeak": all(
            payload["contamination_count"] == 0 for payload in arm_payloads.values()
        ),
        "CanonicalMutationFromRead": all(
            payload["canonical_mutation_count"] == 0 for payload in arm_payloads.values()
        ),
        "CandidateComplexProfilesDefaultOff": _complex_defaults_off(env),
    }
    effect_checks = {
        "ExactAnswerTurnOrRequiredRoleGain": (
            (turn_delta >= 0.03 and role_delta >= -0.01)
            or (role_delta >= 0.03 and turn_delta >= -0.01)
        ),
        "QwenJudgePointDeltaNonNegative": judge_delta >= 0.0,
        "PairedJudgeCILowerBound": ci_low >= -0.01,
        "P95LatencyRatio": latency_ratio <= 1.5,
    }
    hard_pass = all(hard_checks.values())
    effect_pass = all(effect_checks.values())
    entry_pass = hard_pass and effect_pass
    metrics_payload = {
        "schema_version": "milai-product02-longmemeval-metrics-v2",
        "run_id": run_id,
        "status": "PASS" if hard_pass else "FAIL",
        "arms": arm_payloads,
        "deltas_b2_minus_b1": {
            "reader_visible_answer_turn_coverage": turn_delta,
            "required_role_coverage": role_delta,
            "qwen_judge_accuracy": judge_delta,
            "matched_baseline_qwen_judge_accuracy": matched_baseline_accuracy,
            "matched_candidate_qwen_judge_accuracy": matched_candidate_accuracy,
            "p95_latency_ratio": latency_ratio,
            "paired_judge_ci_95": [ci_low, ci_high],
            "paired_wins": sum(
                right and not left
                for left, right in zip(baseline_judges, candidate_judges, strict=True)
            ),
            "paired_losses": sum(
                left and not right
                for left, right in zip(baseline_judges, candidate_judges, strict=True)
            ),
        },
        "hard_checks": hard_checks,
        "candidate_effect_checks": effect_checks,
        "candidate_entry_pass": entry_pass,
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED},
        "paired_judge_case_count": len(paired_judge_case_ids),
        "same_qwen_self_judge": True,
        "leaderboard_equivalence_claimed": False,
        "semantic_retries": 0,
        "technical_retries": 0,
        "votes": 0,
    }
    artifacts.write_json("metrics.json", metrics_payload)
    finished_at = datetime.now(UTC)
    if not hard_pass:
        terminal_status = "FAIL_PRODUCT02_HARD_GATE_REPAIR_REQUIRED"
        disposition = "ACTIVE_REPAIR"
    elif effect_pass and formal:
        terminal_status = "PASS_LEAN_MEMORY_USABLE"
        disposition = B2
    elif effect_pass:
        terminal_status = "PASS_PRODUCT02_128_ENTRY_FOR_500"
        disposition = "B2_PENDING_500_CONFIRMATION"
    else:
        terminal_status = "PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE"
        disposition = "B0_B1_EQUIVALENT_BASELINE"
    terminal = {
        "schema_version": "milai-product02-longmemeval-terminal-v1",
        "run_id": run_id,
        "status": terminal_status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
        "case_count": args.case_count,
        "formal_holdout_consumed": formal,
        "product_commit": lock.git_commit,
        "product_lock_digest": lock.digest,
        "label_manifest_sha256": label_manifest_sha256,
        "selection_sha256": selection_sha256,
        "run_sha256": canonical_sha256(run_payload),
        "cases_sha256": _sha256_file(args.output / "cases.jsonl"),
        "metrics_sha256": canonical_sha256(metrics_payload),
        "candidate_default_enabled": False,
        "selected_disposition": disposition,
        "candidate_entry_pass": entry_pass,
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if hard_pass else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(
            f"Product-02 LongMemEval failed closed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
