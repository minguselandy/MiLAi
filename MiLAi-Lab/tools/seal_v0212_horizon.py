"""Seal the metadata-only sampling process before opening discovery source/evaluation fields."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.prospective_admission import OrderContract


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(root: Path) -> dict:
    metadata = json.loads((root / "horizon-metadata.json").read_text())
    allocation = json.loads((root / "allocation.json").read_text())
    items = metadata["items"]
    parent = {row["user_id"]: row["user_id"] for row in items}

    def find(user: str) -> str:
        while parent[user] != user:
            user = parent[user]
        return user

    names: dict[str, str] = {}
    for row in items:
        assert "_event" in row["id"] and row["id"].split("_event")[0].strip()
        name = " ".join(
            unicodedata.normalize("NFKC", row["id"].split("_event")[0]).casefold().split()
        )
        if name in names:
            a, b = find(row["user_id"]), find(names[name])
            parent[max(a, b)] = min(a, b)
        else:
            names[name] = row["user_id"]
    clusters: dict[str, list[dict]] = defaultdict(list)
    for row in items:
        clusters[find(row["user_id"])].append(row)
    exposure = {}
    excluded = set()
    methods = LAB.parent / "MiLAi/var/dg11/paper/method-configs/preference.json"
    method_config = json.loads(methods.read_text())["datasets"]["HorizonBench"]
    for kind, config_key in [
        ("PROTECTED_PARTITION", "formal_inputs"),
        ("EXPOSED_TASK", "smoke_inputs"),
    ]:
        pin = method_config[config_key]
        path = LAB.parent / "MiLAi" / pin["path"]
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
        frozen_ids = {
            value.decode() for value in re.findall(rb'"([^"\n]*_counterfactuals\.json)"', raw)
        }
        matched_ids = {
            row["id"] for row in items if any(value.endswith(row["id"]) for value in frozen_ids)
        }
        assert len(matched_ids) == len(frozen_ids)
        affected = sorted({find(row["user_id"]) for row in items if row["id"] in matched_ids})
        excluded.update(affected)
        exposure[kind] = {
            "path": str(path),
            "sha256": pin["sha256"],
            "question_ids": sorted(matched_ids),
            "clusters": affected,
        }
    permitted = tuple(sorted(set(clusters) - excluded))
    contract = OrderContract(
        allocation["goal_id"],
        allocation["contract_version"],
        metadata["revision"],
        allocation["seed"],
    )
    discovery, confirmation = contract.partition(permitted)
    probes = {}
    for cluster in discovery:
        group = clusters[cluster]
        users = contract.order("probe", tuple(sorted({row["user_id"] for row in group})))
        user = users[0]
        selected = []
        for evolved in (True, False):
            subset = [
                row for row in group if row["user_id"] == user and row["has_evolved"] == evolved
            ]
            if subset:
                selected.append(
                    min(
                        subset,
                        key=lambda row: (
                            contract.digest("probe", row["generator"] + "/" + row["id"]),
                            row["id"],
                        ),
                    )
                )
        probes[cluster] = {
            "selected_user": user,
            "queries": selected,
            "metadata_eligible": len(selected) == 2,
        }
    profile_path = LAB / "configs/v0212-a0-profile.json"
    write(root / "a0-profile.json", json.loads(profile_path.read_text()))
    exposure["review"] = {
        "mode": "MODEL_ASSISTED_ADJUDICATION",
        "reviewer": "/root/v0212_admission_review",
        "scope": "Metadata IDs, official generation lineage code, historical local indices",
        "historical_files_scanned": 38761,
        "matching_files": 18,
        "matching_question_ids": 130,
        "new_ids_outside_two_frozen_partitions": 0,
        "limited_claim": ("No overlap found against this frozen local exposure index; "
                          "not universal novelty"),
        "labour": "Orchestrator model-assisted review, separate from benchmark/Judge; not free",
    }
    write(root / "exposure-manifest.json", exposure)
    member_manifest = {
        key: {
            "users": sorted({row["user_id"] for row in group}),
            "query_ids": [row["generator"] + "/" + row["id"] for row in group],
            "query_count": len(group),
            "prior_excluded": key in excluded,
        }
        for key, group in sorted(clusters.items())
    }
    write(root / "cluster-manifest.json", member_manifest)
    body = {
        "seal": "A",
        "contract": dataclasses.asdict(contract),
        "canonical_cluster_rule": ("Union complete user_id and all equal "
            "NFKC/casefold/whitespace-normalized item-ID names across and within generators; "
            "canonical ID is minimum user_id in connected component; no bare user_N joining"),
        "lineage_limit": ("Conservative visible metadata association, not proof of identity "
                          "or hidden independence"),
        "prepartition_exclusion": ("Propagate old protected/exposed IDs across their complete "
                                   "association clusters; retain all original pool counts"),
        "serialization": ("UTF8 JSON array ensure_ascii=false separators=(',',':'); SHA256; "
                          "ties canonical ID"),
        "pool_clusters": len(clusters),
        "pool_queries": len(items),
        "prior_excluded_clusters": sorted(excluded),
        "prior_excluded_queries": sum(len(clusters[c]) for c in excluded),
        "candidate_clusters": len(permitted),
        "discovery": list(discovery),
        "confirmation": list(confirmation),
        "discovery_queries": sum(len(clusters[c]) for c in discovery),
        "confirmation_queries": sum(len(clusters[c]) for c in confirmation),
        "probe_selection": ("First hash-ordered full user_id within cluster; first hash-ordered "
                            "evolved and static item for that user; "
                            "no replacement for missing pair"),
        "preselected_probes": probes,
        "accepted_target": 12,
        "screening_cap": 60,
        "minimum_batch_clusters": 2,
        "eligibility": [
            "NO_FROZEN_EXPOSURE_OVERLAP",
            "LICENSE_READY",
            "CLUSTER_RESOLVED",
            "PRESELECTED_EVOLVED_STATIC_PAIR",
            "EXACT_SOURCE_AVAILABLE_WITHIN_BOUNDS",
            "OFFICIAL_EVALUATOR_FIELDS_PRESENT_AND_VALID",
        ],
        "eligibility_forbidden": [
            "gold_value",
            "difficulty",
            "expected_model_success",
            "model_output",
        ],
        "rejection_codes": [
            "PROTECTED_PARTITION",
            "EXPOSED_TASK",
            "NEAR_DUPLICATE_SOURCE",
            "EXPOSURE_UNRESOLVED",
            "CLUSTER_UNRESOLVED",
            "LICENSE_UNRESOLVED",
            "SOURCE_UNAVAILABLE",
            "CORRUPT_DATA",
            "MODALITY_UNSUPPORTED",
            "RESOURCE_INFEASIBLE",
            "REQUIRED_PROBE_MISSING",
        ],
        "unknown_policy": "UNRESOLVED_AND_CONTINUE_FIXED_ORDER",
        "stopping": ("12 accepted OR 60 screened OR frozen preparation/review cap "
                     "OR pool exhaustion; "
                     "no accepted replacement"),
        "lane": "A_HORIZON_DISCOVERY",
        "lane_reason": ("STALE pinned tree/releases provide generation framework but no fixed "
                        "published scenario package; Horizon fixed data and deterministic "
                        "evaluator "
                        "available; FactConsolidation remains unallocated fallback"),
        "licenses": {"Horizon_code": "Apache-2.0", "Horizon_data": "CC-BY-4.0"},
        "pins": {
            name: sha(root / name)
            for name in [
                "allocation.json",
                "horizon-metadata.json",
                "horizon-download.json",
                "horizon-readme.txt",
                "horizon-license.txt",
                "horizon-evaluate.py",
                "horizon-build.py",
                "exposure-manifest.json",
                "cluster-manifest.json",
                "a0-profile.json",
            ]
        },
        "admission_code_sha256": sha(LAB / "src/milai_lab/methods/prospective_admission.py"),
        "score_code_sha256": sha(LAB / "src/milai_lab/methods/horizon_diagnostic.py"),
        "before_discovery_body_review": True,
        "benchmark_generations": 0,
        "confirmation_body_review": False,
    }
    wire = (
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with (root / "seal-a.json").open("xb") as output:
        output.write(wire)
    write(root / "seal-a-sha256.json", {"sha256": hashlib.sha256(wire).hexdigest()})
    return {
        key: body[key]
        for key in (
            "pool_clusters",
            "pool_queries",
            "candidate_clusters",
            "discovery_queries",
            "confirmation_queries",
        )
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seal(args.root.resolve())))
