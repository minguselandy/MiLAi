#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.context_preflight import material_turn_ordinals  # noqa: E402
from milai_lab.longmemeval_gate import canonical_sha256  # noqa: E402
from run_product01_s1_context_preflight import _sha256_file  # noqa: E402
from run_product01_s4_longmemeval import (  # noqa: E402
    MODEL_ID,
    VllmClient,
    _dataset_path,
    _load_population,
)

ROLE_VALUES = (
    "ANSWER",
    "OPERAND",
    "START_EVENT",
    "END_EVENT",
    "TARGET_EVENT",
    "REFERENCE_EVENT",
    "PRIOR_STATE",
    "CURRENT_STATE",
    "COUNT_MEMBER",
    "PREFERENCE_SIGNAL",
    "CURRENT_INTENT",
)
ANNOTATION_MAX_TOKENS = 4_096
SYSTEM_PROMPT = """You annotate exact memory evidence; you do not answer the question.
Given a question, its reference answer, and only the oracle source sessions, select the
minimum source turns whose facts are necessary to derive the reference answer.

Rules:
- Select every independent operand needed for arithmetic, counting, temporal distance,
  temporal ordering, or knowledge updates.
- For a temporal-distance question that names two events (for example, "how many days ...
  when ..."), select both event turns even when the reference answer is only a duration.
- For a temporal-point question asking which event occurred N days/weeks ago, select the
  matching target event, not every dated contrast event in the oracle sessions.
- For set/count questions, select the minimum source turns that together state every positive
  member needed to derive the count. One turn may state multiple members. Do not select
  repeated mentions or negative candidates merely because their sessions were supplied.
- Do not select contrast, distractor, generic advice, or assistant echoes when an original
  user assertion is the remembered fact. For assistant-memory questions, assistant turns
  may be the source fact.
- direct_answer=true only when the turn itself states the answer fact without requiring
  arithmetic or comparison with another turn. Computation operands are not direct answers.
- quote must be copied exactly from the selected source turn and should be the shortest
  substring that carries the needed fact. Use an empty quote only when no short exact
  substring is adequate.
- session_ordinal and turn_ordinal must be copied from the supplied identifiers.
- Return only the requested JSON object.
"""


class AnnotationError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seal Product-02 exact answer-turn labels")
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    return parser


def _seed(case_id: str) -> int:
    digest = hashlib.sha256(f"product02-labels-v1\0{case_id}".encode()).hexdigest()
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _oracle_prompt(record: Mapping[str, Any]) -> str:
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    dates = record.get("haystack_dates")
    gold_ids = record.get("answer_session_ids")
    if (
        not isinstance(session_ids, list)
        or not isinstance(sessions, list)
        or not isinstance(dates, list)
        or not isinstance(gold_ids, list)
        or not (len(session_ids) == len(sessions) == len(dates))
    ):
        raise AnnotationError("LongMemEval oracle session identity is invalid")
    blocks = [
        f"QUESTION_DATE: {record['question_date']}",
        f"QUESTION: {record['question']}",
        "REFERENCE_ANSWER: " + json.dumps(record["answer"], ensure_ascii=False),
        "ORACLE_SOURCE_SESSIONS:",
    ]
    gold = set(gold_ids)
    included = 0
    for session_ordinal, (source_session_id, session, date) in enumerate(
        zip(session_ids, sessions, dates, strict=True)
    ):
        if source_session_id not in gold:
            continue
        if not isinstance(session, list):
            raise AnnotationError("LongMemEval oracle session is invalid")
        included += 1
        blocks.append(
            f"\nSESSION session_ordinal={session_ordinal} "
            f"source_session_id={source_session_id} date={date}"
        )
        for turn_ordinal in material_turn_ordinals(session):
            turn = session[turn_ordinal]
            blocks.append(
                f"TURN turn_ordinal={turn_ordinal} role={turn['role']}\n{turn['content']}"
            )
    if included == 0:
        raise AnnotationError("LongMemEval oracle labels identify no source session")
    return "\n".join(blocks)


def _turns(record: Mapping[str, Any]) -> dict[tuple[int, int], tuple[str, str, str]]:
    sessions = record.get("haystack_sessions")
    session_ids = record.get("haystack_session_ids")
    if not isinstance(sessions, list) or not isinstance(session_ids, list):
        raise AnnotationError("LongMemEval sessions are invalid")
    result: dict[tuple[int, int], tuple[str, str, str]] = {}
    for session_ordinal, (source_session_id, session) in enumerate(
        zip(session_ids, sessions, strict=True)
    ):
        if not isinstance(source_session_id, str) or not isinstance(session, list):
            raise AnnotationError("LongMemEval source session is invalid")
        for turn_ordinal in material_turn_ordinals(session):
            turn = session[turn_ordinal]
            result[(session_ordinal, turn_ordinal)] = (
                source_session_id,
                str(turn["role"]),
                str(turn["content"]),
            )
    return result


