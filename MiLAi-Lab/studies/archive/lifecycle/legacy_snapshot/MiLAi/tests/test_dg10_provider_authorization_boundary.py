from __future__ import annotations

import inspect
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_efficiency import vllm_local_ab
from evals.agent_efficiency import vllm_openworker_adapter as openworker_adapter
from scripts import build_dg10_candidate4_identities as identities
from scripts import dg10_post_r3_provider_gate as post_r3_gate
from scripts import dg10_remediation as remediation
from scripts import run_dg10_remediation
from scripts import run_dg10_serving_characterization as serving


def test_local_completion_fails_before_network_without_post_r3_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def denied() -> dict[str, object]:
        raise post_r3_gate.PostR3ProviderGateError("R3 absent")

    def opener() -> object:
        nonlocal opened
        opened = True
        raise AssertionError("network must remain unreachable")

    monkeypatch.setattr(
        vllm_local_ab.post_r3_gate, "require_post_r3_provider_access", denied
    )
    monkeypatch.setattr(vllm_local_ab.identity, "local_opener", opener)
    with pytest.raises(
        vllm_local_ab.LocalVllmCaptureError,
        match="denied before R3 acceptance",
    ):
        vllm_local_ab._post_json(
            "http://127.0.0.1:7860",
            "/v1/chat/completions",
            {"model": vllm_local_ab.MODEL_ID, "messages": []},
            timeout=1,
        )
    assert opened is False


def test_openworker_completion_fails_before_network_without_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def opener() -> object:
        nonlocal opened
        opened = True
        raise AssertionError("network must remain unreachable")

    monkeypatch.setattr(openworker_adapter, "_post_r3_capability", None)
    monkeypatch.setattr(openworker_adapter, "_opener", opener)
    with pytest.raises(openworker_adapter.AdapterError, match="capability"):
        openworker_adapter._upstream_json(
            "http://172.17.0.1:7860",
            "/v1/chat/completions",
            payload={"model": openworker_adapter.MODEL_ID, "messages": []},
        )
    assert opened is False


def test_buffered_serving_completion_fails_before_network_without_post_r3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def denied() -> dict[str, object]:
        raise post_r3_gate.PostR3ProviderGateError("R3 absent")

    class SpyOpener:
        def open(self, *_args: object, **_kwargs: object) -> object:
            nonlocal opened
            opened = True
            raise AssertionError("network must remain unreachable")

    monkeypatch.setattr(
        serving.post_r3_gate, "require_post_r3_provider_access", denied
    )
    monkeypatch.setattr(serving, "_NO_PROXY_OPENER", SpyOpener())
    with pytest.raises(serving.ServingError, match="denied before R3 acceptance"):
        serving._json_completion(
            url="http://127.0.0.1:3001/v1/chat/completions",
            payload={"model": "AUTO", "messages": []},
            headers={},
            timeout=1,
            tier="T1",
            concurrency=1,
            request_index=0,
            case_id="case-0",
        )
    assert opened is False


def test_opencode_serving_completion_fails_before_subprocess_without_post_r3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed = False

    def denied() -> dict[str, object]:
        raise post_r3_gate.PostR3ProviderGateError("R3 absent")

    def run(*_args: object, **_kwargs: object) -> object:
        nonlocal executed
        executed = True
        raise AssertionError("subprocess must remain unreachable")

    monkeypatch.setattr(
        serving.post_r3_gate, "require_post_r3_provider_access", denied
    )
    monkeypatch.setattr(serving.openworker_e2e, "_run", run)
    with pytest.raises(serving.ServingError, match="denied before R3 acceptance"):
        serving._opencode_completion(
            harness=SimpleNamespace(worker_name="worker"),  # type: ignore[arg-type]
            prompt="hello",
            tier="T2",
            concurrency=1,
            request_index=0,
            case_id="case-0",
        )
    assert executed is False


def test_each_serving_completion_transport_gates_before_its_io_callsite() -> None:
    transports = {
        serving._stream_completion: "_NO_PROXY_OPENER.open",
        serving._json_completion: "_NO_PROXY_OPENER.open",
        serving._opencode_completion: "openworker_e2e._run",
    }
    for function, side_effect in transports.items():
        source = inspect.getsource(function)
        assert source.count("_require_post_r3_completion_access()") == 1
        assert source.index("_require_post_r3_completion_access()") < source.index(
            side_effect
        )


