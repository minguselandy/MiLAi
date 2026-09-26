"""Offline v19 identity gate; source mapping is sealed after V0."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.methods.on_demand_reconstruction.controller import (
    ODR_RECIPE_ID,
    ODR_TRANSPORT_VARIANT,
)

LAB = Path(__file__).resolve().parents[4]
REFERENCE = LAB / "data/manifests/milai-odr-v19-reference.json"
PLAN = LAB / "docs/MILA_ON_DEMAND_RECONSTRUCTION_V19_DEVELOPMENT_PLAN_20260926.md"
B1_CONFIG = LAB / "configs/langmem-b1-v16.json"
REQUIRED_RUNTIME = {
    "src/milai_lab/methods/on_demand_reconstruction/__init__.py",
    "src/milai_lab/methods/on_demand_reconstruction/schema.py",
    "src/milai_lab/methods/on_demand_reconstruction/freshness.py",
    "src/milai_lab/methods/on_demand_reconstruction/evidence_view.py",
    "src/milai_lab/methods/on_demand_reconstruction/controller.py",
    "src/milai_lab/methods/on_demand_reconstruction/metrics.py",
    "src/milai_lab/methods/on_demand_reconstruction/identity.py",
    "src/milai_lab/providers/langmem_chat.py",
    "src/milai_lab/baselines/langmem_agent.py",
    "src/milai_lab/runners/langmem_odr_mechanism.py",
    "src/milai_lab/runners/langmem_m1_mechanism.py",
    "src/milai_lab/runners/langmem_diagnostic.py",
    "src/milai_lab/runners/langmem_merit.py",
    "tools/run_milai_odr.py",
    "tools/inspect_milai_odr.py",
    "configs/milai-odr-v19.json",
}


def verify_odr_lock(lock_path: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    reference, lock, config = read_json(REFERENCE), read_json(lock_path), read_json(config_path)
    expected = {"kind": "MILAI_ODR_V19_LOCK", "status": "FROZEN",
                "reference_manifest_sha256": sha256_file(REFERENCE),
                "recipe_id": ODR_RECIPE_ID,
                "transport_variant": ODR_TRANSPORT_VARIANT}
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("ODR_LOCK_" + key.upper() + "_CHANGED")
    if reference["development_plan_sha256"] != sha256_file(PLAN):
        raise ValueError("ODR_DEVELOPMENT_PLAN_CHANGED")
    source_map = lock.get("source_sha256")
    if not isinstance(source_map, dict) or not REQUIRED_RUNTIME <= source_map.keys():
        raise ValueError("ODR_SOURCE_MAP_MISSING")
    if lock.get("source_mapping_sha256") != digest(source_map):
        raise ValueError("ODR_SOURCE_MAPPING_HASH_CHANGED")
    for relative, sha in source_map.items():
        if sha256_file(LAB / relative) != sha:
            raise ValueError("ODR_SOURCE_CHANGED:" + relative)
    baseline = read_json(B1_CONFIG)
    for key in ("host", "embedding", "embedding_dimension"):
        if config[key] != baseline[key]:
            raise ValueError("ODR_CONFIG_" + key.upper() + "_CHANGED")
    if ((config["capacity"] | {"tokenizer_path": ""})
            != (baseline["capacity"] | {"tokenizer_path": ""})):
        raise ValueError("ODR_CONFIG_CAPACITY_CHANGED")
    if (config["recipe_id"] != ODR_RECIPE_ID
            or config["transport_variant"] != ODR_TRANSPORT_VARIANT):
        raise ValueError("ODR_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_odr_prepared(receipt_path: Path, lock_path: Path, config_path: Path,
                        *, arm_id: str, run_id: str, input_path: Path) -> str:
    verify_odr_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {"status": "PREPARED_ZERO_MODEL", "method": "odr",
                "arm_id": arm_id, "run_id": run_id,
                "lock_sha256": sha256_file(lock_path),
                "config_sha256": sha256_file(config_path),
                "input_sha256": sha256_file(input_path)}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("ODR_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]
