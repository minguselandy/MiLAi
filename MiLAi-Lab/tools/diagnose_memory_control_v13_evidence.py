"""Measure READ-vs-HANDOFF reversals after two cost-matched acquisitions on natural DEV tasks."""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
from collections import Counter, defaultdict
from contextlib import closing, nullcontext
from pathlib import Path
from statistics import fmean

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.control_policy_iteration import (
    Receipts,
    TerminalJob,
    load_policy,
    read_gzip,
    write_gzip,
)
from milai_lab.runners.memory_control_episode import score_episode
from milai_lab.runners.memory_control_outcome_run import comparison_protocol
from milai_lab.runners.qrag_milai_env import cold_root, collect_terminal, outcome_label
from milai_lab.runners.v13_phase import phase_directory, phase_unit


def matched_prefixes(dataset, db, task, budget, tolerance):
    session, menu, _ = cold_root(dataset, db, task, budget)
    reads = [a for a in menu if a.kind == "READ" and not a.parameters.get("expand_context")]
    cost = {a.id: session.proposed_material_cost(a)["incremental_material_tokens"] for a in reads}
    pairs = [
        (abs(cost[a.id] - cost[b.id]), a, b)
        for a, b in itertools.combinations(reads, 2)
        if cost[a.id] and cost[b.id] and abs(cost[a.id] - cost[b.id]) <= tolerance
    ]
    for difference, a, b in sorted(pairs, key=lambda p: (p[0], p[1].id, p[2].id)):
        sessions = [
            cold_root(dataset, db, task, budget, ("search", x.id), session.pool) for x in (a, b)
        ]
        allowed = []
        for _, options, _ in sessions:
            allowed.append(
                {
                    r.id
                    for r in options
                    if r.kind == "READ"
                    and not r.parameters.get("expand_context")
                    and r.parameters["index"] not in {a.parameters["index"], b.parameters["index"]}
                }
            )
        common = next((r.id for r in reads if r.id in allowed[0] & allowed[1]), None)
        if common:
            return (a.id, b.id), common, difference, session.pool
    return None


