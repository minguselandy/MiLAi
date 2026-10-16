"""Derive bounded evidence decisions only after MuSiQue source-family splitting.

Gold proof structure is offline supervision. Runtime input consists of the
question and literal candidate/read paragraphs, never decomposed questions,
answers, answerability, support flags or family identifiers.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from milai_lab.methods.bounded_evidence import (
    STOP_EXHAUSTED,
    STOP_SUFFICIENT,
    decision_payload,
)


def text_key(paragraph: dict[str, Any]) -> tuple[str, str]:
    return paragraph["title"], paragraph["paragraph_text"]


def ranked_pool(row: dict[str, Any], limit: int) -> list[int]:
    """Fixed lexical retrieval reads no gold and never inserts missing supports."""
    documents = [re.findall(r"\w+", (p["title"] + " " + p["paragraph_text"]).lower())
                 for p in row["paragraphs"]]
    scores = BM25Okapi(documents).get_scores(re.findall(r"\w+", row["question"].lower()))
    return sorted(range(len(documents)), key=lambda i: (-scores[i], i))[:limit]


def action_supervision(
    row: dict[str, Any], pool: list[int], opened: list[int],
) -> tuple[dict[str, float], str]:
    """Reference-proof supervision, including literal equivalent support copies.

    An answerable full context with a missing retrieved premise does not prove
    exhaustion: mask that state instead of inventing a negative answerability label.
    Official unanswerable contexts support only a pool-relative insufficient STOP.
    """
    paragraphs = row["paragraphs"]
    required = {text_key(p) for p in paragraphs if p["is_supporting"]}
    seen = {text_key(paragraphs[i]) for i in opened}
    missing = required - seen
    if row["answerable"] and required and not missing:
        return {STOP_SUFFICIENT: 1.0}, "reference_proof_complete"
    choices: dict[tuple[str, str], list[str]] = defaultdict(list)
    for i in pool:
        key = text_key(paragraphs[i])
        if i not in opened and key in missing:
            choices[key].append(f"open_p{pool.index(i)}")
    if choices:
        return {action: 1 / len(choices) / len(equivalents)
                for equivalents in choices.values() for action in equivalents}, "missing_complement"
    if not row["answerable"]:
        return {STOP_EXHAUSTED: 1.0}, "official_unanswerable_pool"
    return {}, "masked_retrieval_gap_or_unannotated_alternative"


def derive_states(record: dict[str, Any], pool_size: int) -> list[dict[str, Any]]:
    row, metadata = record["source"], record["metadata"]
    pool = ranked_pool(row, pool_size)
    items = {i: {"id": f"p{j}", "title": row["paragraphs"][i]["title"],
                 "text": row["paragraphs"][i]["paragraph_text"]}
             for j, i in enumerate(pool)}
    required = {text_key(p) for p in row["paragraphs"] if p["is_supporting"]}
    in_pool = {text_key(row["paragraphs"][i]) for i in pool}
    # Baseline-visited states plus offline expert prefixes teach missing complements.
    # Prefix provenance is metadata, never a runtime feature.
    prefixes: dict[tuple[int, ...], str] = {}
    for count in (0, 1, 2, 4):
        prefixes.setdefault(tuple(pool[:count]), "bm25_prefix")
    proof = [i for i in pool if text_key(row["paragraphs"][i]) in required]
    for count in range(1, len(proof) + 1):
        prefixes.setdefault(tuple(proof[:count]), "reference_prefix")
    result = []
    for prefix, origin in prefixes.items():
        opened = list(prefix)
        target, label_status = action_supervision(row, pool, opened)
        payload = decision_payload(row["question"], [items[i] for i in opened],
                                   [items[i] for i in pool if i not in opened])
        result.append({**payload,
                       "gold": {"next": {"probabilities": target}} if target else {}, "metadata": {
            **metadata, "event_id": f"row-{metadata['row']}-prefix-{len(result)}",
            "prefix_origin": origin, "label_status": label_status,
            "answerable_full_context": row["answerable"],
            "reference_support_covered": required <= in_pool,
            "missing_support_paragraphs": len(required - in_pool),
            "pool_source_indices": pool, "opened_source_indices": opened,
            "known_support_groups": len(required),
            "label_scope": "Annotated proof and literal equivalents; not all semantic proofs",
        }})
    return result


def sample_families(records: list[dict[str, Any]], limit: int, seed: int) -> list[dict[str, Any]]:
    """One answerable/unanswerable variant pair per family; no giant-family dominance."""
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        families[record["metadata"]["family"]].append(record)
    rng = random.Random(seed)  # noqa: S311 -- reproducible data selection
    selected = sorted(families)
    rng.shuffle(selected)
    result = []
    for family in selected[:limit]:
        rows = families[family]
        positive = [r for r in rows if r["source"]["answerable"]]
        anchor = rng.choice(positive or rows)
        result.append(anchor)
        partners = [r for r in rows if r["source"]["id"] == anchor["source"]["id"]
                    and r["source"]["answerable"] != anchor["source"]["answerable"]]
        if partners:
            result.append(rng.choice(partners))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--train-families", type=int, default=64)
    parser.add_argument("--evaluation-families", type=int, default=24)
    parser.add_argument("--pool-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    statistics = {}
    for split in ("train", "dev", "calibration", "test"):
        with (args.families / f"{split}.jsonl").open() as source:
            records = [json.loads(line) for line in source]
        limit = args.train_families if split == "train" else args.evaluation_families
        sampled = sample_families(records, limit, args.seed)
        states = [state for record in sampled for state in derive_states(record, args.pool_size)]
        with (args.output / f"{split}.jsonl").open("w") as out:
            for state in states:
                out.write(json.dumps(state, ensure_ascii=False) + "\n")
        statistics[split] = {
            "families": len({r["metadata"]["family"] for r in sampled}),
            "source_rows": len(sampled), "states": len(states),
            "label_status": dict(Counter(r["metadata"]["label_status"] for r in states)),
            "prefix_origin": dict(Counter(r["metadata"]["prefix_origin"] for r in states)),
            "source_rows_answerability": dict(Counter(str(r["source"]["answerable"])
                                                       for r in sampled)),
            "source_rows_reference_covered": len({
                r["metadata"]["row"] for r in states
                if r["metadata"]["reference_support_covered"]}),
        }
    summary = {"splits": statistics, "pool_size": args.pool_size, "seed": args.seed,
               "family_source": str(args.families.resolve()),
               "wall_seconds": time.perf_counter() - started,
               "cpu_seconds": time.process_time() - cpu, "model_calls": 0,
               "scope": "Derived reference-proof decisions; not downstream QA or calibrated STOP",
               "sampling": "At most one paired question per family before prefix expansion",
               "loss_weighting": "Normalize prefixes per source event, then events per family"}
    (args.output / "preparation.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
