"""Offline document provenance for actual given-request retrieval returns."""
from __future__ import annotations

import json
import os
import shutil
import tarfile
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.instructir import delivered_document_ranking, retrieval_request
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.case_archive import archive_case
from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs
from milai_lab.runners.functional import _bank_reference, frozen, message, prepare


def project_query_result(
    root: Path, result: dict[str, Any], source_to_document: dict[str, str],
) -> dict[str, Any]:
    """Resolve only actual delivered refs against this closed query's own Store.

    A failed call has no successful ranking. The retained result/trace still
    contains its first failure and any actual partial receipt for diagnosis.
    Successful empty retrieval is likewise an empty native ranking, not omitted.
    """
    if result["status"] != "COMPLETED":
        return {"ranking": {}, "entries": [], "status": result["status"],
                "scope": "Failed query retained with empty primary ranking; no output repair."}
    receipt, = [message for message in result["messages"]
                if message.get("type") == "tool" and message.get("name") == "milai_retrieve"]
    packet = json.loads(receipt["content"])
    if packet != result["retrieval_result"]:
        raise ValueError("Scoring must use the actual recorded retrieval ToolMessage")
    freeze = frozen(root)
    bank, owner = result["bank"], result["owner"]
    directory = root / "banks" / _bank_reference(root, freeze["run_id"], bank, owner)
    with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
        service = MemoryService(store, ("functional", freeze["run_id"], bank, owner), owner,
            directory / "memory.lock", functional_contract="functional_v1",
            memory_profile=freeze["config"].get("memory_profile", "ordinary"),
            memory_ranking=freeze["config"].get("memory_ranking", "dense"))

        def resolve(ref: dict[str, Any]) -> dict[str, Any]:
            snapshot = store.get(namespace(service), ref["snapshot_id"])
            if snapshot is None or ref["collection"] != "materials":
                raise ValueError("Delivered reference has no retained material snapshot")
            if ref["item_index"] not in snapshot.value["delivered_indices"]:
                raise ValueError("A retained but unreturned material cannot receive ranking credit")
            return open_evidence_packs(service,
                [snapshot.value["materials"][ref["item_index"]]])[0]

        projection = delivered_document_ranking(packet, resolve, source_to_document)
    return {**projection, "status": result["status"],
            "source": "Actual ToolMessage refs resolved in this query's retained Store",
            "host_request_generated": result["host_request_generated"]}


def archive_query(root: Path, destination: Path, *, base: Path | None = None) -> dict[str, Any]:
    """Retain a closed case losslessly before removing its working directory."""
    if base is not None:
        return archive_case(root, destination, base)
    files = {str(path.relative_to(root)): path.stat().st_size
             for path in root.rglob("*") if path.is_file()}
    with tarfile.open(destination, "x:gz", compresslevel=6) as archive:
        archive.add(root, arcname="case")
    with tarfile.open(destination) as archive:
        archived = {str(Path(member.name).relative_to("case")): member.size
                    for member in archive.getmembers() if member.isfile()}
    if archived != files:
        raise ValueError("Closed case archive does not contain the complete file inventory")
    result = {"archive": str(destination), "files": len(files),
              "uncompressed_bytes": sum(files.values()),
              "archive_bytes": destination.stat().st_size,
              "format": "tar.gz; complete closed Store, raw results, traces and request files",
              "verification": "File names and sizes, no SHA/content fingerprints"}
    shutil.rmtree(root)
    return result


