"""Ninth fixed source: coherent updates across feature spec, backlog, timeline and summary."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from prepare_v0218 import SOURCE_REVISION
from v0218_world import World


def product_review() -> dict:
    features = {
        "F-201": {"priority": "P0", "version": "v2.5", "status": "pending development"},
        "F-202": {"priority": "P0", "version": "v2.5", "status": "pending development"},
        "F-203": {"priority": "P2", "version": "v2.6", "status": "pending evaluation"},
        "F-204": {"priority": "P1", "version": "v2.4", "status": "needs investigation"},
    }
    task = {
        "instruction": "Prepare the Smart Error Notebook product-review artifacts. Persist "
        "feature_spec, backlog, timeline and summary, covering all four features. Keep the "
        "three feature-bearing artifacts mutually consistent with approved team decisions. "
        "Learning Report is an existing v2.4 feature with an access issue requiring investigation, "
        "not a new Phase 1 feature. This work continues in a separate review session.",
        "record_fields": {
            "feature_spec/backlog/timeline": "features: object keyed by all four feature IDs, "
            "each with priority, version, status and phase; basis_revision: review revision",
            "summary": "counts: object with phase1, phase2, existing and pending integer counts; "
            "total: integer feature count; basis_revision: current review revision",
        },
    }
    current = {"features": features, "basis_revision": "review-v1"}
    public = {
        "objects": ["feature_spec", "backlog", "timeline", "summary"],
        "task": task,
        "policy": {
            "domain": "product_review_sync",
            "artifact_roles": {
                "feature_spec": "features",
                "backlog": "features",
                "timeline": "features",
                "summary": "counts",
            },
            "phase_by_version": {"v2.4": "existing", "v2.5": "phase1", "v2.6": "phase2"},
            "clarification_object": "backlog",
            "rules": "Replicate all currently approved feature fields in all three artifacts. "
            "Derive phase from version: v2.4 existing, v2.5 phase1, v2.6 phase2. Count each "
            "feature once in the summary, including existing features in total but not phase1. "
            "Teacher demand and unrelated messages are not release authorization. A feature "
            "with null approved priority/version is genuinely pending a team decision: keep "
            "its priority/version null, status needs decision, phase pending, and request "
            "clarification on backlog; still preserve all known other features and counts. "
            "If all decisions are known, no clarification is required. Partial synchronization "
            "or a correct summary alone does not complete this task.",
        },
        "current": current,
    }
    changed = copy.deepcopy(current)
    changed["features"]["F-203"] = {
        "priority": "P1",
        "version": "v2.5",
        "status": "pending development",
    }
    changed["basis_revision"] = "review-v2"
    changed["decision_notice"] = (
        "Design director confirmed technical feasibility with the technical lead: "
        "move AI Problem-Solving Guidance to Phase 1, P1, v2.5."
    )
    unresolved = copy.deepcopy(current)
    unresolved["features"]["F-203"] = {
        "priority": None,
        "version": None,
        "status": "needs decision",
    }
    unresolved["basis_revision"] = "review-decision-pending"
    irrelevant = copy.deepcopy(current)
    irrelevant["team_event"] = "Unrelated team-building announcement, no product decision."
    return {
        "root": "pm_task3",
        "family": "product_review_sync",
        "source": "tasks/pm/task3/task.py",
        "public": public,
        "variants": {
            "stable": current,
            "superseded": changed,
            "unresolved": unresolved,
            "irrelevant": irrelevant,
        },
        "task_B": {
            **task,
            "instruction": "Resume and finalize all four review artifacts. "
            "Apply authorized changes consistently to feature spec, backlog, timeline "
            "and derived counts; preserve existing-feature classification and known work.",
        },
        "adaptation": [
            "Original stage seeds, design-director feedback, meeting minutes and teacher "
            "interview provide feature IDs, version/priority update and report access issue.",
            "Unlike the native local summary checker phase1=4, this explicit phase taxonomy "
            "keeps already-existing v2.4 separate: initial 2/1/1 and updated 3/0/1 for "
            "phase1/phase2/existing. This is an adapted definition, not a native-rubric verdict.",
            "Local SQLite artifact records replace XLSX/PPTX/Notion artifacts, without layout "
            "or office-file editing claims. Meeting scheduling, email, survey/competitor "
            "extraction and full native rubric are excluded. No real product backlog modified.",
            "Null approved decision and unrelated notice are declared adapted controls. "
            "All feature decisions are ordinary public world inputs, not hidden checker data.",
        ],
        "lineage_audit": "Ninth fixed original source: propagation of one approved change "
        "across independently mutable artifacts and a derived aggregate, not a renamed scalar "
        "update. Partial repair can leave spec/backlog/timeline/summary inconsistent.",
        "exposure": "EXPOSED_DEVELOPMENT",
        "not_applicable": {
            "helpful": "Current small decision table is complete; no artificial "
            "history-only need imposed."
        },
    }


def prepare(root: Path, source_root: Path) -> dict:
    spec = product_review()
    source = source_root / spec["source"]
    spec["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    spec["assets_sha256"] = {
        name: hashlib.sha256((source.parent / "assets/input" / name).read_bytes()).hexdigest()
        for name in ("last_review_meeting.md", "user_interview_teacher.txt")
    }
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    directory = root / spec["root"]
    directory.mkdir()
    contract = directory / "evaluation-contract.json"
    contract.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    World.create(directory / "initial.sqlite", spec["root"], spec["public"])
    manifest = {
        "revision": "EXPANSION_NINTH_SOURCE_V1",
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
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.source_root)))
