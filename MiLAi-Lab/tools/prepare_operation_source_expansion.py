"""Freeze source expansion from inherited training roles and literal evaluation boundaries.

Only source-review views omit native answers/supports. Reference metadata is retained
offline; neither native targets nor boundary checks assign operation labels.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from audit_source_selection import overlap, panel
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from prepare_global_reader import select_questions


def inherited_rows(tables: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Intersect admitted rows, preserving native identity and every inherited role."""
    indices = [{row["row"]: row for row in rows} for rows in tables]
    common = set.intersection(*(set(index) for index in indices))
    result = []
    for native_row in sorted(common):
        original = indices[0][native_row]
        for index in indices:
            row = index[native_row]
            if any(row[key] != original[key] for key in ("question_id", "family", "split")):
                raise ValueError("Inherited source identity or split differs")
            if row["split"] != "train" or not row["included"]:
                raise ValueError("Source expansion requires admitted training metadata")
        result.append(original)
    return result


def source_records(path: Path, selected: set[int]) -> list[dict[str, Any]]:
    # Do not display protected bodies or pass them to a model/reviewer.
    with path.open(encoding="utf-8") as stream:
        records = [{"metadata": {"row": index}, "source": json.loads(line)}
                   for index, line in enumerate(stream) if index in selected]
    if {r["metadata"]["row"] for r in records} != selected:
        raise ValueError("A declared native source row is absent")
    return records


def boundary_issues(records: list[dict[str, Any]],
                    protected: dict[str, dict[str, set[Any]]]) -> list[dict[str, Any]]:
    own = panel(records, {})
    issues = []
    for name, reference in protected.items():
        shared = overlap(own, reference)
        counts = {key: len(value) if isinstance(value, list) else value
                  for key, value in shared.items()}
        if any(value for key, value in counts.items()
               if key != "shared_literal_background_or_target"):
            issues.append({"panel": name, "counts": counts})
    return issues


def training_clusters(records: list[dict[str, Any]], families: set[str]) -> list[list[str]]:
    """Report shared native target-title connections without relabelling original families."""
    parent = {family: family for family in families}

    def find(family: str) -> str:
        while parent[family] != family:
            parent[family] = parent[parent[family]]
            family = parent[family]
        return family

    owners: dict[str, str] = {}
    for record in records:
        family = record["metadata"]["family"]
        for title in panel([record], {})["target_titles"]:
            if title in owners:
                parent[find(family)] = find(owners[title])
            else:
                owners[title] = family
    components: dict[str, list[str]] = {}
    for family in sorted(families):
        components.setdefault(find(family), []).append(family)
    return sorted(components.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    protocol = read_json(args.protocol)
    metadata = inherited_rows([read_jsonl(Path(path)) for path in protocol["metadata_files"]])
    groups = [group for entries in select_questions(metadata, set(), protocol["seed"]).values()
              for group in entries]
    groups.sort(key=lambda group: group["family"])
    random.Random(protocol["seed"]).shuffle(groups)  # noqa: S311 -- predeclared source draw
    native = {record["metadata"]["row"]: record["source"] for record in source_records(
        Path(protocol["source_jsonl"]), {row["row"] for g in groups for row in g["rows"]})}
    protected = {entry["name"]: panel(source_records(Path(entry["source_jsonl"]),
        set(entry["rows"])), {}) for entry in protocol["protected_panels"]}
    for entry in protocol["normalized_panels"]:
        protected[entry["name"]] = panel([
            row for row in read_jsonl(Path(entry["records"]))
            if row["metadata"]["split"] in entry["splits"]], {})
    admitted: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    rejected, eligible = [], []
    for group in groups:
        records = [{"metadata": {**row, "source_row": row["row"],
                                "dataset": protocol["dataset"], "training_allowed": True},
                    "source": native[row["row"]]} for row in group["rows"]]
        if any(r["source"]["id"] != group["question_id"] for r in records):
            raise ValueError("Native source ID differs from inherited metadata")
        issues = boundary_issues(records, protected)
        entry = {"family": group["family"], "question_id": group["question_id"],
                 "native_max_steps": group["steps"], "source_rows": [
                     r["metadata"]["row"] for r in records]}
        if issues:
            rejected.append({**entry, "issues": issues})
        else:
            eligible.append(entry)
            if len(admitted) < protocol["new_family_target"]:
                admitted.append((entry, records))
    records = [r for _, rows in admitted for r in rows]
    existing = set(protocol["existing_operation_train_families"])
    selected = {r["metadata"]["family"] for r in records}
    if existing & selected:
        raise ValueError("New source cohort repeats an existing operation-training family")
    previous = [r for path in protocol["existing_normalized_records"]
                for r in read_jsonl(Path(path)) if r["metadata"]["family"] in existing]
    clusters = training_clusters([*previous, *records], existing | selected)
    args.output.mkdir(parents=True, exist_ok=False)
    views = [{"review_id": f"{protocol['dataset']}-row-{r['metadata']['row']}",
              "family": r["metadata"]["family"], "split": "train",
              "source_row": r["metadata"]["row"], "question": r["source"]["question"],
              "paragraphs": [{k: p[k] for k in ("idx", "title", "paragraph_text")}
                             for p in r["source"]["paragraphs"]]} for r in records]
    for name, rows in (("offline-references", records), ("source-review-inputs", views)):
        with (args.output / f"{name}.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "status": "LITERAL_BOUNDARY_ADMITTED_SOURCE_REVIEW_AND_COLLECTION_PENDING",
        "protocol": str(args.protocol), "metadata_rows": len(metadata),
        "candidate_families": len(groups), "eligible_families": len(eligible),
        "requested_new_families": protocol["new_family_target"],
        "selected_families": len(admitted), "selected_source_rows": len(records),
        "shortfall": max(0, protocol["new_family_target"] - len(admitted)),
        "selection": [entry for entry, _ in admitted], "eligible": eligible, "rejected": rejected,
        "selected_native_max_steps": dict(Counter(g["native_max_steps"] for g, _ in admitted)),
        "existing_operation_train_families": len(existing),
        "combined_registered_train_families": len(existing | selected),
        "combined_target_title_clusters": len(clusters),
        "existing_families_with_native_target_records": len({
            row["metadata"]["family"] for row in previous}),
        "cluster_scope": "Families without normalized native target records stay singleton; "
                         "this is not proof of cross-domain semantic independence.",
        "nontrivial_training_clusters": [group for group in clusters if len(group) > 1],
        "protected_panels": {name: {key: len(value) for key, value in p.items()}
                             for name, p in protected.items()},
        "protected_bodies_exported": False, "model_calls": 0, "new_operation_labels": 0,
        "scope": "Exact question, native target/pool and title boundary only. Known training "
                 "exposure is allowed and retained. No semantic/pretraining isolation claim; "
                 "source review, actual tool states and operation supervision remain pending.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}, "ledger_recorded": False,
    }
    write_json(args.output / "admission.json", report)
    print(json.dumps({k: report[k] for k in (
        "metadata_rows", "candidate_families", "eligible_families", "selected_families",
        "selected_source_rows", "shortfall", "combined_target_title_clusters", "compute")}))


if __name__ == "__main__":
    main()
