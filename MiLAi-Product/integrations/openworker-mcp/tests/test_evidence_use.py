from __future__ import annotations

import json

import pytest

from milai_openworker_mcp.evidence_use import (
    EvidenceUseValidationError,
    apply_evidence_use_protocol,
    apply_ledger_final_protocol,
    evidence_ledger_response_format,
    grounded_evidence_response_format,
    parse_evidence_ledger,
    parse_grounded_evidence_use,
)


def _valid_count() -> dict[str, object]:
    return {
        "disposition": "ANSWERED",
        "answer_text": "There are three: cedar, maple, and pine.",
        "support": [
            {
                "assertion": "The visible evidence names three distinct trees.",
                "evidence_aliases": ["E1", "E2"],
            }
        ],
        "members": [
            {"member": "cedar", "quantity": 1, "evidence_aliases": ["E1"]},
            {"member": "maple", "quantity": 1, "evidence_aliases": ["E1"]},
            {"member": "pine", "quantity": 1, "evidence_aliases": ["E2"]},
        ],
        "calculation": {"expression": "1 + 1 + 1", "result": 3},
        "uncertainties": [],
    }


def test_grounded_protocol_parses_visible_aliases_and_explicit_member_arithmetic() -> None:
    parsed = parse_grounded_evidence_use(
        json.dumps(_valid_count()),
        visible_aliases=("E1", "E2", "C1"),
    )

    assert parsed.disposition == "ANSWERED"
    assert parsed.evidence_aliases == ("E1", "E2")
    assert [item.member for item in parsed.members] == ["cedar", "maple", "pine"]
    assert parsed.to_api()["calculation"] == {"expression": "1 + 1 + 1", "result": 3}


def test_grounded_protocol_rejects_invisible_alias_before_answer_delivery() -> None:
    value = _valid_count()
    value["support"][0]["evidence_aliases"] = ["E9"]  # type: ignore[index]

    with pytest.raises(EvidenceUseValidationError, match="ALIAS_NOT_VISIBLE"):
        parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))


@pytest.mark.parametrize(
    ("expression", "result", "reason"),
    [
        ("1 + 1", 2, "MEMBER_ARITHMETIC_MISMATCH"),
        ("1 + 1 + 1", 4, "ARITHMETIC_MISMATCH"),
        ("sum([1, 1, 1])", 3, "CALCULATION_INVALID"),
    ],
)
def test_grounded_protocol_rejects_inconsistent_or_executable_arithmetic(
    expression: str,
    result: int,
    reason: str,
) -> None:
    value = _valid_count()
    value["calculation"] = {"expression": expression, "result": result}

    with pytest.raises(EvidenceUseValidationError, match=reason):
        parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))


def test_grounded_protocol_does_not_certify_nonanswered_uncertainty() -> None:
    value = _valid_count()
    value["disposition"] = "PARTIAL"

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))

    assert parsed.disposition == "PARTIAL"
    assert parsed.uncertainties == ()


def test_grounded_protocol_accepts_partial_abstention_without_support() -> None:
    value = _valid_count()
    value.update(
        disposition="PARTIAL",
        answer_text="The visible evidence does not establish the requested fact.",
        support=[],
        members=[],
        calculation={"expression": None, "result": None},
        uncertainties=["The requested fact is absent from visible evidence."],
    )

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))

    assert parsed.support == ()
    assert parsed.members == ()


def test_grounded_protocol_allows_explicit_percentage_scale_literal() -> None:
    value = _valid_count()
    value["members"] = [
        {"member": "renovation cost", "quantity": 50_000, "evidence_aliases": ["E1"]},
        {"member": "property price", "quantity": 500_000, "evidence_aliases": ["E2"]},
    ]
    value["calculation"] = {
        "expression": "50000 / 500000 * 100",
        "result": 10,
    }

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))

    assert parsed.calculation.result == 10


def test_grounded_protocol_rejects_calculation_missing_a_member_quantity() -> None:
    value = _valid_count()
    value["members"] = [
        {"member": "renovation cost", "quantity": 50_000, "evidence_aliases": ["E1"]},
        {"member": "property price", "quantity": 500_000, "evidence_aliases": ["E2"]},
    ]
    value["calculation"] = {"expression": "50000 / 5000", "result": 10}

    with pytest.raises(EvidenceUseValidationError, match="MEMBER_ARITHMETIC_MISMATCH"):
        parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))


