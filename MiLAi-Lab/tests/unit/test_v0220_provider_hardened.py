"""Offline Provider failure/accounting injection; no real completions or schema lowering."""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import v0220_schema_admission
from check_v0220_full_schema import keyword_paths
from v02_local_provider import append_event, read_events
from v0213_provider import MODEL, payload
from v0220_evidence import read, save, sha
from v0220_provider_hardened import (
    Provider,
    ProviderStop,
    historical_usage,
    usage_state,
    valid_usage,
)
from v0220_schema_admission import FullSchemaPreflight


def reserve(path, key="old"):
    append_event(
        path,
        {
            "event": "RESERVED",
            "request_id": key,
            "session": "old",
            "prompt_tokens": 100,
            "output_cap": 4096,
            "raw_upper_bound": 4196,
        },
    )


def setup(tmp_path, completion=None, *, count=100, preflight=None):
    history = tmp_path / "historical.jsonl"
    history.touch()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": count})
        if completion:
            return completion(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "server-receipt", "set-cookie": "private"},
            json={
                "usage": {"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112},
                "choices": [{"message": {"content": "中文 output"}}],
            },
        )

    provider = Provider(
        tmp_path / "provider",
        deadline=time.monotonic() + 10,
        max_requests=2,
        historical_ledgers=(history,),
        preflight=preflight or (lambda _: None),
        transport=httpx.MockTransport(handler),
    )
    provider.verify()
    return provider, calls, history


def body():
    return payload([{"role": "user", "content": "synthetic"}], {"type": "object"})


def completions(calls):
    return [r for r in calls if r.url.path == "/v1/chat/completions"]


def test_exact_wire_correlation_headers_and_known_usage(tmp_path):
    provider, calls, _ = setup(tmp_path)
    assert provider.generate("safe", body()) == "中文 output"
    sent = completions(calls)[0]
    key = sent.headers["x-request-id"]
    assert (provider.root / f"{key}-request.json").read_bytes() == sent.content
    receipt = read(provider.root / f"{key}-http.json")
    assert receipt["headers"]["x-request-id"] == "server-receipt"
    assert "set-cookie" not in receipt["headers"]
    assert receipt["request_wire_sha256"] == hashlib.sha256(sent.content).hexdigest()
    state = usage_state(read_events(provider.ledger))
    assert state["known_raw_tokens"] == state["actual_total_raw_tokens"] == 112
    assert state["reserved_raw_upper_bound"] == 0
    provider.close()


@pytest.mark.parametrize(
    "failure",
    [
        "500",
        "400",
        "timeout",
        "connect",
        "malformed",
        "missing",
        "bool",
        "negative",
        "total",
        "interrupt",
    ],
)
def test_unknown_usage_is_durable_and_blocks_second_request(tmp_path, failure):
    def response(request):
        if failure in {"500", "400"}:
            return httpx.Response(int(failure), json={"error": {"message": ""}})
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider text", request=request)
        if failure == "connect":
            raise httpx.ConnectError("private provider text", request=request)
        if failure == "interrupt":
            raise KeyboardInterrupt
        if failure == "malformed":
            return httpx.Response(200, text="not json")
        usage = {"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112}
        if failure == "missing":
            usage = None
        elif failure == "bool":
            usage["prompt_tokens"] = True
        elif failure == "negative":
            usage["completion_tokens"] = -1
        else:
            usage["total_tokens"] = 113
        return httpx.Response(200, json={"usage": usage})

    provider, calls, _ = setup(tmp_path, response)
    with pytest.raises(KeyboardInterrupt if failure == "interrupt" else ProviderStop) as exc:
        provider.generate("safe", body())
    assert "private provider text" not in str(exc.value)
    events = read_events(provider.ledger)
    assert events[-1]["event"] == "USAGE_UNKNOWN"
    state = usage_state(events)
    assert state["actual_total_raw_tokens"] is None
    assert state["known_raw_tokens"] == 0
    assert state["reserved_raw_upper_bound"] == 4196
    with pytest.raises(ProviderStop, match="UNSETTLED_USAGE_NO_RETRY"):
        provider.generate("safe", body())
    assert len(completions(calls)) == 1
    provider.close()


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 101, "completion_tokens": 12, "total_tokens": 113},
        {"prompt_tokens": 100, "completion_tokens": 4097, "total_tokens": 4197},
    ],
)
def test_bound_mismatch_records_actual_not_estimate_and_stops(tmp_path, usage):
    provider, calls, _ = setup(tmp_path, lambda _: httpx.Response(200, json={"usage": usage}))
    with pytest.raises(ProviderStop, match="ACTUAL_RECORDED"):
        provider.generate("safe", body())
    state = usage_state(read_events(provider.ledger))
    assert state["actual_total_raw_tokens"] == usage["total_tokens"]
    assert not state["new_generation_allowed"] and state["violations"]
    assert not state["unresolved_reservations"]
    with pytest.raises(ProviderStop, match="NO_RETRY"):
        provider.generate("safe", body())
    assert len(completions(calls)) == 1
    provider.close()


