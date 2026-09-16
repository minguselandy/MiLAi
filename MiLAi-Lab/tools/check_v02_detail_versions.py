"""Finite public State/cold-client checks for retained ordinary L2 file versions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_e2e_live import metadata
from run_v02_local_vllm import dispatch, manifest, stop_owned
from v02_e2e_state import FileDisclosure, LocalGateError, assemble_layers, save_layers
from v02_low_cost_public import observer

PROJECT = "detail-version-engineering"


def cold(root: Path, case: Path) -> None:
    params = base.read_json(case / "request.json")
    workspace = root / "workspace"
    events = []
    with observer(root / (root.name + "-product"), case, PROJECT, PROJECT) as (call, env):
        head = call("milai_working_state_get", {"scope": "TASK"})
        assert head["state_version_id"] == params["state_version_id"]
        assert head["payload"] == params["payload"]
        guard = FileDisclosure(PROJECT, params["file_refs"], partial(metadata, env))

        def action(tool, args):
            result = dispatch(workspace, params["frozen"], {}, call,
                              {"tool": tool, "arguments_json": json.dumps(args)}, guard)
            events.append({"tool": tool, "args": args, "result": result})
            return result

        files = action("list_files", {})["files"]
        expected_error = params.get("assembly_error")
        if expected_error:
            try:
                assemble_layers(head, workspace, "B", params["config"], files)
            except LocalGateError as exc:
                assert str(exc) == expected_error, str(exc)
            else:
                raise AssertionError("Changed/missing L2 accepted as the saved version")
        else:
            bootstrap = assemble_layers(head, workspace, "B", params["config"], files)
            assert "prefetched_detail" not in bootstrap
            assert "DETAIL_VERSION_ONE" not in json.dumps(bootstrap)
            assert "DETAIL_VERSION_TWO" not in json.dumps(bootstrap)
            guard.acquired(head)

        for name, expected in params["readable"].items():
            assert name in files, "Retained version not discoverable"
            text, offset = "", 0
            while True:
                page = action("read_file", {
                    "path": name, "offset": offset, "expected_sha256": params["frozen"][name],
                })
                assert page["offset"] == offset
                text += page["text"]
                if page["next"] is None:
                    assert page["status"] == "EOF"
                    break
                assert page["next"]["sha256"] == params["frozen"][name]
                assert page["next"]["offset"] > offset
                offset = page["next"]["offset"]
            assert text.encode() == expected.encode(), "Full retained version changed"

        for name, expected in params.get("rejected_reads", {}).items():
            try:
                action("read_file", {"path": name})
            except (ValueError, LocalGateError) as exc:
                assert str(exc) == expected, str(exc)
            else:
                raise AssertionError("Unavailable version disclosed")
        for name in params.get("hidden", []):
            assert name not in files
        guard.before_request()
        base.write_json(case / "result.json", {
            "status": "ENGINEERING_CHECK_PASSED", "pid": os.getpid(),
            "state_version_id": head["state_version_id"], "assembly_error": expected_error,
            "readable": list(params["readable"]), "events": events, "model_calls": 0,
        })


def run(root: Path) -> None:
    config_path = base.LAB / "configs/v02-e2e-generality.json"
    config = base.read_json(config_path)
    assert not config["model_transport_enabled"]
    service = root / (root.name + "-product")
    namespace = service.name + "-pg"
    for command in (
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + namespace],
        ["docker", "volume", "ls", "-q", "--filter",
         "label=com.docker.compose.project=" + namespace],
    ):
        if base._command(command).stdout.strip():
            raise RuntimeError("SERVICE_NAMESPACE_ALREADY_EXISTS")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(root / "plan.json", {
        "pin": base.pin(config_path), "config": config, "cold_processes": 5,
        "source_count": 2, "state_updates": 2, "revocations": 1,
        "model_calls": 0, "provider_tokenize_calls": 0,
        "scope": "RETAINED_NORMAL_FILES_NOT_PRODUCT_HISTORICAL_VERSION_API",
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "service_namespace": namespace,
    })
    workspace = root / "workspace"
    workspace.mkdir()
    one = "DETAIL_VERSION_ONE\r\n首部\n" + "保留版本一。\n" * 320 + "尾部\r\n"
    two = "DETAIL_VERSION_TWO\r\n首部\n" + "独立版本二。\n" * 320 + "尾部\r\n"
    bodies = {"details-v1.md": one, "details-v2.md": two, "independent.txt": "Independent"}
    for name, content in bodies.items():
        (workspace / name).write_bytes(content.encode())
    (workspace / config["l1_path"]).write_text("Continue work; inspect details when needed.")
    frozen = manifest(workspace)
    override = root / "compose-limits.yaml"
    override.write_text("services:\n  postgres:\n    network_mode: bridge\n    cpus: 2\n"
                        "    mem_limit: 1g\n")
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {0, 1})
    results = []
    try:
        base.prepare(service, config_path=config_path, compose_override=override,
                     runtime_overrides={
                         "MILAI_EMBEDDING_PROVIDER": "deterministic_hash",
                         "MILAI_EMBEDDING_SOURCE_DIMENSIONS": "16",
                         "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "16",
                         "MILAI_RETRIEVAL_RERANKER_PROVIDER": "none",
                     })
        parent = root / "parent"
        parent.mkdir()
        with observer(service, parent, PROJECT, PROJECT) as (call, _env):
            refs = {}
            for version in ("v1", "v2"):
                receipt = call("milai_evidence_capture", {
                    "operation_id": "detail-source-" + version,
                    "source_type": "RUNTIME_OBSERVATION",
                    "source_ref": "engineering://detail-version/" + version,
                    "subject_id": "memory-engineering", "speaker": "user",
                    "observed_at": "2026-09-07T10:00:00+08:00",
                    "content": bodies["details-" + version + ".md"],
                    "confirmation": "CAPTURE",
                })
                assert not receipt.get("mcp_error")
                refs[version] = receipt["evidence_id"]
                base.write_json(root / (version + "-source.json"), receipt)
            file_refs = {"details-v1.md": [refs["v1"]], "details-v2.md": [refs["v2"]],
                         "independent.txt": [], config["l1_path"]: []}

            def checkpoint(version):
                local = {**config, "l2_path": "details-" + version + ".md"}
                saved = save_layers(call, workspace, local, frozen, "detail-save-" + version,
                                    [refs[version]])
                assert saved["operation"]["outcome"] == "CONFIRMED"
                assert saved["comparison_opportunity"]
                base.write_json(root / (version + "-save.json"), saved)
                return local, saved

            def launch(name, local, saved, readable, **extra):
                case = root / name
                case.mkdir()
                base.write_json(case / "request.json", {
                    "config": local, "payload": saved["payload"], "frozen": frozen,
                    "state_version_id": saved["operation"]["version_id"],
                    "file_refs": file_refs, "readable": readable, **extra,
                })
                with (case / "worker.log").open("w") as log:
                    completed = subprocess.run(  # noqa: S603
                        [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                         "--cold", str(case)], cwd=case, stdout=log, stderr=log, timeout=60,
                        check=False,
                    )
                assert completed.returncode == 0, "COLD_WORKER_FAILED_SEE_PRESERVED_LOG"
                result = base.read_json(case / "result.json")
                assert result["pid"] != os.getpid()
                results.append({k: v for k, v in result.items() if k != "events"} | {"case": name})

            first_config, first = checkpoint("v1")
            launch("old-head-new-file-unreferenced", first_config, first, bodies)
            second_config, second = checkpoint("v2")
            assert first["operation"]["state_id"] == second["operation"]["state_id"]
            launch("new-head-old-file-retained", second_config, second, bodies)
            (workspace / "details-v2.md").write_text("Different content at the same path")
            launch("changed-current-file", second_config, second, {"details-v1.md": one},
                   assembly_error="DETAIL_VERSION_UNAVAILABLE",
                   rejected_reads={"details-v2.md": "SOURCE_CHANGED"})
            (workspace / "details-v2.md").unlink()
            launch("missing-current-file", second_config, second, {"details-v1.md": one},
                   assembly_error="DETAIL_OUTSIDE_SNAPSHOT",
                   rejected_reads={"details-v2.md": "FILE_NOT_FOUND_OR_NOT_REGULAR"})
            (workspace / "details-v2.md").write_bytes(two.encode())
            revoked = call("milai_evidence_revoke", {
                "evidence_id": refs["v1"], "operation_id": "detail-revoke-v1",
                "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
            })
            assert not revoked.get("mcp_error")
            base.write_json(root / "revocation.json", revoked)
            launch("revoked-old-independent-new", second_config, second,
                   {"details-v2.md": two, "independent.txt": bodies["independent.txt"]},
                   hidden=["details-v1.md"],
                   rejected_reads={"details-v1.md": "FILE_DISCLOSURE_DENIED"})
        assert manifest(workspace) == frozen
        base.write_json(root / "result.json", {
            "status": "RETAINED_DETAIL_VERSION_ENGINEERING_VERIFIED", "cases": results,
            "full_files_restored_to_original_hashes": True,
            "model_calls": 0, "provider_tokenize_calls": 0, "formal_e2e_passed": False,
        })
    finally:
        os.sched_setaffinity(0, affinity)
        base.write_json(root / "cleanup.json", stop_owned(service))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--cold", type=Path)
    args = parser.parse_args()
    if args.cold:
        cold(args.root.resolve(), args.cold.resolve())
    else:
        run(args.root.resolve())
