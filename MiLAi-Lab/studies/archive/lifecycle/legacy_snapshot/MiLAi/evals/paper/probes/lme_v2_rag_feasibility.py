"""Label-free official RAG smoke over the frozen local embedding service."""

from __future__ import annotations

import argparse
import hashlib
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

from evals.paper.identity import sha256_file
from evals.paper.lme_v2_adapter import (
    EXPECTED_CANDIDATE_ID,
    official_contract_identity,
)
from evals.paper.probes.lme_v2_milai_adapter import (
    _create_synthetic_inputs,
)
from evals.paper.services.embedding_server import MODEL_ALIAS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = (
    ROOT / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-003/result.json"
)
FROZEN_PYTHON = Path("/tmp/milai-dg11-paper-dg11-smoke-20260824-001/bin/python")
OFFICIAL_PYTHON = Path(
    "/tmp/milai-dg11-pe06-official-interface-20260824-001/bin/python"
)
CANDIDATE_MANIFEST = ROOT / "var/dg11/freeze/candidate/candidate-manifest.json"
CANDIDATE_INVENTORY = ROOT / "var/dg11/final/candidate/inventory.json"
SYNTHETIC_SOURCE_RESULT = (
    ROOT / "var/dg11/paper/runs/pe06-milai-adapter-smoke-20260824-002/result.json"
)
SUPERSEDED_FAILURES = (
    ROOT
    / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-001/failure-disclosure.json",
    ROOT
    / "var/dg11/paper/runs/pe06-native-rag-smoke-20260824-002/failure-disclosure.json",
)


