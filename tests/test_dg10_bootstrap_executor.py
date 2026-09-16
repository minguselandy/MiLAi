from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from typing import Self

import pytest

from scripts import dg10_bootstrap_executor as executor
from scripts import dg10_remediation as remediation
from scripts import dg10_t2_provider_adapter as provider_adapter


def _receipt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "milai.dg10.remediation-smoke-preflight.v1",
                "candidate_id": remediation.CANDIDATE,
                "status": "AUTHORIZED_READY_FOR_T2_EXECUTION",
                "provider_requests": 0,
                "model_outputs_opened": False,
                "test_access_authorized": False,
                "authorization": {
                    "authorization_payload_sha256": "a" * 64,
                    "call_slot_manifest_sha256": "b" * 64,
                },
            }
        )
        + "\n"
    )
    return path


def _sealed_adapter_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    slot_id: str = "slot-01",
) -> dict[str, object]:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    slots = tuple(f"slot-{index:02d}" for index in range(24))
    monkeypatch.setattr(
        provider_adapter.authorization,
        "authorized_bootstrap_slots",
        lambda _value: slots,
    )
    fixed_root = tmp_path / "var/dg10/t2-bootstrap-candidate.4"
    ledger_path = fixed_root / "attempts.jsonl"
    capability_path = fixed_root / "execution-capability.json"
    request_root = fixed_root / "provider-requests"
    claim_root = fixed_root / "provider-claims"
    raw_root = fixed_root / "raw-sidecars"
    failure_latch_path = fixed_root / "failure-latch.json"
    authorization_path = _receipt(
        tmp_path
        / "docs/reports/DG-10-model-run-authorization-candidate.4-2026-08-22.json"
    )
    ledger = remediation.AttemptLedger(
        ledger_path, authorized_model_call_slots=slots
    )
    ledger.start_attempt(
        phase="T2_CONTROL_PATH_SMOKE",
        arm="T2_CONTROL_PATH",
        case_id="case-01",
        planned_model_calls=1,
        planned_mcp_calls=0,
        attempt_id=slot_id,
    )
    request_id = "dg10-t2-request-" + "a" * 32
    document = provider_adapter.request_document(
        request_id=request_id,
        messages=[{"role": "user", "content": "sealed"}],
    )
    capability = {
        "schema": "milai.dg10.bootstrap-execution-capability.v1",
        "candidate_id": remediation.CANDIDATE,
        "phase": "T2_CONTROL_PATH_SMOKE",
        "authorization_receipt": {
            "path": authorization_path.relative_to(tmp_path).as_posix(),
            "sha256": remediation.sha256_file(authorization_path),
        },
        "authorization_payload_sha256": "a" * 64,
        "call_slot_manifest_sha256": "b" * 64,
        "authorized_model_call_count": 24,
        "fixed_ledger_path": ledger_path.relative_to(tmp_path).as_posix(),
        "fixed_failure_latch_path": failure_latch_path.relative_to(
            tmp_path
        ).as_posix(),
        "fixed_request_root": request_root.relative_to(tmp_path).as_posix(),
        "fixed_provider_claim_root": claim_root.relative_to(tmp_path).as_posix(),
        "fixed_raw_sidecar_root": raw_root.relative_to(tmp_path).as_posix(),
        "remaining_execution_capabilities": 0,
    }
    capability_path.parent.mkdir(parents=True, exist_ok=True)
    capability_path.write_bytes(remediation.encoded_json(capability))
    request_receipt_path = request_root / f"{slot_id}.json"
    request_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    request_receipt_path.write_bytes(
        remediation.encoded_json(
            {
                "schema": "milai.dg10.t2-provider-request.v1",
                "candidate_id": remediation.CANDIDATE,
                "slot_id": slot_id,
                "request_id": request_id,
                "endpoint": provider_adapter.ENDPOINT,
                "model_id": provider_adapter.MODEL_ID,
                "request_payload_sha256": remediation.sha256_bytes(
                    remediation.encoded_json(document)
                ),
                "adapter_sha256": remediation.sha256_file(
                    Path(provider_adapter.__file__).resolve()
                ),
                "planned_provider_request_count": 1,
            }
        )
    )
    return {
        "slot_id": slot_id,
        "request_id": request_id,
        "document": document,
        "ledger": ledger,
        "ledger_path": ledger_path,
        "capability_path": capability_path,
        "request_receipt_path": request_receipt_path,
        "provider_claim_path": claim_root / f"{slot_id}.json",
        "raw_sidecar_path": raw_root / f"{slot_id}.json",
        "failure_latch_path": failure_latch_path,
    }


