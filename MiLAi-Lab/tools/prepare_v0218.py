"""Two source-derived local-world verticals. No model calls or authored memory seeds."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from v0218_world import World

SOURCE_REVISION = "d1b641b3171e584e69a3763c269069f32a13b574"


def scheduling() -> dict:
    public = {
        "objects": ["C03", "C04"],
        "task": {
            "instruction": "Arrange and record complete interviews for C03 and C04 under "
            "the current published availability. Work will resume in another session before "
            "the final schedule is released. Dates are ISO dates, timezone Asia/Shanghai.",
            "record_fields": {
                "start": "ISO datetime +08:00",
                "end": "ISO datetime +08:00",
                "interviewer": "authorized interviewer ID",
                "room": "room ID or online",
                "mode": "in_person or online",
                "confirmed": "boolean",
            },
        },
        "policy": {
            "domain": "scheduling",
            "duration_minutes": 30,
            "interviewers": ["A", "B"],
            "rules": "All candidates require a complete confirmed booking within current "
            "availability. Shared interviewer or physical room cannot overlap. An unresolved "
            "candidate must not have a confirmed booking; record a clarification request.",
        },
        "current": {
            "publication": "availability-v1",
            "rooms": ["301", "302"],
            "candidates": {
                "C03": {
                    "status": "confirmed",
                    "modes": ["in_person"],
                    "windows": [["2026-03-25T09:00:00+08:00", "2026-03-25T12:00:00+08:00"]],
                },
                "C04": {
                    "status": "confirmed",
                    "modes": ["in_person"],
                    "windows": [["2026-03-26T13:00:00+08:00", "2026-03-26T17:00:00+08:00"]],
                },
            },
        },
    }
    changed = copy.deepcopy(public["current"])
    changed["publication"] = "availability-v2"
    changed["rooms"] = ["301"]
    changed["candidates"]["C03"]["modes"] = ["online"]
    changed["candidates"]["C04"]["windows"] = [
        ["2026-03-26T09:00:00+08:00", "2026-03-26T11:00:00+08:00"]
    ]
    unresolved = copy.deepcopy(changed)
    unresolved["candidates"]["C04"]["status"] = "unresolved"
    unresolved["candidates"]["C04"]["windows"] = []
    return {
        "root": "executive_assistant_task2",
        "family": "scheduling",
        "source": "tasks/executive_assistant/task2/task.py",
        "public": public,
        "variants": {"stable": public["current"], "superseded": changed, "unresolved": unresolved},
        "task_B": {
            **public["task"],
            "instruction": "Resume the interview work and finalize "
            "the schedule under the currently published availability. Preserve valid "
            "work. When required availability is genuinely unresolved, record a specific "
            "clarification instead of confirming an unsupported booking.",
        },
        "adaptation": [
            "ISO dates override inconsistent original weekday prose",
            "C03/C04 scheduling slice, not all eight candidates/full rubric",
            "SQLite business records replace real calendar/email/Notion services",
            "no credential-image, voice-fraud, reimbursement or email-privacy claims",
        ],
        "not_applicable": {
            "helpful": "Separate history-navigation profile not built yet",
            "irrelevant": "Metamorphic noncausal event test, not independent root",
        },
    }


def claim() -> dict:
    public = {
        "objects": ["FLT-DLY-0315"],
        "task": {
            "instruction": "Record an insurance adjudication for FLT-DLY-0315 using the "
            "currently valid flight record and policy. This is a reversible internal decision, "
            "not a payment. The claim will be reviewed in another session before release.",
            "record_fields": {
                "decision": "approved, rejected, or pending",
                "amount_cny": "number",
                "delay_minutes": "integer",
                "reason": "current official reason code",
                "basis_revision": "current official record revision",
            },
        },
        "policy": {
            "domain": "claim",
            "covered_reasons": ["weather", "air_traffic_control"],
            "minimum_delay_minutes": 120,
            "hourly_rate_cny": 200,
            "cap_cny": 800,
            "rules": "Use the current valid official record, not claimant estimates. "
            "For covered delay >=120 minutes, pay 200 CNY per completed hour, maximum 800. "
            "Otherwise reject with zero. Pending official facts require clarification and "
            "no approval/rejection. This adapted policy explicitly fixes whole-hour rounding.",
        },
        "current": {
            "claims": {
                "FLT-DLY-0315": {
                    "revision": "official-v1",
                    "status": "confirmed",
                    "scheduled_departure": "2024-03-15T20:00:00+08:00",
                    "actual_departure": "2024-03-15T22:47:00+08:00",
                    "reason": "weather",
                }
            }
        },
    }
    changed = copy.deepcopy(public["current"])
    changed["claims"]["FLT-DLY-0315"].update(revision="official-v2", reason="operational_rotation")
    unresolved = copy.deepcopy(public["current"])
    unresolved["claims"]["FLT-DLY-0315"].update(status="unresolved", revision="review-pending")
    return {
        "root": "insurance_task3",
        "family": "claim",
        "source": "tasks/insurance/task3/task.py",
        "public": public,
        "variants": {"stable": public["current"], "superseded": changed, "unresolved": unresolved},
        "task_B": {
            **public["task"],
            "instruction": "Resume and finalize the claim's internal "
            "adjudication under the current official record and policy. Preserve valid "
            "work; if official facts are pending, record a clarification and do not "
            "make an unsupported final decision. No funds are transferred.",
        },
        "adaptation": [
            "official-v1 is explicitly valid in adapted W0, not native claimant assertion",
            "later authority revision changes the operative adjudication basis",
            "official times are structured public records, not an image recognition result",
            "whole-hour rounding fixed prospectively; local reversible decision, no payout",
            "native fraud-frequency/compliance and full multimodal rubric not reproduced",
        ],
        "not_applicable": {
            "helpful": "Separate history-navigation profile not built yet",
            "irrelevant": "Metamorphic noncausal event test, not independent root",
        },
    }


def prepare(root: Path, source_root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {
        "revision": "VERTICALS_V1",
        "source_revision": SOURCE_REVISION,
        "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
        "roots": [],
        "model_requests": 0,
        "memory_seeds": 0,
        "review": "DEVELOPER_SELF_REVIEW",
    }
    for spec in (scheduling(), claim()):
        original = source_root / spec["source"]
        spec["source_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
        spec["exposure"] = "EXPOSED_DEVELOPMENT"
        directory = root / spec["root"]
        directory.mkdir()
        (directory / "evaluation-contract.json").write_text(json.dumps(spec, indent=2))
        World.create(directory / "initial.sqlite", spec["root"], spec["public"])
        manifest["roots"].append(
            {
                "root": spec["root"],
                "family": spec["family"],
                "source": spec["source"],
                "source_sha256": spec["source_sha256"],
                "contract_sha256": hashlib.sha256(
                    (directory / "evaluation-contract.json").read_bytes()
                ).hexdigest(),
                "variants": list(spec["variants"]),
                "exposure": spec["exposure"],
            }
        )
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.source_root)))
