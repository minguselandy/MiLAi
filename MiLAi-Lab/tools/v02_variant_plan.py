"""Declared experimental branches and deterministic, reversible memory transformations."""

from __future__ import annotations

import json

from v02_local_provider import LocalGateError

VARIANT_ARMS = ("B_representation", "B_structure")
ALL_ARMS = ("G", "A", "B", *VARIANT_ARMS)
RESERVED = frozenset({"evidence_id", "evidence_refs", "state_id", "state_version_id",
                      "operation_id", "expected_version", "version", "scope", "authority",
                      "schema_version", "schema_name", "task_ref", "project", "tenant",
                      "principal", "source_versions"})


def branches(config: dict) -> tuple[str, ...]:
    plan = config.get("memory_variants")
    if plan is None:
        return ALL_ARMS[:3]
    if (config.get("source_mode") != "PUBLIC_SOURCE_SNAPSHOT"
            or not isinstance(plan, dict) or set(plan) != set(VARIANT_ARMS)):
        raise LocalGateError("VARIANT_PLAN_INVALID")
    for arm, spec in plan.items():
        if (not isinstance(spec, dict) or not isinstance(spec.get("layer"), str)
                or spec["layer"] not in {"L1", "L2"}):
            raise LocalGateError("VARIANT_LAYER_REQUIRED")
        kind = spec.get("kind")
        if arm == "B_representation":
            if (kind != "MARKDOWN_JSON_TEXT_WRAPPING_ONLY"
                    or set(spec) - {"layer", "kind", "source_format"}):
                raise LocalGateError("REPRESENTATION_PLAN_INVALID")
        else:
            required = {"layer", "kind"}
            if kind in {"BODY_FIRST", "BODY_LAST"}:
                required.add("body_key")
                if (not isinstance(spec.get("body_key"), str) or not spec["body_key"]
                        or spec["body_key"] in RESERVED):
                    raise LocalGateError("BUSINESS_BODY_KEY_REQUIRED")
            elif kind == "DROP_EMPTY_EDGE_WRAPPERS":
                required.add("empty_wrapper_keys")
                keys = spec.get("empty_wrapper_keys")
                if (not isinstance(keys, list) or not keys or any(
                    not isinstance(k, str) or not k or k in RESERVED for k in keys
                ) or len(set(keys)) != len(keys)):
                    raise LocalGateError("DECLARED_NON_SEMANTIC_WRAPPERS_REQUIRED")
            elif kind != "NON_RESERVED_KEY_REORDER":
                raise LocalGateError("STRUCTURE_KIND_INVALID")
            if set(spec) - {"source_format"} != required:
                raise LocalGateError("STRUCTURE_PLAN_INVALID")
        if spec.get("source_format", "text") not in {"text", "json"}:
            raise LocalGateError("VARIANT_SOURCE_FORMAT_INVALID")
    return ALL_ARMS


class NotApplicable(ValueError):
    """An actual G artifact lacks the declared opportunity; never manufacture one."""


def json_object(raw: str) -> dict:
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise NotApplicable("DUPLICATE_JSON_KEYS")
            value[key] = child
        return value

    try:
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                NotApplicable("NONFINITE_JSON_VALUE")))
    except (ValueError, TypeError) as exc:
        raise NotApplicable("JSON_OBJECT_REQUIRED") from exc
    if not isinstance(result, dict):
        raise NotApplicable("JSON_OBJECT_REQUIRED")
    return result


def transform(raw: bytes, format_name: str, spec: dict) -> dict:
    text = raw.decode("utf-8")
    kind = spec["kind"]
    if kind == "MARKDOWN_JSON_TEXT_WRAPPING_ONLY":
        if format_name == "text":
            value = {"text": text}
            content, result_format = json.dumps(value, ensure_ascii=False), "json"
            assert json.loads(content)["text"] == text
        elif format_name == "json":
            value = json_object(text)
            if set(value) != {"text"} or not isinstance(value["text"], str):
                raise NotApplicable("EXACT_TEXT_WRAPPER_REQUIRED_FOR_UNWRAP")
            content, result_format = value["text"], "text"
        else:
            raise NotApplicable("DECLARED_FORMAT_UNSUPPORTED")
        return {"content": content, "format": result_format, "kind": kind,
                "equivalence": "EXACT_TEXT_WRAPPING_ONLY", "removed_keys": []}
    if format_name != "json":
        raise NotApplicable("STRUCTURE_REQUIRES_EXISTING_JSON_OBJECT")
    before = json_object(text)
    keys = list(before)
    business = [key for key in keys if key not in RESERVED]
    removed = []
    if kind in {"BODY_FIRST", "BODY_LAST"}:
        body = spec["body_key"]
        if body not in business:
            raise NotApplicable("DECLARED_BODY_NOT_PRESENT")
        others = [key for key in business if key != body]
        reordered = [body, *others] if kind == "BODY_FIRST" else [*others, body]
    elif kind == "NON_RESERVED_KEY_REORDER":
        reordered = list(reversed(business))
    elif kind == "DROP_EMPTY_EDGE_WRAPPERS":
        removed = spec["empty_wrapper_keys"]
        if any(key not in before or before[key] not in (None, "", [], {}) for key in removed):
            raise NotApplicable("DECLARED_WRAPPER_MISSING_OR_NONEMPTY")
        kept = [index for index, key in enumerate(keys) if key not in removed]
        if not kept or any(min(kept) < keys.index(key) < max(kept) for key in removed):
            raise NotApplicable("WRAPPERS_ARE_NOT_AT_EDGES")
        reordered = [key for key in business if key not in removed]
        keys = [key for key in keys if key not in removed]
    else:
        raise LocalGateError("STRUCTURE_KIND_INVALID")
    values = iter(reordered)
    order = [key if key in RESERVED else next(values) for key in keys]
    if order == list(before):
        raise NotApplicable("NO_DECLARED_STRUCTURE_CHANGE")
    after = {key: before[key] for key in order}
    assert after == {key: value for key, value in before.items() if key not in removed}
    return {"content": json.dumps(after, ensure_ascii=False), "format": "json", "kind": kind,
            "equivalence": "VALUES_PRESERVED_EXCEPT_DECLARED_EMPTY_WRAPPERS",
            "removed_keys": removed, "before_key_order": list(before), "after_key_order": order}
