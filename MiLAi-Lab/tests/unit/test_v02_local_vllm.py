from __future__ import annotations

import fcntl
import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
provider_module = importlib.import_module("v02_local_provider")
runner = importlib.import_module("run_v02_local_vllm")


@pytest.fixture
def config() -> dict:
    value = json.loads((Path(__file__).resolve().parents[2]
                       / "configs/v02-local-vllm-simulation.json").read_text())
    # MockTransport tests have their own synthetic allowance; historical config stays closed.
    value.update(model_transport_enabled=True, new_model_allocations_authorized=3,
                 new_model_tokens_authorized=60000)
    return value


def reserved(session: str = "G", key: str = "G-001") -> dict:
    return {"event": "RESERVED", "request_id": key, "session": session,
            "prompt_tokens": 100, "output_cap": 1200, "raw_upper_bound": 1300}


def settled(key: str = "G-001", input_tokens: int = 100, output_tokens: int = 50) -> dict:
    return {"event": "SETTLED", "request_id": key,
            "input_tokens": input_tokens, "output_tokens": output_tokens}


def test_budget_counts_all_input_not_just_uncached_and_reserves_output(config: dict) -> None:
    records = [reserved(), settled(input_tokens=19000, output_tokens=500)]
    assert provider_module.check_budget(config, records, "G", 100) == 400
    with pytest.raises(provider_module.LocalGateError, match="TOKEN_LIMIT"):
        provider_module.check_budget(config, records, "G", 250)
    config["batch_token_limit"] = 19700
    with pytest.raises(provider_module.LocalGateError, match="TOKEN_LIMIT"):
        provider_module.check_budget(config, records, "B", 1)


def test_native_arguments_preserve_multiline_quotes_and_opaque_mcp_payload(config, tmp_path):
    config["host_action_format"] = "ARGUMENT_OBJECT"
    text = 'FIRST\n引用 "双引号"、\\路径、\t制表符\r\nLAST\n'
    action = runner.decode_action(json.dumps({"tool": "write_file", "arguments": {
        "path": "details.md", "content": text}, "answer": ""}, ensure_ascii=False), config)
    runner.dispatch(tmp_path, {}, {}, None, action)
    assert (tmp_path / "details.md").read_bytes() == text.encode()
    arguments = {"name": "milai_working_state_update", "arguments": {
        "scope": "TASK", "expected_version": 0,
        "payload": {"arbitrary": [None, False, {"markdown": text}]}}}
    action = runner.decode_action(json.dumps({"tool": "mcp_call", "arguments": arguments,
                                             "answer": ""}), config)
    assert json.loads(action["arguments_json"]) == arguments
    system, schema = runner.host_protocol(config)
    assert schema["properties"]["arguments"]["type"] == "object"
    assert "arguments_json" not in system


def test_native_arguments_never_repair_double_encoded_or_incomplete_output(config):
    config["host_action_format"] = "ARGUMENT_OBJECT"
    with pytest.raises(ValueError, match="ARGUMENT_OBJECT_REQUIRED"):
        runner.decode_action(json.dumps({"tool": "finish", "arguments": "{}", "answer": ""}),
                             config)
    with pytest.raises(json.JSONDecodeError):
        runner.decode_action('{"tool":"write_file","arguments":{"content":"unfinished', config)
    with pytest.raises(provider_module.LocalGateError, match="UNKNOWN_HOST_ACTION_FORMAT"):
        runner.host_protocol({"host_action_format": "unknown"})


@pytest.mark.parametrize("records", [[reserved()], [reserved(), {
    "event": "OUTCOME_UNKNOWN", "request_id": "G-001"}], [reserved(), settled(), {
        "event": "BOUND_VIOLATION", "request_id": "G-001"}]])
def test_unresolved_and_bound_violation_block_next_session(config: dict, records: list) -> None:
    with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
        provider_module.check_budget(config, records, "B", 100)


