"""Bind zero-update, selected and final REF actors to the same official retrieval evaluation."""

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import yaml

STAGES = ("initial", "best", "final")
SCORES = {"support_f1": "f1", "support_coverage_em": "em", "gt_return": "return"}


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    part = path.with_suffix(".tmp")
    with part.open("w") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    part.replace(path)


def attest_initial_weights(actor, base):
    """Check every embedding/encoder tensor consumed by the one-output E5 forward in both towers."""
    import torch
    from qrag_ref_actor_delta import PREFIX
    from safetensors import safe_open

    counts = {}
    with torch.device("cpu"), safe_open(base, framework="pt", device="cpu") as original:
        for tower, prefix in PREFIX.items():
            found = set()
            for name, tensor in actor[tower].items():
                key = name.removeprefix(prefix)
                if not key.startswith(("embeddings.", "encoder.")):
                    continue
                expected = original.get_tensor(key).cpu()
                if tensor.dtype != expected.dtype or not torch.equal(
                    tensor.detach().cpu(), expected
                ):
                    raise ValueError(f"Zero-update actor differs from public E5 in {tower}.{name}")
                found.add(key)
            if not any(k.startswith("embeddings.") for k in found) or not any(
                k.startswith("encoder.layer.23.") for k in found
            ):
                raise ValueError("Incomplete E5 execution weights")
            counts[tower] = len(found)
    return counts


def attest_saved_initial(archive, base, run, receipt):
    import torch
    from qrag_ref_actor_delta import assemble

    codebook = torch.load(archive, map_location="cpu", mmap=True, weights_only=True)
    if (
        codebook["format"] != "qrag_e5_actor_delta_v1"
        or receipt["last_validation"]["optimizer_updates"] != 0
    ):
        raise ValueError("Wrong source for the zero-update evaluation")
    weights = assemble(codebook, base)
    counts = attest_initial_weights(weights, base)
    cfg = yaml.safe_load((run / "config.yaml").read_text())
    if not all(
        weights[k].keys() == set(codebook["shared"][k]) | set(codebook["stored"][k]) for k in counts
    ):
        raise ValueError("Incomplete source actor")
    return {
        "source_kind": "recorded_zero_update_actor",
        "archive": str(archive.resolve()),
        "seed": cfg["seed"],
        "optimizer_updates": 0,
        "upstream_run": str(run.resolve()),
        "forward_tensors_equal_to_public_E5": counts,
        "source_base": str(base.resolve()),
        "verification": "restored CPU tensors compared directly with public general E5",
    }


