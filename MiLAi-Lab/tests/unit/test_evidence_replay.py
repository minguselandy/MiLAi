"""Saved prefix replay cannot search future data or modify the original bank."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from milai_lab.analysis.edit_official import HaluMemOfficial
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.activation import ActivationIndex
from milai_lab.memory.service import MemoryService
from milai_lab.methods.query_structure import build_query_structure
from milai_lab.runners import evidence_replay
from milai_lab.runners.baseline_alignment import AlignmentRun
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def fixture_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                run_type: type[BenchmarkRun] = AlignmentRun) -> tuple[BenchmarkRun, Path]:
    original = tmp_path / "original" / "MiLAi-memory-only"
    original.mkdir(parents=True)
    settings = {
        "arm": "M", "alignment_backend": "MiLAi-memory-only", "memory_profile": "unified_v1",
        "memory_view_mode": "direct", "source_access": "independent_v1",
        "context_tokens": 32000, "model": {"max_tokens": 1000},
        "halumem": {"path": str(tmp_path / "data.jsonl"), "official_checkout": "unused",
                    "reader_failure_policy": "record_known_readonly_failure"},
        "evidence_replay": {"source_run": str(original), "questions": [
            {"owner": "owner", "session": 0, "question": 0},
        ]},
    }
    write_json(original / "actual-config.json", settings)
    (tmp_path / "data.jsonl").write_text(json.dumps({"uuid": "owner", "sessions": [{
        "end_time": "Jan 01, 2025, 12:00:00", "questions": [
            {"question": "Which marker?", "answer": "GOLD_NOT_FOR_READER", "evidence": []},
        ],
    }]}) + "\n")
    execution = run_type.__new__(run_type)
    execution.settings, execution.root = settings, tmp_path / "replay"
    execution.client = SimpleNamespace(config=SimpleNamespace(max_calls=12))
    execution.budget = SimpleNamespace(state={})
    monkeypatch.setattr(execution, "input_tokens", lambda messages, **_: len(json.dumps(messages)))
    return execution, original


@pytest.mark.parametrize("saved_materials", [False, True])
@pytest.mark.parametrize("run_type", [BenchmarkRun, AlignmentRun])
def test_replay_reopens_saved_prefix_without_future_search_or_original_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved_materials: bool,
    run_type: type[BenchmarkRun],
) -> None:
    execution, original = fixture_run(tmp_path, monkeypatch, run_type)
    bank = original / "banks/owner"
    bank.mkdir(parents=True)
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", original.name, "M", "owner"), "owner", bank / "memory.lock",
            functional_contract="functional_v1", memory_profile="unified_v1",
        )
        ref = service.capture_user("first", "turn:0", "EARLY_BLUE_MARKER")["source_ref"]
        native = service.search_sources("marker")
        native.update(records=[], raw_events=service.sources())
        materials = native["source_materials"]
        if saved_materials:
            execution.settings.update(evidence_policy="question_pack_v1")
            execution.settings["evidence_replay"]["reuse_saved_materials"] = True
            materials = execution._source_first_materials(service, "Which marker?", "Jan 1",
                native, [], snapshot_id="old-pool.json")
            structure, _ = build_query_structure(service, "Which marker?", "Jan 1", [ref],
                policy="incremental", call=lambda *_: {"scope": "DERIVED_BLUE_SCOPE", "nodes": [],
                    "rules": [], "remove": [], "remove_rules": [], "unresolved": []})
            materials.append(structure)
            materials[0]["pre_read_calls"] = 1
            native["material_assembly"]["material_origins"].append("query_structure")
        write_json(original / "native/halumem/owner/0/qa/0/retrieval.json", {
            "native_return": native, "materials": materials, "usage": {},
        })
        service.capture_user("later", "turn:0", "FUTURE_RED_MARKER", occurred_at="1900-01-01")
    before = (bank / "memory.sqlite").read_bytes()

    def forbidden(*_: Any, **__: Any) -> None:
        pytest.fail("Replay must not search, maintain or write ActivationIndex")

    monkeypatch.setattr(MemoryService, "search", forbidden)
    monkeypatch.setattr(MemoryService, "search_sources", forbidden)
    monkeypatch.setattr(ActivationIndex, "record_use", forbidden)
    monkeypatch.setattr(execution, "maintain", forbidden)
    if saved_materials:
        monkeypatch.setattr(execution, "_source_first_materials", forbidden)
    seen: list[list[dict[str, Any]]] = []

    def answer(key: str, messages: list[dict[str, Any]], **_: Any) -> str:
        seen.append(copy.deepcopy(messages))
        assert "EARLY_BLUE_MARKER" in repr(messages)
        assert "FUTURE_RED_MARKER" not in repr(messages)
        assert "GOLD_NOT_FOR_READER" not in repr(messages)
        if saved_materials:
            assert "DERIVED_BLUE_SCOPE" in repr(messages)
        return "EARLY_BLUE_MARKER"

    monkeypatch.setattr(execution, "call", answer)
    result = execution.halumem("predict")
    assert result["complete_answers"] == 1 and result["formation_calls"] == 0
    assert result["retrieval_calls"] == 0 and result["activation_feedback"] is False
    assert (bank / "memory.sqlite").read_bytes() == before
    assert (execution.root / "replay-banks/owner/memory.sqlite").exists()
    assert len(seen) == 1
    if saved_materials:
        replayed = read_json(execution.root / "native/halumem/owner/0/qa/0/retrieval.json")
        assert all("pre_read_calls" not in row for row in replayed["materials"])
        old = read_json(original / "native/halumem/owner/0/qa/0/retrieval.json")
        assert old["materials"][0]["pre_read_calls"] == 1
    execution.halumem("predict")
    assert len(seen) == 1, "A saved replay answer is never regenerated"


@pytest.mark.parametrize("catalog_size", [2, 1000])
def test_retrieved_first_control_excludes_the_cached_interpretation(
    tmp_path, monkeypatch, catalog_size
):
    execution, original = fixture_run(tmp_path, monkeypatch, BenchmarkRun)
    execution.settings.update(evidence_policy="question_pack_v1",
                              evidence_selection_policy="retrieved_first_v1")
    execution.settings["evidence_replay"].update(reuse_saved_materials=True,
                                               exclude_query_structure=True)
    bank = original / "banks/owner"
    bank.mkdir(parents=True)
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, ("edit", original.name, "M", "owner"), "owner",
            bank / "memory.lock", functional_contract="functional_v1", memory_profile="unified_v1")
        ref = service.capture_user("s", "0", "EARLY_BLUE_MARKER")["source_ref"]
        service.capture_user("other", "0", "SECOND_SOURCE_MUST_BE_OPENED")
        native = service.search_sources("EARLY_BLUE_MARKER", include_scope=True)
        native.update(records=[], raw_events=service.sources())
        materials = execution._source_first_materials(service, "Which marker?", "Jan 1",
                                                      native, [], snapshot_id="old-pool.json")
        # Repeated candidates exercise a large index space over the same two real Sources.
        materials.extend(copy.deepcopy(materials[-1]) for _ in range(catalog_size - len(materials)))
        origins = native["material_assembly"]["material_origins"]
        origins.extend(origins[-1] for _ in range(catalog_size - len(origins)))
        structure, _ = build_query_structure(service, "Which marker?", "Jan 1", [ref],
            policy="incremental", call=lambda *_: {
                "scope": "DERIVED_SCOPE_NOT_AVAILABLE", "nodes": [],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []})
        materials.append(structure)
        native["material_assembly"]["material_origins"].append("query_structure")
        write_json(original / "native/halumem/owner/0/qa/0/retrieval.json",
                   {"native_return": native, "materials": materials, "usage": {}})
    calls = []

    def answer(key, messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        assert "DERIVED_SCOPE_NOT_AVAILABLE" not in json.dumps(messages)
        assert len(payload["memories"]) == 1
        assert payload["memories"][0]["kind"] == "original_source"
        assert "EARLY_BLUE_MARKER" in json.dumps(payload["memories"])
        assert "SECOND_SOURCE_MUST_BE_OPENED" not in json.dumps(payload["memories"])
        schema = kwargs["response_format"]["json_schema"]["schema"]
        for field in ("item_indices", "expand_context"):
            spec = schema["properties"][field]
            assert len(json.dumps(spec)) < 120
            validator = Draft202012Validator(spec)
            assert validator.is_valid([0, catalog_size - 1])
            assert not validator.is_valid([-1]) and not validator.is_valid([catalog_size])
        return json.dumps({"answer": "EARLY_BLUE_MARKER", "item_indices": [],
            "expand_context": [], "gap": None, "task": "lookup", "candidate_page": 0})

    monkeypatch.setattr(execution, "call", answer)
    result = execution.halumem("predict")
    assert result["complete_answers"] == 1 and len(calls) == 1
    saved = read_json(execution.root / "predictions/halumem/owner/0/qa/0/complete.json")
    assert saved["query_structure_excluded"] is True
    assert saved["evidence"]["query_structure_in_pool"] == 0


def test_replay_scores_saved_answers_once_preserving_invalid_missing_and_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution, _ = fixture_run(tmp_path, monkeypatch)
    execution.settings["evidence_replay"]["questions"] = [
        {"owner": "owner", "session": 0, "question": index} for index in range(4)
    ]
    dataset = json.loads((tmp_path / "data.jsonl").read_text())
    dataset["sessions"][0]["questions"] *= 4
    (tmp_path / "data.jsonl").write_text(json.dumps(dataset) + "\n")
    for index, answer in enumerate(["correct", "invalid", None]):
        write_json(execution.root / f"predictions/halumem/owner/0/qa/{index}/complete.json", {
            "hypothesis": answer, "execution": "missing" if answer is None else "answered",
            "evidence": {}, "prediction_cost": {}, "shared_cost": {},
        })
    calls = []

    class Official:
        def __init__(self, *_: Any) -> None:
            pass

        def score(self, name: str, *args: str) -> dict[str, Any]:
            calls.append((name, args))
            execution._judge_serial += 1
            return {"evaluation_result": "Correct"} if args[-1] == "correct" else {}

        aggregate_qa_results = staticmethod(HaluMemOfficial.aggregate_qa_results)

    monkeypatch.setattr(evidence_replay, "HaluMemOfficial", Official)
    result = evidence_replay.replay_halumem(execution, "score")
    assert result["planned_opportunities"] == 4 and result["opportunities"] == 3
    assert result["correct"] == 1 and result["missing"] == 1 and result["not_run"] == 1
    assert result["labels"] == {"Correct": 1, "invalid": 1}
    scored = read_json(execution.root / "halumem-official-results.json")
    assert scored["overall_score"]["question_answering"]["correct_qa_ratio(all)"] == 1 / 3
    assert len(calls) == 2
    evidence_replay.replay_halumem(execution, "score")
    assert len(calls) == 2
