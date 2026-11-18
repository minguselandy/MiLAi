"""Collect the actual before states reached by frozen policies on TRAIN groups."""

from __future__ import annotations

import json
import random
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.datasets.memory_control_store import connect, dumps, packed
from milai_lab.methods.dataset_control_states import evidence_for, plan_state, task_annotation
from milai_lab.methods.dataset_revision_states import Variant, diagnostics, write_variant
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState, run_memory_control
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import make_policy, start_cold
from milai_lab.runners.memory_control_outcome_run import DEFAULT_STATE_QUOTAS, group_round_robin

SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_state_runs (
    run_id TEXT PRIMARY KEY, config TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_state_visits (
    run_id TEXT NOT NULL REFERENCES policy_state_runs(run_id),
    state_id INTEGER NOT NULL REFERENCES state_variants(state_id),
    source_policy TEXT NOT NULL, online_step INTEGER NOT NULL,
    PRIMARY KEY(run_id,state_id)
);
CREATE TABLE IF NOT EXISTS policy_collection_tasks (
    run_id TEXT NOT NULL REFERENCES policy_state_runs(run_id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    source_policy TEXT NOT NULL, trajectory BLOB NOT NULL,
    PRIMARY KEY(run_id,task_id)
);
"""


class RandomLegal:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311 -- declared exploration draw

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        return self.rng.choice(actions).id


def _source_balanced_order(
    available: list[tuple[int, str, set[str]]], rng: random.Random,
) -> Iterator[tuple[int, set[str]]]:
    by_source: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
    for row in available:
        by_source[row[1].partition("/")[0]].append(row)
    queues = {source: group_round_robin(rows, rng) for source, rows in by_source.items()}
    visits: Counter[str] = Counter()
    while queues:
        source = min(queues, key=lambda name: (visits[name] / DEFAULT_STATE_QUOTAS[name], name))
        item = next(queues[source], None)
        if item is None:
            del queues[source]
        else:
            visits[source] += 1
            yield item


def stopped_checkpoints(paths: list[Path]) -> list[dict[str, Any]]:
    if len(paths) != 2:
        raise ValueError("Policy-state collection needs both trained outcome arms")
    arms = []
    for name, architecture, path in zip(
        ("M0", "M1"), ("object_mlp", "latent_pointer"), paths, strict=True,
    ):
        run = json.loads((path.parent / "run.json").read_text())
        if run["status"] != "COMPLETED" or run["contract"]["supervision_mode"] != "outcome":
            raise ValueError("Policy expansion requires both completed outcome fits")
        if run["contract"]["observation_protocol"] != "semantic_nav_v1":
            raise ValueError("The public state pool uses the common semantic observation")
        if run["contract"]["config"]["object_architecture"] != architecture:
            raise ValueError(f"{name} policy collection requires the matching architecture")
        arms.append(
            {
                "name": name,
                "policy": "checkpoint",
                "checkpoint": str(path.resolve()),
                "observation_protocol": "semantic_nav_v1",
                "stop": "learned",
            }
        )
    return arms


def collect(
    data: Path,
    run_id: str,
    paths: list[Path],
    output: Path,
    *,
    target_states: int,
    task_limit: int | None,
    seed: int,
    device: str,
    balance_sources: bool = False,
) -> dict[str, Any]:
    if target_states <= 0 or (task_limit is not None and task_limit <= 0):
        raise ValueError("Collection counts must be positive")
    dataset = MemoryControlDataset(data)
    revision = dataset.revision
    if revision is None:
        raise ValueError("Policy state aggregation requires V1.1")
    arms = stopped_checkpoints(paths)
    rules = {"name": "rules", "policy": "B3"}
    policies = {arm["name"]: make_policy(dataset, arm, device)[0] for arm in [*arms, rules]}
    order = ("M0", "M1", "rules", "M0", "M1", "M0", "M1", "random", "M0", "M1")
    declaration = {
        "dataset_run_id": dataset.run_id,
        "arms": arms,
        "seed": seed,
        "budget": revision["primary_budget"],
        "policy_rotation": list(order),
        "target_states": target_states,
    }
    if balance_sources:
        declaration["source_task_rotation"] = dict(DEFAULT_STATE_QUOTAS)
    wall, cpu = time.perf_counter(), time.process_time()
    with closing(connect(dataset.path, writable=True)) as db:
        db.executescript(SCHEMA)
        with db:
            saved = db.execute(
                "SELECT config FROM policy_state_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if saved and json.loads(saved[0]) != declaration:
                raise ValueError("Policy collection registration changed")
            if not saved:
                db.execute(
                    "INSERT INTO policy_state_runs VALUES (?,?)", (run_id, dumps(declaration))
                )
        available: list[tuple[int, str, set[str]]] = [
            (r["id"], r["dataset"] + "/" + r["native_group"], set())
            for r in db.execute("""
            SELECT id,dataset,native_group FROM experiment_tasks
            WHERE experiment_role='train' ORDER BY dataset,native_group,id
        """)
        ]
        rng = random.Random(seed)  # noqa: S311 -- registered task order
        candidates = (
            _source_balanced_order(available, rng) if balance_sources
            else group_round_robin(available, rng)
        )
        processed = {
            tid
            for (tid,) in db.execute(
                "SELECT task_id FROM policy_collection_tasks WHERE run_id=?", (run_id,)
            )
        }
        states = db.execute(
            "SELECT count(*) FROM policy_state_visits WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        sampled = 0
        newly_added: Counter[str] = Counter()
        for sequence, (tid, _) in enumerate(candidates):
            if states >= target_states or sampled == task_limit:
                break
            if tid in processed:
                continue
            task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (tid,)).fetchone()
            budget = revision["primary_budget"]
            steps = dataset.config["states"]["control_steps"]
            session, _ = start_cold(dataset, db, task, budget)
            session.shared_preflight = {}
            if not session.take(next(a for a in session.menu(steps) if a.kind == "SEARCH")):
                raise ValueError("Cannot collect a policy state after failed SEARCH")
            source = order[sequence % len(order)]
            policy = RandomLegal(seed + sequence) if source == "random" else policies[source]
            result = run_memory_control(
                session.state, policy, session, max_steps=steps, start_step=1
            )
            # Replay the selected trajectory and only then open offline evidence labels.
            fresh = dataset.start_task(db, task, session.pool, session.focus, budget)
            fresh.shared_preflight = session.shared_preflight
            fresh.take(next(a for a in fresh.menu(steps) if a.kind == "SEARCH"))
            gold = task_annotation(db, task)
            if task["dataset"] == MUSIQUE:
                gold["object_locators"] = [
                    (oid, json.loads(place))
                    for oid, place in db.execute(
                        "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
                    )
                ]
            evidence = evidence_for(task["dataset"], gold, fresh.pool)
            with db:
                for event in result["trace"]:
                    raw = fresh.menu(steps)
                    exact = [fresh.feasibility(a) for a in raw]
                    effective = [asdict(a) for a in fresh.feasible_menu(raw)]
                    if event["before"] != fresh.state.project() or event["actions"] != effective:
                        raise ValueError(
                            "Policy collection replay changed its actual decision input"
                        )
                    duplicate = db.execute(
                        """
                        SELECT 1 FROM states s JOIN state_variants v ON v.state_id=s.id
                        WHERE s.task_id=? AND v.material_budget=? AND s.control_steps=?
                          AND s.prefix=? AND s.candidates=? AND v.observation_protocol=?
                    """,
                        (
                            tid,
                            budget,
                            steps,
                            packed(fresh.prefix),
                            packed(fresh.focus),
                            revision["observation_protocol"],
                        ),
                    ).fetchone()
                    if duplicate is None:
                        planned = plan_state(
                            task,
                            fresh,
                            raw,
                            evidence,
                            steps,
                            "policy_reached",
                            "policy_reached",
                            dataset.tokenizers["encoder"]["maximum_memory_objects"],
                        )
                        feature = Variant(
                            planned,
                            None,
                            packed(exact),
                            packed(diagnostics(fresh, raw, evidence, exact)),
                        )
                        sid = write_variant(db, feature, budget, revision)
                        db.execute(
                            "INSERT INTO policy_state_visits VALUES (?,?,?,?)",
                            (run_id, sid, source, event["step"]),
                        )
                        newly_added[source] += 1
                        states += 1
                    selected = next(a for a in raw if a.id == event["selected"])
                    if selected.kind == "HANDOFF" or states >= target_states:
                        break
                    if not fresh.take(selected):
                        raise ValueError(
                            "Actual policy trajectory replay did not deliver its action"
                        )
                db.execute(
                    "INSERT INTO policy_collection_tasks VALUES (?,?,?,?)",
                    (run_id, tid, source, packed(result)),
                )
            sampled += 1
        by_source_policy = [
            dict(row) for row in db.execute("""
                SELECT t.dataset,v.source_policy,count(*) AS states,
                       count(DISTINCT t.id) AS tasks,count(DISTINCT t.native_group) AS native_groups
                FROM policy_state_visits v JOIN states s ON s.id=v.state_id
                JOIN experiment_tasks t ON t.id=s.task_id WHERE v.run_id=?
                GROUP BY t.dataset,v.source_policy ORDER BY t.dataset,v.source_policy
            """, (run_id,))
        ]
        attempted = dict(db.execute("""
            SELECT source_policy,count(*) FROM policy_collection_tasks WHERE run_id=?
            GROUP BY source_policy
        """, (run_id,)))
    receipt = {
        "run_id": run_id,
        "status": "COMPLETE" if states == target_states else "PARTIAL",
        "distinct_states": states,
        "target_states": target_states,
        "new_states": dict(newly_added),
        "new_episodes": sampled,
        "cumulative_states_by_source_policy": by_source_policy,
        "cumulative_episode_attempts_by_policy": attempted,
        "reader_requests": 0,
        "optimizer_updates": 0,
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "configuration": declaration,
    }
    write_json(output, receipt)
    return receipt