def register(run, initial_index, base, curve, *, initial_only=False):
    cfg_path = run / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    best = max(curve, key=lambda r: r["gt_dev_return"])
    initial = (
        read(initial_index)
        if initial_index.is_file()
        else {"source_kind": "seeded_public_E5_clone", "seed": cfg["seed"], "optimizer_updates": 0}
    )
    if initial["seed"] != cfg["seed"] or initial["optimizer_updates"] != 0:
        raise ValueError("Initial actor and retained fit have different seed or training exposure")
    if initial["source_kind"] == "recorded_zero_update_actor":
        origin = yaml.safe_load((Path(initial["upstream_run"]) / "config.yaml").read_text())
        same_recipe = all(
            origin[k] == cfg[k]
            for k in ("seed", "max_action_length", "max_action_length_in_memory")
        )
        if (
            not same_recipe
            or origin["algo"]["model"]["predictor"] != cfg["algo"]["model"]["predictor"]
            or origin["envs"]["positions_processor"] != cfg["envs"]["positions_processor"]
        ):
            raise ValueError("Recorded zero-update origin and retained official E5 recipe differ")
    # Predeclare the post-fit diagnostic only for a persisting GT drop on the
    # fixed task roster. These TRAIN observations do not enter model selection.
    initial_gt = curve[0]["gt_dev_return"]
    design = {
        "enabled": bool(
            curve[-1]["gt_dev_return"] < initial_gt
            and np.mean([r["gt_dev_return"] for r in curve[-5:]]) < initial_gt
        ),
        "seed": 20261125,
        "pairs": 32,
        "trigger": "Final GT and mean of final five GT validations both below initialization",
    }
    spec = {
        "initial": (0, None, None),
        "best": (best["optimizer_updates"], "best", "best"),
        "final": (curve[-1]["optimizer_updates"], "last", "last"),
    }
    if initial_only:
        spec = {"initial": spec["initial"]}
        design = dict(design, enabled=False, awaiting_terminal_curve=True)
    for label, (step, native, archive) in spec.items():
        directory = run / "retrieval" / label
        directory.mkdir(parents=True, exist_ok=True)
        binding = {
            "stage": label,
            "optimizer_updates": step,
            "seed": cfg["seed"],
            "base": str(base.resolve()),
            "source_run": str(run.resolve()),
            "native_checkpoint": str(Path(cfg["checkpoint_dir"]) / f"model_{native}.pt")
            if native
            else None,
            "durable_archive": str(run / "actors" / f"{archive}.zip") if archive else None,
            "initial_source": initial if label == "initial" else None,
            "terminal_td_probe": design,
        }
        if (directory / "config.yaml").is_file() and (
            directory / "config.yaml"
        ).read_bytes() != cfg_path.read_bytes():
            raise ValueError("Saved evaluation changed the official training configuration")
        metadata = directory / "actor-binding.json"
        if metadata.is_file() and read(metadata) != binding:
            old = read(metadata)
            old_design = old.get("terminal_td_probe", {})
            if label != "initial" or dict(old, terminal_td_probe=design) != binding:
                raise ValueError("Terminal evaluation already bound to another actor")
            if initial_only and not old_design.get("awaiting_terminal_curve"):
                # The complete run already resolved the predeclared TRAIN probe.
                continue
            if not old_design.get("awaiting_terminal_curve") or any(
                old_design.get(key) != design[key] for key in ("seed", "pairs", "trigger")
            ):
                raise ValueError("Initial evaluation has a different diagnostic protocol")
        (directory / "config.yaml").write_bytes(cfg_path.read_bytes())
        save(metadata, binding)


def load_bound_actor(agent, binding):
    import torch
    from qrag_ref_actor_delta import assemble, read_xor_archive

    stage, base = binding["stage"], binding["base"]
    if stage == "initial":
        if agent.policy.state_embed.n_output != 1 or agent.critic.action_embed.model.n_output != 1:
            raise ValueError("The initial E5 attestation requires official single-output pooling")
        source = binding["initial_source"]
        if source["source_kind"] == "recorded_zero_update_actor":
            with torch.device("cpu"):
                delta = torch.load(
                    source["archive"], map_location="cpu", weights_only=True, mmap=True
                )
                if delta["format"] != "qrag_e5_actor_delta_v1":
                    raise ValueError("Invalid initial actor delta")
                actor = assemble(delta, base)
            agent.policy.load_state_dict(actor["policy"], strict=True)
            agent.critic.action_embed.load_state_dict(actor["action_embed"], strict=True)
            agent.alpha = actor["alpha"]
        elif source["source_kind"] != "seeded_public_E5_clone":
            raise ValueError("Unknown initial actor source")
        verified = attest_initial_weights(
            {
                "policy": agent.policy.state_dict(),
                "action_embed": agent.critic.action_embed.state_dict(),
            },
            base,
        )
        if source.get("forward_tensors_equal_to_public_E5", verified) != verified:
            raise ValueError("Execution and zero-update source verification disagree")
        return {"transport": source["source_kind"], "functional_base_equal_tensors": verified}
    native = Path(binding["native_checkpoint"])
    if native.is_file():
        agent.load(str(native), strict=True)
        return {"transport": "upstream_native_actor"}
    archived = Path(binding["durable_archive"])
    receipt = read(archived.with_suffix(".json"))
    if receipt["optimizer_updates"] != binding["optimizer_updates"]:
        raise ValueError("Durable actor does not match its scheduled update")
    with torch.device("cpu"):
        actor, _ = read_xor_archive(archived, base)
    agent.policy.load_state_dict(actor["policy"], strict=True)
    agent.critic.action_embed.load_state_dict(actor["action_embed"], strict=True)
    agent.alpha = actor["alpha"]
    return {"transport": "verified_lossless_actor_archive"}


