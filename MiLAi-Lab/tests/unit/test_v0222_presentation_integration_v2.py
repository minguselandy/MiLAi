"""NOT_ACTUAL_INSTANCE: real scoped stack over synthetic lineage/public/PIDs.

Real new Batch construction, authorization, manifest/plan checks, read scopes,
SQL/FSM mirrors, preparation, preflight, worker, Provider/Transport, original
Session/World and terminal/finish/gate auditors run unchanged. Only fixed lineage
selection/old coordinator attestation, public inputs, PIDs and HTTP are synthetic.
No validator, new authorization method, journal or business effect is replaced.
This is not 40 actual cold OS workers, production history or real-model evidence.
"""

import copy
import json
import os
import socket
import sqlite3
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

import preflight_v0222_presentation_v2 as preflight
import prepare_v0222_presentation as original_prepare
import prepare_v0222_presentation_v2 as prepare
import v0222_presentation_audit as audit
import v0222_presentation_batch_v2 as core
import v0222_presentation_lineage_v2 as lineage
import v0222_presentation_worker_v2 as worker
from prepare_v0221_http_v2 import FINISH, READBACK
from prepare_v0222_full import resolve_p4_spec
from v02_local_provider import append_event, read_events
from v0213_provider import MODEL, TOKENIZE_KEYS
from v0220_evidence import LAB, read, save, seal, sha
from v0220_provider_hardened import ProviderStop
from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_presentation_finish_v2 import Batch
from v0222_presentation_gates_v2 import SCOPE_PREREQUISITES
from v0222_presentation_provider_v2 import FullProvider
from v0222_scoped_history import historical_usage_from_pinned


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("SCOPED_INTEGRATION_MOCK_HTTP_ONLY")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def environment(index):
    value = public()
    value["task"]["request"] = f"Synthetic complete source {index}; not a benchmark case."
    for schema in value["task"]["record_schemas"].values():
        schema["properties"]["text"].update(pattern=r"\S", minLength=1)
        schema["properties"]["extra"]["properties"]["items"]["uniqueItems"] = True
    return value


