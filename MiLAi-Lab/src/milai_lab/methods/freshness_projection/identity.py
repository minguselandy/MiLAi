"""Offline identity gate for the staged freshness projection arms."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.methods.freshness_projection.controller import RECIPE_ID, TRANSPORT_VARIANT

LAB = Path(__file__).resolve().parents[4]
REFERENCE = LAB / "data/manifests/freshness-v19-repair-reference.json"
PLAN = LAB / "docs/v19修复.md"
B1_CONFIG = LAB / "configs/langmem-b1-v16.json"
REQUIRED_RUNTIME = {
    "src/milai_lab/methods/freshness_projection/__init__.py",
    "src/milai_lab/methods/freshness_projection/projection.py",
    "src/milai_lab/methods/freshness_projection/controller.py",
    "src/milai_lab/methods/freshness_projection/identity.py",
    "src/milai_lab/baselines/langmem_instrumentation.py",
    "src/milai_lab/baselines/langmem_revision_store.py",
    "src/milai_lab/providers/langmem_chat.py",
    "src/milai_lab/runners/langmem_m1_mechanism.py",
    "src/milai_lab/runners/langmem_projection_mechanism.py",
    "tools/run_milai_freshness_projection.py",
    "configs/milai-freshness-projection-v19.json",
}


def verify_lock(lock_path: Path, config_path: Path, arm_id: str,
                ) -> tuple[dict[str, Any], dict[str, Any]]:
    reference, lock, config = read_json(REFERENCE), read_json(lock_path), read_json(config_path)
    stage = "A3" if arm_id == "a3_exact_refresh" else "A2"
    expected = {"kind": f"MILAI_FRESHNESS_PROJECTION_V19_{stage}_LOCK", "status": "FROZEN",
                "reference_manifest_sha256": sha256_file(REFERENCE),
                "recipe_id": RECIPE_ID, "transport_variant": TRANSPORT_VARIANT}
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("PROJECTION_LOCK_" + key.upper() + "_CHANGED")
    if reference["repair_plan_sha256"] != sha256_file(PLAN):
        raise ValueError("PROJECTION_REPAIR_PLAN_CHANGED")
    source_map = lock.get("source_sha256")
    if not isinstance(source_map, dict) or not REQUIRED_RUNTIME <= source_map.keys():
        raise ValueError("PROJECTION_SOURCE_MAP_MISSING")
    if lock.get("source_mapping_sha256") != digest(source_map):
        raise ValueError("PROJECTION_SOURCE_MAPPING_HASH_CHANGED")
    for relative, sha in source_map.items():
        if sha256_file(LAB / relative) != sha:
            raise ValueError("PROJECTION_SOURCE_CHANGED:" + relative)
    baseline = read_json(B1_CONFIG)
    for key in ("host", "embedding", "embedding_dimension"):
        if config[key] != baseline[key]:
            raise ValueError("PROJECTION_CONFIG_" + key.upper() + "_CHANGED")
    if ((config["capacity"] | {"tokenizer_path": ""})
            != (baseline["capacity"] | {"tokenizer_path": ""})):
        raise ValueError("PROJECTION_CONFIG_CAPACITY_CHANGED")
    if (config["recipe_id"] != RECIPE_ID
            or config["transport_variant"] != TRANSPORT_VARIANT):
        raise ValueError("PROJECTION_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_prepared(receipt_path: Path, lock_path: Path, config_path: Path,
                    *, run_id: str, arm_id: str, fixture_path: Path) -> str:
    verify_lock(lock_path, config_path, arm_id)
    receipt = read_json(receipt_path)
    expected = {"status": "PREPARED_ZERO_MODEL", "method": "freshness_projection",
                "run_id": run_id, "arm_id": arm_id,
                "lock_sha256": sha256_file(lock_path),
                "config_sha256": sha256_file(config_path),
                "fixture_sha256": sha256_file(fixture_path)}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("PROJECTION_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]
