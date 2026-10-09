"""Pure projection of actual captured bodies under a public adapter contract."""

from __future__ import annotations

import json
import math
from typing import Any

from milai_lab.contracts.memory import ObservationField, ObservationProfile

PROJECTOR_VERSION = "deterministic_fields_v1"
_MISSING = object()


class ObservationError(ValueError):
    """No facts may be asserted for an invalid or ambiguous public mapping."""


def _json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def identity(value: Any) -> str:
    return _json(value)


def profile_identity(profile: ObservationProfile) -> str:
    if not isinstance(profile, ObservationProfile):
        raise ObservationError("invalid_profile")
    if (
        not all(
            type(value) is str and value
            for value in (profile.profile_id, profile.adapter_version, profile.application)
        )
        or not profile.origins
        or not all(type(value) is str and value for value in profile.origins)
        or not profile.fields
        or len({field.name for field in profile.fields}) != len(profile.fields)
        or profile.resource_version_type not in {"integer", "opaque"}
        or profile.completeness not in {"partial", "complete"}
    ):
        raise ObservationError("invalid_profile")
    paths = [profile.object_id_path, profile.objects_path, profile.unknown_path]
    paths.extend(profile.unstructured_paths)
    paths.extend(
        path
        for path in (profile.owner_path, profile.resource_version_path, profile.valid_time_path)
        if path is not None
    )
    for field in profile.fields:
        if (
            not isinstance(field, ObservationField)
            or not field.name
            or field.dtype not in {"string", "integer", "boolean", "number", "json"}
            or type(field.allow_null_clear) is not bool
            or (field.version_domain is not None and not field.version_domain)
        ):
            raise ObservationError("invalid_profile")
        paths.append(field.path)
    if any(
        not isinstance(path, tuple) or not all(type(part) is str for part in path) for path in paths
    ):
        raise ObservationError("invalid_profile_path")
    return profile.profile_id + ":" + profile.adapter_version


def _get(body: Any, path: tuple[str, ...]) -> Any:
    result = body
    for part in path:
        if not isinstance(result, dict) or part not in result:
            return _MISSING
        result = result[part]
    return result


def _pointer(path: tuple[str, ...]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path)


def _body(content: Any) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ObservationError("duplicate_source_key")
            result[key] = value
        return result

    if not isinstance(content, str):
        return content
    try:
        return json.loads(content, object_pairs_hook=unique)
    except ValueError as error:
        raise ObservationError("source_body_invalid_json") from error


def _typed(field: ObservationField, value: Any) -> bool:
    if value is None:
        return field.allow_null_clear
    if field.dtype == "json":
        return True
    if field.dtype == "number":
        return type(value) in {int, float} and math.isfinite(value)
    return type(value) is {"string": str, "integer": int, "boolean": bool}[field.dtype]


def derive_observations(
    source: dict[str, Any], profile: ObservationProfile
) -> tuple[list[dict[str, Any]], str]:
    """Missing fields produce no observation; no response status proves external effects."""
    profile_version = profile_identity(profile)
    if source["role"] != "tool":
        raise ObservationError("projection_requires_tool_source")
    if source["origin"] not in profile.origins:
        raise ObservationError("source_origin_profile_mismatch")
    body = _body(source["content"])
    outcome = _get(body, profile.unknown_path)
    if outcome in profile.unknown_values:
        return [], "unknown"
    objects = _get(body, profile.objects_path)
    if objects is _MISSING:
        return [], "no_projectable_objects"
    many = isinstance(objects, list)
    rows = objects if many else [objects]
    derived: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        object_id = _get(row, profile.object_id_path)
        if object_id is _MISSING:
            continue
        if type(object_id) is not str or not object_id:
            raise ObservationError("object_identity_invalid")
        if profile.owner_path is not None and _get(row, profile.owner_path) != source["owner"]:
            raise ObservationError("object_owner_mismatch")
        version = (
            _get(row, profile.resource_version_path)
            if profile.resource_version_path is not None
            else _MISSING
        )
        if version is _MISSING or version is None:
            version = None
        elif type(version) is not (int if profile.resource_version_type == "integer" else str):
            raise ObservationError("resource_version_invalid")
        valid_time = (
            _get(row, profile.valid_time_path) if profile.valid_time_path is not None else _MISSING
        )
        if valid_time is _MISSING:
            valid_time = None
        object_ref = {
            "id": "obs-object-" + identity([source["owner"], profile.application, object_id]),
            "owner": source["owner"],
            "external_id": object_id,
            "application": profile.application,
            "authority": "observation_only",
        }
        prefix = (*profile.objects_path, str(index)) if many else profile.objects_path
        for field in profile.fields:
            literal = _get(row, field.path)
            if literal is _MISSING:
                continue
            if not _typed(field, literal):
                raise ObservationError("field_type_mismatch:" + field.name)
            observation_id = "obs-" + identity(
                [
                    source["event_id"],
                    object_ref["id"],
                    field.name,
                    profile.profile_id,
                    profile.adapter_version,
                    PROJECTOR_VERSION,
                ]
            )
            observed = {
                "observation_id": observation_id,
                "owner": source["owner"],
                "source_event_id": source["event_id"],
                "source_revision": source.get("source_revision", 1),
                "object_ref": object_ref,
                "field": field.name,
                "field_paths": [_pointer((*prefix, *field.path))],
                "literal_value": literal,
                "clears": literal is None,
                "resource_version": version,
                "resource_version_type": profile.resource_version_type,
                "version_domain": field.version_domain,
                "valid_time": valid_time,
                "observed_at": source["observed_at"],
                "adapter_id": profile.profile_id,
                "adapter_version": profile.adapter_version,
                "adapter_ref": profile_version,
                "projector_version": PROJECTOR_VERSION,
                "completeness": profile.completeness,
                "verification": "actual_source_literal",
                "current_verified": False,
            }
            if observation_id in derived:
                previous = derived[observation_id]
                if {k: v for k, v in previous.items() if k != "field_paths"} != {
                    k: v for k, v in observed.items() if k != "field_paths"
                }:
                    raise ObservationError("same_event_object_field_conflict")
                previous["field_paths"].extend(observed["field_paths"])
            else:
                derived[observation_id] = observed
    return [derived[key] for key in sorted(derived)], "observed"


