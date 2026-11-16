"""Group author-provided 2Wiki TRAIN by shared support entities and titles.

This stage emits metadata only. The archive's dev/test members and answer values
are not inspected, and no source text is sent to a model or displayed. Native
support counts are sampling strata, not certified semantic proof lengths.
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import write_json


def group_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parents = list(range(len(rows)))
    owners: dict[str, int] = {}

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, row in enumerate(rows):
        keys = {f"entity:{entity}" for entity in row["entity_ids"].split("_") if entity}
        keys.update(f"title:{title}" for title, _ in row["supporting_facts"])
        for key in sorted(keys):
            if key in owners:
                parents[root(index)] = root(owners[key])
            else:
                owners[key] = index
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        components[root(index)].append(index)
    families = []
    for number, indices in enumerate(sorted(components.values(),
                                            key=lambda ids: min(rows[i]["_id"] for i in ids))):
        families.append({"family": f"two-wiki-family-{number:06}", "rows": indices,
            "question_ids": [rows[i]["_id"] for i in indices],
            "max_support_titles": max(len({p[0] for p in rows[i]["supporting_facts"]})
                                      for i in indices),
            "types": dict(Counter(rows[i]["type"] for i in indices))})
    return families


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    with zipfile.ZipFile(args.archive) as archive:
        rows = json.load(archive.open("train.json"))
    families = group_sources(rows)
    write_json(args.output / "families.json", families)
    by_row = {i: group["family"] for group in families for i in group["rows"]}
    with (args.output / "metadata.jsonl").open("w") as stream:
        for i, row in enumerate(rows):
            stream.write(json.dumps({"row": i, "question_id": row["_id"],
                "family": by_row[i], "original_split": "train", "type": row["type"],
                "support_titles": len({p[0] for p in row["supporting_facts"]}),
                "reference_relations": len(row["evidences"]),
                "context_paragraphs": len(row["context"])}) + "\n")
    report = {"status": "TRAIN_METADATA_GROUPED_NOT_SEMANTICALLY_REVIEWED",
        "archive": str(args.archive.resolve()), "archive_members_read": ["train.json"],
        "rows": len(rows), "families": len(families),
        "family_max_support_titles": dict(Counter(g["max_support_titles"] for g in families)),
        "largest_family_rows": max(len(g["rows"]) for g in families),
        "group_rule": "Transitive closure of shared native support entity IDs "
                      "OR exact support titles",
        "limitations": "Native support labels, not semantic proofs. Cross-corpus literal "
                       "boundaries and registered historical exposure still require checking.",
        "source_text_or_answers_emitted": False, "model_calls": 0,
        "sha_checks": False, "content_fingerprints": False,
        "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu}
    write_json(args.output / "report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