def _adapter_kwargs(context: dict[str, object]) -> dict[str, object]:
    return {
        "slot_id": context["slot_id"],
        "attempt_id": context["slot_id"],
        "request_id": context["request_id"],
        "request_document_value": context["document"],
        "ledger": context["ledger"],
        "ledger_path": context["ledger_path"],
        "execution_capability_path": context["capability_path"],
        "request_receipt_path": context["request_receipt_path"],
        "provider_claim_path": context["provider_claim_path"],
        "raw_sidecar_path": context["raw_sidecar_path"],
        "failure_latch_path": context["failure_latch_path"],
    }


def test_provider_boundary_journals_slot_before_call_and_latches_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    slots = tuple(f"slot-{index:02d}" for index in range(24))
    monkeypatch.setattr(
        executor.authorization,
        "authorized_bootstrap_slots",
        lambda _receipt: slots,
    )
    authorization_path = _receipt(tmp_path / "authorization.json")
    ledger_path = tmp_path / "attempts.jsonl"
    latch_path = tmp_path / "failure-latch.json"
    capability_path = tmp_path / "execution-capability.json"
    request_root = tmp_path / "provider-requests"
    claim_root = tmp_path / "provider-claims"
    raw_root = tmp_path / "raw-sidecars"
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_AUTHORIZATION", authorization_path)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_LEDGER", ledger_path)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_FAILURE_LATCH", latch_path)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY", capability_path)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_REQUEST_ROOT", request_root)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_CLAIM_ROOT", claim_root)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_RAW_ROOT", raw_root)
    with executor.BootstrapModelExecutor() as boundary:
        def failed_provider(**_kwargs: object) -> object:
            snapshots = remediation.read_attempt_ledger(ledger_path)
            assert snapshots[-1]["attempt_state"] == "PLANNED"
            assert snapshots[-1]["attempt_id"] == slots[0]
            request_receipt = json.loads(
                (request_root / f"{slots[0]}.json").read_text()
            )
            assert request_receipt["request_id"].startswith("dg10-t2-request-")
            assert request_receipt["planned_provider_request_count"] == 1
            raise RuntimeError("provider failed")

        monkeypatch.setattr(executor.provider_adapter, "request_once", failed_provider)
        with pytest.raises(executor.BootstrapExecutionError, match="latched closed"):
            boundary.execute_call(
                slot_id=slots[0],
                case_id="case-00",
                messages=[{"role": "user", "content": "probe"}],
            )
        assert json.loads(latch_path.read_text())["remaining_calls_authorized"] is False
        with pytest.raises(executor.BootstrapExecutionError, match="latched closed"):
            boundary.execute_call(
                slot_id=slots[1],
                case_id="case-01",
                messages=[{"role": "user", "content": "probe"}],
            )


def test_two_executors_cannot_reissue_the_same_candidate_global_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    slots = tuple(f"slot-{index:02d}" for index in range(24))
    monkeypatch.setattr(
        executor.authorization,
        "authorized_bootstrap_slots",
        lambda _receipt: slots,
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_AUTHORIZATION",
        _receipt(tmp_path / "authorization.json"),
    )
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_LEDGER", tmp_path / "attempts.jsonl")
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_FAILURE_LATCH",
        tmp_path / "failure-latch.json",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY",
        tmp_path / "execution-capability.json",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_REQUEST_ROOT",
        tmp_path / "provider-requests",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_CLAIM_ROOT",
        tmp_path / "provider-claims",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_RAW_ROOT",
        tmp_path / "raw-sidecars",
    )
    first = executor.BootstrapModelExecutor()
    try:
        with pytest.raises(executor.BootstrapExecutionError, match="already consumed"):
            executor.BootstrapModelExecutor()
    finally:
        first.close()
    assert remediation.read_attempt_ledger(tmp_path / "attempts.jsonl") == []


