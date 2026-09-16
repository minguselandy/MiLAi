"""Offline real journal with synthetic pinned inputs and explicitly mocked auditors.

No test result here is an actual instance review or model/full execution result.
"""

import copy
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_batch as module
from v02_local_provider import append_event, read_events
from v0220_evidence import read, save, seal, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_presentation_batch import Batch


def events(key, ep):
    return [
        {
            "event": "RESERVED",
            "request_id": key,
            "session": ep,
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


def old_database(root, binding, stop, rows, history, launches):
    with sqlite3.connect(root / "batch.sqlite") as db:
        db.executescript(
            "CREATE TABLE meta(key TEXT,value TEXT);"
            "CREATE TABLE episodes(id TEXT,stage TEXT,ordinal INTEGER,status TEXT);"
            "CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT);"
            "CREATE TABLE launches(stage TEXT,pid INTEGER,started REAL);"
        )
        db.execute("INSERT INTO meta VALUES ('binding',?)", (binding,))
        if stop:
            db.execute("INSERT INTO meta VALUES ('stop',?)", (stop,))
        for row in rows:
            db.execute(
                "INSERT INTO episodes VALUES (?,?,?,?)",
                tuple(row[k] for k in ("id", "stage", "ordinal", "status")),
            )
        for path in history:
            for event in read_events(path):
                db.execute("INSERT INTO events(event) VALUES (?)", (json.dumps(event),))
        for launch in launches:
            db.execute(
                "INSERT INTO launches VALUES (?,?,?)",
                tuple(launch[k] for k in ("stage", "pid", "started")),
            )


def synthetic_audit(batch, ep):
    directory = batch.root / "episodes" / ep
    value = read(directory / "result.json")
    return {
        **value,
        "cost": usage_state(read_events(directory / "provider/provider-ledger-v2.jsonl")),
        "files": {
            str(p): sha(p)
            for p in directory.rglob("*")
            if p.is_file() and p.name != "independent-audit.json"
        },
    }


def fixture(tmp_path, monkeypatch):
    paths = tuple(tmp_path / f"history-{i:02}.jsonl" for i in range(44))
    for p in paths:
        p.touch()
    for i in range(2):
        append_event(
            paths[0],
            {
                "event": "RESERVED",
                "request_id": f"legacy-{i}",
                "session": "old",
                "prompt_tokens": 10,
                "output_cap": 4096,
                "raw_upper_bound": 4106,
            },
        )
        append_event(
            paths[0],
            {
                "event": "SETTLED",
                "request_id": f"legacy-{i}",
                "input_tokens": 10,
                "output_tokens": 1,
            },
        )
    append_event(
        paths[1],
        {
            "event": "RESERVED",
            "request_id": "old-unknown",
            "session": "old",
            "prompt_tokens": 24188,
            "output_cap": 4096,
            "raw_upper_bound": 28284,
        },
    )
    for i, p in enumerate(paths[2:]):
        for event in events(f"history-{i}", f"history-{i}"):
            append_event(p, event)
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", tuple((str(p), sha(p)) for p in paths))
    monkeypatch.setattr(module, "HISTORY_TOTALS", (45, 526, 28284))
    parent = tmp_path / "parent"
    parent.mkdir()
    p3 = [
        {
            "id": f"p3-{i:02}",
            "stage": "P3",
            "root": f"root-{(i - 1) % 8 // 2}",
            "cold": 1 if i <= 8 else 2,
            "variant": "full" if i % 2 else "finish",
            "scope": f"old-p3-{i}",
            "expected": {"action": "put_record" if i % 2 else "finish", "value": i % 8},
        }
        for i in range(1, 17)
    ]
    p4 = [
        {
            "id": f"p4-{i:02}",
            "stage": "P4",
            "root": f"root-{(i - 1) // 6}",
            "family": "synthetic",
            "kind": ("single", "double", "complex")[(i - 1) % 6 // 2],
            "cold": 1 if i % 2 else 2,
            "scope": f"old-p4-{i}",
            "initial_state_sha256": "0" * 64,
            "actions": [{"synthetic_action": j} for j in range(2 if (i - 1) % 6 // 2 == 1 else 1)],
            "intent": {"instruction": "synthetic complete intent", "ordered_writes": [i]},
        }
        for i in range(1, 25)
    ]
    save(parent / "manifest.json", {"contract": {"P3": p3, "P4": p4}})
    save(parent / "execution-binding.json", {"manifest.json": sha(parent / "manifest.json")})
    parent_binding = sha(parent / "execution-binding.json")
    save(
        parent / "P3-independent-review.json",
        {
            "terminal": {"episodes_snapshot": []},
            "files": {str(parent / "manifest.json"): sha(parent / "manifest.json")},
        },
    )
    old_database(parent, parent_binding, module.PARENT_STOP, [], paths[3:28], [])
    boundary = tmp_path / "boundary"
    boundary.mkdir()
    save(boundary / "execution-binding.json", {"parent": parent_binding})
    boundary_binding = sha(boundary / "execution-binding.json")
    boundary_rows = [
        {"id": f"r1-{i:02}", "stage": "R1", "ordinal": i - 1, "status": "OBSERVED"}
        for i in range(1, 17)
    ]
    launch = {"stage": "R1", "pid": 123, "started": 1.0}
    save(
        boundary / "final-decision.json",
        {"status": "INTENT_BOUNDARY_SIGNAL", "selected_condition": "B1"},
    )
    save(boundary / "result.json", {"status": "INTENT_BOUNDARY_SIGNAL"})
    save(
        boundary / "independent-result-review.json",
        {
            "status": "BOUNDARY_RESULT_REVIEW_PASS",
            "selected_condition": "B1",
            "experimental_verdict": "INTENT_BOUNDARY_SIGNAL",
            "execution": {"episodes": boundary_rows, "launch": launch},
            "files": {str(parent / "manifest.json"): sha(parent / "manifest.json")},
        },
    )
    old_database(boundary, boundary_binding, None, boundary_rows, paths[28:], [launch])
    for name, value in {
        "PARENT_ROOT": parent,
        "PARENT_BINDING": parent_binding,
        "PARENT_P3_REVIEW_SHA": sha(parent / "P3-independent-review.json"),
        "BOUNDARY_ROOT": boundary,
        "BOUNDARY_BINDING": boundary_binding,
        "BOUNDARY_REVIEW_SHA": sha(boundary / "independent-result-review.json"),
        "BOUNDARY_RESULT_SHA": sha(boundary / "result.json"),
        "BOUNDARY_DECISION_SHA": sha(boundary / "final-decision.json"),
    }.items():
        monkeypatch.setattr(module, name, value)
    root = tmp_path / "presentation"
    monkeypatch.setattr(module, "ROOT", root)
    plan = {
        "revision": module.REVISION,
        "selected_decoder": "D11",
        "selected_presentation": "B1",
        "http_identity": module.IDENTITY,
        "parent_root": str(parent),
        "parent_binding": parent_binding,
        "boundary_root": str(boundary),
        "boundary_binding": boundary_binding,
        "historical_paths": [str(p) for p in paths],
        "P3": copy.deepcopy(p3),
        "P4": copy.deepcopy(p4),
    }
    for stage in ("P3", "P4"):
        for spec in plan[stage]:
            spec["scope"] = "new-" + spec["id"]
            if stage == "P4":
                spec["initial_state_sha256"] = fingerprint({"scope": spec["scope"]})
    seal(root, entries=[], inputs=list(paths), contract=plan)
    save(
        root / "authorization.json",
        module.make_authorization(root, issued=time.time() - 1, expires=time.time() + 36000),
    )
    save(root / "authorization-source.json", module.authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("manifest.json", "authorization.json", "authorization-source.json")
        },
    )
    # Mock only the explicit independent audit interface; real integration belongs to another suite.
    auditor = ModuleType("v0222_presentation_audit")
    auditor.audit_episode = synthetic_audit
    auditor.validate_reference = lambda *args: None
    auditor.validate_preflight = lambda *args: None
    monkeypatch.setitem(sys.modules, "v0222_presentation_audit", auditor)
    batch = Batch(root, sha(root / "execution-binding.json"))
    batch.initialize()
    return batch


def gates(batch):
    anchor = batch.root / "manifest.json"
    for name, status in [
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
    ]:
        path = batch.root / (name + ".json")
        save(path, {"status": status, "files": {str(anchor): sha(anchor)}})
        batch.freeze_artifact(name, path, status)
    for stage in ("P3", "P4"):
        refs = []
        files = {}
        for spec in batch.plan[stage]:
            for turn in range(1, (1 if stage == "P3" else len(spec["actions"]) + 2) + 1):
                ref = {
                    "stage": stage,
                    "episode": spec["id"],
                    "turn": turn,
                    "selected_condition": "B1",
                    "selected_decoder": "D11",
                    "schema_pair": {},
                    "hashes": {},
                }
                for kind in module.REFERENCE_KINDS:
                    path = batch.root / "refs" / spec["id"] / f"{turn}-{kind}.json"
                    save(path, {"mock_only": True})
                    ref[kind] = str(path)
                    ref["hashes"][kind] = sha(path)
                    files[str(path)] = sha(path)
                refs.append(ref)
        path = batch.root / (stage + "-refs.json")
        save(path, {"references": refs, "files": files})
        batch.freeze_artifact(stage + "_references", path)
        pre = batch.root / (stage + "-preflight.json")
        save(pre, {"status": "G_PREFLIGHT_PASS", "files": {str(path): sha(path)}})
        batch.freeze_artifact(stage + "_preflight", pre)
    path = batch.root / "resolved.json"
    save(path, {"specs": batch.plan["P4"], "files": {str(anchor): sha(anchor)}})
    batch.freeze_artifact("P4_resolved_specs", path)


def complete(batch, monkeypatch, ep, *, count=None, status="PASS", finish=True):
    spec = batch.spec(ep)
    index = list(s["id"] for stage in ("P3", "P4") for s in batch.plan[stage]).index(ep)
    worker_pid = 90000000 + index
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: worker_pid)
        batch.claim(ep)
        directory = batch.root / "episodes" / ep
        (directory / "provider").mkdir(parents=True)
        for turn in range(
            count
            if count is not None
            else (1 if spec["stage"] == "P3" else len(spec["actions"]) + 2)
        ):
            for event in events(f"{ep}-{turn}", ep):
                batch.record(ep, event)
                append_event(directory / "provider/provider-ledger-v2.jsonl", event)
        save(
            directory / "result.json",
            {
                "id": ep,
                "stage": spec["stage"],
                "status": status,
                "pid": worker_pid,
                "checks": {"synthetic_only": True},
            },
        )
    return batch.finish(ep) if finish else None


def pass_p3(batch, monkeypatch):
    batch.launch_once("P3")
    for spec in batch.plan["P3"]:
        complete(batch, monkeypatch, spec["id"])
    path = batch.root / "P3-gate.json"
    save(path, batch.p3_gate())
    batch.freeze_p3_gate(path)


def test_exact_history_and_scope_do_not_authorize_new_instance(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    h = batch.auth["historical"]
    assert (h["requests"], h["known_raw_tokens"], h["reserved_raw_upper_bound"]) == (45, 526, 28284)
    assert h["actual_total_raw_tokens"] is None and len(h["unresolved_reservations"]) == 1
    assert batch.auth["diagnostic_content_failures_continue"] is False
    assert batch.snapshot()["cost"]["requests"] == 0 and len(batch.snapshot()["episodes"]) == 40
    with pytest.raises(ProviderStop, match="ARTIFACT"):
        batch.launch_once("P3")


@pytest.mark.parametrize("kind", ["missing", "duplicate", "reverse", "central"])
def test_history_44_exact_independent_ledgers(tmp_path, monkeypatch, kind):
    fixture(tmp_path, monkeypatch)
    paths = tuple(Path(p) for p, _ in module.HISTORICAL_SOURCES)
    bad = {
        "missing": paths[:-1],
        "duplicate": (*paths[:-1], paths[0]),
        "reverse": tuple(reversed(paths)),
        "central": (*paths, module.BOUNDARY_ROOT / "batch.sqlite"),
    }[kind]
    with pytest.raises(ProviderStop, match="EXACT_44"):
        module.historical_usage_presentation(bad)


def test_rehashed_new_unknown_is_not_an_exception(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    paths = tuple(Path(p) for p, _ in module.HISTORICAL_SOURCES)
    append_event(paths[-1], events("unexpected", "unexpected")[0])
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", tuple((str(p), sha(p)) for p in paths))
    with pytest.raises(ProviderStop, match="NO_NEW_HISTORICAL_UNKNOWN"):
        module.historical_usage_presentation(paths)


@pytest.mark.parametrize(
    "target",
    ["parent_stop", "boundary_stop", "boundary_rows", "boundary_events", "boundary_review"],
)
def test_prior_terminal_evidence_never_changes(tmp_path, monkeypatch, target):
    batch = fixture(tmp_path, monkeypatch)
    if target == "boundary_review":
        with (module.BOUNDARY_ROOT / "independent-result-review.json").open("a") as stream:
            stream.write(" ")
    else:
        root = module.PARENT_ROOT if target == "parent_stop" else module.BOUNDARY_ROOT
        with sqlite3.connect(root / "batch.sqlite") as db:
            if target == "parent_stop":
                db.execute("DELETE FROM meta WHERE key='stop'")
            elif target == "boundary_stop":
                db.execute("INSERT INTO meta VALUES ('stop','NEW_FAILURE')")
            elif target == "boundary_rows":
                db.execute("UPDATE episodes SET status='PENDING' WHERE ordinal=0")
            else:
                db.execute("DELETE FROM events WHERE seq=1")
    with pytest.raises(ProviderStop):
        batch.authorize("P3")


@pytest.mark.parametrize("field", ["actions", "intent", "scope", "initial_state_sha256", "cold"])
def test_only_new_scope_id_and_derived_hash_may_change_plan(tmp_path, monkeypatch, field):
    batch = fixture(tmp_path, monkeypatch)
    spec = batch.plan["P4"][0]
    if field == "scope":
        spec[field] = "old-p4-1"
    elif field == "initial_state_sha256":
        spec[field] = "0" * 64
    elif field == "cold":
        spec[field] = True
    else:
        spec[field] = {}
    with pytest.raises(ProviderStop):
        batch._validate_plan()


def test_p4_requires_16_new_pass_and_derived_gate_not_status_label(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    with pytest.raises(ProviderStop):
        batch.launch_once("P4")
    fake = batch.root / "fake-gate.json"
    save(fake, {"status": "G_P3_PASS"})
    with pytest.raises(ProviderStop, match="REQUIRES_16"):
        batch.freeze_p3_gate(fake)
    pass_p3(batch, monkeypatch)
    batch.launch_once("P4")
    complete(batch, monkeypatch, "p4-01")
    assert batch.snapshot()["cost"]["requests"] == 19


def test_all_16_plus_24_preserve_96_cap_not_80_references(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    pass_p3(batch, monkeypatch)
    assert len(batch.references("P3")) == 16 and len(batch.references("P4")) == 80
    batch.launch_once("P4")
    for spec in batch.plan["P4"]:
        complete(batch, monkeypatch, spec["id"], count=4)
    snap = batch.snapshot()
    assert snap["cost"]["requests"] == 112
    assert all(x["status"] == "PASS" for x in snap["episodes"]) and snap["stop"] is None
    assert batch.auth["caps"] == {"P3": 16, "P4": 96}
    with pytest.raises(ProviderStop, match="ALREADY_LAUNCHED"):
        batch.launch_once("P4")


@pytest.mark.parametrize("status", ["FAIL", "OBSERVED", "CONTENT_DIFFERENCE"])
def test_p3_first_non_pass_is_permanent_even_with_known_usage(tmp_path, monkeypatch, status):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    with pytest.raises(ProviderStop, match="FULL_ACCEPTANCE"):
        complete(batch, monkeypatch, "p3-01", status=status)
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] == 12
    assert batch.snapshot()["stop"] and batch.snapshot()["episodes"][0]["status"] == "FAIL"
    rebuilt = Batch(batch.root, batch.binding_sha)
    with pytest.raises(ProviderStop, match="STOPPED"):
        rebuilt.launch_once("P4")


def test_p4_failure_is_not_repaired_or_rebased(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    pass_p3(batch, monkeypatch)
    batch.launch_once("P4")
    with pytest.raises(ProviderStop):
        complete(batch, monkeypatch, "p4-01", status="FAIL")
    assert batch.snapshot()["stop"] and batch.snapshot()["cost"]["requests"] == 19


def test_delete_database_relaunch_and_cross_root_cannot_reset(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    with pytest.raises(ProviderStop, match="ALREADY_LAUNCHED"):
        batch.launch_once("P3")
    with pytest.raises(ProviderStop, match="ONE_FIXED"):
        Batch(tmp_path / "other", batch.binding_sha)
    batch.path.unlink()
    with pytest.raises(FileExistsError):
        batch.initialize()
    assert not batch.path.exists()


def test_stage_order_pid_reuse_parent_worker_and_one_active(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    with pytest.raises(ProviderStop, match="SEPARATE_COLD"):
        batch.claim("p3-01")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 900)
        with pytest.raises(ProviderStop, match="OUT_OF_ORDER"):
            batch.claim("p3-09")
    complete(batch, monkeypatch, "p3-01")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 90000000)
        with pytest.raises(ProviderStop, match="FRESH_CLIENT"):
            batch.claim("p3-02")
    monkeypatch.setattr(module.os, "getpid", lambda: 900)
    batch.claim("p3-02")
    with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
        batch.claim("p3-03")
    with pytest.raises(ProviderStop, match="NO_OWNED"):
        batch.finish("p3-02")


def test_only_one_own_pending_admitted_before_send(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    monkeypatch.setattr(module.os, "getpid", lambda: 900)
    batch.claim("p3-01")
    ledger = batch.root / "episodes/p3-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in events("own", "p3-01")[:2]:
        batch.record("p3-01", event)
        append_event(ledger, event)
        assert batch.http_admit("p3-01", inflight=True)["pid"] == 900
    with pytest.raises(ProviderStop, match="UNKNOWN"):
        batch.admit("p3-01")
    with pytest.raises(ProviderStop):
        batch.http_admit("p3-02", inflight=True)
    batch.stop("STOP_BEFORE_SEND")
    with pytest.raises(ProviderStop, match="STOPPED"):
        batch.http_admit("p3-01", inflight=True)
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] is None


def test_new_unknown_preserved_and_cap_cannot_be_increased(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    monkeypatch.setattr(module.os, "getpid", lambda: 900)
    batch.claim("p3-01")
    ledger = batch.root / "episodes/p3-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in [*events("own", "p3-01")[:2], {"event": "USAGE_UNKNOWN", "request_id": "own"}]:
        batch.record("p3-01", event)
        append_event(ledger, event)
    assert batch.snapshot()["stop"] == "USAGE_UNKNOWN"
    assert batch.snapshot()["cost"]["requests"] == 1
    with pytest.raises(ProviderStop, match="STOPPED"):
        batch.admit("p3-01")


def test_one_request_cap_and_raw_bound_strict_types(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    monkeypatch.setattr(module.os, "getpid", lambda: 900)
    batch.claim("p3-01")
    event = events("one", "p3-01")[0]
    event["output_cap"] = 4096.0
    with pytest.raises(ProviderStop, match="FROZEN_REQUEST_CAP"):
        batch.record("p3-01", event)
    ledger = batch.root / "episodes/p3-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in events("one", "p3-01"):
        batch.record("p3-01", event)
        append_event(ledger, event)
    with pytest.raises(ProviderStop, match="BATCH_COUNT"):
        batch.record("p3-01", events("two", "p3-01")[0])
    ledger.unlink()
    with pytest.raises(ProviderStop, match="DIVERGED"):
        batch.admit("p3-01")


def test_p3_gate_reaudits_raw_and_checks_both_passes(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    for spec in batch.plan["P3"][:8]:
        complete(batch, monkeypatch, spec["id"])
    with pytest.raises(ProviderStop, match="REQUIRES_16"):
        batch.p3_gate()
    for spec in batch.plan["P3"][8:]:
        complete(batch, monkeypatch, spec["id"])
    gate = batch.p3_gate()
    assert gate["full_passed"] == gate["finish_passed"] == 8
    raw = batch.root / "episodes/p3-01/result.json"
    with raw.open("a") as stream:
        stream.write(" ")
    with pytest.raises(ProviderStop, match="DEPENDENCY_DRIFT"):
        batch.p3_gate()


def test_known_usage_cannot_replace_raw_independent_audit(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    complete(batch, monkeypatch, "p3-01", finish=False)
    audit = sys.modules["v0222_presentation_audit"]
    original = audit.audit_episode

    def wrong_cost(*args):
        value = original(*args)
        value["cost"]["known_raw_tokens"] = 0
        return value

    monkeypatch.setattr(audit, "audit_episode", wrong_cost)
    with pytest.raises(ProviderStop, match="AUDIT_COST"):
        batch.finish("p3-01")
    assert batch.snapshot()["stop"] and batch.snapshot()["cost"]["known_raw_tokens"] == 12


def test_gate_names_and_resolved_spec_are_append_only(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    with pytest.raises(ProviderStop, match="ALREADY_FROZEN"):
        batch.freeze_artifact("P4_resolved_specs", batch.root / "resolved.json")
    path = batch.root / "bad-resolved.json"
    save(
        path,
        {
            "specs": [],
            "files": {str(batch.root / "manifest.json"): sha(batch.root / "manifest.json")},
        },
    )
    with pytest.raises(ProviderStop, match="EXACT_RESOLVED"):
        batch.freeze_artifact("P4_resolved_specs", path)
    with pytest.raises(ProviderStop, match="ONLY_INDEPENDENT"):
        batch.freeze_artifact("p3-01_audit", path)


def test_time_limits_do_not_reset_across_stages(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    pass_p3(batch, monkeypatch)
    batch.launch_once("P4")
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("p4-01")
    row = batch.admit("p4-01")
    now = time.time()
    assert row["deadline"] <= now + 300
    monkeypatch.setattr(module.time, "time", lambda: row["deadline"] + 1)
    with pytest.raises(ProviderStop, match="EPISODE_DEADLINE"):
        batch.http_admit("p4-01")


def test_actual_child_process_claim_is_distinct_and_cannot_be_resumed(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    # Only temporary synthetic constants are replaced in the child; journal/PID checks are real.
    code = """
import sys
from pathlib import Path
sys.path.insert(0, 'tools')
import v0222_presentation_batch as m
from v0220_evidence import read,sha
root=Path(sys.argv[1]);a=read(root/'authorization.json')
m.ROOT=root;m.PARENT_ROOT=Path(a['parent_root']);m.PARENT_BINDING=a['parent_binding']
m.BOUNDARY_ROOT=Path(a['boundary_root']);m.BOUNDARY_BINDING=a['boundary_binding']
m.PARENT_P3_REVIEW_SHA=sha(m.PARENT_ROOT/'P3-independent-review.json')
m.BOUNDARY_REVIEW_SHA=sha(m.BOUNDARY_ROOT/'independent-result-review.json')
m.BOUNDARY_RESULT_SHA=sha(m.BOUNDARY_ROOT/'result.json')
m.BOUNDARY_DECISION_SHA=sha(m.BOUNDARY_ROOT/'final-decision.json')
m.HISTORICAL_SOURCES=tuple((r['path'],r['sha256']) for r in a['historical']['sources'])
m.HISTORY_TOTALS=(45,526,28284)
b=m.Batch(root,sys.argv[2]);b.claim('p3-01');print(b.admit('p3-01')['pid'])
"""
    child = subprocess.run(  # noqa: S603 - fixed local offline synthetic coordinator test
        [sys.executable, "-c", code, str(batch.root), batch.binding_sha],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
    child_pid = int(child.stdout.strip())
    assert child_pid != os.getpid()
    assert batch.snapshot()["episodes"][0]["pid"] == child_pid
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: child_pid + 1)
        with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
            Batch(batch.root, batch.binding_sha).claim("p3-01")
    assert batch.snapshot()["cost"]["requests"] == 0


@pytest.mark.parametrize(
    "issued,expires", [(0, float("inf")), (0, float("nan")), (False, 100), (0, 129601), (1, 1)]
)
def test_authorization_is_finite_and_not_a_phase_extension(tmp_path, monkeypatch, issued, expires):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="FINITE_36_HOUR"):
        module.make_authorization(batch.root, issued=issued, expires=expires)
    assert batch.auth["phase_wall_seconds"] == {"P3": 1800, "P4": 7200}


def test_p3_worker_pid_cannot_be_reused_in_p4(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    pass_p3(batch, monkeypatch)
    batch.launch_once("P4")
    monkeypatch.setattr(module.os, "getpid", lambda: 90000000)
    with pytest.raises(ProviderStop, match="FRESH_CLIENT"):
        batch.claim("p4-01")


def test_deleted_launch_row_does_not_allow_second_launch(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once("P3")
    with batch.transaction() as db:
        db.execute("DELETE FROM launches WHERE stage='P3'")
        db.execute("DELETE FROM meta WHERE key='P3_deadline'")
    with pytest.raises(FileExistsError):
        batch.launch_once("P3")


def test_authorization_builder_does_not_expose_mutable_policy_constants(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    auth = module.make_authorization(batch.root, issued=time.time() - 1, expires=time.time() + 100)
    auth["caps"]["P4"] = 999
    auth["phase_wall_seconds"]["P4"] = 99999
    assert module.CAPS == {"P3": 16, "P4": 96}
    assert module.PHASE_SECONDS == {"P3": 1800, "P4": 7200}
    assert batch.authorize("P4")["caps"]["P4"] == 96
