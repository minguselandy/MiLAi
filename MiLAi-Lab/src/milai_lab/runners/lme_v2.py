"""Released-trajectory retrieval backend using existing MiLAi execution and accounting."""
from __future__ import annotations

import copy
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.longmemeval_v2 import asset_path, bind_media, trajectory_sources
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.retrieval import SourceSearchCache
from milai_lab.memory.service import MemoryService
from milai_lab.runners.functional import _bank_reference, frozen, message, prepare
from milai_lab.runners.multimodal_evidence import delivered_image_context
from milai_lab.runners.retrieval_histories import prepare_history_bank


class LmeMemoryBackend:
    """insert(full trajectory)/query(text,image) backend with closed-template query isolation.

    The existing finite controller ranks textual observations. The query image is retained
    for the separate fixed Reader; it is not encoded by Laya or converted into a caption.
    Selected source images accompany actual delivered locators. The caller must account
    for the complete multimodal Reader input, and must never filter histories using gold.
    """

    def __init__(self, config: Path, data_root: Path, output: Path, *, source_version: str) -> None:
        output.mkdir(parents=True, exist_ok=False)
        self.config, self.data_root, self.output = config, data_root, output
        self.source_version = source_version
        self.trajectories: dict[str, dict[str, Any]] = {}
        self.template = output / "template"
        self.bank, self.owner = "released-haystack", "lme-evaluation"
        self.models: dict[tuple[Any, ...], Any] = {}
        self.source_search_cache = SourceSearchCache()
        self.media: dict[str, dict[str, Any]] = {}
        self.queries = 0
        self.failed = False
        self.cpu_seconds = self.wall_seconds = 0.0

    @contextmanager
    def overhead(self) -> Iterator[None]:
        started, cpu = time.perf_counter(), time.process_time()
        try:
            yield
        finally:
            self.wall_seconds += time.perf_counter()-started
            self.cpu_seconds += time.process_time()-cpu
            write_json(self.output / "orchestration-compute.json", {
                "cpu_seconds": self.cpu_seconds, "wall_seconds": self.wall_seconds,
                "ledger_recorded": False, "model_calls": 0,
                "scope": "Insertion, source setup, closed Store copies and image binding only. "
                         "Excludes existing functional runner model work and later Reader work."})

    def insert(self, trajectory: dict[str, Any]) -> None:
        if self.template.exists() or trajectory["id"] in self.trajectories:
            raise ValueError("Insert each released trajectory once before the first query")
        with self.overhead():
            self.trajectories[trajectory["id"]] = copy.deepcopy(trajectory)

    def _build(self) -> None:
        with self.overhead():
            prepare(self.template, self.config, source_version=self.source_version)
            sources, assets = [], []
            for trajectory in self.trajectories.values():
                rows, images = trajectory_sources(trajectory)
                sources.extend(rows)
                assets.extend(images)
            setup = prepare_history_bank(self.template, bank=self.bank, owner=self.owner, history={
                "source_group": "lme-v2-declared-haystack", "sources": sources})
            self.media = bind_media(assets, setup["sources"], self.data_root)
            write_json(self.output / "source-setup.json", setup)
            write_json(self.output / "bound-images.json", self.media)
            self.ledger = Path(frozen(self.template)["config"]["budget_path"])
            write_json(self.output / "budget-before.json", read_json(self.ledger))

    def query(self, query: str, query_image: str | None = None) -> list[dict[str, str]]:
        """Fresh original haystack for each question; no earlier question/answer enters memory."""
        import shutil

        if self.failed:
            raise ValueError("The first failed query is retained; automatic retry is disabled")
        index = self.queries
        self.queries += 1
        case = self.output / "cases" / f"{index:04d}"
        report: dict[str, Any] = {"status": "RUNNING", "row": index,
            "query": query, "query_image": query_image, "automatic_retry": False,
            "query_image_consumed_by_retriever": False,
            "query_image_destination": "Unchanged fixed Reader question image",
            "query_isolation": "Closed haystack Store clone; shared loaded controller pool"}
        try:
            if not self.template.exists():
                self._build()
            with self.overhead():
                if query_image is not None:
                    asset_path(self.data_root, query_image)
                shutil.copytree(self.template, case)
                write_json(case / "query.json", report)
            result = message(case, bank=self.bank, owner=self.owner, session="evaluation",
                message_id=f"query-{index}", content=query,
                given_retrieval_request={"query": query}, control_models=self.models,
                source_search_cache=self.source_search_cache)
            if result["status"] != "COMPLETED":
                raise RuntimeError("First failed retrieval retained: " + str(result.get("error")))
            with self.overhead():
                freeze = frozen(case)
                settings = freeze["config"]
                bank_id = _bank_reference(case, freeze["run_id"], self.bank, self.owner)
                directory = case / "banks" / bank_id
                with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
                    service = MemoryService(store, ("functional", freeze["run_id"],
                        self.bank, self.owner), self.owner, directory / "memory.lock",
                        functional_contract="functional_v1",
                        memory_profile=settings.get("memory_profile", "ordinary"),
                        memory_ranking=settings.get("memory_ranking", "dense"))
                    context = delivered_image_context(
                        service, result["retrieval_result"], self.media)
                write_json(case / "memory-context.json", context)
                report.update(status="COMPLETED", images=sum(c["type"] == "image" for c in context),
                    reader_called=False, source_version=self.source_version)
            return context
        except BaseException as error:
            self.failed = True
            report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            raise
        finally:
            report["source_index_cache"] = {"builds": self.source_search_cache.builds,
                                            "hits": self.source_search_cache.hits,
                "scope": "Cumulative per-backend native corpus computations; no query/answer cache"}
            write_json(case / "query.json", report)
            if hasattr(self, "ledger"):
                write_json(self.output / "budget-after.json", read_json(self.ledger))
