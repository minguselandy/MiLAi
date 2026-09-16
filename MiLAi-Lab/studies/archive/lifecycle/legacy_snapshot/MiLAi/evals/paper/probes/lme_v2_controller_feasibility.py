"""Label-free official notes and AgentRunbook-R smoke with exact provider receipts."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.agent_efficiency import vllm_local_ab
from evals.paper.identity import sha256_file
from evals.paper.lme_v2_adapter import EXPECTED_CANDIDATE_ID, official_contract_identity
from evals.paper.probes.lme_v2_milai_adapter import _create_synthetic_inputs
from evals.paper.services.embedding_server import MODEL_ALIAS

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2")
DEFAULT_OUTPUT = (
    ROOT / "var/dg11/paper/runs/pe06-native-controller-smoke-20260824-001/result.json"
)
FROZEN_PYTHON = Path("/tmp/milai-dg11-paper-dg11-smoke-20260824-001/bin/python")
OFFICIAL_PYTHON = Path(
    "/tmp/milai-dg11-pe06-official-interface-20260824-001/bin/python"
)
VLLM_IDENTITY = ROOT / "docs/reports/DG-10-vllm-local-identity-2026-08-20.json"
EXPECTED_VLLM_IDENTITY_SHA256 = (
    "0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e"
)
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
SYNTHETIC_SOURCE_RESULT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/result.json"
)
METHODS = ("rag_query_to_slice_notes", "agentrunbook_r")


class ControllerSmokeError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise ControllerSmokeError(f"write-once artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get_json(url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ControllerSmokeError(f"service GET failed: {url}") from exc
    if len(raw) > 16 * 1024 * 1024:
        raise ControllerSmokeError("service response is oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ControllerSmokeError("service response is not JSON") from exc
    if not isinstance(value, dict):
        raise ControllerSmokeError("service response is not an object")
    return value


def _wait_ready(
    processes: tuple[subprocess.Popen[bytes], subprocess.Popen[bytes]],
    endpoints: tuple[tuple[str, str], tuple[str, str]],
) -> None:
    for _ in range(240):
        if any(process.poll() is not None for process in processes):
            raise ControllerSmokeError("paper service exited before readiness")
        ready = 0
        for url, key in endpoints:
            try:
                ready += int(_get_json(url + "/health", key).get("status") == "READY")
            except ControllerSmokeError:
                pass
        if ready == len(endpoints):
            return
        time.sleep(0.25)
    raise ControllerSmokeError("paper service readiness timed out")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _secret_file(root: Path, name: str, secret: str) -> Path:
    path = root / name
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _live_vllm_identity() -> dict[str, Any]:
    if sha256_file(VLLM_IDENTITY) != EXPECTED_VLLM_IDENTITY_SHA256:
        raise ControllerSmokeError("frozen vLLM identity artifact drifted")
    identity = json.loads(VLLM_IDENTITY.read_text(encoding="utf-8"))
    binding = identity.get("binding") if isinstance(identity, dict) else None
    if not isinstance(binding, dict):
        raise ControllerSmokeError("frozen vLLM binding is absent")
    try:
        vllm_local_ab._live_check(binding)
    except vllm_local_ab.LocalVllmCaptureError as exc:
        raise ControllerSmokeError("frozen vLLM live identity drifted") from exc
    service = binding["service"]
    return {
        "binding_sha256": identity["binding_sha256"],
        "identity_path": str(VLLM_IDENTITY.relative_to(ROOT)),
        "identity_sha256": EXPECTED_VLLM_IDENTITY_SHA256,
        "max_model_len": service["max_model_len"],
        "model_id": service["served_model_id"],
        "vllm_lifecycle_mutated": False,
        "vllm_version": service["vllm_version"],
    }


def _run_method(
    *,
    method: str,
    trajectories: Path,
    asset_root: Path,
    question_image: Path,
    target_screenshot: Path,
    embedding_url: str,
    controller_url: str,
    embedding_key: str,
    controller_key: str,
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PAPER_EMBEDDING_KEY"] = embedding_key
    environment["PAPER_CONTROLLER_KEY"] = controller_key
    environment["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            str(OFFICIAL_PYTHON),
            "-m",
            "evals.paper.runners.lme_v2_native",
            "--method",
            method,
            "--trajectories",
            str(trajectories),
            "--asset-root",
            str(asset_root),
            "--question-image",
            str(question_image),
            "--target-screenshot",
            str(target_screenshot),
            "--embedding-base-url",
            embedding_url,
            "--controller-base-url",
            controller_url,
        ],
        cwd=BENCHMARK_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        raise ControllerSmokeError(
            f"official {method} subprocess failed: {completed.stderr[-4000:]}"
        )
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ControllerSmokeError(f"official {method} receipt is invalid") from exc
    if (
        not isinstance(result, dict)
        or result.get("method") != method
        or result.get("paper_data_opened") is not False
        or result.get("question_rows_read") != 0
        or result.get("selected_target_screenshot") is not True
    ):
        raise ControllerSmokeError(f"official {method} receipt drifted")
    return result


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise ControllerSmokeError("PE06 native controller smoke is write-once")
    if not FROZEN_PYTHON.is_file() or not OFFICIAL_PYTHON.is_file():
        raise ControllerSmokeError("required isolated Python environment is absent")
    run_dir = output.parent
    paths = {
        "embedding_identity": run_dir / "embedding-service-identity.json",
        "controller_identity": run_dir / "controller-gateway-identity.json",
        "trajectories": run_dir / "synthetic-trajectories.json",
        "embedding_log": run_dir / "raw/embedding-server.log",
        "controller_log": run_dir / "raw/controller-gateway.log",
    }
    if any(path.exists() for path in paths.values()):
        raise ControllerSmokeError(
            "PE06 native controller smoke artifacts already exist"
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    paths["embedding_log"].parent.mkdir(parents=True, exist_ok=True)
    synthetic = _create_synthetic_inputs(
        SYNTHETIC_SOURCE_RESULT, reuse_identical_assets=True
    )
    _atomic_json_once(paths["trajectories"], synthetic["trajectories"])
    candidate_before = {
        "inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
        "manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
    }
    vllm_identity = _live_vllm_identity()
    embedding_port, controller_port = _free_port(), _free_port()
    if embedding_port == controller_port:
        controller_port = _free_port()
    embedding_url = f"http://127.0.0.1:{embedding_port}"
    controller_url = f"http://127.0.0.1:{controller_port}"
    embedding_key = secrets.token_urlsafe(48)
    controller_key = secrets.token_urlsafe(48)
    processes: list[subprocess.Popen[bytes]] = []
    method_results: dict[str, Any] = {}
    embedding_metrics: dict[str, Any] | None = None
    controller_metrics: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(
        prefix="milai-pe06-native-service-keys-"
    ) as directory:
        key_root = Path(directory)
        embedding_key_path = _secret_file(key_root, "embedding-key", embedding_key)
        controller_key_path = _secret_file(key_root, "controller-key", controller_key)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT)
        with (
            paths["embedding_log"].open("xb") as embedding_log,
            paths["controller_log"].open("xb") as controller_log,
        ):
            processes.append(
                subprocess.Popen(
                    [
                        str(FROZEN_PYTHON),
                        "-m",
                        "evals.paper.services.embedding_server",
                        "--port",
                        str(embedding_port),
                        "--api-key-file",
                        str(embedding_key_path),
                        "--identity-output",
                        str(paths["embedding_identity"]),
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=embedding_log,
                    stderr=subprocess.STDOUT,
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        str(FROZEN_PYTHON),
                        "-m",
                        "evals.paper.services.controller_gateway",
                        "--port",
                        str(controller_port),
                        "--api-key-file",
                        str(controller_key_path),
                        "--identity-output",
                        str(paths["controller_identity"]),
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=controller_log,
                    stderr=subprocess.STDOUT,
                )
            )
            try:
                _wait_ready(
                    (processes[0], processes[1]),
                    ((embedding_url, embedding_key), (controller_url, controller_key)),
                )
                for method in METHODS:
                    method_results[method] = _run_method(
                        method=method,
                        trajectories=paths["trajectories"],
                        asset_root=synthetic["asset_root"],
                        question_image=synthetic["paths"]["question"],
                        target_screenshot=synthetic["paths"]["target_confirmation"],
                        embedding_url=embedding_url,
                        controller_url=controller_url,
                        embedding_key=embedding_key,
                        controller_key=controller_key,
                    )
                embedding_metrics = _get_json(embedding_url + "/metrics", embedding_key)
                controller_metrics = _get_json(
                    controller_url + "/metrics", controller_key
                )
            finally:
                for process in reversed(processes):
                    _stop(process)
    if (
        len(processes) != 2
        or any(process.returncode != 0 for process in processes)
        or embedding_metrics is None
        or controller_metrics is None
    ):
        raise ControllerSmokeError("paper services did not terminate cleanly")
    if (
        embedding_metrics.get("request_count", 0) < 10
        or embedding_metrics.get("item_count", 0) < 14
        or controller_metrics.get("request_count", 0) < 8
        or controller_metrics.get("successful_count")
        != controller_metrics.get("request_count")
        or controller_metrics.get("failed_count") != 0
        or controller_metrics.get("total_tokens", 0) <= 0
    ):
        raise ControllerSmokeError("native controller provider accounting drifted")
    candidate_after = {
        "inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
        "manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
    }
    if candidate_after != candidate_before:
        raise ControllerSmokeError("frozen candidate changed during controller smoke")
    identities = {}
    for name in ("embedding_identity", "controller_identity"):
        identity = json.loads(paths[name].read_text(encoding="utf-8"))
        if not isinstance(identity, dict) or identity.get("status") != "READY":
            raise ControllerSmokeError(f"{name} is invalid")
        identities[name] = {
            "path": str(paths[name].relative_to(ROOT)),
            "sha256": sha256_file(paths[name]),
        }
    payload = {
        "benchmark_contract": official_contract_identity(),
        "candidate_after": candidate_after,
        "candidate_before": candidate_before,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "controller": {
            "effective_generation": {
                "disable_thinking_requested": False,
                "max_completion_tokens": 8192,
                "server_default_enable_thinking": False,
                "temperature": 0.6,
                "top_k": 20,
                "top_p": 0.95,
            },
            "metrics": controller_metrics,
            "model": "Qwen3.6-35B-A3B-FP8",
            "source": "evals/paper/services/controller_gateway.py",
            "source_sha256": sha256_file(
                ROOT / "evals/paper/services/controller_gateway.py"
            ),
        },
        "embedding": {
            "metrics": embedding_metrics,
            "model_request_id": MODEL_ALIAS,
            "projection_dimensions": 128,
            "source": "evals/paper/services/embedding_server.py",
            "source_sha256": sha256_file(
                ROOT / "evals/paper/services/embedding_server.py"
            ),
        },
        "identities": identities,
        "labels_accessed": False,
        "methods": method_results,
        "paper_question_rows_read": 0,
        "runner": {
            "path": "evals/paper/runners/lme_v2_native.py",
            "sha256": sha256_file(ROOT / "evals/paper/runners/lme_v2_native.py"),
        },
        "schema": "milai.dg11.pe06-native-controller-smoke.v1",
        "service_process_limit": 2,
        "status": "PASS",
        "synthetic_trajectories": {
            "path": str(paths["trajectories"].relative_to(ROOT)),
            "sha256": sha256_file(paths["trajectories"]),
        },
        "vllm": vllm_identity,
    }
    _atomic_json_once(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "schema": result["schema"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
