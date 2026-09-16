"""Mock HTTP with real scoped core SQL/FSM/local mirror, synthetic authority/PID.

The inherited core fixture substitutes _authorize with a pinned synthetic anchor,
inserts synthetic preparation artifacts and simulates PID/clock. No real lineage,
raw business acceptance, World effects or live instance is claimed by these tests.
"""

import copy
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0222_presentation_batch_v2 import setup as core_setup

import v0222_presentation_transport_v2 as module
from v02_local_provider import read_events
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import encoded, fingerprint
from v0222_diagnostic import request


def setup(tmp_path, monkeypatch, mode="valid"):
    batch, clock, pid, scopes, _anchor = core_setup.__wrapped__(tmp_path, monkeypatch)
    batch.auth["historical"] = {
        "sources": [{"path": str(tmp_path / ("synthetic-history-" + str(i)))} for i in range(57)],
        "known_raw_tokens": 1081429,
        "unknown_raw_upper_bound": 28284,
        "synthetic_fixture_not_actual_lineage": True,
    }
    batch.plan["http_identity"] = {
        "endpoint": ENDPOINT,
        "model": MODEL,
        "context": 65536,
        "version": "mock-v2",
    }
    batch.launch_once("P3")
    pid[0] = 201
    batch.claim("P3-00")
    directory = tmp_path / "episodes" / "P3-00" / "provider"
    directory.rmdir()  # Only the empty fixture directory, never a live root.
    _, body = request("T1", "D00")
    expected = copy.deepcopy(body)
    calls, timeouts = [], []

    def handle(req):
        calls.append(req.url.path)
        timeouts.append(req.extensions["timeout"]["read"])
        assert scopes[-1].status == "CLOSED_VERIFIED_TWO_OBSERVATIONS"
        with sqlite3.connect(batch.path, timeout=0.1) as probe:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
        if req.url.path == "/v1/models":
            if mode == "stop_models":
                batch.stop("MOCK_STOP_IDENTITY")
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if req.url.path == "/version":
            if mode == "late_identity":
                clock[0] += 301
            return httpx.Response(200, json={"version": "mock-v2"})
        if req.url.path == "/tokenize":
            assert json.loads(req.content) == {k: expected[k] for k in TOKENIZE_KEYS}
            if mode == "stop_tokenize":
                batch.stop("MOCK_STOP_TOKENIZE")
            if mode == "lineage_copy":
                batch.auth["historical"]["sources"][0]["path"] = "MUTATED_SYNTHETIC_AUTH"
            if mode == "duplicate_count":
                return httpx.Response(200, text='{"count":77,"count":77}')
            count = {"bool_count": True, "float_count": 77.0, "too_long": 65536}.get(mode, 77)
            return httpx.Response(201 if mode == "count_201" else 200, json={"count": count})
        assert req.url.path == "/v1/chat/completions"
        assert req.content == encoded(expected).encode()
        assert (
            directory / (req.headers["x-request-id"] + "-request.json")
        ).read_bytes() == req.content
        if mode == "timeout":
            raise httpx.ReadTimeout("mock", request=req)
        if mode == "transport_error":
            raise httpx.ConnectError("mock", request=req)
        if mode == "http500":
            return httpx.Response(500, json={"error": "mock"})
        if mode == "duplicate_usage":
            return httpx.Response(200, text='{"usage":{},"usage":{}}')
        if mode == "nonfinite":
            return httpx.Response(200, text='{"usage":NaN}')
        usage = {"prompt_tokens": 77, "completion_tokens": 5, "total_tokens": 82}
        if mode == "missing_usage":
            usage = None
        elif mode == "bound_prompt":
            usage = {"prompt_tokens": 78, "completion_tokens": 5, "total_tokens": 83}
        elif mode == "bound_output":
            usage = {"prompt_tokens": 77, "completion_tokens": 4097, "total_tokens": 4174}
        elif mode == "bool_usage":
            usage = {"prompt_tokens": 77, "completion_tokens": True, "total_tokens": 78}
        elif mode == "wrong_total":
            usage["total_tokens"] = 999
        if mode == "late_usage":
            clock[0] += 301
        elif mode == "stopped_usage":
            batch.stop("EARLIER_STOP_DURING_HTTP")
        content = {
            "invalid_json": "not-json",
            "deep_json": "[" * 1100 + "0" + "]" * 1100,
            "surrogate": "\ud800",
            "empty": "",
        }.get(mode, '{"text":"x"}')
        value = {"id": "mock", "usage": usage, "choices": [{"message": {"content": content}}]}
        if mode == "missing_id":
            value.pop("id")
        if mode == "content_not_string":
            value["choices"][0]["message"]["content"] = []
        return httpx.Response(200, text=json.dumps(value, ensure_ascii=True))

    def preflight(candidate):
        if fingerprint(candidate) != fingerprint(expected):
            raise ProviderStop("UNFROZEN_WIRE")

    provider = module.Transport(
        directory,
        batch=batch,
        episode="P3-00",
        preflight=preflight,
        transport=httpx.MockTransport(handle),
    )
    return batch, provider, body, calls, clock, scopes, timeouts


