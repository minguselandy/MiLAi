"""Prepare original-source static transfer tasks for the memory-control Reader."""

from __future__ import annotations

import argparse
import sqlite3
import time
import zlib
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from milai_lab.datasets.edit_benchmarks import history_components, longmemeval_history
from milai_lab.datasets.memory_control_reader_task import (
    LONGMEMEVAL_S,
    MEMORYAGENTBENCH_EVENTQA,
    ReaderTask,
)
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import SCHEMA, dumps
from milai_lab.datasets.memory_control_views import insert_views, tokenize_path
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.dataset_reader import DatasetReader
from milai_lab.methods.evidence_reading import project_pack
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import episode_before_reader, make_policy

PROTOCOL = "external_static_source_v1"


@dataclass(frozen=True)
class Turn:
    body: str
    role: str
    session: int
    reported_at: str | None


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    stratum: str
    ordinal: int


@dataclass(frozen=True)
class History:
    group: str
    source: str
    turns: tuple[Turn, ...]
    questions: tuple[Question, ...]


def longmemeval_case(raw: dict[str, Any], group: str, ordinal: int) -> History:
    sessions = longmemeval_history(raw)
    turns = tuple(
        Turn(turn["content"], turn["role"], index, session.date)
        for index, session in enumerate(sessions)
        for turn in session.turns
    )
    question = Question(
        raw["question_id"],
        f"Question date: {raw['question_date']}\nQuestion: {raw['question']}",
        raw["question_type"],
        ordinal,
    )
    return History(group, LONGMEMEVAL_S, turns, (question,))


def longmemeval_histories(path: Path, exposure: Path) -> tuple[dict[str, Any], Iterator[History]]:
    raw = read_json(path)
    previous = read_json(exposure)
    ids = [row["question_id"] for row in raw]
    if (
        len(ids) != len(set(ids))
        or previous["remaining_unexposed_candidate_count"] != 0
        or set(ids) != set(previous["prior_scored_case_ids"])
        or len(ids) != previous["population"]
    ):
        raise ValueError("Use the released Small questions in the verified prior exposure roster")
    groups = {
        key: f"history-component-{i}"
        for i, keys in enumerate(history_components(raw))
        for key in keys
    }
    return (
        {"scope": "previously_evaluated_external_regression", "exposure_receipt": str(exposure)},
        (longmemeval_case(row, groups[row["question_id"]], i) for i, row in enumerate(raw, 1)),
    )


def eventqa_histories(path: Path) -> tuple[dict[str, Any], Iterator[History]]:
    doc = read_json(path)
    if (doc["dataset"], doc["split"], doc["source"]) != (
        "ai-hyz/MemoryAgentBench",
        "Accurate_Retrieval",
        "eventqa_full",
    ):
        raise ValueError("Use the released full EventQA contexts and question IDs")
    rows = doc["contexts"]
    if len({row["source_row"] for row in rows}) != len(rows):
        raise ValueError("EventQA source rows must be unique")

    def histories() -> Iterator[History]:
        ordinal = 0
        for row in rows:
            group = f"eventqa-full-row-{row['source_row']}"
            parts = row["context"].splitlines(keepends=True)
            ids = row["qa_pair_ids"]
            if len(set(ids)) != len(ids):
                raise ValueError("EventQA QA identities must be unique within each context")
            questions = []
            for key, query in zip(ids, row["questions"], strict=True):
                ordinal += 1
                questions.append(Question(f"{group}/{key}", query, group, ordinal))
            yield History(
                group,
                MEMORYAGENTBENCH_EVENTQA,
                tuple(Turn(part, "reference", 0, None) for part in parts),
                tuple(questions),
            )

    return (
        {"scope": "public_external_static_transfer", "source_revision": doc["source_revision"]},
        histories(),
    )


class ExternalPool(CorpusPool):
    """Add released public dates while preserving literal original source text."""

    def __init__(self, db: sqlite3.Connection, turns: tuple[Turn, ...]) -> None:
        self.turns = turns
        super().__init__(db, 1)

    def source(self, ref: str) -> dict[str, Any] | None:
        result = super().source(ref)
        if result is not None:
            result["occurred_at"] = self.turns[self.by_ref[ref].position].reported_at
        return result


