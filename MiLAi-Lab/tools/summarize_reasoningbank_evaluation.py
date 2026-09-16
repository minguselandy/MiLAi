"""Coverage, role costs and paired cluster intervals from native run artifacts.

This analysis reads recorded evaluator outputs, never task answers or model APIs.
Missing planned units remain in the conservative quality denominator.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def events(path):
    if path.exists():
        return [json.loads(line) for line in path.read_text().splitlines() if line]
    return []


def costs(root):
    roles = collections.defaultdict(lambda: {"requests": 0, "tokens": 0, "seconds": 0.0})
    units = collections.defaultdict(lambda: {"requests": 0, "tokens": 0})
    pending = {}
    for path in (root / "provider").glob("*ledger*.jsonl"):
        for event in events(path):
            key = event.get("request_id")
            if event["event"] == "RESERVED":
                pending[key] = event["raw_upper_bound"]
            elif event["event"] == "SETTLED":
                pending.pop(key, None)
                row = roles[event["role"]]
                row["requests"] += 1
                row["tokens"] += event["input_tokens"] + event["output_tokens"]
                row["seconds"] += event["seconds"]
                unit = units[event["session"].split(":")[1]]
                unit["requests"] += 1
                unit["tokens"] += event["input_tokens"] + event["output_tokens"]
    embedding = {"requests": 0, "tokens": 0, "seconds": 0.0, "unknown_requests": 0}
    opened = set()
    for event in events(root / "embedding/embedding-ledger.jsonl"):
        if event["event"] == "RESERVED":
            opened.add(event["request_id"])
        elif event["event"] == "SETTLED":
            opened.discard(event["request_id"])
            embedding["requests"] += 1
            embedding["tokens"] += event["usage"]["total_tokens"]
            embedding["seconds"] += event["seconds"]
    embedding["unknown_requests"] = len(opened)
    return {
        "roles": dict(roles),
        "by_unit": dict(units),
        "embedding": embedding,
        "settled_requests": sum(row["requests"] for row in roles.values()),
        "settled_tokens": sum(row["tokens"] for row in roles.values()),
        "unknown_requests": len(pending),
        "unknown_token_upper_bound": sum(pending.values()),
    }


def samples(config, split):
    root = Path(config["output_root"])
    domain = config["domain"]
    metadata = {row["id"]: row for row in split["domains"][domain]["partitions"][config["split"]]}
    result = []
    travel = load(root / "coverage-scores.json", {})
    groups = {row["id"]: row for row in travel.get("groups", [])}
    for identifier in config["ids"]:
        meta = metadata[identifier]
        unit = {"id": identifier, "cluster": meta["cluster"], "stream": config["stream"]}
        if domain == "travel":
            group = groups.get(identifier, {})
            people = group.get("persons", [])
            terminal = group.get("terminal_sessions", group.get("delivered_sessions", 0))
            unit.update(
                planned_sessions=meta["sessions"],
                terminal_sessions=terminal,
                nonempty_final_plans=group.get("nonempty_final_plans"),
                score_available=terminal == meta["sessions"],
                evaluator_output_available=bool(group),
                ps_numerator=sum(person["full_pass"] for person in people),
                ps_denominator=meta["sessions"],
                sps=group.get("constraint_rate") if group else 0.0,
                sr=float(group.get("full_pass", False)),
                persons=people,
            )
        else:
            session = load(root / f"task-{identifier}/native-session.json", {})
            outcome = session.get("evaluation_record", {}).get("outcome", "missing")
            unit.update(
                planned_sessions=1,
                terminal_sessions=int(bool(session)),
                score_available=outcome in {"correct", "incorrect"},
                correct=float(outcome == "correct"),
                outcome=outcome,
                status=session.get("sample_status", "missing"),
                finish_reason=session.get("finish_reason"),
            )
        result.append(unit)
    return result


def metric(rows, name):
    if name == "ps":
        return sum(row["ps_numerator"] for row in rows) / sum(row["ps_denominator"] for row in rows)
    values = [row[name] for row in rows if row[name] is not None]
    return sum(values) / len(values) if values else 0.0


def paired_outcomes(left, right, *, travel=False):
    """Keep unscored pairs separate from pairs with two native correctness scores."""
    right_by_id = {row["id"]: row for row in right}
    counts = dict.fromkeys(
        ("both_correct", "left_only", "right_only", "both_wrong", "unscored_pair"), 0
    )
    for row in left:
        other = right_by_id[row["id"]]
        if not row["score_available"] or not other["score_available"]:
            counts["unscored_pair"] += 1
            continue
        a, b = bool(row["sr" if travel else "correct"]), bool(other["sr" if travel else "correct"])
        key = (
            "both_correct" if a and b else "left_only" if a else "right_only" if b else "both_wrong"
        )
        counts[key] += 1
    return counts


def paired(left, right, *, name, online, repeats=10000):
    lmap, rmap = {r["id"]: r for r in left}, {r["id"]: r for r in right}
    if set(lmap) != set(rmap):
        raise ValueError("PAIRED_PLANNED_COVERAGE_MISMATCH")
    clusters = collections.defaultdict(list)
    for identifier, row in lmap.items():
        # Online stream labels differ by method; membership defines its identity.
        key = row["stream"] if online else row["cluster"]
        clusters[key].append(identifier)
    keys = sorted(clusters)
    if online:
        right_streams = collections.defaultdict(set)
        for row in right:
            right_streams[row["stream"]].add(row["id"])
        if {frozenset(v) for v in clusters.values()} != {
            frozenset(v) for v in right_streams.values()
        }:
            raise ValueError("PAIRED_ONLINE_STREAM_MEMBERSHIP_MISMATCH")
    rng = random.Random(20260915)  # noqa: S311 -- reproducible statistical resampling
    draws = []
    for _ in range(repeats):
        ids = [identifier for key in rng.choices(keys, k=len(keys)) for identifier in clusters[key]]
        draws.append(metric([lmap[i] for i in ids], name) - metric([rmap[i] for i in ids], name))
    draws.sort()
    return {
        "difference_percentage_points": 100 * (metric(left, name) - metric(right, name)),
        "ci95_percentage_points": [
            100 * draws[int(repeats * 0.025)],
            100 * draws[int(repeats * 0.975) - 1],
        ],
        "resampling_units": len(keys),
        "unit": "stream" if online else "source_cluster",
        "bootstrap_replicates": repeats,
        "seed": 20260915,
        "small_cluster_warning": len(keys) < 10,
        "degenerate_interval": draws[-1] - draws[0] < 1e-12,
        "interval_limit": (
            "An all-tie/degenerate empirical bootstrap is not proof of population equivalence; "
            "few independent streams also limit precision."
        ),
    }


def summarize(batch_paths, output):
    grouped = {}
    for batch_path in batch_paths:
        batch = load(batch_path)
        for job in batch["jobs"]:
            initial = Path(job["config"])
            resolved = initial.with_name(initial.stem + "-resolved.json")
            config = load(resolved if resolved.exists() else initial)
            split = load(Path(config["split_manifest"]))
            key = (
                config["domain"],
                config["protocol"],
                config["method"],
                config.get("analysis_condition", "main"),
                config.get("resource_point", "main"),
            )
            arm = grouped.setdefault(key, {"samples": [], "runs": [], "costs": []})
            cost = costs(Path(config["output_root"]))
            current = samples(config, split)
            for row in current:
                row["model_cost"] = cost["by_unit"].get(row["id"], {"requests": 0, "tokens": 0})
            arm["samples"].extend(current)
            arm["runs"].append(config["output_root"])
            arm["costs"].append(cost)
    arms = []
    for key, arm in grouped.items():
        domain, protocol, method, condition, resource = key
        rows = arm["samples"]
        metrics = ("ps", "sps", "sr") if domain == "travel" else ("correct",)
        arms.append(
            {
                "domain": domain,
                "protocol": protocol,
                "method": method,
                "condition": condition,
                "resource_point": resource,
                "planned_units": len(rows),
                "terminal_units": sum(
                    r["terminal_sessions"] == r["planned_sessions"] for r in rows
                ),
                "planned_sessions": sum(r["planned_sessions"] for r in rows),
                "terminal_sessions": sum(r["terminal_sessions"] for r in rows),
                "score_available_units": sum(r["score_available"] for r in rows),
                "unscored_units": sum(not r["score_available"] for r in rows),
                "native_status_counts": dict(
                    collections.Counter(
                        r.get(
                            "status",
                            "complete_group" if r["score_available"] else "incomplete_group",
                        )
                        for r in rows
                    )
                ),
                "unscored_reasons": dict(
                    collections.Counter(
                        r.get("finish_reason") or r.get("status", "incomplete_group")
                        for r in rows
                        if not r["score_available"]
                    )
                ),
                "successful_units_settled_tokens": sum(
                    r["model_cost"]["tokens"]
                    for r in rows
                    if r["score_available"] and r["sr" if domain == "travel" else "correct"]
                ),
                "coverage_corrected_quality": {name: 100 * metric(rows, name) for name in metrics},
                "settled_requests": sum(c["settled_requests"] for c in arm["costs"]),
                "settled_tokens": sum(c["settled_tokens"] for c in arm["costs"]),
                "unknown_requests": sum(c["unknown_requests"] for c in arm["costs"]),
                "unknown_token_upper_bound": sum(
                    c["unknown_token_upper_bound"] for c in arm["costs"]
                ),
                **arm,
            }
        )
    comparisons = []
    for arm in arms:
        if arm["method"] != "MILAI_EXPERIENCE_REVISION" or arm["condition"] == "append-only":
            continue
        for other in arms:
            if any(arm[key] != other[key] for key in ("domain", "protocol", "resource_point")):
                continue
            if other is arm or other["condition"] == "verified-history":
                continue
            if other["condition"] not in {arm["condition"], "append-only"}:
                continue
            ids = {r["id"] for r in other["samples"]}
            left = [row for row in arm["samples"] if row["id"] in ids]
            if not left or len(left) != len(other["samples"]):
                continue
            metrics = ("ps", "sps", "sr") if arm["domain"] == "travel" else ("correct",)
            comparisons.append(
                {
                    "domain": arm["domain"],
                    "protocol": arm["protocol"],
                    "resource_point": arm["resource_point"],
                    "left": arm["method"] + "/" + arm["condition"],
                    "right": other["method"] + "/" + other["condition"],
                    "paired_units": len(left),
                    "paired_outcomes": paired_outcomes(
                        left, other["samples"], travel=arm["domain"] == "travel"
                    ),
                    "left_paired_settled_tokens": sum(row["model_cost"]["tokens"] for row in left),
                    "right_paired_settled_tokens": sum(
                        row["model_cost"]["tokens"] for row in other["samples"]
                    ),
                    "metrics": {
                        name: paired(
                            left, other["samples"], name=name, online=arm["protocol"] == "O"
                        )
                        for name in metrics
                    },
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"arms": arms, "comparisons": comparisons}, ensure_ascii=False, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.batch, args.output)


if __name__ == "__main__":
    main()