@pytest.mark.parametrize("result", [2.86, 3, "2.86 weeks", "approximately 3 weeks"])
def test_grounded_protocol_validates_rounded_result(result: str | int | float) -> None:
    value = _valid_count()
    value["members"] = [
        {"member": "elapsed days", "quantity": 20, "evidence_aliases": ["E1"]},
        {"member": "days per week", "quantity": 7, "evidence_aliases": ["E2"]},
    ]
    value["calculation"] = {"expression": "20 / 7", "result": result}

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))

    assert parsed.calculation.result == result


def test_grounded_protocol_validates_converted_elapsed_time_operands() -> None:
    value = _valid_count()
    value["members"] = [
        {"member": "elapsed days", "quantity": 28, "evidence_aliases": ["E1"]},
        {"member": "days per week", "quantity": 7, "evidence_aliases": ["E2"]},
    ]
    value["calculation"] = {"expression": "28 / 7", "result": 4}

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))

    assert parsed.calculation.result == 4


def test_grounded_protocol_rejects_ambiguous_unit_bearing_result() -> None:
    value = _valid_count()
    value["members"] = [
        {"member": "elapsed days", "quantity": 20, "evidence_aliases": ["E1"]},
        {"member": "days per week", "quantity": 7, "evidence_aliases": ["E2"]},
    ]
    value["calculation"] = {
        "expression": "20 / 7",
        "result": "3 weeks or 20 days",
    }

    with pytest.raises(EvidenceUseValidationError, match="CALCULATION_INVALID"):
        parse_grounded_evidence_use(value, visible_aliases=("E1", "E2"))


def test_evidence_use_arms_preserve_direct_and_add_only_selected_contract() -> None:
    payload = {
        "model": "Qwen3.6-35B-A3B-FP8",
        "messages": [{"role": "user", "content": "How many?"}],
        "stream": False,
    }

    direct = apply_evidence_use_protocol(payload, mode="direct", visible_aliases=("E1",))
    inventory = apply_evidence_use_protocol(payload, mode="inventory", visible_aliases=("E1",))
    grounded = apply_evidence_use_protocol(payload, mode="grounded", visible_aliases=("E1",))
    ledger = apply_evidence_use_protocol(payload, mode="ledger", visible_aliases=("E1",))

    assert direct == payload
    assert "response_format" not in inventory
    assert inventory["messages"][0]["role"] == "system"
    assert "E1" in inventory["messages"][0]["content"]
    assert grounded["response_format"] == grounded_evidence_response_format(
        visible_aliases=("E1",)
    )
    assert grounded["messages"][0]["content"].count("GroundedEvidenceUseV01") == 1
    assert ledger["response_format"] == evidence_ledger_response_format(
        visible_aliases=("E1",)
    )
    assert "pass one of a two-pass" in ledger["messages"][0]["content"]
    assert "requires non-empty members and calculation" in ledger["messages"][0]["content"]
    assert "supplied reference date" in grounded["messages"][0]["content"]
    assert "elapsed whole-day quantity" in grounded["messages"][0]["content"]
    assert "never put a date string" in grounded["messages"][0]["content"]
    assert "event and calendar-date descriptions" in grounded["messages"][0]["content"]
    assert "only the converted numeric operands" in grounded["messages"][0]["content"]
    assert "decimal precision it displays" in grounded["messages"][0]["content"]
    assert "percentage" in grounded["messages"][0]["content"]
    assert "duration" in grounded["messages"][0]["content"]
    assert "require visible support for each one" in grounded["messages"][0]["content"]
    assert "career length cannot substitute" in grounded["messages"][0]["content"]
    assert "chronology outranks narrative detail" in grounded["messages"][0]["content"]


