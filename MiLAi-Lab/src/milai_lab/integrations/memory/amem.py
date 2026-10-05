"""Thin callback adapter for the pinned author's original JSON-schema A-MEM.

The three author class bodies are compiled unchanged, without importing their
provider/model module. The caller owns all generation/embedding HTTP and usage.
Adaptations: missing ``re`` namespace import, injected model/controller factories,
NumPy cosine in place of sklearn, caller sampling/embedding model, JSON persistence.
This is an adapted author algorithm, not reproduction of its original environment.
"""

from __future__ import annotations

import ast
import json
import os
import pickle
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np

SOURCE_COMMIT = "0c8039f28fdcc08189a23c07a3437d9d2482f9c2"
ADAPTER_VERSION = "amem_author_callbacks_v1"
AUTHOR_CLASSES = ("MemoryNote", "SimpleEmbeddingRetriever", "AgenticMemorySystem")


def _cosine(left: Any, right: Any) -> Any:
    """The standard row-normalized dot product used by cosine_similarity."""
    a, b = np.asarray(left, dtype=np.float32), np.asarray(right, dtype=np.float32)
    a = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), np.finfo(np.float32).eps)
    b = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), np.finfo(np.float32).eps)
    return a @ b.T


def _author_classes(
    source: Path,
    controller: type[Any],
    model: type[Any],
    log: Callable[..., None],
) -> dict[str, Any]:
    git = shutil.which("git")
    if git is None:
        raise ValueError("AMEM_GIT_UNAVAILABLE")
    commit = subprocess.check_output(  # noqa: S603
        [git, "-C", str(source), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    if commit != SOURCE_COMMIT:
        raise ValueError("AMEM_AUTHOR_COMMIT_CHANGED")
    clean = subprocess.run(  # noqa: S603
        [git, "-C", str(source), "diff", "--quiet", SOURCE_COMMIT, "--", "memory_layer.py"],
        check=False,
    )
    if clean.returncode:
        raise ValueError("AMEM_AUTHOR_SOURCE_CHANGED")
    path = source / "memory_layer.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in AUTHOR_CLASSES
    ]
    if tuple(node.name for node in classes) != AUTHOR_CLASSES:
        raise ValueError("AMEM_AUTHOR_CLASSES_CHANGED")
    namespace: dict[str, Any] = {
        "__name__": "milai_amem_author",
        "__file__": str(path),
        "List": list,
        "Dict": dict,
        "Optional": __import__("typing").Optional,
        "LLMController": controller,
        "SentenceTransformer": model,
        "json": json,
        "datetime": datetime,
        "uuid": uuid,
        "re": re,
        "np": np,
        "cosine_similarity": _cosine,
        "os": os,
        "pickle": pickle,
        "print": log,
    }
    # Select original AST nodes; no method, prompt, parser, ranking, or evolution rewrite.
    selected: list[ast.stmt] = list(classes)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return {name: namespace[name] for name in AUTHOR_CLASSES}


class AMemRuntime:
    """Serial occurred-source ingestion and author retrieval, with ordinary saved state."""

    def __init__(
        self,
        source: str | Path,
        root: str | Path,
        *,
        owner: str,
        completion: Callable[[str, dict[str, Any]], str],
        embedding: Any,
        embedding_model: str = "bge-m3",
        evo_threshold: int = 100,
    ) -> None:
        if not owner or not embedding_model or type(evo_threshold) is not int or evo_threshold < 1:
            raise ValueError("AMEM_SCOPE_INVALID")
        self.root, self.owner = Path(root), owner
        self.path = self.root / "state.json"
        self.binding = {
            "owner": owner,
            "author_commit": SOURCE_COMMIT,
            "author_file": "memory_layer.py",
            "adapter_version": ADAPTER_VERSION,
            "embedding_model": embedding_model,
            "evo_threshold": evo_threshold,
            "sampling": "completion_callback_owned",
        }
        self.events: list[dict[str, Any]] = []
        self.ingestions: dict[str, dict[str, Any]] = {}
        self.blocked: str | None = None
        self.active_source: str | None = None
        self._completion, self._embedding = completion, embedding
        outer = self

        class Completion:
            def get_completion(
                self,
                prompt: str,
                response_format: dict[str, Any],
                temperature: float = 0.7,
            ) -> str:
                schema = response_format["json_schema"]["schema"]
                value = outer._invoke("completion", lambda: outer._completion(prompt, schema))
                if not isinstance(value, str):
                    raise ValueError("AMEM_COMPLETION_TEXT_REQUIRED")
                return value

        class Controller:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.llm = Completion()

        class Model:
            def __init__(self, model_name: str) -> None:
                self.model_name = embedding_model

            def get_config_dict(self) -> dict[str, str]:
                return {"model_name": self.model_name}

            def encode(self, texts: list[str]) -> Any:
                def encoded() -> Any:
                    values = np.asarray(outer._embedding.encode(texts), dtype=np.float32)
                    if (
                        values.ndim != 2
                        or values.shape[0] != len(texts)
                        or values.shape[1] == 0
                        or not np.isfinite(values).all()
                        or (np.linalg.norm(values, axis=1) == 0).any()
                    ):
                        raise ValueError("AMEM_EMBEDDING_INVALID")
                    return values

                return outer._invoke("embedding", encoded, rows=len(texts))

        self.classes = _author_classes(Path(source), Controller, Model, self._author_log)
        self.system = self.classes["AgenticMemorySystem"](
            model_name=embedding_model,
            llm_backend="callback",
            llm_model="callback",
            evo_threshold=evo_threshold,
        )
        if self.path.exists():
            self._restore(json.loads(self.path.read_text()))
        else:
            self.persist()

    def _author_log(self, *args: Any, **kwargs: Any) -> None:
        # Author debug prints contain full prompts; retain only failure classification.
        first = str(args[0]) if args else ""
        if first.startswith(("Error analyzing", "JSON parsing error")):
            self.events.append(
                {
                    "kind": "native_error",
                    "status": "error",
                    "reason": first.split(":", 1)[0],
                    "source_id": self.active_source,
                }
            )

    def _invoke(self, kind: str, callback: Callable[[], Any], **metadata: Any) -> Any:
        event = {
            "event_id": str(uuid.uuid4()),
            "kind": kind,
            "status": "pending",
            "source_id": self.active_source,
            **metadata,
        }
        self.events.append(event)
        self.persist()
        try:
            value = callback()
        except Exception as error:
            event.update(status="error", error_type=type(error).__name__)
            self.persist()
            raise
        event["status"] = "completed"
        self.persist()
        return value

    def _native_state(self) -> dict[str, Any]:
        retriever = self.system.retriever
        vectors = retriever.embeddings
        return {
            "memories": [dict(vars(note)) for note in self.system.memories.values()],
            "corpus": list(retriever.corpus),
            "document_ids": retriever.document_ids,
            "embeddings": None if vectors is None else vectors.tolist(),
            "evo_cnt": self.system.evo_cnt,
        }

    def persist(self) -> dict[str, Any]:
        """Save native objects/index and the source journal without regenerating embeddings."""
        self.root.mkdir(parents=True, exist_ok=True)
        state = {
            "binding": self.binding,
            "native": self._native_state(),
            "ingestions": self.ingestions,
            "events": self.events,
            "blocked": self.blocked,
        }
        temporary = self.root / "state.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, allow_nan=False) + "\n")
        temporary.replace(self.path)
        return state

    def _restore(self, state: dict[str, Any]) -> None:
        if state["binding"] != self.binding:
            raise ValueError("AMEM_PERSISTED_SCOPE_CHANGED")
        native = state["native"]
        self.system.memories = {}
        for values in native["memories"]:
            note = self.classes["MemoryNote"].__new__(self.classes["MemoryNote"])
            note.__dict__.update(values)
            self.system.memories[note.id] = note
        self.system.retriever.corpus = native["corpus"]
        self.system.retriever.document_ids = native["document_ids"]
        self.system.retriever.embeddings = (
            None
            if native["embeddings"] is None
            else np.asarray(native["embeddings"], dtype=np.float32)
        )
        self.system.evo_cnt = native["evo_cnt"]
        self.ingestions, self.events, self.blocked = (
            state["ingestions"],
            state["events"],
            state["blocked"],
        )
        # A started source survived without a completed local result. Its provider
        # outcome belongs to the caller; opening state never automatically retries it.
        unfinished = next(
            (key for key, row in self.ingestions.items() if row["status"] == "pending"), None
        )
        if unfinished is not None:
            self.blocked = unfinished

    def snapshot(self) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            json.loads(json.dumps(self._native_state()["memories"], ensure_ascii=False)),
        )

    def set_callbacks(
        self,
        completion: Callable[[str, dict[str, Any]], str],
        embedding: Any,
    ) -> None:
        """Bind the caller's per-operation counted callbacks without changing native state."""
        self._completion, self._embedding = completion, embedding

    def ingest(
        self,
        source_id: str,
        text: str,
        *,
        role: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Add one already occurred source using the author's formation/evolution path."""
        if (
            not source_id
            or not isinstance(text, str)
            or not text
            or role not in {"user", "assistant", "tool"}
            or not observed_at
        ):
            raise ValueError("AMEM_OCCURRED_SOURCE_INVALID")
        source = {"source_id": source_id, "text": text, "role": role, "observed_at": observed_at}
        old = self.ingestions.get(source_id)
        if old is not None:
            if old["source"] != source:
                raise ValueError("AMEM_SOURCE_CHANGED")
            return {
                **old.get("receipt", {"status": "INCOMPLETE", "source_id": source_id}),
                "replayed": True,
            }
        if self.blocked is not None:
            return {
                "status": "INCOMPLETE",
                "reason": "prior_ingest_unresolved",
                "source_id": source_id,
                "blocked_source_id": self.blocked,
            }
        start = len(self.events)
        self.active_source = source_id
        self.ingestions[source_id] = {"source": source, "status": "pending"}
        self.persist()
        try:
            note_id = self.system.add_note(text, time=observed_at)
        except Exception as error:
            self.blocked = source_id
            receipt = {
                "status": "INCOMPLETE",
                "source_id": source_id,
                "error_type": type(error).__name__,
                "native_effect": "partial_or_unknown",
            }
        else:
            failed = any(event["status"] != "completed" for event in self.events[start:])
            receipt = {
                "status": "DEGRADED_NATIVE" if failed else "COMPLETED",
                "source_id": source_id,
                "note_id": note_id,
                "native_effect": "note_stored",
            }
        self.ingestions[source_id].update(status=receipt["status"], receipt=receipt)
        self.active_source = None
        self.persist()
        return {**receipt, "events": self.events[start:]}

    def query(self, text: str, *, k: int = 10) -> dict[str, Any]:
        """Return the author's raw neighbor expansion; k bounds initial retrieval only."""
        if not isinstance(text, str) or type(k) is not int or not 1 <= k <= 10:
            raise ValueError("AMEM_QUERY_INVALID")
        if self.blocked is not None:
            return {
                "status": "INCOMPLETE",
                "context": None,
                "reason": "prior_ingest_unresolved",
                "blocked_source_id": self.blocked,
            }
        start = len(self.events)
        hits: list[int] = []
        retriever = self.system.retriever
        original_search = retriever.search

        def observed_search(query: str, k: int = 5) -> Any:
            indices = original_search(query, k=k)
            hits.extend(int(index) for index in indices)
            return indices

        # Observe the author's actual indices without another embedding request,
        # changing ranking, or modifying the loaded class/method bodies.
        retriever.search = observed_search
        try:
            context = self.system.find_related_memories_raw(text, k=k)
        except Exception as error:
            self.persist()
            return {
                "status": "INCOMPLETE",
                "context": None,
                "error_type": type(error).__name__,
                "events": self.events[start:],
            }
        finally:
            retriever.search = original_search
        notes = list(self.system.memories.values())
        occurrences = []
        expanded_ids = []
        position = 0
        for index in hits:
            sequence = [(index, "retrieval")]
            # Author raw expansion checks j >= k after adding the linked note.
            sequence += [(int(link), "link_expansion") for link in notes[index].links[: k + 1]]
            for selected, kind in sequence:
                note = notes[selected]
                original_line = (
                    "talk start time:"
                    + note.timestamp
                    + "memory content: "
                    + note.content
                    + "memory context: "
                    + note.context
                    + "memory keywords: "
                    + str(note.keywords)
                    + "memory tags: "
                    + str(note.tags)
                    + "\n"
                )
                if not isinstance(context, str) or not context.startswith(original_line, position):
                    raise ValueError("AMEM_AUTHOR_QUERY_DELIVERY_CHANGED")
                end = position + len(original_line)
                source_ids = [
                    source_id
                    for source_id, row in self.ingestions.items()
                    if row.get("receipt", {}).get("note_id") == note.id
                ]
                occurrences.append(
                    {
                        "note_id": note.id,
                        "kind": kind,
                        "source_ids": source_ids,
                        "start": position,
                        "end": end,
                    }
                )
                if kind == "link_expansion":
                    expanded_ids.append(note.id)
                position = end
        self.persist()
        return {
            "status": "COMPLETED",
            "context": context,
            "retrieval_k": k,
            "neighbor_expansion": "author_native_may_exceed_k_and_repeat",
            "retrieved_note_ids": [notes[index].id for index in hits],
            "expanded_note_ids": expanded_ids,
            "occurrences": occurrences,
            "occurrence_count": len(occurrences),
            "provenance": "ingested_note_origin_only; author_neighbor_evolution_not_source_bound",
            "events": self.events[start:],
        }
