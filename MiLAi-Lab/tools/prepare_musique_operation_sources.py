"""Expand actual MuSiQue TRAIN contexts using inherited roles and source boundaries.

Native answerability/supports stay in offline controls. One bank per inherited
family shares immutable paragraphs; each request retains its original visible context.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from audit_source_selection import panel
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from prepare_operation_source_expansion import (
    boundary_issues,
    inherited_rows,
    source_records,
    training_clusters,
)


def export_family(
    family: str, records: list[dict[str, Any]], *, split: str = "train"
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Literal paragraph reuse does not turn native variants into independent sources."""
    keys: dict[tuple[str, str], str] = {}
    sources, requests, controls = [], [], []
    for record in records:
        source, metadata = record["source"], record["metadata"]
        visible, support = [], []
        for paragraph in source["paragraphs"]:
            key = paragraph["title"], paragraph["paragraph_text"]
            if key not in keys:
                ordinal = len(keys)
                identifier = f"{family}/paragraph-{ordinal}"
                keys[key] = identifier
                sources.append(
                    {
                        "session_id": "reference-context",
                        "event_key": f"paragraph-{ordinal}",
                        "original_event_id": identifier,
                        "role": "tool",
                        "origin": "reference_document",
                        "occurred_at": None,
                        "content": paragraph["title"] + "\n" + paragraph["paragraph_text"],
                    }
                )
            visible.append(keys[key])
            if paragraph["is_supporting"]:
                support.append(keys[key])
        request_id = f"native-row-{metadata['row']}"
        requests.append(
            {
                "id": request_id,
                "content": "Use the available sources to answer the "
                "question with source evidence. If the material cannot establish an answer, "
                "explain the limitation.\n\n" + source["question"],
                "retrieval_request": {
                    "query": source["question"],
                    "read_goal": {
                        "purpose": "Answer the supplied question using original sources",
                        "evidence": ["original_source"],
                    },
                },
                "source_event_ids": list(dict.fromkeys(visible)),
                "native_source_row": metadata["row"],
            }
        )
        support = list(dict.fromkeys(support))
        controls.append(
            {
                "schema": "source_reference_witness_v1",
                "source_group": family,
                "split": split,
                "request_id": request_id,
                "native_source_row": metadata["row"],
                "native_question_id": source["id"],
                "native_answerable": source["answerable"],
                "native_answer": source["answer"],
                "native_answer_aliases": source.get("answer_aliases"),
                "reference_proofs": [[[identifier] for identifier in support]]
                if source["answerable"] and support
                else [],
                "partial_native_support_sources": support,
                "scope": "Native answerable support conjunction is an offline witness, "
                "not an exhaustive semantic proof. Missing support never implies HANDOFF.",
            }
        )
    return {
        "id": family,
        "source_group": family,
        "split": split,
        "continuous": False,
        "source_version": "musique-full-v1.0-native-context",
        "dataset": "musique",
        "sources": sources,
        "requests": requests,
    }, controls


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inherited_protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    protocol = read_json(args.inherited_protocol)
    tables = [read_jsonl(Path(path)) for path in protocol["metadata_files"]]
    new = inherited_rows(tables)
    existing = set(protocol["existing_operation_train_families"])
    # Retained rows of an already TRAIN family are also legitimate; excluded rows stay excluded.
    prior = [
        row
        for row in tables[-1]
        if row["family"] in existing and row["split"] == "train" and row["included"]
    ]
    metadata = {row["row"]: row for row in [*new, *prior]}
    protected = {
        entry["name"]: panel(source_records(Path(entry["source_jsonl"]), set(entry["rows"])), {})
        for entry in protocol["protected_panels"]
    }
    protected_families: set[str] = set()
    for entry in protocol["normalized_panels"]:
        records = [
            row
            for row in read_jsonl(Path(entry["records"]))
            if row["metadata"]["split"] in entry["splits"]
        ]
        protected[entry["name"]] = panel(records, {})
        protected_families.update(row["metadata"]["family"] for row in records)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in source_records(Path(protocol["source_jsonl"]), set(metadata)):
        meta = metadata[record["metadata"]["row"]]
        if record["source"]["id"] != meta["question_id"]:
            raise ValueError("Native question identity differs from retained research metadata")
        record["metadata"] = dict(meta)
        groups[meta["family"], meta["question_id"]].append(record)
    admitted, rejected = [], []
    for (family, question), records in sorted(groups.items()):
        issues = boundary_issues(records, protected)
        if family in protected_families or issues:
            rejected.append(
                {
                    "family": family,
                    "question_id": question,
                    "rows": [r["metadata"]["row"] for r in records],
                    "protected_family": family in protected_families,
                    "issues": issues,
                }
            )
        else:
            admitted.extend(records)
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in admitted:
        families[record["metadata"]["family"]].append(record)
    clusters = training_clusters(admitted, set(families))
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(
        args.output / "population.json",
        {
            "inherited_protocol": str(args.inherited_protocol.resolve()),
            "families": {
                family: [r["metadata"]["row"] for r in records]
                for family, records in families.items()
            },
            "target_title_clusters": clusters,
            "rejected_question_groups": rejected,
            "no_sha_validation": True,
            "protected_bodies_exported": False,
        },
    )
    histories, controls = [], []
    for family, records in families.items():
        history, review = export_family(family, sorted(records, key=lambda r: r["metadata"]["row"]))
        histories.append(history)
        controls.extend(review)
    write_json(args.output / "histories.json", {"histories": histories})
    with (args.output / "controls.jsonl").open("w") as stream:
        for row in controls:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(
        args.output / "manifest.json",
        {
            "status": "LEGAL_NATIVE_CONTEXT_POPULATION_EXPORTED_NOT_OPERATION_STATES",
            "candidate_rows": len(metadata),
            "candidate_question_groups": len(groups),
            "eligible_native_variants": len(admitted),
            "eligible_questions": len(groups) - len(rejected),
            "eligible_families": len(families),
            "target_title_clusters": len(clusters),
            "shared_family_clusters": [c for c in clusters if len(c) > 1],
            "source_units": sum(len(h["sources"]) for h in histories),
            "answerability": dict(Counter(str(r["source"]["answerable"]) for r in admitted)),
            "native_step_rows": dict(
                Counter(str(len(r["source"]["question_decomposition"])) for r in admitted)
            ),
            "new_operation_states": 0,
            "no_sha_validation": True,
            "source_jsonl": protocol["source_jsonl"],
            "scope": "Inherited TRAIN and question/target-to-pool/title boundaries preserved. "
            "Each native variant has its own visible context; family banks cannot repair missing "
            "support by exposing another variant. Variants/questions are not independent families. "
            "This adds a source domain to QASPER, not a pure-size-only intervention.",
            "compute": {
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.perf_counter() - started,
            },
        },
    )


if __name__ == "__main__":
    main()
