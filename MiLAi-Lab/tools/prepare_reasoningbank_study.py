"""Freeze source-grouped research splits without exposing evaluator answers.

Run in the benchmark data environment (pyarrow is an optional preparation dependency).
The output directory must be new. Native evaluator inputs stay outside the Lab tree.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def instruction_template(text: str, identifiers: Sequence[str] = ()) -> str:
    for identifier in sorted(identifiers, key=len, reverse=True):
        text = re.sub(
            rf"(?<!\w){re.escape(identifier)}(?!\w)",
            "<identifier>",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"(['\"])(?:(?!\1).)*?\1", "<literal>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<number>", text)
    return " ".join(text.lower().split())


def components(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Join every known shared source, schema, or normalized instruction relation."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        for relation in row["relations"]:
            if relation in seen:
                parent[find(index)] = find(seen[relation])
            seen[relation] = index
    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(find(index), []).append(row)
    for group in grouped.values():
        cluster = digest(sorted(r["id"] for r in group))
        for row in group:
            row["cluster"] = cluster
    return list(grouped.values())


def select_groups(
    groups: list[list[dict[str, Any]]], target: int, *, count_clusters: bool = False
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    selected: list[dict[str, Any]] = []
    amount = 0
    taken = 0
    for group in groups:
        if amount >= target:
            break
        selected.extend(group)
        amount += 1 if count_clusters else len(group)
        taken += 1
    if amount < target:
        raise ValueError(f"Insufficient independent sources: {amount} < {target}")
    return sorted(selected, key=lambda r: r["position"]), groups[taken:]


def prepare(dataset_root: Path, output_root: Path, seed: int) -> dict[str, Any]:
    import pyarrow.parquet as pq

    if output_root.exists():
        raise FileExistsError("Choose a new output directory; existing splits are immutable")
    metadata: dict[str, list[dict[str, Any]]] = {}
    native: dict[str, Any] = {}
    inputs: dict[str, str] = {}
    for domain in ("db_bench", "os_interaction"):
        path = dataset_root / "lifelong" / domain / "train-00000-of-00001.parquet"
        inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        table = pq.read_table(path)
        rows = []
        native[domain] = {}
        for position, raw in enumerate(table.to_pylist()):
            sample_id = str(raw.pop("sample_index"))
            # Upstream stores Python literal dictionaries/lists as strings in Parquet.
            # These fields are decoded for the native evaluator, never emitted as metadata.
            parsed = {
                key: ast.literal_eval(value)
                if key
                in {
                    "table_info",
                    "skill_list",
                    "answer_info",
                    "initialization_command_item",
                    "evaluation_info",
                }
                else value
                for key, value in raw.items()
            }
            native[domain][sample_id] = parsed
            relations = []
            identifiers = []
            if domain == "db_bench":
                info = parsed["table_info"]
                identifiers = [info["name"], *[c["name"] for c in info["column_info_list"]]]
                relations.append("schema:" + digest(info["column_info_list"]))
                source_key = "sql_instruction_row_list_entry_hash"
            else:
                source_key = "raw_entry_hash"
                relations.append("initialization:" + digest(parsed["initialization_command_item"]))
            relations.append("source:" + str(parsed[source_key]))
            relations.append(
                "instruction:" + digest(instruction_template(parsed["instruction"], identifiers))
            )
            rows.append(
                {
                    "id": sample_id,
                    "position": position,
                    "relations": relations,
                    "skills": parsed["skill_list"],
                    "sessions": 1,
                }
            )
        metadata[domain] = rows

    travel_path = dataset_root / "memoryarena/group_travel_planner/data.jsonl"
    inputs[str(travel_path)] = hashlib.sha256(travel_path.read_bytes()).hexdigest()
    native["travel"] = [json.loads(line) for line in travel_path.read_text().splitlines()]
    metadata["travel"] = [
        {
            "id": str(row["id"]),
            "position": position,
            "relations": [
                "base_query:" + digest(instruction_template(row["base_person"]["query"]))
            ],
            "skills": [],
            "sessions": len(row["questions"]),
        }
        for position, row in enumerate(native["travel"])
    ]
    targets = {
        "db_bench": {"DEV": 24, "VALID": 12, "SUPPORT": 40, "TEST": 100},
        "os_interaction": {"DEV": 8, "VALID": 0, "SUPPORT": 40, "TEST": 100},
        "travel": {"DEV": 8, "VALID": 8, "SUPPORT": 20, "TEST": 50},
    }
    manifest: dict[str, Any] = {
        "schema": "milai-reasoningbank-splits-v1",
        "seed": seed,
        "prepared_before_development_generations": True,
        "input_sha256": inputs,
        "preparation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "grouping": {
            "db_bench": (
                "Connected components of upstream source hash, named column schema, "
                "normalized instruction"
            ),
            "os_interaction": (
                "Connected components of raw_entry_hash, exact initialization "
                "and normalized instruction"
            ),
            "travel": "Whole groups joined when normalized given base-person query matches",
            "normalization": "Identifiers (DB only), quoted literals, numbers, case and whitespace",
            "limitations": (
                "No full upstream generation lineage; unobserved semantic near-duplicates "
                "may remain. Skills alone do not define clusters."
            ),
            "answer_fields_used_for_grouping": False,
        },
        "domains": {},
        "second_solver": "DEFERRED_BY_USER",
    }
    for domain, rows in metadata.items():
        if len({r["id"] for r in rows}) != len(rows):
            raise ValueError(f"Duplicate native identity in {domain}")
        groups = components(rows)
        groups.sort(key=lambda group: digest([seed, domain, group[0]["cluster"]]))
        counts = Counter(len(group) for group in groups)
        partitions: dict[str, list[dict[str, Any]]] = {}
        available = groups
        for split, target in targets[domain].items():
            partitions[split], available = select_groups(
                available, target, count_clusters=split == "VALID"
            )
        partitions["RESERVE"] = sorted(
            [row for group in available for row in group], key=lambda r: r["position"]
        )
        cluster_splits: dict[str, str] = {}
        for split, selected in partitions.items():
            for row in selected:
                previous = cluster_splits.setdefault(row["cluster"], split)
                if previous != split:
                    raise ValueError("Source cluster crossed a split")
        test_groups = components(partitions["TEST"])
        test_groups.sort(key=lambda group: digest([seed, domain, "analysis", group[0]["cluster"]]))
        reference, _ = select_groups(test_groups, 20 if domain != "travel" else 0)
        ablation, _ = select_groups(test_groups, 10 if domain != "travel" else 5)
        resource, _ = select_groups(test_groups, 8 if domain != "travel" else 4)
        streams: list[list[dict[str, Any]]] = [[] for _ in range(5)]
        if domain != "travel":
            # Keep source families together; original dataset order is retained within a stream.
            for group in sorted(test_groups, key=lambda g: min(r["position"] for r in g)):
                min(streams, key=len).extend(group)
            for stream in streams:
                stream.sort(key=lambda row: row["position"])
        manifest["domains"][domain] = {
            "total": len(rows),
            "clusters": len(groups),
            "cluster_size_histogram": dict(counts),
            "target_counts": targets[domain],
            "partitions": partitions,
            "counts": {split: len(items) for split, items in partitions.items()},
            "cluster_counts": {
                split: len({r["cluster"] for r in items}) for split, items in partitions.items()
            },
            "sessions": {
                split: sum(r["sessions"] for r in items) for split, items in partitions.items()
            },
            "online_streams": [[r["id"] for r in stream] for stream in streams]
            if domain != "travel"
            else [],
            "verified_replay_subset": [r["id"] for r in reference],
            "contribution_subset": [r["id"] for r in ablation],
            "resource_subset": [r["id"] for r in resource],
            "exposure": (
                "DEV is designated for development; TEST task text and answers "
                "not printed or used for policy design"
            ),
        }
    output_root.mkdir(parents=True)
    for domain, data in native.items():
        path = output_root / "native" / f"{domain}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    (output_root / "splits.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=213)
    args = parser.parse_args()
    manifest = prepare(args.dataset_root, args.output_root, args.seed)
    print(
        json.dumps(
            {
                domain: {
                    key: values[key]
                    for key in ["total", "clusters", "counts", "cluster_counts", "sessions"]
                }
                for domain, values in manifest["domains"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
