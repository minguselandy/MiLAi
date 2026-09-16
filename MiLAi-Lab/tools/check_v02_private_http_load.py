"""Finite authenticated private-user HTTP load; embedded public MCP, real Runtime/PG."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def gateway(root):
    import httpx2 as httpx
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from milai_client import AsyncMilaiClient, HttpxAsyncTransport, MilaiClient
    from milai_mcp import build_server
    from milai_mcp.aigcit_auth import AigcitTokenVerifier, JwksCache
    from milai_mcp.auth_policy import PILOT_SCOPES, AdmissionPolicy
    from milai_mcp.http_transport import HttpResourceBinding
    from milai_mcp.server import CodexFullRuntimeClients

    settings = read(root / "gateway.json")
    issuer, resource = "https://synthetic-auth.example.test", settings["resource"]
    project = "private-load-namespace"
    fixture_path = root / "synthetic-auth.json"
    if not fixture_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid="private-load", alg="ES256", use="sig")
        tokens = {user: jwt.encode({
            "iss": issuer, "aud": resource, "sub": user, "client_id": "load-client",
            "iat": int(time.time()), "exp": int(time.time()) + 900,
            "scope": " ".join(sorted(PILOT_SCOPES)),
            "project": "forged-peer-project", "tenant": "forged-tenant",
        }, key, algorithm="ES256", headers={"typ": "at+jwt", "kid": "private-load"})
            for user in ("ordinary", "hot")}
        fixture_path.touch(mode=0o600)
        write(fixture_path, {"keys": [jwk], "tokens": tokens})
        write(root / "policy.json", {"version": 2, "issuer": issuer, "project_id": project,
                                    "mode": "authenticated_private", "owners": []})
        (root / "policy.json").chmod(0o640)
    fixture = read(fixture_path)

    async def synthetic_as(request):
        if request.url.path.endswith("oauth-authorization-server"):
            return httpx.Response(200, json={"issuer": issuer, "jwks_uri": issuer + "/jwks"})
        return httpx.Response(200, json={"keys": fixture["keys"]})

    binding = HttpResourceBinding.create(issuer_url=issuer, resource_url=resource,
                                        scope={"project_ids": [project]},
                                        scopes=tuple(sorted(PILOT_SCOPES)))
    as_client = httpx.AsyncClient(transport=httpx.MockTransport(synthetic_as))
    verifier = AigcitTokenVerifier(
        cache=JwksCache(issuer, client=as_client), resource_url=resource,
        scope_digest=binding.scope_digest,
        policy=AdmissionPolicy(root / "policy.json", issuer=issuer, project_id=project,
                               enabled_scopes=PILOT_SCOPES, trusted_owner_uid=os.getuid(),
                               mode="authenticated_private"))
    runtime_url = os.environ["MILAI_BASE_URL"]
    clients = {role: MilaiClient(base_url=runtime_url, max_retries=0,
                                token=os.environ[f"MILAI_AGENT_{role.upper()}_TOKEN"])
               for role in ("reader", "submitter", "reviewer", "operator")}

    def asynchronous(role):
        return AsyncMilaiClient(
            base_url=runtime_url, token=os.environ[f"MILAI_AGENT_{role.upper()}_TOKEN"],
            max_retries=0, transport=HttpxAsyncTransport(runtime_url, 10, timing_enabled=True))

    server = build_server(
        "codex-full", clients["reader"], default_scope={"project_ids": [project]},
        codex_full_clients=CodexFullRuntimeClients(**clients), http_principal_binding=binding,
        http_token_verifier=verifier,
        codex_working_state_scope_refs=settings.get("scope_refs", {
            "TASK": "private-load-task", "SESSION": "private-load-session"}),
        working_state_client_factory=lambda: asynchronous("submitter"),
        resolve_client_factory=lambda: asynchronous("reader"), request_timing_enabled=True,
        max_retries=0)
    try:
        server.run(transport="streamable-http", host="127.0.0.1", port=settings["port"],
                   streamable_http_path="/mcp")
    finally:
        for client in clients.values():
            client.close()
        asyncio.run(as_client.aclose())


async def client(root, phase):
    from contextlib import AsyncExitStack

    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from milai_client import AsyncMilaiClient

    from check_v02_service_concurrency import digest, request_fingerprint
    from v02_fixed_arrivals import arrivals, summarize

    config = read(root / "config.json")
    settings = read(root / "gateway.json")
    tokens = read(root / "synthetic-auth.json")["tokens"]
    events, calls, peers = [], [], {}
    report = {"status": "RUNNING", "phase": phase, "pid": os.getpid(), "model_calls": 0}
    saved = {} if phase == "load" else read(root / "receipts.json")
    scopes = ("TASK", "SESSION", "PROJECT")
    try:
        async with AsyncExitStack() as stack:
            for user, token in tokens.items():
                http = await stack.enter_async_context(httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + token}, trust_env=False))
                peers[user] = await stack.enter_async_context(Client(streamable_http_client(
                    settings["url"], http_client=http), mode="2026-07-28"))

            async def call(user, tool, args):
                assert len(calls) < config["maximum_mcp_tool_calls"]
                event = {"user": user, "phase": phase, "tool": tool, "start_s": time.monotonic()}
                calls.append(event)
                try:
                    result = await peers[user].call_tool(tool, args)
                    if result.is_error:
                        event["status"] = "MCP_ERROR"
                        event["error_result"] = result.model_dump(mode="json")
                        raise RuntimeError("MCP_ERROR")
                    value = result.structured_content
                    assert isinstance(value, dict)
                    event.update(status="COMPLETED", response_sha256=digest(value),
                                 runtime_request_id_fingerprint=request_fingerprint(value))
                    return value
                finally:
                    event["end_s"] = time.monotonic()

            async def state_read(user, index):
                scope = scopes[index % len(scopes)]
                value = await call(user, "milai_working_state_get", {"scope": scope})
                expected = saved[user][scope]
                assert value["payload"] == expected["payload"]
                assert value["state_version_id"] == expected["state_version_id"]
                assert not value.get("payload_withheld")
                return {"user": user, "scope": scope,
                        "runtime_request_id_fingerprint": request_fingerprint(value)}

            if phase == "load":
                catalogs = {u: (await peer.list_tools()).model_dump(mode="json")
                            for u, peer in peers.items()}
                assert catalogs["ordinary"] == catalogs["hot"]
                write(root / "catalogs.json", catalogs)
                for user in peers:
                    saved[user] = {}
                    for index, scope in enumerate(scopes):
                        content = (user + " FIRST\n" + "x" * config["payload_text_bytes"][index]
                                   + "\nLAST")
                        source = await call(user, "milai_evidence_capture", {
                            "operation_id": "source-" + scope, "source_type": "AGENT_TURN",
                            "source_ref": "private-load/" + scope, "subject_id": "private-load",
                            "observed_at": "2026-09-07T00:00:00Z", "content": content,
                            "source_context": {"session_id": "private-load-session",
                                               "turn_id": user + "-" + scope,
                                               "turn_ordinal": index,
                                               "round_id": user + "-" + scope,
                                               "round_ordinal": index},
                            "confirmation": "CAPTURE"})
                        value = await call(user, "milai_working_state_update", {
                            "scope": scope, "operation_id": "state-" + scope, "expected_version": 0,
                            "payload": {"first": user, "text": content, "last": user,
                                        "evidence_refs": [source["evidence_id"]]}})
                        assert value["version"] == 1
                        saved[user][scope] = value
                        write(root / "receipts.json", saved)
                write(root / "receipts.json", saved)
                # Background dataset through the public SDK, separate from both users' projects.
                async with AsyncMilaiClient(base_url=os.environ["MILAI_BASE_URL"], max_retries=0,
                        token=os.environ["MILAI_AGENT_SUBMITTER_TOKEN"]) as sdk:
                    indices = iter(range(config["state_count"] - 6))

                    async def seed():
                        for index in indices:
                            value = await sdk.update_working_state({
                                "principal_binding_digest": digest("private-noise"),
                                "project_id": "private-noise", "scope_type": "TASK",
                                "scope_ref": str(index), "expected_version": 0,
                                "payload": {"first": index, "text": "x" *
                                            config["payload_text_bytes"][index % 3],
                                            "last": index}},
                                operation_id="noise-" + str(index))
                            assert value["version"] == 1
                    await asyncio.gather(*(seed() for _ in range(4)))
                report["noise_states_confirmed"] = config["state_count"] - 6
                for user in peers:
                    for index in range(6):
                        await state_read(user, index)
                report["stages"] = []
                for stage in ("baseline", "hot", "recovery"):
                    start = time.monotonic() + 0.1
                    users = ("ordinary", "hot") if stage == "hot" else ("ordinary",)
                    async with asyncio.TaskGroup() as group:
                        for user in users:
                            rate, capacity = ((config["ordinary_rate"], 2) if user == "ordinary"
                                              else (config["hot_rate"], 6))
                            group.create_task(arrivals(
                                count=rate * config["seconds"], rate=rate, capacity=capacity,
                                timeout=10, operation=lambda index, u=user: state_read(u, index),
                                label=stage + "-" + user, events=events, start=start,
                                abort=asyncio.Event()))
                    report["stages"].append({"stage": stage, "users": {
                        user: summarize([e for e in events if e["label"] == stage + "-" + user],
                                        duration=config["seconds"], target_ms=config["read_p95_ms"])
                        for user in users}})
                report["status"] = "PRIVATE_LOAD_COMPLETE_NOT_GENERAL_FAIRNESS" if all(
                    s["users"]["ordinary"]["candidate_target_met"] for s in report["stages"]
                ) else "PRIVATE_ORDINARY_TARGET_FAILED_RECOVERY_OBSERVED"
            else:
                if phase == "cold":
                    for user in peers:
                        for index in range(3):
                            await state_read(user, index)
                    policy = read(root / "policy.json")
                    policy["disabled_subjects"] = ["hot"]
                    write(root / "policy.json", policy)
                async with httpx2.AsyncClient(trust_env=False) as http:
                    denied = await http.post(settings["url"], headers={
                        "Authorization": "Bearer " + tokens["hot"],
                        "MCP-Protocol-Version": "2025-11-25", "MCP-Method": "tools/list",
                        "Accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                    report["hot_denied_status"] = denied.status_code
                    report["hot_denied_body"] = denied.text
                    assert denied.status_code == 403
                    assert all(v["payload"]["text"] not in denied.text
                               for states in saved.values() for v in states.values())
                for index in range(3):
                    await state_read("ordinary", index)
                report.update(status="DISABLED_USER_AND_ORDINARY_ISOLATION_VERIFIED",
                              hot_denied_status=denied.status_code)
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        write(root / (phase + "-calls.json"), calls)
        write(root / (phase + "-arrivals.json"), events)
        write(root / (phase + "-result.json"), report)


def run(root, config_path):
    import run_v02_memory_flow as base
    from run_v02_local_vllm import stop_owned
    from v02_cgroup_observation import host_scheduler_sample

    config = read(config_path)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    write(root / "config.json", config)
    write(root / "preflight.json", {
        "pin": base.pin(config_path),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    service = root / (root.name + "-product")
    group = base.ProcessGroup(root)
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[:2])
    samples = []
    try:
        base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "SYNTHETIC_ONLY",
                                        "MILAI_API_THREADS": "8",
                                        "MILAI_DATABASE_POOL_MAX_SIZE": "8",
                                        "MILAI_REQUEST_TIMING_ENABLED": "true"})
        env = base._clean_environment(base._load_environment(service / "runtime.env"))
        port = base._free_port()
        write(root / "gateway.json", {"port": port, "url": f"http://127.0.0.1:{port}/mcp",
                                      "resource": f"https://127.0.0.1:{port}/mcp"})
        command = [str(base.MCP / ".venv/bin/python"), str(Path(__file__).resolve()),
                   "--root", str(root)]
        for phase in ("load", "cold"):
            gateway_process = group.start("gateway-" + phase, [*command, "--gateway"],
                                          cwd=base.MCP, env=env)
            base._wait_http(f"http://127.0.0.1:{port}/readyz", gateway_process)
            process = group.start("client-" + phase, [*command, "--client", phase],
                                  cwd=base.MCP, env=env)
            deadline = time.monotonic() + config["worker_timeout_seconds"]
            pids = {**read(service / "services.json"), "gateway": gateway_process.pid,
                    "client": process.pid}
            while process.poll() is None and time.monotonic() < deadline:
                samples.append(host_scheduler_sample(pids))
                time.sleep(0.5)
            if process.poll() is None:
                raise TimeoutError("PRIVATE_CLIENT_DEADLINE")
            if process.returncode:
                raise RuntimeError("PRIVATE_CLIENT_FAILED_SEE_OWNED_LOG")
            group.stop()
        write(root / "result.json", {"load": read(root / "load-result.json"),
                                     "cold": read(root / "cold-result.json"), "model_calls": 0})
    finally:
        group.stop()
        write(root / "resource-samples.json", samples)
        write(root / "cleanup.json", stop_owned(service))
        os.sched_setaffinity(0, affinity)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--gateway", action="store_true")
    parser.add_argument("--client", choices=("load", "cold", "disabled"))
    args = parser.parse_args()
    if args.gateway:
        gateway(args.root.resolve())
    elif args.client:
        asyncio.run(client(args.root.resolve(), args.client))
    else:
        run(args.root.resolve(), args.config.resolve())
