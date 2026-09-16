"""Finalize the corrected DG11-PE02 baseline smoke without opening paper labels."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from tokenizers import Tokenizer

from evals.paper.adapters import OracleAdapter
from evals.paper.contracts import MemoryEvent, read_context_archive
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs
from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
LONGMEMEVAL_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval")
OFFICIAL_RETRIEVAL = LONGMEMEVAL_ROOT / "src/retrieval/run_retrieval.py"
OFFICIAL_GENERATION = LONGMEMEVAL_ROOT / "src/generation/run_generation.py"
EXPECTED_COMMIT = "9e0b455f4ef0e2ab8f2e582289761153549043fc"
EXPECTED_DENSE_WEIGHTS = (
    "d0b6e2516913f812360475154323f50e2b1e1da0ce6a435175e08f218784c6fb"
)
EXPECTED_DENSE_TOKENIZER = (
    "5fd1c882abbd30517dced455a2c9768945ec726b96727927e4959348d9de550b"
)


class PE02FinalizeError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _corpus(case: LongMemEvalCase, granularity: str) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    source_ids: list[str] = []
    for session in case.sessions:
        if granularity == "session":
            text = " ".join(
                turn.content for turn in session.turns if turn.role == "user"
            )
            if text:
                texts.append(text)
                source_ids.append(session.session_id)
            continue
        for turn_index, turn in enumerate(session.turns):
            if turn.role == "user":
                texts.append(turn.content)
                source_ids.append(f"{session.session_id}:{turn_index}")
    return texts, source_ids


def _bm25_parity(
    *,
    cases: tuple[LongMemEvalCase, ...],
    records: dict[tuple[str, str], Any],
) -> dict[str, Any]:
    rank_bm25 = importlib.import_module("rank_bm25")
    max_abs_error = 0.0
    compared_scores = 0
    for case in cases:
        for method_id, granularity in (
            ("LME-BM25-S", "session"),
            ("LME-BM25-T", "turn"),
        ):
            texts, source_ids = _corpus(case, granularity)
            scorer = rank_bm25.BM25Okapi([text.split(" ") for text in texts])
            scores = np.asarray(scorer.get_scores(case.question.split(" ")))
            ranking = np.argsort(scores)[::-1][:3]
            expected_ids = [source_ids[int(index)] for index in ranking]
            record = records[(case.source_id, method_id)]
            observed_ids = [str(item["source_id"]) for item in record.trace]
            if observed_ids != expected_ids or list(record.source_ids) != expected_ids:
                raise PE02FinalizeError(
                    f"official BM25 ranking parity failed: {case.source_id}/{method_id}"
                )
            for item, index in zip(record.trace, ranking, strict=True):
                difference = abs(float(item["score"]) - float(scores[int(index)]))
                max_abs_error = max(max_abs_error, difference)
                compared_scores += 1
    if max_abs_error > 5.1e-9:
        raise PE02FinalizeError("official BM25 score parity exceeded rounding bound")
    return {
        "case_count": len(cases),
        "compared_scores": compared_scores,
        "implementation": f"rank-bm25=={importlib.metadata.version('rank-bm25')}",
        "max_abs_error_after_9_decimal_archive_rounding": max_abs_error,
        "status": "PASS",
        "tokenization": "literal-space split",
    }


def _oracle_smoke(tokenizer_path: Path) -> dict[str, Any]:
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    adapter = OracleAdapter(
        token_counter=lambda value: len(tokenizer.encode(value).ids)
    )
    adapter.reset("pe02-synthetic-oracle", "synthetic-case")
    adapter.set_oracle_source_ids(["session-evidence"])
    adapter.ingest(
        MemoryEvent(
            event_id="session-distractor:0",
            content="irrelevant",
            observed_at="2026-01-01T00:00:00Z",
            actor="user",
            scope="pe02-synthetic",
            metadata={"session_id": "session-distractor", "turn_index": 0},
        )
    )
    adapter.ingest(
        MemoryEvent(
            event_id="session-evidence:0",
            content="the synthetic answer is blue",
            observed_at="2026-01-02T00:00:00Z",
            actor="user",
            scope="pe02-synthetic",
            metadata={"session_id": "session-evidence", "turn_index": 0},
        )
    )
    adapter.finalize()
    result = adapter.query(
        "what is the synthetic answer?",
        "2026-01-03T00:00:00Z",
        512,
        "ORACLE_UPPER_BOUND",
    )
    adapter.close()
    if result.source_ids != ("session-evidence",) or "blue" not in result.context:
        raise PE02FinalizeError("synthetic oracle upper-bound smoke failed")
    return {
        "declared_tokens": result.declared_tokens,
        "label_access": "SYNTHETIC_UPPER_BOUND_ONLY",
        "paper_labels_opened": False,
        "status": "PASS",
    }


def run(
    *,
    run_id: str,
    inputs: Path,
    controlled_archive: Path,
    dense_archive: Path,
    characterization_archive: Path,
    tokenizer_path: Path,
    output: Path,
) -> dict[str, Any]:
    _partition, cases = load_inputs(inputs)
    if not 5 <= len(cases) <= 10:
        raise PE02FinalizeError("PE02 smoke must use five to ten opened cases")
    controlled = read_context_archive(controlled_archive)
    dense = read_context_archive(dense_archive)
    characterization = read_context_archive(characterization_archive)
    controlled_by_pair = {
        (record.case_id, record.method_id): record for record in controlled
    }
    expected_controlled = {
        (case.source_id, method)
        for case in cases
        for method in (
            "CTRL-NONE",
            "CTRL-CUSTOM-LEX1",
            "LME-BM25-S",
            "LME-BM25-T",
        )
    }
    if set(controlled_by_pair) != expected_controlled or any(
        record.terminal_status != "SUCCEEDED" for record in controlled
    ):
        raise PE02FinalizeError("controlled smoke denominator or terminal drifted")
    dense_by_pair = {(record.case_id, record.method_id): record for record in dense}
    if set(dense_by_pair) != {(case.source_id, "LME-DENSE") for case in cases} or any(
        record.terminal_status != "SUCCEEDED" for record in dense
    ):
        raise PE02FinalizeError("dense smoke denominator or terminal drifted")
    characterization_by_pair = {
        (record.case_id, record.method_id): record for record in characterization
    }
    if set(characterization_by_pair) != {
        (case.source_id, method)
        for case in cases
        for method in ("CTRL-FULL", "CTRL-TRUNC-FULL")
    }:
        raise PE02FinalizeError("long-context smoke denominator drifted")
    full_records = [
        record for record in characterization if record.method_id == "CTRL-FULL"
    ]
    truncated_records = [
        record for record in characterization if record.method_id == "CTRL-TRUNC-FULL"
    ]
    if any(
        record.terminal_status != "CAPABILITY_UNSUPPORTED"
        or record.usage.get("failure") != "CONTEXT_LIMIT_EXCEEDED"
        for record in full_records
    ) or any(
        record.terminal_status != "SUCCEEDED"
        or not record.context
        or record.declared_tokens > 512
        for record in truncated_records
    ):
        raise PE02FinalizeError("full/truncated characterization semantics drifted")
    memory_records = [
        record for record in (*controlled, *dense) if record.method_id != "CTRL-NONE"
    ]
    if any(
        not record.context
        or record.declared_tokens > 512
        or any(
            "answer" in source_id or "noans" in source_id
            for source_id in record.source_ids
        )
        for record in memory_records
    ):
        raise PE02FinalizeError("model-visible context or source-ID safety drifted")
    dense_envelope = json.loads(dense_archive.read_text(encoding="utf-8"))
    dense_identity = dense_envelope.get("embedder_identity")
    if (
        not isinstance(dense_identity, dict)
        or dense_identity.get("weights_sha256") != EXPECTED_DENSE_WEIGHTS
        or dense_identity.get("tokenizer_sha256") != EXPECTED_DENSE_TOKENIZER
        or dense_envelope.get("status") != "PASS"
        or dense_envelope.get("paper_labels_opened") is not False
    ):
        raise PE02FinalizeError("dense smoke identity drifted")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=LONGMEMEVAL_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != EXPECTED_COMMIT:
        raise PE02FinalizeError("LongMemEval commit drifted")
    result: dict[str, Any] = {
        "baselines": {
            "CTRL-FULL": {
                "case_count": len(full_records),
                "context_limit_exceeded": len(full_records),
                "status": "PASS_CONDITIONAL_NOT_APPLICABLE",
                "track": "LONG_CONTEXT_CHARACTERIZATION",
            },
            "CTRL-TRUNC-FULL": {
                "case_count": len(truncated_records),
                "status": "PASS",
                "track": "LONG_CONTEXT_CHARACTERIZATION",
            },
            "LME-BM25-S/T": _bm25_parity(cases=cases, records=controlled_by_pair),
            "LME-DENSE": {
                "case_count": len(dense),
                "identity": dense_identity,
                "status": "PASS",
            },
            "LME-ORACLE": _oracle_smoke(tokenizer_path),
        },
        "case_count": len(cases),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_ai_reviews": 0,
        "failed_smoke_disclosure": [
            {
                "failure": "duplicate raw benchmark session ID before occurrence-aware pseudonymization",
                "model_loaded": False,
                "provider_requests": 0,
                "run_id": "pe04-harness-smoke-20260824-001",
            },
            {
                "failure": "Python 3.10 lacked StrEnum",
                "model_loaded": False,
                "provider_requests": 0,
                "run_id": "pe02-baseline-smoke-20260824-002",
            },
            {
                "failure": "Python 3.10 lacked datetime.UTC",
                "model_loaded": False,
                "provider_requests": 0,
                "run_id": "pe02-baseline-smoke-20260824-003",
            },
        ],
        "gates": {
            "bm25_official_parity": True,
            "dense_baseline_ready": True,
            "full_history_semantics_ready": True,
            "model_visible_context_nonempty": True,
            "oracle_upper_bound_ready": True,
            "paper_labels_opened": False,
            "raw_answer_marker_absent_from_source_ids": True,
        },
        "inputs": {
            "path": str(inputs.resolve()),
            "sha256": sha256_file(inputs),
        },
        "longmemeval": {
            "commit": commit,
            "official_generation_sha256": sha256_file(OFFICIAL_GENERATION),
            "official_retrieval_sha256": sha256_file(OFFICIAL_RETRIEVAL),
        },
        "paper_labels_opened": False,
        "provider_answer_calls": 0,
        "run_id": run_id,
        "schema": "milai.dg11.paper-official-baseline-smoke.v1",
        "source_artifacts": {
            "characterization_contexts_sha256": sha256_file(characterization_archive),
            "controlled_contexts_sha256": sha256_file(controlled_archive),
            "dense_contexts_sha256": sha256_file(dense_archive),
        },
        "status": "PASS",
        "work_package": "DG11-PE02",
    }
    _atomic_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--controlled-contexts", type=Path, required=True)
    parser.add_argument("--dense-contexts", type=Path, required=True)
    parser.add_argument("--characterization-contexts", type=Path, required=True)
    parser.add_argument(
        "--tokenizer", type=Path, default=Path("/cra/qwen36-35B/tokenizer.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        inputs=args.inputs.resolve(),
        controlled_archive=args.controlled_contexts.resolve(),
        dense_archive=args.dense_contexts.resolve(),
        characterization_archive=args.characterization_contexts.resolve(),
        tokenizer_path=args.tokenizer.resolve(),
        output=args.output.resolve(),
    )
    print(json.dumps({"run_id": result["run_id"], "status": result["status"]}))


if __name__ == "__main__":
    main()
