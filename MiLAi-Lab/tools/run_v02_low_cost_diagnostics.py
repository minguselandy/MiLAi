"""Bounded public testkit diagnostics for the v02-03 isolated study."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime

import run_v02_memory_flow as base
from v02_lme_capture import capture_persistent
from v02_lme_sources import history_events

CONFIG = base.LAB / "configs/v02-low-cost-reuse.json"
ROOT = base.LAB / "artifacts/v02-low-cost-reuse/n0n1-20260906a"
DATA = base.LAB / "artifacts/v02-lme-incremental/data-20260905b"


def resume_network_setup() -> None:
    """Resume this run's failed network allocation, preserving all old networks."""
    base.pin(CONFIG)
    if (ROOT / "services.json").exists() or (ROOT / "prepared.json").exists():
        raise RuntimeError("Refuse setup over a started instance")
    override = ROOT / "compose-network.yaml"
    override.write_text("networks:\n  default:\n    ipam:\n      config:\n"
                        "        - subnet: 10.243.3.0/24\n")
    compose = base.read_json(ROOT / "compose-command.json")
    compose += ["--file", str(override)]
    base.write_json(ROOT / "compose-command.json", compose)
    base.write_json(ROOT / "setup-repair.json", {
        "initial_failure": "Docker predefined address pools fully subnetted",
        "action": "Explicit new run-only 10.243.3.0/24, no existing route/network overlap",
        "experimental_model_allocations": 0,
    })
    base._command([*compose, "up", "--detach", "--wait", "postgres"],
                  cwd=base.RUNTIME, timeout=120)
    env = base._clean_environment(base._load_environment(ROOT / "runtime.env"))
    migrated = base._command([str(base.ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                             cwd=base.RUNTIME, env=env, timeout=180)
    (ROOT / "migration.log").write_text(migrated.stdout + migrated.stderr)
    group = base.ProcessGroup(ROOT)
    api = group.start("api", [str(base.API_EXE)], cwd=base.RUNTIME, env=env)
    worker = group.start("worker", [str(base.WORKER_EXE)], cwd=base.RUNTIME, env=env)
    base.write_json(ROOT / "services.json", {"api": api.pid, "worker": worker.pid})
    base._wait_http(env["MILAI_BASE_URL"] + "/health/ready", api)
    base.write_json(ROOT / "prepared.json", {"status": "READY", "created_at": time.time()})
    print("READY")


def capture(case: str) -> None:
    base.assert_services(ROOT)
    pin = base.pin(CONFIG)
    raw = (DATA / "sources" / f"{case}.json").read_bytes()
    expected = base.read_json(DATA / "manifest.json")["cases"][case]["source_sha256"]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Source hash changed")
    source = json.loads(raw)
    project = f"v0203-diag-{case}"
    events = history_events(source, project)
    directory = ROOT / "diagnostics" / case
    directory.mkdir(parents=True, exist_ok=False)
    environment = base._load_environment(ROOT / "runtime.env")
    prepared = capture_persistent(environment, project, events, directory, 300)
    base.write_json(directory / "source-preparation.json", prepared)
    snapshot = datetime.now(UTC).isoformat()
    base.write_json(directory / "fixed.json", {
        "project": project, "source_sha256": expected, "snapshot": snapshot,
        "pin": pin, "query": source["question"], "reference_time": snapshot,
        "capture_complete_before_testkit": True,
    })
    print(json.dumps({"case": case, "status": "READY", "events": len(events)}))


def trace(case: str, batch: int, name: str, d1: bool) -> None:
    base.assert_services(ROOT)
    pin = base.pin(CONFIG)
    if batch not in (1, 2):
        raise ValueError("Only two diagnostic batches permitted")
    batch_dir = ROOT / "testkit" / f"batch-{batch}"
    previous = list(batch_dir.glob("*/allocation.json"))
    if len(previous) >= 6 or any(not (p.parent / "result.json").exists() for p in previous):
        raise RuntimeError("Testkit quota or unresolved allocation")
    fixed = base.read_json(ROOT / "diagnostics" / case / "fixed.json")
    directory = batch_dir / name
    directory.mkdir(parents=True, exist_ok=False)
    request = {
        "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
        "comparison_semantics_version": "v0.2" if batch == 2 else "v0.1",
        "run_identity": f"v0203-{batch}-{name}",
        "source_snapshot_as_of": fixed["snapshot"],
        "memory_request": {
            "query": fixed["query"], "reference_time": fixed["reference_time"],
            "required_authority": "INFORMATIONAL",
            "requested_scope": {"project_ids": [fixed["project"]]},
            "budget": {"max_results": 50, "max_candidates": 120,
                       "max_context_tokens": 8192, "max_latency_ms": 5000},
        },
    }
    if name == "t3-empty-v2":
        request["memory_request"]["requested_scope"] = {"project_ids": ["v0203-empty-control"]}
    base.write_json(directory / "request.json", request)
    base.write_json(directory / "allocation.json", {
        "kind": "PRODUCT_TESTKIT", "model_allocations": 0, "pin": pin,
        "case": case, "batch": batch, "d1": d1, "timeout_seconds": 120,
        "source": fixed, "started_at": time.time(),
    })
    env = base._load_environment(ROOT / "runtime.env")
    env["MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED"] = str(d1).lower()
    started = time.perf_counter()
    try:
        with (directory / "stdout.json").open("w") as out, (
            directory / "stderr.txt"
        ).open("w") as err:
            proc = subprocess.run(  # noqa: S603 -- pinned public executable, JSON stdin
                [str(base.RUNTIME / ".venv/bin/milai-retrieval-trace-testkit")],
                input=json.dumps(request), text=True, stdout=out, stderr=err,
                env=base._clean_environment(env), cwd=base.RUNTIME, timeout=120, check=False,
            )
        result = {"status": "PASS" if proc.returncode == 0 else "REJECTED",
                  "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        result = {"status": "TIMEOUT"}
    result["elapsed_seconds"] = time.perf_counter() - started
    base.write_json(directory / "result.json", result)
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "resume-network", "capture", "trace"))
    parser.add_argument("--case", choices=("0a995998", "8550ddae", "852ce960"))
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--name", default="t2-count-d1")
    parser.add_argument("--d1-off", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        base.prepare(ROOT, config_path=CONFIG, runtime_overrides={
            "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
            "MILAI_RETRIEVAL_CONTINUATION_V0_1_ENABLED": "true",
            "MILAI_INTRA_SOURCE_ACQUISITION_V0_1_MODE": "SHADOW",
        })
    elif args.action == "resume-network":
        resume_network_setup()
    elif args.action == "capture":
        capture(args.case)
    else:
        trace(args.case, args.batch, args.name, not args.d1_off)


if __name__ == "__main__":
    main()
