"""Check native group quotas and package pricing against recorded, real TRAIN requests."""

from __future__ import annotations

import argparse
import random
import statistics
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.control_acquisition_pool import ExplorationBudget, NativeRootPool, slate_rng
from milai_lab.runners.control_policy_iteration import (
    Receipts,
    acquire,
    bind_mechanism_pool,
    candidate,
    plan_pack,
    read_gzip,
    sampler_priority,
    select_pack,
)


def stress(db, prefix, measured, limits, seed):
    """Accounting stress test on the actual roster and resampled observed TRAIN request counts."""
    rng = random.Random(seed)  # noqa: S311 -- fixed audit
    summaries = []
    for stage, target in enumerate(limits, 1):
        pool = NativeRootPool(db)
        if stage == 1:
            for row in prefix:
                pool.accept(row)
        spend = ExplorationBudget()
        charged = 0
        steps = selected = 0
        while charged < target:
            batch, _ = pool.slate(8, rng, boundary_slot=(steps if target - charged < 5 else 0))
            source, group, task = max(batch, key=lambda x: pool.group_counts[x[0], x[1]])
            # Prefer the most exposed native group in its slate to stress the cap.
            n = rng.choice(measured[source])
            steps += 1
            if charged + n > target:
                if steps > 10 * target:
                    raise ValueError("Could not close the synthetic stress budget")
                continue
            reserved = spend.random_slot(source, target - charged, target)
            r = dict(
                task_id=task,
                source=source,
                native_group_id=group,
                realized_new_exposure=n,
                realized_new_requests=n,
                selection_kind="reserved_uniform" if reserved else "positive_priority",
            )
            pool.accept(r)
            selected += 1
            spend.observe(r)
            charged += n
        maximum = {
            s: max((v for (dataset, _), v in pool.group_counts.items() if dataset == s), default=0)
            for s in pool.source_counts
        }
        assert pool.source_counts[PERSONA] <= sum(pool.source_counts.values()) // 10
        assert all(m <= (4 if s == MUSIQUE else 6) for s, m in maximum.items())
        # One bounded pack's overshoot/undershoot per source is unavoidable.
        assert sum(spend.reserved.values()) >= (target + 3) // 4
        for s, total in spend.exposure.items():
            assert abs(spend.reserved[s] - 0.25 * total) <= max(measured[s])
        summaries.append(
            dict(
                stage=stage,
                simulated_feedback_units=charged,
                new_selected_tasks=selected,
                source_roots=dict(pool.source_counts),
                maximum_before_per_native_group=maximum,
                by_source=spend.report(),
            )
        )
    return summaries


def compare_round_seeds(db, count=512):
    result = {}
    for label, warm in (("without_round_seed", True), ("with_round_seed", False)):
        admitted = []
        for pool_seed in (1102, 1103):
            pool = NativeRootPool(db)
            for i in range(count):
                rng = slate_rng(11, pool_seed, i, warm=warm)
                slate, _ = pool.slate(8, rng)
                s, g, t = rng.choice(slate)
                pool.accept(dict(source=s, native_group_id=g, task_id=t))
            admitted.append(pool.ids)
        result[label] = {
            "tasks_per_round": count,
            "tasks_selected_in_both": len(admitted[0] & admitted[1]),
        }
    return result


def exercise_windows(args, dataset, rows, model):
    from milai_lab.methods.pretrained_control import PretrainedPolicy

    summaries = []
    with (
        closing(connect(dataset.path)) as db,
        tempfile.TemporaryDirectory(dir=args.output.parent) as tmp,
    ):
        for stage in (1, 2):
            pool = NativeRootPool(db)
            if stage == 1:
                for row in rows:
                    pool.accept(row)
            base_seed = 1100 + stage
            policy = FixedContextMemoryPolicy(4) if stage == 1 else PretrainedPolicy(model, 0.05)
            receipts = Receipts(Path(tmp) / str(stage), dataset, db)
            frames = []
            for mode in ("uniform", "structured"):
                opts = argparse.Namespace(
                    seed=11,
                    round=stage,
                    budget=2048,
                    window=8,
                    calls=4000 if stage == 1 else 6000,
                    sampler=mode,
                    utility_lambda=0.05,
                )
                cfg = dict(seed=11, material_budget=2048)
                with patch(
                    "milai_lab.runners.control_policy_iteration.reader_lease",
                    side_effect=AssertionError("Unselected pricing cannot issue Reader requests"),
                ):
                    proposal, planned, meta = select_pack(
                        opts,
                        dataset,
                        db,
                        receipts,
                        pool,
                        ExplorationBudget(),
                        policy,
                        None if stage == 1 else model,
                        model,
                        0,
                        cfg,
                        base_seed,
                    )
                assert all(
                    "grade" not in record and "reader_result" not in record
                    for record, _ in planned[1]
                )
                assert receipts.calls == 0
                frames.append(meta["candidate_task_ids"])
                summaries.append(
                    dict(
                        stage=stage,
                        mode=mode,
                        source=proposal[0]["dataset"],
                        prefix=proposal[1],
                        selected=meta,
                        planned_action_ids=proposal[3].actions,
                        terminal_paths=[record["action_trace"] for record, _ in planned[1]],
                        actual_new_reader_requests=receipts.new_requests,
                    )
                )
            assert frames[0] == frames[1]
    write_json(
        args.output,
        dict(
            scope="Offline S0 checkpoint proxy. Exact legal continuations, zero feedback calls.",
            actual_new_reader_calls=0,
            initial_warm_prefix=len(rows),
            windows=summaries,
        ),
    )
    print(
        [(s["stage"], s["mode"], s["selected"]["task"], s["selected"]["quote"]) for s in summaries]
    )


