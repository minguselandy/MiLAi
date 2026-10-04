"""Independent default-off public parameter and completed-capture explanations.

Presentation only: no argument repair, validation change, observation or source read.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

DECODE_GUIDANCE = (
    "json_dictionary_v1: every encoded object is {'o':[layout_index,values]} where "
    "key_layouts[index] gives ALL original keys IN ORDER paired with values; "
    "{'s':index} gives the complete literal strings[index]. Lists preserve order; "
    "other scalars keep type/value. Decode recursively. Integer indices are zero-based. "
    "Use decoded actual Source IDs/handles/string tool arguments, never indices or "
    "these encoding objects. Original DTOs, ranges, omissions and hash identities remain."
)


PROFILES = {
    "tool_parameter_contract": "explicit_shape_v1",
    "observation_capture_feedback": "typed_effect_v1",
}
CAPTURE_GUIDANCE = (
    "completed_capture_effect describes only the already completed capture whose receipts "
    "are shown. raw_capture_only acknowledges an archived Source, not semantic memory. "
    "memory_projection_only acknowledges deterministic literal projections only when "
    "their actual receipt is complete; its confirmed count is null for pending/partial "
    "writes. Unknown observations, replay and missing projections remain explicit. "
    "A separate completed semantic mutation receipt may acknowledge memory_only storage; "
    "capture does not supply that receipt. No capture receipt confirms future maintenance, "
    "whole-turn coverage, prose entailment, current applicability or business authority."
)


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def profile(name: str, value: Any = "legacy") -> str:
    if name not in PROFILES or type(value) is not str or value not in {"legacy", PROFILES[name]}:
        raise ValueError("PUBLIC_MEMORY_CONTRACT_PROFILE_INVALID:" + name)
    return value


def profiles(settings: dict[str, Any]) -> dict[str, str]:
    return {key: profile(key, settings.get(key, "legacy")) for key in PROFILES}


def nonlegacy(settings: dict[str, Any]) -> dict[str, str]:
    return {key: value for key, value in profiles(settings).items() if value != "legacy"}


def parameter_guidance(
    properties: dict[str, Any],
    *,
    receipt_fields: dict[str, str],
    receipt_contract: str,
    support_contract: str,
    grounding_mode: str,
) -> str:
    """Describe only existing public parameters and the existing Service contract."""
    guidance = (
        "[explicit_shape_v1] Supply actual parameter values of their public types. "
        "content is always a STRING; a JSON object required inside content must be "
        "serialized into that string, not supplied as an object argument. "
        "Neither support metadata nor a Source DTO replaces a parameter value. "
        "No value, source, union, selection, read, coercion or retry is automatic."
    )
    if "field_support" in properties and support_contract == "direct_support_v1":
        guidance += (
            " field_support has exactly content, scope, basis, kind. Each entry is exactly "
            "{source_refs:[actual string leaf IDs]} or {reuse_support_from:actual string "
            "candidate_handle}. EVERY explicit field leaf set must be nonempty, contain "
            "no duplicate IDs, and be a SUBSET of the outer selected source_refs. "
            "Outer source_refs explicitly contains ALL used leaves, including all leaves "
            "reused from a whole field. Reuse is allowed only for that same actually "
            "read candidate and exactly unchanged whole field under the existing "
            "strict canonical JSON comparison, with current revision/version "
            "and leaf hashes still matching; changed fields cannot reuse. Old versions "
            "without field maps permit only their entire legacy_whole_version_set. "
            "user_statement requires ALL outer selected Sources to have user role, "
            "tool_observation requires ALL outer selected Sources to have tool role; "
            "plan/inference permits mixed roles without asserting entailment. Source "
            "owner/hash, actual public trigger, read handle and CAS guards remain. "
            "Trigger metadata authorizes the turn, while a corresponding actual Human "
            "body remains freely selectable support for a fact it expresses. "
            "Metadata, prefixes and index references do not prove a full read or entailment."
        )
    if "semantic_patch" in properties:
        guidance += (
            " semantic_patch contains only actual changed content/scope/basis/kind values. "
            "source_refs and field_support are outer siblings, never patch fields; "
            "scope follows the existing named-key merge rule."
        )
    if "object_ref" in properties:
        guidance += (
            " object_ref is the actual STRING ID from the selected Source companion, "
            "not the object_ref evidence DTO or a dictionary/index argument."
        )
    if "fields" in properties:
        guidance += (
            " fields contains only the finite names/types in its actual public schema; "
            "ordinary prose has no operational fields. Nonempty fields require the "
            "existing matching tool Source/object_ref and tool_observation basis."
        )
    if "content_format" in properties and receipt_contract == "explicit_receipt_v1":
        guidance += (
            " For an applicable explicit tool receipt, content_format is the literal "
            "receipt_json_v1. Both fields and the JSON object DECODED FROM content "
            "must contain exactly the complete declared receipt fields; that decoded "
            "object may additionally contain notes:string only. Field-grounded mode "
            "compares the original observed fields and matching body literals. Ref-only "
            "mode keeps claims unchecked. This does not construct or fill missing values. "
            "Actual declared receipt contract: "
            + canonical(
                {
                    "field_types": receipt_fields,
                    "grounding_mode": grounding_mode,
                    "content_argument_type": "string",
                    "decoded_optional_fields": {"notes": "string"},
                }
            )
        )
    return guidance


def capture_effect(
    capture: dict[str, Any],
    projection: dict[str, Any] | None,
    setting: Any = "legacy",
) -> dict[str, Any]:
    """Package actual returned receipts only; do not inspect bodies or query the Store."""
    if profile("observation_capture_feedback", setting) == "legacy":
        return {}
    complete = projection is not None and projection.get("ok") is True
    value = {
        "schema": "completed_capture_effect_v1",
        "scope": "this completed capture only",
        "source_ref": capture.get("source_ref"),
        "raw_status": capture.get("status"),
        "raw_capture_acknowledged": capture.get("ok") is True,
        "raw_sources_acknowledged": 1 if capture.get("ok") is True else 0,
        "raw_effect": "raw_capture_only" if capture.get("ok") is True else "none",
        "raw_formation_status": capture.get("formation_status"),
        "effect": projection.get("effect")
        if projection is not None
        else ("raw_capture_only" if capture.get("ok") is True else "none"),
        "observation_status": projection.get("status") if projection is not None else None,
        "projection_id": projection.get("projection_id") if projection is not None else None,
        "confirmed_observation_count": projection.get("observation_count")
        if complete and projection is not None
        else None,
        "expected_observation_count": projection.get("expected_observation_count")
        if projection is not None
        else None,
        "projection_current_verified": projection.get("current_verified")
        if projection is not None
        else None,
        "semantic_commit": "not_acknowledged_by_capture",
        "future_maintenance": "not_acknowledged_by_capture",
    }
    return {"completed_capture_effect": value}


def freeze_fields(settings: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    active = nonlegacy(settings)
    exact = settings.get("memory_material_profile", "full_v1") == "compact_exact_v1"
    material = (
        {
            "memory_material_profile": "compact_exact_v1",
            "memory_exact_presentation": {
                "profile": "compact_exact_v1",
                "format": "json_dictionary_v1",
                "decode_guidance_sha256": hashlib.sha256(DECODE_GUIDANCE.encode()).hexdigest(),
            },
        }
        if exact
        else {}
    )
    if not active:
        return material
    return {
        **material,
        **active,
        "public_memory_contract_presentation": {
            "profiles": profiles(settings),
            "catalog_sha256": hashlib.sha256(canonical(catalog).encode()).hexdigest(),
            "capture_guidance_sha256": hashlib.sha256(CAPTURE_GUIDANCE.encode()).hexdigest()
            if active.get("observation_capture_feedback")
            else None,
        },
    }


def check_frozen(frozen: dict[str, Any]) -> None:
    expected = freeze_fields(frozen["config"], frozen["tool_catalog"])
    if any(
        frozen.get(k) != expected.get(k)
        for k in [
            *PROFILES,
            "public_memory_contract_presentation",
            "memory_material_profile",
            "memory_exact_presentation",
        ]
    ):
        raise ValueError("PUBLIC_MEMORY_CONTRACT_FROZEN_CHANGED")
