from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-20"
CLIENT_WHEEL = (
    ROOT / "integrations/python-client/dist/milai_client-0.1.0-py3-none-any.whl"
)
CLIENT_SDIST = ROOT / "integrations/python-client/dist/milai_client-0.1.0.tar.gz"
MCP_WHEEL = ROOT / "integrations/mcp/dist/milai_mcp-0.1.0-py3-none-any.whl"
MCP_SDIST = ROOT / "integrations/mcp/dist/milai_mcp-0.1.0.tar.gz"
WHEELHOUSE = (
    ROOT
    / "integrations/openworker-mcp/wheelhouse/cp312-musllinux_1_2_x86_64-candidate.2"
)
OFFICIAL_HOST = ROOT / "evals/agent_integration/mcp_host.py"
WIRE_HOST = ROOT / "evals/agent_integration/mcp_wire_host.py"
DEFAULT_OUTPUT = ROOT / f"docs/reports/DG-10-mcp-package-gate-candidate.2-{DATE}.json"
_FORBIDDEN_PARTS = frozenset(
    {".env", ".cache", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_FORBIDDEN_SUFFIXES = (".log", ".sqlite", ".sqlite3", ".bak", ".backup", ".blob")
_SECRET_VALUE = "synthetic-package-gate-token-value-000000000000"


class GateError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise GateError(
            f"command failed with status {completed.returncode}; "
            f"stdout_tail={completed.stdout[-1500:]!r}; stderr_tail={completed.stderr[-1500:]!r}"
        )
    return completed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or normalized.startswith("/")
    ):
        raise GateError(f"unsafe archive member: {name}")
    if any(part.lower() in _FORBIDDEN_PARTS for part in path.parts):
        raise GateError(f"forbidden archive member: {name}")
    if normalized.lower().endswith(_FORBIDDEN_SUFFIXES):
        raise GateError(f"forbidden archive member suffix: {name}")


def _scan_wheel(path: Path) -> dict[str, Any]:
    members = 0
    uncompressed = 0
    with ZipFile(path) as archive:
        for member in archive.infolist():
            _safe_member(member.filename)
            unix_type = (member.external_attr >> 16) & 0o170000
            if unix_type == 0o120000:
                raise GateError(f"wheel contains a symlink: {member.filename}")
            members += 1
            uncompressed += member.file_size
    return {
        "path": path.relative_to(ROOT).as_posix()
        if path.is_relative_to(ROOT)
        else path.name,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "members": members,
        "uncompressed_bytes": uncompressed,
        "status": "PASS",
    }


def _scan_sdist(path: Path) -> dict[str, Any]:
    import tarfile

    members = 0
    uncompressed = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            _safe_member(member.name)
            if member.issym() or member.islnk() or member.isdev():
                raise GateError(f"sdist contains an unsafe member: {member.name}")
            members += 1
            uncompressed += member.size
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "members": members,
        "uncompressed_bytes": uncompressed,
        "status": "PASS",
    }