def old_plan(prefix, public_values):
    p3 = [
        {
            "id": f"{prefix}-p3-{i:02d}",
            "stage": "P3",
            "root": f"root-{(i - 1) % 8 // 2}",
            "cold": 1 if i <= 8 else 2,
            "variant": "full" if i % 2 else "finish",
            "scope": f"{prefix}-scope-p3-{i:02d}",
            "expected": copy.deepcopy(put() if i % 2 else FINISH),
        }
        for i in range(1, 17)
    ]
    p4 = []
    for i in range(1, 25):
        kind = (i - 1) % 6 // 2
        actions = [put(), put("right", 1)][: 2 if kind == 1 else 1]
        spec = {
            "id": f"{prefix}-p4-{i:02d}",
            "stage": "P4",
            "root": f"root-{(i - 1) // 6}",
            "family": "SYNTHETIC_ONLY",
            "kind": ("single", "double", "complex")[(i - 1) % 6 // 2],
            "cold": 1 if i % 2 else 2,
            "scope": f"{prefix}-scope-p4-{i:02d}",
            "initial_state_sha256": "0" * 64,
            "actions": actions,
            "intent": {
                "instruction": "Apply these complete writes in order, read records, then finish.",
                "ordered_writes": [
                    {key: action["arguments"][key] for key in ("object_id", "data")}
                    for action in actions
                ],
            },
        }
        p4.append(resolve_p4_spec(spec, public_values[spec["root"]])[0])
    return {"P3": p3, "P4": p4}


def historical_events(key):
    return [
        {
            "event": "RESERVED",
            "request_id": key,
            "session": key,
            "prompt_tokens": 10,
            "output_cap": 4096,
            "raw_upper_bound": 4106,
            "cumulative_raw_cap": None,
            "payload_sha256": "a" * 64,
        },
        {"event": "DISPATCH_STARTED", "request_id": key},
        {"event": "RESPONSE_RECEIVED", "request_id": key, "status_code": 200},
        {
            "event": "USAGE_KNOWN",
            "request_id": key,
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
    ]


def synthetic_history(tmp_path, roots):
    paths = [tmp_path / "legacy-known.jsonl", tmp_path / "legacy-unknown.jsonl"]
    for index in range(55):
        paths.append(
            roots[index % 4]
            / "episodes"
            / f"historical-{index:02d}"
            / "provider/provider-ledger-v2.jsonl"
        )
    for index in range(2):
        append_event(
            paths[0],
            {
                "event": "RESERVED",
                "request_id": f"legacy-{index}",
                "session": "legacy",
                "prompt_tokens": 10,
                "output_cap": 4096,
                "raw_upper_bound": 4106,
            },
        )
        append_event(
            paths[0],
            {
                "event": "SETTLED",
                "request_id": f"legacy-{index}",
                "input_tokens": 10,
                "output_tokens": 1,
            },
        )
    append_event(
        paths[1],
        {
            "event": "RESERVED",
            "request_id": "legacy-unknown",
            "session": "legacy",
            "prompt_tokens": 24188,
            "output_cap": 4096,
            "raw_upper_bound": 28284,
        },
    )
    for index, path in enumerate(paths[2:]):
        path.parent.mkdir(parents=True, exist_ok=True)
        for event in historical_events(f"synthetic-history-{index}"):
            append_event(path, event)
    return [{"path": str(path), "sha256": sha(path)} for path in paths]


def setup(tmp_path, monkeypatch):
    """Freeze synthetic inputs with actual source closure; never fake _authorize."""
    root, parent, previous = (tmp_path / name for name in ("new", "parent", "previous"))
    boundary, ancestor = tmp_path / "boundary", tmp_path / "ancestor"
    public_root = tmp_path / "public"
    public_values, inputs = {}, {}
    for index in range(4):
        name = f"root-{index}"
        public_values[name] = environment(index)
        path = public_root / name / "public-initial.json"
        save(path, public_values[name])
        inputs[str(path)] = sha(path)
    for prefix, old_root in (("parent", parent), ("previous", previous)):
        save(
            old_root / "manifest.json",
            {"contract": old_plan(prefix, public_values), "inputs": inputs},
        )
        save(
            old_root / "execution-binding.json", {"manifest.json": sha(old_root / "manifest.json")}
        )
    save(boundary / "execution-binding.json", {"TEST_ONLY_BOUNDARY": True})
    history_pins = synthetic_history(tmp_path, (ancestor, parent, boundary, previous))
    inventory_files = {
        **inputs,
        **{row["path"]: row["sha256"] for row in history_pins},
        **{
            str(old_root / name): sha(old_root / name)
            for old_root in (parent, previous)
            for name in ("manifest.json", "execution-binding.json")
        },
        str(boundary / "execution-binding.json"): sha(boundary / "execution-binding.json"),
    }
    inventory_path = tmp_path / "synthetic-inventory.json"
    save(
        inventory_path,
        {
            "status": "INDEPENDENT_HISTORY_INVENTORY_REVIEW_PASS_NOT_AUTHORIZATION",
            "TEST_ONLY_NOT_ACTUAL_HISTORY_REVIEW": True,
            "sources": history_pins,
            "terminal_states": [
                {"root": str(path)} for path in (ancestor, parent, boundary, previous)
            ],
            "files": inventory_files,
        },
    )
    inventory_sha = sha(inventory_path)
    for name, value in {
        "ROOT": root,
        "PARENT_ROOT": parent,
        "PARENT_BINDING": sha(parent / "execution-binding.json"),
        "PRESENTATION_ROOT": previous,
        "PRESENTATION_BINDING": sha(previous / "execution-binding.json"),
        "BOUNDARY_ROOT": boundary,
        "BOUNDARY_BINDING": sha(boundary / "execution-binding.json"),
        "INVENTORY_PATH": inventory_path,
        "INVENTORY_SHA256": inventory_sha,
    }.items():
        monkeypatch.setattr(core, name, value)
    monkeypatch.setattr(lineage, "INVENTORY_PATH", inventory_path)
    monkeypatch.setattr(lineage, "INVENTORY_SHA256", inventory_sha)
    monkeypatch.setattr(prepare, "PRESENTATION_ROOT", previous)
    for module in (prepare, original_prepare, audit, worker):
        monkeypatch.setattr(module, "CASES", public_root)
    monkeypatch.setattr(worker, "ROOT", root)
    scopes = []

    def fixed_synthetic_lineage(scope):
        # Only old coordinator selection/attestation is simulated. Pins, strict
        # JSONL, historical FSM, global request IDs and sums remain real.
        inventory = lineage.read_inventory(scope)
        for name, expected in inventory["files"].items():
            scope.read_bytes(Path(name), expected)
        history = historical_usage_from_pinned(scope, inventory["sources"])
        assert (
            history["requests"],
            history["known_raw_tokens"],
            history["reserved_raw_upper_bound"],
        ) == (58, 682, 28284)
        scopes.append(scope)
        return history

    monkeypatch.setattr(lineage, "verify_lineage", fixed_synthetic_lineage)
    with AdmissionReadScope() as scope:
        history = fixed_synthetic_lineage(scope)
        matrix = prepare.episode_specs(scope)
    plan = {
        **matrix,
        "revision": core.REVISION,
        "coordinator_revision": core.COORDINATOR_REVISION,
        "selected_decoder": "D11",
        "selected_presentation": "B1",
        "http_identity": core.IDENTITY,
        "parent_root": str(parent),
        "parent_binding": core.PARENT_BINDING,
        "boundary_root": str(boundary),
        "boundary_binding": core.BOUNDARY_BINDING,
        "presentation_root": str(previous),
        "presentation_binding": core.PRESENTATION_BINDING,
        "historical_paths": [row["path"] for row in history_pins],
    }
    seal(
        root,
        entries=[
            Path(__file__).resolve(),
            LAB / "tests/unit/test_v0220_action_adapter.py",
            LAB / "tools/run_v0222_presentation_v2.py",
        ],
        inputs=[*(Path(name) for name in inventory_files), inventory_path],
        contract=plan,
    )
    save(
        root / "authorization.json",
        core.make_authorization(
            root, issued=time.time() - 1, expires=time.time() + 36000, history=history
        ),
    )
    save(root / "authorization-source.json", core.authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("manifest.json", "authorization.json", "authorization-source.json")
        },
    )
    batch = Batch(root, sha(root / "execution-binding.json"))
    batch.initialize()
    prepared = prepare.materialize_references(batch)
    assert (
        prepared["P3_requests"],
        prepared["P4_requests"],
        prepared["isolated_offline_worlds"],
    ) == (16, 80, 40)
    engineering = root / "engineering.json"
    save(
        engineering,
        {
            "status": "ENGINEERING_CHECKS_PASS",
            "TEST_ONLY_NOT_ENGINEERING_PROOF": True,
            "files": {str(root / "manifest.json"): sha(root / "manifest.json")},
        },
    )
    batch.freeze_artifact("engineering_checks", engineering)
    review_files = {
        str(root / name): sha(root / name)
        for name in (
            "execution-binding.json",
            "manifest.json",
            "authorization.json",
            "authorization-source.json",
        )
    }
    with batch.transaction() as db:
        for name in SCOPE_PREREQUISITES:
            row = dict(db.execute("SELECT * FROM artifacts WHERE name=?", (name,)).fetchone())
            for mapping in (
                {row["path"]: row["sha256"]},
                json.loads(row["dependencies"]),
                read(Path(row["path"]))["files"],
            ):
                for path, expected in mapping.items():
                    assert path not in review_files or review_files[path] == expected
                    review_files[path] = expected
    review = root / "scope-review.json"
    save(
        review,
        {
            "status": "G_AUTH_SCOPE_REVIEW_PASS",
            "root": str(root),
            "binding_sha256": batch.binding_sha,
            "review_is_not_user_consent": True,
            "TEST_ONLY_NOT_ACTUAL_SCOPE_REVIEW": True,
            "files": review_files,
        },
    )
    batch.freeze_artifact("scope_review", review)
    assert type(batch) is Batch and batch._authorize.__func__ is core.Batch._authorize
    assert not batch.snapshot()["stop"]
    return batch, [], scopes


def mocked(batch, calls, scopes, category, outputs=()):
    queue, counted = iter(outputs), None

    def handle(request):
        nonlocal counted
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
        with sqlite3.connect(batch.path, timeout=0.1) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
        calls.append((category, request.url.path))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": batch.plan["http_identity"]["version"]})
        if request.url.path == "/tokenize":
            counted = json.loads(request.content)
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions" and category.startswith("worker:")
        body = json.loads(request.content)
        assert fingerprint(counted) == fingerprint({key: body[key] for key in TOKENIZE_KEYS})
        output = next(queue)
        raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=True, indent=1)
        return httpx.Response(
            200,
            json={
                "id": "MOCK_ONLY",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    return httpx.MockTransport(handle)


def capacity(batch, calls, scopes, stage):
    result = preflight.preflight(
        batch.root,
        batch.binding_sha,
        stage,
        transport=mocked(batch, calls, scopes, stage + "_preflight"),
    )
    assert result["status"] == "G_PREFLIGHT_PASS"
    return result


def execute(batch, monkeypatch, spec, calls, scopes, *, outputs=None, finish=True):
    if outputs is None:
        outputs = (
            [spec["expected"]] if spec["stage"] == "P3" else [*spec["actions"], READBACK, FINISH]
        )
    index = [s["id"] for stage in ("P3", "P4") for s in batch.plan[stage]].index(spec["id"])
    parent_pid, pid, started = os.getpid(), 90000000 + index, time.monotonic()
    transport = mocked(batch, calls, scopes, "worker:" + spec["id"], outputs)

    def provider(*args, **kwargs):
        return FullProvider(*args, **kwargs, transport=transport)

    with monkeypatch.context() as patch:
        patch.setattr(core.os, "getpid", lambda: pid)
        patch.setattr(worker, "FullProvider", provider)
        result = worker.run(batch.root, batch.binding_sha, spec["id"])
        assert result["pid"] == pid
    save(
        batch.root / "exits" / (spec["id"] + ".json"),
        {
            "pid": pid,
            "parent_pid": parent_pid,
            "returncode": 0,
            "timed_out": False,
            "seconds": time.monotonic() - started,
            "TEST_ONLY_SIMULATED_PROCESS": True,
        },
    )
    result = batch.finish(spec["id"]) if finish else result
    print(f"integration {spec['stage']} {spec['id']}: {result['status']}", flush=True)
    return result


@pytest.mark.regression
def test_complete_real_scoped_stack_16_then_24(tmp_path, monkeypatch):
    batch, calls, scopes = setup(tmp_path, monkeypatch)
    capacity(batch, calls, scopes, "P3")
    batch.launch_once("P3")
    for spec in batch.plan["P3"]:
        assert execute(batch, monkeypatch, spec, calls, scopes)["status"] == "PASS"
    assert not (batch.root / "worlds").exists()
    gate = batch.freeze_p3_gate(batch.root / "P3-gate.json")
    assert gate["full_passed"] == gate["finish_passed"] == 8
    capacity(batch, calls, scopes, "P4")
    batch.launch_once("P4")
    for spec in batch.plan["P4"]:
        result = execute(batch, monkeypatch, spec, calls, scopes)
        assert result["status"] == "PASS" and all(result["checks"].values())
        assert result["cost"]["requests"] == len(spec["actions"]) + 2
    snapshot = batch.snapshot()
    assert not snapshot["stop"] and all(row["status"] == "PASS" for row in snapshot["episodes"])
    assert snapshot["cost"]["requests"] == 96
    assert (
        snapshot["cost"]["known_raw_tokens"] == snapshot["cost"]["actual_total_raw_tokens"] == 11520
    )
    assert (
        batch.auth["historical"]["requests"] == 58
        and batch.auth["historical"]["known_raw_tokens"] == 682
    )
    assert batch.auth["historical"]["reserved_raw_upper_bound"] == 28284
    assert batch.auth["caps"] == {"P3": 16, "P4": 96}
    assert sum(path == "/v1/chat/completions" for _, path in calls) == 96
    assert (
        sum(path == "/tokenize" and category.endswith("preflight") for category, path in calls)
        == 192
    )
    assert (
        sum(path == "/tokenize" and category.startswith("worker:") for category, path in calls)
        == 96
    )
    for route in ("/v1/models", "/version"):
        assert sum(path == route for _, path in calls) == 44
    assert len({row["pid"] for row in snapshot["episodes"]}) == 40
    assert len(list((batch.root / "worlds").glob("*.sqlite"))) == 24
    assert len(list((batch.root / "full-reference").rglob("world.sqlite"))) == 40
    assert len(list((batch.root / "claims").glob("*.json"))) == 40
    assert len(list((batch.root / "exits").glob("*.json"))) == 40
    assert not list((batch.root / "episodes").rglob("note-*.json"))
    with batch.transaction() as db:
        batch._mirrors(db)
        events = batch.events(db)
    assert len(events) == 4 * 96
    assert batch.artifact("P3_gate")["status"] == "G_P3_PASS"
    assert all(scope.status == "CLOSED_VERIFIED_TWO_OBSERVATIONS" for scope in scopes)


@pytest.mark.regression
def test_first_wrong_intent_stops_without_business_or_p4(tmp_path, monkeypatch):
    batch, calls, scopes = setup(tmp_path, monkeypatch)
    capacity(batch, calls, scopes, "P3")
    batch.launch_once("P3")
    spec = batch.plan["P3"][0]
    wrong = copy.deepcopy(spec["expected"])
    wrong["arguments"]["object_id"] = "right"
    with pytest.raises(ProviderStop, match="FULL_INTENT_FIDELITY"):
        execute(batch, monkeypatch, spec, calls, scopes, outputs=[wrong])
    snapshot, before = batch.snapshot(), len(calls)
    assert snapshot["stop"] == "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"
    assert snapshot["cost"]["requests"] == 1 and snapshot["cost"]["known_raw_tokens"] == 120
    assert snapshot["episodes"][0]["status"] == "FAIL"
    assert sum(row["status"] == "PENDING" for row in snapshot["episodes"]) == 39
    with pytest.raises(ProviderStop):
        preflight.preflight(
            batch.root,
            batch.binding_sha,
            "P4",
            transport=mocked(batch, calls, scopes, "P4_preflight"),
        )
    with pytest.raises(ProviderStop):
        batch.launch_once("P4")
    assert len(calls) == before and not (batch.root / "worlds").exists()
    assert not (batch.root / "P3-gate.json").exists()
    assert not (batch.root / "live-launch-P4.json").exists()
    assert batch.snapshot()["stop"] == snapshot["stop"]


@pytest.mark.regression
def test_actual_raw_and_visible_corruption_cannot_finish(tmp_path, monkeypatch):
    batch, calls, scopes = setup(tmp_path, monkeypatch)
    capacity(batch, calls, scopes, "P3")
    batch.launch_once("P3")
    spec = batch.plan["P3"][0]
    execute(batch, monkeypatch, spec, calls, scopes, finish=False)
    provider = batch.root / "episodes" / spec["id"] / "provider"
    key = read_events(provider / "provider-ledger-v2.jsonl")[0]["request_id"]
    path, visible = provider / (key + "-http.json"), provider / (key + "-visible.json")
    value = read(path)
    envelope = json.loads(value["body"])
    envelope["choices"][0]["message"]["content"] = json.dumps(put("right"))
    value["body"] = json.dumps(envelope)
    # Only this synthetic unaccepted episode is corrupted; no frozen artifact
    # or production evidence is edited. All hash/acceptance methods stay real.
    path.write_text(json.dumps(value))
    visible.write_text(json.dumps({"content": envelope["choices"][0]["message"]["content"]}))
    with pytest.raises(ProviderStop):
        batch.finish(spec["id"])
    snapshot = batch.snapshot()
    assert snapshot["stop"] and snapshot["episodes"][0]["status"] == "FAIL"
    assert snapshot["cost"]["known_raw_tokens"] == 120
    assert sum(route == "/v1/chat/completions" for _, route in calls) == 1
    assert not (provider.parent / "independent-audit.json").exists()
    with batch.transaction() as db:
        assert (
            db.execute("SELECT 1 FROM artifacts WHERE name=?", (spec["id"] + "_audit",)).fetchone()
            is None
        )
