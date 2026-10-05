"""Finite contracts: independent opt-ins, faithful rejection, no new grammar."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest

from milai_lab.contracts.read_protocol import (
    PROFILES,
    READ_CODES,
    SAVE_GUIDANCE,
    ReadProtocolRejected,
    check_frozen,
    freeze_fields,
    nonlegacy,
    present_catalog,
    profile,
    reject,
    save_guidance,
    snapshot_key,
    validate_settings,
)
from milai_lab.providers.chat_bridge import _action_prompt, _action_schema


@pytest.mark.parametrize("enabled", list(itertools.product([False, True], repeat=3)))
def test_independent_profiles_and_frozen_identity(enabled: tuple[bool, ...]) -> None:
    settings: dict[str, Any] = {
        "memory_reader_policy": "bounded_evidence_v1",
        "memory_mutation_contract": "event_bound_v1",
        "memory_candidate_contract": "read_handle_v1",
        **{
            key: PROFILES[key] if active else "legacy"
            for key, active in zip(PROFILES, enabled, strict=True)
        },
    }
    assert validate_settings(settings)
    catalog = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo",
                "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
        }
    ]
    frozen = {"config": settings, "tool_catalog": catalog, **freeze_fields(settings, catalog)}
    check_frozen(frozen)
    if any(enabled):
        assert frozen["read_protocol_presentation"]["catalog_version"] == "public_memory_v2"
        frozen["config"]["tool_read_feedback"] = "unsupported-profile"
        with pytest.raises(ValueError, match="PROFILE_INVALID"):
            check_frozen(frozen)
    else:
        assert freeze_fields(settings, catalog) == {}


@pytest.mark.parametrize("name", list(PROFILES))
@pytest.mark.parametrize("value", [None, True, 1, {}, "unknown"])
def test_unknown_values_fail(name: str, value: Any) -> None:
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        profile(name, value)


def test_snapshot_requires_explicit_bound_reader() -> None:
    for absent in ["memory_reader_policy", "memory_mutation_contract", "memory_candidate_contract"]:
        settings = {
            "memory_read_protocol": "selected_snapshot_v1",
            "memory_reader_policy": "bounded_evidence_v1",
            "memory_mutation_contract": "event_bound_v1",
            "memory_candidate_contract": "read_handle_v1",
        }
        del settings[absent]
        with pytest.raises(ValueError, match="REQUIRES_BOUND_READ_HANDLE"):
            validate_settings(settings)


def test_finite_rejection_is_not_string_matching_and_never_echoes_input() -> None:
    for code in READ_CODES:
        with pytest.raises(ValueError) as legacy:
            reject(code, "memory_tools")
        assert type(legacy.value) is ValueError and str(legacy.value) == code
        with pytest.raises(ReadProtocolRejected) as caught:
            reject(code, "memory_tools", "typed_read_v1")
        receipt = caught.value.receipt()
        assert receipt == {
            "ok": False,
            "status": "read_rejected",
            "code": code,
            "origin": "memory_tools",
            "semantic_effect": "none",
        }
        assert len(json.dumps(receipt).encode()) <= 1024
    with pytest.raises(ValueError, match="CONTRACT_INVALID"):
        ReadProtocolRejected("V13_PACKET_OWNER_MISMATCH", "memory_tools")
    with pytest.raises(ValueError, match="KEY_INVALID"):
        snapshot_key("")


def test_generic_receipt_copy_and_legacy_action_bytes() -> None:
    catalog = [
        {
            "type": "function",
            "function": {
                "name": "native_memory",
                "description": "Original contract",
                "parameters": {"type": "object"},
            },
        }
    ]
    before = json.dumps(catalog)
    assert present_catalog(catalog) is catalog
    assert save_guidance() == "" and nonlegacy({}) == {}
    assert _action_prompt(catalog) == _action_prompt(catalog, tool_save_communication="legacy")
    enriched = present_catalog(catalog, "completed_receipt_v1")
    assert enriched[0]["function"]["parameters"] == catalog[0]["function"]["parameters"]
    assert SAVE_GUIDANCE in enriched[0]["function"]["description"]
    assert not {"source_refs", "candidate_handle", "field_support"} & set(
        json.dumps(enriched).split()
    )
    assert _action_schema(catalog, generation_only=True) == _action_schema(
        enriched, generation_only=True
    )
    assert json.dumps(catalog) == before
