from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import evals.agent_efficiency.provider_ab as provider_ab_module
from evals.agent_efficiency.provider_ab import (
    DATA_BOUNDARY_ACK,
    HOST_EXECUTION_POLICY,
    HOST_TOOL_SEARCH_PATH,
    REPORT_FORMAT,
    SANDBOX_FILE_POLICY,
    SANDBOX_LAUNCHER,
    SANDBOX_RUNTIME,
    AdapterProcess,
    ProviderEvidenceError,
    _canonical_bytes,
    _command_exit_code,
    _gates,
    _load_workload,
    _manifest,
    _reader_detail_tools,
    _reader_lite_tools,
    _request_payload,
    _score_output,
    _sha256_file,
    _tool_schema_hashes,
    _turns,
    _validate_model_result,
    build_host_execution_lock,
    build_plan,
    reconcile_billing,
    run_provider_ab,
)
from evals.agent_efficiency.provider_ab import _write_json as _atomic_write_json

FAKE_ADAPTER = r"""set -eu
if [ "$EUID" -ne 65534 ]; then
  exit 70
fi
if [ -e /cra/memory/mx_memory/MiLAi/runtime/.env ] || [ -e /root/.profile ]; then
  workspace_visible=true
else
  workspace_visible=false
fi
if IFS= read -r host_line < /etc/passwd 2>/dev/null; then
  exit 73
fi
if (exec 3<>/dev/tcp/1.1.1.1/443) 2>/dev/null; then
  exit 72
fi
while IFS= read -r line; do
  case "$line" in
    *'"op":"close"'*) exit 0 ;;
    *'"op":"handshake"'*)
      if [ "$workspace_visible" = true ]; then exit 71; fi
      printf '%s\n' '{"component_token_counting":"target_model_tokenizer","model_id":"mock-model-2026-08-18","op":"handshake","protocol":"milai-provider-adapter-v2","provider":"approved-mock-provider","provider_origin":"https://provider.invalid","ready":true,"tokenizer_id":"mock-tokenizer-v2","usage_source":"native_provider_response"}'
      ;;
    *'"op":"count_request"'*)
      request_id=$(printf '%s' "$line" | sed -n 's/.*"request_id":"\([^"]*\)".*/\1/p')
      case "$line" in
        *'"variant":"baseline"'*) input=240; memory=80; tools=70 ;;
        *'MILAI_MEMORY_DATA'*) input=80; memory=20; tools=20 ;;
        *) input=80; memory=0; tools=0 ;;
      esac
      printf '{"component_tokens":{"memory_context_tokens":%s,"tool_schema_tokens":%s},"input_tokens":%s,"model_id":"mock-model-2026-08-18","op":"count_result","provider":"approved-mock-provider","request_id":"%s","tokenizer_id":"mock-tokenizer-v2","usage_source":"target_model_tokenizer"}\n' "$memory" "$tools" "$input" "$request_id"
      ;;
    *'"op":"model_call"'*)
      request_id=$(printf '%s' "$line" | sed -n 's/.*"request_id":"\([^"]*\)".*/\1/p')
      case "$line" in
        *'"variant":"baseline"'*) input=240 ;;
        *) input=80 ;;
      esac
      case "$line" in
        *'"case_id":"arithmetic"'*) text='{\"answer\":\"7\",\"abstained\":false,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"DIRECT\"}' ;;
        *'"case_id":"fixed-token"'*) text='{\"answer\":\"READY\",\"abstained\":false,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"DIRECT\"}' ;;
        *'"case_id":"format-token"'*) text='{\"answer\":\"alpha-beta\",\"abstained\":false,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"DIRECT\"}' ;;
        *'"case_id":"boolean"'*) text='{\"answer\":\"true\",\"abstained\":false,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"DIRECT\"}' ;;
        *'"case_id":"current-action-safe"'*) text='{\"answer\":\"Python 3.12\",\"abstained\":false,\"open_issue_ids\":[],\"claim_refs\":[\"claim-python-v2\"],\"reason_code\":\"CURRENT_AUTHORIZED\"}' ;;
        *'"case_id":"live-conflict"'*) text='{\"answer\":null,\"abstained\":true,\"open_issue_ids\":[\"issue-python-conflict\"],\"claim_refs\":[\"claim-python-v1\"],\"reason_code\":\"OPEN_CONFLICT\"}' ;;
        *'"case_id":"revoked-grounding"'*) text='{\"answer\":null,\"abstained\":true,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"GROUNDING_BLOCKED\"}' ;;
        *'"case_id":"authority-insufficient"'*) text='{\"answer\":null,\"abstained\":true,\"open_issue_ids\":[],\"claim_refs\":[\"claim-delete-preference\"],\"reason_code\":\"AUTHORITY_INSUFFICIENT\"}' ;;
        *'"case_id":"scope-mismatch"'*) text='{\"answer\":null,\"abstained\":true,\"open_issue_ids\":[],\"claim_refs\":[],\"reason_code\":\"SCOPE_MISMATCH\"}' ;;
      esac
      provider_id="native-${request_id}"
      printf '{"model_id":"mock-model-2026-08-18","native_calls":[{"finish_reason":"stop","model_id":"mock-model-2026-08-18","native_receipt_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","provider_request_id":"%s","terminal":true,"usage":{"cached_input_tokens":0,"input_tokens":%s,"output_tokens":12,"reasoning_tokens":null}}],"op":"model_result","provider":"approved-mock-provider","request_id":"%s","text":"%s","usage":{"cached_input_tokens":0,"input_tokens":%s,"output_tokens":12,"reasoning_tokens":null},"usage_source":"native_provider_response"}\n' "$provider_id" "$input" "$request_id" "$text" "$input"
      ;;
  esac
done
"""

