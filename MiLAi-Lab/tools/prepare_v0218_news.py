"""Sixth original lineage: explicit structured newsroom authority/conflict adaptation."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from prepare_v0218 import SOURCE_REVISION
from v0218_world import World, digest


def newsroom() -> dict:
    fields = {
        "fire_start": {"publisher": "fire_department", "type": "timestamp"},
        "alarm_received": {"publisher": "fire_department", "type": "timestamp"},
        "casualty_count": {"publisher": "health_commission", "type": "nonnegative_integer"},
        "casualty_status": {"publisher": "health_commission", "type": "status"},
    }
    claims = [
        {
            "id": "briefing-start",
            "incident": "park-fire",
            "field": "fire_start",
            "publisher": "fire_department",
            "edition": 1,
            "value": "2026-03-18T14:28:00+08:00",
        },
        {
            "id": "briefing-alarm",
            "incident": "park-fire",
            "field": "alarm_received",
            "publisher": "fire_department",
            "edition": 1,
            "value": "2026-03-18T14:35:00+08:00",
        },
        {
            "id": "health-count-1",
            "incident": "park-fire",
            "field": "casualty_count",
            "publisher": "health_commission",
            "edition": 1,
            "value": 2,
        },
        {
            "id": "health-status-1",
            "incident": "park-fire",
            "field": "casualty_status",
            "publisher": "health_commission",
            "edition": 1,
            "value": "under_observation",
        },
        {
            "id": "witness-start",
            "incident": "park-fire",
            "field": "fire_start",
            "publisher": "witness",
            "edition": 9,
            "value": "2026-03-18T14:20:00+08:00",
        },
        {
            "id": "witness-count",
            "incident": "park-fire",
            "field": "casualty_count",
            "publisher": "witness",
            "edition": 9,
            "value": 6,
        },
    ]
    task = {
        "instruction": "Maintain the internal fact-check register for park-fire. Persist all "
        "four requested facts with their supporting source IDs. Distinguish fire start from "
        "alarm receipt; do not promote a witness estimate over the competent authority. "
        "This work resumes in a separate session for the evening editorial review.",
        "record_fields": {
            "incident": "park-fire",
            "field": "the requested fact field (same as object ID)",
            "value": "typed resolved value, or null for a genuine unresolved authority conflict",
            "status": "confirmed or conflicting",
            "source_ids": "all current winning authority claim IDs",
            "basis_edition": "highest competent-authority edition for this incident and field",
        },
    }
    public = {
        "objects": list(fields),
        "task": task,
        "policy": {
            "domain": "newsroom_authority",
            "incident": "park-fire",
            "fields": fields,
            "rules": "For each requested fact, use only the specified competent publisher's "
            "claims for this incident and this exact field. Within that publisher/field, the "
            "highest edition replaces earlier editions. Different facts have different roles: "
            "an alarm time is not a fire-start time. If highest-edition authority claims disagree, "
            "persist null/conflicting, cite all those claims and submit a specific verification "
            "request. If they agree, persist the typed value/confirmed and cite all matching "
            "highest-edition authority claims. Later witness or other-incident claims cannot "
            "override them. Counts are nonnegative integers, timestamps require +08:00, "
            "casualty status is under_observation or discharged. "
            "Known facts need no clarification. "
            "An archived_sources display moves unchanged claims to ordinary history: read the "
            "prior_public_record identified by archive_content_sha256. The archive is still "
            "authorized and authoritative; display notices are not new factual evidence.",
        },
        "current": {"claims": claims},
    }
    updated = copy.deepcopy(public["current"])
    for field, value in (("casualty_count", 2), ("casualty_status", "discharged")):
        updated["claims"].append(
            {
                "id": f"health-{field}-2",
                "incident": "park-fire",
                "field": field,
                "publisher": "health_commission",
                "edition": 2,
                "value": value,
            }
        )
    unresolved = copy.deepcopy(updated)
    for field, value in (("casualty_count", 3), ("casualty_status", "under_observation")):
        unresolved["claims"].append(
            {
                "id": f"health-{field}-2-conflict",
                "incident": "park-fire",
                "field": field,
                "publisher": "health_commission",
                "edition": 2,
                "value": value,
            }
        )
    irrelevant = copy.deepcopy(public["current"])
    irrelevant["claims"].extend(
        [
            {
                "id": "other-incident",
                "incident": "other-fire",
                "field": "casualty_count",
                "publisher": "health_commission",
                "edition": 99,
                "value": 50,
            },
            {
                "id": "new-rumor",
                "incident": "park-fire",
                "field": "casualty_count",
                "publisher": "witness",
                "edition": 99,
                "value": 12,
            },
        ]
    )
    helpful = {
        "claims": [],
        "view": "archived_sources",
        "archive_content_sha256": digest(public["current"]),
        "history_access": "Complete unchanged claims remain in the ordinary history resource, "
        "in the prior_public_record identified by this content hash.",
        "notice": "The editorial inbox now displays new notices only; no new factual bulletin.",
    }
    return {
        "root": "journalist_task1",
        "family": "newsroom_authority",
        "source": "tasks/journalist/task1/task.py",
        "public": public,
        "variants": {
            "stable": public["current"],
            "superseded": updated,
            "unresolved": unresolved,
            "irrelevant": irrelevant,
            "helpful": helpful,
        },
        "task_B": {
            **task,
            "instruction": "Resume and finalize all four park-fire register "
            "facts for the evening review, using competent sources and preserving "
            "still-valid findings. Resolve actual updates; verify genuine conflicts.",
        },
        "adaptation": [
            "Structured local authority claims and register rows replace CMS, spreadsheets, "
            "email and multimodal acquisition; this is not the native article-quality rubric.",
            "14:28 fire-start, 14:35 alarm and count 2 are grounded only in the original task's "
            "declared checker expectations, NOT independently transcribed audio/PDF facts. "
            "They are explicitly published task-world premises here, "
            "not runtime private-gold fallback.",
            "The original PDFs have no extractable text in a pypdf 6.0.0 read-only probe. "
            "No OCR, image interpretation, caption, audio transcription or Judge was invoked. "
            "No claim of reproduced multimodal source verification is made.",
            "under_observation initial state, exact claim IDs/edition rules, authority conflict "
            "and latest-notices display are newly declared adaptation facts/controls, not "
            "assertions about unparsed native assets. "
            "Discharged follows the native evening-update theme.",
            "Witness estimates, incident/field scope and authority precedence are kept distinct; "
            "newest globally is not the decision rule. Native evacuation/cause/location/full "
            "timeline, tipster privacy, old-image verification and publishing are excluded.",
            "Helpful overlaps Stable; ordinary history and previous business records stay "
            "equally available, with no fabricated Note and no guaranteed Note advantage.",
        ],
        "lineage_audit": "Sixth frozen original source, not a variant of journalist/task5. "
        "Competing attributed claims and field-specific authority differ from exact inspection "
        "row export and historical/latest distinction; both remain clustered under journalism.",
        "exposure": "EXPOSED_DEVELOPMENT",
        "not_applicable": {},
    }


def prepare(root: Path, source_root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    spec = newsroom()
    spec["source_sha256"] = hashlib.sha256((source_root / spec["source"]).read_bytes()).hexdigest()
    directory = root / spec["root"]
    directory.mkdir()
    contract = directory / "evaluation-contract.json"
    contract.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    World.create(directory / "initial.sqlite", spec["root"], spec["public"])
    manifest = {
        "revision": "EXPANSION_SIXTH_SOURCE_V1",
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