class LMEV2RagSmokeError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise LMEV2RagSmokeError(f"write-once artifact exists: {path}")
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
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise LMEV2RagSmokeError(f"embedding service GET failed: {url}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise LMEV2RagSmokeError("embedding service response is oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LMEV2RagSmokeError("embedding service response is not JSON") from exc
    if not isinstance(value, dict):
        raise LMEV2RagSmokeError("embedding service response is not an object")
    return value


def _wait_ready(process: subprocess.Popen[bytes], base_url: str, api_key: str) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise LMEV2RagSmokeError("embedding service exited before readiness")
        try:
            if _get_json(base_url + "/health", api_key).get("status") == "READY":
                return
        except LMEV2RagSmokeError:
            time.sleep(0.25)
    raise LMEV2RagSmokeError("embedding service readiness timed out")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _official_environment_identity(python: Path) -> dict[str, Any]:
    code = """
import importlib.metadata
import json
import pathlib
import sys
import memory_modules
rows = sorted(
    ({"name": dist.metadata["Name"], "version": dist.version} for dist in importlib.metadata.distributions()),
    key=lambda item: (str(item["name"]).casefold(), str(item["version"])),
)
print(json.dumps({
    "distributions": rows,
    "memory_modules_origin": str(pathlib.Path(memory_modules.__file__).resolve()),
    "python_executable": sys.executable,
    "python_prefix": sys.prefix,
    "python_version": sys.version,
}, sort_keys=True))
""".strip()
    completed = subprocess.run(
        [str(python), "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LMEV2RagSmokeError("official environment identity is invalid") from exc
    if not isinstance(value, dict) or not isinstance(value.get("distributions"), list):
        raise LMEV2RagSmokeError("official environment identity contract drifted")
    value["distribution_identity_sha256"] = hashlib.sha256(
        json.dumps(
            value["distributions"], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    value["python_invocation"] = str(python.absolute())
    return value


def _run_official_rag(
    *,
    python: Path,
    trajectories_path: Path,
    asset_root: Path,
    question_image: Path,
    target_screenshot: Path,
    base_url: str,
    api_key: str,
) -> dict[str, Any]:
    code = """
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from memory_modules.memory import MEMORY_TYPES

RagMemory = MEMORY_TYPES["rag"]

trajectories = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
asset_root = Path(sys.argv[2]).resolve()
question_image = Path(sys.argv[3]).resolve()
target_screenshot = Path(sys.argv[4]).resolve()
base_url = sys.argv[5]
model = sys.argv[6]
query = "What is shown in the backup confirmation for Vault Alpha?"
with tempfile.TemporaryDirectory(prefix="milai-pe06-rag-workspace-") as workspace:
    memory = RagMemory({
        "trajectory_pool_root": None,
        "workspace_dir": workspace,
        "trajectories_root_dir": str(asset_root),
        "controller_params": {
            "model": "UNUSED_FOR_RAW_ONLY_RAG",
            "base_url": "http://127.0.0.1:1/v1",
            "api_key_env": "PAPER_EMBEDDING_KEY",
            "api_key_file": None,
            "max_completion_tokens": 8192,
            "timeout_seconds": 600.0,
            "max_retries": 0,
            "disable_thinking": True,
            "temperature": 0.0,
            "top_p": 1.0,
            "top_k": 1,
        },
        "embedding_params": {
            "model": model,
            "base_url": base_url + "/v1",
            "api_key_env": "PAPER_EMBEDDING_KEY",
            "api_key_file": None,
            "max_input_tokens": 256,
            "query_instruction": "Given a question about past agent trajectories, retrieve relevant memory entries that help answer it.",
        },
        "index_params": {"raw_state_slice_radius": 1},
        "retrieval_params": {
            "enable_notes": False,
            "raw_state_search_top_k": 6,
            "note_search_top_k_per_type": 3,
        },
    })
    memory.configure_runtime()
    for trajectory in trajectories:
        memory.insert(trajectory)
    items = memory.query(query, query_image=str(question_image))
    records = []
    selected_target = False
    for item in items:
        if item["type"] == "image":
            path = Path(item["value"]).resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            selected_target = selected_target or digest == hashlib.sha256(target_screenshot.read_bytes()).hexdigest()
            records.append({"bytes": path.stat().st_size, "sha256": digest, "type": "image"})
        else:
            raw = item["value"].encode("utf-8")
            records.append({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "type": "text"})
    print(json.dumps({
        "embedding_dimensions": int(memory.raw_state_embeddings.shape[1]),
        "inserted_trajectory_ids": memory.inserted_trajectory_ids,
        "item_records": records,
        "paper_data_opened": False,
        "query_image_passed": True,
        "question_rows_read": 0,
        "raw_state_entry_count": len(memory.raw_state_entries),
        "selected_target_screenshot": selected_target,
    }, sort_keys=True))
""".strip()
    environment = dict(os.environ)
    environment["PAPER_EMBEDDING_KEY"] = api_key
    completed = subprocess.run(
        [
            str(python),
            "-c",
            code,
            str(trajectories_path),
            str(asset_root),
            str(question_image),
            str(target_screenshot),
            base_url,
            MODEL_ALIAS,
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        cwd=Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2"),
        timeout=300,
    )
    if completed.returncode != 0:
        raise LMEV2RagSmokeError(
            "official RAG subprocess failed: " + completed.stderr[-2000:]
        )
    try:
        value = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LMEV2RagSmokeError("official RAG receipt is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("paper_data_opened") is not False
        or value.get("question_rows_read") != 0
        or value.get("query_image_passed") is not True
        or value.get("selected_target_screenshot") is not True
        or value.get("embedding_dimensions") != 128
        or value.get("inserted_trajectory_ids")
        != ["trajectory-target", "trajectory-calendar", "trajectory-billing"]
    ):
        raise LMEV2RagSmokeError("official RAG synthetic contract failed")
    return value


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        raise LMEV2RagSmokeError("PE06 native RAG smoke result is write-once")
    if not FROZEN_PYTHON.is_file() or not OFFICIAL_PYTHON.is_file():
        raise LMEV2RagSmokeError("required isolated Python environment is absent")
    if any(not path.is_file() for path in SUPERSEDED_FAILURES):
        raise LMEV2RagSmokeError("superseded native RAG failure disclosure is absent")
    run_dir = output.parent
    identity_output = run_dir / "embedding-service-identity.json"
    trajectories_output = run_dir / "synthetic-trajectories.json"
    raw_log = run_dir / "raw/embedding-server.log"
    if identity_output.exists() or trajectories_output.exists() or raw_log.exists():
        raise LMEV2RagSmokeError("PE06 native RAG smoke artifacts already exist")
    synthetic = _create_synthetic_inputs(
        SYNTHETIC_SOURCE_RESULT, reuse_identical_assets=True
    )
    _atomic_json_once(trajectories_output, synthetic["trajectories"])
    candidate_before = {
        "inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
        "manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
    }
    official_contract = official_contract_identity()
    official_environment = _official_environment_identity(OFFICIAL_PYTHON)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    api_key = secrets.token_urlsafe(48)
    process: subprocess.Popen[bytes] | None = None
    metrics: dict[str, Any] | None = None
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="milai-pe06-embedding-key-") as key_dir:
        key_path = Path(key_dir) / "api-key"
        descriptor = os.open(
            key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(api_key + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT)
        with raw_log.open("xb") as log_handle:
            process = subprocess.Popen(
                [
                    str(FROZEN_PYTHON),
                    "-m",
                    "evals.paper.services.embedding_server",
                    "--port",
                    str(port),
                    "--api-key-file",
                    str(key_path),
                    "--identity-output",
                    str(identity_output),
                ],
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_ready(process, base_url, api_key)
                rag = _run_official_rag(
                    python=OFFICIAL_PYTHON,
                    trajectories_path=trajectories_output,
                    asset_root=synthetic["asset_root"],
                    question_image=synthetic["paths"]["question"],
                    target_screenshot=synthetic["paths"]["target_confirmation"],
                    base_url=base_url,
                    api_key=api_key,
                )
                metrics = _get_json(base_url + "/metrics", api_key)
            finally:
                _stop(process)
    if process is None or process.returncode != 0 or metrics is None:
        raise LMEV2RagSmokeError("embedding service did not terminate cleanly")
    identity = json.loads(identity_output.read_text(encoding="utf-8"))
    if (
        not isinstance(identity, dict)
        or identity.get("status") != "READY"
        or identity.get("provider", {}).get("dimensions") != 128
        or identity.get("api", {}).get("model_alias") != MODEL_ALIAS
        or metrics.get("request_count") != 4
        or metrics.get("item_count") != 5
    ):
        raise LMEV2RagSmokeError("embedding service accounting drifted")
    candidate_after = {
        "inventory_sha256": sha256_file(CANDIDATE_INVENTORY),
        "manifest_sha256": sha256_file(CANDIDATE_MANIFEST),
    }
    if candidate_before != candidate_after:
        raise LMEV2RagSmokeError("frozen candidate changed during RAG smoke")
    payload = {
        "benchmark_contract": official_contract,
        "candidate_after": candidate_after,
        "candidate_before": candidate_before,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "embedding_service": {
            "identity": str(identity_output.relative_to(ROOT)),
            "identity_sha256": sha256_file(identity_output),
            "metrics": metrics,
            "model_request_id": MODEL_ALIAS,
            "source": "evals/paper/services/embedding_server.py",
            "source_sha256": sha256_file(
                ROOT / "evals/paper/services/embedding_server.py"
            ),
        },
        "labels_accessed": False,
        "official_environment": official_environment,
        "paper_question_rows_read": 0,
        "rag": rag,
        "schema": "milai.dg11.pe06-native-rag-smoke.v1",
        "status": "PASS",
        "superseded_smokes": [
            {
                "path": str(path.relative_to(ROOT)),
                "result_use": "EXCLUDED_DEVELOPMENT_SMOKE",
                "sha256": sha256_file(path),
            }
            for path in SUPERSEDED_FAILURES
        ],
        "synthetic_trajectories": {
            "path": str(trajectories_output.relative_to(ROOT)),
            "sha256": sha256_file(trajectories_output),
        },
        "visual_only_retrieval_supported": False,
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