TEST_PROVIDER_CREDENTIAL = "MILAI_PROVIDER_CREDENTIAL_TEST"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _approval_value(
    manifest: Path,
    pricing: Path,
    adapter: Path,
    dependency_lock: Path,
    host_execution_lock: Path,
    runtime: Path,
) -> dict[str, Any]:
    workload, workload_sha = _load_workload()
    tool_hashes = _tool_schema_hashes()
    unshare = Path(shutil.which("unshare") or "").resolve()
    network_hashes = {
        f"{tool}_executable_sha256": (
            None
            if shutil.which(tool) is None
            else _sha256_file(Path(shutil.which(tool) or "").resolve())
        )
        for tool in ("slirp4netns", "nsenter", "nft", "ip")
    }
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        "format": "milai-provider-approval-v3",
        "provider": "approved-mock-provider",
        "provider_origin": "https://provider.invalid",
        "model_id": "mock-model-2026-08-18",
        "tokenizer_id": "mock-tokenizer-v2",
        "data_boundary": DATA_BOUNDARY_ACK,
        "manifest_sha256": _sha256_file(manifest),
        "workload_sha256": workload_sha,
        "pricing_snapshot_sha256": _sha256_file(pricing),
        "runtime_executable_sha256": _sha256_file(runtime),
        "adapter_source_sha256": _sha256_file(adapter),
        "dependency_lock_sha256": _sha256_file(dependency_lock),
        "host_execution_lock_sha256": _sha256_file(host_execution_lock),
        "host_execution_entries_sha256": json.loads(
            host_execution_lock.read_text(encoding="utf-8")
        )["entries_sha256"],
        "host_execution_file_count": json.loads(
            host_execution_lock.read_text(encoding="utf-8")
        )["file_count"],
        "host_execution_policy": HOST_EXECUTION_POLICY,
        "sandbox_launcher_sha256": _sha256_file(SANDBOX_LAUNCHER),
        "sandbox_runtime_sha256": _sha256_file(SANDBOX_RUNTIME),
        "unshare_executable_sha256": _sha256_file(unshare),
        **network_hashes,
        "sandbox_file_policy": SANDBOX_FILE_POLICY,
        "minimum_landlock_abi": 1,
        "reader_tool_schema_sha256": tool_hashes["reader"],
        "reader_lite_tool_schema_sha256": tool_hashes["reader_lite"],
        "secret_environment_names": [TEST_PROVIDER_CREDENTIAL],
        "egress_mode": manifest_value["egress_mode"],
        "provider_ip_addresses": manifest_value["provider_ip_addresses"],
        "run_as_uid": 65534,
        "run_as_gid": 65534,
        "max_provider_requests": 1_000,
        "max_input_tokens_per_request": 1_000,
        "max_output_tokens_per_request": workload["max_output_tokens"],
        "max_cost_usd": "3",
        "billing_tolerance_usd": "0.001",
        "approved_by": "independent-test-operator",
        "approved_at": "2026-08-18T00:00:00Z",
    }


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter_source: str = FAKE_ADAPTER,
    egress_mode: str = "deny-all",
    provider_ip_addresses: list[str] | None = None,
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    adapter = tmp_path / "adapter.sh"
    adapter.write_text(adapter_source, encoding="utf-8")
    runtime = Path("/bin/bash").resolve()
    executables = (runtime, Path(shutil.which("sed") or "").resolve())
    dependency_paths = {str(executables[1])}
    for executable in executables:
        ldd = subprocess.run(
            ["ldd", str(executable)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        dependency_paths.update(
            str(Path(match).resolve())
            for match in re.findall(r"(?:=>\s+)?(/[^\s]+)", ldd)
            if Path(match).resolve().is_file()
        )
    dependency_lock = tmp_path / "adapter-lock.json"
    _write_json(
        dependency_lock,
        {
            "format": "milai-provider-dependency-lock-v1",
            "runtime_executable_sha256": _sha256_file(runtime),
            "files": [
                {"path": path, "sha256": _sha256_file(Path(path))}
                for path in sorted(dependency_paths)
            ],
        },
    )
    host_execution_lock = tmp_path / "host-execution-lock.json"
    _write_json(host_execution_lock, build_host_execution_lock())
    pricing = tmp_path / "pricing.json"
    _write_json(
        pricing,
        {
            "format": "milai-provider-pricing-snapshot-v1",
            "provider": "approved-mock-provider",
            "model_id": "mock-model-2026-08-18",
            "currency": "USD",
            "effective_at": "2026-08-18T00:00:00Z",
            "source_url": "https://provider.invalid/pricing/snapshot",
            "input_per_million": "2",
            "cached_input_per_million": "1",
            "output_per_million": "4",
        },
    )
    approval = tmp_path / "provider-approval.json"
    manifest = tmp_path / "adapter-manifest.json"
    _write_json(
        manifest,
        {
            "format": "milai-provider-adapter-manifest-v3",
            "provider": "approved-mock-provider",
            "provider_origin": "https://provider.invalid",
            "model_id": "mock-model-2026-08-18",
            "tokenizer_id": "mock-tokenizer-v2",
            "runtime_executable_path": str(runtime),
            "runtime_executable_sha256": _sha256_file(runtime),
            "adapter_source_path": str(adapter),
            "adapter_source_sha256": _sha256_file(adapter),
            "dependency_lock_path": str(dependency_lock),
            "dependency_lock_sha256": _sha256_file(dependency_lock),
            "host_execution_lock_path": str(host_execution_lock),
            "host_execution_lock_sha256": _sha256_file(host_execution_lock),
            "secret_environment_names": [TEST_PROVIDER_CREDENTIAL],
            "egress_mode": egress_mode,
            "provider_ip_addresses": provider_ip_addresses or [],
            "run_as_uid": 65534,
            "run_as_gid": 65534,
            "approval_path": str(approval),
        },
    )
    _write_json(
        approval,
        _approval_value(
            manifest,
            pricing,
            adapter,
            dependency_lock,
            host_execution_lock,
            runtime,
        ),
    )
    monkeypatch.setenv(TEST_PROVIDER_CREDENTIAL, "synthetic-provider-secret-7f91")
    approval_sha = _sha256_file(approval)
    plan = build_plan(
        manifest,
        pricing,
        expected_approval_sha256=approval_sha,
        max_input_tokens_per_request=1_000,
        max_cost_usd=Decimal(3),
    )
    return {
        "adapter": adapter,
        "runtime": runtime,
        "dependency_lock": dependency_lock,
        "manifest": manifest,
        "pricing": pricing,
        "approval": approval,
        "host_execution_lock": host_execution_lock,
        "approval_sha": approval_sha,
        "plan": plan,
    }


def _run(inputs: dict[str, Any], *, timeout: float = 5) -> dict[str, Any]:
    return run_provider_ab(
        inputs["manifest"],
        inputs["pricing"],
        expected_approval_sha256=inputs["approval_sha"],
        expected_plan_sha256=inputs["plan"]["plan_sha256"],
        execute_provider=True,
        data_boundary_ack=DATA_BOUNDARY_ACK,
        max_provider_requests=1_000,
        max_input_tokens_per_request=1_000,
        max_cost_usd=Decimal(3),
        timeout_seconds=timeout,
    )


def _billing_files(tmp_path: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    upstream = tmp_path / "provider-invoice.raw"
    upstream.write_bytes(b"synthetic upstream provider invoice\n")
    normalized = tmp_path / "normalized-provider-billing.json"
    records = [
        {
            "provider_request_id": native["provider_request_id"],
            "cost": str(
                Decimal(str(record["expected_cost"])) / len(record["native_calls"])
            ),
        }
        for record in report["records"]
        for native in record["native_calls"]
    ]
    _write_json(
        normalized,
        {
            "format": "milai-normalized-provider-billing-export-v2",
            "provider": report["provider"],
            "model_id": report["model_id"],
            "currency": "USD",
            "period_start": "2026-08-18T00:00:00Z",
            "period_end": "2026-08-19T00:00:00Z",
            "upstream_provider_artifact_sha256": _sha256_file(upstream),
            "records": records,
        },
    )
    evidence = tmp_path / "billing-evidence.json"
    _write_json(
        evidence,
        {
            "format": "milai-provider-billing-evidence-v2",
            "provider": report["provider"],
            "model_id": report["model_id"],
            "currency": "USD",
            "normalized_source_path": str(normalized),
            "normalized_source_sha256": _sha256_file(normalized),
            "upstream_provider_artifact_path": str(upstream),
            "upstream_provider_artifact_sha256": _sha256_file(upstream),
            "source_type": "provider-billing-export",
        },
    )
    return evidence, upstream


def test_frozen_workload_has_exact_recall_rate_and_balanced_cases() -> None:
    workload, workload_sha = _load_workload()
    turns = _turns(workload, 500)
    assert len(turns) == 500
    assert sum(turn.requires_memory for turn in turns) == 100
    assert len({turn.case_id for turn in turns if turn.requires_memory}) == 5
    assert len({turn.case_id for turn in turns if not turn.requires_memory}) == 4
    assert len(workload_sha) == 64


def test_runner_uses_exact_shipped_reader_and_reader_lite_schemas() -> None:
    from milai_client.models import AgentRecallPolicy
    from milai_client.tools import create_milai_tools

    policy = AgentRecallPolicy(scope={"project": "synthetic-milai"}, max_limit=3)
    expected_reader = tuple(
        tool.as_function_schema()
        for tool in create_milai_tools(
            client=object(), recall_policy=policy, profile="reader"
        )
    )
    expected_lite = tuple(
        tool.as_function_schema()
        for tool in create_milai_tools(
            client=object(), recall_policy=policy, profile="reader-lite"
        )
    )
    assert _reader_detail_tools() == expected_reader
    assert _reader_lite_tools() == expected_lite
    assert len(expected_reader) == 6
    assert len(expected_lite) == 1


def test_request_payload_uses_shipped_baseline_tools_and_optimized_none() -> None:
    workload, workload_sha = _load_workload()
    non_memory = _turns(workload, 2)[1]
    baseline, baseline_private = _request_payload(
        workload, workload_sha, non_memory, "baseline", "provider", "model"
    )
    optimized, optimized_private = _request_payload(
        workload, workload_sha, non_memory, "optimized", "provider", "model"
    )
    assert len(baseline["tools"]) == 6
    assert optimized["tools"] == ()
    assert baseline_private["memory_context"]
    assert optimized_private["memory_context"] == ""
    assert baseline["request_id"] != optimized["request_id"]


def test_output_scoring_fails_closed_on_prose_or_forbidden_stale_value() -> None:
    expected = {
        "answer": None,
        "abstained": True,
        "open_issue_ids": [],
        "claim_refs": [],
        "reason_code": "GROUNDING_BLOCKED",
    }
    prose = _score_output(
        "I think eu-west is fine", expected, ["eu-west"], ["revocation"]
    )
    assert prose["passed"] is False
    assert prose["dimensions"]["strict_json_contract"] is False


def test_plan_is_out_of_band_bound_and_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    plan = inputs["plan"]
    assert plan["binding"]["provider_request_count"] == 1_000
    assert plan["network_executed"] is False
    assert plan["authorized_by_cost_limit"] is True
    assert len(plan["plan_sha256"]) == 64
    with pytest.raises(ProviderEvidenceError, match="out-of-band digest"):
        build_plan(
            inputs["manifest"],
            inputs["pricing"],
            expected_approval_sha256="0" * 64,
            max_input_tokens_per_request=1_000,
            max_cost_usd=Decimal(3),
        )


def test_host_execution_lock_is_complete_and_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    manifest, _digest, _environment, _secrets = _manifest(
        inputs["manifest"], expected_approval_sha256=inputs["approval_sha"]
    )
    host_lock = manifest["host_execution_lock"]
    assert host_lock == build_host_execution_lock()
    assert host_lock["policy"] == HOST_EXECUTION_POLICY
    assert host_lock["file_count"] == len(host_lock["files"])
    assert (
        host_lock["entries_sha256"]
        == hashlib.sha256(_canonical_bytes(host_lock["files"])).hexdigest()
    )
    roles = {role for item in host_lock["files"] for role in item["roles"]}
    assert {
        "sandbox-launcher",
        "sandbox-runtime",
        "sandbox-python-import",
        "namespace-helper:unshare",
        "dynamic-dependency",
    } <= roles
    adapter_paths = {item["path"] for item in manifest["dependency_lock"]["files"]}
    host_dynamic_paths = {
        item["path"]
        for item in host_lock["files"]
        if "dynamic-dependency" in item["roles"]
    }
    assert host_dynamic_paths - adapter_paths
    host_paths = {item["path"] for item in host_lock["files"]}
    privileged_executables = [SANDBOX_RUNTIME]
    for name in ("unshare", "slirp4netns", "nsenter", "nft", "ip"):
        resolved = shutil.which(name, path=HOST_TOOL_SEARCH_PATH)
        if resolved is not None:
            privileged_executables.append(Path(resolved).resolve())
    independently_resolved: set[str] = set()
    for executable in privileged_executables:
        output = subprocess.run(
            ["/usr/bin/ldd", str(executable)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        independently_resolved.update(
            str(Path(match).resolve())
            for match in re.findall(r"(?:=>\s+)?(/[^\s]+)", output)
            if Path(match).resolve().is_file()
        )
    assert independently_resolved <= host_paths
    assert (
        inputs["plan"]["binding"]["host_execution_entries_sha256"]
        == host_lock["entries_sha256"]
    )


def test_incomplete_host_execution_lock_fails_despite_fresh_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    host_lock = json.loads(inputs["host_execution_lock"].read_text(encoding="utf-8"))
    removed = next(
        item for item in host_lock["files"] if "dynamic-dependency" in item["roles"]
    )
    host_lock["files"].remove(removed)
    host_lock["file_count"] = len(host_lock["files"])
    host_lock["entries_sha256"] = hashlib.sha256(
        _canonical_bytes(host_lock["files"])
    ).hexdigest()
    _write_json(inputs["host_execution_lock"], host_lock)
    manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
    manifest["host_execution_lock_sha256"] = _sha256_file(inputs["host_execution_lock"])
    _write_json(inputs["manifest"], manifest)
    _write_json(
        inputs["approval"],
        _approval_value(
            inputs["manifest"],
            inputs["pricing"],
            inputs["adapter"],
            inputs["dependency_lock"],
            inputs["host_execution_lock"],
            inputs["runtime"],
        ),
    )
    with pytest.raises(ProviderEvidenceError, match="independently enumerated"):
        build_plan(
            inputs["manifest"],
            inputs["pricing"],
            expected_approval_sha256=_sha256_file(inputs["approval"]),
            max_input_tokens_per_request=1_000,
            max_cost_usd=Decimal(3),
        )


@pytest.mark.parametrize(
    "untrusted_name",
    ["PGPASSWORD", "PYTHONPATH", "LD_PRELOAD", "BASH_ENV", "NODE_OPTIONS"],
)
def test_manifest_is_closed_and_rejects_execution_control_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, untrusted_name: str
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
    manifest["command"] = ["/bin/bash", "decoy", "--api-key", "value"]
    _write_json(inputs["manifest"], manifest)
    with pytest.raises(ProviderEvidenceError, match="closed schema"):
        _manifest(
            inputs["manifest"],
            expected_approval_sha256=inputs["approval_sha"],
        )

    inputs = _inputs(tmp_path / "second", monkeypatch)
    manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
    manifest["secret_environment_names"] = [untrusted_name]
    _write_json(inputs["manifest"], manifest)
    with pytest.raises(ProviderEvidenceError, match="MILAI_PROVIDER_CREDENTIAL"):
        _manifest(
            inputs["manifest"],
            expected_approval_sha256=inputs["approval_sha"],
        )


def test_full_capture_runs_as_distinct_uid_with_workspace_hidden_and_never_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    report = _run(inputs)
    assert report["format"] == REPORT_FORMAT
    assert report["status"] == "PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED"
    assert "PASS" not in report["status"]
    assert report["provider_usage_claimed_native"] is True
    assert report["provider_usage_verified"] is False
    assert report["independent_provider_review_required"] is True
    assert len(report["records"]) == 1_000
    assert report["execution"]["native_model_calls"] == 1_000
    assert report["execution"]["host_execution"] == {
        "policy": HOST_EXECUTION_POLICY,
        "file_count": report["provider_approval"]["host_execution_file_count"],
        "entries_sha256": report["provider_approval"]["host_execution_entries_sha256"],
        "pre_execution_verified": True,
        "post_execution_revalidated": True,
    }
    assert all(report["gates"].values())
    encoded = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "MILAI_MEMORY_DATA",
        "ev-runtime-311 says 3.11",
        "synthetic-provider-secret-7f91",
        '"text":',
        '"messages":',
    ):
        assert forbidden not in encoded


def test_undeclared_host_executable_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = FAKE_ADAPTER.replace(
        'if [ "$EUID" -ne 65534 ]; then\n',
        '/usr/bin/cat --version >/dev/null\nif [ "$EUID" -ne 65534 ]; then\n',
    )
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=source)
    manifest, _digest, _environment, _secrets = _manifest(
        inputs["manifest"],
        expected_approval_sha256=inputs["approval_sha"],
    )
    locked = {item["path"] for item in manifest["dependency_lock"]["files"]}
    assert str(Path("/usr/bin/sed").resolve()) in locked
    assert str(Path("/usr/bin/cat").resolve()) not in locked
    report = _run(inputs, timeout=1)
    assert report["status"] == "FAIL_PARTIAL"
    assert report["execution"]["provider_requests"] == 0


def test_https_origin_ip_allowlist_permits_only_approved_local_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers: list[subprocess.Popen[bytes]] = []
    final_hash_helper_alive: list[bool] = []
    observed_errors: list[str] = []
    in_exit = False
    original_fd_hash = provider_ab_module._sha256_fd
    original_file_hash = provider_ab_module._sha256_file

    class ObservedAdapterProcess(AdapterProcess):
        def _configure_network(self) -> None:
            try:
                super()._configure_network()
            except Exception as exc:
                observed_errors.append(f"configure: {exc}")
                raise
            if self._network_process is not None:
                helpers.append(self._network_process)

        def __exit__(self, *_args: object) -> None:
            nonlocal in_exit
            in_exit = True
            try:
                super().__exit__(*_args)
            except Exception as exc:
                observed_errors.append(f"exit: {exc}")
                raise
            finally:
                in_exit = False

    def observed_fd_hash(descriptor: int) -> str:
        if in_exit and helpers:
            final_hash_helper_alive.append(helpers[-1].poll() is None)
        return original_fd_hash(descriptor)

    def observed_file_hash(path: Path) -> str:
        if in_exit and helpers:
            final_hash_helper_alive.append(helpers[-1].poll() is None)
        return original_file_hash(path)

    monkeypatch.setattr(provider_ab_module, "AdapterProcess", ObservedAdapterProcess)
    monkeypatch.setattr(provider_ab_module, "_sha256_fd", observed_fd_hash)
    monkeypatch.setattr(provider_ab_module, "_sha256_file", observed_file_hash)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("0.0.0.0", 443))
    except OSError:
        listener.close()
        pytest.skip("local TCP/443 is unavailable for namespace allowlist test")
    listener.listen(1)
    listener.settimeout(12)
    accepted: list[bool] = []

    def accept_once() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                accepted.append(connection.recv(4) == b"PING")
        except TimeoutError:
            pass
        finally:
            listener.close()

    thread = threading.Thread(target=accept_once, daemon=True)
    thread.start()
    source = FAKE_ADAPTER.replace(
        "if (exec 3<>/dev/tcp/1.1.1.1/443) 2>/dev/null; then\n  exit 72\nfi\n",
        "exec 4<>/dev/tcp/provider.invalid/443\nprintf PING >&4\nexec 4>&-\n",
    )
    inputs = _inputs(
        tmp_path,
        monkeypatch,
        adapter_source=source,
        egress_mode="https-origin-ip-allowlist",
        provider_ip_addresses=["10.0.2.2"],
    )
    report = _run(inputs)
    thread.join(timeout=10)
    assert report["status"] == "PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED", (
        observed_errors,
        report["failure"],
    )
    assert accepted == [True]
    assert helpers and helpers[-1].poll() is not None
    assert final_hash_helper_alive
    assert not any(final_hash_helper_alive)


def test_helper_shutdown_failure_never_claims_post_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    manifest, _digest, environment, secrets = _manifest(
        inputs["manifest"], expected_approval_sha256=inputs["approval_sha"]
    )

    class UnstoppableHelperProcess(AdapterProcess):
        def _stop_network_helper(self) -> bool:
            return False

    adapter = UnstoppableHelperProcess(
        manifest, environment, secrets, timeout_seconds=1
    )
    with (
        pytest.raises(ProviderEvidenceError, match="network helper did not stop"),
        adapter,
    ):
        pass
    assert adapter.host_execution_evidence()["post_execution_revalidated"] is False


def test_run_rejects_wrong_plan_before_adapter_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "adapter-started"
    source = f"touch {marker}\n" + FAKE_ADAPTER
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=source)
    with pytest.raises(ProviderEvidenceError, match="plan digest"):
        run_provider_ab(
            inputs["manifest"],
            inputs["pricing"],
            expected_approval_sha256=inputs["approval_sha"],
            expected_plan_sha256="0" * 64,
            execute_provider=True,
            data_boundary_ack=DATA_BOUNDARY_ACK,
            max_provider_requests=1_000,
            max_input_tokens_per_request=1_000,
            max_cost_usd=Decimal(3),
            timeout_seconds=1,
        )
    assert not marker.exists()


def test_secret_reflection_fails_to_privacy_bounded_partial_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reflected = FAKE_ADAPTER.replace(
        'provider_id="native-${request_id}"',
        f'provider_id="native-${{{TEST_PROVIDER_CREDENTIAL}}}"',
    )
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=reflected)
    report = _run(inputs)
    assert report["status"] == "FAIL_PARTIAL"
    assert report["execution"]["provider_requests"] == 0
    assert "synthetic-provider-secret-7f91" not in json.dumps(report)
    assert set(report["failure"]) == {
        "code",
        "after_validated_provider_requests",
        "reason_sha256",
    }


