"""Read saved arrival-prefix retrievals without repeating formation or retrieval."""

from __future__ import annotations

import copy
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from milai_lab.analysis.edit_official import HaluMemOfficial
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_maintenance import parse_object

if TYPE_CHECKING:
    from milai_lab.runners.edit_benchmarks import BenchmarkRun


def _cost(folder: Path, elapsed: float) -> dict[str, Any]:
    models: dict[str, Any] = {}
    stages: dict[str, Any] = {}
    for path in folder.rglob("response.json"):
        response = read_json(path)
        usage = response["usage"]
        row = models.setdefault(response["model"], {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
        })
        row["calls"] += 1
        row["input_tokens"] += usage["prompt_tokens"]
        row["output_tokens"] += usage["completion_tokens"]
        relative = path.relative_to(folder).parts
        stage = "ranking" if "ranking" in relative else "paging" if "view" in relative else "answer"
        stage_row = stages.setdefault(stage, {}).setdefault(response["model"], {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
        })
        stage_row["calls"] += 1
        stage_row["input_tokens"] += usage["prompt_tokens"]
        stage_row["output_tokens"] += usage["completion_tokens"]
    return {"models": models, "stages": stages, "embedding_tokens": 0,
            "elapsed_seconds": elapsed}


def _copied_bank(source: Path, destination: Path) -> None:
    """Copy through SQLite's existing snapshot API; never open the original for writes."""
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as copied:
            original.backup(copied)


def _predict(
    execution: BenchmarkRun, source: Path, source_settings: dict[str, Any],
    owner: str, key: str, question: str, date: str,
) -> dict[str, Any]:
    bank = execution.root / "replay-banks" / owner
    _copied_bank(source / "banks" / owner / "memory.sqlite", bank / "memory.sqlite")
    started = time.monotonic()
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", source.name, source_settings.get("arm", "ordinary"), owner),
            owner, bank / "memory.lock", mutation_contract="event_bound_v1",
            candidate_contract="read_handle_v1", functional_contract="functional_v1",
            memory_profile=source_settings.get("memory_profile", "ordinary"),
            memory_ranking=source_settings.get("memory_ranking", "dense"),
        )
        original = source / "native" / key / "retrieval.json"
        saved = read_json(original)
        native = copy.deepcopy(saved["native_return"])
        pool = execution.root / "native" / key / "retrieval.json"
        snapshot_id = str(pool.relative_to(execution.root))
        # These are the actual values/revisions returned at this question, never
        # the copied bank's latest values. The service only reopens their exact
        # sources and predecessor revisions; no future search is performed.
        semantic = execution._record_materials(service, native["records"], date)
        materials = execution._source_first_materials(
            service, question, date, native, semantic, snapshot_id=snapshot_id,
        )
        write_json(pool, {
            "materials": materials, "native_return": native, "source_snapshot": str(original),
            "returned_count": len(materials), "shared_retrieval_usage": saved.get("usage"),
            "evidence_variant": execution.settings.get("evidence_variant", "S2"),
        })
        failure = None
        try:
            answer, _ = execution.answer_material(
                question, date, key, materials, snapshot_id=snapshot_id,
                material_reader=lambda items: execution._live_materials(service, items),
            )
        except ValueError as error:
            failure = execution._known_reader_failure(error, key)
            if failure is None:
                raise
            answer = None
        # answer_material reports all pages actually read. Final evidence comes
        # from resident_refs, which is narrower when paging drops a nomination.
        view_path = execution.root / "http" / key / "memory-view.json"
        view = read_json(view_path) if view_path.exists() else {}
        final_indices = [ref["item_index"] for ref in view.get("resident_refs", [])]
        if not (view.get("delivery_plan", {}).get("body_delivered")
                or view_path.with_name("request.json").exists()):
            final_indices = []
        final = [materials[index] for index in final_indices]
        delivered_indices = {ref["item_index"] for ref in view.get(
            "capacity_continuation", {}).get("delivered_page_refs", [])}
        delivered_indices.update(final_indices)
        assembly = native["material_assembly"]
        origins = assembly.get("material_origins")
        result = {
            "question": question, "hypothesis": answer,
            "execution": "answered" if isinstance(answer, str) else "missing",
            "source_snapshot": str(original), "source_bank": str(source / "banks" / owner),
            "source_state": "saved arrival-prefix records and original ranges; no new search",
            "evidence": {
                "pool": len(materials), "read": len(delivered_indices), "final": len(final),
                "linked_candidates": assembly["linked_original_candidates"],
                "semantic_candidates": assembly["semantic_candidates"],
                "semantic_in_pool": assembly["semantic_materials"],
                "semantic_final": sum(item.get("kind") == "semantic_view" for item in final),
                "linked_final": (sum(origins[index] == "linked_source"
                                     for index in final_indices) if origins is not None else None),
                "final_item_indices": final_indices,
            },
            "prediction_cost": _cost(execution.root / "http" / key, time.monotonic() - started),
            "shared_cost": {
                "formation": str(source / "maintenance" / key.split("/qa/")[0]),
                "retrieval": str(original), "accounting": "reused once, not charged per arm",
            },
            **({"reader_failure": failure} if failure is not None else {}),
        }
        return result