def test_bootstrap_rejects_symlinked_authorization_before_capability_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    target = _receipt(tmp_path / "sealed/authorization.json")
    authorization_path = tmp_path / "authorization.json"
    authorization_path.symlink_to(target)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_AUTHORIZATION", authorization_path)
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_LEDGER", tmp_path / "attempts.jsonl")
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_FAILURE_LATCH",
        tmp_path / "failure-latch.json",
    )
    capability = tmp_path / "execution-capability.json"
    monkeypatch.setattr(executor, "ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY", capability)
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_REQUEST_ROOT",
        tmp_path / "provider-requests",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_CLAIM_ROOT",
        tmp_path / "provider-claims",
    )
    monkeypatch.setattr(
        executor,
        "ACTIVE_BOOTSTRAP_RAW_ROOT",
        tmp_path / "raw-sidecars",
    )

    with pytest.raises(executor.BootstrapExecutionError, match="unsafe fixed T2 authorization"):
        executor.BootstrapModelExecutor()
    assert not capability.exists()


def test_sealed_adapter_issues_one_accounted_request_per_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    slots = tuple(f"slot-{index:02d}" for index in range(24))
    monkeypatch.setattr(executor.authorization, "authorized_bootstrap_slots", lambda _value: slots)
    paths = {
        "ACTIVE_BOOTSTRAP_AUTHORIZATION": _receipt(tmp_path / "authorization.json"),
        "ACTIVE_BOOTSTRAP_LEDGER": tmp_path / "attempts.jsonl",
        "ACTIVE_BOOTSTRAP_FAILURE_LATCH": tmp_path / "failure-latch.json",
        "ACTIVE_BOOTSTRAP_EXECUTION_CAPABILITY": tmp_path / "execution-capability.json",
        "ACTIVE_BOOTSTRAP_REQUEST_ROOT": tmp_path / "provider-requests",
        "ACTIVE_BOOTSTRAP_CLAIM_ROOT": tmp_path / "provider-claims",
        "ACTIVE_BOOTSTRAP_RAW_ROOT": tmp_path / "raw-sidecars",
    }
    for name, value in paths.items():
        monkeypatch.setattr(executor, name, value)
    calls = 0

    def one_request(**kwargs: object) -> executor.provider_adapter.SealedProviderResult:
        nonlocal calls
        calls += 1
        assert set(kwargs) == {
            "slot_id",
            "attempt_id",
            "request_id",
            "request_document_value",
            "ledger",
            "ledger_path",
            "execution_capability_path",
            "request_receipt_path",
            "provider_claim_path",
            "raw_sidecar_path",
            "failure_latch_path",
        }
        assert kwargs["slot_id"] == kwargs["attempt_id"]
        request_document = kwargs["request_document_value"]
        assert isinstance(request_document, dict)
        assert request_document["model"] == executor.provider_adapter.MODEL_ID
        ledger = kwargs["ledger"]
        assert isinstance(ledger, remediation.AttemptLedger)
        claim_path = kwargs["provider_claim_path"]
        raw_path = kwargs["raw_sidecar_path"]
        assert isinstance(claim_path, Path)
        assert isinstance(raw_path, Path)
        remediation.atomic_write_new(
            claim_path,
            remediation.encoded_json({"slot_id": kwargs["slot_id"]}),
        )
        ledger.record_provider_claimed(
            str(kwargs["attempt_id"]),
            provider_claim_digest=remediation.sha256_file(claim_path),
        )
        raw = json.dumps(
            {"id": f"provider-{calls}", "choices": [], "usage": {}}
        ).encode()
        remediation.atomic_write_new(raw_path, raw)
        ledger.record_provider_accepted(
            str(kwargs["attempt_id"]),
            f"provider-{calls}",
            raw_sidecar_digest=remediation.sha256_file(raw_path),
        )
        return executor.provider_adapter.SealedProviderResult(
            provider_response_id=f"provider-{calls}",
            usage={
                "input_tokens": 2,
                "output_tokens": 1,
                "cached_input_tokens": 0,
                "reasoning_tokens": 0,
            },
            finish_reason="stop",
            raw_sidecar_digest=remediation.sha256_file(raw_path),
        )

    monkeypatch.setattr(executor.provider_adapter, "request_once", one_request)
    with executor.BootstrapModelExecutor() as boundary:
        for index in range(2):
            result = boundary.execute_call(
                slot_id=slots[index],
                case_id=f"case-{index}",
                messages=[{"role": "user", "content": "one request only"}],
            )
            assert result["provider_request_count"] == 1
    assert calls == 2
    assert "provider_call" not in inspect.signature(executor.BootstrapModelExecutor.execute_call).parameters
    reconciled = remediation.reconcile_attempt_ledger(paths["ACTIVE_BOOTSTRAP_LEDGER"])
    assert reconciled["known_completed_calls"] == 2
    latest = {
        str(row["attempt_id"]): row
        for row in remediation.read_attempt_ledger(
            paths["ACTIVE_BOOTSTRAP_LEDGER"]
        )
    }
    assert latest[slots[0]]["native_request_ids"] == ["provider-1"]
    assert latest[slots[1]]["native_request_ids"] == ["provider-2"]
    assert len(list(paths["ACTIVE_BOOTSTRAP_REQUEST_ROOT"].glob("*.accepted.json"))) == 2