def test_pre_call_target_token_limit_stops_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "charged-model-call"
    oversized = FAKE_ADAPTER.replace(
        'request_id=$(printf \'%s\' "$line" | sed -n \'s/.*"request_id":"\\([^"]*\\)".*/\\1/p\')\n      case "$line" in\n        *\'"variant":"baseline"\'*) input=240; memory=80; tools=70 ;;',
        'request_id=$(printf \'%s\' "$line" | sed -n \'s/.*"request_id":"\\([^"]*\\)".*/\\1/p\')\n      case "$line" in\n        *\'"variant":"baseline"\'*) input=2000; memory=80; tools=70 ;;',
        1,
    ).replace(
        '*\'"op":"model_call"\'*)\n',
        f'*\'"op":"model_call"\'*)\n      touch {marker}\n',
    )
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=oversized)
    report = _run(inputs)
    assert report["status"] == "FAIL_PARTIAL"
    assert report["execution"]["provider_requests"] == 0
    assert not marker.exists()


def test_partial_line_timeout_is_total_deadline_and_kills_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stalled = "printf '{'\nwhile :; do :; done\n"
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=stalled)
    started = time.monotonic()
    report = _run(inputs, timeout=0.15)
    elapsed = time.monotonic() - started
    assert report["status"] == "FAIL_PARTIAL"
    assert elapsed < 2
    assert report["execution"]["provider_requests"] == 0


