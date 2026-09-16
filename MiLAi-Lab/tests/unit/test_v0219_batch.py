"""Synthetic offline runner/auditor checks: no real models, Product or cold-chain claim."""

import copy
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import audit_v0219 as audit
import run_v0212_horizon as launcher
import run_v0219 as batch
import v0218_host as common
import v0219_host as host
from v0213_provider import MODEL, Provider
from v0218_memory import content_digest
from v0218_world import World, digest


def test_ordered_first_four_and_no_outcome_selection():
    roots = ["root-a", "root-b", "root-c", "root-d"]
    rows = batch.episode_plan(roots)
    assert len(rows) == 28
    assert [r["root"] for r in rows if r["phase"] == "A"] == roots
    for key in roots:
        selected = [r for r in rows if r["root"] == key]
        assert selected[0]["phase"] == "A"
        assert {(r["variant"], r["arm"]) for r in selected[1:]} == {
            (v, a) for v in batch.VARIANTS for a in batch.ARMS
        }
    with pytest.raises(ValueError):
        batch.episode_plan(["duplicate", "duplicate"])


@pytest.mark.parametrize(
    "status,reason,allowed",
    [
        ("FINISHED", None, True),
        ("GENERATION_CAP_REACHED", None, True),
        ("EPISODE_DEADLINE", None, True),
        ("INFRASTRUCTURE_OR_PROTOCOL_STOP", "MODEL_CONTEXT_LIMIT", True),
        ("INFRASTRUCTURE_OR_PROTOCOL_STOP", "WALL_CLOCK_LIMIT", True),
        ("INFRASTRUCTURE_OR_PROTOCOL_STOP", "PUBLIC_NOTE_COMMIT_NOT_VERIFIED", False),
        ("INFRASTRUCTURE_OR_PROTOCOL_STOP", "USAGE_UNKNOWN_RESERVATION_RETAINED", False),
    ],
)
def test_stop_classification_and_no_unknown_retry(status, reason, allowed):
    outcome = {"status": status, "reason": reason}
    assert batch.continuation_allowed(outcome, {"pending": 0, "violations": 0}) is allowed
    assert not batch.continuation_allowed(outcome, {"pending": 1, "violations": 0})
    assert not batch.continuation_allowed(outcome, {"pending": 0, "violations": 1})


def test_prefetch_rejects_partial_order_hash_and_content(tmp_path):
    w = World.create(
        tmp_path / "world.sqlite",
        "scope",
        {"task": {}, "policy": {"all": "rules"}, "current": {"all": "facts"}, "objects": ["x"]},
    )
    cfg = {
        "arm": "N0",
        "phase": "B",
        "policy_system": host.system_for("N0"),
        "public_prefetch": host.PUBLIC_PREFETCH,
        "note_commit": None,
    }
    with host.configured(cfg):
        receipt = common.prefetch(w)
    assert len(audit.audit_prefetch(receipt, w.snapshot())) == 5
    for mutation in ("missing", "order", "content", "version", "scope"):
        bad = copy.deepcopy(receipt)
        if mutation == "missing":
            bad["reads"].pop()
        elif mutation == "order":
            bad["reads"].reverse()
        elif mutation == "content":
            bad["reads"][0]["response"]["content"] = {"partial": "facts"}
        elif mutation == "version":
            bad["reads"][0]["response"]["version"] += 1
        else:
            bad["scope"] = "other"
        with pytest.raises(AssertionError):
            audit.audit_prefetch(bad, w.snapshot())


