"""Read-only settlement of the sealed batch using its pre-outcome protocol.

Only writes a new requested compact report, never modifies original run evidence.
This is post-run analysis code, not part of the sealed selection/runtime closure.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

from prepare_utility_proxy import sha
from v02_local_provider import read_events


def unadmitted_reservations(events: list[dict], dispatched_payloads: list[str]) -> list[str]:
    """Provider prepares before the transport gate; a rejected dispatch is not inference."""
    counts = Counter(dispatched_payloads)
    rejected = []
    for event in events:
        if event["event"] != "RESERVED":
            continue
        payload = event["payload_sha256"]
        if counts[payload]:
            counts[payload] -= 1
        else:
            rejected.append(event["request_id"])
    if any(counts.values()):
        raise ValueError("DISPATCH_WITHOUT_PROVIDER_RESERVATION")
    return rejected


def historical_costs(inputs: dict) -> dict:
    """Gross historical costs, not allocated per card or added to this batch's quota."""
    banks = {}
    for name in inputs["source_sha256"]:
        path = Path(name)
        if path.name != "bank.json":
            continue
        values = {}
        for kind, relative in (
            ("text", "provider/provider-ledger.jsonl"),
            ("embedding", "embedding/embedding-ledger.jsonl"),
        ):
            ledger = path.parent / relative
            events = read_events(ledger)
            reserved = {r["request_id"]: r for r in events if r["event"] == "RESERVED"}
            settled = {r["request_id"]: r for r in events if r["event"] == "SETTLED"}
            unknown = reserved.keys() - settled.keys()
            values[kind] = {
                "ledger_sha256": sha(ledger),
                "requests": len(reserved),
                "reported_token_subtotal": sum(
                    r["usage"]["total_tokens"] for r in settled.values()
                ),
                "unknown_requests": len(unknown),
                "actual_tokens": None
                if unknown
                else sum(r["usage"]["total_tokens"] for r in settled.values()),
            }
        banks[path.parent.name] = values
    cache = []
    for name in inputs["source_sha256"]:
        if name.endswith("-http.json"):
            response = json.loads(Path(name).read_text())
            value = json.loads(response["body"])
            cache.append(value.get("usage", {}).get("total_tokens"))
    return {
        "bank_source_runs_gross": banks,
        "cached_query_receipt_count": len(cache),
        "cached_query_reported_tokens": sum(n for n in cache if type(n) is int),
        "cached_query_unknown_receipts": sum(type(n) is not int for n in cache),
        "scope": "Sunk gross DEV/VALID source-run costs, not exact-bundle formation attribution; "
        "cached receipts overlap source-run embeddings and are NOT additive. "
        "Full lifecycle attribution and monetary cost remain UNKNOWN; no fresh "
        "retrieval or lifecycle saving is claimed.",
    }


def paired_rows(plan: list[dict], arms: dict[str, dict]) -> list[dict]:
    pairs = []
    for index in sorted({r["pair_index"] for r in plan}):
        rows = [r for r in plan if r["pair_index"] == index]
        metadata = rows[0]
        values = {r["arm"]: arms.get(r["attempt_id"]) for r in rows}
        known = all(v and v["outcome"] in {"correct", "incorrect"} for v in values.values())
        complete = all(v and v["status"] != "FAILED" for v in values.values())
        delta = None
        cost_delta = None
        seconds_delta = None
        if known:
            delta = int(values["UTILITY"]["outcome"] == "correct") - int(
                values["STATIC"]["outcome"] == "correct"
            )
        if complete:
            cost_delta = values["UTILITY"]["charged_tokens"] - values["STATIC"]["charged_tokens"]
            seconds_delta = values["UTILITY"]["seconds"] - values["STATIC"]["seconds"]
        pairs.append(
            {
                "pair_index": index,
                "domain": metadata["domain"],
                "task_id": metadata["task_id"],
                "repeat": metadata["repeat"],
                "selection_changed": metadata["selection_changed"],
                "mechanism_eligible": metadata["mechanism_eligible"],
                "arms": values,
                "quality_delta": delta,
                "charged_tokens_delta": cost_delta,
                "wall_seconds_delta": seconds_delta,
            }
        )
    return pairs


