"""Public file-source imports and cold Host file reads; no model or private Product imports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import run_v02_memory_flow as base
from check_v02_e2e_live import metadata
from run_v02_local_vllm import dispatch, stop_owned
from v02_e2e_state import FileDisclosure, LocalGateError, file_path, remap_declared_refs
from v02_file_sources import file_material
from v02_low_cost_public import observer
from v02_public_snapshot import prepare_snapshot


def load_sources(directory: Path) -> dict:
    manifest = base.read_json(directory / "manifest.json")
    observed = datetime.now(UTC).isoformat()
    files = []
    for entry in manifest["files"]:
        raw = file_path(directory, entry["snapshot_file"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        files.append({"path": entry["snapshot_file"],
                      "source_uri": Path(entry["source_path"]).as_uri(),
                      "observed_at": observed, "content": raw.decode("utf-8"),
                      "sha256": entry["sha256"]})
    source = {"schema_version": "v02-file-source-only-v1", "files": files}
    file_material(source, "preflight")
    return source


def cold(root: Path, request: Path) -> None:
    params = base.read_json(request)
    binding = base.read_json(root / "prepared-bindings.json")["branches"][params["arm"]]
    files, _, _ = file_material(
        base.read_json(root / "file-source-package.json"), binding["project"])
    directory = request.parent
    workspace = root / "workspaces" / params["arm"]
    frozen = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}
    with observer(root / (root.name + "-product"), directory,
                  binding["project"], binding["task_ref"]) as (call, env):
        head = call("milai_working_state_get", {"scope": "TASK"})
        assert head["state_version_id"] == params["receipt"]["state_version_id"]
        if params["hidden"]:
            assert head["payload"] == {} and head["payload_withheld"]
        else:
            assert head["payload"] == params["receipt"]["payload"]
        guard = FileDisclosure(binding["project"], binding["file_evidence_refs"],
                               partial(metadata, env))

        def action(tool, arguments):
            return dispatch(workspace, frozen, {}, call,
                            {"tool": tool, "arguments_json": json.dumps(arguments)}, guard)

        visible = action("list_files", {})["files"]
        assert set(visible) == set(files) - set(params["hidden"])
        read_hashes = {}
        for name in files:
            if name in params["hidden"]:
                try:
                    action("read_file", {"path": name})
                except LocalGateError as exc:
                    assert str(exc) == "FILE_DISCLOSURE_DENIED"
                else:
                    raise AssertionError("Revoked file disclosed")
                continue
            text, offset = "", 0
            while True:
                page = action("read_file", {"path": name, "offset": offset,
                                            "expected_sha256": frozen[name]})
                text += page["text"]
                if page["next"] is None:
                    assert page["status"] == "EOF"
                    break
                assert page["next"]["offset"] > offset
                offset = page["next"]["offset"]
            assert text.encode() == files[name].encode()
            read_hashes[name] = hashlib.sha256(text.encode()).hexdigest()
        guard.before_request()
        base.write_json(directory / "result.json", {
            "status": "COLD_FILE_SNAPSHOT_VERIFIED", "pid": os.getpid(),
            "state_id": head["state_id"], "version_id": head["state_version_id"],
            "hidden": params["hidden"], "read_hashes": read_hashes, "model_calls": 0,
        })


def run(root: Path, config_path: Path) -> dict:
    config = base.read_json(config_path)
    assert not config["model_transport_enabled"]
    source = load_sources(base.LAB / config["file_preparation"])
    pin = base.pin(config_path)
    service = root / (root.name + "-product")
    namespace = service.name + "-pg"
    for command in (["docker", "ps", "-aq"], ["docker", "volume", "ls", "-q"]):
        assert not base._command([*command, "--filter",
                                 "label=com.docker.compose.project=" + namespace]).stdout.strip()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base.write_json(root / "file-source-package.json", source)
    base.write_json(root / "config.json", config)
    base.write_json(root / "preflight.json", {
        "pin": pin, "model_calls": 0,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(
            (root / "file-source-package.json").read_bytes()).hexdigest(),
    })
    report = {"status": "RUNNING", "model_calls": 0, "cold": []}
    affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, sorted(affinity)[:2])
    try:
        base.prepare(service, config_path=config_path,
                     compose_override=base.LAB / "tools/containers/v02-local-bounded.compose.yaml",
                     runtime_overrides={"MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED"})
        bindings = prepare_snapshot(root, source)
        receipts = {}
        files = file_material(source, root.name)[0]
        g_refs = [ref for refs in bindings["branches"]["G"]["file_evidence_refs"].values()
                  for ref in refs]
        payload = {"first": "FILE_SNAPSHOT_ENGINEERING_FIXTURE", "source_files": list(files),
                   "evidence_refs": g_refs, "last": "NOT_AGENT_GENERATED_MEMORY"}
        for arm, binding in bindings["branches"].items():
            workspace = root / "workspaces" / arm
            for name, text in files.items():
                path = workspace / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode())
            directory = root / ("save-" + arm)
            directory.mkdir()
            with observer(service, directory, binding["project"], binding["task_ref"]) as (call, _):
                proposed = remap_declared_refs(payload, binding["reference_mapping_from_g"])
                receipts[arm] = call("milai_working_state_update", {
                    "scope": "TASK", "expected_version": 0,
                    "operation_id": "file-fixture-" + arm, "payload": proposed,
                })
                assert receipts[arm]["payload"] == proposed
                head = call("milai_working_state_get", {"scope": "TASK"})
                assert head["state_version_id"] == receipts[arm]["state_version_id"]
        assert len({v["state_id"] for v in receipts.values()}) == 3
        base.write_json(root / "state-receipts.json", receipts)

        def verify(arm, label, hidden):
            directory = root / label
            directory.mkdir()
            request = directory / "request.json"
            base.write_json(request, {"arm": arm, "hidden": hidden, "receipt": receipts[arm]})
            base._command([sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                           "--cold", str(request)], cwd=base.LAB, timeout=120)
            result = base.read_json(directory / "result.json")
            assert not Path("/proc", str(result["pid"])).exists()
            report["cold"].append(result)

        for arm in receipts:
            verify(arm, "cold-" + arm, [])
        a = bindings["branches"]["A"]
        first = next(iter(files))
        directory = root / "revoke-A"
        directory.mkdir()
        with observer(service, directory, a["project"], a["task_ref"]) as (call, _):
            value = call("milai_evidence_revoke", {
                "evidence_id": a["file_evidence_refs"][first][0], "operation_id": "revoke-file-A",
                "reason_code": "USER_REQUEST", "confirmation": "REVOKE",
            })
            assert not value.get("mcp_error")
            base.write_json(directory / "receipt.json", value)
        verify("A", "revoked-cold-A", [first])
        verify("B", "unaffected-cold-B", [])
        report["status"] = "PUBLIC_FILE_IMPORT_COLD_RECOVERY_AND_REVOCATION_VERIFIED"
    except BaseException as exc:
        report.update(status="FAILED", error_type=type(exc).__name__)
        raise
    finally:
        if (service / "runtime.env").exists():
            report["cleanup"] = stop_owned(service)
        os.sched_setaffinity(0, affinity)
        base.write_json(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--cold", type=Path)
    args = parser.parse_args()
    if args.cold:
        cold(args.root.resolve(), args.cold.resolve())
    else:
        run(args.root.resolve(), args.config.resolve())
