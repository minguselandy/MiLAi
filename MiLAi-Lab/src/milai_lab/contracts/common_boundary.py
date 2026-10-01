"""Independent opt-in common boundary contracts; original validators stay authoritative."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

PROFILES = {
    "common_read_profile": "bounded_public_v1",
    "common_formation_profile": "closed_host_v1",
    "common_host_profile": "read_only_v1",
    "common_semantic_fallback": "single_summary_v1",
}
HEADER = "[Owner-scoped returned memory snapshot]\n"
POLICY = (
    "Returned owner-scoped subset, not a complete corpus. Original order and native "
    "IDs are retained. Prefixes and omissions are not full reads. Model-generated "
    "summaries and native extraction remain unchecked; no M revision or CAS is "
    "assigned to native values. Explicit reads incur separate costs."
)


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def profiles(settings: dict[str, Any]) -> dict[str, str]:
    result = {}
    for key, enabled in PROFILES.items():
        value = settings.get(key, "legacy")
        if type(value) is not str or value not in {"legacy", enabled}:
            raise ValueError("COMMON_BOUNDARY_PROFILE_INVALID:" + key)
        result[key] = value
    return result


def validate(settings: dict[str, Any], arm: str) -> dict[str, str]:
    chosen = profiles(settings)
    active = any(value != "legacy" for value in chosen.values())
    if not active:
        return {}
    if settings.get("generation_admission_profile") != "durable_shared_v1":
        raise ValueError("COMMON_BOUNDARY_SHARED_ADMISSION_REQUIRED")
    if settings.get("memory_mutation_contract") != "event_bound_v1":
        raise ValueError("COMMON_BOUNDARY_ACTUAL_EVENT_BINDING_REQUIRED")
    if chosen["common_formation_profile"] != "legacy" and (
        settings.get("memory_writer_repairs", 0) != 0
        or type(settings.get("memory_writer_repairs", 0)) is not int
    ):
        raise ValueError("COMMON_BOUNDARY_REPAIR_DISABLED_REQUIRED")
    if chosen["common_read_profile"] != "legacy":
        if settings["controls"]["material_max_tokens"] != 2048:
            raise ValueError("COMMON_BOUNDARY_MATERIAL_2048_REQUIRED")
        if settings["controls"]["raw_rag"]["top_k"] != 6:
            raise ValueError("COMMON_BOUNDARY_MAX6_REQUIRED")
        if (
            arm == "field_grounded"
            and settings.get("memory_reader_policy") != "bounded_evidence_v1"
        ):
            raise ValueError("COMMON_BOUNDARY_M_EXISTING_READER_REQUIRED")
    if (
        chosen["common_semantic_fallback"] != "legacy"
        and chosen["common_formation_profile"] == "legacy"
    ):
        raise ValueError("COMMON_BOUNDARY_SUMMARY_CLOSED_REQUIRED")
    if arm == "B2" and settings.get("memory_observation_profile") is not None:
        raise ValueError("COMMON_BOUNDARY_RAW_ONLY_PROJECTION_DISABLED_REQUIRED")
    return {key: value for key, value in chosen.items() if value != "legacy"}


def bounded_view(
    rows: list[dict[str, Any]],
    *,
    binding: dict[str, Any],
    token_count: Callable[[str], int],
    query_kind: str,
    result_metadata: Any = None,
    max_tokens: int = 2048,
    max_records: int = 6,
) -> dict[str, Any]:
    """Bound a returned ordered subset; no retrieval, invented DTO, or changed ranking."""
    originals = clone(rows)
    ids = [row["id"] for row in originals]
    if any(type(value) is not str or not value for value in ids):
        raise ValueError("COMMON_BOUNDARY_ACTUAL_RESULT_ID_REQUIRED")
    if len(set(ids)) != len(ids):
        raise ValueError("COMMON_BOUNDARY_RESULT_IDS_DUPLICATED")
    selected = originals[:max_records]
    packet: dict[str, Any] = {
        "schema": "common_returned_snapshot_v1",
        "binding": clone(binding),
        "query_kind": query_kind,
        "policy": POLICY,
        "snapshot_sha256": digest(originals),
        "returned_count": len(originals),
        "result_metadata_sha256": digest(result_metadata),
        "selected": [{"id": row["id"], "dto_sha256": digest(row)} for row in selected],
        "result_metadata": clone(result_metadata),
        "items": [],
        "omitted_ids": ids.copy(),
    }

    def material() -> str:
        return HEADER + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))

    if token_count(material()) > max_tokens:
        raise ValueError("COMMON_BOUNDARY_METADATA_EXCEEDS_BUDGET")
    for row in selected:
        text_fields = [key for key in ("content", "memory") if type(row.get(key)) is str]
        candidate: dict[str, Any] = {"dto": clone(row), "dto_sha256": digest(row), "prefixes": {}}
        packet["items"].append(candidate)
        packet["omitted_ids"].remove(row["id"])
        if token_count(material()) <= max_tokens:
            continue
        for key in text_fields:
            candidate["dto"][key] = ""
            candidate["prefixes"][key] = {
                "delivered_codepoints": 0,
                "original_codepoints": len(row[key]),
                "utf8_sha256": hashlib.sha256(row[key].encode()).hexdigest(),
                "complete": False,
            }
        if not text_fields or token_count(material()) > max_tokens:
            packet["items"].pop()
            packet["omitted_ids"].append(row["id"])
            continue
        for key in text_fields:
            low, high = 0, len(row[key])
            while low < high:
                middle = (low + high + 1) // 2
                candidate["dto"][key] = row[key][:middle]
                candidate["prefixes"][key]["delivered_codepoints"] = middle
                if token_count(material()) <= max_tokens:
                    low = middle
                else:
                    high = middle - 1
            candidate["dto"][key] = row[key][:low]
            candidate["prefixes"][key]["delivered_codepoints"] = low
            candidate["prefixes"][key]["complete"] = low == len(row[key])
            # Boolean text token costs can change; retain only actually fitting prefixes.
            while low and token_count(material()) > max_tokens:
                low -= 1
                candidate["dto"][key] = row[key][:low]
                candidate["prefixes"][key]["delivered_codepoints"] = low
                candidate["prefixes"][key]["complete"] = False
    # Omission order always follows the original returned result order.
    omitted = set(packet["omitted_ids"])
    packet["omitted_ids"] = [key for key in ids if key in omitted]
    text = material()
    if token_count(text) > max_tokens:
        raise ValueError("COMMON_BOUNDARY_MATERIAL_EXCEEDS_BUDGET")
    return {
        "packet": packet,
        "material": text,
        "material_tokens": token_count(text),
        "packet_sha256": digest(packet),
        "snapshot_rows": originals,
        "result_metadata": clone(result_metadata),
    }