def _normalize_selection(
    value: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    turns: Mapping[tuple[int, int], tuple[str, str, str]],
) -> dict[str, Any]:
    session_ordinal = value.get("session_ordinal")
    turn_ordinal = value.get("turn_ordinal")
    role = value.get("requirement_role")
    direct = value.get("direct_answer")
    quote = value.get("quote")
    if (
        isinstance(session_ordinal, bool)
        or not isinstance(session_ordinal, int)
        or isinstance(turn_ordinal, bool)
        or not isinstance(turn_ordinal, int)
        or role not in ROLE_VALUES
        or not isinstance(direct, bool)
        or not isinstance(quote, str)
    ):
        raise AnnotationError("model selection shape is invalid")
    source = turns.get((session_ordinal, turn_ordinal))
    if source is None:
        raise AnnotationError("model selected an unknown source turn")
    source_session_id, speaker, content = source
    gold_ids = record.get("answer_session_ids")
    if not isinstance(gold_ids, list) or source_session_id not in set(gold_ids):
        raise AnnotationError("model selected a non-oracle source session")
    quote_status = "EMPTY_TURN_ONLY"
    if quote:
        if quote in content:
            quote_status = "EXACT"
        else:
            match = re.search(re.escape(quote), content, flags=re.IGNORECASE)
            if match is None:
                quote = ""
                quote_status = "NONEXACT_OMITTED"
            else:
                quote = content[match.start() : match.end()]
                quote_status = "CASE_NORMALIZED_EXACT"
    return {
        "session_ordinal": session_ordinal,
        "source_session_id": source_session_id,
        "turn_ordinal": turn_ordinal,
        "speaker": speaker,
        "requirement_role": role,
        "direct_answer": direct,
        "quote": quote,
        "quote_status": quote_status,
        "source_text_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


async def _run(args: argparse.Namespace) -> int:
    if not 1 <= args.concurrency <= 16:
        raise AnnotationError("annotation concurrency must be 1..16")
    if args.output.exists():
        raise AnnotationError("label output already exists; labels are immutable")
    dataset_path, dataset_sha256 = _dataset_path(args.dataset_manifest)
    records = _load_population(dataset_path)
    provider = VllmClient(args.vllm_base_url, args.concurrency)
    model = await provider.verify()
    semaphore = asyncio.Semaphore(args.concurrency)
    async def annotate(record: Mapping[str, Any]) -> dict[str, Any]:
        case_id = str(record["question_id"])
        if case_id.endswith("_abs"):
            return {
                "case_id": case_id,
                "negative_without_answer_turn": True,
                "selections": [],
                "provider_called": False,
            }
        selection_item = {
            "type": "object",
            "properties": {
                "turn_ordinal": {"type": "integer", "minimum": 0},
                "requirement_role": {"type": "string", "enum": list(ROLE_VALUES)},
                "direct_answer": {"type": "boolean"},
                "quote": {"type": "string"},
            },
            "required": [
                "turn_ordinal",
                "requirement_role",
                "direct_answer",
                "quote",
            ],
            "additionalProperties": False,
        }
        question = str(record.get("question", ""))
        two_event_distance = bool(
            re.search(
                r"\bhow many days ago did I\b.+\bwhen I\b",
                question,
                flags=re.IGNORECASE,
            )
        )
        require_each_oracle = two_event_distance
        session_keys: dict[int, str] = {}
        if require_each_oracle:
            session_ids = record.get("haystack_session_ids")
            gold_ids = record.get("answer_session_ids")
            if (
                not isinstance(session_ids, list)
                or not isinstance(gold_ids, list)
                or any(not isinstance(value, str) or not value for value in gold_ids)
            ):
                raise AnnotationError(
                    f"positive case {case_id} has invalid oracle sessions"
                )
            gold_set = set(gold_ids)
            session_keys = {
                ordinal: f"session_ordinal_{ordinal}"
                for ordinal, source_session_id in enumerate(session_ids)
                if source_session_id in gold_set
            }
            if not session_keys:
                raise AnnotationError(f"positive case {case_id} has no oracle sessions")
            schema = {
                "type": "object",
                "properties": {
                    key: {"type": "array", "minItems": 1, "items": selection_item}
                    for key in session_keys.values()
                },
                "required": list(session_keys.values()),
                "additionalProperties": False,
            }
        else:
            schema = {
                "type": "object",
                "properties": {
                    "selections": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            **selection_item,
                            "properties": {
                                "session_ordinal": {"type": "integer", "minimum": 0},
                                **selection_item["properties"],
                            },
                            "required": ["session_ordinal", *selection_item["required"]],
                        },
                    }
                },
                "required": ["selections"],
                "additionalProperties": False,
            }
        prompt = _oracle_prompt(record)
        try:
            async with semaphore:
                value, metadata = await provider.complete(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    schema_name="milai_product02_answer_turn_labels",
                    schema=schema,
                    max_tokens=ANNOTATION_MAX_TOKENS,
                    seed=_seed(case_id),
                )
        except Exception as exc:
            raise AnnotationError(
                f"case {case_id} provider protocol failed: {type(exc).__name__}: {exc}"
            ) from exc
        if require_each_oracle:
            raw: list[dict[str, Any]] = []
            for session_ordinal, key in session_keys.items():
                session_raw = value.get(key)
                if not isinstance(session_raw, list) or not session_raw or any(
                    not isinstance(item, Mapping) for item in session_raw
                ):
                    raise AnnotationError(
                        f"positive case {case_id} has no valid selection for {key}"
                    )
                raw.extend(
                    {**item, "session_ordinal": session_ordinal}
                    for item in session_raw
                )
        else:
            raw = value.get("selections")
            if not isinstance(raw, list) or not raw or any(
                not isinstance(item, Mapping) for item in raw
            ):
                raise AnnotationError(f"positive case {case_id} has no valid selection")
        source_turns = _turns(record)
        normalized = [
            _normalize_selection(item, record=record, turns=source_turns) for item in raw
        ]
        by_identity: dict[tuple[int, int, str], dict[str, Any]] = {}
        for item in normalized:
            identity = (
                item["session_ordinal"],
                item["turn_ordinal"],
                item["requirement_role"],
            )
            prior = by_identity.get(identity)
            if prior is None:
                by_identity[identity] = item
                continue
            prior["direct_answer"] = bool(
                prior["direct_answer"] or item["direct_answer"]
            )
            exact_quotes = sorted(
                (quote for quote in (prior["quote"], item["quote"]) if quote),
                key=lambda quote: (len(quote), quote),
            )
            prior["quote"] = exact_quotes[0] if exact_quotes else ""
            prior["quote_status"] = (
                "DETERMINISTIC_DUPLICATE_MERGE_EXACT"
                if exact_quotes
                else "DETERMINISTIC_DUPLICATE_MERGE_EMPTY"
            )
        selections = list(by_identity.values())
        minimum_distinct_turns = 2 if two_event_distance else 1
        distinct_turns = {
            (int(selection["session_ordinal"]), int(selection["turn_ordinal"]))
            for selection in selections
        }
        if len(distinct_turns) < minimum_distinct_turns:
            raise AnnotationError(
                f"positive case {case_id} has {len(distinct_turns)} source turns; "
                f"semantic minimum is {minimum_distinct_turns}"
            )
        return {
            "case_id": case_id,
            "negative_without_answer_turn": False,
            "selections": selections,
            "provider_called": True,
            "duplicate_selection_count": len(normalized) - len(selections),
            "annotation_input_sha256": canonical_sha256(
                [SYSTEM_PROMPT, prompt]
            ),
            "provider": metadata,
        }

    try:
        tasks = [asyncio.create_task(annotate(record)) for record in records]
        try:
            completed = 0
            for future in asyncio.as_completed(tasks):
                await future
                completed += 1
                if completed % 25 == 0 or completed == len(tasks):
                    print(
                        json.dumps({"annotated": completed, "total": len(tasks)}),
                        flush=True,
                    )
            cases = [task.result() for task in tasks]
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    finally:
        await provider.close()
    payload = {
        "schema_version": "milai-product02-answer-turn-labels-v1",
        "classification": "EVALUATION_PLANE_MODEL_ASSISTED_SEALED_LABELS",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": dataset_sha256,
        "case_count": len(cases),
        "case_order_sha256": canonical_sha256([case["case_id"] for case in cases]),
        "annotation_model": {
            "id": MODEL_ID,
            "served_model": model,
            "temperature": 0,
            "max_tokens": ANNOTATION_MAX_TOKENS,
            "semantic_retries": 0,
            "votes": 0,
        },
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "procedure": {
            "inputs": ["question", "question_date", "reference_answer", "oracle_sessions"],
            "product_outputs_opened": False,
            "reader_outputs_opened": False,
            "native_has_answer_used_by_annotator": False,
            "exact_quote_replay_validated": True,
            "temporal_distance_anchor_minimum_validated": True,
            "negative_cases": "question_id suffix _abs; deterministic empty answer-turn set",
        },
        "claim_ceiling": (
            "model-assisted exact-turn evaluation labels; not independently human-adjudicated "
            "benchmark ground truth or leaderboard-equivalent"
        ),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": _sha256_file(args.output),
                "case_count": len(cases),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"annotation failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
