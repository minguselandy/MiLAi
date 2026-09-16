"""Selected compiler → MockHTTP → original Session/SQLite → independent audit.

FakeBatch isolates provider/execution integration. It is not a substitute for the
real coordinator's separately tested authorization, cold-process or finite gates.
"""

import copy
import json
import os
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS, payload
from v0218_world import World, digest
from v0220_action_contract import ActionContract
from v0220_evidence import read, save, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_session import Session
from v0220_wire_contract import encoded, fingerprint
from v0222_batch import historical_usage_v0222
from v0222_full_audit import audit
from v0222_full_provider import FullProvider, resolved_spec
from v0222_string_contract import compile_contract

READBACK = {"action": "read", "arguments": {"resource": "records"}}
FINISH = {"action": "finish", "arguments": {"message": "Observed complete synthetic records."}}


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Only MockTransport is allowed in this test")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def environment():
    value = public()
    for schema in value["task"]["record_schemas"].values():
        schema["properties"]["text"].update(pattern=r"\S", minLength=1)
        schema["properties"]["extra"]["properties"]["items"]["uniqueItems"] = True
    return value


def actions():
    result = [put(), put("right", 1)]
    for action in result:
        action["arguments"]["data"]["text"] = "  " + action["arguments"]["data"]["text"] + "\t\n"
    return result


class FakeBatch:
    def __init__(self, root, stage, *, variant="full"):
        self.root, self.events, self.stopped = root, [], None
        root.mkdir(parents=True)
        self.episode = stage.lower() + "-01"
        self.deadline = time.time() + 120
        history = tuple(root / ("synthetic-history-" + str(i) + ".jsonl") for i in range(3))
        for path in history:
            path.touch()
        self.auth = {"historical": historical_usage_v0222(history)}
        spec = {
            "id": self.episode,
            "stage": stage,
            "root": "SYNTHETIC_ONLY",
            "scope": "new-synthetic-scope",
            "actions": actions(),
            "intent": {"ordered_writes": actions()},
            "variant": variant,
            "expected": actions()[0] if variant == "full" else FINISH,
            "initial_state_sha256": "PRESERVED_OLD_SCOPE_DERIVED_VALUE",
        }
        self.plan = {
            "P3": [spec] if stage == "P3" else [],
            "P4": [spec] if stage == "P4" else [],
            "http_identity": {
                "endpoint": ENDPOINT,
                "model": MODEL,
                "context": 65536,
                "version": "0.27.1",
            },
        }
        self.artifacts = {
            "P1_final_selection": {"selected_condition": "D11"},
            "P2_gate": {"status": "G_P2_PASS"},
        }
        self.refs = {"P3": [], "P4": []}

    def admit(self, episode):
        if self.stopped:
            raise ProviderStop("BATCH_STOPPED")
        assert episode == self.episode
        stage = "P4" if self.plan["P4"] else "P3"
        return {"stage": stage, "cap": 4 if stage == "P4" else 1, "deadline": self.deadline}

    def authorize(self, stage):
        assert stage in {"P3", "P4"}
        self.admit(self.episode)
        return self.auth

    def artifact(self, name):
        return copy.deepcopy(self.artifacts[name])

    def references(self, stage):
        return copy.deepcopy(self.refs[stage])

    def record(self, episode, event):
        assert episode == self.episode
        usage_state([*self.events, event])
        self.events.append(event)

    def stop(self, reason):
        self.stopped = self.stopped or reason


def reference(batch, stage, index, canonical, output):
    plan = compile_contract(canonical["response_format"]["json_schema"]["schema"])
    assert plan.validate_output(encoded(output)) == output
    row = {"episode": batch.episode, "stage": stage, "turn": index, "hashes": {}}
    for kind, value in (
        ("canonical", canonical),
        ("wire", plan.prepare(canonical)),
        ("output", {"raw": encoded(output)}),
    ):
        path = batch.root / "reference-requests" / (f"{stage}-{index:02d}.{kind}.json")
        save(path, value)
        row[kind], row["hashes"][kind] = str(path), sha(path)
    batch.refs[stage].append(row)


