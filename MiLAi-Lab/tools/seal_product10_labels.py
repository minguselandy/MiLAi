#!/usr/bin/env python3
"""Seal model-assisted Product-10 instance groups before any Product outcome is opened."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from milai_lab.context_preflight import (  # noqa: E402
    select_outcome_blind_context_cases,
    structural_metadata,
)
from milai_lab.datasets.registry import load_dataset_manifest  # noqa: E402
from milai_lab.product10 import (  # noqa: E402
    CAPABILITY_SHAPES,
    canonical_sha256,
    runtime_source_turn_ref,
    structural_capability_shapes,
    validate_label_bundle,
)

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
MODEL_CONFIG_SHA256 = "570ef7ea45a7e1d3de2b1d3c70c4ac3562d0e768acdc195778cb4f4d95025845"
TOKENIZER_SHA256 = "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
PROMPT_VERSION = "product10-instance-group-annotation-v0.2"


class SealError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "data/manifests/longmemeval-s-cleaned-500.json",
    )
    parser.add_argument(
        "--answer-turn-labels",
        type=Path,
        default=ROOT / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json",
    )
    parser.add_argument(
        "--membership-candidate",
        type=Path,
        default=ROOT / "data/labels/product03-context24-selection.v0.1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/labels/product10-instance-groups.jsonl",
    )
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("--vllm-base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--concurrency", type=int, default=8)
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_inputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = load_dataset_manifest(args.dataset_manifest)
    errors = manifest.verify()
    if errors:
        raise SealError("dataset pin failed: " + "; ".join(errors))
    filename = manifest.split_files.get("population_500")
    if filename is None:
        raise SealError("dataset manifest has no population_500 split")
    dataset_path = Path(manifest.external_root) / filename
    population = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(population, list) or len(population) != 500:
        raise SealError("LongMemEval population identity is invalid")
    labels = json.loads(args.answer_turn_labels.read_text(encoding="utf-8"))
    if (
        not isinstance(labels, dict)
        or labels.get("dataset_sha256") != manifest.file_sha256[filename]
        or labels.get("case_count") != 500
        or not isinstance(labels.get("cases"), list)
    ):
        raise SealError("answer-turn label identity is invalid")
    membership = json.loads(args.membership_candidate.read_text(encoding="utf-8"))
    if (
        not isinstance(membership, dict)
        or membership.get("opened_development_only") is not True
        or not isinstance(membership.get("cases"), list)
        or len(membership["cases"]) != 24
    ):
        raise SealError("membership candidate identity is invalid")
    metadata = {
        "dataset_path": str(dataset_path),
        "dataset_sha256": manifest.file_sha256[filename],
        "dataset_manifest_sha256": _sha256_file(args.dataset_manifest),
        "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
        "membership_candidate_sha256": _sha256_file(args.membership_candidate),
        "labels": labels,
        "membership": membership,
    }
    return [dict(row) for row in population if isinstance(row, dict)], metadata


def _development_membership(
    population: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]
) -> list[dict[str, Any]]:
    by_id = {str(row["question_id"]): dict(row) for row in population}
    label_by_id = {
        str(row["case_id"]): row
        for row in metadata["labels"]["cases"]
        if isinstance(row, Mapping)
    }
    candidate_ids = {str(row["case_id"]) for row in metadata["membership"]["cases"]}
    development = select_outcome_blind_context_cases(population, case_count=128)
    eligible = [
        item.question_id
        for item in development
        if bool(label_by_id.get(item.question_id, {}).get("selections"))
    ]
    if len(eligible) < 24:
        raise SealError("answerable development pool cannot support 24 Product-10 cases")
    return [
        {
            "record": by_id[case_id],
            "source_label": label_by_id[case_id],
            "in_membership_candidate": case_id in candidate_ids,
            "structural_metadata": structural_metadata(by_id[case_id]).to_dict(),
        }
        for case_id in eligible
    ]


def _select_annotated(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    remaining = [dict(row) for row in rows if row.get("capability_shapes")]
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    while any(counts[shape] < 3 for shape in CAPABILITY_SHAPES):
        deficits = {shape for shape in CAPABILITY_SHAPES if counts[shape] < 3}
        ranked = sorted(
            remaining,
            key=lambda row: (
                -len(deficits.intersection(row["capability_shapes"])),
                not bool(row["in_membership_candidate"]),
                hashlib.sha256(str(row["case_id"]).encode()).hexdigest(),
            ),
        )
        if not ranked or not deficits.intersection(ranked[0]["capability_shapes"]):
            missing = {shape: counts[shape] for shape in deficits}
            raise SealError(f"annotated development pool cannot cover Product-10 shapes: {missing}")
        chosen = ranked[0]
        selected.append(chosen)
        remaining.remove(chosen)
        counts.update(chosen["capability_shapes"])

    while len(selected) < 24:
        query_counts = Counter(str(row["query_type"]) for row in selected)
        ranked = sorted(
            remaining,
            key=lambda row: (
                query_counts[str(row["query_type"])],
                -len(row["capability_shapes"]),
                not bool(row["in_membership_candidate"]),
                hashlib.sha256(str(row["case_id"]).encode()).hexdigest(),
            ),
        )
        if not ranked:
            raise SealError("annotated development pool ended before 24 cases")
        chosen = ranked[0]
        selected.append(chosen)
        remaining.remove(chosen)
        counts.update(chosen["capability_shapes"])
    return sorted(selected, key=lambda row: str(row["case_id"]))


def _candidate_turns(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    answer_sessions = record.get("answer_session_ids")
    session_ids = record.get("haystack_session_ids")
    sessions = record.get("haystack_sessions")
    if not isinstance(answer_sessions, list) or not isinstance(session_ids, list):
        raise SealError("answer session identity is invalid")
    if not isinstance(sessions, list) or len(sessions) != len(session_ids):
        raise SealError("answer session material is invalid")
    answer_set = {str(value) for value in answer_sessions}
    candidates: list[dict[str, Any]] = []
    for session_ordinal, (source_session_id, session) in enumerate(
        zip(session_ids, sessions, strict=True)
    ):
        if str(source_session_id) not in answer_set:
            continue
        if not isinstance(session, list):
            raise SealError("answer session is not a turn list")
        for turn_ordinal, turn in enumerate(session):
            if not isinstance(turn, Mapping):
                raise SealError("answer-session turn is invalid")
            content = turn.get("content")
            role = turn.get("role")
            if not isinstance(content, str) or not content or not isinstance(role, str):
                continue
            candidates.append(
                {
                    "index": len(candidates),
                    "session_ordinal": session_ordinal,
                    "turn_ordinal": turn_ordinal,
                    "speaker": role,
                    "source_turn_ref": runtime_source_turn_ref(
                        record,
                        session_ordinal=session_ordinal,
                        turn_ordinal=turn_ordinal,
                    ),
                    "text": content,
                }
            )
    if not candidates:
        raise SealError("case has no candidate answer-session turns")
    return candidates


def _annotation_messages(
    record: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    source_label: Mapping[str, Any],
) -> list[dict[str, str]]:
    mandatory_coordinates = {
        (int(item["session_ordinal"]), int(item["turn_ordinal"]))
        for item in source_label.get("selections", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("session_ordinal"), int)
        and isinstance(item.get("turn_ordinal"), int)
    }
    payload = {
        "question": record.get("question"),
        "question_date": record.get("question_date"),
        "reference_answer": record.get("answer"),
        "candidate_turns": [
            {
                "index": item["index"],
                "speaker": item["speaker"],
                "text": item["text"],
                "mandatory_previous_proxy": (
                    (int(item["session_ordinal"]), int(item["turn_ordinal"]))
                    in mandatory_coordinates
                ),
            }
            for item in candidates
        ],
    }
    system = (
        "You annotate evaluation labels before seeing any system output. Identify every distinct "
        "real-world instance required to answer the question. Group repeated mentions of the same "
        "instance together. A candidate index may appear in at most one group. Omit irrelevant "
        "turns, but every candidate marked mandatory_previous_proxy=true must appear in exactly "
        "one group. Temporal anchors and aggregation operands are separate required instances "
        "unless they are repeated mentions of the same real-world event. "
        "Classify capability shapes using only the supplied question, reference, and source turns. "
        "ENUMERATION means multiple distinct answer instances; COUNTING means a numeric "
        "aggregation; "
        "REPEATED_MENTION means at least one instance is repeated in multiple candidate turns; "
        "SAME_TYPE_DIFFERENT_INSTANCE means at least two distinct instances share a type; "
        "CROSS_SESSION_AGGREGATION means multiple source sessions are combined; UPDATE_COLLECTION "
        "means an update must coexist with or replace collection members; CONTINUATION means "
        "multiple "
        "distinct instances could be exposed across bounded reads. Return only strict JSON."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "member_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "required_for_answer": {"type": "boolean"},
                        "rationale_code": {"type": "string"},
                    },
                    "required": ["member_indices", "required_for_answer", "rationale_code"],
                    "additionalProperties": False,
                },
            },
            "capability_shapes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["groups", "capability_shapes"],
        "additionalProperties": False,
    }


class _Provider:
    def __init__(self, base_url: str, concurrency: int) -> None:
        normalized = base_url.rstrip("/").removesuffix("/v1")
        if normalized not in {"http://127.0.0.1:7860", "http://localhost:7860"}:
            raise SealError("label provider must be the frozen loopback vLLM")
        self._client = httpx.AsyncClient(
            base_url=normalized,
            timeout=httpx.Timeout(180),
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def verify(self) -> dict[str, Any]:
        response = await self._client.get("/v1/models")
        if response.status_code >= 400:
            raise SealError(
                f"annotation provider HTTP {response.status_code}: {response.text[:1000]}"
            )
        payload = response.json()
        models = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(models, list) or len(models) != 1 or models[0].get("id") != MODEL_ID:
            raise SealError("frozen annotation model identity drifted")
        return dict(models[0])

    async def annotate(
        self, case_id: str, messages: Sequence[Mapping[str, str]]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        seed = int(
            hashlib.sha256(f"product10\0{case_id}\0labels".encode()).hexdigest()[:16],
            16,
        ) & ((1 << 63) - 1)
        started = time.perf_counter()
        response = await self._client.post(
            "/v1/chat/completions",
            json={
                "model": MODEL_ID,
                "messages": list(messages),
                "temperature": 0,
                "top_p": 1,
                "seed": seed,
                "max_tokens": 2048,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "product10_instance_groups",
                        "strict": True,
                        "schema": _schema(),
                    },
                },
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            raise SealError(
                f"annotation provider HTTP {response.status_code}: {response.text[:1000]}"
            )
        body = response.json()
        choices = body.get("choices") if isinstance(body, Mapping) else None
        if not isinstance(choices, list) or len(choices) != 1:
            raise SealError("annotation provider returned invalid choice cardinality")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise SealError("annotation provider returned no content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SealError(f"case {case_id} annotation JSON was incomplete") from exc
        if not isinstance(parsed, dict):
            raise SealError("annotation output is not an object")
        usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
        return parsed, {
            "provider_request_id": body.get("id"),
            "response_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "elapsed_ms": round(elapsed_ms, 6),
            "seed": seed,
        }


def _validate_annotation(
    case_id: str,
    annotation: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    source_label: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_groups = annotation.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise SealError(f"case {case_id} has no annotated instance group")
    available = set(range(len(candidates)))
    seen: set[int] = set()
    groups: list[dict[str, Any]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        raw_members = raw_group.get("member_indices")
        if not isinstance(raw_members, list):
            continue
        members = sorted(
            {
                value
                for value in raw_members
                if isinstance(value, int)
                and not isinstance(value, bool)
                and value in available
                and value not in seen
            }
        )
        if not members:
            continue
        seen.update(members)
        refs = [str(candidates[index]["source_turn_ref"]) for index in members]
        groups.append(
            {
                "group_id": f"{case_id}:g{len(groups) + 1}",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": refs,
                "required_for_answer": True,
                "rationale_code": raw_group.get("rationale_code"),
            }
        )
    indexed = {
        (int(item["session_ordinal"]), int(item["turn_ordinal"]))
        for item in source_label.get("selections", [])
        if isinstance(item, Mapping)
    }
    candidate_index = {
        (int(item["session_ordinal"]), int(item["turn_ordinal"])): int(item["index"])
        for item in candidates
    }
    required_proxy_indices = {candidate_index[key] for key in indexed if key in candidate_index}
    for missing_index in sorted(required_proxy_indices.difference(seen)):
        groups.append(
            {
                "group_id": f"{case_id}:g{len(groups) + 1}",
                "acceptable_evidence_ids": [],
                "acceptable_turn_refs": [
                    str(candidates[missing_index]["source_turn_ref"])
                ],
                "required_for_answer": True,
                "rationale_code": "MANDATORY_PROXY_FALLBACK",
            }
        )
    if not groups:
        raise SealError(f"case {case_id} has no required instance group")
    return groups


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise SealError("X0 output already exists; seals are append-forbidden")
    if not 1 <= args.concurrency <= 8:
        raise SealError("annotation concurrency must be 1..8")
    population, metadata = _load_inputs(args)
    selected = _development_membership(population, metadata)
    args.trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = args.trace_dir / "annotation-trace.private.jsonl"
    cached: dict[str, dict[str, Any]] = {}
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get("case_id"), str):
                raise SealError("X0 annotation checkpoint is invalid")
            case_id = str(value["case_id"])
            if case_id in cached or value.get("annotation_prompt_version") != PROMPT_VERSION:
                raise SealError("X0 annotation checkpoint identity drifted")
            cached[case_id] = value
    provider = _Provider(args.vllm_base_url, args.concurrency)
    await provider.verify()
    semaphore = asyncio.Semaphore(args.concurrency)
    checkpoint_lock = asyncio.Lock()

    async def annotate(item: Mapping[str, Any]) -> dict[str, Any]:
        record = item["record"]
        case_id = str(record["question_id"])
        if case_id in cached:
            return dict(cached[case_id])
        candidates = _candidate_turns(record)
        messages = _annotation_messages(record, candidates, item["source_label"])
        async with semaphore:
            annotation, provider_trace = await provider.annotate(case_id, messages)
        groups = _validate_annotation(
            case_id,
            annotation,
            candidates,
            item["source_label"],
        )
        model_shapes = annotation.get("capability_shapes")
        shapes = structural_capability_shapes(
            question_type=str(record["question_type"]),
            question=str(record["question"]),
            group_member_counts=[len(group["acceptable_turn_refs"]) for group in groups],
            reference_session_count=len(set(record["answer_session_ids"])),
            model_shapes=(
                [str(value) for value in model_shapes]
                if isinstance(model_shapes, list)
                else []
            ),
        )
        annotation_input = {
            "question": record["question"],
            "question_date": record["question_date"],
            "reference_answer": record["answer"],
            "candidates": candidates,
        }
        result = {
            "record_type": "case",
            "case_id": case_id,
            "annotation_prompt_version": PROMPT_VERSION,
            "query_type": record["question_type"],
            "capability_shapes": list(shapes),
            "instance_groups": groups,
            "opportunity": {
                "structural": len(groups) >= 2,
                "official_frontier_required": True,
                "residual_query": (
                    "Return another distinct historical instance relevant to the original "
                    "question that has not already been shown."
                ),
            },
            "reference_session_count": len(set(record["answer_session_ids"])),
            "question_sha256": canonical_sha256(record["question"]),
            "reference_answer_sha256": canonical_sha256(record["answer"]),
            "annotation_input_sha256": canonical_sha256(annotation_input),
            "annotation_output_sha256": canonical_sha256(annotation),
            "model_assisted_proxy": True,
            "human_adjudication_status": "PENDING",
            "in_membership_candidate": item["in_membership_candidate"],
            "selection_metadata": item["structural_metadata"],
            "provider": provider_trace,
            "private_trace": {
                "annotation_input": annotation_input,
                "annotation_output": annotation,
                "provider": provider_trace,
            },
        }
        async with checkpoint_lock:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return result

    try:
        annotated = await asyncio.gather(*(annotate(item) for item in selected))
    finally:
        await provider.close()
    selected_rows = _select_annotated(annotated)
    public_rows = [
        {key: value for key, value in row.items() if key != "private_trace"}
        for row in selected_rows
    ]
    prompt_sha256 = canonical_sha256(
        {"version": PROMPT_VERSION, "schema": _schema(), "shapes": CAPABILITY_SHAPES}
    )
    header = {
        "record_type": "manifest",
        "schema_version": "milai-product10-instance-groups-v0.1",
        "created_at": datetime.now(UTC).isoformat(),
        "classification": "OPENED_DEVELOPMENT_ONLY / MODEL_ASSISTED_PROXY",
        "case_count": 24,
        "case_ids": [row["case_id"] for row in public_rows],
        "case_order_sha256": canonical_sha256([row["case_id"] for row in public_rows]),
        "dataset_sha256": metadata["dataset_sha256"],
        "dataset_manifest_sha256": metadata["dataset_manifest_sha256"],
        "source_answer_turn_labels_sha256": metadata["answer_turn_labels_sha256"],
        "membership_candidate_sha256": metadata["membership_candidate_sha256"],
        "selection_procedure": (
            "fixed greedy seven-shape coverage over the pre-existing outcome-blind structural "
            "128 development pool; answerability and pre-Product reference topology only; prior "
            "Context24 membership is a tie-break preference"
        ),
        "annotation": {
            "model": MODEL_ID,
            "model_config_sha256": MODEL_CONFIG_SHA256,
            "tokenizer_sha256": TOKENIZER_SHA256,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256,
            "temperature": 0,
            "product_outputs_opened": False,
            "reader_outputs_opened": False,
            "human_adjudication_status": "PENDING",
            "claim_ceiling": "model-assisted proxy; not human-adjudicated gold",
        },
        "formal_files_accessed": True,
        "formal_cases_scored": 0,
        "product_labels_visible": False,
    }
    bundle: list[Mapping[str, Any]] = [header, *public_rows]
    validate_label_bundle(bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for row in bundle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    summary = {
        "status": "PASS_PRODUCT10_X0_LABEL_SEAL",
        "output": str(args.output),
        "output_sha256": _sha256_file(args.output),
        "trace_sha256": _sha256_file(trace_path),
        "case_count": len(public_rows),
        "group_count": sum(len(row["instance_groups"]) for row in public_rows),
        "structural_opportunity_count": sum(
            bool(row["opportunity"]["structural"]) for row in public_rows
        ),
        "capability_counts": dict(
            sorted(
                Counter(
                    shape for row in public_rows for shape in row["capability_shapes"]
                ).items()
            )
        ),
        "formal_files_accessed": True,
        "formal_cases_scored": 0,
    }
    summary_path = args.trace_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"Product-10 label seal failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
