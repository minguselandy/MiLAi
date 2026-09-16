#!/usr/bin/env python3
"""Run an opened-development LongMemEval slice through real Codex HTTP MCP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import run_product09_codex_lifecycle as p09
from milai_lab.context_preflight import material_turn_ordinals, source_session_instance_keys
from milai_lab.scorers.answers import answer_values, score_normalized_em_f1_v1

LAB = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = LAB / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_SELECTION = LAB / "data/labels/product05-openworker-lme-selection.v0.1.json"
DEFAULT_ANSWER_TURNS = LAB / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json"
DEFAULT_CASES = ("8550ddae", "71a3fd6b", "0a995998", "852ce960")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _load_cases(
    manifest_path: Path,
    selection_path: Path,
    answer_turns_path: Path,
    case_ids: tuple[str, ...],
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if (
        selection.get("opened_development_only") is not True
        or selection.get("formal_holdout_consumed") is not False
    ):
        raise p09.Product09Error("LongMemEval selection is not opened development data")
    metadata = {
        str(row["case_id"]): dict(row)
        for row in selection.get("cases", [])
        if isinstance(row, dict) and isinstance(row.get("case_id"), str)
    }
    if any(case_id not in metadata for case_id in case_ids):
        raise p09.Product09Error("requested case is outside the opened-development selection")
    answer_turns = json.loads(answer_turns_path.read_text(encoding="utf-8"))
    turn_labels = {
        str(row["case_id"]): dict(row)
        for row in answer_turns.get("cases", [])
        if isinstance(row, dict) and isinstance(row.get("case_id"), str)
    }
    if any(case_id not in turn_labels for case_id in case_ids):
        raise p09.Product09Error("requested case has no sealed answer-turn annotation")
    root = manifest.get("external_root")
    filename = manifest.get("split_files", {}).get("population_500")
    expected = manifest.get("file_sha256", {}).get(filename)
    if not isinstance(root, str) or not isinstance(filename, str):
        raise p09.Product09Error("LongMemEval manifest is malformed")
    dataset = Path(root) / filename
    if not dataset.is_file() or _sha256(dataset) != expected:
        raise p09.Product09Error("LongMemEval dataset identity mismatch")
    population = json.loads(dataset.read_text(encoding="utf-8"))
    by_id = {
        str(record["question_id"]): dict(record)
        for record in population
        if isinstance(record, dict) and isinstance(record.get("question_id"), str)
    }
    return [
        (by_id[case_id], metadata[case_id], turn_labels[case_id])
        for case_id in case_ids
    ]


def _observed_at(value: object, ordinal: int) -> str:
    if not isinstance(value, str):
        raise p09.Product09Error("LongMemEval observation date is invalid")
    normalized = re.sub(r"\s+\([^)]+\)", "", value).strip()
    parsed = datetime.strptime(normalized, "%Y/%m/%d %H:%M").replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=ordinal)).isoformat()


def _history_events(
    record: Mapping[str, Any], project: str, answer_turns: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, int | str]]]:
    case_id = str(record["question_id"])
    sessions = record.get("haystack_sessions")
    session_ids = record.get("haystack_session_ids")
    dates = record.get("haystack_dates")
    answer_session_ids = record.get("answer_session_ids")
    if (
        not isinstance(sessions, list)
        or not isinstance(session_ids, list)
        or not isinstance(dates, list)
        or not isinstance(answer_session_ids, list)
        or not (len(sessions) == len(session_ids) == len(dates))
    ):
        raise p09.Product09Error("LongMemEval case shape is invalid")
    instances = source_session_instance_keys(session_ids)
    answer_sources = {str(value) for value in answer_session_ids}
    answer_runtime_sessions: set[str] = set()
    answer_turn_refs: dict[str, dict[str, int | str]] = {}
    annotated_turns = {
        (int(row["session_ordinal"]), int(row["turn_ordinal"])): row
        for row in answer_turns.get("selections", [])
        if isinstance(row, Mapping)
        and isinstance(row.get("session_ordinal"), int)
        and isinstance(row.get("turn_ordinal"), int)
    }
    events: list[dict[str, Any]] = []
    for session_ordinal, (source_session_id, instance, session, date) in enumerate(
        zip(session_ids, instances, sessions, dates, strict=True)
    ):
        source_session = str(source_session_id)
        runtime_session = f"lme:{_stable(case_id, 12)}:{_stable(instance, 20)}"
        if source_session in answer_sources:
            answer_runtime_sessions.add(runtime_session)
        ordinals = material_turn_ordinals(session)
        if not isinstance(session, list):
            raise AssertionError("validated LongMemEval session changed type")
        turn_ids = {ordinal: f"{runtime_session}:turn:{ordinal}" for ordinal in ordinals}
        for index, ordinal in enumerate(ordinals):
            turn = session[ordinal]
            if not isinstance(turn, Mapping):
                raise AssertionError("validated LongMemEval turn changed type")
            role = str(turn["role"])
            event_type = {
                "user": "USER_MESSAGE",
                "assistant": "ASSISTANT_MESSAGE",
                "tool": "TOOL_RESULT",
                "system": "SESSION_MARKER",
            }[role]
            event_identity = f"{case_id}\0{instance}\0{ordinal}"
            source_id = (
                f"lme://{_stable(case_id, 12)}/{_stable(instance, 20)}/turn/{ordinal}"
            )
            annotation = annotated_turns.get((session_ordinal, ordinal))
            if annotation is not None:
                answer_turn_refs[source_id] = {
                    "source_session_id": source_session,
                    "session_ordinal": session_ordinal,
                    "turn_ordinal": ordinal,
                    "speaker": str(annotation.get("speaker", role)),
                }
            events.append(
                {
                    "schema_version": "host-agent-event-v1",
                    "event_id": "lme-" + _stable(event_identity, 40),
                    "event_type": event_type,
                    "session_id": runtime_session,
                    "source_id": source_id,
                    "subject_id": f"longmemeval:{case_id}",
                    "observed_at": _observed_at(date, ordinal),
                    "content": str(turn["content"]),
                    "turn_id": turn_ids[ordinal],
                    "turn_ordinal": ordinal,
                    "round_id": f"{runtime_session}:round:{ordinal // 2}",
                    "round_ordinal": ordinal // 2,
                    **(
                        {"previous_turn_id": turn_ids[ordinals[index - 1]]}
                        if index
                        else {}
                    ),
                    **(
                        {"next_turn_id": turn_ids[ordinals[index + 1]]}
                        if index + 1 < len(ordinals)
                        else {}
                    ),
                    "_project": project,
                }
            )
    if not answer_runtime_sessions:
        raise p09.Product09Error("answer sessions could not be mapped to Runtime identity")
    if annotated_turns and len(answer_turn_refs) != len(annotated_turns):
        raise p09.Product09Error("answer-turn annotation could not be mapped to Runtime identity")
    return events, answer_runtime_sessions, answer_turn_refs


def _capture_case(
    environment: dict[str, str],
    events: list[dict[str, Any]],
    *,
    workers: int,
) -> list[str]:
    def capture(raw: dict[str, Any]) -> dict[str, Any]:
        event = dict(raw)
        project = str(event.pop("_project"))
        return p09._capture(
            environment,
            project=project,
            event=event,
            data_classification="DEIDENTIFIED",
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        receipts = list(executor.map(capture, events))
    outbox_ids: list[str] = []
    for result in receipts:
        receipt = result.get("receipt")
        if not isinstance(receipt, dict) or not isinstance(receipt.get("outbox_id"), str):
            raise p09.Product09Error("LongMemEval capture receipt is malformed")
        outbox_ids.append(receipt["outbox_id"])
    return outbox_ids


def _wait_projection_batched(
    environment: dict[str, str], outbox_ids: list[str], *, batch_size: int = 512
) -> None:
    for start in range(0, len(outbox_ids), batch_size):
        p09._wait_projection(environment, outbox_ids[start : start + batch_size])


def _visible_sessions(run: Mapping[str, Any]) -> set[str]:
    sessions: set[str] = set()
    for call in run.get("calls", []):
        if not isinstance(call, Mapping):
            continue
        context = call.get("structured_content")
        if not isinstance(context, Mapping):
            continue
        for evidence in context.get("evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            source = evidence.get("source")
            if isinstance(source, Mapping) and isinstance(source.get("id"), str):
                sessions.add(str(source["id"]))
    return sessions


def _visible_turn_refs(run: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    for call in run.get("calls", []):
        if not isinstance(call, Mapping):
            continue
        context = call.get("structured_content")
        if not isinstance(context, Mapping):
            continue
        for evidence in context.get("evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            source = evidence.get("source")
            if not isinstance(source, Mapping):
                continue
            turn_refs = source.get("turn_refs")
            if isinstance(turn_refs, list):
                refs.update(value for value in turn_refs if isinstance(value, str))
    return refs


def _call_identities(call: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    evidence_ids: set[str] = set()
    turn_refs: set[str] = set()
    context = call.get("structured_content")
    if not isinstance(context, Mapping):
        return evidence_ids, turn_refs
    for evidence in context.get("evidence", []):
        if not isinstance(evidence, Mapping):
            continue
        evidence_id = evidence.get("id")
        if isinstance(evidence_id, str):
            evidence_ids.add(evidence_id)
        source = evidence.get("source")
        if not isinstance(source, Mapping):
            continue
        raw_turn_refs = source.get("turn_refs")
        if isinstance(raw_turn_refs, list):
            turn_refs.update(value for value in raw_turn_refs if isinstance(value, str))
    return evidence_ids, turn_refs


def _behavior_trace(
    run: Mapping[str, Any], *, expected_query: str | None = None
) -> dict[str, Any]:
    calls = [call for call in run.get("calls", []) if isinstance(call, Mapping)]
    seen_evidence_ids: set[str] = set()
    seen_turn_refs: set[str] = set()
    first_query: str | None = None
    previous_returned_context_id: str | None = None
    rows: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, Mapping) else {}
        query = arguments.get("query")
        query = query if isinstance(query, str) else None
        if index == 0:
            first_query = query
        requested_previous = arguments.get("previous_context_id")
        requested_previous = requested_previous if isinstance(requested_previous, str) else None
        context = call.get("structured_content")
        context = context if isinstance(context, Mapping) else {}
        returned_context_id = context.get("context_id")
        returned_context_id = returned_context_id if isinstance(returned_context_id, str) else None
        continuation = context.get("continuation")
        continuation = continuation if isinstance(continuation, Mapping) else {}
        evidence_ids, turn_refs = _call_identities(call)
        novel_evidence_ids = evidence_ids - seen_evidence_ids
        novel_turn_refs = turn_refs - seen_turn_refs
        rows.append(
            {
                "call_index": index + 1,
                "query_sha256": (
                    hashlib.sha256(query.encode()).hexdigest() if query is not None else None
                ),
                "query_matches_expected": (
                    query == expected_query
                    if query is not None and expected_query is not None
                    else None
                ),
                "same_query_as_first": query == first_query,
                "previous_context_id_present": requested_previous is not None,
                "previous_context_matches_prior_call": (
                    requested_previous == previous_returned_context_id
                    if requested_previous is not None and index > 0
                    else None
                ),
                "retrieval_status": context.get("retrieval_status"),
                "candidate_origin": continuation.get("candidate_origin"),
                "continuation_available": continuation.get("available"),
                "continuation_reason": continuation.get("reason"),
                "evidence_count": len(evidence_ids),
                "novel_evidence_count": len(novel_evidence_ids),
                "turn_ref_count": len(turn_refs),
                "novel_turn_ref_count": len(novel_turn_refs),
            }
        )
        seen_evidence_ids.update(evidence_ids)
        seen_turn_refs.update(turn_refs)
        previous_returned_context_id = returned_context_id
    after_first = rows[1:]
    return {
        "calls": rows,
        "multi_call": len(rows) > 1,
        "stateful_continuation_used": any(
            row["previous_context_id_present"] is True for row in after_first
        ),
        "valid_lineage_call_count": sum(
            row["previous_context_matches_prior_call"] is True for row in after_first
        ),
        "persisted_frontier_call_count": sum(
            row["candidate_origin"] == "PERSISTED_FRONTIER" for row in after_first
        ),
        "fresh_reacquisition_after_first_count": sum(
            row["previous_context_id_present"] is False for row in after_first
        ),
        "novel_turn_refs_after_first": sum(
            int(row["novel_turn_ref_count"]) for row in after_first
        ),
    }


def _score_case(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    run: dict[str, Any],
    required_sessions: set[str],
    required_turn_refs: Mapping[str, Mapping[str, int | str]],
) -> dict[str, Any]:
    answers = answer_values(record["answer"])
    score = score_normalized_em_f1_v1(str(run["answer"]), answers)
    visible = _visible_sessions(run)
    visible_turn_refs = _visible_turn_refs(run)
    arguments_narrow = all(
        isinstance(call.get("arguments"), Mapping)
        and set(call["arguments"]) <= {"query", "previous_context_id"}
        for call in run["calls"]
        if isinstance(call, Mapping)
    )
    answer_turn_visibility = [
        {**descriptor, "visible": turn_ref in visible_turn_refs}
        for turn_ref, descriptor in required_turn_refs.items()
    ]
    cumulative_required_turn_refs: set[str] = set()
    required_turn_coverage_by_call: list[dict[str, Any]] = []
    required_ref_set = set(required_turn_refs)
    for call_index, call in enumerate(run["calls"], start=1):
        if not isinstance(call, Mapping):
            continue
        _evidence_ids, call_turn_refs = _call_identities(call)
        current_required = call_turn_refs & required_ref_set
        before = set(cumulative_required_turn_refs)
        cumulative_required_turn_refs.update(current_required)
        required_turn_coverage_by_call.append(
            {
                "call_index": call_index,
                "required_turn_count_in_call": len(current_required),
                "new_required_turn_count": len(current_required - before),
                "cumulative_required_turn_count": len(cumulative_required_turn_refs),
                "all_required_turns_cumulative": (
                    required_ref_set <= cumulative_required_turn_refs
                ),
            }
        )
    first_call_required_count = (
        int(required_turn_coverage_by_call[0]["cumulative_required_turn_count"])
        if required_turn_coverage_by_call
        else 0
    )
    expected_query = record.get("question")
    behavior = _behavior_trace(
        run,
        expected_query=expected_query if isinstance(expected_query, str) else None,
    )
    return {
        "case_id": str(record["question_id"]),
        "question_type": record["question_type"],
        "capability_family": metadata["capability_family"],
        "answer": run["answer"],
        "reference": record["answer"],
        "tool_calls": len(run["calls"]),
        "tool_arguments_narrow": arguments_narrow,
        "behavior": behavior,
        "any_required_session_visible": bool(visible & required_sessions),
        "all_required_sessions_visible": required_sessions <= visible,
        "required_session_count": len(required_sessions),
        "visible_required_session_count": len(visible & required_sessions),
        "answer_turn_count": len(required_turn_refs),
        "visible_answer_turn_count": len(visible_turn_refs & required_turn_refs.keys()),
        "all_answer_turns_visible": required_turn_refs.keys() <= visible_turn_refs,
        "answer_turn_visibility": answer_turn_visibility,
        "required_turn_coverage_by_call": required_turn_coverage_by_call,
        "first_call_required_turn_count": first_call_required_count,
        "all_answer_turns_visible_on_first_call": (
            len(required_ref_set) == first_call_required_count
        ),
        "required_turns_recovered_after_first_count": (
            len(cumulative_required_turn_refs) - first_call_required_count
        ),
        "exact_match": int(score["exact_match"]),
        "normalized_f1": float(score["normalized_f1"]),
        "latency_ms": run["latency_ms"],
        "returncode": run["returncode"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    selected = _load_cases(
        args.dataset_manifest,
        args.selection_manifest,
        args.answer_turn_labels,
        tuple(args.case_ids),
    )
    postgres_port = p09._free_port()
    api_port = p09._free_port()
    compose_project = f"{args.run_id}-pg"
    postgres_started = False
    phase = "bootstrap"
    summary: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="milai-p09-lme-") as temporary:
        root = Path(temporary)
        env_file = root / "runtime.env"
        processes = p09.ProcessGroup(root)
        p09._command(
            [
                str(p09.OPS_EXE),
                "init",
                "--env-file",
                str(env_file),
                "--blob-root",
                str(root / "blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(api_port),
            ],
            cwd=p09.RUNTIME,
        )
        environment = p09._load_environment(env_file)
        environment["MILAI_DATA_MODE"] = "DEIDENTIFIED_ALLOWED"
        if args.enable_persisted_frontier_continuation:
            environment["MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED"] = "true"
        compose = [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(env_file),
            "--file",
            str(p09.RUNTIME / "compose.yaml"),
        ]
        try:
            phase = "postgres"
            p09._command([*compose, "up", "--detach", "postgres"], cwd=p09.RUNTIME, timeout=120)
            postgres_started = True
            deadline = time.monotonic() + 90
            while True:
                migration = p09._command(
                    [str(p09.ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                    cwd=p09.RUNTIME,
                    env=p09._clean_environment(
                        {
                            "MILAI_MIGRATION_DATABASE_URL": environment[
                                "MILAI_MIGRATION_DATABASE_URL"
                            ]
                        }
                    ),
                    timeout=120,
                    check=False,
                )
                if migration.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise p09.Product09Error(
                        "LongMemEval PostgreSQL migration did not become ready"
                    )
                time.sleep(1)
            p09._start_runtime(processes, environment)

            phase = "capture"
            case_runtime: list[dict[str, Any]] = []
            total_events = 0
            for record, metadata, answer_turns in selected:
                case_id = str(record["question_id"])
                project = f"p09-lme-{_stable(case_id, 12)}"
                events, required_sessions, required_turn_refs = _history_events(
                    record, project, answer_turns
                )
                capture_started = time.perf_counter()
                outbox_ids = _capture_case(
                    environment,
                    events,
                    workers=args.capture_workers,
                )
                capture_ms = (time.perf_counter() - capture_started) * 1_000
                projection_started = time.perf_counter()
                _wait_projection_batched(environment, outbox_ids)
                projection_wait_ms = (time.perf_counter() - projection_started) * 1_000
                total_events += len(events)
                case_runtime.append(
                    {
                        "record": record,
                        "metadata": metadata,
                        "project": project,
                        "required_sessions": required_sessions,
                        "required_turn_refs": required_turn_refs,
                        "capture_ms": round(capture_ms, 3),
                        "projection_wait_ms": round(projection_wait_ms, 3),
                    }
                )

            phase = "codex"
            endpoints: list[tuple[str, str]] = []
            for item in case_runtime:
                port = p09._free_port()
                token = secrets.token_urlsafe(40)
                p09._start_mcp(
                    processes,
                    environment,
                    port=port,
                    inbound_token=token,
                    project=str(item["project"]),
                    name=f"mcp-{_stable(str(item['project']), 8)}",
                )
                endpoints.append((f"http://127.0.0.1:{port}/mcp", token))

            def ask(index: int) -> dict[str, Any]:
                record = case_runtime[index]["record"]
                continuation_policy = ""
                if args.behavior_policy == "guided-continuation":
                    continuation_policy = (
                        " If a result says continuation.available=true and the evidence may be "
                        "incomplete, make one continuation call using exactly the same query and "
                        "that result's context_id as previous_context_id; do not paraphrase the "
                        "query for that continuation."
                    )
                prompt = (
                    "This is an opened-development LongMemEval memory task. Use only the MiLAi "
                    "memory tool as historical evidence; do not use files, shell, web, or prior "
                    "knowledge. You may make at most two focused memory calls."
                    f"{continuation_policy} Answer the question "
                    "concisely with no explanation.\n"
                    f"Question date: {record['question_date']}\n"
                    f"Question: {record['question']}"
                )
                endpoint, token = endpoints[index]
                return p09._run_codex(
                    args.codex,
                    mcp_url=endpoint,
                    inbound_token=token,
                    prompt=prompt,
                    timeout_seconds=args.codex_timeout_seconds,
                )

            with ThreadPoolExecutor(max_workers=len(case_runtime)) as executor:
                runs = list(executor.map(ask, range(len(case_runtime))))
            results = [
                {
                    **_score_case(
                        item["record"],
                        item["metadata"],
                        run_result,
                        item["required_sessions"],
                        item["required_turn_refs"],
                    ),
                    "capture_ms": item["capture_ms"],
                    "projection_wait_ms": item["projection_wait_ms"],
                }
                for item, run_result in zip(case_runtime, runs, strict=True)
            ]
            counts = p09._database_counts(compose)
            phase = "complete"
            exact = sum(int(row["exact_match"]) for row in results)
            all_evidence = sum(bool(row["all_required_sessions_visible"]) for row in results)
            all_answer_turns = sum(bool(row["all_answer_turns_visible"]) for row in results)
            summary = {
                "schema_version": "milai-product09-codex-http-lme-slice-v3",
                "status": "PASS_PRODUCT09_LME_DIAGNOSTIC_EXECUTED",
                "run_id": args.run_id,
                "phase": phase,
                "selection": "OPENED_DEVELOPMENT_ONLY",
                "formal_holdout_consumed": False,
                "persisted_frontier_continuation_enabled": (
                    args.enable_persisted_frontier_continuation
                ),
                "behavior_policy": args.behavior_policy,
                "case_count": len(results),
                "history_event_count": total_events,
                "capture_workers": args.capture_workers,
                "codex_parallelism": len(results),
                "exact_accuracy": exact / len(results),
                "mean_normalized_f1": sum(float(row["normalized_f1"]) for row in results)
                / len(results),
                "any_required_session_recall": sum(
                    bool(row["any_required_session_visible"]) for row in results
                )
                / len(results),
                "all_required_session_recall": all_evidence / len(results),
                "all_answer_turn_recall": all_answer_turns / len(results),
                "first_call_all_answer_turn_recall": sum(
                    bool(row["all_answer_turns_visible_on_first_call"])
                    for row in results
                )
                / len(results),
                "case_with_required_turn_gain_count": sum(
                    int(row["required_turns_recovered_after_first_count"]) > 0
                    for row in results
                ),
                "required_turns_recovered_after_first_count": sum(
                    int(row["required_turns_recovered_after_first_count"])
                    for row in results
                ),
                "capture_ms": round(
                    sum(float(row["capture_ms"]) for row in results), 3
                ),
                "projection_wait_ms": round(
                    sum(float(row["projection_wait_ms"]) for row in results), 3
                ),
                "behavior": {
                    "multi_call_case_count": sum(
                        bool(row["behavior"]["multi_call"]) for row in results
                    ),
                    "stateful_continuation_case_count": sum(
                        bool(row["behavior"]["stateful_continuation_used"])
                        for row in results
                    ),
                    "persisted_frontier_call_count": sum(
                        int(row["behavior"]["persisted_frontier_call_count"])
                        for row in results
                    ),
                    "fresh_reacquisition_after_first_count": sum(
                        int(row["behavior"]["fresh_reacquisition_after_first_count"])
                        for row in results
                    ),
                    "novel_turn_refs_after_first": sum(
                        int(row["behavior"]["novel_turn_refs_after_first"])
                        for row in results
                    ),
                },
                "results": results,
                "database_counts": counts,
                "canonical_mutation": counts["canonical"],
                "model_backend": "none",
                "judge": "none_deterministic_normalized_em_f1_only",
                "leaderboard_equivalence_claimed": False,
                "run_owned_database_volume_removed": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            }
            return summary
        except Exception as exc:
            summary = {
                "schema_version": "milai-product09-codex-http-lme-slice-v3",
                "status": "FAIL_PRODUCT09_LME_DIAGNOSTIC",
                "run_id": args.run_id,
                "phase": phase,
                "failure": {"type": type(exc).__name__, "message": str(exc)},
                "formal_holdout_consumed": False,
                "persisted_frontier_continuation_enabled": (
                    args.enable_persisted_frontier_continuation
                ),
                "behavior_policy": args.behavior_policy,
                "run_owned_database_volume_removed": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
            }
            return summary
        finally:
            processes.stop()
            if postgres_started:
                down = p09._command(
                    [*compose, "down", "--volumes", "--remove-orphans"],
                    cwd=p09.RUNTIME,
                    timeout=90,
                    check=False,
                )
                summary["run_owned_database_volume_removed"] = down.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--selection-manifest", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--answer-turn-labels", type=Path, default=DEFAULT_ANSWER_TURNS)
    parser.add_argument("--case-ids", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--capture-workers", type=int, default=8)
    parser.add_argument("--codex-timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--behavior-policy",
        choices=("natural", "guided-continuation"),
        default="natural",
    )
    parser.add_argument(
        "--enable-persisted-frontier-continuation",
        action="store_true",
        help="enable Product-11 D1 in the fresh simulation Runtime",
    )
    parser.add_argument(
        "--codex",
        type=Path,
        default=Path(os.environ.get("CODEX_BIN", "/root/.local/bin/codex")),
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output already exists")
    if not 1 <= args.capture_workers <= 16:
        raise SystemExit("capture-workers must be between 1 and 16")
    summary = run(args)
    p09._write_summary(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