def _wheelhouse_gate() -> dict[str, Any]:
    manifest_path = WHEELHOUSE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise GateError("wheelhouse manifest entries are missing")
    expected = {str(entry["path"]): entry for entry in entries}
    actual = {
        path.name: path
        for path in WHEELHOUSE.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    if set(actual) != set(expected):
        raise GateError("wheelhouse exact file set drift")
    wheel_scans = []
    for name, path in sorted(actual.items()):
        entry = expected[name]
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise GateError("wheelhouse member identity drift")
        if path.suffix == ".whl":
            wheel_scans.append(_scan_wheel(path))
    canonical = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if canonical != manifest.get("canonical_entries_sha256"):
        raise GateError("wheelhouse canonical root drift")
    if (manifest.get("offline_clean_install") or {}).get("status") != "PASS":
        raise GateError("wheelhouse offline clean install evidence is absent")
    return {
        "manifest_sha256": _sha256(manifest_path),
        "canonical_entries_sha256": canonical,
        "entry_count": len(entries),
        "wheel_count": len(wheel_scans),
        "archive_scan": "PASS",
        "offline_clean_install": manifest["offline_clean_install"],
        "target": manifest["target"],
    }


def _create_venv(path: Path) -> Path:
    _run(["uv", "venv", "--python", "3.11", str(path)])
    return path / "bin/python"


def _install_wheel_environment(workspace: Path) -> tuple[Path, dict[str, Any]]:
    venv = workspace / "wheel-venv"
    python = _create_venv(venv)
    lock = WHEELHOUSE / "requirements.lock"
    result = _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--offline",
            "--require-hashes",
            "--find-links",
            str(WHEELHOUSE),
            "--requirements",
            str(lock),
        ],
        timeout=180,
    )
    _run([str(python), "-I", "-c", "import milai_client, milai_mcp, mcp"])
    _run([str(venv / "bin/milai-mcp"), "--help"], cwd=workspace)
    return python, {
        "status": "PASS",
        "network": "offline",
        "lock_sha256": _sha256(lock),
        "diagnostic": result.stderr.strip().splitlines()[-1:],
    }


def _install_sdist_environment(workspace: Path) -> dict[str, Any]:
    venv = workspace / "sdist-venv"
    python = _create_venv(venv)
    lock_lines = (
        (WHEELHOUSE / "requirements.lock").read_text(encoding="utf-8").splitlines()
    )
    if not lock_lines[0].startswith("milai-client==") or not lock_lines[1].startswith(
        "milai-mcp=="
    ):
        raise GateError("unexpected local package lock prefix")
    third_party = workspace / "third-party.lock"
    third_party.write_text("\n".join(lock_lines[2:]) + "\n", encoding="utf-8")
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--offline",
            "--require-hashes",
            "--requirements",
            str(third_party),
        ],
        timeout=180,
    )
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--offline",
            "--no-deps",
            str(CLIENT_SDIST),
            str(MCP_SDIST),
        ],
        timeout=180,
    )
    _run([str(python), "-I", "-c", "import milai_client, milai_mcp, mcp"])
    _run([str(venv / "bin/milai-mcp"), "--help"], cwd=workspace)
    return {
        "status": "PASS",
        "network": "offline",
        "client_sdist_sha256": _sha256(CLIENT_SDIST),
        "mcp_sdist_sha256": _sha256(MCP_SDIST),
    }