@pytest.mark.parametrize("mode", ["valid", "invalid_json", "deep_json", "surrogate", "empty"])
def test_raw_passthrough_has_one_core_mirror_and_original_evidence_shape(
    tmp_path, monkeypatch, mode
):
    batch, provider, body, calls, _, scopes, _ = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        content = provider.generate("P3-00", body)
        expected = {
            "invalid_json": "not-json",
            "deep_json": "[" * 1100 + "0" + "]" * 1100,
            "surrogate": "\ud800",
            "empty": "",
        }.get(mode, '{"text":"x"}')
        assert content == expected
        with batch.transaction() as db:
            central = batch.events(db)
            batch._mirrors(db)
        assert central == read_events(provider.ledger)
        assert [e["event"] for e in central] == [
            "RESERVED",
            "DISPATCH_STARTED",
            "RESPONSE_RECEIVED",
            "USAGE_KNOWN",
        ]
        assert usage_state(central)["known_raw_tokens"] == 82
        assert calls == ["/v1/models", "/version", "/tokenize", "/v1/chat/completions"]
        assert len({id(s) for s in scopes}) == len(scopes)
        key = central[0]["request_id"]
        assert {p.name for p in provider.root.iterdir() if p.is_file()} == {
            "provider-ledger-v2.jsonl",
            *(
                key + suffix
                for suffix in (
                    "-tokenize-request.json",
                    "-tokenize-http.json",
                    "-request.json",
                    "-tokenize.json",
                    "-lineage.json",
                    "-http.json",
                    "-visible.json",
                )
            ),
        }
        assert (
            json.loads((provider.root / (key + "-lineage.json")).read_bytes())
            == batch.auth["historical"]
        )
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode",
    [
        "timeout",
        "transport_error",
        "http500",
        "missing_usage",
        "duplicate_usage",
        "nonfinite",
        "bool_usage",
        "wrong_total",
    ],
)
def test_unknown_usage_stops_once_and_never_retries(tmp_path, monkeypatch, mode):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        state = batch.snapshot()
        assert state["stop"] and state["cost"]["actual_total_raw_tokens"] is None
        assert state["cost"]["requests"] == 1
        assert sum(e["event"] == "USAGE_UNKNOWN" for e in read_events(provider.ledger)) == 1
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        assert calls.count("/v1/chat/completions") == 1
        with batch.transaction() as db:
            batch._mirrors(db)
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode,total",
    [
        ("bound_prompt", 83),
        ("bound_output", 4174),
        ("missing_id", 82),
        ("content_not_string", 82),
        ("late_usage", 82),
        ("stopped_usage", 82),
    ],
)
def test_known_late_or_invalid_response_is_charged_without_release(
    tmp_path, monkeypatch, mode, total
):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        state = batch.snapshot()
        assert state["stop"] and state["cost"]["known_raw_tokens"] == total
        assert state["cost"]["actual_total_raw_tokens"] == total
        if mode == "stopped_usage":
            assert state["stop"] == "EARLIER_STOP_DURING_HTTP"
        events = read_events(provider.ledger)
        assert sum(e["event"] == "BOUND_VIOLATION" for e in events) == int(mode.startswith("bound"))
        assert not any(e["event"] == "USAGE_UNKNOWN" for e in events)
        assert state["episodes"][0]["status"] == "FAIL"
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        assert calls.count("/v1/chat/completions") == 1
        with batch.transaction() as db:
            batch._mirrors(db)
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode",
    [
        "bool_count",
        "float_count",
        "too_long",
        "duplicate_count",
        "count_201",
        "stop_tokenize",
    ],
)
def test_invalid_tokenize_or_stop_cannot_reserve_or_dispatch(tmp_path, monkeypatch, mode):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch, mode)
    try:
        provider.verify()
        with pytest.raises((ProviderStop, ValueError)):
            provider.generate("P3-00", body)
        assert batch.snapshot()["stop"]
        assert batch.snapshot()["cost"]["requests"] == 0
        assert "/v1/chat/completions" not in calls
    finally:
        provider.close()


