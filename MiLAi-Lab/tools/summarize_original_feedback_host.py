"""Reconcile autonomous Host arms, fixed task denominators and bound source reviews."""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from milai_lab.harness.artifact_io import read_json, read_jsonl


def budget_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def delta(a: dict[str, Any], z: dict[str, Any]) -> dict[str, Any]:
        return {key: z.get(key, 0) - a.get(key, 0) for key in a.keys() | z.keys()}

    return {
        "generation": delta(before["generation"], after["generation"]),
        "embedding": delta(before["embedding"], after["embedding"]),
        "generation_requests": after["generation_requests"] - before["generation_requests"],
        "compute": {
            key: delta(
                before.get("compute", {}).get(key, {}), after.get("compute", {}).get(key, {})
            )
            for key in before.get("compute", {}).keys() | after.get("compute", {}).keys()
        },
    }


def current_tools(result: dict[str, Any]) -> dict[str, int | None]:
    messages = result.get("messages", [])
    humans = [i for i, m in enumerate(messages) if m.get("type") == "human"]
    if not humans:
        return {"tool_attempts": None, "tool_returns": None, "tool_errors": None}
    current = messages[humans[-1] + 1 :]
    calls = [
        c
        for m in current
        if m["type"] == "ai"
        for c in m.get("tool_calls", [])
        if c["name"] == "milai_retrieve"
    ]
    receipts = [m for m in current if m["type"] == "tool" and m.get("name") == "milai_retrieve"]
    return {
        "tool_attempts": len(calls),
        "tool_returns": len(receipts),
        "tool_errors": sum(m.get("status") == "error" for m in receipts),
    }


