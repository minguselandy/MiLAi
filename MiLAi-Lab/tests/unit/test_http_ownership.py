from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

import httpx
import pytest

from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, http_budget_scope
from milai_lab.harness.http_ownership import (
    HttpOwnership,
    HttpOwnershipError,
    check_frozen,
    freeze_fields,
)
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig

LAB = Path(__file__).resolve().parents[2]


def proof(path: Path, name: str, value: Any) -> None:
    p = path / name
    assert not p.exists()
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def maps() -> dict[str, Any]:
    result = {}
    # The old engineering audit included a sibling worktree on its author's host.
    # A portable regression records the checkout actually executing the test.
    for tree, lab in [("checkout", LAB)]:
        result[tree] = {}
        for group, dirs, suffix in [
            ("runtime", ["src"], ".py"),
            ("tests", ["tests"], ".py"),
            ("configs", ["configs", "data/configs"], None),
        ]:
            files = sorted(
                {
                    p
                    for d in dirs
                    for p in (lab / d).rglob("*")
                    if p.is_file() and (suffix is None or p.suffix == suffix)
                }
            )
            if group == "runtime":
                files = sorted([*files, lab / "tools/run_v13_1_d0.py"])
            result[tree][group] = {
                str(p.relative_to(lab)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
            }
    return result


def child(
    path: Path, name: str, code: str, settings: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    directory = path / name
    directory.mkdir()
    driver = directory / "driver.py"
    driver.write_text(code)
    before = maps()
    command = [sys.executable, str(driver), json.dumps(settings)]
    result = subprocess.run(command, cwd=LAB, text=True, capture_output=True, timeout=15)  # noqa: S603
    (directory / "stdout.log").write_text(result.stdout)
    (directory / "stderr.log").write_text(result.stderr)
    proof(directory, "before.json", before)
    proof(directory, "after.json", maps())
    proof(
        directory,
        "receipt.json",
        {
            "command": command,
            "returncode": result.returncode,
            "driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        },
    )
    return result


def seed(path: Path) -> tuple[dict[str, Any], VLLMConfig, VLLMConfig, dict[str, Any]]:
    host = VLLMConfig("http://synthetic/v1", "synthetic-host", max_tokens=8)
    embedding = VLLMConfig("http://synthetic/v1", "synthetic-embedding")
    ledger = path / "synthetic-ledger.json"
    old = RunBudget(RunLimits(generation_requests=20), ledger)
    r = old.reserve("chat/completions", {"messages": [], "max_tokens": 8})
    old.finish(r, {"total_tokens": 2})
    old.reserve("chat/completions", {"messages": [], "max_tokens": 7})
    value = json.loads(ledger.read_text())
    value["history"] = [{"kind": "synthetic-prior-unknown", "usage": "unknown"}]
    ledger.write_text(json.dumps(value, indent=2) + "\n")
    settings = {
        "budget_path": str(ledger),
        "http_ownership_profile": "serialized_ledger_owner_v1",
        "http_ownership_domain": {
            "deployment_id": "synthetic-deployment",
            "clients": [asdict(host), asdict(embedding)],
        },
    }
    return settings, host, embedding, value


def response(known: bool = True) -> httpx.Response:
    body = {
        "id": "synthetic",
        "object": "chat.completion",
        "created": 1,
        "model": "synthetic-host",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "unchanged final"},
            }
        ],
    }
    if known:
        body["usage"] = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    return httpx.Response(200, json=body)