def verify_common(common):
    required = {
        "seed": 42,
        "groups": 300,
        "max_steps": 4,
        "dataset": "musique",
        "feedback": "GroundTruthFeedback",
        "never_terminate": False,
        "penalize_extra_steps": False,
        "per_fact_reward": 0.0,
        "completion_reward": 1.0,
        "reader_calls": 0,
    }
    if any(common.get(k) != v for k, v in required.items()):
        raise ValueError("Native retrieval differs from the registered GT protocol")


def retrieval_protocol(cfg, env):
    feedback = env.feedback_model
    common = {
        "seed": int(cfg.seed),
        "dataset": cfg.envs.task,
        "data_path": cfg.envs.data_path,
        "groups": len(env.dataset),
        "max_steps": env.max_steps,
        "sort_by_index": env.sort_by_index,
        "feedback": type(feedback).__name__,
        "never_terminate": feedback.never_terminate,
        "penalize_extra_steps": feedback.penalize_extra_steps,
        "per_fact_reward": float(feedback.per_fact_reward),
        "completion_reward": float(feedback.completion_reward),
        "action_length": env.action_embed_length,
        "action_length_in_memory": env.max_action_length_in_memory,
        "positions": type(env.positions_processor).__name__,
        "native_evaluator": "upstream eval_retriever.evaluate_episode greedy",
        "reader_calls": 0,
        "device": str(cfg.device),
        "state_chunk_tokens": int(cfg.algo.pqn.hyperparams.max_action_length_in_memory),
    }
    verify_common(common)
    return common


def record_protocol(cfg, env, binding, witness):
    common = retrieval_protocol(cfg, env)
    if common["seed"] != binding["seed"]:
        raise ValueError("Selection seed differs between actor and evaluator")
    destination = Path(cfg.pretrained_path) / "native-protocol.json"
    if destination.is_file() and read(destination)["common"] != common:
        raise ValueError("Cannot append validation rows under changed retrieval semantics")
    save(
        destination,
        {
            "common": common,
            "stage": binding["stage"],
            "optimizer_updates": binding["optimizer_updates"],
            "actor_origin": witness,
        },
    )


def grade_row(row):
    pred, truth = set(row["pred_idx"]), set(row["sf_idx"])
    if not truth or len(row["pred_idx"]) != len(pred) or not 1 <= len(pred) <= 4:
        raise ValueError("Malformed official support-index trajectory")
    common = len(pred & truth)
    expected = {
        "f1": 2 * common / (len(pred) + len(truth)),
        "em": float(truth <= pred),
        "return": float(truth <= pred),
    }
    if any(not math.isclose(row[k], v, abs_tol=1e-8) for k, v in expected.items()):
        raise ValueError("Native output differs from registered support-coverage and GT semantics")
    return [row[k] for k in SCORES.values()]


def attempts(directory):
    measured = list(
        map(json.loads, (directory / "validation-resource.jsonl").read_text().splitlines())
    )
    if not measured or measured[-1]["exit_code"] != 0:
        raise ValueError("Retriever evaluation has no successful terminal invocation")
    launches = directory / "validation-launches.jsonl"
    n = len(launches.read_text().splitlines()) if launches.is_file() else None
    return {
        "settled_invocations": len(measured),
        "launches": n,
        "unsettled_invocations": max(0, n - len(measured)) if n is not None else None,
        "one_gpu_job_hours": sum(r["elapsed_seconds"] for r in measured) / 3600,
    }


