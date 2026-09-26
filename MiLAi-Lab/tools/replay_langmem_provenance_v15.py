"""Replay sealed v15 MERIT receipts through original tools in both v16 paths."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import langgraph.store.memory as memory_module
import langmem.knowledge.tools as langmem_tools  # type: ignore[import-untyped]
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore

from milai_lab.baselines.langmem_agent import VLLMEmbeddings
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.harness.contextual_artifacts import write_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel
from milai_lab.runners.langmem_merit import run_exposed_merit_arc

LAB = Path(__file__).resolve().parents[1]
TRACE = LAB / "artifacts/langmem-foundation/final-merit-r2/trace.jsonl"
ORIGINAL_RESULTS = LAB / "artifacts/langmem-foundation/final-merit-r2/results"
SELECTION = LAB / "data/manifests/contextual-memory-v7-e0-selection-final.json"
ORIGINAL_CONFIG = LAB / "artifacts/langmem-foundation/final-merit-r2/config.json"


def _sealed_events() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [json.loads(line) for line in TRACE.read_text().splitlines()]
    complete = [row for row in rows if row.get("event") == "vllm_response"]
    return ([row for row in complete if row["path"] == "chat/completions"],
            [row for row in complete if row["path"] == "embeddings"])


def _created_ids() -> list[uuid.UUID]:
    result = []
    for index in range(5):
        row = json.loads((ORIGINAL_RESULTS / "episodes" / f"episode-{index}.json").read_text())
        for message in row["messages"]:
            if message["type"] == "tool" and message.get("name") == "manage_memory":
                content = message["content"]
                if content.startswith("created memory "):
                    result.append(uuid.UUID(content.removeprefix("created memory ")))
    return result


def _run_once(output: Path, instrumented: bool) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    next_id = count(1)
    uuid.uuid4 = lambda: uuid.UUID(int=next(next_id))
    host_rows, embed_rows = _sealed_events()
    host_pending, embed_pending = list(host_rows), list(embed_rows)
    host_requests: list[dict[str, Any]] = []
    embed_requests: list[dict[str, Any]] = []
    host_wire: list[str] = []
    embed_wire: list[str] = []
    original_uuids = iter(_created_ids())
    langmem_tools.uuid = SimpleNamespace(UUID=uuid.UUID, uuid4=lambda: next(original_uuids))

    def host_reply(request: httpx.Request) -> httpx.Response:
        raw = request.read()
        host_wire.append(raw.decode("utf-8"))
        host_requests.append(json.loads(raw))
        return httpx.Response(200, json=host_pending.pop(0)["receipt"])

    def embed_reply(request: httpx.Request) -> httpx.Response:
        raw = request.read()
        embed_wire.append(raw.decode("utf-8"))
        embed_requests.append(json.loads(raw))
        return httpx.Response(200, json=embed_pending.pop(0)["receipt"])

    config = json.loads(ORIGINAL_CONFIG.read_text())
    sidecar = RevisionSidecar(output / "instrumentation.sqlite") if instrumented else None
    observer = (ProvenanceObserver(sidecar, "v15-b0-merit-r2", "b0")
                if sidecar is not None else None)
    host_events: list[dict[str, Any]] = []
    embed_events: list[dict[str, Any]] = []

    def emit_host(event: dict[str, Any]) -> None:
        host_events.append(event)
        if observer is not None:
            observer.capture_provider_event(event)

    with VLLMClient(VLLMConfig(**config["host"]),
                    emit=emit_host, transport=httpx.MockTransport(host_reply)) as host:
        with VLLMClient(VLLMConfig(
            base_url=config["embedding"]["base_url"],
            model=config["embedding"]["model"],
            timeout=config["embedding"].get("timeout", 180),
        ), emit=embed_events.append,
            transport=httpx.MockTransport(embed_reply)) as embed:
            base_store = InMemoryStore(index={
                "dims": 1024, "embed": VLLMEmbeddings(embed, config["embedding"]["model"]),
                "fields": ["content"],
            })
            store = ObservedStore(base_store, observer) if observer else base_store
            with SqliteSaver.from_conn_string(str(output / "checkpoint.sqlite")) as saver:
                result = run_exposed_merit_arc(
                    SELECTION, output / "results", "v15-b0-merit-r2", VLLMChatModel(
                        client=host, capacity_path=output / "capacity.json", observer=observer,
                    ), store, saver, {"v0_source": "v15_final_merit_r2"},
                    observer=observer,
                )
    if observer is not None:
        observer.assert_healthy()
    if host_pending or embed_pending:
        raise ValueError("V15_REPLAY_RECEIPTS_NOT_EXHAUSTED")
    evidence = {
        "result": result,
        "host_requests": host_requests,
        "embedding_requests": embed_requests,
        "host_wire_utf8": host_wire,
        "embedding_wire_utf8": embed_wire,
        "host_statuses": [row["event"] for row in host_events],
        "embedding_statuses": [row["event"] for row in embed_events],
        "episodes": [json.loads((output / "results" / "episodes" /
                                f"episode-{index}.json").read_text())
                     for index in range(5)],
        "sidecar_counts": ({table: len(sidecar.rows(table)) for table in (
            "observations", "revisions", "searches", "tool_calls", "requests",
            "request_material")}
                           if sidecar is not None else None),
        "sidecar_cost": sidecar.costs() if sidecar is not None else None,
    }
    if sidecar is not None:
        sidecar.close()
    write_json(output / "evidence.json", evidence)
    return evidence


def _difference(control: dict[str, Any], instrumented: dict[str, Any]) -> dict[str, Any]:
    fields = ("result", "host_requests", "embedding_requests", "host_wire_utf8",
              "embedding_wire_utf8", "host_statuses", "embedding_statuses", "episodes")
    return {field: control[field] != instrumented[field] for field in fields}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FixedDateTime:
            return cls(2026, 9, 26, tzinfo=tz)

    memory_module.datetime = FixedDateTime  # type: ignore[attr-defined]
    control = _run_once(args.output / "control", False)
    instrumented = _run_once(args.output / "instrumented", True)
    differences = _difference(control, instrumented)
    report = {
        "status": "PASS" if not any(differences.values()) else "MODEL_VISIBLE_PARITY_MISMATCH",
        "source": {"trace": str(TRACE), "selection": str(SELECTION),
                   "native_world": "pinned MERIT arc.make_world()"},
        "receipts": {"generation": len(control["host_requests"]),
                     "embedding": len(control["embedding_requests"])},
        "differences": differences,
        "sidecar_counts": instrumented["sidecar_counts"],
        "sidecar_cost": instrumented["sidecar_cost"],
    }
    write_json(args.output / "report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
