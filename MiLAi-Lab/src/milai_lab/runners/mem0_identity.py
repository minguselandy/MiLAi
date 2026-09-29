"""Frozen identity for the external-memory Formation comparison."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_agent import RECIPE_ID as B1_RECIPE_ID
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import read_json
from milai_lab.integrations.memory.mem0 import (
    MEM0_POLICY,
    MEM0_PROTOCOL_ID,
    MEM0_SEARCH_CONTRACT_SHA256,
    MEM0_SYSTEM_PROMPT_SHA256,
)
from milai_lab.integrations.memory.mem0 import MEM0_SOURCE_COMMIT as MEM0_SOURCE_COMMIT
from milai_lab.methods.freshness_projection.identity import (
    LAB,
    REQUIRED_APPLICATION_V25_RUNTIME,
    _verify_ser_lock,
)

PROTOCOL = LAB / "data/manifests/milai-external-memory-v26-protocol.json"
INPUT_REFERENCE = LAB / "data/manifests/milai-external-memory-v26-input-reference.json"
PROTOCOL_BY_ARM = {
    "b1_control": "langmem_default_v1",
    "mem0_native_autoadd": MEM0_PROTOCOL_ID,
}
REQUIRED_EXTERNAL_V26_RUNTIME = REQUIRED_APPLICATION_V25_RUNTIME | {
    "src/milai_lab/runners/mem0_native.py",
    "src/milai_lab/runners/mem0_identity.py",
    "src/milai_lab/runners/langmem_diagnostic.py",
    "src/milai_lab/baselines/langmem_agent.py",
    "tools/run_milai_external_memory_v26.py",
    "configs/milai-external-memory-v26.json",
    "pyproject.toml",
    "uv.lock",
}


def verify_external_v26_lock(lock_path: Path, config_path: Path,
                             *, arm_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, config = _verify_ser_lock(
        lock_path, config_path, kind="MILAI_EXTERNAL_MEMORY_V26_LOCK",
        recipe_id=B1_RECIPE_ID, transport_variant="json_action",
        required_runtime=REQUIRED_EXTERNAL_V26_RUNTIME,
    )
    expected = {
        "protocol_sha256": sha256_file(PROTOCOL),
        "input_reference_sha256": sha256_file(INPUT_REFERENCE),
        "protocol_by_arm": PROTOCOL_BY_ARM,
        "mem0_source_commit": MEM0_SOURCE_COMMIT,
        "mem0_system_prompt_sha256": MEM0_SYSTEM_PROMPT_SHA256,
        "mem0_search_contract_sha256": MEM0_SEARCH_CONTRACT_SHA256,
        "mem0_environment_receipt_sha256": sha256_file(
            LAB / config["mem0_environment"]["receipt_path"]),
    }
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("EXTERNAL_V26_LOCK_" + key.upper() + "_CHANGED")
    if arm_id not in PROTOCOL_BY_ARM:
        raise ValueError("EXTERNAL_V26_ARM_UNKNOWN")
    if config.get("mem0_policy") != MEM0_POLICY:
        raise ValueError("EXTERNAL_V26_MEM0_POLICY_CHANGED")
    return lock, config


def verify_external_v26_prepared(receipt_path: Path, lock_path: Path,
                                 config_path: Path, *, run_id: str,
                                 arm_id: str, inputs_path: Path,
                                 diagnostic_freeze: Path) -> str:
    verify_external_v26_lock(lock_path, config_path, arm_id=arm_id)
    receipt = read_json(receipt_path)
    expected = {
        "status": "PREPARED_ZERO_MODEL",
        "method": "external_memory_v26",
        "run_id": run_id, "arm_id": arm_id,
        "lock_sha256": sha256_file(lock_path),
        "config_sha256": sha256_file(config_path),
        "input_sha256": sha256_file(inputs_path),
        "diagnostic_freeze_sha256": sha256_file(diagnostic_freeze),
        "input_reference_sha256": sha256_file(INPUT_REFERENCE),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError("EXTERNAL_V26_PREPARED_" + key.upper() + "_CHANGED")
    return expected["lock_sha256"]
