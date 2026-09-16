"""Full opened-history public import, exact declared-reference remap and cold branch checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

import run_v02_memory_flow as base
from check_v02_e2e_live import capture, metadata
from run_v02_local_vllm import manifest
from v02_e2e_state import FileDisclosure, remap_declared_refs
from v02_lme_capture import capture_persistent
from v02_lme_sources import history_events
from v02_local_provider import read_events, write_json
from v02_low_cost_public import observer


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cold(request: Path) -> None:
    params = base.read_json(request)
    directory = request.parent / "cold"
    directory.mkdir()
    with observer(Path(params["service_root"]), directory, params["project"], params["task"]) as (
        call,
        env,
    ):
        head = call("milai_working_state_get", {"scope": "TASK"})
        assert head["payload"] == params["expected_payload"]
        guard = FileDisclosure(
            params["project"], params["file_refs"], lambda ref: metadata(env, ref)
        )
        for path in params["file_refs"]:
            guard.read(path)
        write_json(
            directory / "result.json",
            {
                "pid": os.getpid(),
                "head": head,
                "all_files_eligible": True,
                "files": manifest(Path(params["workspace"])),
            },
        )


def run(root: Path, output_name: str = "source-branches", resume: bool = False) -> None:
    service = root / "e2e-branch-20260906b"
    base.assert_services(service)
    config = base.read_json(base.LAB / "configs/v02-e2e-generality.json")
    assert config["model_transport_enabled"] is False
    if Path(output_name).name != output_name or output_name in {".", ".."}:
        raise ValueError("Unsafe output name")
    directory = root / output_name
    directory.mkdir(exist_ok=resume)
    selection = base.read_json(base.LAB / "studies/active/MILA_V02_LME_INCREMENTAL_SELECTION.json")
    case = selection["D"][0]
    source_root = base.LAB / "artifacts/v02-lme-incremental/data-20260905b"
    source_path = source_root / "sources" / (case + ".json")
    expected = base.read_json(source_root / "manifest.json")["cases"][case]
    assert sha(source_path) == expected["source_sha256"]
    source = base.read_json(source_path)
    license_path = Path("/cra/memory/mx_memory/benchmarks/LongMemEval/LICENSE")
    write_json(
        directory / "selection.json",
        {
            "case": case,
            "source_sha256": sha(source_path),
            "rule": "FIRST_OPENED_D",
            "license_path": str(license_path),
            "license_sha256": sha(license_path),
            "license_observed": "Repository MIT license",
            "license_limit": "Local opened-development use; no dataset redistribution claim",
            "timestamp_convention": "Session time as UTC; turn order kept separately",
            "new_generation_requests": 0,
        },
    )
    env = base._load_environment(service / "runtime.env")
    branches = {}
    original_events = None
    original_payload = None
    original_ids = None
    for arm in ("G", "A", "B"):
        branch = directory / arm
        branch.mkdir(exist_ok=resume)
        project = "source-branch-" + arm.lower() + "-20260906b"
        workspace = branch / "workspace"
        if workspace.exists():
            assert resume
        elif arm == "G":
            workspace.mkdir()
            for session in source["sessions"]:
                write_json(workspace / f"session-{session['session_ordinal']:03d}.json", session)
        else:
            shutil.copytree(directory / "G/workspace", workspace)
        for session in source["sessions"]:
            assert (
                base.read_json(workspace / f"session-{session['session_ordinal']:03d}.json")
                == session
            )
        events = history_events(source, project, preserve_session_time=True)
        write_json(branch / "events.json", events)
        if resume and (branch / "source-receipts.jsonl").exists():
            existing = read_events(branch / "source-receipts.jsonl")
            assert len(existing) == len(events) and all(
                row.get("status") == "RAW_EVIDENCE_CAPTURED" for row in existing
            )
            imported = {
                "status": "EXISTING_PUBLIC_RECEIPTS_REVALIDATED_NO_RECAPTURE",
                "events": len(existing),
                "initial_capture_timing": "NOT_RECORDED",
            }
        else:
            imported = capture_persistent(env, project, events, branch, 120)
        write_json(branch / "import.json", imported)
        receipts = read_events(branch / "source-receipts.jsonl")
        assert [row["source_id"] for row in receipts] == [event["source_id"] for event in events]
        ids = [row["receipt"]["evidence_id"] for row in receipts]
        assert len(set(ids)) == len(events) == expected["source_turns"]
        observations = []
        with httpx.Client(
            base_url=env["MILAI_BASE_URL"],
            trust_env=False,
            follow_redirects=False,
            timeout=10,
            headers={"Authorization": "Bearer " + env["MILAI_API_TOKEN"]},
        ) as client:
            for event, ref in zip(events, ids, strict=True):
                response = client.get("/v1/evidence/" + ref)
                response.raise_for_status()
                value = response.json()
                assert value["content"] == event["content"]
                assert value["source_ref"] == event["source_id"]
                assert datetime.fromisoformat(value["observed_at"]) == datetime.fromisoformat(
                    event["observed_at"]
                )
                assert value["subject_id"] == event["subject_id"]
                role = {
                    "USER_MESSAGE": "user",
                    "ASSISTANT_MESSAGE": "assistant",
                    "TOOL_RESULT": "tool",
                    "SESSION_MARKER": "system",
                }[event["event_type"]]
                assert value["speaker"] == role
                assert value["permission_snapshot"]["project_ids"] == [project]
                assert value["permission_snapshot"]["readable"] is True
                assert value["retention_state"] == "READABLE" and value["revoked_at"] is None
                for key in (
                    "session_id",
                    "turn_id",
                    "turn_ordinal",
                    "round_id",
                    "round_ordinal",
                    "previous_turn_id",
                    "next_turn_id",
                ):
                    assert value["source_context"][key] == event.get(key)
                observations.append(value)
        write_json(branch / "metadata.json", observations)
        file_refs = {}
        for session in source["sessions"]:
            name = f"session-{session['session_ordinal']:03d}.json"
            sid = f"lme-{project}-{session['session_ordinal']}"
            file_refs[name] = [
                ref for event, ref in zip(events, ids, strict=True) if event["session_id"] == sid
            ]
        if arm == "G":
            original_events, original_ids = events, ids
            original_payload = {
                "engineering": "Source identity check; no semantic summary",
                "nested": [{"evidence_id": ids[0]}],
                "evidence_refs": [ids[-1]],
            }
        else:
            for before, after in zip(original_events, events, strict=True):
                for key in ("event_type", "content", "subject_id", "observed_at", "turn_ordinal"):
                    assert before[key] == after[key]
        mapping = dict(zip(original_ids, ids, strict=True))
        payload = remap_declared_refs(original_payload, mapping)
        with observer(service, branch, project, project) as (call, _):
            receipt = call(
                "milai_working_state_update",
                {
                    "scope": "TASK",
                    "state_id": None,
                    "expected_version": 0,
                    "operation_id": project + "-save",
                    "payload": payload,
                },
            )
            assert receipt.get("payload") == payload and receipt["version"] == 1
            # Fixed source-derived query, never the future benchmark question or gold answer.
            query = events[0]["content"][:160]
            found = call("milai_memory_resolve", {"query": query})
            write_json(branch / "initial-search.json", found)
            assert found.get("retrieval_status") in {"HIT", "DEGRADED"} and found.get("evidence")
            canary = "BRANCH_PRIVATE_CANARY_" + arm + "_723f"
            cap = capture(call, project, canary)
        write_json(
            branch / "public.json",
            {
                "import": imported,
                "mapping": mapping,
                "save": receipt,
                "initial_search": found,
                "canary": cap,
            },
        )
        params = {
            "project": project,
            "task": project,
            "service_root": str(service),
            "workspace": str(workspace),
            "expected_payload": payload,
            "file_refs": file_refs,
        }
        request = branch / "cold-request.json"
        write_json(request, params)
        completed = subprocess.run(  # noqa: S603 -- fixed no-model cold worker
            [sys.executable, str(Path(__file__).resolve()), "--cold", str(request)],
            cwd=base.LAB,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        (branch / "cold-worker.log").write_text(completed.stdout + completed.stderr)
        assert completed.returncode == 0, completed.stderr
        recovered = base.read_json(branch / "cold/result.json")
        assert recovered["pid"] != os.getpid()
        if arm != "G":
            assert recovered["files"] == branches["G"]["files"]
        branches[arm] = {
            "project": project,
            "ids": ids,
            "files": recovered["files"],
            "search": found,
            "canary": canary,
            "canary_id": cap["evidence_id"],
        }
        print(json.dumps({"arm": arm, "events": len(ids), "cold_recovery": "PASS"}), flush=True)
    searches = []
    for b in branches.values():
        ordinal = {ref: i for i, ref in enumerate(b["ids"])}
        searches.append(
            [
                {k: item.get(k) for k in ("text", "kind", "observed_at")}
                | {"event_ordinals": [ordinal[ref] for ref in item.get("evidence_ids", [])]}
                for item in b["search"]["evidence"]
            ]
        )
    write_json(directory / "normalized-initial-searches.json", searches)
    initial_search_equivalent = searches[0] == searches[1] == searches[2]
    for arm, other in (("A", "B"), ("B", "A")):
        b, foreign = branches[arm], branches[other]
        check = directory / (arm + "-isolation")
        check.mkdir()
        with observer(service, check, b["project"], b["project"]) as (call, runtime_env):
            found = call("milai_memory_resolve", {"query": foreign["canary"]})
            assert foreign["canary"] not in json.dumps(found)
            head = call("milai_working_state_get", {})
            denied = call(
                "milai_working_state_update",
                {
                    "scope": "TASK",
                    "state_id": head["state_id"],
                    "expected_version": head["version"],
                    "operation_id": b["project"] + "-foreign",
                    "payload": {"evidence_id": foreign["canary_id"]},
                },
            )
            assert "EVIDENCE_REFERENCE_INVALID" in json.dumps(denied)
            guard = FileDisclosure(
                b["project"],
                {"foreign": [foreign["canary_id"]]},
                lambda ref: metadata(runtime_env, ref),
            )
            assert guard.visible({"foreign": "hash"}) == {}
            write_json(
                check / "result.json",
                {"search": found, "foreign_reference": denied, "foreign_file_hidden": True},
            )
    write_json(
        directory / "result.json",
        {
            "status": "FULL_SOURCE_BRANCH_ENGINEERING_OBSERVED",
            "new_generation_requests": 0,
            "case": case,
            "events_per_branch": len(original_events),
            "branches": 3,
            "files_per_branch": len(branches["G"]["files"]),
            "all_source_content_time_role_and_turn_links_verified": True,
            "initial_query_result_order_equivalent": initial_search_equivalent,
            "retrieval_statuses": {
                arm: b["search"]["retrieval_status"] for arm, b in branches.items()
            },
            "degraded_retrieval_is_not_clean_pass": True,
            "scope": "One fixed query, exact references, full source files, three fresh processes",
            "all_possible_queries_equivalent": "NOT_PROVEN",
            "model_task_effect": "NOT_RUN",
            "reference_cap": "State limit remains 256; full-history refs stay outside State",
        },
    )
    assert initial_search_equivalent, "Initial retrieval order differs; preserve fairness gap"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--cold", type=Path)
    parser.add_argument("--output-name", default="source-branches")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.cold:
        cold(args.cold.resolve())
    else:
        run(args.root.resolve(), args.output_name, args.resume)
