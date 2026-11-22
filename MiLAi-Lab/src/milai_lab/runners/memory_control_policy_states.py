"""Collect the actual before states reached by frozen policies on TRAIN groups."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
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
from milai_lab.runners.memory_control_checkpoint_selection import training_receipt
from milai_lab.runners.memory_control_episode import make_policy, start_cold
from milai_lab.runners.memory_control_outcome_run import DEFAULT_STATE_QUOTAS, group_round_robin

POLICY_ROTATION = ("M0", "M1", "rules", "M0", "M1", "M0", "M1", "random", "M0", "M1")

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
    weights: dict[str, int] | None = None,
) -> Iterator[tuple[int, set[str]]]:
    by_source: dict[str, list[tuple[int, str, set[str]]]] = defaultdict(list)
    for row in available:
        by_source[row[1].partition("/")[0]].append(row)
    queues = {source: group_round_robin(rows, rng) for source, rows in by_source.items()}
    active_weights = DEFAULT_STATE_QUOTAS if weights is None else weights
    visits: Counter[str] = Counter()
    while queues:
        source = min(queues, key=lambda name: (visits[name] / active_weights[name], name))
        item = next(queues[source], None)
        if item is None:
            del queues[source]
        else:
            visits[source] += 1
            yield item


def _assign_policies(
    candidates: Iterable[tuple[int, set[str]]], sources: dict[int, str] | None,
) -> Iterator[tuple[int, int, str]]:
    visits: Counter[str] = Counter()
    for sequence, (tid, _) in enumerate(candidates):
        position = sequence
        if sources is not None:
            corpus = sources[tid]
            position = visits[corpus]
            visits[corpus] += 1
        yield sequence, tid, POLICY_ROTATION[position % len(POLICY_ROTATION)]


def stopped_checkpoints(
    paths: list[Path], *, observation: str = "semantic_nav_v1", dataset_run_id: str | None = None,
    utility_lambda: float | None = None,
) -> list[dict[str, Any]]:
    if len(paths) != 2:
        raise ValueError("Policy-state collection needs both trained outcome arms")
    arms = []
    representation = None
    for name, architecture, path in zip(
        ("M0", "M1"), ("object_mlp", "latent_pointer"), paths, strict=True,
    ):
        run = json.loads(training_receipt(path).read_text())
        contract = run["contract"]
        if run["status"] != "COMPLETED" or contract["supervision_mode"] != "outcome":
            raise ValueError("Policy expansion requires both completed outcome fits")
        if (contract["observation_protocol"] != observation
                or (dataset_run_id is not None and contract["dataset_run_id"] != dataset_run_id)):
            raise ValueError("The public state pool uses the common semantic observation")
        if contract["config"]["object_architecture"] != architecture:
            raise ValueError(f"{name} policy collection requires the matching architecture")
        fields = ("backbone", "projection_version", "object_feature_layout", "numeric_mode",
                  "quality_cost")
        current = tuple(contract["config"].get(key) for key in fields)
        if representation is not None and current != representation:
            raise ValueError("Both policies need the same deployment representation")
        representation = current
        arms.append(
            {
                "name": name,
                "policy": "checkpoint",
                "checkpoint": str(path.resolve()),
                "observation_protocol": observation,
                "stop": "learned",
                **({"utility_lambda": utility_lambda} if utility_lambda is not None else {}),
            }
        )
    return arms


def inherited_budget_rotation(
    db: sqlite3.Connection, revision: dict[str, Any], seed: int,
) -> dict[tuple[str, str], int]:
    """Choose among registered TRAIN budgets once per native group for this round."""
    primary = revision["primary_budget"]
    allowed = set(revision["train_budget_variants"])
    choices: dict[tuple[str, str], int] = {}
    rows = db.execute("""
        SELECT DISTINCT t.dataset,t.native_group,v.material_budget
        FROM experiment_tasks t JOIN states s ON s.task_id=t.id
        JOIN state_variants v ON v.state_id=s.id
        WHERE t.experiment_role='train' AND s.sampling<>'policy_reached' AND v.material_budget<>?
        ORDER BY t.dataset,t.native_group,v.material_budget
    """, (primary,))
    for source, group, budget in rows:
        key = (source, group)
        if budget in allowed:
            if key in choices and choices[key] != budget:
                raise ValueError("The native group has conflicting registered alternate budgets")
            choices[key] = budget
    rng = random.Random(seed + 1)  # noqa: S311 -- separate fixed stream for budget assignment
    return {key: primary if rng.randrange(3) == 0 else value for key, value in choices.items()}


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
    utility_lambda: float | None = None,
    rotate_train_budgets: bool = False,
) -> dict[str, Any]:
    if target_states <= 0 or (task_limit is not None and task_limit <= 0):
        raise ValueError("Collection counts must be positive")
    first = json.loads(training_receipt(paths[0]).read_text())["contract"]
    dataset = MemoryControlDataset(
        data, observation_protocol=first["observation_protocol"],
        numeric_observation=first["config"].get("numeric_mode", "off") != "off",
    )
    revision = dataset.revision
    if revision is None:
        raise ValueError("Policy state aggregation requires V1.1")
    v12 = dataset.control_release is not None
    if rotate_train_budgets and not v12:
        raise ValueError("Native-group TRAIN budget rotation requires the V1.2 release")
    arms = stopped_checkpoints(
        paths, observation=dataset.observation_protocol,
        dataset_run_id=dataset.run_id if v12 else None, utility_lambda=utility_lambda,
    )
    rules = {"name": "rules", "policy": "B3"}
    policies = {arm["name"]: make_policy(dataset, arm, device)[0] for arm in [*arms, rules]}
    declaration = {
        "dataset_run_id": dataset.run_id,
        "arms": arms,
        "seed": seed,
        "budget": revision["primary_budget"],
        "policy_rotation": list(POLICY_ROTATION),
        "target_states": target_states,
    }
    if balance_sources and not v12:
        declaration["source_task_rotation"] = dict(DEFAULT_STATE_QUOTAS)
    wall, cpu = time.perf_counter(), time.process_time()
    with closing(connect(dataset.path, writable=True)) as db:
        db.executescript(SCHEMA)
        budgets = {}
        if rotate_train_budgets:
            budgets = inherited_budget_rotation(db, revision, seed)
            declaration["budget_rotation"] = {
                "protocol": "inherited_native_group_primary_or_registered_alternate_v1",
                "primary_fraction": 1 / 3,
                "alternates": revision["train_budget_variants"],
                "groups": len(budgets),
            }
        source_targets = None
        if v12:
            datasets = [r[0] for r in db.execute("""
                SELECT DISTINCT dataset FROM experiment_tasks WHERE experiment_role='train'
                ORDER BY dataset
            """)]
            base, extra = divmod(target_states, len(datasets))
            source_targets = {source: base + (index < extra)
                              for index, source in enumerate(datasets)}
            declaration["source_state_targets"] = source_targets
            balance_sources = True
            revision = {**revision, "dataset_release": dataset.config["dataset_release"],
                        "observation_protocol": dataset.observation_protocol}
        with db:
            saved = db.execute(
                "SELECT config FROM policy_state_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            registered = json.loads(saved[0]) if saved else None
            per_source = balance_sources and (
                registered is None or registered.get("policy_rotation_scope") == "source"
            )
            if per_source:
                declaration["policy_rotation_scope"] = "source"
            if registered is not None and registered != declaration:
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
            _source_balanced_order(available, rng, dict.fromkeys(source_targets, 1)
                                   if source_targets else None) if balance_sources
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
        by_source: Counter[str] = Counter(dict(db.execute("""
            SELECT t.dataset,count(*) FROM policy_state_visits v JOIN states s ON s.id=v.state_id
            JOIN experiment_tasks t ON t.id=s.task_id WHERE v.run_id=? GROUP BY t.dataset
        """, (run_id,))))
        sampled = 0
        newly_added: Counter[str] = Counter()
        sources = {tid: key.partition("/")[0] for tid, key, _ in available} if per_source else None
        for sequence, tid, source in _assign_policies(candidates, sources):
            if states >= target_states or sampled == task_limit:
                break
            if tid in processed:
                continue
            task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (tid,)).fetchone()
            dataset_name = task["dataset"]
            if (source_targets is not None
                    and by_source[dataset_name] >= source_targets[dataset_name]):
                continue
            budget = budgets.get((dataset_name, task["native_group"]), revision["primary_budget"])
            steps = dataset.config["states"]["control_steps"]
            session, _ = start_cold(dataset, db, task, budget)
            session.shared_preflight = {}
            if not session.take(next(a for a in session.menu(steps) if a.kind == "SEARCH")):
                raise ValueError("Cannot collect a policy state after failed SEARCH")
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
                    feasible = fresh.feasible_menu(raw)
                    fresh.observe_numeric(feasible)
                    effective = [asdict(a) for a in feasible]
                    if event["before"] != fresh.state.project() or event["actions"] != effective:
                        raise ValueError(
                            "Policy collection replay changed its actual decision input"
                        )
                    duplicate = db.execute(
                        """
                        SELECT 1 FROM states s JOIN state_variants v ON v.state_id=s.id
                        WHERE s.task_id=? AND v.material_budget=? AND s.control_steps=?
                          AND s.prefix=? AND s.candidates=? AND (? OR v.observation_protocol=?)
                    """,
                        (
                            tid,
                            budget,
                            steps,
                            packed(fresh.prefix),
                            packed(fresh.focus),
                            v12,
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
                        by_source[dataset_name] += 1
                        states += 1
                    selected = next(a for a in raw if a.id == event["selected"])
                    if (selected.kind == "HANDOFF" or states >= target_states
                            or (source_targets is not None
                                and by_source[dataset_name] >= source_targets[dataset_name])):
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
        source_budgets = [
            dict(row) for row in db.execute("""
                SELECT t.dataset,x.material_budget,count(*) AS states
                FROM policy_state_visits v JOIN states s ON s.id=v.state_id
                JOIN state_variants x ON x.state_id=s.id
                JOIN experiment_tasks t ON t.id=s.task_id WHERE v.run_id=?
                GROUP BY t.dataset,x.material_budget ORDER BY t.dataset,x.material_budget
            """, (run_id,))
        ]
    receipt = {
        "run_id": run_id,
        "status": "COMPLETE" if states == target_states else "PARTIAL",
        "distinct_states": states,
        "target_states": target_states,
        "new_states": dict(newly_added),
        "new_episodes": sampled,
        "cumulative_states_by_source_policy": by_source_policy,
        "cumulative_episode_attempts_by_policy": attempted,
        "cumulative_states_by_source_budget": source_budgets,
        **({"actual_states_by_source": dict(by_source)} if v12 else {}),
        "reader_requests": 0,
        "optimizer_updates": 0,
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "configuration": declaration,
    }
    write_json(output, receipt)
    return receipt
