#!/usr/bin/env python3
"""Score Product-11 D2 SHADOW on opened-development LME exact turn identities."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import run_product09_codex_lifecycle as p09
import run_product09_codex_lme as lme

LAB = Path(__file__).resolve().parents[1]
RUNTIME = LAB.parent / "MiLAi-Product" / "runtime"
DEFAULT_CASE_ID = "0a995998"
SIMULATED_SELECTION_CAP = 20
WIDE_BUDGET = {
    "max_results": 50,
    "max_candidates": 120,
    "max_context_tokens": 16_384,
    "max_latency_ms": 5_000,
}


class LmeD2ShadowError(RuntimeError):
    pass


def _strings(value: object) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _score_shadow(
    raw: Mapping[str, Any],
    required_turn_refs: Mapping[str, Mapping[str, int | str]],
    *,
    simulated_selection_cap: int = SIMULATED_SELECTION_CAP,
) -> dict[str, Any]:
    context = raw.get("memory_context")
    context = context if isinstance(context, Mapping) else {}
    public_turn_refs = _strings(context.get("selected_source_turn_refs"))
    shadow = raw.get("intra_source_acquisition_shadow")
    if not isinstance(shadow, Mapping):
        raise LmeD2ShadowError("Runtime response omitted D2 SHADOW diagnostics")
    raw_candidates = shadow.get("candidates")
    candidates = (
        [row for row in raw_candidates if isinstance(row, Mapping)]
        if isinstance(raw_candidates, list)
        else []
    )
    fine_turn_refs = {
        source_ref
        for row in candidates
        if isinstance((source_ref := row.get("source_ref")), str) and source_ref
    }
    candidates_by_source_ref = {
        str(row["source_ref"]): row
        for row in candidates
        if isinstance(row.get("source_ref"), str) and row.get("source_ref")
    }
    novel_source_ranks: dict[str, int] = {}
    per_source_first_rows: list[Mapping[str, Any]] = []
    per_source_counts: dict[tuple[str, str], int] = {}
    for row in sorted(
        candidates,
        key=lambda item: (
            int(item.get("global_rank", 1_000_000)),
            str(item.get("evidence_id", "")),
        ),
    ):
        if row.get("already_in_coarse_pool") is not False:
            continue
        source_ref = row.get("source_ref")
        session_id = row.get("session_id")
        source_type = row.get("source_type")
        if not all(
            isinstance(value, str) and value
            for value in (source_ref, session_id, source_type)
        ):
            continue
        assert isinstance(source_ref, str)
        assert isinstance(session_id, str)
        assert isinstance(source_type, str)
        key = (source_type, session_id)
        rank = per_source_counts.get(key, 0) + 1
        per_source_counts[key] = rank
        novel_source_ranks[source_ref] = rank
        if rank == 1:
            per_source_first_rows.append(row)
    per_source_first_global_positions = {
        str(row["source_ref"]): position
        for position, row in enumerate(per_source_first_rows, start=1)
    }
    simulated_selected_rows = per_source_first_rows[:simulated_selection_cap]
    simulated_selected_turn_refs = {
        str(row["source_ref"])
        for row in simulated_selected_rows
        if isinstance(row.get("source_ref"), str) and row.get("source_ref")
    }
    required = set(required_turn_refs)
    public_required = required & public_turn_refs
    fine_required = required & fine_turn_refs
    missing_before_shadow = required - public_required
    recovered_missing = missing_before_shadow & fine_required
    simulated_selected_required = required & simulated_selected_turn_refs
    simulated_cumulative_required = public_required | simulated_selected_required
    simulated_recovered_missing = missing_before_shadow & simulated_selected_required
    return {
        "required_turn_count": len(required),
        "public_required_turn_count": len(public_required),
        "missing_required_turn_count": len(missing_before_shadow),
        "fine_required_turn_count": len(fine_required),
        "recovered_missing_required_turn_count": len(recovered_missing),
        "all_missing_required_turns_fine_acquired": missing_before_shadow <= fine_required,
        "required_turn_visibility": [
            {
                **required_turn_refs[turn_ref],
                "turn_ref": turn_ref,
                "public_context": turn_ref in public_required,
                "d2_shadow": turn_ref in fine_required,
                "recovered_by_d2_shadow": turn_ref in recovered_missing,
                "d2_global_rank": candidates_by_source_ref.get(turn_ref, {}).get(
                    "global_rank"
                ),
                "d2_channel_rank": (
                    candidates_by_source_ref.get(turn_ref, {})
                    .get("channel_ranks", {})
                    .get("FTS_INTRA_SOURCE")
                    if isinstance(
                        candidates_by_source_ref.get(turn_ref, {}).get("channel_ranks"),
                        Mapping,
                    )
                    else None
                ),
                "already_in_coarse_pool": candidates_by_source_ref.get(turn_ref, {}).get(
                    "already_in_coarse_pool"
                ),
                "d2_novel_source_rank": novel_source_ranks.get(turn_ref),
                "d2_position_among_per_source_first_novel": (
                    per_source_first_global_positions.get(turn_ref)
                ),
                "simulated_policy_selected": turn_ref in simulated_selected_turn_refs,
                "simulated_policy_cumulative_visible": (
                    turn_ref in simulated_cumulative_required
                ),
            }
            for turn_ref in sorted(required)
        ],
        "shadow": {
            key: shadow.get(key)
            for key in (
                "mode",
                "status",
                "acquisition_channel",
                "requested_coarse_session_count",
                "requested_coarse_candidate_count",
                "fine_candidate_count",
                "novel_fine_candidate_count",
                "public_context_changed",
                "frontier_changed",
                "new_global_source_acquisition_calls",
                "hydration_credited_as_discovery",
                "hidden_model_calls",
                "canonical_mutation",
            )
        },
        "selection_diagnostics": {
            "source_with_novel_candidate_count": len(per_source_counts),
            "per_source_first_novel_candidate_count": len(per_source_counts),
            "missing_turns_covered_by_per_source_novel_cap_1": sum(
                novel_source_ranks.get(turn_ref) == 1 for turn_ref in missing_before_shadow
            ),
            "all_missing_turns_covered_by_per_source_novel_cap_1": all(
                novel_source_ranks.get(turn_ref) == 1 for turn_ref in missing_before_shadow
            ),
            "simulated_policy": {
                "name": "FIRST_NOVEL_PER_SOURCE_THEN_GLOBAL_CAP",
                "cap": simulated_selection_cap,
                "selected_candidate_count": len(simulated_selected_rows),
                "selected_required_turn_count": len(simulated_selected_required),
                "cumulative_required_turn_count": len(simulated_cumulative_required),
                "recovered_missing_required_turn_count": len(
                    simulated_recovered_missing
                ),
                "lost_public_required_turn_count": len(
                    public_required - simulated_cumulative_required
                ),
                "all_missing_required_turns_recovered": (
                    missing_before_shadow <= simulated_selected_required
                ),
            },
        },
    }


def _query(record: Mapping[str, Any]) -> str:
    return str(record["question"])


def _wait_projection_batched(
    environment: dict[str, str], outbox_ids: Sequence[str], *, batch_size: int = 512
) -> None:
    for start in range(0, len(outbox_ids), batch_size):
        p09._wait_projection(environment, list(outbox_ids[start : start + batch_size]))


def _aggregate_results(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_count = len(results)
    scorable_results = [row for row in results if int(row["required_turn_count"]) > 0]
    scorable_case_count = len(scorable_results)
    required = sum(int(row["required_turn_count"]) for row in results)
    public = sum(int(row["public_required_turn_count"]) for row in results)
    fine = sum(int(row["fine_required_turn_count"]) for row in results)
    simulated = sum(
        int(row["selection_diagnostics"]["simulated_policy"]["cumulative_required_turn_count"])
        for row in results
    )
    opportunities = [row for row in results if int(row["missing_required_turn_count"]) > 0]
    timing_fields = ("capture_ms", "projection_wait_ms", "resolve_ms")
    timing_totals = {
        field: round(sum(float(row.get(field, 0.0)) for row in results), 3)
        for field in timing_fields
    }
    return {
        "case_count": case_count,
        "exact_turn_scorable_case_count": scorable_case_count,
        "zero_required_turn_case_count": case_count - scorable_case_count,
        "required_turn_count": required,
        "public_required_turn_count": public,
        "fine_required_turn_count": fine,
        "simulated_cumulative_required_turn_count": simulated,
        "public_micro_coverage": public / required if required else 1.0,
        "fine_micro_coverage": fine / required if required else 1.0,
        "simulated_cumulative_micro_coverage": simulated / required if required else 1.0,
        "public_macro_coverage": (
            sum(
                int(row["public_required_turn_count"])
                / int(row["required_turn_count"])
                for row in scorable_results
            )
            / scorable_case_count
            if scorable_case_count
            else 1.0
        ),
        "simulated_cumulative_macro_coverage": (
            sum(
                int(row["selection_diagnostics"]["simulated_policy"]["cumulative_required_turn_count"])
                / int(row["required_turn_count"])
                for row in scorable_results
            )
            / scorable_case_count
            if scorable_case_count
            else 1.0
        ),
        "case_with_public_gap_count": len(opportunities),
        "case_with_simulated_gain_count": sum(
            int(row["selection_diagnostics"]["simulated_policy"]["recovered_missing_required_turn_count"])
            > 0
            for row in results
        ),
        "case_with_simulated_loss_count": sum(
            int(row["selection_diagnostics"]["simulated_policy"]["lost_public_required_turn_count"])
            > 0
            for row in results
        ),
        "missing_required_turn_count": sum(
            int(row["missing_required_turn_count"]) for row in results
        ),
        "simulated_recovered_missing_required_turn_count": sum(
            int(row["selection_diagnostics"]["simulated_policy"]["recovered_missing_required_turn_count"])
            for row in results
        ),
        "all_public_gap_cases_fully_recovered": all(
            bool(
                row["selection_diagnostics"]["simulated_policy"]
                ["all_missing_required_turns_recovered"]
            )
            for row in opportunities
        ),
        "timing_totals_ms": timing_totals,
        "timing_share": {
            field: (
                value / sum(timing_totals.values()) if sum(timing_totals.values()) else 0.0
            )
            for field, value in timing_totals.items()
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    requested_case_ids = tuple(args.case_ids or (DEFAULT_CASE_ID,))
    selected = lme._load_cases(
        args.dataset_manifest,
        args.selection_manifest,
        args.answer_turn_labels,
        requested_case_ids,
    )
    postgres_port = p09._free_port()
    api_port = p09._free_port()
    compose_project = f"{args.run_id}-pg"
    postgres_started = False
    cleanup = False
    results: list[dict[str, Any]] = []
    total_history_event_count = 0
    with tempfile.TemporaryDirectory(prefix="milai-lme-d2-shadow-") as temporary:
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
            cwd=RUNTIME,
        )
        environment = p09._load_environment(env_file)
        environment.update(
            {
                "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
                "MILAI_INTRA_SOURCE_ACQUISITION_V0_1_MODE": "SHADOW",
            }
        )
        compose = [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(env_file),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        try:
            p09._command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
            postgres_started = True
            deadline = time.monotonic() + 90
            while True:
                migration = p09._command(
                    [str(p09.ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                    cwd=RUNTIME,
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
                    raise LmeD2ShadowError("fresh PostgreSQL migration did not become ready")
                time.sleep(1)
            p09._start_runtime(processes, environment)
            for record, metadata, answer_turns in selected:
                case_id = str(record["question_id"])
                project = f"p11-d2-{lme._stable(f'{args.run_id}:{case_id}', 16)}"
                events, _, required_turn_refs = lme._history_events(
                    record, project, answer_turns
                )
                total_history_event_count += len(events)
                capture_started = time.perf_counter()
                outbox_ids = lme._capture_case(
                    environment,
                    events,
                    workers=args.capture_workers,
                )
                capture_ms = (time.perf_counter() - capture_started) * 1_000
                projection_started = time.perf_counter()
                _wait_projection_batched(environment, outbox_ids)
                projection_wait_ms = (time.perf_counter() - projection_started) * 1_000
                resolve_started = time.perf_counter()
                status_code, raw = p09._http_json(
                    "POST",
                    f"{environment['MILAI_BASE_URL']}/v1/memory/resolve",
                    token=environment["MILAI_AGENT_READER_TOKEN"],
                    payload={
                        "query": _query(record),
                        "invocation_mode": "EXPLICIT_READ",
                        "requested_scope": {"project_ids": [project]},
                        "required_authority": "INFORMATIONAL",
                        "required_freshness": "CURRENT",
                        "consistency_mode": "CANONICAL_REQUIRED",
                        "reference_time": lme._observed_at(record["question_date"], 0),
                        "budget": WIDE_BUDGET,
                    },
                    timeout=30,
                )
                resolve_ms = (time.perf_counter() - resolve_started) * 1_000
                if status_code != 200:
                    raise LmeD2ShadowError(
                        f"Runtime resolve for {case_id} returned HTTP {status_code}"
                    )
                result = _score_shadow(raw, required_turn_refs)
                results.append(
                    {
                        "case_id": case_id,
                        "capability_family": metadata["capability_family"],
                        "history_event_count": len(events),
                        "capture_ms": round(capture_ms, 3),
                        "projection_wait_ms": round(projection_wait_ms, 3),
                        "resolve_ms": round(resolve_ms, 3),
                        **result,
                    }
                )
            counts = p09._database_counts(compose)
            if counts["canonical"] != 0:
                raise LmeD2ShadowError("D2 SHADOW resolve mutated Canonical tables")
        finally:
            processes.stop()
            if postgres_started:
                down = p09._command(
                    [*compose, "down", "--volumes", "--remove-orphans"],
                    cwd=RUNTIME,
                    timeout=90,
                    check=False,
                )
                cleanup = down.returncode == 0
    valid = (
        len(results) == len(requested_case_ids)
        and all(
            row["shadow"]["mode"] == "SHADOW"
            and row["shadow"]["status"] == "COMPLETE"
            and row["shadow"]["public_context_changed"] is False
            and row["shadow"]["frontier_changed"] is False
            and row["shadow"]["new_global_source_acquisition_calls"] == 0
            and row["shadow"]["hidden_model_calls"] == 0
            and row["shadow"]["canonical_mutation"] is False
            for row in results
        )
        and counts["canonical"] == 0
        and cleanup
    )
    aggregate = _aggregate_results(results)
    return {
        "schema_version": "milai-lme-d2-shadow-diagnostic-v0.2",
        "status": (
            "PASS_LME_D2_SHADOW_DIAGNOSTIC_EXECUTED"
            if valid
            else "FAIL_LME_D2_SHADOW_DIAGNOSTIC_INVALID"
        ),
        "run_id": args.run_id,
        "case_ids": list(requested_case_ids),
        "selection": "OPENED_DEVELOPMENT_ONLY",
        "formal_holdout_consumed": False,
        "model_assisted_answer_turn_labels": True,
        "human_adjudication_claimed": False,
        "product_effect_claimed": False,
        "query_label_blind": True,
        "simulated_selection_policy": {
            "name": "FIRST_NOVEL_PER_SOURCE_THEN_GLOBAL_CAP",
            "exclude_already_in_coarse_pool": True,
            "source_identity": ["source_type", "session_id"],
            "per_source_cap": 1,
            "global_cap": SIMULATED_SELECTION_CAP,
            "ranking": ["global_rank", "evidence_id"],
            "public_context_combination": "UNION_NON_DESTRUCTIVE",
        },
        "history_event_count": total_history_event_count,
        "database_counts": counts,
        "run_owned_database_volume_removed": cleanup,
        "aggregate": aggregate,
        "results": results,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="opened-development case id; repeat for a multi-case run",
    )
    parser.add_argument("--dataset-manifest", type=Path, default=lme.DEFAULT_MANIFEST)
    parser.add_argument("--selection-manifest", type=Path, default=lme.DEFAULT_SELECTION)
    parser.add_argument("--answer-turn-labels", type=Path, default=lme.DEFAULT_ANSWER_TURNS)
    parser.add_argument("--capture-workers", type=int, default=8)
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
