"""Build label-free LongMemEval paper inputs using an explicit field allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from evals.paper.datasets.longmemeval import pseudonymize_session_id

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = Path(
    "/cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
)
DEFAULT_SOURCE_IDS = ROOT / "var/dg11/splits/v1/paper-test-v1/source-ids.json"
DEFAULT_HOLDOUT = ROOT / "var/dg11/paper/freeze/longmemeval-holdout-inputs.json"
DEFAULT_FULL = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
FORBIDDEN_KEYS = frozenset(
    {"answer", "answers", "answer_session_ids", "gold_answers", "has_answer"}
)


class PaperInputError(RuntimeError):
    pass


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            value,
            handle,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _case(row: dict[str, Any]) -> dict[str, Any]:
    source_id = row.get("question_id")
    session_ids = row.get("haystack_session_ids")
    dates = row.get("haystack_dates")
    sessions = row.get("haystack_sessions")
    if (
        not isinstance(source_id, str)
        or not isinstance(row.get("question_type"), str)
        or not isinstance(row.get("question"), str)
        or not isinstance(row.get("question_date"), str)
        or not isinstance(session_ids, list)
        or not isinstance(dates, list)
        or not isinstance(sessions, list)
        or len(session_ids) != len(dates)
        or len(session_ids) != len(sessions)
    ):
        raise PaperInputError("LongMemEval input row contract drifted")
    rendered_sessions: list[dict[str, Any]] = []
    for occurrence, (session_id, observed_at, turns) in enumerate(
        zip(session_ids, dates, sessions, strict=True)
    ):
        if not isinstance(turns, list) or not turns:
            raise PaperInputError("LongMemEval session contract drifted")
        rendered_turns: list[dict[str, str]] = []
        for turn in turns:
            if not isinstance(turn, dict):
                raise PaperInputError("LongMemEval turn contract drifted")
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise PaperInputError("LongMemEval turn role/content drifted")
            rendered_turns.append({"content": content, "role": role})
        rendered_sessions.append(
            {
                "observed_at": str(observed_at),
                "session_id": pseudonymize_session_id(
                    source_id, str(session_id), occurrence
                ),
                "turns": rendered_turns,
            }
        )
    return {
        "category": row["question_type"],
        "question": row["question"],
        "question_date": row["question_date"],
        "sessions": rendered_sessions,
        "source_id": source_id,
    }


def _contains_forbidden(value: object) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_KEYS.intersection(value)) or any(
            _contains_forbidden(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False


def run(
    *, dataset: Path, source_ids_path: Path, holdout_output: Path, full_output: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    source_manifest = json.loads(source_ids_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 500:
        raise PaperInputError("LongMemEval full denominator drifted")
    if not isinstance(source_manifest, dict) or not isinstance(
        source_manifest.get("source_ids"), list
    ):
        raise PaperInputError("paper source-ID manifest drifted")
    holdout_ids = tuple(str(value) for value in source_manifest["source_ids"])
    if len(holdout_ids) != 100 or len(set(holdout_ids)) != 100:
        raise PaperInputError("paper holdout denominator drifted")
    by_id = {str(row.get("question_id")): row for row in rows if isinstance(row, dict)}
    if len(by_id) != 500 or not set(holdout_ids).issubset(by_id):
        raise PaperInputError("LongMemEval source identities drifted")
    dataset_sha256 = hashlib.sha256(dataset.read_bytes()).hexdigest()

    def payload(partition: str, selected: tuple[str, ...]) -> dict[str, Any]:
        cases = [_case(by_id[source_id]) for source_id in selected]
        value: dict[str, Any] = {
            "case_count": len(cases),
            "cases": cases,
            "dataset_sha256": dataset_sha256,
            "forbidden_label_fields_present": False,
            "label_fields_accessed": False,
            "paper_labels_opened": False,
            "partition": partition,
            "schema": "milai.dg11.paper-longmemeval-inputs.v1",
            "source_ids": list(selected),
        }
        if _contains_forbidden(value):
            raise PaperInputError("a label field leaked into paper inputs")
        return value

    holdout = payload("LME-PAPER-HOLDOUT-100", holdout_ids)
    full_ids = tuple(str(row["question_id"]) for row in rows if isinstance(row, dict))
    full = payload("LME-FULL-500-CHARACTERIZATION", full_ids)
    _atomic_json(holdout_output, holdout)
    _atomic_json(full_output, full)
    return holdout, full


def write_subset(
    *, source: Path, output: Path, source_ids: tuple[str, ...], partition: str
) -> dict[str, Any]:
    """Create an unfrozen smoke input from an already label-free input archive."""

    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperInputError("label-free subset source is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or value.get("paper_labels_opened") is not False
        or value.get("label_fields_accessed") is not False
        or value.get("forbidden_label_fields_present") is not False
        or not isinstance(value.get("cases"), list)
        or not isinstance(value.get("dataset_sha256"), str)
    ):
        raise PaperInputError("label-free subset source contract drifted")
    if not 1 <= len(source_ids) <= 10 or len(set(source_ids)) != len(source_ids):
        raise PaperInputError("smoke subset must contain one to ten unique cases")
    by_id = {
        str(case.get("source_id")): case
        for case in value["cases"]
        if isinstance(case, dict)
    }
    if not set(source_ids).issubset(by_id):
        raise PaperInputError("smoke subset contains an unknown source ID")
    subset: dict[str, Any] = {
        "case_count": len(source_ids),
        "cases": [by_id[source_id] for source_id in source_ids],
        "dataset_sha256": value["dataset_sha256"],
        "forbidden_label_fields_present": False,
        "label_fields_accessed": False,
        "paper_labels_opened": False,
        "partition": partition,
        "schema": "milai.dg11.paper-longmemeval-inputs.v1",
        "source_ids": list(source_ids),
    }
    if _contains_forbidden(subset):
        raise PaperInputError("a label field leaked into the smoke subset")
    _atomic_json(output, subset)
    return subset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--source-ids", type=Path, default=DEFAULT_SOURCE_IDS)
    parser.add_argument("--holdout-output", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--full-output", type=Path, default=DEFAULT_FULL)
    parser.add_argument("--smoke-output", type=Path)
    parser.add_argument("--smoke-source-id", action="append", default=[])
    args = parser.parse_args()
    holdout, full = run(
        dataset=args.dataset.resolve(),
        source_ids_path=args.source_ids.resolve(),
        holdout_output=args.holdout_output.resolve(),
        full_output=args.full_output.resolve(),
    )
    smoke = None
    if bool(args.smoke_output) != bool(args.smoke_source_id):
        raise PaperInputError(
            "--smoke-output and at least one --smoke-source-id are required together"
        )
    if args.smoke_output is not None:
        smoke = write_subset(
            source=args.full_output.resolve(),
            output=args.smoke_output.resolve(),
            source_ids=tuple(args.smoke_source_id),
            partition="LME-OPENED-SMOKE",
        )
    print(
        json.dumps(
            {
                "full": full["case_count"],
                "holdout": holdout["case_count"],
                "paper_labels_opened": False,
                "smoke": smoke["case_count"] if smoke else None,
                "status": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