def test_oversized_input_uses_the_same_deadline_and_kills_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch, adapter_source="while :; do :; done\n")
    manifest, _digest, environment, secrets = _manifest(
        inputs["manifest"],
        expected_approval_sha256=inputs["approval_sha"],
    )
    started = time.monotonic()
    with (
        AdapterProcess(
            manifest,
            environment,
            secrets,
            timeout_seconds=0.2,
        ) as adapter,
        pytest.raises(ProviderEvidenceError, match="adapter input timed out"),
    ):
        adapter.exchange({"op": "oversized", "payload": "x" * 4_000_000})
    assert time.monotonic() - started < 3


def test_late_partial_line_failure_retains_only_validated_cost_and_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    late = ("model_calls=0\n" + FAKE_ADAPTER).replace(
        '*\'"op":"model_call"\'*)\n',
        '*\'"op":"model_call"\'*)\n'
        "      model_calls=$((model_calls + 1))\n"
        '      if [ "$model_calls" -eq 4 ]; then '
        "printf '{'; while :; do :; done; fi\n",
    )
    inputs = _inputs(tmp_path, monkeypatch, adapter_source=late)
    report = _run(inputs, timeout=0.15)
    assert report["status"] == "FAIL_PARTIAL"
    assert report["execution"]["provider_requests"] == 3
    assert report["execution"]["native_model_calls"] == 3
    assert len(report["records"]) == 3
    assert Decimal(report["execution"]["actual_expected_cost"]) > 0


