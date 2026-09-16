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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.harness.artifacts import RunArtifacts  # noqa: E402
from milai_lab.product02_decision import sealed_answer_evidence  # noqa: E402
from milai_lab.product03_opportunity import (  # noqa: E402
    OpportunityCase,
    channel_candidate_refs,
    compare_mechanisms,
    select_allowed_treatment,
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
    _wait_projection,
)
from run_product02_context_gate import _dataset_path, _load_population  # noqa: E402
from run_product02_longmemeval import _load_label_manifest  # noqa: E402


class ProbeError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Product-03 official acquisition opportunity probe"
    )
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-lock", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--label-manifest", type=Path, required=True)
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("A0", "DIAGNOSTIC", "T1"), required=True)
    parser.add_argument("--baseline-artifact", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:38081")
    parser.add_argument("--capture-concurrency", type=int, default=8)
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _selection(path: Path) -> tuple[list[dict[str, str]], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, Mapping) else None
    schema = raw.get("schema_version") if isinstance(raw, Mapping) else None
    opportunity_selection = schema == "milai-product03-opportunity-selection-v0.1"
    micro_selection = schema == "milai-product03-t1-micro-selection-v0.1"
    context_selection = schema == "milai-product03-context24-selection-v0.1"
    if (
        not isinstance(raw, Mapping)
        or not (opportunity_selection or micro_selection or context_selection)
        or raw.get("opened_development_only") is not True
        or raw.get("formal_holdout_consumed") is not False
        or not isinstance(cases, list)
        or (opportunity_selection and not 12 <= len(cases) <= 16)
        or (micro_selection and not 8 <= len(cases) <= 12)
        or (context_selection and len(cases) != 24)
    ):
        raise ProbeError("opportunity selection contract is invalid")
    selected: list[dict[str, str]] = []
    for item in cases:
        if not isinstance(item, Mapping) or any(
            not isinstance(item.get(key), str)
            for key in ("case_id", "family", "query_type")
        ):
            raise ProbeError("opportunity selection case is invalid")
        selected.append(
            {
                "case_id": str(item["case_id"]),
                "family": str(item["family"]),
                "query_type": str(item["query_type"]),
            }
        )
    if len({item["case_id"] for item in selected}) != len(selected):
        raise ProbeError("opportunity selection contains duplicate cases")
    families = Counter(item["family"].split("_", 1)[0] for item in selected)
    f1_types = {
        item["query_type"] for item in selected if item["family"].startswith("F1_")
    }
    opportunity_valid = (
        families["F1"] >= 6
        and len(f1_types) >= 4
        and families["F2"] >= 2
        and families["F3"] >= 2
        and families["F4"] + families["F5"] >= 2
    )
    micro_valid = families["F1"] == len(selected)
    if (opportunity_selection and not opportunity_valid) or (
        micro_selection and not micro_valid
    ):
        raise ProbeError("opportunity selection does not satisfy family coverage")
    return selected, _sha256_file(path)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProbeError(f"{label} is missing or invalid")
    return value


def _opportunity_from_row(row: Mapping[str, Any]) -> OpportunityCase:
    candidate_refs = _mapping(row.get("candidate_refs"), "candidate refs")
    raw_groups = row.get("required_role_groups")
    if not isinstance(raw_groups, list):
        raise ProbeError("required role groups are invalid")
    return OpportunityCase(
        case_id=str(row["case_id"]),
        family=str(row["family"]),
        query_type=str(row["query_type"]),
        answer_turn_refs=tuple(str(value) for value in row.get("answer_turn_refs", [])),
        required_role_groups=tuple(
            tuple(str(value) for value in group)
            for group in raw_groups
            if isinstance(group, list)
        ),
        candidate_refs={
            str(key): tuple(str(value) for value in values)
            for key, values in candidate_refs.items()
            if isinstance(values, list)
        },
        candidate_count=int(row["candidate_count"]),
        duplicate_occurrence_count=int(row["duplicate_occurrence_count"]),
    )


def _load_artifact_cases(path: Path) -> list[OpportunityCase]:
    case_path = path / "cases.jsonl"
    if not case_path.is_file():
        raise ProbeError("baseline opportunity artifact has no cases.jsonl")
    return [
        _opportunity_from_row(json.loads(line))
        for line in case_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise ProbeError("run output already exists")
    if not 1 <= args.capture_concurrency <= 12:
        raise ProbeError("capture concurrency must be 1..12")
    if (args.profile == "A0") != (args.baseline_artifact is None):
        raise ProbeError("only DIAGNOSTIC profile accepts a baseline artifact")

    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, args.product_root)
    if not verification.valid:
        raise ProbeError("Product pin failed: " + "; ".join(verification.errors))
    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    population = _load_population(dataset_path)
    population_by_id = {str(item["question_id"]): item for item in population}
    selected, selection_sha256 = _selection(args.selection)
    _label_payload, labels_by_id = _load_label_manifest(
        args.label_manifest,
        dataset_sha256=dataset_sha256,
        population=population,
    )
    if any(item["case_id"] not in population_by_id for item in selected):
        raise ProbeError("selection contains a case outside the pinned dataset")
    if any(
        population_by_id[item["case_id"]].get("question_type") != item["query_type"]
        for item in selected
    ):
        raise ProbeError("selection query type drifted from the pinned dataset")

    env = _load_env(args.env_file)
    submitter = RuntimeHttpClient(
        args.base_url,
        env["MILAI_AGENT_SUBMITTER_TOKEN"],
        max_connections=args.capture_concurrency,
    )
    reader = RuntimeHttpClient(
        args.base_url,
        env["MILAI_AGENT_READER_TOKEN"],
        max_connections=4,
    )
    artifacts = RunArtifacts(args.output)
    started_at = datetime.now(UTC)
    run_id = f"product03-opportunity-{args.profile.casefold()}-{started_at:%Y%m%dT%H%M%SZ}"
    artifacts.write_json(
        "run.json",
        {
            "schema_version": "milai-product03-opportunity-run-v1",
            "run_id": run_id,
            "status": "RUNNING",
            "started_at": started_at.isoformat(),
            "arm_kind": "PRODUCT_BLACK_BOX_READ_ONLY_TRACE",
            "profile": args.profile,
            "product_commit": lock.git_commit,
            "product_tree_sha256": lock.tree_sha256,
            "product_lock_digest": lock.digest,
            "dataset_sha256": dataset_sha256,
            "label_manifest_sha256": _sha256_file(args.label_manifest),
            "selection_sha256": selection_sha256,
            "case_count": len(selected),
            "candidate_ceiling": 120,
            "context_token_budget": 8192,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
            "automatic_retries": 0,
            "formal_holdout_consumed": False,
        },
    )

    rows: list[OpportunityCase] = []
    failures: list[dict[str, str]] = []
    try:
        capabilities = await reader.request("GET", "/v1/capabilities")
        if capabilities.get("contract_version") != "agent.v1":
            raise ProbeError("Runtime agent contract is incompatible")
        for ordinal, selected_case in enumerate(selected, start=1):
            case_id = selected_case["case_id"]
            record = population_by_id[case_id]
            started = time.perf_counter()
            try:
                events = _history_events(record)
                sealed = sealed_answer_evidence(record, events, labels_by_id[case_id])
                outbox_ids, identities = await _capture_case(
                    submitter,
                    events,
                    concurrency=args.capture_concurrency,
                )
                await _wait_projection(reader, outbox_ids)
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
                            "max_context_tokens": 8192,
                            "max_latency_ms": 2000,
                        },
                    },
                )
                context = _mapping(result.get("memory_context"), "MemoryContext")
                compile_trace = _mapping(context.get("compile_trace"), "compile trace")
                acquired = _mapping(
                    compile_trace.get("acquired_candidate_trace"),
                    "acquired candidate trace",
                )
                candidates_raw = acquired.get("candidates")
                if not isinstance(candidates_raw, list) or any(
                    not isinstance(value, Mapping) for value in candidates_raw
                ):
                    raise ProbeError("acquired candidates are invalid")
                candidates = [value for value in candidates_raw if isinstance(value, Mapping)]
                known_refs = {value["source_ref"] for value in identities.values()}
                observed_refs = {
                    str(value["source_turn_ref"])
                    for value in candidates
                    if isinstance(value.get("source_turn_ref"), str)
                }
                if not observed_refs.issubset(known_refs):
                    raise ProbeError("scope or source identity leak in acquired trace")
                if acquired.get("candidate_count") != len(candidates) or len(candidates) > 120:
                    raise ProbeError("candidate ceiling or trace cardinality drifted")
                search_trace = _mapping(result.get("search_trace"), "search trace")
                dispositions_raw = search_trace.get("acquisition_probe_dispositions")
                dispositions = (
                    [value for value in dispositions_raw if isinstance(value, Mapping)]
                    if isinstance(dispositions_raw, list)
                    else []
                )
                executed_channels = {
                    str(value.get("channel"))
                    for value in dispositions
                    if value.get("status") == "EXECUTED"
                }
                if args.profile == "A0" and executed_channels.intersection(
                    {"EVIDENCE_DENSE", "ADJACENT_TURNS"}
                ):
                    raise ProbeError("A0 executed a diagnostic channel")
                if args.profile == "DIAGNOSTIC" and not {
                    "EVIDENCE_DENSE",
                    "ADJACENT_TURNS",
                }.issubset({str(value.get("channel")) for value in dispositions}):
                    raise ProbeError("diagnostic official channels were not traced")
                if args.profile == "T1" and (
                    "EVIDENCE_DENSE"
                    not in {str(value.get("channel")) for value in dispositions}
                    or "ADJACENT_TURNS" in executed_channels
                ):
                    raise ProbeError("T1 channel trace is not Dense-union only")
                refs = channel_candidate_refs(candidates)
                duplicate_occurrences = sum(
                    max(0, len(value.get("channel_ranks", {})) - 1)
                    for value in candidates
                    if isinstance(value.get("channel_ranks"), Mapping)
                )
                row = OpportunityCase(
                    case_id=case_id,
                    family=selected_case["family"],
                    query_type=selected_case["query_type"],
                    answer_turn_refs=tuple(
                        label.source_turn_ref for label in sealed.answer_labels
                    ),
                    required_role_groups=sealed.required_role_groups,
                    candidate_refs=refs,
                    candidate_count=len(candidates),
                    duplicate_occurrence_count=duplicate_occurrences,
                )
                payload = {
                    "case_id": row.case_id,
                    "ordinal": ordinal,
                    "status": "PASS",
                    "family": row.family,
                    "query_type": row.query_type,
                    "answer_turn_refs": list(row.answer_turn_refs),
                    "required_role_groups": [
                        list(group) for group in row.required_role_groups
                    ],
                    "candidate_refs": {
                        key: list(values) for key, values in row.candidate_refs.items()
                    },
                    "candidate_count": row.candidate_count,
                    "duplicate_occurrence_count": row.duplicate_occurrence_count,
                    "new_region_count": sum(
                        int(value.get("new_region_count", 0)) for value in dispositions
                    ),
                    "probe_dispositions": dispositions,
                    "acquired_trace_sha256": acquired.get("trace_sha256"),
                    "bound_trace_sha256": _mapping(
                        compile_trace.get("bound_evidence_trace"),
                        "bound Evidence trace",
                    ).get("trace_sha256"),
                    "reader_visible_trace_sha256": _mapping(
                        compile_trace.get("reader_visible_trace"),
                        "Reader-visible trace",
                    ).get("reader_context_sha256"),
                    "reader_evidence_boundary": compile_trace.get(
                        "reader_evidence_boundary"
                    ),
                    "lean_recall_mode": compile_trace.get("lean_recall_mode"),
                    "canonical_mutation_count": int(
                        compile_trace.get("canonical_mutation") is not False
                    ),
                    "reader_calls": 0,
                    "answer_calls": 0,
                    "judge_calls": 0,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 6),
                }
                if payload["canonical_mutation_count"] != 0:
                    raise ProbeError("read path reported canonical mutation")
                artifacts.append_jsonl("cases.jsonl", payload)
                rows.append(row)
                print(
                    json.dumps(
                        {
                            "case": f"{ordinal}/{len(selected)}",
                            "case_id": case_id,
                            "status": "PASS",
                            "candidate_count": len(candidates),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            except Exception as exc:
                failure = {
                    "case_id": case_id,
                    "failure_type": type(exc).__name__,
                    "failure_message": str(exc)[:500],
                }
                failures.append(failure)
                artifacts.append_jsonl(
                    "cases.jsonl",
                    {
                        **failure,
                        "ordinal": ordinal,
                        "status": "FAIL",
                        "family": selected_case["family"],
                        "query_type": selected_case["query_type"],
                        "canonical_mutation_count": 0,
                        "reader_calls": 0,
                        "answer_calls": 0,
                        "judge_calls": 0,
                    },
                )
                print(json.dumps({**failure, "status": "FAIL"}, sort_keys=True), flush=True)
    finally:
        await submitter.close()
        await reader.close()

    comparison: dict[str, object] | None = None
    selected_treatment: str | None = None
    if args.baseline_artifact is not None and not failures:
        selected_ids = {row.case_id for row in rows}
        baseline_rows = [
            row
            for row in _load_artifact_cases(args.baseline_artifact)
            if row.case_id in selected_ids
        ]
        comparison = compare_mechanisms(baseline_rows, rows)
        selected_treatment = select_allowed_treatment(comparison)
    passed = len(rows) == len(selected) and not failures
    metrics = {
        "schema_version": "milai-product03-opportunity-metrics-v1",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "profile": args.profile,
        "case_count": len(rows),
        "failed_case_count": len(failures),
        "candidate_count": sum(row.candidate_count for row in rows),
        "duplicate_occurrence_count": sum(
            row.duplicate_occurrence_count for row in rows
        ),
        "comparison": comparison,
        "selected_treatment": selected_treatment,
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "canonical_mutation_count": 0,
    }
    artifacts.write_json("metrics.json", metrics)
    finished_at = datetime.now(UTC)
    terminal_status = (
        "FAIL_PRODUCT03_OPPORTUNITY_PROBE"
        if not passed
        else "PASS_PRODUCT03_A0_CAPTURED"
        if args.profile == "A0"
        else "PASS_PRODUCT03_T1_SELECTED"
        if selected_treatment is not None
        else "NO_SIMPLE_CHANNEL_OPPORTUNITY"
    )
    terminal = {
        "schema_version": "milai-product03-opportunity-terminal-v1",
        "run_id": run_id,
        "status": terminal_status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
        "profile": args.profile,
        "product_lock_digest": lock.digest,
        "selection_sha256": selection_sha256,
        "metrics_sha256": _canonical_sha256(metrics),
        "selected_treatment": selected_treatment,
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "canonical_mutation_count": 0,
    }
    artifacts.write_json("terminal.json", terminal)
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if passed else 1


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(
            f"Product-03 opportunity probe failed closed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
