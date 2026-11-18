"""Derive a versioned dataset while preserving V1 source identities and roles."""

from __future__ import annotations

import os
import random
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import DB_NAME, connect, get_meta, set_meta, unpack

REVISION_SCHEMA = """
CREATE TABLE experiment_groups (
    dataset TEXT NOT NULL, native_group TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('train','dev','confirm')),
    origin TEXT NOT NULL, eligible_fresh_confirmation INTEGER NOT NULL,
    PRIMARY KEY(dataset, native_group)
);
CREATE VIEW experiment_tasks AS
    SELECT t.*, CASE WHEN t.clean_role='excluded' THEN 'excluded' ELSE g.role END AS experiment_role
    FROM task_index t LEFT JOIN experiment_groups g USING(dataset, native_group);
CREATE TABLE state_variants (
    state_id INTEGER PRIMARY KEY REFERENCES states(id),
    dataset_release TEXT NOT NULL,
    parent_state_id INTEGER REFERENCES states(id),
    material_budget INTEGER NOT NULL,
    observation_protocol TEXT NOT NULL,
    action_feasibility BLOB NOT NULL,
    diagnostics BLOB NOT NULL
);
CREATE TABLE revision_task_builds (
    task_id INTEGER NOT NULL REFERENCES tasks(id), material_budget INTEGER NOT NULL,
    PRIMARY KEY(task_id, material_budget)
);
CREATE INDEX state_variants_parent ON state_variants(parent_state_id);
CREATE TABLE outcome_runs (
    run_id TEXT PRIMARY KEY, config TEXT NOT NULL
);
ALTER TABLE action_outcomes RENAME TO action_outcomes_legacy;
CREATE TABLE action_outcomes (
    state_id INTEGER NOT NULL REFERENCES states(id), action_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES outcome_runs(run_id), repeat_index INTEGER NOT NULL DEFAULT 0,
    bound_action BLOB, sampling_origin TEXT, branch_seed INTEGER,
    reader_protocol TEXT NOT NULL, execution_status TEXT NOT NULL,
    action_status TEXT, reader_status TEXT, scoring_status TEXT,
    next_state BLOB, terminal_state BLOB, first_step_material BLOB, delivered_material BLOB,
    task_result BLOB, costs BLOB, native_metrics BLOB,
    training_quality REAL CHECK (training_quality BETWEEN 0 AND 1),
    success_witness INTEGER,
    PRIMARY KEY (state_id, action_id, run_id, repeat_index)
);
INSERT INTO outcome_runs
    SELECT DISTINCT run_id, '{"protocol":"legacy_v1"}' FROM action_outcomes_legacy;
INSERT INTO action_outcomes
    (state_id, action_id, run_id, repeat_index, reader_protocol, execution_status,
     next_state, delivered_material, task_result, costs)
    SELECT state_id, action_id, run_id, 0, reader_protocol, execution_status,
           next_state, delivered_material, task_result, costs FROM action_outcomes_legacy;
DROP TABLE action_outcomes_legacy;
"""


def assignments(
    db: sqlite3.Connection,
    history: list[dict[str, str]],
    *,
    seed: int,
    confirm_fraction: float,
) -> list[tuple[str, str, str, str, bool]]:
    if not 0 <= confirm_fraction < 1:
        raise ValueError("Confirmation fraction must be in [0, 1)")
    groups = {
        (row["dataset"], row["native_group"]): row["clean_role"]
        for row in db.execute(
            "SELECT DISTINCT dataset,native_group,clean_role FROM task_index "
            "WHERE clean_role<>'excluded'"
        )
    }
    if db.execute("""
        SELECT 1 FROM task_index WHERE clean_role<>'excluded'
        GROUP BY dataset,native_group HAVING count(DISTINCT clean_role)>1
    """).fetchone():
        raise ValueError("Parent has crossing clean group roles")
    historical: dict[tuple[str, str], tuple[str, str]] = {}
    for row in history:
        key = (row["dataset"], row["native_group"])
        role, origin = row["role"], row["origin"]
        if key not in groups or role not in {"train", "dev", "confirm"} or not origin:
            raise ValueError(f"Invalid native group assignment {key}: {role}")
        if role == "train" and groups[key] != "train":
            raise ValueError("A historical declaration cannot admit validation to training")
        existing = historical.get(key)
        if existing and existing[0] != role:
            raise ValueError(f"Conflicting historical roles for {key}")
        historical[key] = (role, origin)

    candidates = defaultdict(list)
    for (source, group), parent in sorted(groups.items()):
        if parent == "validation" and (source, group) not in historical:
            candidates[source].append(group)
    rng = random.Random(seed)  # noqa: S311 -- reproducible allocation of native groups
    fresh: set[tuple[str, str]] = set()
    for source, population in candidates.items():
        rng.shuffle(population)
        fresh.update(
            (source, group) for group in population[: round(len(population) * confirm_fraction)]
        )

    result = []
    for (source, group), parent in sorted(groups.items()):
        key = (source, group)
        role, origin = historical.get(
            key,
            (
                "train" if parent == "train" else "confirm" if key in fresh else "dev",
                "parent_clean_train" if parent == "train" else "unassigned_validation_seeded",
            ),
        )
        result.append((source, group, role, origin, key in fresh))
    return result