def test_multiple_clients_generation_embedding_span_finish(tmp_path: Path) -> None:
    settings, host, embedding, initial = seed(tmp_path)
    entered, release_transport, finish_entered, release_finish = Event(), Event(), Event(), Event()
    records, wires, errors = [], [], []
    active, peak = 0, 0
    counter = Lock()

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        value = json.loads(request.content)
        with counter:
            active += 1
            peak = max(peak, active)
            wires.append(value)
        if value.get("messages", [{}])[0].get("content") == "known":
            entered.set()
            assert release_transport.wait(5)
        with counter:
            active -= 1
        if request.url.path.endswith("embeddings"):
            return httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [1.0]}], "usage": {"total_tokens": 3}}
            )
        return response(value["messages"][0]["content"] == "known")

    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        owner = budget.http_owner
        actual_persist = owner.persist

        def persist(b: RunBudget) -> None:
            records.append(json.loads(json.dumps(b.state)))
            if b.state["generation"]["known_tokens"] == initial["generation"]["known_tokens"] + 5:
                if not finish_entered.is_set():
                    finish_entered.set()
                    assert release_finish.wait(5)
            actual_persist(b)

        owner.persist = persist
        clients = [
            VLLMClient(host, transport=httpx.MockTransport(transport), budget=budget),
            VLLMClient(host, transport=httpx.MockTransport(transport), budget=budget),
            VLLMClient(embedding, transport=httpx.MockTransport(transport), budget=budget),
        ]
        attempts = [Event(), Event(), Event()]

        def call(i: int) -> None:
            attempts[i].set()
            try:
                if i == 2:
                    clients[i].embed(["literal"], embedding.model)
                else:
                    clients[i].chat([{"role": "user", "content": "known" if i == 0 else "unknown"}])
            except BaseException as error:
                errors.append(repr(error))

        threads = [Thread(target=call, args=(i,)) for i in range(3)]
        threads[0].start()
        assert entered.wait(5)
        for t in threads[1:]:
            t.start()
        assert all(e.wait(5) for e in attempts)
        release_transport.set()
        assert finish_entered.wait(5)
        assert owner.mutex.locked()
        assert len(wires) == 1
        release_finish.set()
        for t in threads:
            t.join(5)
            assert not t.is_alive()
        assert not errors and peak == 1 and len(wires) == 3
        assert budget.state["generation_requests"] == initial["generation_requests"] + 2
        assert (
            budget.state["generation"]["known_tokens"] == initial["generation"]["known_tokens"] + 5
        )
        assert (
            budget.state["generation"]["unknown_usage"]
            == initial["generation"]["unknown_usage"] + 1
        )
        assert budget.state["embedding"] == {
            "charged_tokens": 3,
            "known_tokens": 3,
            "unknown_usage": 0,
        }
        assert budget.state["history"] == initial["history"]
        proof(
            tmp_path,
            "actual-concurrency.json",
            {
                "wires": wires,
                "peak": peak,
                "every_persist_state": records,
                "initial": initial,
                "final": budget.state,
            },
        )
        for client in clients:
            client.close()


@pytest.mark.parametrize("alias,other_domain", [(False, False), (True, False), (False, True)])
def test_other_process_refuses_before_load_and_client(
    tmp_path: Path, alias: bool, other_domain: bool
) -> None:
    settings, _, _, _ = seed(tmp_path)
    second = json.loads(json.dumps(settings))
    if alias:
        link = tmp_path / "ledger-alias.json"
        link.symlink_to(settings["budget_path"])
        second["budget_path"] = str(link)
    if other_domain:
        second["http_ownership_domain"]["deployment_id"] = "different-arm-and-root"
    code = """import json,sys
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.harness.http_ownership import HttpOwnership,HttpOwnershipError
from milai_lab.providers.contextual_vllm import VLLMClient,VLLMConfig
flags={'load':False,'client':False}
real=HttpOwnership._read_disk
def read(self):
 flags['load']=True
 return real(self)
HttpOwnership._read_disk=read
try:
 with http_budget_scope(json.loads(sys.argv[1])) as budget:
  flags['client']=True
  VLLMClient(VLLMConfig('http://synthetic/v1','synthetic-host',max_tokens=8),budget=budget)
except HttpOwnershipError as e:
 print(json.dumps({'error':str(e),'flags':flags}))
 sys.exit(17)
"""
    with http_budget_scope(settings):
        result = child(tmp_path, "competitor", code, second)
        assert result.returncode == 17
        assert json.loads(result.stdout) == {
            "error": "HTTP_OWNER_BUSY",
            "flags": {"load": False, "client": False},
        }


