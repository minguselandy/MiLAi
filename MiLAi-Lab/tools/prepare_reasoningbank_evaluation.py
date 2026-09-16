"""Materialize the frozen single-model support, main and contribution matrices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from replay_v0213_cost import save, sha

METHODS = {
    "native": "NATIVE_AGENT_OR_HISTORY", "om": "OM_SYNC_PORT",
    "rb": "REASONINGBANK_BASE_PORT", "milai": "MILAI_EXPERIENCE_REVISION",
}


def prepare(decision_file: Path, phase: str) -> Path:
    decision = json.loads(decision_file.read_text())
    if decision["status"] != "POLICY_AND_RESOURCES_FROZEN_BEFORE_TEST":
        raise ValueError("VERSION_SELECTION_NOT_COMPLETE")
    root = Path(decision["evidence_root"]) / phase
    root.mkdir(parents=True, exist_ok=False)
    split = json.loads(Path(decision["template"]["split_manifest"]).read_text())
    jobs = []
    support = {}
    if phase != "support":
        state = json.loads((root.parent / "support/batch-status.json").read_text())
        if state["pending"] or state["running"]:
            raise ValueError("SUPPORT_FORMATION_NOT_TERMINAL")
        for job in state["completed"].values():
            if "config" not in job:
                continue
            config = json.loads(Path(job["config"]).read_text())
            support[(config["domain"], config["method"])] = job.get("bank")

    def add(domain, alias, ids, protocol, *, label="main", parent=None, resource="main"):
        method = METHODS.get(alias, alias)
        identifier = f"{label}-{domain}-{alias}-{protocol}-{len(jobs):03d}"
        limits = decision["resources"][resource][domain]
        config = {
            **decision["template"], "domain": domain,
            "split": "SUPPORT" if phase == "support" else "TEST",
            "method": method, "protocol": protocol, "stream": identifier,
            "ids": ids, "output_root": str(root / identifier),
            "unit_limits": limits, "max_tokens": limits["max_tokens"] * len(ids),
            "max_requests": limits["max_requests"] * len(ids),
            "wall_seconds": limits["wall_seconds"] * len(ids) + 180,
            "analysis_condition": label, "resource_point": resource,
            "decision_sha256": sha(decision_file.read_bytes()),
            "request_timeout_seconds": (
                decision["transport_selection"]["request_timeout_seconds"][domain]
            ),
        }
        if phase != "support" and protocol in {"F", "G"} and alias != "native":
            bank = support.get((domain, method))
            if not bank:
                raise ValueError(f"NO_FORMED_SUPPORT_BANK: {domain}/{method}")
            config["bank_input"] = bank
        if label == "append-only":
            config["revision_application"] = "append_only"
        if label == "verified-history":
            config["verified_history_count"] = 3
        path = root / (identifier + "-config.json")
        save(path, config)
        job = {"id": identifier, "config": str(path)}
        if parent:
            job["parent"] = parent
        jobs.append(job)
        return identifier

    for domain, partition in split["domains"].items():
        if phase == "support":
            ids = [row["id"] for row in partition["partitions"]["SUPPORT"]]
            for alias in ("om", "rb", "milai"):
                if domain == "travel":
                    parent = None
                    for identifier in ids:
                        parent = add(
                            domain, alias, [identifier], "G", label="support", parent=parent
                        )
                else:
                    add(domain, alias, ids, "O", label="support")
        elif phase == "main":
            ids = [row["id"] for row in partition["partitions"]["TEST"]]
            for alias in METHODS:
                if domain == "travel":
                    for identifier in ids:
                        add(domain, alias, [identifier], "G")
                else:
                    add(domain, alias, ids, "F")
                    for stream in partition["online_streams"]:
                        add(domain, alias, stream, "O")
            if domain != "travel":
                add(domain, "NATIVE_VERIFIED_HISTORY_REFERENCE",
                    partition["verified_replay_subset"], "O", label="verified-history")
        elif phase == "contribution":
            ids = partition["contribution_subset"]
            if domain == "travel":
                for identifier in ids:
                    add(domain, "milai", [identifier], "G", label="append-only")
            else:
                add(domain, "milai", ids, "F", label="append-only")
        elif phase == "resources":
            ids = partition["resource_subset"]
            for resource in ("low", "high"):
                for alias in ("rb", "milai"):
                    if domain == "travel":
                        for identifier in ids:
                            add(
                                domain, alias, [identifier], "G",
                                label="resource", resource=resource
                            )
                    else:
                        add(domain, alias, ids, "F", label="resource", resource=resource)
    configs = [json.loads(Path(job["config"]).read_text()) for job in jobs]
    manifest = {
        "id": phase.upper(), "workers": decision["workers"], "jobs": jobs,
        "decision": str(decision_file), "decision_sha256": sha(decision_file.read_bytes()),
        "planned_units": sum(len(config["ids"]) for config in configs),
        "generation_ceiling": sum(config["max_requests"] for config in configs),
        "raw_token_ceiling": sum(config["max_tokens"] for config in configs),
    }
    path = root / "batch.json"
    save(path, manifest)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--phase", choices=["support", "main", "contribution", "resources"],
                        required=True)
    args = parser.parse_args()
    print(prepare(args.decision, args.phase))


if __name__ == "__main__":
    main()
