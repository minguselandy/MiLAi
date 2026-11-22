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
from milai_lab.datasets.memory_control_revision import (
    derive,
    derive_control_snapshot,
    supervision_audit,
)
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
    for meta, sampled in zip(selected, cases, strict=True):
        meta["object_count"] = sampled["object_count"]
        meta["actions"] = len(sampled["actions"])
        meta["known_weak_actions"] = sum(sampled["offline_supervision"]["weak_evidence_known_mask"])
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
    if command == "derive-control-snapshot":
        parent = args.parent or Path(config["parent_root"])
        print(derive_control_snapshot(parent, root, config, args.parent_revision))
        return 0
    if command == "rebind-parent-outcomes":
        from milai_lab.runners.memory_control_outcome_reuse import rebind_parent_outcomes

        dataset = MemoryControlDataset(db_path, observation_protocol=args.observation_protocol)
        result = rebind_parent_outcomes(
            dataset, args.parent_run_id, args.run_id,
            limit_states=args.limit_states, workers=args.workers,
        )
        output = root / "reports" / "outcomes" / args.run_id / "reuse-report.json"
        write_json(output, result)
        print(f"Reuse receipt at {output}")
        return 0
    if command == "lock-branch-plan":
        from milai_lab.runners.memory_control_delta_sampling import (
            DELTA_QUOTAS,
            register_branch_plan,
            register_ranked_delta,
        )

        if args.output.exists():
            raise ValueError("Choose a new output for the frozen TRAIN branch roster")
        quotas = (read_json(args.quotas) if args.quotas else DELTA_QUOTAS
                  if args.kind == "incremental_pair" else dict.fromkeys(DELTA_QUOTAS, 1000))
        dataset = MemoryControlDataset(db_path, observation_protocol=args.observation_protocol)
        if args.ranked_proposals:
            if args.kind != "incremental_pair" or args.online_proposals is None:
                raise ValueError("Ranked proposals require the incremental TRAIN plan and input")
            result = register_ranked_delta(
                dataset, args.core_run, args.online_proposals, seed=args.seed, quotas=quotas,
            )
        else:
            result = register_branch_plan(
                dataset, args.core_run, seed=args.seed, kind=args.kind, quotas=quotas,
                online_proposals=args.online_proposals,
            )
        write_json(args.output, result)
        return 0
    if command == "propose-train-actions":
        from milai_lab.runners.memory_control_delta_sampling import (
            online_train_proposals,
            ranked_train_proposals,
        )

        if args.output.exists():
            raise ValueError("Choose a new proposal output")
        dataset = MemoryControlDataset(db_path, observation_protocol=args.observation_protocol)
        if args.ranked_source_targets:
            def progress(row: dict[str, Any]) -> None:
                if args.progress_output:
                    write_json(args.progress_output, {
                        **row, "observed_at": datetime.now(UTC).isoformat(), "pid": os.getpid(),
                    })

            if args.states_per_source is not None:
                raise ValueError("Choose ranked source targets or the historical per-source limit")
            result = ranked_train_proposals(
                dataset, args.core_run, args.checkpoint, seed=args.seed, device=args.device,
                targets=read_json(args.ranked_source_targets), prior_path=args.prior_proposals,
                feature_store=args.feature_store, raw_store=args.raw_feature_store,
                progress=progress,
            )
        else:
            if args.states_per_source is None or any((args.prior_proposals, args.feature_store,
                                                     args.raw_feature_store, args.progress_output)):
                raise ValueError("Historical proposal acquisition requires its per-source limit")
            result = online_train_proposals(
                dataset, args.core_run, args.checkpoint, seed=args.seed, device=args.device,
                states_per_source=args.states_per_source,
                share_checkpoint_encoder=args.share_checkpoint_encoder,
            )
        write_json(args.output, result)
        return 0
    if command == "report-pairs":
        from milai_lab.runners.memory_control_pair_report import pair_information_report

        dataset = MemoryControlDataset(db_path, observation_protocol=args.observation_protocol)
        write_json(args.output, pair_information_report(dataset, args.run_id, args.peer_run))
        return 0
    if command == "report-pair-coverage":
        from milai_lab.runners.memory_control_pair_report import registered_pair_coverage

        dataset = MemoryControlDataset(db_path, observation_protocol=args.observation_protocol)
        coverage = registered_pair_coverage(dataset, args.run_id, tuple(args.share_reader_run))
        write_json(args.output, coverage)
        return 0
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
            Chooser,
            JointChooser,
            execute_outcomes,
            prepare_outcomes,
            score_outcomes,
        )

        if not args.run_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Run ID must use letters, digits, hyphens or underscores")
        dataset = MemoryControlDataset(
            db_path, require_complete=False, observation_protocol=args.observation_protocol,
        )
        if command == "prepare-outcomes":
            from milai_lab.methods.control_observation import control_input
            from milai_lab.methods.memory_control import (
                FixedContextMemoryPolicy,
                MemoryAction,
                MemoryControlState,
            )
            from milai_lab.methods.small_control_model import SmallControlModel
            from milai_lab.methods.small_memory_policy import SmallMemoryPolicy, best_scored_action
            from milai_lab.runners.memory_control_checkpoint_selection import selected_candidate
            from milai_lab.runners.memory_control_episode import checkpoint_contract
            from milai_lab.runners.memory_control_outcome_run import REFERENCE_SHORT

            if (len(args.checkpoint) > 2 or (args.action and not args.state_id)
                    or (args.policy_pool and args.state_id)):
                raise ValueError("Use at most two checkpoints or explicit diagnostic actions")
            selections = args.recommendation_selection
            if selections and (args.checkpoint or not args.policy_pool or len(selections) != 2):
                raise ValueError("Policy-pool recommendations require two matching selections")
            chosen = [selected_candidate(path) for path in selections]
            paths = [Path(row["checkpoint"]) for row in chosen] if chosen else args.checkpoint
            if args.share_checkpoint_encoder and len(paths) != 2:
                raise ValueError("Provide two checkpoints for shared recommendation encoding")
            fixed = FixedContextMemoryPolicy()
            suggestions: list[tuple[str, Chooser]] = [] if chosen else [
                ("fixed_context4", fixed.choose),
            ]
            models: list[SmallControlModel] = []
            for i, path in enumerate(paths):
                model = SmallControlModel.load(path, device=args.device)
                name = str(path.resolve())
                if chosen:
                    item = chosen[i]
                    contract = checkpoint_contract(path)
                    if (contract["dataset_run_id"] != dataset.run_id
                            or contract["observation_protocol"] != dataset.observation_protocol
                            or contract["supervision_mode"] != "outcome"
                            or item["utility_lambda"] != chosen[0]["utility_lambda"]
                            or item["stop"] != "learned" or item["precision"] != "learned"):
                        raise ValueError("Recommendation checkpoints differ from the policy recipe")
                    value = item["utility_lambda"]
                    model.set_utility_lambda(value)
                    name += f"@epoch={item['epoch']},lambda={value}"
                models.append(model)

                def recommend(
                    state: MemoryControlState, actions: list[MemoryAction],
                    policy: SmallControlModel = model,
                ) -> str:
                    scored = policy.score(control_input(state, actions))
                    if chosen:
                        return best_scored_action(scored, actions)
                    return max(zip(scored.scores, scored.action_ids, strict=True))[1]

                suggestions.append((name, recommend))
            joint: JointChooser | None = None
            if args.share_checkpoint_encoder:
                first, second = models
                shared_scores = first.bind_shared_object_scorer(second)

                def recommend_together(
                    state: MemoryControlState, actions: list[MemoryAction],
                ) -> list[str]:
                    scored = shared_scores(control_input(state, actions))
                    if chosen:
                        return [best_scored_action(item, actions) for item in scored]
                    return [
                        fixed.choose(state, actions),
                        *(max(zip(item.scores, item.action_ids, strict=True))[1]
                          for item in scored),
                    ]

                joint = recommend_together
            continuation = continuation_policy = None
            continuation_path = args.continuation_checkpoint
            continuation_epoch = args.continuation_epoch
            utility_lambda = None
            if args.continuation_selection:
                if continuation_path or continuation_epoch is not None:
                    raise ValueError("Choose one registered continuation checkpoint selection")
                selected = selected_candidate(args.continuation_selection)
                continuation_path = Path(selected["checkpoint"])
                continuation_epoch = selected["epoch"]
                utility_lambda = selected["utility_lambda"]
            if continuation_path:
                if args.branch_plan and not args.continuation_selection:
                    raise ValueError("Continuation audits require the selected O checkpoint")
                if continuation_epoch is None or continuation_epoch < 1:
                    raise ValueError("Register the selected continuation checkpoint epoch")
                path = continuation_path.resolve()
                contract = checkpoint_contract(path)
                if (contract["observation_protocol"] != dataset.observation_protocol
                        or contract.get("supervision_mode") != "outcome"
                        or contract.get("dataset_run_id") != dataset.run_id):
                    raise ValueError("Continuation needs a matched outcome checkpoint")
                frozen = SmallControlModel.load(path, device=args.device)
                if utility_lambda is not None:
                    frozen.set_utility_lambda(utility_lambda)
                continuation_policy = SmallMemoryPolicy(frozen)
                continuation = {
                    **REFERENCE_SHORT, "kind": "frozen-policy-short", "policy": "SmallMemoryPolicy",
                    "read_limit": None, "checkpoint": str(path),
                    "checkpoint_seed": contract["seed"], "checkpoint_model": contract["config"],
                    "checkpoint_supervision": contract["supervision_mode"],
                    "epoch": continuation_epoch, "stop_rule": "learned",
                    **({"utility_lambda": frozen.utility_lambda}
                       if frozen.config.quality_cost else {}),
                }
            elif args.continuation_epoch is not None:
                raise ValueError("A frozen continuation epoch needs its checkpoint")
            result = prepare_outcomes(
                dataset, args.run_id, limit=args.state_limit, state_ids=args.state_id,
                explicit_actions=args.action, seed=args.seed, suggestions=suggestions,
                policy_pool=args.policy_pool, dev_plan=args.dev_plan,
                branch_workers=args.branch_workers, joint_suggestions=joint,
                continuation=continuation, continuation_policy=continuation_policy,
                branch_plan=args.branch_plan,
            )
            result["recommendation_encoder_forwards"] = [
                model.counters["forwards"] for model in models
            ]
        elif command == "execute-outcomes":
            result = execute_outcomes(
                dataset, args.run_id, limit=args.limit,
                share_reader_runs=tuple(args.share_reader_run),
            )
        else:
            result = score_outcomes(dataset, args.run_id, seal=args.seal, limit=args.limit)
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
    snapshot = sub.add_parser(
        "derive-control-snapshot", help="Derive V1.2 without changing native group roles"
    )
    snapshot.add_argument("--parent", type=Path, help="Existing V1.1 dataset directory")
    snapshot.add_argument("--parent-revision", required=True, help="Recorded source revision")
    rebind = sub.add_parser("rebind-parent-outcomes", help="Rebind a sealed parent outcome run")
    rebind.add_argument("--parent-run-id", required=True)
    rebind.add_argument("--run-id", required=True)
    rebind.add_argument("--limit-states", type=int)
    rebind.add_argument("--workers", type=int, default=1, help="Parallel CPU-only replay workers")
    delta_plan = sub.add_parser("lock-branch-plan")
    delta_plan.add_argument("--core-run", required=True)
    delta_plan.add_argument("--kind", choices=["incremental_pair", "continuation_audit"],
                            required=True)
    delta_plan.add_argument("--quotas", type=Path)
    delta_plan.add_argument("--online-proposals", type=Path)
    delta_plan.add_argument("--ranked-proposals", action="store_true")
    delta_plan.add_argument("--output", type=Path, required=True)
    delta_plan.add_argument("--seed", type=int, default=20261118)
    proposals = sub.add_parser("propose-train-actions")
    proposals.add_argument("--core-run", required=True)
    proposals.add_argument("--checkpoint", action="append", type=Path, required=True)
    proposals.add_argument("--share-checkpoint-encoder", action="store_true")
    proposals.add_argument("--device", default="cpu")
    proposals.add_argument("--states-per-source", type=int)
    proposals.add_argument("--ranked-source-targets", type=Path)
    proposals.add_argument("--prior-proposals", type=Path)
    proposals.add_argument("--feature-store", type=Path)
    proposals.add_argument("--raw-feature-store", type=Path)
    proposals.add_argument("--progress-output", type=Path)
    proposals.add_argument("--seed", type=int, default=20261118)
    proposals.add_argument("--output", type=Path, required=True)
    pairs = sub.add_parser("report-pairs")
    pairs.add_argument("--run-id", required=True)
    pairs.add_argument("--peer-run")
    pairs.add_argument("--output", type=Path, required=True)
    pair_coverage = sub.add_parser("report-pair-coverage", help="Audit registered TRAIN branches")
    pair_coverage.add_argument("--run-id", required=True)
    pair_coverage.add_argument("--share-reader-run", action="append", default=[])
    pair_coverage.add_argument("--output", type=Path, required=True)
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
    prepare_outcome.add_argument("--recommendation-selection", type=Path, action="append",
                                 default=[])
    prepare_outcome.add_argument("--share-checkpoint-encoder", action="store_true",
                                 help="Share the encoding of a matched frozen checkpoint pair")
    prepare_outcome.add_argument("--policy-pool")
    prepare_outcome.add_argument("--dev-plan", type=Path,
                                 help="Use the registered DEV cohort for held branch evaluation")
    prepare_outcome.add_argument("--device", default="cpu")
    prepare_outcome.add_argument("--seed", type=int, default=20261118)
    prepare_outcome.add_argument("--branch-workers", type=int, default=1,
                                 help="CPU processes for local branch preparation")
    prepare_outcome.add_argument("--continuation-checkpoint", type=Path)
    prepare_outcome.add_argument("--continuation-selection", type=Path)
    prepare_outcome.add_argument("--continuation-epoch", type=int)
    prepare_outcome.add_argument("--branch-plan", type=Path)
    execute_outcome = sub.add_parser("execute-outcomes", help="Use the original Reader ledger")
    execute_outcome.add_argument("--run-id", required=True)
    execute_outcome.add_argument("--limit", type=int, required=True)
    execute_outcome.add_argument("--share-reader-run", action="append", default=[])
    score_outcome = sub.add_parser("score-outcomes", help="Score and ingest completed Reader calls")
    score_outcome.add_argument("--run-id", required=True)
    score_outcome.add_argument("--seal", action="store_true")
    score_outcome.add_argument("--limit", type=int,
                               help="Score up to N replies from states without pending branches")
    for command in (
        prepare_outcome, execute_outcome, score_outcome, rebind, delta_plan, proposals, pairs,
        pair_coverage,
    ):
        command.add_argument("--observation-protocol", choices=(
            "metadata_v1", "semantic_nav_v1", "semantic_nav_delta_v2",
        ))
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
    if args.command == "report-pair-coverage":
        return stage(args, root, config)
    root.mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    name = ".outcomes.lock" if args.command in {
        "prepare-outcomes", "execute-outcomes", "score-outcomes", "rebind-parent-outcomes",
    } else ".build.lock"
    with (root / name).open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        return stage(args, root, config)


if __name__ == "__main__":
    raise SystemExit(main())
