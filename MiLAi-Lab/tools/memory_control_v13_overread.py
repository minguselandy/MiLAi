"""Compare matched 2k and 6k model scores on the frozen, already-paid two-action DEV capture."""

from __future__ import annotations

import fcntl
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from diagnose_memory_control_v13_evidence import native_deltas
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.methods.control_cost_scale import load_host_cost_scale, require_same_host_cost_scale
from milai_lab.runners.control_policy_iteration import read_gzip, write_gzip

OBJECTIVES = {"DQ": "direct", "PQ-U": "paired"}
TARGET = "pi0-fixedcontext-4"
PENALTY = 0.05
SCALE = 1912.0


def capture_inputs(root):
    directory = root / "evidence-diagnostic"
    reg = read_json(directory / "registration.json")
    closed = read_json(directory / "capture.json")
    roster = read_json(root / "rosters/curve-2048.json")
    if (
        not reg
        or not closed
        or reg["role"] != "TUNE_diagnostic"
        or reg["continuation"] != TARGET
        or reg["material_budget"] != 2048
        or closed["feedback_calls"] != 156
        or read_json(Path(reg["population"])) != roster
        or roster["role"] != "dev"
        or roster.get("v13_role") != "curve"
        or reg["dataset_run_id"] != roster["dataset_run_id"]
    ):
        raise ValueError("Expected the closed pi0 DEV diagnostic")
    eligible = {t["task_id"]: (t["dataset"], t["native_group"]) for t in roster["tasks"]}
    witnessed = []
    seen = set()
    support = defaultdict(lambda: defaultdict(Counter))
    for file in sorted((directory / "pairs").glob("*.json.gz")):
        row = read_gzip(file)
        key = (row["dataset"], row["native_group"])
        candidate = row["candidate"]
        if (
            row["split_role"] != "dev"
            or eligible.get(row["task_id"]) != key
            or key in seen
            or len(row["states"]) != 2
        ):
            raise ValueError("Changed diagnostic root")
        seen.add(key)
        states = []
        paired = defaultdict(list)
        for state in row["states"]:
            if set(state["labels"]) != {candidate, "handoff"}:
                raise ValueError("Changed two-action menu")
            gains = native_deltas(state["labels"], candidate, PENALTY, SCALE)
            states.append(
                dict(
                    prefix=state["prefix"],
                    online=state["online"],
                    gains=gains,
                    origins={
                        k: [v["reader_receipt_ids"], v["companion_receipt_id"]]
                        for k, v in state["labels"].items()
                    },
                )
            )
            for axis, truth in gains.items():
                support[key[0]][axis][
                    "positive" if truth > 0 else "negative" if truth < 0 else "tie"
                ] += 1
                paired[axis].append(truth)
        for axis, values in paired.items():
            if len(values) == 2:
                support[key[0]][axis]["pairs"] += 1
                support[key[0]][axis]["flips"] += int(values[0] * values[1] < 0)
        witnessed.append(
            dict(
                task_id=row["task_id"],
                native_group=key[1],
                source=key[0],
                candidate=candidate,
                states=states,
            )
        )
    counts = Counter(s for s, _ in seen)
    if len(seen) != 36 or dict(counts) != closed["groups"] or set(counts.values()) != {12}:
        raise ValueError("Incomplete frozen diagnostic roster")
    return dict(registration=reg, roots=witnessed), support


def binary_count(measures, key, denominator):
    m = measures.get(key, {"n": 0, "mean": None})
    if m["n"] != denominator:
        raise ValueError(f"Different label support for {key}")
    positive = 0 if not denominator else round(m["mean"] * denominator)
    if denominator and (
        not 0 <= positive <= denominator
        or not math.isclose(m["mean"], positive / denominator, abs_tol=1e-12)
    ):
        raise ValueError(f"Invalid binary count for {key}")
    return positive


def ratio(k, n):
    return {"numerator": k, "denominator": n, "rate": k / n if n else None}


