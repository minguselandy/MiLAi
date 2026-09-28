"""Offline join of declared obligations and human observations; never a semantic judge."""

from __future__ import annotations

import argparse
import copy
import json
import string
from collections.abc import Sequence
from pathlib import Path
from typing import Any

LAYERS = (
    "current_explicit_obligations", "persistent_obligations",
    "later_use_obligations", "diagnostic_completeness",
)
STAGES = (
    "present_in_user_request", "requires_memory", "memory_formed", "memory_delivered",
    "answer_contains", "tool_argument_contains", "world_effect_correct",
)
RESULTS = ("pass", "fail", "unknown", "not_applicable")
STAGE_VALUES = ("yes", "no", "unknown", "not_applicable")
_MANUAL = {"legacy_score", "earliest_breakpoint", "note"}


def _object(value: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if (not isinstance(value, dict) or not required <= value.keys()
            or not value.keys() <= required | (optional or set())):
        raise ValueError("INVALID_OBLIGATION_TRACE_SHAPE")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("INVALID_OBLIGATION_TRACE_TEXT")
    return value


def _rows(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("INVALID_OBLIGATION_TRACE_LIST")
    return value


def _version(value: dict[str, Any]) -> None:
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("INVALID_OBLIGATION_TRACE_VERSION")


def _manual_fields(row: dict[str, Any]) -> dict[str, Any]:
    for name in ("earliest_breakpoint", "note"):
        if name in row and row[name] is not None:
            _text(row[name])
    # Legacy scores are opaque JSON, not recomputed or coerced.
    return {name: copy.deepcopy(row[name]) for name in sorted(_MANUAL) if name in row}


def _contract_cases(contract: dict[str, Any]) -> list[dict[str, Any]]:
    _object(contract, {"schema_version", "runtime_must_not_read", "cases"}, _MANUAL)
    _version(contract)
    if contract["runtime_must_not_read"] is not True:
        raise ValueError("OBLIGATION_CONTRACT_MUST_BE_OFFLINE")
    cases = _rows(contract["cases"])
    if not cases:
        raise ValueError("OBLIGATION_CONTRACT_CASES_EMPTY")
    seen_cases: set[str] = set()
    for case in cases:
        _object(case, {"case_id", "messages", "obligations"}, _MANUAL)
        case_id = _text(case["case_id"])
        if case_id in seen_cases:
            raise ValueError("DUPLICATE_OBLIGATION_CASE")
        seen_cases.add(case_id)
        messages: dict[str, str] = {}
        for row in _rows(case["messages"]):
            _object(row, {"message_id", "text"})
            key = _text(row["message_id"])
            if key in messages:
                raise ValueError("DUPLICATE_OBLIGATION_MESSAGE")
            if not isinstance(row["text"], str):
                raise ValueError("INVALID_OBLIGATION_MESSAGE_TEXT")
            messages[key] = row["text"]
        message_order = {key: index for index, key in enumerate(messages)}
        seen: set[str] = set()
        for row in _rows(case["obligations"]):
            _object(row, {"id", "case_id", "target_message_id", "layer", "description",
                          "task_failing", "basis"})
            key = _text(row["id"])
            if key in seen:
                raise ValueError("DUPLICATE_OBLIGATION_ID")
            seen.add(key)
            if _text(row["case_id"]) != case_id or _text(row["target_message_id"]) not in messages:
                raise ValueError("DANGLING_OBLIGATION_MESSAGE")
            if not isinstance(row["layer"], str) or row["layer"] not in LAYERS:
                raise ValueError("INVALID_OBLIGATION_LAYER")
            _text(row["description"])
            if type(row["task_failing"]) is not bool:
                raise ValueError("INVALID_OBLIGATION_TASK_FAILING")
            diagnostic = row["layer"] == "diagnostic_completeness"
            if diagnostic and row["task_failing"]:
                raise ValueError("DIAGNOSTIC_CANNOT_BE_TASK_FAILING")
            basis = _rows(row["basis"])
            if not basis and not diagnostic:
                raise ValueError("OBLIGATION_REQUIRES_VISIBLE_BASIS")
            for source in basis:
                _object(source, {"message_id", "quote"})
                message_id, quote = _text(source["message_id"]), _text(source["quote"])
                if message_id not in messages or quote not in messages[message_id]:
                    raise ValueError("OBLIGATION_BASIS_NOT_EXACT_VISIBLE_QUOTE")
                if message_order[message_id] > message_order[row["target_message_id"]]:
                    raise ValueError("OBLIGATION_BASIS_NOT_YET_VISIBLE")
    return cases


def _observations(
    observations: dict[str, Any], keys: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    _object(observations, {"schema_version", "observations"}, _MANUAL)
    _version(observations)
    result = {}
    for row in _rows(observations["observations"]):
        _object(row, {"case_id", "obligation_id"}, {"result", "evidence", *STAGES, *_MANUAL})
        key = (_text(row["case_id"]), _text(row["obligation_id"]))
        if key not in keys:
            raise ValueError("DANGLING_OBLIGATION_OBSERVATION")
        if key in result:
            raise ValueError("DUPLICATE_OBLIGATION_OBSERVATION")
        if row.get("result", "unknown") not in RESULTS:
            raise ValueError("INVALID_OBLIGATION_RESULT")
        for stage in STAGES:
            if row.get(stage, "unknown") not in STAGE_VALUES:
                raise ValueError("INVALID_OBLIGATION_STAGE_VALUE")
        _manual_fields(row)
        for evidence in _rows(row.get("evidence", [])):
            _object(evidence, {"path", "sha256", "location"})
            _text(evidence["path"])
            digest = evidence["sha256"]
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(char not in string.hexdigits for char in digest)):
                raise ValueError("INVALID_OBLIGATION_EVIDENCE_HASH")
            location = evidence["location"]
            if not ((isinstance(location, str) and location.strip())
                    or (isinstance(location, dict) and location)):
                raise ValueError("INVALID_OBLIGATION_EVIDENCE_LOCATION")
        result[key] = row
    return result


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {"total": len(rows), **{name: sum(row["result"] == name for row in rows)
                                 for name in RESULTS},
            "missing": sum(row["observation_status"] == "missing" for row in rows)}


def compose_obligation_trace(
    contract: dict[str, Any], observations: dict[str, Any],
) -> dict[str, Any]:
    """Validate references and group manual results; chain values imply no verdict or cause.

    Exact quotes establish mechanical provenance, not natural-language entailment. Evidence
    SHA/location fields are checked for shape; source authentication remains the evaluator's job.
    The case/obligation pair is the identity, including when IDs recur in separate cases.
    """
    cases = _contract_cases(contract)
    keys = {(case["case_id"], row["id"]) for case in cases for row in case["obligations"]}
    observed = _observations(observations, keys)
    joined, all_rows = [], []
    for case in cases:
        rows = []
        for obligation in case["obligations"]:
            observation = observed.get((case["case_id"], obligation["id"]))
            manual = observation or {}
            rows.append({**copy.deepcopy(obligation),
                "observation_status": "provided" if observation is not None else "missing",
                "result": manual.get("result", "unknown"),
                "chain": {stage: manual.get(stage, "unknown") for stage in STAGES},
                "evidence": copy.deepcopy(manual.get("evidence", [])), **_manual_fields(manual)})
        all_rows.extend(rows)
        joined.append({"case_id": case["case_id"], **_manual_fields(case),
            "layers": {layer: [row for row in rows if row["layer"] == layer] for layer in LAYERS},
            "layer_counts": {layer: _counts([row for row in rows if row["layer"] == layer])
                             for layer in LAYERS},
            "explicit_current_including_later_use_counts": _counts([
                row for row in rows if row["layer"] in (LAYERS[0], LAYERS[2])]),
            "task_failing_counts": _counts([row for row in rows if row["task_failing"]])})
    return {"schema_version": 1, "runtime_must_not_read": True, "cases": joined,
        "contract_metadata": _manual_fields(contract),
        "observation_metadata": _manual_fields(observations),
        "layer_counts": {layer: _counts([row for row in all_rows if row["layer"] == layer])
                         for layer in LAYERS},
        "explicit_current_including_later_use_counts": _counts([
            row for row in all_rows if row["layer"] in (LAYERS[0], LAYERS[2])]),
        "task_failing_counts": _counts([row for row in all_rows if row["task_failing"]])}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output is not None and any(
        args.output.resolve() == path.resolve()
        or (args.output.exists() and args.output.samefile(path))
        for path in (args.contract, args.observations)
    ):
        raise ValueError("OBLIGATION_TRACE_OUTPUT_CANNOT_REPLACE_INPUT")
    result = compose_obligation_trace(json.loads(args.contract.read_text()),
                                      json.loads(args.observations.read_text()))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)


if __name__ == "__main__":
    main()