def p4_setup(tmp_path):
    batch = FakeBatch(tmp_path / "batch", "P4")
    original = batch.plan["P4"][0]
    world = World.create(
        batch.root / "worlds" / (batch.episode + ".sqlite"), original["scope"], environment()
    )
    batch.artifacts["P4_resolved_specs"] = {
        "specs": [{**copy.deepcopy(original), "initial_state_sha256": digest(world.snapshot())}]
    }
    host = Session(
        world,
        batch.root / "episodes" / batch.episode,
        episode_id=batch.episode,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=original["intent"],
        validate_binding=lambda: batch.authorize("P4"),
    )
    save(host.directory / "initial-world.json", world.snapshot())

    class OfflineReference:
        def __init__(self):
            self.outputs = iter([*actions(), READBACK, FINISH])
            self.turn = 0

        def verify(self):
            return {"profile": "OFFLINE_REFERENCE_NOT_MODEL"}

        def generate(self, episode, body):
            self.turn += 1
            value = next(self.outputs)
            reference(batch, "P4", self.turn, body, value)
            return encoded(value)

        def close(self):
            pass

    offline_world = World.create(
        batch.root / "offline-reference.sqlite", original["scope"], environment()
    )
    offline_host = Session(
        offline_world,
        batch.root / "offline-reference-session",
        episode_id=batch.episode,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=original["intent"],
        validate_binding=lambda: None,
    )
    assert offline_host.run(OfflineReference(), deadline=time.monotonic() + 30)["status"] == (
        "SESSION_FINISHED_NOT_TASK_VERDICT"
    )
    assert len(batch.refs["P4"]) == 4 and world.snapshot()["records"] == {}
    return batch, world, host


def p3_setup(tmp_path, variant="full"):
    batch = FakeBatch(tmp_path / "batch", "P3", variant=variant)
    contract = ActionContract.from_public(environment())
    body = payload(
        [
            {"role": "system", "content": "SYNTHETIC INTENT_ORACLE VALIDATE_ONLY; no dispatch."},
            {
                "role": "user",
                "content": encoded({"authorized_action": batch.plan["P3"][0]["expected"]}),
            },
        ],
        contract.action_schema(finish_only=variant == "finish"),
    )
    reference(batch, "P3", 1, body, batch.plan["P3"][0]["expected"])
    return batch, body


def mock_transport(outputs, calls, *, failure=None):
    queue = iter(outputs)
    counted = None

    def handle(request):
        nonlocal counted
        calls.append({"route": request.url.path, "body": request.content})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.27.1"})
        if request.url.path == "/tokenize":
            counted = json.loads(request.content)
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions"
        actual = json.loads(request.content)
        assert counted == {k: actual[k] for k in TOKENIZE_KEYS}
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "HTTP500":
            return httpx.Response(500, json={"error": {"message": ""}})
        value = next(queue)
        # Deliberately different legal JSON formatting from the offline reference.
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, indent=1)
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        if failure == "usage_bound":
            usage = {"prompt_tokens": 99, "completion_tokens": 20, "total_tokens": 119}
        return httpx.Response(
            200,
            json={
                "id": "mock-full-response",
                "usage": (None if failure == "missing_usage" else usage),
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
            },
        )

    return httpx.MockTransport(handle)


def run_p4(batch, world, host, outputs, calls, failure=None):
    provider = FullProvider(
        host.directory / "provider",
        batch=batch,
        episode=batch.episode,
        world=world,
        transport=mock_transport(outputs, calls, failure=failure),
    )
    result = host.run(provider, deadline=provider.provider.deadline)
    save(host.directory / "final-world.json", world.snapshot())
    save(host.directory / "final-ledger.json", world.ledger())
    result.update(pid=os.getpid(), unresolved_operations=host.adapter.journal.unresolved())
    save(host.directory / "worker-result.json", result)
    return provider, result


def test_full_p4_mock_http_original_session_world_and_independent_audit(tmp_path):
    batch, world, host = p4_setup(tmp_path)
    before = copy.deepcopy(batch.plan["P4"][0])
    calls = []
    _, result = run_p4(batch, world, host, [*actions(), READBACK, FINISH], calls)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert result["completed_turns"] == 4 and result["note_writes"] == 0
    verdict = audit(batch, batch.episode)
    assert verdict["status"] == "PASS", verdict["checks"]
    assert all(verdict["checks"][f"actual_session_request_rebuilt_{i}"] for i in range(1, 5))
    assert world.snapshot()["version"] == 2 and len(world.ledger()) == 2
    assert world.snapshot()["records"]["left"]["text"] == actions()[0]["arguments"]["data"]["text"]
    assert batch.plan["P4"][0] == before
    assert (
        resolved_spec(batch, batch.episode)["initial_state_sha256"]
        != before["initial_state_sha256"]
    )
    assert usage_state(batch.events)["known_raw_tokens"] == 480 and batch.stopped is None
    body = read(Path(batch.refs["P4"][1]["canonical"]))
    binding = next(
        read(p)
        for p in (host.directory / "provider").glob("contract-*-binding.json")
        if read(p)["original_request"]["messages"][-1]["content"] == body["messages"][-1]["content"]
    )
    assert fingerprint(binding["original_request"]) != fingerprint(body)


