"""Estimate within-wire Reader utility dispersion using physical, scored TRAIN requests only."""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, variance

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.methods.control_cost_scale import load_host_cost_scale


def gz(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def paid_id(record):
    if record["actual_requests"] != 1 or record.get("measurement_reused_from"):
        return None
    begin, end = record["ledger_before"], record["ledger_after"]
    assert end == begin + 1
    provider = record.get("reader_result", {}).get("response", {}).get("id")
    return (begin, provider) if provider else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--warm", type=Path, required=True)
    p.add_argument("--host-cost-scale", type=Path, required=True)
    p.add_argument("--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads((a.warm / "round.json").read_text())
    scale, _ = load_host_cost_scale(
        a.host_cost_scale, dataset_run_id=cfg["dataset_run"], budget=cfg["material_budget"]
    )
    penalty = cfg["utility_lambda"]
    if (cfg["sampler"], cfg["continuation_mode"], cfg["round"]) != ("uniform", "full_episode", 0):
        raise ValueError("Expected the common uniform TRAIN warm round")
    db = a.dataset / "memory_control.sqlite3" if a.dataset.is_dir() else a.dataset
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        tasks = {
            tid: (src, group)
            for tid, src, group in connection.execute(
                "SELECT id,dataset,native_group FROM experiment_tasks "
                "WHERE experiment_role='train' AND clean_role='train'"
            )
        }
        run = json.loads(
            connection.execute("SELECT value FROM metadata WHERE key='run_id'").fetchone()[0]
        )
        assert run == cfg["dataset_run"]
    counts = defaultdict(Counter)
    groups = defaultdict(list)
    used_receipts = set()
    slots = set()
    provider_ids = set()
    for path in sorted((a.warm / "packs").glob("*.json.gz")):
        r = gz(path)
        src = r["source"]
        tid = r["task_id"]
        native = r["native_group_id"]
        root = r["root_state_id"]
        if (
            r["split_role"],
            tasks.get(tid),
            r["collection_round"],
            r["continuation_policy_id"],
        ) != ("train", (src, native), 0, cfg["continuation_policy_id"]):
            raise ValueError("Root outside the frozen TRAIN protocol")
        counts[src]["roots"] += 1
        measured = defaultdict(list)
        for outcome in r["outcomes"]:
            (receipt_id,) = outcome["reader_receipt_ids"]
            d = gz(a.warm / "receipts" / (receipt_id + ".json.gz"))
            assert (d["task_id"], d["native_group_id"], d["receipt_id"]) == (
                tid,
                native,
                receipt_id,
            )
            used_receipts.add(receipt_id)
            companion = outcome["companion_receipt_id"]
            cp_id = None
            if src == MUSIQUE:
                cp = gz(a.warm / "receipts" / (companion + ".json.gz"))
                assert cp["task_id"] != tid and tasks[cp["task_id"]] == (src, native)
                assert cp["native_group_id"] == native
                cp_id = paid_id(cp)
                used_receipts.add(companion)
                if cp_id is None:
                    counts[src]["unverified_companion_observations"] += 1
                    continue
            else:
                assert companion is None
            if d["actual_requests"] == 0 or d.get("measurement_reused_from"):
                counts[src]["excluded_cached_branches"] += 1
                continue
            identity = paid_id(d)
            if (
                identity is None
                or not outcome["quality_observed"]
                or not outcome["future_cost_observed"]
            ):
                counts[src]["excluded_unverified_or_masked_branches"] += 1
                continue
            if identity[0] in slots or identity[1] in provider_ids:
                raise ValueError("Duplicated physical ledger slot or provider response ID")
            slots.add(identity[0])
            provider_ids.add(identity[1])
            counts[src]["distinct_paid_branches"] += 1
            costs = d["costs"]
            fixed = costs["incremental_material_tokens"] + costs["reader_input_tokens"]
            tokens = costs["reader_output_tokens"]
            assert outcome["immediate_cost"] + outcome["future_cost"] == fixed + tokens
            # Group by exact object equality through reversible JSON. Never compare different roots.
            wire = json.dumps(d["reader_wire"], sort_keys=True, separators=(",", ":"))
            q = outcome["reader_quality"]
            measured[(wire, cp_id, fixed)].append(
                dict(
                    receipt=receipt_id,
                    provider=identity[1],
                    ledger=identity[0],
                    source=src,
                    native_group=native,
                    task=tid,
                    root=root,
                    action=outcome["first_action_id"],
                    seed=d["reader_wire"].get("seed"),
                    companion=companion,
                    quality=q,
                    output_tokens=tokens,
                    deterministic_tokens=fixed,
                    net_utility=q - penalty * (fixed + tokens) / scale,
                )
            )
        for members in measured.values():
            if len(members) > 1:
                groups[src].append(members)
    summaries = {}
    for src in counts:
        strata = groups[src]
        df = sum(len(g) - 1 for g in strata)
        sums = Counter()
        for g in strata:
            for field in ("quality", "output_tokens", "net_utility"):
                sums[field] += (len(g) - 1) * variance(row[field] for row in g)
            mq = mean(row["quality"] for row in g)
            mt = mean(row["output_tokens"] for row in g)
            sums["quality_output_covariance"] += sum(
                (row["quality"] - mq) * (row["output_tokens"] - mt) for row in g
            )
        var = {
            field: sums[field] / df if df else None
            for field in ("quality", "output_tokens", "net_utility", "quality_output_covariance")
        }
        summaries[src] = dict(
            counts[src],
            repeated_wires=len(strata),
            native_groups_with_repeats=len({g[0]["native_group"] for g in strata}),
            repeat_observations=sum(map(len, strata)),
            within_wire_df=df,
            same_first_action_repeats=sum(len(g) - len({r["action"] for r in g}) for g in strata),
            pooled_within_wire_variances=var,
        )
    write_json(
        a.output,
        dict(
            dataset_run=run,
            split_role="train",
            continuation=cfg["continuation_policy_id"],
            cost_unit=scale,
            penalty=penalty,
            new_reader_requests=0,
            linked_logical_receipts=len(used_receipts),
            by_source=summaries,
            physical_repeat_strata=dict(groups),
            meaning="Within fixed seed/wire and companion; conditional on observed TRAIN repeats.",
        ),
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