def replay_halumem(execution: BenchmarkRun, phase: str) -> dict[str, Any]:
    """One configured arm over retained question pools; no maintenance or activation writes."""
    replay = execution.settings["evidence_replay"]
    source = Path(replay["source_run"]).resolve()
    source_settings = read_json(source / "actual-config.json")
    selected = replay["questions"]
    selection = execution.settings["halumem"]
    users = {user["uuid"]: user for user in halumem_users(
        Path(selection["path"]), list(dict.fromkeys(item["owner"] for item in selected)),
    )}
    variant = execution.settings.get("evidence_variant", "S2")
    ranking = execution.settings.get("reader_ranking", "native")
    execution._judge_serial = 0
    official = HaluMemOfficial(
        Path(selection["official_checkout"]),
        lambda prompt: parse_object(execution.call(
            execution._judge_key(), [{"role": "user", "content": prompt}], structured=True,
        )),
    ) if phase != "predict" else None
    table = []
    records: dict[str, Any] = {name: [] for name in (
        "memory_integrity_records", "memory_accuracy_records", "memory_update_records",
        "question_answering_records",
    )}
    counts = {"judge_failures": 0}
    for item in selected:
        owner, session_index, question_index = item["owner"], item["session"], item["question"]
        session = users[owner]["sessions"][session_index]
        qa = session["questions"][question_index]
        key = f"halumem/{owner}/{session_index}/qa/{question_index}"
        prediction_path = execution.root / "predictions" / key / "complete.json"
        if phase != "score" and not prediction_path.exists():
            prediction = _predict(execution, source, source_settings, owner, key,
                                  qa["question"], session["end_time"])
            write_json(prediction_path, prediction)
        row: dict[str, Any] = {
            "question_id": key, "variant": variant, "reader_ranking": ranking,
            "answer_path": str(prediction_path), "official_label": "unscored",
        }
        if not prediction_path.exists():
            row.update(execution="not_run", evidence=None, prediction_cost=None)
            table.append(row)
            continue
        prediction = read_json(prediction_path)
        row.update({name: prediction[name] for name in (
            "execution", "evidence", "prediction_cost", "shared_cost",
        )})
        if official is not None:
            evaluation_path = execution.root / "evaluation" / key / "complete.json"
            if evaluation_path.exists():
                scored = read_json(evaluation_path)
                execution._judge_serial = scored["judge_serial"]
            else:
                answer = prediction["hypothesis"]
                started = time.monotonic()
                judge_serial = execution._judge_serial + 1
                verdict = execution._safe_score(
                    official, counts, "question", qa["question"], qa["answer"],
                    "\n".join(e["memory_content"] for e in qa["evidence"]), answer,
                ) if isinstance(answer, str) else {}
                scored = {
                    "record": {**qa, "uuid": owner, "ssession_id": session_index,
                               "question_index": question_index, "system_response": answer,
                               "result_type": verdict.get("evaluation_result")},
                    "verdict": verdict, "judge_serial": execution._judge_serial,
                    "judge_cost": _cost(execution.root / "http/halumem/judge" /
                                        f"{judge_serial:06d}", time.monotonic() - started)
                    if isinstance(answer, str) else {"models": {}, "elapsed_seconds": 0},
                }
                write_json(evaluation_path, scored)
            records["question_answering_records"].append(scored["record"])
            row["official_label"] = scored["record"]["result_type"] or (
                "missing" if prediction["hypothesis"] is None else "invalid")
            row["judge_cost"] = scored["judge_cost"]
        table.append(row)
        write_json(execution.root / "evidence-results.json", table)
    write_json(execution.root / "evidence-results.json", table)
    summary = {
        "status": "PREDICTIONS_SAVED" if phase == "predict" else "SCORED_SAVED_PREDICTIONS",
        "variant": variant, "reader_ranking": ranking, "planned_opportunities": len(selected),
        "opportunities": sum(row["execution"] != "not_run" for row in table),
        "complete_answers": sum(row["execution"] == "answered" for row in table),
        "known_reader_failures": sum(row["execution"] == "missing" for row in table),
        "not_run": sum(row["execution"] == "not_run" for row in table),
        "judge_calls": execution._judge_serial,
        "shared_state": str(source), "formation_calls": 0, "retrieval_calls": 0,
        "activation_feedback": False,
    }
    if official is not None:
        summary.update(
            correct=sum(row["official_label"] == "Correct" for row in table),
            missing=summary["known_reader_failures"],
            labels=dict(Counter(row["official_label"] for row in table
                                if row["execution"] == "answered")),
        )
        result = official.aggregate_qa_results(records)
        result["shared_cost"] = "Original formation and retrieval reused; not full-system cost"
        write_json(execution.root / "halumem-official-results.json", result)
        write_json(execution.root / "common-qa-results.json", summary)
    write_json(execution.root / "evidence-summary.json", summary)
    return summary
