"""Same-bytes historical accounting for the prospective presentation V2 batch.

This is read-only accounting, not permission to send or restart. The generic
adapter does not choose a lineage or waive unknown usage. presentation_history
checks the exact independently reviewed 57-ledger inventory; a future Batch must
separately verify authorization and fresh historical coordinator terminal states.
No mutable current ledger, central mirror, HTTP or model runtime is used here.
"""

from __future__ import annotations

import json
from pathlib import Path

from v02_local_provider import accounting
from v0220_provider_hardened import usage_state
from v0222_admission_read_scope import AdmissionReadScope
from v0222_scoped_evidence import _guard, read_pinned_events

INVENTORY_PATH = Path(
    "/cra/memory/mx_memory/evidence/v0222-admission-offline/"
    "20260912-read-scope-r1/independent-history-inventory.json"
)
INVENTORY_SHA256 = "58b388f1370093867bcdeac88ee48f24cf55c6d4e992a7c7561ae27fb471f013"


class ScopedHistoryError(ValueError):
    """Historical accounting or the exact frozen carry contract failed."""


def _counts(event: dict, keys: tuple[str, ...]) -> None:
    if any(type(event.get(key)) is not int or event[key] < 0 for key in keys):
        raise ScopedHistoryError("NONNEGATIVE_INTEGER_TOKEN_COUNTS_REQUIRED")


def _bounds(reservation: dict, prompt: int, completion: int) -> None:
    if (
        prompt != reservation["prompt_tokens"]
        or completion > reservation["output_cap"]
        or prompt + completion > reservation["raw_upper_bound"]
    ):
        raise ScopedHistoryError("HISTORICAL_USAGE_RESERVATION_MISMATCH")


def _legacy(events: list[dict]) -> dict:
    """Preserve legacy FSM/accounting; independently check actual usage bounds."""
    pending, seen = {}, set()
    for event in events:
        kind, key = event.get("event"), event.get("request_id")
        if kind == "RESERVED":
            if key in seen:
                raise ScopedHistoryError("DUPLICATE_HISTORICAL_REQUEST")
            _counts(event, ("prompt_tokens", "output_cap", "raw_upper_bound"))
            if event["raw_upper_bound"] != event["prompt_tokens"] + event["output_cap"]:
                raise ScopedHistoryError("INVALID_HISTORICAL_RESERVATION_SUM")
            pending[key] = event
            seen.add(key)
        elif kind == "SETTLED":
            if key not in pending:
                raise ScopedHistoryError("CORRUPT_LEGACY_HISTORY_FSM")
            _counts(event, ("input_tokens", "output_tokens"))
            _bounds(pending[key], event["input_tokens"], event["output_tokens"])
            del pending[key]
        elif kind != "BOUND_VIOLATION" or key not in pending:
            raise ScopedHistoryError("CORRUPT_LEGACY_HISTORY_FSM")
    return accounting(events)


