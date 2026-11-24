"""Freeze development-selected 24k policies and repeat only the matching fits on immutable data."""

from __future__ import annotations

import argparse
import fcntl
from collections import Counter, defaultdict
from pathlib import Path

from calibrate_memory_control_v13_baselines import checkpoint_grid
from confirm_memory_control_v13 import select_peer, validate_dev_family
from milai_lab.runners.memory_control_episode import allocate_native_groups
from milai_lab.runners.v13_phase import phase_directory, phase_unit
from report_memory_control_v13_project_cost import aggregate
from run_memory_control_v13_rounds import json_file, publish, run
from settle_memory_control_v13_round import invoke, point_path

LEARNED = ("DQ", "PQ-U", "PQ-A")


def roster(root, acquisition_seed):
    paths = {}
    for label in (*LEARNED, "QR", "rule", "gte"):
        if label in {"rule", "gte"}:
            key = "gte-batch8" if label == "gte" else label
        else:
            point = json_file(point_path(root, label, acquisition_seed, 24000))
            if point["usage"]["exposure"] != 24000 or point["method"] != label:
                raise ValueError(f"The {label} candidate did not use the registered 24k exposure")
            key, _ = checkpoint_grid({}, Path(point["deployment"]["arm"]["checkpoint"]))
        selected = json_file(root / "baselines" / (key + "-selection.json"))["selected"]
        registration = json_file(root / "baselines" / (key + "-registration.json"))
        allowed = {arm["name"]: arm for arm in registration["candidates"]}
        paths[label] = root / "baselines/tune" / selected
        protocol = json_file(paths[label] / "protocol.json")
        if protocol["arm"] != allowed.get(selected):
            raise ValueError("TUNE arm differs from its registered calibration winner")
        if (
            label in (*LEARNED, "QR")
            and Path(protocol["arm"]["checkpoint"]).resolve()
            != Path(point["deployment"]["arm"]["checkpoint"]).resolve()
        ):
            raise ValueError("Calibration readout belongs to another checkpoint")
    return paths


def freeze(root, seed):
    paths = roster(root, seed)
    families = {k: validate_dev_family([v]) for k, v in paths.items()}
    protocols = [json_file(v / "protocol.json") for v in paths.values()]
    populations = [p["population"] for p in protocols]
    if any(p != populations[0] for p in populations[1:]) or any(
        p["comparison"] != protocols[0]["comparison"] for p in protocols[1:]
    ):
        raise ValueError("Candidate scores came from different development tasks")
    final = max(LEARNED, key=lambda k: families[k]["selection_score"])
    same = select_peer(families, [k for k in ("gte", *LEARNED) if k != final], final, True)
    practical = select_peer(families, ["rule", "gte", "QR"], final, False)
    selection = {
        "final": final,
        "same_backbone": same,
        "practical": practical,
        "fit_seed_for_selection": seed,
        "rule": "Highest native macro lower bound on common TUNE. "
        "Exact ties between final methods prefer DQ, then PQ-U, then PQ-A.",
        "families": families,
        "tune_tasks": len(populations[0]["tasks"]),
        "fresh_requests": 0,
    }
    publish(root / "s4" / "frozen-candidates.json", selection)
    return selection, paths


def evidence_fit(root, initial, seed):
    parent = json_file(initial.parent / "run.json")
    base = parent["contract"]
    if parent["status"] != "completed" or not parent["reload_scores_equal"] or base["probe"]:
        raise ValueError("Need the verified complete initial evidence fit")
    out = root / "weights" / f"s1-f{seed}"
    metrics = root / "gte" / f"s1-f{seed}"
    comparable = (
        "input",
        "full_population",
        "observation_protocol",
        "selected_per_epoch",
        "epochs",
        "object_batch",
        "effective_batch",
        "lr",
        "supervision_mode",
        "mixed_precision",
        "source_inventory",
        "updates",
        "source_weights",
    )
    if (out / "run.json").exists():
        previous = json_file(out / "run.json")
        contract = previous["contract"]
        if contract["seed"] != seed or any(contract[k] != base[k] for k in comparable):
            raise ValueError("Existing evidence fit has a different frozen recipe or inventory")
        if (
            previous["status"] == "completed"
            and previous["reload_scores_equal"]
            and (out / "checkpoint/control.pt").is_file()
            and (metrics / "run.json").is_file()
            and previous == json_file(metrics / "run.json")
        ):
            return out / "checkpoint"
    run(
        "pretrained_control_train",
        "--objective",
        "evidence",
        "--data",
        base["input"],
        "--backbone",
        json_file(initial / "controller.json")["backbone"],
        "--output",
        out,
        "--metrics",
        metrics,
        "--epochs",
        base["epochs"],
        "--lr",
        base["lr"],
        "--object-batch",
        base["object_batch"],
        "--batch",
        base["effective_batch"],
        "--seed",
        seed,
    )
    result = json_file(out / "run.json")
    if (
        result["status"] != "completed"
        or not result["reload_scores_equal"]
        or any(result["contract"][k] != base[k] for k in comparable)
    ):
        raise ValueError("Repeat changed the initial fit recipe or input")
    return out / "checkpoint"