def test_ledger_final_protocol_supplies_validated_ledger_as_data() -> None:
    payload = {
        "model": "Qwen3.6-35B-A3B-FP8",
        "messages": [
            {"role": "system", "content": "OpenWorker system policy."},
            {"role": "user", "content": "How many?"},
        ],
        "stream": True,
    }
    ledger_payload = _valid_count()
    del ledger_payload["disposition"]
    del ledger_payload["answer_text"]
    ledger = parse_evidence_ledger(
        ledger_payload, visible_aliases=("E1", "E2")
    )

    final = apply_ledger_final_protocol(
        payload, ledger=ledger, visible_aliases=("E1", "E2")
    )

    assert final["response_format"] == grounded_evidence_response_format(
        visible_aliases=("E1", "E2")
    )
    assert [message["role"] for message in final["messages"]] == ["system", "user"]
    instruction = final["messages"][0]["content"]
    assert "pass two of a two-pass" in instruction
    assert "truth and completeness were not certified" in instruction
    assert "every endpoint required" in instruction
    assert "use visible chronology" in instruction
    assert "MILAI_PROVISIONAL_EVIDENCE_LEDGER_BEGIN" in instruction
    assert '"result":3' in instruction
    assert payload["messages"][0]["content"] == "OpenWorker system policy."


def test_grounded_transport_schema_uses_vllm_supported_keywords() -> None:
    """Runtime validation retains uniqueness without asking xgrammar to enforce it."""

    schema = grounded_evidence_response_format()

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert "uniqueItems" not in keys(schema)

    duplicate = _valid_count()
    duplicate["support"][0]["evidence_aliases"] = ["E1", "E1"]  # type: ignore[index]
    with pytest.raises(EvidenceUseValidationError, match="SCHEMA_INVALID"):
        parse_grounded_evidence_use(duplicate, visible_aliases=("E1", "E2"))


def test_grounded_transport_schema_constrains_aliases_to_reader_inventory() -> None:
    schema = grounded_evidence_response_format(visible_aliases=("E1", "C2", "E1"))
    properties = schema["json_schema"]["schema"]["properties"]

    support_alias = properties["support"]["items"]["properties"]["evidence_aliases"]
    member_alias = properties["members"]["items"]["properties"]["evidence_aliases"]
    assert support_alias["items"]["enum"] == ["E1", "C2"]
    assert member_alias["items"]["enum"] == ["E1", "C2"]


def test_evidence_use_merges_existing_system_message_for_qwen_role_order() -> None:
    payload = {
        "model": "Qwen3.6-35B-A3B-FP8",
        "messages": [
            {"role": "system", "content": "OpenWorker system policy."},
            {"role": "user", "content": "How many?"},
        ],
        "stream": True,
    }

    inventory = apply_evidence_use_protocol(
        payload,
        mode="inventory",
        visible_aliases=("E1", "E2"),
    )

    assert [message["role"] for message in inventory["messages"]] == ["system", "user"]
    assert inventory["messages"][0]["content"].startswith("OpenWorker system policy.")
    assert "Reader-visible alias inventory: E1, E2" in inventory["messages"][0]["content"]
    assert payload["messages"][0]["content"] == "OpenWorker system policy."


def test_grounded_lookup_may_leave_members_and_calculation_empty() -> None:
    value = {
        "disposition": "ANSWERED",
        "answer_text": "Your marker was cedar.",
        "support": [{"assertion": "The marker was cedar.", "evidence_aliases": ["E1"]}],
        "members": [],
        "calculation": {"expression": None, "result": None},
        "uncertainties": [],
    }

    parsed = parse_grounded_evidence_use(value, visible_aliases=("E1",))

    assert parsed.answer_text == "Your marker was cedar."
    assert parsed.members == ()


def test_grounded_protocol_rejects_duplicate_members_and_extra_fields() -> None:
    duplicate = _valid_count()
    duplicate["members"][1]["member"] = " Cedar "  # type: ignore[index]
    with pytest.raises(EvidenceUseValidationError, match="MEMBER_DUPLICATE"):
        parse_grounded_evidence_use(duplicate, visible_aliases=("E1", "E2"))

    extra = _valid_count()
    extra["canonical_changed"] = False
    with pytest.raises(EvidenceUseValidationError, match="SCHEMA_INVALID"):
        parse_grounded_evidence_use(extra, visible_aliases=("E1", "E2"))
