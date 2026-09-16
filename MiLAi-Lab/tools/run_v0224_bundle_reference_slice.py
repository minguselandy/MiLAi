"""One frozen R03 complete first-P4 reference, never a Gate A or chain verdict.

The complete Session outer wall is a conservative admission-union upper bound.
No internal guard timer, candidate patch, trace or profiler is installed. The
parent must independently record actual process exit and complete <=300s wall.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace

INSTANCE = "bundle-v1-slice"
CPU_ROOT = Path("/cra/memory/mx_memory/evidence/v0224/20260913-gate-a-bundle-v1") / INSTANCE
REVISION = "V0224_GATE_A_EXECUTION_R03_BUNDLE_AUTHORITY"
FIXED_LIMITS = {
    "http_requests_allowed": 0,
    "model_requests_allowed": 0,
    "device_calls_allowed": 0,
    "concurrency": 1,
    "worker_outer_seconds": 300,
    "phase_seconds": 300,
    "session_seconds": 60,
    "session_outer_upper_bound_seconds": 18,
    "slice_count": 1,
}
QUERIES = {
    "meta": "SELECT * FROM meta ORDER BY key",
    "episodes": "SELECT * FROM episodes ORDER BY stage,ordinal",
    "events": "SELECT * FROM events ORDER BY seq",
    "artifacts": "SELECT * FROM artifacts ORDER BY name",
    "launches": "SELECT * FROM launches ORDER BY stage",
    "claims": "SELECT * FROM claims ORDER BY episode",
}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _unprofiled():
    _require(
        sys.getprofile() is None and sys.gettrace() is None and threading.active_count() == 1,
        "UNPROFILED_SINGLE_THREAD_SLICE_REQUIRED",
    )


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _absolute(value):
    return (
        type(value) is str
        and "\x00" not in value
        and Path(value).is_absolute()
        and str(Path(value)) == value
        and ".." not in Path(value).parts
    )


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("NONFINITE_JSON_NUMBER")


def _finite_float(value):
    result = float(value)
    _require(math.isfinite(result), "NONFINITE_JSON_NUMBER")
    return result


def _read(path):
    return json.loads(
        Path(path).read_bytes(),
        object_pairs_hook=_pairs,
        parse_constant=_constant,
        parse_float=_finite_float,
    )


def _contract_path(value):
    _require(_absolute(value), "CANONICAL_ABSOLUTE_EXECUTION_CONTRACT_REQUIRED")
    path = Path(value)
    _require(path.resolve(strict=True) == path, "EXECUTION_CONTRACT_PATH_ALIAS_FORBIDDEN")
    return path


def _save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _exact(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def validate_contract(contract):
    _unprofiled()
    _require(
        type(contract) is dict and contract.get("status") == "R03_SINGLE_REFERENCE_SLICE_FROZEN",
        "FROZEN_SINGLE_REFERENCE_SLICE_REQUIRED",
    )
    _require(
        contract.get("execution_revision") == REVISION
        and contract.get("instance") == INSTANCE
        and contract.get("root") == str(CPU_ROOT),
        "EXACT_R03_ROOT_AND_REVISION_REQUIRED",
    )
    for key, value in FIXED_LIMITS.items():
        _require(
            type(contract.get(key)) is int and contract[key] == value,
            "EXACT_SINGLE_SLICE_LIMITS_REQUIRED",
        )
    _require(_digest(contract.get("binding_sha256")), "EXACT_BINDING_PIN_REQUIRED")
    spec = contract.get("first_p4_spec")
    _require(
        type(spec) is dict
        and spec.get("stage") == "P4"
        and spec.get("id") == INSTANCE + "-p4-01"
        and type(spec.get("actions")) is list
        and len(spec["actions"]) in (1, 2),
        "EXACT_FIRST_P4_SPEC_REQUIRED",
    )
    public = contract.get("public_source")
    _require(
        type(public) is dict
        and set(public) == {"path", "sha256"}
        and _absolute(public["path"])
        and _digest(public["sha256"]),
        "FROZEN_PUBLIC_SOURCE_REQUIRED",
    )
    baseline = contract.get("coordinator_baseline")
    _require(
        type(baseline) is dict
        and set(baseline) == {"path", "sha256"}
        and _absolute(baseline["path"])
        and _digest(baseline["sha256"]),
        "FROZEN_COORDINATOR_BASELINE_REQUIRED",
    )
    authority = contract.get("static_authority")
    _require(
        type(authority) is dict
        and set(authority)
        == {"bundle_path", "bundle_sha256", "receipt_path", "receipt_sha256", "limits"},
        "EXACT_EXTERNAL_STATIC_AUTHORITY_REQUIRED",
    )
    for key in ("bundle", "receipt"):
        _require(
            _absolute(authority[key + "_path"]) and _digest(authority[key + "_sha256"]),
            "PINNED_AUTHORITY_PATH_REQUIRED",
        )
    _require(authority["bundle_path"] != authority["receipt_path"], "DISTINCT_AUTHORITY_REQUIRED")
    limits = authority["limits"]
    _require(
        type(limits) is dict
        and set(limits) == {"max_header_bytes", "max_payload_bytes", "max_paths", "max_blobs"}
        and all(type(v) is int and v > 0 for v in limits.values()),
        "FIXED_POSITIVE_BUNDLE_LIMITS_REQUIRED",
    )
    files = contract.get("files")
    _require(
        type(files) is dict
        and bool(files)
        and all(_absolute(p) and _digest(d) for p, d in files.items()),
        "COMPLETE_CURRENT_EXECUTION_PINS_REQUIRED",
    )
    mutable = {str(CPU_ROOT / "batch.sqlite") + suffix for suffix in ("", "-wal", "-shm")}
    _require(not mutable & set(files), "MUTABLE_CURRENT_SQL_CANNOT_BE_FILE_PINNED")
    required = {
        str(CPU_ROOT / "execution-binding.json"): contract["binding_sha256"],
        public["path"]: public["sha256"],
        baseline["path"]: baseline["sha256"],
        authority["bundle_path"]: authority["bundle_sha256"],
        authority["receipt_path"]: authority["receipt_sha256"],
    }
    _require(
        all(files.get(path) == digest for path, digest in required.items()),
        "MANDATORY_CONTROL_PINS_REQUIRED",
    )
    return contract


def _verify_pins(contract):
    from v0220_evidence import dependencies

    sources = dependencies([Path(__file__).resolve()])
    _require(
        all(str(path) in contract["files"] for path in sources),
        "COMPLETE_WORKER_SOURCE_CLOSURE_REQUIRED",
    )
    for name, digest in contract["files"].items():
        _require(_sha(name) == digest, "FROZEN_EXECUTION_INPUT_DRIFT: " + name)


def sql_snapshot(root):
    path = Path(root) / "batch.sqlite"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        _require(
            [
                r[0]
                for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            == sorted(QUERIES),
            "EXACT_SIX_COORDINATOR_TABLES_REQUIRED",
        )
        return {name: [dict(row) for row in db.execute(query)] for name, query in QUERIES.items()}


def _initial(snapshot, plan, binding):
    _require(
        type(plan.get("P3")) is list
        and len(plan["P3"]) == 16
        and type(plan.get("P4")) is list
        and len(plan["P4"]) == 24,
        "FULL_FROZEN_16_24_PLAN_REQUIRED",
    )
    expected = [
        {
            "id": spec["id"],
            "stage": stage,
            "ordinal": i,
            "cap": 1 if stage == "P3" else 4,
            "status": "PENDING",
            "pid": None,
            "deadline": None,
        }
        for stage in ("P3", "P4")
        for i, spec in enumerate(plan[stage])
    ]
    _require(
        _exact(snapshot["episodes"], expected)
        and snapshot["meta"] == [{"key": "binding", "value": binding}]
        and all(not snapshot[key] for key in ("events", "claims", "launches")),
        "FRESH_40_PENDING_NO_CURRENT_ACTIVITY_REQUIRED",
    )


@contextmanager
def _phase(phases, name):
    start = time.monotonic_ns()
    primary = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            elapsed = time.monotonic_ns() - start
            phases.append(
                {
                    "phase": name,
                    "wall_ns": elapsed,
                    "status": "RETURNED" if primary is None else "UNWOUND",
                }
            )
            _require(0 < elapsed <= 300_000_000_000, "SLICE_PHASE_OUTER_LIMIT: " + name)
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note("SECONDARY_PHASE_OBSERVATION_FAILURE: " + repr(error))


def _run_slice(contract, out, phases, details):
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_full import resolve_p4_spec
    from v0220_intent_audit import effects
    from v0222_presentation_audit import initial_for, validate_reference, world_evidence
    from v0223_transaction_primary_fix import installed_transaction_fix
    from v0224_bundle_cpu_batch import OfflineBatch, StaticAuthority, selected_root
    from v0224_reference_outer_bounds import prepare_p4_bounded
    from v0224_static_bundle import BundleLimits

    root = selected_root()
    _require(str(root) == contract["root"], "SELECTED_ROOT_DRIFT")
    authority = contract["static_authority"]
    config = StaticAuthority(
        bundle_path=Path(authority["bundle_path"]),
        bundle_sha256=authority["bundle_sha256"],
        receipt_path=Path(authority["receipt_path"]),
        receipt_sha256=authority["receipt_sha256"],
        limits=BundleLimits(**authority["limits"]),
    )
    baseline = contract["coordinator_baseline"]
    _require(_sha(baseline["path"]) == baseline["sha256"], "FROZEN_COORDINATOR_BASELINE_DRIFT")
    frozen_before = _read(baseline["path"])
    before = sql_snapshot(root)
    _save(out / "coordinator-before.json", before)
    _require(_exact(before, frozen_before), "CURRENT_COORDINATOR_BASELINE_MISMATCH")
    primary = None
    try:
        with installed_transaction_fix():
            with _phase(phases, "constructor_and_public_source"):
                batch = OfflineBatch(root, contract["binding_sha256"], static_authority=config)
                _initial(before, batch.plan, contract["binding_sha256"])
                spec = batch.plan["P4"][0]
                _require(_exact(spec, contract["first_p4_spec"]), "FIRST_PLAN_SPEC_DRIFT")
                public_path = CASES / spec["root"] / "public-initial.json"
                _require(
                    str(public_path) == contract["public_source"]["path"],
                    "EXACT_PUBLIC_CASE_SOURCE_REQUIRED",
                )
                manifest = _read(root / "manifest.json")
                _require(
                    _sha(root / "manifest.json") == batch.binding["manifest.json"]
                    and manifest["inputs"].get(str(public_path))
                    == contract["public_source"]["sha256"]
                    and _sha(public_path) == contract["public_source"]["sha256"],
                    "CURRENT_MANIFEST_PUBLIC_PIN_DRIFT",
                )
                public = _read(public_path)
                resolved, change = resolve_p4_spec(spec, public)
                _require(_exact(resolved, spec), "FIRST_PLAN_SPEC_NOT_PRE_RESOLVED")
                reference = out / "full-reference" / "P4" / spec["id"]
            counts = {"attempted": 0, "returned": 0}
            details["guard_counts"] = counts
            bounds = []
            details["outer_bounds"] = bounds

            def guard():
                counts["attempted"] += 1
                with batch._operation("PREP"):
                    pass
                counts["returned"] += 1

            with _phase(phases, "complete_first_reference"):
                rows, resolved_record = prepare_p4_bounded(
                    reference, spec, public, guard, bounds_collector=bounds
                )
                _save(out / "reference-rows.json", rows)
                _save(out / "resolved-spec.json", resolved_record)
            with _phase(phases, "original_reference_and_independent_effect_audit"):
                _require(
                    _exact(resolved_record, {"spec": resolved, "derived_hash_diff": change}),
                    "RESOLVED_REFERENCE_SPEC_DRIFT",
                )
                expected_turns = len(spec["actions"]) + 2
                _require(
                    len(rows) == expected_turns
                    and [row["turn"] for row in rows] == list(range(1, expected_turns + 1)),
                    "COMPLETE_REFERENCE_ROWS_REQUIRED",
                )
                _require(
                    counts["attempted"] == counts["returned"] == 2 + (1 + 2 * len(rows)),
                    "FULL_REFERENCE_GUARD_COVERAGE_REQUIRED",
                )
                for row in rows:
                    validate_reference(SimpleNamespace(root=out), row, resolved)
                final, ledger, checks = world_evidence(reference / "world.sqlite", resolved)
                turns = [
                    _read(path) for path in sorted((reference / "session").glob("turn-*.json"))
                ]
                session = _read(reference / "session/session-result.json")
                initial = initial_for(resolved)
                verdict = effects(resolved, initial, final, ledger, turns)
                _require(
                    all(checks.values())
                    and verdict["status"] == "PASS"
                    and session["status"] == "SESSION_FINISHED_NOT_TASK_VERDICT"
                    and session["episode_id"] == spec["id"]
                    and session["completed_turns"] == len(rows)
                    and session["note_writes"] == 0
                    and not session["rejection_counts"],
                    "INDEPENDENT_COMPLETE_REFERENCE_EFFECTS_REQUIRED",
                )
                _require(
                    len(bounds) == 1
                    and bounds[0]["status"] == "QUALIFIED_OUTER_UPPER_BOUND"
                    and bounds[0]["session_wall_at_most_18"] is True
                    and 0 < bounds[0]["session_wall_ns"] <= 18_000_000_000
                    and bounds[0]["admission_union_upper_bound_ns"] == bounds[0]["session_wall_ns"],
                    "COMPLETE_SESSION_CONSERVATIVE_UPPER_BOUND_REQUIRED",
                )
                details.update(
                    provider_rows=len(rows),
                    runtime_guard_count=1 + 2 * len(rows),
                    setup_guard_count=2,
                    independent_effects=verdict,
                    world_checks=checks,
                    session_result=session,
                )
                _save(out / "independent-effect-review.json", {"effects": verdict, "world": checks})
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            with _phase(phases, "current_SQL_after"):
                after = sql_snapshot(root)
                _save(out / "coordinator-after.json", after)
                _require(_exact(after, before), "CURRENT_COORDINATOR_SQL_CHANGED")
        except BaseException as error:
            if primary is None:
                raise
            primary.add_note("SECONDARY_COORDINATOR_RECHECK_FAILURE: " + repr(error))


def main():
    started = time.monotonic_ns()
    _unprofiled()
    from v0222_scoped_cpu_guard import enable_cpu_network_guard

    enable_cpu_network_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--contract-sha256", required=True)
    args = parser.parse_args()
    args.contract = _contract_path(args.contract)
    _require(
        _digest(args.contract_sha256) and _sha(args.contract) == args.contract_sha256,
        "EXTERNAL_EXECUTION_CONTRACT_HASH_MISMATCH",
    )
    contract = validate_contract(_read(args.contract))
    os.environ["MILA_V0224_INSTANCE"] = INSTANCE
    out = args.contract.parent / "reference-slice"
    out.mkdir(exist_ok=False)
    _save(
        out / "worker-start.json",
        {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "unix": time.time(),
            "contract_sha256": args.contract_sha256,
        },
    )
    phases, details, failure = [], {}, None
    try:
        with _phase(phases, "frozen_inputs_before"):
            _verify_pins(contract)
        _run_slice(contract, out, phases, details)
    except BaseException as exc:
        failure = exc
    finally:
        try:
            with _phase(phases, "frozen_inputs_after"):
                _verify_pins(contract)
                _contract_path(str(args.contract))
                _require(_sha(args.contract) == args.contract_sha256, "EXECUTION_CONTRACT_CHANGED")
        except BaseException as exc:
            if failure is None:
                failure = exc
            else:
                failure.add_note("SECONDARY_FROZEN_INPUT_RECHECK_FAILURE: " + repr(exc))
    raw_files = {}
    try:
        raw_files = {str(path): _sha(path) for path in sorted(out.rglob("*")) if path.is_file()}
    except BaseException as exc:
        if failure is None:
            failure = exc
        else:
            failure.add_note("SECONDARY_RAW_PIN_FAILURE: " + repr(exc))
    elapsed = time.monotonic_ns() - started
    if not 0 < elapsed <= 300_000_000_000:
        if failure is None:
            failure = ValueError("SLICE_WORKER_OUTER_LIMIT_BEFORE_REPORT")
        else:
            failure.add_note("SLICE_WORKER_OUTER_LIMIT_BEFORE_REPORT")
    result = {
        "status": "R03_REFERENCE_SLICE_VALIDATED_NOT_GATE_A"
        if failure is None
        else "R03_REFERENCE_SLICE_FAILED",
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "instance": INSTANCE,
        "contract_sha256": args.contract_sha256,
        "execution_revision": REVISION,
        "phases": phases,
        "wall_before_result_write_ns": elapsed,
        "model_requests": 0,
        "http_requests": 0,
        "device_calls": 0,
        "mock_effects_are_not_model_results": True,
        "details": details,
        "raw_files": raw_files,
        "exception_type": None if failure is None else type(failure).__name__,
        "reason": None if failure is None else str(failure),
        "notes": [] if failure is None else list(getattr(failure, "__notes__", [])),
        "limits": [
            "Only first P4 complete reference; not full matrix or Gate A.",
            "Complete Session <=18s is an upper bound, not measured admission union.",
            "Caller audit/report and parent finish are outside that bound; no90s chain claim.",
            "Parent must check actual exit and complete worker<=300s including report/exit.",
        ],
    }
    try:
        _save(out / "worker-result.json", result)
    except BaseException as exc:
        if failure is None:
            raise
        failure.add_note("SECONDARY_RESULT_SAVE_FAILURE: " + repr(exc))
    if failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
