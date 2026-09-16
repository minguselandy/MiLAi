"""Original P4 reference path, cut only at its first offline generate boundary.

The deliberate exception runs through the original Session FAIL_CLOSED path,
provider close, result persistence and reference effect audit. It is diagnostic
prefix completion, never a successful reference or a deadline override. Both
U/S modes execute these same named wrappers and coverage counters. Strict U
sets observe_internal_timing=False: only original business clocks run, and
internal observation durations/timestamps remain absent or None.
"""

from __future__ import annotations

import sys
import threading
import time
from functools import wraps
from pathlib import Path


class DiagnosticPrefixReached(Exception):
    """Fixed first-generate cutoff after the original runtime deadline check."""


def run_reference_prefix(
    batch_factory,
    directory: Path,
    *,
    public_loader=None,
    full_prefix=False,
    observe_internal_timing=True,
):
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise RuntimeError("UNPROFILED_UNTRACED_PROCESS_REQUIRED")
    if threading.active_count() != 1:
        raise RuntimeError("SINGLE_THREAD_PREFIX_REQUIRED")
    from prepare_v0221_http_v2 import CASES
    from prepare_v0222_presentation import materialize_references
    from prepare_v0222_presentation_v2 import _PreparationView
    from v0220_evidence import read
    from v0220_provider_hardened import ProviderStop
    from v0220_session import Session
    from v0222_admission_read_scope import AdmissionReadScope
    from v0222_presentation_references import ReferenceProvider, prepare_p4

    coverage = {"scopes": [], "guards": [], "runtime_guard_count": 0, "generate_boundary_count": 0}
    result = {
        "coverage": coverage,
        "terminal_status": "PREFIX_NOT_REACHED",
        "runtime_guard_wall_ns": [],
        "runtime_guard_intervals": [],
        "session_result": None,
        "session_start_monotonic": None,
        "session_deadline_monotonic": None,
        "session_end_monotonic": None,
        "internal_timing_observed": observe_internal_timing,
        "deadline_hit": False,
        "prefix_marker": False,
        "full_reference_pass": False,
    }
    original_close = AdmissionReadScope._close
    original_run = Session.run
    original_generate = ReferenceProvider.generate
    runtime = False
    expected_episode = None
    batch = None
    primary = None
    view = None

    @wraps(original_close)
    def close(scope, *args, **kwargs):
        try:
            return original_close(scope, *args, **kwargs)
        finally:
            coverage["scopes"].append(
                {
                    "ordinal": len(coverage["scopes"]) + 1,
                    "status": scope.status,
                    "stats": scope.stats,
                }
            )

    @wraps(original_run)
    def run(host, provider, *, deadline):
        nonlocal runtime
        if result["session_result"] is not None or runtime:
            raise RuntimeError("ONE_ORIGINAL_REFERENCE_SESSION_REQUIRED")
        if observe_internal_timing:
            result["session_start_monotonic"] = time.monotonic()
            result["session_deadline_monotonic"] = deadline
        runtime = True
        try:
            outcome = original_run(host, provider, deadline=deadline)
            result["session_result"] = dict(outcome)
            result["deadline_hit"] = outcome["status"] == "EPISODE_DEADLINE"
            return outcome
        finally:
            runtime = False
            if observe_internal_timing:
                result["session_end_monotonic"] = time.monotonic()

    @wraps(original_generate)
    def generate(provider, episode, body):
        if (
            not runtime
            or episode != expected_episode
            or provider.spec["id"] != expected_episode
            or coverage["runtime_guard_count"] != 2
            or result["prefix_marker"]
        ):
            raise RuntimeError("EXACT_FIRST_REFERENCE_GENERATE_BOUNDARY_REQUIRED")
        coverage["generate_boundary_count"] += 1
        result["prefix_marker"] = True
        # Do not inspect or retain body and do not execute the scripted action.
        raise DiagnosticPrefixReached("FROZEN_FIRST_GENERATE_PREFIX")

    def guard():
        boundary = "runtime" if runtime else "setup"
        ordinal = len(coverage["guards"]) + 1
        started = time.perf_counter_ns() if observe_internal_timing else None
        status = "RETURNED"
        try:
            with batch._operation("PREP"):
                pass
        except BaseException:
            status = "UNWOUND"
            raise
        finally:
            elapsed = time.perf_counter_ns() - started if observe_internal_timing else None
            coverage["guards"].append({"ordinal": ordinal, "boundary": boundary, "status": status})
            if runtime:
                coverage["runtime_guard_count"] += 1
                if observe_internal_timing:
                    result["runtime_guard_wall_ns"].append(elapsed)
                    result["runtime_guard_intervals"].append(
                        {"start_ns": started, "end_ns": started + elapsed}
                    )

    AdmissionReadScope._close = close
    Session.run = run
    ReferenceProvider.generate = generate
    try:
        batch = batch_factory()
        spec = batch.plan["P4"][0]
        expected_episode = spec["id"]
        result["episode"] = expected_episode
        if full_prefix:
            if public_loader is not None:
                raise ValueError("ORIGINAL_FULL_PREFIX_PUBLIC_SOURCE_PATH_REQUIRED")

            class PreparationView(_PreparationView):
                def authorize(self, stage):
                    if stage != "PREP":
                        raise ProviderStop("REFERENCE_PREPARATION_CANNOT_AUTHORIZE_MODEL_STAGE")
                    guard()

            view = PreparationView(batch)
            materialize_references(view)
        else:
            public = (
                public_loader(spec)
                if public_loader is not None
                else read(CASES / spec["root"] / "public-initial.json")
            )
            prepare_p4(directory, spec, public, guard)
        result["terminal_status"] = "UNEXPECTED_REFERENCE_COMPLETION"
    except BaseException as exc:
        primary = exc
        result["outer_exception_type"] = type(exc).__name__
        result["outer_reason"] = str(exc)
        session = result["session_result"] or {}
        if (
            result["prefix_marker"]
            and session.get("status") == "FAIL_CLOSED"
            and session.get("exception_type") == "DiagnosticPrefixReached"
            and "close_exception_type" not in session
            and str(exc) == "REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET"
            and coverage["runtime_guard_count"] == 2
            and all(row["status"] == "RETURNED" for row in coverage["guards"])
        ):
            result["terminal_status"] = "PREFIX_REACHED_NOT_REFERENCE_PASS"
        elif result["deadline_hit"]:
            result["terminal_status"] = "ORIGINAL_SESSION_DEADLINE"
        else:
            result["terminal_status"] = "ORIGINAL_PATH_STOP"
    finally:
        ReferenceProvider.generate = original_generate
        Session.run = original_run
        AdmissionReadScope._close = original_close
    result["scope_count"] = len(coverage["scopes"])
    result["prefix_mode"] = "full_55_scope" if full_prefix else "first_p4_5_scope"
    result["p3_reference_count"] = (
        len(list((batch.root / "full-reference" / "P3").glob("*/reference-validation.json")))
        if full_prefix and batch is not None
        else 0
    )
    if result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS" and (
        result["scope_count"] != (55 if full_prefix else 5)
        or len(coverage["guards"]) != (54 if full_prefix else 4)
        or (full_prefix and result["p3_reference_count"] != 16)
        or any(row["status"] != "CLOSED_VERIFIED_TWO_OBSERVATIONS" for row in coverage["scopes"])
    ):
        result["terminal_status"] = "PREFIX_COVERAGE_INCOMPLETE"
    if result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS":
        result["batch_stop"] = {
            "status": (
                "ORIGINAL_MATERIALIZER_DIAGNOSTIC_STOP"
                if full_prefix
                else "NOT_REQUESTED_INTENTIONAL_DIAGNOSTIC_CUTOFF"
            ),
            "instance_reuse_allowed": False,
        }
    elif batch is None:
        result["batch_stop"] = {"status": "NO_CONSTRUCTED_BATCH"}
    else:
        # Match materialize_references' outer view.stop: retain the original
        # ProviderStop text, otherwise use only the original exception type.
        reason = (
            str(primary)
            if isinstance(primary, ProviderStop)
            else type(primary).__name__
            if primary is not None
            else result["terminal_status"]
        )
        try:
            batch.stop(reason)
            result["batch_stop"] = {"status": "STOP_RECORDED", "reason": reason}
        except BaseException as secondary:
            result["batch_stop"] = {
                "status": "SECONDARY_STOP_FAILURE",
                "reason": reason,
                "exception_type": type(secondary).__name__,
            }
            if primary is not None:
                primary.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)
    if view is not None and view.stop_errors:
        result["materializer_secondary_stop_errors"] = list(view.stop_errors)
        if primary is not None:
            for name in view.stop_errors:
                primary.add_note("SECONDARY_PREPARATION_STOP_FAILURE: " + name)
        if result["terminal_status"] == "PREFIX_REACHED_NOT_REFERENCE_PASS":
            result["terminal_status"] = "PREFIX_CLEANUP_FAILED"
    if primary is not None and not isinstance(primary, Exception):
        raise primary
    result["runtime_guard_union_ns"] = (
        sum(result["runtime_guard_wall_ns"]) if observe_internal_timing else None
    )
    return result
