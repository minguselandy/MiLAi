"""Compare frozen source judgments to native references and their actual source boundary.

This runs only after the source-first annotation snapshot. Native answers are
reported separately and never used to rewrite those judgments. Exact title/text
comparisons are local; no digest or model is involved.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def target_indices(review: dict[str, Any]) -> set[int]:
    paths = review["complete_proofs"] + review.get("qualified_alternative_proofs", [])
    return set(review["useful_partial_evidence"]) | {i for path in paths for i in path}


def panel(records: list[dict[str, Any]], reviews: dict[int, dict[str, Any]]
          ) -> dict[str, set[Any]]:
    result: dict[str, set[Any]] = {key: set() for key in (
        "pool", "target", "pool_titles", "target_titles", "questions")}
    for record in records:
        source, meta = record["source"], record["metadata"]
        reviewed = target_indices(reviews[meta["row"]]) if meta["row"] in reviews else set()
        for p in source["paragraphs"]:
            key = (p["title"], p["paragraph_text"])
            result["pool"].add(key)
            result["pool_titles"].add(p["title"])
            if p["is_supporting"] or p["idx"] in reviewed:
                result["target"].add(key)
                result["target_titles"].add(p["title"])
        result["questions"].add(source["question"])
    return result


def overlap(left: dict[str, set[Any]], right: dict[str, set[Any]]) -> dict[str, Any]:
    return {
        "left_target_in_right_pool": sorted(p[0] for p in left["target"] & right["pool"]),
        "right_target_in_left_pool": sorted(p[0] for p in right["target"] & left["pool"]),
        "left_target_title_in_right_pool": sorted(left["target_titles"] & right["pool_titles"]),
        "right_target_title_in_left_pool": sorted(right["target_titles"] & left["pool_titles"]),
        "same_questions": len(left["questions"] & right["questions"]),
        "shared_literal_background_or_target": len(left["pool"] & right["pool"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("reviews", type=Path)
    parser.add_argument("reservation", type=Path)
    parser.add_argument("reserved_source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    records = [json.loads(line) for line in args.sources.read_text().splitlines()]
    reviews = {r["source_row"]: r for r in read_json(args.reviews)["cases"]}
    assert set(reviews) == {r["metadata"]["row"] for r in records}
    comparisons, summary = [], {}
    for split in ("train", "dev"):
        rows = [r for r in records if r["metadata"]["split"] == split]
        counts: Counter[str] = Counter()
        for record in rows:
            source, meta = record["source"], record["metadata"]
            review = reviews[meta["row"]]
            assert review["family"] == meta["family"] and review["split"] == split
            counts[f"native_{source['answerable']}__source_{review['disposition']}"] += 1
            comparisons.append({"row": meta["row"], "dataset": meta["dataset"],
                "native_source_row": meta["native_source_row"], "split": split,
                "family": meta["family"], "review_id": review["review_id"],
                "original_answerable": source["answerable"], "original_answer": source["answer"],
                "original_support_indices": [p["idx"] for p in source["paragraphs"]
                                             if p["is_supporting"]],
                "source_disposition": review["disposition"],
                "source_answer": review["expected_answer"],
                "source_proofs": review["complete_proofs"],
                "source_qualified": review.get("qualified", False)})
        summary[split] = dict(counts)
    write_json(args.output / "reference-comparison.json", comparisons)
    splits = {split: [r for r in records if r["metadata"]["split"] == split]
              for split in ("train", "dev")}
    panels = {split: panel(rows, reviews) for split, rows in splits.items()}
    reservation = read_json(args.reservation)
    reserved_ids = {i for g in reservation["selected"]
                    for i in g["protected_source_rows"]}
    selected_ids = {i for g in reservation["selected"] for i in g["source_rows"]}
    reserved = [{"metadata": {"row": index}, "source": json.loads(line)}
                for index, line in enumerate(args.reserved_source.open()) if index in reserved_ids]
    assert len(reserved) == len(reserved_ids)
    panels["reserved"] = panel(reserved, {})
    panels["reserved_selected"] = panel(
        [r for r in reserved if r["metadata"]["row"] in selected_ids], {})
    boundaries = {f"{left}__{right}": overlap(panels[left], panels[right])
                  for left, right in (("train", "dev"), ("train", "reserved"),
                                      ("dev", "reserved"), ("train", "reserved_selected"),
                                      ("dev", "reserved_selected"))}
    conflicts = []
    for split, others in (("train", ("dev", "reserved")), ("dev", ("reserved",))):
        for record in splits[split]:
            own = panel([record], reviews)
            for other in others:
                details = overlap(own, panels[other])
                if any(value for key, value in details.items()
                       if key != "shared_literal_background_or_target"):
                    conflicts.append({"row": record["metadata"]["row"], "split": split,
                        "family": record["metadata"]["family"], "against": other,
                        "details": details})
    write_json(args.output / "boundary-conflicts.json", conflicts)
    write_json(args.output / "report.json", {
        "status": "REFERENCE_COMPARISON_AND_REVIEWED_TARGET_BOUNDARY_CLOSED",
        "source_annotation_snapshot": str(args.reviews), "sources": str(args.sources),
        "reserved_family_rows": len(reserved_ids), "reserved_selected_rows": len(selected_ids),
        "native_source_cross_table": summary, "boundaries": boundaries,
        "conflicting_rows": len({r["row"] for r in conflicts}),
        "conflicting_families": sorted({r["family"] for r in conflicts}),
        "source_annotations_changed": False, "model_calls": 0,
        "sha_checks": False, "content_fingerprints": False,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
        "scope": "All native supports plus reviewed complete/qualified/partial evidence. "
                 "Reserved panel uses native targets only and remains unexposed to reviewer; "
                 "its later semantic proofs still require checking. No source judgment is "
                 "automatically corrected to a native answer; cross-table is not "
                 "a noise-rate proof."})
    counts_only = {name: {key: len(value) if isinstance(value, list) else value
                          for key, value in details.items()}
                   for name, details in boundaries.items()}
    print(json.dumps({"cross_table": summary, "boundaries": counts_only,
                      "conflicting_families": sorted({r["family"] for r in conflicts})}))


if __name__ == "__main__":
    main()