def test_reentry_close_and_duplicate_budget_rejected(tmp_path: Path) -> None:
    settings, host, _, _ = seed(tmp_path)
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        owner = budget.http_owner
        seen = []

        def transport(request: httpx.Request) -> httpx.Response:
            with pytest.raises(HttpOwnershipError, match="REENTRY"):
                client.chat([])
            with pytest.raises(HttpOwnershipError, match="REQUEST_ACTIVE"):
                client.close()
            seen.append(json.loads(request.content))
            return response()

        client = VLLMClient(host, budget=budget, transport=httpx.MockTransport(transport))
        with pytest.raises(HttpOwnershipError, match="SECOND_BUDGET"):
            RunBudget(budget.limits, budget.path, http_owner=owner)
        with pytest.raises(HttpOwnershipError, match="CLIENTS_STILL_OPEN"):
            owner.close()
        with pytest.raises(HttpOwnershipError, match="OUTSIDE_REQUEST"):
            budget.reserve("chat/completions", {"messages": [], "max_tokens": 8})
        client.chat([])
        assert len(seen) == 1
        client.close()
        with pytest.raises(HttpOwnershipError, match="CLIENT_CLOSED"):
            client.chat([])
        with pytest.raises(HttpOwnershipError, match="CLIENT_CLOSED"):
            client.close()


@pytest.mark.parametrize(
    "fault",
    [
        "base",
        "config",
        "request_model",
        "request_path",
        "budget",
        "limits",
        "domain",
        "pid",
        "missing",
        "stale",
    ],
)
def test_dispatch_drift_fails_without_reserve(tmp_path: Path, fault: str) -> None:
    settings, host, _, initial = seed(tmp_path)
    dispatches = []
    wrong_budget = RunBudget(RunLimits(), tmp_path / "wrong-budget.json")
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        owner = budget.http_owner
        client = VLLMClient(
            host,
            budget=budget,
            transport=httpx.MockTransport(lambda request: dispatches.append(request) or response()),
        )
        original_domain = json.loads(json.dumps(owner.domain))
        original_pid = owner.pid
        if fault == "base":
            client._client.base_url = httpx.URL("http://other/v1/")
        elif fault == "timeout":
            client._client.timeout = httpx.Timeout(host.timeout + 1)
        elif fault == "config":
            client.config = replace(host, max_tokens=9)
        elif fault == "budget":
            client.budget = wrong_budget
        elif fault == "limits":
            budget.limits = replace(budget.limits, generation_requests=100)
        elif fault == "domain":
            owner.domain["deployment_id"] = "changed"
        elif fault == "pid":
            owner.pid += 1
        elif fault == "missing":
            Path(settings["budget_path"]).unlink()
        elif fault == "stale":
            state = json.loads(Path(settings["budget_path"]).read_text())
            state["generation_requests"] += 1
            state["ledger_revision"] = state.get("ledger_revision", 0) + 1
            Path(settings["budget_path"]).write_text(json.dumps(state))
        with pytest.raises(HttpOwnershipError):
            if fault == "request_model":
                client._post(
                    "chat/completions", {"model": "other", "messages": [], "max_tokens": 8}
                )
            elif fault == "request_path":
                client._post(
                    "../chat/completions", {"model": host.model, "messages": [], "max_tokens": 8}
                )
            else:
                client.chat([])
        assert (
            not dispatches and budget.state["generation_requests"] == initial["generation_requests"]
        )
        owner.domain, owner.pid = original_domain, original_pid
        client.close()


