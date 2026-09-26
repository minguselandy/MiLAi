"""One offline identity gate for the frozen LangMem foundation recipe."""

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
from milai_lab.harness.contextual_artifacts import digest, read_json
from milai_lab.providers.langmem_chat import _action_prompt, _action_schema

LAB = Path(__file__).resolve().parents[3]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_foundation_lock(
    lock_path: Path, config_path: Path, *, require_frozen: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind source, upstream tools, recipe, and local endpoints before opening state."""
    lock = read_json(lock_path)
    config = read_json(config_path)
    if require_frozen and lock["status"] != "FROZEN":
        raise ValueError("FOUNDATION_LOCK_NOT_FROZEN")
    expected: dict[str, Any] = {
        "uv_lock_sha256": sha256_file(LAB / "uv.lock"),
        "pyproject_sha256": sha256_file(LAB / "pyproject.toml"),
        "upstream_manifest_sha256": sha256_file(LAB / lock["upstream_manifest"]),
        "recipe_id": RECIPE_ID,
        "transport_variant": "json_action",
        "generation_schema_variant": "free_order_arguments_v1",
        "system_prompt": SYSTEM_PROMPT,
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "namespace": list(MEMORY_NAMESPACE),
    }
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError(f"FOUNDATION_LOCK_{key.upper()}_CHANGED")
    for relative, value in lock["source_sha256"].items():
        if sha256_file(LAB / relative) != value:
            raise ValueError(f"FOUNDATION_SOURCE_CHANGED:{relative}")

    tools = [
        convert_to_openai_tool(create_manage_memory_tool(namespace=MEMORY_NAMESPACE)),
        convert_to_openai_tool(create_search_memory_tool(namespace=MEMORY_NAMESPACE)),
    ]
    tool_identity = {
        "memory_tools": tools,
        "memory_tools_sha256": digest(tools),
        "json_action_schema_memory_only_sha256": digest(
            _action_schema(tools, generation_only=True)
        ),
        "json_action_prompt_memory_only_sha256": hashlib.sha256(
            _action_prompt(tools).encode()
        ).hexdigest(),
    }
    for key, value in tool_identity.items():
        if lock.get(key) != value:
            raise ValueError(f"FOUNDATION_LOCK_{key.upper()}_CHANGED")

    host = config["host"]
    embedding = config["embedding"]
    if (config["recipe_id"] != RECIPE_ID
            or config["transport_variant"] != "json_action"
            or host["tool_mode"] != "json_action"
            or host["model"] != lock["model_identity"]["host"]["served_model"]
            or host["max_tokens"] != lock["capacity"]["output_tokens"]
            or host["max_calls"] != lock["factory"]["max_model_attempts_per_public_message"]
            or host["enable_thinking"] is not False
            or embedding["model"] != lock["model_identity"]["embedding"]["served_model"]
            or config["embedding_dimension"] != lock["long_term_store"]["index"]["dims"]
            or config["capacity"] | {"tokenizer_path": ""}
            != lock["capacity"] | {"tokenizer_path": ""}):
        raise ValueError("FOUNDATION_CONFIG_RECIPE_CHANGED")
    return lock, config


def verify_prepared_run(
    receipt_path: Path,
    lock_path: Path,
    config_path: Path,
    *,
    merit_selection: Path | None = None,
    diagnostic_inputs: Path | None = None,
) -> str:
    """Reject resumed checkpoints whose frozen source or public inputs changed."""
    verify_foundation_lock(lock_path, config_path)
    receipt = read_json(receipt_path)
    expected = {
        "status": "PREPARED_ZERO_MODEL",
        "recipe_id": RECIPE_ID,
        "lock_sha256": sha256_file(lock_path),
        "config_sha256": sha256_file(config_path),
    }
    if merit_selection is not None:
        expected["merit_selection_sha256"] = sha256_file(merit_selection)
    if diagnostic_inputs is not None:
        expected["diagnostic_inputs_sha256"] = sha256_file(diagnostic_inputs)
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"FOUNDATION_PREPARED_{key.upper()}_CHANGED")
    return expected["lock_sha256"]
