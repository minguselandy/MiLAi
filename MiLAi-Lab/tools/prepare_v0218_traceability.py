"""Fifth frozen source: native inspection database rows, explicit local export adaptation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from prepare_v0218 import SOURCE_REVISION
from v0218_world import World, digest

DATABASE_SHA256 = "986f8f65086b96d5f252c0d5bdf828b1562173e4126cb6d0e1a73bdd05cbd3d4"


def source_rows(database: Path) -> list[dict]:
    assert hashlib.sha256(database.read_bytes()).hexdigest() == DATABASE_SHA256
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT store_id, store_name, district, date, result, detail "
                "FROM inspections ORDER BY store_id, date"
            )
        ]
    assert len(rows) == 15
    assert hashlib.sha256(database.read_bytes()).hexdigest() == DATABASE_SHA256
    return rows


def inspection_traceability(rows: list[dict], *, include_helpful: bool = False) -> dict:
    public = {
        "objects": ["S037"],
        "task": {
            "instruction": "Create the current inspection evidence export for store S037. "
            "Include its complete confirmed inspection history, latest observation date/result, "
            "and whether any historical inspection failed. Persist the local export record. "
            "A later passed inspection must not erase a genuine historical failure. "
            "This internal evidence workflow resumes in a separate session before review.",
            "record_fields": {
                "inspection_rows": "list of full confirmed source rows for this store only; "
                "preserve store_id, store_name, district, date, result, detail",
                "latest_date": "ISO date of latest confirmed or explicitly pending inspection",
                "latest_result": "exact result 合格/不合格, or pending if latest is unresolved",
                "historical_failure": "boolean: any confirmed historical 不合格 row",
                "status": "confirmed or pending",
                "basis_revision": "current revision for this store, not a global revision",
            },
        },
        "policy": {
            "domain": "inspection_traceability",
            "columns": ["store_id", "store_name", "district", "date", "result", "detail"],
            "pass_result": "合格",
            "fail_result": "不合格",
            "rules": "Export every confirmed source row for the target store exactly once, "
            "no other stores; row order does not matter. Report latest result and historical "
            "failure separately. A pending inspection is not a confirmed row: retain known "
            "history, set the latest result/status to pending, and submit a specific request "
            "to verify that inspection. Fully confirmed facts do not need clarification.",
        },
        "current": {
            "inspections": copy.deepcopy(rows),
            "store_revisions": {"S037": "inspection-v1"},
            "pending_inspections": {},
        },
    }
    changed = copy.deepcopy(public["current"])
    changed["inspections"].append(
        {
            "store_id": "S037",
            "store_name": "润健卡路里",
            "district": "鼓楼",
            "date": "2026-03-18",
            "result": "合格",
            "detail": "舆情复查",
        }
    )
    changed["store_revisions"]["S037"] = "inspection-v2"
    unresolved = copy.deepcopy(public["current"])
    unresolved["store_revisions"]["S037"] = "inspection-review-pending"
    unresolved["pending_inspections"]["S037"] = {"date": "2026-03-18", "status": "unresolved"}
    irrelevant = copy.deepcopy(public["current"])
    irrelevant["inspections"].append(
        {
            "store_id": "unrelated-store",
            "store_name": "Another store",
            "district": "Elsewhere",
            "date": "2026-03-18",
            "result": "不合格",
            "detail": "Unrelated adapted control",
        }
    )
    spec = {
        "root": "journalist_task5",
        "family": "inspection_traceability",
        "source": "tasks/journalist/task5/task.py",
        "public": public,
        "variants": {
            "stable": public["current"],
            "superseded": changed,
            "unresolved": unresolved,
            "irrelevant": irrelevant,
        },
        "task_B": {
            **public["task"],
            "instruction": "Resume and finalize the store S037 "
            "inspection evidence export using current records. Refresh only changed "
            "information and preserve historical findings. Verify genuinely pending "
            "results before treating them as confirmed.",
        },
        "asset": {
            "path": "tasks/journalist/task5/assets/input/food_inspection.db",
            "sha256": DATABASE_SHA256,
            "native_rows": 15,
            "acquisition": "Read-only SQLite SELECT, original bytes unchanged",
        },
        "adaptation": [
            "Preserve all 15 native initial database rows and the native S037 2026-03-18 "
            "re-inspection insertion; confirmed history is retained, not overwritten",
            "Structured current resource replaces Agent-issued SQL; real local SQLite export "
            "record replaces CSV/article files, not a native SQL skill or article-quality score",
            "Video/audio/screenshot provenance, corporate statement verification, reporter/PR "
            "emails and full native rubric are excluded; no actual publication or email",
            "Pending inspection and unrelated-store controls are new explicit adapted variants",
            "Old latest-inspection date becomes stale; prior historical failures remain true. "
            "Not every statement in a prior Note is assumed superseded",
        ],
        "lineage_audit": "Fifth source in the frozen screen order, now asset-complete. "
        "Row-set export completeness, per-store temporal history and current-versus-historical "
        "claims differ from the preceding schedule/claim/release/financial comparison tasks.",
        "exposure": "EXPOSED_DEVELOPMENT",
        "not_applicable": {
            "helpful": "Not yet built; unrelated-store update is applicability "
            "control, not an independent root or a Helpful condition"
        },
    }
    if include_helpful:
        latest = {}
        for row in rows:
            if row["date"] > latest.get(row["store_id"], {}).get("date", ""):
                latest[row["store_id"]] = copy.deepcopy(row)
        spec["variants"]["helpful"] = {
            **copy.deepcopy(public["current"]),
            "inspections": list(latest.values()),
            "view": "latest_per_store",
            "archive_content_sha256": digest(public["current"]),
            "history_access": "Read the ordinary history resource. The prior_public_record "
            "with the identified content hash contains the complete unchanged source history.",
        }
        spec["public"]["policy"]["rules"] += (
            " A latest_per_store view changes display only, not source facts or store revisions. "
            "Its archive_content_sha256 identifies the complete prior_public_record in the "
            "ordinary history resource, available with the same permissions. Use that archive "
            "for complete exports; the latest-only view is not evidence that older rows vanished."
        )
        spec["not_applicable"] = {}
        spec["adaptation"].append(
            "Helpful overlaps Stable: a declared display-only latest-row dashboard retains "
            "full original source facts in ordinary authorized history. Existing business "
            "exports also remain available in both arms. No Note is fabricated, required, "
            "or consulted to select the event; this does not guarantee a Note benefit."
        )
    return spec


def prepare(root: Path, source_root: Path, *, include_helpful: bool = False) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    database = source_root / "tasks/journalist/task5/assets/input/food_inspection.db"
    spec = inspection_traceability(source_rows(database), include_helpful=include_helpful)
    spec["source_sha256"] = hashlib.sha256((source_root / spec["source"]).read_bytes()).hexdigest()
    directory = root / spec["root"]
    directory.mkdir()
    contract = directory / "evaluation-contract.json"
    contract.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    World.create(directory / "initial.sqlite", spec["root"], spec["public"])
    manifest = {
        "revision": "EXPANSION_FIFTH_SOURCE_V2_HELPFUL"
        if include_helpful
        else "EXPANSION_FIFTH_SOURCE_V1",
        "source_revision": SOURCE_REVISION,
        "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
        "model_requests": 0,
        "memory_seeds": 0,
        "roots": [
            {
                "root": spec["root"],
                "family": spec["family"],
                "source": spec["source"],
                "source_sha256": spec["source_sha256"],
                "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
                "variants": list(spec["variants"]),
                "exposure": spec["exposure"],
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--include-helpful", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.source_root, include_helpful=args.include_helpful)))
