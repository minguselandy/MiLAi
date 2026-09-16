"""Synthetic journal tests, not model evidence or production admission.

Only fixed input constants and the separate reference/raw auditor are substituted.
SQLite transactions, authorization, historical accounting, ordering and gates are real.
"""

import copy
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_boundary_audit as audit
import v0222_boundary_batch as module
from v02_local_provider import append_event, read_events
from v0220_evidence import read, save, seal, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0222_boundary_batch import Batch


def settled_events(key, session=None):
    return [
        {
            "event": "RESERVED",
            "request_id": key,
            "session": session or key,
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


def fixture(tmp_path, monkeypatch):
    histories = tuple(tmp_path / f"history-{i:02}.jsonl" for i in range(28))
    for p in histories:
        p.touch()
    for i in range(2):
        append_event(
            histories[0],
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
            histories[0],
            {
                "event": "SETTLED",
                "request_id": f"legacy-{i}",
                "input_tokens": 10,
                "output_tokens": 1,
            },
        )
    append_event(
        histories[1],
        {
            "event": "RESERVED",
            "request_id": "old-unknown",
            "session": "old",
            "prompt_tokens": 24188,
            "output_cap": 4096,
            "raw_upper_bound": 28284,
        },
    )
    for i, p in enumerate(histories[2:]):
        for event in settled_events(f"history-known-{i}"):
            append_event(p, event)
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", tuple((str(p), sha(p)) for p in histories))
    monkeypatch.setattr(module, "HISTORY_TOTALS", (29, 334, 28284))
    parent = tmp_path / "stopped-parent"
    parent.mkdir()
    parent_specs = [
        {"id": source, "root": root, "expected": {"action": "test", "value": i}}
        for i, (source, root) in enumerate(
            zip(module.SOURCE_EPISODES, module.ROOT_ORDER, strict=True)
        )
    ]
    save(parent / "manifest.json", {"contract": {"P3": parent_specs}})
    save(parent / "execution-binding.json", {"manifest.json": sha(parent / "manifest.json")})
    parent_binding = sha(parent / "execution-binding.json")
    save(
        parent / "P3-independent-review.json",
        {
            "status": "P3_FAILURE_EVIDENCE_AND_STOP_REVIEW_PASS",
            "binding_sha256": parent_binding,
            "terminal": {"permanent_batch_stop": module.PARENT_STOP, "episodes_snapshot": []},
            "files": {str(parent / "manifest.json"): sha(parent / "manifest.json")},
        },
    )
    with sqlite3.connect(parent / "batch.sqlite") as db:
        db.executescript(
            "CREATE TABLE meta(key TEXT,value TEXT);"
            "CREATE TABLE episodes(stage TEXT,status TEXT,ordinal INTEGER);"
            "CREATE TABLE events(seq INTEGER PRIMARY KEY,event TEXT);"
            "CREATE TABLE artifacts(path TEXT,sha256 TEXT,dependencies TEXT);"
        )
        db.executemany(
            "INSERT INTO meta VALUES (?,?)",
            [("binding", parent_binding), ("stop", module.PARENT_STOP)],
        )
        for p in histories[3:]:
            for event in read_events(p):
                db.execute("INSERT INTO events(event) VALUES (?)", (json.dumps(event),))
    monkeypatch.setattr(module, "PARENT_ROOT", parent)
    monkeypatch.setattr(module, "PARENT_BINDING", parent_binding)
    monkeypatch.setattr(module, "PARENT_P3_REVIEW_SHA", sha(parent / "P3-independent-review.json"))
    root = tmp_path / "new-boundary"
    monkeypatch.setattr(module, "ROOT", root)
    specs = []
    for cold in (1, 2):
        for p in parent_specs:
            for condition in ("B0", "B1") if cold == 1 else ("B1", "B0"):
                specs.append(
                    {
                        "id": f"r1-{len(specs) + 1:02}",
                        "stage": "R1",
                        "root": p["root"],
                        "cold": cold,
                        "condition": condition,
                        "source_episode": p["id"],
                        "expected": p["expected"],
                    }
                )
    seal(
        root,
        entries=[],
        inputs=list(histories),
        contract={
            "revision": module.REVISION,
            "episodes": specs,
            "historical_paths": [str(p) for p in histories],
            "http_identity": module.IDENTITY,
            "selected_decoder": "D11",
            "parent_binding": parent_binding,
            "parent_root": str(parent),
        },
    )
    save(
        root / "authorization.json",
        module.make_authorization(root, issued=time.time() - 1, expires=time.time() + 3600),
    )
    save(root / "authorization-source.json", module.authorization_source())
    save(
        root / "execution-binding.json",
        {
            name: sha(root / name)
            for name in ("manifest.json", "authorization.json", "authorization-source.json")
        },
    )
    # Reference compiler/raw audit have dedicated integration tests in the parent task.
    monkeypatch.setattr(audit, "validate_reference", lambda *args: None)
    monkeypatch.setattr(audit, "validate_preflight", lambda *args: None, raising=False)
    monkeypatch.setattr(audit, "audit_episode", mock_audit_episode)
    batch = Batch(root, sha(root / "execution-binding.json"))
    batch.initialize()
    return batch


def mock_audit_episode(batch, episode):
    """Explicit test stand-in; derives the bit from an immutable synthetic raw file."""
    directory = batch.root / "episodes" / episode
    observation = read(directory / "observation.json")
    return {
        **observation,
        "files": {
            str(p): sha(p)
            for p in directory.rglob("*")
            if p.is_file() and p.name != "independent-observation.json"
        },
    }


def gates(batch):
    refs, files = [], {}
    for spec in batch.plan["episodes"]:
        reference = {"episode": spec["id"], "hashes": {}}
        for kind in ("canonical", "wire", "output", "diff"):
            p = batch.root / "references" / spec["id"] / (kind + ".json")
            save(p, {"synthetic_only": kind})
            reference[kind] = str(p)
            reference["hashes"][kind] = sha(p)
            files[str(p)] = sha(p)
        source = module.PARENT_ROOT / "manifest.json"
        reference.update(source_canonical=str(source), source_canonical_sha256=sha(source))
        files[str(source)] = sha(source)
        refs.append(reference)
    p = batch.root / "references.json"
    save(p, {"references": refs, "files": files})
    batch.freeze_artifact("references", p)
    for name, status in (
        ("scope_review", "G_AUTH_SCOPE_REVIEW_PASS"),
        ("engineering_checks", "ENGINEERING_CHECKS_PASS"),
        ("preflight", "G_PREFLIGHT_PASS"),
    ):
        target = batch.root / (name + ".json")
        save(target, {"status": status, "files": {str(p): sha(p)}})
        batch.freeze_artifact(name, target, status)


def observe(batch, monkeypatch, index, exact):
    parent_pid = os.getpid()
    worker_pid = 90000000 + index
    spec = batch.plan["episodes"][index]
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: worker_pid)
        batch.claim(spec["id"])
        directory = batch.root / "episodes" / spec["id"]
        (directory / "provider").mkdir(parents=True)
        for event in settled_events(f"request-{index}", spec["id"]):
            batch.record(spec["id"], event)
            append_event(directory / "provider/provider-ledger-v2.jsonl", event)
        save(
            directory / "observation.json",
            {
                **{k: spec[k] for k in ("id", "root", "cold", "condition")},
                "exact_fidelity": exact,
                "status": "OBSERVED",
                "pid": worker_pid,
            },
        )
    assert os.getpid() == parent_pid
    return batch.finish(spec["id"])


def test_history_exact_28_and_unique_unknown(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    history = batch.auth["historical"]
    assert history["requests"] == 29 and history["known_raw_tokens"] == 334
    assert history["actual_total_raw_tokens"] is None
    assert history["reserved_raw_upper_bound"] == 28284
    assert len(history["unresolved_reservations"]) == 1
    assert batch.authorize("R1") == batch.auth


@pytest.mark.parametrize("variant", ["missing", "duplicate", "reordered", "central"])
def test_history_cannot_drop_duplicate_reorder_or_add_mirror(tmp_path, monkeypatch, variant):
    fixture(tmp_path, monkeypatch)
    paths = tuple(Path(p) for p, _ in module.HISTORICAL_SOURCES)
    paths = {
        "missing": paths[:-1],
        "duplicate": (*paths[:-1], paths[0]),
        "reordered": (paths[1], paths[0], *paths[2:]),
        "central": (*paths, tmp_path / "central.jsonl"),
    }[variant]
    with pytest.raises(ProviderStop):
        module.historical_usage_boundary(paths)


def test_even_rebound_new_history_unknown_cannot_be_whitelisted(tmp_path, monkeypatch):
    fixture(tmp_path, monkeypatch)
    paths = tuple(Path(p) for p, _ in module.HISTORICAL_SOURCES)
    append_event(paths[-1], settled_events("new-unknown")[0])
    monkeypatch.setattr(module, "HISTORICAL_SOURCES", tuple((str(p), sha(p)) for p in paths))
    with pytest.raises(ProviderStop, match="NO_NEW_HISTORICAL_UNKNOWN"):
        module.historical_usage_boundary(paths)


@pytest.mark.parametrize(
    "issued,expires",
    [(0, float("inf")), (0, float("nan")), (True, 100), (0, 36 * 3600 + 1), (1, 1)],
)
def test_finite_authorization_window(tmp_path, monkeypatch, issued, expires):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="FINITE_36_HOUR"):
        module.make_authorization(batch.root, issued=issued, expires=expires)


def test_old_batch_stop_cannot_be_removed(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(module.PARENT_ROOT / "batch.sqlite") as db:
        db.execute("DELETE FROM meta WHERE key='stop'")
    with pytest.raises(ProviderStop, match="PARENT_MUST_REMAIN"):
        batch.authorize("R1")


def test_old_review_dependency_drift_blocks_authorization(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with (module.PARENT_ROOT / "manifest.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ProviderStop, match="PARENT_EVIDENCE"):
        batch.authorize("R1")


def test_fixed_root_and_sqlite_deletion_never_reset_batch(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="ONE_FIXED"):
        Batch(tmp_path / "another", batch.binding_sha)
    batch.path.unlink()
    with pytest.raises(FileExistsError):
        batch.initialize()
    assert not batch.path.exists()
    with pytest.raises(sqlite3.OperationalError):
        batch.snapshot()


def test_missing_gates_and_relaunch_rejected(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    with pytest.raises(ProviderStop, match="ARTIFACT"):
        batch.launch_once()
    gates(batch)
    batch.launch_once()
    with pytest.raises(ProviderStop, match="ALREADY_LAUNCHED"):
        batch.launch_once()
    with pytest.raises(ProviderStop, match="SEPARATE_COLD"):
        batch.claim("r1-01")


def test_artifact_name_is_append_only_and_dependencies_checked_on_admit(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    with pytest.raises(ProviderStop, match="ALREADY_FROZEN"):
        batch.freeze_artifact("preflight", batch.root / "preflight.json")
    batch.launch_once()
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 901)
        batch.claim("r1-01")
        p = Path(batch.references()[0]["wire"])
        with p.open("a") as stream:
            stream.write(" ")
        with pytest.raises(ProviderStop, match="DEPENDENCY_DRIFT"):
            batch.admit("r1-01")


def test_known_content_failure_is_observed_and_second_pass_gate_is_mandatory(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    for i in range(8):
        observation = observe(batch, monkeypatch, i, i % 2 == 1)
        assert observation["status"] == "OBSERVED"
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 908)
        with pytest.raises(ProviderStop, match="ARTIFACT"):
            batch.claim("r1-09")
    first = batch.decision()
    assert first["repeat_required"] is True
    p = batch.root / "firstpass-decision.json"
    save(p, first)
    batch.set_decision(p)
    for i in range(8, 16):
        observe(batch, monkeypatch, i, i % 2 == 0)
    result = batch.decision(final=True)
    assert result["status"] == "INTENT_BOUNDARY_SIGNAL"
    assert result["selected_condition"] == "B1"
    save(batch.root / "final-decision.json", result)
    batch.set_decision(batch.root / "final-decision.json", final=True)
    assert batch.snapshot()["cost"]["requests"] == 16
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 999)
        with pytest.raises(ProviderStop, match="NO_RESTART"):
            batch.claim("r1-01")


def test_no_signal_cannot_start_conditional_positions(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    for i in range(8):
        observe(batch, monkeypatch, i, False)
    p = batch.root / "firstpass-decision.json"
    save(p, batch.decision())
    batch.set_decision(p)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 999)
        with pytest.raises(ProviderStop, match="SECOND_PASS_NOT_TRIGGERED"):
            batch.claim("r1-09")


def test_arbitrary_pass_bit_and_incomplete_decision_rejected(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    p = batch.root / "forged.json"
    save(p, {"status": "OBSERVED", "exact_fidelity": True})
    with pytest.raises(ProviderStop, match="ONLY_INDEPENDENT"):
        batch.freeze_artifact("r1-01_observation", p)
    with pytest.raises(ProviderStop, match="COMPLETE_OBSERVED"):
        batch.set_decision(p)


def test_unknown_consumes_attempt_and_stops_reconstructed_coordinator(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    events = settled_events("unknown", "r1-01")[:2]
    events.append({"event": "USAGE_UNKNOWN", "request_id": "unknown", "classification": "HTTP_500"})
    ledger = batch.root / "episodes/r1-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in events:
        batch.record("r1-01", event)
        append_event(ledger, event)
    reconstructed = Batch(batch.root, batch.binding_sha)
    assert reconstructed.snapshot()["cost"]["requests"] == 1
    assert reconstructed.snapshot()["stop"] == "USAGE_UNKNOWN"
    with pytest.raises(ProviderStop, match="STOPPED"):
        reconstructed.admit("r1-01")


def test_unsettled_crash_central_mirror_drift_and_cap_are_not_reset(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    reservation = settled_events("reserved", "r1-01")[0]
    bad = copy.deepcopy(reservation)
    bad["output_cap"] = 4096.0
    with pytest.raises(ProviderStop, match="FROZEN_REQUEST_CAP"):
        batch.record("r1-01", bad)
    batch.record("r1-01", reservation)
    with pytest.raises(ProviderStop, match="UNKNOWN_OR_VIOLATION"):
        batch.admit("r1-01")
    assert batch.snapshot()["cost"]["requests"] == 1


def test_single_writer_order_new_pid_and_parent_finish_required(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 901)
        with pytest.raises(ProviderStop, match="OUT_OF_ORDER"):
            batch.claim("r1-02")
    observe(batch, monkeypatch, 0, False)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 90000000)
        with pytest.raises(ProviderStop, match="FRESH_CLIENT"):
            batch.claim("r1-02")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 902)
        batch.claim("r1-02")
        with pytest.raises(ProviderStop, match="SINGLE_ACTIVE"):
            batch.claim("r1-03")


def test_phase_and_episode_deadlines_are_finite(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    start = time.time()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    row = batch.admit("r1-01")
    assert 299 <= row["deadline"] - start <= 301
    monkeypatch.setattr(module.time, "time", lambda: start + 301)
    with pytest.raises(ProviderStop, match="EPISODE_DEADLINE"):
        batch.admit("r1-01")


def test_observation_raw_changes_and_forged_decision_fail(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    for i in range(8):
        observe(batch, monkeypatch, i, False)
    p = batch.root / "forged-decision.json"
    save(p, {"status": "REPEAT_REQUIRED", "repeat_required": True})
    with pytest.raises(ProviderStop, match="NOT_DERIVED"):
        batch.set_decision(p)
    raw = batch.root / "episodes/r1-01/observation.json"
    with raw.open("a") as stream:
        stream.write(" ")
    with pytest.raises(ProviderStop, match="DEPENDENCY_DRIFT"):
        batch.decision()


def test_one_request_per_position_and_central_mirror_match(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    ledger = batch.root / "episodes/r1-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in settled_events("first", "r1-01"):
        batch.record("r1-01", event)
        append_event(ledger, event)
    with pytest.raises(ProviderStop, match="BATCH_COUNT"):
        batch.record("r1-01", settled_events("second", "r1-01")[0])
    assert usage_state(read_events(ledger))["requests"] == 1
    ledger.unlink()
    with pytest.raises(ProviderStop, match="DIVERGED"):
        batch.admit("r1-01")


def test_inflight_http_admission_only_own_unsent_reservation(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    with pytest.raises(ProviderStop, match="EXACT_OWN_UNSENT"):
        batch.http_admit("r1-01", inflight=True)
    ledger = batch.root / "episodes/r1-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    events = settled_events("one", "r1-01")
    for event in events[:2]:
        batch.record("r1-01", event)
        append_event(ledger, event)
        assert batch.http_admit("r1-01", inflight=True)["pid"] == 901
    with pytest.raises(ProviderStop, match="UNKNOWN_OR_VIOLATION"):
        batch.http_admit("r1-01")
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "getpid", lambda: 902)
        with pytest.raises(ProviderStop, match="NOT_OWNED"):
            batch.http_admit("r1-01", inflight=True)
    for event in events[2:]:
        batch.record("r1-01", event)
        append_event(ledger, event)
    assert batch.http_admit("r1-01")["pid"] == 901
    with pytest.raises(ProviderStop, match="EXACT_OWN_UNSENT"):
        batch.http_admit("r1-01", inflight=True)


def test_inflight_http_cannot_ignore_new_stop_or_expiration(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    deadline = batch.admit("r1-01")["deadline"]
    ledger = batch.root / "episodes/r1-01/provider/provider-ledger-v2.jsonl"
    ledger.parent.mkdir(parents=True)
    for event in settled_events("one", "r1-01")[:2]:
        batch.record("r1-01", event)
        append_event(ledger, event)
    with monkeypatch.context() as patch:
        patch.setattr(module.time, "time", lambda: deadline + 1)
        with pytest.raises(ProviderStop, match="EPISODE_DEADLINE"):
            batch.http_admit("r1-01", inflight=True)
    batch.stop("EXPLICIT_STOP")
    with pytest.raises(ProviderStop, match="STOPPED"):
        batch.http_admit("r1-01", inflight=True)
    assert batch.snapshot()["cost"]["actual_total_raw_tokens"] is None


def test_worker_cannot_finish_own_observation(tmp_path, monkeypatch):
    batch = fixture(tmp_path, monkeypatch)
    gates(batch)
    batch.launch_once()
    monkeypatch.setattr(module.os, "getpid", lambda: 901)
    batch.claim("r1-01")
    with pytest.raises(ProviderStop, match="NO_OWNED_LIVE"):
        batch.finish("r1-01")


@pytest.mark.parametrize("field", ["plan", "auth"])
def test_in_memory_scope_cannot_override_sealed_scope(tmp_path, monkeypatch, field):
    batch = fixture(tmp_path, monkeypatch)
    if field == "auth":
        batch.auth["caps"]["R1"] = 999
    else:
        batch.plan["episodes"][0]["expected"] = {"replacement": True}
    with pytest.raises(ProviderStop, match="IN_MEMORY"):
        batch.authorize("R1")
