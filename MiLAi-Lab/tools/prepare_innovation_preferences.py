"""Pair reviewed local edits with explicit counterfactuals and reviewed actual failures.

This is offline preference data, not a claim that a reference repairs every old
bank error. No original model response or memory bank is modified.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.semantic_delta import compile_delta, indexed_target


def sparse_envelope(envelope):
    result = copy.deepcopy(envelope)
    for create in result.get("creates", []):
        if not create.get("rules"):
            create.pop("rules", None)
    changes = {target: {key: value for key, value in item.items() if value}
               for target, item in result.get("changes", {}).items()}
    result["changes"] = {target: item for target, item in changes.items() if item}
    return {key: value for key, value in result.items() if value}


def prepare(row, observed_reason=None):
    result = copy.deepcopy(row)
    chosen = indexed_target(row["delta_target"])
    proposed = compile_delta(chosen, row["mapping"], indexed=True)
    if proposed:
        negatives = [{"target": {}, "origin": {"kind": "counterfactual_no_change",
            "observed_model_output": False,
            "preference_reason": "The unchanged actual before omits a required edit."}}]
    else:
        current = next(item for item in row["input"]["delivery"]["evidence"]
                       if item.get("delivery_kind", "current") == "current")
        negatives = [{"target": {"creates": [{"nodes": [{
            "text": current["text"], "basis": current["id"], "kind": "reported"}]}]},
            "origin": {"kind": "counterfactual_redundant_copy", "observed_model_output": False,
                       "preference_reason": "The Source retains this acknowledgment/restatement; "
                                            "no semantic operation is needed."}}]
    if observed_reason is not None:
        path = Path(row["provenance"]["request_path"]).with_name("response.json")
        response = json.loads(path.read_text())
        choice = response["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError("Preference response was not a completed model output")
        actual = parse_object(choice["message"]["content"], reject_duplicate_keys=True)
        negatives.append({"target": indexed_target(actual), "origin": {
            "kind": "observed_model_output", "observed_model_output": True,
            "response_path": str(path), "source_version": row["provenance"]["source_version"],
            "preference_reason": observed_reason,
            "conversion": "Program labels/positional node references only; no semantic repair."}})
    unique = []
    for negative in negatives:
        negative["target"] = sparse_envelope(negative["target"])
        operations = compile_delta(negative["target"], row["mapping"], indexed=True)
        if operations == proposed:
            raise ValueError("Preference alternatives compile to identical operations")
        prior = next((item for item in unique if item["operations"] == operations), None)
        if prior is None:
            unique.append({"target": negative["target"], "origins": [negative["origin"]],
                           "operations": operations})
        else:
            prior["origins"].append(negative["origin"])
    result["rejected"] = [{key: value for key, value in item.items() if key != "operations"}
                          for item in unique]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    rows = [json.loads(line) for line in args.references.read_text().splitlines() if line.strip()]
    paired = [prepare(row, config["observed_negatives"].get(row["example_id"])) for row in rows]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in paired))
    args.output.with_suffix(".preparation.json").write_text(json.dumps({
        "examples": len(paired), "source_chains": len({r["provenance"]["owner"] for r in rows}),
        "distinct_rejected_actions": sum(len(row["rejected"]) for row in paired),
        "observed_response_origins": sum(origin["observed_model_output"] for row in paired
            for negative in row["rejected"] for origin in negative["origins"]),
        "model_calls": 0, "parameter_updates": 0, "semantic_bank_writes": 0,
        "scope": config["scope"], "config": str(args.config),
        "authoring_review_cost": "Not separately metered; not zero.",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
