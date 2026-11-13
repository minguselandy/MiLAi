"""Bind continuous first answers to exact final inputs and original-source arrival cuts."""
from __future__ import annotations

import argparse
import copy
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from summarize_original_feedback_host import final_provider_input, position_bank


def source_identity(source: dict) -> tuple[str, str, str]:
    return source["session_id"], source["event_key"], source["role"]


def verify_arrived_sources(expected: list[dict], stored: list[dict],
                           declared_origins: set[str] | None = None) -> list[dict]:
    """Store presence proves availability, not that the Host actually received a source."""
    originals = {source_identity(s): s for s in expected}
    if len(originals) != len(expected):
        raise ValueError("Repeated original source identity in declared arrival prefix")
    origins = declared_origins if declared_origins is not None else {s["origin"] for s in expected}
    actual = {}
    for row in stored:
        if not row["namespace"] or row["namespace"][-1] != "v13_1_sources":
            continue
        value = row["value"]
        if value.get("origin") not in origins:
            continue
        identity = value["session"], value["capture_key"], value["role"]
        if identity in actual:
            raise ValueError("Repeated original source in actual final-input snapshot")
        actual[identity] = value
    if set(actual) != set(originals):
        raise ValueError("Actual source prefix contains missing or future original arrivals")
    bindings = []
    for identity, source in originals.items():
        value = actual[identity]
        if value["content"] != source["content"] or value["origin"] != source["origin"]:
            raise ValueError("Actual original source body or origin differs from declared source")
        bindings.append({"identity": list(identity), "source_ref": value["event_id"],
                         "source_revision": value["source_revision"]})
    return bindings


def public_messages(messages: list[dict]) -> list[dict]:
    return [{k: copy.deepcopy(v) for k, v in m.items()
             if k not in {"reasoning", "reasoning_content"}} for m in messages]


def bind_completed_context(result_path: Path, result: dict, closed_paths: list[str],
                           available: list[dict], declared_origins: set[str]) -> dict:
    boundary, messages = final_provider_input(result_path, result)
    if messages is None:
        return {"binding_status": "NO_BOUND_COMPLETED_CONTEXT", "final_input": boundary}
    candidates = []
    for name in closed_paths:
        path = Path(name)
        closed = read_json(path)
        if (closed.get("schema") != "closed_host_message_v1"
                or closed.get("status") != "CLOSED_INVOCATION_SNAPSHOTTED"):
            raise ValueError("Require an actual closed Host snapshot")
        context = closed.get("final_context")
        if (closed.get("final_context_status") == "BOUND_TO_COMPLETED_FINAL_GENERATION"
                and closed["message_status"] == result["status"] and context
                and context["output_message_id"] == boundary["final_message_id"]):
            candidates.append((path, closed))
    if len(candidates) != 1:
        return {"binding_status": "MISSING_OR_AMBIGUOUS_CLOSED_CONTEXT",
                "final_input": boundary, "matching_snapshots": len(candidates)}
    path, closed = candidates[0]
    if (closed["bank"] != result["bank"]
            or any(result[k] != v for k, v in closed["public_message"].items())
            or public_messages(messages) != closed["final_context"]["messages"]):
        raise ValueError("Closed snapshot differs from the actual completed final input")
    before = closed.get("pre_final_snapshot")
    if not before or before["status"] != "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE":
        return {"binding_status": "NO_PRE_FINAL_SOURCE_INVENTORY", "final_input": boundary}
    if before["output_message_id"] != boundary["final_message_id"]:
        raise ValueError("Source inventory belongs to another final response")
    inventory = path.parent / before["inventory"]
    bindings = verify_arrived_sources(available, read_json(inventory)["memory_store_values"],
                                      declared_origins)
    return {"binding_status": "BOUND_FINAL_INPUT_AND_VERIFIED_ORIGINAL_ARRIVAL_PREFIX",
        "final_input": boundary, "closed_snapshot": str(path),
        "source_inventory": str(inventory), "original_source_bindings": bindings,
        "actual_final_provider_messages": public_messages(messages),
        "scope": "Provider input bound by actual response ID; original source identity, role, "
                 "origin and full body checked against the pre-final Store. Source availability "
                 "is distinct from model visibility. Prior assistant assertions are not original "
                 "human reports, and derived Views are not automatically certified evidence."}


def prepare(fixture: dict, root: Path, profile: str, method: str) -> dict:
    if read_json(root / "fixture.json") != fixture:
        raise ValueError("Runtime fixture differs from declared common source/request history")
    driver = read_json(root / "driver.json")
    if driver["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES", "FAILED"}:
        raise ValueError("Use closed first runs, not a moving live prefix")
    if (not driver.get("continue_host_history") or driver.get("given_requests")
            or driver.get("native_probe")):
        raise ValueError("Require original autonomous continuous Host outcomes")
    positions = {}
    for row in driver["completed"]:
        if row.get("profile", row["policy"]) == profile:
            key = row["history"], row["request"]
            if key in positions:
                raise ValueError("Repeated first position in the selected profile")
            positions[key] = row
    results = {}
    for path in (root / profile / "banks").glob("*/*-result.json"):
        result = read_json(path)
        key = result["bank"], result["message_id"]
        if key in results:
            raise ValueError("Ambiguous persisted original result")
        results[key] = path, result
    packets, used = [], set()
    for history in fixture["histories"]:
        available = copy.deepcopy(history["sources"])
        origins = {s["origin"] for s in [*history["sources"],
            *(s for q in history["requests"] for s in q.get("incoming_sources", []))]}
        for request in history["requests"]:
            available.extend(copy.deepcopy(request.get("incoming_sources", [])))
            key = history["id"], request["id"]
            actual = positions.get(key)
            packet = {"method": method, "history": key[0], "request": key[1],
                "source_group": history["source_group"], "query": request["content"],
                "status": actual["status"] if actual else "NOT_EXECUTED",
                "answer": actual.get("answer") if actual else None,
                "declared_arrived_sources": copy.deepcopy(available),
                "binding_status": "NO_COMPLETED_FIRST_RESPONSE"}
            if actual is not None:
                used.add(key)
                result_path, result = results[position_bank(history, request), request["id"]]
                if (actual["status"] != result["status"]
                        or actual.get("answer") != result.get("final_answer")):
                    raise ValueError("First driver outcome differs from actual result")
                packet["result_path"] = str(result_path)
                packet.update(bind_completed_context(result_path, result,
                    actual.get("closed_host_snapshots", []), available, origins))
            packets.append(packet)
    if used != set(positions):
        raise ValueError("Actual position is outside the declared original history")
    return {"status": "CLOSED_FIRSTS_BOUND_FOR_SOURCE_REVIEW_NOT_YET_GRADED",
        "method": method, "root": str(root), "profile": profile, "positions": packets,
        "planned_positions": len(packets), "actual_positions": len(positions),
        "training_labels_allowed": False, "oracle_annotations_used": False,
        "model_calls": 0, "Host_calls": 0, "no_sha_validation": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run", nargs=3, required=True, metavar=("METHOD", "ROOT", "PROFILE"))
    args = parser.parse_args()
    t, cpu = time.perf_counter(), time.process_time()
    method, root, profile = args.run
    result = prepare(read_json(args.fixture), Path(root), profile, method)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "review-inputs.json", result)
    write_json(args.output / "manifest.json", {k: v for k, v in result.items() if k != "positions"}
        | {"compute": {"cpu_seconds": time.process_time() - cpu,
                       "wall_seconds": time.perf_counter() - t}})


if __name__ == "__main__":
    main()
