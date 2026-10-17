"""Broad reference-supervised reader cohorts, sampled before source expansion.

Only admitted train/dev metadata and the original TRAIN mirror are read. The
protected candidate file is not an input. Native annotations remain explicitly
weak supervision; this tool neither invents semantic gold nor relabels answers.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.methods.bounded_evidence import decision_payload
from prepare_musique_decisions import action_supervision, ranked_pool, text_key


def select_questions(
    metadata: list[dict[str, Any]], excluded: set[str], seed: int,
) -> dict[int, list[dict[str, Any]]]:
    """One maximum-step question per family; retain every admitted variant."""
    families: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list))
    for row in metadata:
        if row["question_id"] not in excluded:
            families[row["family"]][row["question_id"]].append(row)
    rng = random.Random(seed)  # noqa: S311 -- frozen sampling, not security
    strata: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for family, questions in sorted(families.items()):
        steps = max(int(q[0]) for q in questions)
        question = rng.choice(sorted(q for q in questions if int(q[0]) == steps))
        strata[steps].append({"family": family, "question_id": question,
                              "steps": steps, "rows": questions[question]})
    for groups in strata.values():
        rng.shuffle(groups)
    return dict(strata)


def derive_global_states(record: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    """Different evidence states share literal sources and random candidate aliases."""
    source, metadata = record["source"], record["metadata"]
    rng = random.Random(seed + metadata["row"])  # noqa: S311 -- reproducible views
    lexical = ranked_pool(source, len(source["paragraphs"]))
    pool = list(lexical)
    rng.shuffle(pool)
    items = {idx: {"id": f"p{slot}", "title": source["paragraphs"][idx]["title"],
                   "text": source["paragraphs"][idx]["paragraph_text"]}
             for slot, idx in enumerate(pool)}
    support_keys = {text_key(p) for p in source["paragraphs"] if p["is_supporting"]}
    representatives = {text_key(source["paragraphs"][idx]): idx for idx in pool
                       if text_key(source["paragraphs"][idx]) in support_keys}
    proof = list(representatives.values())
    rng.shuffle(proof)
    unrelated = [idx for idx in pool if text_key(source["paragraphs"][idx]) not in support_keys]
    prefixes: dict[tuple[int, ...], list[str]] = {}
    for opened, origin in [([], "empty"), (lexical[:2], "bm25_two"),
                           (rng.sample(pool, min(2, len(pool))), "random_two"),
                           (proof[:-1], "reference_leave_one_out"),
                           (proof, "reference_complete"), (unrelated[:2], "unrelated_two")]:
        # Read order is not the supervision unit; avoid duplicated evidence sets.
        prefixes.setdefault(tuple(sorted(opened)), []).append(origin)
    states: list[dict[str, Any]] = []
    for opened_key, origins in prefixes.items():
        opened = [idx for idx in pool if idx in opened_key]
        target, status = action_supervision(source, pool, opened)
        payload = decision_payload(source["question"], [items[i] for i in opened],
                                   [items[i] for i in pool if i not in opened])
        states.append({**payload, "gold": {"next": {"probabilities": target}} if target else {},
            "metadata": {**metadata,
                "event_id": f"global-row-{metadata['row']}-state-{len(states)}",
                "training_event": metadata["question_id"],
                "prefix_origins": origins, "label_status": status,
                "label_scope": "Native reference weak supervision, not source-semantic gold",
                "steps": int(metadata["question_id"][0]),
                "pool_source_indices": pool, "opened_source_indices": opened,
                "bm25_source_indices": lexical, "known_support_groups": len(support_keys),
                "answerable_full_context": source["answerable"],
                "training_allowed": metadata["split"] == "train"}})
    return states


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    selection, selected = {}, {}
    excluded = set(protocol["excluded_question_ids"])
    for role in ("train", "dev"):
        metadata = [json.loads(line) for line in
                    Path(protocol["metadata"][role]).read_text().splitlines()]
        strata = select_questions(metadata, excluded, protocol["data_seed"])
        selection[role] = {str(k): v for k, v in strata.items()}
        if role == "dev":
            selected[role] = [g for groups in strata.values() for g in groups]
        else:
            selected[role] = [g for k, count in protocol["cohorts"][-1]["family_quota"].items()
                              for g in strata[int(k)][:count]]
    write_json(args.output / "selection-before-source-expansion.json", selection)
    by_row = {r["row"]: r for groups in selected.values() for g in groups for r in g["rows"]}
    sources = {}
    with Path(protocol["train_mirror"]).open() as stream:
        for index, line in enumerate(stream):
            if index in by_row:
                source = json.loads(line)
                if source["id"] != by_row[index]["question_id"]:
                    raise ValueError("Source row identity differs from admitted metadata")
                sources[index] = {"source": source, "metadata": by_row[index]}
    write_jsonl(args.output / "selected-sources.jsonl", list(sources.values()))
    states: dict[str, list[dict[str, Any]]] = {
        role: [state for group in groups for meta in group["rows"]
                     for state in derive_global_states(sources[meta["row"]], protocol["data_seed"])]
              for role, groups in selected.items()}
    # Admission is based solely on full input capacity, before any model forward.
    from transformers import AutoTokenizer

    from train_laya_matched import audit

    tokenizer_type: Any = AutoTokenizer
    tok = tokenizer_type.from_pretrained(Path(protocol["base_checkpoint"]) / "tokenizer",
                                        local_files_only=True)
    lengths = {role: audit(rows, tok, protocol["max_len"], protocol["head_max_len"])
               for role, rows in states.items()}
    write_json(args.output / "lengths-before-admission.json", lengths)
    excluded_length = set()
    for role, rows in states.items():
        for row, length in zip(rows, lengths[role], strict=True):
            if length["state_tokens_dropped"] or length["head_tokens_dropped"]:
                excluded_length.add(row["metadata"]["question_id"])
    summary: dict[str, Any] = {}
    for cohort in protocol["cohorts"]:
        name = cohort["name"]
        folder = args.output / name
        folder.mkdir()
        family_set = {g["family"] for k, n in cohort["family_quota"].items()
                      for g in selection["train"][k][:n]}
        summary[name] = {}
        for role in ("train", "dev"):
            rows = [r for r in states[role]
                    if r["metadata"]["question_id"] not in excluded_length
                    and (role == "dev" or r["metadata"]["family"] in family_set)]
            write_jsonl(folder / f"{role}.jsonl", rows)
            summary[name][role] = {
                "states": len(rows), "labelled": sum(bool(r["gold"]) for r in rows),
                "families": len({r["metadata"]["family"] for r in rows}),
                "questions": len({r["metadata"]["question_id"] for r in rows}),
                "source_rows": len({r["metadata"]["row"] for r in rows}),
                "family_steps": dict(Counter({r["metadata"]["family"]: r["metadata"]["steps"]
                                              for r in rows}.values())),
                "label_status": dict(Counter(r["metadata"]["label_status"] for r in rows))}
    write_json(args.output / "preparation.json", {
        "status": "PREPARED_REFERENCE_SUPERVISION_ONLY", "cohorts": summary,
        "length_excluded_question_ids": sorted(excluded_length),
        "length_rule": "Entire paired question removed, no backfill, no truncation",
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "model_forwards": 0, "heldout_candidate_file_loaded": False,
        "calibration_loaded": False, "source_semantic_labels_generated": False})
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
