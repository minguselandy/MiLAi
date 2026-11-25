"""Register two fresh native-group comparisons from closed DEV fits and read their results."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from statistics import fmean, stdev

import numpy as np

from dispatch_memory_control_v13 import dispatch, order_contract, schedule
from milai_lab.datasets.memory_control_store import connect, get_meta
from milai_lab.runners.memory_control_confirmation import (
    InsufficientDevGroups,
    confirmation_capacity,
    full_tune_parent,
    plan_confirmation_power,
    power_dev_records,
)
from milai_lab.runners.memory_control_episode import (
    checkpoint_contract,
    episode_population,
    train_sources_disjoint,
)
from milai_lab.scorers.memory_control_episode_metrics import (
    RESOURCE_AXES,
    SOURCES,
    centered_bootstrap_pvalue,
    holm_adjust,
    input_result,
    paired_comparison,
    paired_inline_latency,
    percentiles,
)
from report_memory_control_v13_deployment import packet_measurements, summarize_run

SEEDS = {11, 29, 47}
COST_FIELDS = {"local_gpu_seconds": "total_local_gpu_seconds", "currency": "total_charged_currency"}
COMPONENTS = ["controller", "reader", "retrieval", "preprocessing"]
FAMILY_ALPHA = 0.025


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prior_v13_runs(data, role_audit, explicit=()):
    """Reconcile any already-issued packets in this experiment before a new registration."""
    root = role_audit.parent
    if root.name == "fresh-sources":
        root = root.parent
    with closing(connect(data)) as db:
        release = get_meta(db, "run_id")
    runs = set(explicit)
    for path in root.rglob("protocol.json"):
        if (
            not (path.parent / "episodes").is_dir()
            and not (path.parent / "episode-archive.json").is_file()
        ):
            continue
        population = read(path).get("population", {})
        if (
            isinstance(population, dict)
            and population.get("role") == "confirm"
            and population.get("dataset_run_id") == release
        ):
            runs.add(path.parent)
    return sorted(runs)


def checked_capacity(data, role_audit, packet_audit, target, seed, prior=()):
    role, packets = read(role_audit), read(packet_audit)
    with closing(connect(data)) as db:
        if not get_meta(db, "confirmation_only") or get_meta(db, "run_id") != role["run_id"]:
            raise ValueError("Mismatch between the fresh release and its role audit")
        full_groups = dict(
            db.execute(
                "SELECT dataset,count(*) FROM experiment_groups "
                "WHERE eligible_fresh_confirmation=1 GROUP BY dataset"
            )
        )
        if full_groups != role["eligible_groups"]:
            raise ValueError("Registered group capacity changed")
    if (
        packets["reader_calls"]
        or packets["fitting_states"]
        or set(packets["cold_prepare_sources"]) != set(SOURCES)
        or any(packets["current_release_group_overlap"].values())
        or any(packets["physical_native_outcome_overlap"].values())
    ):
        raise ValueError("Fresh source overlap or cold preparation failed")
    if packets.get("dataset_run_id") != role["run_id"]:
        raise ValueError("Packet ledger check belongs to a different fresh release")
    return confirmation_capacity(data, target, seed, list(prior))


def tune_support(selection, spec):
    if not spec.get("tune_subset"):
        return None, None
    path = (selection.parent / spec["tune_subset"]).resolve()
    roster = read(path)
    full_tune_parent(roster)
    return path, roster


def projected_endpoints(protocol, packets):
    """Calculate native quality bounds and per-task resource coverage on exactly the common rows."""
    pop = protocol["population"]
    measurement = packet_measurements(protocol["arm"], pop, packets, None)
    excluded = pop.get("predeclared_unevaluable_tasks", {})
    groups = defaultdict(set)
    for task in pop["tasks"]:
        if str(task["task_id"]) not in excluded:
            groups[task["dataset"]].add(task["native_group"])
    axes = {}
    for key in dict.fromkeys((*RESOURCE_AXES, "controller_gpu_ms", *COST_FIELDS.values())):
        values = [
            v
            for row in packets.values()
            if type(v := row.get("costs", {}).get(key)) in (int, float)
            and math.isfinite(v)
            and v >= 0
        ]
        axes[key] = {
            "measured": len(values),
            "missing": len(packets) - len(values),
            "known_sum": sum(values),
            "total_if_complete": sum(values) if len(values) == len(packets) else None,
            "p50": percentiles(values, 0.5) if values else None,
            "p95": percentiles(values, 0.95) if values else None,
        }
    return {
        "registered_tasks": len(packets),
        "groups": sum(len(g) for g in groups.values()),
        "eligible_groups_by_source": {s: len(g) for s, g in groups.items()},
        "native": measurement["native"],
        "macro_range_points": measurement["macro_range_points"],
        "per_task_costs": axes,
        "new_reader_calls_for_projection": 0,
        "resource_scope": (
            "Existing per-task measurements on the selected native groups. "
            "Whole-window timings and physical charges are not prorated."
        ),
    }


def fit_sensitivity(projections):
    lower = [v["macro_range_points"][0] for v in projections]
    upper = [v["macro_range_points"][1] for v in projections]
    fully_observed = all(not src["unknown"] for v in projections for src in v["native"].values())
    costs = {}
    for key in projections[0]["per_task_costs"]:
        totals = [v["per_task_costs"][key]["total_if_complete"] for v in projections]
        known = [n for n in totals if n is not None]
        costs[key] = {
            "measured_fits": len(known),
            "fits": len(totals),
            "range_if_complete": [min(known), max(known)] if len(known) == len(totals) else None,
        }
    return {
        "fit_seeds": [v["seed"] for v in projections],
        "macro_bounds_envelope": [min(lower), max(upper)],
        "quality_points_sample_sd_if_observed": stdev(lower)
        if fully_observed and len(lower) > 1
        else None,
        "cost_totals_across_fits": costs,
    }


def validate_dev_family(paths, *, final=False, tune_subset=None):
    common_roster = tune_subset
    full_roster = full_tune_parent(tune_subset)
    if len(paths) not in ((3,) if final else (1, 3)):
        raise ValueError("Use three final fits and a fixed or three-fit comparator")
    arms, bounds, backbones, projections = [], [], set(), []
    selected = None
    family_contract = None
    family_population = None
    for path in paths:
        protocol = read(path / "protocol.json")
        pop, arm = protocol["population"], protocol["arm"]
        if (
            read(path / "run.json")["status"] != "COMPLETED"
            or pop["role"] != "dev"
            or pop.get("v13_role") != "tune"
            or pop["material_budget"] != 2048
            or arm.get("environment") != "qrag_milai_v13"
        ):
            raise ValueError("Final selection requires closed natural 2,048-token V13 TUNE runs")
        if common_roster is None and family_population is not None and family_population != pop:
            raise ValueError("Different fit-evaluation populations require an explicit TUNE subset")
        family_population = pop
        recipe = {k: v for k, v in arm.items() if k not in {"checkpoint", "name", "seed"}}
        if arm["policy"] in {"pretrained_checkpoint", "qrag_milai"}:
            if len(paths) == 1 and arm.get("seed") != 11:
                raise ValueError(
                    "A singleton learned ranking comparator must be its seed-11 deployment"
                )
            ckpt = Path(arm["checkpoint"])
            contract = (
                checkpoint_contract(ckpt)
                if arm["policy"] == "pretrained_checkpoint"
                else read(ckpt / "training.json")
            )
            if (
                not (ckpt / "control.pt").is_file()
                or contract["seed"] != arm["seed"]
                or not contract["fitted_groups"]
                or contract.get("probe")
            ):
                raise ValueError("Fit seed or measured checkpoint provenance differs")
            if final and contract["supervision_mode"] not in {"paired", "direct"}:
                raise ValueError("Final seed fits must be trained on actual terminal outcomes")
            backbones.add(str(Path(read(ckpt / "controller.json")["backbone"]).resolve()))
            recipe.update(objective=contract["supervision_mode"])
            if arm["policy"] == "pretrained_checkpoint":
                recipe.update(
                    {
                        k: contract[k]
                        for k in ("input", "effective_batch", "epochs", "lr", "pair_weight")
                    }
                )
        elif final:
            raise ValueError("Final family needs actual seed-specific outcome fits")
        elif arm["policy"] == "gte_relevance":
            backbones.add(str(Path(arm["backbone"]).resolve()))
        if family_contract is not None and recipe != family_contract:
            raise ValueError("Fit-seed family differs in method, data or deployed readout")
        family_contract = recipe
        basis = len(paths) == 1 or arm.get("seed") == 11
        if basis and (
            pop.get("subset_kind") is not None or (full_roster is not None and pop != full_roster)
        ):
            raise ValueError(
                "Baseline ranking requires the full parent TUNE run for fit 11 or fixed policy"
            )
        if common_roster is not None and pop not in (full_roster, common_roster):
            raise ValueError("A fit readout uses neither its frozen subset nor its parent TUNE")
        original = summarize_run(path) if basis or common_roster is None else None
        if basis:
            selected = {
                "run": str(path),
                "seed": arm.get("seed"),
                "tasks": len(pop["tasks"]),
                "groups": original["registered_groups"],
                "macro_range_points": original["macro_range_points"],
            }
        if common_roster is None:
            bounds.append(original["macro_range_points"])
        else:
            proto, records = power_dev_records(path, common_roster)
            measured = projected_endpoints(proto, records)
            projections.append(
                {
                    **measured,
                    "seed": arm.get("seed"),
                    "input_tasks": len(pop["tasks"]),
                    "run": str(path),
                }
            )
            bounds.append(measured["macro_range_points"])
        arms.append(arm)
    if len(arms) == 3 and {a.get("seed") for a in arms} != SEEDS:
        raise ValueError("Actual fitted seeds 11, 29 and 47 are required")
    if len(backbones) > 1:
        raise ValueError("Seed family changed backbone")
    return {
        "arms": arms,
        "dev_runs": list(map(str, paths)),
        "quality_bounds_points": bounds,
        "selection_score": selected["macro_range_points"][0],
        "selection_basis": selected,
        **(
            {
                "common_fit_support": projections,
                "fit_seed_sensitivity": fit_sensitivity(projections),
            }
            if projections
            else {}
        ),
        "backbone": next(iter(backbones), None),
    }


def select_peer(families, candidates, final, same):
    if not candidates or final in candidates:
        raise ValueError("Predeclare competing control families excluding the final method")
    valid = [
        k
        for k in candidates
        if k in families and (not same or families[k]["backbone"] == families[final]["backbone"])
    ]

    def signature(family):
        return sorted(
            json.dumps({k: v for k, v in a.items() if k != "name"}, sort_keys=True)
            for a in families[family]["arms"]
        )

    if any(signature(k) == signature(final) for k in valid):
        raise ValueError("A comparator aliases the final deployed method")
    if len(valid) != len(candidates) or len(set(candidates)) != len(candidates):
        raise ValueError("Candidate set changed or includes an unmatched backbone")
    return min(valid, key=lambda k: (-families[k]["selection_score"], k))


def cost_data(paths, field, *, dev_roster=None):
    data = []
    for path in paths:
        protocol, rows = (
            power_dev_records(path, dev_roster) if dev_roster is not None else input_result(path)
        )
        contract = protocol["comparison"].get("total_cost")
        costs = {tid: row.get("costs", {}).get(field) for tid, row in rows.items()}
        unit = next(k for k, v in COST_FIELDS.items() if v == field)
        if (
            not contract
            or contract.get("unit") != unit
            or (unit == "currency" and not contract.get("currency_code"))
            or set(contract.get("includes", [])) != set(COMPONENTS)
            or not contract.get("measurement_protocol")
            or len(costs) != len(protocol["population"]["tasks"])
            or any(
                type(c) not in (int, float) or not math.isfinite(c) or c < 0 for c in costs.values()
            )
        ):
            return None
        data.append((contract, costs))
    if any(c != data[0][0] for c, _ in data):
        raise ValueError("Total cost scope, currency or meter changed")
    return data


def cap_candidate(data, audits, limit, arms, seed, prior):
    target = limit // arms
    while target > 0:
        cap = checked_capacity(data, *audits, target, seed, prior)
        if cap["actual_tasks"] * arms <= limit:
            return cap
        target -= max(1, cap["actual_tasks"] - limit // arms)
    raise ValueError("Reader cap does not accommodate three-source whole groups")


def register(args):
    if min(
        args.draws,
        args.power_repeats,
        args.bootstrap_repeats,
        args.quality_mde,
    ) <= 0 or (args.reader_cap is not None and args.reader_cap <= 0):
        raise ValueError("Positive simulation counts, cap and meaningful effect required")
    spec = read(args.selection)
    final = spec["final"]
    subset_path, common_roster = tune_support(args.selection, spec)
    families = {
        k: validate_dev_family(
            [Path(p).resolve() for p in v],
            final=k == final,
            tune_subset=common_roster,
        )
        for k, v in spec["families"].items()
    }
    selection_protocols = [
        read(Path(info["selection_basis"]["run"]) / "protocol.json") for info in families.values()
    ]
    if any(
        p["population"] != selection_protocols[0]["population"]
        or p["comparison"] != selection_protocols[0]["comparison"]
        for p in selection_protocols[1:]
    ):
        raise ValueError(
            "All competing full TUNE ranking inputs must share their roster and Reader"
        )
    peers = {
        k: select_peer(families, spec[k], final, k == "same_backbone")
        for k in ("same_backbone", "practical")
    }
    chosen = [final, *dict.fromkeys(peers.values())]
    arms = []
    for k in chosen:
        for a in families[k]["arms"]:
            if a not in arms:
                arms.append(a)
    if len({a["name"] for a in arms}) != len(arms):
        raise ValueError("Confirmation arm names must identify unique deployed configurations")
    paths = {k: [Path(p) for p in families[k]["dev_runs"]] for k in chosen}
    comparison_runs = [p for runs in paths.values() for p in runs]
    leader_protocol = read(comparison_runs[0] / "protocol.json")
    for path in comparison_runs[1:]:
        proto = read(path / "protocol.json")
        if (
            common_roster is None and proto["population"] != leader_protocol["population"]
        ) or proto["comparison"] != leader_protocol["comparison"]:
            raise ValueError("Selected DEV evaluations must share the task allocation and Reader")
    field = COST_FIELDS[args.cost_unit]
    measured_total = (
        cost_data([*paths[final], *paths[peers["practical"]]], field, dev_roster=common_roster)
        is not None
    )
    audits = (args.role_audit, args.packet_audit)
    prior = prior_v13_runs(args.data, args.role_audit, getattr(args, "prior_run", ()))
    reader_cap = args.reader_cap
    if reader_cap is None:
        inventory = checked_capacity(args.data, *audits, None, args.seed, prior)
        reader_cap = inventory["actual_tasks"] * len(arms)
    capacities = []
    for fraction in (0.25, 0.5, 1.0):
        limit = int(reader_cap * fraction)
        if limit < 3 * len(arms):
            continue
        try:
            cap = cap_candidate(args.data, audits, limit, len(arms), args.seed, prior)
        except ValueError as exc:
            if "accommodate" in str(exc) or "every native source" in str(exc):
                continue
            raise
        if capacities and cap["selected_groups"] == capacities[-1]["capacity"]["selected_groups"]:
            continue
        projections = {}
        for key, peer in peers.items():
            use_cost = key == "practical" and measured_total
            try:
                power = plan_confirmation_power(
                    cap,
                    paths[final],
                    paths[peer],
                    draws=args.draws,
                    repeats=args.power_repeats,
                    primary_comparisons=2,
                    holm_plan=True,
                    analysis_seed=args.seed + 1,
                    cost_field=field if use_cost else "reader_input_tokens",
                    minimum_quality_effect=args.quality_mde,
                    mask_unknown_quality=True,
                    savings_null=0.15 if use_cost else 0.0,
                    total_workload_cost=use_cost,
                    tune_subset=common_roster,
                )
            except InsufficientDevGroups as exc:
                projections[key] = {
                    "superiority_power_at_mde": None,
                    "joint_engineering_power_at_zero_quality_loss_20pct_true_savings": None,
                    "unidentified_reason": str(exc),
                }
                continue
            projections[key] = {
                "dev_groups_used": power["source_groups_used"],
                "dev_groups_available": power["source_groups_available"],
                "superiority_power_at_mde": power["quality_power_at_minimum_effect"],
                "dev_quality_effects_by_fit": power["conservative_dev_design"][
                    "seed_quality_delta_points"
                ],
                "joint_engineering_power_at_zero_quality_loss_20pct_true_savings": power[
                    "scenarios"
                ][0]["joint_pass_probability"]
                if use_cost
                else None,
                "dev_resource_filter": power["cost_field"],
            }
        capacities.append({"capacity": cap, "projections": projections})
        joint = projections["practical"][
            "joint_engineering_power_at_zero_quality_loss_20pct_true_savings"
        ]
        if (
            (projections["same_backbone"]["superiority_power_at_mde"] or 0.0) >= 0.8
            and joint is not None
            and joint >= 0.8
        ):
            break
    if not capacities:
        raise ValueError("Reader budget has no complete three-source allocation")
    cap = capacities[-1]["capacity"]
    population = episode_population(
        args.data,
        role="confirm",
        allowed_arms=arms,
        target_tasks=cap["target_tasks"],
        seed=args.seed,
        excluded_groups={tuple(g) for g in cap["excluded_exposed_native_groups"]},
    )
    actual = Counter((r["dataset"], r["native_group"]) for r in population["tasks"])
    if actual != {
        (s, g["native_group"]): g["tasks"] for s, gg in cap["selected_groups"].items() for g in gg
    }:
        raise ValueError("Fresh group allocation differs from power planning")
    for arm in arms:
        train_sources_disjoint(arm, population["tasks"])
    # Native inference keeps failed requests unobserved. Resource statistics retain their costs.
    population.update(
        v13_role="confirm_fresh",
        terminal_quality_failures=None,
        confirmation_primary_comparisons=2,
        bootstrap_repeats=args.bootstrap_repeats,
    )
    comparison_slots = {
        key: len({a["name"] for k in (final, peer) for a in families[k]["arms"]})
        * len(population["tasks"])
        for key, peer in peers.items()
    }
    order = order_contract(arms, getattr(args, "window_tasks", 16), args.seed + 17)
    population["v13_dispatch"] = order
    registration = {
        "dispatch": order,
        "comparison_first_slots": comparison_slots,
        "families": families,
        "final": final,
        "peers": peers,
        "dev_selection": spec,
        "selection_rule": (
            "Highest lower-bound native macro on the common full TUNE "
            "seed-11 or fixed deployment run"
        ),
        "tune_subset": str(subset_path) if subset_path else None,
        "fit_repeat_tasks": len(common_roster["tasks"])
        if common_roster is not None
        else len(leader_protocol["population"]["tasks"]),
        "quality_mde_points": args.quality_mde,
        "family_one_sided_alpha": FAMILY_ALPHA,
        "quality_noninferiority_points": 1,
        "required_total_savings": 0.15,
        "cost_aggregation": "actual_registered_workload_total_averaged_across_fit_replicates",
        "cost_field": field,
        "cost_unit": args.cost_unit,
        "required_components": COMPONENTS,
        "dev_total_cost_available": measured_total,
        "capacity_power_grid": capacities,
        "simulated_draws": args.draws,
        "power_repeats": args.power_repeats,
        "analysis_seed": args.seed + 1,
        "max_reader_calls": reader_cap,
        "reader_cap_source": (
            "remaining_fresh_tasks_times_unique_deployments"
            if args.reader_cap is None
            else "explicit"
        ),
        "reserved_first_calls": len(arms) * len(population["tasks"]),
        "power_policy": (
            "first grid point with joint engineering and quality power >=0.80, "
            "otherwise largest tested capacity"
        ),
        "role_audit": str(args.role_audit.resolve()),
        "packet_audit": str(args.packet_audit.resolve()),
        "run_directories": {a["name"]: f"arm-{i + 1:02d}" for i, a in enumerate(arms)},
    }
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        out = Path(tmp) / "registration"
        out.mkdir()
        save(out / "population.json", population)
        save(out / "registration.json", registration)
        save(out / "dispatch-schedule.json", schedule(order, len(population["tasks"])))
        for arm in arms:
            save(out / (registration["run_directories"][arm["name"]] + ".json"), arm)
        out.rename(args.output)


def measured_savings(pop, policy_costs, baseline_costs, repeats, seed):
    """Sum measured deployment costs for the registered workload, preserving source task counts."""
    groups = defaultdict(lambda: defaultdict(list))
    for task in pop["tasks"]:
        groups[task["dataset"]][task["native_group"]].append(task["task_id"])
    rng = np.random.default_rng(seed)
    observed = np.zeros(2)
    balanced = np.zeros(2)
    source_costs = {}
    samples = np.zeros((repeats, 2))
    for source in SOURCES:
        clusters = []
        for ids in groups[source].values():
            costs = [
                fmean(sum(r[i] for i in ids) for r in runs)
                for runs in (policy_costs, baseline_costs)
            ]
            clusters.append([*costs, len(ids)])
        x = np.array(clusters, float)
        totals = x.sum(axis=0)
        observed += totals[:2]
        balanced += totals[:2] / totals[2]
        source_costs[source] = {
            "policy_total_mean_across_fits": float(totals[0]),
            "baseline_total_mean_across_fits": float(totals[1]),
            "registered_tasks": int(totals[2]),
        }
        draws = rng.integers(0, len(x), (repeats, len(x)))
        sums = x[draws].sum(axis=1)
        samples += totals[2] * sums[:, :2] / sums[:, 2, None]
    if observed[1] <= 0 or np.any(samples[:, 1] <= 0):
        return None
    savings = 1 - observed[0] / observed[1]
    draws = 1 - samples[:, 0] / samples[:, 1]
    return {
        "savings": float(savings),
        "policy_total_mean_across_fits": float(observed[0]),
        "baseline_total_mean_across_fits": float(observed[1]),
        "by_source": source_costs,
        "equal_source_weighted_savings_sensitivity": float(1 - balanced[0] / balanced[1]),
        "interval_95": np.quantile(draws, [0.025, 0.975]).tolist(),
        "p_savings_above_15pct": centered_bootstrap_pvalue(draws, savings, 0.15),
    }


def readout(args):
    reg, pop = [read(args.registration / p) for p in ("registration.json", "population.json")]
    schedule_status = None
    if pop.get("v13_dispatch"):
        schedule_status = read(args.runs / "dispatch-summary.json")
        if schedule_status["status"] != "COMPLETED":
            raise ValueError("Complete the frozen interleaved dispatch before formal readout")
    by_arm = {}
    resources = {}
    for arm in pop["arms"]:
        name = arm["name"]
        root = args.runs / reg["run_directories"][name]
        proto = read(root / "protocol.json")
        if proto["population"] != pop or proto["arm"] != arm:
            raise ValueError("Confirmation readout differs from the frozen registration")
        resources[name] = summarize_run(root)
        by_arm[name] = root
    actual_calls = sum(r["actual_reader_calls"] for r in resources.values())
    if actual_calls > reg["max_reader_calls"]:
        raise ValueError("Confirmation Reader call cap exceeded")

    def runs(family):
        return [by_arm[a["name"]] for a in reg["families"][family]["arms"]]

    final = runs(reg["final"])
    metrics = {}
    raw = {}
    total = None
    for key in ("same_backbone", "practical"):
        peer = runs(reg["peers"][key])
        m = paired_comparison(
            final,
            peer,
            repeats=pop["bootstrap_repeats"],
            seed=reg["analysis_seed"],
            primary_comparisons=2,
        )
        bounds = []
        for family in (reg["final"], reg["peers"][key]):
            group = [
                resources[a["name"]]["macro_range_points"] for a in reg["families"][family]["arms"]
            ]
            bounds.append([fmean(r[i] for r in group) for i in (0, 1)])
        metrics[key] = {
            k: m[k]
            for k in (
                "quality_delta_points",
                "quality_interval_95",
                "familywise_quality_interval",
                "source_strata",
                "independent_groups",
                "paired_quality_complete",
                "paired_reader_input_complete",
                "reader_input_token_savings",
                "token_savings_interval_95",
                "by_seed",
                "seed_spread",
                "seed_and_group_sensitivity",
            )
            if k in m
        }
        metrics[key]["missing_quality_bounds_points"] = [
            bounds[0][0] - bounds[1][1],
            bounds[0][1] - bounds[1][0],
        ]
        p = m["one_sided_centered_pvalues"]
        if key == "same_backbone":
            raw[key] = p["quality_superiority"]
        else:
            setup = {
                p: resources[read(p / "protocol.json")["arm"]["name"]]["policy_load_ms_per_attempt"]
                for p in [*final, *peer]
            }

            def latency(models, reference, offsets=setup):
                return paired_inline_latency(
                    models,
                    reference,
                    repeats=pop["bootstrap_repeats"],
                    seed=reg["analysis_seed"],
                    policy_load_ms_per_task=offsets,
                )

            if len(peer) == 1:
                metrics[key]["end_to_end_latency"] = latency(final, peer[0])
            else:
                by_seed = {read(p / "protocol.json")["arm"]["seed"]: p for p in peer}
                metrics[key]["end_to_end_latency_by_fit"] = {
                    str(s): latency([p], by_seed[s])
                    for p in final
                    if (s := read(p / "protocol.json")["arm"]["seed"]) is not None
                }
            cost = cost_data([*final, *peer], reg["cost_field"])
            if cost is not None:
                total = measured_savings(
                    pop,
                    [r for _, r in cost[: len(final)]],
                    [r for _, r in cost[len(final) :]],
                    pop["bootstrap_repeats"],
                    reg["analysis_seed"],
                )
            raw[key] = (
                max(p["quality_noninferiority"], total["p_savings_above_15pct"])
                if p["quality_noninferiority"] is not None and total
                else None
            )
    adjusted = holm_adjust(raw)
    findings = {}
    for key, pval in adjusted.items():
        findings[key] = (
            "unidentified"
            if pval is None
            else "supported"
            if pval <= reg["family_one_sided_alpha"]
            else "not_supported"
        )
    result = {
        "native_contrasts": metrics,
        "measured_total_cost": total,
        "cost_unit": reg["cost_unit"],
        "unadjusted_one_sided_p": raw,
        "holm_adjusted_p": adjusted,
        "findings": findings,
        "primary_definitions": {
            "same_backbone": "native macro superiority over frozen same-backbone control",
            "practical": "native macro delta > -1 point and measured total cost savings > 15%",
        },
        "inference": (
            "Stratified paired native-group bootstrap conditional on fit seeds 11/29/47. "
            "The fit-seed bootstrap is a separate sensitivity result."
        ),
        "earlier_sampling_and_reader_variation": "Not estimated by these fit-seed comparisons",
        "observed_resources_by_arm": resources,
        "unique_reader_calls": (
            None
            if any(r["reader_charge_lower_bound_only"] for r in resources.values())
            else actual_calls
        ),
        "known_reader_calls": actual_calls,
        "interleaved_dispatch": schedule_status,
        "registered_maximum_calls": reg["max_reader_calls"],
    }
    save(args.output, result)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    capacity = sub.add_parser("capacity")
    reg = sub.add_parser("register")
    for p in (capacity, reg):
        p.add_argument("--data", type=Path, required=True)
        p.add_argument("--prior-run", type=Path, action="append", default=[])
        p.add_argument("--role-audit", type=Path, required=True)
        p.add_argument("--packet-audit", type=Path, required=True)
        p.add_argument("--seed", type=int, default=20261125)
        p.add_argument("--output", type=Path, required=True)
    capacity.add_argument(
        "--target-tasks", type=int, help="Defaults to all remaining eligible tasks"
    )
    reg.add_argument("--selection", type=Path, required=True)
    reg.add_argument(
        "--reader-cap",
        type=int,
        help="Defaults to remaining fresh tasks times unique deployed arms",
    )
    reg.add_argument("--cost-unit", choices=COST_FIELDS, default="local_gpu_seconds")
    reg.add_argument("--window-tasks", type=int, default=16)
    reg.add_argument("--quality-mde", type=float, default=1.0)
    reg.add_argument("--draws", type=int, default=250)
    reg.add_argument("--power-repeats", type=int, default=500)
    reg.add_argument("--bootstrap-repeats", type=int, default=5000)
    dispatch_cli = sub.add_parser("dispatch")
    dispatch_cli.add_argument("--registration", type=Path, required=True)
    dispatch_cli.add_argument("--runs", type=Path, required=True)
    dispatch_cli.add_argument("--device", default="cuda")
    dispatch_cli.add_argument("--limit-windows", type=int)
    result = sub.add_parser("readout")
    result.add_argument("--registration", type=Path, required=True)
    result.add_argument("--runs", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.command == "capacity":
        save(
            args.output,
            checked_capacity(
                args.data,
                args.role_audit,
                args.packet_audit,
                args.target_tasks,
                args.seed,
                prior_v13_runs(args.data, args.role_audit, args.prior_run),
            ),
        )
    elif args.command == "register":
        register(args)
    elif args.command == "dispatch":
        if args.limit_windows is not None and args.limit_windows < 1:
            cli.error("--limit-windows must be positive")
        print(json.dumps(dispatch(args), indent=2))
    else:
        readout(args)
