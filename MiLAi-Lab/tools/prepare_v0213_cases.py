"""Open only the frozen discovery prefix and isolate online/evaluator artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from replay_v0213_cost import read, save, sha


def normalize_schema(value):
    """The release mixes Python type names and JSON Schema type names."""
    types = {"dict": "object", "str": "string", "int": "integer", "float": "number",
             "bool": "boolean", "list": "array", "tuple": "array"}
    if isinstance(value, list):
        return [normalize_schema(item) for item in value]
    if isinstance(value, dict):
        return {key: types.get(item, item) if key == "type" and isinstance(item, str)
                else normalize_schema(item) for key, item in value.items()}
    return value


def prepare(root: Path) -> dict:
    if (root / "accepted.json").exists():
        return read(root / "accepted.json")
    sealed = root / "seal-a.json"
    assert sha(sealed.read_bytes()) == read(root / "seal-a-sha256.json")["sha256"]
    seal = read(sealed)
    release = root / "release/Mem2ActBench"
    # Decode only accepted candidate rows; all other corpus bytes remain unpresented.
    query_lines = (release / "qa_dataset.jsonl").read_bytes().splitlines()
    session_lines = (release / "toolmem_conversation.jsonl").read_bytes().splitlines()
    qmeta = json.loads((root / "qa_dataset-metadata.json").read_text())
    smeta = json.loads((root / "toolmem_conversation-metadata.json").read_text())
    qrows = {row["qa_id"]: row["row"] for row in qmeta}
    srows = {row["session_id"]: row["row"] for row in smeta}
    accepted, screening = [], []
    for cluster in seal["discovery"][:seal["screen_limit"]]:
        qid = cluster["representative_qa"]
        record = json.loads(query_lines[qrows[qid]])
        reason = None
        tool = record.get("target_tool_schema")
        expected = record.get("tool_call")
        if not isinstance(tool, dict) or not isinstance(expected, dict):
            reason = "MISSING_TOOL_CONTRACT"
        elif tool.get("name") != expected.get("name"):
            reason = "REFERENCE_TOOL_SCHEMA_DISAGREEMENT"
        elif not isinstance(record.get("query"), str) or not record["query"].strip():
            reason = "MISSING_QUERY"
        elif list(Draft202012Validator(normalize_schema(tool["parameters"])).iter_errors(
                expected["arguments"])):
            reason = "REFERENCE_PARAMETERS_VIOLATE_SCHEMA"
        status = "REJECT_BEFORE_ACCEPT" if reason else "ACCEPT"
        screening.append({"qa_id": qid, "cluster_id": cluster["cluster_id"],
                          "status": status, "reason": reason, "body_review_opened": True})
        if reason:
            continue
        key = f"task-{len(accepted) + 1:02d}"
        online, evaluation = root / "online" / key, root / "evaluation" / key
        online.mkdir(parents=True, exist_ok=True)
        evaluation.mkdir(parents=True, exist_ok=True)
        sources = {}
        for sid in seal["history_mapping"][qid]:
            raw = session_lines[srows[sid]] + b"\n"
            path = sid + ".jsonl"
            (online / path).write_bytes(raw)
            sources[path] = sha(raw)
        save(online / "source-index.json", sources)
        # Only the question and author-provided known-tool schema cross this boundary.
        save(online / "task.json", {"question": record["query"], "business_tools": [tool],
                                   "tools_mode": "KNOWN_TOOL_PARAMETER_GROUNDING",
                                   "action_mode": "ACTION_INTENT_ONLY"})
        save(evaluation / "reference.json", record)
        save(evaluation / "evaluation-contract.json", {
            "status": "AWAITING_PREGENERATION_SUPPORT_REVIEW",
            "expected_intent": [{"name": expected["name"], "arguments": expected["arguments"]}],
            "score": "Complete JSON intent; key order irrelevant; bool distinct from number",
            "schema_adapter": "Python dict/str/int/float/bool/list/tuple types to JSON Schema",
            "equivalences": "NONE_UNLESS_PREDECLARED_IN_REVIEW",
            "reference_schema_valid": True,
            "tool_selection_scored": False, "external_execution": False,
            "source_sessions": seal["history_mapping"][qid],
            "reference_sha256": sha(query_lines[qrows[qid]]),
        })
        accepted.append({"key": key, "qa_id": qid, "cluster_id": cluster["cluster_id"],
                         "source_hashes": sources,
                         "task_sha256": sha((online / "task.json").read_bytes()),
                         "status": "ACCEPTED_NOT_RUN"})
        if len(accepted) == seal["accept_limit"]:
            break
    result = {"status": "PREFIX_ACCEPTED_PENDING_SEAL_B", "accepted": accepted,
              "first_wave": [r["key"] for r in accepted[:2]], "screening": screening,
              "confirmation_body_opened": False, "new_generations": 0}
    save(root / "accepted.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root)
    print(json.dumps(result, indent=2))