def test_model_result_rejects_hidden_rounds_usage_mismatch_and_nonterminal_state() -> (
    None
):
    request = {"request_id": "oe-ab-request", "max_output_tokens": 10}
    manifest = {"provider": "provider", "model_id": "model"}
    native = {
        "provider_request_id": "native-request-0001",
        "model_id": "model",
        "usage": {
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "output_tokens": 1,
            "reasoning_tokens": None,
        },
        "terminal": True,
        "finish_reason": "stop",
        "native_receipt_sha256": "a" * 64,
    }
    response = {
        "op": "model_result",
        "request_id": "oe-ab-request",
        "provider": "provider",
        "model_id": "model",
        "usage_source": "native_provider_response",
        "text": "{}",
        "usage": dict(native["usage"]),
        "native_calls": [native],
    }
    bad_usage = json.loads(json.dumps(response))
    bad_usage["native_calls"].append(
        dict(native, provider_request_id="native-request-0002")
    )
    with pytest.raises(ProviderEvidenceError, match="does not equal"):
        _validate_model_result(bad_usage, request, manifest, counted_input_tokens=10)
    nonterminal = json.loads(json.dumps(response))
    nonterminal["native_calls"][0]["terminal"] = False
    with pytest.raises(ProviderEvidenceError, match="terminal"):
        _validate_model_result(nonterminal, request, manifest, counted_input_tokens=10)


