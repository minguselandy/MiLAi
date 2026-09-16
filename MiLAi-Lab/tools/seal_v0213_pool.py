"""Freeze a cluster-disjoint discovery prefix using lineage metadata only."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from replay_v0213_cost import read, save, sha, wire


def freeze(root: Path, excluded_ids: set[str], exposure_receipt: Path) -> dict:
    protocol = read(root / "pre-open-protocol.json")
    queries = json.loads((root / "qa_dataset-metadata.json").read_text())
    sessions = json.loads((root / "toolmem_conversation-metadata.json").read_text())
    parents = {row["session_id"]: row["session_id"] for row in sessions}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(a, b):
        a, b = find(a), find(b)
        parents[max(a, b)] = min(a, b)

    owner = defaultdict(list)
    for session in sessions:
        for source in session["original_conversation_ids"]:
            owner[source].append(session["session_id"])
    for group in owner.values():
        for session in group[1:]:
            union(group[0], session)
    invalid, mappings, uncertain_sessions = [], {}, set()
    for query in queries:
        lineage = sorted(set(query["source_conversation_ids"] + query["evolution_source_ids"]))
        mapped = sorted({sid for source in lineage for sid in owner[source]})
        missing = [source for source in lineage if not owner[source]]
        if missing or not mapped:
            uncertain_sessions.update(mapped)
            invalid.append({"qa_id": query["qa_id"], "reason": "UNRESOLVED_LINEAGE",
                            "missing_source_ids": missing})
        else:
            mappings[query["qa_id"]] = mapped
        # Propagate all known shared lineage even when one part is unresolved.
        for session in mapped[1:]:
            union(mapped[0], session)
    groups = defaultdict(lambda: {"session_ids": [], "source_ids": [], "qa_ids": []})
    for session in sessions:
        group = groups[find(session["session_id"])]
        group["session_ids"].append(session["session_id"])
        group["source_ids"].extend(session["original_conversation_ids"])
    for query_id, mapped in mappings.items():
        groups[find(mapped[0])]["qa_ids"].append(query_id)

    def ordered_hash(identifier):
        return sha(wire({"goal": protocol["goal"], "seed": protocol["seed"], "id": identifier}))

    excluded, universe = [], []
    uncertain_roots = {find(sid) for sid in uncertain_sessions}
    for group_root, group in groups.items():
        if not group["qa_ids"]:
            continue
        group["source_ids"] = sorted(set(group["source_ids"]))
        group["session_ids"].sort()
        group["qa_ids"].sort()
        cluster_id = sha(wire(group["source_ids"]))
        record = {"cluster_id": cluster_id, **group,
                  "representative_qa": min(group["qa_ids"], key=ordered_hash)}
        if set(group["source_ids"]) & excluded_ids:
            excluded.append({**record, "reason": "PRIOR_EXPOSURE_OR_PROTECTION"})
        elif group_root in uncertain_roots:
            excluded.append({**record, "reason": "ASSOCIATED_UNRESOLVED_LINEAGE"})
        else:
            universe.append(record)
    universe.sort(key=lambda row: ordered_hash(row["cluster_id"]))
    cutoff = len(universe) - math.ceil(len(universe) / 3)
    result = {"status": "SEAL_A_FROZEN", "protocol_sha256": sha(wire(protocol)),
              "exposure_review_sha256": sha(exposure_receipt.read_bytes()),
              "release_manifest_sha256": sha((root / "release-manifest.json").read_bytes()),
              "queries_total": len(queries), "sessions_total": len(sessions),
              "invalid_mapping": invalid, "excluded_clusters": excluded,
              "discovery": universe[:cutoff], "confirmation": universe[cutoff:],
              "history_mapping": mappings, "screen_limit": protocol["screening_limit"],
              "accept_limit": protocol["accepted_limit"], "first_wave": 2,
              "raw_bodies_opened": False}
    path = root / "seal-a.json"
    if path.exists():
        assert read(path) == result, "Existing Seal A is immutable"
    else:
        save(path, result)
        save(root / "seal-a-sha256.json", {"sha256": sha(path.read_bytes())})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--exposure-review", type=Path, required=True)
    args = parser.parse_args()
    review = read(args.exposure_review)
    result = freeze(args.root, set(review["excluded_source_ids"]), args.exposure_review)
    print(json.dumps({"status": result["status"], "discovery": len(result["discovery"]),
                      "confirmation": len(result["confirmation"]),
                      "invalid_mapping": len(result["invalid_mapping"]),
                      "excluded_clusters": len(result["excluded_clusters"])}))
