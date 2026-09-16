from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DATE = "2026-08-20"
DEFAULT_CONTAINER_ID = (
    "bcec1ef46198559a99c4c4b0a89fc1fa34382123df121464b5393e491485050f"
)
DEFAULT_MODEL_ROOT = Path("/cra/qwen36-35B")
DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_OUTPUT = ROOT / f"docs/reports/DG-10-vllm-local-identity-{DATE}.json"


class LocalVllmIdentityError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_base_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise LocalVllmIdentityError("invalid local vLLM port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise LocalVllmIdentityError(
            "vLLM target must be one explicit 127.0.0.1 HTTP origin"
        )
    return f"http://127.0.0.1:{port}"


def local_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )


def http_bytes(base_url: str, path: str, *, timeout: float = 10) -> tuple[int, bytes]:
    base = strict_base_url(base_url)
    if not path.startswith("/") or path.startswith("//"):
        raise LocalVllmIdentityError("invalid vLLM endpoint path")
    request = urllib.request.Request(base + path, method="GET")
    try:
        with local_opener().open(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise LocalVllmIdentityError("local vLLM endpoint unavailable") from exc


def http_json(base_url: str, path: str) -> dict[str, Any]:
    status_code, raw = http_bytes(base_url, path)
    if status_code != 200:
        raise LocalVllmIdentityError("local vLLM endpoint did not return HTTP 200")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalVllmIdentityError("local vLLM endpoint returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise LocalVllmIdentityError("local vLLM endpoint returned a non-object")
    return value


def run_json(command: list[str]) -> Any:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise LocalVllmIdentityError(
            f"identity command failed with status {completed.returncode}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocalVllmIdentityError("identity command returned invalid JSON") from exc


def _file_metadata(path: Path, root: Path) -> dict[str, Any]:
    current = path.lstat()
    if not stat.S_ISREG(current.st_mode) or stat.S_ISLNK(current.st_mode):
        raise LocalVllmIdentityError("model closure contains a non-regular file")
    return {
        "path": path.relative_to(root).as_posix(),
        "device": current.st_dev,
        "inode": current.st_ino,
        "size": current.st_size,
        "mtime_ns": current.st_mtime_ns,
        "mode": f"{stat.S_IMODE(current.st_mode):04o}",
        "uid": current.st_uid,
        "gid": current.st_gid,
    }


def model_closure(model_root: Path, *, progress: bool = False) -> dict[str, Any]:
    if not model_root.is_absolute() or model_root.resolve() != model_root:
        raise LocalVllmIdentityError("model root must be an absolute non-symlink path")
    root_stat = model_root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise LocalVllmIdentityError("model root must be a regular directory")
    candidates = sorted(model_root.rglob("*"))
    paths: list[Path] = []
    for candidate in candidates:
        current = candidate.lstat()
        if stat.S_ISLNK(current.st_mode):
            raise LocalVllmIdentityError("model closure contains a symlink")
        if stat.S_ISDIR(current.st_mode):
            continue
        if not stat.S_ISREG(current.st_mode):
            raise LocalVllmIdentityError("model closure contains a special file")
        paths.append(candidate)
    if not paths:
        raise LocalVllmIdentityError("model closure is empty")
    before = [_file_metadata(path, model_root) for path in paths]
    entries: list[dict[str, Any]] = []
    for index, (path, metadata) in enumerate(zip(paths, before, strict=True), start=1):
        entries.append(
            {
                "path": metadata["path"],
                "size": metadata["size"],
                "sha256": sha256_file(path),
            }
        )
        if progress and (index == len(paths) or index % 5 == 0):
            print(
                json.dumps(
                    {
                        "event": "MODEL_HASH_PROGRESS",
                        "completed": index,
                        "total": len(paths),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
                flush=True,
            )
    after_paths = sorted(
        path for path in model_root.rglob("*") if path.is_file() or path.is_symlink()
    )
    if after_paths != paths:
        raise LocalVllmIdentityError("model closure membership changed while hashing")
    after = [_file_metadata(path, model_root) for path in paths]
    if before != after:
        raise LocalVllmIdentityError("model closure metadata changed while hashing")
    root_after = model_root.lstat()
    root_identity = {
        "device": root_stat.st_dev,
        "inode": root_stat.st_ino,
        "mode": f"{stat.S_IMODE(root_stat.st_mode):04o}",
        "uid": root_stat.st_uid,
        "gid": root_stat.st_gid,
    }
    if root_identity != {
        "device": root_after.st_dev,
        "inode": root_after.st_ino,
        "mode": f"{stat.S_IMODE(root_after.st_mode):04o}",
        "uid": root_after.st_uid,
        "gid": root_after.st_gid,
    }:
        raise LocalVllmIdentityError("model root changed while hashing")
    return {
        "host_path": str(model_root),
        "root_identity": root_identity,
        "file_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "entries_sha256": sha256_bytes(canonical_bytes(entries)),
        "entries": entries,
    }


def _descendants(root_pid: int) -> set[int]:
    parents: dict[int, int] = {}
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            values = {
                line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                for line in status_path.read_text(encoding="utf-8").splitlines()
                if ":" in line
            }
            parents[int(status_path.parent.name)] = int(values["PPid"])
        except (OSError, KeyError, ValueError):
            continue
    result = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in result and pid not in result:
                result.add(pid)
                changed = True
    return result


def accelerator_identity(container_pid: int) -> dict[str, Any]:
    inventory = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    applications = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,gpu_uuid",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if inventory.returncode != 0 or applications.returncode != 0:
        raise LocalVllmIdentityError("NVIDIA identity is unavailable")
    gpu_by_uuid: dict[str, dict[str, Any]] = {}
    for line in inventory.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 6:
            raise LocalVllmIdentityError("unexpected NVIDIA inventory response")
        index, name, uuid, driver, memory, capability = parts
        gpu_by_uuid[uuid] = {
            "index_at_observation": int(index),
            "name": name,
            "uuid": uuid,
            "driver_version": driver,
            "memory_total_mib": int(memory),
            "compute_capability": capability,
        }
    descendants = _descendants(container_pid)
    selected: set[str] = set()
    for line in applications.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid in descendants:
            selected.add(parts[1])
    if not selected or not selected.issubset(gpu_by_uuid):
        raise LocalVllmIdentityError("vLLM GPU assignment cannot be resolved")
    return {
        "tensor_parallel_gpu_count": len(selected),
        "gpus": [gpu_by_uuid[uuid] for uuid in sorted(selected)],
    }


def collect_binding(
    container_id: str,
    model_root: Path,
    base_url: str,
    *,
    progress: bool = False,
) -> dict[str, Any]:
    base = strict_base_url(base_url)
    inspected = run_json(["docker", "container", "inspect", container_id])
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise LocalVllmIdentityError("container identity is ambiguous")
    container = inspected[0]
    if not isinstance(container, dict) or container.get("Id") != container_id:
        raise LocalVllmIdentityError("container identity drift")
    state = container.get("State") or {}
    if state.get("Status") != "running" or int(container.get("RestartCount", -1)) != 0:
        raise LocalVllmIdentityError("vLLM container is not continuously running")
    image_id = container.get("Image")
    images = run_json(["docker", "image", "inspect", str(image_id)])
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise LocalVllmIdentityError("image identity is ambiguous")
    image = images[0]
    mounts = [
        {
            "type": item.get("Type"),
            "source": item.get("Source"),
            "destination": item.get("Destination"),
            "rw": item.get("RW"),
        }
        for item in container.get("Mounts") or []
    ]
    model_mounts = [
        item
        for item in mounts
        if item["source"] == str(model_root) and item["destination"] == "/models"
    ]
    if len(model_mounts) != 1:
        raise LocalVllmIdentityError("exact model mount is absent")
    health_status, health_body = http_bytes(base, "/health")
    if health_status != 200 or health_body:
        raise LocalVllmIdentityError("unexpected vLLM health response")
    version = http_json(base, "/version")
    models = http_json(base, "/v1/models")
    model_values = models.get("data")
    if not isinstance(model_values, list) or len(model_values) != 1:
        raise LocalVllmIdentityError("vLLM must expose exactly one model")
    served = model_values[0]
    if not isinstance(served, dict):
        raise LocalVllmIdentityError("vLLM model response is malformed")
    openapi_status, openapi_bytes = http_bytes(base, "/openapi.json")
    if openapi_status != 200:
        raise LocalVllmIdentityError("vLLM OpenAPI schema is unavailable")
    labels = (image.get("Config") or {}).get("Labels") or {}
    return {
        "schema": "milai.pvlocal.vllm-binding.v1",
        "container": {
            "id": container_id,
            "name": str(container.get("Name", "")).removeprefix("/"),
            "image_id": image_id,
            "created": container.get("Created"),
            "started_at": state.get("StartedAt"),
            "restart_count": container.get("RestartCount"),
            "argv": container.get("Args"),
            "network_mode": (container.get("HostConfig") or {}).get("NetworkMode"),
            "port_bindings": (container.get("HostConfig") or {}).get("PortBindings"),
            "mounts": mounts,
            "environment_names": sorted(
                value.split("=", 1)[0]
                for value in (container.get("Config") or {}).get("Env") or []
            ),
        },
        "image": {
            "id": image.get("Id"),
            "repo_digests": sorted(image.get("RepoDigests") or []),
            "created": image.get("Created"),
            "os": image.get("Os"),
            "architecture": image.get("Architecture"),
            "vllm_version_label": labels.get("ai.vllm.image.tag"),
            "vllm_revision": labels.get("ai.vllm.build.commit"),
        },
        "service": {
            "base_url": base,
            "vllm_version": version.get("version"),
            "served_model_id": served.get("id"),
            "served_model_root": served.get("root"),
            "max_model_len": served.get("max_model_len"),
            "openapi_sha256": sha256_bytes(openapi_bytes),
        },
        "model": model_closure(model_root, progress=progress),
        "accelerator": accelerator_identity(int(state.get("Pid", 0))),
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_report(
    container_id: str, model_root: Path, base_url: str, *, progress: bool = False
) -> dict[str, Any]:
    binding = collect_binding(
        container_id, model_root.resolve(), base_url, progress=progress
    )
    return {
        "schema": "milai.pvlocal.vllm-identity.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "LOCAL_TARGET_OBSERVED_REVERIFY_REQUIRED",
        "data_boundary": "SYNTHETIC_OR_DEIDENTIFIED_ONLY",
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "vllm_lifecycle_mutated": False,
        "binding_sha256": sha256_bytes(canonical_bytes(binding)),
        "binding": binding,
        "known_limits": [
            "The existing vLLM process was observed and called; it was not started, stopped, restarted, or reconfigured.",
            "The existing model bind mount is writable and the service listens on 0.0.0.0; pre/post identity re-verification is mandatory.",
            "Self-hosted inference has no upstream billing export and cannot close OE-F06.",
            "This author-generated identity requires independent re-verification.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Observe and hash one already-running local vLLM target"
    )
    parser.add_argument("--container-id", default=DEFAULT_CONTAINER_ID)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(
        args.container_id,
        args.model_root,
        args.base_url,
        progress=True,
    )
    atomic_write(args.output.resolve(), report)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "binding_sha256": report["binding_sha256"],
                "model_entries_sha256": report["binding"]["model"][
                    "entries_sha256"
                ],
                "model_file_count": report["binding"]["model"]["file_count"],
                "model_total_bytes": report["binding"]["model"]["total_bytes"],
                "status": report["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
