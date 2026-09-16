"""Prepare ordinary source files and isolated public Evidence bindings; no generation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx

import run_v02_memory_flow as base
from v02_file_sources import file_material
from v02_lme_capture import capture_persistent
from v02_lme_sources import history_events
from v02_local_provider import read_events, write_json
from v02_low_cost_public import observer
from v02_variant_plan import branches as planned_branches


def prepare_snapshot(root: Path, source: dict) -> dict:
    is_files = source.get("schema_version") == "v02-file-source-only-v1"
    files = file_material(source, root.name)[0] if is_files else {
        f"session-{s['session_ordinal']:03d}.json": json.dumps(s, ensure_ascii=False, indent=2)
        + "\n"
        for s in source["sessions"]
    }
    service = root / (root.name + "-product")
    base.assert_services(service)
    versions = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    write_json(root / "initial-source-files.json", files)
    output = root / "source-preparation"
    output.mkdir()
    env = base._load_environment(service / "runtime.env")
    original_ids = None
    branches = {}
    config = base.read_json(root / "config.json")
    for arm in planned_branches(config):
        directory = output / arm
        directory.mkdir()
        project = root.name + "-" + arm.lower()
        if is_files:
            _, events, file_ids = file_material(source, project)
        else:
            events = history_events(source, project, preserve_session_time=True)
            file_ids = {
                f"session-{s['session_ordinal']:03d}.json": [
                    e["source_id"] for e in events
                    if e["session_id"] == f"lme-{project}-{s['session_ordinal']}"
                ] for s in source["sessions"]
            }
        ids = capture_verified(env, project, events, directory)
        with observer(service, directory, project, project) as (call, _):
            head = call("milai_working_state_get", {"scope": "TASK"})
            assert head["status"] == "ABSENT", "Never clear an existing G or branch State"
            write_json(directory / "initial-head.json", head)
        if original_ids is None:
            original_ids = ids
        public_ids = dict(zip((e["source_id"] for e in events), ids, strict=True))
        refs = {name: [public_ids[value] for value in values] for name, values in file_ids.items()}
        branches[arm] = {
            "project": project,
            "task_ref": project,
            "file_evidence_refs": refs,
            "reference_mapping_from_g": dict(zip(original_ids, ids, strict=True)),
        }
        print(json.dumps({"prepared": arm, "events": len(ids), "files": len(files)}), flush=True)
    result = {
        "status": "PUBLIC_SOURCES_VERIFIED",
        "source_files": versions,
        "branches": branches,
        "new_generation_requests": 0,
        "G_new_evidence": "Must be mapped before comparison",
    }
    write_json(root / "prepared-bindings.json", result)
    return result


def capture_verified(env: dict, project: str, events: list[dict], directory: Path) -> list[str]:
    """Public durable receipts plus full current Evidence readback; never infer a lost commit."""
    try:
        imported = capture_persistent(env, project, events, directory, 120)
        write_json(directory / "import.json", imported)
        receipts = read_events(directory / "source-receipts.jsonl")
        assert [r["source_id"] for r in receipts] == [e["source_id"] for e in events]
        ids = [r["receipt"]["evidence_id"] for r in receipts]
        assert len(ids) == len(set(ids)) == len(events)
        evidence = []
        with httpx.Client(
            base_url=env["MILAI_BASE_URL"],
            trust_env=False,
            follow_redirects=False,
            timeout=10,
            headers={"Authorization": "Bearer " + env["MILAI_API_TOKEN"]},
        ) as c:
            for event, ref in zip(events, ids, strict=True):
                response = c.get("/v1/evidence/" + ref)
                response.raise_for_status()
                record = response.json()
                assert record["evidence_id"] == ref
                assert record["content"] == event["content"]
                assert record["source_ref"] == event["source_id"]
                assert record["subject_id"] == event["subject_id"]
                assert datetime.fromisoformat(record["observed_at"]) == datetime.fromisoformat(
                    event["observed_at"]
                )
                assert record["permission_snapshot"]["project_ids"] == [project]
                assert record["permission_snapshot"]["readable"] is True
                assert record["retention_state"] == "READABLE" and record["revoked_at"] is None
                roles = {
                    "USER_MESSAGE": "user",
                    "ASSISTANT_MESSAGE": "assistant",
                    "TOOL_RESULT": "tool",
                    "SESSION_MARKER": "system",
                }
                assert record["speaker"] == roles[event["event_type"]]
                for key in (
                    "session_id",
                    "turn_id",
                    "turn_ordinal",
                    "round_id",
                    "round_ordinal",
                    "previous_turn_id",
                    "next_turn_id",
                ):
                    assert record["source_context"][key] == event.get(key)
                evidence.append(record)
        write_json(directory / "verified-metadata.json", evidence)
        return ids
    except Exception as exc:
        write_json(directory / "verification-failure.json", {
            "error_type": type(exc).__name__, "status": "NOT_VERIFIED_NO_RETRY",
            "receipts": "source-receipts.jsonl may contain partial confirmed operations",
        })
        raise
