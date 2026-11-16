"""Finite record tasks with executable, deliberately narrow evidence semantics.

This is a controlled research task, not a natural-language benchmark. Source
records, question predicates and packet coverage are public; expected answers
stay offline. Each root supplies contrasting queries over the same source bank.
"""
from __future__ import annotations

import json
import random
import string
from typing import Any

PROTOCOL = (
    "Controlled registry task. Each source is a JSON record with subject, field, value, "
    "valid_from and valid_until. For the requested subject and each requested field, "
    "use the unique record with valid_from <= as_of < valid_until. Other subjects and "
    "dates do not apply. Records are authoritative only within that interval. Return "
    "the exact field-to-value JSON object serialized as the answer string; preserve "
    "field and value spelling. Cite delivered records. Explain missing evidence rather "
    "than guessing. The registry guarantees at most one applicable record per field."
)
FIELDS = ("owner", "room", "code", "limit", "color", "status")


def make_root(index: int, split: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed + index * 104729)  # noqa: S311 -- reproducible fixture

    def token(prefix: str) -> str:
        return prefix + "".join(rng.choices(string.ascii_lowercase, k=9))

    subject, other = token("Unit-"), token("Unit-")
    first, second = rng.sample(FIELDS, 2)
    records = []
    for who, field, start, end in (
        (subject, first, "2025-01-01", "2027-01-01"),
        (subject, second, "2025-01-01", "2027-01-01"),
        (subject, first, "2023-01-01", "2025-01-01"),
        (subject, second, "2027-01-01", "2029-01-01"),
        (other, first, "2025-01-01", "2027-01-01"),
        (other, second, "2025-01-01", "2027-01-01"),
    ):
        records.append({"record_id": token("record-"), "subject": who, "field": field,
                        "value": token("value-"), "valid_from": start, "valid_until": end})
    rng.shuffle(records)  # Neither position nor ID encodes applicability.
    queries = [{"subject": subject, "fields": fields, "as_of": "2026-06-01"}
               for fields in ([first], [second], [first, second])]
    return {"group_id": f"registry-root-{index:05}", "split": split,
            "records": records, "queries": queries, "protocol": PROTOCOL,
            "scope": "Program-defined registry semantics only; no natural task claim"}


def query_text(query: dict[str, Any]) -> str:
    return PROTOCOL + "\nRequested lookup: " + json.dumps(query, sort_keys=True)


def matching_records(records: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    matches: dict[str, Any] = {}
    for record in records:
        if (record["subject"] == query["subject"] and record["field"] in query["fields"]
                and record["valid_from"] <= query["as_of"] < record["valid_until"]):
            field = record["field"]
            if field in matches and matches[field] != record:
                raise ValueError("Controlled task has competing applicable records")
            matches[field] = record
    return matches


def packet_records(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse only actual delivered original sources; no controller-only bodies."""
    records = []
    for item in packet["evidence"]:
        if item["kind"] != "original_source":
            continue
        for source in item["evidence"]:
            try:
                record = json.loads(source["content"])
            except (ValueError, TypeError):
                continue  # Partial source ranges are not complete registry records.
            required = {"record_id", "subject", "field", "value", "valid_from", "valid_until"}
            if isinstance(record, dict) and required <= record.keys() and record not in records:
                records.append(record)
    return records


def packet_coverage(query: dict[str, Any], packet: dict[str, Any]) -> int:
    return len(matching_records(packet_records(packet), query))


def score_first(root: dict[str, Any], query: dict[str, Any], packet: dict[str, Any],
                response: dict[str, Any] | None, *,
                observed_status: str | None = None) -> dict[str, Any]:
    """Grade the fixed registry task, not general natural-language entailment."""
    truth = matching_records(root["records"], query)
    expected = {key: value["value"] for key, value in truth.items()}
    if set(expected) != set(query["fields"]):
        raise ValueError("Fixture lacks an authoritative answer for a requested field")
    material = matching_records(packet_records(packet), query)
    sufficient = all(key in material and material[key] == truth[key] for key in expected)
    answer, execution, output_format = None, "UNKNOWN", "unavailable"
    if response is None and observed_status in {"FAILED", "NOT_EXECUTED"}:
        execution = "FAILED"
    if response is not None:
        execution = ("COMPLETED" if response["choices"][0]["finish_reason"] == "stop"
                     else "FAILED")
        if execution == "COMPLETED":
            output_format = "invalid"
            try:
                outer = json.loads(response["choices"][0]["message"]["content"])
                answer = json.loads(outer["answer"])
                output_format = "valid" if isinstance(answer, dict) else "invalid"
            except (ValueError, TypeError, KeyError):
                pass
    exact = isinstance(answer, dict) and answer == expected
    supported = isinstance(answer, dict) and all(
        key in material and material[key]["value"] == value for key, value in answer.items())
    complete = isinstance(answer, dict) and set(answer) == set(expected)
    primary = None if execution == "UNKNOWN" else (
        execution == "COMPLETED" and sufficient and exact)
    return {"execution_status": execution, "output_format_status": output_format,
            "material_sufficient": sufficient,
            "answer_exact": exact, "answer_supported": supported,
            "answer_complete": complete,
            "primary_outcome": primary,
            "expected_offline": expected, "parsed_answer": answer,
            "label_grade": "A_program_defined_registry_fields_only",
            "limitation": "Does not grade explanation prose or natural-language entailment"}