_reader: DatasetReader | None = None
_material_limit = 0


def _load_capacity(config: Path, limit: int) -> None:
    global _reader, _material_limit
    _reader, _material_limit = DatasetReader(config), limit


def full_history_capacity(history: History) -> dict[str, Any]:
    reader = _reader
    assert reader is not None
    question = history.questions[0]
    all_turns = [
        {
            "source_ref": f"s{i}",
            "role": t.role,
            "origin": "dialogue" if history.source == LONGMEMEVAL_S else "reference_document",
            "content": t.body,
            "range": [0, len(t.body)],
            "occurred_at": t.reported_at,
        }
        for i, t in enumerate(history.turns)
    ]
    evidence = project_pack({"kind": "original_source", "text": dumps(all_turns)}, 0)
    packet = reader.plan([evidence], ReaderTask(history.source, question.text), _material_limit)
    return {
        "group": history.group,
        "questions": len(history.questions),
        "capacity_probe": question.key,
        "source_units": len(history.turns),
        "characters": sum(len(t.body) for t in history.turns),
        "material_tokens": packet.material_tokens,
        "material_fits": packet.material_fits,
        "host_fits_for_probe": packet.host_fits,
        "failure_reason": packet.failure_reason,
        "prompt_tokens_for_probe": packet.capacity["prompt_tokens"] if packet.capacity else None,
    }


