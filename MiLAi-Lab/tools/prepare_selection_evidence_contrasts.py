"""Controlled evidence changes with identical candidate actions and questions.

Already observed literal premise copies receive neutral read IDs; all candidates
remain offered. This tests complement selection without forcing a switch merely
by removing an action. It is an authored mechanism probe, not an on-policy trace.
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import selection_payload
from prepare_source_selection import open_target
from reviewed_reader_supervision import reviewed_target


def contrasts(initial: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    if not review["complete_proofs"]:
        return []
    proof = min(review["complete_proofs"], key=lambda p: (len(p), tuple(sorted(p))))
    if len(proof) < 2:
        return []
    pool = initial["metadata"]["pool_source_indices"]
    candidates = initial["state"]["candidates"]
    by_source = dict(zip(pool, candidates, strict=True))
    result = []
    for missing in sorted(proof):
        opened = sorted(set(proof) - {missing})
        observed = [{**by_source[i], "id": f"observed{slot}"}
                    for slot, i in enumerate(opened)]
        target, status = reviewed_target(review, pool, opened)
        target = open_target({"next": {"probabilities": target}})
        result.append({**selection_payload(initial["state"]["question"], observed, candidates),
            "gold": {"next": {"probabilities": target}} if target else {},
            "metadata": {**initial["metadata"],
                "event_id": f"contrast-{review['source_row']}-missing-{missing}",
                "label_status": status, "observed_source_indices": opened,
                "opened_source_indices": opened,
                "prefix_origins": ["controlled_observed_premise_copy"],
                "missing_source_index": missing, "reviewed_proof": proof,
                "source_qualified": review.get("qualified", False),
                "training_allowed": False, "authored_duplicate_premise_probe": True}})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in args.decisions.read_text().splitlines()]
    initial = {r["metadata"]["row"]: r for r in rows if not r["state"]["read_evidence"]}
    reviews = {r["source_row"]: r for r in read_json(args.reviews)["cases"]}
    examples: list[dict[str, Any]] = []
    pairs = []
    for source_row, item in sorted(initial.items()):
        group = contrasts(item, reviews[source_row])
        start = len(examples)
        examples.extend(group)
        for left, right in combinations(range(len(group)), 2):
            ltarget, rtarget = open_target(group[left]["gold"]), open_target(group[right]["gold"])
            if ltarget and rtarget:
                pairs.append({"left": start + left, "right": start + right,
                    "source_row": source_row, "family": item["metadata"]["family"],
                    "requires_choice_change": not (set(ltarget) & set(rtarget))})
    (args.output / "contrasts.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in examples))
    write_json(args.output / "pairs.json", pairs)
    from transformers import AutoTokenizer

    from train_laya_matched import audit

    tokenizer_type: Any = AutoTokenizer
    tok = tokenizer_type.from_pretrained(args.checkpoint / "tokenizer", local_files_only=True)
    lengths = audit(examples, tok, 8192, 512)
    write_json(args.output / "lengths.json", lengths)
    assert not any(r["state_tokens_dropped"] or r["head_tokens_dropped"] for r in lengths)
    report = {"status": "PREPARED_BEFORE_MODEL_FORWARD", "contexts": len(examples),
        "labelled_contexts": sum(bool(r["gold"]) for r in examples), "pairs": len(pairs),
        "families": len({r["metadata"]["family"] for r in examples}),
        "disjoint_target_pairs": sum(p["requires_choice_change"] for p in pairs),
        "max_tokens": max(r["sequence_tokens"] for r in lengths), "model_calls": 0,
        "scope": "Same candidate bodies/actions and question, different observed literal premises. "
                 "Neutral observed IDs do not reveal original candidate IDs. Acceptance on both "
                 "views is primary; require a switch only for disjoint admissible target sets. "
                 "Not natural trajectories or arbitrary semantic intervention robustness.",
        "sha_checks": False, "content_fingerprints": False}
    write_json(args.output / "preparation.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
