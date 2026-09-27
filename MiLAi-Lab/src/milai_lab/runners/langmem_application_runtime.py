"""Open the ordinary LangMem runtime for one application phase process."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from milai_lab.baselines.langmem_agent import VLLMEmbeddings, open_persistent_state
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, Trace
from milai_lab.methods.freshness_projection.controller import ProjectionController
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel


@dataclass
class ApplicationRuntime:
    model: VLLMChatModel
    store: BaseStore
    checkpointer: BaseCheckpointSaver[str]
    observer: ProvenanceObserver


def projection_for_arm(observer: ProvenanceObserver, emit: Any, store: ObservedStore,
                       arm_id: str, config: dict[str, Any]) -> ProjectionController | None:
    if arm_id == "b1_control":
        return None
    policy = config["refresh_policy"] if arm_id == "a5_rank_bounded_rebase" else {
        "refresh_until_current_candidate": False,
        "max_exact_refresh_per_search": None,
    }
    return ProjectionController(observer, emit, arm=arm_id, store=store,
                                stage="v21", **policy)


@contextmanager
def open_application_runtime(config: dict[str, Any], run_id: str, arm_id: str,
                             root: Path, stage: str) -> Iterator[ApplicationRuntime]:
    root.mkdir(parents=True, exist_ok=True)
    budget = RunBudget(RunLimits(questions=12, arms=3, generation_requests=None,
                                 generation_tokens=None, embedding_tokens=None),
                       Path(config["budget_path"]))
    trace = Trace(root / "trace.jsonl", stage)
    sidecar = RevisionSidecar(root / "instrumentation.sqlite")
    observer = ProvenanceObserver(sidecar, run_id, arm_id)

    def emit(event: dict[str, Any]) -> None:
        offset = trace.path.stat().st_size if trace.path.exists() else 0
        trace(event)
        record = json.dumps({"stage": trace.stage, **event}, ensure_ascii=False) + "\n"
        observer.capture_provider_event(event, {
            "path": str(trace.path.resolve()), "byte_offset": offset,
            "record_sha256": hashlib.sha256(record.encode("utf-8")).hexdigest(),
        })

    host_config = VLLMConfig(**config["host"])
    embed_config = VLLMConfig(base_url=config["embedding"]["base_url"],
                              model=config["embedding"]["model"],
                              timeout=config["embedding"].get("timeout", 180))
    try:
        observer.assert_healthy()
        with VLLMClient(host_config, emit=emit, budget=budget,
                        capacity=HostCapacity(config["capacity"])) as host:
            with VLLMClient(embed_config, emit=trace, budget=budget) as embed:
                embeddings = VLLMEmbeddings(embed, embed_config.model)
                with open_persistent_state(
                    os.environ["MILAI_LANGMEM_POSTGRES_DSN"],
                    root / "checkpoints.sqlite", embeddings,
                    embedding_dimensions=config["embedding_dimension"],
                ) as (base_store, saver):
                    store = ObservedStore(base_store, observer)
                    projection = projection_for_arm(observer, emit, store, arm_id, config)
                    model = VLLMChatModel(
                        client=host, capacity_path=root / "message-capacity.json",
                        observer=observer, projection=projection)
                    yield ApplicationRuntime(model, store, saver, observer)
    finally:
        sidecar.close()