def _scratch_db(history: History, dataset: MemoryControlDataset, path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("CREATE TABLE task_navigation (task_id INTEGER PRIMARY KEY, excerpts BLOB NOT NULL)")
    db.execute(
        "INSERT INTO roots (id,dataset,native_group,raw_path,location) VALUES (1,?,?,?,?)",
        (history.source, history.group, str(path), "{}"),
    )
    db.executemany(
        """
        INSERT INTO objects (root_id,position,kind,role,location,preview,body,characters,block)
        VALUES (1,?,?,?,?,?,?,?,?)
        """,
        (
            (
                i,
                "message" if history.source == LONGMEMEVAL_S else "paragraph",
                turn.role,
                "{}",
                "",
                zlib.compress(turn.body.encode(), 1),
                len(turn.body),
                turn.session,
            )
            for i, turn in enumerate(history.turns)
        ),
    )
    db.executemany(
        """
        INSERT INTO tasks (id,root_id,split,source_row,native_id,query,setting)
        VALUES (?,1,'external',?,? ,?,'static')
        """,
        ((q.ordinal, q.ordinal, q.key, q.text) for q in history.questions),
    )
    source_rows = db.execute("SELECT * FROM objects ORDER BY position").fetchall()
    encoder = dataset.encoder_tokenizer or tokenize_path(dataset.tokenizers["encoder"]["path"])
    insert_views(db, source_rows, dataset.reader, encoder, dataset.config["views"])
    return db


def make_external_arm(name: str, checkpoint: Path | None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": name,
        "policy": name,
        "observation_protocol": "semantic_nav_v1",
        "reads": 4,
        "stop": "fixed",
        "precision": "learned",
    }
    if checkpoint is not None:
        run = read_json(checkpoint.parent / "run.json")
        if run["status"] != "COMPLETED" or not (checkpoint / "weights.pt").is_file():
            raise ValueError("External transfer requires an actual completed fit")
        contract = run["contract"]
        config.update(
            policy="checkpoint",
            checkpoint=str(checkpoint.resolve()),
            seed=contract["seed"],
            observation_protocol=contract["observation_protocol"],
            stop="fixed" if contract["supervision_mode"] == "weak" else "learned",
        )
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--source", choices=("longmemeval", "eventqa"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--exposure", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_subparsers(dest="command", required=True)
    capacity = modes.add_parser("capacity")
    capacity.add_argument("--workers", type=int, default=1)
    prepare = modes.add_parser("prepare")
    variants = prepare.add_mutually_exclusive_group(required=True)
    variants.add_argument("--baseline", choices=("B0", "B1", "B2", "B3", "B4"))
    variants.add_argument("--checkpoint", type=Path)
    prepare.add_argument("--per-stratum", type=int)
    prepare.add_argument("--device", default="cpu")
    args = parser.parse_args()
    if args.source == "longmemeval":
        if args.exposure is None:
            parser.error("provide the prior exposure roster for LongMemEval")
        provenance, histories = longmemeval_histories(args.input, args.exposure)
    else:
        provenance, histories = eventqa_histories(args.input)
    arm = None
    if args.command == "prepare":
        name = args.baseline or args.checkpoint.parent.name
        arm = make_external_arm(name, args.checkpoint)
    dataset = MemoryControlDataset(
        args.data, observation_protocol=arm["observation_protocol"] if arm is not None else None
    )
    host, revision = dataset.host, dataset.revision
    assert host is not None and revision is not None
    budget = revision["primary_budget"]
    started = time.perf_counter()
    output: dict[str, Any] = {
        "protocol": PROTOCOL,
        "source": args.source,
        "input": str(args.input.resolve()),
        "provenance": provenance,
        "material_budget": budget,
        "reference_run_id": dataset.run_id,
        "reader_requests": 0,
        "optimizer_updates": 0,
        "sha_validation": False,
    }
    if args.command == "capacity":
        if args.workers < 1:
            parser.error("use a positive worker count")
        if args.workers == 1:
            _load_capacity(host.config_path, budget)
            counts = list(map(full_history_capacity, histories))
        else:
            with ProcessPoolExecutor(
                max_workers=args.workers,
                mp_context=get_context("spawn"),
                initializer=_load_capacity,
                initargs=(host.config_path, budget),
            ) as pool:
                counts = list(pool.map(full_history_capacity, histories))
        output.update(
            status="CAPACITY_MEASURED",
            histories=counts,
            native_groups=len({x["group"] for x in counts}),
            position_count=sum(x["questions"] for x in counts),
            host_capacity_probes=len(counts),
            host_capacity_probes_exceeded=sum(x["host_fits_for_probe"] is False for x in counts),
            positions_full_material_exceeded=sum(
                x["questions"] for x in counts if not x["material_fits"]
            ),
        )
    else:
        per_stratum = args.per_stratum
        if per_stratum is not None and per_stratum < 1:
            parser.error("use a positive per-stratum diagnostic count")
        assert arm is not None
        policy, model = make_policy(dataset, arm, args.device)
        by_stratum: Counter[str] = Counter()
        available = 0
        results = []
        for history in histories:
            available += len(history.questions)
            candidates = []
            for q in history.questions:
                if per_stratum is None or by_stratum[q.stratum] < per_stratum:
                    candidates.append(q)
                    by_stratum[q.stratum] += 1
            if not candidates:
                continue
            with closing(_scratch_db(history, dataset, args.input)) as db:
                corpus = ExternalPool(db, history.turns)
                for q in candidates:
                    task = db.execute(
                        "SELECT * FROM task_index WHERE id=?", (q.ordinal,)
                    ).fetchone()
                    seed = (revision["seed"] + q.ordinal) % (2**31 - 1)
                    record = episode_before_reader(
                        dataset, db, task, arm, policy, model, budget, seed, pool=corpus
                    )
                    record.update(native_question_id=q.key, question_stratum=q.stratum)
                    path = args.output.parent / args.output.stem / f"{q.ordinal}.json"
                    write_json(path, record)
                    results.append(
                        {
                            "native_question_id": q.key,
                            "status": record["status"],
                            "group": history.group,
                            "episode": str(path),
                        }
                    )
        output.update(
            status="PREPARED",
            arm=arm,
            episodes=results,
            by_stratum=dict(by_stratum),
            position_count=len(results),
            registered_positions=available,
            per_stratum=per_stratum,
            native_groups=len({x["group"] for x in results}),
            by_status=dict(Counter(x["status"] for x in results)),
        )
    output["wall_seconds"] = time.perf_counter() - started
    write_json(args.output, output)
    print(f"External {args.command} receipt at {args.output}")


if __name__ == "__main__":
    main()
