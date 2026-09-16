"""Complete runtime validation observation on one new Session instance only.

U delegates to original presentation prepare_p4 without observation clocks.
S records whole validate_runtime intervals, not merely its nested PREP callback.
No18s gate is applied here: qualified calibration must precede interpretation.
"""

from __future__ import annotations

import time
from pathlib import Path

from prepare_v0222_full import resolve_p4_spec, session
from v0218_world import World, digest
from v0220_evidence import save
from v0220_intent_audit import effects
from v0220_provider_hardened import ProviderStop
from v0222_presentation_references import ReferenceProvider
from v0222_presentation_references import prepare_p4 as original_prepare_p4


def _validate_observation(observation, turns):
    callbacks = observation["callback_counts"]
    expected_runtime = 1 + 2 * turns
    if callbacks != {"attempted": expected_runtime + 2, "returned": expected_runtime + 2}:
        raise ValueError("COMPLETE_SETUP_AND_RUNTIME_CALLBACK_COUNTS_REQUIRED")
    if observation["mode"] == "U":
        if observation["runtime_intervals"] or observation["session_interval"] is not None:
            raise ValueError("STRICT_U_INTERNAL_TIMING_FORBIDDEN")
        return
    spans = observation["runtime_intervals"]
    session_span = observation["session_interval"]
    if (
        observation["setup_callbacks"] != {"attempted": 2, "returned": 2}
        or len(spans) != expected_runtime
        or session_span is None
    ):
        raise ValueError("EXACT_RUNTIME_SPANS_AND_TWO_SETUP_CALLBACKS_REQUIRED")
    start, end = session_span["start_ns"], session_span["end_ns"]
    if type(start) is not int or type(end) is not int or not start < end:
        raise ValueError("VALID_COMPLETE_SESSION_INTERVAL_REQUIRED")
    cursor = start
    for number, span in enumerate(spans, 1):
        left, right = span["start_ns"], span["end_ns"]
        if (
            span["ordinal"] != number
            or not span["returned"]
            or type(left) is not int
            or type(right) is not int
            or not cursor <= left < right <= end
            or span["callback_attempted_delta"] != 1
            or span["callback_returned_delta"] != 1
        ):
            raise ValueError("COMPLETE_ORDERED_NONOVERLAPPING_RUNTIME_INTERVALS_REQUIRED")
        cursor = right
    observation["runtime_union_ns"] = sum(span["end_ns"] - span["start_ns"] for span in spans)


