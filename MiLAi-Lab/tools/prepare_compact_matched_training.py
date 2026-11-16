"""Prepare a compact counterpart of the original operation and feedback training chain."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json

COMPACT_BRANCH = """    if projection == "compact_actions":
        state = payload["state"]
        decoded = json.loads(state) if isinstance(state, str) else state
        shared = project_operation_payload({**payload, "state": decoded}, "shared_actions")
        return {**shared, "state": json.dumps(shared["state"], ensure_ascii=False,
                                              separators=(",", ":"), allow_nan=False)}
"""
PROJECTION_ENTRY = (
    '    """Project matched training/live inputs; '
    'task and actual operation options stay fixed."""\n'
)
OLD_CHOICES = '"shared_actions", "shared_actions_request_text"),'
NEW_CHOICES = (
    '"shared_actions", "shared_actions_request_text",\n'
    '                            "compact_actions"),'
)


def extend_runtime(source: Path, target: Path) -> dict[str, Any]:
    """Three explicit source edits; removing them reproduces every original byte."""
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"),
    )
    changed = []
    relative = Path("src/milai_lab/methods/laya_memory_policy.py")
    old = (source / relative).read_text()
    if old.count(PROJECTION_ENTRY) != 1 or 'projection == "compact_actions"' in old:
        raise ValueError("Expected the unmodified original operation projection")
    new = old.replace(PROJECTION_ENTRY, PROJECTION_ENTRY + COMPACT_BRANCH)
    (target / relative).write_text(new)
    if new.replace(COMPACT_BRANCH, "") != old:
        raise ValueError("Compact projection changed more than its explicit branch")
    changed.append(str(relative))
    for name in ("train_bounded_laya.py", "evaluate_bounded_laya.py"):
        relative = Path("tools") / name
        old = (source / relative).read_text()
        if old.count(OLD_CHOICES) != 1:
            raise ValueError("Expected one original operation-state CLI choice list")
        new = old.replace(OLD_CHOICES, NEW_CHOICES)
        (target / relative).write_text(new)
        if new.replace(NEW_CHOICES, OLD_CHOICES) != old:
            raise ValueError("Compact CLI admission changed unrelated code")
        changed.append(str(relative))
    unchanged = 0
    for folder in ("src", "tools"):
        for path in (source / folder).rglob("*.py"):
            relative_name = str(path.relative_to(source))
            if relative_name not in changed:
                if path.read_bytes() != (target / relative_name).read_bytes():
                    raise ValueError("An unrelated original runtime source changed")
                unchanged += 1
    return {
        "base": str(source.resolve()),
        "runtime": str(target.resolve()),
        "changed_files": changed,
        "unchanged_python_files": unchanged,
        "reverse_edits_recover_original_bytes": True,
        "scope": "Only compact_actions admission and JSON syntax whitespace. Original shared "
        "projection, instructions, data, optimizer, sampling, losses and evaluators remain intact. "
        "Request-text is a separate unchanged condition. No model result or input-fit proof.",
    }


def compact_spec(
    original: dict[str, Any],
    runtime: Path,
    output: Path,
    phase: str,
    *,
    unbound_init: bool,
) -> dict[str, Any]:
    result = {
        "run_id": original["run_id"],
        "argv": copy.deepcopy(original["argv"]),
        "environment": copy.deepcopy(original["environment"]),
    }
    argv = result["argv"]
    entry = next(i for i, a in enumerate(argv) if Path(a).name == "train_bounded_laya.py")
    if argv[argv.index("--operation-state") + 1] != "shared_actions":
        raise ValueError("Compact counterpart requires the original shared-actions recipe")
    argv[entry] = str(runtime / "tools/train_bounded_laya.py")
    argv[entry + 3] = str(output)
    argv[argv.index("--operation-state") + 1] = "compact_actions"
    argv[argv.index("--compute-phase") + 1] = phase
    if unbound_init:
        argv[entry + 2] = None
    result.update(
        output=str(output),
        compute_phase=phase,
        cwd=str(runtime),
        status="PENDING_COMPACT_OPERATION_SAVED_SELECTION" if unbound_init else "PREPARED_NOT_RUN",
        initialization_pending=unbound_init,
    )
    result["environment"]["PYTHONPATH"] = str(runtime / "src") + ":" + str(runtime / "tools")
    # This verifies the full command, rather than a selected list of favorable settings.
    restored = list(argv)
    restored[entry] = original["argv"][entry]
    restored[entry + 2] = original["argv"][entry + 2]
    restored[entry + 3] = original["argv"][entry + 3]
    restored[restored.index("--operation-state") + 1] = "shared_actions"
    restored[restored.index("--compute-phase") + 1] = original["argv"][
        original["argv"].index("--compute-phase") + 1
    ]
    if restored != original["argv"]:
        raise ValueError("Compact recipe changed the original exposure/optimization command")
    result["original_command_equal_except_declared_fields"] = True
    return result


