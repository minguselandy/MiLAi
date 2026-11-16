"""Declare only never-entered cold-bank positions after a retained Host interruption."""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json
from summarize_optimization_host import summarize_cohort
from summarize_original_feedback_host import position_bank


def arm_view(dispatch: dict[str, Any], arm_id: str) -> dict[str, Any]:
    (arm,) = [a for a in dispatch["arms"] if a["id"] == arm_id]
    view = copy.deepcopy(dispatch)
    view.update(
        arms=[copy.deepcopy(arm)],
        unique_arms=1,
        planned_positions=dispatch["study"]["positions_per_unique_arm"],
    )
    return view


def positions(fixture: dict[str, Any]) -> dict[tuple[str, str], str]:
    rows: dict[tuple[str, str], str] = {}
    for history in fixture["histories"]:
        for request in history["requests"]:
            key = history["id"], request["id"]
            if key in rows:
                raise ValueError("Original task identity repeats")
            rows[key] = position_bank(history, request)
    return rows


def subset(fixture: dict[str, Any], keys: set[tuple[str, str]]) -> dict[str, Any]:
    result = copy.deepcopy(fixture)
    result["histories"] = []
    for history in fixture["histories"]:
        requests = [q for q in history["requests"] if (history["id"], q["id"]) in keys]
        if requests:
            result["histories"].append(
                {**copy.deepcopy(history), "requests": copy.deepcopy(requests)}
            )
    return result


def segment_paths(parent: Path, arm_id: str) -> list[Path]:
    root = parent.parent / "continuations" / arm_id
    paths = []
    for directory in sorted(root.glob("segment-*")):
        path = directory / "dispatch.json"
        if not path.is_file():
            raise ValueError("Incomplete continuation preparation must be inspected first")
        paths.append(path)
    return paths


