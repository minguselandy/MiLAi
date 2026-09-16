from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_TAG = "openworker-v2:2026.5.9.1"
BASE_ID = "sha256:afa555cfccdb05c0e8a4a0b1ad84f364496d8721d45c9dbd796a7afbe5e7f05d"
OUTPUT = (
    ROOT
    / "integrations/openworker-mcp/wheelhouse/cp312-musllinux_1_2_x86_64-candidate.2"
)
LOCAL_WHEELS = (
    ROOT / "integrations/python-client/dist/milai_client-0.1.0-py3-none-any.whl",
    ROOT / "integrations/mcp/dist/milai_mcp-0.1.0-py3-none-any.whl",
)


def _run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        stdout_tail = completed.stdout[-4000:]
        stderr_tail = completed.stderr[-4000:]
        raise RuntimeError(
            "bounded subprocess failure\n"
            f"stdout_tail={stdout_tail!r}\n"
            f"stderr_tail={stderr_tail!r}"
        )
    return completed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _docker_image() -> dict[str, Any]:
    value = json.loads(_run(["docker", "image", "inspect", BASE_TAG]).stdout)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise RuntimeError("unexpected Docker image inspection response")
    image = value[0]
    if image.get("Id") != BASE_ID:
        raise RuntimeError("OpenWorker base image identity drift")
    if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
        raise RuntimeError("OpenWorker base image platform drift")
    return image


def _third_party_requirements() -> str:
    completed = _run(
        [
            "uv",
            "export",
            "--project",
            "integrations/mcp",
            "--frozen",
            "--no-dev",
            "--format",
            "requirements-txt",
            "--no-emit-project",
            "--no-emit-package",
            "milai-client",
        ]
    )
    exported = completed.stdout
    forbidden = ("-e ", "../python-client", "milai-mcp @", "git+", "http://")
    if any(value in exported for value in forbidden):
        raise RuntimeError("requirements export retained a local or insecure source")
    if "mcp==2.0.0" not in exported or "httpx==0.28.1" not in exported:
        raise RuntimeError(
            "requirements export is missing the locked MCP/client closure"
        )
    return exported


def _local_requirement_lines() -> str:
    lines = []
    for wheel in LOCAL_WHEELS:
        if not wheel.is_file():
            raise FileNotFoundError(wheel)
        name = "milai-client" if wheel.name.startswith("milai_client") else "milai-mcp"
        lines.append(f"{name}==0.1.0 --hash=sha256:{_sha256(wheel)}")
    return "\n".join(lines) + "\n"


def _canonical_root(entries: list[dict[str, Any]]) -> str:
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _download(stage: Path, requirements: Path) -> None:
    cache = Path("/tmp/milai-dg10-pip-cache-candidate2")
    cache.mkdir(mode=0o700, exist_ok=True)
    cache.chmod(0o700)
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=256m",
            "--mount",
            f"type=bind,src={requirements},dst=/input/requirements.txt,readonly",
            "--mount",
            f"type=bind,src={stage},dst=/output",
            "--mount",
            f"type=bind,src={cache},dst=/root/.cache/pip",
            "--entrypoint",
            "/usr/bin/python3",
            BASE_TAG,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--require-hashes",
            "--dest",
            "/output",
            "--requirement",
            "/input/requirements.txt",
        ]
    )


def _reuse_third_party(stage: Path, source: Path) -> None:
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise TypeError("source wheelhouse manifest entries are missing")
    local_names = {wheel.name for wheel in LOCAL_WHEELS}
    copied = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("source wheelhouse entry is invalid")
        name = entry.get("path")
        size = entry.get("size")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise RuntimeError("source wheelhouse entry path is unsafe")
        if name in local_names or name == "requirements.lock":
            continue
        source_file = source / name
        if (
            not source_file.is_file()
            or source_file.is_symlink()
            or source_file.stat().st_size != size
            or _sha256(source_file) != digest
        ):
            raise RuntimeError("source wheelhouse entry identity drift")
        shutil.copy2(source_file, stage / name)
        copied += 1
    if copied == 0:
        raise RuntimeError("source wheelhouse has no reusable third-party artifacts")