@pytest.mark.parametrize("variant", ["full", "finish"])
def test_p3_validate_only_has_no_world_and_audits(tmp_path, monkeypatch, variant):
    batch, body = p3_setup(tmp_path, variant)

    def forbidden(*args, **kwargs):
        raise AssertionError("P3 may not initialize a World")

    monkeypatch.setattr(World, "__init__", forbidden)
    calls = []
    provider = FullProvider(
        batch.root / "episodes" / batch.episode / "provider",
        batch=batch,
        episode=batch.episode,
        transport=mock_transport([batch.plan["P3"][0]["expected"]], calls),
    )
    provider.verify()
    raw = provider.generate(batch.episode, body)
    provider.close()
    save(
        batch.root / "episodes" / batch.episode / "worker-result.json",
        {
            "status": "VALIDATE_ONLY_PASS",
            "raw": raw,
            "business_dispatches": 0,
            "notebook_writes": 0,
            "pid": os.getpid(),
        },
    )
    assert audit(batch, batch.episode)["status"] == "PASS"
    assert not (batch.root / "worlds").exists()
    assert usage_state(batch.events)["known_raw_tokens"] == 120


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_value",
        "early_finish",
        "whitespace",
        "duplicates",
        "wrong_cas",
        "invalid_json",
        "missing_usage",
        "usage_bound",
        "HTTP500",
        "timeout",
    ],
)
def test_p4_first_bad_output_or_usage_never_reaches_executor(tmp_path, failure):
    batch, world, host = p4_setup(tmp_path)
    initial = world.snapshot()
    bad = copy.deepcopy(actions()[0])
    if failure == "wrong_value":
        bad["arguments"]["data"]["text"] = bad["arguments"]["data"]["text"].strip()
    elif failure == "early_finish":
        bad = FINISH
    elif failure == "whitespace":
        bad["arguments"]["data"]["text"] = " \t\n"
    elif failure == "duplicates":
        bad["arguments"]["data"]["extra"]["items"] = ["x", "x"]
    elif failure == "wrong_cas":
        bad["arguments"]["expected_version"] = 7
    elif failure == "invalid_json":
        bad = "not JSON"
    calls = []
    provider, result = run_p4(batch, world, host, [bad], calls, failure=failure)
    assert result["status"] == "FAIL_CLOSED" and result["completed_turns"] == 0
    assert world.snapshot() == initial and world.ledger() == []
    assert batch.stopped is not None
    assert sum(r["route"] == "/v1/chat/completions" for r in calls) == 1
    assert not list((host.directory / "provider").glob("contract-*-validation.json"))
    assert not list(host.directory.glob("intent-*.json"))
    with pytest.raises(ProviderStop, match="STOPPED_NO_RETRY"):
        provider.generate(batch.episode, read(Path(batch.refs["P4"][0]["canonical"])))
    assert sum(r["route"] == "/v1/chat/completions" for r in calls) == 1
    cost = usage_state(batch.events)
    assert cost["requests"] == 1
    if failure in {"missing_usage", "HTTP500", "timeout"}:
        assert cost["actual_total_raw_tokens"] is None
    else:
        assert cost["known_raw_tokens"] == (119 if failure == "usage_bound" else 120)


def test_stale_second_write_is_not_rebased_or_retried(tmp_path):
    batch, world, host = p4_setup(tmp_path)
    second = copy.deepcopy(actions()[1])
    second["arguments"]["expected_version"] = 0
    calls = []
    _, result = run_p4(batch, world, host, [actions()[0], second], calls)
    assert result["status"] == "FAIL_CLOSED" and result["completed_turns"] == 1
    assert world.snapshot()["version"] == 1 and set(world.snapshot()["records"]) == {"left"}
    assert len(world.ledger()) == 1 and usage_state(batch.events)["requests"] == 2
    assert batch.stopped == "FULL_INTENT_FIDELITY_FAILURE_BEFORE_DISPATCH"