def probe_summary(run, stage, binding, prior_design, prior_cases):
    design = binding.get("terminal_td_probe")
    if not design or not design["enabled"]:
        return None, prior_design, prior_cases
    file = run / "retrieval" / stage / "terminal-td-probe.json"
    probe = read(file)
    cases = [
        (r["train_id"], r["prefix"], r["actions"], r["terminal_rewards"]) for r in probe["pairs"]
    ]
    if (
        len(cases) != design["pairs"]
        or probe["optimizer_steps"]
        or probe["reader_calls"]
        or probe["design"] != design
        or probe["optimizer_updates"] != binding["optimizer_updates"]
        or (prior_design is not None and prior_design != design)
        or (prior_cases is not None and prior_cases != cases)
    ):
        raise ValueError("Terminal target diagnostic changed its matched source pairs or weights")
    return (
        {**{k: v for k, v in probe.items() if k != "pairs"}, "per_pair_result": str(file)},
        design,
        cases,
    )


def evaluation_q_summary(rows):
    values = [
        r
        for r in rows
        if len(r.get("q_values", [])) == len(r["pred_idx"])
        and all(math.isfinite(q) for q in r["q_values"])
    ]
    if not values:
        return {"observed": 0}
    roots = [r["q_values"][0] for r in values]
    gaps = []
    for r in values:
        gt = set(r["sf_idx"])
        gaps.append(int(r["pred_idx"][0] in gt))
    success = [r["q_values"][0] for r in values if r["return"]]
    failure = [r["q_values"][0] for r in values if not r["return"]]
    return {
        "observed": len(values),
        "missing_or_nonfinite": len(rows) - len(values),
        "first_action_support_rate": float(np.mean(gaps)),
        "chosen_root_q_median": float(np.median(roots)),
        "chosen_root_q_sd": float(np.std(roots)),
        "mean_root_q_on_completion": float(np.mean(success)) if success else None,
        "mean_root_q_on_failure": float(np.mean(failure)) if failure else None,
        "scope": "Deployed online scores of greedy selected TUNE chunks.",
    }


def read_path_summary(indexed, initial=None):
    """Count support actually delivered by each prefix of recorded greedy retrievals."""
    curves = []
    rows = list(indexed.values())
    for reads in range(1, 5):
        counts = [
            (len(set(r["pred_idx"][:reads]) & set(r["sf_idx"])), len(set(r["sf_idx"])))
            for r in rows
        ]
        curves.append(
            {
                "reads_up_to": reads,
                "questions": len(rows),
                "questions_with_a_support": sum(found > 0 for found, _ in counts),
                "questions_with_all_supports": sum(found == total for found, total in counts),
                "mean_support_recall": float(np.mean([found / total for found, total in counts])),
            }
        )
    report = {"observed_prefixes": curves}
    if initial is not None:
        if indexed.keys() != initial.keys() or any(
            set(r["sf_idx"]) != set(initial[q]["sf_idx"]) for q, r in indexed.items()
        ):
            raise ValueError("First-read contrast requires matching questions and support sets")
        matched = [q for q, r in indexed.items() if r["pred_idx"][0] == initial[q]["pred_idx"][0]]
        report["same_first_object"] = {
            "questions": len(matched),
            "initial_complete": sum(int(initial[q]["em"]) for q in matched),
            "actor_complete": sum(int(indexed[q]["em"]) for q in matched),
            "mean_paired_f1_difference": (
                float(np.mean([indexed[q]["f1"] - initial[q]["f1"] for q in matched]))
                if matched
                else None
            ),
        }
    return report