def derive(parent: Path, root: Path, revision: dict[str, Any], role_file: Path) -> Path:
    output = root / DB_NAME
    source_path = parent / DB_NAME
    if source_path.resolve() == output.resolve():
        raise ValueError("Revision needs a separate database")
    declared = read_json(role_file)
    config = {
        "revision": revision,
        "parent_path": str(source_path.resolve()),
        "role_manifest": str(role_file.resolve()),
    }
    if output.exists():
        with closing(connect(output)) as db:
            if get_meta(db, "derivation") != config:
                raise ValueError("Existing revision has different roles, source or configuration")
            stored = [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM experiment_groups ORDER BY dataset,native_group"
                )
            ]
        with closing(connect(source_path)) as source:
            expected = assignments(
                source,
                declared,
                seed=revision["seed"],
                confirm_fraction=revision["confirmation_fraction"],
            )
        if stored != expected:
            raise ValueError("Native group role manifest changed")
        return output

    temporary = root / f".{DB_NAME}.{os.getpid()}.partial"
    with closing(connect(source_path)) as source:
        parent_config = get_meta(source, "configuration")
        if parent_config["dataset_release"] != revision["parent_release"]:
            raise ValueError("Parent release differs from configuration")
        groups = assignments(
            source,
            declared,
            seed=revision["seed"],
            confirm_fraction=revision["confirmation_fraction"],
        )
        with closing(connect(temporary, writable=True)) as db:
            source.backup(db)
            db.executescript(REVISION_SCHEMA)
            db.executemany("INSERT INTO experiment_groups VALUES (?,?,?,?,?)", groups)
            set_meta(db, "derivation", config)
            set_meta(db, "parent_run_id", get_meta(source, "run_id"))
            set_meta(db, "run_id", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}")
            set_meta(
                db,
                "configuration",
                {
                    **parent_config,
                    "data_root": str(root),
                    "dataset_release": revision["dataset_release"],
                    "processing_version": revision["processing_version"],
                },
            )
            set_meta(db, "parent_state_max", db.execute("SELECT max(id) FROM states").fetchone()[0])
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Revision contains unresolved database references")
            db.commit()
    temporary.replace(output)
    (root / "manifests").mkdir(exist_ok=True)
    write_json(
        root / "manifests/experiment-groups.json",
        [
            dict(
                zip(
                    ("dataset", "native_group", "role", "origin", "eligible_fresh_confirmation"),
                    group,
                    strict=True,
                )
            )
            for group in groups
        ],
    )
    write_json(
        root / "manifests/derivation.json",
        {
            **config,
            "dataset_root": str(root.resolve()),
            "parent_raw": str(parent.resolve() / "raw"),
            "parent_source_manifest": str(parent.resolve() / "manifests/sources.json"),
            "content_verification": "disabled",
            "native_groups": len(groups),
        },
    )
    return output