@pytest.mark.parametrize("failure", ["503", "timeout", "unknown"])
def test_unknown_or_transport_failure_keeps_original_charge(tmp_path: Path, failure: str) -> None:
    settings, host, _, initial = seed(tmp_path)
    events = []

    def transport(request: httpx.Request) -> httpx.Response:
        if failure == "503":
            return httpx.Response(503, text="synthetic unavailable")
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return response(False)

    with http_budget_scope(settings) as budget:
        assert budget is not None
        with VLLMClient(
            host, budget=budget, emit=events.append, transport=httpx.MockTransport(transport)
        ) as client:
            if failure == "unknown":
                client.chat([])
            else:
                with pytest.raises(httpx.HTTPError):
                    client.chat([])
        final = json.loads(Path(settings["budget_path"]).read_text())
        assert final["generation_requests"] == initial["generation_requests"] + 1
        assert final["generation"]["unknown_usage"] == initial["generation"]["unknown_usage"] + 1
        assert final["generation"]["known_tokens"] == initial["generation"]["known_tokens"]
        assert final["generation"]["charged_tokens"] > initial["generation"]["charged_tokens"]
        proof(
            tmp_path,
            "original-outcome.json",
            {"initial": initial, "final": final, "events": events},
        )
    with http_budget_scope(settings) as reopened:
        assert reopened is not None and reopened.state == final


@pytest.mark.parametrize(
    "phase", ["reserve_file", "reserve_directory", "finish_file", "finish_directory"]
)
def test_actual_persistence_failure_retains_bytes_no_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    settings, host, _, initial = seed(tmp_path)
    dispatches = []
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        with VLLMClient(
            host,
            budget=budget,
            transport=httpx.MockTransport(
                lambda request: dispatches.append(json.loads(request.content)) or response()
            ),
        ) as client:
            real_fsync = os.fsync
            calls = 0
            failed = {
                "reserve_file": 1,
                "reserve_directory": 2,
                "finish_file": 3,
                "finish_directory": 4,
            }[phase]

            def fail(fd: int) -> None:
                nonlocal calls
                calls += 1
                if calls == failed:
                    raise OSError("synthetic persistence cut")
                real_fsync(fd)

            with monkeypatch.context() as patch:
                patch.setattr(os, "fsync", fail)
                with pytest.raises(OSError, match="persistence cut"):
                    client.chat([])
            with pytest.raises(HttpOwnershipError, match="PERSISTENCE_UNCERTAIN"):
                client.chat([])
            assert len(dispatches) == (1 if phase.startswith("finish") else 0)
        actual = json.loads(Path(settings["budget_path"]).read_text())
        proof(
            tmp_path,
            "persistence-original.json",
            {
                "phase": phase,
                "initial": initial,
                "actual": actual,
                "dispatches": dispatches,
                "partial_files": [str(p) for p in tmp_path.glob("*.tmp")],
            },
        )
    with http_budget_scope(settings) as reopened:
        assert reopened is not None and reopened.state == actual
    if phase == "finish_directory":
        assert actual["generation"]["known_tokens"] == initial["generation"]["known_tokens"] + 5
        assert actual["generation"]["unknown_usage"] == initial["generation"]["unknown_usage"]
    if phase in {"reserve_directory", "finish_file"}:
        assert actual["generation"]["unknown_usage"] == initial["generation"]["unknown_usage"] + 1


