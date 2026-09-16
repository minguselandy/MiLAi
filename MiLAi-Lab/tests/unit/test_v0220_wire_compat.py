"""Dual-contract regression, mock HTTP + real isolated effects; no model calls."""

import copy
import itertools
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0220_action_adapter import public, put
from test_v0220_provider_hardened import reserve

from v02_local_provider import read_events
from v0213_provider import MODEL, payload
from v0218_world import World
from v0220_action_contract import ActionContract
from v0220_evidence import read, save, seal, sha
from v0220_provider_hardened import ProviderStop, usage_state
from v0220_session import Session
from v0220_wire_admission import WireSchemaAdmission
from v0220_wire_contract import WireContractError, compile_contract, fingerprint
from v0220_wire_provider import WireProvider


def unique_public():
    value = public()
    for schema in value["task"]["record_schemas"].values():
        schema["properties"]["extra"]["properties"]["items"]["uniqueItems"] = True
    return value


def test_positive_subsets_preserve_all_valid_values_but_reject_duplicates():
    schema = {"type": "array", "items": {"enum": [1, 2, 3]}, "uniqueItems": True}
    plan = compile_contract(schema)
    for n in range(5):
        for xs in itertools.product([1, 2, 3], repeat=n):
            values = list(xs)
            valid = Draft202012Validator(schema).is_valid(values)
            assert not valid or Draft202012Validator(plan.wire).is_valid(values)
            if valid:
                assert plan.validate_output(json.dumps(values)) == values
            else:
                with pytest.raises(WireContractError, match="OUTPUT_PUBLIC_CONTRACT"):
                    plan.validate_output(json.dumps(values))
    assert schema["uniqueItems"] is True and "uniqueItems" not in plan.wire
    assert plan.manifest()["deferred_checks"][0]["path"] == "/uniqueItems"


@pytest.mark.parametrize("array", [[1, 1.0], [{"a": 1}, {"a": 1}], [["a"], ["a"]]])
def test_json_schema_equality_not_python_string_or_set_equality(array):
    plan = compile_contract({"type": "array", "uniqueItems": True})
    with pytest.raises(WireContractError):
        plan.validate_output(json.dumps(array))


def test_boolean_and_number_distinct_according_to_json_schema():
    assert compile_contract({"type": "array", "uniqueItems": True}).validate_output(
        "[true, 1]"
    ) == [True, 1]


def test_keyword_traversal_preserves_property_names_literals_and_escaped_pointer():
    schema = {
        "type": "object",
        "properties": {
            "uniqueItems": {"type": "string", "enum": ["uniqueItems"]},
            "a/~b": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        },
        "default": {"uniqueItems": True},
        "examples": [{"uniqueItems": False}],
    }
    before = copy.deepcopy(schema)
    plan = compile_contract(schema)
    assert schema == before
    assert plan.wire["properties"]["uniqueItems"] == schema["properties"]["uniqueItems"]
    assert plan.wire["default"] == schema["default"]
    assert plan.wire["examples"] == schema["examples"]
    assert plan.manifest()["deferred_checks"][0]["path"] == "/properties/a~1~0b/uniqueItems"
    retrieved = plan.canonical
    retrieved["properties"].clear()
    assert plan.canonical == before


@pytest.mark.parametrize(
    "schema",
    [
        {"not": {"uniqueItems": True}},
        {"oneOf": [{"uniqueItems": True}, {}]},
        {"if": {"uniqueItems": True}, "then": {"const": []}},
        {"$ref": "https://invalid.example/never-read"},
        {"$defs": {"a": {"uniqueItems": True}}},
        {"contains": {"uniqueItems": True}},
        {"unevaluatedItems": False},
        {"x-unknown": {"uniqueItems": True}},
    ],
)
def test_unreviewed_or_negative_contexts_fail_closed(schema):
    with pytest.raises(WireContractError, match="UNREVIEWED"):
        compile_contract(schema)


