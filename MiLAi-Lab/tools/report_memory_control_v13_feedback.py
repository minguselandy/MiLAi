"""Count real Reader exposure and measure the action headroom on executed comparison packs."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean


def load(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def per_round(directory):
    contract = json.loads((directory / "round.json").read_text())
    by_kind = defaultdict(Counter)
    resources = defaultdict(Counter)
    statuses = Counter()
    charged = set()
    for path in sorted((directory / "receipts").glob("*.json.gz")):
        r = load(path)
        k = "companion" if r["receipt_id"].startswith("companion_") else "branch"
        if "_repeat" in r["receipt_id"]:
            k += "_repeat"
        by_kind[k]["receipts"] += 1
        by_kind[k]["exposure"] += r["feedback_exposure"]
        if r.get("actual_requests") is None:
            by_kind[k]["unknown_request_count_receipts"] += 1
        else:
            by_kind[k]["new_requests"] += r["actual_requests"]
        statuses[r["status"]] += 1
        if r.get("actual_requests"):
            span = list(range(r["ledger_before"], r["ledger_after"]))
            if len(span) != r["actual_requests"] or charged.intersection(span):
                raise ValueError(f"Duplicated/mismatched charge within {directory}")
            charged.update(span)
        for name in (
            "reader_input_tokens",
            "reader_output_tokens",
            "reader_cached_tokens",
            "reader_client_wall_ms",
            "controller_gpu_ms",
            "controller_wall_ms",
            "pool_and_bm25_wall_ms",
            "navigation_and_admission_wall_ms",
        ):
            value = r.get("costs", {}).get(name)
            if value is not None:
                resources[name]["observed"] += 1
                resources[name]["observed_total"] += value
                if r["feedback_exposure"]:
                    resources[name]["exposed_observations"] += 1
                    resources[name]["exposed_total"] += value
                if r.get("actual_requests"):
                    resources[name]["new_request_total"] += value
    headroom = defaultdict(list)
    populations = defaultdict(Counter)
    groups = defaultdict(set)
    ids = set()
    for path in sorted((directory / "packs").glob("*.json.gz")):
        pack = load(path)
        if (
            pack["split_role"] != "train"
            or pack["continuation_mode"] != "full_episode"
            or pack["continuation_policy_id"] != contract["continuation_policy_id"]
        ):
            raise ValueError("Mixed supervision protocols")
        source = pack["source"]
        if pack["root_state_id"] in ids:
            raise ValueError("Duplicate comparison root")
        ids.add(pack["root_state_id"])
        groups[source].add(pack["native_group_id"])
        pop = populations[source]
        pop["packs"] += 1
        pop["equivalent_level_pairs"] += len(pack["equivalent_levels"])
        ys = {
            v["first_action_id"]: v["reader_quality"]
            for v in pack["outcomes"]
            if v["quality_observed"]
        }
        pop["executed_actions"] += len(pack["outcomes"])
        pop["observed_action_quality"] += len(ys)
        if len(ys) >= 2:
            pop["comparable_quality_packs"] += 1
            pop["nonconstant_quality_packs"] += int(max(ys.values()) > min(ys.values()))
        if "handoff" in ys and len(ys) > 1:
            headroom[source].append(max(ys.values()) - ys["handoff"])
        for a, b in pack["comparisons"]:
            if a in ys and b in ys:
                pop["observed_predefined_comparisons"] += 1
                pop["nonzero_deltas"] += ys[a] != ys[b]
    for source, pop in populations.items():
        pop["native_groups"] = len(groups[source])
    return dict(
        directory=str(directory.resolve()),
        round=contract["round"],
        continuation_policy=contract["continuation_policy_id"],
        sampler=contract["sampler"],
        by_receipt_kind=by_kind,
        receipt_status=statuses,
        resources=resources,
        source_coverage=populations,
        packs=len(ids),
        finite_measured_pool_gain_over_handoff={
            s: {"mean": fmean(values), "roots": len(values)} for s, values in headroom.items()
        },
    ), charged


def report(directories):
    seen_dirs = set()
    rows = []
    paid = set()
    for directory in directories:
        # The same warm directory can be passed once per arm, but billed once per project.
        row, span = per_round(directory)
        if directory.resolve() not in seen_dirs and paid & span:
            raise ValueError("Two distinct run directories claim the same new ledger charge")
        paid.update(span)
        seen_dirs.add(directory.resolve())
        rows.append(row)
    return dict(
        rounds=rows,
        total_feedback_exposure=sum(
            k["exposure"] for r in rows for k in r["by_receipt_kind"].values()
        ),
        verified_unique_new_reader_requests=len(paid),
        unknown_request_count_receipts_in_distinct_directories=sum(
            sum(k.get("unknown_request_count_receipts", 0) for k in row["by_receipt_kind"].values())
            for row in {r["directory"]: r for r in rows}.values()
        ),
        exposure_scope=(
            "Supplied collection directories, including paid partial packages. "
            "Development readouts and QR online collection are metered separately."
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("rounds", type=Path, nargs="+")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = report(args.rounds)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    tmp.replace(args.out)