def test_fork_with_inherited_locked_mutex_never_unlocks_parent(tmp_path: Path) -> None:
    settings, host, _, _ = seed(tmp_path)
    entered, release = Event(), Event()
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None

        def transport(request: httpx.Request) -> httpx.Response:
            entered.set()
            assert release.wait(8)
            return response()

        client = VLLMClient(host, budget=budget, transport=httpx.MockTransport(transport))
        errors = []

        def request() -> None:
            try:
                client.chat([])
            except BaseException as error:
                errors.append(repr(error))

        worker = Thread(target=request)
        worker.start()
        assert entered.wait(5) and budget.http_owner.mutex.locked()
        rd, wr = os.pipe()
        before = maps()
        pid = os.fork()
        if pid == 0:
            os.close(rd)
            result = {}
            try:
                client.chat([])
            except HttpOwnershipError as error:
                result["request"] = str(error)
            try:
                budget.http_owner.close()
            except HttpOwnershipError as error:
                result["close"] = str(error)
            os.write(wr, json.dumps(result).encode())
            os._exit(0)
        os.close(wr)
        try:
            assert select.select([rd], [], [], 5)[0], "fork child blocked on inherited mutex"
            result = json.loads(os.read(rd, 10000))
            _, status = os.waitpid(pid, 0)
            assert status == 0
            assert all("FORK_OR_PID_CHANGED" in v for v in result.values())
            competitor = child(
                tmp_path,
                "after-fork-competitor",
                """import json,sys
from pathlib import Path
from milai_lab.harness.http_ownership import HttpOwnership,HttpOwnershipError
s=json.loads(sys.argv[1])
try: HttpOwnership(Path(s['budget_path']),s['http_ownership_domain'])
except HttpOwnershipError as e: print(str(e));sys.exit(17)
""",
                settings,
            )
            assert competitor.returncode == 17 and "HTTP_OWNER_BUSY" in competitor.stdout
            proof(
                tmp_path,
                "fork-original.json",
                {
                    "child_pid": pid,
                    "child_result": result,
                    "wait_status": status,
                    "before": before,
                    "after": maps(),
                },
            )
        finally:
            os.close(rd)
            release.set()
            worker.join(5)
        assert not worker.is_alive() and not errors
        client.close()


def test_actual_process_cut_after_durable_reserve_reopens_charged(tmp_path: Path) -> None:
    settings, _, _, initial = seed(tmp_path)
    result = child(
        tmp_path,
        "dispatch-cut",
        """import json,sys,os,httpx
from pathlib import Path
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.providers.contextual_vllm import VLLMClient,VLLMConfig
s=json.loads(sys.argv[1])
def cut(request):
 Path(s['budget_path']+'.actual-mock-dispatch').write_text(request.content.decode())
 os._exit(77)
with http_budget_scope(s) as b:
 config = VLLMConfig('http://synthetic/v1','synthetic-host',max_tokens=8)
 with VLLMClient(config,budget=b,transport=httpx.MockTransport(cut)) as c:
  c.chat([])
""",
        settings,
    )
    assert result.returncode == 77
    with http_budget_scope(settings) as budget:
        assert budget is not None
        assert budget.state["generation_requests"] == initial["generation_requests"] + 1
        assert (
            budget.state["generation"]["unknown_usage"]
            == initial["generation"]["unknown_usage"] + 1
        )
        assert budget.state["history"] == initial["history"]


@pytest.mark.parametrize(
    "invalid", ["missing", "negative", "boolean", "noninteger", "json", "limits"]
)
def test_initial_ledger_is_not_replaced_by_zero(tmp_path: Path, invalid: str) -> None:
    settings, _, _, initial = seed(tmp_path)
    path = Path(settings["budget_path"])
    if invalid == "missing":
        path.unlink()
    elif invalid == "json":
        path.write_text("{malformed")
    elif invalid == "limits":
        initial["limits"]["questions"] = "changed"
        path.write_text(json.dumps(initial))
    else:
        initial["generation"]["unknown_usage"] = {
            "negative": -1,
            "boolean": True,
            "noninteger": 1.5,
        }[invalid]
        path.write_text(json.dumps(initial))
    raw = path.read_bytes() if path.exists() else None
    with pytest.raises(HttpOwnershipError):
        with http_budget_scope(settings):
            pytest.fail("invalid ledger admitted")
    assert (path.read_bytes() if path.exists() else None) == raw


