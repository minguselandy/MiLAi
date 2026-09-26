"""Zero-model fixed-vector PostgresStore check in a unique Lab namespace."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.postgres import PostgresStore

from milai_lab.baselines.langmem_agent import FoundationScope, build_agent, invoke_public_message
from milai_lab.baselines.langmem_instrumentation import ProvenanceObserver
from milai_lab.baselines.langmem_revision_store import ObservedStore, RevisionSidecar
from milai_lab.harness.contextual_artifacts import write_json
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.langmem_chat import VLLMChatModel


class FixedEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1023


def _receipt(action: dict[str, Any], identity: str) -> dict[str, Any]:
    return {"id": identity, "model": "fixed-mock", "choices": [{
        "finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(action),
        }}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    dsn = os.environ["MILAI_LANGMEM_POSTGRES_DSN"]
    run_id = "v16-v0-pg-" + uuid.uuid4().hex
    memory_id = str(uuid.uuid4())
    responses = [
        _receipt({"calls": [{"name": "manage_memory", "arguments": {
            "action": "update", "id": memory_id, "content": "ramen"}}]}, "fixed-g1"),
        _receipt({"calls": [{"name": "search_memory", "arguments": {
            "query": "food", "limit": 1}}, {"name": "manage_memory", "arguments": {
            "action": "update", "id": memory_id, "content": "soba"}}]}, "fixed-g2"),
        _receipt({"answer": "Done."}, "fixed-g3"),
    ]
    sent: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.read()))
        return httpx.Response(200, json=responses.pop(0))

    sidecar = RevisionSidecar(args.sidecar)
    observer = ProvenanceObserver(sidecar, run_id, "b1_instrumented")
    namespace = ("langmem", run_id, "b1_instrumented", "v0-user")
    try:
        with PostgresStore.from_conn_string(
            dsn, index={"dims": 1024, "embed": FixedEmbeddings(),
                        "fields": ["content"]},
        ) as base_store:
            base_store.setup()
            store = ObservedStore(base_store, observer)
            with TemporaryDirectory() as temporary:
                with SqliteSaver.from_conn_string(
                    str(Path(temporary) / "checkpoint.sqlite"),
                ) as saver:
                    with VLLMClient(
                        VLLMConfig(base_url="http://fixed-mock/v1/", model="fixed-mock"),
                        transport=httpx.MockTransport(respond),
                        emit=observer.capture_provider_event,
                    ) as client:
                        model = VLLMChatModel(client=client, observer=observer)
                        messages = invoke_public_message(
                            build_agent(model, store, saver, observer=observer), model,
                            FoundationScope(run_id, "b1_instrumented", "v0-user", "v0-episode"),
                            "Remember food.",
                        )
            observer.assert_healthy()
            revisions = sidecar.rows("revisions")
            search = sidecar.rows("searches")[0]
            returned = json.loads(search["returned_json"])
            actual = base_store.get(namespace, memory_id)
            assert [row["revision"] for row in revisions] == [1, 2]
            assert [row["actual_effect"] for row in revisions] == ["insert", "update"]
            assert returned[0]["revision"] == 1
            assert actual is not None and actual.value == {"content": "soba"}
            assert messages[-1].content == "Done."
            assert len(sent) == 3
            result = {
                "status": "PASS_ZERO_MODEL_FIXED_VECTOR",
                "run_id": run_id, "namespace": namespace, "memory_id": memory_id,
                "revisions": [row["revision"] for row in revisions],
                "search_return_revision": returned[0]["revision"],
                "search_score": returned[0]["score"],
                "provider_requests": len(sent),
                "sidecar_cost": sidecar.costs(),
            }
            write_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False))
    finally:
        sidecar.close()


if __name__ == "__main__":
    main()