def final_provider_input(
    result_path: Path,
    result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    """Bind actual final provider input by response ID; Store presence supplies no receipt."""
    missing = {"status": "NO_BOUND_COMPLETED_FINAL_INPUT"}
    messages = result.get("messages", [])
    if (
        result["status"] != "COMPLETED"
        or not messages
        or messages[-1]["type"] != "ai"
        or messages[-1].get("tool_calls")
        or "failure_delivery" in result
    ):
        return missing, None
    if "attempt" not in result:
        return {**missing, "reason": "actual_attempt_identity_unavailable"}, None
    stem = result_path.name.removesuffix(
        f"-attempt-{result['attempt']}.json").removesuffix("-result.json")
    trace = result_path.with_name(stem + f"-trace-{result['attempt']}.jsonl")
    if not trace.exists():
        return {**missing, "reason": "actual_trace_unavailable"}, None
    final_id = messages[-1]["id"]
    candidates = []
    for index, event in enumerate(read_jsonl(trace)):
        if event.get("event") == "vllm_response" and event["receipt"].get("id") == final_id:
            candidates.append((index, event))
    if len(candidates) != 1:
        return {**missing, "matching_provider_responses": len(candidates)}, None
    index, event = candidates[0]
    messages = copy.deepcopy(event["request"]["messages"])
    return {
        "status": "BOUND_TO_ACTUAL_COMPLETED_FINAL_PROVIDER_INPUT",
        "trace": str(trace),
        "trace_event_index": index,
        "final_message_id": final_id,
        "visible_retrieval_receipts": sum(
            m["role"] == "tool" and m.get("name") == "milai_retrieve" for m in messages),
    }, messages


def final_host_receipts(
    result_path: Path, result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    boundary, messages = final_provider_input(result_path, result)
    return boundary, ([m for m in messages if m["role"] == "tool"
                       and m.get("name") == "milai_retrieve"] if messages is not None else None)


def position_bank(history: dict[str, Any], request: dict[str, Any]) -> str:
    """Match the existing runner's continuous/independent bank identity exactly."""
    return (cast(str, history["id"])
            if history.get("continuous") and not request.get("independent")
            else cast(str, history["id"]) + "-" + cast(str, request["id"]))


def rendered_task(request: dict[str, Any], setup: dict[str, Any]) -> str:
    from milai_lab.runners.retrieval_histories import host_task_content

    return host_task_content(request, setup)


def visible_prefetches(
    requests: list[dict[str, Any]], setup: dict[str, Any],
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if messages is None:
        return None
    return [{"request": request["id"], "receipt": copy.deepcopy(setup["prefetch"])}
            for request in requests if request.get("provide_prefetch") and any(
                m["role"] == "user" and m["content"] == rendered_task(request, setup)
                for m in messages)]


def summarize(dispatch: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    study = dispatch["study"]
    if (
        len(dispatch["arms"]) != dispatch["unique_arms"]
        or dispatch["planned_positions"] != len(dispatch["arms"]) * study["positions_per_arm"]
    ):
        raise ValueError("Keep every declared unique arm and public-position denominator")
    fixture = read_json(Path(study["histories"]))
    reviewed = {(r["arm_id"], r["history"], r["request"]): r for r in reviews}
    if len(reviewed) != len(reviews):
        raise ValueError("Each actual public position has at most one source-authored review")
    used_reviews: set[tuple[str, str, str]] = set()
    rows, arms = [], []
    intervals = []
    for arm in dispatch["arms"]:
        root = Path(arm["output"])
        profile = arm["policy"] + "-rich"
        positions: dict[tuple[str, str], Any] = {}
        results: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}
        run: dict[str, Any] = {
            "arm_id": arm["id"],
            "aliases": arm["aliases"],
            "output": str(root),
            "status": "NOT_EXECUTED",
            "costs": None,
            "inference_audit": None,
            "inference_condition_status": "NOT_EXECUTED",
        }
        driver = None
        if (root / "driver.json").exists():
            driver = read_json(root / "driver.json")
            if driver["status"] == "RUNNING":
                raise ValueError("Close actual Host jobs before summary or ledger reconciliation")
            if (
                driver["source_version"] != study["source_version"]
                or driver["planned_positions"] != study["positions_per_arm"]
                or driver["native_probe"]
                or driver["given_requests"]
                or not driver["continue_host_history"]
                or read_json(root / "fixture.json") != fixture
            ):
                raise ValueError("Host run changed original conditions, tasks or autonomy")
            expected = read_json(Path(arm["config"]))
            settings = expected["entrypoints"]["functional"]
            settings["memory_control"]["policy"] = arm["policy"]
            settings["retrieval_tool"] = "rich"
            settings["config_version"] += "-" + profile
            if read_json(root / (profile + "-config.json")) != expected:
                raise ValueError("Actual Host runtime configuration differs from its bound arm")
            for p in driver["completed"]:
                key = p["history"], p["request"]
                if key in positions or p["policy"] != arm["policy"] or p["interface"] != "rich":
                    raise ValueError("Closed position duplicated or assigned to a different policy")
                positions[key] = p
            for path in (root / profile / "banks").glob("*/*-result.json"):
                result = read_json(path)
                key = result["bank"], result["message_id"]
                if key in results:
                    raise ValueError("Multiple final result artifacts name one public invocation")
                results[key] = path, result
            run.update(
                status=driver["status"],
                costs=budget_delta(
                    read_json(root / "budget-before.json"), read_json(root / "budget-after.json")
                ),
                driver_cpu_seconds_nested=driver["cpu_seconds"],
                inference_condition_status="AUDIT_UNAVAILABLE",
            )
            intervals.append((driver["started_epoch"], driver["finished_epoch"], arm["id"]))
        inference_path = Path(str(root) + "-inference.json")
        if inference_path.exists():
            inference = read_json(inference_path)
            if inference["status"] == "RUNNING":
                raise ValueError("Close the Host inference wrapper before summary")
            expected_module = Path(study["runtime"]) / "src/milai_lab/providers/laya_local.py"
            module = inference.get("native_decision_module_file")
            if (
                (module is not None and Path(module).resolve() != expected_module.resolve())
                or (module is None and inference["status"] != "FAILED_RETAINED")
                or any(m["status"] != "VERIFIED" for m in inference["model_loads"])
            ):
                raise ValueError("Actual scorer runtime or inference condition differs")
            if arm["policy"] == "laya" and any(
                Path(m["checkpoint"]).resolve() != Path(arm["checkpoint"]).resolve()
                for m in inference["model_loads"]
            ):
                raise ValueError("Actual Host scorer loaded another checkpoint")
            run["inference_audit"] = inference
            run["inference_condition_status"] = (
                ("VERIFIED_LOADED_SCORERS" if inference["model_loads"] else "NO_SCORER_LOADED")
                if inference["status"] == "COMPLETED"
                else "FAILED_ATTEMPT_INCOMPLETE_AUDIT"
            )
            if driver is None:
                run["status"] = "WRAPPER_" + inference["status"] + "_NO_NATIVE_DRIVER"
        actual_keys = set()
        actual_result_keys = set()
        for history in fixture["histories"]:
            available_by_bank: dict[str, list[dict[str, Any]]] = {}
            requests_by_bank: dict[str, list[dict[str, Any]]] = {}
            for request in history["requests"]:
                bank = position_bank(history, request)
                available = available_by_bank.setdefault(
                    bank, copy.deepcopy(request.get("sources", history["sources"])))
                available.extend(request.get("incoming_sources", []))
                prior_requests = requests_by_bank.setdefault(bank, [])
                prior_requests.append(request)
                key = history["id"], request["id"]
                actual_keys.add(key)
                actual_result_keys.add((bank, request["id"]))
                review_key = arm["id"], *key
                result_item = results.get((bank, request["id"]))
                recorded = positions.get(key)
                row: dict[str, Any] = {
                    "arm_id": arm["id"],
                    "history": history["id"],
                    "family": history["source_group"],
                    "request": request["id"],
                    "bank": bank,
                    "execution": "NOT_EXECUTED",
                    "result_status": None,
                    "result_path": None,
                    "answer": None,
                    "tool_attempts": None,
                    "tool_returns": None,
                    "tool_errors": None,
                    "semantic_grade": "unknown",
                    "delivery_grade": "unknown",
                    "final_host_input": {"status": "NO_ACTUAL_RESULT"},
                    "visible_prefetch_receipts": None,
                    "review": None,
                    "confirmed_task_success": False,
                }
                visible_receipts = None
                if result_item is not None:
                    path, result = result_item
                    setup = (read_json(path.parent / "retrieval-setup.json")
                             if any(q.get("provide_prefetch") for q in prior_requests) else {})
                    if result["content"] != rendered_task(request, setup):
                        raise ValueError("Actual public message differs from the declared task")
                    if recorded is not None and recorded["status"] != result["status"]:
                        raise ValueError("Driver closure differs from the actual public result")
                    row.update(
                        execution="RESULT_RETAINED"
                        if recorded is not None
                        else "RESULT_RETAINED_WITHOUT_DRIVER_COMPLETION",
                        result_status=result["status"],
                        result_path=str(path.resolve()),
                        answer=result.get("final_answer"),
                        **current_tools(result),
                    )
                    row["final_host_input"], wire = final_provider_input(path, result)
                    visible_receipts = ([m for m in wire if m["role"] == "tool"
                        and m.get("name") == "milai_retrieve"] if wire is not None else None)
                    row["visible_prefetch_receipts"] = visible_prefetches(
                        prior_requests, setup, wire)
                elif recorded is not None:
                    row.update(
                        execution="DRIVER_COMPLETED_RESULT_MISSING",
                        result_status=recorded["status"],
                    )
                elif (
                    driver is not None
                    and driver.get("active") is not None
                    and all(
                        driver["active"][k] == v
                        for k, v in {"history": history["id"], "request": request["id"]}.items()
                    )
                ):
                    row["execution"] = "ENTERED_WITHOUT_RETAINED_RESULT"
                if review_key in reviewed:
                    review = reviewed[review_key]
                    delivery = review.get("delivery", {"grade": "unknown"})
                    if (
                        row["result_path"] is None
                        or Path(review["result_path"]).resolve() != Path(row["result_path"])
                        or review["answer"] != row["answer"]
                        or review["grade"] not in {"correct", "partial", "incorrect", "unknown"}
                    ):
                        raise ValueError("Review must bind this exact actual result/answer")
                    if delivery["grade"] not in {
                        "sufficient",
                        "partial",
                        "insufficient",
                        "unknown",
                    }:
                        raise ValueError("Delivery support uses its own declared grade")
                    if delivery["grade"] != "unknown" and (
                        visible_receipts is None
                        or not delivery["rationale"]
                        or delivery["visible_tool_receipts"] != visible_receipts
                    ):
                        raise ValueError(
                            "Delivery review must bind all actual final-input Tool receipts"
                        )
                    if (delivery["grade"] != "unknown"
                            and delivery.get("visible_prefetch_receipts", [])
                            != row["visible_prefetch_receipts"]):
                        raise ValueError(
                            "Delivery review must bind actual final-input prefetch receipts")
                    identities = {(x["session_id"], x["event_key"], x["role"]) for x in available}
                    if (review["grade"] != "unknown" or delivery["grade"] != "unknown") and (
                        not review["rationale"]
                        or not review["source_refs"]
                        or any(tuple(ref) not in identities for ref in review["source_refs"])
                    ):
                        raise ValueError(
                            "Known semantic grades need source evidence available at this prefix"
                        )
                    used_reviews.add(review_key)
                    row.update(
                        semantic_grade=review["grade"],
                        delivery_grade=delivery["grade"],
                        review=copy.deepcopy(review),
                        confirmed_task_success=(
                            row["result_status"] == "COMPLETED" and review["grade"] == "correct"
                        ),
                    )
                rows.append(row)
        if set(positions) - actual_keys or set(results) - actual_result_keys:
            raise ValueError("Run contains a position outside the fixed public denominator")
        own = [r for r in rows if r["arm_id"] == arm["id"]]
        run.update(
            planned_positions=len(own),
            execution_counts=dict(Counter(r["execution"] for r in own)),
            semantic_counts=dict(Counter(r["semantic_grade"] for r in own)),
            delivery_counts=dict(Counter(r["delivery_grade"] for r in own)),
            completed=sum(r["result_status"] == "COMPLETED" for r in own),
            zero_call_results=sum(r["tool_attempts"] == 0 for r in own),
            tool_count_unknown=sum(r["tool_attempts"] is None for r in own),
            confirmed_task_successes=sum(r["confirmed_task_success"] for r in own),
        )
        arms.append(run)
    if set(reviewed) != used_reviews:
        raise ValueError("A source review names an undeclared or unexecuted public position")
    intervals.sort()
    if any(a[1] > z[0] for a, z in pairwise(intervals)):
        raise ValueError("Overlapping Host jobs cannot supply disjoint shared-ledger costs")
    return {
        "status": "AUTONOMOUS_HOST_DENOMINATORS_AND_BOUND_REVIEWS_RECONCILED",
        "arms": arms,
        "positions": rows,
        "planned_positions": len(rows),
        "semantic_scope": "Author judgments bind actual answers; cited prefix identities "
        "are checked mechanically, semantic sufficiency is not automatically certified. Unknown "
        "and unexecuted positions remain unknown, never inferred incorrect or correct. Answer/task "
        "success does not certify delivery support or Host knowledge. Delivery grades separately "
        "bind all actual final-provider-input Tool receipts; Store presence is not visibility.",
        "cost_scope": "Each closed arm's shared-ledger delta counted once. Message/HTTP/driver and "
        "wrapper totals are nested; do not add them. Missing costs remain unavailable. "
        "This analyzer does not settle CPU or write an operational ledger.",
        "aliases_scope": "Identical checkpoint aliases share one actual trajectory and are not "
        "additional independent samples.",
        "exposure": study["exposure"],
        "model_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    cpu = time.process_time()
    reviews = read_json(args.reviews)["reviews"] if args.reviews is not None else []
    result = summarize(read_json(args.dispatch), reviews)
    result.update(
        cpu_seconds_pending=time.process_time() - cpu, ledger_recorded=False, no_sha_validation=True
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(result["status"])


if __name__ == "__main__":
    main()