def test_frozen_profile_domain_and_exact_completion_capability(tmp_path: Path) -> None:
    settings, host, _, _ = seed(tmp_path)
    frozen = {"config": settings, **freeze_fields(settings)}
    check_frozen(frozen)
    frozen["http_ownership_binding"]["domain_sha256"] = "a" * 64
    with pytest.raises(HttpOwnershipError, match="FROZEN_CHANGED"):
        check_frozen(frozen)
    assert freeze_fields({}) == freeze_fields({"http_ownership_profile": "legacy"}) == {}
    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        client = VLLMClient(
            host, budget=budget, transport=httpx.MockTransport(lambda _: response())
        )
        with budget.http_owner.request(
            client,
            budget,
            asdict(host),
            "http://synthetic/v1/",
            "chat/completions",
            "http://synthetic/v1/chat/completions",
            host.model,
        ):
            reservation = budget.reserve("chat/completions", {"messages": [], "max_tokens": 8})
            with pytest.raises(HttpOwnershipError, match="COMPLETION_NOT_AUTHORIZED"):
                budget.finish(tuple(reservation), {"total_tokens": 1})
            budget.finish(reservation, {"total_tokens": 5})
            with pytest.raises(HttpOwnershipError, match="COMPLETION_NOT_AUTHORIZED"):
                budget.finish(reservation, {"total_tokens": 1})
        client.close()


def test_scoped_second_budget_and_budgetless_client_reject_before_httpx(tmp_path: Path) -> None:
    settings, host, _, _ = seed(tmp_path)
    with http_budget_scope(settings) as budget:
        assert budget is not None
        with pytest.raises(HttpOwnershipError, match="SECOND_BUDGET"):
            RunBudget(budget.limits, budget.path)
        with pytest.raises(HttpOwnershipError, match="EXACT_BUDGET"):
            VLLMClient(host)


def test_actual_httpx_timeout_rejected_at_private_dispatch_before_reserve(tmp_path: Path) -> None:
    settings, host, _, initial = seed(tmp_path)
    dispatches = []
    with http_budget_scope(settings) as budget:
        assert budget is not None
        with VLLMClient(
            host,
            budget=budget,
            transport=httpx.MockTransport(lambda r: dispatches.append(r) or response()),
        ) as client:
            client._client.timeout = httpx.Timeout(host.timeout + 1)
            with pytest.raises(HttpOwnershipError, match="TIMEOUT_CHANGED"):
                client._post(
                    "chat/completions", {"model": host.model, "messages": [], "max_tokens": 8}
                )
            assert not dispatches and budget.state == initial