@pytest.mark.parametrize("mode", ["stop_models", "late_identity"])
def test_identity_failure_keeps_context_empty_and_no_tokenize(tmp_path, monkeypatch, mode):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch, mode)
    try:
        with pytest.raises(ProviderStop):
            provider.verify()
        assert provider.context is None and batch.snapshot()["stop"]
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        assert "/tokenize" not in calls
    finally:
        provider.close()


@pytest.mark.parametrize("change", ["wire", "float_cap", "bool_cap", "wrong_session", "unverified"])
def test_request_rejected_before_tokenize(tmp_path, monkeypatch, change):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    try:
        if change != "unverified":
            provider.verify()
        if change == "wire":
            body["temperature"] = 0.5
        elif change == "float_cap":
            body["max_tokens"] = 4096.0
        elif change == "bool_cap":
            body["max_tokens"] = True
        with pytest.raises(ProviderStop):
            provider.generate("OTHER" if change == "wrong_session" else "P3-00", body)
        assert "/tokenize" not in calls and batch.snapshot()["cost"]["requests"] == 0
        assert batch.snapshot()["stop"]
    finally:
        provider.close()


def test_request_cap_cannot_be_restarted(tmp_path, monkeypatch):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        provider.generate("P3-00", body)
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        assert calls.count("/v1/chat/completions") == 1
        assert batch.snapshot()["cost"]["requests"] == 1
    finally:
        provider.close()


def test_lineage_evidence_is_a_deep_copy_not_old_44_ledger_helper(tmp_path, monkeypatch):
    batch, provider, body, *_ = setup(tmp_path, monkeypatch, "lineage_copy")
    original = copy.deepcopy(batch.auth["historical"])
    try:
        provider.verify()
        provider.generate("P3-00", body)
        lineage = json.loads(next(provider.root.glob("*-lineage.json")).read_bytes())
        assert lineage == original and lineage != batch.auth["historical"]
        assert len(lineage["sources"]) == 57
    finally:
        provider.close()


def test_constructor_error_stops_before_any_http(tmp_path, monkeypatch):
    batch, provider, _, calls, *_ = setup(tmp_path, monkeypatch)
    provider.close()
    with pytest.raises(ProviderStop, match="DIRECTORY_OUTSIDE"):
        module.Transport(
            tmp_path / "wrong",
            batch=batch,
            episode="P3-00",
            preflight=lambda body: None,
            transport=httpx.MockTransport(lambda req: pytest.fail("unexpected HTTP")),
        )
    assert batch.snapshot()["stop"] and not calls


def test_fresh_tokenize_deadline_limits_network_timeout(tmp_path, monkeypatch):
    _, provider, body, _, clock, _, timeouts = setup(tmp_path, monkeypatch)
    try:
        provider.verify()
        clock[0] = 1299.5
        provider.generate("P3-00", body)
        assert timeouts[-2:] == [0.5, 0.5]
    finally:
        provider.close()


