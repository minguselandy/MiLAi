"""Fixed, native MemSyco-Bench rows with gold confined to evaluation cases.

Source: XMUDeepLIT/MemSyco-Bench fd1f0f0270f35467aace1f9c0bf6a8bfb9b87221.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milai_lab.datasets.contextual import EvaluationCase, HistoryMessage, TaskInput

TRACKS = frozenset(
    {"contextual_scope_control", "valid_memory_selection", "personalized_memory_use"}
)
_ROW_ID = re.compile(r'^\s*\{\s*"id"\s*:\s*"([^"]+)"')


@dataclass(frozen=True)
class MemSycoTask:
    """Runtime input, deliberately without the source row's evaluation/metadata."""

    case_id: str
    track: str
    task: TaskInput


def _task(row: dict[str, Any], *, source_commit: str) -> MemSycoTask:
    case_id = row["id"]
    track = row["task"]
    if track not in TRACKS:
        raise ValueError(f"unsupported MemSyco track: {track}")
    dialogue = row["dialogue"]
    if not isinstance(dialogue, list) or not dialogue:
        raise ValueError(f"MemSyco {case_id}: dialogue must be a nonempty list")
    opaque_id = hashlib.sha256(f"{source_commit}:{track}:{case_id}".encode()).hexdigest()[:20]
    history_id = f"memsyco-{opaque_id}"
    history: list[HistoryMessage] = []
    for index, turn in enumerate(dialogue):
        role, content = turn["role"], turn["content"]
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise ValueError(f"MemSyco {case_id}: invalid dialogue turn {index}")
        history.append(
            HistoryMessage(
                event_id=f"{history_id}-event-{index:06d}",
                role=role,
                content=content,
            )
        )
    question = row["question"]
    if not isinstance(question, str):
        raise ValueError(f"MemSyco {case_id}: question must be a string")
    return MemSycoTask(case_id, track, TaskInput(
        user_id=f"memsyco-user-{opaque_id}", history_id=history_id,
        history=tuple(history), question=question))


def _case(row: dict[str, Any], *, split: str, source_commit: str) -> EvaluationCase:
    runtime = _task(row, source_commit=source_commit)
    evaluation, source_metadata = row["evaluation"], row["metadata"]
    return EvaluationCase(
        case_id=runtime.case_id,
        dataset="memsyco",
        split=split,
        task=runtime.task,
        answer=evaluation["reference_answer"],
        groups={"track": runtime.track, "subtype": source_metadata.get("subtype", "")},
        metadata={
            "task": runtime.track,
            "memory": row["memory"],
            "evaluation": evaluation,
            "source_metadata": source_metadata,
            "source_commit": source_commit,
        },
    )


def _selected_rows(
    selection_path: Path,
    *,
    group: str = "screen",
    case_ids: Collection[str] | None = None,
    data_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read only IDs selected by the frozen manifest, in manifest order.

    ``case_ids`` narrows a declared group; it cannot introduce other rows.
    Confirmation is intentionally opt-in via ``group='confirmation'``.
    """
    manifest = json.loads(selection_path.read_text(encoding="utf-8"))
    if group not in {"screen", "smoke", "development", "confirmation"}:
        raise ValueError("MEMSYCO_GROUP_UNDECLARED")
    declared = manifest["groups"][group]["cases"]
    allowed = {(entry["task"], entry["case_id"]) for entry in declared}
    selected_ids = set(case_ids) if case_ids is not None else {case_id for _, case_id in allowed}
    unknown = selected_ids - {case_id for _, case_id in allowed}
    if unknown:
        raise ValueError(f"MemSyco IDs outside {group}: {sorted(unknown)}")
    wanted = {(track, case_id) for track, case_id in allowed if case_id in selected_ids}
    root = data_root or Path(manifest["external_root"])
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for source in manifest["source_files"]:
        track = source["task"]
        ids = {case_id for task, case_id in wanted if task == track}
        if not ids:
            continue
        path = root / source["relative_path"]
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                match = _ROW_ID.match(line)
                if match is None or match.group(1) not in ids:
                    continue
                row = json.loads(line)
                key = (row["task"], row["id"])
                if key not in wanted:
                    continue
                if key in found:
                    raise ValueError(f"duplicate MemSyco case {key}")
                found[key] = row
    missing = wanted - found.keys()
    if missing:
        raise ValueError(f"missing MemSyco cases: {sorted(missing)}")
    return manifest, [
        found[(entry["task"], entry["case_id"])]
        for entry in declared
        if (entry["task"], entry["case_id"]) in wanted
    ]


def load_memsyco(selection_path: Path, *, group: str = "screen",
                 case_ids: Collection[str] | None = None,
                 data_root: Path | None = None) -> list[EvaluationCase]:
    """Evaluator-only rows; historical screen/confirmation behavior is unchanged."""
    manifest, rows = _selected_rows(selection_path, group=group, case_ids=case_ids,
                                    data_root=data_root)
    return [_case(row, split=group, source_commit=manifest["source_commit"]) for row in rows]


def load_memsyco_tasks(selection_path: Path, *, group: str,
                       case_ids: Collection[str] | None = None,
                       data_root: Path | None = None) -> list[MemSycoTask]:
    """Strip evaluator fields before handing any benchmark material to the runtime."""
    manifest, rows = _selected_rows(selection_path, group=group, case_ids=case_ids,
                                    data_root=data_root)
    return [_task(row, source_commit=manifest["source_commit"]) for row in rows]