@pytest.mark.parametrize("tamper", ["scope", "path", "derived_hash", "resolved_intent"])
def test_p4_world_and_resolved_spec_are_bound_before_http(tmp_path, tamper):
    batch, world, host = p4_setup(tmp_path)
    if tamper == "scope":
        world.scope = "wrong-scope"
    elif tamper == "path":
        world = World.create(batch.root / "wrong-world.sqlite", world.scope, environment())
    elif tamper == "derived_hash":
        batch.artifacts["P4_resolved_specs"]["specs"][0]["initial_state_sha256"] = "old-hash"
    else:
        batch.artifacts["P4_resolved_specs"]["specs"][0]["actions"][0]["arguments"]["data"][
            "text"
        ] = "changed"
    calls = []
    with pytest.raises(ProviderStop):
        FullProvider(
            host.directory / "provider",
            batch=batch,
            episode=batch.episode,
            world=world,
            transport=mock_transport([], calls),
        )
    assert calls == [] and batch.events == []


def test_p3_legal_but_wrong_value_is_not_repaired_or_passed(tmp_path):
    batch, body = p3_setup(tmp_path)
    bad = copy.deepcopy(actions()[0])
    bad["arguments"]["data"]["text"] = "valid schema but wrong value"
    calls = []
    provider = FullProvider(
        batch.root / "episodes" / batch.episode / "provider",
        batch=batch,
        episode=batch.episode,
        transport=mock_transport([bad], calls),
    )
    try:
        provider.verify()
        with pytest.raises(ProviderStop, match="FIDELITY_FAILURE_BEFORE_DISPATCH"):
            provider.generate(batch.episode, body)
    finally:
        provider.close()
    assert not (batch.root / "worlds").exists()
    assert usage_state(batch.events)["known_raw_tokens"] == 120
    assert not list(provider.root.glob("contract-*-validation.json"))


def test_json_schema_integral_float_cas_is_not_released_to_strict_world(tmp_path):
    batch, world, host = p4_setup(tmp_path)
    bad = copy.deepcopy(actions()[0])
    bad["arguments"]["expected_version"] = 0.0
    # Draft 2020-12 integer includes integral numbers; World intentionally requires int.
    plan = compile_contract(host.contract.action_schema())
    assert plan.validate_output(encoded(bad)) == bad
    initial, calls = world.snapshot(), []
    _, result = run_p4(batch, world, host, [bad], calls)
    assert result["status"] == "FAIL_CLOSED" and result["completed_turns"] == 0
    assert batch.stopped == "WORLD_VERSION_INTEGER_REQUIRED_BEFORE_DISPATCH"
    assert world.snapshot() == initial and world.ledger() == []
    assert usage_state(batch.events)["known_raw_tokens"] == 120
    assert not list(host.directory.glob("intent-*.json"))


def test_auditor_binds_actual_raw_action_even_if_saved_receipts_remain_correct(tmp_path):
    batch, world, host = p4_setup(tmp_path)
    calls = []
    run_p4(batch, world, host, [*actions(), READBACK, FINISH], calls)
    assert audit(batch, batch.episode)["status"] == "PASS"
    reservation = next(e for e in batch.events if e["event"] == "RESERVED")
    provider = host.directory / "provider"
    key = reservation["request_id"]
    forged = copy.deepcopy(actions()[0])
    forged["arguments"]["data"]["text"] = "a different schema-valid synthetic business value"
    raw = json.dumps(forged)
    turn_path = host.directory / "turn-01.json"
    turn = read(turn_path)
    original_action, original_receipt = (
        copy.deepcopy(turn["action"]),
        copy.deepcopy(turn["response"]),
    )
    turn["raw"] = raw
    http_path, visible_path = provider / (key + "-http.json"), provider / (key + "-visible.json")
    http = read(http_path)
    envelope = json.loads(http["body"])
    envelope["choices"][0]["message"]["content"] = raw
    http["body"] = json.dumps(envelope)
    # Corrupt only this test's owned synthetic raw evidence. Keep the actual effects,
    # action annotation and receipt unchanged to defeat a merely shallow comparison.
    turn_path.write_text(json.dumps(turn))
    http_path.write_text(json.dumps(http))
    visible_path.write_text(json.dumps({"content": raw}))
    assert read(turn_path)["action"] == original_action
    assert read(turn_path)["response"] == original_receipt
    verdict = audit(batch, batch.episode)
    assert verdict["status"] == "FAIL"
    assert verdict["checks"]["raw_turns_one_to_one"] is True
    assert verdict["checks"]["independent_effect_replay"] is True
    assert verdict["checks"]["raw_actions_independently_decoded"] is False
    assert verdict["checks"]["raw_business_intent_fidelity"] is False
    assert verdict["checks"]["actual_session_request_rebuilt_2"] is False
