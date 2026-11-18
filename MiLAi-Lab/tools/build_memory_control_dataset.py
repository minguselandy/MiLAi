"""Rebuild, validate and consume the pinned MiLAi memory-control V1 dataset."""

from __future__ import annotations

import argparse
import fcntl
import os
import shlex
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_acquire import acquire
from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER, normalize
from milai_lab.datasets.memory_control_report import read_json, report, write_json
from milai_lab.datasets.memory_control_revision import derive, supervision_audit
from milai_lab.datasets.memory_control_store import DB_NAME, connect, get_meta, set_meta, unpack
from milai_lab.datasets.memory_control_views import build_views, resolve_tokenizers
from milai_lab.methods.dataset_control_states import build_states
from milai_lab.methods.dataset_revision_states import build_observations
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_dataset_rollout import prepare_branches
from milai_lab.runners.memory_control_dataset_validation import (
    Audit,
    audit_musique,
    audit_persona,
    audit_qasper,
    audit_views_states,
    sampled_projection,
)

LAB = Path(__file__).resolve().parents[1]
DEFAULT = LAB / "configs/datasets/memory_control_v1.json"


def source_audit(db: sqlite3.Connection, root: Path, config: dict[str, Any], audit: Audit) -> None:
    acquisition = read_json(root / "manifests/acquisition.json", {})
    for item in acquisition.get("files", []):
        path = root / "raw" / item["source"] / item["path"]
        audit.check(
            item["parsed"] and path.is_file() and path.stat().st_size == item.get("bytes"),
            "raw_file_receipt",
            item["path"],
        )
        if item["parsed"]:
            audit.tally("source_files_parsed")
        else:
            audit.tally("source_files_failed")
        if "declared_bytes" in item and item["parsed"]:
            audit.check(
                item["bytes"] == item["declared_bytes"],
                "official_archive_bytes_differ",
                item["path"],
            )
    for key, handler in (
        (MUSIQUE, audit_musique),
        (QASPER, audit_qasper),
        (PERSONA, audit_persona),
    ):
        handler(db, root / "raw" / key, config["sources"][key], audit)
        for split, stats in get_meta(db, "raw_counts")[key].items():
            n = audit.measured[f"{key}/{split}/raw"]
            audit.check(
                n == stats["normalized"] == stats["raw"] and stats["source_parsed"],
                "official_task_count_or_coverage",
                (key, split, n),
            )
    audit.check(
        audit.measured["persona_unique_histories"]
        == acquisition.get("distinct_history_references"),
        "persona_reference_count_disagrees",
        acquisition.get("distinct_history_references"),
    )


