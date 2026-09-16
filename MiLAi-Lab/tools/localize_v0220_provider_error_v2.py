"""Seal a zero-model replay of installed input validation and public error conversion."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from v0220_evidence import LAB, read, save, seal, sha


def run(root: Path) -> dict:
    source = Path("/cra/memory/mx_memory/evidence/v0220/v2-candidate1-v1")
    request = source / "episodes/v2c1-01/v2c1-01-01-request.json"
    http = source / "episodes/v2c1-01/v2c1-01-01-http.json"
    script = LAB / "tools/v0220_provider_cpu_probe_v3.py"
    seal(
        root,
        entries=[Path(__file__), script],
        inputs=[request, http, source / "manifest.json"],
        contract={
            "authority": "New user Goal: full Schema Provider compatibility, error "
            "localization and unknown usage handling before deciding V2 resumption",
            "stage": "CPU_ERROR_LOCALIZATION",
            "model_requests": 0,
            "no_shared_service_changes": True,
            "container": "bcec1ef46198",
        },
    )
    completed = subprocess.run(  # noqa: S603 - owned probe code, fixed CPU subprocess
        ["/usr/bin/docker", "exec", "-i", "bcec1ef46198", "python3", "-c", script.read_text()],
        input=request.read_text(),
        capture_output=True,
        text=True,
        timeout=45,
    )
    save(
        root / "process.json",
        {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode:
        raise ValueError("CPU_PROBE_PROCESS_FAILED")
    value = json.loads(completed.stdout.splitlines()[-1])
    save(root / "probe.json", value)
    assert value["counts"] == {
        "input_validation_entered": 1,
        "post_validation_reached": 0,
        "engine_submissions": 0,
    }
    assert value["observed"]["cause_type"] == "ValueError"
    assert "uniqueItems" in value["observed"]["cause_message"]
    assert value["observed"]["public_error"] == json.loads(read(http)["body"])
    result = {
        "status": "EXACT_PUBLIC_HTTP500_SHAPE_REPRODUCED_FROM_PRE_ENGINE_SCHEMA_REJECTION",
        "failed_request_sha256": sha(request),
        "path": "uniqueItems -> vLLM XGrammar rejection -> Guidance ValueError -> "
        "AsyncLLM.generate wraps plain exception as empty EngineGenerateError -> HTTP500",
        "engine_submissions_in_reproduction": 0,
        "model_requests": 0,
        "historical_usage": "Still unresolved: this is a controlled code-path reproduction, "
        "not a recovered per-request engine/usage receipt. Old reservation is untouched.",
        "original_failure_attribution": "Strong matching deterministic validation/wrapper path; "
        "historical stack was not logged, so independent concurrent infrastructure faults "
        "are not retrospectively ruled out.",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
