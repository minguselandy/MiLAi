"""Reconcile existing metadata-only source components; never open task content."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--lab", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifests = args.lab / "data/manifests"
    paths = {
        name: manifests / name
        for name in [
            "v13-1-memsyco-source-availability.json",
            "v13-1-source-exposure.json",
            "v13-1-pilot-prospective-selection.json",
            "v13-1-source-exposure-pilot-reservation.json",
        ]
    }
    before = {str(path): sha(path) for path in [*paths.values(), args.catalog]}
    availability = read(paths["v13-1-memsyco-source-availability.json"])
    reservation = read(paths["v13-1-source-exposure-pilot-reservation.json"])
    pilot = read(paths["v13-1-pilot-prospective-selection.json"])
    exposure = read(paths["v13-1-source-exposure.json"])
    if sha(args.catalog) != availability["metadata_catalog_sha256"]:
        raise ValueError("Metadata catalog changed")
    if sha(paths["v13-1-source-exposure.json"]) != availability["source_exposure_sha256"]:
        raise ValueError("Parent exposure identity changed")
    if (
        sha(paths["v13-1-pilot-prospective-selection.json"])
        != (reservation["reservation_selection_sha256"])
    ):
        raise ValueError("Reservation identity changed")
    catalog = read(args.catalog)
    allowed = {"case_id", "task", "native_source_id", "dialogue_sha256", "raw_line_sha256"}
    for component in catalog:
        if set(component) != {"source_group_id", "excluded", "members"}:
            raise ValueError("Unexpected catalog fields: do not access task content")
        if any(set(row) != allowed for row in component["members"]):
            raise ValueError("Unexpected row fields: do not access task content")
    reserved = set(reservation["source_group_ids"])
    graph = []
    counts = {}
    for component in catalog:
        state = (
            "OLD_EXCLUDED"
            if component["excluded"]
            else "PILOT_RESERVED"
            if component["source_group_id"] in reserved
            else "UNRESERVED_METADATA_ONLY"
        )
        graph.append(
            {
                "source_group_id": component["source_group_id"],
                "state": state,
                "members": component["members"],
            }
        )
    for task in availability["counts"]:
        eligible = [
            c
            for c in graph
            if c["state"] == "UNRESERVED_METADATA_ONLY"
            and any(row["task"] == task for row in c["members"])
        ]
        counts[task] = {
            "unreserved_rows": sum(row["task"] == task for c in eligible for row in c["members"]),
            "independent_components": len(eligible),
            "old_nominal_formal100_proven": False,
            "formal_selected": False,
        }
        expected = pilot["memsyco"]["counts"][task]
        if (
            counts[task]["unreserved_rows"] != expected["remaining_unreserved_questions"]
            or len(eligible) != expected["remaining_unreserved_components"]
        ):
            raise ValueError("Source-capacity count changed")
    report = {
        "kind": "V13_2_SOURCE_GROUP_CAPACITY_AMENDMENT",
        "amendment_id": "v13.2-source-capacity-001",
        "status": "REGISTERED_BEFORE_NEW_PILOT_CONTENT_ACCESS_NO_RECLAIM",
        "authorization": "User explicitly requested full v13.2 plan execution",
        "original_registries_preserved": before,
        "source_commit": availability["source_commit"],
        "component_rule": availability["component_rule"],
        "graph": graph,
        "counts": counts,
        "reserved_rows_kept_excluded": len(reservation["case_ids"]),
        "merit_reserved_seeds_kept_excluded": reservation["merit_base_seeds"],
        "merit_old_seeds_kept_excluded": exposure["explicit_union"]["merit_base_seeds"],
        "old_to_new_status": {
            "EXPOSED_OR_OLD_RESERVED": "EXCLUDED_UNCHANGED",
            "V13_1_PILOT_RESERVED": "EXCLUDED_UNCHANGED_NO_ACCESS_PROOF_FOR_RECLAIM",
            "UNRESERVED_METADATA_ONLY": "UNSELECTED_NO_NEW_CONTENT_ACCESS",
        },
        "statistical_scope": (
            "Valid has only two unreserved components; seven questions cannot prove "
            "independent update efficacy or five-percentage-point noninferiority."
        ),
        "formal_size": "UNFROZEN: use pilot paired variance and prespecified precision",
        "new_content_access": False,
        "new_model_calls": 0,
        "independent_review": "UNAVAILABLE: prospective rubric/package is not scored evidence",
        "second_family": "UNAVAILABLE: existing two endpoints are one family",
        "full_goal": "ACTIVE",
        "product": "NO_GO",
        "script_sha256": sha(Path(__file__)),
    }
    if before != {name: sha(Path(name)) for name in before}:
        raise ValueError("Metadata or original registry changed during read-only audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "components": len(graph),
                "counts": counts,
                "reserved_rows_kept_excluded": report["reserved_rows_kept_excluded"],
            }
        )
    )


if __name__ == "__main__":
    main()