def _offline_verify(stage: Path) -> dict[str, Any]:
    command = (
        "set -eu; "
        "python3 -m venv /tmp/milai-clean; "
        "/tmp/milai-clean/bin/python -m pip install --disable-pip-version-check "
        "--no-index --only-binary=:all: --require-hashes --find-links=/wheelhouse "
        "-r /wheelhouse/requirements.lock; "
        "cd /tmp; "
        "/tmp/milai-clean/bin/python -I -c 'import milai_client, milai_mcp'; "
        "/tmp/milai-clean/bin/milai-mcp --help >/tmp/mcp-help; "
        "test -s /tmp/mcp-help; "
        "/tmp/milai-clean/bin/python -m pip check"
    )
    completed = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,exec,nosuid,nodev,size=512m",
            "--mount",
            f"type=bind,src={stage},dst=/wheelhouse,readonly",
            "--entrypoint",
            "/bin/sh",
            BASE_TAG,
            "-c",
            command,
        ]
    )
    return {
        "status": "PASS",
        "network": "none",
        "filesystem": "read-only root plus bounded tmpfs",
        "cwd": "/tmp outside repository",
        "pip_check_tail": completed.stdout.strip().splitlines()[-1:],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the DG-10 CPython 3.12 musl wheelhouse"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--reuse-third-party-from", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to replace existing wheelhouse: {output}")

    image = _docker_image()
    third_party = _third_party_requirements()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".milai-dg10-wheelhouse-", dir=output.parent
    ) as temporary:
        workspace = Path(temporary)
        third_party_path = workspace / "third-party-requirements.txt"
        third_party_path.write_text(third_party, encoding="utf-8")
        stage = workspace / "wheelhouse"
        stage.mkdir(mode=0o700)
        if args.reuse_third_party_from is None:
            _download(stage, third_party_path)
            network_note = (
                "Build downloaded only locked Python artifacts; offline verification used "
                "Docker --network none. No Model Provider endpoint or credential was used."
            )
        else:
            source = args.reuse_third_party_from.resolve()
            _reuse_third_party(stage, source)
            network_note = (
                "Third-party artifacts were reused from the digest-verified prior wheelhouse; "
                "offline verification used Docker --network none. No external endpoint, Model "
                "Provider endpoint, or credential was used."
            )
        for wheel in LOCAL_WHEELS:
            shutil.copy2(wheel, stage / wheel.name)

        lock = _local_requirement_lines() + third_party
        (stage / "requirements.lock").write_text(lock, encoding="utf-8")
        verification = _offline_verify(stage)
        if _docker_image().get("Id") != image.get("Id"):
            raise RuntimeError("OpenWorker base image changed during wheelhouse build")

        entries = [
            {
                "path": path.name,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(stage.iterdir())
            if path.is_file() and path.name != "manifest.json"
        ]
        manifest = {
            "schema": "milai.dg10.musl-wheelhouse.v1",
            "status": "LOCAL_CANDIDATE_REVIEW_REQUIRED",
            "data_boundary": "SYNTHETIC_OR_DEIDENTIFIED_ONLY",
            "target": {
                "image_id": BASE_ID,
                "platform": "linux/amd64",
                "os": "Alpine Linux 3.22.4",
                "python": "3.12.13",
                "uv": "0.11.9",
                "libc": "musl",
            },
            "source_locks": {
                "mcp_uv_lock_sha256": _sha256(ROOT / "integrations/mcp/uv.lock"),
                "client_uv_lock_sha256": _sha256(
                    ROOT / "integrations/python-client/uv.lock"
                ),
            },
            "entry_count": len(entries),
            "entries": entries,
            "canonical_entries_sha256": _canonical_root(entries),
            "offline_clean_install": verification,
            "network_note": network_note,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