def paired_evaluation(run, roster, curve):
    ids = sorted(roster["groups"])
    if len(ids) != 300 or len(set(ids)) != 300 or roster["role"] != "TUNE" or roster["n"] != 300:
        raise ValueError("Expected 300 distinct fixed TUNE source IDs")
    reports = {}
    arrays = {}
    gold = None
    common = None
    best = max(curve, key=lambda r: r["gt_dev_return"])
    checkpoints = {"initial": curve[0], "best": best, "final": curve[-1]}
    prior_design = prior_cases = None
    first_design = None
    initial_rows = None
    for stage in STAGES:
        path = run / "retrieval" / stage
        witness = read(path / "native-protocol.json")
        binding = read(path / "actor-binding.json")
        if stage == "initial":
            first_design = binding.get("terminal_td_probe")
        elif binding.get("terminal_td_probe") != first_design:
            raise ValueError("Gradient probe trigger differs between actors")
        if (
            witness["stage"] != stage
            or binding["stage"] != stage
            or witness["optimizer_updates"] != checkpoints[stage]["optimizer_updates"]
            or binding["optimizer_updates"] != witness["optimizer_updates"]
        ):
            raise ValueError("Receipt is for the wrong terminal actor")
        if common is not None and witness["common"] != common:
            raise ValueError("Retrieval settings differ between actors")
        common = witness["common"]
        verify_common(common)
        items = [json.loads(line) for line in (path / "eval_seed42.jsonl").read_text().splitlines()]
        indexed = {r["id"]: r for r in items}
        if len(items) != len(ids) or sorted(indexed) != ids:
            raise ValueError("Retrieval records do not cover the registered native IDs")
        supports = [set(indexed[i]["sf_idx"]) for i in ids]
        if gold is not None and gold != supports:
            raise ValueError("Support facts differ across the paired native questions")
        gold = supports
        values = np.asarray([grade_row(indexed[i]) for i in ids], dtype=np.float64)
        arrays[stage] = values
        means = dict(zip(SCORES, values.mean(axis=0).tolist(), strict=True))
        probe, prior_design, prior_cases = probe_summary(
            run, stage, binding, prior_design, prior_cases
        )
        resource = attempts(path)
        probe_seconds = probe["assigned_gpu_seconds"] if probe else 0.0
        resource.update(
            measured_terminal_probe_gpu_seconds=probe_seconds,
            one_gpu_retrieval_hours_excluding_probe=(
                resource["one_gpu_job_hours"] - probe_seconds / 3600
                if resource["unsettled_invocations"] == 0
                and resource["one_gpu_job_hours"] >= probe_seconds / 3600
                else None
            ),
        )
        reports[stage] = {
            "read_path": read_path_summary(indexed, initial_rows),
            "terminal_gradient_probe": probe,
            "chosen_online_q": evaluation_q_summary(items),
            "optimizer_updates": witness["optimizer_updates"],
            "means": means,
            "origin": witness["actor_origin"],
            "resource": resource,
            "matches_logged_gt_return": math.isclose(
                means["gt_return"], checkpoints[stage]["gt_dev_return"], abs_tol=1e-8
            ),
        }
        if stage == "initial":
            initial_rows = indexed
    draws = np.random.default_rng(20261125).integers(0, len(ids), (5000, len(ids)))
    pairs = {}
    per_question = [
        {
            "id": i,
            "native_scores": {
                stage: dict(zip(SCORES, arrays[stage][j].tolist(), strict=True)) for stage in STAGES
            },
        }
        for j, i in enumerate(ids)
    ]
    for left, right in (("best", "initial"), ("final", "initial"), ("final", "best")):
        delta = arrays[left] - arrays[right]
        tag = f"{left}_minus_{right}"
        pairs[tag] = {}
        for col, axis in enumerate(SCORES):
            d = delta[:, col]
            pairs[tag][axis] = {
                "mean_delta": float(d.mean()),
                "conditional_interval_95": np.quantile(
                    d[draws].mean(axis=1), [0.025, 0.975]
                ).tolist(),
                "improved": int((d > 1e-10).sum()),
                "regressed": int((d < -1e-10).sum()),
                "tied": int((abs(d) <= 1e-10).sum()),
            }
        for row, ds in zip(per_question, delta, strict=True):
            row[tag] = dict(zip(SCORES, ds.tolist(), strict=True))
    delta_path = run / "paired-native-retrieval.jsonl"
    partial = delta_path.with_suffix(".part")
    partial.write_text("".join(json.dumps(v) + "\n" for v in per_question))
    partial.replace(delta_path)
    base_gt = reports["initial"]["means"]["gt_return"]
    tail = [r["gt_dev_return"] for r in curve[-5:]]
    compatible = all(r["matches_logged_gt_return"] for r in reports.values())
    final = pairs["final_minus_initial"]
    sustained = (
        compatible
        and all(t > base_gt for t in tail)
        and all(
            final[k]["conditional_interval_95"][0] > 0
            for k in ("support_f1", "support_coverage_em")
        )
    )

    def direction(v):
        return "higher" if v > 1e-10 else "lower" if v < -1e-10 else "tied"

    directions = {
        tag: {k: direction(row["mean_delta"]) for k, row in metrics.items()}
        for tag, metrics in pairs.items()
    }
    best_gain = all(
        pairs["best_minus_initial"][axis]["mean_delta"] > 1e-10
        for axis in ("support_f1", "support_coverage_em")
    )
    final_loss = all(
        final[axis]["mean_delta"] < -1e-10 for axis in ("support_f1", "support_coverage_em")
    )
    if not compatible:
        pattern = "unestablished_logged_GT_readback_disagreement"
    elif sustained:
        pattern = "sustained_gain_on_fixed_development_roster"
    elif final_loss:
        pattern = "selected_best_gain_with_final_degradation" if best_gain else "final_degradation"
    elif best_gain:
        pattern = "selected_best_gain_without_established_sustained_gain"
    else:
        pattern = "mixed_or_unestablished_gain"
    return {
        "actors": reports,
        "paired_differences": pairs,
        "common_protocol": common,
        "observed_pattern": pattern,
        "best_improved_both_support_metrics": best_gain,
        "final_regressed_both_support_metrics": final_loss,
        "directions": directions,
        "last_five_logged_gt_returns": tail,
        "all_three_gt_readbacks_agree": compatible,
        "sustained_gain_on_fixed_tune": "observed" if sustained else "not_established",
        "sustained_definition": (
            "All final five GT returns above initialization, all logged GT means reproduced, "
            "and positive paired 95% lower endpoints for final F1 and coverage EM."
        ),
        "scope": (
            "Single training seed and fixed development questions. Best was chosen on this roster. "
            "Paired intervals are conditional on the actors."
        ),
        "bootstrap": {"unit": "native question", "paired_draws": 5000, "seed": 20261125},
        "per_question_deltas": str(delta_path),
        "reader_calls": 0,
    }