def historical_usage_from_pinned(scope: AdmissionReadScope, sources: list | tuple) -> dict:
    """Aggregate explicit ordered pins: two legacy ledgers, then v2 ledgers.

    Legacy pending objects are retained in full with their actual ledger path.
    Any v2 pending/unknown or violation is rejected, never converted into legacy
    debt. All reservations have globally unique request IDs. Validation failure
    poisons the caller's scope, including when the caller catches the exception.
    The caller still owns close and must not use a result before close succeeds.
    """
    with _guard(scope):
        if type(sources) not in (list, tuple) or len(sources) < 2:
            raise ScopedHistoryError("EXPLICIT_ORDERED_HISTORY_WITH_TWO_LEGACY_LEDGERS_REQUIRED")
        pins, paths, request_ids = [], set(), set()
        pending, violations = [], []
        known = requests = 0
        for index, source in enumerate(sources):
            if type(source) is not dict or set(source) != {"path", "sha256"}:
                raise ScopedHistoryError("EXACT_HISTORY_PATH_AND_SHA256_REQUIRED")
            name = source["path"]
            if (
                type(name) is not str
                or not Path(name).is_absolute()
                or str(Path(name)) != name
                or ".." in Path(name).parts
                or name in paths
            ):
                raise ScopedHistoryError("DISTINCT_CANONICAL_ABSOLUTE_HISTORY_PATHS_REQUIRED")
            paths.add(name)
            events = read_pinned_events(scope, Path(name), source["sha256"])
            for event in events:
                key = event.get("request_id")
                if type(key) is not str or type(event.get("event")) is not str:
                    raise ScopedHistoryError("STRING_HISTORY_EVENT_AND_REQUEST_ID_REQUIRED")
                if event["event"] == "RESERVED":
                    if key in request_ids:
                        raise ScopedHistoryError("GLOBALLY_UNIQUE_HISTORICAL_REQUESTS_REQUIRED")
                    request_ids.add(key)
            if index < 2:
                state = _legacy(events)
                known += state["raw_tokens"]
                pending.extend({**row, "ledger": name} for row in state["pending"])
                violations.extend(state["violations"])
            else:
                state = usage_state(events)
                if state["unresolved_reservations"] or state["violations"]:
                    raise ScopedHistoryError("NO_NEW_HISTORICAL_UNKNOWN_OR_VIOLATION")
                reservations = {
                    event["request_id"]: event for event in events if event["event"] == "RESERVED"
                }
                for event in events:
                    if event["event"] == "USAGE_KNOWN":
                        usage = event["usage"]
                        _bounds(
                            reservations[event["request_id"]],
                            usage["prompt_tokens"],
                            usage["completion_tokens"],
                        )
                known += state["known_raw_tokens"]
            requests += state["requests"]
            pins.append(dict(source))
        return {
            "sources": pins,
            "requests": requests,
            "known_raw_tokens": known,
            "actual_total_raw_tokens": None if pending else known,
            "unresolved_reservations": pending,
            "reserved_raw_upper_bound": sum(row["raw_upper_bound"] for row in pending),
            "reservation_is_actual_usage": False,
            "violations": violations,
            "new_generation_allowed": not pending and not violations,
            "settlement_policy": "Only authentic per-request usage evidence; never CPU inference",
        }


def presentation_history(scope: AdmissionReadScope) -> dict:
    """Verify the exact 57-ledger carry; not an admission or terminal-state gate.

    The inventory digest is a source constant, not a caller-supplied replacement
    unknown whitelist. Its dependency tree and live coordinator SQL remain the
    future Batch lineage check's responsibility, not implied by this function.
    """
    with _guard(scope):
        inventory = scope.read_json(INVENTORY_PATH, INVENTORY_SHA256)
        if (
            inventory["status"] != "INDEPENDENT_HISTORY_INVENTORY_REVIEW_PASS_NOT_AUTHORIZATION"
            or len(inventory["sources"]) != 57
        ):
            raise ScopedHistoryError("EXACT_REVIEWED_57_LEDGER_INVENTORY_REQUIRED")
        result = historical_usage_from_pinned(scope, inventory["sources"])
        aggregate = {
            "ledger_files": len(result["sources"]),
            "requests": result["requests"],
            "known_raw_tokens": result["known_raw_tokens"],
            "unknown_reservations": len(result["unresolved_reservations"]),
            "reserved_raw_upper_bound": result["reserved_raw_upper_bound"],
            "actual_total_raw_tokens": result["actual_total_raw_tokens"],
            "reservation_is_actual_usage": result["reservation_is_actual_usage"],
            "violations": result["violations"],
            "new_unknown_reservations": [],
        }

        # Canonical JSON equality distinguishes bool from int in complete objects.
        def exact(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

        if (
            exact(aggregate) != exact(inventory["aggregate"])
            or exact(result["unresolved_reservations"])
            != exact(inventory["original_unknown_complete_objects"])
            or (result["requests"], result["known_raw_tokens"], result["reserved_raw_upper_bound"])
            != (58, 1081429, 28284)
            or len(result["unresolved_reservations"]) != 1
            or result["violations"]
        ):
            raise ScopedHistoryError("EXACT_ORIGINAL_UNKNOWN_AND_HISTORY_TOTALS_REQUIRED")
        return result
