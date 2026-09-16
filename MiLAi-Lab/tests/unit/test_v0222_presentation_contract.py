"""Pure reversible presentation over synthetic and all 96 previously exposed references."""

import copy
import hashlib
import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from test_v0222_boundary_contract import fixture

from v0220_wire_contract import encoded, fingerprint
from v0222_boundary_contract import transform
from v0222_presentation_contract import (
    PresentationContractError,
    audit_presentation,
    present,
)

FROZEN = Path("/cra/memory/mx_memory/evidence/v0222/20260911-http-r1/full-reference")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("PURE_PRESENTATION_TEST_FORBIDS_NETWORK")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def serialize(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def initial(body):
    return json.loads(body["messages"][1]["content"])


def set_initial(body, value):
    body["messages"][1]["content"] = serialize(value)


def finish_schema():
    return {
        "type": "object",
        "required": ["action", "arguments"],
        "additionalProperties": False,
        "properties": {
            "action": {"const": "finish"},
            "arguments": {
                "type": "object",
                "required": ["message"],
                "additionalProperties": False,
                "properties": {"message": {"type": "string"}},
            },
        },
    }


def single_finish():
    body, _, _ = fixture()
    value = initial(body)
    value["authorized_intent"] = {
        "authorized_action": {"action": "finish", "arguments": {"message": "  Finished.\n "}}
    }
    set_initial(body, value)
    body["response_format"]["json_schema"]["schema"] = finish_schema()
    return body


def chain(turn, *, writes=2):
    body, _, _ = fixture()
    value = initial(body)
    value["authorized_intent"] = {
        "instruction": "Original chain instruction. Read public versions; finish after readback.",
        "ordered_writes": [
            {"object_id": f"synthetic-{i}", "data": {"text": ' café\n\t "quoted" \\ '}}
            for i in range(writes)
        ],
    }
    set_initial(body, value)
    for index in range(turn - 1):
        body["messages"].extend(
            [
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"action": "read", "arguments": {"resource": "records"}}, indent=2
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "tool_result": {
                                "status": "PUBLIC_OBSERVATION",
                                "version": index,
                                "content": {"authorized_intent": "ordinary nested business field"},
                            }
                        },
                        ensure_ascii=True,
                        indent=1,
                    ),
                },
            ]
        )
    body["messages"].append(
        {
            "role": "user",
            "content": json.dumps(
                {
                    "remaining_generation_opportunities": 5 - turn,
                    "final_delivery_reservation": 1,
                    "last_completed_public_observation": {
                        "version": turn - 1,
                        "version_domain": "WORLD",
                    },
                }
            ),
        }
    )
    if turn == 4:
        body["response_format"]["json_schema"]["schema"] = finish_schema()
    return body


def assert_exact_inverse(body):
    before = copy.deepcopy(body)
    result = present(body)
    assert serialize(body) == serialize(before)
    assert result is not body and result["messages"] is not body["messages"]
    audit = audit_presentation(body, result)
    assert audit["status"] == "PRESENTATION_CONTRACT_PASS"
    assert all(audit["checks"].values())
    assert serialize(result["messages"][2:-1]) == serialize(body["messages"][2:])
    assert serialize(result["messages"][0]) == serialize(body["messages"][0])
    assert serialize({k: v for k, v in result.items() if k != "messages"}) == serialize(
        {k: v for k, v in body.items() if k != "messages"}
    )
    moved = json.loads(result["messages"][-1]["content"])
    assert moved == {"authorized_intent": initial(body)["authorized_intent"]}
    restored = copy.deepcopy(result)
    remainder = json.loads(restored["messages"][1]["content"])
    remainder["authorized_intent"] = json.loads(restored["messages"].pop()["content"])[
        "authorized_intent"
    ]
    set_initial(restored, remainder)
    assert serialize(restored) == serialize(body)
    splice = audit["reversible_diff"]["content_splice"]
    old = body["messages"][1]["content"]
    start = splice["start_character"]
    assert old[start : start + len(splice["removed"])] == splice["removed"]
    assert (
        old[:start] + splice["added"] + old[start + len(splice["removed"]) :]
        == (result["messages"][1]["content"])
    )
    assert splice["start_utf8_byte"] == len(old[:start].encode())
    assert audit["original_request"]["utf8_bytes"] == len(serialize(body).encode())
    assert audit["presented_request"]["utf8_bytes"] == len(serialize(result).encode())
    return result


@pytest.mark.parametrize(
    "text",
    [
        '  中文 café "quoted" \\ path\nnew\ttab  ',
        "emoji \U0001f600 e\u0301 é\r\n\t",
        "\u0000 still nonempty \u2028",
        " whitespace  ",
    ],
)
def test_full_exact_old_b1_unicode_and_input_isolation(text):
    body, _, _ = fixture(text)
    result = assert_exact_inverse(body)
    assert serialize(result) == serialize(transform(body, "B1"))
    result["messages"][0]["content"] = "caller mutation"
    assert body["messages"][0]["content"] != "caller mutation"


