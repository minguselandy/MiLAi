"""Native backends assembled around the existing online benchmark and Reader.

This module owns experiment scheduling, not another memory formation pipeline.
The backend sees ObservedSession only; gold remains in the inherited evaluator.
"""

from __future__ import annotations

import copy
import sqlite3
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, cast

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.contracts.memory_backend import MemoryBackend, MemorySession
from milai_lab.datasets.edit_benchmarks import ObservedSession, halumem_time, halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun, reader_messages

BACKENDS = ("RawRAG-local", "Hindsight-native-local-recall", "MiLAi-memory-only")


def alignment_settings(config: dict[str, Any], backend: str) -> dict[str, Any]:
    """One explicit configuration per arm, retaining the ordinary maintenance recipe."""
    if backend not in config["alignment"]["backends"] or backend not in BACKENDS:
        raise ValueError("Unknown declared alignment backend")
    settings = cast(dict[str, Any], copy.deepcopy(config["entrypoints"]["benchmark"]))
    settings.pop("arms", None)
    settings.update(arm="M", alignment_backend=backend, alignment=config["alignment"])
    settings["retrieval_limit"] = config["alignment"]["qa_top_k"]
    settings["memory_view_mode"] = config["alignment"]["delivery"]
    return settings


def prepare_alignment(config: dict[str, Any], root: Path) -> dict[str, Any]:
    """Declare actual development opportunities without banks or model clients."""
    path = root / "alignment-prepared.json"
    if path.exists():
        manifest = read_json(path)
        if manifest["configuration"] != config:
            raise ValueError("Prepared comparison changed; use a distinct output root")
        return dict(manifest)
    alignment = config["alignment"]
    if alignment["source_policy"] != "source-only" or alignment["history_protocol"] != (
        "halumem-online-prefix"
    ):
        raise ValueError("First comparison requires the declared source-only online prefix")
    if alignment["delivery"] not in {"direct", "staged", "state_driven"}:
        raise ValueError("Unknown declared delivery")
    if alignment["qa_top_k"] != 20 or alignment["update_top_k"] != 10:
        raise ValueError("First comparison declares QA20 and evaluator-only update10")
    settings = config["entrypoints"]["benchmark"]
    selection = settings["halumem"]
    users = halumem_users(Path(selection["path"]), selection["users"])
    opportunities: dict[str, Any] = {}
    for user in users:
        ordered = sorted(enumerate(user["sessions"]), key=lambda pair: (
            halumem_time(pair[1]["start_time"]), pair[0],
        ))[:selection["session_prefix"]]
        opportunities[user["uuid"]] = {
            "session_ordinals": [ordinal for ordinal, _ in ordered],
            "sessions": len(ordered),
            "qa": sum(len(session.get("questions", [])) for _, session in ordered
                      if not session.get("is_generated_qa_session", False)),
            "native_updates": sum(
                memory["is_update"] == "True" for _, session in ordered
                if not session.get("is_generated_qa_session", False)
                for memory in session.get("memory_points", [])),
        }
    manifest = {
        "status": "PREPARED_ZERO_MODEL", "protocol": alignment,
        "configuration": config, "per_user_opportunities": opportunities,
        "per_backend_opportunities": {
            field: sum(row[field] for row in opportunities.values())
            for field in ("sessions", "qa", "native_updates")
        },
        "native_and_common_answers": "separate",
        "bank_ids": {
            backend: {owner: f"milai-local-{uuid.uuid4().hex}" for owner in opportunities}
            for backend in alignment["backends"]
        },
        "runtime_method_inputs": "ObservedSession only; current query after completed ingestion",
        "reference_queries": "evaluator-only isolated view or N/A",
        "repetitions": 1, "models_called": 0,
    }
    if root.exists() and any(root.iterdir()):
        raise ValueError("New comparison requires an empty output root")
    write_json(path, manifest)
    return manifest