def test_sealed_adapter_contains_exactly_one_native_request_site(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _sealed_adapter_context(tmp_path, monkeypatch)
    calls = 0

    class Response:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "id": "provider-native-1",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "done"},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                    },
                }
            ).encode()

    class Opener:
        def open(self, request: object, *, timeout: float) -> Response:
            nonlocal calls
            calls += 1
            assert request.full_url == provider_adapter.ENDPOINT
            assert json.loads(request.data) == expected_document
            assert timeout == provider_adapter.TIMEOUT_SECONDS
            return Response()

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", lambda: Opener())
    expected_document = context["document"]
    try:
        result = provider_adapter.request_once(**_adapter_kwargs(context))
        assert calls == 1
        assert result.provider_response_id == "provider-native-1"
        assert result.usage["input_tokens"] == 2
        assert result.raw_sidecar_digest == remediation.sha256_file(
            context["raw_sidecar_path"]
        )
        snapshots = remediation.read_attempt_ledger(context["ledger_path"])
        assert [row["attempt_state"] for row in snapshots] == [
            "PLANNED",
            "PROVIDER_CLAIMED",
            "PROVIDER_ACCEPTED",
        ]
    finally:
        context["ledger"].close()


def test_sealed_adapter_rejects_payload_policy_drift_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def opener() -> object:
        nonlocal opened
        opened = True
        raise AssertionError("provider opener must remain unreachable")

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", opener)
    request_id = "dg10-t2-request-" + "b" * 32
    document = provider_adapter.request_document(
        request_id=request_id,
        messages=[{"role": "user", "content": "sealed"}],
    )
    document["max_tokens"] = provider_adapter.MAX_TOKENS + 1
    ledger_path = tmp_path / "attempts.jsonl"
    ledger = remediation.AttemptLedger(ledger_path)
    with pytest.raises(provider_adapter.SealedProviderError, match="policy drift"):
        provider_adapter.request_once(
            slot_id="slot-01",
            attempt_id="slot-01",
            request_id=request_id,
            request_document_value=document,
            ledger=ledger,
            ledger_path=ledger_path,
            execution_capability_path=tmp_path / "capability.json",
            request_receipt_path=tmp_path / "request.json",
            provider_claim_path=tmp_path / "claim.json",
            raw_sidecar_path=tmp_path / "raw.json",
            failure_latch_path=tmp_path / "latch.json",
        )
    ledger.close()
    assert opened is False


def test_sealed_adapter_rejects_direct_request_without_fixed_slot_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(remediation, "ROOT", tmp_path)
    opened = False

    def opener() -> object:
        nonlocal opened
        opened = True
        raise AssertionError("provider opener must remain unreachable")

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", opener)
    request_id = "dg10-t2-request-" + "c" * 32
    document = provider_adapter.request_document(
        request_id=request_id,
        messages=[{"role": "user", "content": "sealed"}],
    )
    fixed_root = tmp_path / "var/dg10/t2-bootstrap-candidate.4"
    ledger_path = fixed_root / "attempts.jsonl"
    ledger = remediation.AttemptLedger(ledger_path)
    ledger.start_attempt(
        phase="T2_CONTROL_PATH_SMOKE",
        arm="T2_CONTROL_PATH",
        case_id="case-01",
        planned_model_calls=1,
        planned_mcp_calls=0,
        attempt_id="slot-01",
    )
    with pytest.raises(provider_adapter.SealedProviderError, match="artifacts are invalid"):
        provider_adapter.request_once(
            slot_id="slot-01",
            attempt_id="slot-01",
            request_id=request_id,
            request_document_value=document,
            ledger=ledger,
            ledger_path=ledger_path,
            execution_capability_path=fixed_root / "execution-capability.json",
            request_receipt_path=fixed_root / "provider-requests/slot-01.json",
            provider_claim_path=fixed_root / "provider-claims/slot-01.json",
            raw_sidecar_path=fixed_root / "raw-sidecars/slot-01.json",
            failure_latch_path=fixed_root / "failure-latch.json",
        )
    ledger.close()
    assert opened is False


