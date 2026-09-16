from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIRECTORY = ROOT / "evals/agent_efficiency"
for candidate in (ROOT, EVAL_DIRECTORY):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import vllm_local_identity as local_identity

from scripts import dg10_remediation as remediation

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
VLLM_VERSION = "0.27.1"
IDENTITY_SHA256 = "0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e"
DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_IDENTITY = ROOT / "docs/reports/DG-10-vllm-local-identity-2026-08-20.json"
DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-model-probe-candidate.4-2026-08-22.json"
MAX_RESPONSE_BYTES = 1024 * 1024


class ModelProbeError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ModelProbeError(reason)


def _object(value: object, reason: str) -> dict[str, Any]:
    _require(isinstance(value, dict), reason)
    return value


def _get_json(base_url: str, path: str, *, timeout: float) -> tuple[dict[str, Any], str]:
    _require(path in {"/v1/models", "/version"}, "model probe path is not allowlisted")
    request = urllib.request.Request(base_url + path, method="GET")
    try:
        with local_identity.local_opener().open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except (OSError, urllib.error.URLError) as exc:
        raise ModelProbeError("local vLLM read-only probe failed") from exc
    _require(status == 200 and len(raw) <= MAX_RESPONSE_BYTES, "local vLLM probe response invalid")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelProbeError("local vLLM probe response is not JSON") from exc
    return _object(value, "local vLLM probe response is not an object"), hashlib.sha256(raw).hexdigest()


def _inspect_container(container_id: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["docker", "inspect", container_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ModelProbeError("container read-only inspection failed") from exc
    _require(completed.returncode == 0 and not completed.stderr, "container inspection failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ModelProbeError("container inspection is not JSON") from exc
    _require(isinstance(value, list) and len(value) == 1, "container inspection cardinality drift")
    return _object(value[0], "container inspection row invalid")


def build_probe(*, base_url: str, identity_report: Path, timeout: float) -> dict[str, Any]:
    base = local_identity.strict_base_url(base_url)
    identity_report = identity_report.resolve()
    _require(
        identity_report.is_file()
        and not identity_report.is_symlink()
        and remediation.sha256_file(identity_report) == IDENTITY_SHA256,
        "frozen vLLM identity report drift",
    )
    try:
        frozen = json.loads(identity_report.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelProbeError("frozen vLLM identity report invalid") from exc
    frozen = _object(frozen, "frozen vLLM identity root invalid")
    binding = _object(frozen.get("binding"), "frozen vLLM binding absent")
    _require(
        local_identity.sha256_bytes(local_identity.canonical_bytes(binding))
        == frozen.get("binding_sha256"),
        "frozen vLLM binding digest drift",
    )
    service = _object(binding.get("service"), "frozen vLLM service binding absent")
    container = _object(binding.get("container"), "frozen container binding absent")
    model = _object(binding.get("model"), "frozen model binding absent")
    _require(
        service.get("base_url") == base
        and service.get("served_model_id") == MODEL_ID
        and service.get("vllm_version") == VLLM_VERSION
        and service.get("max_model_len") == 65536,
        "requested model service differs from frozen binding",
    )

    models_response, models_raw_sha256 = _get_json(base, "/v1/models", timeout=timeout)
    version_response, version_raw_sha256 = _get_json(base, "/version", timeout=timeout)
    rows = models_response.get("data")
    _require(
        models_response.get("object") == "list" and isinstance(rows, list) and len(rows) == 1,
        "live model list cardinality drift",
    )
    row = _object(rows[0], "live model row invalid")
    _require(
        row.get("id") == MODEL_ID
        and row.get("root") == service.get("served_model_root")
        and row.get("max_model_len") == service.get("max_model_len")
        and version_response == {"version": VLLM_VERSION},
        "live served model identity drift",
    )

    current_container = _inspect_container(str(container.get("id")))
    current_state = _object(current_container.get("State"), "container state absent")
    current_config = _object(current_container.get("Config"), "container config absent")
    current_host_config = _object(current_container.get("HostConfig"), "container host config absent")
    entrypoint = current_config.get("Entrypoint")
    command = current_config.get("Cmd")
    _require(
        current_container.get("Id") == container.get("id")
        and current_container.get("Image") == container.get("image_id")
        and current_container.get("RestartCount") == container.get("restart_count") == 0
        and current_state.get("Running") is True
        and current_state.get("StartedAt") == container.get("started_at")
        and isinstance(entrypoint, list)
        and isinstance(command, list)
        and entrypoint[1:] + command == container.get("argv")
        and current_host_config.get("PortBindings") == container.get("port_bindings"),
        "live vLLM container identity or lifecycle drift",
    )

    model_root = model.get("host_path")
    _require(isinstance(model_root, str), "frozen model root absent")
    current_model = local_identity.model_closure(Path(model_root), progress=False)
    _require(current_model == model, "served model byte closure drift")

    return {
        "schema": "milai.dg10.model-readonly-probe.v1",
        "candidate_id": remediation.CANDIDATE,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS_READ_ONLY_MODEL_AND_LIFECYCLE_REVALIDATION",
        "identity_report": {
            "path": identity_report.relative_to(ROOT).as_posix(),
            "sha256": IDENTITY_SHA256,
            "binding_sha256": frozen["binding_sha256"],
        },
        "service": {
            "base_url_class": "LOOPBACK_LOCAL_VLLM",
            "served_model_id": MODEL_ID,
            "vllm_version": VLLM_VERSION,
            "max_model_len": 65536,
            "models_response_sha256": models_raw_sha256,
            "version_response_sha256": version_raw_sha256,
        },
        "container": {
            "container_id_sha256": remediation.sha256_bytes(str(container["id"]).encode()),
            "image_id": container["image_id"],
            "started_at": container["started_at"],
            "restart_count": 0,
            "running": True,
            "lifecycle_mutated": False,
        },
        "model_byte_closure": {
            "file_count": current_model["file_count"],
            "total_bytes": current_model["total_bytes"],
            "entries_sha256": current_model["entries_sha256"],
            "exact_match_to_frozen_identity": True,
        },
        "requests": {
            "read_only_http_get_count": 2,
            "container_inspect_count": 1,
            "model_completion_count": 0,
            "tokenizer_request_count": 0,
            "external_provider_request_count": 0,
        },
        "model_run_authorized": False,
        "independent_acceptance": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DG-10 candidate.4 read-only model probe")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--identity-report", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_probe(
        base_url=args.base_url,
        identity_report=args.identity_report,
        timeout=args.timeout,
    )
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
