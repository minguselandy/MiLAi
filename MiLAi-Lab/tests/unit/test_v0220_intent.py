"""Synthetic independent V2 effect and HTTP-chain auditor tests; no real model calls."""

import copy
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put

from run_v0220_intent import ANNOTATION, actions_for
from v02_local_provider import accounting, read_events
from v0213_provider import MODEL, Provider
from v0218_world import World, digest
from v0220_evidence import read, save
from v0220_intent_audit import audit, effects
from v0220_session import Session


def fixture(tmp_path, outputs=None):
    identity = "synthetic"
    world = World.create(tmp_path / "worlds" / f"{identity}.sqlite", "owned", public())
    initial = world.snapshot()
    wanted = [put(), put("right", 1)]
    spec = {
        "id": identity,
        "scope": "owned",
        "actions": wanted,
        "initial_state_sha256": digest(initial),
        "intent": {"ordered_writes": wanted},
    }
    actions = (
        outputs
        if outputs is not None
        else [
            *wanted,
            {"action": "read", "arguments": {"resource": "records"}},
            {"action": "finish", "arguments": {"message": "Executed the fixture."}},
        ]
    )
    pending = iter(actions)

    def transport(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 123})
        if request.url.path == "/v1/chat/completions":
            value = next(pending)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": 123, "completion_tokens": 42, "total_tokens": 165},
                },
            )
        raise AssertionError("UNEXPECTED_OFFLINE_ROUTE")

    directory = tmp_path / "episodes" / identity
    host = Session(
        world,
        directory,
        episode_id=identity,
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent=spec["intent"],
        validate_binding=lambda: None,
    )
    save(directory / "initial-world.json", initial)
    deadline = time.monotonic() + 30
    result = host.run(
        Provider(
            directory, deadline=deadline, max_requests=4, transport=httpx.MockTransport(transport)
        ),
        deadline=deadline,
    )
    save(directory / "final-world.json", world.snapshot())
    save(directory / "final-ledger.json", world.ledger())
    save(
        directory / "worker-result.json",
        {
            **result,
            "pid": os.getpid(),
            "cost": accounting(read_events(directory / "provider-ledger.jsonl")),
            "unresolved_operations": [],
        },
    )
    return spec, host, initial


def test_exact_full_intent_http_state_receipt_chain(tmp_path):
    spec, host, _ = fixture(tmp_path)
    verdict = audit(tmp_path, spec)
    assert verdict["status"] == "PASS", verdict
    assert verdict["business_attempts"] == verdict["effects"] == 2
    assert verdict["cost"]["requests"] == 4
    assert len(host.world.ledger()) == 2


@pytest.mark.parametrize(
    "mutation", ["value", "order", "extra_effect", "missing_readback", "finish_only"]
)
def test_legality_or_done_cannot_substitute_for_intent_fidelity(tmp_path, mutation):
    writes = [put(), put("right", 1)]
    readback = {"action": "read", "arguments": {"resource": "records"}}
    finish = {"action": "finish", "arguments": {"message": "All complete."}}
    actions = [*writes, readback, finish]
    if mutation == "value":
        writes[0]["arguments"]["data"]["amount"] = 999
    elif mutation == "order":
        actions = [put("right", 0), put("left", 1), readback, finish]
    elif mutation == "extra_effect":
        actions = [*writes, put("left", 2), finish]
    elif mutation == "missing_readback":
        actions = [*writes, finish]
    else:
        actions = [finish]
    spec, host, _ = fixture(tmp_path, actions)
    assert host.rows[-1]["response"]["status"] == "SESSION_FINISHED"
    verdict = audit(tmp_path, spec)
    assert verdict["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["receipt", "scope", "ledger", "readback"])
def test_independent_effect_audit_rejects_tampered_evidence(tmp_path, mutation):
    spec, host, initial = fixture(tmp_path)
    final, ledger, turns = host.world.snapshot(), host.world.ledger(), copy.deepcopy(host.rows)
    if mutation == "receipt":
        turns[0]["response"]["version"] = 2
    elif mutation == "scope":
        final["scope"] = "other"
    elif mutation == "ledger":
        ledger.pop()
    else:
        turns[2]["response"]["content"]["left"]["amount"] = 999
    assert effects(spec, initial, final, ledger, turns)["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["request", "http", "initial_presentation"])
def test_real_input_chain_not_inferred_from_host_intent_file(tmp_path, mutation):
    spec, host, _ = fixture(tmp_path)
    directory = host.directory
    if mutation == "request":
        path = directory / "synthetic-01-request.json"
        data = read(path)
        data["messages"][0]["content"] = "changed policy"
    elif mutation == "http":
        path = directory / "synthetic-01-http.json"
        data = read(path)
        body = json.loads(data["body"])
        body["usage"]["completion_tokens"] = 100
        data["body"] = json.dumps(body)
    else:
        path = directory / "initial-presentation.json"
        data = read(path)
        data["inherited_note"] = "wrong-arm note"
    path.write_text(json.dumps(data))
    assert audit(tmp_path, spec)["status"] == "FAIL"


def test_corpus_conversion_is_explicit_and_does_not_mutate_reference():
    record = {"object_id": "left", **put()["arguments"]["data"]}
    original = copy.deepcopy(record)
    selection = {
        "single": "left",
        "sequence": ["left", "left"],
        "complex": "left",
        "text_path": ["text"],
    }
    actions = actions_for(selection, {"left": record}, "complex_complete_record")
    assert record == original
    assert "object_id" not in actions[0]["arguments"]["data"]
    assert actions[0]["arguments"]["data"]["text"] == original["text"] + ANNOTATION
    assert actions[0]["arguments"]["data"]["extra"] == original["extra"]
