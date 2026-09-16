"""Terminal wrapper controls plus original-auditor Mock integration, no admission."""

import copy
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_presentation_terminal_v2 as module
import v0222_presentation_transport as transport_module
from v0220_evidence import save, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import encoded


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("TERMINAL_TEST_MUST_NOT_USE_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(
        transport_module, "historical_usage_presentation", lambda _: {"sources": []}
    )


def events_for(episode, count=1):
    events = []
    for i in range(count):
        key = f"{episode}-{i}"
        events.extend(
            [
                {
                    "event": "RESERVED",
                    "request_id": key,
                    "session": episode,
                    "prompt_tokens": 10,
                    "output_cap": 4096,
                    "raw_upper_bound": 4106,
                },
                {"event": "DISPATCH_STARTED", "request_id": key},
                {"event": "RESPONSE_RECEIVED", "request_id": key},
                {
                    "event": "USAGE_KNOWN",
                    "request_id": key,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                },
            ]
        )
    return events


def write_ledger(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(encoded(e) + "\n" for e in events))


def controls(batch, *, worker=8, parent=7):
    episode, stage = batch.episode, batch.spec(batch.episode)["stage"]
    batch.binding_sha = "a" * 64
    batch.auth["expires_unix"] = 9000.0
    batch.claim_marker_path = lambda name: batch.root / "claims" / (name + ".json")
    claim = {"episode": episode, "pid": worker, "started": 100.0, "deadline": 400.0}
    launch = {"stage": stage, "pid": parent, "started": 90.0}
    row = {
        "id": episode,
        "stage": stage,
        "ordinal": 0,
        "cap": 1 if stage == "P3" else 4,
        "status": "RUNNING",
        "pid": worker,
        "deadline": 400.0,
    }
    save(batch.claim_marker_path(episode), {**claim, "binding_sha256": batch.binding_sha})
    save(
        batch.root / ("live-launch-" + stage + ".json"),
        {
            "stage": stage,
            "pid": parent,
            "unix": 90.0,
            "binding_sha256": batch.binding_sha,
        },
    )
    save(
        batch.root / "exits" / (episode + ".json"),
        {
            "pid": worker,
            "parent_pid": parent,
            "returncode": 0,
            "timed_out": False,
            "seconds": 20.0,
            "stdout": "",
            "stderr": "",
        },
    )
    return {"episode_row": row, "claim_row": claim, "launch_row": launch}


def synthetic(tmp_path, monkeypatch, *, stage="P3", count=1):
    """Only old audit is stubbed here; separate tests below run the real auditor."""
    root = tmp_path / "batch"
    spec = {"id": "synthetic-01", "stage": stage}
    batch = SimpleNamespace(root=root, episode=spec["id"], plan={}, auth={}, value=spec)
    batch.spec = lambda _: copy.deepcopy(batch.value)
    kwargs = controls(batch)
    directory = root / "episodes" / batch.episode
    events = events_for(batch.episode, count)
    write_ledger(directory / "provider/provider-ledger-v2.jsonl", events)
    save(directory / "worker-result.json", {"pid": 8})
    if stage == "P4":
        (root / "worlds").mkdir()
        (root / "worlds" / (batch.episode + ".sqlite")).write_bytes(b"SYNTHETIC_STUB_WORLD")

    def old_audit(_batch, _episode):
        paths = [
            p
            for p in directory.rglob("*")
            if p.is_file()
            and p.suffix in {".json", ".jsonl"}
            and p.name != "independent-audit.json"
        ]
        if stage == "P4":
            paths.append(root / "worlds" / (batch.episode + ".sqlite"))
        return {
            "id": batch.episode,
            "stage": stage,
            "status": "PASS",
            "pid": 8,
            "cost": usage_state(events),
            "checks": {"STUB_ONLY": True},
            "files": {str(p): sha(p) for p in paths},
        }

    monkeypatch.setattr(module, "audit_episode", old_audit)
    kwargs["events"] = events
    return batch, kwargs, old_audit


def run(batch, kwargs):
    return module.audit_claimed_episode(batch, batch.episode, **kwargs)


def mutate_json(path, callback):
    value = json.loads(path.read_text())
    callback(value)
    path.write_text(encoded(value))


def test_only_three_external_pins_added_and_arguments_unchanged(tmp_path, monkeypatch):
    batch, kwargs, old = synthetic(tmp_path, monkeypatch)
    before = copy.deepcopy(kwargs)
    expected = old(None, None)
    result = run(batch, kwargs)
    assert {k: v for k, v in result.items() if k != "files"} == {
        k: v for k, v in expected.items() if k != "files"
    }
    assert set(result["files"]) - set(expected["files"]) == {
        str(batch.claim_marker_path(batch.episode)),
        str(batch.root / "live-launch-P3.json"),
        str(batch.root / "exits" / (batch.episode + ".json")),
    }
    assert kwargs == before
    assert not (batch.root / "batch.sqlite").exists()
    assert not (batch.root / "episodes" / batch.episode / "independent-audit.json").exists()


