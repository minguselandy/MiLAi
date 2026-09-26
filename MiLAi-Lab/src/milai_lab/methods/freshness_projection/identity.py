"""Offline identity gate for the staged freshness projection arms."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.methods.freshness_projection.controller import (
    RECIPE_ID,
    SER_RECIPE_ID,
    SER_TRANSPORT_VARIANT,
    SER_V21_RECIPE_ID,
    SER_V21_TRANSPORT_VARIANT,
    TRANSPORT_VARIANT,
)

LAB = Path(__file__).resolve().parents[4]
REFERENCE = LAB / "data/manifests/freshness-v19-repair-reference.json"
PLAN = LAB / "docs/v19修复.md"
B1_CONFIG = LAB / "configs/langmem-b1-v16.json"
SER_REFERENCE = LAB / "data/manifests/milai-ser-v20-reference.json"
MASTER_PLAN = LAB / "docs/MILAI_LONG_HORIZON_MASTER_DEVELOPMENT_PLAN_20260926.md"
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
REQUIRED_SER_RUNTIME = REQUIRED_RUNTIME | {
    "src/milai_lab/methods/freshness_projection/lineage.py",
    "tools/run_milai_ser.py",
    "configs/milai-ser-v20.json",
}
REQUIRED_SER_V21_RUNTIME = REQUIRED_SER_RUNTIME | {
    "tools/run_milai_ser_v21.py",
    "configs/milai-ser-v21.json",
}
REQUIRED_SER_V22_RUNTIME = REQUIRED_SER_V21_RUNTIME | {
    "tools/run_milai_ser_v22.py",
    "configs/milai-ser-v22.json",
    "src/milai_lab/runners/langmem_diagnostic.py",
    "src/milai_lab/runners/langmem_merit.py",
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


def _verify_ser_lock(lock_path: Path, config_path: Path, *, kind: str,
                     recipe_id: str, transport_variant: str,
                     required_runtime: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    reference, lock, config = (read_json(SER_REFERENCE), read_json(lock_path),
                               read_json(config_path))
    expected = {
        "kind": kind, "status": "FROZEN",
        "reference_manifest_sha256": sha256_file(SER_REFERENCE),
        "master_plan_sha256": sha256_file(MASTER_PLAN),
        "recipe_id": recipe_id,
        "transport_variant": transport_variant,
    }
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("SER_LOCK_" + key.upper() + "_CHANGED")
    if reference["master_plan_sha256"] != sha256_file(MASTER_PLAN):
        raise ValueError("SER_MASTER_PLAN_CHANGED")
    source_map = lock.get("source_sha256")
    if not isinstance(source_map, dict) or not required_runtime <= source_map.keys():
        raise ValueError("SER_SOURCE_MAP_MISSING")
    if lock.get("source_mapping_sha256") != digest(source_map):
        raise ValueError("SER_SOURCE_MAPPING_HASH_CHANGED")
    for relative, sha in source_map.items():
        if sha256_file(LAB / relative) != sha:
            raise ValueError("SER_SOURCE_CHANGED:" + relative)
    baseline = read_json(B1_CONFIG)
    for key in ("host", "embedding", "embedding_dimension"):
        if config[key] != baseline[key]:
            raise ValueError("SER_CONFIG_" + key.upper() + "_CHANGED")
    if ((config["capacity"] | {"tokenizer_path": ""})
            != (baseline["capacity"] | {"tokenizer_path": ""})):
        raise ValueError("SER_CONFIG_CAPACITY_CHANGED")
    if (config["recipe_id"] != recipe_id
            or config["transport_variant"] != transport_variant):
        raise ValueError("SER_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_ser_lock(lock_path: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return _verify_ser_lock(
        lock_path, config_path, kind="MILAI_SER_V20_LOCK",
        recipe_id=SER_RECIPE_ID, transport_variant=SER_TRANSPORT_VARIANT,
        required_runtime=REQUIRED_SER_RUNTIME)


def verify_ser_v21_lock(lock_path: Path, config_path: Path,
                        ) -> tuple[dict[str, Any], dict[str, Any]]:
    return _verify_ser_lock(
        lock_path, config_path, kind="MILAI_SER_V21_LOCK",
        recipe_id=SER_V21_RECIPE_ID, transport_variant=SER_V21_TRANSPORT_VARIANT,
        required_runtime=REQUIRED_SER_V21_RUNTIME)


def verify_ser_v22_lock(lock_path: Path, config_path: Path,
                        ) -> tuple[dict[str, Any], dict[str, Any]]:
    return _verify_ser_lock(
        lock_path, config_path, kind="MILAI_SER_V22_LOCK",
        recipe_id=SER_V21_RECIPE_ID, transport_variant=SER_V21_TRANSPORT_VARIANT,
        required_runtime=REQUIRED_SER_V22_RUNTIME)


def verify_ser_prepared(receipt_path: Path, lock_path: Path, config_path: Path,
                        *, run_id: str, arm_id: str, fixture_path: Path) -> str:
    verify_ser_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {"status": "PREPARED_ZERO_MODEL", "method": "ser_v20",
                "run_id": run_id, "arm_id": arm_id,
                "lock_sha256": sha256_file(lock_path),
                "config_sha256": sha256_file(config_path),
                "fixture_sha256": sha256_file(fixture_path)}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("SER_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]


def verify_ser_v21_prepared(receipt_path: Path, lock_path: Path, config_path: Path,
                            *, run_id: str, arm_id: str, fixture_path: Path) -> str:
    verify_ser_v21_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {"status": "PREPARED_ZERO_MODEL", "method": "ser_v21",
                "run_id": run_id, "arm_id": arm_id,
                "lock_sha256": sha256_file(lock_path),
                "config_sha256": sha256_file(config_path),
                "fixture_sha256": sha256_file(fixture_path)}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("SER_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]


def verify_ser_v22_prepared(receipt_path: Path, lock_path: Path, config_path: Path,
                            *, run_id: str, arm_id: str, mode: str,
                            input_path: Path, exposed_freeze: Path,
                            diagnostic_freeze: Path | None) -> str:
    verify_ser_v22_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {"status": "PREPARED_ZERO_MODEL", "method": "ser_v22",
                "run_id": run_id, "arm_id": arm_id, "mode": mode,
                "lock_sha256": sha256_file(lock_path),
                "config_sha256": sha256_file(config_path),
                "input_sha256": sha256_file(input_path),
                "exposed_freeze_sha256": sha256_file(exposed_freeze)}
    if diagnostic_freeze is not None:
        expected["diagnostic_freeze_sha256"] = sha256_file(diagnostic_freeze)
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("SER_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]