@pytest.fixture(
    params=[(True, False), (False, False), (True, True)],
    ids=["natural-note-fixture", "no-write-fixture", "resource-stop-after-note"],
)
def offline_wave(tmp_path, monkeypatch, request):
    has_note, resource_stop = request.param
    root = tmp_path / "wave"
    case = root / "cases/synthetic"
    public = {
        "task": {"request": "Synthetic full-field work", "fixture_arm": "unused"},
        "policy": {"rules": "No real behavior claim"},
        "current": {"value": 0},
        "objects": ["item"],
    }
    batch.save(case / "public-initial.json", public)
    batch.save(case / "public-changed.json", {"value": 1})
    schema = {
        "type": "object",
        "properties": {"object_id": {"const": "item"}, "value": {"type": "integer"}},
        "required": ["object_id", "value"],
        "additionalProperties": False,
    }
    for name, value in (("initial", 0), ("changed", 1)):
        oracle = {
            "objects": ["item"],
            "public_schemas": {"item": schema},
            "postconditions": {"item": {"properties": {"value": {"const": value}}}},
            "semantic_paths": [],
            "pending_schema": {"type": "object"},
        }
        batch.save(case / ("oracle-" + name + ".json"), oracle)
    manifest = {
        "episodes": batch.episode_plan(["synthetic"]),
        "generation_cap": 16,
        "seconds_per_episode": 900,
        "max_requests": 112,
        "batch_seconds": 7230,
        "policy_systems": {a: host.system_for(a) for a in ("A", *batch.ARMS)},
        "public_prefetch": host.PUBLIC_PREFETCH,
        "roots": [{"root": "synthetic", "family": "synthetic_fixture"}],
    }
    batch.save(root / "manifest.json", manifest)
    batch.save(root / "manifest-sha256.json", {"sha256": batch.sha(root / "manifest.json")})
    monkeypatch.setattr(batch, "validate", lambda _: manifest)
    monkeypatch.setattr(audit, "validate", lambda _: manifest)
    notes = {}

    @contextmanager
    def product(path, installed):
        path.mkdir()
        try:
            yield path
        finally:
            batch.save(
                path / "cleanup.json",
                {"api_stopped": True, "compose_stop_returncode": 0, "fixture_only": True},
            )

    @contextmanager
    def observer(owned, directory, *, task, principal, project):
        assert task == principal == project
        directory.mkdir(parents=True, exist_ok=True)

        def call(name, args):
            if name == "milai_memory_list":
                return {"items": [] if task not in notes else [notes[task]]}
            if name == "milai_memory_save":
                previous = notes.get(task)
                if previous:
                    assert args["options"]["expected_version"] == previous["version"]
                row = {
                    "memory_id": task + "-note",
                    "version": 1 if not previous else previous["version"] + 1,
                    "content_digest": content_digest(args["content"]),
                    "content": args["content"],
                    "status": "ACTIVE",
                    "authority": "HOST_WORKING",
                }
                notes[task] = row
                return {k: v for k, v in row.items() if k != "content"} | {
                    "commit_status": "COMMITTED",
                    "durable": True,
                }
            row = notes[task]
            assert name == "milai_memory_read" and args["target"]["version"] == row["version"]
            assert args["target"]["id"] == row["memory_id"]
            return {**row, "offset": 0, "next_offset": None}

        yield call

    class OfflineProvider(Provider):
        def generate(self, session, body):
            if resource_stop and session.endswith("-A") and self.turn == 4:
                raise ValueError("MODEL_CONTEXT_LIMIT")
            return super().generate(session, body)

        def __init__(self, directory, **kwargs):
            self.turn = 0

            def response(request):
                if request.url.path == "/v1/models":
                    return httpx.Response(
                        200, json={"data": [{"id": MODEL, "max_model_len": 65536}]}
                    )
                if request.url.path == "/tokenize":
                    return httpx.Response(200, json={"count": 123})
                body = json.loads(request.content)
                eid = directory.name
                initial = json.loads(body["messages"][1]["content"])
                version = json.loads(body["messages"][-1]["content"])["current_world_version"]
                if eid.endswith("-A"):
                    operations = [
                        ("read", {"resource": "current"}),
                        ("put_record", {"object_id": "item", "data": {"value": 0}}),
                        (
                            "request_clarification",
                            {"object_id": "item", "data": {"question": "Unresolved fixture?"}},
                        ),
                        ("save_note", {"note": "Ordinary fixture note; value0, question pending."}),
                        ("finish", {"message": "Fixture handoff"}),
                    ]
                    if not has_note:
                        operations = [op for op in operations if op[0] != "save_note"]
                else:
                    operations = []
                    if not eid.endswith("-N0"):
                        assert (initial["saved_working_note"] is not None) is has_note
                        operations.append(
                            ("save_note", {"note": "Fixture review of current sources."})
                        )
                    else:
                        assert initial["saved_working_note"] is None
                    if "-changed-" in eid:
                        operations.append(
                            ("put_record", {"object_id": "item", "data": {"value": 1}})
                        )
                    operations.append(("finish", {"message": "Fixture done"}))
                action, args = operations[self.turn]
                self.turn += 1
                if action in {"put_record", "request_clarification"}:
                    args["expected_version"] = version
                raw = json.dumps({"action": action, "arguments_json": json.dumps(args)})
                return httpx.Response(
                    200,
                    json={
                        "choices": [{"finish_reason": "stop", "message": {"content": raw}}],
                        "usage": {
                            "prompt_tokens": 123,
                            "completion_tokens": 10,
                            "total_tokens": 133,
                        },
                    },
                )

            super().__init__(directory, transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(launcher, "product", product)
    monkeypatch.setattr(batch, "observer", observer)
    monkeypatch.setattr(common, "observer", observer)
    monkeypatch.setattr(common, "Provider", OfflineProvider)
    calls = []

    def cold(config, path, remaining):
        batch.save(path, config)
        started = time.time()
        result = host.run(path)
        result["pid"] = 1000 + len(calls)
        calls.append(config)
        batch.save(Path(config["output"]) / "result.json", result, exclusive=False)
        exited = {
            "pid": result["pid"],
            "returncode": 0,
            "started_unix": started,
            "exited_unix": time.time(),
            "wait_reaped": True,
            "timeout": False,
            "exit_verified_before_next_episode": True,
            "synthetic_fixture_not_real_exit": True,
        }
        batch.save(path.with_suffix(".exit.json"), exited)
        return {**result, "exit_receipt": exited, "exit_verified_before_next_episode": True}

    monkeypatch.setattr(batch, "cold", cold)
    result = batch.run(root, tmp_path / "unused-installed")
    assert result["status"] == "F2_EXECUTED_REQUIRES_CHAIN_AND_SEMANTIC_AUDIT", result
    return root, result


def test_full_synthetic_wave_and_audit(offline_wave):
    root, result = offline_wave
    assert len(result["rows"]) == 7
    if result["rows"][0]["status"] == "INFRASTRUCTURE_OR_PROTOCOL_STOP":
        assert result["rows"][0]["handoff_recovered_by_public_read_only"]
        assert (root / "episodes/synthetic-A/handoff-recovery/receipt.json").exists()
    summary = audit.audit(root)
    assert summary["complete_wave"] and summary["A_attempts"] == 1
    assert summary["B_attempts"] == 6
    assert summary["B_both_presented"] == (0 if summary["A_NO_WRITE"] else 4)
    assert summary["harness_prefetch_reads"] == 30
    assert summary["cost"]["pending"] == summary["cost"]["violations"] == 0
    for arm in batch.ARMS:
        # Stable still has A's unreviewed pending question. Do not silently label it PASS.
        assert summary["B_by_arm_unreviewed"][arm] == {"PASS": 1, "UNKNOWN": 1}
    assert not summary["goal_complete"]
    with pytest.raises(ValueError, match="NO_AUTOMATIC_RESTART"):
        batch.run(root, root / "unused")


@pytest.mark.parametrize("tamper", ["payload", "prefetch", "copy", "world", "commit"])
def test_audit_rejects_tampered_evidence(offline_wave, tamper):
    root, result = offline_wave
    target = next(r for r in result["rows"] if r["arm"] == "N1" and r["variant"] == "changed")
    eid = target["id"]
    directory = root / "episodes" / eid
    if tamper == "payload":
        rid = target["actions"][0]["request_id"]
        path = directory / (rid + "-request.json")
        data = batch.read(path)
        data["messages"].pop(6)
    elif tamper == "prefetch":
        path = directory / "public-prefetch.json"
        data = batch.read(path)
        data["reads"].pop()
    elif tamper == "copy":
        path = root / "branch-audits" / eid / "note-copy.json"
        data = batch.read(path) if path.exists() else {}
        data["content_rewritten"] = True
    elif tamper == "world":
        path = directory / "final-world.json"
        data = batch.read(path)
        data["records"]["item"]["value"] = 99
    else:
        path = directory / "memory-calls.json"
        data = batch.read(path)
        data["calls"][0]["response"]["version"] += 1
    batch.save(path, data, exclusive=False)
    with pytest.raises((AssertionError, ValueError)):
        audit.audit(root)


def test_branch_reconstruction_preserves_full_a_without_mutation(tmp_path):
    public = {"task": {}, "policy": {}, "current": {"value": 0}, "objects": ["x"]}
    a = World.create(tmp_path / "a.sqlite", "a", public)
    a.act(
        operation_id="a", expected_version=0, action="put_record", object_id="x", data={"value": 0}
    )
    before = a.snapshot()
    stable = a.clone(tmp_path / "s.sqlite", "s")
    changed = a.clone(tmp_path / "c.sqlite", "c")
    changed.publish(event_id="source-grounded-changed", current={"value": 1})
    assert audit.expected_branch(before, "s", None) == stable.snapshot()
    assert audit.expected_branch(before, "c", {"value": 1}) == changed.snapshot()
    assert a.snapshot() == before and digest(a.snapshot()) == digest(before)
