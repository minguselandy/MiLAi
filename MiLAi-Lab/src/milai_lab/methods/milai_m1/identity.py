"""Separate v17 source/run identity without mutating the frozen v16 lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.methods.milai_m1.controller import M1_RECIPE_ID, M1_TRANSPORT_VARIANT

LAB = Path(__file__).resolve().parents[4]
REFERENCE = LAB / "data/manifests/milai-m1-v17-reference.json"
B1_LOCK = LAB / "data/locks/langmem-b1.lock.json"
B1_CONFIG = LAB / "configs/langmem-b1-v16.json"
PLAN = LAB / "docs/MILA_LANGMEM_M1_V17_DEVELOPMENT_PLAN_20260926.md"
ARMS = ("b1_control", "m1")
REQUIRED_RUNTIME = {
    "src/milai_lab/methods/__init__.py",
    "src/milai_lab/methods/milai_m1/__init__.py",
    "src/milai_lab/methods/milai_m1/decision_basis.py",
    "src/milai_lab/methods/milai_m1/evidence_view.py",
    "src/milai_lab/methods/milai_m1/recheck.py",
    "src/milai_lab/methods/milai_m1/state_store.py",
    "src/milai_lab/methods/milai_m1/controller.py",
    "src/milai_lab/methods/milai_m1/identity.py",
    "src/milai_lab/providers/langmem_chat.py",
    "src/milai_lab/baselines/langmem_agent.py",
    "src/milai_lab/baselines/langmem_instrumentation.py",
    "src/milai_lab/runners/langmem_diagnostic.py",
    "src/milai_lab/runners/langmem_merit.py",
    "src/milai_lab/runners/langmem_m1_mechanism.py",
    "tools/run_langmem_provenance.py",
    "tools/run_milai_m1.py",
    "configs/milai-m1-v17.json",
    "pyproject.toml", "uv.lock",
}


def verify_m1_lock(lock_path: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, config = read_json(lock_path), read_json(config_path)
    reference = read_json(REFERENCE)
    expected = {
        "kind": "MILAI_M1_V17_LOCK", "status": "FROZEN",
        "reference_manifest_sha256": sha256_file(REFERENCE),
        "reference_b1_lock_sha256": sha256_file(B1_LOCK),
        "recipe_id": M1_RECIPE_ID,
        "transport_variant": M1_TRANSPORT_VARIANT,
    }
    for field, value in expected.items():
        if lock.get(field) != value:
            raise ValueError(f"M1_LOCK_{field.upper()}_CHANGED")
    if reference["development_plan_sha256"] != sha256_file(PLAN):
        raise ValueError("M1_DEVELOPMENT_PLAN_CHANGED")
    if (reference["reference_artifacts_sha256"]["data/locks/langmem-b1.lock.json"]
            != sha256_file(B1_LOCK)):
        raise ValueError("M1_REFERENCE_B1_LOCK_CHANGED")
    source_map = lock.get("source_sha256")
    if (not isinstance(source_map, dict)
            or not REQUIRED_RUNTIME <= source_map.keys()
            or not reference["reference_source_sha256"].keys() <= source_map.keys()):
        raise ValueError("M1_SOURCE_MAP_MISSING")
    if lock.get("source_mapping_sha256") != digest(source_map):
        raise ValueError("M1_SOURCE_MAPPING_HASH_CHANGED")
    for relative, sha in source_map.items():
        if sha256_file(LAB / relative) != sha:
            raise ValueError(f"M1_SOURCE_CHANGED:{relative}")
    for relative, sha in reference["reference_source_sha256"].items():
        if relative not in source_map and sha256_file(LAB / relative) != sha:
            raise ValueError(f"M1_REFERENCE_SOURCE_CHANGED:{relative}")
    old = read_json(B1_CONFIG)
    if (config.get("recipe_id") != M1_RECIPE_ID
            or config.get("transport_variant") != M1_TRANSPORT_VARIANT
            or config.get("host") != old["host"]
            or config.get("embedding") != old["embedding"]
            or config.get("embedding_dimension") != old["embedding_dimension"]
            or config.get("capacity", {}) | {"tokenizer_path": ""}
            != old["capacity"] | {"tokenizer_path": ""}
            or "m1_state_path" not in config
            or "sidecar_path" not in config):
        raise ValueError("M1_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_m1_prepared(
    receipt_path: Path, lock_path: Path, config_path: Path,
    *, arm_id: str, run_id: str, input_path: Path,
) -> str:
    verify_m1_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {
        "status": "PREPARED_ZERO_MODEL", "method": "m1",
        "arm_id": arm_id, "run_id": run_id,
        "lock_sha256": sha256_file(lock_path),
        "config_sha256": sha256_file(config_path),
        "input_sha256": sha256_file(input_path),
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(f"M1_PREPARED_{field.upper()}_CHANGED")
    return expected["lock_sha256"]
