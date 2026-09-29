"""Foundation-owned identity gates bind the canonical request implementation."""

from __future__ import annotations

import hashlib
import importlib
import json
import uuid
from pathlib import Path

import pytest
from langgraph.store.memory import InMemoryStore

from milai_lab.application import APPLICATION_SOURCE_FILES
from milai_lab.baselines import langmem_b1_identity, langmem_identity
from milai_lab.baselines.langmem_agent import create_memory_read_tool
from milai_lab.baselines.langmem_strict_tools import _invalid_receipt, _receipt
from milai_lab.contracts.memory import MemoryMutationReceipt, MemoryReadResult, MemoryRecord
from milai_lab.harness.source_identity import REQUEST_SOURCE_FILES
from milai_lab.methods.freshness_projection import identity as freshness
from milai_lab.methods.milai_m1 import identity as m1
from milai_lab.methods.on_demand_reconstruction import identity as odr

LAB = Path(__file__).resolve().parents[2]


def test_current_identity_gates_register_canonical_request_sources() -> None:
    required = set(REQUEST_SOURCE_FILES)
    assert required <= langmem_b1_identity.REQUIRED_OVERLAY
    assert required <= m1.REQUIRED_RUNTIME
    assert required <= odr.REQUIRED_RUNTIME
    assert required <= freshness.REQUIRED_RUNTIME
    assert required <= freshness.REQUIRED_APPLICATION_V25_RUNTIME


def test_development_identity_rejects_canonical_request_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(LAB / "tools"))
    entry = importlib.import_module("run_langmem_foundation")
    config = tmp_path / "config.json"
    config.write_text("{}")
    settings = {"checkpoint_path": str(tmp_path / "checkpoints.sqlite")}
    entry._verify_development_spike(config, settings, "request-architecture")
    receipt = json.loads(next(tmp_path.glob("spike-identity-*.json")).read_text())
    assert set(REQUEST_SOURCE_FILES) <= receipt["source_sha256"].keys()
    original_sha = entry.sha256_file
    monkeypatch.setattr(entry, "sha256_file", lambda path: (
        "0" * 64 if path == LAB / "src/milai_lab/memory/presentation.py"
        else original_sha(path)))
    with pytest.raises(ValueError, match="DEVELOPMENT_SPIKE_IDENTITY_CHANGED"):
        entry._verify_development_spike(config, settings, "request-architecture")


@pytest.mark.parametrize("relative", [
    "src/milai_lab/analysis/trace_accounting.py",
    "src/milai_lab/runners/writer_policy.py",
    "src/milai_lab/contracts/request.py",
    "src/milai_lab/contracts/benchmark.py",
    "src/milai_lab/contracts/scope.py",
    "src/milai_lab/memory/mcp.py",
    "src/milai_lab/memory/read_tools.py",
    "src/milai_lab/memory/revision_store.py",
    "src/milai_lab/memory/strict_tools.py",
    "src/milai_lab/memory/embeddings.py",
    "src/milai_lab/providers/chat_bridge.py",
    "src/milai_lab/providers/request_pipeline.py",
    "src/milai_lab/methods/langmem_recipe.py",
    "src/milai_lab/integrations/memory/mem0.py",
    "src/milai_lab/integrations/memory/simplemem.py",
    "src/milai_lab/harness/artifact_io.py",
    "src/milai_lab/harness/benchmark_execution.py",
])
def test_foundation_gate_rejects_missing_and_changed_request_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str,
) -> None:
    monkeypatch.setattr(langmem_identity, "LAB", tmp_path)
    registered = (*APPLICATION_SOURCE_FILES, *REQUEST_SOURCE_FILES)
    for registered_relative in ("uv.lock", "pyproject.toml", "upstream.json", *registered):
        path = tmp_path / registered_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source identity\n")
    sha = langmem_identity.sha256_file
    lock = {
        "status": "FROZEN", "upstream_manifest": "upstream.json",
        "uv_lock_sha256": sha(tmp_path / "uv.lock"),
        "pyproject_sha256": sha(tmp_path / "pyproject.toml"),
        "upstream_manifest_sha256": sha(tmp_path / "upstream.json"),
        "recipe_id": langmem_identity.RECIPE_ID, "transport_variant": "json_action",
        "generation_schema_variant": "free_order_arguments_v1",
        "system_prompt": langmem_identity.SYSTEM_PROMPT,
        "system_prompt_sha256": hashlib.sha256(langmem_identity.SYSTEM_PROMPT.encode()).hexdigest(),
        "namespace": list(langmem_identity.MEMORY_NAMESPACE),
        "source_sha256": {relative: sha(tmp_path / relative)
                          for relative in APPLICATION_SOURCE_FILES},
    }
    lock_path, config_path = tmp_path / "new-lock.json", tmp_path / "config.json"
    lock_path.write_text(json.dumps(lock))
    config_path.write_text("{}")
    with pytest.raises(ValueError, match="FOUNDATION_REQUEST_SOURCE_MAP_MISSING"):
        langmem_identity.verify_foundation_lock(lock_path, config_path)
    lock["source_sha256"] = {relative: sha(tmp_path / relative) for relative in registered}
    omitted = lock["source_sha256"].pop(relative)
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match="FOUNDATION_REQUEST_SOURCE_MAP_MISSING"):
        langmem_identity.verify_foundation_lock(lock_path, config_path)
    lock["source_sha256"][relative] = omitted
    lock_path.write_text(json.dumps(lock))
    (tmp_path / relative).write_text("changed implementation\n")
    with pytest.raises(ValueError, match="FOUNDATION_SOURCE_CHANGED:" + relative):
        langmem_identity.verify_foundation_lock(lock_path, config_path)


def test_memory_dtos_describe_actual_receipts_without_changing_unknown_fields() -> None:
    memory_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    value = {"content": "synthetic stored material", "unknown": {"retain": True}}
    record: MemoryRecord = {"id": str(memory_id), "value": value}
    namespace = ("langmem", "synthetic-run", "synthetic-arm", "synthetic-owner")
    store = InMemoryStore()
    store.put(namespace, record["id"], record["value"])
    read = create_memory_read_tool(namespace, store)
    found: MemoryReadResult = json.loads(read.invoke({
        "type": "tool_call", "id": "read-found", "name": "read_memory",
        "args": {"id": record["id"]},
    }).content)
    assert found == {"ok": True, "status": "found", **record}
    store.delete(namespace, record["id"])
    missing: MemoryReadResult = json.loads(read.invoke({
        "type": "tool_call", "id": "read-missing", "name": "read_memory",
        "args": {"id": record["id"]},
    }).content)
    assert missing == {"ok": False, "status": "not_found", "id": record["id"]}
    mutation: MemoryMutationReceipt = json.loads(_receipt(
        "synthetic-mutation", "no_change", memory_id, ok=True).content)
    assert mutation == {"ok": True, "status": "no_change", "id": record["id"]}
    invalid: MemoryMutationReceipt = json.loads(_invalid_receipt(
        "synthetic-invalid", "target_id_required").content)
    assert invalid == {"ok": False, "status": "invalid_arguments", "reason": "target_id_required"}