def _json_ranges(text: str) -> dict[tuple[str, ...], tuple[int, int]]:
    """Locate original JSON members; no reserialized prose becomes evidence."""
    decoder = json.JSONDecoder()
    ranges: dict[tuple[str, ...], tuple[int, int]] = {}

    def whitespace(position: int) -> int:
        while position < len(text) and text[position].isspace():
            position += 1
        return position

    def visit(position: int, path: tuple[str, ...]) -> int:
        position = whitespace(position)
        start = position
        if text[position] == "{":
            position = whitespace(position + 1)
            while text[position] != "}":
                member_start = position
                key, position = decoder.raw_decode(text, position)
                position = whitespace(position)
                child_path = (*path, key)
                position = visit(position + 1, child_path)
                ranges[child_path] = (member_start, position)
                position = whitespace(position)
                if text[position] == ",":
                    position = whitespace(position + 1)
            end = position + 1
        elif text[position] == "[":
            index = 0
            position = whitespace(position + 1)
            while text[position] != "]":
                position = visit(position, (*path, str(index)))
                index += 1
                position = whitespace(position)
                if text[position] == ",":
                    position = whitespace(position + 1)
            end = position + 1
        else:
            _, end = decoder.raw_decode(text, position)
        ranges[path] = (start, end)
        return end

    visit(0, ())
    return ranges


def maintenance_projection(
    source: dict[str, Any], profile: ObservationProfile, text: str
) -> dict[str, Any]:
    """Public field literals and exact original spans, without semantic formation.

    Profile-declared prose stays an original extraction input. Unmapped material
    remains in the Source, not a second observation or a fabricated summary.
    """
    observations, outcome = derive_observations(source, profile)
    if outcome != "observed" or not observations:
        return {"outcome": outcome, "observations": []}
    ranges = _json_ranges(text)

    def path_for(pointer: str) -> tuple[str, ...]:
        return tuple(part.replace("~1", "/").replace("~0", "~")
                     for part in pointer[1:].split("/"))

    material = []
    object_paths: set[tuple[str, ...]] = set()
    for observation in observations:
        paths = [path_for(pointer) for pointer in observation["field_paths"]]
        field_path = next(field.path for field in profile.fields
                          if field.name == observation["field"])
        prefixes = [path[:len(path) - len(field_path)] for path in paths]
        object_paths.update(prefixes)
        identity_paths = [(*prefix, *profile.object_id_path) for prefix in prefixes]
        identity_paths.extend(
            (*prefix, *path) for prefix in prefixes for path in (
                profile.resource_version_path, profile.valid_time_path
            ) if path is not None
        )
        spans = [ranges[path] for path in dict.fromkeys([*identity_paths, *paths])
                 if path in ranges]
        material.append({**observation, "ranges": spans})
    prose = [ranges[path] for prefix in sorted(object_paths)
             for declared in profile.unstructured_paths
             if (path := (*prefix, *declared)) in ranges]
    return {"outcome": outcome, "observations": material, "unstructured_ranges": prose}


def observation_view(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Partial-order field selection; arrival time never chooses between conflicting facts."""
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in observations:
        groups.setdefault(row["object_ref"]["id"], {}).setdefault(row["field"], []).append(row)
    result = []
    for _object_id, fields in sorted(groups.items()):
        field_views = {}
        for name, history in sorted(fields.items()):
            history = sorted(history, key=lambda row: (row["observed_at"], row["observation_id"]))

            def older(first: dict[str, Any], second: dict[str, Any]) -> bool:
                return (
                    first["version_domain"] is not None
                    and first["version_domain"] == second["version_domain"]
                    and first["resource_version_type"]
                    == second["resource_version_type"]
                    == "integer"
                    and first["resource_version"] is not None
                    and second["resource_version"] is not None
                    and first["resource_version"] < second["resource_version"]
                )

            candidates = [row for row in history if not any(older(row, other) for other in history)]
            unique = all(
                row["literal_value"] == candidates[0]["literal_value"] for row in candidates
            )
            comparable = (
                all(
                    row["version_domain"] is not None
                    and row["resource_version_type"] == "integer"
                    and row["resource_version"] is not None
                    for row in history
                )
                and len({row["version_domain"] for row in history}) == 1
            )
            field_views[name] = {
                "status": "observed" if unique else "conflict",
                **({"literal_value": candidates[0]["literal_value"]} if unique else {}),
                "selection": "comparable_latest" if comparable else "unordered_observations",
                "candidates": candidates,
                "history": history,
                "last_observed_at": history[-1]["observed_at"],
                "current_verified": False,
            }
        sample = next(iter(fields.values()))[0]
        result.append(
            {"object_ref": sample["object_ref"], "fields": field_views, "current_verified": False}
        )
    return result
