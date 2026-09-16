"""Replay reviewed historical reads in isolated no-network containers; never invoke Codex."""

# Fixed Docker commands with immutable image identity and isolated, reviewed replay inputs.
# ruff: noqa: S603, S607

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from audit_v02_task_cost import EXPECTED, LAB, LEDGER, sha
from v02_readable_container import augment_profile, docker_command, load_environment

ROOT = LAB / "artifacts/v02-cost-first/run-20260906a"


def main() -> None:
    assert sha(LEDGER.read_bytes()) == EXPECTED
    config = load_environment()
    image = subprocess.check_output(["docker", "image", "inspect", config["image_id"],
                                     "--format", "{{.Id}}"], text=True).strip()
    assert image == config["image_id"]
    audit = json.loads((ROOT / "cost-audit.json").read_text())
    results = []
    for allocation in json.loads(LEDGER.read_text())["allocations"]:
        if allocation["arm"] == "G":
            continue
        original = LAB / allocation["artifact"]
        directory = ROOT / "replay" / allocation["allocation_id"]
        directory.mkdir(parents=True, exist_ok=False)
        workspace, home = directory / "workspace", directory / "home"
        home.mkdir()
        prior = Path(json.loads((original / "host-paths.json").read_text())["workspace"])
        assert not any(p.is_symlink() for p in prior.rglob("*"))
        shutil.copytree(prior, workspace)
        source_hash = sha((workspace / "sources/history.json").read_bytes())
        shutil.copy2(LAB / "tools/v02_readable_smoke_worker.py", workspace / "smoke.py")
        event_bytes = (original / "events.jsonl").read_bytes()
        evidence = next(s for s in audit["sessions"]
                        if s["allocation_id"] == allocation["allocation_id"])
        assert sha(event_bytes) == evidence["events_sha256"]
        events = [json.loads(s) for s in event_bytes.decode().splitlines()]
        jobs = [e["item"] for e in events if e.get("type") == "item.completed"
                and e.get("item", {}).get("type") == "command_execution"
                and e["item"]["exit_code"] != 0]
        (workspace / "jobs.json").write_text(json.dumps(jobs))
        (directory / "profile-with-capabilities.toml").write_text(
            augment_profile((original / "host-profile.toml").read_text()))
        name = "v0204-read-" + allocation["allocation_id"].lower().replace("_", "-")
        args = docker_command(image, workspace, home, Path(shutil.which("codex")).resolve(),
                              Path(shutil.which("rg")).resolve(), name, network="none",
                              entrypoint="python3")
        started = time.perf_counter()
        try:
            run = subprocess.run([*args, "smoke.py"], capture_output=True, timeout=120,
                                 env={"PATH": os.environ["PATH"]})
        finally:
            subprocess.run(["docker", "stop", "--time", "1", name],
                           capture_output=True, check=False)
        (directory / "stdout").write_bytes(run.stdout)
        (directory / "stderr").write_bytes(run.stderr)
        assert run.returncode == 0, f"Container smoke failed: {directory}"
        result = json.loads(run.stdout)
        result.update({"allocation_id": allocation["allocation_id"], "image_id": image,
                       "elapsed_seconds": time.perf_counter() - started, "network": "none"})
        assert sha((workspace / "sources/history.json").read_bytes()) == source_hash
        assert source_hash == sha((prior / "sources/history.json").read_bytes())
        (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        results.append(result)
        print(json.dumps({"allocation": allocation["allocation_id"], "status": result["status"]}),
              flush=True)
    output = {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "ERRORS",
              "image_id": image, "new_model_allocations": 0, "new_model_tokens": 0,
              "replayed_commands": sum(len(r["commands"]) for r in results), "results": results}
    (ROOT / "smoke-results.json").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
