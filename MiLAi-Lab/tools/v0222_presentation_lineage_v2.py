"""Pinned presentation history plus fresh historical coordinator observations.

This is evidence verification, not authorization, a restart, or a new batch.
The caller owns AdmissionReadScope and must successfully close it before using
the result. Immutable evidence (including frozen World.sqlite files) is checked
through the explicit scoped readers. Current coordinator SQLite databases are
never hashed into that scope or cached: every call opens fresh mode=ro snapshots.
The four snapshots are separate observations, not a distributed transaction.

The oldest V0221 marker has only the new launch-review observation pin. Its
original launch PID/time and unchanged bytes since execution remain UNKNOWN;
passing this verifier does not retroactively establish that historical fact.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from v0220_wire_contract import fingerprint
from v0222_admission_read_scope import AdmissionReadScope
from v0222_scoped_evidence import _guard, _strict_json, read_pinned_events, verify_tree
from v0222_scoped_history import INVENTORY_PATH, INVENTORY_SHA256, presentation_history

LAUNCH_REVIEW_PATH = INVENTORY_PATH.parent / "independent-history-launch-review.json"
LAUNCH_REVIEW_SHA256 = "9c56c0d349b84c08764fae7efbbfc4c1d2a94858ff0ba6f0e1c3def2e32e9b43"
EVIDENCE_INDEX_PATH = INVENTORY_PATH.parent / "lineage-evidence-index.json"
EVIDENCE_INDEX_SHA256 = "50260be836884ed6b507c77f31e58398f4bc2a94c72338dc435f93d4c486b993"
INDEX_STATUS = "FIXED_TWO_ROOT_LINEAGE_EVIDENCE_INDEX_NOT_AUTHORIZATION"


class LineageError(ValueError):
    """A pinned history or fresh terminal coordinator observation changed."""


def read_inventory(scope: AdmissionReadScope) -> dict:
    """Read the fixed inventory only; this is not a complete lineage check."""
    with _guard(scope):
        inventory = scope.read_json(INVENTORY_PATH, INVENTORY_SHA256)
        if (
            inventory["status"] != "INDEPENDENT_HISTORY_INVENTORY_REVIEW_PASS_NOT_AUTHORIZATION"
            or len(inventory["sources"]) != 57
            or len(inventory["terminal_states"]) != 4
            or not isinstance(inventory["files"], dict)
            or not inventory["files"]
        ):
            raise LineageError("EXACT_REVIEWED_INVENTORY_REQUIRED")
        roots = [row["root"] for row in inventory["terminal_states"]]
        if len(set(roots)) != 4:
            raise LineageError("FOUR_DISTINCT_HISTORICAL_COORDINATORS_REQUIRED")
        for name in roots:
            if (
                type(name) is not str
                or not Path(name).is_absolute()
                or str(Path(name)) != name
                or ".." in Path(name).parts
            ):
                raise LineageError("CANONICAL_ABSOLUTE_HISTORICAL_ROOT_REQUIRED")
            for suffix in ("batch.sqlite", "batch.sqlite-wal", "batch.sqlite-shm"):
                if str(Path(name) / suffix) in inventory["files"]:
                    raise LineageError("DYNAMIC_COORDINATOR_MUST_NOT_BE_A_STATIC_PIN")
        for index, source in enumerate(inventory["sources"]):
            if inventory["files"].get(source["path"]) != source["sha256"]:
                raise LineageError("HISTORICAL_LEDGER_PIN_NOT_IN_INVENTORY_FILES")
            if (
                index >= 2
                and sum(
                    Path(source["path"]).is_relative_to(Path(root) / "episodes") for root in roots
                )
                != 1
            ):
                raise LineageError("EVERY_V2_LEDGER_REQUIRES_EXACTLY_ONE_TERMINAL_COORDINATOR")
        return inventory


def _snapshot(root: Path) -> dict:
    """One fresh consistent read-only SQL snapshot; never create a missing DB."""
    path = root / "batch.sqlite"
    if path.resolve() != path or not path.is_file():
        raise LineageError("REGULAR_UNALIASED_EXISTING_COORDINATOR_REQUIRED")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        objects = list(db.execute("SELECT name,type FROM sqlite_master"))
        tables = {row[0] for row in objects if row[1] == "table"}
        if any(row[0] == "launches" and row[1] != "table" for row in objects):
            raise LineageError("LAUNCHES_MUST_BE_ORIGINAL_TABLE_OR_ABSENT")
        meta_rows = list(db.execute("SELECT key,value FROM meta"))
        if len({row[0] for row in meta_rows}) != len(meta_rows):
            raise LineageError("DUPLICATE_HISTORICAL_META_KEYS")
        episodes = [
            dict(row) for row in db.execute("SELECT * FROM episodes ORDER BY stage,ordinal")
        ]
        events = [
            _strict_json(row[0]) for row in db.execute("SELECT event FROM events ORDER BY seq")
        ]
        if any(type(event) is not dict for event in events):
            raise LineageError("CENTRAL_EVENT_OBJECT_REQUIRED")
        launches = (
            [dict(row) for row in db.execute("SELECT * FROM launches ORDER BY stage")]
            if "launches" in tables
            else None
        )
        columns = {
            name: [dict(row) for row in db.execute("SELECT * FROM pragma_table_info(?)", (name,))]
            for name in sorted(tables)
        }
        return {
            "meta": dict(meta_rows),
            "episodes": episodes,
            "events": events,
            "launches": launches,
            "tables": sorted(tables),
            "columns": columns,
        }


def _terminal(scope: AdmissionReadScope, inventory: dict, expected: dict, proof: dict) -> None:
    root = Path(expected["root"])
    files = inventory["files"]
    binding = root / "execution-binding.json"
    if files.get(str(binding)) != expected["binding_sha256"]:
        raise LineageError("TERMINAL_BINDING_PIN_NOT_IN_INVENTORY")
    scope.read_json(binding, expected["binding_sha256"])
    result_path = Path(expected["terminal_result_path"])
    if (
        result_path.parent != root
        or files.get(str(result_path)) != expected["terminal_result_sha256"]
    ):
        raise LineageError("TERMINAL_RESULT_PIN_NOT_IN_INVENTORY")
    result = scope.read_json(result_path, expected["terminal_result_sha256"])
    current = _snapshot(root)
    episodes, events = current["episodes"], current["events"]
    counts = Counter((row["stage"], row["status"]) for row in episodes)
    summaries = [
        {"stage": stage, "status": status, "count": count}
        for (stage, status), count in sorted(counts.items())
    ]
    if (
        current["meta"].get("binding") != expected["binding_sha256"]
        or ("stop" in current["meta"]) != (expected["stop"] is not None)
        or fingerprint(current["meta"].get("stop")) != fingerprint(expected["stop"])
        or fingerprint(episodes) != fingerprint(expected["episodes_snapshot"])
        or fingerprint(episodes) != expected["episodes_fingerprint"]
        or fingerprint(summaries) != fingerprint(expected["episode_state_counts"])
        or [row["id"] for row in episodes if row["status"] == "PENDING"] != expected["unrun"]
        or [row["id"] for row in episodes if row["status"] == "FAIL"] != expected["failed"]
        or fingerprint(episodes) != fingerprint(result["batch"]["episodes"])
        or fingerprint(current["meta"].get("stop")) != fingerprint(result["batch"]["stop"])
    ):
        raise LineageError("HISTORICAL_TERMINAL_BINDING_STOP_OR_EPISODES_CHANGED")
    if (
        fingerprint(current["tables"]) != fingerprint(proof["schema"]["tables"])
        or fingerprint(current["columns"]) != fingerprint(proof["schema"]["columns"])
        or ("launches" in current["tables"]) is not proof["launches"]["table_present"]
    ):
        raise LineageError("HISTORICAL_COORDINATOR_SCHEMA_CHANGED")
    if fingerprint(current["launches"]) != fingerprint(proof["launches"]["expected_rows"]):
        raise LineageError("HISTORICAL_COMPLETE_LAUNCH_STATE_CHANGED")
    if type(expected["central_event_count"]) is not int or (
        len(events) != expected["central_event_count"]
        or fingerprint(events) != expected["central_events_fingerprint"]
    ):
        raise LineageError("HISTORICAL_CENTRAL_EVENTS_CHANGED")
    local = [
        event
        for source in inventory["sources"][2:]
        if Path(source["path"]).is_relative_to(root / "episodes")
        for event in read_pinned_events(scope, Path(source["path"]), source["sha256"])
    ]
    if not local or sorted(map(fingerprint, events)) != sorted(map(fingerprint, local)):
        raise LineageError("HISTORICAL_CENTRAL_LOCAL_MIRROR_DIVERGED")
    if any(
        expected[key] is not True
        for key in (
            "local_mirror_exact_multiset",
            "central_not_counted_as_an_additional_ledger",
            "read_only_snapshots_unchanged",
            "database_files_not_bound",
        )
    ):
        raise LineageError("INVENTORY_TERMINAL_REVIEW_NOT_PASS")


def _launch_review(scope: AdmissionReadScope, inventory: dict) -> dict:
    """Launch-purpose semantics only; public verify_lineage owns the full tree."""
    review = scope.read_json(LAUNCH_REVIEW_PATH, LAUNCH_REVIEW_SHA256)
    if (
        review["status"]
        != "INDEPENDENT_HISTORY_LAUNCH_REVIEW_WITH_EXPLICIT_UNKNOWN_NOT_AUTHORIZATION"
        or fingerprint(review["history_inventory"])
        != fingerprint({"path": str(INVENTORY_PATH), "sha256": INVENTORY_SHA256})
        or [row["root"] for row in review["roots"]]
        != [row["root"] for row in inventory["terminal_states"]]
        or not isinstance(review["files"], dict)
        or not review["files"]
    ):
        raise LineageError("EXACT_PINNED_LAUNCH_SUPPLEMENT_REQUIRED")
    for index, (proof, expected) in enumerate(
        zip(review["roots"], inventory["terminal_states"], strict=True)
    ):
        if (
            proof["binding_sha256"] != expected["binding_sha256"]
            or proof["terminal"]["inventory_pointer"] != f"/terminal_states/{index}"
        ):
            raise LineageError("LAUNCH_SUPPLEMENT_WRONG_TERMINAL_BINDING")
        for key in ("stop", "unrun", "failed", "episode_state_counts", "episodes_fingerprint"):
            if fingerprint(proof["terminal"][key]) != fingerprint(expected[key]):
                raise LineageError("LAUNCH_SUPPLEMENT_TERMINAL_MISMATCH")
        schema = proof["schema"]
        if review["files"].get(schema["source_path"]) != schema["source_sha256"]:
            raise LineageError("LAUNCH_SCHEMA_SOURCE_NOT_PINNED")
        scope.read_bytes(Path(schema["source_path"]), schema["source_sha256"])
        root, markers = Path(proof["root"]), proof["launches"]["markers"]
        marker_paths = [marker["path"] for marker in markers]
        if len(set(marker_paths)) != len(marker_paths) or sorted(marker_paths) != sorted(
            str(path) for path in root.glob("live-launch*.json")
        ):
            raise LineageError("EXACT_CURRENT_LAUNCH_MARKER_SET_REQUIRED")
        for marker in markers:
            path = Path(marker["path"])
            if path.parent != root or review["files"].get(str(path)) != marker["sha256"]:
                raise LineageError("LAUNCH_MARKER_NOT_PINNED_TO_ROOT")
            field = "expected_value"
            if index == 0:
                if (
                    marker["historical_original_pid_and_time"] != "UNKNOWN"
                    or "expected_value" in marker
                ):
                    raise LineageError("OLDEST_LAUNCH_HISTORICAL_UNKNOWN_MUST_REMAIN_EXPLICIT")
                field = "expected_value_for_future_drift_check"
            value = scope.read_json(path, marker["sha256"])
            if (
                fingerprint(value) != fingerprint(marker[field])
                or value["binding_sha256"] != expected["binding_sha256"]
            ):
                raise LineageError("LAUNCH_MARKER_CONTENT_OR_BINDING_CHANGED")
    return review


def verify_lineage(scope: AdmissionReadScope) -> dict:
    """Verify static closure, exact 57-ledger history and four fresh SQL states.

    Returns the unchanged presentation_history object, without counting central
    mirrors again. This does not grant a send, waive unknown costs, or establish
    the original oldest launch PID/time. SQL is always freshly observed, even
    when this function is called twice within one still-open read scope.
    The fixed two-root index gives exactly one same-purpose tree traversal per
    invocation; its private completed set is never shared with another call.
    Each original root still undergoes its own complete purpose-specific checks.
    """
    with _guard(scope):
        index = scope.read_json(EVIDENCE_INDEX_PATH, EVIDENCE_INDEX_SHA256)
        if (
            type(index) is not dict
            or set(index) != {"status", "description", "files"}
            or index["status"] != INDEX_STATUS
            or type(index["description"]) is not str
            or type(index["files"]) is not dict
            or fingerprint(index["files"])
            != fingerprint(
                {
                    str(INVENTORY_PATH): INVENTORY_SHA256,
                    str(LAUNCH_REVIEW_PATH): LAUNCH_REVIEW_SHA256,
                }
            )
            or not INVENTORY_PATH.is_absolute()
            or not LAUNCH_REVIEW_PATH.is_absolute()
            or INVENTORY_PATH == LAUNCH_REVIEW_PATH
        ):
            raise LineageError("EXACT_TWO_PINNED_LINEAGE_ROOTS_REQUIRED")
        verify_tree(scope, EVIDENCE_INDEX_PATH, EVIDENCE_INDEX_SHA256)
        inventory = read_inventory(scope)
        history = presentation_history(scope)
        review = _launch_review(scope, inventory)
        for expected, proof in zip(inventory["terminal_states"], review["roots"], strict=True):
            _terminal(scope, inventory, expected, proof)
        return history
