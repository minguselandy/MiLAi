"""Released Mem2Act GivenTool inputs and separate offline accounting.

The primary memory bank contains the full released session sequence. Gold source
IDs describe coverage and correlation; they never select the online search pool.
No generation, business execution, source repair or content fingerprints occur here.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter, defaultdict
from typing import Any


def given_tool_input(row: dict[str, Any]) -> dict[str, Any]:
    """Only the published query and supplied target documentation reach the Host."""
    return copy.deepcopy({key: row[key] for key in ("query", "target_tool_schema")})


def public_history(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep every session/turn, including distractors and unusual released roles.

    The normalizer's per-turn source_id is offline lineage, not conversation text.
    A tool argument named source_id remains intact inside its historical call.
    """
    return [{"session_id": session["session_id"],
             "turns": [copy.deepcopy({key: value for key, value in turn.items()
                                      if key != "source_id"}) for turn in session["turns"]]}
            for session in sessions]


def source_coverage(
    rows: list[dict[str, Any]], sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Audit declared lineage without shrinking the evaluation or filling gaps.

    Connected components describe shared target sources/full sessions. They are
    not independent users: the primary experiment has one common released bank.
    """
    source_sessions: dict[str, list[int]] = defaultdict(list)
    for index, session in enumerate(sessions):
        for source in session["original_conversation_ids"]:
            source_sessions[source].append(index)
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners: dict[str, int] = {}
    cases = []
    for index, row in enumerate(rows):
        requested = set(row["source_conversation_ids"])
        matched = sorted({i for source in requested for i in source_sessions[source]})
        missing = sorted(source for source in requested if not source_sessions[source])
        exposed = requested | {source for i in matched
                               for source in sessions[i]["original_conversation_ids"]}
        for source in exposed:
            if source in owners:
                parent[find(index)] = find(owners[source])
            else:
                owners[source] = index
        cases.append({"qa_id": row["qa_id"], "requested_sources": len(requested),
            "session_indices": matched, "missing_source_ids": missing,
            "schema_name_matches_reference": (
                row["target_tool_schema"]["name"] == row["tool_call"]["name"])})
    groups: dict[int, list[str]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[find(index)].append(row["qa_id"])
    components = list(groups.values())
    return {"cases": cases, "source_components": components,
        "counts": {"qa": len(rows), "sessions": len(sessions),
            "no_declared_sources": sum(not row["source_conversation_ids"] for row in rows),
            "no_matched_sessions": sum(not case["session_indices"] for case in cases),
            "partially_missing_sources": sum(bool(case["session_indices"])
                and bool(case["missing_source_ids"]) for case in cases),
            "missing_source_ids": len({source for case in cases
                                       for source in case["missing_source_ids"]}),
            "schema_name_mismatches": sum(not case["schema_name_matches_reference"]
                                          for case in cases),
            "source_components": len(components)},
        "component_sizes": dict(Counter(map(len, components))),
        "released_roles": dict(Counter(turn["role"] for session in sessions
                                       for turn in session["turns"])),
        "primary_bank": "All released sessions, in release order, for every query; "
                        "no gold-based online corpus filter or independent-user claim."}


def exact_json_value(left: Any, right: Any) -> bool:
    """JSON equality: object order ignored, array order/types retained.

    JSON has one number type, so 1 and 1.0 agree; booleans are not numbers.
    """
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        return (isinstance(right, (int, float)) and not isinstance(right, bool)
                and left == right)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            exact_json_value(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(
            exact_json_value(a, b) for a, b in zip(left, right, strict=True))
    return bool(left == right)


def score_business_calls(
    reference: dict[str, Any], calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Additional MiLAi exact metrics, not an unverified replica of paper TA/F1.

    `calls` contains all predicted business calls, excluding memory tool calls.
    Zero/multiple calls, wrong tool or malformed arguments get no value credit.
    Extra arguments lose strict match even when all expected values are present.
    """
    expected = reference["arguments"]
    predicted = calls[0] if len(calls) == 1 else {}
    name_match = predicted.get("name") == reference["name"]
    valid_arguments = isinstance(predicted.get("arguments"), dict)
    actual = predicted["arguments"] if valid_arguments else {}
    matched = sum(name_match and key in actual and exact_json_value(actual[key], value)
                  for key, value in expected.items())
    precision = matched / len(actual) if actual else 0.0
    recall = matched / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    bleu = 0.0
    if len(calls) == 1 and valid_arguments and isinstance(predicted.get("name"), str):
        # Explicit MiLAi adaptation: case-sensitive Unicode words/punctuation of
        # sorted-key JSON, clipped unigram precision with brevity penalty, no smoothing.
        def tokens(value: dict[str, Any]) -> list[str]:
            call = {"name": value["name"], "arguments": value["arguments"]}
            return re.findall(r"\w+|[^\w\s]", json.dumps(call, ensure_ascii=False,
                              sort_keys=True, allow_nan=False))

        target_tokens, actual_tokens = tokens(reference), tokens(predicted)
        overlap = sum((Counter(target_tokens) & Counter(actual_tokens)).values())
        bleu = (overlap / len(actual_tokens)
                * math.exp(min(0.0, 1 - len(target_tokens) / len(actual_tokens))))
    return {"business_call_count": len(calls), "tool_name_match": name_match,
        "argument_values_correct": matched, "argument_values_total": len(expected),
        "argument_value_accuracy": matched / len(expected) if expected else None,
        "strict_call_match": bool(name_match and valid_arguments
                                  and exact_json_value(actual, expected)),
        "parameter_value_precision": precision, "parameter_value_recall": recall,
        "parameter_value_f1": f1, "bleu1_json_lexical": bleu,
        "scope": "MiLAi adaptation: exact JSON argument pairs for F1, canonical JSON "
                 "word/punctuation BLEU-1. Not verified author implementation or leaderboard "
                 "TA. No default filling, best-of-call selection or real business execution."}
