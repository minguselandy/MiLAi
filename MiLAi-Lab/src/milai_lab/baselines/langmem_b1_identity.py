"""Frozen source and input identity for the v16 model-hidden experiment."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool
from langmem import (  # type: ignore[import-untyped]
    create_manage_memory_tool,
    create_search_memory_tool,
)

from milai_lab.baselines.langmem_agent import MEMORY_NAMESPACE, RECIPE_ID, SYSTEM_PROMPT
from milai_lab.baselines.langmem_identity import sha256_file
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.providers.langmem_chat import _action_prompt, _action_schema

LAB = Path(__file__).resolve().parents[3]
REFERENCE = LAB / "data/manifests/langmem-b1-v16-reference.json"
FOUNDATION_LOCK = LAB / "data/locks/langmem-foundation.lock.json"
INSTRUMENTATION_VERSION = "b1-sidecar-v1"
ARMS = ("b0_control", "b1_instrumented")
REQUIRED_OVERLAY = {
    "configs/langmem-b1-v16.json",
    "pyproject.toml",
    "uv.lock",
    "src/milai_lab/baselines/langmem_agent.py",
    "src/milai_lab/baselines/langmem_b1_identity.py",
    "src/milai_lab/baselines/langmem_instrumentation.py",
    "src/milai_lab/baselines/langmem_revision_store.py",
    "src/milai_lab/providers/langmem_chat.py",
    "src/milai_lab/runners/langmem_foundation.py",
    "src/milai_lab/runners/langmem_diagnostic.py",
    "src/milai_lab/runners/langmem_merit.py",
    "tools/run_langmem_provenance.py",
}


def verify_b1_lock(lock_path: Path, config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, config = read_json(lock_path), read_json(config_path)
    reference, foundation = read_json(REFERENCE), read_json(FOUNDATION_LOCK)
    expected = {
        "kind": "LANGMEM_B1_V16_LOCK",
        "status": "FROZEN",
        "instrumentation_version": INSTRUMENTATION_VERSION,
        "arms": list(ARMS),
        "reference_manifest_sha256": sha256_file(REFERENCE),
        "reference_foundation_lock_sha256": sha256_file(FOUNDATION_LOCK),
        "model_visible_contract": reference["model_visible_contract"],
    }
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError(f"B1_LOCK_{key.upper()}_CHANGED")
    if (reference["reference_foundation_lock_sha256"]
            != expected["reference_foundation_lock_sha256"]):
        raise ValueError("B1_REFERENCE_FOUNDATION_LOCK_CHANGED")
    source_map = lock.get("source_sha256")
    if not isinstance(source_map, dict) or not REQUIRED_OVERLAY <= source_map.keys():
        raise ValueError("B1_SOURCE_MAP_MISSING")
    for relative, sha in source_map.items():
        if sha256_file(LAB / relative) != sha:
            raise ValueError(f"B1_SOURCE_CHANGED:{relative}")
    for relative, sha in foundation["source_sha256"].items():
        if relative not in source_map and sha256_file(LAB / relative) != sha:
            raise ValueError(f"B1_REFERENCE_SOURCE_CHANGED:{relative}")
    tools = [
        convert_to_openai_tool(create_manage_memory_tool(namespace=MEMORY_NAMESPACE)),
        convert_to_openai_tool(create_search_memory_tool(namespace=MEMORY_NAMESPACE)),
    ]
    visible = {
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "memory_tools_sha256": digest(tools),
        "json_action_schema_memory_only_sha256": digest(
            _action_schema(tools, generation_only=True)),
        "json_action_prompt_memory_only_sha256": hashlib.sha256(
            _action_prompt(tools).encode()).hexdigest(),
        "namespace": list(MEMORY_NAMESPACE),
    }
    for key, value in visible.items():
        if reference["model_visible_contract"][key] != value:
            raise ValueError(f"B1_MODEL_VISIBLE_{key.upper()}_CHANGED")
    host, embedding = config["host"], config["embedding"]
    if (config["recipe_id"] != RECIPE_ID
            or config["transport_variant"] != "json_action"
            or host["tool_mode"] != "json_action"
            or host["model"] != foundation["model_identity"]["host"]["served_model"]
            or host["temperature"] != 0
            or host["max_tokens"] != foundation["capacity"]["output_tokens"]
            or host["max_calls"] != foundation["factory"]["max_model_attempts_per_public_message"]
            or host["enable_thinking"] is not False
            or embedding["model"] != foundation["model_identity"]["embedding"]["served_model"]
            or config["embedding_dimension"] != foundation["long_term_store"]["index"]["dims"]
            or config["capacity"] | {"tokenizer_path": ""}
            != foundation["capacity"] | {"tokenizer_path": ""}):
        raise ValueError("B1_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_b1_prepared(
    receipt_path: Path, lock_path: Path, config_path: Path,
    *, arm_id: str, run_id: str, merit_selection: Path | None = None,
    diagnostic_inputs: Path | None = None,
    diagnostic_freeze: Path | None = None,
) -> str:
    verify_b1_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {
        "status": "PREPARED_ZERO_MODEL",
        "instrumentation_version": INSTRUMENTATION_VERSION,
        "arm_id": arm_id, "run_id": run_id,
        "lock_sha256": sha256_file(lock_path),
        "config_sha256": sha256_file(config_path),
    }
    if merit_selection is not None:
        expected["merit_selection_sha256"] = sha256_file(merit_selection)
    if diagnostic_inputs is not None:
        expected["diagnostic_inputs_sha256"] = sha256_file(diagnostic_inputs)
    if diagnostic_freeze is not None:
        expected["diagnostic_freeze_sha256"] = sha256_file(diagnostic_freeze)
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"B1_PREPARED_{key.upper()}_CHANGED")
    return expected["lock_sha256"]