def test_request_limit_and_session_authorization(config: dict) -> None:
    records = [row for i in range(10) for row in (reserved(key=str(i)), settled(key=str(i)))]
    with pytest.raises(provider_module.LocalGateError, match="REQUEST_LIMIT"):
        provider_module.check_budget(config, records, "G", 100)
    with pytest.raises(provider_module.LocalGateError, match="SESSION_NOT_AUTHORIZED"):
        provider_module.check_budget(config, [], "RERUN", 100)


@pytest.mark.parametrize("endpoint", ["https://api.example.com", "http://localhost:7860",
                                      "http://127.0.0.1:7968", "http://127.0.0.1:7860@evil"])
def test_non_pinned_endpoints_are_denied(config: dict, tmp_path: Path, endpoint: str) -> None:
    config["provider_base_url"] = endpoint
    with pytest.raises(provider_module.LocalGateError, match="LOOPBACK"):
        provider_module.LocalProvider(config, tmp_path, "G")


@pytest.mark.parametrize("failure", ["timeout", "missing_usage", "input_mismatch",
                                      "output_mismatch", "redirect"])
def test_uncertain_requests_persist_and_never_retry(
    config: dict, tmp_path: Path, failure: str,
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        # Reservation must exist before the HTTP dispatch, including after a restart.
        assert provider_module.accounting(provider_module.read_events(
            tmp_path / "provider-ledger.jsonl"))["pending"]
        if failure == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://api.example.com"})
        usage = {"prompt_tokens": 101, "completion_tokens": 10, "total_tokens": 111}
        if failure == "output_mismatch":
            usage = {"prompt_tokens": 100, "completion_tokens": 1201, "total_tokens": 1301}
        return httpx.Response(200, json={} if failure == "missing_usage" else {"usage": usage})

    client = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
        client.complete([], {}, tmp_path)
    client.close()
    restarted = provider_module.LocalProvider(config, tmp_path, "B", httpx.MockTransport(handle))
    with pytest.raises(provider_module.LocalGateError, match="UNRESOLVED"):
        restarted.complete([], {}, tmp_path)
    restarted.close()
    assert calls == ["/tokenize", "/v1/chat/completions"]


def test_single_inflight_lock_blocks_before_any_network(config: dict, tmp_path: Path) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500)

    client = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    with (tmp_path / "provider.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(provider_module.LocalGateError, match="ONE_REQUEST_IN_FLIGHT"):
            client.complete([], {}, tmp_path)
    client.close()
    assert calls == []


@pytest.mark.parametrize("thinking", [None, False, True])
def test_request_payload_and_usage_settlement(config: dict, tmp_path: Path, thinking) -> None:
    if thinking is not None:
        config["enable_thinking"] = thinking
    bodies = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        assert "authorization" not in request.headers
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        return httpx.Response(200, json={"id": "local-test", "usage": {
            "prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
            "prompt_tokens_details": {"cached_tokens": 90},
            "completion_tokens_details": {"reasoning_tokens": 7 if thinking else 0}},
            "choices": [{"finish_reason": "stop", "message": {
                "content": "{}", "reasoning": "not a tool action" if thinking else None}}]})

    client = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    assert client.complete([{"role": "user", "content": "data"}], {}, tmp_path) == "{}"
    client.close()
    for key in ("model", "messages", "chat_template_kwargs", "add_generation_prompt",
                "add_special_tokens"):
        assert bodies[0][key] == bodies[1][key]
    state = provider_module.accounting(provider_module.read_events(
        tmp_path / "provider-ledger.jsonl"))
    assert state["raw_tokens"] == 110 and state["pending"] == []
    assert bodies[1]["max_tokens"] == 1200
    assert bodies[1]["chat_template_kwargs"] == {"enable_thinking": thinking is True}
    # completion_tokens already contains reasoning; the subset must not be added twice.
    settlement = provider_module.read_events(tmp_path / "provider-ledger.jsonl")[-1]
    assert settlement["output_tokens"] == 10
    assert settlement["usage"]["completion_tokens_details"]["reasoning_tokens"] == (
        7 if thinking else 0)
    traces = provider_module.read_events(tmp_path / "budget-preflights.jsonl")
    assert [t["status"] for t in traces] == [
        "TOKENIZE_ATTEMPT", "BUDGET_ACCEPTED_NOT_DISPATCHED",
    ]
    assert traces[-1]["prompt_tokens"] == 100


@pytest.mark.parametrize("value", ["true", 1, None])
def test_invalid_thinking_mode_rejected_before_network(config, tmp_path, value):
    config["enable_thinking"] = value
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(500)

    with pytest.raises(provider_module.LocalGateError, match="THINKING_MODE_MUST_BE_BOOLEAN"):
        provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    assert not calls


def test_denied_full_input_records_count_without_reservation_or_generation(config, tmp_path):
    ledger = tmp_path / "provider-ledger.jsonl"
    for event in [reserved(), settled(input_tokens=11167, output_tokens=147)]:
        provider_module.append_event(ledger, event)
    original = ledger.read_bytes()
    calls = []

    def handle(request):
        calls.append(request.url.path)
        assert provider_module.read_events(tmp_path / "budget-preflights.jsonl")[-1][
            "status"] == "TOKENIZE_ATTEMPT"
        return httpx.Response(200, json={"count": 12000})

    client = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    with pytest.raises(provider_module.LocalGateError, match="TOKEN_LIMIT_BEFORE_DISPATCH"):
        client.complete([{"role": "user", "content": "full retained context"}], {}, tmp_path)
    client.close()
    assert calls == ["/tokenize"]
    assert ledger.read_bytes() == original
    trace = provider_module.read_events(tmp_path / "budget-preflights.jsonl")[-1]
    assert trace["status"] == "STOPPED_BEFORE_GENERATION"
    assert trace["prompt_tokens"] == 12000
    assert trace["budget"]["raw_tokens_remaining_before_next_input"] == 8686
    assert trace["reason"] == "TOKEN_LIMIT_BEFORE_DISPATCH"
    assert not list(tmp_path.glob("*-request.json"))


def test_tokenize_timeout_is_observed_without_generation_usage(config, tmp_path):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("fixture", request=request)

    client = provider_module.LocalProvider(config, tmp_path, "G", httpx.MockTransport(handle))
    with pytest.raises(httpx.ReadTimeout):
        client.complete([], {}, tmp_path)
    client.close()
    trace = provider_module.read_events(tmp_path / "budget-preflights.jsonl")[-1]
    assert trace["status"] == "STOPPED_BEFORE_GENERATION"
    assert trace["error_type"] == "ReadTimeout" and "prompt_tokens" not in trace
    assert calls == ["/tokenize"]
    assert not (tmp_path / "provider-ledger.jsonl").exists()


def test_budget_notice_preserves_sources_does_not_accumulate_and_uses_batch_limit(config, tmp_path):
    original = [{"role": "user", "content": "FIRST\ncomplete source\nLAST"}]
    assert runner.request_messages(original, config, tmp_path, "G") is original
    config.update(host_budget_observation=True, new_model_tokens_authorized=20000)
    ledger = tmp_path / "provider-ledger.jsonl"
    for event in [reserved("A", "A-001"), settled("A-001", 14000, 1000)]:
        provider_module.append_event(ledger, event)
    first = runner.request_messages(original, config, tmp_path, "G")
    assert len(first) == 2 and first[0] == original[0] and len(original) == 1
    assert '"raw_tokens_remaining_before_next_input": 5000' in first[-1]["content"]
    assert '"session_raw_tokens_used": 0' in first[-1]["content"]
    for event in [reserved("G", "G-002"), settled("G-002", 1000, 100)]:
        provider_module.append_event(ledger, event)
    second = runner.request_messages(original, config, tmp_path, "G")
    assert len(second) == 2 and second[0] == original[0]
    assert '"raw_tokens_remaining_before_next_input": 3900' in second[-1]["content"]
    assert '"raw_tokens_remaining_before_next_input": 5000' in first[-1]["content"]


def test_bootstrap_only_changes_detail_prefetch(config: dict, tmp_path: Path) -> None:
    (tmp_path / "details.md").write_text("detailed current source\n")
    head = {"schema_version": "host-cognitive-state-v1", "scope": "TASK",
            "authority": "HOST_WORKING", "state_id": "s", "state_version_id": "v",
            "status": "ACTIVE", "version": 1, "payload": {runner.FIELD: {
        "owner": config["experiment_id"], "l1": "short", "l2": {"path": "details.md",
                               "sha256": runner.sha(tmp_path / "details.md")}}}}
    a = runner.assemble_bootstrap(head, tmp_path, "A", config)
    b = runner.assemble_bootstrap(head, tmp_path, "B", config)
    detail = a.pop("prefetched_detail")
    assert a == b and detail["text"] == "detailed current source\n"
    (tmp_path / "details.md").write_text("changed")
    with pytest.raises(provider_module.LocalGateError, match="VERSION_UNAVAILABLE"):
        runner.assemble_bootstrap(head, tmp_path, "B", config)


def test_restore_fails_on_warning_and_path_escape(config: dict, tmp_path: Path) -> None:
    head = {"status": "ACTIVE", "version": 1, "payload": {}, "warnings": ["revoked"]}
    with pytest.raises(provider_module.LocalGateError, match="RESTORE_NOT_USABLE"):
        runner.assemble_bootstrap(head, tmp_path, "A", config)
    head = {"schema_version": "host-cognitive-state-v1", "scope": "TASK",
            "authority": "HOST_WORKING", "state_id": "s", "state_version_id": "v",
            "status": "ACTIVE", "version": 1, "payload": {runner.FIELD: {
        "owner": config["experiment_id"], "l1": "short",
        "l2": {"path": "../private", "sha256": "unknown"}}}}
    with pytest.raises(provider_module.LocalGateError, match="OUTSIDE_SNAPSHOT"):
        runner.assemble_bootstrap(head, tmp_path, "B", config)


def test_source_writes_and_governance_are_denied(tmp_path: Path) -> None:
    for relative in ("../escape", "/absolute", "sources/input.md", ".env", "frozen.md"):
        with pytest.raises(ValueError):
            runner.write_artifact(tmp_path, relative, "changed", {"frozen.md": "sha"})
    called = []
    result = runner.dispatch(tmp_path, {}, {"milai_evidence_revoke": {}},
                             lambda *args: called.append(args), {"tool": "mcp_call",
                             "arguments_json": json.dumps({"name": "milai_evidence_revoke"})})
    assert result["status"] == "DENIED" and not called


def test_no_paid_authorization(config: dict, tmp_path: Path) -> None:
    config["paid_model_allocations_authorized"] = 1
    with pytest.raises(provider_module.LocalGateError, match="PAID_CALLS_FORBIDDEN"):
        provider_module.LocalProvider(config, tmp_path, "G")


@pytest.mark.parametrize("name", ["milai_proposals_list", "milai_deletion_status_get",
                                  "milai_namespace_cleanup_status"])
def test_public_read_only_catalog_names_remain_callable(tmp_path: Path, name: str) -> None:
    called = []

    def call(tool: str, args: dict) -> dict:
        called.append((tool, args))
        return {"status": "TEST_READ"}

    result = runner.dispatch(tmp_path, {}, {name: {"name": name}}, call, {
        "tool": "mcp_call", "arguments_json": json.dumps({"name": name, "arguments": {}})})
    assert result["status"] == "TEST_READ" and called == [(name, {})]