class AlignmentRun(BenchmarkRun):
    """Reuse original prefix, receipts, actual request accounting and official labels."""

    @property
    def session_output_supported(self) -> bool:
        return str(self.settings["alignment_backend"]) == "MiLAi-memory-only"

    @property
    def reference_retrieval_supported(self) -> bool:
        # Raw source retrieval is not an exported semantic memory state. Native
        # Hindsight recall is not declared to be side-effect-free or cloneable.
        return str(self.settings["alignment_backend"]) == "MiLAi-memory-only"

    def __init__(self, settings: dict[str, Any], root: Path, *, phase: str) -> None:
        super().__init__(settings, root, phase=phase)
        self.backends: dict[str, MemoryBackend] = {}

    def _backend(self, service: MemoryService) -> MemoryBackend:
        owner = service.owner
        if owner in self.backends:
            return self.backends[owner]
        backend = self.settings["alignment_backend"]
        location = self.root / "native-banks" / owner
        if backend == "RawRAG-local":
            from milai_lab.baselines.rawrag_local import RawRAGLocal

            value: MemoryBackend = RawRAGLocal(
                location, bank_id=self.settings["alignment_bank_ids"][owner],
                granularity=self.settings["alignment"]["rawrag"]["granularity"],
            )
        elif backend == "Hindsight-native-local-recall":
            from milai_lab.integrations.memory.hindsight import HindsightBackend

            value = HindsightBackend(
                location, bank_id=self.settings["alignment_bank_ids"][owner],
                **self.settings["alignment"]["hindsight"],
            )
        else:
            from milai_lab.methods.milai_memory_only import MiLAiMemoryBackend

            def maintain(session: MemorySession, key: str) -> list[str]:
                observed = ObservedSession(session.session_id, session.date, session.turns)
                return super(AlignmentRun, self).maintain(service, observed, key)

            def retrieve(question: str, date: str, key: str, limit: int) -> list[dict[str, Any]]:
                return self.retrieve_material(service, question, date, key, limit=limit)

            value = MiLAiMemoryBackend(
                maintain=maintain, retrieve=retrieve,
                maintenance_result=lambda key: read_json(
                    self.root / "maintenance" / key / "complete.json"),
                retrieval_native=lambda key: read_json(
                    self.root / "http" / key / "retrieval-native.json"),
                usage=lambda: dict(self.budget.state),
            )
        self.backends[owner] = value
        return value

    def maintain(self, service: MemoryService, observed: ObservedSession, key: str) -> list[str]:
        self._evaluation_key = key
        receipt = self._backend(service).ingest(observed, key=key)
        write_json(self.root / "native" / key / "ingestion.json", receipt)
        if (not receipt["completed"]
                and self.settings["alignment_backend"] != "MiLAi-memory-only"):
            raise RuntimeError("Native ingestion not completed; current QA cannot proceed")
        # Existing MiLAi known partial maintenance has settled receipts and keeps
        # its natural history. Unknown writes/Store failures propagate before a
        # return; a recorded gap is neither retried nor called semantic success.
        return receipt["session_output"] or []

    def answer(self, service: MemoryService, question: str, date: str, key: str) -> str:
        path = self.root / "native" / key / "retrieval.json"
        if path.exists():
            retrieval = read_json(path)
        else:
            retrieval = self._backend(service).retrieve(
                question, date, key=key, limit=self.settings["alignment"]["qa_top_k"],
            )
            write_json(path, retrieval)
        # The actual return is retained intact. Common transport only renders
        # those materials; no additional extractor, selector or identity binding.
        cached_response = (self.root / "http" / key / "response.json").exists()
        answer, used = self.answer_material(question, date, key, retrieval["materials"])
        if (self.settings["alignment_backend"] == "MiLAi-memory-only"
                and service.memory_profile == "unified_v1"):
            from milai_lab.memory.activation import ActivationIndex

            index = ActivationIndex(service)
            for material in used:
                if "record_id" in material:
                    index.record_use(material["record_id"], request_id=key, cached=cached_response)
        return answer

    def _score_retrieval(self, service: MemoryService, query: str) -> list[str]:
        if not self.reference_retrieval_supported:
            return []
        # Reference text can issue handles and populate search caches. Preserve
        # the actual session state once and perform these evaluator-only reads
        # in its own Store; none of those effects re-enter the method bank.
        folder = self.root / "evaluation-views" / self._evaluation_key
        folder.mkdir(parents=True, exist_ok=True)
        database = folder / "memory.sqlite"
        if not database.exists():
            with sqlite3.connect(database) as destination:
                service.store.conn.backup(destination)
            write_json(folder / "view.json", {
                "session_key": self._evaluation_key, "owner": service.owner,
                "namespace": list(service.namespace), "purpose": "evaluator-only-update-K10",
                "source": "actual session state after current predictions; no future ingestion",
            })
        with SqliteStore.from_conn_string(str(database)) as store:
            isolated = MemoryService(
                store, service.namespace, service.owner, folder / "memory.lock",
                mutation_contract=service.mutation_contract,
                candidate_contract=service.candidate_contract,
                semantic_retriever=self._semantic_retriever(),
                memory_profile=service.memory_profile, memory_ranking=service.memory_ranking,
            )
            return super()._score_retrieval(isolated, query)

    def _reader_messages(
        self, question: str, date: str, memories: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        return reader_messages(
            question, date, memories,
            memory_view=("source_history" if self.settings["alignment_backend"] == "RawRAG-local"
                         else "retained_state"),
            projection=self.settings.get("reader_projection", "legacy"),
        )

    def halumem(self, phase: str = "all") -> dict[str, Any]:
        result = super().halumem(phase)
        if phase == "predict":
            return result
        result["backend_capabilities"] = {
            "session_output": "supported" if self.session_output_supported else "N/A",
            "reference_update_state": (
                "supported-isolated-view" if self.reference_retrieval_supported else "N/A"
            ),
        }
        if not self.session_output_supported:
            for name in ("memory_integrity", "memory_accuracy", "memory_extraction_f1"):
                result["overall_score"][name] = None
        if not self.reference_retrieval_supported:
            result["overall_score"]["memory_update"] = None
            result["overall_score"]["memory_type_accuracy"] = None
        rows = result["question_answering_records"]
        labels = Counter(row["result_type"] or "invalid" for row in rows
                         if row["system_response"] is not None)
        per_user = {}
        for owner in self.settings["halumem"]["users"]:
            actual = [row for row in rows if row["uuid"] == owner]
            per_user[owner] = {
                "correct": sum(row["result_type"] == "Correct" for row in actual),
                "opportunities": len(actual),
                "missing": sum(row["system_response"] is None for row in actual),
                "invalid": sum(row["system_response"] is not None
                               and row["result_type"] is None for row in actual),
            }
        common = {
            "status": "SCORED_SAVED_PREDICTIONS", "backend": self.settings["alignment_backend"],
            "protocol": self.settings["alignment"],
            "correct": sum(row["result_type"] == "Correct" for row in rows),
            "opportunities": len(rows),
            "missing": sum(row["system_response"] is None for row in rows),
            "labels": dict(labels), "per_user": per_user,
            "backend_capabilities": result["backend_capabilities"],
            "official_labels": "unchanged; source conflicts require separate evidence review",
            "semantic_advantage": "unchecked", "native_answer_result": None,
        }
        write_json(self.root / "common-qa-results.json", common)
        write_json(self.root / "halumem-official-results.json", result)
        return common

    def close(self) -> None:
        try:
            for backend in self.backends.values():
                backend.close()
        finally:
            super().close()


def run_alignment_arm(config: dict[str, Any], root: Path, backend: str, phase: str) -> None:
    """One explicit arm/phase dispatch; no automatic scoring or retries."""
    if phase not in {"predict", "score"}:
        raise ValueError("Predict and score require separate explicit dispatch")
    settings = alignment_settings(config, backend)
    prepared = read_json(root / "alignment-prepared.json")
    if prepared["configuration"] != config:
        raise ValueError("Comparison configuration differs from its preparation")
    settings["alignment_bank_ids"] = prepared["bank_ids"][backend]
    output = root / backend
    terminal = output / f"terminal-{phase}.json"
    if terminal.exists():
        raise ValueError("Closed arm/phase already exists; do not repeat")
    if phase == "score":
        for selected in config["alignment"]["backends"]:
            prior = root / selected / "terminal-predict.json"
            if not prior.exists() or read_json(prior)["status"] != "PREDICTIONS_SAVED":
                raise ValueError("Every declared backend must close predictions before scoring")
    execution = AlignmentRun(settings, output, phase=phase)
    try:
        result = execution.halumem(phase)
        write_json(terminal, {
            "status": "PREDICTIONS_SAVED" if phase == "predict" else "SCORED",
            "phase": phase, "backend": backend, "result": result,
        })
    except BaseException as error:
        write_json(terminal, {
            "status": "FAILED", "phase": phase, "backend": backend,
            "error": {"type": type(error).__name__, "message": str(error)},
            "no_automatic_retry": True,
        })
        raise
    finally:
        execution.close()
