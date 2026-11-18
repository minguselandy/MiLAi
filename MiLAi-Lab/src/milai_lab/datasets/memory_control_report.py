"""Produce measured release receipts and concise rebuild documentation."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_store import DB_NAME, get_meta


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.is_file() else default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    part.replace(path)


def table_counts(db: sqlite3.Connection, source: str, split: str) -> dict[str, int]:
    args = (source, split)
    tasks, groups, clean, clean_groups = db.execute(
        """
        SELECT count(*),count(DISTINCT native_group),sum(clean_role<>'excluded'),
               count(DISTINCT CASE WHEN clean_role<>'excluded' THEN native_group END)
        FROM task_index WHERE dataset=? AND split=?
    """,
        args,
    ).fetchone()
    objects, views = db.execute(
        """
        WITH wanted AS (SELECT DISTINCT root_id FROM task_index WHERE dataset=? AND split=?)
        SELECT (SELECT count(*) FROM objects o JOIN wanted w ON o.root_id=w.root_id),
               (SELECT count(*) FROM views v JOIN objects o ON o.id=v.object_id
                              JOIN wanted w ON o.root_id=w.root_id)
    """,
        args,
    ).fetchone()
    state_count, jobs, covered = db.execute(
        """
        SELECT count(*),count(j.state_id),count(DISTINCT s.task_id)
        FROM task_index t JOIN states s ON s.task_id=t.id
        LEFT JOIN rollout_jobs j ON j.state_id=s.id WHERE t.dataset=? AND t.split=?
    """,
        args,
    ).fetchone()
    anomalies = db.execute(
        "SELECT count(*) FROM anomalies WHERE dataset=? AND split=?", args
    ).fetchone()[0]
    outcomes = db.execute(
        """
        SELECT count(*) FROM action_outcomes a JOIN states s ON s.id=a.state_id
        JOIN task_index t ON t.id=s.task_id WHERE t.dataset=? AND t.split=?
    """,
        args,
    ).fetchone()[0]
    return {
        "normalized": tasks,
        "groups": groups,
        "objects": objects,
        "views": views,
        "states": state_count,
        "tasks_with_states": covered,
        "rollout_jobs": jobs,
        "executed_outcomes": outcomes,
        "anomalies": anomalies,
        "clean_tasks": clean or 0,
        "clean_groups": clean_groups,
    }


def export_rows(db: sqlite3.Connection, path: Path, query: str) -> None:
    part = path.with_name(path.name + ".part")
    with part.open("w", encoding="utf-8") as stream:
        for row in db.execute(query):
            data = dict(row)
            if "detail" in data:
                data["detail"] = json.loads(data["detail"])
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    part.replace(path)


def report(
    db: sqlite3.Connection, root: Path, config: dict[str, Any], *, commands: list[str]
) -> dict[str, Any]:
    manifests = root / "manifests"
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    acquired = read_json(manifests / "acquisition.json", {})
    verified = read_json(reports / "validation.json", {})
    smokes = {
        arm: read_json(reports / arm / "dataset-dry-run.json", {})
        for arm in ("object_mlp", "latent_pointer")
    }
    run_id = get_meta(db, "run_id")
    rollout_probe = read_json(reports / "rollout-probe.json", {})
    raw_counts = get_meta(db, "raw_counts")
    source_rows = []
    for source, cfg in config["sources"].items():
        for split, raw in raw_counts[source].items():
            key = f"{source}/{split}"
            declared = cfg["declared_tasks"][split]
            counts = table_counts(db, source, split)
            source_rows.append(
                {
                    "dataset": source,
                    "split": split,
                    "declared": declared,
                    "declared_approximate": cfg.get("declared_tasks_approximate", False),
                    "declared_groups": cfg.get("declared_groups", {}).get(split),
                    "raw": raw["raw"],
                    "normalized_excluded": raw["excluded"],
                    "source_parsed": raw["source_parsed"],
                    **{
                        key: raw[key]
                        for key in ("raw_groups", "raw_history_references")
                        if key in raw
                    },
                    **counts,
                    **verified.get("state_statistics", {}).get(key, {}),
                }
            )
    total = {
        name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]  # noqa: S608
        for name in (
            "tasks",
            "objects",
            "views",
            "states",
            "weak_labels",
            "rollout_jobs",
            "action_outcomes",
            "anomalies",
            "exclusions",
        )
    }
    status = {
        "raw_data_ready": bool(acquired.get("files"))
        and not acquired.get("errors")
        and all(row["source_parsed"] for row in source_rows),
        "normalized_tasks_ready": all(
            row["raw"] > 0 and row["raw"] == row["normalized"] for row in source_rows
        ),
        "weak_supervision_ready": (
            all(row.get("weak_rows", 0) > 0 for row in source_rows) and bool(verified.get("passed"))
        ),
        "milai_loader_ready": all(
            value.get("status") == "PASSED" and value.get("run_id") == run_id
            for value in smokes.values()
        ),
        "embedding_features_ready": "not_requested",
        "rollout_jobs_ready": (
            all(row["rollout_jobs"] == row["states"] > 0 for row in source_rows)
            and rollout_probe.get("dataset_run_id") == run_id
        ),
        "executed_outcome_rows": total["action_outcomes"],
        "outcome_training_ready": False,
    }
    ready = bool(verified.get("passed")) and all(
        status[key] is True
        for key in (
            "raw_data_ready",
            "normalized_tasks_ready",
            "weak_supervision_ready",
            "milai_loader_ready",
            "rollout_jobs_ready",
        )
    )
    raw_files = Counter(parsed=0, failed=0)
    for item in acquired.get("files", []):
        raw_files["parsed" if item["parsed"] else "failed"] += 1
    result = {
        "status": "DATA_PREP_COMPLETE" if ready else "PARTIAL_WITH_BLOCKERS",
        "run_id": run_id,
        "data_root": str(root),
        "database_bytes": (root / DB_NAME).stat().st_size,
        "raw_bytes": sum(f.get("bytes", 0) for f in acquired.get("files", [])),
        "raw_file_counts": dict(raw_files),
        **status,
        "splits": source_rows,
        "unique_table_counts": total,
        "official_group_overlap": {
            source: len(groups)
            for source, groups in get_meta(db, "official_group_overlap", {}).items()
        },
        "validation": verified,
        "loader_dry_runs": smokes,
        "rollout_probe": rollout_probe,
        "tokenizers": get_meta(db, "tokenizers"),
        "code_base": get_meta(db, "code_base"),
        "configuration": config,
        "rebuild_commands": commands,
    }
    if verified:
        observed = Counter(verified.get("measurements", {}))
        errors = Counter(verified.get("errors", {}))
        statuses = ("exact", "normalized", "ambiguous", "unmatched")
        result["evidence_alignment"] = {
            key: {status: observed[f"{key}/{status}"] for status in statuses}
            for key in (
                "qasper/train/evidence",
                "qasper/validation/evidence",
                "qasper/train/highlighted_evidence",
                "qasper/validation/highlighted_evidence",
                "personamem_v2/train/snippet",
                "personamem_v2/validation/snippet",
            )
        }
        result["reference_mismatches"] = {
            "sql_foreign_keys": errors["sql_foreign_keys"],
            "view_object_ranges": errors["view_object_range_mismatch"],
            "state_candidate_views": errors["state_candidate_view_mismatch"],
            "state_read_views": errors["state_prefix_or_delivered_mismatch"],
            "action_bindings": errors["state_action_binding_mismatch"],
            "weak_masks": errors["state_unknown_mask_mismatch"],
        }
    result["clean_split_totals"] = {
        role: {"tasks": tasks, "states": states}
        for role, tasks, states in db.execute("""
            SELECT t.clean_role, count(DISTINCT t.id), count(s.id)
            FROM tasks t LEFT JOIN states s ON s.task_id=t.id GROUP BY t.clean_role
        """)
    }
    write_json(reports / "build_report.json", result)
    write_json(
        manifests / "sources.json",
        {
            "run_id": run_id,
            "dataset_release": config["dataset_release"],
            "processing_version": config["processing_version"],
            "sources": config["sources"],
            "splits": source_rows,
            "file_receipts": "acquisition.json",
        },
    )
    write_json(manifests / "configuration.json", config)
    write_json(
        manifests / "splits.json",
        {
            "official_group_overlap": get_meta(db, "official_group_overlap"),
            "clean_training_policy": config["supervision"]["clean_split_policy"],
            "removed_train_rows": total["exclusions"],
            "removed_rows": "clean_train_exclusions.jsonl",
            "clean_group_overlap": verified.get("clean_group_overlap"),
            "random_source_groups": get_meta(db, "random_source_groups"),
        },
    )
    export_rows(
        db,
        manifests / "clean_train_exclusions.jsonl",
        """
        SELECT e.task_id,t.dataset,t.split,t.native_group,t.raw_path,t.source_row,e.reason
        FROM exclusions e JOIN task_index t ON t.id=e.task_id ORDER BY t.id,e.reason
    """,
    )
    export_rows(db, reports / "anomalies.jsonl", "SELECT * FROM anomalies ORDER BY id")
    tick = chr(96)
    fence = tick * 3
    lines = [
        f"# MiLAi memory_control_v1 · {result['status']}",
        "",
        f"数据目录 {tick}{root}{tick}\uff0c构建编号 {tick}{run_id}{tick}。原始文件 "
        f"{raw_files['parsed']:,} 个\uff0c共 {result['raw_bytes']:,} 字节。校验阶段记录 "
        f"{raw_files['failed']:,} 个源文件失败。",
        "",
        "| 来源 / split | 作者声明 | 实际原始 | 规范化 | 独立组 | 引用对象 | 引用视图 |"
        " 状态 | 有已知证据标签的状态 | 已执行收益 | 异常 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in source_rows:
        declared = ("约 " if row["declared_approximate"] else "") + f"{row['declared']:,}"
        if row["declared_groups"]:
            declared += f" QA / {row['declared_groups']:,} 论文"
        values = [
            row["raw"],
            row["normalized"],
            row["groups"],
            row["objects"],
            row["views"],
            row["states"],
            row.get("weak_rows", 0),
            row["executed_outcomes"],
            row["anomalies"],
        ]
        lines.append(
            f"| {row['dataset']} / {row['split']} | {declared} | "
            + " | ".join(f"{v:,}" for v in values)
            + " |"
        )
    lines.extend(
        [
            "",
            f"全库有 {total['objects']:,} 个对象、{total['views']:,} 个视图、"
            f"{total['states']:,} 个状态和 {total['rollout_jobs']:,} 个 rollout 作业。"
            "每行的对象与视图统计该 split 引用的唯一条目\uff0c"
            "PersonaMem 两个官方 split 共享原始历史。",
            "",
            "## 交付状态",
            "",
            fence + "text",
            *(f"{k}: {str(v).lower()}" for k, v in status.items()),
            fence,
            "",
            "## 重建",
            "",
            "在实际 MiLAi-Lab 工作目录运行下列命令。",
            "",
            fence + "bash",
            *commands,
            fence,
            "",
        ]
    )
    (reports / "BUILD_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return result
