"""Fixed Provider, real native Codex HTTP MCP save/cold read on private test PG."""

# ruff: noqa: RUF001 -- Exact source punctuation is part of the fidelity check.

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from v02_local_provider import ENDPOINT, MODEL, write_json

PAYLOAD = {"note": " 首\r\n任意自由文本，不要求业务字段。\n尾 \n",
           "unrelated": {"value": 7, "keep": True}}
TOOLS = {"milai_working_state_get", "milai_working_state_update", "milai_evidence_capture",
         "milai_memory_get", "milai_memory_resolve"}


def definitions(request):
    result = {}
    for tool in request["tools"]:
        for member in tool["tools"] if tool["type"] == "namespace" else [tool]:
            name = (tool["name"] + "__" if tool["type"] == "namespace" else "") + member["name"]
            for target in TOOLS:
                if name.endswith(target):
                    result[target] = name
    return result


def fixture(root: Path, phase: str):
    requests = []

    def respond(request):
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        body = json.loads(request.content)
        requests.append(body)
        names = definitions(body)
        assert set(names) == TOOLS
        number = len(requests)
        if phase == "G" and number == 1:
            name = names["milai_working_state_update"]
            args = {"scope": "TASK", "expected_version": 0,
                    "operation_id": "native-engineering-save-20260908", "payload": PAYLOAD}
        elif (phase == "G" and number == 2) or (phase == "R" and number == 1):
            name, args = names["milai_working_state_get"], {"scope": "TASK"}
        else:
            name, args = None, {}
        if name:
            text = "<tool_call><function=" + name + ">" + "".join(
                "<parameter=" + key + ">\n" + (value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)) + "\n</parameter>"
                for key, value in args.items()) + "</function></tool_call>"
        else:
            text = "Fixed-provider transport check completed."
        return httpx.Response(200, json={"id": f"resp_fixture_{phase}_{number}",
            "object": "response", "model": MODEL, "created_at": int(time.time()),
            "status": "completed", "output": [{"type": "message", "role": "assistant",
                "id": f"msg_{phase}_{number}", "status": "completed", "content": [
                    {"type": "output_text", "text": text, "annotations": []}]}],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}})

    return httpx.MockTransport(respond)


def state_records(value):
    if isinstance(value, str):
        if value.startswith("Wall time: ") and "\nOutput:\n" in value:
            value = value.split("\nOutput:\n", 1)[1]
        try:
            yield from state_records(json.loads(value))
        except json.JSONDecodeError:
            return
    elif isinstance(value, list):
        for item in value:
            yield from state_records(item)
    elif isinstance(value, dict):
        if "state_id" in value and "payload" in value:
            yield value
        for item in value.values():
            yield from state_records(item)


def verify_presentation(directory: Path):
    presented = []
    for path in sorted(directory.glob("native-request-*.bin")):
        body = json.loads(path.read_bytes())
        for item in body["input"]:
            if item.get("type") == "function_call_output":
                presented.extend(state_records(item["output"]))
    write_json(directory / "presented-states.json", presented)
    assert any(v.get("version") == 1 and v["payload"] == PAYLOAD for v in presented)
    return presented


async def public_checks(root: Path, phase: str):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    settings = json.loads((root / "gateway.json").read_text())
    tokens = json.loads((root / "synthetic-auth.json").read_text())["tokens"]
    result = {}
    for user in ("ordinary", "hot"):
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + tokens[user]},
                                      trust_env=False) as http:
            async with Client(streamable_http_client(settings["url"], http_client=http),
                              mode="legacy") as client:
                catalog = await client.list_tools()
                assert {t.name for t in catalog.tools} == TOOLS
                result[user] = {"catalog": catalog.model_dump(mode="json", by_alias=True),
                                "instructions": client.instructions}
                response = await client.call_tool("milai_working_state_get", {"scope": "TASK"})
                assert not response.is_error
                value = response.structured_content
                result[user]["state"] = value
                if phase == "before" or user == "hot":
                    assert value["status"] == "ABSENT"
                else:
                    assert value["payload"] == PAYLOAD and value["version"] == 1
    write_json(root / (phase + "-public.json"), result)
    return result