def group_summary(pairs: list[dict]) -> dict:
    known = [p for p in pairs if p["quality_delta"] is not None]
    costs = [p for p in pairs if p["charged_tokens_delta"] is not None]
    return {
        "scheduled_pairs": len(pairs),
        "known_quality_pairs": len(known),
        "unknown_quality_pairs": len(pairs) - len(known),
        "quality_gains": sum(p["quality_delta"] == 1 for p in known),
        "quality_regressions": sum(p["quality_delta"] == -1 for p in known),
        "quality_ties": sum(p["quality_delta"] == 0 for p in known),
        "correct_on_known_pairs": {
            arm: sum(p["arms"][arm]["outcome"] == "correct" for p in known)
            for arm in ("STATIC", "UTILITY")
        },
        "cost_complete_pairs": len(costs),
        "charged_tokens_delta_known_pairs": sum(p["charged_tokens_delta"] for p in costs),
        "wall_seconds_delta_known_pairs": sum(p["wall_seconds_delta"] for p in costs),
        "median_wall_seconds_delta": statistics.median(p["wall_seconds_delta"] for p in costs)
        if costs
        else None,
        "selection_changes": sum(p["selection_changed"] for p in pairs),
        "eligible_opportunities": sum(p["mechanism_eligible"] for p in pairs),
    }


