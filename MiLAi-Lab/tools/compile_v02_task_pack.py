"""Compile frozen task materials into disabled, reviewable Host configurations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import run_v02_memory_flow as base
from run_v02_e2e_generality import phase_contract
from v02_local_provider import LocalGateError, write_json
from v02_post_g_sources import source_delta
from v02_variant_plan import ALL_ARMS, branches


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def linked(directory: Path, reference: dict) -> tuple[Path, bytes]:
    path = (directory / reference["path"]).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise LocalGateError("TASK_PACK_LINK_OUTSIDE_PACKAGE")
    raw = path.read_bytes()
    if digest(raw) != reference["sha256"]:
        raise LocalGateError("TASK_PACK_LINK_IDENTITY_CHANGED")
    return path, raw


def compile_pack(index_path: Path, bindings_path: Path, host_path: Path, output: Path) -> dict:
    """No services or Provider calls; compilation neither spends nor grants allocations."""
    index_bytes, binding_bytes, host_bytes = (p.read_bytes() for p in (
        index_path, bindings_path, host_path))
    index, binding, host = (json.loads(raw) for raw in (index_bytes, binding_bytes, host_bytes))
    manifest_path, manifest_bytes = linked(base.LAB, {
        "path": index["manifest_path"], "sha256": index["manifest_sha256"]})
    manifest = json.loads(manifest_bytes)
    if binding["manifest_sha256"] != digest(manifest_bytes):
        raise LocalGateError("VARIANT_BINDINGS_TARGET_DIFFERENT_TASK_PACK")
    ids = [entry["id"] for entry in manifest["chains"]]
    if len(set(ids)) != len(ids) or set(ids) != set(binding["bindings"]):
        raise LocalGateError("EXACT_TASK_BINDING_SET_REQUIRED")
    output = output.resolve()
    if not output.is_relative_to(base.LAB.resolve()):
        raise LocalGateError("COMPILED_CONFIG_MUST_BE_LAB_RELATIVE")
    # Host options are a separate explicit template, never copied from past execution grants.
    forbidden = {"source_path", "source_sha256", "post_g_source", "generator_task",
                 "evaluation_contract", "memory_variants", "authorization_basis", "execution_id"}
    if forbidden.intersection(host):
        raise LocalGateError("HOST_TEMPLATE_CONTAINS_TASK_OR_EXECUTION_BINDINGS")
    if any(host.get(key, 0) != 0 for key in (
        "new_model_allocations_authorized", "new_model_tokens_authorized",
        "paid_model_allocations_authorized", "model_transport_enabled", "formal_d4_d5_enabled",
    )):
        raise LocalGateError("TASK_COMPILATION_CANNOT_INHERIT_EXECUTION_AUTHORIZATION")
    if host.get("product_lock") != index["product_lock"]:
        raise LocalGateError("TASK_HOST_PRODUCT_LOCK_DIFFERS")
    prepared = []
    for entry in manifest["chains"]:
        task_path, task_bytes = linked(manifest_path.parent, {
            "path": entry["task_path"], "sha256": entry["task_sha256"]})
        task = json.loads(task_bytes)
        if (task["id"] != entry["id"] or task["family"] != entry["family"]
                or task["sessions"] != list(ALL_ARMS)):
            raise LocalGateError("TASK_PACK_ENTRY_DIFFERS")
        # IDs select frozen declarations; they never select retrieval or interpretation code.
        spec = binding["bindings"][entry["id"]]
        if (spec["B_structure"]["kind"] != task["structure"] or any(
            spec["B_representation"][key] != task["representation"][key]
            for key in ("layer", "kind")
        )):
            raise LocalGateError("VARIANT_BINDING_CHANGES_DECLARED_COMPARISON")
        for variant in spec.values():
            if "source_format" not in variant:
                raise LocalGateError("VARIANT_SOURCE_FORMAT_MUST_BE_EXPLICIT")
        if any(variant["layer"] == "L1" and variant["source_format"] != host["l1_format"]
               for variant in spec.values()):
            raise LocalGateError("VARIANT_FORMAT_DIFFERS_FROM_HOST_L1")
        raw = {name: linked(task_path.parent, task[field])[1] for name, field in (
            ("input-source.json", "generator_sources"),
            ("continuation-source.json", "continuation_sources"),
            ("evaluation-contract.json", "evaluation"))}
        delta = source_delta(json.loads(raw["input-source.json"]),
                             json.loads(raw["continuation-source.json"]))
        if [f["path"] for f in delta["files"]] != task["post_g_new_source_paths"]:
            raise LocalGateError("TASK_POST_G_DELTA_DIFFERS")
        directory = output / entry["id"]
        # Prevent a manifest ID from choosing a path outside the new output directory.
        if directory.parent != output or directory.name in {"", ".", ".."}:
            raise LocalGateError("TASK_ID_NOT_A_DIRECTORY_NAME")
        prefix = directory.relative_to(base.LAB.resolve()).as_posix()
        config = {**host, "schema_version": 1, "experiment_id": "MILA-V02-05-" + task["id"],
            "source_mode": "PUBLIC_SOURCE_SNAPSHOT", "source_path": prefix + "/input-source.json",
            "source_sha256": digest(raw["input-source.json"]),
            "task_evaluation": "SOURCE_ASSERTIONS_FROZEN",
            "evaluation_contract": {"path": prefix + "/evaluation-contract.json",
                                    "sha256": digest(raw["evaluation-contract.json"])},
            "generator_task": task["generator_task"], "memory_variants": spec,
            "local_sessions": list(ALL_ARMS), "model_transport_enabled": False,
            "formal_d4_d5_enabled": False, "new_model_allocations_authorized": 0,
            "new_model_tokens_authorized": 0, "paid_model_allocations_authorized": 0}
        continuation = None
        if delta["files"]:
            config["post_g_source"] = {"path": prefix + "/continuation-source.json",
                "sha256": digest(raw["continuation-source.json"])}
            continuation = raw["continuation-source.json"]
        elif raw["input-source.json"] != raw["continuation-source.json"]:
            raise LocalGateError("UNCHANGED_SOURCE_PACKAGE_BYTES_DIFFER")
        branches(config)
        phase_contract(config, raw["input-source.json"], raw["evaluation-contract.json"],
                       continuation)
        prepared.append((directory, config, raw, {
            "id": task["id"], "family": task["family"], "task_sha256": digest(task_bytes),
            "memory_case": task["memory_case"], "variant_applicability": "REQUIRES_ACTUAL_G",
            "L1_sufficiency": "NOT_EVALUATED", "source_assertions": entry["source_assertions"],
            "config_path": prefix + "/config.json", "post_G_new_files": len(delta["files"])}))
    # Validate the complete pack before publishing any candidate.
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = {"status": "COMPILED_DISABLED_REQUIRES_EXECUTION_GATES", "chains": [],
        "manifest_sha256": digest(manifest_bytes), "index_sha256": digest(index_bytes),
        "bindings_sha256": digest(binding_bytes), "host_template_sha256": digest(host_bytes),
        "compiler_sha256": digest(Path(__file__).read_bytes()), "new_model_calls": 0,
        "formal_D4_D5": "NOT_ENTERED", "developer_visibility": index["developer_visibility"]}
    for directory, config, raw, record in prepared:
        directory.mkdir()
        for name, content in raw.items():
            (directory / name).write_bytes(content)
        write_json(directory / "config.json", config)
        record["config_sha256"] = digest((directory / "config.json").read_bytes())
        result["chains"].append(record)
    write_json(output / "compiled-manifest.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("index", "bindings", "host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compile_pack(args.index, args.bindings, args.host, args.output),
                     ensure_ascii=False))
