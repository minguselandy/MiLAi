"""Twelfth source: fictional headcount-constrained register and explicit adapted policy."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from prepare_v0218 import SOURCE_REVISION
from v0218_world import World


def capacity_review() -> dict:
    candidates = {
        key: {
            "performance": p,
            "collaboration": c,
            "potential": t,
            "core_priority": False,
            "followup_support": False,
            "attendance_output_mismatch": key == "I03",
            "recorded_cautious": key == "I04",
        }
        for key, p, c, t in (
            ("I01", 4.8, 4.7, 4.8),
            ("I02", 4.2, 4.3, 4.1),
            ("I03", 3.7, 3.8, 3.6),
            ("I04", 4.1, 4.4, 4.5),
            ("I05", 2.9, 3.1, 2.8),
        )
    }
    task = {
        "instruction": "Prepare the fictional intern batch's internal capacity allocation "
        "records in both ats and summary. Apply the explicit experimental score and capacity "
        "rules to all five IDs; retain complete ranks, recommendation reasons and source "
        "conflict flags. These are draft records, not real hiring decisions or notifications. "
        "The batch will be resumed in a separate session after a staffing update.",
        "record_fields": "Both ats and summary require rows (one per candidate_id, with numeric "
        "score, integer rank, recommendation convert/hold/reject, reason retained/capacity/"
        "below_threshold/headcount_pending, and flags list); headcount (integer or null); "
        "basis_revision. Same candidate data/ranking must appear in both artifacts.",
    }
    current = {"candidates": candidates, "headcount": 4, "basis_revision": "capacity-v1"}
    public = {
        "objects": ["ats", "summary"],
        "task": task,
        "current": current,
        "policy": {
            "domain": "capacity_allocation",
            "clarification_object": "summary",
            "minimum_score": 10,
            "priority_bonus": 1,
            "support_bonus": 0.3,
            "rules": "Experimental draft allocation only: score = performance + collaboration "
            "+ potential + 1 if core_priority + 0.3 if followup_support. Attendance is not "
            "a scoring input. Rank every candidate once, 1 through N, descending score; "
            "ties may be ordered either way, but ats and summary must agree. Scores below "
            "10 are reject/below_threshold. Other candidates ranked within known headcount "
            "are convert/retained; other eligible candidates are hold/capacity. If headcount "
            "is unknown, preserve all computed ranks/scores, reject below-threshold entries "
            "and hold eligible entries with headcount_pending, then ask on summary. "
            "Flag attendance_output_mismatch when present, core_business_priority when core "
            "priority is true, and public_private_support_conflict when recorded_cautious "
            "and followup_support are both true. Flags do not independently change the score. "
            "Do not erase unfavorable evidence or add invented flags. All rows must be "
            "complete and consistent across both artifacts; known capacity needs no question.",
        },
    }
    changed = copy.deepcopy(current)
    changed.update(headcount=3, basis_revision="capacity-v2")
    changed["candidates"]["I02"]["core_priority"] = True
    changed["candidates"]["I04"]["followup_support"] = True
    unresolved = copy.deepcopy(changed)
    unresolved.update(headcount=None, basis_revision="capacity-pending")
    irrelevant = copy.deepcopy(current)
    irrelevant["other_team_headcount"] = 1
    return {
        "root": "hr_task1",
        "family": "capacity_allocation",
        "source": "tasks/hr/task1/task.py",
        "public": public,
        "variants": {
            "stable": current,
            "superseded": changed,
            "unresolved": unresolved,
            "irrelevant": irrelevant,
        },
        "task_B": {
            **task,
            "instruction": "Resume the fictional batch's ats and summary "
            "records under current headcount and confirmed source signals. Recompute "
            "allocation consistently, preserve full rankings and all required flags, "
            "and explain unallocated entries using the declared rules.",
        },
        "adaptation": [
            "Performance/collaboration/potential values read from original scorecard XLSX "
            "with read-only ZIP/XML; five IDs and B headcount=3, I02 priority and I04 follow-up "
            "support come from original public task seed/events.",
            "Additive score, bonuses, threshold, initial headcount=4 and reason enums are "
            "new explicit experimental rules, not the original subjective hiring rubric.",
            "I03 mismatch and I04 recorded-cautious predicates are declared structured "
            "adaptations of task-described signals; no audio/image interpretation is claimed.",
            "Real local ats/summary draft records replace Notion and JSON files. No real "
            "candidate data, protected traits, employment decision, notification, audio "
            "processing or native full-rubric result; no model training or Judge.",
            "Unknown headcount and other-team controls are explicitly adapted. Rank ties "
            "allow multiple legal orders; duplicates, selective omission and stale capacity "
            "cannot satisfy the complete batch contract.",
        ],
        "lineage_audit": "Twelfth frozen original source: capacity-limited joint allocation "
        "and ranking permutation, current evidence bonuses and dual-register consistency. "
        "Not a new root per candidate, score variant or capacity value.",
        "exposure": "EXPOSED_DEVELOPMENT",
        "not_applicable": {
            "helpful": "Current small scorecard and signals remain complete; "
            "no artificial archival dependency."
        },
    }


def prepare(root: Path, source_root: Path) -> dict:
    spec = capacity_review()
    source = source_root / spec["source"]
    spec["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    spec["scorecard_sha256"] = hashlib.sha256(
        (source.parent / "assets/input/intern_conversion_scorecard.xlsx").read_bytes()
    ).hexdigest()
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    directory = root / spec["root"]
    directory.mkdir()
    contract = directory / "evaluation-contract.json"
    contract.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    World.create(directory / "initial.sqlite", spec["root"], spec["public"])
    manifest = {
        "revision": "EXPANSION_TWELFTH_SOURCE_V1",
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