@pytest.mark.parametrize("key", ["anyOf", "allOf", "prefixItems"])
def test_positive_combinators_are_transformed(key):
    plan = compile_contract({key: [{"type": "array", "uniqueItems": True}]})
    assert "uniqueItems" not in plan.wire[key][0]
    assert plan.canonical[key][0]["uniqueItems"] is True


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', "NaN", "Infinity", "1e999", "{broken"])
def test_nonfinite_and_duplicate_keys_never_release(raw):
    with pytest.raises(WireContractError):
        compile_contract({}).validate_output(raw)


def test_no_targets_fields_cas_or_identity_contracts_removed():
    contract = ActionContract.from_public(unique_public())
    schema = contract.action_schema()
    plan = compile_contract(schema)
    assert len(plan.wire["anyOf"]) == len(schema["anyOf"])
    assert len(plan.manifest()["deferred_checks"]) == 2
    for field in ["object_id", "tenant", "scope", "version", "operation_id"]:
        invalid = put()
        invalid["arguments"]["data"][field] = "private-sentinel"
        with pytest.raises(WireContractError) as exc:
            plan.validate_output(json.dumps(invalid))
        assert "private-sentinel" not in str(exc.value) + json.dumps(exc.value.issues)
    for bad_version in [True, -1, "1"]:
        invalid = put()
        invalid["arguments"]["expected_version"] = bad_version
        with pytest.raises(WireContractError):
            plan.validate_output(json.dumps(invalid))


def test_request_copy_full_contract_disclosure_and_unchanged_sources():
    schema = ActionContract.from_public(unique_public()).action_schema()
    request = payload(
        [
            {"role": "system", "content": "Keep original policy"},
            {"role": "user", "content": "全部当前来源,不裁剪"},
        ],
        schema,
    )
    before = copy.deepcopy(request)
    plan = compile_contract(schema)
    wire = plan.prepare(request)
    assert request == before
    assert wire["messages"][1:] == before["messages"][1:]
    assert wire["messages"][0]["content"].startswith(before["messages"][0]["content"])
    assert plan.canonical_json in wire["messages"][0]["content"]
    assert wire["response_format"]["json_schema"]["strict"] is True


def mock_provider(tmp_path, outputs, *, history_pending=False, admission=None):
    history = tmp_path / "history.jsonl"
    history.touch()
    if history_pending:
        reserve(history)
    queue, calls = iter(outputs), []

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": MODEL, "max_model_len": 65536}]})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100})
        assert request.url.path == "/v1/chat/completions"
        output = next(queue)
        if isinstance(output, httpx.Response):
            return output
        if isinstance(output, Exception):
            raise output
        raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112},
                "choices": [{"message": {"content": raw}}],
            },
        )

    provider = WireProvider(
        tmp_path / "provider",
        deadline=time.monotonic() + 20,
        max_requests=4,
        historical_ledgers=(history,),
        admission=admission or (lambda *_: None),
        transport=httpx.MockTransport(handler),
    )
    return provider, calls, history


def make_host(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "owned", unique_public())
    return Session(
        world,
        tmp_path / "session",
        episode_id="synthetic",
        profile="INTENT_ORACLE",
        arm="ORACLE",
        intent={"instruction": "Mechanical synthetic actions, not memory"},
        validate_binding=lambda: None,
    )