def whole_group_roster(parent, cap, selection_seed, parent_path):
    """Choose the largest feasible target in the seeded whole-group allocation sequence."""
    if cap >= len(parent["tasks"]):
        return parent
    sizes = defaultdict(Counter)
    for t in parent["tasks"]:
        sizes[t["dataset"]][t["native_group"]] += 1
    for target in range(cap, 0, -1):
        chosen = set(allocate_native_groups(sizes, target, selection_seed))
        count = sum(sizes[src][group] for src, group in chosen)
        if count <= cap and {src for src, _ in chosen} == set(sizes):
            break
    else:
        raise ValueError("Budget cannot admit all three sources as intact native groups")
    tasks = [t for t in parent["tasks"] if (t["dataset"], t["native_group"]) in chosen]
    ids = {str(t["task_id"]) for t in tasks}
    return dict(
        parent,
        tasks=tasks,
        target_tasks=target,
        task_counts=dict(Counter(t["dataset"] for t in tasks)),
        predeclared_unevaluable_tasks={
            k: v for k, v in parent.get("predeclared_unevaluable_tasks", {}).items() if k in ids
        },
        subset_kind="frozen_fit_repeat",
        parent_tune_roster=str(parent_path.resolve()),
        selection_seed=selection_seed,
        selection="budgeted_whole_native_group_DEV",
    )


def repeat_population(root, learned, chosen):
    parent_path = root / "rosters/tune-2048.json"
    curve = json_file(root / "rosters/curve-2048.json")
    record_path = root / "s4" / "repeat-allocation.json"
    nfits = 2 * len(learned)
    if record_path.exists():
        record = json_file(record_path)
        if record["selected_families"] != chosen or record["new_dev_readout_arms"] != nfits:
            raise ValueError("Previously frozen fit-repeat allocation belongs to different arms")
    else:
        physical = aggregate(root)
        independent = {
            str(Path(p["deployment"]["path"]).resolve())
            for f in (root / "curve-points").glob("*.json")
            for p in (json_file(f),)
            if p["acquisition_seed"] != 11
        }
        spent = extra = 0
        for r in physical["runs"]:
            directory = root / r["path"]
            if r["kind"] == "readout":
                protocol = json_file(directory / "protocol.json")
                development = protocol["population"]["role"] == "dev"
            else:
                declaration = directory / "registration.json"
                development = (
                    declaration.is_file()
                    and json_file(declaration).get("role") == "TUNE_diagnostic"
                )
            if development:
                billed = r.get("settled_new_requests", 0) + r.get("unknown_charge_records", 0)
                if str(directory.resolve()) in independent:
                    extra += billed
                else:
                    spent += billed
        budget = 12000
        capacity = (budget - spent) // nfits
        # Preserve at least the native curve cohort's order of sample size if
        # exceptional prior failures use up the suggested development allocation.
        cap = max(len(curve["tasks"]), capacity)
        parent = json_file(parent_path)
        roster = whole_group_roster(parent, cap, 20261125, parent_path)
        record = dict(
            selected_families=chosen,
            suggested_development_calls=budget,
            new_dev_readout_arms=nfits,
            development_calls_already_charged=spent,
            independent_acquisition_dev_calls_separate=extra,
            projected_development_upper=spent + nfits * len(roster["tasks"]),
            population=roster,
        )
        publish(record_path, record)
    path = root / "s4" / "repeat-population.json"
    publish(path, record["population"])
    return path