class _RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "MiLAiSyntheticPackageGate/1"

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _send(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/v1/capabilities":
            self._send(
                200,
                {
                    "api_version": "1",
                    "contract_version": "agent.v1",
                    "runtime_version": "0.1.0",
                    "profile": "local",
                    "capabilities": ["memory:read"],
                    "routes": ["L0", "L1"],
                    "consistency_modes": ["CANONICAL_REQUIRED"],
                    "agent_profiles": ["reader-lite"],
                    "features": {},
                    "limits": {"max_recall_limit": 3},
                    "data_mode": "SYNTHETIC",
                    "schema_status": "0.1.x EXPERIMENTAL / NO-GO FOR FREEZE",
                    "implementation_status": "CANDIDATE",
                },
            )
            return
        self._send(404, {"error": {"code": "NOT_FOUND"}})

    def do_POST(self) -> None:
        if self.path != "/v1/memory/query":
            self._send(404, {"error": {"code": "NOT_FOUND"}})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            self._send(400, {"error": {"code": "BAD_REQUEST"}})
            return
        self.server.requests.append(body)  # type: ignore[attr-defined]
        self._send(
            200,
            {
                "results": [],
                "open_issue_ids": ["issue-synthetic-live"],
                "retrieval_trace_id": "trace-synthetic-package-gate",
                "consistency": body.get("consistency"),
                "snapshot": {"canonical_outbox_sequence": 7},
                "degraded_components": ["vector"],
                "fallback_used": True,
                "fallback_reason": "SYNTHETIC_PROJECTION_UNAVAILABLE",
                "abstained": True,
                "abstention_reason": "CANONICAL_UNAVAILABLE",
                "request_id": "request-synthetic-package-gate",
            },
        )


@contextmanager
def _runtime() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = str(server.server_address[0])
        port = int(server.server_address[1])
        yield f"http://{host}:{port}", server.requests  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _host_cases(
    python: Path, workspace: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results = []
    with _runtime() as (base_url, requests):
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MILAI_BASE_URL": base_url,
            "MILAI_AGENT_TOKEN": _SECRET_VALUE,
            "MILAI_AGENT_SCOPE_JSON": '{"project_ids":["milai"]}',
            "MILAI_AGENT_REQUIRED_AUTHORITY": "ACTION_SAFE",
            "MILAI_AGENT_CONSISTENCY_FLOOR": "CANONICAL_REQUIRED",
            "MILAI_AGENT_MAX_LIMIT": "3",
        }
        payload = json.dumps({"query": "synthetic package gate"})
        forbidden_policy_payload = json.dumps(
            {"query": "synthetic package gate", "consistency": "EVENTUAL", "limit": 99}
        )
        for host_name, script in (
            ("official", OFFICIAL_HOST),
            ("independent-wire", WIRE_HOST),
        ):
            for mode, expected_protocol in (
                ("2026-07-28", "2026-07-28"),
                ("legacy", "2025-11-25"),
            ):
                for reconnect in range(2):
                    completed = _run(
                        [
                            str(python),
                            str(script),
                            "--profile",
                            "reader-lite",
                            "--mode",
                            mode,
                            "--tool",
                            "milai_recall",
                        ],
                        cwd=workspace,
                        input_text=payload,
                        env=environment,
                        timeout=30,
                    )
                    value = json.loads(completed.stdout)
                    if value.get("protocol_version") != expected_protocol:
                        raise GateError("host protocol negotiation drift")
                    if value.get("tools") != ["milai_recall"]:
                        raise GateError("reader-lite catalog drift")
                    call = (
                        value.get("call") if host_name == "independent-wire" else value
                    )
                    if host_name == "official":
                        structured = call.get("structured")
                        is_error = call.get("is_error")
                    else:
                        structured = call.get("structuredContent")
                        is_error = call.get("isError")
                    if is_error is not False or not isinstance(structured, dict):
                        raise GateError("MCP recall call failed")
                    if (
                        structured.get("status") != "ABSTAINED"
                        or structured.get("open_issue_ids") != ["issue-synthetic-live"]
                        or structured.get("trace_id") != "trace-synthetic-package-gate"
                        or structured.get("degraded_components") != ["vector"]
                        or structured.get("abstention_reason")
                        != "CANONICAL_UNAVAILABLE"
                    ):
                        raise GateError("MCP safety/trace output was not preserved")
                    results.append(
                        {
                            "host": host_name,
                            "protocol": expected_protocol,
                            "reconnect_index": reconnect,
                            "catalog": ["milai_recall"],
                            "call": "ABSTAINED_TRACE_OPENISSUE_DEGRADED_PRESERVED",
                            "status": "PASS",
                        }
                    )
                    if reconnect == 0:
                        rejected_run = _run(
                            [
                                str(python),
                                str(script),
                                "--profile",
                                "reader-lite",
                                "--mode",
                                mode,
                                "--tool",
                                "milai_recall",
                            ],
                            cwd=workspace,
                            input_text=forbidden_policy_payload,
                            env=environment,
                            timeout=30,
                        )
                        rejected_value = json.loads(rejected_run.stdout)
                        rejected_call = (
                            rejected_value.get("call")
                            if host_name == "independent-wire"
                            else rejected_value
                        )
                        rejected_error = (
                            rejected_call.get("isError")
                            if host_name == "independent-wire"
                            else rejected_call.get("is_error")
                        )
                        if rejected_error is not True:
                            raise GateError("reader-lite accepted model policy arguments")
                        results.append(
                            {
                                "host": host_name,
                                "protocol": expected_protocol,
                                "catalog": ["milai_recall"],
                                "call": "MODEL_POLICY_ARGUMENTS_REJECTED",
                                "status": "PASS",
                            }
                        )
        observed = list(requests)
    if len(observed) != 8:
        raise GateError("unexpected Runtime request count")
    for request in observed:
        if request.get("requested_scope") != {"project_ids": ["milai"]}:
            raise GateError("Host Scope was not fixed")
        if request.get("required_authority") != "ACTION_SAFE":
            raise GateError("Host authority was not fixed")
        if (
            request.get("consistency") != "CANONICAL_REQUIRED"
            or request.get("limit") != 3
        ):
            raise GateError("Host consistency/limit cap was not enforced")
    return results, observed


def _write_report(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DG-10 MCP package gate")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    wheelhouse = _wheelhouse_gate()
    archives = [
        _scan_wheel(CLIENT_WHEEL),
        _scan_sdist(CLIENT_SDIST),
        _scan_wheel(MCP_WHEEL),
        _scan_sdist(MCP_SDIST),
    ]
    with tempfile.TemporaryDirectory(prefix="milai-dg10-package-gate-") as temporary:
        workspace = Path(temporary)
        python, wheel_install = _install_wheel_environment(workspace)
        sdist_install = _install_sdist_environment(workspace)
        hosts, runtime_requests = _host_cases(python, workspace)
    unit = _run(
        [
            str(ROOT / "integrations/mcp/.venv/bin/pytest"),
            "-q",
            "-p",
            "no:cacheprovider",
            "integrations/mcp/tests",
        ],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if _SECRET_VALUE in json.dumps(hosts) or _SECRET_VALUE in unit.stdout + unit.stderr:
        raise GateError("synthetic token reflected into report/test output")
    report = {
        "schema": "milai.dg10.mcp-package-gate.v1",
        "date": DATE,
        "status": "LOCAL_CANDIDATE_REVIEW_REQUIRED",
        "data_boundary": "SYNTHETIC_ONLY",
        "provider_requests": 0,
        "provider_cost": 0,
        "runtime_banner": "0.1.x CANDIDATE",
        "schema_banner": "0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE",
        "archives": archives,
        "wheelhouse": wheelhouse,
        "fresh_installs": {"wheel": wheel_install, "sdist": sdist_install},
        "host_interoperability": hosts,
        "runtime_request_policy": {
            "request_count": len(runtime_requests),
            "scope": {"project_ids": ["milai"]},
            "authority": "ACTION_SAFE",
            "consistency": "CANONICAL_REQUIRED",
            "max_limit": 3,
            "status": "PASS",
        },
        "profile_tests": {
            "status": "PASS",
            "summary": unit.stdout.strip().splitlines()[-1],
            "reader_lite_exact_catalog": ["milai_recall"],
            "dangerous_tools_absent": True,
            "all_schemas_additional_properties_false": True,
        },
        "gate_results": {
            "MCG-00": "PASS_LOCAL_CANDIDATE",
            "MCG-01": "PASS_LOCAL_CANDIDATE",
            "MCG-02": "PASS_LOCAL_CANDIDATE",
            "OG-03": "DEFERRED_TO_BOUND_PVLOCAL_TARGET_TOKENIZER_REPORT",
        },
        "known_limits": [
            "This package gate does not invoke a model tokenizer; candidate.2 PV-LOCAL A/B is the authoritative local OG-03 evidence.",
            "This is author-generated local evidence and requires independent re-verification.",
            "No real Provider request, bill, credential, Prompt, memory body, or raw model output was used.",
        ],
    }
    _write_report(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