def test_complete_mock_http_session_real_sqlite_effects_and_receipts(tmp_path):
    host = make_host(tmp_path)
    provider, calls, _ = mock_provider(
        tmp_path,
        [
            put(),
            put("right", 1),
            {"action": "read", "arguments": {"resource": "records"}},
            {"action": "finish", "arguments": {"message": "Done"}},
        ],
    )
    result = host.run(provider, deadline=time.monotonic() + 20)
    assert result["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
    assert len(host.world.ledger()) == 2
    assert host.world.snapshot()["version"] == 2
    assert usage_state(read_events(provider.provider.ledger))["known_raw_tokens"] == 448
    assert len([r for r in calls if r.url.path == "/v1/chat/completions"]) == 4
    bindings = list(provider.root.glob("contract-*-binding.json"))
    assert len(bindings) == 4
    for path in bindings:
        binding = read(path)
        matching = [
            r
            for r in calls
            if r.url.path == "/v1/chat/completions"
            and fingerprint(json.loads(r.content)) == binding["wire_request_sha256"]
        ]
        assert len(matching) == 1


def test_duplicate_items_block_before_dispatch_but_usage_is_preserved(tmp_path):
    host = make_host(tmp_path)
    invalid = put()
    invalid["arguments"]["data"]["extra"]["items"] = ["a", "a"]
    provider, calls, _ = mock_provider(tmp_path, [invalid])
    result = host.run(provider, deadline=time.monotonic() + 20)
    assert result["status"] == "FAIL_CLOSED" and not host.world.ledger()
    assert host.world.snapshot()["version"] == 0
    state = usage_state(read_events(provider.provider.ledger))
    assert state["known_raw_tokens"] == 112 and not state["unresolved_reservations"]
    assert len([r for r in calls if r.url.path == "/v1/chat/completions"]) == 1
    assert read(next(provider.root.glob("*-failure.json")))["released_to_host"] is False
    with pytest.raises(ProviderStop, match="STOPPED_NO_RETRY"):
        provider.generate("synthetic", payload([], host.contract.action_schema()))


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500, json={"error": {"message": ""}}),
        httpx.ReadTimeout("private"),
        httpx.Response(200, json={"choices": []}),
    ],
)
def test_transport_unknown_remains_unknown_without_retry(tmp_path, failure):
    provider, calls, _ = mock_provider(tmp_path, [failure])
    provider.verify()
    with pytest.raises(ProviderStop):
        provider.generate("synthetic", payload([], {"type": "object"}))
    with pytest.raises(ProviderStop, match="NO_RETRY"):
        provider.generate("synthetic", payload([], {"type": "object"}))
    assert usage_state(read_events(provider.provider.ledger))["actual_total_raw_tokens"] is None
    assert len([r for r in calls if r.url.path == "/v1/chat/completions"]) == 1
    provider.close()


def test_history_unknown_blocks_even_compatible_wire_with_no_generation(tmp_path):
    provider, calls, history = mock_provider(tmp_path, [], history_pending=True)
    before = history.read_bytes()
    provider.verify()
    with pytest.raises(ProviderStop, match="UNSETTLED_USAGE"):
        provider.generate("synthetic", payload([], {"type": "array", "uniqueItems": True}))
    assert history.read_bytes() == before
    assert [r.url.path for r in calls] == ["/v1/models"]
    provider.close()


def test_cas_still_rejected_no_silent_latest_version_or_retry(tmp_path):
    host = make_host(tmp_path)
    host.world.publish(event_id="new-observation", current={"authorized": False})
    provider, calls, _ = mock_provider(tmp_path, [put()])
    result = host.run(provider, deadline=time.monotonic() + 20)
    assert result["status"] == "PROTOCOL_REJECTION_STOP"
    assert result["code"] == "VERSION_CONFLICT" and host.world.snapshot()["records"] == {}
    assert len([r for r in calls if r.url.path == "/v1/chat/completions"]) == 1


def admission_fixture(tmp_path, mutate=None):
    root = tmp_path / "cpu-evidence"
    roots = ["synthetic-a", "synthetic-b", "synthetic-c", "synthetic-d"]
    identity = {"synthetic_identity": "never a live backend"}
    seal(
        root,
        entries=[],
        inputs=[],
        contract={
            "revision": "UNIQUE_ITEMS_RUNTIME_V1",
            "roots": roots,
            "public_contract_unchanged": True,
            "backend_identity": identity,
        },
    )
    inventory, probes, requests = [], [], []
    for key in roots:
        for mode in ("full", "finish"):
            schema = {
                "type": "object",
                "properties": {
                    "target": {"const": key},
                    "mode": {"const": mode},
                    "values": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                },
            }
            original = payload([{"role": "user", "content": "CPU fixture"}], schema)
            plan = compile_contract(schema)
            wire = plan.prepare(original)
            entry_id = key + "-" + mode
            for suffix, body in (("canonical", original), ("wire", wire)):
                save(root / "requests" / (entry_id + "-" + suffix + ".json"), body)
                probes.append(
                    {
                        "id": entry_id + "-" + suffix,
                        "counts": {
                            "engine_submissions": 0,
                            "input_validation_entered": 1,
                            "post_validation_reached": 1,
                        },
                        "observed": {
                            "cause_message": "CPU_PROBE_STOP_AFTER_PARAMETER_VALIDATION_NO_ENGINE"
                        },
                    }
                )
            inventory.append(
                {
                    "id": entry_id,
                    "canonical_request_sha256": fingerprint(original),
                    "wire_request_sha256": fingerprint(wire),
                    "contract": plan.manifest(),
                }
            )
            requests.append(original)
    result = {
        "all_wire_cpu_pass": True,
        "all_local_semantic_checks_pass": True,
        "model_requests": 0,
    }
    if mutate:
        mutate(inventory, probes, result)
    for name, value in (("inventory", inventory), ("probes", probes), ("result", result)):
        save(root / (name + ".json"), value)
    hashes = {
        name: sha(root / name)
        for name in ("manifest.json", "result.json", "inventory.json", "probes.json")
    }
    return root, hashes, identity, requests