def check(root: Path, config_path: Path):
    import run_v02_memory_flow as base
    from run_v02_local_vllm import stop_owned
    from run_v02_native_session import run

    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    group = base.ProcessGroup(root)
    service = root / (root.name + "-product")
    report = {"status": "STARTED", "actual_model_generations": 0,
              "kind": "NATIVE_CODEX_FIXED_PROVIDER_REAL_PRIVATE_MCP_PG", "sessions": {}}
    started = time.monotonic()
    try:
        base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "SYNTHETIC_ONLY",
                                        "MILAI_REQUEST_TIMING_ENABLED": "true"})
        env = base._clean_environment(base._load_environment(service / "runtime.env"))
        port = base._free_port()
        url = f"http://127.0.0.1:{port}/mcp"
        write_json(root / "gateway.json", {"port": port, "url": url,
                   "resource": f"https://127.0.0.1:{port}/mcp", "scope_refs": {}})
        gateway_script = str(base.LAB / "tools/check_v02_private_http_load.py")
        gateway = group.start("private-mcp", [str(base.MCP / ".venv/bin/python"),
            gateway_script, "--gateway", "--root", str(root)],
            cwd=base.MCP, env=env)
        base._wait_http(f"http://127.0.0.1:{port}/readyz", gateway)
        report["gateway_pid"] = gateway.pid
        asyncio.run(public_checks(root, "before"))
        token = json.loads((root / "synthetic-auth.json").read_text())["tokens"]["ordinary"]
        for phase in ("G", "R"):
            allocation = {"provider_base_url": ENDPOINT, "model": MODEL,
                "paid_model_allocations_authorized": 0, "request_timeout_seconds": 20,
                "model_transport_enabled": True, "new_model_tokens_authorized": 2000,
                "new_model_allocations_authorized": 1, "local_sessions": [phase],
                "session_token_limit": 2000, "batch_token_limit": 2000,
                "max_requests_per_session": 3 if phase == "G" else 2,
                "request_input_token_limit": 1000, "max_output_tokens": 300,
                "output_codec": "qwen_xml", "session_deadline_seconds": 60}
            directory = root / phase
            current = run(directory, allocation, "Perform the fixed protocol check.", phase,
                          transport=fixture(root, phase), mcp={"url": url, "token": token})
            report["sessions"][phase] = current
            assert current["status"] == "COMPLETED" and current["container_absent"]
            verify_presentation(directory)
        public = asyncio.run(public_checks(root, "after"))
        report.update(status="FIXED_PROVIDER_NATIVE_MCP_SAVE_AND_COLD_READ_VERIFIED",
                      state_id=public["ordinary"]["state"]["state_id"], state_version=1)
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        group.stop()
        report["cleanup"] = stop_owned(service)
        report["seconds_including_cleanup"] = time.monotonic() - started
        write_json(root / "result.json", report)
    return report


def cold_followup(root: Path):
    """Resume a retained engineering save after an offline observer repair; never redo G."""
    import run_v02_memory_flow as base
    from run_v02_local_vllm import stop_owned
    from run_v02_native_session import run

    initial = json.loads((root / "G/result.json").read_text())
    assert initial["status"] == "COMPLETED" and initial["container_absent"]
    saved = verify_presentation(root / "G")[0]
    service = root / (root.name + "-product")
    config_path = service / "config.json"
    base.pin(config_path)
    group = base.ProcessGroup(root)
    report = {"status": "STARTED", "actual_model_generations": 0, "new_G_sessions": 0}
    started = time.monotonic()
    try:
        compose = base.read_json(service / "compose-command.json")
        base._command([*compose, "up", "--detach", "--wait", "postgres"], cwd=base.RUNTIME)
        env = base._clean_environment(base._load_environment(service / "runtime.env"))
        api = group.start("api", [str(base.API_EXE)], cwd=base.RUNTIME, env=env)
        worker = group.start("worker", [str(base.WORKER_EXE)], cwd=base.RUNTIME, env=env)
        write_json(service / "services.json", {"api": api.pid, "worker": worker.pid})
        base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
        settings = base.read_json(root / "gateway.json")
        gateway_script = str(base.LAB / "tools/check_v02_private_http_load.py")
        gateway = group.start("private-mcp-cold", [str(base.MCP / ".venv/bin/python"),
            gateway_script, "--gateway", "--root", str(root)],
            cwd=base.MCP, env=env)
        base._wait_http(f"http://127.0.0.1:{settings['port']}/readyz", gateway)
        token = base.read_json(root / "synthetic-auth.json")["tokens"]["ordinary"]
        allocation = base.read_json(root / "G/allocation.json")
        allocation.update(local_sessions=["R"], max_requests_per_session=2)
        current = run(root / "R", allocation, "Perform the fixed protocol check.", "R",
                      transport=fixture(root, "R"), mcp={"url": settings["url"], "token": token})
        report["R"] = current
        assert current["status"] == "COMPLETED" and current["container_absent"]
        recovered = verify_presentation(root / "R")[0]
        assert recovered["state_version_id"] == saved["state_version_id"]
        public = asyncio.run(public_checks(root, "after"))
        assert public["ordinary"]["state"]["state_version_id"] == saved["state_version_id"]
        report.update(status="FIXED_PROVIDER_NATIVE_MCP_SAVE_AND_COLD_READ_VERIFIED",
                      state_id=saved["state_id"], state_version_id=saved["state_version_id"])
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        group.stop()
        report["cleanup"] = stop_owned(service)
        report["seconds_including_cleanup"] = time.monotonic() - started
        write_json(root / "cold-followup.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cold-followup", action="store_true")
    args = parser.parse_args()
    report = (cold_followup(args.root.resolve()) if args.cold_followup
              else check(args.root.resolve(), args.config.resolve()))
    print(json.dumps({k: v for k, v in report.items() if k != "sessions"}))