def complete_stage(directory, roster):
    """A successful immutable native readback can be reused after another actor's interruption."""
    try:
        attempts(directory)
        cfg = read(directory / "actor-binding.json")
        rec = read(directory / "native-protocol.json")
        if (
            cfg.get("terminal_td_probe", {}).get("enabled")
            and not (directory / "terminal-td-probe.json").is_file()
        ):
            return False
        if (cfg["stage"], cfg["optimizer_updates"]) != (rec["stage"], rec["optimizer_updates"]):
            return False
        records = [
            json.loads(line) for line in (directory / "eval_seed42.jsonl").read_text().splitlines()
        ]
        return len(records) == 300 and {r["id"] for r in records} == set(read(roster)["groups"])
    except (FileNotFoundError, KeyError, ValueError):
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("register")
    prepare.add_argument("--initial-only", action="store_true")
    for key in ("run", "base", "initial-index"):
        prepare.add_argument("--" + key, type=Path, required=True)
    capture = sub.add_parser("attest-initial")
    for key in ("source-run", "archive", "base", "cutover", "output"):
        capture.add_argument("--" + key, type=Path, required=True)
    closed = sub.add_parser("check-stage")
    closed.add_argument("--directory", type=Path, required=True)
    closed.add_argument("--roster", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "attest-initial":
        save(
            args.output,
            attest_saved_initial(args.archive, args.base, args.source_run, read(args.cutover)),
        )
        raise SystemExit(0)
    if args.command == "check-stage":
        raise SystemExit(0 if complete_stage(args.directory, args.roster) else 1)
    from qrag_ref_result import complete_curve, measured_curve

    curve = measured_curve(args.run) if args.initial_only else complete_curve(args.run)
    if not curve:
        raise ValueError("The measured initialization is required")
    register(
        args.run.resolve(), args.initial_index, args.base, curve, initial_only=args.initial_only
    )