def analyze(root: Path) -> dict:
    terminal = json.loads((root / "terminal.json").read_text())
    admission = json.loads((root / "admission.json").read_text())
    plan = json.loads((root / "plan.json").read_text())
    if sha(root / "admission.json") != terminal["admission_sha256"]:
        raise ValueError("ADMISSION_IDENTITY_CHANGED")
    if sha(root / "plan.json") != admission["source_sha256"][str(root / "plan.json")]:
        raise ValueError("PLAN_IDENTITY_CHANGED")
    events = read_events(root / "provider/provider-ledger.jsonl")
    with sqlite3.connect(f"file:{root / 'budget.sqlite'}?mode=ro", uri=True) as db:
        dispatched = [
            row[0]
            for row in db.execute(
                "SELECT payload_sha256 FROM attempts WHERE purpose='generation' ORDER BY id"
            )
        ]
    not_dispatched = unadmitted_reservations(events, dispatched)
    arms = {}
    for row in plan:
        path = root / "arms" / row["attempt_id"] / "result.json"
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        before, after = result["budget_before"], result["budget_after"]
        text_before, text_after = before["kinds"]["text"], after["kinds"]["text"]
        settled = [
            e for e in events if e["event"] == "SETTLED" and e.get("session") == row["attempt_id"]
        ]
        settled_ids = {e["request_id"] for e in settled}
        first_payload = next(
            (
                e["payload_sha256"]
                for e in events
                if e["event"] == "RESERVED" and e["request_id"] in settled_ids
            ),
            None,
        )
        arms[row["attempt_id"]] = {
            "status": result["status"],
            "outcome": result["outcome"],
            "failure_reason": result.get("reason") or result.get("finish_reason"),
            "seconds": result["seconds"],
            "reported_tokens": text_after["reported_tokens"] - text_before["reported_tokens"],
            "charged_tokens": text_after["charged_tokens"] - text_before["charged_tokens"],
            "unknown_upper_tokens": text_after["unknown_token_upper_bound"]
            - text_before["unknown_token_upper_bound"],
            "all_http_requests": after["total_requests"] - before["total_requests"],
            "generation_requests": after["requests_by_purpose"].get("generation", 0)
            - before["requests_by_purpose"].get("generation", 0),
            "prompt_tokens": sum(e["input_tokens"] for e in settled),
            "completion_tokens": sum(e["output_tokens"] for e in settled),
            "settled_generation_seconds": sum(e["seconds"] for e in settled),
            "observable_use": "UNKNOWN",
            "first_settled_payload_sha256": first_payload,
        }
        arm = arms[row["attempt_id"]]
        arm["actual_total_tokens"] = None if arm["unknown_upper_tokens"] else arm["reported_tokens"]
    pairs = paired_rows(plan, arms)
    for pair in pairs:
        payloads = [
            v.get("first_settled_payload_sha256") if v else None for v in pair["arms"].values()
        ]
        pair["same_first_settled_payload"] = len(set(payloads)) == 1 if all(payloads) else None
    groups = {}
    for domain in ("db_bench", "os_interaction"):
        for repeat in (False, True):
            groups[f"{domain}:{'repeats' if repeat else 'independent'}"] = group_summary(
                [p for p in pairs if p["domain"] == domain and p["repeat"] == repeat]
            )
    groups["independent_unchanged_selection"] = group_summary(
        [p for p in pairs if not p["repeat"] and not p["selection_changed"]]
    )
    eligible = [p for p in pairs if p["mechanism_eligible"]]
    eligible_signal = bool(eligible) and all(
        p["quality_delta"] is not None
        and p["quality_delta"] >= 0
        and p["charged_tokens_delta"] is not None
        and p["charged_tokens_delta"] < 0
        and all(v["unknown_upper_tokens"] == 0 for v in p["arms"].values())
        for p in eligible
    )
    # A direction signal requires an original AND its preselected repeat, not two new tasks.
    eligible_signal = eligible_signal and {p["repeat"] for p in eligible} == {False, True}
    usage = terminal["budget"]
    if any(
        v["unknown_token_upper_bound"] or v["pending_requests"] for v in usage["kinds"].values()
    ):
        eligible_signal = False
    # The protocol's quality non-regression gate is not waived for unchanged
    # selections. Such losses are background variability, not causal Utility harm,
    # but they cannot be silently removed to declare an overall positive signal.
    protocol_signal = eligible_signal and not any(p["quality_delta"] == -1 for p in pairs)
    charged = sum(a["charged_tokens"] for a in arms.values())
    shared_tokens = usage["kinds"]["text"]["charged_tokens"] - charged
    shared_requests = usage["total_requests"] - sum(a["all_http_requests"] for a in arms.values())
    if min(shared_tokens, shared_requests) < 0:
        raise ValueError("COST_RECONCILIATION_FAILED")
    inputs = json.loads((root / "inputs.proposal.json").read_text())
    return {
        "schema": "milai-utility-proxy-result-v1",
        "arm_kind": "RESEARCH_PROTOTYPE",
        "status": terminal["status"],
        "stop_reason": terminal["reason"],
        "admission_sha256": terminal["admission_sha256"],
        "evidence_root": str(root),
        "terminal_sha256": sha(root / "terminal.json"),
        "scheduled_arms": len(plan),
        "terminal_arm_records": len(arms),
        "failed_or_error_arms": sum(
            a["status"] == "FAILED" or "error" in a["status"] for a in arms.values()
        ),
        "budget_interrupted_arms": [
            key for key, a in arms.items() if "BATCH_" in (a["failure_reason"] or "")
        ],
        "unrecorded_arms": len(plan) - len(arms),
        "groups": groups,
        "eligible_pairwise_cost_quality_pattern": eligible_signal,
        "protocol_direction_signal": protocol_signal,
        "mechanism_eligible_independent_tasks": len(
            {(p["domain"], p["task_id"]) for p in eligible}
        ),
        "decision": (
            "KEEP_LAB_ONLY_EXPLORATORY_SIGNAL"
            if protocol_signal
            else "KEEP_SIMPLE_BENEFIT_NOT_ESTABLISHED"
        ),
        "general_benefit": "NOT_ESTABLISHED_ONE_INDEPENDENT_ELIGIBLE_TASK",
        "promotion": "NOT_ADMITTED",
        "observable_use": "UNKNOWN",
        "safety_scope": "No Product authority/write path; native container isolation retained. "
        "Not an independent safety evaluation.",
        "usage": usage,
        "actual_new_text_tokens": (
            None
            if usage["kinds"]["text"]["unknown_token_upper_bound"]
            else usage["kinds"]["text"]["reported_tokens"]
        ),
        "provider_reservations_not_dispatched": not_dispatched,
        "dispatch_accounting_note": "A Provider-local reservation can precede a refused budget "
        "admission. Only transport-admitted requests are outbound; uncertain admitted "
        "requests retain their known upper bound. No failed outbound request is refunded.",
        "shared_text_charged_tokens": shared_tokens,
        "shared_http_requests": shared_requests,
        "shared_preparation_seconds": inputs["preparation_seconds"],
        "batch_seconds_from_first_request": (
            terminal["ended_at_unix"] - usage["started_at_unix"]
            if usage["started_at_unix"]
            else None
        ),
        "historical_cache_cost": "SUNK_NOT_REMEASURED_NOT_A_FRESH_RETRIEVAL_SAVING",
        "historical_cost_receipts": historical_costs(inputs),
        "pairs": pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = analyze(args.root)
    with args.output.open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({k: v for k, v in value.items() if k != "pairs"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
