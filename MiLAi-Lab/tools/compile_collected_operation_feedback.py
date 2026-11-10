"""Bind actual branch readouts and compile explicit native-witness feedback, retaining unknowns."""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from prepare_handoff_feedback import reviewed_relation
from retrieval_feedback import feedback_counts, validate_feedback


def witness_relation(left: bool | None, right: bool | None) -> str:
    """A coarse recorded-reference endpoint, never a semantic sufficiency judgment."""
    if left is True and right is True:
        return "tie"
    if left is True and right is False:
        return "left"
    if left is False and right is True:
        return "right"
    return "unknown"


def compile_case(
    row: dict[str, Any],
    branches: list[dict[str, Any]],
    reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = copy.deepcopy(row)
    result["gold"] = {}
    pairs = []
    for a, b in itertools.combinations(branches, 2):
        left, right = a["action"]["id"], b["action"]["id"]
        quality = witness_relation(a["reference_proof_complete"], b["reference_proof_complete"])
        answer = "unknown"
        if reviews is not None:
            ar, br = reviews.get(left, {}), reviews.get(right, {})
            quality = reviewed_relation(
                ar.get("material_status", "unknown"),
                br.get("material_status", "unknown"),
                "delivery",
            )
            answer = reviewed_relation(
                ar.get("answer_status", "unknown")
                if a["readout_status"] == "COMPLETED"
                else "unknown",
                br.get("answer_status", "unknown")
                if b["readout_status"] == "COMPLETED"
                else "unknown",
                "answer",
            )
        pairs.append(
            {
                "left": left,
                "right": right,
                "answer": answer,
                "delivery": quality,
                "actual_readouts": [a["readout"], b["readout"]],
            }
        )
    result["feedback"] = {"comparisons": pairs}
    result["metadata"]["feedback_semantics"] = (
        "source_reviewed_material_and_answer"
        if reviews is not None
        else "native_reference_witness_coverage_NOT_semantic_sufficiency_or_Host_success"
    )
    validate_feedback(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("readouts", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    preparation = read_json(args.prepared / "run.json")
    readout_run = read_json(args.readouts / "run.json")
    if (
        preparation["status"] != "COMPLETED"
        or readout_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}
        or Path(readout_run["prepared"]).resolve() != args.prepared.resolve()
    ):
        raise ValueError("Compile only a closed first-readout matrix bound to this preparation")
    cases = read_json(args.prepared / "cases.json")
    rows = read_jsonl(args.prepared / "states.jsonl")
    paths = read_json(args.readouts / "readout-paths.json")
    collection = Path(preparation["collection"])
    collection_run = read_json(collection / "run.json")
    controls = {
        (c["source_group"], c["request_id"]): c
        for c in read_jsonl(Path(collection_run["controls"]))
    }
    # Read only completed selected events, even while later collection families are running.
    selected_ids = {case["event_id"] for case in cases}
    original = {}
    with (collection / "states.jsonl").open() as stream:
        for line in stream:
            value = json.loads(line)
            if value["metadata"]["event_id"] in selected_ids:
                original[value["metadata"]["event_id"]] = value
                if len(original) == len(selected_ids):
                    break
    review_source = read_json(args.reviews) if args.reviews else None
    supplied = (
        {}
        if review_source is None
        else {(r["event_id"], r["actual_action"]["id"]): r for r in review_source["records"]}
    )
    compiled, review_inputs, sft, matched = [], [], [], []
    for case in cases:
        row = rows[case["state_index"]]
        if row["metadata"]["event_id"] != case["event_id"] or row["metadata"]["split"] != "train":
            raise ValueError("Feedback state identity or research role changed")
        bound = []
        reviews = None if review_source is None else {}
        for branch in case["branches"]:
            candidates = {paths[p][case["case_key"]] for p in branch["policies"]}
            if len(candidates) != 1:
                raise ValueError("Shared full binding was not assigned one actual readout")
            path = Path(candidates.pop())
            record = read_json(path)
            if (
                record["event_id"] != case["event_id"]
                or record["family"] != case["family"]
                or record["action"] != branch["action"]
                or read_json(Path(record["request"])) != branch["readout_request"]
            ):
                raise ValueError("Readout differs from its executed action, packet or public task")
            actual = {
                **branch,
                "readout": str(path.resolve()),
                "readout_status": record["status"],
                "answer": record["answer"],
                "usage": record.get("usage"),
                "reference_proof_complete": branch["reference_proof_complete"]
                if branch["execution_result"]["ok"]
                else None,
            }
            bound.append(actual)
            review = supplied.get((case["event_id"], branch["action"]["id"]))
            if review is not None:
                if (
                    review["actual_action"] != branch["action"]
                    or Path(review["readout"]).resolve() != path.resolve()
                ):
                    raise ValueError("Semantic review differs from the bound first outcome")
                reviews[branch["action"]["id"]] = review
        feedback = compile_case(row, bound, reviews)
        compiled.append(feedback)
        review_inputs.append(
            {
                "event_id": case["event_id"],
                "family": case["family"],
                "question": case["before"]["task"]["request"],
                "native_control": controls[case["family"], case["request_id"]],
                "branches": bound,
            }
        )
        base = original[case["event_id"]]
        if base["state"] != row["state"] or base["questions"] != row["questions"]:
            raise ValueError("Source-matched SFT example changed the actual model input")
        if base["gold"] and any(
            p["delivery"] in {"left", "right"} for p in feedback["feedback"]["comparisons"]
        ):
            matched.append(feedback)
            sft.append(base)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, records in (
        ("raw-feedback", compiled),
        ("matched-feedback", matched),
        ("matched-sft", sft),
    ):
        with (args.output / f"{name}.jsonl").open("w") as stream:
            for row in records:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "review-inputs.json", review_inputs)
    write_json(
        args.output / "manifest.json",
        {
            "status": "BOUND_BRANCH_FEEDBACK_COMPILED_NOT_FITTED",
            "prepared": str(args.prepared.resolve()),
            "readouts": str(args.readouts.resolve()),
            "reviews": str(args.reviews) if args.reviews else None,
            "states": len(compiled),
            "families": len({r["metadata"]["family"] for r in compiled}),
            "matched_states": len(matched),
            "readout_status": dict(
                Counter(b["readout_status"] for r in review_inputs for b in r["branches"])
            ),
            "feedback": {
                target: feedback_counts(compiled, target) for target in ("answer", "delivery")
            },
            "no_sha_validation": True,
            "new_model_calls": 0,
            "scope": "Native-witness proxy and semantic review use separate versions. "
            "Both-incomplete and missing judgments stay unknown. Same-input SFT is retained "
            "on shared directional support; no fitted model or generalization claim.",
            "compute": {
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        },
    )


if __name__ == "__main__":
    main()
