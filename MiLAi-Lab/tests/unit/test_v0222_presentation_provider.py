"""Mock HTTP through the new Provider and original Session/Adapter/SQLite.

The fixture coordinator isolates these layers; it is not a real scope or history
approval. No network, benchmark/model generation, or production root is used.
"""

import copy
import json
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0220_action_adapter import public, put

import v0222_presentation_provider as module
import v0222_presentation_transport as transport_module
from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0218_world import World, digest
from v0220_evidence import read, save
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_session import Session
from v0220_wire_contract import fingerprint
from v0222_presentation_contract import audit_presentation, present
from v0222_presentation_provider import FullProvider
from v0222_presentation_references import prepare_p3, prepare_p4

READBACK = {"action": "read", "arguments": {"resource": "records"}}
FINISH = {"action": "finish", "arguments": {"message": "Complete synthetic records observed."}}


@pytest.fixture(autouse=True)
def no_network_or_real_history(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("ONLY_MOCK_HTTP_ALLOWED")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(
        transport_module, "historical_usage_presentation", lambda _: {"sources": []}
    )


def environment():
    value = public()
    for schema in value["task"]["record_schemas"].values():
        schema["properties"]["text"].update(pattern=r"\S", minLength=1)
        schema["properties"]["extra"]["properties"]["items"]["uniqueItems"] = True
    return value


class FixtureBatch:
    def __init__(self, root, stage, *, variant="full", writes=2):
        self.root, self.episode = root, stage.lower() + "-01"
        root.mkdir()
        actions = [put(), put("right", 1)][:writes]
        self.value = {
            "id": self.episode,
            "stage": stage,
            "root": "SYNTHETIC_ONLY",
            "scope": "new-synthetic-presentation-scope",
            "variant": variant,
            "actions": actions,
            "expected": actions[0] if variant == "full" else FINISH,
            "initial_state_sha256": "OFFLINE_PREPARATION_WILL_RESOLVE",
            "intent": {
                "instruction": "Execute these whole writes in order, read records, then finish.",
                "ordered_writes": [
                    {k: a["arguments"][k] for k in ("object_id", "data")} for a in actions
                ],
            },
        }
        self.plan = {
            "selected_decoder": "D11",
            "selected_presentation": "B1",
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            },
        }
        self.auth, self.events, self.stopped = {"historical": {"sources": []}}, [], None
        self.deadline = time.time() + 120
        self.refs = []

    def spec(self, episode):
        assert episode == self.episode
        return copy.deepcopy(self.value)

    def admit(self, episode):
        if self.stopped:
            raise ProviderStop("FIXTURE_BATCH_STOPPED")
        assert episode == self.episode
        stage = self.value["stage"]
        return {"stage": stage, "cap": 1 if stage == "P3" else 4, "deadline": self.deadline}

    def http_admit(self, episode, *, inflight=False):
        return self.admit(episode)

    def references(self, stage):
        assert stage == self.value["stage"]
        return copy.deepcopy(self.refs)

    def record(self, episode, event):
        assert episode == self.episode
        usage_state([*self.events, event])
        self.events.append(event)

    def stop(self, reason):
        self.stopped = self.stopped or reason


def setup(tmp_path, stage="P4", *, variant="full", writes=2):
    batch = FixtureBatch(tmp_path / "batch", stage, variant=variant, writes=writes)
    directory = batch.root / "references"
    if stage == "P3":
        batch.refs = prepare_p3(directory, batch.value, environment(), lambda: None)
        return batch, None, None
    batch.refs, prepared = prepare_p4(directory, batch.value, environment(), lambda: None)
    batch.value = prepared["spec"]
    world = World.create(
        batch.root / "worlds" / (batch.episode + ".sqlite"), batch.value["scope"], environment()
    )
    host = Session(
        world,
        batch.root / "episodes" / batch.episode,
        episode_id=batch.episode,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=batch.value["intent"],
        validate_binding=lambda: batch.admit(batch.episode),
    )
    return batch, world, host


