"""Fixed STALE scenarios as three independent probes over one full history.

Data revision: STALEproj/STALE 617c51dc200b5ab09970834144c7e51c77959af0.
Only manifest-selected scenario objects are decoded from the large JSON release.
"""

from __future__ import annotations

import hashlib
import json
import mmap
from collections.abc import Collection
from pathlib import Path
from typing import Any

from milai_lab.datasets.contextual import EvaluationCase, HistoryMessage, TaskInput

PROBE_KEYS = ("dim1_query", "dim2_query", "dim3_query")


def _selected_row(data: mmap.mmap, uid: str) -> dict[str, Any]:
    token = f'"uid": "{uid}"'.encode()
    position = data.find(token)
    if position < 0:
        raise ValueError(f"missing STALE scenario {uid}")
    start = data.rfind(b"\n  {", 0, position)
    if start < 0:
        raise ValueError(f"cannot locate STALE scenario boundary {uid}")
    next_start = data.find(b"\n  {", position + len(token))
    end = next_start if next_start >= 0 else data.rfind(b"\n]")
    if end < 0:
        raise ValueError(f"cannot locate STALE scenario end {uid}")
    row: dict[str, Any] = json.loads(data[start + 1 : end].rstrip().rstrip(b","))
    if row["uid"] != uid:
        raise ValueError(f"STALE scenario ID mismatch for {uid}")
    return row


def _scenario_cases(
    row: dict[str, Any], *, source_revision: str, probe_keys: tuple[str, ...]
) -> list[EvaluationCase]:
    uid = row["uid"]
    opaque_id = hashlib.sha256(f"{source_revision}:{uid}".encode()).hexdigest()[:20]
    history_id = f"stale-{opaque_id}"
    sessions = row["haystack_session"]
    timestamps = row["timestamps"]
    if not isinstance(sessions, list) or len(sessions) != len(timestamps):
        raise ValueError(f"STALE {uid}: sessions/timestamps do not align")
    history: list[HistoryMessage] = []
    for session_index, (session, date) in enumerate(zip(sessions, timestamps, strict=True)):
        if not isinstance(session, list) or not isinstance(date, str):
            raise ValueError(f"STALE {uid}: invalid session {session_index}")
        session_id = f"{history_id}-session-{session_index:03d}"
        for turn_index, turn in enumerate(session):
            role, content = turn["role"], turn["content"]
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise ValueError(f"STALE {uid}: invalid turn {session_index}:{turn_index}")
            history.append(
                HistoryMessage(
                    event_id=f"{session_id}-event-{turn_index:04d}",
                    role=role,
                    content=content,
                    session_id=session_id,
                    date=date,
                )
            )
    shared_history = tuple(history)
    queries = row["probing_queries"]
    metadata = {
        "scenario_id": uid,
        "type": row["type"],
        "M_old": row["M_old"],
        "M_new": row["M_new"],
        "explanation": row["explanation"],
        "relevant_session_index": row["relevant_session_index"],
        "probing_queries": queries,
        "source_revision": source_revision,
    }
    cases: list[EvaluationCase] = []
    for probe_key in probe_keys:
        question = queries[probe_key]
        if not isinstance(question, str):
            raise ValueError(f"STALE {uid}: missing {probe_key}")
        cases.append(
            EvaluationCase(
                case_id=f"{uid}:{probe_key}",
                dataset="stale",
                split="fixed-small",
                task=TaskInput(
                    user_id=f"stale-user-{opaque_id}",
                    history_id=history_id,
                    history=shared_history,
                    question=question,
                ),
                answer=None,
                groups={"type": row["type"], "dimension": probe_key[:4]},
                metadata={**metadata, "probe_key": probe_key},
            )
        )
    return cases


def load_stale(
    selection_path: Path,
    *,
    scenario_ids: Collection[str] | None = None,
    data_path: Path | None = None,
) -> list[EvaluationCase]:
    """Load manifest-selected T1/T2 scenarios without trimming or reordering history."""
    manifest = json.loads(selection_path.read_text(encoding="utf-8"))
    declared = manifest["scenarios"]
    allowed = {entry["scenario_id"] for entry in declared}
    selected = set(scenario_ids) if scenario_ids is not None else allowed
    if selected - allowed:
        raise ValueError(f"STALE scenarios outside fixed selection: {sorted(selected - allowed)}")
    path = data_path or Path(manifest["external_root"]) / "T1_T2_400_FULL.json"
    cases: list[EvaluationCase] = []
    with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for entry in declared:
            uid = entry["scenario_id"]
            if uid not in selected:
                continue
            row = _selected_row(data, uid)
            if row["type"] != entry["type"]:
                raise ValueError(f"STALE type mismatch for {uid}")
            keys = tuple(entry["probe_keys"])
            if keys != PROBE_KEYS:
                raise ValueError(f"STALE probe keys differ from native dimensions for {uid}")
            cases.extend(
                _scenario_cases(row, source_revision=manifest["source_revision"], probe_keys=keys)
            )
    return cases
