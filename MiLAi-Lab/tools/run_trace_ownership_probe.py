"""Finite synthetic real-MCP/HTTP/PG probe; Provider is an in-process fixture.

No model endpoint is contacted. Product source must be committed and manifest-pinned;
the caller supplies an already migrated, isolated synthetic database via role URLs.
Artifacts (including failures) are private, new-per-run and never committed.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from milai.testkit.observed_runtime import ObservedRuntime
from milai_openworker_mcp.trace_testkit import (
    DevRunCapability,
    NativeProviderResponse,
    NativeTaskMetadata,
    ObservedOpenWorkerProviderAdapter,
    OpenAIChatRequest,
    ProviderRequest,
    ProviderTransportError,
)

from milai_lab.analysis.owner_exports import assemble_owner_attempts
from milai_lab.analysis.trace_join import join_attempts
from milai_lab.product_adapter.manifest import (
    ProductLock,
    PublicInterfacePin,
    SourceManifestPin,
    verify_product_lock,
)

MODEL = "Qwen3.6-35B-A3B-FP8"  # Gateway contract only; no model loaded or called.
CONTENT = "Purchase marker: synthetic ceramic cups await pickup."
QUERY = "Recall purchase marker cups awaiting pickup"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(  # noqa: S603 -- fixed read-only Git arguments
        ["git", "-C", str(root), *args], text=True,  # noqa: S607
    ).strip()


def _pin(product: Path, commit: str, output: Path) -> ProductLock:
    if _git(product, "rev-parse", "HEAD") != commit:
        raise ValueError("PROBE_COMMIT_MISMATCH")
    manifest_path = product / "product.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    paths = [*manifest["tree_paths"], "product.manifest.json"]
    if _git(product, "status", "--porcelain", "--", *paths):
        raise ValueError("PROBE_PRODUCT_SOURCE_MUST_BE_COMMITTED")
    method_paths = [str(Path(__file__).resolve()), inspect.getfile(assemble_owner_attempts),
                    inspect.getfile(join_attempts)]
    if _git(product, "status", "--porcelain", "--", *method_paths):
        raise ValueError("PROBE_METHOD_SOURCE_MUST_BE_COMMITTED")
    # The verifier's Git field describes an independent Product repository. This
    # is a monorepo: exact containing commit is checked above and stored separately.
    lock = ProductLock(
        1, manifest["product_name"], manifest["product_version"], str(product), None,
        tuple(manifest["tree_paths"]), manifest["tree_sha256"],
        tuple(PublicInterfacePin(x["interface_id"], x["path"], x["sha256"])
              for x in manifest["public_interfaces"]),
        SourceManifestPin("product.manifest.json", manifest["schema_version"], _sha(manifest_path)),
    )
    result = verify_product_lock(lock, product)
    _write(output / "product.lock.json", lock.to_dict())
    _write(output / "pin-verification.json", result.to_dict())
    if not result.valid:
        raise ValueError("PROBE_PRODUCT_PIN_FAILED")
    for value, relative in (
        (ObservedRuntime, "runtime/src"),
        (ObservedOpenWorkerProviderAdapter, "integrations/openworker-mcp/src"),
    ):
        if not Path(inspect.getfile(value)).resolve().is_relative_to(product / relative):
            raise ValueError("PROBE_IMPORTED_PRODUCT_MISMATCH")
    installed = []
    for package, modules in (
        ("runtime", {"milai": "runtime/src"}),
        ("integrations/mcp", {"milai_mcp": "integrations/mcp/src",
                              "milai_client": "integrations/python-client/src"}),
        ("integrations/openworker-mcp", {
            "milai_openworker_mcp": "integrations/openworker-mcp/src",
            "milai_client": "integrations/python-client/src",
        }),
    ):
        # Inspect installed public CLI import locations, not private Product helpers.
        code = (
            "import importlib,json,sys; print(json.dumps({'python':sys.version,"
            "'modules':{n:importlib.import_module(n).__file__ for n in sys.argv[1:]}}))"
        )
        raw = subprocess.check_output(  # noqa: S603 -- fixed introspection, no service startup
            [str(product / package / ".venv/bin/python"), "-c", code, *modules],
            text=True, timeout=10,
        )
        record = json.loads(raw)
        for module, relative in modules.items():
            if not Path(record["modules"][module]).resolve().is_relative_to(product / relative):
                raise ValueError("PROBE_CLI_PRODUCT_MISMATCH")
        installed.append({"package": package, **record})
    _write(output / "installed-cli-identity.json", installed)
    return lock


class FixtureTransport:
    """Exercises real gateway accounting without real inference or HTTP."""

    name = "json"

    def __init__(self) -> None:
        self.mode = "success"
        self.calls = 0

    def invoke(
        self, request: ProviderRequest, capability: DevRunCapability,
    ) -> NativeProviderResponse:
        del request, capability
        self.calls += 1
        if self.calls > 8:
            raise RuntimeError("PROBE_CALL_LIMIT")
        if self.mode in {"not-started", "response-lost"}:
            raise ProviderTransportError(
                "SYNTHETIC_TRANSPORT_FAILURE", request_started=self.mode == "response-lost",
            )
        if self.mode == "unknown":
            raise RuntimeError("SYNTHETIC_UNKNOWN_TRANSPORT_STATE")
        native = "synthetic-native-" + str(self.calls)
        payload = {
            "id": native, "object": "chat.completion", "choices": [{
                "index": 0, "message": {"role": "assistant", "content": "Synthetic fixture."},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        return NativeProviderResponse(native, 5, 3, "stop", payload)


def _post(base: str, token: str, path: str, body: object) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 -- owned loopback testkit URL
        base + path, data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "Idempotency-Key": str(uuid4()),
    })
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        return json.load(response)  # type: ignore[no-any-return]


def _worker(product: Path, config: dict[str, Any], output: Path) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "MILAI_WORKER_DATABASE_URL": os.environ["MILAI_TEST_WORKER_DATABASE_URL"],
        "MILAI_BLOB_ROOT": config["blob_root"], "MILAI_TENANT_ID": config["tenant_id"],
        "MILAI_LOCAL_ACTOR_ID": config["local_actor_id"], "MILAI_ENVIRONMENT": "test",
        "MILAI_EMBEDDING_PROVIDER": "deterministic_hash", "MILAI_EMBEDDING_PREWARM": "false",
        "MILAI_WORKER_EVENT_LIMIT": "3", "MILAI_WORKER_MAX_ATTEMPTS": "1",
    }
    result = subprocess.run(  # noqa: S603 -- pinned Product CLI, role-scoped synthetic DB
        [str(product / "runtime/.venv/bin/milai-worker"), "--once"],
        env=environment, capture_output=True, timeout=20, check=False,
    )
    _write(output / "worker.json", {
        "returncode": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    })
    if result.returncode:
        raise RuntimeError("PROBE_WORKER_FAILED")


def run(product: Path, commit: str, output: Path) -> dict[str, Any]:
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    lock = _pin(product, commit, output)
    run_id = "trace-chain-" + uuid4().hex
    started = time.monotonic()
    now = datetime.now(UTC)
    # Short UDS pathname; preserve only this run's private directory for diagnosis.
    socket_root = Path(tempfile.mkdtemp(prefix="milai-trace-", dir="/dev/shm"))
    admin, reader = "synthetic-admin-" + uuid4().hex, "synthetic-reader-" + uuid4().hex
    config = {
        "environment": "test", "data_mode": "SYNTHETIC_ONLY",
        "database_url": os.environ["MILAI_TEST_API_DATABASE_URL"],
        "steward_database_url": os.environ["MILAI_TEST_STEWARD_DATABASE_URL"],
        "tenant_id": str(uuid4()), "local_actor_id": str(uuid4()),
        "blob_root": str(output / "blobs"), "api_token": admin, "agent_reader_token": reader,
        "causal_token_secret": "synthetic-causal-" + uuid4().hex,
        "embedding_provider": "deterministic_hash", "embedding_prewarm": False,
    }
    _write(output / "manifest.json", {
        "schema": "milai-trace-chain-probe-v1", "run_id": run_id,
        "arm_kind": "PRODUCT_TESTKIT", "monorepo_commit": commit,
        "product_lock_digest": lock.digest, "method_sha256": _sha(Path(__file__)),
        "method_sources_sha256": {
            "runner": _sha(Path(__file__)),
            "owner_exports": _sha(Path(inspect.getfile(assemble_owner_attempts))),
            "trace_join": _sha(Path(inspect.getfile(join_attempts))),
        },
        "input_sha256": hashlib.sha256((CONTENT + "\n" + QUERY).encode()).hexdigest(),
        "provider": "CONTROLLED_IN_PROCESS_FIXTURE", "tokenizer": "SYNTHETIC_WORDLEVEL",
        "max_host_attempts": 8, "max_fixture_invocations": 8, "max_wall_seconds": 120,
        "model_requests": 0, "experiment_allocations": 0, "socket_root": str(socket_root),
        "tenant_id": config["tenant_id"], "default_runtime_settings": True,
        "claim_ceiling": "ENGINEERING_TRACE_PROVENANCE_NOT_MODEL_EFFECT",
    })
    _write(output / "provider-manifest.json", {
        "schema": "milai.provider.dev-run.v1", "run_id": run_id, "phase": "functional_f1",
        "provider": "local_vllm", "endpoint_identity": "http://127.0.0.1:1", "model_id": MODEL,
        "dataset_manifest_sha256": hashlib.sha256(CONTENT.encode()).hexdigest(),
        "prompt_template_sha256": hashlib.sha256(QUERY.encode()).hexdigest(),
        "max_native_requests": 8, "max_prompt_tokens": 32000, "max_completion_tokens": 768,
        "deadline": (now + timedelta(seconds=120)).isoformat(),
        "expires_at": (now + timedelta(seconds=120)).isoformat(),
        "synthetic_or_deidentified_only": True, "closed_test_access": False,
    })
    _write(output / "tokenizer.json", {
        "version": "1.0", "truncation": None, "padding": None, "added_tokens": [],
        "normalizer": None, "pre_tokenizer": {"type": "Whitespace"},
        "post_processor": None, "decoder": None,
        "model": {"type": "WordLevel", "vocab": {"[UNK]": 0}, "unk_token": "[UNK]"},
    })
    token_file = socket_root / "reader.token"
    with token_file.open("x") as stream:
        stream.write(reader)
    token_file.chmod(0o600)
    fixture = FixtureTransport()
    cases: list[dict[str, Any]] = []
    adapter = None
    runtime = ObservedRuntime(config)
    broker = None
    try:
        with runtime:
            mcp_executable = product / "integrations/mcp/.venv/bin/milai-mcp"
            policy = {
                "schema": "milai.openworker.mcp-broker-policy.v1", "profile": "reader-lite",
                "socket_path": str(socket_root / "reader-lite.sock"), "socket_mode": "0600",
                "allowed_peer_uids": [os.geteuid()], "mcp_executable": str(mcp_executable),
                "mcp_executable_sha256": _sha(mcp_executable), "base_url": runtime.base_url,
                "scope": {"project_ids": ["orchid-release"]},
                "required_authority": "INFORMATIONAL", "consistency_floor": "CANONICAL_REQUIRED",
                "max_limit": 3, "max_connections": 2, "child_shutdown_seconds": 2,
                "mcp_max_retries": 0,
            }
            _write(output / "broker-policy.json", policy)
            with (output / "broker.log").open("xb") as broker_log:
                broker = subprocess.Popen([  # noqa: S603 -- pinned Product CLI
                    str(product / "integrations/openworker-mcp/.venv/bin/milai-mcp-broker"),
                    "--policy", str(output / "broker-policy.json"), "--token-file", str(token_file),
                ], env={"PATH": os.environ.get("PATH", "")}, stdout=broker_log, stderr=broker_log)
                for _ in range(100):
                    if (socket_root / "reader-lite.sock").exists():
                        break
                    if broker.poll() is not None:
                        raise RuntimeError("PROBE_BROKER_START_FAILED")
                    time.sleep(0.05)
                else:
                    raise RuntimeError("PROBE_BROKER_START_TIMEOUT")
                adapter = ObservedOpenWorkerProviderAdapter(
                    output / "provider-manifest.json", output / "provider-ledger.jsonl",
                    output / "host-trace.jsonl", memory_mode="query-first",
                    prefetch_socket=socket_root / "reader-lite.sock",
                    tokenizer_json=output / "tokenizer.json",
                    broker_policy=output / "broker-policy.json",
                    task_fixture=product / "contracts/agent/v1/dg13u-u1-candidate-fixture.json",
                )
                adapter.transport = fixture
                host_id = str(uuid4())

                def attempt(
                    name: str, query: str, mode: str = "success", retry: str | None = None,
                ) -> None:
                    fixture.mode = mode
                    before = len(runtime.owner_traces())
                    error = None
                    route = None
                    try:
                        _, route = adapter.complete(
                            OpenAIChatRequest.parse({
                                "model": MODEL, "stream": False, "max_tokens": 64,
                                "messages": [{"role": "user", "content": query}],
                            }),
                            NativeTaskMetadata(host_id, "trace-session", "op-" + str(len(cases))),
                            retry_of=retry,
                        )
                    except Exception as exc:
                        error = type(exc).__name__
                    cases.append({"case": name, "route": route, "error_type": error,
                                  "host": adapter.owner_traces()[-1],
                                  "runtime": runtime.owner_traces()[before:]})

                attempt("no-memory", "What is two plus two?")
                attempt("no-memory-repeat", "What is two plus two?",
                        retry=cases[-1]["host"]["host_attempt_trace_id"])
                attempt("abstain", QUERY)
                _post(runtime.base_url, admin, "/v1/evidence", {
                    "source_type": "RUNTIME_OBSERVATION", "source_ref": "synthetic://trace-probe",
                    "subject_id": "orchid-release", "speaker": "user",
                    "observed_at": "2026-01-01T10:00:00Z", "content": CONTENT,
                    "media_type": "text/plain", "retention_state": "READABLE",
                    "permission_snapshot": {"readable": True, "project_ids": ["orchid-release"]},
                })
                _worker(product, config, output)
                attempt("success-use-unknown", QUERY)
                attempt("retry", QUERY, retry=cases[-1]["host"]["host_attempt_trace_id"])
                attempt("failure-not-started", QUERY, "not-started")
                attempt("failure-response-lost", QUERY, "response-lost")
                attempt("failure-unknown-dispatch", QUERY, "unknown")
    finally:
        if adapter is not None:
            adapter.close()
        if broker is not None:
            broker.terminate()
            try:
                broker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                broker.kill()
                broker.wait(timeout=5)
        # Only the newly created per-run capability file is removed; no user credential.
        token_file.unlink(missing_ok=True)
        _write(output / "owner-facts.json", cases)
        _write(output / "runtime-facts.json", runtime.owner_traces())
    joined = assemble_owner_attempts(
        cases, run_id=run_id, product_lock_digest=lock.digest,
        result_refs=[f"result:{_sha(output / 'owner-facts.json')}:{i}" for i in range(len(cases))],
    )
    _write(output / "joined.json", joined)
    if [row["host"]["terminal"] for row in joined] != [
        "NO_MEMORY", "NO_MEMORY", "ABSTAIN", "SUCCESS", "SUCCESS", "FAILURE", "FAILURE", "FAILURE",
    ]:
        raise ValueError("PROBE_TERMINAL_COVERAGE_FAILED")
    requests = [r for row in joined for r in row["requests"]]
    if fixture.calls != 7 or len(requests) != 7:
        raise ValueError("PROBE_INVOCATION_COVERAGE_FAILED")
    expected_hash = hashlib.sha256(CONTENT.encode()).hexdigest()
    if any(v["content_sha256"] != expected_hash for row in joined for trace in row["runtime"]
           for v in trace["selected_versions"]):
        raise ValueError("PROBE_EXACT_VERSION_FAILED")
    if any(r["observable_use"] != "UNKNOWN" for r in requests):
        raise ValueError("PROBE_UNSUPPORTED_USE_CLAIM")
    if [len(r["exposed_versions"]) for r in requests] != [0, 0, 1, 1, 0, 1, 0]:
        raise ValueError("PROBE_DISPATCH_COVERAGE_FAILED")
    summary = {
        "status": "FRESH_CHAIN_PASS_CACHE_ORIGIN_NOT_PROVEN", "cases": len(cases),
        "fixture_invocations": fixture.calls, "model_requests": 0,
        "unknown_fixture_usage": sum(r["unknown_usage"] for r in requests),
        "fixture_known_input_units": sum(r["usage"]["input_tokens"] or 0 for r in requests),
        "fixture_known_output_units": sum(r["usage"]["output_tokens"] or 0 for r in requests),
        "actual_model_tokens": 0,
        "wall_seconds": round(time.monotonic() - started, 3),
        "owner_facts_sha256": _sha(output / "owner-facts.json"),
        "joined_sha256": _sha(output / "joined.json"),
    }
    _write(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--product-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def timeout(signum: int, frame: Any) -> None:
        raise TimeoutError("PROBE_WALL_LIMIT")

    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(120)
    try:
        result = run(args.product_root.resolve(), args.product_commit, args.output.resolve())
        print(json.dumps(result))
    except Exception as exc:
        if args.output.is_dir():
            _write(args.output / "failure.json", {"error_type": type(exc).__name__,
                                                  "model_requests": 0})
        raise
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
