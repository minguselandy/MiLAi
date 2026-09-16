"""Finite real public-MCP read/CAS/revocation/crash composition; no model or SQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_durable_save import stop_process
from check_v02_e2e_live import capture
from run_v02_local_vllm import stop_owned
from v02_low_cost_public import observer

CONFIG = base.LAB / "configs/v02-concurrent-faults.json"


def verify_reads(events: list[dict], markers: dict[str, str], revoke_end: float) -> dict:
    counts = {arm: {"during": 0, "post_ack": 0} for arm in markers}
    for event in events:
        if event["phase"] not in {"read-during", "read-after-revoke"}:
            continue
        arm, value = event["arm"], event["value"]
        assert not value.get("mcp_error")
        text = json.dumps(value, ensure_ascii=False)
        assert all(marker not in text for other, marker in markers.items() if other != arm)
        counts[arm]["during"] += event["phase"] == "read-during"
        if event["start"] >= revoke_end:
            counts[arm]["post_ack"] += 1
            if arm == "a":
                assert value["payload"] == {} and value["payload_withheld"]
                assert markers[arm] not in text
        if arm == "b":
            assert value["payload"]["first"] == markers[arm]
            assert value["payload"]["last"] == markers[arm]
            assert value["version"] in {1, 2}
    assert all(counts[a]["during"] > 0 and counts[a]["post_ack"] >= 4 for a in markers)
    return counts


def run(root: Path, config_path: Path = CONFIG) -> dict:
    config = base.read_json(config_path)
    assert not config["model_transport_enabled"] and config["readers"] == 2
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(root / "config.json", config)
    base.write_json(
        root / "preflight.json",
        {
            "pin": base.pin(config_path),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "clock": time.get_clock_info("monotonic").implementation,
        },
    )
    service = root / (root.name + "-product")
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[: config["runtime_cpu_affinity_count"]])
    events, markers, branches = [], {}, {}
    report = {"status": "RUNNING", "model_calls": 0, "checks": {}}
    started, group = time.monotonic(), None
    event_lock = threading.Lock()

    def observed(call, arm, phase, tool, args):
        event = {"arm": arm, "phase": phase, "tool": tool, "start": time.monotonic()}
        try:
            value = call(tool, args)
            event["value"] = value
            return value
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["end"] = time.monotonic()
            with event_lock:
                events.append(event)
                base.write_json(root / "public-events.json", events)

    try:
        base.prepare(
            service,
            config_path=config_path,
            compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
            runtime_overrides={
                "MILAI_DATA_MODE": config["data_mode"],
                "MILAI_API_THREADS": str(config["api_threads"]),
                "MILAI_DATABASE_POOL_MAX_SIZE": str(config["database_pool_max_size"]),
                "MILAI_DATABASE_POOL_MAX_WAITING": str(config["database_pool_max_waiting"]),
                **({"MILAI_DATABASE_POOL_MAX_PER_TENANT": str(
                    config["database_pool_max_per_tenant"])}
                   if config.get("database_pool_max_per_tenant") is not None else {}),
            },
        )
        env = base._load_environment(service / "runtime.env")
        report["worker_stop"] = stop_process(service, "worker", signal.SIGKILL)
        with ExitStack() as stack:
            calls = {}
            for arm in ("a", "b"):
                directory = root / ("live-" + arm)
                directory.mkdir()
                project = root.name + "-" + arm
                markers[arm] = "CONCURRENT_PRIVATE_" + arm + "_c73e19"
                call, _ = stack.enter_context(observer(service, directory, project, project))
                calls[arm] = call
                cap = capture(call, project, markers[arm])
                request = {
                    "scope": "TASK",
                    "expected_version": 0,
                    "operation_id": "initial-" + arm,
                    "payload": {
                        "first": markers[arm],
                        "text": " 空白\r\n\t" * 50,
                        "last": markers[arm],
                        "evidence_refs": [cap["evidence_id"]],
                    },
                }
                receipt = observed(call, arm, "seed", "milai_working_state_update", request)
                assert receipt["version"] == 1 and receipt["payload"] == request["payload"]
                branches[arm] = {
                    "project": project,
                    "evidence_id": cap["evidence_id"],
                    "request": request,
                    "receipt": receipt,
                }
            base.write_json(root / "branches.json", branches)
            ready = {arm: threading.Event() for arm in calls}
            gate = threading.Barrier(3)

            def reader(arm):
                gate.wait(timeout=10)
                for i in range(config["reads_during_mutation_each"]):
                    observed(
                        calls[arm], arm, "read-during", "milai_working_state_get", {"scope": "TASK"}
                    )
                    if i == 0:
                        ready[arm].set()

            with ThreadPoolExecutor(max_workers=4) as executor:
                readers = [executor.submit(reader, arm) for arm in calls]
                gate.wait(timeout=10)
                assert all(event.wait(timeout=10) for event in ready.values())
                race = threading.Barrier(2)

                def writer(index):
                    race.wait(timeout=10)
                    request = {
                        **branches["b"]["request"],
                        "expected_version": 1,
                        "state_id": branches["b"]["receipt"]["state_id"],
                        "operation_id": "race-" + str(index),
                        "payload": {**branches["b"]["request"]["payload"], "revision": index},
                    }
                    return request, observed(
                        calls["b"], "b", "cas-race", "milai_working_state_update", request
                    )

                writes = [executor.submit(writer, i) for i in range(2)]
                outcomes = [f.result(timeout=15) for f in writes]
                winners = [(q, v) for q, v in outcomes if not v.get("mcp_error")]
                losers = [v for _, v in outcomes if v.get("mcp_error")]
                assert len(winners) == len(losers) == 1
                assert winners[0][1]["version"] == 2
                assert "STALE_WORKING_STATE" in json.dumps(losers[0])
                report["checks"]["distinct_operation_cas_single_winner"] = True
                branches["b"]["winner_request"], branches["b"]["winner_receipt"] = winners[0]
                revoked = observed(
                    calls["a"],
                    "a",
                    "revoke",
                    "milai_evidence_revoke",
                    {
                        "evidence_id": branches["a"]["evidence_id"],
                        "operation_id": "revoke-a",
                        "reason_code": "USER_REQUEST",
                        "confirmation": "REVOKE",
                    },
                )
                assert not revoked.get("mcp_error")
                revoke_end = next(e["end"] for e in events if e["phase"] == "revoke")
                for future in readers:
                    future.result(timeout=30)
            read_events = [e for e in events if e["phase"] == "read-during"]
            mutation_events = [e for e in events if e["phase"] in {"cas-race", "revoke"}]
            overlap = sum(
                r["start"] < w["end"] and w["start"] < r["end"]
                for r in read_events
                for w in mutation_events
            )
            assert overlap > 0
            report["checks"]["public_request_overlap_pairs"] = overlap
            for arm in calls:
                for _ in range(config["reads_after_revoke_each"]):
                    observed(
                        calls[arm],
                        arm,
                        "read-after-revoke",
                        "milai_working_state_get",
                        {"scope": "TASK"},
                    )
            report["checks"]["read_isolation_and_post_revoke"] = verify_reads(
                events, markers, revoke_end
            )
            replay = observed(
                calls["a"],
                "a",
                "revoked-replay",
                "milai_working_state_update",
                branches["a"]["request"],
            )
            assert replay["replayed"] and replay["payload"] == {} and replay["payload_withheld"]
            report["api_stop"] = stop_process(service, "api", signal.SIGKILL)
            for arm in calls:
                failed = observed(
                    calls[arm], arm, "api-down", "milai_working_state_get", {"scope": "TASK"}
                )
                assert failed.get("mcp_error")
                assert all(marker not in json.dumps(failed) for marker in markers.values())
            report["checks"]["api_down_no_cached_payload"] = True
        # Both old MCP processes have ended. Restart only run-owned API/worker.
        group = base.ProcessGroup(service)
        api = group.start(
            "api", [str(base.API_EXE)], cwd=base.RUNTIME, env=base._clean_environment(env)
        )
        worker = group.start(
            "worker", [str(base.WORKER_EXE)], cwd=base.RUNTIME, env=base._clean_environment(env)
        )
        base.write_json(service / "services.json", {"api": api.pid, "worker": worker.pid})
        base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        assert api.pid != report["api_stop"]["pid"] and worker.pid != report["worker_stop"]["pid"]
        for arm, branch in branches.items():
            directory = root / ("cold-" + arm)
            directory.mkdir()
            with observer(service, directory, branch["project"], branch["project"]) as (call, _):
                value = observed(
                    call, arm, "cold-get", "milai_working_state_get", {"scope": "TASK"}
                )
                expected = branch.get("winner_receipt", branch["receipt"])
                assert value["state_version_id"] == expected["state_version_id"]
                if arm == "a":
                    assert value["payload"] == {} and value["payload_withheld"]
                    assert markers[arm] not in json.dumps(value)
                else:
                    assert value["payload"] == expected["payload"]
                    replay = observed(
                        call,
                        arm,
                        "cold-replay",
                        "milai_working_state_update",
                        branch["winner_request"],
                    )
                    assert (
                        replay["replayed"]
                        and replay["state_version_id"] == expected["state_version_id"]
                    )
            report["checks"]["cold_" + arm] = True
        report["status"] = "CONCURRENT_FAULT_COMPOSITION_VERIFIED_NOT_FULL_D3"
    except Exception as exc:
        report.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        base.write_json(root / "branches.json", branches)
        if service.exists():
            report["cleanup"] = stop_owned(service)
        if group is not None:
            group.stop()
        os.sched_setaffinity(0, affinity)
        report["seconds"] = time.monotonic() - started
        base.write_json(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.config.resolve())))
