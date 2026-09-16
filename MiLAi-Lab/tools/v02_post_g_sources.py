"""Deliver declared new file observations after G exits, through public Evidence only."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import run_v02_memory_flow as base
from v02_file_sources import file_material
from v02_local_provider import LocalGateError, read_events, write_json
from v02_public_snapshot import capture_verified
from v02_variant_plan import branches as planned_branches


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_delta(initial: dict, continuation: dict) -> dict:
    """New observations preserve the original package; revisions use new ordinary paths."""
    file_material(initial, "phase-preflight")
    file_material(continuation, "phase-preflight")
    before = {f["path"]: f for f in initial["files"]}
    after = {f["path"]: f for f in continuation["files"]}
    if any(after.get(name) != value for name, value in before.items()):
        raise LocalGateError("POST_G_ORIGINAL_OBSERVATION_CHANGED")
    return {"schema_version": "v02-file-source-only-v1",
            "files": [value for name, value in after.items() if name not in before]}


def source_packages(root: Path) -> tuple[dict, dict, dict]:
    config = base.read_json(root / "config.json")
    reference = config.get("post_g_source")
    if not isinstance(reference, dict) or not isinstance(reference.get("sha256"), str):
        raise LocalGateError("POST_G_SOURCE_NOT_DECLARED")
    if (sha(root / "input-source.json") != config.get("source_sha256")
            or sha(root / "continuation-source.json") != reference["sha256"]):
        raise LocalGateError("POST_G_SOURCE_IDENTITY_CHANGED")
    initial = base.read_json(root / "input-source.json")
    continuation = base.read_json(root / "continuation-source.json")
    return initial, continuation, source_delta(initial, continuation)


def bindings_fingerprint(root: Path) -> dict:
    return {name: sha(root / name) for name in (
        "config.json", "input-source.json", "continuation-source.json", "prepared-bindings.json",
        "frozen-g-files.json", "checkpoint-result.json", "G/worker-exit.json", "G/result.json",
    )}


def completed_g_files(root: Path) -> dict:
    """Require the completed, frozen G boundary before changing any continuation sources."""
    exit_record = base.read_json(root / "G/worker-exit.json")
    generator = base.read_json(root / "G/result.json")
    events = [e for e in read_events(root / "allocations.jsonl") if e.get("session") == "G"]
    if (exit_record.get("returncode") != 0 or generator.get("status") != "COMPLETED"
            or not events or events[-1].get("event") != "TERMINAL"
            or events[-1].get("status") != "COMPLETED"):
        raise LocalGateError("POST_G_REQUIRES_COMPLETED_WORKER_EXIT")
    if any(e.get("session") != "G" for e in read_events(root / "allocations.jsonl")):
        raise LocalGateError("POST_G_BRANCH_ALREADY_STARTED")
    checkpoint = base.read_json(root / "checkpoint-result.json")
    if checkpoint.get("status") not in {"SAVED_CONFIRMED", "NO_CHANGE"}:
        raise LocalGateError("POST_G_CHECKPOINT_UNCONFIRMED")
    frozen = base.read_json(root / "frozen-g-files.json")
    workspace = root / "G/workspace"
    current = {p.relative_to(workspace).as_posix(): sha(p)
               for p in workspace.rglob("*") if p.is_file()}
    if current != frozen or any(p.is_symlink() for p in workspace.rglob("*")):
        raise LocalGateError("POST_G_FROZEN_WORKSPACE_CHANGED")
    return frozen


def prepare_post_g_sources(root: Path) -> dict:
    """One attempt, after synchronous worker exit; partial imports never become a ready phase."""
    _, continuation, delta = source_packages(root)
    frozen = completed_g_files(root)
    for item in delta["files"]:
        name = item["path"]
        if any(name == old or name.startswith(old + "/") or old.startswith(name + "/")
               for old in frozen):
            raise LocalGateError("POST_G_SOURCE_OVERWRITES_G_ARTIFACT")
    snapshot = base.read_json(root / "prepared-bindings.json")
    arms = planned_branches(base.read_json(root / "config.json"))
    if (snapshot.get("status") != "PUBLIC_SOURCES_VERIFIED"
            or set(snapshot["branches"]) != set(arms)
            or len({b["project"] for b in snapshot["branches"].values()}) != len(arms)):
        raise LocalGateError("POST_G_BRANCH_BINDINGS_INVALID")
    fingerprint = bindings_fingerprint(root)
    output = root / "post-g-source-preparation"
    output.mkdir()  # An earlier partial attempt is evidence, not permission to replay captures.
    started = time.monotonic()
    result = {"status": "PREPARING", "bindings_sha256": fingerprint, "branches": {},
              "new_generation_requests": 0, "new_source_files": len(delta["files"])}
    try:
        env = base._load_environment(root / (root.name + "-product") / "runtime.env")
        all_ids: set[str] = set()
        for arm in arms[1:]:
            binding = snapshot["branches"][arm]
            directory = output / arm
            directory.mkdir()
            refs = {}
            if delta["files"]:
                _, observations, logical_refs = file_material(delta, binding["project"])
                ids = capture_verified(env, binding["project"], observations, directory)
                if all_ids.intersection(ids):
                    raise LocalGateError("POST_G_CROSS_BRANCH_EVIDENCE")
                all_ids.update(ids)
                mapping = dict(zip((e["source_id"] for e in observations), ids, strict=True))
                refs = {name: [mapping[ref] for ref in values]
                        for name, values in logical_refs.items()}
            result["branches"][arm] = {"project": binding["project"], "file_evidence_refs": refs}
            write_json(output / "progress.json", result)
        if bindings_fingerprint(root) != fingerprint:
            raise LocalGateError("POST_G_BINDINGS_CHANGED_DURING_PREPARATION")
        result.update(status="POST_G_PUBLIC_SOURCES_VERIFIED",
                      source_files={f["path"]: f["sha256"] for f in continuation["files"]},
                      elapsed_seconds=time.monotonic() - started)
        write_json(root / "post-g-source-update.json", result)
    except Exception as exc:
        result.update(status="FAILED_NO_RETRY", error_type=type(exc).__name__,
                      elapsed_seconds=time.monotonic() - started)
        raise
    finally:
        write_json(output / "result.json", result)
    return result


def prepared_update(root: Path) -> dict:
    """Recheck the frozen phase before branch copying/binding; no writes or retries."""
    _, continuation, delta = source_packages(root)
    result = base.read_json(root / "post-g-source-update.json")
    if (result.get("status") != "POST_G_PUBLIC_SOURCES_VERIFIED"
            or result.get("bindings_sha256") != bindings_fingerprint(root)
            or result.get("source_files") != {f["path"]: f["sha256"]
                                              for f in continuation["files"]}):
        raise LocalGateError("POST_G_UPDATE_NOT_VERIFIED")
    snapshot = base.read_json(root / "prepared-bindings.json")
    names = {f["path"] for f in delta["files"]}
    seen: set[str] = set()
    for arm in planned_branches(base.read_json(root / "config.json"))[1:]:
        binding = result["branches"][arm]
        refs = binding["file_evidence_refs"]
        ids = [ref for values in refs.values() for ref in values]
        if (binding["project"] != snapshot["branches"][arm]["project"] or set(refs) != names
                or any(len(values) != 1 for values in refs.values())
                or len(ids) != len(set(ids)) or seen.intersection(ids)):
            raise LocalGateError("POST_G_UPDATE_BINDING_INVALID")
        seen.update(ids)
    return result


def stage_post_g_files(root: Path, workspace: Path) -> None:
    prepared_update(root)
    _, _, delta = source_packages(root)
    for item in delta["files"]:
        target = workspace / item["path"]
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise LocalGateError("POST_G_SYMLINK_NOT_ALLOWED")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(item["content"].encode("utf-8"))
