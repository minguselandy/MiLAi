"""Materialize label-free inputs for the DG11 extended paper benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import cast

from evals.paper.identity import sha256_file

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEAM_ROOT = Path("/cra/memory/mx_memory/benchmarks/BEAM")
DEFAULT_HORIZON_ROOT = Path("/cra/memory/mx_memory/benchmarks/HorizonBench")
DEFAULT_CUPID_ROOT = Path("/cra/memory/mx_memory/benchmarks/CUPID")
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg11/paper/freeze"
HORIZON_FORMAL_PER_STRATUM = 20
CUPID_FORMAL_PER_TYPE = 30
CUPID_SMOKE_PER_TYPE = 2
BEAM_CATEGORIES = (
    "abstention",
    "contradiction_resolution",
    "event_ordering",
    "information_extraction",
    "instruction_following",
    "knowledge_update",
    "multi_session_reasoning",
    "preference_following",
    "summarization",
    "temporal_reasoning",
)
HORIZON_FORBIDDEN_KEYS = frozenset(
    {
        "correct",
        "correct_letter",
        "distractor_letter",
        "has_evolved",
        "preference_evolution",
    }
)
CUPID_FORBIDDEN_KEYS = frozenset(
    {
        "contextual_preference",
        "current_checklist",
        "current_context_factor",
        "current_contextual_preference",
        "instance_type",
    }
)
BEAM_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "compliance_indicators",
        "conversation_reference",
        "conversation_references",
        "expected_compliance",
        "ideal_answer",
        "ideal_response",
        "ideal_summary",
        "non_compliance_signs",
        "rubric",
        "source_chat_ids",
        "why_unanswerable",
    }
)


class ExtendedInputError(RuntimeError):
    pass


def _atomic_json_once(path: Path, value: object) -> None:
    if path.exists():
        raise ExtendedInputError(f"extended input artifact is write-once: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
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


def _contains_key(value: object, forbidden: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        return bool(forbidden.intersection(value)) or any(
            _contains_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def _stable_rank(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}\0{value}".encode()).hexdigest()


def _source_files(paths: Iterable[Path], root: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(paths):
        if not path.is_file():
            raise ExtendedInputError(f"required benchmark source is absent: {path}")
        files.append(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    return files


def _message(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ExtendedInputError("benchmark message is not an object")
    role = value.get("role")
    content = value.get("content")
    if role not in {"user", "assistant"} or not isinstance(content, str):
        raise ExtendedInputError("benchmark message role/content drifted")
    message = {"content": content, "role": role}
    time_anchor = value.get("time_anchor")
    if isinstance(time_anchor, str) and time_anchor:
        message["observed_at"] = time_anchor
    return message


def build_beam_inputs(beam_root: Path) -> dict[str, object]:
    """Build all 400 label-free questions from the repository 128K cohort."""

    cohort = beam_root / "chats/100K"
    chat_dirs = sorted(
        (path for path in cohort.iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    if len(chat_dirs) != 20:
        raise ExtendedInputError("BEAM initial cohort denominator drifted")
    histories: list[dict[str, object]] = []
    cases: list[dict[str, str]] = []
    selected_sources: list[Path] = []
    category_counts: Counter[str] = Counter()
    for chat_dir in chat_dirs:
        chat_path = chat_dir / "chat.json"
        questions_path = chat_dir / "probing_questions/probing_questions.json"
        selected_sources.extend((chat_path, questions_path))
        chat = json.loads(chat_path.read_text(encoding="utf-8"))
        questions = json.loads(questions_path.read_text(encoding="utf-8"))
        if not isinstance(chat, list) or not isinstance(questions, dict):
            raise ExtendedInputError("BEAM chat/question envelope drifted")
        sessions: list[dict[str, object]] = []
        for batch_ordinal, batch in enumerate(chat):
            if not isinstance(batch, dict) or not isinstance(batch.get("turns"), list):
                raise ExtendedInputError("BEAM batch contract drifted")
            for turn_ordinal, turn in enumerate(batch["turns"]):
                if not isinstance(turn, list) or not turn:
                    raise ExtendedInputError("BEAM turn contract drifted")
                sessions.append(
                    {
                        "messages": [_message(item) for item in turn],
                        "session_id": (
                            f"beam-{int(chat_dir.name):02d}-"
                            f"{batch_ordinal:02d}-{turn_ordinal:03d}"
                        ),
                    }
                )
        history_id = f"beam-history-{int(chat_dir.name):02d}"
        histories.append({"history_id": history_id, "sessions": sessions})
        if tuple(sorted(questions)) != tuple(sorted(BEAM_CATEGORIES)):
            raise ExtendedInputError("BEAM question category set drifted")
        for category in BEAM_CATEGORIES:
            items = questions[category]
            if not isinstance(items, list) or len(items) != 2:
                raise ExtendedInputError("BEAM category denominator drifted")
            for ordinal, item in enumerate(items):
                if not isinstance(item, dict) or not isinstance(item.get("question"), str):
                    raise ExtendedInputError("BEAM question contract drifted")
                category_counts[category] += 1
                cases.append(
                    {
                        "case_id": (
                            f"beam-{int(chat_dir.name):02d}-{category}-{ordinal:02d}"
                        ),
                        "category": category,
                        "history_id": history_id,
                        "question": item["question"],
                    }
                )
    payload: dict[str, object] = {
        "answer_label_fields_read_by_preparer": False,
        "case_count": len(cases),
        "cases": cases,
        "category_counts": dict(sorted(category_counts.items())),
        "forbidden_label_fields_present": False,
        "histories": histories,
        "history_count": len(histories),
        "paper_labels_opened": False,
        "partition": "BEAM-128K-FULL",
        "published_scale_label": "128K",
        "repository_directory_label": "100K",
        "scale_label_difference_disclosed": True,
        "schema": "milai.dg11.paper-beam-inputs.v1",
        "source_files": _source_files(selected_sources, beam_root),
    }
    if len(cases) != 400 or any(category_counts[key] != 40 for key in BEAM_CATEGORIES):
        raise ExtendedInputError("BEAM formal denominator drifted")
    if _contains_key(payload, BEAM_FORBIDDEN_KEYS):
        raise ExtendedInputError("a BEAM scorer-label field leaked into paper inputs")
    return payload


def _horizon_options(value: object) -> list[dict[str, str]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or len(value) != 5:
        raise ExtendedInputError("HorizonBench option contract drifted")
    options = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ExtendedInputError("HorizonBench option is not an object")
        letter = item.get("letter")
        option = item.get("option")
        if letter not in {"A", "B", "C", "D", "E"} or not isinstance(option, str):
            raise ExtendedInputError("HorizonBench option field drifted")
        options.append({"letter": letter, "option": option})
    return options


def _horizon_case(row: Mapping[str, object]) -> tuple[dict[str, object], str, str]:
    source_id = row.get("id")
    conversation = row.get("conversation")
    generator = row.get("generator")
    evolved = row.get("has_evolved")
    if (
        not isinstance(source_id, str)
        or not isinstance(conversation, str)
        or not isinstance(generator, str)
        or not isinstance(evolved, bool)
    ):
        raise ExtendedInputError("HorizonBench row contract drifted")
    options = _horizon_options(row.get("options"))
    history_id = "horizon-history-" + hashlib.sha256(conversation.encode()).hexdigest()[:20]
    case: dict[str, object] = {
        "case_id": source_id,
        "history_id": history_id,
        "options": options,
        "question": (
            "Which of the following responses would align with the user's "
            "preferences the most?"
        ),
    }
    return case, generator, "evolved" if evolved else "static"


def build_horizon_inputs(
    benchmark_rows: Sequence[Mapping[str, object]],
    sample_rows: Sequence[Mapping[str, object]],
    *,
    source_files: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    if len(benchmark_rows) != 4245 or len(sample_rows) != 10:
        raise ExtendedInputError("HorizonBench source denominator drifted")
    sample_ids = {str(row.get("id")) for row in sample_rows}
    if len(sample_ids) != 10:
        raise ExtendedInputError("HorizonBench sample identities drifted")
    strata: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in benchmark_rows:
        source_id = row.get("id")
        generator = row.get("generator")
        evolved = row.get("has_evolved")
        if not isinstance(source_id, str) or not isinstance(generator, str) or not isinstance(evolved, bool):
            raise ExtendedInputError("HorizonBench selection metadata drifted")
        if source_id not in sample_ids:
            strata[(generator, "evolved" if evolved else "static")].append(row)
    if len(strata) != 6:
        raise ExtendedInputError("HorizonBench expected six generator/evolution strata")
    selected: list[Mapping[str, object]] = []
    stratum_counts: dict[str, int] = {}
    for key in sorted(strata):
        ranked = sorted(
            strata[key],
            key=lambda row: _stable_rank("milai-dg11-horizon-v1", str(row["id"])),
        )
        if len(ranked) < HORIZON_FORMAL_PER_STRATUM:
            raise ExtendedInputError("HorizonBench stratum is too small")
        selected.extend(ranked[:HORIZON_FORMAL_PER_STRATUM])
        stratum_counts[f"{key[0]}:{key[1]}"] = HORIZON_FORMAL_PER_STRATUM

    def payload(
        rows: Sequence[Mapping[str, object]], partition: str, counts: Mapping[str, int]
    ) -> dict[str, object]:
        histories: dict[str, str] = {}
        cases: list[dict[str, object]] = []
        for row in rows:
            case, _, _ = _horizon_case(row)
            conversation = row["conversation"]
            assert isinstance(conversation, str)
            history_id = str(case["history_id"])
            existing = histories.setdefault(history_id, conversation)
            if existing != conversation:
                raise ExtendedInputError("HorizonBench history digest collision")
            cases.append(case)
        value: dict[str, object] = {
            "answer_label_fields_read_by_preparer": False,
            "case_count": len(cases),
            "cases": cases,
            "forbidden_label_fields_present": False,
            "histories": [
                {"conversation": conversation, "history_id": history_id}
                for history_id, conversation in sorted(histories.items())
            ],
            "history_count": len(histories),
            "paper_labels_opened": False,
            "partition": partition,
            "schema": "milai.dg11.paper-horizon-inputs.v1",
            "selection_metadata_read_by_preparer": True,
            "source_files": source_files,
            "stratum_counts": dict(sorted(counts.items())),
        }
        if _contains_key(value, HORIZON_FORBIDDEN_KEYS):
            raise ExtendedInputError("a HorizonBench label field leaked into inputs")
        return value

    formal = payload(selected, "HORIZON-BALANCED-120", stratum_counts)
    sample_counts: Counter[str] = Counter()
    for row in sample_rows:
        _, generator, state = _horizon_case(row)
        sample_counts[f"{generator}:{state}"] += 1
    smoke = payload(sample_rows, "HORIZON-OFFICIAL-SAMPLE-10-SMOKE", sample_counts)
    formal_cases = cast(list[dict[str, object]], formal["cases"])
    if {str(case["case_id"]) for case in formal_cases}.intersection(sample_ids):
        raise ExtendedInputError("HorizonBench smoke/formal inputs overlap")
    return formal, smoke


def _cupid_dialogue(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ExtendedInputError("CUPID dialogue contract drifted")
    return [_message(item) for item in value]


def _cupid_case(row: Mapping[str, object], ordinal: int) -> dict[str, object]:
    request = row.get("current_request")
    interactions = row.get("prior_interactions")
    if not isinstance(request, str) or not isinstance(interactions, list):
        raise ExtendedInputError("CUPID row contract drifted")
    sessions = []
    for index, interaction in enumerate(interactions):
        if not isinstance(interaction, Mapping):
            raise ExtendedInputError("CUPID interaction contract drifted")
        sessions.append(
            {
                "messages": _cupid_dialogue(interaction.get("dialogue")),
                "session_id": f"cupid-{ordinal:04d}-session-{index:02d}",
            }
        )
    return {
        "case_id": f"cupid-{ordinal:04d}",
        "current_request": request,
        "sessions": sessions,
    }


def build_cupid_inputs(
    rows: Sequence[Mapping[str, object]], *, source_files: list[dict[str, object]]
) -> tuple[dict[str, object], dict[str, object]]:
    if len(rows) != 756:
        raise ExtendedInputError("CUPID source denominator drifted")
    strata: dict[str, list[tuple[int, Mapping[str, object]]]] = defaultdict(list)
    for ordinal, row in enumerate(rows):
        instance_type = row.get("instance_type")
        if instance_type not in {"consistent", "contrastive", "changing"}:
            raise ExtendedInputError("CUPID instance type drifted")
        strata[str(instance_type)].append((ordinal, row))
    if {key: len(value) for key, value in strata.items()} != {
        "changing": 252,
        "consistent": 252,
        "contrastive": 252,
    }:
        raise ExtendedInputError("CUPID stratum denominator drifted")
    formal_rows: list[tuple[int, Mapping[str, object]]] = []
    smoke_rows: list[tuple[int, Mapping[str, object]]] = []
    for key in sorted(strata):
        ranked = sorted(
            strata[key],
            key=lambda item: _stable_rank(
                "milai-dg11-cupid-v1", f"{item[0]}:{item[1].get('persona_id')}"
            ),
        )
        formal_rows.extend(ranked[:CUPID_FORMAL_PER_TYPE])
        smoke_rows.extend(
            ranked[
                CUPID_FORMAL_PER_TYPE : CUPID_FORMAL_PER_TYPE
                + CUPID_SMOKE_PER_TYPE
            ]
        )

    def payload(
        selected: Sequence[tuple[int, Mapping[str, object]]], partition: str, per_type: int
    ) -> dict[str, object]:
        cases = [_cupid_case(row, ordinal) for ordinal, row in selected]
        value: dict[str, object] = {
            "answer_label_fields_read_by_preparer": False,
            "case_count": len(cases),
            "cases": cases,
            "forbidden_label_fields_present": False,
            "paper_labels_opened": False,
            "partition": partition,
            "schema": "milai.dg11.paper-cupid-inputs.v1",
            "selection_metadata_read_by_preparer": True,
            "source_files": source_files,
            "stratum_counts": {
                "changing": per_type,
                "consistent": per_type,
                "contrastive": per_type,
            },
        }
        if _contains_key(value, CUPID_FORBIDDEN_KEYS):
            raise ExtendedInputError("a CUPID label field leaked into inputs")
        return value

    formal = payload(formal_rows, "CUPID-BALANCED-90", CUPID_FORMAL_PER_TYPE)
    smoke = payload(smoke_rows, "CUPID-DISJOINT-SMOKE-6", CUPID_SMOKE_PER_TYPE)
    formal_cases = cast(list[dict[str, object]], formal["cases"])
    smoke_cases = cast(list[dict[str, object]], smoke["cases"])
    formal_ids = {case["case_id"] for case in formal_cases}
    smoke_ids = {case["case_id"] for case in smoke_cases}
    if formal_ids.intersection(smoke_ids):
        raise ExtendedInputError("CUPID smoke/formal inputs overlap")
    return formal, smoke


def _load_parquet(paths: Sequence[Path]) -> Sequence[Mapping[str, object]]:
    try:
        from datasets import load_dataset  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExtendedInputError(
            "datasets is required only for materializing parquet-backed inputs"
        ) from exc
    dataset = load_dataset(
        "parquet",
        data_files={"test": [str(path) for path in paths]},
        split="test",
    )
    return cast(Sequence[Mapping[str, object]], dataset)


def run(
    *,
    beam_root: Path,
    horizon_root: Path,
    cupid_root: Path,
    output_root: Path,
) -> dict[str, object]:
    beam = build_beam_inputs(beam_root)
    horizon_benchmark_paths = sorted(
        (horizon_root / "data/hf/benchmark").glob("test-*.parquet")
    )
    horizon_sample_paths = sorted(
        (horizon_root / "data/hf/sample").glob("test-*.parquet")
    )
    horizon_sources = _source_files(
        [*horizon_benchmark_paths, *horizon_sample_paths], horizon_root
    )
    horizon, horizon_smoke = build_horizon_inputs(
        _load_parquet(horizon_benchmark_paths),
        _load_parquet(horizon_sample_paths),
        source_files=horizon_sources,
    )
    cupid_path = cupid_root / "data/hf/test.parquet"
    cupid_sources = _source_files([cupid_path], cupid_root)
    cupid, cupid_smoke = build_cupid_inputs(
        _load_parquet([cupid_path]), source_files=cupid_sources
    )
    artifacts = {
        "beam": (output_root / "beam-128k-inputs.json", beam),
        "cupid": (output_root / "cupid-subset-inputs.json", cupid),
        "cupid_smoke": (output_root / "cupid-smoke-inputs.json", cupid_smoke),
        "horizon": (output_root / "horizon-subset-inputs.json", horizon),
        "horizon_smoke": (
            output_root / "horizon-smoke-inputs.json",
            horizon_smoke,
        ),
    }
    for path, value in artifacts.values():
        _atomic_json_once(path, value)
    return {
        name: {
            "case_count": value["case_count"],
            "output": str(path),
            "sha256": sha256_file(path),
        }
        for name, (path, value) in artifacts.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beam-root", type=Path, default=DEFAULT_BEAM_ROOT)
    parser.add_argument("--horizon-root", type=Path, default=DEFAULT_HORIZON_ROOT)
    parser.add_argument("--cupid-root", type=Path, default=DEFAULT_CUPID_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = run(
        beam_root=args.beam_root.resolve(),
        horizon_root=args.horizon_root.resolve(),
        cupid_root=args.cupid_root.resolve(),
        output_root=args.output_root.resolve(),
    )
    print(json.dumps({"artifacts": result, "status": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    main()