def prepare(
    baseline_spec: Path, nine_plan: Path, output: Path, *, saved_runtime: Path
) -> dict[str, Any]:
    baseline = read_json(baseline_spec)["baseline_operation_spec"]
    original = read_json(nine_plan)
    (feedback,) = [
        r for r in original["plans"] if r["source_cohort"] == 128 and r["arm"] == "answer"
    ]
    old_op = Path(baseline["environment"]["PYTHONPATH"].split(":")[0]).parent
    old_feedback = Path(original["frozen_lab"])
    output.mkdir(parents=True, exist_ok=False)
    op_runtime, fb_runtime = (
        output / "operation-runtime/MiLAi-Lab",
        output / "feedback-runtime/MiLAi-Lab",
    )
    freezes = {
        "operation": extend_runtime(old_op, op_runtime),
        "feedback": extend_runtime(old_feedback, fb_runtime),
        "saved_cpu": extend_runtime(saved_runtime, output / "saved-runtime/MiLAi-Lab"),
    }
    saved_entry = output / "saved-runtime/MiLAi-Lab/tools/evaluate_bounded_laya.py"
    if "--disable-reference-compile" not in saved_entry.read_text():
        raise ValueError("Saved counterpart must retain the declared CPU evaluator compile control")
    operation = compact_spec(
        baseline,
        op_runtime,
        output / "operation-fit",
        "evidence_gap_compact_operation256_seed0_u524_v1",
        unbound_init=False,
    )
    operation["run_id"] = "compact-source256-operation-seed0-u524-v1"
    operation["source_version"] = old_op.parent.name + "+compact-whitespace-v1"
    after = compact_spec(
        feedback,
        fb_runtime,
        output / "feedback-fit",
        "evidence_gap_compact_feedback128_answer_seed0_u192_v1",
        unbound_init=True,
    )
    after["run_id"] = "compact-source128-answer-seed0-u192-v1"
    after.update(
        arm="answer",
        source_cohort=128,
        source_version=original["source_version"] + "+compact-whitespace-v1",
    )
    report = {
        "status": "MATCHED_COMPACT_CHAIN_PREPARED_INPUT_AND_ANALYZER_CHECKS_PENDING",
        "source_baseline_spec": str(baseline_spec.resolve()),
        "source_nine_plan": str(nine_plan.resolve()),
        "runtime_overlays": freezes,
        "operation": operation,
        "feedback_template": after,
        "original_operation_control": baseline,
        "original_feedback_control": feedback,
        "original_ledger": original["plans"][0]["argv"][
            original["plans"][0]["argv"].index("--budget") + 1
        ],
        "operation_selection": baseline["selection_rule"],
        "feedback_selection": "Original ANSWER saved-CPU macro on the fixed64 feedback states. "
        "earliest tie,update0 eligible;selected old860 and real Host still required.",
        "stages": "Full original operation exposure524/8384 from multilingual base, then original "
        "source128 ANSWER192/3072 from its actually selected compact operation checkpoint. "
        "Feedback initialization stays unbound; never treat shared u262 as compact-trained.",
        "scope": "Matched-format training pipeline, not solely inference formatting or pure loss. "
        "State/target/sampling/optimizer conditions match each historical counterpart; resulting "
        "weights and selected updates may differ. Original32/64/128,Q,regularization and newprefix "
        "studies remain unchanged. No all-variant compact Cartesian expansion is scheduled.",
        "gates": [
            "Complete original serialized queue first.",
            "Complete the existing30-position format/Host pilot; preserve failures.",
            "Verify original shared inputs, compact input lengths, native option permutations, "
            "targets, original training-plan draws and weights before fit admission.",
            "Prepare native/saved verifier bindings and preserve the original baseline masked64 "
            "position791 gap; no retry of that historical missing output.",
            "Bind compact feedback initialization only after actual complete compact operation "
            "saved-CPU selection and matching-train audit; then run all feedback checkpoints.",
        ],
        "actual_new_model_jobs": 0,
        "actual_Host_results": 0,
        "model_calls": 0,
        "ledger_recorded": False,
        "no_sha_validation": True,
    }
    write_json(output / "study.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_analysis_study", type=Path)
    parser.add_argument("nine_fit_plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--saved-runtime",
        type=Path,
        required=True,
        help="Original declared saved-CPU dependency freeze, including compile control",
    )
    args = parser.parse_args()
    cpu = time.process_time()
    result = prepare(
        args.baseline_analysis_study,
        args.nine_fit_plan,
        args.output,
        saved_runtime=args.saved_runtime,
    )
    receipt = {
        "status": result["status"],
        "study": str((args.output / "study.json").resolve()),
        "cpu_seconds_pending": time.process_time() - cpu,
        "ledger_recorded": False,
        "model_calls": 0,
        "no_sha_validation": True,
    }
    with (args.output / "preparation.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(receipt["status"])


if __name__ == "__main__":
    main()
