"""Authorized W1 read-only readiness audit; never tokenizes or sends completions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL
from v0220_evidence import LAB, dependencies, save, seal, sha, validate
from v0220_provider_hardened import historical_usage
from v0220_wire_admission import backend_identity
from v0221_authorization import HISTORY, REVISION, check_authorization

GOAL = LAB / "studies/active/MILA_V0221_真实生成兼容验证与动作执行复验_GOAL_20260911.md"
WIRE = Path("/cra/memory/mx_memory/evidence/v0220-wire-fix/20260911-v1")
CONTAINER = "bcec1ef46198"
AUTHORIZED_BATCH = Path("/cra/memory/mx_memory/evidence/v0221/20260911-r1")
FLAGS = {
    "--model",
    "--served-model-name",
    "--max-model-len",
    "--tensor-parallel-size",
    "--pipeline-parallel-size",
    "--dtype",
    "--quantization",
    "--reasoning-parser",
    "--structured-outputs-config",
    "--gpu-memory-utilization",
}


def command(argv: list[str]) -> dict:
    started = time.monotonic()
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)  # noqa: S603
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "seconds": time.monotonic() - started,
    }


def selected_args() -> dict:
    # Capture privately, export ONLY the known safe parameter values; never Env/Cmd wholesale.
    value = subprocess.run(  # noqa: S603 - fixed read-only selected container
        ["/usr/bin/docker", "inspect", "--format", "{{json .Args}}", CONTAINER],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    args = json.loads(value.stdout)
    selected = {}
    for i, arg in enumerate(args):
        key = arg.split("=", 1)[0]
        if key in FLAGS:
            selected[key] = arg.split("=", 1)[1] if "=" in arg else args[i + 1]
    return selected


def run(root: Path) -> dict:
    if root.resolve() != AUTHORIZED_BATCH:
        raise ValueError("USER_GRANT_BOUND_TO_SINGLE_V0221_BATCH")
    old = validate(WIRE)
    expected_identity = old["contract"]["backend_identity"]
    now = time.time()
    grant = {
        "origin": "USER_CONVERSATION",
        "path": "B",
        "reply": "授权",
        "question": "是否明确授权 V0221 采用路径 B：保留历史 1 次未知请求及 28,284 raw 预约、"  # noqa: RUF001
        "不结算为零，独立执行 W2（最多 16 次），并仅在全部门通过后执行 W3（最多 96 次）？"  # noqa: RUF001
        "新增未知立即停发，不重试旧请求、不变更共享服务。",  # noqa: RUF001
        "historical_unknown_explicit": True,
        "allowed_stages": ["W1", "W2", "W3", "W4"],
        "observed_utc": "2026-09-11 12:26:12 UTC",
        "provenance_limit": "Operator record of actual user reply; not a digital signature",
    }
    implementation = dependencies([Path(__file__)])
    seal(
        root,
        entries=[Path(__file__)],
        inputs=[*HISTORY, WIRE / "manifest.json", WIRE / "result.json"],
        contract={
            "stage": "W0_AUTH_AND_W1_SERVICE_READINESS",
            "goal_sha256": sha(GOAL),
            "planned_W2": 16,
            "planned_W3": 24,
            "model_requests": 0,
            "read_only_deadline_unix": now + 600,
            "baseline_identity": expected_identity,
        },
    )
    save(
        root / "goal-frozen.json",
        {"path": str(GOAL), "sha256": sha(GOAL), "text": GOAL.read_text()},
    )
    save(root / "authorization-source.json", grant)
    history = historical_usage(HISTORY)
    authorization = {
        "revision": REVISION,
        "path": "B",
        "goal_sha256": sha(GOAL),
        "batch_id": root.name,
        "evidence_root": str(root.resolve()),
        "source_sha256": sha(root / "authorization-source.json"),
        "issued_unix": dt.datetime.fromisoformat("2026-09-11T12:26:12+00:00").timestamp(),
        "expires_unix": dt.datetime.fromisoformat("2026-09-11T18:26:12+00:00").timestamp(),
        "allowed_stages": ["W1", "W2", "W3", "W4"],
        "request_caps": {"W1": 0, "W2": 16, "W3": 96, "W4": 0},
        "model_concurrency": 1,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "raw_token_cap": None,
        "historical": history,
        "accepted_unknown": history["unresolved_reservations"],
        "historical_usage_settled": False,
        "reconciliation": None,
        "implementation_sha256": {str(p): sha(p) for p in implementation},
        "backend_identity": expected_identity,
        "wire_manifest_sha256": sha(WIRE / "manifest.json"),
        "new_unknown_stops_batch": True,
        "automatic_retry": False,
        "shared_service_changes": False,
        "new_tasks_or_state": False,
        "generation_allocation_active": False,
        "note": "User scope recorded; no generation dispatch until full policy and W1 gates pass",
    }
    save(root / "authorization.json", authorization)
    auth_sha, source_sha = sha(root / "authorization.json"), sha(root / "authorization-source.json")
    check_authorization(root, auth_sha, source_sha, stage="W1")
    save(
        root / "authorization-check.json",
        {
            "status": "EXACT_PATH_B_USER_SCOPE_VERIFIED",
            "authorization_sha256": auth_sha,
            "source_sha256": source_sha,
            "generation_dispatch_unlocked": False,
        },
    )
    identity = backend_identity(CONTAINER)
    save(root / "backend-identity.json", identity)
    args = selected_args()
    save(root / "selected-service-args.json", args)
    gpu = command(
        [
            "/usr/bin/docker",
            "exec",
            CONTAINER,
            "nvidia-smi",
            "--query-gpu=index,name,uuid,utilization.gpu,memory.used",
            "--format=csv,noheader",
        ]
    )
    save(root / "container-gpu.json", gpu)
    host = command(
        [
            "/usr/bin/nvidia-smi",
            "--query-gpu=index,name,uuid,utilization.gpu,memory.used",
            "--format=csv,noheader",
        ]
    )
    save(root / "host-gpu.json", host)
    observations = {}
    with httpx.Client(
        base_url=ENDPOINT, trust_env=False, follow_redirects=False, timeout=5
    ) as client:
        for name, path in (("models", "/v1/models"), ("health", "/health")):
            start = time.monotonic()
            try:
                response = client.get(path)
                observations[name] = {
                    "status_code": response.status_code,
                    "body": response.text,
                    "seconds": time.monotonic() - start,
                }
            except httpx.HTTPError as exc:
                observations[name] = {"status_code": None, "exception_type": type(exc).__name__}
            save(root / (name + ".json"), observations[name])
    backend_match = identity == expected_identity
    args_match = (
        args.get("--max-model-len") == "65536"
        and (args.get("--served-model-name") == MODEL)
        and "--structured-outputs-config" not in args
    )
    ready = backend_match and args_match and gpu["returncode"] == 0
    result = {
        "status": "READ_ONLY_SERVICE_CHECK_ONLY"
        if ready
        else ("BACKEND_DRIFT" if not backend_match or not args_match else "SERVICE_NOT_READY"),
        "backend_identity_match": backend_match,
        "selected_parameters_match": args_match,
        "container_gpu_returncode": gpu["returncode"],
        "host_gpu_returncode": host["returncode"],
        "model_requests": 0,
        "tokenize_requests": 0,
        "new_usage_unknown": 0,
        "G_AUTH": "USER_PATH_B_SCOPE_RECORDED_NOT_GENERATION_POLICY_ADMISSION",
        "G_PREFLIGHT": "INCOMPLETE" if ready else "NOT_MET_SERVICE_READINESS",
        "G_LIVE_COMPAT": "NOT_TRIGGERED",
        "G_KNOWN_INTENT_V0221": "NOT_TRIGGERED",
        "W2_attempted": 0,
        "W2_unrun": 16,
        "W3_attempted": 0,
        "W3_unrun": 24,
        "historical_usage": history,
        "limit": "HTTP health/model listing alone do not prove GPU generation readiness. "
        "No service/GPU permission repair or generation probe was attempted.",
    }
    validate(root)
    check_authorization(root, auth_sha, source_sha, stage="W1")
    save(root / "result.json", result)
    if not ready:
        save(
            root / "stop.json",
            {
                "reason": result["status"],
                "unix": time.time(),
                "new_candidate_or_service_change_requires_new_authorization": True,
            },
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
