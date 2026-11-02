"""Prepare autonomous Host comparisons from the original nine fits and saved selections."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def prepare_study(nine_path: Path, output: Path) -> dict[str, Any]:
    """Keep original public histories/configuration; no model or outcome-based selection."""
    nine = read_json(nine_path)
    protocol = read_json(Path(nine["protocol"]))
    histories, origins = [], []
    for batch in protocol["dev_batches"]:
        fixture = read_json(Path(batch["histories"]))
        if [h["source_group"] for h in fixture["histories"]] != batch["groups"]:
            raise ValueError("Original dev batch no longer matches its declared source groups")
        histories.extend(copy.deepcopy(fixture["histories"]))
        origins.append({"path": batch["histories"], "groups": batch["groups"]})
    if (
        len(histories) != 8
        or len({h["source_group"] for h in histories}) != 8
        or any(h["split"] != "dev" or not h["continuous"] for h in histories)
        or sum(len(h["requests"]) for h in histories) != 16
    ):
        raise ValueError(
            "This original Host follow-up binds eight continuous dev histories/16 positions"
        )
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "histories.json", {"schema": fixture["schema"], "histories": histories})
    config = read_json(Path(protocol["bound_config"]))
    control = config["entrypoints"]["functional"]["memory_control"]
    if (
        control["checkpoint"] != nine["common_initialization"]
        or control["state_projection"] != "shared_actions"
        or control["max_len"] != 16384
        or control["head_max_len"] != 2048
        or control["device"] != "cpu"
        or control["threads"] != 4
    ):
        raise ValueError(
            "Original Host configuration differs from the declared initialization/input"
        )
    write_json(output / "config-template.json", config)
    fits = [
        {
            "run_id": p["run_id"],
            "objective": p["arm"],
            "source_cohort": p["source_cohort"],
            "fit_output": p["output"],
            "targets": ["answer", "delivery"] if p["arm"] == "continued-ce" else [p["arm"]],
        }
        for p in nine["plans"]
    ]
    if len(fits) != 9 or {(p["objective"], p["source_cohort"]) for p in fits} != {
        (arm, n) for arm in ("answer", "delivery", "continued-ce") for n in (32, 64, 128)
    }:
        raise ValueError("Keep all nine original fits and both predeclared CE selection views")
    report = {
        "schema": "original_feedback_autonomous_host_v1",
        "status": "PREPARED_NOT_BOUND",
        "nine_fit_plan": str(nine_path.resolve()),
        "protocol": nine["protocol"],
        "runtime": nine["frozen_lab"],
        "source_version": nine["source_version"],
        "histories": str((output / "histories.json").resolve()),
        "history_origins": origins,
        "config_template": str((output / "config-template.json").resolve()),
        "common_initialization": nine["common_initialization"],
        "fits": fits,
        "family_units": 8,
        "continuous_cold_banks_per_arm": 8,
        "positions_per_arm": 16,
        "controls": ["fixed_context", "rules", "jev_initialization"],
        "model_replicate": "seed0 fits; one predeclared Host trajectory per arm/history",
        "inference": {
            "device": "cpu",
            "visible_cuda_devices": "",
            "threads": 4,
            "max_len": 16384,
            "head_max_len": 2048,
            "operation_state": "shared_actions",
            "loaded_weight_dtype": "torch.float32",
            "mha_fastpath_enabled": False,
            "reference_compile_override": False,
        },
        "Host": "Same original Host model, temperature1, thinking, generation capacity, prompt, "
        "JSON-action protocol, source arrivals, return cap2048 and own continuing history. "
        "No forced retrieval or matched call-count requirement. Actual usage may differ.",
        "selection": "Use saved feedback-dev selections after verified retention closure. "
        "No Host outcome or old-retention metric changes a checkpoint. CE answer/delivery views "
        "stay separate; identical checkpoint paths share one execution with explicit aliases.",
        "denominators": "All declared16 positions per unique arm, including failed, zero-call, "
        "entered-without-result and unexecuted positions. Completion is not correctness.",
        "exposure": "Eight already exposed development families; no independent confirmation or "
        "Host-noise estimate. Decisive model seeds0/1/2 and broader confirmation remain required.",
        "quality": "Source-authored review of actual new Host answers and supporting receipts, "
        "separate from execution status. No copying original collector grades to new outputs.",
        "automatic_retry": False,
        "model_calls": 0,
        "quality_labels": [],
    }
    write_json(output / "study.json", report)
    return report


def inspect_bindings(study: dict[str, Any], saved_root: Path) -> dict[str, Any]:
    """Require both original selection and retention artifacts; pending fits remain explicit."""
    rows = []
    for fit in study["fits"]:
        root = saved_root / fit["run_id"]
        row: dict[str, Any] = {**fit, "status": "PENDING_SAVED_SELECTION_AND_RETENTION"}
        if not (root / "selection.json").is_file() or not (root / "retention.json").is_file():
            rows.append(row)
            continue
        selected, retention = read_json(root / "selection.json"), read_json(root / "retention.json")
        if (
            selected["status"] != "SAVED_CPU_FEEDBACK_SELECTION_VERIFIED"
            or retention["status"]
            != "SAVED_CPU_SELECTION_AND_RETENTION_VERIFIED;HOST_EVALUATION_PENDING"
            or selected["run_id"] != fit["run_id"]
            or retention["run_id"] != fit["run_id"]
            or selected["deployment_selection"] != retention["deployment_selection"]
            or set(selected["deployment_selection"]) != set(fit["targets"])
            or retention["conditions"] != study["inference"]
        ):
            raise ValueError(
                "Original saved selection/retention identity or inference conditions differ"
            )
        for target, point in selected["deployment_selection"].items():
            expected = (
                Path(study["common_initialization"])
                if point["update"] == 0
                else Path(fit["fit_output"]) / "checkpoints" / f"update-{point['update']}"
            )
            if (
                Path(point["checkpoint"]).resolve() != expected.resolve()
                or point["condition"] != study["inference"]
                or target not in retention["selected_old_operation"]
                or not (expected / "model.safetensors").is_file()
            ):
                raise ValueError("Selected checkpoint or actual retention binding is unavailable")
        row.update(
            status="READY",
            selection=str((root / "selection.json").resolve()),
            retention=str((root / "retention.json").resolve()),
            deployment_selection=selected["deployment_selection"],
        )
        rows.append(row)
    return {
        "status": "READY" if all(r["status"] == "READY" for r in rows) else "PENDING",
        "fits": rows,
        "ready_fits": sum(r["status"] == "READY" for r in rows),
    }


def bind_study(
    study: dict[str, Any],
    inspection: dict[str, Any],
    output: Path,
    *,
    python: str,
    attention_wrapper: str,
    inference_wrapper: str,
    host_site_packages: str | None = None,
) -> dict[str, Any]:
    """Bind exact saved checkpoints after all nine frozen closures; dispatch remains separate."""
    if inspection["status"] != "READY" or len(inspection["fits"]) != 9:
        raise ValueError("Complete all nine original saved/retention closures before Host dispatch")
    arms: list[dict[str, Any]] = [
        {"id": name, "policy": name, "aliases": []} for name in ["fixed_context", "rules"]
    ]
    arms.append(
        {
            "id": "jev_initialization",
            "policy": "laya",
            "checkpoint": study["common_initialization"],
            "aliases": ["original_source256_update262"],
        }
    )
    by_checkpoint = {str(Path(study["common_initialization"]).resolve()): arms[-1]}
    for fit in inspection["fits"]:
        for target, point in fit["deployment_selection"].items():
            key = str(Path(point["checkpoint"]).resolve())
            alias = {
                "run_id": fit["run_id"],
                "target": target,
                "update": point["update"],
                "selection": fit["selection"],
                "retention": fit["retention"],
            }
            if key not in by_checkpoint:
                new_arm: dict[str, Any] = {
                    "id": f"{fit['run_id']}-{target}-selected-u{point['update']}",
                    "policy": "laya",
                    "checkpoint": key,
                    "aliases": [],
                }
                arms.append(new_arm)
                by_checkpoint[key] = new_arm
            by_checkpoint[key]["aliases"].append(alias)
    output.mkdir(parents=True, exist_ok=False)
    runtime = Path(study["runtime"])
    for arm in arms:
        config = read_json(Path(study["config_template"]))
        settings = config["entrypoints"]["functional"]
        settings["memory_control"]["policy"] = arm["policy"]
        if "checkpoint" in arm:
            settings["memory_control"]["checkpoint"] = arm["checkpoint"]
        settings["config_version"] += "-host-followup-" + arm["id"]
        path = output / "configs" / (arm["id"] + ".json")
        write_json(path, config)
        destination = output / "runs" / arm["id"]
        arm.update(
            config=str(path.resolve()),
            output=str(destination.resolve()),
            status="NOT_EXECUTED",
            argv=[
                python,
                "-u",
                attention_wrapper,
                inference_wrapper,
                str(destination.resolve()) + "-inference.json",
                str(runtime / "tools/run_host_intent_retrieval.py"),
                str(path.resolve()),
                study["histories"],
                str(destination.resolve()),
                "--source-version",
                study["source_version"],
                "--policies",
                arm["policy"],
                "--interfaces",
                "rich",
                "--split",
                "dev",
                "--continue-host-history",
                "--capture-control-steps",
            ],
            cwd=str(runtime),
            environment={
                "PYTHONPATH": str(runtime / "src") + ":" + str(runtime / "tools"),
                "CUDA_VISIBLE_DEVICES": "",
                "TOKENIZERS_PARALLELISM": "false",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
        )
        if host_site_packages is not None:
            arm["argv"].extend(["--host-site-packages", host_site_packages])
    report = {
        "status": "ALL_ORIGINAL_SAVED_POLICIES_BOUND_NOT_EXECUTED",
        "study": study,
        "host_site_packages": host_site_packages,
        "bindings": inspection,
        "arms": arms,
        "unique_arms": len(arms),
        "planned_positions": len(arms) * study["positions_per_arm"],
        "automatic_retry": False,
        "model_calls": 0,
        "ledger": read_json(Path(study["config_template"]))["entrypoints"]["functional"][
            "budget_path"
        ],
    }
    write_json(output / "dispatch.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("nine_fit_plan", type=Path)
    inspect = commands.add_parser("inspect")
    bind = commands.add_parser("bind")
    for sub in (inspect, bind):
        sub.add_argument("study", type=Path)
        sub.add_argument("saved_root", type=Path)
    for flag in ("python", "attention-wrapper", "inference-wrapper"):
        bind.add_argument("--" + flag, required=True)
    bind.add_argument("--host-site-packages")
    for sub in (prepare, inspect, bind):
        sub.add_argument("output", type=Path)
    args = parser.parse_args()
    cpu = time.process_time()
    if args.mode == "prepare":
        result = prepare_study(args.nine_fit_plan, args.output)
        receipt = args.output / "preparation.json"
    else:
        study = read_json(args.study)
        result = inspect_bindings(study, args.saved_root)
        if args.mode == "bind":
            result = bind_study(
                study,
                result,
                args.output,
                python=args.python,
                attention_wrapper=args.attention_wrapper,
                inference_wrapper=args.inference_wrapper,
                host_site_packages=args.host_site_packages,
            )
            receipt = args.output / "binding.json"
        else:
            receipt = args.output
    result.update(
        cpu_seconds_pending=time.process_time() - cpu,
        ledger_recorded=False,
        model_calls=0,
        no_sha_validation=True,
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(result["status"])


if __name__ == "__main__":
    main()