def summarize_scores(scores, support):
    """Summarize standard score outputs; the same function processes both checkpoints."""
    axes = {}
    for axis, stem in (("quality", ""), ("utility", "_utility")):
        table = {}
        for mode in ("original", "swapped"):
            cell = {}
            prefix = mode + stem
            for method, raw in scores.items():
                if set(raw["sources"]) != set(support):
                    raise ValueError("Score sources differ")
                sources = {}
                for src, measures in raw["sources"].items():
                    truth = support[src][axis]
                    r = measures[prefix + "_two_action_regret"]
                    if r["n"] != sum(truth[k] for k in ("positive", "negative", "tie")):
                        raise ValueError("Score covered different before states")
                    row = dict(
                        regret=r,
                        true_ties=truth["tie"],
                        measured_reversals=ratio(truth["flips"], truth["pairs"]),
                    )
                    for field, name, den in (
                        ("false_stop", "_stop_on_profitable_read", "positive"),
                        ("overread", "_read_on_profitable_stop", "negative"),
                        ("both_reversal_signs_correct", "_both_reversal_signs_correct", "flips"),
                    ):
                        row[field] = ratio(
                            binary_count(measures, prefix + name, truth[den]), truth[den]
                        )
                    sources[src] = row
                data = dict(
                    source_macro_regret=mean(r["regret"]["mean"] for r in sources.values()),
                    sources=sources,
                )
                for field, name in (
                    ("false_stop", "false_stop"),
                    ("overread", "overread"),
                    ("reversal_hits", "both_reversal_signs_correct"),
                ):
                    rr = [r[name] for r in sources.values()]
                    data[field] = ratio(
                        sum(v["numerator"] for v in rr), sum(v["denominator"] for v in rr)
                    )
                cell[method] = data
            cell["paired_minus_direct_macro_regret"] = (
                cell["paired"]["source_macro_regret"] - cell["direct"]["source_macro_regret"]
            )
            table[mode] = cell
        table["swapped_minus_original_macro_regret"] = {
            m: table["swapped"][m]["source_macro_regret"]
            - table["original"][m]["source_macro_regret"]
            for m in scores
        }
        axes[axis] = table
    return axes


def closed_fit(checkpoint, objective, round_id, packs, identity):
    fit = read_json(checkpoint.parent / "run.json", {})
    c = fit.get("contract", {})
    proof = read_json(checkpoint / "fit_completion.json", {})
    if (
        fit.get("status") != "completed"
        or not fit.get("reload_scores_equal")
        or not (checkpoint / "control.pt").is_file()
        or not fit.get("fit_identity")
        or fit["fit_identity"] != proof.get("fit_identity")
        or fit["optimizer_updates"] != proof.get("summary", {}).get("optimizer_updates")
        or c["seed"] != 11
        or c["supervision_mode"] != objective
        or c["probe"]
        or c["cost_scale"] != SCALE
        or c["target"] != [round_id, TARGET]
        or c["input"] not in {str([packs]), str([packs.resolve()])}
    ):
        raise ValueError("Warm/6k fit, data or continuation does not match the diagnostic")
    require_same_host_cost_scale(c["scale_source"], identity)
    return fit


def verify_score(raw, checkpoint, round_id):
    if (
        not raw
        or Path(raw["checkpoint"]).resolve() != checkpoint.resolve()
        or raw["fit_target"] != [round_id, TARGET]
        or not raw["matched_continuation"]
        or raw["measured_continuation"] != TARGET
        or raw["cost_scale"] != SCALE
        or raw["utility_lambda"] != PENALTY
    ):
        raise ValueError("Score does not match the frozen checkpoint, target and utility unit")


def has_error_split(raw):
    split = raw.get("overread_utility_error")
    return (
        isinstance(split, dict)
        and bool(split)
        and set(split) == set(raw.get("sources", {}))
        and all(set(modes) == {"original", "swapped"} for modes in split.values())
    )


def cpu_score(directory, checkpoint, path):
    env = dict(
        os.environ,
        CUDA_VISIBLE_DEVICES="",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="1",
        TOKENIZERS_PARALLELISM="false",
        PYTHONDONTWRITEBYTECODE="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    subprocess.run(  # noqa: S603 -- fixed local score command, no Reader dispatch
        [
            sys.executable,
            str(Path(__file__).with_name("diagnose_memory_control_v13_evidence.py")),
            "--output",
            str(directory),
            "score",
            "--device",
            "cpu",
            "--require-matched-continuation",
            "--utility-lambda",
            str(PENALTY),
            "--checkpoint",
            str(checkpoint),
            "--result",
            str(path),
        ],
        check=True,
        env=env,
    )


def changes(before, after):
    out = {}
    for axis in ("quality", "utility"):
        out[axis] = {}
        for mode in ("original", "swapped"):
            out[axis][mode] = {}
            for objective in OBJECTIVES.values():
                a = before[axis][mode][objective]
                b = after[axis][mode][objective]
                row = dict(source_macro_regret=b["source_macro_regret"] - a["source_macro_regret"])
                for k in ("overread", "false_stop", "reversal_hits"):
                    if a[k]["denominator"] != b[k]["denominator"]:
                        raise ValueError("Unmatched diagnostic opportunities")
                    row[k] = ratio(b[k]["numerator"] - a[k]["numerator"], b[k]["denominator"])
                out[axis][mode][objective] = row
    return out