def sample_cases(
    db: sqlite3.Connection, dataset: MemoryControlDataset, audit: Audit
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for source, specs in {
        MUSIQUE: ("unanswerable", "answerable"),
        QASPER: ("multiple_annotations", "figure_only", "paged_paper"),
        PERSONA: ("updated", "others", "unknown_snippet"),
    }.items():
        found = set()
        seen = set()
        for row in db.execute(
            """
            SELECT t.*,a.data, (SELECT max(s.id) FROM states s WHERE s.task_id=t.id) as state_id
            FROM task_index t JOIN annotations a ON a.task_id=t.id
            WHERE t.dataset=? AND t.clean_role<>'excluded' ORDER BY t.id
        """,
            (source,),
        ):
            if row["native_group"] in seen or row["state_id"] is None:
                continue
            data = unpack(row["data"])
            possible = set()
            if source == MUSIQUE:
                possible.add("answerable" if data["answerable"] else "unanswerable")
            elif source == PERSONA:
                if data["updated"] and data["prev_pref"]:
                    possible.add("updated")
                if data["who"] == "others":
                    possible.add("others")
                if not data["snippet_fully_visible"]:
                    possible.add("unknown_snippet")
            else:
                ans = data["answer_annotations"]
                kinds = {
                    m["evidence_kind"]
                    for a in ans
                    if not a["answer"]["unanswerable"]
                    for m in a["evidence_alignment"]
                }
                if len(ans) > 1:
                    possible.add("multiple_annotations")
                if kinds == {"caption_only"}:
                    possible.add("figure_only")
                if (
                    "paged_paper" not in found
                    and db.execute(
                        """
                    SELECT 1 FROM views v JOIN objects o ON o.id=v.object_id
                    WHERE o.root_id=? AND v.method='literal_page' LIMIT 1
                """,
                        (row["root_id"],),
                    ).fetchone()
                ):
                    possible.add("paged_paper")
            case = next((item for item in specs if item in possible and item not in found), None)
            if case is None:
                continue
            selected.append(
                {
                    "dataset": source,
                    "case": case,
                    "state_id": row["state_id"],
                    "task_id": row["id"],
                    "split": row["split"],
                }
            )
            found.add(case)
            seen.add(row["native_group"])
            if found == set(specs):
                break
        audit.check(
            found == set(specs),
            "semantic_sample_category_missing",
            [source, sorted(set(specs) - found)],
        )
    cases = dataset.rows([item["state_id"] for item in selected])
    sampled_projection(cases, audit)
    for meta, case in zip(selected, cases, strict=True):
        meta["object_count"] = case["object_count"]
        meta["actions"] = len(case["actions"])
        meta["known_weak_actions"] = sum(case["offline_supervision"]["weak_evidence_known_mask"])
        if meta["case"] in {"figure_only", "unknown_snippet"}:
            audit.check(
                meta["known_weak_actions"] == 0,
                "incomplete_annotation_has_weak_labels",
                meta["task_id"],
            )
    return selected


def validate(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    path = root / DB_NAME
    audit = Audit()
    with closing(connect(path)) as db:
        audit.check(
            db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "sqlite_structure", str(path)
        )
        for row in db.execute("PRAGMA foreign_key_check"):
            audit.check(False, "sql_foreign_keys", list(row))
        source_audit(db, root, config, audit)
        print("Verified all official source records and history mappings", flush=True)
        clean = {}
        for source in config["sources"]:
            overlap = db.execute(
                """
                SELECT count(*) FROM (
                    SELECT native_group FROM task_index WHERE dataset=? AND clean_role='train'
                    INTERSECT
                    SELECT native_group FROM task_index
                    WHERE dataset=? AND clean_role='validation'
                )
            """,
                (source, source),
            ).fetchone()[0]
            clean[source] = overlap
            audit.check(overlap == 0, "clean_group_overlap", [source, overlap])
        summaries = audit_views_states(db, config, audit)
        print("Verified full view ranges, action bindings and weak masks", flush=True)
        samples = []
        if get_meta(db, "build_done"):
            samples = sample_cases(db, MemoryControlDataset(path), audit)
        for dataset, splits in get_meta(db, "raw_counts").items():
            for split, info in splits.items():
                n = db.execute(
                    """
                    SELECT count(DISTINCT s.task_id) FROM states s JOIN task_index t
                    ON t.id=s.task_id WHERE t.dataset=? AND t.split=?
                """,
                    (dataset, split),
                ).fetchone()[0]
                audit.check(
                    n == info["normalized"], "missing_task_state_coverage", [dataset, split, n]
                )
        executed = db.execute("SELECT count(*) FROM action_outcomes").fetchone()[0]
        samples_by_source = {}
        for arm in ("train", "validation"):
            for source, groups, random_groups in db.execute(
                """
                SELECT t.dataset,count(DISTINCT t.native_group),
                    count(DISTINCT CASE WHEN s.sampling='random_source' THEN t.native_group END)
                FROM task_index t JOIN states s ON s.task_id=t.id
                WHERE t.clean_role=? AND s.recipe='initial_candidates'
                GROUP BY t.dataset
            """,
                (arm,),
            ):
                samples_by_source[f"{source}/{arm}"] = {
                    "groups": groups,
                    "random_source_groups": random_groups,
                    "fraction": random_groups / groups,
                }
                audit.check(
                    random_groups >= groups * config["states"]["random_source_fraction"],
                    "random_source_quota",
                    [source, arm, groups, random_groups],
                )
        validation = {
            "run_id": get_meta(db, "run_id"),
            "passed": not audit.errors,
            "errors": dict(audit.errors),
            "example_errors": dict(audit.examples),
            "measurements": dict(audit.measured),
            "state_statistics": {f"{s}/{p}": dict(c) for (s, p), c in summaries.items()},
            "clean_group_overlap": clean,
            "sampled_semantic_cases": samples,
            "clean_random_source_coverage": samples_by_source,
            "executed_outcome_rows": executed,
        }
    write_json(root / "reports/validation.json", validation)
    return validation


def dry_run_arguments(encoder: dict[str, Any], architecture: str, root: Path) -> list[str]:
    args = [
        sys.executable,
        "tools/run_small_memory_policy.py",
        "train",
        "--dry-run",
        "--data",
        str(root / DB_NAME),
        "--output",
        str(root / "reports" / architecture),
        "--object-architecture",
        architecture,
        "--threads",
        "4",
    ]
    for field in (
        "family",
        "backbone",
        "chunk_tokens",
        "encode_batch_size",
        "readout",
        "projection_version",
        "maximum_memory_objects",
        "object_width",
        "object_heads",
        "object_slots",
        "object_blocks",
        "object_ffn_width",
        "object_dropout",
        "prior_policy",
        "prior_reads",
        "prior_margin",
        "object_feature_layout",
    ):
        if field in encoder:
            args.extend(("--" + field.replace("_", "-"), str(encoder[field])))
    return args


def probe(root: Path, config: dict[str, Any]) -> None:
    dataset = MemoryControlDataset(root / DB_NAME)
    _, encoder = resolve_tokenizers(config)
    for arm in ("object_mlp", "latent_pointer"):
        destination = root / "reports" / arm
        old_receipt = read_json(destination / "dataset-dry-run.json", {})
        if old_receipt.get("run_id") == dataset.run_id and old_receipt.get("status") == "PASSED":
            continue
        if destination.is_dir() and not any(destination.iterdir()):
            destination.rmdir()
        subprocess.run(dry_run_arguments(encoder, arm, root), cwd=LAB, check=True)  # noqa: S603
    probes = []
    for row in dataset.smoke_batch("train"):
        source = row["provenance"]["dataset"]
        with closing(connect(dataset.path)) as db:
            sid = db.execute(
                "SELECT min(id) FROM states WHERE task_id=?", (row["provenance"]["task_id"],)
            ).fetchone()[0]
        result = prepare_branches(dataset, sid)
        tag = f"{source}-rollout"
        path = root / "reports" / (tag + ".json")
        write_json(path, result)
        probes.append(
            {
                "source": source,
                "state_id": sid,
                "file": path.name,
                "prepared_branches": len(result["branches"]),
                "first_step_material_tokens": {
                    b["bound_action"]["id"]: b["costs"]["first_step_material_tokens"]
                    for b in result["branches"]
                },
            }
        )
    source_row = probes[0]
    search = prepare_branches(dataset, source_row["state_id"], before_search=True)
    write_json(root / "reports/before-search-rollout.json", search)
    write_json(
        root / "reports/rollout-probe.json",
        {
            "dataset_run_id": dataset.run_id,
            "sources": probes,
            "before_search_rollout": "before-search-rollout.json",
            "local_bound_branches": sum(r["prepared_branches"] for r in probes)
            + len(search["branches"]),
            "reader_calls": 0,
        },
    )


def stage(args: argparse.Namespace, root: Path, config: dict[str, Any]) -> int:
    command = args.command
    db_path = root / DB_NAME
    if command == "revise":
        derive(args.parent or Path(config["parent_root"]), root, config, args.roles)
        print(f"Roles frozen in {db_path}")
        return 0
    if command == "audit-train":
        result = supervision_audit(db_path, parent=args.parent_states)
        version = result["state_version"]
        output = root / "reports" / f"{version}-supervision.json"
        write_json(output, result)
        print(f"Supervision counts written to {output}")
        return 0
    if command == "build-observations":
        with closing(connect(db_path, writable=True)) as db:
            result = build_observations(db_path, db, workers=args.state_workers,
                                        budget_scope=args.budget_scope, task_limit=args.task_limit)
        print(result)
        return int(not result["scope_complete"] and args.task_limit is None)
    if command in {"validate", "report"} and "parent_release" in config:
        from milai_lab.runners.memory_control_revision_validation import validate_revision

        verified = validate_revision(db_path)
        write_json(root / "reports" / "revision-validation.json", verified)
        if command == "report":
            audit = supervision_audit(db_path, parent=False)
            write_json(root / "reports" / "revision-supervision.json", audit)
            with closing(connect(db_path)) as db:
                outcome_statuses = [dict(row) for row in db.execute("""
                    SELECT run_id,execution_status,count(*) AS branches,
                           count(DISTINCT state_id) AS before_states
                    FROM action_outcomes GROUP BY run_id,execution_status
                """)]
            write_json(root / "reports" / "revision-report.json", {
                **verified, "statistics": "revision-supervision.json",
                "parent_statistics": "parent-supervision.json",
                "source_roles": "../manifests/experiment-groups.json",
                "outcomes": outcome_statuses,
            })
        print(verified["status"])
        return 0
    if command in {"prepare-outcomes", "execute-outcomes", "score-outcomes"}:
        from milai_lab.runners.memory_control_outcome_run import (
            execute_outcomes,
            prepare_outcomes,
            score_outcomes,
        )

        if not args.run_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Run ID must use letters, digits, hyphens or underscores")
        dataset = MemoryControlDataset(db_path, require_complete=False)
        if command == "prepare-outcomes":
            from milai_lab.methods.control_observation import control_input
            from milai_lab.methods.memory_control import FixedContextMemoryPolicy
            from milai_lab.methods.small_control_model import SmallControlModel

            if (len(args.checkpoint) > 2 or (args.action and not args.state_id)
                    or (args.policy_pool and args.state_id)):
                raise ValueError("Use at most two checkpoints or explicit diagnostic actions")
            suggestions = [("fixed_context4", FixedContextMemoryPolicy().choose)]
            for path in args.checkpoint:
                model = SmallControlModel.load(path, device=args.device)

                def recommend(state: Any, actions: Any, policy: Any = model) -> str:
                    scored = policy.score(control_input(state, actions))
                    return max(zip(scored.scores, scored.action_ids, strict=True))[1]

                suggestions.append((str(path.resolve()), recommend))
            result = prepare_outcomes(dataset, args.run_id, limit=args.state_limit,
                                      state_ids=args.state_id, explicit_actions=args.action,
                                      seed=args.seed, suggestions=suggestions,
                                      policy_pool=args.policy_pool, dev_plan=args.dev_plan)
        elif command == "execute-outcomes":
            result = execute_outcomes(dataset, args.run_id, limit=args.limit)
        else:
            result = score_outcomes(dataset, args.run_id, seal=args.seal)
        output = root / "reports" / "outcomes" / args.run_id / (
            f"{command}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        )
        write_json(output, result)
        print(f"{command} receipt at {output}")
        return 0
    if command in {"acquire", "all"}:
        result = acquire(root / "raw", config["sources"], workers=args.download_workers)
        write_json(root / "manifests/acquisition.json", result)
        if command == "acquire":
            print(
                f"Acquisition attempted {len(result['files'])} files, "
                f"with {len(result['errors'])} errors"
            )
            return int(bool(result["errors"]))
    if command in {"normalize", "all"}:
        normalize(db_path, root / "raw", config)
    if command in {"normalize", "build", "all"}:
        with closing(connect(db_path, writable=True)) as db:
            if get_meta(db, "configuration") != config:
                raise ValueError("Configuration differs from the normalized release")
            if get_meta(db, "run_id") is None:
                rid = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
                set_meta(db, "run_id", rid)
                base = subprocess.check_output(  # noqa: S603
                    ["/usr/bin/git", "-C", str(LAB), "rev-parse", "HEAD"], text=True
                ).strip()
                set_meta(db, "code_base", base)
                db.commit()
            if command in {"build", "all"}:
                if not get_meta(db, "tokenizers"):
                    build_views(db, config)
                if not get_meta(db, "build_done"):
                    build_states(db, config, workers=args.state_workers)
    if command in {"validate", "all"}:
        checked = validate(root, config)
        if command == "validate":
            print(f"Validation {'passed' if checked['passed'] else 'failed'}")
            return int(not checked["passed"])
    if command == "probe" or (command == "all" and checked["passed"]):
        probe(root, config)
    if command in {"report", "all"}:
        prefix = (
            "PYTHONPATH=src RAYON_NUM_THREADS=6 "
            + shlex.quote(sys.executable)
            + " tools/build_memory_control_dataset.py --root "
            + shlex.quote(str(root))
        )
        with closing(connect(db_path)) as db:
            result = report(
                db,
                root,
                config,
                commands=[
                    f"{prefix} {name}"
                    for name in (
                        "all",
                        "acquire",
                        "normalize",
                        "build",
                        "validate",
                        "probe",
                        "report",
                    )
                ],
            )
        print(f"{result['status']}  {root / 'reports/BUILD_REPORT.md'}")
        return int(result["status"] != "DATA_PREP_COMPLETE")
    if command == "collect-outcomes":
        result = prepare_branches(
            MemoryControlDataset(db_path),
            args.state_id,
            args.action,
            before_search=args.before_search,
        )
        write_json(args.output, result)
        print(f"Prepared {len(result['branches'])} local branches in {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--root", type=Path, help="Persistent output directory")
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--state-workers", type=int, default=6)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("all", "acquire", "normalize", "build", "validate", "probe", "report"):
        sub.add_parser(name)
    revise = sub.add_parser("revise", help="Derive V1.1 and freeze native group roles")
    revise.add_argument("--parent", type=Path, help="Existing V1 dataset directory")
    revise.add_argument("--roles", type=Path, required=True, help="Historical group declarations")
    audit_train = sub.add_parser("audit-train", help="Measure role and weak-supervision coverage")
    audit_train.add_argument("--parent-states", action="store_true")
    observations = sub.add_parser("build-observations", help="Regenerate V1.1 states and labels")
    observations.add_argument("--budget-scope", default="all",
                              choices=["all", "primary", "train_variants", "dev_diagnostics"])
    observations.add_argument("--task-limit", type=int, help="Explicit incremental build size")
    prepare_outcome = sub.add_parser("prepare-outcomes", help="Prepare durable actual branches")
    prepare_outcome.add_argument("--run-id", required=True)
    prepare_outcome.add_argument("--state-limit", type=int, default=3000)
    prepare_outcome.add_argument("--state-id", type=int, action="append", default=[])
    prepare_outcome.add_argument("--action", action="append", default=[])
    prepare_outcome.add_argument("--checkpoint", type=Path, action="append", default=[])
    prepare_outcome.add_argument("--policy-pool")
    prepare_outcome.add_argument("--dev-plan", type=Path,
                                 help="Use the registered DEV cohort for held branch evaluation")
    prepare_outcome.add_argument("--device", default="cpu")
    prepare_outcome.add_argument("--seed", type=int, default=20261118)
    execute_outcome = sub.add_parser("execute-outcomes", help="Use the original Reader ledger")
    execute_outcome.add_argument("--run-id", required=True)
    execute_outcome.add_argument("--limit", type=int, required=True)
    score_outcome = sub.add_parser("score-outcomes", help="Score and ingest completed Reader calls")
    score_outcome.add_argument("--run-id", required=True)
    score_outcome.add_argument("--seal", action="store_true")
    collect = sub.add_parser(
        "collect-outcomes", help="Prepare matched local branches and Host wires"
    )
    collect.add_argument("--state-id", type=int, required=True)
    collect.add_argument("--action", action="append", help="An offered action ID, repeatable")
    collect.add_argument("--before-search", action="store_true")
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = read_json(args.config)
    root = (args.root or Path(config["data_root"])).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    name = ".outcomes.lock" if args.command in {
        "prepare-outcomes", "execute-outcomes", "score-outcomes",
    } else ".build.lock"
    with (root / name).open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        return stage(args, root, config)


if __name__ == "__main__":
    raise SystemExit(main())