def collect_reference(args):
    population = json.loads(args.population.read_text())
    if population["role"] != "dev" or population["v13_role"] != "curve":
        raise ValueError("Use the registered DEV learning-curve population")
    ds = MemoryControlDataset(args.data)
    budget = population["material_budget"]
    config = dict(
        population=str(args.population.resolve()),
        dataset_run_id=ds.run_id,
        cap_per_source=args.per_source,
        budget_tolerance=args.tolerance,
        seed=population["seed"],
        material_budget=budget,
        role="TUNE_diagnostic",
        continuation="pi0-fixedcontext-4",
        max_operations=6,
        material_protocol="two different first R2 objects, same shared next R2 binding",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    registration = args.output / "registration.json"
    if registration.exists() and json.loads(registration.read_text()) != config:
        raise ValueError("Existing evidence diagnostic uses a different protocol")
    registration.write_text(json.dumps(config, indent=2))
    counts = Counter()
    missing = Counter()
    used = set()
    with (args.output / ".lock").open("a") as lock, closing(connect(ds.path)) as db:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts = Receipts(args.output / "receipts", ds, db)
        policy = FixedContextMemoryPolicy(4)
        for item in population["tasks"]:
            source, group, tid = item["dataset"], item["native_group"], item["task_id"]
            if counts[source] >= args.per_source or (source, group) in used:
                continue
            path = args.output / "pairs" / f"{tid}.json.gz"
            if not path.exists():
                task = db.execute(
                    "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='dev'", (tid,)
                ).fetchone()
                if task is None or task["native_group"] != group or task["dataset"] != source:
                    raise ValueError("Diagnostic roster and dataset differ")
                match = matched_prefixes(ds, db, task, budget, args.tolerance)
                if match is None:
                    missing[source] += 1
                    continue
                prefixes, candidate, difference, pool = match
                seed = population["seed"] + tid
                adjunct = None
                if source == MUSIQUE:
                    (other,) = db.execute(
                        "SELECT * FROM experiment_tasks WHERE dataset=? "
                        "AND native_group=? AND experiment_role='dev' AND id!=?",
                        (source, group, tid),
                    ).fetchall()
                    env, _, setup = cold_root(ds, db, other, budget)
                    adjunct = receipts.measure(
                        other, env, policy, seed, f"companion_{other['id']}", setup=setup
                    )
                states = []
                for prefix in prefixes:
                    labels = {}
                    for target in ("handoff", candidate):
                        env, menu, setup = cold_root(ds, db, task, budget, ("search", prefix), pool)
                        online = env.online(menu)
                        chosen = next(a for a in menu if a.id == target)
                        episode = receipts.measure(
                            task,
                            env,
                            policy,
                            seed,
                            f"{tid}_{prefix}_{target}",
                            first=chosen,
                            setup=setup,
                        )
                        labels[target] = outcome_label(source, episode, adjunct)
                    states.append(dict(prefix=prefix, online=online, labels=labels))
                write_gzip(
                    path,
                    dict(
                        task_id=tid,
                        native_group=group,
                        dataset=source,
                        split_role="dev",
                        candidate=candidate,
                        states=states,
                        material_tokens_difference=difference,
                    ),
                )
            used.add((source, group))
            counts[source] += 1
        (args.output / "capture.json").write_text(
            json.dumps(
                dict(groups=counts, unmatched=missing, feedback_calls=receipts.calls), indent=2
            )
        )


def native_deltas(labels, candidate, penalty, scale):
    read, stop = labels[candidate], labels["handoff"]
    if not read["quality_observed"] or not stop["quality_observed"]:
        return {}
    gain = read["reader_quality"] - stop["reader_quality"]
    result = {"quality": gain}
    if penalty is not None and (
        not penalty
        or all(a["future_cost_observed"] and a["immediate_cost"] is not None for a in (read, stop))
    ):
        cost_gap = (
            (
                read["immediate_cost"]
                + read["future_cost"]
                - stop["immediate_cost"]
                - stop["future_cost"]
            )
            if penalty
            else 0.0
        )
        result["utility"] = gain - penalty * cost_gap / scale
    return result


def require_equal(left, right, message):
    if left != right:
        raise ValueError(message)


class AlignedReceipts(Receipts):
    """Reuse a paid single-task response only after transport and native scorer checks."""

    def __init__(self, directory, dataset, db, reference, reuse_only, peer_compatible=True):
        super().__init__(directory, dataset, db)
        self.donor = reference
        self.reuse_only = reuse_only
        self.peer_compatible = peer_compatible
        self.foreign_by_task = defaultdict(list)
        self.unreadable_donor_files = set()
        for f in (reference / "receipts").glob("*.json.gz"):
            try:
                self.foreign_by_task[read_gzip(f)["task_id"]].append(f)
            except (OSError, EOFError, ValueError, TypeError, KeyError):
                self.unreadable_donor_files.add(f)

    def match(self, job, record, *, peer, donor_only=False):
        paths = (
            [
                self.donor / "receipts" / self.path(job.key).name,
                *self.foreign_by_task[job.task["id"]],
            ]
            if peer and self.peer_compatible
            else []
        )
        if not donor_only:
            paths.extend(self.by_task[job.task["id"]])
        for f in dict.fromkeys(paths):
            if not f.is_file() or f in self.unreadable_donor_files:
                continue
            prior = read_gzip(f)
            if (
                (prior.get("task_id"), prior.get("native_group_id"))
                != (job.task["id"], job.task["native_group"])
                or prior.get("reader_wire") != record["reader_wire"]
                or not prior.get("grade")
            ):
                continue
            origin = Path(prior.get("measurement_reused_from") or f)
            # A donor alias is usable only when its actual paid observation can be verified.
            if origin.parent.resolve() not in {
                self.directory.resolve(),
                (self.donor / "receipts").resolve(),
            }:
                continue
            if not origin.is_file() or origin in self.unreadable_donor_files:
                continue
            paid = prior if origin.resolve() == f.resolve() else read_gzip(origin)
            response = (paid.get("reader_result") or {}).get("response") or {}
            if (
                type(paid.get("actual_requests")) is not int
                or paid["actual_requests"] != 1
                or type(paid.get("ledger_before")) is not int
                or paid.get("ledger_after") != paid["ledger_before"] + 1
                or (paid.get("reader_result") or {}).get("status") != "reader_completed"
                or not response.get("id")
                or response.get("model") != record["reader_wire"]["model"]
                or (paid["task_id"], paid["native_group_id"])
                != (job.task["id"], job.task["native_group"])
                or paid["reader_wire"] != record["reader_wire"]
                or paid.get("reader_result") != prior.get("reader_result")
                or paid.get("measurement_reused_from")
            ):
                continue
            usage = response.get("usage") or {}
            costs = paid["costs"]
            if costs.get("reader_usage_source") == "provider":
                tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
            elif costs.get("reader_usage_source") == "local_tokenizer":
                choice = (response.get("choices") or [{}])[0].get("message") or {}
                content = choice.get("content")
                tokens = (
                    record["capacity"].get("prompt_tokens"),
                    self.dataset.host.capacity.text_tokens(
                        str(choice.get("reasoning_content") or "") + content
                    )
                    if isinstance(content, str)
                    else None,
                )
            else:
                continue
            if tokens != (costs.get("reader_input_tokens"), costs.get("reader_output_tokens")):
                continue
            check = {
                "reader_result": paid["reader_result"],
                "visible_source_aliases": record["visible_source_aliases"],
            }
            try:
                score_episode(self.dataset, self.db, job.task, check)
            except (IndexError, KeyError, TypeError):
                continue
            if check.get("grade") and check["grade"] == prior["grade"] == paid.get("grade"):
                return f, paid, str(origin.resolve())
        return None

    def readout(self, job, record, get_ledger):
        def offline(_):
            raise RuntimeError(
                "No compatible physical measurement; reuse-only collection cannot issue HTTP"
            )

        return super().readout(job, record, offline if self.reuse_only else get_ledger)


def registered_pairs(ds, db, population, config, donor, receipts):
    counts = Counter()
    unmatched = Counter()
    used = set()
    rows = []
    proved = 0
    existing = {f.name.removesuffix(".json.gz") for f in (donor / "pairs").glob("*.json.gz")}
    closure = read_json(donor / "capture.json")
    if not closure or list((donor / "receipts").glob("*.inflight")):
        raise ValueError("A closed DEV donor capture is required")
    for item in population["tasks"]:
        source, group, tid = item["dataset"], item["native_group"], item["task_id"]
        if counts[source] >= config["cap_per_source"] or (source, group) in used:
            continue
        task = db.execute(
            "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='dev'", (tid,)
        ).fetchone()
        if task is None or (task["dataset"], task["native_group"]) != (source, group):
            raise ValueError("Diagnostic task differs from the native DEV roster")
        match = matched_prefixes(
            ds, db, task, config["material_budget"], config["budget_tolerance"]
        )
        if match is None:
            unmatched[source] += 1
            continue
        prefixes, candidate, difference, pool = match
        if str(tid) not in existing:
            raise ValueError("Frozen diagnostic root is missing")
        old = read_gzip(donor / "pairs" / f"{tid}.json.gz")
        require_equal(
            (
                old["split_role"],
                old["task_id"],
                old["dataset"],
                old["native_group"],
                old["candidate"],
                old["material_tokens_difference"],
                tuple(s["prefix"] for s in old["states"]),
            ),
            ("dev", tid, source, group, candidate, difference, tuple(prefixes)),
            "Frozen native root, prefix, READ candidate or budget binding differs",
        )
        seed = config["seed"] + tid
        for state in old["states"]:
            prefix = state["prefix"]
            env, menu, _ = cold_root(
                ds, db, task, config["material_budget"], ("search", prefix), pool
            )
            require_equal(
                json.loads(json.dumps(env.online(menu))),
                state["online"],
                "Frozen legal before or action menu differs",
            )
            require_equal(
                set(state["labels"]), {"handoff", candidate}, "Frozen comparison menu differs"
            )
            stop = next(a for a in menu if a.id == "handoff")
            job = TerminalJob(
                task, env, FixedContextMemoryPolicy(4), seed, f"{tid}_{prefix}_handoff", stop
            )
            empty = collect_terminal(env, job.policy, seed, stop)
            proved += int(
                bool(empty["reader_wire"])
                and receipts.match(job, empty, peer=True, donor_only=True) is not None
            )
        rows.append((task, old))
        counts[source] += 1
        used.add((source, group))
    require_equal(existing, {str(t["id"]) for t, _ in rows}, "Frozen diagnostic roster differs")
    require_equal(dict(counts), closure["groups"], "Closed donor native group counts differ")
    require_equal(dict(unmatched), closure["unmatched"], "Closed donor unmatched counts differ")
    return rows, counts, unmatched, proved


def verify_pair(path, original, config, receipts):
    row = read_gzip(path)
    for k in (
        "task_id",
        "native_group",
        "dataset",
        "split_role",
        "candidate",
        "material_tokens_difference",
    ):
        require_equal(row[k], original[k], "Completed root differs from its frozen roster")
    require_equal(
        (row["continuation_policy_id"], row["utility_lambda"]),
        (config["continuation"], config["utility_lambda"]),
        "Completed policy binding differs",
    )
    bound = set()
    masked = Counter()
    for state, source in zip(row["states"], original["states"], strict=True):
        require_equal(
            (state["prefix"], state["online"]),
            (source["prefix"], source["online"]),
            "Completed root changed its prefix or legal before",
        )
        require_equal(
            set(state["labels"]), {"handoff", row["candidate"]}, "Completed choices differ"
        )
        for aid, label in state["labels"].items():
            key = f"{row['task_id']}_{state['prefix']}_{aid}"
            require_equal(label["reader_receipt_ids"], [key], "Unexpected primary receipt binding")
            # Original comparison rows pin only the companion's identity, never its old grade.
            cp = source["labels"][aid]["companion_receipt_id"]
            require_equal(label["companion_receipt_id"], cp, "Companion task binding changed")
            record = read_gzip(receipts.path(key))
            require_equal(
                (record["receipt_id"], record["task_id"], record["native_group_id"]),
                (key, row["task_id"], row["native_group"]),
                "Wrong primary native member",
            )
            companion = read_gzip(receipts.path(cp)) if cp else None
            if companion:
                require_equal(
                    (companion["receipt_id"], companion["native_group_id"]),
                    (cp, row["native_group"]),
                    "Wrong companion native group",
                )
                if (
                    companion["task_id"] == row["task_id"]
                    or cp != f"companion_{companion['task_id']}"
                ):
                    raise ValueError("Invalid companion task ID")
                bound.add(cp)
            bound.add(key)
            require_equal(
                outcome_label(row["dataset"], record, companion),
                label,
                "Stored native target differs from the recomputed pair",
            )
            masked["quality"] += not label["quality_observed"]
            masked["cost"] += not label["future_cost_observed"]
    return bound, masked


def collect_aligned(args):
    population = read_json(args.population)
    donor = args.reuse_capture.resolve()
    output = args.output.resolve()
    if donor == output:
        raise ValueError("Use a distinct destination for the aligned capture")
    if args.reuse_only and args.device != "cpu":
        raise ValueError("Offline reuse validation must run on CPU")
    if population["role"] != "dev" or population["v13_role"] != "curve":
        raise ValueError("Use the registered DEV curve cohort")
    ds = MemoryControlDataset(args.data)
    target = read_json(args.target_round / "round.json")
    if not target or read_json(args.target_round / "progress.json", {}).get("state") != "complete":
        raise ValueError("A closed full-continuation target round is required")
    proto = comparison_protocol(ds, {"mode": "full_episode"})
    expected = dict(
        dataset_run=ds.run_id,
        observation=ds.observation_protocol,
        environment=dict(retrieval=32, scored=8, max_operations=6, gamma=1.0),
        material_budget=population["material_budget"],
        reader=proto,
        continuation_mode="full_episode",
    )
    if (
        any(target[k] != v for k, v in expected.items())
        or population["dataset_run_id"] != ds.run_id
    ):
        raise ValueError(
            "Target round, dataset, legal environment or native Reader protocol differs"
        )
    prior = read_json(donor / "registration.json")
    if (
        not prior
        or prior["role"] != "TUNE_diagnostic"
        or read_json(Path(prior["population"])) != population
        or prior["seed"] != population["seed"]
        or prior["material_budget"] != population["material_budget"]
        or prior["dataset_run_id"] != ds.run_id
        or prior["cap_per_source"] != args.per_source
        or prior["budget_tolerance"] != args.tolerance
        or prior["max_operations"] != 6
    ):
        raise ValueError("Donor capture or registered DEV acquisition differs")
    identity = target["continuation_policy_id"]
    if identity != "pi0-fixedcontext-4" and not Path(identity).is_absolute():
        raise ValueError(
            "Expected the immutable continuation checkpoint recorded by the target round"
        )
    config = dict(
        prior,
        population=str(args.population.resolve()),
        continuation=identity,
        continuation_mode="full_episode",
        utility_lambda=target["utility_lambda"],
        reader=proto,
        target_round=str(args.target_round.resolve()),
        target_collection_round=target["round"],
        target_acquisition_seed=target["seed"],
        reuse_capture=str(donor),
        diagnostic_seed_protocol="registered DEV population seed plus task ID",
    )
    output.mkdir(parents=True, exist_ok=True)
    gate = phase_directory(output)

    def work_unit():
        return nullcontext() if args.reuse_only else phase_unit(gate, "evaluate")

    with (
        (output / ".lock").open("a") as own,
        (donor / ".lock").open("r") as source_lock,
        closing(connect(ds.path)) as db,
    ):
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(source_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        registration = output / "registration.json"
        if registration.exists():
            require_equal(read_json(registration), config, "Aligned run binding differs")
        elif any((output / name).exists() for name in ("receipts", "pairs", "capture.json")):
            raise ValueError("Unbound aligned artifacts already exist")
        write_json(registration, config)
        peer_compatible = prior.get("reader") is None or prior["reader"] == proto
        receipts = AlignedReceipts(
            output / "receipts", ds, db, donor, args.reuse_only, peer_compatible
        )
        roster, counts, missing, handoff_reusable = registered_pairs(
            ds, db, population, config, donor, receipts
        )
        slots = 4 * len(roster) + counts[MUSIQUE]
        write_json(
            output / "preflight.json",
            dict(
                registered_groups=len(roster),
                logical_slots=slots,
                verified_compatible_handoffs=handoff_reusable,
                donor_reader_declaration_compatible=peer_compatible,
                unreadable_donor_receipt_files=len(receipts.unreadable_donor_files),
                unproven_handoff_slots=2 * len(roster) - handoff_reusable,
                new_request_upper_bound_given_handoffs=slots - handoff_reusable,
                absolute_new_request_upper_bound=slots,
            ),
        )
        policy = None
        bound = set()
        masked = Counter()
        for task, old in roster:
            path = output / "pairs" / f"{task['id']}.json.gz"
            if path.is_file():
                keys, masks = verify_pair(path, old, config, receipts)
                bound.update(keys)
                masked.update(masks)
                continue
            if policy is None:
                with work_unit():
                    policy, _ = load_policy(
                        ds,
                        None if identity == "pi0-fixedcontext-4" else Path(identity),
                        args.device,
                        target["utility_lambda"],
                    )
            tid = task["id"]
            seed = config["seed"] + tid
            candidate = old["candidate"]
            with work_unit():
                jobs = []
                states = []
                has_companion = task["dataset"] == MUSIQUE
                if has_companion:
                    (other,) = db.execute(
                        "SELECT * FROM experiment_tasks WHERE dataset=? AND native_group=? "
                        "AND experiment_role='dev' AND id!=?",
                        (MUSIQUE, task["native_group"], tid),
                    ).fetchall()
                    env, _, setup = cold_root(ds, db, other, config["material_budget"])
                    jobs.append(
                        TerminalJob(
                            other, env, policy, seed, f"companion_{other['id']}", setup=setup
                        )
                    )
                for root in old["states"]:
                    prefix = root["prefix"]
                    state = dict(prefix=prefix, online=root["online"], labels={})
                    states.append(state)
                    for aid in ("handoff", candidate):
                        env, menu, setup = cold_root(
                            ds, db, task, config["material_budget"], ("search", prefix)
                        )
                        require_equal(
                            json.loads(json.dumps(env.online(menu))),
                            state["online"],
                            "Aligned before changed after registration",
                        )
                        action = next(a for a in menu if a.id == aid)
                        jobs.append(
                            TerminalJob(
                                task, env, policy, seed, f"{tid}_{prefix}_{aid}", action, setup
                            )
                        )
                prepared = []
                for job in jobs:
                    if not receipts.path(job.key).is_file():
                        prepared.append(receipts.prepare(job))
                        continue
                    stored = read_gzip(receipts.path(job.key))
                    current = collect_terminal(job.session, job.policy, job.seed, job.first)
                    require_equal(
                        (
                            stored["task_id"],
                            stored["native_group_id"],
                            stored["reader_wire"],
                            stored["action_trace"],
                        ),
                        (
                            job.task["id"],
                            job.task["native_group"],
                            current["reader_wire"],
                            current["action_trace"],
                        ),
                        "Resumed terminal request or continuation path differs",
                    )
                    prepared.append((stored, False))
                results = receipts.measure_batch(jobs, prepared)
                bound.update(j.key for j in jobs)
                companion = results.pop(0) if has_companion else None
                for state, pair in zip(states, (results[:2], results[2:]), strict=True):
                    for aid, rec in zip(("handoff", candidate), pair, strict=True):
                        label = outcome_label(task["dataset"], rec, companion)
                        state["labels"][aid] = label
                        masked["quality"] += not label["quality_observed"]
                        masked["cost"] += not label["future_cost_observed"]
                write_gzip(
                    output / "pairs" / f"{tid}.json.gz",
                    dict(
                        task_id=tid,
                        native_group=task["native_group"],
                        dataset=task["dataset"],
                        split_role="dev",
                        candidate=candidate,
                        states=states,
                        material_tokens_difference=old["material_tokens_difference"],
                        continuation_policy_id=identity,
                        utility_lambda=target["utility_lambda"],
                    ),
                )
        records = [read_gzip(f) for f in receipts.directory.glob("*.json.gz")]
        require_equal({r["receipt_id"] for r in records}, bound, "Unbound diagnostic receipt")
        require_equal(
            {f.name.removesuffix(".json.gz") for f in (output / "pairs").glob("*.json.gz")},
            {str(t["id"]) for t, _ in roster},
            "Unexpected diagnostic pair file",
        )
        by_kind = defaultdict(Counter)
        charged = set()
        for item in records:
            key = item["receipt_id"]
            kind = (
                "companion"
                if key.startswith("companion_")
                else "handoff"
                if key.endswith("_handoff")
                else "read"
            )
            m = by_kind[kind]
            m["slots"] += 1
            m["exposure"] += item["feedback_exposure"]
            m["reused"] += bool(item.get("measurement_reused_from"))
            m["unknown_requests"] += item["actual_requests"] is None
            m["new_requests"] += item["actual_requests"] or 0
            m["masked_single_task_results"] += not bool(item.get("grade"))
            if item["actual_requests"]:
                chunk = range(item["ledger_before"], item["ledger_after"])
                if len(chunk) != item["actual_requests"] or charged.intersection(chunk):
                    raise ValueError("Duplicate or inconsistent aligned native ledger charge")
                charged.update(chunk)
        write_json(
            output / "capture.json",
            dict(
                groups=dict(counts),
                unmatched=dict(missing),
                state="complete",
                by_kind=dict(by_kind),
                feedback_calls=receipts.calls,
                actual_new_requests=sum(r["actual_requests"] or 0 for r in records),
                unknown_request_receipts=sum(r["actual_requests"] is None for r in records),
                logical_receipts=len(records),
                reused_responses=sum(bool(r.get("measurement_reused_from")) for r in records),
                imported_exposure=sum(
                    r["feedback_exposure"] for r in records if r.get("measurement_reused_from")
                ),
                masked_quality_labels=masked["quality"],
                masked_future_cost_labels=masked["cost"],
                new_request_upper_bound_given_handoffs=slots - handoff_reusable,
                absolute_new_request_upper_bound=slots,
                continuation=identity,
                utility_lambda=target["utility_lambda"],
            ),
        )


def collect(args):
    if bool(getattr(args, "target_round", None)) != bool(getattr(args, "reuse_capture", None)):
        raise ValueError("Register both the target continuation round and closed DEV capture")
    if getattr(args, "target_round", None):
        return collect_aligned(args)
    if getattr(args, "reuse_only", False):
        raise ValueError("Offline replay needs a registered donor and target")
    return collect_reference(args)


def score(args):
    import math

    import torch

    from milai_lab.methods.pretrained_control import PretrainedControl

    penalty = args.utility_lambda
    if penalty is not None and (not math.isfinite(penalty) or penalty < 0):
        raise ValueError("Expected a nonnegative finite penalty")
    envelope = json.loads((args.output / "registration.json").read_text())
    binding_path = args.checkpoint.parent / "run.json"
    contract = (
        json.loads(binding_path.read_text()).get("contract", {}) if binding_path.is_file() else {}
    )
    fitted_target = contract.get("target")
    matched = bool(fitted_target and fitted_target[1] == envelope["continuation"])
    if args.require_matched_continuation and not matched:
        raise ValueError(
            "The diagnostic continuation differs from this outcome checkpoint's target"
        )
    model = PretrainedControl.load(args.checkpoint, device=args.device).eval()
    measures = defaultdict(lambda: defaultdict(list))
    with torch.inference_mode():
        for file in sorted((args.output / "pairs").glob("*.json.gz")):
            row = read_gzip(file)
            stats = measures[row["dataset"]]
            measured = defaultdict(list)
            predictions = defaultdict(list)
            candidate = row["candidate"]
            for i, state in enumerate(row["states"]):
                online = state["online"]
                gains = native_deltas(state["labels"], candidate, penalty, model.cost_scale)
                for axis in gains:
                    measured[axis].append(gains[axis])
                if not gains:
                    continue
                idx = {a["id"]: k for k, a in enumerate(online["actions"])}
                read, stop = idx[candidate], idx["handoff"]
                clean_tokens = None
                for mode, donor in (
                    ("original", None),
                    ("swapped", row["states"][1 - i]["online"]["observation"]),
                ):
                    start = model.counters["input_tokens"]
                    quality, future = model.score(online, diagnostic_evidence=donor)
                    tokens = model.counters["input_tokens"] - start
                    if clean_tokens is not None and tokens != clean_tokens:
                        raise ValueError("Evidence replacement changed the controller input length")
                    clean_tokens = tokens
                    for axis, truth in gains.items():
                        heads = (
                            quality
                            if axis == "quality"
                            else model.net_from_scores(online, quality, future, penalty)
                        )
                        delta = float((heads[read].mean() - heads[stop].mean()).item())
                        prefers_read = delta > 0 or (delta == 0 and read < stop)
                        key = mode if axis == "quality" else mode + "_utility"
                        predictions[axis, mode].append(delta)
                        stats[key + "_absolute_delta_error"].append(abs(delta - truth))
                        stats[key + "_two_action_regret"].append(
                            max(0.0, truth) - (truth if prefers_read else 0.0)
                        )
                        if truth > 0:
                            stats[key + "_stop_on_profitable_read"].append(int(not prefers_read))
                        elif truth < 0:
                            stats[key + "_read_on_profitable_stop"].append(int(prefers_read))
            for axis, values in measured.items():
                if len(values) != 2:
                    continue
                flip = values[0] * values[1] < 0
                label = "" if axis == "quality" else "utility_"
                stats[label + "measured_reversal"].append(int(flip))
                if flip:
                    for mode in ("original", "swapped"):
                        stats[mode + "_" + label + "both_reversal_signs_correct"].append(
                            int(
                                all(
                                    p * y > 0
                                    for p, y in zip(predictions[axis, mode], values, strict=True)
                                )
                            )
                        )
    summary = dict(
        checkpoint=str(args.checkpoint),
        fit_target=fitted_target,
        measured_continuation=envelope["continuation"],
        matched_continuation=matched,
        cost_scale=model.cost_scale,
        utility_lambda=penalty,
        action_space="observed candidate versus HANDOFF; ties follow current menu order",
        sources={
            s: {k: {"mean": fmean(v), "n": len(v)} for k, v in axes.items()}
            for s, axes in measures.items()
        },
    )
    args.result.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    collect_p = sub.add_parser("collect")
    collect_p.add_argument("--data", type=Path, required=True)
    collect_p.add_argument("--population", type=Path, required=True)
    collect_p.add_argument("--per-source", type=int, default=12)
    collect_p.add_argument("--tolerance", type=int, default=64)
    collect_p.add_argument("--target-round", type=Path)
    collect_p.add_argument("--reuse-capture", type=Path)
    collect_p.add_argument("--device", default="cpu")
    collect_p.add_argument(
        "--reuse-only", action="store_true", help="CPU replay with HTTP disabled"
    )
    score_p = sub.add_parser("score")
    score_p.add_argument("--checkpoint", type=Path, required=True)
    score_p.add_argument("--device", default="cuda")
    score_p.add_argument("--utility-lambda", type=float, help="Add calibrated net-utility regret")
    score_p.add_argument("--require-matched-continuation", action="store_true")
    score_p.add_argument("--result", type=Path, required=True)
    args = p.parse_args()
    if args.command == "collect":
        collect(args)
    else:
        score(args)
