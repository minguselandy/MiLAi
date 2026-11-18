"""Read the clean memory-control split as native M0/M1 training rows."""

from __future__ import annotations

import math
import random
import sqlite3
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA
from milai_lab.datasets.memory_control_store import DB_NAME, connect, get_meta, unpack
from milai_lab.datasets.memory_control_views import tokenize_path
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.memory_control import MemoryAction


@dataclass(frozen=True)
class StateIndex:
    id: int
    dataset: str
    group: str
    root: int
    recipe: str
    bucket: tuple[int, int]


class MemoryControlDataset:
    def __init__(self, path: Path, *, require_complete: bool = True) -> None:
        self.path = path / DB_NAME if path.is_dir() else path
        with closing(connect(self.path)) as db:
            self.config = get_meta(db, "configuration")
            self.tokenizers = get_meta(db, "tokenizers")
            self.run_id = get_meta(db, "run_id")
            self.random_groups = {
                key: set(values) for key, values in get_meta(db, "random_source_groups", {}).items()
            }
            if require_complete and not get_meta(db, "build_done"):
                raise ValueError("The dataset has not finished building")
        self.reader = tokenize_path(self.tokenizers["reader"]["path"])
        self.material_limit = self.config["views"]["reader_material_tokens"]

    def index(self, role: str) -> list[StateIndex]:
        if role not in {"train", "validation"}:
            raise ValueError("Select an explicit clean split")
        with closing(connect(self.path)) as db:
            return [
                StateIndex(
                    r["id"],
                    r["dataset"],
                    r["native_group"],
                    r["root_id"],
                    r["recipe"],
                    (r["object_count"] // 8, r["encoder_length_bucket"]),
                )
                for r in db.execute(
                    """
                        SELECT s.id,t.dataset,t.native_group,t.root_id,s.recipe,
                               s.object_count,s.encoder_length_bucket
                        FROM task_index t JOIN states s ON s.task_id=t.id
                        WHERE t.clean_role=? ORDER BY t.root_id,s.id
                    """,
                    (role,),
                )
            ]

    def windows(self, steps: int, batch_size: int, seed: int) -> list[list[int]]:
        """Rotate datasets and roots, then bucket the finite selected CPU batch."""
        index = self.index("train")
        by_group: dict[str, dict[str, list[StateIndex]]] = defaultdict(lambda: defaultdict(list))
        for row in index:
            by_group[row.dataset][row.group].append(row)
        if not by_group or steps <= 0 or batch_size <= 0:
            raise ValueError("The schedule needs clean TRAIN data and a positive step/batch size")
        datasets = sorted(by_group)
        rng = random.Random(seed)  # noqa: S311 -- reproducible exposure schedule
        queues: dict[tuple[str, bool], deque[str]] = {}
        for source, groups in by_group.items():
            for random_source in (True, False):
                ordered = [
                    group
                    for group in sorted(groups)
                    if (group in self.random_groups[source]) == random_source
                ]
                rng.shuffle(ordered)
                queues[source, random_source] = deque(ordered)
        batch_size = min(batch_size, len(index))
        quota = math.ceil(batch_size * self.config["states"]["random_source_fraction"])
        result = []
        for step in range(steps):
            selected: dict[int, StateIndex] = {}
            for slot in range(batch_size):
                source = datasets[(step * batch_size + slot) % len(datasets)]
                stratum = slot < quota
                for fallback in (stratum, not stratum):
                    queue = queues[source, fallback]
                    for _ in range(len(queue)):
                        group = queue[0]
                        queue.rotate(-1)
                        choices = [r for r in by_group[source][group] if r.id not in selected]
                        if choices:
                            row = rng.choice(choices)
                            selected[row.id] = row
                            break
                    else:
                        continue
                    break
            result.append([r.id for r in sorted(selected.values(), key=lambda r: r.bucket)])
        return result

    def replay(
        self,
        db: sqlite3.Connection,
        state_id: int,
        pool: CorpusPool | None = None,
        *,
        allow_excluded: bool = False,
    ) -> tuple[sqlite3.Row, CorpusExecution, list[MemoryAction]]:
        row = db.execute(
            """
            SELECT s.*,t.dataset,t.root_id,t.native_group,t.raw_path,t.location,t.native_id,
                   t.setting,t.source_row,t.split,t.clean_role,t.query
            FROM states s JOIN task_index t ON t.id=s.task_id WHERE s.id=?
        """,
            (state_id,),
        ).fetchone()
        if row is None:
            raise KeyError(state_id)
        if row["clean_role"] == "excluded" and not allow_excluded:
            raise ValueError("State is outside the clean training/validation split")
        if pool is None or pool.root_id != row["root_id"]:
            pool = CorpusPool(db, row["root_id"])
        session = CorpusExecution(
            pool, row["query"], unpack(row["candidates"]), self.reader, self.material_limit
        )
        actions = session.replay(row["control_steps"], unpack(row["prefix"]))
        if (
            [asdict(a) for a in actions] != unpack(row["actions"])
            or [list(item) for item in session.opened.items()] != unpack(row["delivered"])
            or session.used_tokens != row["material_tokens"]
        ):
            raise ValueError(f"Saved action, view or budget does not replay for state {state_id}")
        return row, session, actions

    def rows(self, state_ids: list[int], *, allow_excluded: bool = False) -> list[dict[str, Any]]:
        """Warm CPU data grouped by root, with exact native rows returned in caller order."""
        with closing(connect(self.path)) as db:
            # Join each scheduled ID first. Loading one paper or dialogue can serve many rows.
            by_root: dict[int, list[int]] = defaultdict(list)
            for state_id in dict.fromkeys(state_ids):
                scope = db.execute(
                    "SELECT t.root_id FROM states s JOIN tasks t ON t.id=s.task_id WHERE s.id=?",
                    (state_id,),
                ).fetchone()
                if scope is None:
                    raise KeyError(state_id)
                by_root[scope[0]].append(state_id)
            ready = {}
            for root, group in by_root.items():
                pool = CorpusPool(db, root)
                annotations: dict[int, Any] = {}
                for sid in group:
                    state, session, actions = self.replay(
                        db, sid, pool, allow_excluded=allow_excluded
                    )
                    task_id = state["task_id"]
                    if task_id not in annotations:
                        annotations[task_id] = unpack(
                            db.execute(
                                "SELECT data FROM annotations WHERE task_id=?", (task_id,)
                            ).fetchone()[0]
                        )
                    weak = db.execute(
                        "SELECT * FROM weak_labels WHERE state_id=?", (sid,)
                    ).fetchone()
                    values = unpack(weak["evidence"])
                    if len(values) != len(actions):
                        raise ValueError("Weak labels do not match this action menu")
                    annotation = annotations[task_id]
                    answerability = None
                    preference = None
                    if state["dataset"] == MUSIQUE:
                        answerability = [annotation["answerable"]]
                    elif state["dataset"] == PERSONA:
                        preference = {
                            k: annotation[k]
                            for k in ("who", "updated", "prev_pref", "sensitive_info", "preference")
                        }
                    else:
                        answerability = [
                            not ann["answer"]["unanswerable"]
                            for ann in annotation["answer_annotations"]
                        ]
                    ready[sid] = {
                        "sample_id": f"state-{sid}",
                        "group_id": (f"{state['dataset']}/{state['native_group']}"),
                        "split": state["clean_role"],
                        **session.online(actions),
                        "offline_supervision": {
                            "label_grade": "weak_native_evidence",
                            "weak_evidence_loss_weight": 1.0,
                            "weak_evidence_values": {
                                a.id: v for a, v in zip(actions, values, strict=True)
                            },
                            "weak_evidence_known_mask": [v is not None for v in values],
                            "weak_answerability": answerability,
                            "weak_preference": preference,
                            "corpus_coverage": weak["corpus_coverage"],
                            "observed_action_ids": [],
                            "preferences": [],
                        },
                        "execution": {"status": "not_executed", "outcome": None, "cost": None},
                        "provenance": {
                            "dataset": state["dataset"],
                            "task_id": task_id,
                            "original_split": state["split"],
                            "raw_path": state["raw_path"],
                            "original_row": state["source_row"],
                            "native_id": state["native_id"],
                            "setting": state["setting"],
                            "state_recipe": state["recipe"],
                            "sampling": state["sampling"],
                        },
                        "object_count": state["object_count"],
                    }
        return [ready[sid] for sid in state_ids]

    def smoke_batch(self, role: str) -> list[dict[str, Any]]:
        """Choose genuine known targets with different menus and previously opened material."""
        index = self.index(role)
        batch: list[dict[str, Any]] = []
        for source in sorted(self.config["sources"]):
            recipes = (
                ("initial_candidates",)
                if source == MUSIQUE
                else ("after_read", "initial_candidates")
            )
            found = False
            for recipe in recipes:
                seen = set()
                for item in index:
                    if item.dataset != source or item.group in seen or item.recipe != recipe:
                        continue
                    seen.add(item.group)
                    loaded = self.rows([item.id])
                    supervision = loaded[0]["offline_supervision"]
                    values = supervision["weak_evidence_values"].values()
                    if not any(v is True for v in values):
                        continue
                    batch.extend(loaded)
                    found = True
                    break
                if found:
                    break
            if not found:
                raise ValueError(f"No eligible real {source}/{role} row for training verification")
        return batch
