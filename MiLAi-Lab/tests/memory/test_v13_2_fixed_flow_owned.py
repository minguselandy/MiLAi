"""Root controlled-flow integration: real current SDKs, synthetic inputs, Mock HTTP."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.application.world import ApplicationWorld
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import current_http_budget
from milai_lab.harness.http_ownership import PROFILE, HttpOwnership, HttpOwnershipError
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners import v13_1_d0 as d0

LAB = Path(__file__).resolve().parents[2]
DRIVER = LAB / "tools/run_v13_2_fixed_flow_owned.py"
ENGINEERING = runpy.run_path(str(LAB / "tests/memory/test_v13_2_read_protocol.py"))


def load_driver() -> Any:
    spec = importlib.util.spec_from_file_location("root_owned_fixed_flow", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup(path: Path, *, owned: bool, formation: str, prefetch: bool) -> tuple[Any, Path, Path]:
    fp, cp, settings = ENGINEERING["synthetic_settings"](path)
    settings.update(
        max_calls_per_message=12,
        memory_formation_policy=formation,
        memory_prefetch="enabled" if prefetch else "disabled",
        memory_source_backlinks="enabled",
        memory_representation="milai",
        memory_support_contract="direct_support_v1",
        tool_schema_communication="shape_feedback_v1",
    )
    if formation == "tool_only_v1":
        settings["memory_observation_profile"] = "reservation_v1"
    if owned:
        settings.update(
            http_ownership_profile=PROFILE,
            http_ownership_domain={
                "deployment_id": "root-synthetic-controlled-flow",
                "clients": [asdict(VLLMConfig(**settings[k])) for k in ("host", "embedding")],
            },
        )
    ledger = Path(settings["budget_path"])
    state = read_json(ledger)
    state.update(generation_requests=4, history=[{"synthetic_prior_unknown": True}])
    state["generation"] = {"charged_tokens": 170, "known_tokens": 29, "unknown_usage": 1}
    state["embedding"] = {"charged_tokens": 11, "known_tokens": 11, "unknown_usage": 0}
    write_json(ledger, state)
    write_json(cp, settings)
    world_path = path / "trusted-world.sqlite"
    world = ApplicationWorld(world_path, True)
    try:
        original_receipt = world.reserve_and_label(
            "owner", "generic-item", 1, "generic-place", "plain"
        )
    finally:
        world.close()

    def event(role: str, key: str, content: str, origin: str) -> dict[str, Any]:
        return {
            "role": role,
            "event_key": key,
            "session_id": "s",
            "origin": origin,
            "content": content,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        }

    stream = path / "synthetic-observed-flow.json"
    write_json(
        stream,
        {
            "streams": [
                {
                    "case_id": "synthetic-entry",
                    "owner": "owner",
                    "world_path_for_trusted_adapter_only": str(world_path),
                    "boundaries": [
                        {
                            "events": [
                                event(
                                    "user", "u", "Actual public statement", "public_user_message"
                                ),
                                event("tool", "u:actual", original_receipt, "reserve_and_label"),
                            ]
                        },
                        {
                            "events": [
                                event(
                                    "user",
                                    "future",
                                    "FUTURE_CONTENT_MUST_NOT_ENTER_WIRE",
                                    "public_user_message",
                                )
                            ]
                        },
                    ],
                }
            ]
        },
    )
    root = path / "run"
    frozen = d0.prepare(fp, cp, root)
    write_json(
        root / "controlled-flow-freeze.json",
        {
            "driver_sha256": hashlib.sha256(DRIVER.read_bytes()).hexdigest(),
            "stream_sha256": hashlib.sha256(stream.read_bytes()).hexdigest(),
            "http_ownership_profile": frozen.get("http_ownership_profile", "legacy"),
            "http_ownership_binding": frozen.get("http_ownership_binding", {}),
        },
    )
    return load_driver(), root, stream


def argv(root: Path, stream: Path, boundary: int = 0) -> list[str]:
    return [
        str(DRIVER),
        "--run-root",
        str(root),
        "--stream",
        str(stream),
        "--stream-index",
        "0",
        "--boundary",
        str(boundary),
    ]


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("formation", ["none", "tool_only_v1"])
@pytest.mark.parametrize("prefetch", [False, True])
def test_actual_fixed_flow_four_cells_owner_and_legacy_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owned: bool, formation: str, prefetch: bool
) -> None:
    driver, root, stream = setup(tmp_path, owned=owned, formation=formation, prefetch=prefetch)
    wires, budgets, lifecycle, services, worlds = [], [], [], [], []
    original_client_close = VLLMClient.close
    original_owner_close = HttpOwnership.close
    original_service, original_world = driver.MemoryService, driver.ApplicationWorld
    original_write = driver.write_json

    def owner_close(owner: HttpOwnership) -> None:
        receipts = list(root.rglob("controlled-boundary-0.json"))
        lifecycle.append(
            {
                "owner_close": True,
                "terminal_present": bool(receipts),
                "clients": len(owner._clients),
            }
        )
        assert receipts and read_json(receipts[0])["status"] == "completed"
        assert not owner._clients
        original_owner_close(owner)

    def client_close(client: VLLMClient) -> None:
        if owned:
            assert client.budget.http_owner is not None and not client.budget.http_owner.closed
        lifecycle.append({"client_close": client.config.model})
        original_client_close(client)

    def service(*args: Any, **kwargs: Any) -> Any:
        value = original_service(*args, **kwargs)
        services.append(value)
        return value

    def world(*args: Any, **kwargs: Any) -> Any:
        value = original_world(*args, **kwargs)
        worlds.append(value)
        return value

    def writing(path: Path, value: Any) -> None:
        if path.name == "controlled-boundary-0.json":
            active = current_http_budget()
            assert (active is not None) == owned
            if active is not None:
                assert active.http_owner is not None and not active.http_owner.closed
            if value["status"] == "completed":
                for actual in [s.store.conn for s in services] + [w.conn for w in worlds]:
                    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                        actual.execute("SELECT 1")
                if active is not None:
                    assert not active.http_owner._clients
            lifecycle.append(
                {"receipt_status": value["status"], "inside_owner": active is not None}
            )
        original_write(path, value)

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        budget = kwargs["budget"]
        budgets.append(budget)

        def transport(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            wires.append({"url": str(request.url), "body": body, "ledger": read_json(budget.path)})
            if owned:
                assert budget.http_owner is not None and budget.http_owner.mutex.locked()
                assert read_json(budget.path) == budget.state
            if request.url.path.endswith("embeddings"):
                response = {
                    "data": [
                        {"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])
                    ],
                    "usage": {"total_tokens": 3},
                }
            else:
                response = {
                    "id": "synthetic-writer",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {"answer": "No additional synthetic proposal"}
                                ),
                            },
                        }
                    ],
                    "usage": {"total_tokens": 7},
                }
            return httpx.Response(200, json=response)

        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(driver, "MemoryService", service)
    monkeypatch.setattr(driver, "ApplicationWorld", world)
    monkeypatch.setattr(driver, "write_json", writing)
    monkeypatch.setattr(driver, "VLLMClient", client)
    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(VLLMClient, "close", client_close)
    if owned:
        monkeypatch.setattr(HttpOwnership, "close", owner_close)
    monkeypatch.setattr(sys, "argv", argv(root, stream))
    driver.main()
    receipt_path = next(root.rglob("controlled-boundary-0.json"))
    output = read_json(receipt_path)
    assert output["status"] == "completed" and not output["free_host_sample"]
    assert output["actual_host_final"] is None
    assert len({id(b) for b in budgets}) == 1
    assert sum("messages" in wire["body"] for wire in wires) == int(formation == "none")
    assert "FUTURE_CONTENT_MUST_NOT_ENTER_WIRE" not in json.dumps(wires)
    assert "world_path_for_trusted_adapter_only" not in json.dumps(wires)
    assert output["budget"]["generation"]["unknown_usage"] == 1
    assert output["budget"]["history"] == [{"synthetic_prior_unknown": True}]
    assert output["formation"]["generation_calls"] == int(formation == "none")
    assert output["formation"]["status"] == (
        "no_change" if formation == "none" else "deterministic_observation_only"
    )
    if owned:
        assert lifecycle[-1] == {"owner_close": True, "terminal_present": True, "clients": 0}
    write_json(
        tmp_path / "actual-root-controlled-flow.json",
        {
            "owned": owned,
            "formation": formation,
            "prefetch": prefetch,
            "wires": wires,
            "lifecycle": lifecycle,
            "receipt": output,
        },
    )


@pytest.mark.parametrize("fault", ["profile", "binding", "already_attempted", "prior_boundary"])
def test_controlled_flow_refusals_before_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    driver, root, stream = setup(tmp_path, owned=True, formation="none", prefetch=True)
    calls = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("SDK_CONSTRUCTION_FORBIDDEN")

    monkeypatch.setattr(driver, "VLLMClient", forbidden)
    freeze_path = root / "controlled-flow-freeze.json"
    frozen = read_json(freeze_path)
    boundary = 0
    if fault == "profile":
        frozen["http_ownership_profile"] = "legacy"
    elif fault == "binding":
        frozen["http_ownership_binding"]["domain_sha256"] = "b" * 64
    elif fault == "already_attempted":
        case_root = root / hashlib.sha256(b"synthetic-entry").hexdigest()[:16]
        write_json(case_root / "controlled-boundary-0.json", {"status": "interrupted"})
    else:
        boundary = 1
    write_json(freeze_path, frozen)
    original = Path(read_json(root / "input-freeze.json")["config"]["budget_path"]).read_bytes()
    monkeypatch.setattr(sys, "argv", argv(root, stream, boundary))
    with pytest.raises(ValueError, match="CONTROLLED_FLOW"):
        driver.main()
    assert not calls
    assert (
        Path(read_json(root / "input-freeze.json")["config"]["budget_path"]).read_bytes()
        == original
    )
    assert current_http_budget() is None


def scripted_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("embeddings"):
        result = {
            "data": [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(body["input"])],
            "usage": {"total_tokens": 3},
        }
    else:
        result = {
            "id": "synthetic-writer",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"answer": "No additional synthetic proposal"}),
                    },
                }
            ],
            "usage": {"total_tokens": 7},
        }
    return httpx.Response(200, json=result)


def test_controlled_constructor_failure_keeps_attempt_and_releases_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, root, stream = setup(tmp_path, owned=True, formation="none", prefetch=True)
    settings = read_json(root / "input-freeze.json")["config"]
    ledger = Path(settings["budget_path"])
    before = ledger.read_bytes()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Root synthetic constructor failure before returned client")

    monkeypatch.setattr(driver, "VLLMClient", fail)
    monkeypatch.setattr(sys, "argv", argv(root, stream))
    with pytest.raises(SystemExit) as stopped:
        driver.main()
    assert stopped.value.code == 1 and current_http_budget() is None
    outcome = read_json(next(root.rglob("controlled-boundary-0.json")))
    assert outcome["status"] == "interrupted" and outcome["error_type"] == "OSError"
    assert ledger.read_bytes() == before
    fresh = HttpOwnership(ledger, settings["http_ownership_domain"])
    try:
        assert fresh.initial_state == json.loads(before)
    finally:
        fresh.close()
    write_json(
        tmp_path / "constructor-failure-original.json",
        {
            "receipt": outcome,
            "ledger_unchanged": True,
            "fresh_owner_acquired": True,
            "actual_model_http": 0,
        },
    )


def test_controlled_actual_transport_close_failure_preserves_receipt_and_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, root, stream = setup(tmp_path, owned=True, formation="none", prefetch=True)
    settings = read_json(root / "input-freeze.json")["config"]
    clients = []

    class FailingTransport(httpx.MockTransport):
        def close(self) -> None:
            super().close()
            raise OSError("Root actual synthetic transport.close failure")

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        transport = (
            FailingTransport(scripted_response)
            if args[0].model == settings["host"]["model"]
            else httpx.MockTransport(scripted_response)
        )
        value = VLLMClient(*args, **kwargs, transport=transport)
        clients.append(value)
        return value

    monkeypatch.setattr(driver, "VLLMClient", client)
    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(sys, "argv", argv(root, stream))
    owner = None
    try:
        with pytest.raises(HttpOwnershipError, match="CLIENTS_STILL_OPEN"):
            driver.main()
        assert current_http_budget() is None
        owner = clients[0].budget.http_owner
        assert owner is not None and not owner.closed and len(owner._clients) == 1
        assert clients[0]._client.is_closed
        outcome = read_json(next(root.rglob("controlled-boundary-0.json")))
        assert outcome["status"] == "interrupted" and outcome["error_type"] == "OSError"
        assert "transport.close failure" in outcome["error"]
        with pytest.raises(HttpOwnershipError, match="HTTP_OWNER_BUSY"):
            HttpOwnership(Path(settings["budget_path"]), settings["http_ownership_domain"])
        write_json(
            tmp_path / "close-failure-before-manual-teardown.json",
            {
                "receipt": outcome,
                "owner_closed": owner.closed,
                "registered": len(owner._clients),
                "httpx_closed_flag": clients[0]._client.is_closed,
                "competitor_busy": True,
            },
        )
    finally:
        # Explicit test cleanup after original evidence; no runtime recovery/retry.
        if owner is not None:
            for wrapper, _, _ in list(owner._clients.values()):
                owner.abort_client(wrapper)
            owner.close()


def test_controlled_unknown_writer_is_pending_not_retried_or_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, root, stream = setup(tmp_path, owned=True, formation="none", prefetch=True)
    generation_dispatches = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("chat/completions"):
            generation_dispatches.append(request.content.hex())
            raise httpx.ReadTimeout("Root synthetic unknown writer", request=request)
        return scripted_response(request)

    def client(*args: Any, **kwargs: Any) -> VLLMClient:
        return VLLMClient(*args, **kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr(driver, "VLLMClient", client)
    monkeypatch.setattr(d0, "VLLMClient", client)
    monkeypatch.setattr(sys, "argv", argv(root, stream))
    driver.main()
    receipt_path = next(root.rglob("controlled-boundary-0.json"))
    original = receipt_path.read_bytes()
    result = read_json(receipt_path)
    assert result["status"] == "completed"  # boundary execution completed; formation is pending
    assert (
        result["formation"]["status"] == "pending"
        and result["formation"]["effect"] == "unconfirmed"
    )
    assert result["formation"]["generation_calls"] == len(generation_dispatches) == 1
    assert result["budget"]["generation"]["unknown_usage"] == 2
    assert result["budget"]["generation"]["known_tokens"] == 29
    assert current_http_budget() is None
    with pytest.raises(ValueError, match="ALREADY_ATTEMPTED"):
        driver.main()
    assert receipt_path.read_bytes() == original and len(generation_dispatches) == 1
    write_json(
        tmp_path / "unknown-writer-original.json",
        {
            "receipt": result,
            "generation_dispatches": generation_dispatches,
            "explicit_formation_pending": True,
            "boundary_completed_does_not_mean_formation_success": True,
        },
    )