def test_reconciliation_recomputes_complete_capture_and_never_returns_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    report = _run(inputs)
    report_path = tmp_path / "report.json"
    _write_json(report_path, report)
    evidence, _upstream = _billing_files(tmp_path, report)
    reconciled = reconcile_billing(
        report_path,
        evidence,
        inputs["manifest"],
        inputs["pricing"],
        expected_report_sha256=_sha256_file(report_path),
        expected_approval_sha256=inputs["approval_sha"],
        expected_plan_sha256=inputs["plan"]["plan_sha256"],
    )
    assert reconciled["status"] == "PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED"
    assert "PASS" not in reconciled["status"]
    assert reconciled["provider_usage_verified"] is False
    assert reconciled["execution"]["billing_reconciled"] is True
    assert _command_exit_code("run", report["status"]) == 3
    assert _command_exit_code("reconcile", reconciled["status"]) == 3
    assert _command_exit_code("plan", None) == 0


@pytest.mark.parametrize(
    "mutation",
    ["empty_gates", "short_records", "forged_quality", "extra_normalized_field"],
)
def test_reconciliation_rejects_forged_complete_reports_even_with_new_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    report = _run(inputs)
    if mutation == "empty_gates":
        report["gates"] = {}
    elif mutation == "short_records":
        report["records"].pop()
    elif mutation == "forged_quality":
        report["records"][0]["quality"]["passed"] = False
    else:
        report["records"][0]["normalized_output"]["private_body"] = (
            "must-not-survive-reconciliation"
        )
    report_path = tmp_path / "forged-report.json"
    _write_json(report_path, report)
    evidence, _upstream = _billing_files(tmp_path, report)
    with pytest.raises(ProviderEvidenceError):
        reconcile_billing(
            report_path,
            evidence,
            inputs["manifest"],
            inputs["pricing"],
            expected_report_sha256=_sha256_file(report_path),
            expected_approval_sha256=inputs["approval_sha"],
            expected_plan_sha256=inputs["plan"]["plan_sha256"],
        )