def mocked(outputs, calls, *, failure=None):
    queue, counted = iter(outputs), None

    def handle(request):
        nonlocal counted
        calls.append((request.url.path, request.content))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if request.url.path == "/tokenize":
            counted = json.loads(request.content)
            return httpx.Response(
                200, json={"count": 100.0 if failure == "tokenize_float" else 100}
            )
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert counted == {k: body[k] for k in TOKENIZE_KEYS}
        if failure == "HTTP500":
            return httpx.Response(500, json={"error": "synthetic"})
        value = next(queue)
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, indent=1)
        return httpx.Response(
            200,
            json={
                "id": "TEST_ONLY_completion",
                "usage": None
                if failure == "missing_usage"
                else {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    return httpx.MockTransport(handle)


def provider_for(batch, world, outputs, calls, **kwargs):
    return FullProvider(
        batch.root / "episodes" / batch.episode / "provider",
        batch=batch,
        episode=batch.episode,
        world=world,
        transport=mocked(outputs, calls, **kwargs),
    )


@pytest.mark.parametrize("writes", [1, 2])
def test_original_session_complete_effect_and_dynamic_presentation(tmp_path, writes):
    batch, world, host = setup(tmp_path, writes=writes)
    initial, initial_messages, calls = world.snapshot(), copy.deepcopy(host.messages), []
    provider = provider_for(batch, world, [*batch.value["actions"], READBACK, FINISH], calls)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert result["completed_turns"] == writes + 2 and result["note_writes"] == 0
    assert (
        effects(batch.value, initial, world.snapshot(), world.ledger(), host.rows)["status"]
        == "PASS"
    )
    assert host.messages[:2] == initial_messages and len(host.messages) == 2 + 2 * (writes + 2)
    assert batch.stopped is None and usage_state(batch.events)["known_raw_tokens"] == 120 * (
        writes + 2
    )
    bindings = [read(p) for p in provider.root.glob("contract-*-binding.json")]
    assert len(bindings) == writes + 2
    for b in bindings:
        assert fingerprint(present(b["original_request"])) == fingerprint(b["presented_request"])
        assert b["presentation_diff"] == audit_presentation(
            b["original_request"], b["presented_request"]
        )
        moved = json.loads(b["presented_request"]["messages"][-1]["content"])
        assert moved == {"authorized_intent": batch.value["intent"]}
    last = max(bindings, key=lambda b: len(b["original_request"]["messages"]))
    assert fingerprint(
        last["original_request"]["response_format"]["json_schema"]["schema"]
    ) == fingerprint(host.contract.action_schema(finish_only=writes == 2))
    assert any(
        fingerprint(b["original_request"]) != fingerprint(read(Path(batch.refs[i]["canonical"])))
        for i in range(1, writes + 2)
        for b in bindings
        if len(b["original_request"]["messages"]) == 3 + 2 * i
    )


@pytest.mark.parametrize("variant", ["full", "finish"])
def test_p3_original_target_or_legal_finish_without_world(tmp_path, monkeypatch, variant):
    batch, _, _ = setup(tmp_path, "P3", variant=variant)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("P3_RUNTIME_MUST_NOT_CREATE_WORLD")

    monkeypatch.setattr(World, "__init__", forbidden)
    output = (
        batch.value["expected"]
        if variant == "full"
        else {"action": "finish", "arguments": {"message": "Another legal finish."}}
    )
    provider = provider_for(batch, None, [output], [])
    body = read(Path(batch.refs[0]["canonical"]))
    before = copy.deepcopy(body)
    provider.verify()
    assert json.loads(provider.generate(batch.episode, body)) == output
    provider.close()
    assert body == before and batch.stopped is None and not (batch.root / "worlds").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_target",
        "wrong_value",
        "CASfloat",
        "schema",
        "unique",
        "early_finish",
        "invalid_json",
        "missing_usage",
        "HTTP500",
        "tokenize_float",
    ],
)
def test_bad_output_not_released_and_accounted(tmp_path, failure):
    batch, world, host = setup(tmp_path)
    initial, calls = world.snapshot(), []
    bad = copy.deepcopy(batch.value["actions"][0])
    if failure == "wrong_target":
        bad["arguments"]["object_id"] = "right"
    elif failure == "wrong_value":
        bad["arguments"]["data"]["text"] = "wrong legal text"
    elif failure == "CASfloat":
        bad["arguments"]["expected_version"] = 0.0
    elif failure == "schema":
        bad["arguments"]["data"]["text"] = " \t\n "
    elif failure == "unique":
        bad["arguments"]["data"]["extra"]["items"] = ["x", "x"]
    elif failure == "early_finish":
        bad = FINISH
    elif failure == "invalid_json":
        bad = "not JSON"
    provider = provider_for(batch, world, [bad], calls, failure=failure)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "FAIL_CLOSED" and result["completed_turns"] == 0
    assert world.snapshot() == initial and world.ledger() == [] and batch.stopped
    assert not list(host.directory.glob("intent-*.json"))
    assert not list(provider.root.glob("contract-*-validation.json"))
    count = sum(route == "/v1/chat/completions" for route, _ in calls)
    assert count == (0 if failure == "tokenize_float" else 1)
    with pytest.raises(ProviderStop, match="STOPPED_NO_RETRY"):
        provider.generate(batch.episode, read(Path(batch.refs[0]["canonical"])))
    assert sum(route == "/v1/chat/completions" for route, _ in calls) == count
    cost = usage_state(batch.events)
    if failure in {"missing_usage", "HTTP500"}:
        assert cost["actual_total_raw_tokens"] is None
    elif failure != "tokenize_float":
        assert cost["known_raw_tokens"] == 120


@pytest.mark.parametrize("failure", ["extra_write", "stale_CAS", "no_readback"])
def test_later_bad_action_preserves_only_first_authorized_effect(tmp_path, failure):
    batch, world, host = setup(tmp_path, writes=1 if failure != "stale_CAS" else 2)
    second = put("right", 1)
    if failure == "stale_CAS":
        second["arguments"]["expected_version"] = 0
    elif failure == "no_readback":
        second = FINISH
    calls = []
    provider = provider_for(batch, world, [batch.value["actions"][0], second], calls)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "FAIL_CLOSED" and result["completed_turns"] == 1
    assert len(world.ledger()) == 1 and set(world.snapshot()["records"]) == {"left"}
    assert usage_state(batch.events)["requests"] == 2 and batch.stopped


@pytest.mark.parametrize("suffix", ["-binding.json", "-validation.json", "-intent-diff.json"])
def test_evidence_save_failure_locks_even_if_failure_report_also_fails(
    tmp_path, monkeypatch, suffix
):
    batch, world, host = setup(tmp_path)
    initial = world.snapshot()
    calls = []
    bad = copy.deepcopy(batch.value["actions"][0])
    if suffix == "-intent-diff.json":
        bad["arguments"]["data"]["text"] = "wrong"
    provider = provider_for(batch, world, [bad], calls)

    def failed_save(path, value):
        if str(path).endswith((suffix, "-failure.json")):
            if str(path).endswith("-intent-diff.json"):
                assert provider.stopped
                assert batch.stopped == "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"
            raise OSError("SIMULATED_DISK_FAILURE")
        save(path, value)

    monkeypatch.setattr(module, "save", failed_save)
    result = host.run(provider, deadline=provider.provider.deadline)
    expected_stop = (
        "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"
        if suffix == "-intent-diff.json"
        else "OSError"
    )
    assert result["status"] == "FAIL_CLOSED" and batch.stopped == expected_stop
    assert world.snapshot() == initial and provider.failure_report_error == "OSError"
    assert usage_state(batch.events)["requests"] == (0 if suffix == "-binding.json" else 1)


@pytest.mark.parametrize("tamper", ["budget", "history", "schema", "wire", "future_turn"])
def test_request_drift_stops_before_next_http(tmp_path, monkeypatch, tamper):
    batch, world, host = setup(tmp_path)
    calls = []
    provider = provider_for(batch, world, [*batch.value["actions"], READBACK, FINISH], calls)
    original = provider.generate

    def changed(session, body):
        body = copy.deepcopy(body)
        if tamper == "budget":
            value = json.loads(body["messages"][-1]["content"])
            value["remaining_generation_opportunities"] = 99
            body["messages"][-1]["content"] = json.dumps(value)
        elif tamper == "history" and provider.turn:
            body["messages"][2]["content"] = "{}"
        elif tamper == "schema":
            body["temperature"] = 0.1
        elif tamper == "future_turn":
            save(host.directory / "turn-04.json", {"turn": 4})
        return original(session, body)

    if tamper == "wire":

        def altered(value):
            value["messages"] = []
            provider._wire_preflight(value)

        provider.provider.preflight = altered
    else:
        monkeypatch.setattr(provider, "generate", changed)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "FAIL_CLOSED" and batch.stopped
    assert usage_state(batch.events)["requests"] == (1 if tamper == "history" else 0)


@pytest.mark.parametrize("tamper", ["scope", "path", "hash"])
def test_world_binding_fails_before_http(tmp_path, tamper):
    batch, world, _ = setup(tmp_path)
    calls = []
    if tamper == "scope":
        world.scope = "wrong"
    elif tamper == "path":
        world.path = batch.root / "unowned.sqlite"
    else:
        batch.value["initial_state_sha256"] = "wrong"
    with pytest.raises(ProviderStop):
        provider_for(batch, world, [], calls)
    assert not calls and batch.stopped


@pytest.mark.parametrize("tamper", ["raw", "action", "turn_number"])
def test_saved_prior_turn_must_match_released_raw_and_action(tmp_path, monkeypatch, tamper):
    batch, world, host = setup(tmp_path)
    calls = []
    provider = provider_for(batch, world, [*batch.value["actions"], READBACK, FINISH], calls)
    original = provider.generate

    def changed(session, body):
        if provider.turn == 1:
            path = host.directory / "turn-01.json"
            row = read(path)
            if tamper == "raw":
                row["raw"] = "{}"
            elif tamper == "action":
                row["action"]["arguments"]["data"]["text"] = "forged"
            else:
                row["turn"] = 2
            path.write_text(json.dumps(row))
        return original(session, body)

    monkeypatch.setattr(provider, "generate", changed)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "FAIL_CLOSED" and batch.stopped
    assert len(world.ledger()) == 1 and usage_state(batch.events)["requests"] == 1


def test_close_failure_sets_permanent_stop(tmp_path, monkeypatch):
    batch, _, _ = setup(tmp_path, "P3")
    provider = provider_for(batch, None, [], [])

    def failed_close():
        raise OSError("SIMULATED_CLIENT_CLOSE_FAILURE")

    monkeypatch.setattr(provider.provider, "close", failed_close)
    with pytest.raises(OSError):
        provider.close()
    assert batch.stopped == "OSError" and provider.stopped and provider.closed


@pytest.mark.parametrize(
    "tamper", ["operation_id", "request_sha256", "before_sha256", "read_content", "read_hash"]
)
def test_first_public_reply_cannot_be_forged_with_matching_outgoing_history(
    tmp_path, monkeypatch, tamper
):
    batch, world, host = setup(tmp_path, writes=1)
    calls = []
    provider = provider_for(batch, world, [*batch.value["actions"], READBACK, FINISH], calls)
    generate = provider.generate
    target_turn = 2 if tamper.startswith("read_") else 1

    def forged(session, body):
        if provider.turn == target_turn:
            path = host.directory / f"turn-{target_turn:02d}.json"
            row = read(path)
            reply = row["response"]
            if tamper == "read_content":
                reply["content"]["left"]["text"] = "forged public read"
                reply["content_sha256"] = digest(reply["content"])
            elif tamper == "read_hash":
                reply["content_sha256"] = "0" * 64
            else:
                reply[tamper] = "FORGED_NOT_ACTUAL" if tamper == "operation_id" else "0" * 64
            path.write_text(json.dumps(row))
            body = copy.deepcopy(body)
            body["messages"][target_turn * 2 + 1]["content"] = json.dumps(
                {"tool_result": reply}
            )
            budget = json.loads(body["messages"][-1]["content"])
            budget["last_completed_public_observation"]["response_sha256"] = digest(reply)
            body["messages"][-1]["content"] = json.dumps(budget)
        return generate(session, body)

    monkeypatch.setattr(provider, "generate", forged)
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "FAIL_CLOSED"
    assert batch.stopped == (
        "ContractError"
        if tamper == "read_hash"
        else "ACTUAL_PUBLIC_RECEIPT_NOT_FROM_COMPLETED_ACTION"
    )
    assert len(world.ledger()) == 1 and usage_state(batch.events)["requests"] == target_turn
    assert sum(path == "/v1/chat/completions" for path, _ in calls) == target_turn


def test_actual_operation_status_reply_preserves_original_public_query(tmp_path):
    batch, world, host = setup(tmp_path, writes=1)
    query = {
        "action": "operation_status",
        "arguments": {"operation_id": batch.episode + ":01"},
    }
    provider = provider_for(batch, world, [*batch.value["actions"], query, READBACK, FINISH], [])
    result = host.run(provider, deadline=provider.provider.deadline)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT" and batch.stopped is None
    assert len(world.ledger()) == 1 and usage_state(batch.events)["requests"] == 4
