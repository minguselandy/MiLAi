"""Finite V0214 public-MCP/real-PG acceptance and same-condition read baseline; no models."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from check_v0210_control import LAB, write
from run_v0212_horizon import product
from v0210_v05_product import observer


def latency_summary(events: list[dict]) -> dict:
    """Nearest-rank quantiles; overlapping wall span, not sum of request durations."""
    if not events:
        return {"count": 0, "p50_seconds": None, "p95_seconds": None,
                "p99_seconds": None, "throughput_per_second": None}
    samples = sorted(event["end"] - event["start"] for event in events)
    elapsed = max(event["end"] for event in events) - min(event["start"] for event in events)
    return {"count": len(samples), "wall_seconds": elapsed,
            **{f"p{p}_seconds": samples[math.ceil(len(samples) * p / 100) - 1]
               for p in (50, 95, 99)},
            "throughput_per_second": len(samples) / elapsed if elapsed else None,
            "errors": sum(bool(event.get("result", {}).get("mcp_error") or event.get("error"))
                          for event in events)}


def verify_cas(outcomes: list[dict], head: dict) -> dict:
    winners = [item for item in outcomes if not item.get("mcp_error")]
    losers = [item for item in outcomes if item.get("mcp_error")]
    assert len(winners) == len(losers) == 1
    assert "STALE_WORKING_STATE" in json.dumps(losers[0])
    assert head["version"] == winners[0]["version"] == 2
    assert head["payload"] == winners[0]["payload"]
    return {"status": "PASS", "winners": 1, "stale_losers": 1, "head_version": 2}


def peak_overlap(events: list[dict]) -> int:
    active = peak = 0
    for _, change in sorted([(e["start"], 1) for e in events]
                            + [(e["end"], -1) for e in events]):
        active += change
        peak = max(peak, active)
    return peak


def check(root: Path, owned: Path, *, repeats: int, burst: int) -> dict:
    events: list[dict] = []
    event_lock = threading.Lock()
    token = uuid4().hex
    bindings = {arm: {"principal": f"v0214-{token}-{arm}",
                      "project": f"v0214-{token}-{arm}", "task": f"task-{arm}"}
                for arm in ("a", "b")}
    markers = {arm: f"V0214_PRIVATE_{token}_{arm}" for arm in bindings}
    notes, states, calls = {}, {}, {}
    report = {"status": "RUNNING", "model_requests": 0, "raw_tokens": 0,
              "business_actions_executed": 0, "checks": {}}

    def recorded(arm, phase, tool, arguments, *, public=None, binding=None):
        event = {"request_id": uuid4().hex, "arm": arm, "phase": phase, "tool": tool,
                 "binding": binding or bindings[arm], "arguments": arguments,
                 "start": time.monotonic()}
        try:
            event["result"] = (public or calls[arm])(tool, arguments)
            return event["result"]
        except Exception as exc:
            event["error"] = type(exc).__name__
            raise
        finally:
            event["end"] = time.monotonic()
            with event_lock:
                events.append(event)
                write(root / "public-events.json", events)

    with ExitStack() as stack:
        for arm, binding in bindings.items():
            calls[arm] = stack.enter_context(observer(owned, root / f"mcp-{arm}", **binding))
            catalog = recorded(arm, "catalog", None, {})
            expected = json.loads((LAB.parent / "MiLAi-Product/contracts/mcp/"
                "compact-memory-v1.release-0.1.15.tools.json").read_text())
            assert {row["name"]: row["inputSchema"] for row in catalog["tools"]["tools"]} == {
                row["name"]: row["inputSchema"] for row in
                expected["catalogs"]["compact-memory-v1"]["tools"]}
            before = recorded(arm, "initial-absent", "milai_working_state_get", {"scope": "TASK"})
            assert before["status"] == "ABSENT"
            notes[arm] = recorded(arm, "seed-note", "milai_memory_save", {
                "content": markers[arm], "operation_id": f"seed-note-{arm}",
                "options": {"action": "ADD_NOTE"}})
            states[arm] = recorded(arm, "seed-state", "milai_working_state_update", {
                "scope": "TASK", "expected_version": 0, "operation_id": f"seed-state-{arm}",
                "payload": {"marker": markers[arm]}})
            assert states[arm]["version"] == 1
            assert not notes[arm].get("mcp_error")
        write(root / "bindings.json", bindings)

        # Baseline and repeat use the exact same public path, scope, corpus and concurrency.
        # This is a service baseline, not a claim about candidate helper latency.
        rounds = {}
        for phase in ("baseline", "repeat"):
            def reader(arm, phase=phase):
                for _ in range(repeats):
                    for tool, args in (
                        ("milai_memory_read", {"target": {"kind": "NOTE", "id": notes[arm][
                            "memory_id"]}}),
                        ("milai_memory_search", {"query": markers[arm],
                                                 "note_query": markers[arm]}),
                    ):
                        result = recorded(arm, phase, tool, args)
                        text = json.dumps(result)
                        assert not result.get("mcp_error") and markers[arm] in text
                        assert all(marker not in text for other, marker in markers.items()
                                   if other != arm)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(reader, bindings))
            selected = [e for e in events if e["phase"] == phase]
            rounds[phase] = {tool: latency_summary([e for e in selected if e["tool"] == tool])
                             for tool in ("milai_memory_read", "milai_memory_search")}
            rounds[phase]["peak_client_inflight"] = peak_overlap(selected)
            if phase == "baseline":
                write(root / "performance-comparison-frozen.json", {
                    "baseline": rounds[phase], "allowed_p95_ratio": 2.0,
                    "same_conditions": True, "candidate_helper_measured": False,
                    "scope": "LOCAL_SERVICE_REPEATABILITY_ONLY_NOT_PRODUCTION_SLO"})
        report["performance"] = rounds
        report["performance_repeatability"] = {tool: {
            "p95_ratio": rounds["repeat"][tool]["p95_seconds"] / rounds["baseline"][tool][
                "p95_seconds"],
            "within_frozen_ratio": rounds["repeat"][tool]["p95_seconds"] <= 2 * rounds[
                "baseline"][tool]["p95_seconds"]}
            for tool in ("milai_memory_read", "milai_memory_search")}
        report["internal_timing"] = {"database_connection_wait": None, "server_queue_wait": None,
            "reason": "Not exposed by this pinned compact public MCP response; not assumed zero.",
            "latency_scope": "Client-observed complete MCP HTTP session plus tool roundtrip"}
        assert rounds["baseline"]["peak_client_inflight"] >= 2
        report["checks"]["T25_concurrent_users"] = "PASS_SCOPED_RESULTS_AND_OVERLAPPING_REQUESTS"
        report["server_global_lock_proof"] = (
            "No new server lock introduced by Lab-only code; client overlap alone "
            "does not prove SQL-level parallel execution.")

        for arm, other in (("a", "b"), ("b", "a")):
            denied = recorded(arm, "cross-principal", "milai_memory_read", {
                "target": {"kind": "NOTE", "id": notes[other]["memory_id"]}})
            assert denied.get("mcp_error") and markers[other] not in json.dumps(denied)
        # Vary exactly one part of the binding; no seed is created in these three scopes.
        for field in ("principal", "project", "task"):
            changed = {**bindings["a"], field: bindings["a"][field] + "-isolated"}
            with observer(owned, root / f"isolation-{field}", **changed) as public:
                result = recorded("a", f"isolation-{field}", "milai_working_state_get",
                                  {"scope": "TASK"}, public=public, binding=changed)
                assert result["status"] == "ABSENT" and markers["a"] not in json.dumps(result)
                write(root / f"isolation-{field}.json", {"binding": changed, "result": result})
        report["checks"]["T01_T25_binding_isolation"] = "PASS_PRINCIPAL_PROJECT_TASK"

        barrier = threading.Barrier(2)
        def writer(index):
            barrier.wait(timeout=10)
            return recorded("a", "cas-race", "milai_working_state_update", {
                "scope": "TASK", "state_id": states["a"]["state_id"], "expected_version": 1,
                "operation_id": f"race-{index}", "payload": {"writer": index}})
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, range(2)))
        head = recorded("a", "cas-head", "milai_working_state_get", {"scope": "TASK"})
        report["checks"]["T24_two_writers"] = verify_cas(outcomes, head)

        # Capacity stress is read-only. An error is counted, never silently retried.
        # Independent MCP processes avoid mistaking one entrypoint's scheduling queue
        # for concurrent admission at the shared Runtime/PG boundary.
        stress_calls = [(arm, calls[arm]) for arm in bindings]
        for index in range(6):
            arm = "a" if index % 2 == 0 else "b"
            public = stack.enter_context(observer(
                owned, root / f"stress-mcp-{index}", **bindings[arm]))
            stress_calls.append((arm, public))
        start_burst = threading.Barrier(burst)
        def overloaded(index):
            arm, public = stress_calls[index % len(stress_calls)]
            start_burst.wait(timeout=15)
            try:
                return recorded(arm, "overload", "milai_memory_search", {
                    "query": markers[arm], "note_query": markers[arm]}, public=public)
            except Exception as exc:
                return {"transport_error": type(exc).__name__}
        with ThreadPoolExecutor(max_workers=burst) as pool:
            responses = list(pool.map(overloaded, range(burst)))
        stress = [e for e in events if e["phase"] == "overload"]
        rejection_text = json.dumps(responses)
        capacity_rejections = sum("DATABASE_BUSY" in json.dumps(row) or "capacity" in
                                  json.dumps(row).lower() for row in responses)
        report["checks"]["T26_overload"] = {
            "status": "PASS" if capacity_rejections else "CAPACITY_NOT_REACHED",
            "capacity_rejections": capacity_rejections,
            "independent_mcp_entrypoints": len(stress_calls),
            "all_finished_within_30s": max(e["end"] - e["start"] for e in stress) < 30,
            "requests": burst, "latency": latency_summary(stress),
            "error_outcomes": [row for row in responses if row.get("mcp_error")
                               or row.get("transport_error")]}
        assert report["checks"]["T26_overload"]["all_finished_within_30s"]
        assert "Bearer " not in rejection_text

        # Deleting only this check's owned synthetic note leaves append-only evidence retained.
        deleted = recorded("a", "delete-note", "milai_memory_delete", {
            "operation_id": "delete-own-note", "target": {"kind": "NOTE", "id": notes["a"][
                "memory_id"], "expected_version": 1, "confirmation": "DELETE"}})
        assert not deleted.get("mcp_error")
        denied = recorded("a", "after-delete", "milai_memory_read", {
            "target": {"kind": "NOTE", "id": notes["a"]["memory_id"]}})
        assert markers["a"] not in json.dumps(denied)
        captured = recorded("b", "capture-dependency", "milai_memory_save", {
            "content": "Synthetic dependency for V0214 revocation check.",
            "operation_id": "capture-dependency", "options": {"action": "CAPTURE_EVIDENCE",
                "source_type": "DOCUMENT", "source_ref": f"synthetic:{token}",
                "subject_id": token, "observed_at": datetime.now(UTC).isoformat(),
                "confirmation": "CAPTURE"}})
        evidence_id = captured["evidence_id"]
        saved = recorded("b", "save-dependent-state", "milai_working_state_update", {
            "scope": "TASK", "state_id": states["b"]["state_id"], "expected_version": 1,
            "operation_id": "dependent-state", "payload": {"marker": markers["b"],
                "evidence_refs": [evidence_id]}})
        assert saved["payload"]
        revoked = recorded("b", "revoke-dependency", "milai_memory_delete", {
            "operation_id": "revoke-dependency", "target": {"kind": "EVIDENCE",
                "id": evidence_id, "reason_code": "PERMISSION_REVOKED", "confirmation": "REVOKE"}})
        assert not revoked.get("mcp_error")
        after = recorded("b", "after-revoke", "milai_working_state_get", {"scope": "TASK"})
        assert after["payload"] == {} and after["payload_withheld"] and after["warnings"]
        assert markers["b"] not in json.dumps(after)
        report["checks"]["T06_delete_and_revocation"] = "PASS_BODY_WITHHELD_AFTER_ACK"
        report["deleted_material"] = (
            "One owned synthetic Note soft-deleted; one owned synthetic Evidence revoked. "
            "Audit/history and volumes retained; not represented as undoable revocation.")

    # Old MCP processes have exited. This session inherits binding, not old messages.
    started = time.monotonic()
    with observer(owned, root / "cold-mcp", **bindings["a"]) as public:
        restored = recorded("a", "cold-restored", "milai_working_state_get",
                            {"scope": "TASK"}, public=public)
        assert restored["payload"] == head["payload"] and restored["version"] == 2
        write(root / "cold-restored.json", restored)
    report["cold_mcp_resume_seconds"] = time.monotonic() - started
    report["cold_scope"] = "NEW_MCP_PROCESS_AND_SESSION_NOT_FULL_HOST_MODEL_E2E"
    report["checks"]["T27_no_auth_secret_in_public_ledger"] = not any(
        value in json.dumps(events) for value in ("Bearer ", "MILAI_CODEX_TOKEN"))
    assert report["checks"]["T27_no_auth_secret_in_public_ledger"]
    report["public_calls"] = len(events)
    report["status"] = ("PASS" if report["checks"]["T26_overload"]["status"] == "PASS"
                        else "PASS_EXCEPT_UNREACHED_CAPACITY")
    return report


def run(root: Path, installed: Path, *, repeats: int = 12, burst: int = 64) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    settings = {"MILAI_DATABASE_POOL_MAX_SIZE": "2", "MILAI_DATABASE_POOL_MAX_WAITING": "1",
                "MILAI_DATABASE_CONNECT_TIMEOUT_SECONDS": "0.25", "MILAI_API_THREADS": "32"}
    write(root / "allocation.json", {"repeats_each_tool_each_user": repeats,
        "baseline_users": 2, "overload_burst": burst, "overload_mcp_processes": 8,
        "runtime_overrides": settings,
        "model_requests": 0, "external_business_actions": 0,
        "read_p95_repeat_ratio_frozen_after_baseline": 2.0,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_product_runner_sha256": hashlib.sha256((LAB / "tools/run_v0212_horizon.py").
                                                       read_bytes()).hexdigest()})
    try:
        with product(root / "product", installed, runtime_overrides=settings) as owned:
            result = check(root, owned, repeats=repeats, burst=burst)
    except Exception as exc:
        write(root / "failure.json", {"error": type(exc).__name__, "message": str(exc),
                                      "model_requests": 0})
        raise
    result["cleanup"] = json.loads((root / "product/cleanup.json").read_text())
    assert result["cleanup"]["api_stopped"] and result["cleanup"]["compose_stop_returncode"] == 0
    write(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--burst", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.installed.resolve(),
                         repeats=args.repeats, burst=args.burst)))
