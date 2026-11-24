"""Run the common warm, fixed-pool and on-policy feedback experiments on the native runtime."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import statistics
import subprocess
import sys
from argparse import Namespace
from pathlib import Path


def json_file(path):
    return json.loads(path.read_text())


def publish(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and json_file(path) != obj:
        raise ValueError(f"Registration differs from existing file {path}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    tmp.replace(path)


def run(module, *args):
    from contextlib import nullcontext

    from milai_lab.runners.v13_phase import phase_directory, phase_unit

    scope = nullcontext()
    if module == "pretrained_control_train":
        output = Path(args[args.index("--output") + 1])
        scope = phase_unit(phase_directory(output), "fit")
    with scope:
        subprocess.run(  # noqa: S603 -- fixed local entry point and argv, no shell
            [sys.executable, "-m", "milai_lab.runners." + module, *map(str, args)], check=True
        )


def exposure(directory):
    calls = 0
    for path in (directory / "receipts").glob("*.json.gz"):
        with gzip.open(path) as f:
            calls += json.load(f)["feedback_exposure"]
    return calls


def collect(args, directory, calls, stage, mode, prior=None, sampler=None, shared=None):
    pool_seed = args.acquisition_seed * 100 + stage if stage else None
    window = args.recipe["eligible_pool_window"] if stage else 1
    progress_file = directory / "progress.json"
    if progress_file.is_file() and json_file(progress_file).get("state") == "complete":
        config = json_file(directory / "round.json")
        expected = {
            "seed": args.acquisition_seed,
            "pool_seed": pool_seed,
            "round": stage,
            "sampler": mode,
            "candidate_window": window,
            "material_budget": args.recipe["memory_budget_tokens"],
            "environment": args.recipe["environment"],
            "observation": args.recipe["observation"],
            "utility_lambda": args.recipe["utility_lambda"],
            "continuation_mode": "full_episode",
            "continuation_policy_id": str(prior.resolve()) if prior else "pi0-fixedcontext-4",
            "sampling_checkpoint": str(sampler.resolve()) if sampler else None,
        }
        warm_config = json_file(args.warm / "round.json")
        if (
            any(config.get(k) != v for k, v in expected.items())
            or config["dataset_run"] != warm_config["dataset_run"]
            or config["reader"] != warm_config["reader"]
            or config.get("reuse_from", []) != ([str(shared.resolve())] if shared else [])
            or config.get("exclude_roots_from", [])
            != ([str(args.warm.resolve())] if stage == 1 else [])
            or json_file(progress_file)["complete_packs"]
            != len(list((directory / "packs").glob("*.json.gz")))
            or exposure(directory) != calls
        ):
            raise ValueError(f"Closed acquisition differs from the frozen round at {directory}")
        return
    flags = ["--pool-seed", pool_seed] if pool_seed is not None else []
    if prior:
        flags += ["--continuation-checkpoint", prior]
    if sampler:
        flags += ["--sampler-checkpoint", sampler]
    if shared:
        flags += ["--reuse-from", shared]
    if stage == 1:
        flags += ["--exclude-roots-from", args.warm]
    run(
        "control_policy_iteration",
        "--dataset",
        args.dataset,
        "--output",
        directory,
        "--seed",
        args.acquisition_seed,
        "--round",
        stage,
        "--calls",
        calls,
        "--window",
        window,
        "--budget",
        args.recipe["memory_budget_tokens"],
        "--utility-lambda",
        args.recipe["utility_lambda"],
        "--sampler",
        mode,
        *flags,
    )
    if exposure(directory) != calls:
        raise RuntimeError(f"Round closed with a different exposure at {directory}")


def fit(args, name, data, parent, objective, scale):
    path = args.weights / name
    metrics = args.root / "fits" / name
    if (path / "run.json").exists():
        info = json_file(path / "run.json")
        c = info["contract"]
        if (
            c["seed"] != args.fit_seed
            or c["supervision_mode"] != objective
            or c["parent"] != str(parent)
            or c["cost_scale"] != scale
            or c["input"] != str([data / "packs"])
            or c["probe"]
        ):
            raise RuntimeError(f"Prior fit does not match stage {name}")
        if getattr(args, "cost_identity", None) is not None:
            from milai_lab.methods.control_cost_scale import require_same_host_cost_scale

            if not c.get("scale_source"):
                raise ValueError(f"Prior fit has no TRAIN Host calibration source at {path}")
            require_same_host_cost_scale(c["scale_source"], args.cost_identity)
        if info["status"] == "completed":
            if not info["reload_scores_equal"] or not (path / "checkpoint/control.pt").is_file():
                raise RuntimeError(f"Final weights missing for {name}")
            try:
                final_metrics = json_file(metrics / "run.json")
            except (FileNotFoundError, json.JSONDecodeError):
                final_metrics = None
            if final_metrics == info:
                return path / "checkpoint"
    run(
        "pretrained_control_train",
        "--objective",
        objective,
        "--data",
        data / "packs",
        "--initialize",
        parent,
        "--output",
        path,
        "--metrics",
        metrics,
        "--seed",
        args.fit_seed,
        *(
            ["--cost-scale-report", args.cost_scale_report]
            if getattr(args, "cost_scale_report", None)
            else ["--warm-packs", args.warm / "packs"]
        ),
        "--epochs",
        args.recipe["fit"]["epochs"],
        "--batch",
        args.recipe["fit"]["effective_batch"],
        "--lr",
        args.recipe["fit"]["learning_rate"],
    )
    return path / "checkpoint"


def evaluate(args, name, checkpoint):
    out = args.root / "eval" / name
    arm = args.root / "arms" / (name + ".json")
    publish(
        arm,
        dict(
            name=name,
            policy="pretrained_checkpoint",
            checkpoint=str(checkpoint),
            environment="qrag_milai_v13",
            observation_protocol=args.recipe["observation"],
            utility_lambda=args.recipe["utility_lambda"],
            seed=args.fit_seed,
        ),
    )
    subprocess.run(  # noqa: S603 -- fixed local entry point and argv, no shell
        [
            sys.executable,
            str(Path(__file__).with_name("run_memory_control_v13_evaluation.py")),
            "evaluate",
            "--arm",
            str(arm),
            "--data",
            str(args.dataset),
            "--output",
            str(out),
            "--population",
            str(args.curve),
            "--device",
            "cuda",
        ],
        check=True,
    )


def register_acquisition_repeat(args):
    if (
        args.acquisition_seed not in (29, 47)
        or args.fit_seed != 11
        or args.until != 12000
        or args.frozen_data
        or args.refit_only
        or args.refit_method
        or args.recipe["warm_feedback_calls"] != 2000
        or list(args.recipe["feedback_checkpoints"])[:2] != [6000, 12000]
        or not args.recipe.get("cost_scale_report")
    ):
        raise ValueError(
            "Independent acquisition repeats require seed 29/47, fit 11, and the 2k/6k/12k recipe"
        )
    if not (args.s1 / "control.pt").is_file():
        raise ValueError("Independent acquisition requires the frozen S1 checkpoint")
    from milai_lab.methods.control_cost_scale import (
        load_host_cost_scale,
        require_same_host_cost_scale,
    )

    primary_warm = json_file(args.root / "warm-11/round.json")
    paired = json_file(args.root / "fits/a11-f11-warm-paired/run.json")["contract"]
    _, unit = load_host_cost_scale(
        args.root / args.recipe["cost_scale_report"],
        dataset_run_id=primary_warm["dataset_run"],
        budget=args.recipe["memory_budget_tokens"],
    )
    require_same_host_cost_scale(paired["scale_source"], unit)
    evidence = {}
    previous_cohort = None
    for n, phase in ((6000, "fixed_pool_mechanism"), (12000, "natural_policy_iteration")):
        review_path = args.root / f"dev-review-a11-{n}.json"
        review = json_file(review_path)
        if (
            review["phase"] != phase
            or review["acquisition_seed"] != 11
            or review["fitting_seed"] != 11
            or review["cumulative_feedback_per_learning_arm"] != n
        ):
            raise ValueError("The repeat requires the bound seed-11 development comparisons")
        points = {m: json_file(Path(review["checkpoints"][m])) for m in ("PQ-U", "PQ-A")}
        paths = []
        for m, p in points.items():
            cohort = p["cohort"]
            if (
                p["method"] != m
                or p["acquisition_seed"] != 11
                or p["fit_seed"] != 11
                or p["usage"]["exposure"] != n
                or cohort != json_file(args.curve)
                or cohort["role"] != "dev"
                or cohort["v13_role"] != "curve"
                or json_file(Path(p["deployment"]["path"]) / "run.json")["status"] != "COMPLETED"
                or (previous_cohort is not None and cohort != previous_cohort)
            ):
                raise ValueError(
                    "The two repeat-trigger points need the completed matched DEV roster and budget"
                )
            previous_cohort = cohort
            paths.append([Path(x).resolve() for x in p["acquisition_paths"]])
        if paths[0][0] != paths[1][0] or paths[0][0] != (args.root / "warm-11").resolve():
            raise ValueError("Seed-11 samplers did not share their paid warm")
        common = [json_file(x[1] / "mechanism-pool.json")["common_pool"] for x in paths]
        if common[0] != common[1] or not Path(common[0]).is_file():
            raise ValueError("Seed-11 mechanism samplers need the same frozen TRAIN pool")
        contrast = review["quality_contrasts"]["PQ-A vs PQ-U"]
        evidence[str(n)] = dict(
            review=str(review_path),
            comparison="PQ-A vs PQ-U",
            phase=phase,
            quality_delta_points=contrast["quality_delta_points"],
            quality_interval_95=contrast["quality_interval_95"],
            difference_range_given_unobserved=contrast["difference_range_given_unobserved"],
            source_strata=contrast["source_strata"],
            common_pool=common[0],
        )
    if (
        Path(paired["parent"]).resolve() != args.s1.resolve()
        or json_file(args.root / "fits/a11-f11-recipe.json") != args.recipe
    ):
        raise ValueError("Independent acquisition must retain the seed-11 S1 and frozen recipe")
    registration = args.root / "repeats" / f"a{args.acquisition_seed}-f11-registration.json"
    reason = getattr(args, "repeat_reason", None)
    if reason is None and registration.exists():
        reason = json_file(registration).get("reason")
    publish(
        registration,
        dict(
            acquisition_seed=args.acquisition_seed,
            fit_seed=11,
            methods=["PQ-U", "PQ-A"],
            through=12000,
            warm=str(args.warm),
            exposure_cap_per_arm=12000,
            new_physical_request_cap=22000,
            evaluated_evidence=evidence,
            trigger="explicit acquisition-repeat invocation",
            reason=reason or "Replicate the registered fixed-pool and natural online comparisons",
            evaluation_charged_separately=True,
        ),
    )


def repeat_accounting(args, rollouts, point):
    by_dir = {}
    charged = set()
    allowed_receipts = {(p / "receipts").resolve() for chain in rollouts.values() for p in chain}
    for method in ("PQ-U", "PQ-A"):
        for path in rollouts[method]:
            key = str(path.resolve())
            if key in by_dir:
                continue
            counts = dict(exposure=0, known_new_requests=0, unknown_request_receipts=0)
            for receipt_path in (path / "receipts").glob("*.json.gz"):
                with gzip.open(receipt_path) as stream:
                    receipt = json.load(stream)
                if origin := receipt.get("measurement_reused_from"):
                    allowed = (
                        {(args.warm / "receipts").resolve()}
                        if path == args.warm
                        else allowed_receipts
                    )
                    if Path(origin).parent.resolve() not in allowed:
                        raise ValueError(
                            "Independent acquisition cannot import another seed's supervision"
                        )
                if (
                    receipt.get("reader_wire")
                    and receipt["reader_wire"]["seed"] != args.acquisition_seed
                ):
                    raise ValueError("Reader seed differs from the independent acquisition")
                counts["exposure"] += receipt["feedback_exposure"]
                new = receipt["actual_requests"]
                if new is None:
                    counts["unknown_request_receipts"] += 1
                elif new:
                    positions = range(receipt["ledger_before"], receipt["ledger_after"])
                    if len(positions) != new or charged.intersection(positions):
                        raise ValueError("Duplicate or inconsistent physical repeat charges")
                    charged.update(positions)
                    counts["known_new_requests"] += new
            by_dir[key] = counts
    arm_exposure = {
        m: sum(by_dir[str(p.resolve())]["exposure"] for p in rollouts[m]) for m in ("PQ-U", "PQ-A")
    }
    unknown = sum(d["unknown_request_receipts"] for d in by_dir.values())
    if any(v != point for v in arm_exposure.values()) or len(charged) + unknown > 2 * point - 2000:
        raise ValueError("Independent sampler repeat exceeds its registered training allowance")
    ranges = []
    for slot in sorted(charged):
        if ranges and ranges[-1][1] == slot:
            ranges[-1][1] = slot + 1
        else:
            ranges.append([slot, slot + 1])
    publish(
        args.root / "repeats" / f"a{args.acquisition_seed}-f11-accounting-{point}.json",
        dict(
            acquisition_seed=args.acquisition_seed,
            fit_seed=11,
            checkpoint=point,
            per_arm_exposure=arm_exposure,
            sum_arm_exposure=sum(arm_exposure.values()),
            unique_known_physical_requests=len(charged),
            unknown_request_receipts=unknown,
            physical_upper_bound=len(charged) + unknown,
            registered_physical_cap=2 * point - 2000,
            unique_physical_ledger_intervals=ranges,
            by_distinct_directory=by_dir,
            evaluation_directories=[
                str(args.root / "eval" / f"a{args.acquisition_seed}-f11-{m}-{n}")
                for n in (6000, 12000)
                if n <= point
                for m in rollouts
            ],
            evaluation_charged_separately=True,
        ),
    )

    if point == 12000:
        destination = args.root / "repeats"
        with (destination / ".combined.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            files = [destination / f"a{seed}-f11-accounting-12000.json" for seed in (29, 47)]
            if all(f.is_file() for f in files):
                records = [json_file(f) for f in files]
                seen = set()
                for record in records:
                    for begin, end in record["unique_physical_ledger_intervals"]:
                        span = range(begin, end)
                        if seen.intersection(span):
                            raise ValueError("Independent acquisition seeds share a paid request")
                        seen.update(span)
                ceiling = sum(r["physical_upper_bound"] for r in records)
                total = sum(r["sum_arm_exposure"] for r in records)
                if total != 48000 or ceiling > 44000:
                    raise ValueError("Combined 29/47 training budget differs from its registration")
                publish(
                    destination / "acquisition-29-47-accounting.json",
                    dict(
                        seeds=[29, 47],
                        fit_seed=11,
                        arm_exposure=total,
                        known_unique_new_requests=len(seen),
                        physical_upper_bound=ceiling,
                        maximum_physical_calls=44000,
                        requested_additional_exposure_cap=48000,
                        evaluation_charged_separately=True,
                        accounting=[str(f) for f in files],
                    ),
                )


def round_matrix(args):
    from report_memory_control_v13_curves import point as record_point

    args.warm = args.root / f"warm-{args.acquisition_seed}"
    repeat = getattr(args, "acquisition_repeat", False)
    if repeat:
        register_acquisition_repeat(args)
        collect(args, args.warm, 2000, 0, "uniform")
    warm_contract = json_file(args.warm / "round.json")
    if repeat:
        main_warm = json_file(args.root / "warm-11/round.json")
        if (
            warm_contract["seed"] != args.acquisition_seed
            or warm_contract["round"] != 0
            or warm_contract.get("reuse_from")
            or warm_contract.get("exclude_roots_from")
            or warm_contract["reader"] != main_warm["reader"]
            or warm_contract["dataset_run"] != main_warm["dataset_run"]
            or (args.warm.resolve() == (args.root / "warm-11").resolve())
        ):
            raise ValueError("A repeat must collect its own compatible seed-specific warm")
    if (
        exposure(args.warm) != args.recipe["warm_feedback_calls"]
        or warm_contract["environment"] != args.recipe["environment"]
        or warm_contract["observation"] != args.recipe["observation"]
        or warm_contract["material_budget"] != args.recipe["memory_budget_tokens"]
        or warm_contract["sampler"] != "uniform"
        or json_file(args.curve)["material_budget"] != args.recipe["memory_budget_tokens"]
    ):
        raise ValueError("Warm exposures, native environment or DEV budget differ from the recipe")
    tag = f"a{args.acquisition_seed}-f{args.fit_seed}"
    if report := args.recipe.get("cost_scale_report"):
        from milai_lab.methods.control_cost_scale import load_host_cost_scale

        args.cost_scale_report = (args.root / report).resolve()
        scale, source = load_host_cost_scale(
            args.cost_scale_report,
            dataset_run_id=warm_contract["dataset_run"],
            budget=args.recipe["memory_budget_tokens"],
        )
        args.cost_identity = source
        registration = dict(scale=scale, source=source, reader_requests=0)
        original = args.root / "fits" / f"{tag}-cost-scale.json"
        if original.exists():
            from milai_lab.methods.control_cost_scale import require_same_host_cost_scale

            registered = json_file(original)
            if registered.get("scale") != scale or registered.get("reader_requests") != 0:
                raise ValueError("Saved run used a different normalization")
            require_same_host_cost_scale(registered["source"], source)
            registration = registered
    else:
        # Retain the measured-outcome unit used by earlier explicitly registered trials.
        scale_samples = []
        for path in (args.warm / "packs").glob("*.json.gz"):
            with gzip.open(path) as f:
                scale_samples.extend(
                    o["future_cost"] for o in json.load(f)["outcomes"] if o["future_cost_observed"]
                )
        scale = max(1.0, statistics.median(scale_samples))
        registration = dict(
            training_source=str(args.warm),
            future_cost_median=scale,
            observed_action_count=len(scale_samples),
        )
    publish(args.root / "fits" / f"{tag}-cost-scale.json", registration)
    publish(args.root / "fits" / f"{tag}-recipe.json", args.recipe)
    selected = ("PQ-U", "PQ-A") if repeat else (args.refit_method or ("DQ", "PQ-U", "PQ-A"))
    warm_models = {}
    prior = {}
    for method in selected:
        objective = "direct" if method == "DQ" else "paired"
        if objective not in warm_models:
            warm_models[objective] = fit(
                args, f"{tag}-warm-{objective}", args.warm, args.s1, objective, scale
            )
        prior[method] = warm_models[objective]
    fits = {method: [args.s1.parent, initial.parent] for method, initial in prior.items()}
    rollouts = {method: [args.warm] for method in prior}
    previous = args.recipe["warm_feedback_calls"]
    for stage, point in enumerate(args.recipe["feedback_checkpoints"], 1):
        calls = point - previous
        previous = point
        if point > args.until:
            break
        pools = {}
        needed = {"PQ-U" if method == "DQ" else method for method in prior}
        for method, mode in (("PQ-U", "uniform"), ("PQ-A", "structured")):
            if method not in needed:
                continue
            data = args.root / "collection" / f"a{args.acquisition_seed}-{method}-{point}"
            if args.frozen_data:
                contract = json_file(data / "round.json")
                if (
                    contract["sampler"] != mode
                    or contract["round"] != stage
                    or contract["seed"] != args.acquisition_seed
                    or exposure(data) != calls
                ):
                    raise ValueError(f"Incomplete or incompatible frozen source {data}")
            else:
                collect(
                    args,
                    data,
                    calls,
                    stage,
                    mode,
                    prior[method] if stage > 1 else None,
                    prior[method] if method == "PQ-A" else None,
                    pools.get("PQ-U") if stage == 1 and method == "PQ-A" else None,
                )
            pools[method] = data
        for method in prior:
            name = f"{tag}-{method}-{point}"
            prior[method] = fit(
                args,
                name,
                pools["PQ-U" if method == "DQ" else method],
                prior[method],
                "direct" if method == "DQ" else "paired",
                scale,
            )
            if args.refit_only:
                continue
            evaluate(args, name, prior[method])
            fits[method].append(prior[method].parent)
            rollouts[method].append(pools["PQ-U" if method == "DQ" else method])
            record_point(
                Namespace(
                    evaluation=args.root / "eval" / name,
                    method=method,
                    calls=point,
                    qr=None,
                    rollouts=rollouts[method],
                    fits=fits[method],
                    acquisition_seed=args.acquisition_seed,
                    fit_seed=args.fit_seed,
                    output=args.root / "curve-points" / (name + ".json"),
                )
            )

        if repeat:
            repeat_accounting(args, rollouts, point)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs/memory_control_v13/feedback.json",
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--s1", type=Path, required=True)
    parser.add_argument("--curve", type=Path, required=True)
    parser.add_argument(
        "--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2")
    )
    parser.add_argument("--acquisition-seed", type=int, default=11)
    parser.add_argument("--fit-seed", type=int, default=11)
    parser.add_argument(
        "--acquisition-repeat",
        action="store_true",
        help="Run the conditional independent 29/47 acquisition protocols through 12k",
    )
    parser.add_argument(
        "--repeat-reason", help="Optional development evidence motivating this repeat"
    )
    parser.add_argument(
        "--frozen-data",
        action="store_true",
        help="Reuse the recorded acquisition seed and its actual continuation targets",
    )
    parser.add_argument(
        "--refit-method",
        choices=("DQ", "PQ-U", "PQ-A"),
        action="append",
        help="Limit frozen-data repeat fitting to preselected methods",
    )
    parser.add_argument(
        "--refit-only",
        action="store_true",
        help="Fit the frozen-data chain; defer readouts to selected registered arms",
    )
    parser.add_argument("--until", type=int, required=True)
    args = parser.parse_args()
    if (args.refit_method or args.refit_only) and not args.frozen_data:
        parser.error("A partial method matrix requires immutable frozen acquisition data")
    if args.refit_method and len(set(args.refit_method)) != len(args.refit_method):
        parser.error("Specify each repeated method only once")
    args.recipe = json_file(args.config)
    controls = [args.recipe["warm_feedback_calls"], *args.recipe["feedback_checkpoints"]]
    if (
        len(controls) < 3
        or controls != sorted(set(controls))
        or controls[0] <= 0
        or args.until not in controls[1:]
    ):
        parser.error("Choose an increasing schedule and an actual feedback checkpoint")
    for key in ("root", "weights", "s1", "curve", "dataset"):
        setattr(args, key, getattr(args, key).resolve())
    with (args.root / f".rounds-{args.acquisition_seed}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        round_matrix(args)
