"""Build shared mixed-corpus inputs, then project full source/reference supervision.

Natural prefixes and both supervision schemes' expert prefixes share the same
literal pool and aliases. Only prefixes of fewer than four reads are decisions;
the actual fixed4 trajectory is evaluated separately. No model forward occurs.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import decision_payload
from prepare_musique_decisions import action_supervision, ranked_pool, text_key
from prepare_source_selection import project


def effective_reviews(snapshot: dict[str, Any], addenda: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(snapshot)
    by_row = {r["source_row"]: r for r in result["cases"]}
    for item in addenda["cases"]:
        review = by_row[item["source_row"]]
        review["complete_proofs"].extend(item["additional_complete_proofs"])
        review["projection_addendum"] = item
    return result


def derive(record: dict[str, Any], review: dict[str, Any], seed: int,
           read_budget: int = 4) -> list[dict[str, Any]]:
    source, meta = record["source"], record["metadata"]
    rng = random.Random(seed + meta["row"])  # noqa: S311 -- fixed offline sampling
    lexical = ranked_pool(source, len(source["paragraphs"]))
    pool = list(lexical)
    rng.shuffle(pool)
    items = {idx: {"id": f"p{slot}", "title": source["paragraphs"][idx]["title"],
                   "text": source["paragraphs"][idx]["paragraph_text"]}
             for slot, idx in enumerate(pool)}
    prefixes: dict[tuple[int, ...], list[str]] = {}

    def add(opened: list[int], origin: str) -> None:
        key = tuple(sorted(set(opened)))
        if len(key) < read_budget:
            prefixes.setdefault(key, []).append(origin)

    add([], "empty")
    random_order = list(pool)
    rng.shuffle(random_order)
    for count in range(1, read_budget):
        add(lexical[:count], "bm25_prefix")
        add(random_order[:count], "random_prefix")
    required = {text_key(p) for p in source["paragraphs"] if p["is_supporting"]}
    representatives = {text_key(source["paragraphs"][idx]): idx for idx in pool
                       if text_key(source["paragraphs"][idx]) in required}
    paths = [(list(representatives.values()), "reference")]
    paths += [(path, "reviewed") for path in review["complete_proofs"]]
    paths += [(path, "qualified") for path in review.get("qualified_alternative_proofs", [])]
    partial_groups = review.get("partial_evidence_groups",
                                [[i] for i in review["useful_partial_evidence"]])
    paths += [([next(i for i in pool if i in group) for group in partial_groups], "partial")]
    for path, origin in paths:
        add(path, origin + "_complete")
        for missing in path:
            add([i for i in path if i != missing], origin + "_leave_one_out")
        for count in range(1, min(read_budget, len(path))):
            add(path[:count], origin + "_prefix")
    rows: list[dict[str, Any]] = []
    for key, origins in prefixes.items():
        opened = [i for i in pool if i in key]
        target, status = action_supervision(source, pool, opened)
        payload = decision_payload(source["question"], [items[i] for i in opened],
                                   [items[i] for i in pool if i not in opened])
        rows.append({**payload, "gold": {"next": {"probabilities": target}} if target else {},
            "metadata": {**meta, "event_id": f"selection-row-{meta['row']}-state-{len(rows)}",
                "training_event": f"{meta['dataset']}:{meta['question_id']}",
                "prefix_origins": origins, "label_status": status,
                "label_scope": "Native reference before source/open-only projection",
                "pool_source_indices": pool, "opened_source_indices": opened,
                "bm25_source_indices": lexical, "read_budget": read_budget}})
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("addenda", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--max-len", type=int, default=8192)
    parser.add_argument("--head-max-len", type=int, default=512)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    records = [json.loads(line) for line in args.sources.read_text().splitlines()]
    snapshot = read_json(args.reviews)
    reviews = effective_reviews(snapshot, read_json(args.addenda))
    by_row = {r["source_row"]: r for r in reviews["cases"]}
    assert {r["metadata"]["row"] for r in records} == set(by_row)
    rows = [r for record in records for r in derive(
        record, by_row[record["metadata"]["row"]], args.seed)]
    for state_id, row in enumerate(rows):
        row["metadata"]["state_id"] = state_id
    write_json(args.output / "effective-reviews.json", reviews)
    write_rows(args.output / "reference-decisions-before-projection.jsonl", rows)
    from transformers import AutoTokenizer

    from train_laya_matched import audit

    tokenizer_type: Any = AutoTokenizer
    tok = tokenizer_type.from_pretrained(args.checkpoint / "tokenizer", local_files_only=True)
    summary, lengths, exports_by_split = {}, {}, {}
    for split in ("train", "dev"):
        selected = [r for r in rows if r["metadata"]["split"] == split]
        exports, stats = project(selected, reviews["cases"], split)
        exports_by_split[split] = exports
        lengths[split] = audit(exports["source"], tok, args.max_len, args.head_max_len)
        for name, exported in exports.items():
            write_rows(args.output / name / f"{split}.jsonl", exported)
        summary[split] = {k: v for k, v in stats.items() if k != "source_review"}
        summary[split]["recipes"] = {name: {
            "states": len(exported), "labelled": sum(bool(r["gold"]) for r in exported),
            "fitted_families": len({r["metadata"]["family"] for r in exported if r["gold"]}),
            "label_status": dict(Counter(r["metadata"]["label_status"] for r in exported))}
            for name, exported in exports.items()}
    write_json(args.output / "lengths.json", lengths)
    oversized = [r for batch in lengths.values() for r in batch
                 if r["state_tokens_dropped"] or r["head_tokens_dropped"]]
    for exports in exports_by_split.values():
        assert all({k: left[k] for k in ("state", "questions")} == {
            k: right[k] for k in ("state", "questions")}
            for left, right in zip(exports["source"], exports["reference"], strict=True))
    report = {"status": "PREPARED" if not oversized else "INPUT_CAPACITY_FAILED",
        "splits": summary, "max_tokens": max(r["sequence_tokens"]
                                              for batch in lengths.values() for r in batch),
        "oversized_states": oversized, "shared_visible_inputs": True,
        "state_scope": "Empty,BM25/random1..3,both reference/reviewed proof leave-one/prefixes, "
                       "qualified and partial-premise states. Expert origins are offline metadata. "
                       "Not on-policy trajectories or a STOP training objective.",
        "all_source_cases_retained": len(records), "model_calls": 0,
        "sha_checks": False, "content_fingerprints": False,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu}
    write_json(args.output / "preparation.json", report)
    print(json.dumps({"splits": {s: v["recipes"] for s, v in summary.items()},
                      "max_tokens": report["max_tokens"], "oversized": len(oversized)}))
    if oversized:
        raise ValueError("Full input capacity failed; no states were silently truncated or removed")


if __name__ == "__main__":
    main()