def test_output_failure_does_not_erase_valid_usage(tmp_path):
    usage = {"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112}
    provider, _, _ = setup(tmp_path, lambda _: httpx.Response(200, json={"usage": usage}))
    with pytest.raises(ProviderStop, match="VISIBLE_OUTPUT_INVALID_USAGE_KNOWN"):
        provider.generate("safe", body())
    assert usage_state(read_events(provider.ledger))["actual_total_raw_tokens"] == 112
    provider.close()


def test_old_debt_cannot_be_hidden_by_new_provider_directory(tmp_path):
    provider, calls, history = setup(tmp_path)
    reserve(history)
    before = history.read_bytes()
    with pytest.raises(ProviderStop, match="UNSETTLED_USAGE"):
        provider.generate("safe", body())
    assert not completions(calls) and not provider.ledger.exists()
    assert history.read_bytes() == before
    report = historical_usage((history,))
    assert report["actual_total_raw_tokens"] is None and report["reserved_raw_upper_bound"] == 4196
    provider.close()


@pytest.mark.parametrize("phase", ["RESERVED", "DISPATCH_STARTED", "RESPONSE_RECEIVED"])
def test_crash_tail_remains_unknown_without_terminal_event(tmp_path, phase):
    path = tmp_path / "ledger"
    reserve(path)
    if phase != "RESERVED":
        append_event(path, {"event": "DISPATCH_STARTED", "request_id": "old"})
    if phase == "RESPONSE_RECEIVED":
        append_event(path, {"event": "RESPONSE_RECEIVED", "request_id": "old"})
    state = usage_state(read_events(path))
    assert state["actual_total_raw_tokens"] is None and not state["new_generation_allowed"]


@pytest.mark.parametrize("count", [True, -1, 61441])
def test_invalid_tokenize_or_context_never_dispatches(tmp_path, count):
    provider, calls, _ = setup(tmp_path, count=count)
    with pytest.raises(ProviderStop, match="INVALID_TOKEN_COUNT"):
        provider.generate("safe", body())
    assert not completions(calls) and not provider.ledger.exists()
    provider.close()


def test_preflight_rejection_happens_before_tokenize_and_reservation(tmp_path):
    def reject(_):
        raise ProviderStop("FULL_SCHEMA_PROVIDER_INCOMPATIBLE_NO_DISPATCH")

    provider, calls, _ = setup(tmp_path, preflight=reject)
    with pytest.raises(ProviderStop, match="FULL_SCHEMA"):
        provider.generate("safe", body())
    assert [r.url.path for r in calls] == ["/v1/models"]
    assert not provider.ledger.exists()
    provider.close()


def test_keyword_inventory_preserves_literal_and_property_names():
    value = {
        "properties": {
            "uniqueItems": {"type": "boolean"},
            "arr": {"type": "array", "uniqueItems": True},
        },
        "const": {"uniqueItems": True},
    }
    before = json.dumps(value)
    assert keyword_paths(value, "uniqueItems") == ["/properties/arr/uniqueItems"]
    assert json.dumps(value) == before


def test_usage_boolean_total_is_not_integer():
    assert not valid_usage({"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": True})


def test_duplicate_or_missing_history_rejected(tmp_path):
    path = tmp_path / "ledger"
    path.touch()
    with pytest.raises(ProviderStop):
        historical_usage((path, path))
    with pytest.raises(ProviderStop):
        historical_usage((tmp_path / "missing",))
    with pytest.raises(ProviderStop):
        historical_usage(())


def test_unknown_historical_event_not_silently_ignored(tmp_path):
    path = tmp_path / "ledger"
    append_event(path, {"event": "WAIVED", "request_id": "old"})
    with pytest.raises(ProviderStop, match="CORRUPT_HISTORICAL"):
        historical_usage((path,))


def test_preflight_requires_all_hashes_and_detects_drift(tmp_path):
    with pytest.raises(ProviderStop, match="COMPLETE_PREFLIGHT_HASH_BINDING"):
        FullSchemaPreflight(tmp_path, hashes={})
    hashes = {}
    for name in ("manifest.json", "result.json", "inventory.json", "probes.json"):
        save(tmp_path / name, {})
        hashes[name] = sha(tmp_path / name)
    gate = FullSchemaPreflight(tmp_path, hashes=hashes)
    hashes["result.json"] = "changed caller mapping does not alter gate"
    (tmp_path / "result.json").write_text("[]")
    with pytest.raises(ProviderStop, match="PREFLIGHT_EVIDENCE_DRIFT"):
        gate(body())


def matrix(tmp_path, monkeypatch, *, rejected=False, missing=False):
    roots = ["a", "b", "c", "d"]
    save(
        tmp_path / "manifest.json",
        {"contract": {"roots": roots, "no_schema_lowering_or_target_filtering": True}},
    )
    inventory, rows = [], []
    for key in roots:
        for suffix in ("-full", "-finish"):
            identity = key + suffix
            value = body()
            value["response_format"]["json_schema"]["schema"] = {"const": identity}
            path = tmp_path / "requests" / (identity + ".json")
            save(path, value)
            inventory.append({"id": identity, "request_sha256": sha(path)})
            rows.append(
                {
                    "id": identity,
                    "status": "REJECTED" if rejected and key == "a" else "PASS_CPU_ONLY",
                }
            )
    save(
        tmp_path / "result.json",
        {"unchanged_public_contract": True, "rows": rows[:-1] if missing else rows},
    )
    save(tmp_path / "inventory.json", inventory)
    save(tmp_path / "probes.json", [])
    monkeypatch.setattr(
        v0220_schema_admission, "validate", lambda root: read(root / "manifest.json")
    )
    return FullSchemaPreflight(
        tmp_path,
        hashes={
            name: sha(tmp_path / name)
            for name in ("manifest.json", "result.json", "inventory.json", "probes.json")
        },
    )


def test_one_failed_root_blocks_even_another_passing_root(tmp_path, monkeypatch):
    gate = matrix(tmp_path, monkeypatch, rejected=True)
    with pytest.raises(ProviderStop, match="FULL_SCHEMA_PROVIDER_INCOMPATIBLE"):
        gate(read(tmp_path / "requests/d-full.json"))


def test_missing_schema_variant_cannot_count_as_pass(tmp_path, monkeypatch):
    gate = matrix(tmp_path, monkeypatch, missing=True)
    with pytest.raises(ProviderStop, match="INCOMPLETE_FULL_SCHEMA_MATRIX"):
        gate(body())


def test_cpu_gate_binds_exact_schema_without_claiming_live_admission(tmp_path, monkeypatch):
    gate = matrix(tmp_path, monkeypatch)
    gate(read(tmp_path / "requests/d-full.json"))
    with pytest.raises(ProviderStop, match="UNVALIDATED_SCHEMA"):
        gate(body())
    (tmp_path / "requests/d-full.json").write_text("{}")
    with pytest.raises(ProviderStop, match="PREFLIGHT_REQUEST_DRIFT"):
        gate(body())


def test_invalid_event_transition_cannot_settle_unknown(tmp_path):
    path = tmp_path / "ledger"
    reserve(path)
    append_event(path, {"event": "USAGE_UNKNOWN", "request_id": "old"})
    append_event(
        path,
        {
            "event": "USAGE_KNOWN",
            "request_id": "old",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    )
    with pytest.raises(ProviderStop, match="CORRUPT_USAGE_LEDGER"):
        usage_state(read_events(path))


def test_existing_directory_cannot_reset_unknown_usage(tmp_path):
    provider, _, history = setup(tmp_path)
    with pytest.raises(FileExistsError):
        Provider(
            provider.root,
            deadline=time.monotonic() + 10,
            max_requests=2,
            historical_ledgers=(history,),
            preflight=lambda _: None,
        )
    provider.close()
