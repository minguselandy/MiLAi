"""Bounded public SDK/MCP calibration worker, run with the pinned MCP interpreter."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clock_identity() -> dict:
    return {
        "boot_id_sha256": hashlib.sha256(
            Path("/proc/sys/kernel/random/boot_id").read_bytes()
        ).hexdigest(),
        "time_namespace": os.readlink("/proc/self/ns/time"),
        "clock": time.get_clock_info("monotonic").implementation,
    }


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def request_fingerprint(value: dict) -> str | None:
    request_id = value.get("request_id")
    return (
        hashlib.sha256(request_id.encode()).hexdigest()[:16]
        if isinstance(request_id, str)
        else None
    )


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return (
        {
            "n": len(values),
            **{f"p{p}_ms": ordered[math.ceil(len(ordered) * p / 100) - 1] for p in (50, 95, 99)},
        }
        if ordered
        else {"n": 0}
    )


async def compare_mcp_mode(root: Path, url: str, token: str, mode: str, seed: bool) -> dict:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    config = json.loads((root / "config.json").read_text())
    events: list[dict] = []
    phases: list[dict] = []
    receipts_path = root / "mcp-shared-receipts.json"
    receipts = {} if seed else json.loads(receipts_path.read_text())
    scopes = ("TASK", "SESSION", "PROJECT")
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
        async with Client(
            streamable_http_client(url, http_client=http), mode=config["mcp_protocol_mode"]
        ) as client:
            catalog = await client.list_tools()
            write(root / f"mcp-{mode}-catalog.json", catalog.model_dump(mode="json"))

            async def call(tool, args, phase):
                start = time.monotonic()
                event = {"phase": phase, "tool": tool, "scope": args["scope"], "start": start}
                events.append(event)
                try:
                    result = await asyncio.wait_for(
                        client.call_tool(tool, args), config["request_timeout_seconds"]
                    )
                    assert not result.is_error
                    value = result.structured_content
                    assert isinstance(value, dict)
                    event.update(
                        status="COMPLETED",
                        response_sha256=digest(value),
                        runtime_request_id_fingerprint=request_fingerprint(value),
                    )
                    return value
                except BaseException as exc:
                    event.update(status="FAILED_OR_CANCELLED", error_type=type(exc).__name__)
                    raise
                finally:
                    event["elapsed_ms"] = (time.monotonic() - start) * 1000

            try:
                if seed:
                    for scope, size in zip(scopes, config["payload_text_bytes"], strict=True):
                        receipts[scope] = await call(
                            "milai_working_state_update",
                            {
                                "scope": scope,
                                "operation_id": "compare-" + scope,
                                "expected_version": 0,
                                "payload": {"scope": scope, "text": "x" * size},
                            },
                            "seed",
                        )
                        assert receipts[scope]["version"] == 1
                    write(receipts_path, receipts)
                for scope in scopes:
                    value = await call("milai_working_state_get", {"scope": scope}, "warmup")
                    assert value["state_version_id"] == receipts[scope]["state_version_id"]
                    assert value["payload"] == receipts[scope]["payload"]

                for concurrency in config["read_concurrency"]:
                    for repeat in range(config["rounds"]):
                        label = f"c{concurrency}-r{repeat}"
                        indices = iter(range(config["reads_per_round"]))
                        start = time.monotonic()

                        async def reader(indices=indices, label=label):
                            for index in indices:
                                scope = scopes[index % len(scopes)]
                                value = await call(
                                    "milai_working_state_get", {"scope": scope}, label
                                )
                                assert (
                                    value["state_version_id"] == receipts[scope]["state_version_id"]
                                )
                                assert value["payload"] == receipts[scope]["payload"]

                        async with asyncio.TaskGroup() as group:
                            for _ in range(concurrency):
                                group.create_task(reader())
                        selected = [e for e in events if e["phase"] == label]
                        phases.append(
                            {
                                "name": label,
                                "concurrency": concurrency,
                                "client_latency": distribution([e["elapsed_ms"] for e in selected]),
                                "completed_per_second": len(selected) / (time.monotonic() - start),
                            }
                        )
                report = {
                    "status": "MODE_COMPLETED",
                    "mode": mode,
                    "phases": phases,
                    "tool_calls": len(events),
                    "same_state_versions_verified": True,
                }
                write(root / f"mcp-{mode}-result.json", report)
                return report
            finally:
                write(root / f"mcp-{mode}-events.json", events)


async def calibrate(root: Path) -> dict:
    # Public SDK only; no Product application/persistence imports or SQL access.
    from milai_client import AsyncMilaiClient, ConflictError, HttpxAsyncTransport

    config = json.loads((root / "config.json").read_text())
    assert config["model_transport_enabled"] is False
    events: list[dict] = []
    physical: list[dict] = []
    started = time.monotonic()

    class ObservedTransport(HttpxAsyncTransport):
        async def send(self, method, path, data, headers):
            begin = time.monotonic()
            event = {"path": path, "start_s": begin - started}
            try:
                response = await super().send(method, path, data, headers)
                event["status"] = response.status
                return response
            except BaseException as exc:
                event["error_type"] = type(exc).__name__
                raise
            finally:
                event["end_s"] = time.monotonic() - started
                physical.append(event)

    client = AsyncMilaiClient(
        token=os.environ["MILAI_AGENT_SUBMITTER_TOKEN"],
        base_url=os.environ["MILAI_BASE_URL"],
        max_retries=config["max_retries"],
        transport=ObservedTransport(
            os.environ["MILAI_BASE_URL"], config["request_timeout_seconds"]
        ),
    )
    report: dict = {
        "status": "RUNNING",
        "new_model_requests": 0,
        "seeded": 0,
        "phases": [],
        "service_slo": "NOT_BENCHMARKED_AT_GATEWAY_BOUNDARY",
        "coverage": "TWO_HOST_BINDINGS_ONE_RUNTIME_ACTOR_AND_TENANT",
        "search_and_index": "NOT_TESTED_WORKING_STATE_INDEX_NA",
        "server_queue_and_pool_wait": None,
    }
    bindings = [
        {
            "principal_binding_digest": digest("host-" + str(i % 2)),
            "project_id": "p1-project-" + str(i % 2),
            "scope_type": "TASK",
            "scope_ref": str(i),
        }
        for i in range(config["state_count"])
    ]
    payloads = [
        {"marker": f"state-{i}", "text": "x" * config["payload_text_bytes"][i % 3]}
        for i in range(len(bindings))
    ]

    async def measure(label, index, operation):
        if len(events) >= config["maximum_sdk_logical_calls"]:
            raise RuntimeError("LOGICAL_CALL_LIMIT")
        event = {"phase": label, "index": index, "start_s": time.monotonic() - started}
        events.append(event)
        try:
            result = await asyncio.wait_for(operation(), config["request_timeout_seconds"])
            event.update(
                status="COMPLETED",
                response_sha256=digest(result),
                runtime_request_id_fingerprint=request_fingerprint(result),
            )
            return result
        except BaseException as exc:
            event.update(status="FAILED_OR_CANCELLED", error_type=type(exc).__name__)
            raise
        finally:
            event["end_s"] = time.monotonic() - started
            event["elapsed_ms"] = (event["end_s"] - event["start_s"]) * 1000

    async def bounded(count, concurrency, operation):
        indices = iter(range(count))

        async def work():
            for i in indices:
                await operation(i)

        async with asyncio.TaskGroup() as group:
            for _ in range(concurrency):
                group.create_task(work())

    try:
        await client.capabilities()

        async def seed(i):
            saved = await measure(
                "seed",
                i,
                lambda: client.update_working_state(
                    {**bindings[i], "expected_version": 0, "payload": payloads[i]},
                    operation_id=f"seed-{i}",
                ),
            )
            assert saved["version"] == 1 and saved["payload"] == payloads[i]
            report["seeded"] += 1

        await bounded(len(bindings), config["seed_concurrency"], seed)
        report["save_client_latency"] = distribution([e["elapsed_ms"] for e in events])
        # Same scope string with another trusted binding cannot alias an existing State.
        absent = await client.get_working_state(
            {**bindings[0], "principal_binding_digest": digest("b")}
        )
        assert absent["status"] == "ABSENT" and absent["payload"] == {}
        report["principal_negative_control"] = "ABSENT"

        head = await client.get_working_state(bindings[0])
        start = asyncio.Event()

        async def compete(number):
            await start.wait()
            try:
                result = await client.update_working_state(
                    {
                        **bindings[0],
                        "state_id": head["state_id"],
                        "expected_version": 1,
                        "payload": {"winner": number},
                    },
                    operation_id=f"compete-{number}",
                )
                return {"kind": "COMMITTED", "receipt": result, "number": number}
            except ConflictError as exc:
                return {"kind": "CONFLICT", "code": exc.code, "number": number}

        tasks = [asyncio.create_task(compete(i)) for i in range(2)]
        start.set()
        outcomes = await asyncio.gather(*tasks)
        assert sorted(o["kind"] for o in outcomes) == ["COMMITTED", "CONFLICT"]
        assert next(o for o in outcomes if o["kind"] == "CONFLICT")["code"] == "STALE_WORKING_STATE"
        winner = next(o for o in outcomes if o["kind"] == "COMMITTED")
        payloads[0] = winner["receipt"]["payload"]
        recovered = await client.get_working_state(bindings[0])
        assert recovered["state_version_id"] == winner["receipt"]["state_version_id"]
        replay = await client.update_working_state(
            {
                **bindings[0],
                "state_id": head["state_id"],
                "expected_version": 1,
                "payload": payloads[0],
            },
            operation_id=f"compete-{winner['number']}",
        )
        assert replay["replayed"] and replay["state_version_id"] == recovered["state_version_id"]
        report["cas"] = {"outcomes": outcomes, "direct_read": recovered, "replay": replay}

        for concurrency in config["read_concurrency"]:
            phase_events = []
            for repeat in range(config["rounds"]):
                label = f"read-c{concurrency}-r{repeat}"
                phase_start = time.monotonic()

                async def read(i, repeat=repeat, label=label):
                    index = (repeat * config["reads_per_round"] + i) % len(bindings)
                    value = await measure(
                        label, index, lambda: client.get_working_state(bindings[index])
                    )
                    assert value["payload"] == payloads[index]
                    assert value["version"] == (2 if index == 0 else 1)

                await bounded(config["reads_per_round"], concurrency, read)
                selected = [e for e in events if e["phase"] == label]
                phase_events.extend(selected)
                report["phases"].append(
                    {
                        "name": label,
                        "concurrency": concurrency,
                        "client_latency": distribution([e["elapsed_ms"] for e in selected]),
                        "completed_per_second": len(selected) / (time.monotonic() - phase_start),
                    }
                )
            combined = distribution([e["elapsed_ms"] for e in phase_events])
            if combined["p95_ms"] > config["sdk_read_p95_stop_ms"]:
                report.update(status="READ_LATENCY_STOP_NO_HIGHER_LOAD", stopped_at=concurrency)
                break
        else:
            report["status"] = "STATE_CALIBRATION_COMPLETED_NOT_FULL_P1"
    except BaseException as exc:
        report.update(status="STOPPED_WITH_FAILURE", error_type=type(exc).__name__)
        raise
    finally:
        await client.close()
        report.update(physical_attempts=len(physical), elapsed_seconds=time.monotonic() - started)
        write(root / "sdk-result.json", report)
        write(root / "sdk-events.json", events)
        write(root / "http-attempts.json", physical)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(calibrate(args.root)), ensure_ascii=False))