def test_single_finish_keeps_full_original_action():
    result = assert_exact_inverse(single_finish())
    assert (
        json.loads(result["messages"][-1]["content"])["authorized_intent"]["authorized_action"][
            "action"
        ]
        == "finish"
    )


@pytest.mark.parametrize("kind", ["full", "finish", "p4-first", "p4-history", "p4-final"])
def test_fresh_unsorted_request_audit_survives_existing_transport_save_policy(tmp_path, kind):
    body = {
        "full": lambda: fixture()[0],
        "finish": single_finish,
        "p4-first": lambda: chain(1),
        "p4-history": lambda: chain(3),
        "p4-final": lambda: chain(4),
    }[kind]()
    assert list(body["messages"][1]) == ["role", "content"]
    result = present(body)
    audit = audit_presentation(body, result)
    persisted = []
    for name, value in (("canonical", body), ("presented", result), ("audit", audit)):
        path = tmp_path / (name + ".json")
        path.write_text(encoded(value), encoding="utf-8")
        persisted.append(json.loads(path.read_text(encoding="utf-8")))
    saved_body, saved_result, saved_audit = persisted
    assert list(saved_body["messages"][1]) == ["content", "role"]
    assert saved_body["messages"][1]["content"] == body["messages"][1]["content"]
    assert fingerprint(audit_presentation(saved_body, saved_result)) == fingerprint(saved_audit)
    assert saved_audit["original_request"]["sha256_utf8"] == fingerprint(body)
    assert saved_audit["presented_request"]["sha256_utf8"] == fingerprint(result)
    # Candidate-only reordering remains rejected; saving both uses the already
    # existing transport encoding and is not a license to reorder the contract.
    with pytest.raises(PresentationContractError, match="EXACT_PRESENTATION_TRANSFORM_REQUIRED"):
        audit_presentation(body, saved_result)


@pytest.mark.parametrize("turn", [1, 2, 3, 4])
@pytest.mark.parametrize("writes", [1, 2])
def test_entire_p4_chain_survives_each_turn_and_finish_only(turn, writes):
    body = chain(turn, writes=writes)
    result = assert_exact_inverse(body)
    intent = json.loads(result["messages"][-1]["content"])["authorized_intent"]
    assert len(intent["ordered_writes"]) == writes
    assert all("expected_version" not in row for row in intent["ordered_writes"])
    assert result["messages"][-2] == body["messages"][-1]
    if turn == 4:
        assert result["response_format"]["json_schema"]["schema"] == finish_schema()
    # Repeated calls do not retain a previous prepared prompt or inject extra answers.
    assert serialize(present(body)) == serialize(result)
    with pytest.raises(PresentationContractError):
        present(result)