def test_sealed_wire_cpu_admission_preserves_prompt_freedom_not_option_drift(tmp_path):
    root, hashes, identity, requests = admission_fixture(tmp_path)
    gate = WireSchemaAdmission(root, hashes=hashes, identity=lambda: identity)
    for original in requests:
        original["messages"] = [{"role": "user", "content": "Different complete legal history"}]
        plan = compile_contract(original["response_format"]["json_schema"]["schema"])
        gate(original, plan.prepare(original))
    request = copy.deepcopy(requests[0])
    request["structured_outputs"] = {"regex": ".*"}
    with pytest.raises(ProviderStop, match="OPTIONS"):
        gate(
            request,
            compile_contract(request["response_format"]["json_schema"]["schema"]).prepare(request),
        )


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda inv, probes, result: inv.pop(), "INCOMPLETE_WIRE_MATRIX"),
        (lambda inv, probes, result: probes.pop(), "INCOMPLETE_WIRE_CPU_EVIDENCE"),
        (
            lambda inv, probes, result: probes[-1]["counts"].update(post_validation_reached=0),
            "NOT_PASS",
        ),
        (
            lambda inv, probes, result: probes[-1]["counts"].update(engine_submissions=1),
            "CPU_BOUNDARY",
        ),
        (lambda inv, probes, result: result.update(all_wire_cpu_pass=False), "NOT_ADMITTED"),
        (
            lambda inv, probes, result: inv[0]["contract"].update(revision="changed"),
            "COMPILER_BINDING",
        ),
    ],
)
def test_any_incomplete_or_failed_root_blocks_otherwise_valid_pair(tmp_path, mutation, expected):
    root, hashes, identity, requests = admission_fixture(tmp_path, mutation)
    request = requests[0]
    with pytest.raises(ProviderStop, match=expected):
        WireSchemaAdmission(root, hashes=hashes, identity=lambda: identity)(
            request,
            compile_contract(request["response_format"]["json_schema"]["schema"]).prepare(request),
        )


def test_backend_drift_blocks_before_http(tmp_path):
    root, hashes, _, requests = admission_fixture(tmp_path)
    request = requests[0]
    with pytest.raises(ProviderStop, match="BACKEND_CHANGED"):
        WireSchemaAdmission(root, hashes=hashes, identity=lambda: {"changed": True})(
            request,
            compile_contract(request["response_format"]["json_schema"]["schema"]).prepare(request),
        )


def test_prompt_or_canonical_wire_drift_is_not_silent_contract_lowering(tmp_path):
    root, hashes, identity, requests = admission_fixture(tmp_path)
    request = requests[0]
    wire = compile_contract(request["response_format"]["json_schema"]["schema"]).prepare(request)
    wire["messages"][0]["content"] = "Omit the complete public contract"
    with pytest.raises(ProviderStop, match="UNREVIEWED_WIRE_OR_PROMPT"):
        WireSchemaAdmission(root, hashes=hashes, identity=lambda: identity)(request, wire)