def test_reconciliation_requires_the_real_upstream_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    report = _run(inputs)
    report_path = tmp_path / "report.json"
    _write_json(report_path, report)
    evidence, upstream = _billing_files(tmp_path, report)
    upstream.unlink()
    with pytest.raises(ProviderEvidenceError, match="regular file"):
        reconcile_billing(
            report_path,
            evidence,
            inputs["manifest"],
            inputs["pricing"],
            expected_report_sha256=_sha256_file(report_path),
            expected_approval_sha256=inputs["approval_sha"],
            expected_plan_sha256=inputs["plan"]["plan_sha256"],
        )


def test_billing_sidecar_cannot_override_approved_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    report = _run(inputs)
    report_path = tmp_path / "report.json"
    _write_json(report_path, report)
    evidence, _upstream = _billing_files(tmp_path, report)
    value = json.loads(evidence.read_text(encoding="utf-8"))
    value["tolerance"] = "1000"
    _write_json(evidence, value)
    with pytest.raises(ProviderEvidenceError, match="closed schema"):
        reconcile_billing(
            report_path,
            evidence,
            inputs["manifest"],
            inputs["pricing"],
            expected_report_sha256=_sha256_file(report_path),
            expected_approval_sha256=inputs["approval_sha"],
            expected_plan_sha256=inputs["plan"]["plan_sha256"],
        )