@pytest.mark.parametrize(
    "stage,index",
    [
        *(("P3", index) for index in range(16)),
        *(("P4", index) for index in range(80)),
    ],
)
def test_all_96_existing_frozen_references_and_persisted_roundtrip(stage, index):
    references = json.loads((FROZEN / f"{stage}-reference-index.json").read_text())
    row = references[index]
    path = Path(row["canonical"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["hashes"]["canonical"]
    body = json.loads(path.read_text())
    result = assert_exact_inverse(body)
    persisted_body = json.loads(encoded(body))
    persisted_result = json.loads(encoded(result))
    assert all(audit_presentation(persisted_body, persisted_result)["checks"].values())
    if stage == "P3" and initial(body)["authorized_intent"]["authorized_action"]["action"] == (
        "put_record"
    ):
        assert encoded(result).encode() == encoded(transform(body, "B1")).encode()
    if stage == "P4":
        assert (
            initial(body)["authorized_intent"]
            == json.loads(result["messages"][-1]["content"])["authorized_intent"]
        )


@pytest.mark.parametrize(
    "damage",
    [
        "no_intent",
        "extra_intent",
        "extra_instruction",
        "missing_resource",
        "duplicate_resource",
        "wrong_origin",
        "wrong_profile",
        "note",
        "intent_not_last",
        "alternate_serialization",
        "duplicate_json_key",
        "nan_json",
        "nonfinite_parameter",
        "invalid_unicode",
        "non_json_container",
        "extra_system",
        "wrong_initial_role",
        "extra_message_key",
        "bad_single_action",
        "float_cas",
        "bool_cas",
        "chain_filled_cas",
        "chain_extra_action",
        "chain_missing_budget",
        "chain_history_reordered",
        "duplicate_tool_key",
    ],
)
def test_reject_structurally_damaged_original_without_repair(damage):
    body = (
        chain(2) if damage.startswith("chain_") or damage == "duplicate_tool_key" else fixture()[0]
    )
    value = initial(body)
    if damage == "no_intent":
        del value["authorized_intent"]
    elif damage == "extra_intent":
        body["messages"].append(
            {
                "role": "user",
                "content": serialize({"authorized_intent": value["authorized_intent"]}),
            }
        )
    elif damage == "extra_instruction":
        value["instruction"] = "extra instructions"
    elif damage == "missing_resource":
        value["observations"].pop()
    elif damage == "duplicate_resource":
        value["observations"][1] = copy.deepcopy(value["observations"][0])
    elif damage in {"wrong_origin", "wrong_profile"}:
        value[damage.removeprefix("wrong_")] = "wrong"
    elif damage == "note":
        value["inherited_note"] = "not allowed"
    elif damage == "intent_not_last":
        value = {
            "authorized_intent": value["authorized_intent"],
            **{k: v for k, v in value.items() if k != "authorized_intent"},
        }
    elif damage == "nonfinite_parameter":
        body["temperature"] = float("inf")
    elif damage == "invalid_unicode":
        body["messages"][0]["content"] = "\ud800"
    elif damage == "non_json_container":
        body["messages"] = tuple(body["messages"])
    elif damage == "extra_system":
        body["messages"].append({"role": "system", "content": "additional instruction"})
    elif damage == "wrong_initial_role":
        body["messages"][1]["role"] = "assistant"
    elif damage == "extra_message_key":
        body["messages"][1]["name"] = "extra"
    elif damage == "bad_single_action":
        value["authorized_intent"]["authorized_action"]["action"] = "read"
    elif damage in {"float_cas", "bool_cas"}:
        value["authorized_intent"]["authorized_action"]["arguments"]["expected_version"] = (
            0.0 if damage == "float_cas" else False
        )
    elif damage == "chain_filled_cas":
        value["authorized_intent"]["ordered_writes"][0]["expected_version"] = 0
    elif damage == "chain_extra_action":
        value["authorized_intent"]["authorized_action"] = {"action": "read"}
    elif damage == "chain_missing_budget":
        body["messages"].pop()
    elif damage == "chain_history_reordered":
        body["messages"][2], body["messages"][3] = body["messages"][3], body["messages"][2]
    elif damage == "duplicate_tool_key":
        body["messages"][3]["content"] = '{"tool_result": {}, "tool_result": {}}'
    set_initial(body, value)
    if damage == "alternate_serialization":
        body["messages"][1]["content"] = json.dumps(value, ensure_ascii=True, indent=2)
    elif damage == "duplicate_json_key":
        body["messages"][1]["content"] = (
            '{"authorized_intent": null, ' + (body["messages"][1]["content"][1:])
        )
    elif damage == "nan_json":
        body["messages"][1]["content"] = body["messages"][1]["content"].replace(
            '"inherited_note": null', '"inherited_note": NaN'
        )
    with pytest.raises(PresentationContractError):
        present(body)


@pytest.mark.parametrize(
    "damage",
    [
        "schema_order",
        "schema_value",
        "parameter",
        "system_instruction",
        "source_cut",
        "intent_instruction",
        "intent_value",
        "cas_fill",
        "next_action",
        "extra_intent",
        "history_cut",
        "history_reordered",
        "tool_content",
        "budget_content",
        "unicode",
    ],
)
def test_audit_rejects_any_unreviewed_presented_change(damage):
    body = chain(3)
    result = present(body)
    if damage == "schema_order":
        schema = result["response_format"]["json_schema"]["schema"]
        schema["properties"] = dict(reversed(list(schema["properties"].items())))
    elif damage == "schema_value":
        result["response_format"]["json_schema"]["schema"]["additionalProperties"] = True
    elif damage == "parameter":
        result["seed"] += 1
    elif damage == "system_instruction":
        result["messages"][0]["content"] += " Copy carefully."
    elif damage == "source_cut":
        value = initial(result)
        value["observations"].pop()
        set_initial(result, value)
    elif damage in {"intent_instruction", "intent_value", "cas_fill", "next_action"}:
        moved = json.loads(result["messages"][-1]["content"])
        intent = moved["authorized_intent"]
        if damage == "intent_instruction":
            intent["instruction"] += " Added guidance."
        elif damage == "intent_value":
            intent["ordered_writes"][0]["data"]["text"] = "short"
        elif damage == "cas_fill":
            intent["ordered_writes"][0]["expected_version"] = 0
        else:
            intent["ordered_writes"] = intent["ordered_writes"][:1]
        result["messages"][-1]["content"] = serialize(moved)
    elif damage == "extra_intent":
        result["messages"].append(copy.deepcopy(result["messages"][-1]))
    elif damage == "history_cut":
        del result["messages"][2:4]
    elif damage == "history_reordered":
        result["messages"][2:4], result["messages"][4:6] = (
            result["messages"][4:6],
            result["messages"][2:4],
        )
    elif damage == "tool_content":
        result["messages"][3]["content"] += " "
    elif damage == "budget_content":
        result["messages"][-2]["content"] += " "
    elif damage == "unicode":
        result["messages"][-1]["content"] = "\udfff"
    with pytest.raises(PresentationContractError):
        audit_presentation(body, result)