def expected_dispatch(
    parent_path: Path,
    parent: dict[str, Any],
    arm_id: str,
    output: Path,
    remaining: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    (original,) = [a for a in parent["arms"] if a["id"] == arm_id]
    study = copy.deepcopy(parent["study"])
    study.update(
        histories=str(output / "histories.json"),
        execution_id=study["execution_id"] + "-" + arm_id + "-" + output.name,
        positions_per_unique_arm=len(positions(remaining)),
        dispatch_scope=study["dispatch_scope"] + " Explicit unattempted-only continuation; "
        "original failed batch and original arm/cohort denominators remain separate.",
    )
    arm = copy.deepcopy(original)
    destination = output / "runs" / arm_id
    config = output / "configs" / (arm_id + ".json")
    replacements = {
        original["config"]: str(config),
        parent["study"]["histories"]: study["histories"],
        original["output"]: str(destination),
        original["output"] + "-inference.json": str(destination) + "-inference.json",
    }
    arm.update(
        config=str(config),
        output=str(destination),
        status="NOT_EXECUTED",
        argv=[replacements.get(arg, arg) for arg in original["argv"]],
    )
    dispatch = copy.deepcopy(parent)
    dispatch.update(
        study=study,
        arms=[arm],
        unique_arms=1,
        planned_positions=len(positions(remaining)),
        continuation={
            **provenance,
            "parent_dispatch": str(parent_path.resolve()),
            "parent_arm_id": arm_id,
        },
    )
    return dispatch


def audit_previous(parent_path: Path, arm_id: str, previous: list[Path]) -> dict[str, Any]:
    parent = read_json(parent_path)
    if (
        parent["status"] != "OPTIMIZATION_HOST_METHODS_BOUND_NOT_EXECUTED"
        or "continuation" in parent
    ):
        raise ValueError("Continuation is scoped to the declared optimization Host protocol")
    (original,) = [a for a in parent["arms"] if a["id"] == arm_id]
    fixture = read_json(Path(parent["study"]["histories"]))
    original_positions = positions(fixture)
    if len(original_positions) != parent["study"]["positions_per_unique_arm"]:
        raise ValueError("Original task denominator differs from its fixed fixture")
    attempted: dict[tuple[str, str], dict[str, Any]] = {}
    touched_banks: set[str] = set()
    owners: list[dict[str, Any]] = []
    for path in [parent_path, *previous]:
        dispatch = read_json(path)
        if path.resolve() != parent_path.resolve() and (
            Path(dispatch["continuation"]["parent_dispatch"]).resolve() != parent_path.resolve()
            or dispatch["continuation"]["parent_arm_id"] != arm_id
        ):
            raise ValueError("Prior continuation belongs to a different original comparison")
        (arm,) = [a for a in dispatch["arms"] if a["id"] == arm_id]
        current_fixture = read_json(Path(dispatch["study"]["histories"]))
        keys = set(positions(current_fixture))
        if (
            not keys <= original_positions.keys()
            or current_fixture != subset(fixture, keys)
            or dispatch["bindings"] != parent["bindings"]
            or any(
                dispatch["study"][key] != parent["study"][key]
                for key in ("runtime", "source_version", "inference")
            )
            or any(arm[key] != original[key] for key in ("policy", "environment"))
            or arm.get("checkpoint") != original.get("checkpoint")
            or read_json(Path(arm["config"])) != read_json(Path(original["config"]))
        ):
            raise ValueError("Prior segment changed an original task, model or condition")
        owner_path = path.parent / "orchestration" / arm_id / "driver.json"
        if not owner_path.is_file():
            raise ValueError(
                "A prepared attempt has no closed owner; inspect it before another segment"
            )
        owner = read_json(owner_path)
        if owner["status"] not in {
            "COMPLETED",
            "COMPLETED_WITH_NATIVE_FAILURES_RETAINED",
            "FAILED_RETAINED",
        }:
            raise ValueError("Every preceding attempt must be closed before continuation")
        if (
            Path(owner["dispatch"]).resolve() != path.resolve()
            or owner["arm_id"] != arm_id
            or owner["output"] != arm["output"]
            or owner["argv"] != arm["argv"]
            or owner["environment"] != arm["environment"]
        ):
            raise ValueError("Prior owner is not bound to its declared attempt")
        for process_key, marker in [("pid", str(owner_path.parent)), ("child_pid", arm["output"])]:
            try:
                argv = Path("/proc", str(owner[process_key]), "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError):
                argv = []
            if marker.encode() in argv:
                raise ValueError("A preceding owner is still alive")
        # This view verifies only this closed original arm/segment, never another live arm.
        summary = summarize_cohort(arm_view(dispatch, arm_id), [])
        for row in summary["positions"]:
            if row["execution"] == "NOT_EXECUTED":
                continue
            key = row["history"], row["request"]
            if key in attempted:
                raise ValueError("A task was already attempted in more than one retained segment")
            attempted[key] = {
                "history": key[0],
                "request": key[1],
                "bank": row["bank"],
                "execution": row["execution"],
                "result_status": row["result_status"],
                "result_path": row["result_path"],
                "dispatch": str(path.resolve()),
            }
            touched_banks.add(row["bank"])
        index = read_json(Path(arm["output"]) / (arm["policy"] + "-rich") / "bank-index.json")
        touched_banks.update(item["identity"]["bank"] for item in index)
        native_path = Path(arm["output"]) / "driver.json"
        owners.append(
            {
                "dispatch": str(path.resolve()),
                "owner": str(owner_path),
                "owner_record": owner,
                "native_driver": str(native_path),
                "native_record": read_json(native_path),
            }
        )
    remaining_keys = set(original_positions) - attempted.keys()
    if any(original_positions[key] in touched_banks for key in remaining_keys):
        raise ValueError(
            "Remaining positions share a touched bank; cold restart would lose actual history"
        )
    return {
        "parent": parent,
        "remaining_fixture": subset(fixture, remaining_keys),
        "provenance": {
            "schema": "unattempted-cold-bank-host-v1",
            "original_arm_positions": len(original_positions),
            "original_cohort_positions": parent["planned_positions"],
            "excluded_attempts": [attempted[k] for k in original_positions if k in attempted],
            "remaining_positions": [
                {"history": k[0], "request": k[1], "bank": bank}
                for k, bank in original_positions.items()
                if k in remaining_keys
            ],
            "touched_banks": sorted(touched_banks),
            "prior_owners": owners,
            "same_original_task_values": True,
            "all_remaining_banks_untouched": True,
            "failed_positions_retried": False,
            "scope": "Only never-entered cold banks. Same original requests, sources, model, "
            "caps and frozen runtime; new process/setup costs are real recovery costs. "
            "No inference-format switch, automatic retry, batch-success rewrite or "
            "additional independent samples.",
        },
    }


def validate_continuation(path: Path, *, for_launch: bool = False) -> dict[str, Any]:
    actual = read_json(path)
    meta = actual["continuation"]
    parent_path, arm_id = Path(meta["parent_dispatch"]), meta["parent_arm_id"]
    siblings = segment_paths(parent_path, arm_id)
    index = [p.resolve() for p in siblings].index(path.resolve())
    if for_launch and index != len(siblings) - 1:
        raise ValueError("A later continuation exists; this prepared attempt is stale")
    audit = audit_previous(parent_path, arm_id, siblings[:index])
    expected = expected_dispatch(
        parent_path,
        audit["parent"],
        arm_id,
        path.parent,
        audit["remaining_fixture"],
        audit["provenance"],
    )
    if (
        actual != expected
        or read_json(Path(actual["study"]["histories"])) != audit["remaining_fixture"]
        or read_json(Path(actual["arms"][0]["config"]))
        != read_json(Path(next(a for a in audit["parent"]["arms"] if a["id"] == arm_id)["config"]))
    ):
        raise ValueError(
            "Continuation no longer matches the exact unattempted positions and conditions"
        )
    return audit


def prepare(parent_path: Path, arm_id: str) -> dict[str, Any]:
    previous = segment_paths(parent_path, arm_id)
    audit = audit_previous(parent_path, arm_id, previous)
    remaining = audit["remaining_fixture"]
    if not positions(remaining):
        raise ValueError("No unattempted original positions remain")
    output = parent_path.parent / "continuations" / arm_id / f"segment-{len(previous) + 1:03d}"
    output.mkdir(parents=True, exist_ok=False)
    dispatch = expected_dispatch(
        parent_path, audit["parent"], arm_id, output, remaining, audit["provenance"]
    )
    (original,) = [a for a in audit["parent"]["arms"] if a["id"] == arm_id]
    write_json(output / "histories.json", remaining)
    write_json(Path(dispatch["arms"][0]["config"]), read_json(Path(original["config"])))
    write_json(output / "dispatch.json", dispatch)
    validate_continuation(output / "dispatch.json", for_launch=True)
    return {
        "status": "UNATTEMPTED_ONLY_CONTINUATION_BOUND_NOT_EXECUTED",
        "dispatch": str(output / "dispatch.json"),
        "arm_id": arm_id,
        "remaining_positions": len(positions(remaining)),
        "excluded_attempts": len(audit["provenance"]["excluded_attempts"]),
        "original_arm_positions": audit["provenance"]["original_arm_positions"],
        "original_cohort_positions": audit["provenance"]["original_cohort_positions"],
        "model_calls": 0,
        "no_sha_validation": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "validate"))
    parser.add_argument("dispatch", type=Path)
    parser.add_argument("--arm-id")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started = time.process_time()
    if args.mode == "prepare":
        if args.arm_id is None:
            parser.error("prepare requires --arm-id")
        result = prepare(args.dispatch.resolve(), args.arm_id)
    else:
        audit = validate_continuation(args.dispatch.resolve(), for_launch=True)
        result = {
            "status": "UNATTEMPTED_ONLY_ADMISSION_REVERIFIED",
            "remaining_positions": len(positions(audit["remaining_fixture"])),
            "model_calls": 0,
        }
    result.update(cpu_seconds_pending=time.process_time() - started, ledger_recorded=False)
    with args.report.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["status"], result["remaining_positions"])


if __name__ == "__main__":
    main()