def run_given_queries(
    config: Path, queries: list[dict[str, Any]], source_bank: Path, output: Path,
    *, source_version: str,
) -> dict[str, Any]:
    """Full declared query cohort, fresh source copy per case and one warm model pool.

    Source-bank preparation is separate. The runner never loads qrels. Compression
    retains every closed case while avoiding thousands of uncompressed Store copies.
    Unexpected failures stop after retaining that first case; no automatic retry.
    """
    setup = read_json(source_bank / "preparation.json")
    if setup["status"] != "COMPLETE_SOURCE_STORE":
        raise ValueError("The complete source Store must be closed before query evaluation")
    if len({row["_id"] for row in queries}) != len(queries):
        raise ValueError("Each declared InstructIR query must have a unique native ID")
    output.mkdir(parents=True, exist_ok=False)
    (output / "cases").mkdir()
    (output / "working").mkdir()
    source_to_document = read_json(source_bank / "source-map.json")
    started = time.perf_counter()
    overhead_wall = overhead_cpu = 0.0
    query_unattributed_cpu = 0.0
    budget_path = None
    models: dict[tuple[Any, ...], Any] = {}
    rankings: dict[str, dict[str, float]] = {}
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": source_version, "started_epoch": time.time(),
        "planned_positions": len(queries), "completed": [], "automatic_retry": False,
        "source_bank": str(source_bank), "corpus_documents": setup["source_documents"],
        "artifact_storage": "case_blocks_v1 against retained method template; byte-exact recovery",
        "request_transport": "programmatic_given_request", "host_request_generated": False,
        "qrels_loaded": False, "model_pool": "Same process across independent query copies",
        "ranking_protocol": "Returned original ranges or explicit returned view citations; "
                            "first wire occurrence. Failed calls have empty primary rankings."}
    write_json(output / "driver.json", driver)

    @contextmanager
    def overhead() -> Iterator[None]:
        nonlocal overhead_wall, overhead_cpu
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            yield
        finally:
            overhead_wall += time.perf_counter() - wall
            overhead_cpu += time.process_time() - cpu

    try:
        with overhead():
            template = output / "template"
            source_template = source_bank / "template"
            shutil.copytree(source_template, template,
                            ignore=shutil.ignore_patterns("input-freeze.json"))
            prepare(template, config, source_version=source_version,
                    run_id=frozen(source_template)["run_id"])
            budget_path = Path(frozen(template)["config"]["budget_path"])
            write_json(output / "budget-before.json", read_json(budget_path))
            write_json(output / "query-cohort.json", {"queries": [row["_id"] for row in queries],
                "scope": "Full caller-declared release order, IDs are evaluator-side only"})
            write_json(output / "rankings.json", rankings)
        for index, row in enumerate(queries):
            with overhead():
                driver["active"] = {"row": index, "query_id": row["_id"]}
                write_json(output / "driver.json", driver)
                case_root = output / "working" / f"{index:05d}"
                shutil.copytree(template, case_root)
                request = retrieval_request(row)
                entry_budget = read_json(budget_path)
            result = None
            query_wall, query_cpu = time.perf_counter(), time.process_time()
            try:
                result = message(case_root, bank=setup["bank"], owner=setup["owner"],
                    session="instructir-query", message_id=row["_id"], content=request["query"],
                    given_retrieval_request=request, control_models=models)
            finally:
                elapsed_wall = time.perf_counter() - query_wall
                elapsed_cpu = time.process_time() - query_cpu
                before = result["budget_before"] if result is not None else entry_budget
                after = result["budget_after"] if result is not None else read_json(budget_path)
                billed_cpu = sum(values.get("cpu_seconds", 0) - before.get("compute", {}).get(
                    name, {}).get("cpu_seconds", 0)
                    for name, values in after.get("compute", {}).items())
                exclusive_cpu = elapsed_cpu - billed_cpu
                if exclusive_cpu < 0:
                    raise ValueError("Nested compute exceeds measured query CPU")
                query_unattributed_cpu += exclusive_cpu
                driver["active"].update(query_wall_seconds=elapsed_wall,
                    query_cpu_seconds_nested=elapsed_cpu,
                    query_cpu_seconds_not_yet_recorded=exclusive_cpu,
                    working_directory=str(case_root))
            with overhead():
                driver["active"]["retrieval_status"] = result["status"]
                write_json(output / "driver.json", driver)
                projection = project_query_result(case_root, result, source_to_document)
                case = {"row": index, "query_id": row["_id"], "status": result["status"],
                    "error": result.get("error"), "query_wall_seconds": elapsed_wall,
                    "query_cpu_seconds_nested": elapsed_cpu,
                    "ledger_compute_cpu_seconds_nested": billed_cpu,
                    "query_cpu_seconds_not_yet_recorded": exclusive_cpu, **projection}
                write_json(case_root / "evaluation.json", case)
                archive = archive_query(case_root, output / "cases" / f"{index:05d}.tar.gz",
                                        base=template)
                case["artifacts"] = archive
                rankings[row["_id"]] = projection["ranking"]
                driver["completed"].append(case)
                write_json(output / "rankings.json", rankings)
                write_json(output / "driver.json", driver)
            print(json.dumps({"completed": len(driver["completed"]), "planned": len(queries),
                              "status": result["status"]}), flush=True)
            known_failure = (result.get("error_category") == "provider_protocol"
                and result.get("error_type") == "IncompleteChatResponse"
                and all(after[kind]["unknown_usage"] == before[kind]["unknown_usage"]
                        for kind in ("generation", "embedding")))
            if result["status"] != "COMPLETED" and not known_failure:
                raise RuntimeError("First failed query retained; inspect before continuing")
        driver["status"] = ("COMPLETED_WITH_FAILURES" if any(
            case["status"] != "COMPLETED" for case in driver["completed"]) else "COMPLETED")
        driver["program_counts"] = dict(Counter(case["status"] for case in driver["completed"]))
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        driver.update(wall_seconds=time.perf_counter() - started, finished_epoch=time.time())
        write_json(output / "driver.json", driver)
        write_json(output / "orchestration-compute.json", {
            "wall_seconds": overhead_wall, "cpu_seconds": overhead_cpu + query_unattributed_cpu,
            "orchestration_cpu_seconds": overhead_cpu,
            "query_cpu_seconds_not_in_nested_ledger_phases": query_unattributed_cpu,
            "scope": "Preparation/copies/projection/archive plus query CPU not already charged "
                     "by nested native/other compute phases. Query wall includes runtime setup "
                     "and retrieval, including interrupted calls; excludes reset/archive. "
                     "Driver wall is nested.",
            "model_calls": 0, "ledger_recorded": False,
            "ledger": str(budget_path) if budget_path is not None else None})
        if budget_path is not None:
            write_json(output / "budget-after.json", read_json(budget_path))
    return driver
