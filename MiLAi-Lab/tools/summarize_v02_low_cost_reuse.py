"""Produce the compact terminal ledger without dropping failed allocations."""

from __future__ import annotations

import json

import run_v02_memory_flow as base
from run_v02_low_cost_diagnostics import CONFIG, ROOT
from v02_low_cost_protocol import digest, usage_tokens


def main() -> None:
    rows = []
    for path in sorted(ROOT.parent.glob("*/sessions/*/allocation.json")):
        allocation = base.read_json(path)
        result = base.read_json(path.parent / "result.json")
        tokens = usage_tokens(result)
        if tokens is None:
            raise RuntimeError("Started usage unresolved; terminal cost ledger unavailable")
        usage = result.get("usage") or []
        row = {"allocation_id": allocation["allocation_id"], "phase": allocation["phase"],
               "batch_id": allocation["batch_id"], "case_id": allocation["case_id"],
               "arm": allocation["arm"], "kind": allocation["kind"],
               "status": result.get("status", "COMPLETED"),
               "model_started": result["model_started"], "tokens": tokens,
               "input_tokens": sum(x["input_tokens"] for x in usage),
               "output_tokens": sum(x["output_tokens"] for x in usage),
               "cached_input_tokens": sum(x["cached_input_tokens"] for x in usage),
               "raw_online_seconds": result["raw_online_seconds"],
               "operational_online_seconds": result.get("operational_online_seconds"),
               "instrumentation_seconds": result.get("instrumentation_seconds"),
               "tool_actions": base.tool_action_count(
                   base.parse_events(path.parent / "events.jsonl")),
               "source_sha256": allocation["source_sha256"],
               "config_sha256": allocation["config_sha256"],
               "artifact": str(path.parent.relative_to(base.LAB))}
        if (path.parent / "qualification.json").exists():
            row["qualification"] = base.read_json(path.parent / "qualification.json")
            checkpoint = base.read_json(path.parent / "checkpoint.json")
            row["checkpoint"] = {key: checkpoint[key] for key in (
                "status", "reason", "model_tokens", "model_dispatches", "delta_save_seconds",
                "delta_save_cpu_seconds", "api_calls")}
        rows.append(row)
    completed = [r for r in rows if r["model_started"]]
    if len(completed) != 2 or any(r.get("qualification", {}).get("status") != "INELIGIBLE"
                                 for r in completed):
        raise RuntimeError("This summary requires the observed two-ineligible-history exit")
    testkit = []
    for path in sorted(ROOT.glob("testkit/batch-*/*/result.json")):
        a = base.read_json(path.parent / "allocation.json")
        testkit.append({"batch": a["batch"], "case": a["case"],
                        "artifact": str(path.parent.relative_to(base.LAB)),
                        **base.read_json(path)})
    config = base.read_json(CONFIG)
    result = {
        "status": "COMPLETED_KEEP_BASELINE" if (ROOT / "cleanup.json").exists()
                  else "IN_PROGRESS_EXIT_SELECTED", "study": "MILA-V02-03",
        "pin": base.pin(CONFIG), "config_sha256": digest(CONFIG),
        "stages": {"N0": "READY", "N1": "NEUTRAL_TRACE_READY",
                   "N2": "AUDIT_COMPLETE_COUNT_AMBIGUOUS_CONTROLS_SCORABLE",
                   "N3": "CONDITIONAL_CHECKPOINT_READY_WITH_PUBLIC_STRING_BOUNDARY_REJECTION",
                   "N4": "NOT_EVALUABLE_NO_ELIGIBLE_EXACT_COPY",
                   "N5": "NOT_ENTERED_NO_N4_PASS_OR_RELIABLE_QA_DEFECT"},
        "model_allocations": len(rows), "actual_model_sessions": len(completed),
        "phase_allocations": {phase: sum(r["phase"] == phase for r in rows)
                              for phase in ("N0_N2", "N3_N4", "N5")},
        "limits": config["model_phase_limits"],
        "known_token_launch_gate": config["known_token_launch_gate"],
        "known_input_tokens": sum(r["input_tokens"] for r in rows),
        "known_output_tokens": sum(r["output_tokens"] for r in rows),
        "known_total_tokens": sum(r["tokens"] for r in rows),
        "cached_input_tokens_subset": sum(r["cached_input_tokens"] for r in rows),
        "all_allocations_terminal": True, "unknown_started_usage": False,
        "raw_online_seconds_all_allocations": sum(r["raw_online_seconds"] for r in rows),
        "completed_G_operational_seconds": sum(r["operational_online_seconds"] for r in completed),
        "candidate_rejection_seconds": sum(
            r["checkpoint"]["delta_save_seconds"] for r in completed),
        "candidate_rejection_api_calls": sum(r["checkpoint"]["api_calls"] for r in completed),
        "G_notes": 2, "eligible_notes": 0, "natural_state_saves": 0,
        "successful_candidate_saves": 0, "future_allocations": 0,
        "F_S_token_ratio": None, "F_S_wall_net_gain": None,
        "full_G_plus_F_or_S_path_cost": None,
        "effect_claim": "NOT_EVALUABLE; neither cost superiority nor inferiority established",
        "allocations": rows, "testkit_calls": testkit,
        "testkit_calls_total": len(testkit), "testkit_official_resolve_reads": 3 * len(testkit),
        "checks": {"runtime_pg_pytest": {"passed": 962, "skipped": 1,
                    "skip_reason": "Runtime venv lacks milai_client; one context-chat test"},
                   "runtime_static_build": "PASS", "lab_pytest_passed": 159,
                   "lab_ruff_mypy_boundary_build": "PASS", "directed_pg_continuation_passed": 7,
                   "exact_note_unit_passed": 23, "exact_note_public_pg": "PASS_RESTRICTED_INPUT",
                   "full_A0_tool_count": 13},
        "research_cost_limitations": [
            "No F/S paths executed; their complete costs and ratios are unobserved, not zero.",
            "First pre-model prompt-input timeout has known raw duration but unknown exact "
            "operational/instrumentation partition; counts one allocation, zero model exec.",
            "First N3 diagnostic wall time was not retained; kept unknown, not zero.",
            "Capture/READY, setup, diagnostics, tests and observer costs are research overhead; "
            "available phase receipts preserved; root engineering total not fully observed.",
        ],
        "later_model_inputs": "UNOBSERVED", "independent_judge_model_allocations": 0,
        "root_offline_review_is_not_independent_human_gold": True,
        "formal_500_scoring": False, "public_deployment": False,
        "automatic_maintenance": False, "D2": "SHADOW", "default": "FULL_A0",
        "cleanup": base.read_json(ROOT / "cleanup.json") if (ROOT / "cleanup.json").exists()
                   else {"status": "PENDING"},
    }
    target = base.LAB / "studies/active/MILA_V02_LOW_COST_REUSE_RESULTS.json"
    base.write_json(target, result)
    print(json.dumps({key: result[key] for key in (
        "model_allocations", "actual_model_sessions", "known_total_tokens", "eligible_notes",
        "completed_G_operational_seconds", "candidate_rejection_seconds")}))


if __name__ == "__main__":
    main()
