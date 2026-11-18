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
from milai_lab.datasets.memory_control_outcomes import outcome_supervision, run_protocols
from milai_lab.datasets.memory_control_reader_task import reader_task
from milai_lab.datasets.memory_control_store import DB_NAME, connect, get_meta, unpack
from milai_lab.datasets.memory_control_views import tokenize_path
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.dataset_reader import DatasetReader
from milai_lab.methods.memory_control import MemoryAction


@dataclass(frozen=True)
class StateIndex:
    id: int
    dataset: str
    group: str
    root: int
    recipe: str
    bucket: tuple[int, int]
    task: int = 0
    budget: int = 2048
    has_positive: bool = False


class MemoryControlDataset:
    def __init__(
        self, path: Path, *, require_complete: bool = True,
        observation_protocol: str | None = None, outcome_runs: tuple[str, ...] = (),
        outcome_role: str = "train",
    ) -> None:
        self.path = path / DB_NAME if path.is_dir() else path
        with closing(connect(self.path)) as db:
            self.config = get_meta(db, "configuration")
            self.tokenizers = get_meta(db, "tokenizers")
            self.run_id = get_meta(db, "run_id")
            derivation = get_meta(db, "derivation")
            self.revision = derivation["revision"] if derivation else None
            scopes = set(get_meta(db, "observation_scopes", []))
            self.random_groups = {
                key: set(values) for key, values in get_meta(db, "random_source_groups", {}).items()
            }
            if require_complete and not get_meta(db, "build_done"):
                raise ValueError("The dataset has not finished building")
            if self.revision and require_complete and not (
                "all" in scopes or {"primary", "train_variants"} <= scopes
            ):
                raise ValueError("The revised primary and TRAIN budget scopes are still building")
            self.observation_protocol = observation_protocol or (
                self.revision["observation_protocol"] if self.revision else "metadata_v1")
            if self.observation_protocol not in {"metadata_v1", "semantic_nav_v1"}:
                raise ValueError("Unknown observation protocol")
            if self.revision is None and self.observation_protocol != "metadata_v1":
                raise ValueError("V1 only has metadata navigation")
            if outcome_runs and not self.revision:
                raise ValueError("Actual branch supervision requires the revised dataset")
            if len(set(outcome_runs)) != len(outcome_runs):
                raise ValueError("Select each outcome run only once")
            if outcome_role not in {"train", "dev"} or (outcome_role == "dev" and not outcome_runs):
                raise ValueError("DEV outcome evaluation needs separate declared outcome runs")
            self.outcome_runs = outcome_runs
            self.outcome_role = outcome_role
            self.outcome_declarations = run_protocols(
                db, outcome_runs, self.observation_protocol, role=outcome_role
            )
        self.reader = tokenize_path(self.tokenizers["reader"]["path"])
        self.material_limit = self.config["views"]["reader_material_tokens"]
        self.host = (DatasetReader(Path(self.config["views"]["reader_config"]))
                     if self.revision else None)
        self.encoder_tokenizer = (tokenize_path(self.tokenizers["encoder"]["path"])
                                  if self.observation_protocol == "semantic_nav_v1" else None)

    def index(self, role: str, *, trainable: bool = False) -> list[StateIndex]:
        if role not in {"train", "validation", "dev"}:
            raise ValueError("Select an explicit clean split")
        with closing(connect(self.path)) as db:
            if self.revision:
                return self._revised_index(db, "dev" if role == "validation" else role,
                                           trainable=trainable)
            if trainable or role == "dev":
                raise ValueError("Coverage and DEV roles require the revised dataset")
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

    def _revised_index(
        self, db: sqlite3.Connection, role: str, *, trainable: bool,
    ) -> list[StateIndex]:
        assert self.revision is not None
        outcome_ids = set()
        if self.outcome_runs and trainable:
            if role != self.outcome_role:
                return []
            outcome_ids = {s for s, run in db.execute("""
                SELECT DISTINCT state_id,run_id FROM action_outcomes
                WHERE execution_status='ingested' AND training_quality IS NOT NULL
            """) if run in self.outcome_runs}
        result = []
        for r in db.execute("""
            SELECT s.id,t.dataset,t.native_group,t.root_id,s.recipe,s.task_id,
                   s.object_count,s.encoder_length_bucket,v.material_budget,
                   v.action_feasibility,w.evidence
            FROM experiment_tasks t JOIN states s ON s.task_id=t.id
            JOIN state_variants v ON v.state_id=s.id JOIN weak_labels w ON w.state_id=s.id
            WHERE t.experiment_role=? AND (? OR s.sampling<>'policy_reached')
              AND (t.experiment_role='train' OR v.material_budget=?)
            ORDER BY t.root_id,s.id
        """, (role, bool(self.outcome_runs), self.revision["primary_budget"])):
            if trainable and self.outcome_runs and r["id"] not in outcome_ids:
                continue
            known = [y for y, (feasible, _) in zip(unpack(r["evidence"]),
                                                  unpack(r["action_feasibility"]), strict=True)
                     if y is not None and feasible is True]
            if trainable and not self.outcome_runs and not known:
                continue
            result.append(StateIndex(r["id"], r["dataset"], r["native_group"], r["root_id"],
                r["recipe"], (r["object_count"] // 8, r["encoder_length_bucket"]),
                r["task_id"], r["material_budget"], any(known)))
        return result

    def start_task(
        self, db: sqlite3.Connection, row: sqlite3.Row, pool: CorpusPool, focus: list[int],
        budget: int, *, annotation: dict[str, Any] | None = None,
    ) -> CorpusExecution:
        if self.revision is None:
            return CorpusExecution(pool, row["query"], focus, self.reader, budget)
        if annotation is None and row["dataset"] == PERSONA:
            task_id = row["task_id"] if "task_id" in row.keys() else row["id"]
            annotation = unpack(db.execute("SELECT data FROM annotations WHERE task_id=?",
                                           (task_id,)).fetchone()[0])
        task_id = row["task_id"] if "task_id" in row.keys() else row["id"]
        public, _ = reader_task(row["dataset"], row["query"], task_id, annotation or {},
                                self.revision["option_seed"])
        navigation: dict[int, dict[str, Any]] = {}
        if self.encoder_tokenizer is not None and focus:
            saved = db.execute("SELECT excerpts FROM task_navigation WHERE task_id=?",
                               (task_id,)).fetchone()
            navigation = ({int(k): v for k, v in unpack(saved[0]).items()} if saved else
                          pool.navigation(row["query"], focus, self.encoder_tokenizer,
                                          self.revision["navigation_tokens_per_candidate"]))
        return CorpusExecution(pool, row["query"], focus, self.reader, budget,
                               public_task=public, host=self.host, navigation=navigation)

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
        annotation: dict[str, Any] | None = None,
    ) -> tuple[sqlite3.Row, CorpusExecution, list[MemoryAction]]:
        source = "experiment_tasks" if self.revision else "task_index"
        extra = ",t.experiment_role,v.material_budget,v.action_feasibility" if self.revision else ""
        variants = "JOIN state_variants v ON v.state_id=s.id" if self.revision else ""
        row = db.execute(
            f"""
            SELECT s.*,t.dataset,t.root_id,t.native_group,t.raw_path,t.location,t.native_id,
                   t.setting,t.source_row,t.split,t.clean_role,t.query {extra}
            FROM states s JOIN {source} t ON t.id=s.task_id {variants} WHERE s.id=?
        """,  # noqa: S608
            (state_id,),
        ).fetchone()
        if row is None:
            raise KeyError(state_id)
        if row["clean_role"] == "excluded" and not allow_excluded:
            raise ValueError("State is outside the clean training/validation split")
        if self.revision and row["experiment_role"] not in {"train", "dev"}:
            raise ValueError("Before-state replay is restricted to train and dev")
        if pool is None or pool.root_id != row["root_id"]:
            pool = CorpusPool(db, row["root_id"])
        session = self.start_task(db, row, pool, unpack(row["candidates"]),
                                  row["material_budget"] if self.revision else self.material_limit,
                                  annotation=annotation)
        actions = session.replay(row["control_steps"], unpack(row["prefix"]))
        if (
            [asdict(a) for a in actions] != unpack(row["actions"])
            or [list(item) for item in session.opened.items()] != unpack(row["delivered"])
            or session.used_tokens != row["material_tokens"]
        ):
            raise ValueError(f"Saved action, view or budget does not replay for state {state_id}")
        return row, session, actions

    def rows(
        self, state_ids: list[int], *, allow_excluded: bool = False, features_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Warm CPU data grouped by root, with exact native rows returned in caller order."""
        with closing(connect(self.path)) as db:
            # Join each scheduled ID first. Loading one paper or dialogue can serve many rows.
            by_root: dict[int, list[int]] = defaultdict(list)
            for state_id in dict.fromkeys(state_ids):
                relation = "experiment_tasks" if self.revision else "task_index"
                role = "experiment_role" if self.revision else "clean_role"
                scope = db.execute(f"""
                    SELECT t.root_id,t.{role} AS role,t.id AS task_id
                    FROM states s JOIN {relation} t ON t.id=s.task_id WHERE s.id=?
                """, (state_id,)).fetchone()  # noqa: S608
                if scope is None:
                    raise KeyError(state_id)
                if ((scope["role"] == "excluded" and not allow_excluded)
                        or (self.revision and scope["role"] not in {"train", "dev"})):
                    raise ValueError("State is outside the permitted supervision roles")
                if self.outcome_runs and scope["role"] != self.outcome_role:
                    raise ValueError("State is outside the loaded outcome role")
                by_root[scope[0]].append(state_id)
            ready = {}
            for root, group in by_root.items():
                pool = CorpusPool(db, root)
                annotations: dict[int, Any] = {}
                for sid in group:
                    task_id, = db.execute(
                        "SELECT task_id FROM states WHERE id=?", (sid,)
                    ).fetchone()
                    if not features_only and task_id not in annotations:
                        annotations[task_id] = unpack(
                            db.execute(
                                "SELECT data FROM annotations WHERE task_id=?", (task_id,)
                            ).fetchone()[0]
                        )
                    state, session, actions = self.replay(
                        db, sid, pool, allow_excluded=allow_excluded,
                        annotation=annotations.get(task_id),
                    )
                    if features_only:
                        if self.revision:
                            feasible = unpack(state["action_feasibility"])
                            actions = [a for a, (fits, _) in zip(actions, feasible, strict=True)
                                       if a.kind != "READ" or fits is True]
                        ready[sid] = {**session.online(actions),
                                      "object_count": state["object_count"]}
                        continue
                    weak = db.execute(
                        "SELECT * FROM weak_labels WHERE state_id=?", (sid,)
                    ).fetchone()
                    values = unpack(weak["evidence"])
                    if len(values) != len(actions):
                        raise ValueError("Weak labels do not match this action menu")
                    if self.revision:
                        weak_by_id = self._feasible_labels(
                            [asdict(action) for action in actions], values,
                            unpack(state["action_feasibility"]),
                        )
                        actions = [a for a in actions if a.id in weak_by_id]
                        values = list(weak_by_id.values())
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
                        "sample_id": self.state_uid(sid),
                        "group_id": (f"{state['dataset']}/{state['native_group']}"),
                        "split": state["experiment_role"] if self.revision else state["clean_role"],
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
                    if self.outcome_runs:
                        ready[sid]["offline_supervision"] = outcome_supervision(
                            db, sid, {a.id for a in actions}, self.outcome_runs)
        return [ready[sid] for sid in state_ids]

    def encoder_rows(self, state_ids: list[int]) -> list[dict[str, Any]]:
        return self.rows(state_ids, features_only=True)

    @staticmethod
    def _feasible_labels(
        actions: list[dict[str, Any]], labels: list[bool | None],
        feasibility: list[list[Any]],
    ) -> dict[str, bool | None]:
        return {a["id"]: y for a, y, (fits, _) in zip(actions, labels, feasibility, strict=True)
                if fits is True or a["kind"] != "READ"}

    def training_rows(self, state_ids: list[int]) -> list[dict[str, Any]]:
        """Read mutable supervision independently from immutable cached encoder inputs."""
        if not self.revision:
            raise ValueError("Feature-linked supervision requires V1.1")
        result = []
        with closing(connect(self.path)) as db:
            for sid in state_ids:
                row = db.execute("""
                    SELECT s.actions,t.dataset,t.native_group,t.id AS task_id,t.experiment_role,
                           v.material_budget,v.action_feasibility,w.evidence
                    FROM states s JOIN experiment_tasks t ON t.id=s.task_id
                    JOIN state_variants v ON v.state_id=s.id JOIN weak_labels w ON w.state_id=s.id
                    WHERE s.id=? AND t.experiment_role IN ('train','dev')
                """, (sid,)).fetchone()
                if row is None:
                    raise ValueError("Unknown or protected state in feature-linked training batch")
                if self.outcome_runs and row["experiment_role"] != self.outcome_role:
                    raise ValueError("State is outside the loaded outcome role")
                menu = unpack(row["actions"])
                values = self._feasible_labels(menu, unpack(row["evidence"]),
                                               unpack(row["action_feasibility"]))
                supervision = (outcome_supervision(db, sid, set(values), self.outcome_runs)
                               if self.outcome_runs else {
                                   "label_grade": "weak_native_evidence",
                                   "weak_evidence_loss_weight": 1.0,
                                   "weak_evidence_values": values,
                               })
                result.append({
                    "sample_id": self.state_uid(sid), "split": row["experiment_role"],
                    "actions": [a for a in menu if a["id"] in values],
                    "offline_supervision": supervision,
                    "group_id": f"{row['dataset']}/{row['native_group']}",
                    "provenance": {"dataset": row["dataset"], "task_id": row["task_id"],
                                   "material_budget": row["material_budget"]},
                })
        return result

    def state_uid(self, state_id: int) -> str:
        if self.revision:
            return f"{self.revision['dataset_release']}/{state_id}@{self.observation_protocol}"
        return f"state-{state_id}"

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