def test_atomic_writer_leaves_one_complete_json_object(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    _write_json(target, {"old": True})
    _atomic_write_json(target, {"status": "FAIL_PARTIAL", "records": []})
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "records": [],
        "status": "FAIL_PARTIAL",
    }
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))


def test_budget_gates_use_maximum_per_request_not_only_aggregate() -> None:
    workload, _ = _load_workload()
    variant = {
        "model_calls": 500,
        "native_model_calls": 500,
        "usage": {"input_tokens": 10_000},
        "component_tokens": {
            "memory_context_tokens": 2_000,
            "tool_schema_tokens": 2_000,
        },
        "max_component_tokens": {
            "memory_context_tokens": 2_001,
            "tool_schema_tokens": 251,
        },
        "quality_rate": 1.0,
        "safety_failures": {},
        "expected_cost": "1",
    }
    baseline = dict(variant)
    baseline["usage"] = {"input_tokens": 20_000}
    baseline["expected_cost"] = "2"
    aggregates = {
        str(count): {
            "baseline": baseline,
            "optimized": variant,
            "extra_optimized_model_round_trips": 0,
        }
        for count in (100, 500)
    }
    aggregates["100"]["baseline"] = dict(baseline, model_calls=100)
    aggregates["100"]["optimized"] = dict(variant, model_calls=100)
    gates = _gates(workload, aggregates)
    assert gates["100_turn_milai_tokens_under_30000"] is True
    assert gates["100_memory_budget"] is False
    assert gates["100_tool_budget"] is False


def test_canonical_json_is_stable() -> None:
    assert _canonical_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert hashlib.sha256(_canonical_bytes({"a": 1})).hexdigest() == (
        "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
    )