def test_constructor_normalized_url_refusal_closes_created_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, host, _, _ = seed(tmp_path)
    host = replace(host, base_url="http://synthetic/v1/../v2")
    settings["http_ownership_domain"]["clients"][0] = asdict(host)
    ledger = Path(settings["budget_path"])
    before = ledger.read_bytes()
    created: list[httpx.Client] = []
    original = httpx.Client
    dispatches = []

    class TrackingClient(original):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        owner = budget.http_owner
        with monkeypatch.context() as patch:
            patch.setattr(httpx, "Client", TrackingClient)
            with pytest.raises(HttpOwnershipError, match="CLIENT_CHANGED") as error:
                VLLMClient(
                    host, budget=budget,
                    transport=httpx.MockTransport(lambda r: dispatches.append(r) or response()),
                )
        assert len(created) == 1 and created[0].is_closed
        assert str(created[0].base_url) == "http://synthetic/v2/"
        assert not owner._clients and not dispatches and ledger.read_bytes() == before
        proof(tmp_path, "normalized-url-cleanup.json", {
            "declared": host.base_url, "actual": str(created[0].base_url),
            "original_error": str(error.value), "httpx_is_closed": created[0].is_closed,
            "registered_clients": len(owner._clients), "dispatches": len(dispatches),
            "ledger_before_sha256": hashlib.sha256(before).hexdigest(),
            "ledger_after_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        })
    assert owner.closed
    with http_budget_scope(settings) as reopened:
        assert reopened is not None


@pytest.mark.parametrize("cleanup", ["complete", "before", "transport", "noop"])
def test_partial_initialization_cleanup_keeps_lease_on_actual_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cleanup: str
) -> None:
    settings, host, _, _ = seed(tmp_path)
    ledger = Path(settings["budget_path"])
    before = ledger.read_bytes()
    owner = HttpOwnership(ledger, settings["http_ownership_domain"])
    budget = RunBudget(RunLimits(generation_requests=20), ledger, http_owner=owner)
    created: list[httpx.Client] = []
    original = httpx.Client
    initialization_error = HttpOwnershipError("synthetic original validation failure")
    dispatches = []

    class ClosingTransport(httpx.MockTransport):
        resource_closed = False

        def close(self) -> None:
            if cleanup == "transport":
                raise OSError("synthetic transport cleanup failure")
            super().close()
            self.resource_closed = True

    transport = ClosingTransport(lambda r: dispatches.append(r) or response())

    class TrackingClient(original):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

        def close(self) -> None:
            if cleanup == "before":
                raise OSError("synthetic client cleanup failure")
            if cleanup == "noop":
                return
            super().close()

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise initialization_error

    try:
        with monkeypatch.context() as patch:
            patch.setattr(httpx, "Client", TrackingClient)
            patch.setattr(owner, "assert_client", refuse)
            with pytest.raises(HttpOwnershipError, match="original validation failure") as error:
                VLLMClient(host, budget=budget, transport=transport)
        assert error.value is initialization_error and len(created) == 1
        assert not dispatches and ledger.read_bytes() == before
        registered = len(owner._clients)
        cause = error.value.__cause__
        if cleanup == "complete":
            assert created[0].is_closed and transport.resource_closed
            assert registered == 0 and cause is None
            owner.close()
        else:
            assert registered == 1 and not transport.resource_closed
            assert owner._clients[next(iter(owner._clients))][2] is True
            if cleanup == "noop":
                assert isinstance(cause, HttpOwnershipError) and "CLOSE_INCOMPLETE" in str(cause)
            else:
                assert isinstance(cause, OSError) and "cleanup failure" in str(cause)
            # HTTPX marks CLOSED before calling transport.close: this actual
            # failure must retain the lease even though is_closed is true.
            assert created[0].is_closed == (cleanup == "transport")
            with pytest.raises(HttpOwnershipError, match="CLIENTS_STILL_OPEN"):
                owner.close()
            competitor = child(tmp_path, "cleanup-competitor", """import json,sys
from pathlib import Path
from milai_lab.harness.http_ownership import HttpOwnership,HttpOwnershipError
s=json.loads(sys.argv[1])
try: HttpOwnership(Path(s['budget_path']),s['http_ownership_domain'])
except HttpOwnershipError as e: print(str(e));sys.exit(17)
""", settings)
            assert competitor.returncode == 17 and "HTTP_OWNER_BUSY" in competitor.stdout
        proof(tmp_path, "partial-initialization-cleanup.json", {
            "cleanup": cleanup, "original_error": str(error.value),
            "original_type": type(error.value).__name__,
            "cleanup_error": str(cause) if cause else None,
            "cleanup_type": type(cause).__name__ if cause else None,
            "httpx_is_closed": created[0].is_closed,
            "actual_transport_closed": transport.resource_closed,
            "registered_clients": registered, "lease_closed": owner.closed,
            "dispatches": len(dispatches), "ledger_unchanged": ledger.read_bytes() == before,
        })
    finally:
        # Test teardown only: explicitly release the synthetic transport and
        # registry after recording the refusal. Runtime performs no retry.
        if not owner.closed:
            httpx.MockTransport.close(transport)
            if created:
                original.close(created[0])
            for wrapper, _, _ in list(owner._clients.values()):
                owner.abort_client(wrapper)
            owner.close()


def test_httpx_constructor_failure_without_returned_resource_releases_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, host, _, _ = seed(tmp_path)
    before = Path(settings["budget_path"]).read_bytes()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic constructor failure before returned resource")

    with http_budget_scope(settings) as budget:
        assert budget is not None and budget.http_owner is not None
        with monkeypatch.context() as patch:
            patch.setattr(httpx, "Client", fail)
            with pytest.raises(OSError, match="constructor failure"):
                VLLMClient(host, budget=budget)
        assert not budget.http_owner._clients
        assert Path(settings["budget_path"]).read_bytes() == before
