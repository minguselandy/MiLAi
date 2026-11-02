"""Verify the declared encoder-scope/soft-target controls over the frozen Q baseline."""
from __future__ import annotations

import argparse
import copy
import json
import struct
import time
from pathlib import Path
from typing import Any

from analyze_feedback_fit import analyze
from analyze_quality_feedback_fit import quality_analysis_plan
from milai_lab.harness.artifact_io import read_json, write_json


def regularization_analysis_plan(
    study: dict[str, Any], quality: dict[str, Any], original: dict[str, Any],
) -> dict[str, Any]:
    """Allow the two declared interventions without changing the matched Q recipe."""
    base = quality_analysis_plan(quality, original)
    baseline, = [p for p in base["plans"] if p["quality_mode"] == "quality-direction"]
    if (study["baseline_run_id"] != baseline["run_id"]
            or study["common_initialization"] != quality["common_initialization"]
            or study["base_runtime"] != quality["base_runtime"]
            or study["label_smoothing"] != .05
            or [p["intervention"] for p in study["plans"]] != ["freeze-encoder", "soft-target"]):
        raise ValueError("Regularization changed its baseline or declared interventions")
    plans = []
    for spec in study["plans"]:
        argv = list(spec["argv"])
        entry = next(i for i, arg in enumerate(argv)
                     if Path(arg).name == "train_bounded_laya.py")
        if (argv[entry + 3] != spec["output"]
                or argv[argv.index("--compute-phase") + 1] != spec["compute_phase"]
                or spec["source_cohort"] != baseline["source_cohort"]
                or spec["cwd"] != baseline["cwd"] or spec["arm"] != "answer"):
            raise ValueError("Regularization output/data/runtime binding changed")
        expected_environment = copy.deepcopy(baseline["environment"])
        if spec["intervention"] == "freeze-encoder":
            if argv.count("--freeze-encoder") != 1 or "--pair-label-smoothing" in argv:
                raise ValueError("Encoder control must change only the update scope")
            argv.remove("--freeze-encoder")
        else:
            if (argv.count("--pair-label-smoothing") != 1 or "--freeze-encoder" in argv
                    or Path(argv[entry]) != Path(study["training_overlay"])
                    / "train_bounded_laya.py"):
                raise ValueError("Soft-target control changed scope or training overlay")
            flag = argv.index("--pair-label-smoothing")
            if float(argv[flag + 1]) != study["label_smoothing"]:
                raise ValueError("Soft-target strength differs from the fixed declared value")
            del argv[flag:flag + 2]
            argv[entry] = baseline["argv"][entry]
            expected_environment["PYTHONPATH"] = ":".join((
                str(Path(study["base_runtime"]) / "src"), study["training_overlay"],
                str(Path(study["base_runtime"]) / "tools")))
        argv[entry + 3] = baseline["output"]
        argv[argv.index("--compute-phase") + 1] = baseline["compute_phase"]
        if argv != baseline["argv"] or spec["environment"] != expected_environment:
            raise ValueError("Regularization changed matched targets, draws, budget or environment")
        plans.append({**copy.deepcopy(spec), "quality_mode": "quality-direction"})
    return {"source_version": base["source_version"] + "+regularization-overlay-v1",
            "protocol": base["protocol"], "plans": plans,
            "baseline_run_id": baseline["run_id"]}


def checkpoint_tensor_changes(base: Path, checkpoint: Path) -> dict[str, Any]:
    """Compare stored tensor bytes directly, without loading models or computing digests."""
    with base.open("rb") as before, checkpoint.open("rb") as after:
        size_a = struct.unpack("<Q", before.read(8))[0]
        size_b = struct.unpack("<Q", after.read(8))[0]
        left, right = json.loads(before.read(size_a)), json.loads(after.read(size_b))
        left.pop("__metadata__", None)
        right.pop("__metadata__", None)
        if left.keys() != right.keys() or any(
                (a["dtype"], a["shape"]) != (right[name]["dtype"], right[name]["shape"])
                for name, a in left.items()):
            raise ValueError("Saved parameter schema changed from the common initialization")
        groups: dict[str, dict[str, Any]] = {
            name: {"tensors": 0, "changed_tensors": [], "tensor_payload_bytes": 0}
            for name in ("encoder", "non_encoder")}
        for name, a in left.items():
            start_a, end_a = a["data_offsets"]
            start_b, end_b = right[name]["data_offsets"]
            if end_a - start_a != end_b - start_b:
                raise ValueError("Saved tensor byte extents changed")
            group = groups["encoder" if name.startswith("encoder.") else "non_encoder"]
            group["tensors"] += 1
            group["tensor_payload_bytes"] += end_a - start_a
            before.seek(8 + size_a + start_a)
            after.seek(8 + size_b + start_b)
            remaining = end_a - start_a
            changed = False
            while remaining:
                count = min(8 * 1024 * 1024, remaining)
                x, y = before.read(count), after.read(count)
                if len(x) != count or len(y) != count:
                    raise ValueError("Stored tensor payload is incomplete")
                changed |= x != y
                remaining -= count
            if changed:
                group["changed_tensors"].append(name)
    if not all(group["tensors"] for group in groups.values()):
        raise ValueError("Parameter-scope verification needs encoder and non-encoder tensors")
    return {"base": str(base), "checkpoint": str(checkpoint), "groups": groups,
            "scope": "Exact stored tensor-byte comparison at saved points; not intermediate "
                     "optimizer history or per-example gradient attribution. No SHA or digest."}


def verify_parameter_scope(native: dict[str, Any]) -> list[dict[str, Any]]:
    base = Path(native["recipe"]["base_checkpoint"]) / "model.safetensors"
    results = []
    for point in native["curve"]:
        if point["update"] == 0:
            continue
        result = checkpoint_tensor_changes(base, Path(point["checkpoint"]) / "model.safetensors")
        if native["recipe"]["freeze_encoder"] and result["groups"]["encoder"]["changed_tensors"]:
            raise ValueError("Frozen encoder changed in a saved checkpoint")
        results.append({"update": point["update"], **result})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("quality_plan", type=Path)
    parser.add_argument("original_plan", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    study = read_json(args.study)
    plan = regularization_analysis_plan(
        study, read_json(args.quality_plan), read_json(args.original_plan))
    spec, = [p for p in plan["plans"] if p["run_id"] == args.run_id]
    result = analyze(plan, args.run_id, quality_mode="quality-direction",
        pair_label_smoothing=(study["label_smoothing"]
                              if spec["intervention"] == "soft-target" else None))
    result.update(intervention=spec["intervention"], baseline_run_id=study["baseline_run_id"],
        saved_parameter_scope=verify_parameter_scope(result), study=str(args.study.resolve()),
        model_calls=0, ledger_recorded=False, cpu_seconds_pending=time.process_time() - started,
        no_sha_validation=True)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "analysis.json", result)
    print(result["status"], result["intervention"], result["in_memory_selection"])


if __name__ == "__main__":
    main()
