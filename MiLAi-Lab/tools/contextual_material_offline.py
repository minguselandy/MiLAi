"""Read-only fixed v7 receipt comparison for the v5 material projection."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

from milai_lab.methods.contextual_memory.material_view import (
    MaterialView,
    serialized_material_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/contextual-v5-material-offline.json"
OUTPUT = ROOT / "artifacts/contextual-user-memory/v5-material-offline/result.json"
READ_TOOLS = {"memory_read", "memory_search"}
REQUIRED = {"source_replacement", "current_interpretation", "support_replacement",
            "revised_interpretation", "session_neighbor_correction"}


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def calls(path: Path) -> list[dict[str, Any]]:
    result = []
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event.get("event") == "host_tool_call" and event["call"]["name"] in READ_TOOLS:
            result.append(event["call"])
    return result


def original_nodes(value: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(value, dict):
        if value.get("kind") in {"source", "interpretation"} and "ref" in value:
            found.append(value)
        for key in ("materials", "expanded_materials", "associated_materials", "sources"):
            found.extend(original_nodes(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            found.extend(original_nodes(item))
    return found


def original_parts(item: dict[str, Any]) -> list[tuple[int, int, str]]:
    key = "content" if item["kind"] == "source" else "text"
    entries = item.get("excerpts", [item])
    parts = []
    for entry in entries:
        body = entry.get("content") if "excerpts" in item else entry.get(key)
        if not isinstance(body, str):
            continue
        page = entry.get("page", {})
        start = page.get("start", 0)
        end = page.get("end", len(body))
        parts.append((start, end, body))
    return parts


def check_packet(
    original: dict[str, Any], projected: dict[str, Any], view: MaterialView,
    *, all_bodies: bool = False,
) -> dict[str, int]:
    assert projected.get("status") != "INSUFFICIENT_MATERIAL_BUDGET"
    rows = projected["materials"]
    by_exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_exact[view.binding(row["ref"]).exact_ref].append(row)
    roots = (original.get("materials", []) + original.get("expanded_materials", [])
             if "materials" in original else [original])
    for root in roots:
        ref = root["ref"]
        if root.get("kind") not in {"source", "interpretation"}:
            expansion_refs = {
                view.resolve_ref(short) for short in projected.get("unexpanded_refs", [])
            }
            assert ref in expansion_refs
            continue
        assert ref in by_exact, f"missing selected object {ref}"
        representative = by_exact[ref][0]
        assert representative["kind"] == root["kind"]
        assert representative["status"] == root["status"]
        if root["kind"] == "source":
            assert representative["role"] == root["role"]
        for field in ("applicability", "applicability_reasons", "conditions", "context",
                      "valid_from", "valid_until", "uncertain_start", "uncertain_end"):
            if root.get(field):
                assert representative.get(field) == root[field], (ref, field)
        current = root.get("current_ref")
        if current and current != ref:
            assert view.resolve_ref(representative["current_ref"]) == current
        related = representative.get("related", [])
        for relation in root.get("associated_materials", []):
            if relation.get("relation") in REQUIRED:
                assert any(
                    link["relation"] == relation["relation"]
                    and view.resolve_ref(link["ref"]) == relation["ref"]
                    for link in related
                ), (ref, relation["relation"])
        for relation in root.get("associated_materials", []):
            if relation.get("relation") in {"prior_interpretation", "source_provenance"}:
                assert any(
                    link["relation"] == relation["relation"]
                    and view.resolve_ref(link["ref"]) == relation["ref"]
                    for link in related
                ), (ref, relation["relation"])
    originals = defaultdict(list)
    for item in original_nodes(original):
        originals[item["ref"]].extend(original_parts(item))
    delivered = 0
    actual: dict[str, dict[int, str]] = defaultdict(dict)
    for row in rows:
        binding = view.binding(row["ref"])
        key = "content" if row["kind"] == "source" else "text"
        parts = ([(row["range"][0], row["range"][1], row[key])]
                 if key in row and "range" in row else [
                     (part["range"][0], part["range"][1], part[key])
                     for part in row.get("excerpts", [])
                 ])
        assert binding.spans == tuple((start, end) for start, end, _ in parts)
        for start, end, body in parts:
            assert end - start == len(body)
            assert any(lower <= start and upper >= end
                       and source[start - lower:end - lower] == body
                       for lower, upper, source in originals[binding.exact_ref]), binding.exact_ref
            delivered += len(body)
            for offset, char in enumerate(body, start):
                actual[binding.exact_ref][offset] = char
    if all_bodies:
        expected: dict[str, dict[int, str]] = defaultdict(dict)
        for ref, parts in originals.items():
            for start, _, body in parts:
                for offset, char in enumerate(body, start):
                    previous = expected[ref].get(offset)
                    assert previous is None or previous == char, ref
                    expected[ref][offset] = char
        assert actual == expected, "strict view omitted or changed a recorded body span"
    # Different recorded events may say the same thing; their exact refs stay distinct.
    return {"objects": len(by_exact), "delivered_chars": delivered}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    tokenizer_path = Path(manifest["tokenizer_path"])
    tokenizer_digest = hashlib.sha256(
        (tokenizer_path / "tokenizer.json").read_bytes()
    ).hexdigest()
    assert tokenizer_digest == manifest["tokenizer_json_sha256"]
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), local_files_only=True)
    totals = defaultdict(lambda: {"legacy_tokens": 0, "strict_tokens": 0,
                                  "default_tokens": 0, "legacy_bytes": 0,
                                  "strict_bytes": 0, "default_bytes": 0,
                                  "receipts": 0})
    details = []
    for entry in manifest["entries"]:
        path = ROOT / entry["trace"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["trace_sha256"]
        call = calls(path)[entry["read_call_ordinal"]]
        assert call["name"] == entry["tool"] and digest(call["result"]) == entry["result_sha256"]
        old = call["result"]
        strict_view = MaterialView(f"offline-strict-{len(details)}")
        strict = strict_view.project(
            old, max_bytes=16000, linked=entry["arm"] == "H2_LINKED",
            include_optional=True,
        )
        checked = check_packet(old, strict, strict_view, all_bodies=True)
        default_view = MaterialView(f"offline-default-{len(details)}")
        default = default_view.project(
            old, max_bytes=16000, linked=entry["arm"] == "H2_LINKED",
        )
        check_packet(old, default, default_view)
        old_json = json.dumps(old, ensure_ascii=False, sort_keys=True)
        strict_json = json.dumps(strict, ensure_ascii=False, sort_keys=True)
        default_json = json.dumps(default, ensure_ascii=False, sort_keys=True)
        old_tokens = len(tokenizer.encode(old_json, add_special_tokens=False))
        strict_tokens = len(tokenizer.encode(strict_json, add_special_tokens=False))
        default_tokens = len(tokenizer.encode(default_json, add_special_tokens=False))
        deferred = []
        for node in original_nodes(old):
            if "relation" in node and node["relation"] not in REQUIRED and original_parts(node):
                deferred.append({"ref": node["ref"], "relation": node["relation"],
                                 "reason": "provenance_or_prior_on_demand"})
        key = f"{entry['case']}/{entry['arm']}"
        group = totals[key]
        group["legacy_tokens"] += old_tokens
        group["strict_tokens"] += strict_tokens
        group["default_tokens"] += default_tokens
        group["legacy_bytes"] += serialized_material_bytes(old)
        group["strict_bytes"] += serialized_material_bytes(strict)
        group["default_bytes"] += serialized_material_bytes(default)
        group["receipts"] += 1
        details.append({"case": entry["case"], "arm": entry["arm"],
                        "read_call_ordinal": entry["read_call_ordinal"],
                        "legacy_tokens": old_tokens, "strict_tokens": strict_tokens,
                        "default_tokens": default_tokens, "deferred": deferred,
                        **checked})
    result = {"protocol": "legacy-v7-read-only-diagnostic-v1",
              "view": "contextual-material-view-v1", "tokenizer_path": str(tokenizer_path),
              "tokenizer_json_sha256": manifest["tokenizer_json_sha256"],
              "material_view_sha256": hashlib.sha256((
                  ROOT / "src/milai_lab/methods/contextual_memory/material_view.py"
              ).read_bytes()).hexdigest(),
              "offline_tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
              "legacy_tokens": sum(item["legacy_tokens"] for item in details),
              "strict_tokens": sum(item["strict_tokens"] for item in details),
              "default_tokens": sum(item["default_tokens"] for item in details),
              "by_case_arm": dict(totals), "receipts": details,
              "audit_checks": {
                  "strict_selected_body_ranges": (
                      "all selected recorded body characters at exact ref and offset"
                  ),
                  "metadata": (
                      "status, role, applicability limits, conditions, context, current ref"
                  ),
                  "relations": "necessary corrections and provenance/prior expansion links",
                  "legacy_protocol": "v7 read-only diagnosis; not v5 ingestion evidence",
              }}
    assert result["strict_tokens"] < result["legacy_tokens"]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "legacy_tokens", "strict_tokens", "default_tokens",
    )},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