def test_past_pass_is_reauditable_without_wall_clock_admission(tmp_path, monkeypatch):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    kwargs["episode_row"]["status"] = "PASS"
    save(batch.root / "episodes" / batch.episode / "independent-audit.json", {"old": True})
    assert run(batch, kwargs)["status"] == "PASS"


@pytest.mark.parametrize("state", ["FAIL", "PENDING", "OBSERVED", None])
def test_failed_or_unclaimed_episode_never_passes(tmp_path, monkeypatch, state):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    kwargs["episode_row"]["status"] = state
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", 7),
        ("pid", 8.0),
        ("pid", True),
        ("parent_pid", 9),
        ("parent_pid", 7.0),
        ("returncode", False),
        ("returncode", 0.0),
        ("returncode", -9),
        ("timed_out", True),
        ("timed_out", 0),
        ("seconds", True),
        ("seconds", -1),
        ("seconds", 300.01),
        ("seconds", "20"),
    ],
)
def test_bad_exit_never_reaches_original_auditor(tmp_path, monkeypatch, field, value):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    mutate_json(
        batch.root / "exits" / (batch.episode + ".json"), lambda v: v.update({field: value})
    )
    monkeypatch.setattr(
        module, "audit_episode", lambda *_: pytest.fail("invalid exit reached audit")
    )
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


@pytest.mark.parametrize("seconds", [0, 0.0, 300, 300.0])
def test_elapsed_closed_interval(tmp_path, monkeypatch, seconds):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    mutate_json(
        batch.root / "exits" / (batch.episode + ".json"), lambda v: v.update(seconds=seconds)
    )
    assert run(batch, kwargs)["status"] == "PASS"


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_exit_seconds_are_rejected_from_raw_json(tmp_path, monkeypatch, seconds):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    path = batch.root / "exits" / (batch.episode + ".json")
    value = json.loads(path.read_text())
    value["seconds"] = seconds
    path.write_text(json.dumps(value))  # Deliberately invalid nonfinite JSON evidence.
    with pytest.raises(ValueError):
        run(batch, kwargs)


def test_nested_independent_audit_namesake_cannot_hide_json(tmp_path, monkeypatch):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    save(batch.root / "episodes" / batch.episode / "nested/independent-audit.json", {})
    with pytest.raises(ProviderStop, match="COMPLETE_ORIGINAL_EPISODE_EVIDENCE_SET"):
        run(batch, kwargs)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("claim_row", "pid", 8.0),
        ("launch_row", "pid", 7.0),
        ("episode_row", "pid", True),
        ("episode_row", "cap", True),
        ("episode_row", "ordinal", 0.0),
        ("episode_row", "id", "other"),
        ("episode_row", "stage", "P4"),
        ("episode_row", "deadline", 401.0),
        ("claim_row", "started", 80.0),
        ("claim_row", "deadline", 401.0),
        ("claim_row", "deadline", True),
        ("launch_row", "stage", "P4"),
    ],
)
def test_exact_claim_rows_and_deadline_derivation(tmp_path, monkeypatch, target, field, value):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    kwargs[target][field] = value
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


@pytest.mark.parametrize("marker", ["claim", "launch"])
@pytest.mark.parametrize("change", ["binding", "pid", "extra", "duplicate", "nan", "utf8"])
def test_marker_raw_and_exact_content(tmp_path, monkeypatch, marker, change):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    path = (
        batch.claim_marker_path(batch.episode)
        if marker == "claim"
        else batch.root / "live-launch-P3.json"
    )
    if change == "duplicate":
        path.write_text(path.read_text().rstrip()[:-1] + ', "pid":8}')
    elif change == "nan":
        path.write_text('{"pid":NaN}')
    elif change == "utf8":
        path.write_bytes(b"\xff")
    else:
        mutate_json(
            path,
            lambda v: v.update(
                {{"binding": "binding_sha256", "pid": "pid", "extra": "extra"}[change]: "changed"}
            ),
        )
    with pytest.raises((ProviderStop, ValueError)):
        run(batch, kwargs)


def test_claim_cannot_be_hidden_inside_episode(tmp_path, monkeypatch):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    batch.claim_marker_path = lambda _: batch.root / "episodes" / batch.episode / "claim.json"
    with pytest.raises(ProviderStop, match="EXTERNAL_CLAIM"):
        run(batch, kwargs)


