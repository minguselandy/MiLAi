"""Read-only parent terminal adaptation; not admission or process attestation.

The caller supplies fresh SQL rows/events and owns final stop/ownership/deadline
checks, transaction commit and artifact freezing. We neither read current SQL nor
put locally hashed active evidence into an AdmissionReadScope. The unchanged
original auditor still reconstructs sources, raw outputs and public World effects.
Runner-owned exit evidence is checked for consistency, not treated as proof that
an OS process really terminated. Before/after reads are not immutable snapshots.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from pathlib import Path
from types import SimpleNamespace

from v0220_provider_hardened import ProviderStop, usage_state
from v0220_wire_contract import fingerprint
from v0222_http import strict_http_json
from v0222_presentation_audit import audit_episode

PHASE_SECONDS = {"P3": 1800, "P4": 7200}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ProviderStop(code)


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _bytes(path: Path) -> bytes:
    _require(
        path.is_absolute() and path.resolve() == path and path.is_file(),
        "REGULAR_UNALIASED_TERMINAL_EVIDENCE_REQUIRED",
    )
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _episode_files(directory: Path) -> dict[Path, bytes]:
    # Only the original parent audit is excluded. A nested namesake cannot hide.
    return {
        p: _bytes(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
        and p.suffix in {".json", ".jsonl"}
        and p != directory / "independent-audit.json"
    }


def _world_bytes(path: Path) -> bytes:
    _require(
        not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")),
        "CLOSED_WORLD_WITHOUT_UNBOUND_SQLITE_SIDECARS_REQUIRED",
    )
    return _bytes(path)


def audit_claimed_episode(
    batch,
    episode: str,
    *,
    episode_row: dict,
    claim_row: dict,
    launch_row: dict,
    events: list,
) -> dict:
    """Check an owned completed output, returning the old audit plus three pins.

    RUNNING is for parent finish; PASS supports later P3-gate re-audits. FAIL and
    PENDING never qualify. Historical episode deadlines are derived, not compared
    to the current clock: later gate re-audit must not retroactively expire PASS.
    ``events`` is the complete fresh current-batch central event list. This method
    reads files only and never stops, freezes, authorizes or mutates a Batch.
    """
    _require(
        type(episode) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", episode) is not None,
        "CANONICAL_EPISODE_ID_REQUIRED",
    )
    root = Path(batch.root)
    _require(root.is_absolute() and root.resolve() == root, "CANONICAL_BATCH_ROOT_REQUIRED")
    binding = batch.binding_sha
    _require(
        type(binding) is str and re.fullmatch(r"[0-9a-f]{64}", binding) is not None,
        "EXACT_TERMINAL_BINDING_REQUIRED",
    )
    _require(
        all(type(row) is dict for row in (episode_row, claim_row, launch_row))
        and type(events) is list,
        "EXPLICIT_TERMINAL_ROWS_AND_EVENTS_REQUIRED",
    )
    episode_row, claim_row, launch_row, events = copy.deepcopy(
        (episode_row, claim_row, launch_row, events)
    )
    spec, plan, auth = copy.deepcopy((batch.spec(episode), batch.plan, batch.auth))
    stage = spec["stage"]
    _require(stage in PHASE_SECONDS and spec["id"] == episode, "EXACT_TERMINAL_SPEC_REQUIRED")
    cap = 1 if stage == "P3" else 4
    _require(
        episode_row.get("id") == episode
        and episode_row.get("stage") == stage
        and episode_row.get("status") in {"RUNNING", "PASS"}
        and type(episode_row.get("cap")) is int
        and episode_row["cap"] == cap
        and type(episode_row.get("ordinal")) is int
        and episode_row["ordinal"] >= 0,
        "RUNNING_OR_PASSED_EXACT_EPISODE_ROW_REQUIRED",
    )
    _require(
        set(claim_row) == {"episode", "pid", "started", "deadline"}
        and set(launch_row) == {"stage", "pid", "started"}
        and claim_row["episode"] == episode
        and launch_row["stage"] == stage
        and all(
            type(row.get("pid")) is int and row["pid"] > 0
            for row in (episode_row, claim_row, launch_row)
        )
        and episode_row["pid"] == claim_row["pid"] != launch_row["pid"]
        and all(
            _finite(value)
            for value in (
                claim_row["started"],
                claim_row["deadline"],
                launch_row["started"],
                episode_row.get("deadline"),
                auth.get("expires_unix"),
            )
        ),
        "EXACT_COLD_CLAIM_AND_LAUNCH_REQUIRED",
    )
    deadline = min(
        launch_row["started"] + PHASE_SECONDS[stage],
        claim_row["started"] + 300,
        auth["expires_unix"],
    )
    _require(
        launch_row["started"] <= claim_row["started"] < deadline
        and fingerprint(episode_row["deadline"]) == fingerprint(claim_row["deadline"])
        and claim_row["deadline"] == deadline,
        "CLAIM_DERIVED_DEADLINE_DRIFT",
    )
    claim_path = Path(batch.claim_marker_path(episode))
    _require(claim_path == root / "claims" / (episode + ".json"), "EXTERNAL_CLAIM_PATH_REQUIRED")
    launch_path = root / ("live-launch-" + stage + ".json")
    exit_path = root / "exits" / (episode + ".json")
    external = {p: _bytes(p) for p in (claim_path, launch_path, exit_path)}
    claim, launch, exit_record = (
        strict_http_json(external[p].decode("utf-8")) for p in (claim_path, launch_path, exit_path)
    )
    _require(
        fingerprint(claim) == fingerprint({**claim_row, "binding_sha256": binding})
        and fingerprint(launch)
        == fingerprint(
            {
                "stage": stage,
                "pid": launch_row["pid"],
                "unix": launch_row["started"],
                "binding_sha256": binding,
            }
        ),
        "EXACT_CLAIM_AND_LAUNCH_MARKERS_REQUIRED",
    )
    _require(
        type(exit_record) is dict
        and type(exit_record.get("pid")) is int
        and type(exit_record.get("parent_pid")) is int
        and exit_record["pid"] == claim_row["pid"]
        and exit_record["parent_pid"] == launch_row["pid"]
        and type(exit_record.get("returncode")) is int
        and exit_record["returncode"] == 0
        and exit_record.get("timed_out") is False
        and _finite(exit_record.get("seconds"))
        and exit_record["seconds"] <= 300,
        "CLEAN_BOUNDED_COLD_WORKER_EXIT_REQUIRED",
    )
    directory = root / "episodes" / episode
    before = _episode_files(directory)
    ledger_path = directory / "provider" / "provider-ledger-v2.jsonl"
    local = [strict_http_json(line) for line in before[ledger_path].decode("utf-8").splitlines()]
    _require(all(type(e) is dict for e in [*events, *local]), "EVENT_OBJECTS_REQUIRED")
    usage_state(events)  # Validate the complete supplied central FSM before selecting IDs.
    ids = {
        e["request_id"] for e in events if e["event"] == "RESERVED" and e.get("session") == episode
    }
    central = [e for e in events if e["request_id"] in ids]
    _require(
        fingerprint(central) == fingerprint(local), "EXACT_ORDERED_CENTRAL_LOCAL_EVENTS_REQUIRED"
    )
    cost = usage_state(central)
    _require(
        cost["new_generation_allowed"] and cost["requests"] in ({1} if stage == "P3" else {3, 4}),
        "COMPLETE_BOUNDED_TERMINAL_COST_REQUIRED",
    )
    world = root / "worlds" / (episode + ".sqlite")
    if stage == "P4":
        before[world] = _world_bytes(world)
    frozen_view = SimpleNamespace(
        root=root,
        spec=lambda _: copy.deepcopy(spec),
        plan=plan,
        auth=auth,
    )
    result = audit_episode(frozen_view, episode)
    _require(
        result["id"] == episode
        and result["stage"] == stage
        and result["status"] == "PASS"
        and type(result["pid"]) is int
        and result["pid"] == claim_row["pid"]
        and fingerprint(result["cost"]) == fingerprint(cost),
        "ORIGINAL_INDEPENDENT_AUDIT_MUST_MATCH_CLAIM_AND_CENTRAL_COST",
    )
    expected_files = {str(p): _sha(raw) for p, raw in before.items()}
    _require(
        fingerprint(result["files"]) == fingerprint(expected_files),
        "COMPLETE_ORIGINAL_EPISODE_EVIDENCE_SET_REQUIRED",
    )
    after = _episode_files(directory)
    if stage == "P4":
        after[world] = _world_bytes(world)
    _require(before == after, "TERMINAL_EPISODE_EVIDENCE_CHANGED_DURING_AUDIT")
    for path, raw in external.items():
        _require(_bytes(path) == raw, "TERMINAL_EXTERNAL_EVIDENCE_CHANGED_DURING_AUDIT")
    _require(
        fingerprint((batch.spec(episode), batch.plan, batch.auth, batch.binding_sha))
        == fingerprint((spec, plan, auth, binding)),
        "TERMINAL_BATCH_CONTROL_CHANGED_DURING_AUDIT",
    )
    result = copy.deepcopy(result)
    result["files"].update({str(p): _sha(raw) for p, raw in external.items()})
    return result
