"""Synthetic history/FSM tests. No HTTP, real corpus or coordinator mutation."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0222_scoped_history as module
from v0220_provider_hardened import historical_usage, usage_state
from v0222_admission_read_scope import AdmissionReadError, AdmissionReadScope
from v0222_scoped_history import (
    historical_usage_from_pinned,
    presentation_history,
)


def reserved(key, prompt=10, cap=4):
    return {
        "event": "RESERVED",
        "request_id": key,
        "session": "synthetic-session",
        "prompt_tokens": prompt,
        "output_cap": cap,
        "raw_upper_bound": prompt + cap,
        "payload_sha256": "a" * 64,
        "cumulative_raw_cap": None,
    }


def legacy(key, prompt=10, output=1):
    return [
        reserved(key, prompt, max(output, 4)),
        {"event": "SETTLED", "request_id": key, "input_tokens": prompt, "output_tokens": output},
    ]


def v2(key, prompt=10, output=1):
    return [
        reserved(key, prompt, max(output, 4)),
        {"event": "DISPATCH_STARTED", "request_id": key},
        {"event": "RESPONSE_RECEIVED", "request_id": key},
        {
            "event": "USAGE_KNOWN",
            "request_id": key,
            "usage": {
                "prompt_tokens": prompt,
                "completion_tokens": output,
                "total_tokens": prompt + output,
            },
        },
    ]


def put(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def pins(tmp_path, ledgers):
    return [
        put(
            tmp_path / f"ledger-{index}.jsonl",
            b"".join(json.dumps(event).encode() + b"\n" for event in events),
        )
        for index, events in enumerate(ledgers)
    ]


def poisoned(scope, call, match=None):
    with pytest.raises(Exception, match=match) as first:
        call()
    assert scope.status == "POISONED"
    with pytest.raises(type(first.value)) as closing:
        scope.close()
    assert closing.value is first.value
    assert scope.status == "CLOSED_FAILED"
    return first.value


def test_legacy_compatible_and_v2_known_total(tmp_path):
    sources = pins(tmp_path, [legacy("a"), [reserved("b")], v2("c")])
    original = historical_usage(tuple(Path(row["path"]) for row in sources[:2]))
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, sources)
        assert actual == {
            **original,
            "sources": sources,
            "requests": 3,
            "known_raw_tokens": 22,
        }
        assert actual["actual_total_raw_tokens"] is None
        assert actual["reserved_raw_upper_bound"] == 14
        assert actual["new_generation_allowed"] is False
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 3


def test_settled_total_includes_v2_not_stale_legacy_total(tmp_path):
    sources = pins(tmp_path, [legacy("a"), [], v2("c")])
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, tuple(sources))
    assert actual["requests"] == 2
    assert actual["known_raw_tokens"] == actual["actual_total_raw_tokens"] == 22
    assert actual["new_generation_allowed"] is True  # Accounting only, not Batch authority.
    assert actual["reserved_raw_upper_bound"] == 0


def test_empty_ledgers_are_valid_data_not_exact_presentation_history(tmp_path):
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, pins(tmp_path, [[], [], []]))
    assert actual["requests"] == actual["known_raw_tokens"] == 0


def test_repeated_calls_recheck_semantics_and_defensive_objects(tmp_path):
    sources = pins(tmp_path, [legacy("a"), [reserved("b")], v2("c")])
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, sources)
        expected = copy.deepcopy(actual)
        actual["unresolved_reservations"][0]["payload_sha256"] = "changed"
        actual["sources"][0]["path"] = "changed"
        assert historical_usage_from_pinned(scope, sources) == expected
        assert scope.stats["first_reads"] == 3
        assert scope.stats["repeat_references"] == 3
        assert scope.stats["json_parses"] == 0  # JSONL is reparsed, not a JSON-document cache.


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("value", [True, 10.0, -1, None, "10"])
def test_strict_reservation_counts(tmp_path, position, value):
    ledgers = [legacy("a"), legacy("b"), v2("c")]
    ledgers[position][0]["prompt_tokens"] = value
    sources = pins(tmp_path, ledgers)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources))


@pytest.mark.parametrize("version", ["legacy", "v2"])
@pytest.mark.parametrize("field", ["prompt", "completion", "sum", "bool"])
def test_usage_bounds_without_violation_marker(tmp_path, version, field):
    events = legacy("c") if version == "legacy" else v2("c")
    usage = events[-1] if version == "legacy" else events[-1]["usage"]
    prompt = "input_tokens" if version == "legacy" else "prompt_tokens"
    output = "output_tokens" if version == "legacy" else "completion_tokens"
    if field == "prompt":
        usage[prompt] = 9
    elif field == "completion":
        usage[output] = 5
    elif field == "bool":
        usage[output] = True
    else:
        events[0]["raw_upper_bound"] += 1
    if version == "v2":
        usage["total_tokens"] = usage[prompt] + usage[output]
    sources = pins(tmp_path, [events, []] if version == "legacy" else [[], [], events])
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources))


@pytest.mark.parametrize("stop", [1, 2, 3, "unknown", "violation", "reordered", "duplicate"])
def test_new_pending_unknown_violation_and_invalid_fsm_rejected(tmp_path, stop):
    events = v2("c")
    if type(stop) is int:
        events = events[:stop]
    elif stop == "unknown":
        events[-1] = {"event": "USAGE_UNKNOWN", "request_id": "c"}
    elif stop == "violation":
        events.append({"event": "BOUND_VIOLATION", "request_id": "c"})
    elif stop == "reordered":
        events[1], events[2] = events[2], events[1]
    else:
        events.append(events[-1])
    sources = pins(tmp_path, [[], [], events])
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources))


@pytest.mark.parametrize(
    "ledgers",
    [
        [legacy("a"), legacy("a")],
        [legacy("a"), [], v2("a")],
        [[], [], v2("a"), v2("a")],
        [legacy("a") + legacy("a"), []],
    ],
)
def test_global_request_ids_cannot_double_count(tmp_path, ledgers):
    sources = pins(tmp_path, ledgers)
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources), "GLOBALLY_UNIQUE")


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "one",
        "mapping",
        "duplicate",
        "extra",
        "relative",
        "parent",
        "noncanonical",
        "hash",
        "symlink",
    ],
)
def test_explicit_source_structure_paths_and_hashes(tmp_path, kind):
    sources = pins(tmp_path, [legacy("a"), legacy("b")])
    if kind == "empty":
        sources = []
    elif kind == "one":
        sources = sources[:1]
    elif kind == "mapping":
        sources = {row["path"]: row["sha256"] for row in sources}
    elif kind == "duplicate":
        sources[1] = sources[0]
    elif kind == "extra":
        sources[0]["allow_unknown"] = True
    elif kind == "relative":
        sources[0]["path"] = "ledger-0.jsonl"
    elif kind == "parent":
        sources[0]["path"] = str(tmp_path) + "/../" + tmp_path.name + "/ledger-0.jsonl"
    elif kind == "noncanonical":
        sources[0]["path"] = str(tmp_path) + "/./ledger-0.jsonl"
    elif kind == "symlink":
        link = tmp_path / "alias.jsonl"
        link.symlink_to(sources[0]["path"])
        sources[0]["path"] = str(link)
    else:
        sources[0]["sha256"] = "0" * 64
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources))


@pytest.mark.parametrize("raw", [b"\n", b"[]\n", b'{"a":1,"a":2}\n', b'{"n":NaN}', b"\xff"])
def test_strict_jsonl_even_after_bytes_preverification(tmp_path, raw):
    sources = pins(tmp_path, [[], []])
    sources[0] = put(Path(sources[0]["path"]), raw)
    scope = AdmissionReadScope()
    scope.read_bytes(sources[0]["path"], sources[0]["sha256"])
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources))


def test_close_drift_and_next_scope_freshness(tmp_path):
    sources = pins(tmp_path, [legacy("a"), []])
    scope = AdmissionReadScope()
    historical_usage_from_pinned(scope, sources)
    Path(sources[0]["path"]).write_bytes(b"changed")
    with pytest.raises(AdmissionReadError):
        scope.close()
    assert scope.status == "CLOSED_FAILED"
    fresh = AdmissionReadScope()
    poisoned(fresh, lambda: historical_usage_from_pinned(fresh, sources))


def test_legacy_violation_reported_not_waived(tmp_path):
    events = [reserved("a"), {"event": "BOUND_VIOLATION", "request_id": "a"}]
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, pins(tmp_path, [events, []]))
    assert actual["violations"] == events[1:]
    assert actual["new_generation_allowed"] is False
    assert actual["actual_total_raw_tokens"] is None


def inventory_fixture(tmp_path, monkeypatch):
    ledgers = [legacy("a", 1000, 100) + legacy("b", 1000, 121), [reserved("old", 24188, 4096)]]
    ledgers += [v2(f"v2-{i}") for i in range(54)] + [v2("last", 1078613, 1)]
    sources = pins(tmp_path, ledgers)
    inventory = {
        "status": "INDEPENDENT_HISTORY_INVENTORY_REVIEW_PASS_NOT_AUTHORIZATION",
        "sources": sources,
        "aggregate": {
            "ledger_files": 57,
            "requests": 58,
            "known_raw_tokens": 1081429,
            "unknown_reservations": 1,
            "reserved_raw_upper_bound": 28284,
            "actual_total_raw_tokens": None,
            "reservation_is_actual_usage": False,
            "violations": [],
            "new_unknown_reservations": [],
        },
        "original_unknown_complete_objects": [{**ledgers[1][0], "ledger": sources[1]["path"]}],
    }
    path = tmp_path / "inventory.json"
    pin = put(path, inventory)
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    monkeypatch.setattr(module, "INVENTORY_SHA256", pin["sha256"])
    return inventory, path


def test_exact_inventory_policy_synthetic_and_all_bytes_verified(tmp_path, monkeypatch):
    inventory, _ = inventory_fixture(tmp_path, monkeypatch)
    with AdmissionReadScope() as scope:
        actual = presentation_history(scope)
    assert actual["known_raw_tokens"] == 1081429
    assert actual["unresolved_reservations"] == inventory["original_unknown_complete_objects"]
    assert actual["new_generation_allowed"] is False
    assert scope.stats["first_reads"] == scope.stats["closing_reads"] == 58


@pytest.mark.parametrize("change", ["missing", "added", "reorder", "replace", "aggregate"])
def test_inventory_tamper_cannot_replace_source_constant(tmp_path, monkeypatch, change):
    inventory, path = inventory_fixture(tmp_path, monkeypatch)
    if change == "missing":
        inventory["sources"].pop()
    elif change == "added":
        inventory["sources"].append(inventory["sources"][-1])
    elif change == "reorder":
        inventory["sources"].reverse()
    elif change == "replace":
        inventory["sources"][-1]["sha256"] = "0" * 64
    else:
        inventory["aggregate"]["known_raw_tokens"] = 0
    put(path, inventory)  # Do not replace the independently pinned digest.
    scope = AdmissionReadScope()
    poisoned(scope, lambda: presentation_history(scope))


@pytest.mark.parametrize("change", ["payload", "extra", "missing", "float", "bool", "ledger"])
def test_exact_unknown_semantics_not_just_total(tmp_path, monkeypatch, change):
    inventory, path = inventory_fixture(tmp_path, monkeypatch)
    unknown = inventory["original_unknown_complete_objects"][0]
    if change == "payload":
        unknown["payload_sha256"] = "b" * 64
    elif change == "extra":
        unknown["waived"] = True
    elif change == "missing":
        del unknown["session"]
    elif change == "float":
        unknown["prompt_tokens"] = 24188.0
    elif change == "bool":
        unknown["cumulative_raw_cap"] = False
    else:
        unknown["ledger"] = inventory["sources"][0]["path"]
    # Synthetic trusted inventory is internally inconsistent; runtime recomputes.
    monkeypatch.setattr(module, "INVENTORY_SHA256", put(path, inventory)["sha256"])
    scope = AdmissionReadScope()
    poisoned(scope, lambda: presentation_history(scope), "EXACT_ORIGINAL_UNKNOWN")


def test_v2_pure_state_acceptance_matches_for_valid_events(tmp_path):
    events = v2("c", 0, 0)
    expected = usage_state(events)
    with AdmissionReadScope() as scope:
        actual = historical_usage_from_pinned(scope, pins(tmp_path, [[], [], events]))
    for key, value in expected.items():
        assert actual[key] == value


@pytest.mark.parametrize("total", [True, 10, 12, 11.0])
def test_actual_usage_total_must_be_strict_integer_exact_sum(tmp_path, total):
    events = v2("c")
    events[-1]["usage"]["total_tokens"] = total
    sources = pins(tmp_path, [[], [], events])
    scope = AdmissionReadScope()
    poisoned(scope, lambda: historical_usage_from_pinned(scope, sources), "CORRUPT_USAGE_LEDGER")


@pytest.mark.parametrize("change", ["before_reserved", "duplicate_settled"])
def test_legacy_settlement_sequence_rejected(tmp_path, change):
    events = legacy("a")
    if change == "before_reserved":
        events.reverse()
    else:
        events.append(events[-1])
    sources = pins(tmp_path, [events, []])
    scope = AdmissionReadScope()
    poisoned(
        scope, lambda: historical_usage_from_pinned(scope, sources), "CORRUPT_LEGACY_HISTORY_FSM"
    )


def test_explicit_scope_required():
    with pytest.raises(TypeError, match="EXPLICIT_ADMISSION"):
        historical_usage_from_pinned(None, [])


def test_closed_scope_cannot_be_reused(tmp_path):
    scope = AdmissionReadScope()
    scope.close()
    with pytest.raises(AdmissionReadError, match="ALREADY_CLOSED"):
        historical_usage_from_pinned(scope, pins(tmp_path, [[], []]))