def mechanism_readouts(root, first, selected, data, seed):
    methods = selected["final"], selected["practical"]
    for index, method in enumerate(methods):
        arm = selected["families"][method]["arms"][0]
        path = root / "s4" / "arms" / f"{method}-reference.json"
        publish(path, arm)
        invoke(
            "run_memory_control_v13_evaluation.py",
            "transfer",
            "--rosters",
            root / "rosters",
            "--data",
            data,
            "--arm",
            path,
            "--output",
            root / "s4/transfer" / method,
            "--device",
            "cuda",
            "--reference-run",
            first[method],
            *(["--budgets-only"] if index else []),
        )
    for method in dict.fromkeys((selected["final"], selected["same_backbone"])):
        if method not in LEARNED:
            continue
        arm = selected["families"][method]["arms"][0]
        checkpoint = arm["checkpoint"]
        curve_point = json_file(point_path(root, method, seed, 24000))
        last_round = Path(curve_point["acquisition_paths"][-1])
        target = json_file(last_round / "round.json")["continuation_policy_id"]
        if json_file(Path(checkpoint).parent / "run.json")["contract"]["target"][1] != target:
            raise ValueError("A different continuation generated the final fitted targets")
        aligned = root / "s4" / "aligned-evidence" / last_round.name
        invoke(
            "diagnose_memory_control_v13_evidence.py",
            "--output",
            aligned,
            "collect",
            "--data",
            data,
            "--population",
            root / "rosters/curve-2048.json",
            "--device",
            "cuda",
            "--target-round",
            last_round,
            "--reuse-capture",
            root / "evidence-diagnostic",
        )
        result = root / "s4" / f"evidence-{method}-f{seed}.json"
        previous = json_file(result) if result.is_file() else {}
        if (
            previous.get("checkpoint") == checkpoint
            and previous.get("utility_lambda") == arm["utility_lambda"]
            and previous.get("matched_continuation")
            and previous.get("measured_continuation") == target
        ):
            continue
        with phase_unit(phase_directory(root), "evaluate"):
            invoke(
                "diagnose_memory_control_v13_evidence.py",
                "--output",
                aligned,
                "score",
                "--checkpoint",
                checkpoint,
                "--device",
                "cuda",
                "--utility-lambda",
                arm["utility_lambda"],
                "--require-matched-continuation",
                "--result",
                result,
            )


def repeat(args):
    root, weights = args.root.resolve(), args.weights.resolve()
    selected, first = freeze(root, args.acquisition_seed)
    final, same, practical = (selected[k] for k in ("final", "same_backbone", "practical"))
    chosen = list(dict.fromkeys((final, same, practical)))
    learned = [method for method in chosen if method in LEARNED]
    families = {method: [str(first[method])] for method in chosen}
    comparison_dir = root / "s4"
    mechanism_readouts(root, first, selected, args.dataset, args.acquisition_seed)
    population_path = repeat_population(root, learned, chosen)
    for seed in (29, 47):
        initial = evidence_fit(root, args.s1, seed)
        fit_flags = [arg for method in learned for arg in ("--refit-method", method)]
        invoke(
            "run_memory_control_v13_rounds.py",
            "--root",
            root,
            "--weights",
            weights,
            "--s1",
            initial,
            "--curve",
            root / "rosters/curve-2048.json",
            "--until",
            24000,
            "--acquisition-seed",
            args.acquisition_seed,
            "--fit-seed",
            seed,
            "--frozen-data",
            "--refit-only",
            *fit_flags,
        )
        for method in learned:
            model = weights / f"a{args.acquisition_seed}-f{seed}-{method}-24000" / "checkpoint"
            arm = dict(
                selected["families"][method]["arms"][0],
                name=f"{method}-f{seed}-frozen-readout",
                checkpoint=str(model),
                seed=seed,
            )
            arm_path = comparison_dir / "arms" / (arm["name"] + ".json")
            publish(arm_path, arm)
            out = comparison_dir / "tune" / arm["name"]
            invoke(
                "run_memory_control_v13_evaluation.py",
                "evaluate",
                "--data",
                args.dataset,
                "--population",
                population_path,
                "--arm",
                arm_path,
                "--output",
                out,
                "--device",
                "cuda",
            )
            families[method].append(str(out))
    for method, paths in families.items():
        validate_dev_family(
            [Path(p) for p in paths], final=method == final, tune_subset=json_file(population_path)
        )
    spec = {
        "families": families,
        "tune_subset": str(population_path),
        "final": final,
        "same_backbone": [same],
        "practical": [practical],
    }
    publish(comparison_dir / "selection.json", spec)
    # No protected outcomes are accessed by development selection or fitting repeats.
    return spec


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--acquisition-seed", type=int, choices=[11], default=11)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    refit = sub.add_parser("repeat")
    refit.add_argument("--weights", type=Path, required=True)
    refit.add_argument("--s1", type=Path, required=True)
    refit.add_argument(
        "--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2")
    )
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(args.root.resolve(), args.acquisition_seed)
    else:
        with (args.root / ".frozen-data-repeats.lock").open("a") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            repeat(args)
