"""Finite synthetic mechanics: no business verifier, source inference or transport."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from milai_lab.contracts.public_memory_contracts import (
    capture_effect,
    check_frozen,
    freeze_fields,
    nonlegacy,
    parameter_guidance,
    profiles,
)
from milai_lab.methods.compact_exact import decode, encode


@pytest.mark.parametrize("name", ["tool_parameter_contract", "observation_capture_feedback"])
@pytest.mark.parametrize("invalid", [True, 1, None, "unknown"])
def test_unknown_profile_is_not_a_legacy_fallback(name: str, invalid: Any) -> None:
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        profiles({name: invalid})


@pytest.mark.parametrize(
    "guide,effect", [(False, False), (True, False), (False, True), (True, True)]
)
def test_independent_profiles_freeze_and_drift(guide: bool, effect: bool) -> None:
    settings = {
        "tool_parameter_contract": "explicit_shape_v1" if guide else "legacy",
        "observation_capture_feedback": "typed_effect_v1" if effect else "legacy",
    }
    catalog = [{"function": {"name": "literal_tool", "parameters": {"type": "object"}}}]
    extra = freeze_fields(settings, catalog)
    assert len(nonlegacy(settings)) == int(guide) + int(effect)
    frozen = {"config": settings, "tool_catalog": catalog, **extra}
    check_frozen(frozen)
    if guide or effect:
        changed = copy.deepcopy(frozen)
        changed["public_memory_contract_presentation"]["catalog_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="FROZEN_CHANGED"):
            check_frozen(changed)
    else:
        assert extra == freeze_fields({}, catalog) == {}
        assert capture_effect({"ok": True}, None) == {}


def test_guide_explains_actual_outer_membership_without_business_values() -> None:
    properties = {
        name: {}
        for name in ["field_support", "semantic_patch", "object_ref", "fields", "content_format"]
    }
    text = parameter_guidance(
        properties,
        receipt_fields={"generic_a": "string", "generic_b": "integer"},
        receipt_contract="explicit_receipt_v1",
        support_contract="direct_support_v1",
        grounding_mode="field_grounded",
    )
    assert "SUBSET of the outer selected source_refs" in text
    assert "serialized into that string, not supplied as an object argument" in text
    assert "generic_a" in text and "generic_b" in text
    assert "scope, basis, kind" in text and "legacy_whole_version_set" in text
    assert "read handle and CAS guards remain" in text
    baseline = parameter_guidance(
        {},
        receipt_fields={},
        receipt_contract="optional",
        support_contract="legacy",
        grounding_mode="ref_only",
    )
    assert "field_support" not in baseline and "object_ref" not in baseline
    assert "generic_a" not in baseline


def test_capture_feedback_is_scoped_acknowledgment_and_never_new_write_count() -> None:
    capture = {
        "ok": True,
        "status": "raw_captured",
        "formation_status": "formed",
        "source_ref": "real-synthetic-id",
    }
    raw = capture_effect(capture, None, "typed_effect_v1")["completed_capture_effect"]
    assert raw["raw_sources_acknowledged"] == 1 and raw["effect"] == "raw_capture_only"
    assert raw["semantic_commit"] == "not_acknowledged_by_capture"
    assert raw["confirmed_observation_count"] is None
    partial = capture_effect(
        capture,
        {
            "ok": False,
            "status": "pending",
            "effect": "memory_projection_only",
            "expected_observation_count": 4,
        },
        "typed_effect_v1",
    )["completed_capture_effect"]
    assert partial["expected_observation_count"] == 4
    assert partial["confirmed_observation_count"] is None
    assert partial["future_maintenance"] == "not_acknowledged_by_capture"


def test_json_dictionary_exact_types_key_order_unicode_arrays_and_reserved_keys() -> None:
    value = {
        "order_z": None,
        "order_a": True,
        "float": 1.0,
        "int": 1,
        "unicode": 'é / e\u0301 / 日本語 / 中文\n"quoted"',
        "scopes": [{"b": 2, "a": 1}, {"a": 1, "b": 2}],
        "repeated": [
            {"source_ref": "source-real-literal", "hash": "9" * 64},
            {"hash": "9" * 64, "source_ref": "source-real-literal"},
        ],
        "literal_encoding_keys": {"o": [True, ["literal"]], "s": 0},
        "missing_vs_null": [{}, {"x": None}],
    }
    before = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    frame = encode(value)
    assert "source-real-literal" in frame["strings"]
    restored = decode(json.loads(json.dumps(frame, sort_keys=True)))
    assert json.dumps(restored, ensure_ascii=False, separators=(",", ":")) == before
    assert type(restored["float"]) is float and type(restored["int"]) is int
    assert list(restored) == list(value)
    assert list(restored["scopes"][0]) != list(restored["scopes"][1])


@pytest.mark.parametrize("index", [True, 0.0, -1, 100000])
@pytest.mark.parametrize("target", ["layout", "string"])
def test_dictionary_indices_are_strict_and_not_tool_argument_coercions(
    index: Any, target: str
) -> None:
    frame = encode({"x": "repeated literal", "y": "repeated literal"})
    if target == "layout":
        frame["root"]["o"][0] = index
    else:
        frame["root"]["o"][1][0]["s"] = index
    with pytest.raises(ValueError, match="INDEX_INVALID"):
        decode(frame)


@pytest.mark.parametrize(
    "fault",
    ["duplicate_key", "duplicate_layout", "duplicate_string", "width", "hash", "node", "nan"],
)
def test_dictionary_corruption_never_silently_restores_an_approximate_dto(fault: str) -> None:
    frame = encode({"x": "repeated literal", "y": "repeated literal"})
    if fault == "duplicate_key":
        frame["key_layouts"][0].append(frame["key_layouts"][0][0])
    elif fault == "duplicate_layout":
        frame["key_layouts"].append(frame["key_layouts"][0])
    elif fault == "duplicate_string":
        frame["strings"].append(frame["strings"][0])
    elif fault == "width":
        frame["root"]["o"][1].pop()
    elif fault == "hash":
        frame["decoded_sha256"] = "0" * 64
    elif fault == "node":
        frame["root"] = {"unrecognized": 1}
    else:
        frame["root"] = float("nan")
    with pytest.raises(ValueError):
        decode(frame)


@pytest.mark.parametrize(
    "guide,effect", [(False, False), (True, False), (False, True), (True, True)]
)
def test_exact_material_factor_has_independent_frozen_codec_identity(
    guide: bool, effect: bool
) -> None:
    settings = {
        "memory_material_profile": "compact_exact_v1",
        "tool_parameter_contract": "explicit_shape_v1" if guide else "legacy",
        "observation_capture_feedback": "typed_effect_v1" if effect else "legacy",
    }
    catalog = [{"function": {"name": "actual_tool"}}]
    frozen = {"config": settings, "tool_catalog": catalog, **freeze_fields(settings, catalog)}
    assert frozen["memory_material_profile"] == "compact_exact_v1"
    assert frozen["memory_exact_presentation"]["format"] == "json_dictionary_v1"
    check_frozen(frozen)
    altered = copy.deepcopy(frozen)
    altered["config"]["memory_material_profile"] = "compact_v1"
    with pytest.raises(ValueError, match="FROZEN_CHANGED"):
        check_frozen(altered)


def test_failed_raw_capture_does_not_acknowledge_a_completed_raw_effect() -> None:
    value = capture_effect({"ok": False, "status": "rejected"}, None, "typed_effect_v1")[
        "completed_capture_effect"
    ]
    assert value["effect"] == value["raw_effect"] == "none"
    assert not value["raw_capture_acknowledged"] and value["raw_sources_acknowledged"] == 0
    assert value["confirmed_observation_count"] is None