def test_container_capability_is_derived_from_replayed_post_r3_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization_path = tmp_path / "post-r3.json"
    authorization_path.write_text("{}\n", encoding="utf-8")
    stage_digest = "a" * 64
    source_root = "b" * 64
    envelope = {
        "authorization": {
            "stage_receipts": [
                {"path": f"stage-{index}.json", "sha256": stage_digest}
                for index in range(4)
            ],
            "identities": {"source_inventory_sha256": source_root},
        }
    }
    monkeypatch.setattr(
        post_r3_gate, "ACTIVE_POST_R3_AUTHORIZATION", authorization_path
    )
    monkeypatch.setattr(
        post_r3_gate, "require_post_r3_provider_access", lambda: envelope
    )
    output = tmp_path / "run/capability.json"
    capability = post_r3_gate.materialize_container_capability(output)
    assert json.loads(output.read_text(encoding="utf-8")) == capability
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    assert capability["authorization_sha256"] == remediation.sha256_file(
        authorization_path
    )
    assert capability["r3_stage_receipt_sha256"] == stage_digest
    assert capability["source_inventory_root_sha256"] == source_root


def test_post_r3_preflight_requests_no_test_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"authorized": True, "reason_codes": []}

    monkeypatch.setattr(
        run_dg10_remediation.authorization,
        "evaluate_first_model_authorization",
        evaluate,
    )
    report = run_dg10_remediation.post_r3_preflight(
        candidate=remediation.CANDIDATE,
        planned_model_calls=300,
        r0_r2_aggregate_path=Path("aggregate.json"),
        r3_stage_receipt_path=Path("r3.json"),
        identity_receipt_path=Path("identities.json"),
    )
    assert report["status"] == "AUTHORIZED_READY_FOR_POST_R3_EXECUTION"
    assert report["provider_requests"] == 0
    assert captured["phase"] == run_dg10_remediation.authorization.POST_R3_PHASE
    assert captured["planned_model_calls"] == 300
    assert captured["test_access_requested"] is False


def test_successful_post_r3_cli_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        run_dg10_remediation.authorization,
        "evaluate_first_model_authorization",
        lambda **_kwargs: {"authorized": True, "reason_codes": []},
    )
    output = tmp_path / "post-r3.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_dg10_remediation.py",
            "--phase",
            "post-r3",
            "--candidate",
            remediation.CANDIDATE,
            "--planned-model-calls",
            "300",
            "--r3-stage-receipt",
            str(tmp_path / "r3.json"),
            "--output",
            str(output),
        ],
    )
    run_dg10_remediation.main()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == (
        "AUTHORIZED_READY_FOR_POST_R3_EXECUTION"
    )


def test_every_completion_literal_is_inside_the_fixed_boundary_closure() -> None:
    expected = {
        "evals/agent_efficiency/vllm_local_ab.py": "require_post_r3_provider_access",
        "evals/agent_efficiency/vllm_openworker_adapter.py": (
            "completion denied without fixed post-R3 capability"
        ),
        "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py": (
            "ProviderExecutionGateway"
        ),
        "runtime/src/milai/adapters/provider_execution.py": (
            "class ProviderExecutionGateway"
        ),
        "scripts/dg10_t2_provider_adapter.py": "_validated_bootstrap_binding",
        "scripts/run_dg10_benchmark_dev_smoke.py": "vllm_local_ab._post_json",
        "scripts/run_dg10_benchmark_milai_mcp_smoke.py": (
            "_dg10_original_upstream_json"
        ),
        "scripts/run_dg10_bfcl_multiturn_generation_worker.py": (
            "vllm_local_ab._post_json"
        ),
        "scripts/run_dg10_bfcl_prompt_capability_probe.py": (
            "vllm_local_ab._post_json"
        ),
        "scripts/run_dg10_bfcl_single_turn_dev_smoke.py": (
            "vllm_local_ab._post_json"
        ),
        "scripts/run_dg10_serving_characterization.py": (
            "_require_post_r3_completion_access"
        ),
        "scripts/run_dg10_tier3_same_vllm_judge.py": (
            "dev_smoke.vllm_local_ab._post_json"
        ),
    }
    observed: dict[str, str] = {}
    for path in identities.source_paths():
        relative = path.relative_to(remediation.ROOT).as_posix()
        if path.suffix != ".py" or relative.startswith("tests/"):
            continue
        source = path.read_text(encoding="utf-8")
        if "/v1/chat/completions" in source:
            observed[relative] = source
    assert set(observed) == set(expected)
    for relative, boundary_marker in expected.items():
        assert boundary_marker in observed[relative]