def test_sealed_adapter_rejects_repeated_direct_slot_before_second_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _sealed_adapter_context(tmp_path, monkeypatch)
    calls = 0

    class Response:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return remediation.encoded_json(
                {
                    "id": "provider-native-repeat",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "done"},
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                }
            )

    class Opener:
        def open(self, _request: object, *, timeout: float) -> Response:
            nonlocal calls
            calls += 1
            assert timeout == provider_adapter.TIMEOUT_SECONDS
            return Response()

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", lambda: Opener())
    try:
        provider_adapter.request_once(**_adapter_kwargs(context))
        with pytest.raises(
            provider_adapter.SealedProviderError,
            match="slot artifacts already exist",
        ):
            provider_adapter.request_once(**_adapter_kwargs(context))
        assert calls == 1
        assert context["provider_claim_path"].is_file()
    finally:
        context["ledger"].close()


def test_sealed_adapter_atomic_claim_limits_concurrent_direct_replay_to_one_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _sealed_adapter_context(tmp_path, monkeypatch)
    worker_count = 8
    barrier = Barrier(worker_count)
    real_binding = provider_adapter._validated_bootstrap_binding

    def synchronized_binding(**kwargs: object) -> dict[str, object]:
        result = real_binding(**kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(
        provider_adapter, "_validated_bootstrap_binding", synchronized_binding
    )
    calls = 0
    lock = Lock()

    class Response:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return remediation.encoded_json(
                {
                    "id": "provider-native-concurrent",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "done"},
                        }
                    ],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1},
                }
            )

    class Opener:
        def open(self, _request: object, *, timeout: float) -> Response:
            nonlocal calls
            assert timeout == provider_adapter.TIMEOUT_SECONDS
            with lock:
                calls += 1
            return Response()

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", lambda: Opener())

    def invoke() -> str:
        try:
            provider_adapter.request_once(**_adapter_kwargs(context))
        except provider_adapter.SealedProviderError as exc:
            return str(exc)
        return "SUCCESS"

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            outcomes = list(pool.map(lambda _index: invoke(), range(worker_count)))
        assert outcomes.count("SUCCESS") == 1
        assert sum("already durably claimed" in item for item in outcomes) == 7
        assert calls == 1
        assert context["failure_latch_path"].is_file()
        reconciled = remediation.reconcile_attempt_ledger(context["ledger_path"])
        assert reconciled["claimed_model_calls"] == 1
        assert reconciled["known_completed_calls"] == 0
    finally:
        context["ledger"].close()


def test_sealed_adapter_journals_native_id_before_semantic_response_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _sealed_adapter_context(tmp_path, monkeypatch)

    class Response:
        status = 200

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return remediation.encoded_json(
                {
                    "id": "provider-native-before-semantic-parse",
                    "choices": [],
                    "usage": {},
                }
            )

    class Opener:
        def open(self, _request: object, *, timeout: float) -> Response:
            assert timeout == provider_adapter.TIMEOUT_SECONDS
            return Response()

    monkeypatch.setattr(provider_adapter.local_identity, "local_opener", lambda: Opener())
    try:
        with pytest.raises(
            provider_adapter.SealedProviderError,
            match="choice denominator drift",
        ):
            provider_adapter.request_once(**_adapter_kwargs(context))
        snapshots = remediation.read_attempt_ledger(context["ledger_path"])
        assert snapshots[-1]["attempt_state"] == "PROVIDER_ACCEPTED"
        assert snapshots[-1]["native_request_ids"] == [
            "provider-native-before-semantic-parse"
        ]
        assert snapshots[-1]["raw_sidecar_digest"] == remediation.sha256_file(
            context["raw_sidecar_path"]
        )
        assert context["raw_sidecar_path"].is_file()
        assert context["failure_latch_path"].is_file()
    finally:
        context["ledger"].close()