def supervision_audit(path: Path, *, parent: bool) -> dict[str, Any]:
    """Audit weak labels, exact feasibility and admitted group-level annotation fields."""
    strata: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    budgets: dict[tuple[str, ...], set[int]] = defaultdict(set)
    groups: dict[tuple[str, ...], set[str]] = defaultdict(set)
    persona_states: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    with closing(connect(path)) as db:
        parent_max = get_meta(db, "parent_state_max")
        revised = parent_max is not None
        role_column = "experiment_role" if revised else "clean_role"
        relation = "experiment_tasks" if revised else "task_index"
        counts = [
            dict(row)
            for row in db.execute(f"""
            SELECT dataset,{role_column} AS role,count(*) AS tasks,
                   count(DISTINCT native_group) AS groups,count(DISTINCT root_id) AS roots
            FROM {relation} GROUP BY dataset,{role_column}
        """)  # noqa: S608
        ]
        variant_join = "LEFT JOIN state_variants v ON v.state_id=s.id" if revised else ""
        variants = (
            "v.material_budget,v.action_feasibility,v.diagnostics"
            if revised and not parent
            else ("NULL AS material_budget,NULL AS action_feasibility,NULL AS diagnostics")
        )
        scope = (
            "WHERE s.id<=?"
            if revised and parent
            else "WHERE v.state_id IS NOT NULL"
            if revised
            else ""
        )
        default_budget = get_meta(db, "configuration")["views"]["reader_material_tokens"]
        query = f"""
            SELECT t.dataset,t.{role_column} AS role,t.native_group,s.task_id,s.recipe,s.sampling,
                w.evidence,w.corpus_coverage,s.material_tokens,{variants}
            FROM states s JOIN {relation} t ON t.id=s.task_id
            JOIN weak_labels w ON s.id=w.state_id {variant_join} {scope}
        """  # noqa: S608
        for row in db.execute(query, (parent_max,) if revised and parent else ()):
            key = (
                row["dataset"],
                row["role"],
                row["recipe"],
                str(row["material_budget"] or default_budget),
            )
            c = strata[key]
            c["states"] += 1
            budgets[key].add(row["task_id"])
            groups[key].add(row["native_group"])
            labels = unpack(row["evidence"])
            n_pos, n_neg, n_unknown = (labels.count(v) for v in (True, False, None))
            c["positive_actions"] += n_pos
            c["known_actions"] += n_pos + n_neg
            c["unknown_actions"] += n_unknown
            c["positive_states"] += bool(n_pos)
            c["mixed_states"] += bool(n_pos and n_neg)
            c["known_negative_only_states"] += bool(n_neg and not n_pos)
            c["unknown_states"] += not (n_pos or n_neg)
            c["material_tokens"] += row["material_tokens"]
            c[f"coverage/{row['corpus_coverage']}"] += 1
            c[f"sampling/{row['sampling']}"] += 1
            persona = None
            if row["dataset"] == "personamem_v2":
                persona = persona_states[row["role"], row["native_group"]]
                persona["states"] += 1
                persona["positive_states"] += bool(n_pos)
            if row["action_feasibility"] is not None:
                fits = [feasible for feasible, _ in unpack(row["action_feasibility"])]
                feasible_positive = sum(
                    y is True and f is True for y, f in zip(labels, fits, strict=True)
                )
                c["feasible_positive_states"] += feasible_positive > 0
                if persona is not None:
                    persona["feasible_positive_states"] += feasible_positive > 0
                c["positive_but_no_feasible_states"] += n_pos > 0 and not feasible_positive
                c["infeasible_positive_reads"] += sum(
                    y is True and f is False for y, f in zip(labels, fits, strict=True)
                )
                c["feasible_known_states"] += any(
                    y is not None and f is True for y, f in zip(labels, fits, strict=True)
                )
                for name, value in unpack(row["diagnostics"]).items():
                    if value is not None:
                        c[name] += value
        persona_strata: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        if revised and not parent:
            for row in db.execute("""
                SELECT t.experiment_role,t.native_group,a.data
                FROM experiment_tasks t JOIN annotations a ON a.task_id=t.id
                WHERE t.dataset='personamem_v2' AND t.experiment_role IN ('train','dev')
            """):
                annotations = unpack(row["data"])
                aligned = bool(annotations["snippet_fully_visible"])
                persona = persona_states[row["experiment_role"], row["native_group"]]
                persona["native_tasks"] += 1
                persona["aligned_native_tasks"] += aligned
                for field in ("who", "updated", "sensitive_info", "pref_type"):
                    key = (row["experiment_role"], field, str(annotations.get(field)))
                    persona_strata[key]["tasks"] += 1
                    persona_strata[key]["aligned_evidence_tasks"] += aligned
            for role, group, status, n in db.execute("""
                SELECT t.experiment_role,t.native_group,o.execution_status,count(*)
                FROM action_outcomes o JOIN states s ON s.id=o.state_id
                JOIN experiment_tasks t ON t.id=s.task_id
                WHERE t.dataset='personamem_v2' GROUP BY 1,2,3
            """):
                persona_states[role, group][f"outcome/{status}"] += n
        return {
            "database": str(path),
            "dataset_run_id": get_meta(db, "run_id"),
            "state_version": "parent" if parent or not revised else "revision",
            "tasks_groups_and_roots": counts,
            "parent_clean_roles": [
                dict(row)
                for row in db.execute("""
                SELECT dataset,clean_role,count(*) AS tasks,
                count(DISTINCT native_group) AS groups,count(DISTINCT root_id) AS roots
                FROM task_index GROUP BY dataset,clean_role
            """)
            ],
            "state_supervision": [
                dict(
                    zip(("dataset", "role", "recipe", "budget"), key, strict=True),
                    tasks=len(budgets[key]),
                    groups=len(groups[key]),
                    **c,
                )
                for key, c in sorted(strata.items())
            ],
            "persona_groups": [
                {"role": role, "persona": group, **c}
                for (role, group), c in sorted(persona_states.items())
            ],
            "persona_strata": [
                {"role": role, "attribute": field, "category": category, **c}
                for (role, field, category), c in sorted(persona_strata.items())
            ],
            "outcomes": dict(
                db.execute(
                    "SELECT execution_status,count(*) FROM action_outcomes "
                    "GROUP BY execution_status"
                )
            ),
            "reader_calls_in_audit": 0,
            "optimizer_updates_in_audit": 0,
            "revised_feasibility_measured": revised and not parent,
        }