def settle_overread(root, seed, points):
    if seed != 11:
        raise ValueError("The warm-vs-6k overread diagnostic is registered for seed 11")
    directory = root / "evidence-diagnostic"
    dest = directory / "overread-6000"
    dest.mkdir(parents=True, exist_ok=True)
    capture, support = capture_inputs(root)
    warm = root / "warm-11"
    uniform = root / "collection/a11-PQ-U-6000"
    for path, calls, stage in ((warm, 2000, 0), (uniform, 4000, 1)):
        decl = read_json(path / "round.json", {})
        progress = read_json(path / "progress.json", {})
        if (
            decl.get("sampler") != "uniform"
            or decl.get("dataset_run") != capture["registration"]["dataset_run_id"]
            or decl.get("seed") != 11
            or decl.get("round") != stage
            or decl.get("continuation_policy_id") != TARGET
            or decl.get("utility_lambda") != PENALTY
            or decl.get("material_budget") != 2048
            or progress.get("state") != "complete"
            or progress["feedback_calls"] != calls
        ):
            raise ValueError("Require the completed common warm and uniform pi0 round")
    if [
        Path(p).resolve() for p in read_json(uniform / "round.json").get("exclude_roots_from", [])
    ] != [warm.resolve()]:
        raise ValueError("6k acquisition was not bound to the shared warm")
    scale, identity = load_host_cost_scale(
        root / "frozen-host-cost-scale.json",
        dataset_run_id=capture["registration"]["dataset_run_id"],
        budget=2048,
    )
    if scale != SCALE:
        raise ValueError("Cost unit differs from registration")
    models = {}
    warm_scores = {}
    cohort = read_json(root / "rosters/curve-2048.json")
    for method, obj in OBJECTIVES.items():
        point = points[method]
        if (
            point["method"] != method
            or point["fit_seed"] != seed
            or point["acquisition_seed"] != seed
            or point["cohort"] != cohort
            or point["usage"]["exposure"] != 6000
            or [Path(p).resolve() for p in point["acquisition_paths"]]
            != [warm.resolve(), uniform.resolve()]
        ):
            raise ValueError("Require closed 6k DQ/PQ-U points on the same registered inputs")
        raw = read_json(directory / f"warm-11-{obj}.json")
        parent = Path(raw["checkpoint"])
        verify_score(raw, parent, 0)
        old = closed_fit(parent, obj, 0, warm / "packs", identity)
        checkpoint = Path(point["deployment"]["arm"]["checkpoint"])
        fit = closed_fit(checkpoint, obj, 1, uniform / "packs", identity)
        runpath = Path(point["deployment"]["path"])
        if (
            not Path(fit["contract"]["parent"]).samefile(parent)
            or read_json(runpath / "run.json", {}).get("status") != "COMPLETED"
            or read_json(runpath / "protocol.json", {}).get("arm") != point["deployment"]["arm"]
        ):
            raise ValueError("Published 6k readout or fit parent differs")
        models[obj] = (checkpoint, fit, old)
        warm_scores[obj] = raw
    if not Path(models["direct"][2]["contract"]["parent"]).samefile(
        models["paired"][2]["contract"]["parent"]
    ):
        raise ValueError("Warm fits did not start at the same S1")
    before = summarize_scores(warm_scores, support)
    if read_json(directory / "warm-11-direct-vs-paired.json", {}).get("axes") != before:
        raise ValueError("2k aggregation differs from the observed registered warm summary")
    scores = {}
    with (dest / ".score.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for obj, (checkpoint, fit, _) in models.items():
            binding = dict(
                capture=capture,
                fit_identity=fit["fit_identity"],
                target=fit["contract"]["target"],
                objective=obj,
                updates=fit["optimizer_updates"],
                cost_unit=SCALE,
                penalty=PENALTY,
                checkpoint=str(checkpoint.resolve()),
                device="cpu",
            )
            output = dest / f"{obj}.json.gz"
            record = read_gzip(output) if output.is_file() else {}
            if record.get("binding") != binding or not has_error_split(record.get("score", {})):
                with tempfile.TemporaryDirectory(dir=dest) as tmp:
                    path = Path(tmp) / "score.json"
                    cpu_score(directory, checkpoint, path)
                    raw = read_json(path)
                    verify_score(raw, checkpoint, 1)
                    if not has_error_split(raw):
                        raise ValueError("Missing 6k error split")
                    write_gzip(output, dict(binding=binding, score=raw))
            else:
                raw = record["score"]
                verify_score(raw, checkpoint, 1)
            scores[obj] = raw
        after = summarize_scores(scores, support)
        split = {obj: score["overread_utility_error"] for obj, score in scores.items()}
        for obj, values in split.items():
            for src, modes in values.items():
                for mode, err in modes.items():
                    if (
                        err["n"]
                        != after["utility"][mode][obj]["sources"][src]["overread"]["numerator"]
                    ):
                        raise ValueError(
                            "Utility error decomposition has the wrong overread support"
                        )
        path = dest / "comparison.json"
        write_json(
            path,
            dict(
                seed=seed,
                existing_reader_feedback=156,
                new_reader_requests=0,
                new_fits=0,
                controller_gpu_hours=0,
                measured_continuation=TARGET,
                utility_lambda=PENALTY,
                cost_scale=SCALE,
                sources_2k=str(directory / "warm-11-direct-vs-paired.json"),
                scores_6k={o: str(dest / f"{o}.json.gz") for o in scores},
                observed_support=support,
                axes_6k=after,
                change_6k_minus_2k=changes(before, after),
                overread_utility_error_6k=split,
            ),
        )
    return path
