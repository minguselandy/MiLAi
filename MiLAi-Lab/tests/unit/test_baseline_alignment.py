"""The aligned entry reuses the online loop and never sends evaluator fields to backends."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from milai_lab.contracts.memory_backend import IngestionResult, MemorySession, RetrievalResult
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners import edit_benchmarks
from milai_lab.runners.baseline_alignment import (
    BACKENDS,
    AlignmentRun,
    alignment_settings,
    prepare_alignment,
    run_alignment_arm,
)


def configuration() -> dict[str, Any]:
    return read_json(Path(__file__).parents[2] / "configs/milai-baseline-alignment-local-v1.json")


def source_user() -> dict[str, Any]:
    sessions = []
    for index in (1, 0):
        clock = f"Jan 0{index + 1}, 2025, 12:00:00"
        sessions.append({
            "start_time": clock, "end_time": clock,
            "dialogue": [{"role": "user", "content": f"actual source {index}",
                          "timestamp": clock, "has_answer": True}],
            "memory_points": [{"memory_content": "PRIVATE REFERENCE", "is_update": "False",
                               "memory_type": "event", "memory_source": "dialogue",
                               "importance": 1, "original_memories": []}],
            "questions": [{"question": f"query {index}", "answer": "PRIVATE ANSWER",
                           "evidence": []}],
        })
    return {"uuid": "opaque-owner", "persona_info": "PRIVATE PERSONA", "sessions": sessions}


class ActualReturnBackend:
    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.events: list[tuple[str, int]] = []

    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult:
        self.history.append({"session_id": session.session_id, "date": session.date,
                             "turns": session.turns})
        self.events.append(("ingest", len(self.history)))
        return {"session_id": session.session_id, "completed": True,
                "native_return": {"settled": True}, "session_output": None,
                "usage": {"status": "unobserved"}}

    def retrieve(self, question: str, date: str, *, key: str, limit: int) -> RetrievalResult:
        self.events.append((question, len(self.history)))
        return {"materials": copy.deepcopy(self.history), "native_return": self.history,
                "returned_count": len(self.history), "source_mapping": "original-sessions",
                "usage": {"status": "unobserved"}}

    def close(self) -> None:
        pass


def test_prepare_keeps_qa_and_update_budgets_and_opaque_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from milai_lab.runners import baseline_alignment

    monkeypatch.setattr(baseline_alignment, "halumem_users", lambda *_: [source_user()])
    config = configuration()
    root = tmp_path / "prepared"
    first = prepare_alignment(config, root)
    assert first["per_backend_opportunities"] == {"sessions": 2, "qa": 2, "native_updates": 0}
    assert first["per_user_opportunities"]["opaque-owner"]["session_ordinals"] == [1, 0]
    banks = [first["bank_ids"][backend]["opaque-owner"] for backend in BACKENDS]
    assert len(set(banks)) == 3
    assert all("opaque-owner" not in bank for bank in banks)
    assert first == prepare_alignment(config, root)
    assert not (root / "banks").exists() and not (root / "http").exists()
    other = prepare_alignment(config, tmp_path / "independent")
    assert other["bank_ids"] != first["bank_ids"]
    settings = alignment_settings(config, "MiLAi-memory-only")
    assert settings["retrieval_limit"] == 20 and settings["alignment"]["update_top_k"] == 10
    assert settings["memory_view_mode"] == "direct"
    assert settings["maintenance_recipe"] == "extract_then_edit"


def test_existing_online_loop_delivers_only_current_observed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = configuration()
    settings = alignment_settings(config, "RawRAG-local")
    settings["halumem"]["users"] = ["opaque-owner"]
    monkeypatch.setattr(edit_benchmarks, "halumem_users", lambda *_: [source_user()])
    execution = AlignmentRun.__new__(AlignmentRun)
    execution.settings, execution.root, execution.phase = settings, tmp_path, "predict"
    execution.backends = {}
    backend = ActualReturnBackend()
    monkeypatch.setattr(execution, "_backend", lambda _: backend)
    monkeypatch.setattr(execution, "_semantic_retriever", lambda: None)
    delivered = []

    def answer(question: str, date: str, key: str, materials: list[dict[str, Any]]) -> Any:
        delivered.append(copy.deepcopy(materials))
        return "scripted answer", materials

    monkeypatch.setattr(execution, "answer_material", answer)
    result = execution.halumem("predict")
    assert result["sessions"] == 2 and result["complete_answers"] == 2
    assert result["judge_calls"] == 0
    assert backend.events == [("ingest", 1), ("query 0", 1), ("ingest", 2), ("query 1", 2)]
    assert len(delivered[0]) == 1 and len(delivered[1]) == 2
    for session in backend.history:
        assert set(session) == {"session_id", "date", "turns"}
        assert set(session["turns"][0]) == {"role", "content", "timestamp"}
    assert "PRIVATE" not in repr(backend.history)
    assert "query" not in repr(backend.history) and "scripted answer" not in repr(backend.history)
    saved = read_json(tmp_path / "halumem-predictions.json")
    assert [row["session"] for row in saved] == [1, 0]
    assert all(row["extracted_memories"] == [] for row in saved)
    assert not (tmp_path / "http").exists()


def test_score_requires_all_declared_predictions(tmp_path: Path) -> None:
    config = configuration()
    write_json(tmp_path / "alignment-prepared.json", {
        "configuration": config,
        "bank_ids": {backend: {} for backend in BACKENDS},
    })
    write_json(tmp_path / BACKENDS[0] / "terminal-predict.json", {"status": "PREDICTIONS_SAVED"})
    with pytest.raises(ValueError, match="Every declared backend"):
        run_alignment_arm(config, tmp_path, BACKENDS[0], "score")
    assert not (tmp_path / BACKENDS[0] / "actual-config.json").exists()
