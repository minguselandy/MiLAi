"""Prepare declared development histories through the existing Store operations.

These are evaluator-side fixture operations, not a policy, a learned Writer or
an oracle view. Their actual receipts and cost remain separate from Host tasks.
"""
from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import write_json
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.functional_edit_memory import FunctionalEditMemory
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.memory_control import FixedMemoryPolicy
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.functional import _bank_reference, frozen, seed_sources


def prepare_history_bank(
    root: Path, *, bank: str, owner: str, history: dict[str, Any],
    source_progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """One fresh bank; version history comes from actual save/update receipts."""
    started, cpu = time.perf_counter(), time.process_time()
    freeze = frozen(root)
    settings = freeze["config"]
    bank_id = _bank_reference(root, freeze["run_id"], bank, owner)
    directory = root / "banks" / bank_id
    directory.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema": "retrieval_history_setup_v1", "bank": bank,
        "source_group": history["source_group"], "revisions": [], "prefetch": None,
        "model_calls": 0, "writer": "scripted fixture operations, not model output"}
    with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
        service = MemoryService(store, ("functional", freeze["run_id"], bank, owner), owner,
            directory / "memory.lock", functional_contract="functional_v1",
            memory_profile=settings.get("memory_profile", "ordinary"),
            memory_ranking=settings.get("memory_ranking", "dense"))
        sources = seed_sources(service, history["sources"], directory / "source-imports.json",
                               preserve_occurrence=True, progress=source_progress)
        report["sources"] = sources
        if history.get("stored_revisions") or history.get("prefetch"):
            capacity = HostCapacity(settings["capacity"])
            writer = FunctionalEditMemory(service, capacity.text_tokens, interface_version="I2",
                material_limit=settings["ordinary_material_tokens"],
                source_access="independent_v1", source_tokenization="unicode_v1")
            records: dict[str, str] = {}
            original_refs = {row["original_event_id"]: row["receipt"]["source_ref"]
                             for row in sources}
            for number, revision in enumerate(history.get("stored_revisions", [])):
                source = service.source(original_refs[revision["source_event_id"]])
                assert source is not None
                writer.context(source["session"], source["capture_key"], freeze["config_version"])
                cfg = cast(RunnableConfig, {"configurable": {"user_id": owner,
                    "v13_session": source["session"], "v13_turn_id": source["capture_key"],
                    "v13_config_version": freeze["config_version"]}})
                evidence = [row["fragment_handle"]
                            for row in service.source_fragments(source["event_id"])]
                name = revision["record"]
                if name not in records:
                    receipt = writer.save_edit(cfg, f"setup-save-{number}", units=[{
                        "text": revision["text"], "role": "content", "evidence": evidence}],
                        scope=revision.get("scope"))
                    if receipt["ok"]:
                        records[name] = receipt["id"]
                else:
                    current = service.read(records[name])
                    unit = current["value"]["edit_state"]["units"][0]["unit_id"]
                    receipt = writer.update_edit(cfg, f"setup-update-{number}",
                        current["candidate_handle"], [{"operation": "replace", "target_unit": unit,
                            "text": revision["text"], "evidence": evidence}])
                report["revisions"].append(receipt)
                write_json(directory / "retrieval-setup.json", report)
                if not receipt["ok"]:
                    raise ValueError("Declared fixture storage operation failed: " + str(receipt))
            if history.get("prefetch"):
                request = RetrievalRequest.model_validate(history["prefetch"])
                source = service.capture_user("setup-prefetch", "request", request.query)
                service.bind_public_turn("setup-prefetch", "request", source["source_ref"],
                    config_version=freeze["config_version"], phase="start")
                cfg = cast(RunnableConfig, {"configurable": {"user_id": owner,
                    "v13_session": "setup-prefetch", "v13_turn_id": "request",
                    "v13_config_version": freeze["config_version"]}})
                reader = IntentRetrievalMemory(service, capacity.text_tokens,
                    material_limit=settings["ordinary_material_tokens"], read_limit=3,
                    source_access="independent_v1", source_tokenization="unicode_v1",
                    control_policy=FixedMemoryPolicy(reads=1), control_steps=3,
                    control_record=lambda event: report.setdefault("prefetch_trace", []).append(
                        copy.deepcopy(event)))
                report["prefetch"] = reader.retrieve(cfg, "setup-read", request)
        report["stored_records"] = service.records()
    report["compute"] = {"wall_seconds": time.perf_counter() - started,
                         "cpu_seconds": time.process_time() - cpu}
    write_json(directory / "retrieval-setup.json", report)
    return report


def host_task_content(request: dict[str, Any], setup: dict[str, Any]) -> str:
    """Only the public task and an explicitly supplied actual prior tool receipt."""
    content = str(request["content"])
    if request.get("provide_prefetch"):
        content += ("\n\nContext already delivered to you by MiLAi in this bank "
                    "(an actual tool receipt, not a coverage judgment):\n"
                    + json.dumps(setup["prefetch"], ensure_ascii=False))
    return content
