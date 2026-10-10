"""Whole-exchange RawRAG using the LongMemEval flat-BM25 route.

The author's ``process_item_flat_index`` indexes user text at session/turn
granularity; its BM25 route uses ``rank_bm25.BM25Okapi`` with space splitting
and descending NumPy argsort. We retain those choices without answer-location
labels, and deliver the complete original exchange rather than the index key.
This is a local adaptation, not a reproduction of the author's model scores.
Author source: xiaowu0162/LongMemEval, commit
9e0b455f4ef0e2ab8f2e582289761153549043fc, src/retrieval/run_retrieval.py.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal

from milai_lab.contracts.memory_backend import IngestionResult, MemorySession, RetrievalResult

BM25_VERSION = "0.2.2"


class RawRAGLocal:
    """Persist only arrived sessions in one backend/user/repetition bank.

    No generation, embedding, Selector, summary, task quota, character truncation,
    or answer write-back occurs here. The caller checks complete Reader capacity.
    ``root`` and ``bank_id`` must identify an isolated experimental instance.
    """

    def __init__(
        self, root: str | Path, *, bank_id: str,
        granularity: Literal["session", "turn"] = "session",
    ) -> None:
        if not bank_id or granularity not in {"session", "turn"}:
            raise ValueError("RAWRAG_BANK_OR_GRANULARITY_INVALID")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.bank_id, self.granularity = bank_id, granularity
        self.db = sqlite3.connect(self.root / "rawrag.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS binding (value TEXT NOT NULL)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sessions "
            "(ordinal INTEGER PRIMARY KEY, session_id TEXT UNIQUE NOT NULL, "
            "date TEXT NOT NULL, turns TEXT NOT NULL)"
        )
        binding = json.dumps({"bank_id": bank_id, "granularity": granularity,
                              "retriever": "flat-bm25", "rank_bm25": BM25_VERSION})
        stored = self.db.execute("SELECT value FROM binding").fetchone()
        if stored is not None and stored[0] != binding:
            self.db.close()
            raise ValueError("RAWRAG_BANK_BINDING_CHANGED")
        if stored is None:
            self.db.execute("INSERT INTO binding VALUES (?)", (binding,))
        self.db.commit()

    def ingest(self, session: MemorySession, *, key: str) -> IngestionResult:
        # Only the already projected source fields cross this boundary.
        turns = [{field: turn[field] for field in ("role", "content", "timestamp")}
                 for turn in session.turns]
        serialized = json.dumps(turns, ensure_ascii=False)
        stored = self.db.execute(
            "SELECT date, turns FROM sessions WHERE session_id = ?", (session.session_id,),
        ).fetchone()
        if stored is not None and stored != (session.date, serialized):
            raise ValueError("RAWRAG_SESSION_ID_REUSED_WITH_DIFFERENT_SOURCE")
        if stored is None:
            self.db.execute(
                "INSERT INTO sessions (session_id, date, turns) VALUES (?, ?, ?)",
                (session.session_id, session.date, serialized),
            )
            self.db.commit()
        return {
            "session_id": session.session_id, "completed": True,
            "native_return": {"bank_id": self.bank_id, "session_id": session.session_id,
                              "stored": True, "already_stored": stored is not None,
                              "turn_count": len(turns)},
            "session_output": None,
            "usage": {"generation_tokens": 0, "embedding_tokens": 0,
                      "retrieval": "local_bm25", "request_key": key},
        }

    def _units(self) -> list[dict[str, Any]]:
        units = []
        for session_id, date, serialized in self.db.execute(
            "SELECT session_id, date, turns FROM sessions ORDER BY ordinal"
        ):
            turns = json.loads(serialized)
            if self.granularity == "session":
                units.append({"id": session_id, "session_id": session_id, "date": date,
                              "turns": turns,
                              "index_text": " ".join(
                                  row["content"] for row in turns if row["role"] == "user"),
                              "turn_range": [0, len(turns)]})
            else:
                starts = [i for i, row in enumerate(turns) if row["role"] == "user"]
                for start, end in zip(starts, [*starts[1:], len(turns)], strict=True):
                    units.append({"id": f"{session_id}_{start + 1}", "session_id": session_id,
                                  "date": date, "turns": turns[start:end],
                                  "index_text": turns[start]["content"],
                                  "turn_range": [start, end]})
        return units

    def retrieve(self, question: str, date: str, *, key: str, limit: int) -> RetrievalResult:
        if type(limit) is not int or limit < 1:
            raise ValueError("RAWRAG_RETURN_LIMIT_INVALID")
        units = self._units()
        ranked: list[dict[str, Any]] = []
        if units:
            # Optional dependency; importing the Lab core never imports this package.
            from importlib import import_module
            from importlib.metadata import version

            import numpy as np
            BM25Okapi = import_module("rank_bm25").BM25Okapi

            if version("rank-bm25") != BM25_VERSION:
                raise ValueError("RAWRAG_BM25_VERSION_CHANGED")
            bm25 = BM25Okapi([row["index_text"].split(" ") for row in units])
            scores = bm25.get_scores(question.split(" "))
            ranked = [{**units[int(index)], "score": float(scores[index])}
                      for index in np.argsort(scores)[::-1][:limit]]
        materials = [
            {"id": row["id"], "session_id": row["session_id"], "date": row["date"],
             "text": json.dumps(row["turns"], ensure_ascii=False), "turns": row["turns"],
             "turn_range": row["turn_range"], "score": row["score"],
             "provenance": "original_exchange", "truncated": False}
            for row in ranked
        ]
        return {
            "materials": materials,
            "native_return": {"results": ranked, "query_timestamp": date,
                              "retriever": "flat-bm25", "granularity": self.granularity,
                              "requested_count": limit, "indexed_count": len(units)},
            "returned_count": len(ranked), "source_mapping": "original_session_and_turn_range",
            "usage": {"generation_tokens": 0, "embedding_tokens": 0,
                      "retrieval": "local_bm25", "request_key": key},
        }

    def close(self) -> None:
        self.db.close()
