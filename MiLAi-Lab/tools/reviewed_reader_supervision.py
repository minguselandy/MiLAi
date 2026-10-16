"""Source-reviewed alternatives and ambiguity masks on frozen decision inputs.

Proofs are offline annotations, not runtime features. Each proof is a conjunction
of source paragraph indices; the list of proofs is a disjunction. This marks
admissible next evidence, not an optimal cost policy or exhaustive world knowledge.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import STOP_EXHAUSTED, STOP_SUFFICIENT


def reviewed_target(review: dict, pool: list[int], opened: list[int]) -> tuple[dict, str]:
    if review["disposition"] == "masked":
        return {}, "masked_source_review"
    seen = set(opened)
    proofs = [set(path) for path in review["complete_proofs"]]
    if any(proof <= seen for proof in proofs):
        return {STOP_SUFFICIENT: 1.0}, "reviewed_proof_complete"
    if review["disposition"] == "supported":
        feasible = [proof for proof in proofs if proof <= seen | set(pool)]
        if not feasible:
            return {}, "masked_reviewed_retrieval_gap"
        useful = set().union(*(proof - seen for proof in feasible))
    elif review["disposition"] == "pool_insufficient":
        # An incomplete pool can still offer a grounded entity/premise to read.
        useful = set(review["useful_partial_evidence"]) - seen
    else:
        raise ValueError("Unknown source-review disposition")
    actions = [f"open_p{i}" for i, source_index in enumerate(pool) if source_index in useful]
    if actions:
        return {key: 1 / len(actions) for key in actions}, "reviewed_missing_complement"
    if review["disposition"] == "pool_insufficient":
        return {STOP_EXHAUSTED: 1.0}, "reviewed_pool_insufficient"
    return {}, "masked_reviewed_retrieval_gap"


def relabel(rows: list[dict], reviews: list[dict], split: str) -> tuple[list[dict], dict]:
    by_row = {r["source_row"]: r for r in reviews if r["split"] == split}
    results, changes = [], []
    for index, row in enumerate(rows):
        metadata = row["metadata"]
        if metadata["row"] not in by_row:
            continue
        review = by_row[metadata["row"]]
        if metadata["split"] != split or metadata["family"] != review["family"]:
            raise ValueError("Source review crossed its original split or family")
        target, reason = reviewed_target(review, metadata["pool_source_indices"],
                                         metadata["opened_source_indices"])
        result = copy.deepcopy(row)
        result["reference_gold"] = result["gold"]
        result["gold"] = {"next": {"probabilities": target}} if target else {}
        result["metadata"].update(original_state_index=index,
            original_label_status=metadata["label_status"], label_status=reason,
            label_scope="Source-reviewed closed-pool annotation, not all semantic proofs",
            review_id=review["review_id"], reviewer_is_independent=False,
            training_allowed=split == "train")
        if result["gold"] != row["gold"]:
            changes.append({"event_id": metadata["event_id"], "source_row": metadata["row"],
                            "from": row["gold"], "to": result["gold"], "reason": reason})
        results.append(result)
    found = {r["metadata"]["row"] for r in results}
    if found != set(by_row):
        raise ValueError("A reviewed source row is absent from the frozen decision split")
    return results, {"states": len(results), "source_rows": len(found),
        "families": len({r["metadata"]["family"] for r in results}),
        "labelled": sum(bool(r["gold"]) for r in results),
        "label_status": dict(Counter(r["metadata"]["label_status"] for r in results)),
        "changed_states": len(changes), "changes": changes,
        "runtime_inputs_unchanged": all(
            {k: r[k] for k in ("state", "questions")} == {
                k: rows[r["metadata"]["original_state_index"]][k] for k in ("state", "questions")}
            for r in results)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    review = read_json(args.review)
    stats = {}
    for split in ("train", "dev"):
        rows = [json.loads(x) for x in (args.decisions / f"{split}.jsonl").read_text().splitlines()]
        labelled, stats[split] = relabel(rows, review["cases"], split)
        (args.output / f"{split}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in labelled))
    write_json(args.output / "preparation.json", {
        "status": "SOURCE_REVIEWED_PILOT_PREPARED", "source": str(args.decisions.resolve()),
        "review": str(args.review.resolve()), "splits": stats,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "new_model_calls": 0, "calibration_test_loaded": False,
        "scope": "Selected source-review pilot; dev stays evaluation-only. "
                 "Original data, weights, predictions and official QA scores unchanged."})


if __name__ == "__main__":
    main()