@pytest.mark.parametrize("change", ["missing", "reordered", "usage", "foreign_session", "unknown"])
def test_complete_central_order_and_usage_match(tmp_path, monkeypatch, change):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    events = copy.deepcopy(kwargs["events"])
    if change == "missing":
        events.pop()
    elif change == "reordered":
        events[1], events[2] = events[2], events[1]
    elif change == "usage":
        events[-1]["usage"] = {"prompt_tokens": 10, "completion_tokens": 11, "total_tokens": 21}
    elif change == "foreign_session":
        events[0]["session"] = "another"
    else:
        events[-1] = {"event": "USAGE_UNKNOWN", "request_id": events[0]["request_id"]}
    kwargs["events"] = events
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


def test_whole_batch_events_select_only_owned_request_ids(tmp_path, monkeypatch):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch)
    kwargs["events"] = events_for("previous") + kwargs["events"]
    assert run(batch, kwargs)["cost"]["requests"] == 1


@pytest.mark.parametrize(
    "stage,count,accepted",
    [
        ("P3", 1, True),
        ("P3", 2, False),
        ("P4", 2, False),
        ("P4", 3, True),
        ("P4", 4, True),
        ("P4", 5, False),
    ],
)
def test_request_count_boundaries(tmp_path, monkeypatch, stage, count, accepted):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch, stage=stage, count=count)
    if accepted:
        assert run(batch, kwargs)["cost"]["requests"] == count
    else:
        with pytest.raises(ProviderStop):
            run(batch, kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "FAIL"),
        ("pid", 8.0),
        ("pid", True),
        ("pid", 99),
        ("id", "another"),
        ("stage", "P4"),
        ("cost", {}),
        ("files", {}),
    ],
)
def test_original_audit_result_cannot_override_parent_facts(tmp_path, monkeypatch, field, value):
    batch, kwargs, old = synthetic(tmp_path, monkeypatch)

    def changed(*args):
        result = old(*args)
        result[field] = value
        return result

    monkeypatch.setattr(module, "audit_episode", changed)
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


@pytest.mark.parametrize(
    "change", ["append", "delete", "rewrite", "claim", "exit", "control", "world"]
)
def test_evidence_change_during_old_audit_fails_closed(tmp_path, monkeypatch, change):
    batch, kwargs, old = synthetic(tmp_path, monkeypatch, stage="P4", count=3)
    directory = batch.root / "episodes" / batch.episode

    def changed(*args):
        result = old(*args)
        if change == "append":
            save(directory / "hidden.json", {"extra": True})
        elif change == "delete":
            (directory / "worker-result.json").unlink()
        elif change == "rewrite":
            (directory / "worker-result.json").write_text("{}")
        elif change == "claim":
            batch.claim_marker_path(batch.episode).write_text("{}")
        elif change == "exit":
            (batch.root / "exits" / (batch.episode + ".json")).write_text("{}")
        elif change == "control":
            batch.value["extra"] = True
        else:
            (batch.root / "worlds" / (batch.episode + ".sqlite")).write_bytes(b"changed")
        return result

    monkeypatch.setattr(module, "audit_episode", changed)
    with pytest.raises(ProviderStop):
        run(batch, kwargs)


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_unbound_world_sidecars_are_not_hidden(tmp_path, monkeypatch, suffix):
    batch, kwargs, _ = synthetic(tmp_path, monkeypatch, stage="P4", count=3)
    (batch.root / "worlds" / (batch.episode + ".sqlite" + suffix)).write_bytes(b"unbound")
    with pytest.raises(ProviderStop, match="SIDECARS"):
        run(batch, kwargs)


@pytest.mark.parametrize(
    "stage,variant,writes",
    [
        ("P3", "full", 1),
        ("P3", "finish", 1),
        ("P4", "full", 1),
        ("P4", "full", 2),
    ],
)
def test_original_auditor_complete_mock_source_and_world(
    tmp_path, monkeypatch, stage, variant, writes
):
    # Only model HTTP is mocked by these old fixtures. Do not stub audit_episode.
    from test_v0222_presentation_audit import execute_mock, prepared

    batch, _ = prepared(tmp_path, monkeypatch, stage, variant=variant, writes=writes)
    execute_mock(batch, legal_finish=variant == "finish")
    kwargs = controls(batch, worker=os.getpid(), parent=os.getpid() + 100000)
    # ExecuteMock persisted this exact synthetic history before controls added expiry.
    kwargs["events"] = batch.events
    before = {str(p): sha(p) for p in (batch.root / "episodes").rglob("*") if p.is_file()}
    result = run(batch, kwargs)
    assert result["status"] == "PASS"
    assert result["cost"]["requests"] == (1 if stage == "P3" else writes + 2)
    assert all(sha(Path(p)) == h for p, h in result["files"].items())
    assert before == {str(p): sha(p) for p in (batch.root / "episodes").rglob("*") if p.is_file()}
    if stage == "P4":
        assert str(batch.root / "worlds" / (batch.episode + ".sqlite")) in result["files"]