def verify_closed_warm(args):
    progress = read_json(args.warm / "progress.json")
    cfg = read_json(args.warm / "round.json")
    if progress.get("state") != "complete" or progress["feedback_calls"] != 2000:
        raise ValueError("Warm account is not closed at the 2k boundary")
    files = sorted((args.warm / "packs").glob("*.json.gz"))
    data = args.dataset / "memory_control.sqlite3" if args.dataset.is_dir() else args.dataset
    with closing(connect(data)) as db:
        pool = NativeRootPool(db)
    bound = set()
    price_errors = 0
    checked = 0
    for f in files:
        row = read_gzip(f)
        pool.accept(row)
        for out in row["outcomes"]:
            bound.update(out["reader_receipt_ids"])
            if out.get("companion_receipt_id"):
                bound.add(out["companion_receipt_id"])
        quote = row.get("expected_cost")
        if quote is not None:
            checked += 1
            price_errors += int(
                quote["expected_arm_exposure"] != row["realized_new_exposure"]
                or quote["expected_new_requests"] != row["realized_new_requests"]
            )
    slots = set()
    physical = unknown = exposure = unbound_paid = 0
    receipts = set()
    for f in (args.warm / "receipts").glob("*.json.gz"):
        r = read_gzip(f)
        key = r["receipt_id"]
        receipts.add(key)
        exposure += r["feedback_exposure"]
        unknown += r["actual_requests"] is None
        if r["actual_requests"]:
            billed = range(r["ledger_before"], r["ledger_after"])
            if len(billed) != r["actual_requests"] or slots.intersection(billed):
                raise ValueError("Duplicate or inconsistent native HTTP ledger slots")
            physical += len(billed)
            slots.update(billed)
            if key not in bound:
                unbound_paid += len(billed)
    if bound - receipts or exposure != 2000 or progress["actual_new_requests"] != physical:
        raise ValueError("Warm manifest and actual native request records disagree")
    if (
        sum(pool.source_counts.values()) != len(files)
        or pool.source_counts[PERSONA] > len(files) // 10
    ):
        raise ValueError("Native-group warm source quota differs from executed roots")
    if unbound_paid or unknown or receipts - bound:
        write_json(
            args.output,
            dict(
                status="unresolved",
                exposure=exposure,
                verified_nonoverlapping_ledger_charges=physical,
                unknown_request_counts=unknown,
                unbound_paid=unbound_paid,
                unbound_receipt_ids=sorted(receipts - bound),
            ),
        )
        raise ValueError("Unresolved warm charges or receipts. See the closure report")
    common = bind_mechanism_pool(args.warm, cfg["seed"] * 100 + 1, pool, cfg)
    snapshot = read_gzip(common)
    future = {}
    for s, groups in snapshot["available"].items():
        cap = 4 if s == MUSIQUE else 6
        maximum = max((v for (src, _), v in pool.group_counts.items() if src == s), default=0)
        full = maximum
        for g, values in groups.items():
            if (
                values["before_slots"] != cap - pool.group_counts[s, g]
                or set(values["tasks"]) & pool.ids
            ):
                raise ValueError(
                    "Common TRAIN mechanism roster contains ineligible tasks or group slots"
                )
            full = max(
                full, pool.group_counts[s, g] + min(len(values["tasks"]), values["before_slots"])
            )
        if full > cap:
            raise ValueError("The frozen pool could exceed a cumulative native cap")
        future[s] = dict(
            warm_roots=pool.source_counts[s],
            warm_maximum_before_per_group=maximum,
            available_native_groups=len(groups),
            available_tasks=sum(len(v["tasks"]) for v in groups.values()),
            maximum_possible_combined_before_per_group=full,
            cap=cap,
        )
    write_json(
        args.output,
        dict(
            status="verified",
            dataset_run=cfg["dataset_run"],
            complete_before_roots=len(files),
            unique_bound_receipts=len(bound),
            verified_nonoverlapping_ledger_charges=physical,
            exposure=exposure,
            unbound_paid=unbound_paid,
            unknown_request_counts=unknown,
            unbound_receipts=len(receipts - bound),
            by_source=future,
            common_pool=str(common),
            exact_pricing_checked_roots=checked,
            realized_cost_mismatches=price_errors,
        ),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--warm", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--roots", type=int, default=160)
    p.add_argument("--full-replays", type=int, default=32)
    p.add_argument("--head-checkpoint", type=Path)
    p.add_argument("--policy-window-only", action="store_true")
    p.add_argument("--verify-closed-warm", action="store_true")
    args = p.parse_args()
    if args.verify_closed_warm:
        verify_closed_warm(args)
        return
    files = sorted((args.warm / "packs").glob("*.json.gz"))[: args.roots]
    if len(files) != args.roots:
        raise ValueError("Require all registered prefix roots")
    rows = [read_gzip(f) for f in files]
    config = read_json(args.warm / "round.json")
    dataset = MemoryControlDataset(args.dataset)
    head = None
    if args.head_checkpoint:
        from milai_lab.methods.pretrained_control import PretrainedControl

        head = PretrainedControl.load(args.head_checkpoint, device="cpu")
    if args.policy_window_only:
        if head is None:
            raise ValueError("The policy-window check requires a loaded S0 model")
        exercise_windows(args, dataset, rows, head)
        return
    from milai_lab.runners.control_policy_iteration import model_utilities

    stats = defaultdict(Counter)
    actions = defaultdict(list)
    width = []
    ranks = defaultdict(list)
    policy = FixedContextMemoryPolicy(4)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(connect(dataset.path)) as db,
        tempfile.TemporaryDirectory(dir=args.output.parent) as tmp,
    ):
        local = Receipts(Path(tmp) / "isolated", dataset, db)
        peer = Receipts(Path(tmp) / "peer", dataset, db, [args.warm / "receipts"])
        for i, r in enumerate(rows):
            source = r["source"]
            curr = stats[source]
            keys = [o["reader_receipt_ids"][0] for o in r["outcomes"]]
            companion = r["outcomes"][0]["companion_receipt_id"]
            if companion:
                keys.insert(0, companion)
            rec = [read_gzip(args.warm / "receipts" / (k + ".json.gz")) for k in keys]
            unique = []
            for m in rec:
                wire = (m["task_id"], m["reader_wire"])
                if wire not in unique:
                    unique.append(wire)
            curr["roots"] += 1
            curr["nominal_feedback_units"] += len(keys)
            curr["distinct_terminal_wires"] += len(unique)
            curr["coalescible_packages"] += len(unique) < len(keys)
            curr["observed_actual_requests"] += sum(m["actual_requests"] or 0 for m in rec)
            actions[source].append(len(unique))
            if i >= args.full_replays:
                continue
            proposal = candidate(
                dataset,
                db,
                r["task_id"],
                config["material_budget"],
                config["seed"],
                policy,
                None,
                config["utility_lambda"],
            )
            jobs, prepared, cost = plan_pack(dataset, db, local, proposal, policy, config)
            assert [job.key for job in jobs] == keys
            assert all(
                preview["reader_wire"] == actual["reader_wire"]
                for (preview, _), actual in zip(prepared, rec, strict=True)
            )
            assert cost["independent_feedback_units"] == len(unique)
            assert cost["expected_new_requests"] == len(unique)
            target = peer.quote(jobs, prepared)
            assert target["independent_feedback_units"] == cost["independent_feedback_units"]
            assert target["expected_new_requests"] == 0
            before = peer.calls
            with patch(
                "milai_lab.runners.control_policy_iteration.reader_lease",
                side_effect=AssertionError("CPU audit cannot issue Reader transport"),
            ):
                result = acquire(peer, proposal, config, (jobs, prepared, target))
            assert peer.calls - before == target["expected_arm_exposure"]
            for restored, original in zip(result["outcomes"], r["outcomes"], strict=True):
                assert all(
                    restored[k] == original[k]
                    for k in ("first_action_id", "reader_quality", "future_cost", "action_trace")
                )
            curr["exact_cpu_policy_replays"] += 1
            curr["peer_replay_exposure"] += peer.calls - before
            if head:
                net = model_utilities(head, proposal[2], config["utility_lambda"])
                numerator = sampler_priority("structured", net, proposal[2], proposal[3], 1)
                ranks[source].append((numerator / len(keys), numerator / len(unique)))
            width.append(len(keys) - len(unique))
        outcomes = {}
        for src, pairs in ranks.items():
            inversions = sum(
                (a - b) * (c - d) < 0 for i, (a, c) in enumerate(pairs) for b, d in pairs[i + 1 :]
            )
            outcomes[src] = dict(
                roots=len(pairs),
                positive=sum(a > 0 for a, _ in pairs),
                cost_correction_pairwise_order_reversals=inversions,
            )
        report = dict(
            native_train_prefix=len(rows),
            actual_new_reader_calls_during_audit=peer.new_requests,
            source_counts={s: dict(v) for s, v in stats.items()},
            mean_overpricing_on_cpu_replays=statistics.mean(width),
            score_check=outcomes,
            score_check_model=str(args.head_checkpoint) if head else None,
            uniform_round_seed_overlap=compare_round_seeds(db),
            native_quota_stress=stress(db, rows, actions, [4000, 6000], config["seed"]),
            stress_scope="TRAIN roster and sampled observed call counts; simulated selection only.",
        )
        write_json(args.output, report)
        print(report["source_counts"], report["score_check"])


if __name__ == "__main__":
    main()