def _prepare_s(directory: Path, spec: dict, public: dict, validate_binding, observation):
    # Original business statements remain in the same order; only the instance
    # wrapper and outer Session timing statements are inserted.
    if spec.get("stage") != "P4":
        raise ProviderStop("P4_REFERENCE_REQUIRED")
    validate_binding()
    resolved, change = resolve_p4_spec(spec, public)
    world = World.create(directory / "world.sqlite", resolved["scope"], public)
    initial = world.snapshot()
    if digest(initial) != resolved["initial_state_sha256"]:
        raise ProviderStop("REFERENCE_DERIVED_INITIAL_DIGEST_MISMATCH")
    host = session(world, directory, resolved, validate_binding)
    observation["setup_callbacks"] = dict(observation["callback_counts"])
    original_validate_runtime = host.validate_runtime
    had_instance_method = "validate_runtime" in vars(host)
    prior_instance_method = vars(host).get("validate_runtime")

    def observed_validate_runtime():
        counts = observation["callback_counts"]
        attempted_before, returned_before = counts["attempted"], counts["returned"]
        row = {
            "ordinal": len(observation["runtime_intervals"]) + 1,
            "start_ns": None,
            "end_ns": None,
            "returned": False,
        }
        primary = None
        try:
            try:
                row["start_ns"] = time.monotonic_ns()
            except BaseException as error:
                observation["errors"].append("RUNTIME_START_CLOCK: " + repr(error))
            result = original_validate_runtime()
            row["returned"] = True
            return result
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                row["end_ns"] = time.monotonic_ns()
                row["callback_attempted_delta"] = counts["attempted"] - attempted_before
                row["callback_returned_delta"] = counts["returned"] - returned_before
                observation["runtime_intervals"].append(row)
            except BaseException as error:
                observation["errors"].append("RUNTIME_END_OBSERVATION: " + repr(error))
                if primary is not None:
                    primary.add_note("SECONDARY_RUNTIME_OBSERVATION: " + repr(error))

    # Only this fresh instance is changed; original class/modules remain intact.
    provider = ReferenceProvider(directory, resolved)
    host.validate_runtime = observed_validate_runtime
    run_primary = None
    try:
        try:
            observation["session_interval"] = {"start_ns": time.monotonic_ns(), "end_ns": None}
        except BaseException as error:
            observation["errors"].append("SESSION_START_CLOCK: " + repr(error))
        result = host.run(provider, deadline=time.monotonic() + 60)
    except BaseException as error:
        run_primary = error
        raise
    finally:
        try:
            end = time.monotonic_ns()
            if observation["session_interval"] is not None:
                observation["session_interval"]["end_ns"] = end
        except BaseException as error:
            observation["errors"].append("SESSION_END_CLOCK: " + repr(error))
            if run_primary is not None:
                run_primary.add_note("SECONDARY_SESSION_OBSERVATION: " + repr(error))
        finally:
            # Restore exact prior instance attribute state even on business failure.
            try:
                if had_instance_method:
                    host.validate_runtime = prior_instance_method
                else:
                    del host.validate_runtime
            except BaseException as error:
                observation["errors"].append("RUNTIME_INSTANCE_RESTORE: " + repr(error))
                if run_primary is not None:
                    run_primary.add_note("SECONDARY_RUNTIME_INSTANCE_RESTORE: " + repr(error))
    final, ledger = world.snapshot(), world.ledger()
    verdict = effects(resolved, initial, final, ledger, host.rows)
    if result["status"] != "SESSION_FINISHED_NOT_TASK_VERDICT" or verdict["status"] != "PASS":
        raise ProviderStop("REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET")
    if len(provider.rows) != len(resolved["actions"]) + 2 or not 3 <= len(provider.rows) <= 4:
        raise ProviderStop("REFERENCE_COMPLETE_READBACK_FINISH_REQUIRED")
    for name, value in (
        ("initial-world", initial),
        ("final-world", final),
        ("final-ledger", ledger),
        ("independent-effects", verdict),
    ):
        save(directory / (name + ".json"), value)
    return provider.rows, {"spec": resolved, "derived_hash_diff": change}


def prepare_p4_observed(directory, spec, public, validate_binding, *, mode, observation):
    """Caller supplies an empty exact dict; it is filled even when business fails."""
    if mode not in {"U", "S"} or type(observation) is not dict or observation:
        raise TypeError("EXACT_MODE_AND_EMPTY_OBSERVATION_DICT_REQUIRED")
    observation.update(
        mode=mode,
        status="INCOMPLETE",
        callback_counts={"attempted": 0, "returned": 0},
        setup_callbacks=None,
        runtime_intervals=[],
        session_interval=None,
        runtime_union_ns=None,
        errors=[],
    )

    def counted_binding():
        observation["callback_counts"]["attempted"] += 1
        result = validate_binding()
        observation["callback_counts"]["returned"] += 1
        return result

    try:
        if mode == "U":
            result = original_prepare_p4(directory, spec, public, counted_binding)
        else:
            result = _prepare_s(directory, spec, public, counted_binding, observation)
        if observation["errors"]:
            raise ValueError("INVALID_RUNTIME_OBSERVATION")
        _validate_observation(observation, len(result[0]))
        observation["status"] = "STRICT_U_UNTIMED" if mode == "U" else "COMPLETE_RUNTIME_INTERVALS"
        return result
    except BaseException as primary:
        observation["status"] = "FAILED_NOT_MEASUREMENT_QUALIFIED"
        observation["primary_exception"] = type(primary).__name__
        observation["primary_reason"] = str(primary)
        raise
