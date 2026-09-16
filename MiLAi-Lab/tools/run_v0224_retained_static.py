"""Fixed A1 four-turn CPU workflow; strict U has no internal observer clocks.

Only the parent times full worker lifecycles. S records complete original
Session.validate_runtime intervals, including nested PREP and host checks.
Only reference parent/worker operations are enabled in this revision. Future K3
requires a separate operation contract and implementation review. No failed
position is retried; this four-turn calibration does not establish Gate A.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

BASE = Path("/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-retained-static-v1")
ORDER = (
    "retainv1-d1-u1",
    "retainv1-d1-s1",
    "retainv1-d1-s2",
    "retainv1-d1-u2",
    "retainv1-d1-u3",
    "retainv1-d1-s3",
)
REVISION = "V0224_R05_CPU_RETAINED_STATIC_01"
LIMITS = {
    "http_requests": 0,
    "model_requests": 0,
    "device_calls": 0,
    "concurrency": 1,
    "positions": 6,
    "parent_seconds": 600,
    "worker_seconds": 300,
    "session_seconds": 60,
    "strict_u_worker_upper_seconds": 60,
    "runtime_union_ns": 18_000_000_000,
    "maximum_overhead_ratio": 1.10,
}


@dataclass(frozen=True)
class ReferenceSelection:
    index: int
    root: str
    kind: str
    actions: int
    turns: int
    runtime: int
    callbacks: int


LONG_PATH = ReferenceSelection(2, "A-1db36ca3de1602c36e98", "two_object_sequence", 2, 4, 9, 11)
ORIGINAL_MANIFEST = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-scope-digest-v1/"
    "digestv1-d1-u1/manifest.json"
)
ORIGINAL_MANIFEST_SHA256 = "b6a70171ba24cd855e0738246cfcd33558353ac782ef086aac0f22857b768452"
A0_REVIEW = Path(
    "/cra/memory/mx_memory/evidence/v0224/20260913-a-scope-digest-v2/"
    "independent-r04-a0-calibration-review.json"
)
A0_REVIEW_SHA256 = "5ba177bd85576f92e8d5eaf3f7047353257c268d46a950d162afb4ef4c034a3a"


TESTBED_GUARANTEE = "V0224_R05_COLD_PROCESS_STATIC_AUTHORITY"
R05_EVIDENCE_PINS = {
    (
        '/cra/memory/mx_memory/evidence/v0224/20260913-a-workflow-v1/'
        'independent-a1-calibration-result-review.json'
    ): '44dc8703222bd52dcbc000708a35c6a2329b59e9caa7bd7585ae56aa42b1395d',
    (
        '/cra/memory/mx_memory/evidence/v0224/20260913-a-zlib-feasibility-v1/'
        'independent-zlib-feasibility-result-review.json'
    ): '7d1f3d4ef0f4295e782b7f1935808dd3f0b4b40c401cbfaa870d9162cbff7bc3',
    (
        '/cra/memory/mx_memory/evidence/v0224/20260913-a-zlib-feasibility-v1/'
        'simplified-testbed-contract-draft.json'
    ): '5ccea76a1399fc7516b58d51ca0cfc9dda3d311093163e87ba67c364496502a9',
    (
        '/cra/memory/mx_memory/evidence/v0224/20260913-a-zlib-feasibility-v1/'
        'independent-r05-testbed-scope-review.json'
    ): '61c7b82b8b19ad44acd9248327611119a429760be91ff3c911025c2a4f1eba23',
    (
        '/cra/memory/mx_memory/MiLAi-Lab/studies/active/'
        'MILA_V0224_GATE_A_REVISION_05_RETAINED_STATIC_TESTBED_20260913.md'
    ): 'd8bf02f2d500ac0efacd37e535cfd7e7fc042ef68ea5e6eac95126d22f9a8f37',
}


def select_reference(plan, frozen_spec):
    """Return the actual producer object after checking the original complete case."""
    from run_v0224_bundle_reference_slice_v2 import _exact, _read

    require(sha(ORIGINAL_MANIFEST) == ORIGINAL_MANIFEST_SHA256, "ORIGINAL_SELECTION_SOURCE_DRIFT")
    original = _read(ORIGINAL_MANIFEST)["contract"]["P4"][LONG_PATH.index]
    require(len(plan["P3"]) == 16 and len(plan["P4"]) == 24, "COMPLETE_PLAN_REQUIRED")
    spec = plan["P4"][LONG_PATH.index]
    require(_exact(spec, frozen_spec), "EXACT_FROZEN_PRODUCER_SPEC_REQUIRED")
    require(
        spec["root"] == LONG_PATH.root
        and spec["kind"] == LONG_PATH.kind
        and len(spec["actions"]) == LONG_PATH.actions,
        "EXACT_FROZEN_REFERENCE_SHAPE_REQUIRED",
    )
    mechanical = {"id", "scope", "initial_state_sha256"}
    require(
        _exact({k: v for k, v in original.items() if k not in mechanical},
               {k: v for k, v in spec.items() if k not in mechanical}),
        "ORIGINAL_COMPLETE_REFERENCE_SEMANTICS_REQUIRED",
    )
    return spec


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def load_contract(path, digest):
    from run_v0224_bundle_reference_slice_v2 import _contract_path, _digest, _read

    path = _contract_path(str(path))
    require(_digest(digest) and sha(path) == digest, "EXTERNAL_CALIBRATION_CONTRACT_DRIFT")
    contract = _read(path)
    validate_contract(contract)
    return path, contract


def validate_contract(contract):
    from run_v0224_bundle_reference_slice_v2 import _absolute, _digest, _exact, _unprofiled

    _unprofiled()
    require(
        type(contract) is dict and contract.get("status") == "R05_LONG_PATH_CALIBRATION_FROZEN",
        "FROZEN_RUNTIME_UNION_CONTRACT_REQUIRED",
    )
    require(
        contract.get("execution_revision") == REVISION and _exact(contract.get("limits"), LIMITS),
        "EXACT_CALIBRATION_REVISION_LIMITS_REQUIRED",
    )
    require(
        _exact(contract.get("reference_selection"), asdict(LONG_PATH))
        and contract.get("operation") == "A1_REFERENCE_CALIBRATION",
        "EXACT_A1_OPERATION_AND_SELECTION_REQUIRED",
    )
    require(
        contract.get("testbed_guarantee") == TESTBED_GUARANTEE,
        "EXPLICIT_R05_REDUCED_STATIC_GUARANTEE_REQUIRED",
    )
    positions = contract.get("positions")
    require(
        type(positions) is list
        and len(positions) == 6
        and [p.get("name") for p in positions] == list(ORDER),
        "FIXED_SIX_POSITION_ORDER_REQUIRED",
    )
    files = contract.get("files")
    require(
        type(files) is dict
        and bool(files)
        and all(_absolute(p) and _digest(d) for p, d in files.items()),
        "EXTERNAL_INPUT_PINS_REQUIRED",
    )
    require(
        files.get(str(ORIGINAL_MANIFEST)) == ORIGINAL_MANIFEST_SHA256
        and files.get(str(A0_REVIEW)) == A0_REVIEW_SHA256,
        "A0_AND_ORIGINAL_SELECTION_PINS_REQUIRED",
    )
    require(
        R05_EVIDENCE_PINS.items() <= files.items(), "EXACT_R05_CONTRACT_AND_FAILED_HISTORY_REQUIRED"
    )
    authority = contract.get("static_authority")
    require(
        type(authority) is dict
        and set(authority)
        == {"bundle_path", "bundle_sha256", "receipt_path", "receipt_sha256", "limits"},
        "EXACT_EXTERNAL_AUTHORITY_REQUIRED",
    )
    for kind in ("bundle", "receipt"):
        require(
            _absolute(authority[kind + "_path"])
            and _digest(authority[kind + "_sha256"])
            and files.get(authority[kind + "_path"]) == authority[kind + "_sha256"],
            "EXTERNALLY_PINNED_AUTHORITY_REQUIRED",
        )
    require(
        authority["bundle_path"] != authority["receipt_path"], "DISTINCT_AUTHORITY_PATHS_REQUIRED"
    )
    bounds = authority["limits"]
    require(
        type(bounds) is dict
        and set(bounds) == {"max_header_bytes", "max_payload_bytes", "max_paths", "max_blobs"}
        and all(type(v) is int and v > 0 for v in bounds.values()),
        "FIXED_BUNDLE_LIMITS_REQUIRED",
    )
    for position in positions:
        name = position["name"]
        require(
            set(position)
            == {
                "name",
                "arm",
                "root",
                "binding_sha256",
                "reference_spec",
                "public_source",
                "coordinator_baseline",
            },
            "EXACT_POSITION_FIELDS_REQUIRED",
        )
        require(
            position["root"] == str(BASE / name)
            and position["arm"] == ("U" if name[-2] == "u" else "S"),
            "FIXED_ARM_ROOT_REQUIRED",
        )
        binding = position["binding_sha256"]
        require(
            _digest(binding) and files.get(str(BASE / name / "execution-binding.json")) == binding,
            "FIXED_BINDING_PIN_REQUIRED",
        )
        spec = position["reference_spec"]
        require(
            type(spec) is dict
            and spec.get("id") == name + "-p4-03"
            and spec.get("stage") == "P4"
            and type(spec.get("actions")) is list
            and len(spec["actions"]) == 2
            and spec.get("root") == LONG_PATH.root
            and spec.get("kind") == LONG_PATH.kind,
            "FROZEN_TWO_ACTION_FOUR_TURN_P4_REQUIRED",
        )
        for field in ("public_source", "coordinator_baseline"):
            row = position[field]
            require(
                type(row) is dict
                and set(row) == {"path", "sha256"}
                and _absolute(row["path"])
                and _digest(row["sha256"])
                and files.get(row["path"]) == row["sha256"],
                "EXTERNALLY_PINNED_POSITION_INPUT_REQUIRED",
            )
        require(
            not {str(BASE / name / "batch.sqlite") + suffix for suffix in ("", "-wal", "-shm")}
            & set(files),
            "CURRENT_SQL_CANNOT_BE_FILE_PINNED",
        )
    ordinary_specs = [
        {
            k: v
            for k, v in p["reference_spec"].items()
            if k not in {"id", "scope", "initial_state_sha256"}
        }
        for p in positions
    ]
    require(
        all(_exact(s, ordinary_specs[0]) for s in ordinary_specs)
        and all(_exact(p["public_source"], positions[0]["public_source"]) for p in positions),
        "SAME_ORIGINAL_REFERENCE_AND_PUBLIC_INPUT_FOR_ALL_POSITIONS_REQUIRED",
    )
    require(
        len({p["coordinator_baseline"]["path"] for p in positions}) == 6,
        "SIX_SEPARATELY_FROZEN_COORDINATOR_BASELINES_REQUIRED",
    )
    return contract


def verify_inputs(contract):
    from v0220_evidence import dependencies

    require(
        all(str(path) in contract["files"] for path in dependencies([Path(__file__).resolve()])),
        "COMPLETE_EXECUTING_SOURCE_CLOSURE_REQUIRED",
    )
    for name, digest in contract["files"].items():
        path = Path(name)
        require(
            path.resolve(strict=True) == path and sha(path) == digest,
            "FROZEN_CALIBRATION_INPUT_DRIFT: " + name,
        )


def validate_observation(value, arm):
    require(
        value["mode"] == arm
        and value["callback_counts"] == {"attempted": 11, "returned": 11}
        and value["errors"] == [],
        "COMPLETE_ELEVEN_CALLBACKS_REQUIRED",
    )
    if arm == "U":
        require(
            value["status"] == "STRICT_U_UNTIMED"
            and value["runtime_intervals"] == []
            and value["session_interval"] is None
            and value["runtime_union_ns"] is None
            and value["setup_callbacks"] is None,
            "STRICT_U_NO_INTERNAL_OBSERVER_DATA_REQUIRED",
        )
        return None
    require(
        value["status"] == "COMPLETE_RUNTIME_INTERVALS"
        and value["setup_callbacks"] == {"attempted": 2, "returned": 2},
        "COMPLETE_S_RUNTIME_OBSERVATION_REQUIRED",
    )
    rows = value["runtime_intervals"]
    session = value["session_interval"]
    require(
        type(session) is dict
        and set(session) == {"start_ns", "end_ns"}
        and all(type(v) is int for v in session.values())
        and 0 < session["end_ns"] - session["start_ns"] <= 60_000_000_000,
        "COMPLETE_S_SESSION_WITHIN_ORIGINAL_60_REQUIRED",
    )
    require(type(rows) is list and len(rows) == 9, "NINE_COMPLETE_RUNTIME_INTERVALS_REQUIRED")
    cursor, total = session["start_ns"], 0
    for ordinal, row in enumerate(rows, 1):
        require(
            row["ordinal"] == ordinal
            and row["returned"] is True
            and row["callback_attempted_delta"] == row["callback_returned_delta"] == 1
            and type(row["start_ns"]) is int
            and type(row["end_ns"]) is int
            and cursor <= row["start_ns"] < row["end_ns"] <= session["end_ns"],
            "COMPLETE_ORDERED_NONOVERLAPPING_RUNTIME_INTERVAL_REQUIRED",
        )
        total += row["end_ns"] - row["start_ns"]
        cursor = row["end_ns"]
    require(value["runtime_union_ns"] == total, "EXACT_FULL_RUNTIME_INTERVAL_UNION_REQUIRED")
    return total


def run_reference(position, authority, out, details):
    # No observer clock here: strict U uses only clocks required by original business code.
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from run_v0224_bundle_reference_slice_v2 import _exact, _initial, _read, sql_snapshot
    from v0220_intent_audit import effects
    from v0222_presentation_audit import initial_for, validate_reference, world_evidence
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0224_retained_static_batch import (
        OfflineBatch,
        StaticAuthority,
        selected_root,
        workpoint_purpose,
    )
    from v0224_runtime_admission_observation import prepare_p4_observed
    from v0224_static_bundle import BundleLimits

    root = selected_root()
    require(str(root) == position["root"], "SELECTED_CALIBRATION_ROOT_DRIFT")
    require(workpoint_purpose(root) == "A1_REFERENCE_CALIBRATION", "A1_WORKPOINT_REQUIRED")
    config = StaticAuthority(
        bundle_path=Path(authority["bundle_path"]),
        bundle_sha256=authority["bundle_sha256"],
        receipt_path=Path(authority["receipt_path"]),
        receipt_sha256=authority["receipt_sha256"],
        limits=BundleLimits(**authority["limits"]),
    )
    baseline = position["coordinator_baseline"]
    require(sha(baseline["path"]) == baseline["sha256"], "FROZEN_SQL_BASELINE_DRIFT")
    before = sql_snapshot(root)
    save(out / "coordinator-before.json", before)
    require(_exact(before, _read(baseline["path"])), "CURRENT_SQL_BASELINE_MISMATCH")
    primary = None
    try:
        with installed_transaction_fix(), OfflineBatch(
            root, position["binding_sha256"], static_authority=config
        ) as batch:
            _initial(before, batch.plan, position["binding_sha256"])
            # Preserve the actual producer's pinned manifest order for embedded JSON strings.
            spec = select_reference(batch.plan, position["reference_spec"])
            public_path = CASES / spec["root"] / "public-initial.json"
            manifest = _read(root / "manifest.json")
            expected = position["public_source"]
            require(
                str(public_path) == expected["path"]
                and sha(public_path) == expected["sha256"]
                and sha(root / "manifest.json") == batch.binding["manifest.json"]
                and manifest["inputs"].get(str(public_path)) == expected["sha256"],
                "CURRENT_MANIFEST_DIRECT_PUBLIC_PIN_REQUIRED",
            )
            public = _read(public_path)
            resolved, change = resolve_p4_spec(spec, public)
            require(_exact(resolved, spec), "SPEC_MUST_ALREADY_BE_RESOLVED")

            def guard():
                with batch._operation("PREP"):
                    pass

            observation = {}
            details["observation"] = observation
            directory = out / "full-reference" / "P4" / spec["id"]
            rows, resolved_record = prepare_p4_observed(
                directory,
                spec,
                public,
                guard,
                mode=position["arm"],
                observation=observation,
            )
            save(out / "reference-rows.json", rows)
            save(out / "resolved-spec.json", resolved_record)
            require(
                _exact(resolved_record, {"spec": resolved, "derived_hash_diff": change})
                and len(rows) == 4
                and [r["turn"] for r in rows] == [1, 2, 3, 4],
                "COMPLETE_FOUR_REFERENCE_ROWS_REQUIRED",
            )
            for row in rows:
                validate_reference(SimpleNamespace(root=out), row, resolved)
            final, ledger, checks = world_evidence(directory / "world.sqlite", resolved)
            turns = [_read(path) for path in sorted((directory / "session").glob("turn-*.json"))]
            session = _read(directory / "session/session-result.json")
            verdict = effects(resolved, initial_for(resolved), final, ledger, turns)
            require(
                all(checks.values())
                and verdict["status"] == "PASS"
                and session["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
                and session["episode_id"] == spec["id"]
                and session["completed_turns"] == 4
                and session["note_writes"] == 0
                and not session["rejection_counts"],
                "COMPLETE_ORIGINAL_REFERENCE_AND_WORLD_EFFECTS_REQUIRED",
            )
            union = validate_observation(observation, position["arm"])
            details.update(
                provider_rows=4,
                independent_effects=verdict,
                world_checks=checks,
                session_result=session,
                runtime_union_ns=union,
                runtime_union_is_qualified=False,
            )
            save(out / "independent-effect-review.json", {"effects": verdict, "world": checks})
            details["retained_static_authority"] = batch.retained_authority_stats()
        require(batch._static_released, "EXPLICIT_RETAINED_AUTHORITY_RELEASE_REQUIRED")
        details["retained_static_release_completed"] = True
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            after = sql_snapshot(root)
            save(out / "coordinator-after.json", after)
            require(_exact(after, before), "CURRENT_SQL_CHANGED")
        except BaseException as exc:
            if primary is None:
                raise
            primary.add_note("SECONDARY_SQL_RECHECK_FAILURE: " + repr(exc))


def worker(contract_path, digest, name):
    from run_v0224_bundle_reference_slice_v2 import _unprofiled

    _unprofiled()
    path, contract = load_contract(contract_path, digest)
    require(name in ORDER, "ONE_FROZEN_POSITION_REQUIRED")
    position = next(p for p in contract["positions"] if p["name"] == name)
    os.environ["MILA_V0224_INSTANCE"] = name
    out = path.parent / "calibration-v1" / "positions" / name
    out.mkdir(parents=True, exist_ok=False)
    save(
        out / "worker-start.json",
        {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "position": name,
            "arm": position["arm"],
            "contract_sha256": digest,
        },
    )
    details, failure = {}, None
    try:
        verify_inputs(contract)
        run_reference(position, contract["static_authority"], out, details)
    except BaseException as exc:
        failure = exc
    finally:
        try:
            verify_inputs(contract)
            load_contract(path, digest)
            _unprofiled()
        except BaseException as exc:
            if failure is None:
                failure = exc
            else:
                failure.add_note("SECONDARY_FINAL_INPUT_CHECK: " + repr(exc))
    raw_files, raw_pins_complete = {}, False
    try:
        for raw_path in sorted(out.rglob("*")):
            if raw_path.is_file():
                raw_files[str(raw_path)] = sha(raw_path)
        raw_pins_complete = True
    except BaseException as exc:
        if failure is None:
            failure = exc
        else:
            failure.add_note("SECONDARY_RAW_PIN_COLLECTION_FAILURE: " + repr(exc))
    result = {
        "status": "REFERENCE_COMPLETE_OBSERVATION_NOT_YET_CALIBRATED"
        if failure is None
        else "REFERENCE_POSITION_FAILED_NO_RETRY",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "position": name,
        "arm": position["arm"],
        "contract_sha256": digest,
        "details": details,
        "raw_files": raw_files,
        "raw_pins_complete": raw_pins_complete,
        "exception_type": None if failure is None else type(failure).__name__,
        "reason": None if failure is None else str(failure),
        "notes": [] if failure is None else list(getattr(failure, "__notes__", [])),
        "model_requests": 0,
        "http_requests": 0,
        "device_calls": 0,
        "strict_u_internal_observer_clocks": 0 if position["arm"] == "U" else None,
        "actual_exit_and_complete_worker_wall": "PARENT_REQUIRED",
    }
    try:
        save(out / "worker-result.json", result)
    except BaseException as exc:
        if failure is None:
            raise
        failure.add_note("SECONDARY_RESULT_SAVE_FAILURE: " + repr(exc))
    if failure is not None:
        raise failure
    return result


def calibration_verdict(children, workers):
    require(len(children) == len(workers) == 6, "COMPLETE_SIX_POSITIONS_REQUIRED")
    values = {"U": [], "S": []}
    for name, child, result in zip(ORDER, children, workers, strict=True):
        arm = "U" if name[-2] == "u" else "S"
        require(
            result["position"] == name
            and result["arm"] == arm
            and child["phase"] == name
            and child["returncode"] == 0
            and child["cleanup_complete"] is True
            and child["owned_group_gone"] is True
            and child["pid"] == result["pid"]
            and result["status"] == "REFERENCE_COMPLETE_OBSERVATION_NOT_YET_CALIBRATED"
            and 0 < child["elapsed_seconds"] <= 300,
            "ACTUAL_COMPLETE_COLD_CHILD_REQUIRED",
        )
        validate_observation(result["details"]["observation"], arm)
        if arm == "S":
            span = result["details"]["observation"]["session_interval"]
            require(
                (span["end_ns"] - span["start_ns"]) / 1e9 <= child["elapsed_seconds"],
                "S_SESSION_MUST_BE_CONTAINED_IN_COMPLETE_CHILD_WALL",
            )
        values[arm].append(child["elapsed_seconds"])
    require(len({c["pid"] for c in children}) == 6, "SIX_DISTINCT_COLD_PROCESSES_REQUIRED")
    by_position = {
        name: child["elapsed_seconds"] for name, child in zip(ORDER, children, strict=True)
    }
    pair_ratios = [
        by_position[f"retainv1-d1-s{i}"] / by_position[f"retainv1-d1-u{i}"] for i in (1, 2, 3)
    ]
    ratio = statistics.median(pair_ratios)
    u_complete_60 = all(value <= 60 for value in values["U"])
    qualified = u_complete_60 and ratio <= 1.10
    unions = [r["details"]["observation"]["runtime_union_ns"] for r in workers if r["arm"] == "S"]
    return {
        "measurement_qualified": qualified,
        "strict_u_complete_session_bound": "PROVED_BY_WHOLE_WORKER" if u_complete_60 else "UNKNOWN",
        "strict_u_worker_outer_seconds": values["U"],
        "s_worker_outer_seconds": values["S"],
        "paired_s_over_u_ratios": pair_ratios,
        "paired_ratio_median": ratio,
        "ratio_of_medians_descriptive_only": statistics.median(values["S"])
        / statistics.median(values["U"]),
        "maximum_ratio": 1.10,
        "s_runtime_union_ns": unions,
        "all_s_runtime_unions_at_most_18": all(value <= 18_000_000_000 for value in unions)
        if qualified
        else None,
        "gate_a": "NOT_PASSED_BY_CALIBRATION",
    }


def parent(contract_path, digest):
    start = time.monotonic()
    deadline = start + 600
    from run_v0224_bundle_preparation_v2 import _remaining, _run_child
    from run_v0224_bundle_reference_slice_v2 import _read, _unprofiled

    _unprofiled()
    path, contract = load_contract(contract_path, digest)
    out = path.parent / "calibration-v1"
    out.mkdir(exist_ok=False)
    (out / "children").mkdir()
    children, workers = [], []
    report = {
        "status": "CALIBRATION_INCOMPLETE",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "contract_sha256": digest,
        "children": children,
        "worker_results": [],
        "parent_limit_seconds": 600,
        "worker_limit_seconds": 300,
        "child_deadline_kind": "MIN_PARENT_600_DEADLINE_AND_CHILD_300_DEADLINE",
    }
    save(out / "parent-start.json", report)
    try:
        verify_inputs(contract)
        for name in ORDER:
            _remaining(deadline)
            _run_child(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "worker",
                    "--contract",
                    str(path),
                    "--contract-sha256",
                    digest,
                    "--position",
                    name,
                ],
                name,
                out / "children",
                min(deadline, time.monotonic() + 300),
                children,
            )
            worker_path = out / "positions" / name / "worker-result.json"
            result = _read(worker_path)
            require(
                result["parent_pid"] == os.getpid() and result["contract_sha256"] == digest,
                "ACTUAL_WORKER_PARENT_CONTRACT_REQUIRED",
            )
            workers.append(result)
            report["worker_results"].append({"path": str(worker_path), "sha256": sha(worker_path)})
        report["verdict"] = calibration_verdict(children, workers)
        verify_inputs(contract)
        load_contract(path, digest)
        _unprofiled()
        _remaining(deadline)
        report.update(
            status="SIX_CALIBRATION_CHILDREN_COMPLETE_PARENT_EXTERNAL_EXIT_REQUIRED",
            elapsed_before_report_seconds=time.monotonic() - start,
        )
        save(out / "parent-result.json", report)
        _remaining(deadline)
        return report
    except BaseException as primary:
        report.update(
            status="CALIBRATION_FAILED_NO_RETRY",
            exception_type=type(primary).__name__,
            reason=str(primary),
            elapsed_seconds=time.monotonic() - start,
        )
        try:
            save(out / "parent-failure.json", report)
        except BaseException as secondary:
            primary.add_note("SECONDARY_PARENT_RESULT_FAILURE: " + repr(secondary))
        raise


def main():
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("parent", "worker"))
    parser.add_argument("--contract", required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--position", choices=ORDER)
    args = parser.parse_args()
    if args.command == "parent":
        require(args.position is None, "PARENT_HAS_NO_OPTIONAL_POSITION")
        parent(args.contract, args.contract_sha256)
    else:
        require(args.position is not None, "WORKER_REQUIRES_ONE_POSITION")
        worker(args.contract, args.contract_sha256, args.position)


if __name__ == "__main__":
    main()
