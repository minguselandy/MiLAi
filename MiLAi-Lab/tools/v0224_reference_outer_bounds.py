"""R03 conservative outer bounds, without Session-internal timing probes.

A qualified complete Session wall <=18s proves its contained admission union is
<=18s. Exceeding that wall fails this stronger gate; it does not measure the union.
The prepare interval additionally includes setup, original checks and raw saves,
but neither interval includes subsequent caller or parent finish/commit work.
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

SESSION_OUTER_LIMIT_NS = 18_000_000_000


def prepare_p4_bounded(
    directory: Path, spec: dict, public: dict, validate_binding, *, bounds_collector: list
) -> tuple[list, dict]:
    """Original complete reference preparation plus an explicit stronger wall gate.

    Collector must be a caller-owned exact list. Original failures remain primary;
    failed/incomplete runs never yield a qualified admission-union upper bound.
    Four observer clock reads on success; original deadline evaluation unchanged.
    """
    if type(bounds_collector) is not list:
        raise TypeError("EXACT_OUTER_BOUNDS_COLLECTOR_LIST_REQUIRED")
    prepare_start = time.monotonic_ns()
    session_start = session_end = None
    prepare_completed = session_completed = False
    primary = None
    try:
        if spec.get("stage") != "P4":
            raise ProviderStop("P4_REFERENCE_REQUIRED")
        validate_binding()
        resolved, change = resolve_p4_spec(spec, public)
        world = World.create(directory / "world.sqlite", resolved["scope"], public)
        initial = world.snapshot()
        if digest(initial) != resolved["initial_state_sha256"]:
            raise ProviderStop("REFERENCE_DERIVED_INITIAL_DIGEST_MISMATCH")
        host = session(world, directory, resolved, validate_binding)
        provider = ReferenceProvider(directory, resolved)
        session_start = time.monotonic_ns()
        result = host.run(provider, deadline=time.monotonic() + 60)
        session_end = time.monotonic_ns()
        session_completed = True
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
        prepare_completed = True
        if session_end <= session_start:
            raise ProviderStop("POSITIVE_COMPLETE_SESSION_OUTER_WALL_REQUIRED")
        if session_end - session_start > SESSION_OUTER_LIMIT_NS:
            raise ProviderStop("STRONG_OUTER_WALL_LIMIT_EXCEEDED_NOT_UNION_FAILURE")
        return provider.rows, {"spec": resolved, "derived_hash_diff": change}
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            prepare_end = time.monotonic_ns()
            if type(prepare_end) is not int or prepare_end <= prepare_start:
                raise ProviderStop("POSITIVE_COMPLETE_PREPARE_OUTER_WALL_REQUIRED")
            session_wall = None if session_end is None else session_end - session_start
            qualified = (
                primary is None
                and prepare_completed
                and session_completed
                and session_wall is not None
                and 0 < session_wall <= SESSION_OUTER_LIMIT_NS
            )
            bounds_collector.append(
                {
                    "status": "QUALIFIED_OUTER_UPPER_BOUND" if qualified else "NOT_QUALIFIED",
                    "timing_kind": "OUTER_WALL_UPPER_BOUND_NOT_EXACT_ADMISSION_UNION",
                    "session_wall_ns": session_wall,
                    "prepare_wall_ns": prepare_end - prepare_start,
                    "session_completed": session_completed,
                    "prepare_completed": prepare_completed,
                    "session_wall_at_most_18": (
                        None if session_wall is None else 0 < session_wall <= SESSION_OUTER_LIMIT_NS
                    ),
                    "admission_union_upper_bound_ns": session_wall if qualified else None,
                    "primary_exception": None if primary is None else type(primary).__name__,
                    "primary_reason": None if primary is None else str(primary),
                }
            )
        except BaseException as observation_error:
            if primary is None:
                raise
            primary.add_note(
                "SECONDARY_OUTER_BOUND_OBSERVATION_FAILURE: " + repr(observation_error)
            )
