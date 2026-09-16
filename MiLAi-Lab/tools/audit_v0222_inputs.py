"""Recomputable P0 evidence audit: local files only; no provider/dispatcher instance."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from v0220_action_contract import ActionContract, unique_object
from v0220_evidence import read, save, sha

BASE = Path("/cra/memory/mx_memory/evidence")
OLD = BASE / "v0221/20260911-http-r1-v2"
DESTINATION = BASE / "v0222/p0-audit-20260911"
CASES = BASE / "v0219/f2-wave1-v1/cases"
MAPS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
ARRAYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
SINGLES = {
    "items",
    "additionalProperties",
    "propertyNames",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "unevaluatedProperties",
    "unevaluatedItems",
    "additionalItems",
    "contentSchema",
}
STRING_KEYS = ("type", "pattern", "minLength", "maxLength", "enum", "const", "format")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def pointer(parts):
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def reconstruct_old_wire(canonical: dict) -> dict:
    """Independent replay of frozen V1 mapping; never import its transport/tokenizer chain."""
    result = copy.deepcopy(canonical)
    schema = canonical["response_format"]["json_schema"]["schema"]

    def visit(node):
        if isinstance(node, bool):
            return node
        mapped = {}
        for key, value in node.items():
            if key == "uniqueItems":
                continue
            if key in {"properties", "patternProperties"}:
                mapped[key] = {name: visit(child) for name, child in value.items()}
            elif key in {"anyOf", "allOf", "prefixItems"}:
                mapped[key] = [visit(child) for child in value]
            elif key in {"items", "additionalProperties", "propertyNames"}:
                mapped[key] = visit(value)
            else:
                mapped[key] = copy.deepcopy(value)
        return mapped

    result["response_format"]["json_schema"]["schema"] = visit(schema)
    notice = (
        "Transport compatibility contract (not business facts or action authorization): "
        "the decoder cannot enforce uniqueItems. Array items must still be unique where "
        "the unchanged public schema requires it. Every response is validated against "
        "the full schema before any action; duplicates are rejected, never deduplicated. "
        "All original sources, goals, identity and version rules remain in force. "
        "Authoritative public response schema:\n" + encoded(schema)
    )
    if result["messages"] and result["messages"][0]["role"] == "system":
        result["messages"][0]["content"] += "\n\n" + notice
    else:
        result["messages"].insert(0, {"role": "system", "content": notice})
    return result


def string_constraints(schema: dict) -> list[dict]:
    """Traverse schema-valued keywords, never literal default/enum/example contents."""
    rows = []

    def visit(node, path, operators):
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise ValueError("NON_SCHEMA_NODE")
        types = node.get("type", [])
        is_string = types == "string" or (isinstance(types, list) and "string" in types)
        if (
            is_string
            or any(k in node for k in STRING_KEYS[1:4])
            or isinstance(node.get("const"), str)
            or any(isinstance(v, str) for v in node.get("enum", []))
            or "format" in node
        ):
            rows.append(
                {
                    "pointer": pointer(path),
                    "keywords": {k: copy.deepcopy(node[k]) for k in STRING_KEYS if k in node},
                    "operators": operators,
                    "has_reference": "$ref" in node,
                }
            )
        for key, value in node.items():
            next_operators = [*operators, {"keyword": key, "pointer": pointer([*path, key])}]
            if key in MAPS:
                for name, child in value.items():
                    visit(child, [*path, key, name], operators)
            elif key in ARRAYS or (key == "items" and isinstance(value, list)):
                for i, child in enumerate(value):
                    visit(child, [*path, key, i], next_operators)
            elif key in SINGLES:
                visit(value, [*path, key], next_operators)
            elif key == "dependencies":
                for name, child in value.items():
                    if isinstance(child, (dict, bool)):
                        visit(child, [*path, key, name], next_operators)

    visit(schema, [], [])
    return rows


def validate_raw(schema: dict, raw: str) -> dict:
    """Strict finite JSON plus the complete draft/format validator, without repair."""
    Draft202012Validator.check_schema(schema)
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
        encoded(value)
    except (ValueError, TypeError, RecursionError) as exc:
        return {
            "accepted": False,
            "layer": "JSON",
            "code": getattr(exc, "code", type(exc).__name__),
        }
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    return {
        "accepted": not errors,
        "layer": "FULL_SCHEMA",
        "errors": [
            {
                "path": pointer(list(e.absolute_path)),
                "schema_path": pointer(list(e.absolute_schema_path)),
                "rule": e.validator,
            }
            for e in errors
        ],
    }


def field_diff(expected, actual, path=()) -> list[dict]:
    if type(expected) is not type(actual):
        return [
            {"path": pointer(list(path)), "kind": "TYPE", "expected": expected, "actual": actual}
        ]
    if isinstance(expected, dict):
        rows = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                rows.append(
                    {"path": pointer([*path, key]), "kind": "EXTRA" if key in actual else "MISSING"}
                )
            else:
                rows.extend(field_diff(expected[key], actual[key], (*path, key)))
        return rows
    if isinstance(expected, list):
        rows = []
        for i in range(max(len(expected), len(actual))):
            if i >= len(expected) or i >= len(actual):
                rows.append({"path": pointer([*path, i]), "kind": "LENGTH"})
            else:
                rows.extend(field_diff(expected[i], actual[i], (*path, i)))
        return rows
    return (
        []
        if expected == actual
        else [
            {
                "path": pointer(list(path)),
                "kind": "VALUE",
                "expected": expected,
                "actual": actual,
            }
        ]
    )


def positions(haystack: str, needle: str) -> dict:
    offsets = [m.start() for m in re.finditer(re.escape(needle), haystack)] if needle else []
    return {
        "count": len(offsets),
        "character_offsets": offsets,
        "utf8_byte_offsets": [len(haystack[:i].encode()) for i in offsets],
    }


def string_leaves(value, path=()):
    if isinstance(value, str):
        yield pointer(list(path)), value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from string_leaves(child, (*path, key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from string_leaves(child, (*path, i))


def metrics(value: str) -> dict:
    return {
        "characters": len(value),
        "utf8_bytes": len(value.encode()),
        "sha256_utf8": hashlib.sha256(value.encode()).hexdigest(),
    }


def validator_boundaries() -> list[dict]:
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    schema = {
        "type": "object",
        "properties": {"text": text},
        "required": ["text"],
        "additionalProperties": False,
    }
    cases = [
        ("single_character_legal", "f", True),
        ("ascii_address_and_words", "sample@example.invalid ordinary multi word text", True),
        ("unicode_escaped", '中文 café "quote" \\ backslash\nnewline\ttab', True),
        ("boundary_whitespace", " \t ; middle! \n", True),
        ("empty", "", False),
        ("all_whitespace", " \t\n", False),
        ("wrong_type_integer", 1, False),
        ("wrong_type_null", None, False),
    ]
    rows = [
        {"name": name, "schema": schema, "raw": encoded({"text": value}), "expected_accept": accept}
        for name, value, accept in cases
    ]
    for name, raw in [
        ("duplicate_key", '{"text":"a","text":"b"}'),
        ("missing", "{}"),
        ("extra_property", '{"text":"a","x":0}'),
        ("nonfinite", '{"text": NaN}'),
        ("overflow", '{"text":1e999}'),
    ]:
        rows.append({"name": name, "schema": schema, "raw": raw, "expected_accept": False})
    for name, rule, value, accept in [
        ("max_length_boundary", {"maxLength": 2}, "中a", True),
        ("max_length_reject", {"maxLength": 2}, "中ab", False),
        ("enum_accept", {"enum": ["fixed"]}, "fixed", True),
        ("enum_reject", {"enum": ["fixed"]}, "other", False),
        ("const_reject", {"const": "fixed"}, "other", False),
        ("anchored_accept", {"pattern": "^[A-Z]{2}$"}, "AB", True),
        ("anchored_reject", {"pattern": "^[A-Z]{2}$"}, "xABx", False),
        ("unanchored_accept", {"pattern": "AB"}, "xABx", True),
        ("format_reject", {"format": "date"}, "not-date", False),
    ]:
        changed = copy.deepcopy(schema)
        changed["properties"]["text"].update(rule)
        rows.append(
            {
                "name": name,
                "schema": changed,
                "raw": encoded({"text": value}),
                "expected_accept": accept,
            }
        )
    for row in rows:
        row["validation"] = validate_raw(row["schema"], row["raw"])
        row["pass"] = row["validation"]["accepted"] is row["expected_accept"]
        row["decoder_membership"] = "UNOBSERVED"
    return rows


def build_audit(old: Path = OLD) -> dict:
    inputs = {}

    def load(path):
        inputs[str(path)] = sha(path)
        return read(path)

    manifest = load(old / "manifest.json")
    specs = manifest["contract"]["W2"]
    first = specs[0]
    provider = old / "episodes" / first["id"] / "provider"
    paths = list(provider.glob("*-request.json"))
    if len(paths) != 1:
        raise ValueError("EXPECTED_EXACTLY_ONE_OLD_REQUEST")
    request_path = paths[0]
    request_id = request_path.name.removesuffix("-request.json")
    wire = load(request_path)
    canonical = load(old / "W2-requests" / f"{first['id']}.canonical.json")
    reference = load(old / "W2-requests" / f"{first['id']}.output.json")
    http = load(provider / (request_id + "-http.json"))
    visible = load(provider / (request_id + "-visible.json"))
    bindings = [load(p) for p in provider.glob("contract-*-binding.json")]
    schema = canonical["response_format"]["json_schema"]["schema"]
    request_bytes = request_path.read_bytes()
    raw = json.loads(http["body"])["choices"][0]["message"]["content"]
    output = json.loads(raw, object_pairs_hook=unique_object)
    expected = first["expected"]
    canonical_user = json.loads(canonical["messages"][-1]["content"])
    wire_user = json.loads(wire["messages"][-1]["content"])
    checks = {
        "documented_request_hash": sha(request_path)
        == "1439c7b01ad6c6497df13ecbe26e9b1e785b556aa8fa1d33dcf75edd2c80e174",
        "documented_visible_hash": sha(provider / (request_id + "-visible.json"))
        == "8cfc900d21f67eb2ddc0a769a87ee2bb441bfbfb6983f77602be7f4cbc7e6d7c",
        "expected_equals_reference": expected == json.loads(reference["raw"]),
        "canonical_intent_exact": canonical_user["authorized_intent"]["authorized_action"]
        == expected,
        "wire_intent_exact": wire_user["authorized_intent"]["authorized_action"] == expected,
        "wire_prepare_exact": reconstruct_old_wire(canonical) == wire,
        "serialized_http_bytes_exact": encoded(wire).encode() == request_bytes,
        "http_receipt_request_sha_exact": http["request_wire_sha256"] == sha(request_path),
        "saved_visible_equals_http_content": visible["content"] == raw,
        "canonical_binding_exact": len(bindings) == 1
        and bindings[0]["original_request"] == canonical,
    }
    traces = []
    for path, value in string_leaves(expected):
        escaped = json.dumps(value, ensure_ascii=False)[1:-1]
        double = json.dumps(escaped, ensure_ascii=False)[1:-1]
        traces.append(
            {
                "path": path,
                "decoded_value": value,
                **metrics(value),
                "json_escape_once": escaped,
                "json_escape_twice": double,
                "http_bytes_escaped_twice": positions(request_bytes.decode(), double),
                "messages": [
                    {
                        "index": i,
                        "role": m["role"],
                        "decoded_literal": positions(m["content"], value),
                        "json_string_content": positions(m["content"], escaped),
                    }
                    for i, m in enumerate(wire["messages"])
                ],
            }
        )
    conflicts = []
    marker = re.compile(r"(?i)\b(?:must|never|do not|ignore|exactly|output|preserve)\b")
    for i, message in enumerate(wire["messages"]):
        for match in marker.finditer(message["content"]):
            conflicts.append(
                {
                    "message": i,
                    "role": message["role"],
                    "offset": match.start(),
                    "excerpt": message["content"][max(0, match.start() - 80) : match.end() + 140],
                }
            )
    contracts, objects = [], []
    for spec in specs[:8]:
        body = load(old / "W2-requests" / (spec["id"] + ".canonical.json"))
        full = body["response_format"]["json_schema"]["schema"]
        contracts.append(
            {
                "root": spec["root"],
                "variant": spec["variant"],
                "schema_sha256": fingerprint(full),
                "strings": string_constraints(full),
            }
        )
        if spec["variant"] == "finish":
            continue
        public = load(CASES / spec["root"] / "public-initial.json")
        ref = load(CASES / spec["root"] / "independent-reference.json")
        records = ref.get("records", ref.get("initial_records"))
        action_contract = ActionContract.from_public(public)
        for target, target_schema in action_contract.write_schemas().items():
            data = {k: v for k, v in records[target].items() if k != "object_id"}
            validation = validate_raw(target_schema, encoded(data))
            objects.append(
                {
                    "root": spec["root"],
                    "object_id": target,
                    "schema_sha256": fingerprint(target_schema),
                    "strings": string_constraints(target_schema),
                    "reference": validation,
                }
            )
    references = []
    for row in load(old / "reference-requests.json"):
        values = {key: load(Path(row[key])) for key in ("canonical", "wire", "output")}
        original = values["canonical"]
        original_schema = original["response_format"]["json_schema"]["schema"]
        references.append(
            {
                "episode": row["episode"],
                "turn": row["turn"],
                "hashes_match": all(sha(Path(row[k])) == row["hashes"][k] for k in values),
                "wire_exact": reconstruct_old_wire(original) == values["wire"],
                "validation": validate_raw(original_schema, values["output"]["raw"]),
                "decoder_membership": "UNOBSERVED",
            }
        )
    source = old / "executed-source/tools/v0221_http_provider.py"
    inputs[str(source)] = sha(source)
    compiler = old / "executed-source/tools/v0220_wire_contract.py"
    inputs[str(compiler)] = sha(compiler)
    inputs[str(Path(__file__).resolve())] = sha(Path(__file__).resolve())
    boundary = validator_boundaries()
    differences = field_diff(expected, output)
    for difference in differences:
        for side in ("expected", "actual"):
            if isinstance(difference.get(side), str):
                difference[side + "_metrics"] = metrics(difference[side])
    return {
        "revision": "V0222_P0_INPUT_AUDIT_V1",
        "old_root": str(old),
        "inputs": inputs,
        "model_requests": 0,
        "online_tokenize_requests": 0,
        "http_requests": 0,
        "device_or_container_operations": 0,
        "decoder_membership": "UNOBSERVED",
        "transport_provenance": {
            "body": str(request_path),
            "sender_source": str(source),
            "evidence_limit": "Saved content=raw bytes, same-source sender and HTTP receipt; "
            "not an independent packet capture or server-side decoded-prompt trace.",
            "escape_path": [
                "UTF-8 HTTP JSON bytes",
                "JSON decode body/messages content",
                "JSON decode user presentation/authorized_action",
                "original value",
            ],
        },
        "chain_checks": checks,
        "expected": expected,
        "actual_raw": raw,
        "field_diff": differences,
        "field_metrics": traces,
        "request_metrics": metrics(request_bytes.decode()),
        "message_metrics": [
            {"index": i, "role": m["role"], **metrics(m["content"])}
            for i, m in enumerate(wire["messages"])
        ],
        "observable_instruction_markers": conflicts,
        "conflict_interpretation": "Markers are review candidates, not proven conflicts. "
        "System explicitly makes sources data and requires exact authorized_action; "
        "the complete authorized action is already at the end of the final user message. "
        "Long and repeated contracts are observable; attention effects are UNOBSERVED.",
        "string_contracts": contracts,
        "objects": objects,
        "references": references,
        "reference_validation": validate_raw(schema, encoded(expected)),
        "actual_validation": validate_raw(schema, raw),
        "validator_boundaries": boundary,
        "status": "P0_INPUT_AUDIT_PASS"
        if all(checks.values())
        and len(objects) == 25
        and len(contracts) == 8
        and len(references) == 96
        and all(r["reference"]["accepted"] for r in objects)
        and all(
            r["hashes_match"] and r["wire_exact"] and r["validation"]["accepted"]
            for r in references
        )
        and all(r["pass"] for r in boundary)
        else "P0_INPUT_AUDIT_NOT_MET",
        "causal_conclusion": "No observed value/escaping corruption in the saved request chain. "
        "Schema-valid value mismatch remains; decoder internals and causal explanation UNOBSERVED.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DESTINATION)
    args = parser.parse_args()
    if args.root.resolve() != DESTINATION or args.root.exists():
        raise SystemExit("EXACT_FRESH_P0_ROOT_REQUIRED")
    report = build_audit()
    args.root.mkdir(parents=True, exist_ok=False)
    save(args.root / "audit.json", report)
    compact = {
        "status": report["status"],
        "audit_sha256": sha(args.root / "audit.json"),
        "objects": len(report["objects"]),
        "contracts": len(report["string_contracts"]),
        "reference_requests": len(report["references"]),
        "field_diff_paths": [r["path"] for r in report["field_diff"]],
        "model_requests": 0,
        "http_requests": 0,
        "decoder_membership": "UNOBSERVED",
    }
    save(args.root / "result.json", compact)
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