@pytest.mark.parametrize("point", ["tokenize_request", "lineage", "raw_http", "visible"])
def test_evidence_failure_stops_without_unearned_output(tmp_path, monkeypatch, point):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    error = OSError("MOCK_EVIDENCE_FAILURE")
    original_save, original_open = module.save, Path.open
    suffix = {
        "tokenize_request": "-tokenize-request.json",
        "lineage": "-lineage.json",
        "raw_http": "-http.json",
    }.get(point)

    def save(path, value):
        if (
            suffix is not None
            and path.name.endswith(suffix)
            and not (point == "raw_http" and path.name.endswith("-tokenize-http.json"))
        ):
            raise error
        return original_save(path, value)

    def opened(path, *args, **kwargs):
        if point == "visible" and path.name.endswith("-visible.json"):
            raise error
        return original_open(path, *args, **kwargs)

    try:
        provider.verify()
        monkeypatch.setattr(module, "save", save)
        monkeypatch.setattr(Path, "open", opened)
        with pytest.raises((OSError, ProviderStop)):
            provider.generate("P3-00", body)
        state = batch.snapshot()
        assert state["stop"] == "OSError"
        assert state["cost"]["requests"] == int(point in {"raw_http", "visible"})
        assert state["cost"]["known_raw_tokens"] == (82 if point == "visible" else 0)
        assert (state["cost"]["actual_total_raw_tokens"] is None) == (point == "raw_http")
        assert calls.count("/v1/chat/completions") == int(point in {"raw_http", "visible"})
        with batch.transaction() as db:
            batch._mirrors(db)
    finally:
        provider.close()


def test_tokenize_error_locks_before_error_report_and_keeps_first_reason(tmp_path, monkeypatch):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    original, observed = module.save, []

    def save(path, value):
        if path.name.endswith("-tokenize-request.json"):
            original(path, value)
            batch.stop("FIRST_SAVE_STOP")
            return
        if path.name.endswith("-tokenize-error.json"):
            observed.append(batch.snapshot()["stop"])
            raise OSError("SECONDARY_REPORT_FAILURE")
        return original(path, value)

    try:
        provider.verify()
        monkeypatch.setattr(module, "save", save)
        with pytest.raises(ProviderStop) as raised:
            provider.generate("P3-00", body)
        assert observed == ["FIRST_SAVE_STOP"]
        assert batch.snapshot()["stop"] == "FIRST_SAVE_STOP"
        assert any("report failed" in note for note in raised.value.__notes__)
        assert "/tokenize" not in calls
    finally:
        provider.close()


def test_stop_after_dispatch_marker_prevents_http_and_preserves_unknown(tmp_path, monkeypatch):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    original = batch.dispatch_started

    def dispatch(episode, request_id):
        original(episode, request_id)
        batch.stop("STOP_AFTER_DISPATCH_MARKER")

    try:
        provider.verify()
        monkeypatch.setattr(batch, "dispatch_started", dispatch)
        with pytest.raises(ProviderStop):
            provider.generate("P3-00", body)
        assert "/v1/chat/completions" not in calls
        assert batch.snapshot()["stop"] == "STOP_AFTER_DISPATCH_MARKER"
        assert [e["event"] for e in read_events(provider.ledger)] == [
            "RESERVED",
            "DISPATCH_STARTED",
            "USAGE_UNKNOWN",
        ]
        with batch.transaction() as db:
            batch._mirrors(db)
    finally:
        provider.close()


def test_monotonic_budget_includes_slow_tokenize_evidence_before_send(tmp_path, monkeypatch):
    batch, provider, body, calls, *_ = setup(tmp_path, monkeypatch)
    original = module.save

    def save(path, value):
        original(path, value)
        if path.name.endswith("-tokenize-request.json"):
            provider.deadline = module.time.monotonic() - 1

    try:
        provider.verify()
        monkeypatch.setattr(module, "save", save)
        with pytest.raises(ProviderStop, match="WALL_CLOCK"):
            provider.generate("P3-00", body)
        assert "/tokenize" not in calls and batch.snapshot()["stop"]
    finally:
        provider.close()
