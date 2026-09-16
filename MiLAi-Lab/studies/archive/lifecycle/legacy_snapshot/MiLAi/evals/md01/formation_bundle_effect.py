"""Score the MD-01 bundle builder against the pre-sealed contrasting labels."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from milai.application.memory_formation import build_memory_formation_bundle
from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.memory_formation import MemoryFormationBundleV01
from milai.domain.requirement_state import canonical_sha256

FIXTURE = Path("evals/md01/fixtures/contrasting-episodes.v0.1.json")
RUN_LOCK = Path("var/md01/md01-memory-formation-bundle-20260830-001/run-lock.json")


class MD01EffectError(RuntimeError):
    """The sealed MD-01 input or a scored Formation invariant drifted."""


def execute_md01_effect(root: Path) -> dict[str, Any]:
    """Build twice without labels, seal predictions, then score them."""

    root = root.resolve()
    fixture_path = root / FIXTURE
    lock = _object(root / RUN_LOCK)
    fixture = _object(fixture_path)
    _verify_run_lock(lock, fixture_path, fixture)
    conversations = _sequence(fixture.get("conversations"), "conversations")
    predictions: list[dict[str, Any]] = []
    deterministic_matches = 0
    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        turns = [
            dict(_mapping(item, "turn"))
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        if any("expected_episodes" in item or "labels" in item for item in turns):
            raise MD01EffectError("MD01_BUILDER_INPUT_LABEL_LEAKAGE")
        first = build_memory_formation_bundle(turns)
        second = build_memory_formation_bundle(turns)
        first_payload = {
            "bundle": first.bundle.model_dump(mode="json"),
            "receipt": first.receipt.model_dump(mode="json"),
        }
        second_payload = {
            "bundle": second.bundle.model_dump(mode="json"),
            "receipt": second.receipt.model_dump(mode="json"),
        }
        deterministic_matches += int(first_payload == second_payload)
        predictions.append(
            {
                "conversation_id": str(conversation["conversation_id"]),
                **first_payload,
            }
        )

    prediction_digest = canonical_sha256(predictions)
    metrics = _score(conversations, predictions, deterministic_matches)
    thresholds = _mapping(lock.get("thresholds"), "thresholds")
    checks = _checks(metrics, thresholds)
    bundle_core_pass = all(
        checks[name]
        for name in (
            "raw_span_coverage_one",
            "user_semantic_source_precision_one",
            "artifact_lineage_closure_one",
            "deterministic_replay_one",
            "external_calls_zero",
            "canonical_mutations_zero",
        )
    )
    episode_pass = all(
        checks[name]
        for name in (
            "episode_boundary_precision_threshold",
            "episode_boundary_recall_threshold",
            "episode_pairwise_f1_threshold",
        )
    )
    if not bundle_core_pass and any(
        not checks[name]
        for name in (
            "raw_span_coverage_one",
            "user_semantic_source_precision_one",
            "artifact_lineage_closure_one",
            "canonical_mutations_zero",
        )
    ):
        status = "FAIL_RAW_OR_AUTHORITY_BOUNDARY"
    elif bundle_core_pass and episode_pass:
        status = "PASS_MD01_MEMORY_FORMATION_CORE_PENDING_REGRESSION"
    elif bundle_core_pass:
        status = "PARTIAL_BUNDLE_PASS_EPISODE_UNRESOLVED"
    else:
        status = "PARKED_EPISODE_BOUNDARY_NO_GENERALIZED_GAIN"
    output: dict[str, Any] = {
        "schema": "milai.md01.formation-bundle-effect.v0.1",
        "run_id": str(lock["run_id"]),
        "run_lock_digest": str(lock["run_lock_digest"]),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "source_scope": {
            "conversation_count": len(conversations),
            "formal_holdout_used": False,
            "builder_visible_labels": False,
            "experimental_feature_flags": "OFF",
        },
        "predictions": predictions,
        "prediction_digest": prediction_digest,
        "metrics": metrics,
        "checks": checks,
        "status": status,
        "safety": {
            "raw_fallback_required": True,
            "provider_calls": 0,
            "reader_calls": 0,
            "retrieval_calls": 0,
            "database_calls": 0,
            "canonical_mutations": 0,
        },
    }
    output["results_digest"] = canonical_sha256(output)
    return output


def _score(
    conversations: Sequence[Any],
    predictions: Sequence[Mapping[str, Any]],
    deterministic_matches: int,
) -> dict[str, Any]:
    prediction_by_id = {str(item["conversation_id"]): item for item in predictions}
    raw_char_total = 0
    raw_char_covered = 0
    boundary_true_positive = 0
    boundary_false_positive = 0
    boundary_false_negative = 0
    boundary_reason_correct = 0
    boundary_reason_total = 0
    pair_true_positive = 0
    pair_false_positive = 0
    pair_false_negative = 0
    artifact_source_total = 0
    artifact_user_source = 0
    artifact_lineage_total = 0
    artifact_lineage_closed = 0
    external_calls = {
        "provider_calls": 0,
        "reader_calls": 0,
        "retrieval_calls": 0,
        "database_calls": 0,
    }
    canonical_mutations = 0

    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        conversation_id = str(conversation["conversation_id"])
        prediction = prediction_by_id[conversation_id]
        bundle = MemoryFormationBundleV01.model_validate(prediction["bundle"])
        receipt = _mapping(prediction["receipt"], "receipt")
        turns = [
            _mapping(item, "turn")
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        expected = [
            _mapping(item, "expected episode")
            for item in _sequence(
                conversation.get("expected_episodes"), "expected episodes"
            )
        ]
        source_by_id = {str(item["evidence_id"]): item for item in turns}
        source_index = {
            str(item["evidence_id"]): index for index, item in enumerate(turns)
        }
        source_role = {
            str(item["evidence_id"]): str(item["speaker"]).casefold() for item in turns
        }
        raw_char_total += sum(len(str(item["content"])) for item in turns)
        for episode in bundle.episode_candidates:
            for span in episode.source_spans:
                source = source_by_id.get(span.evidence_id)
                if source is not None and _span_exact(span, source):
                    raw_char_covered += len(span.text)

        predicted_groups = [
            [source_index[span.evidence_id] for span in episode.source_spans]
            for episode in bundle.episode_candidates
        ]
        expected_groups = [list(item["turn_indexes"]) for item in expected]
        predicted_boundaries = {group[0] for group in predicted_groups[1:]}
        expected_boundaries = {group[0] for group in expected_groups[1:]}
        boundary_true_positive += len(predicted_boundaries & expected_boundaries)
        boundary_false_positive += len(predicted_boundaries - expected_boundaries)
        boundary_false_negative += len(expected_boundaries - predicted_boundaries)
        predicted_reasons = {
            group[0]: episode.boundary_reason
            for group, episode in zip(
                predicted_groups, bundle.episode_candidates, strict=True
            )
        }
        for expected_episode in expected:
            boundary_reason_total += 1
            start = int(expected_episode["turn_indexes"][0])
            boundary_reason_correct += int(
                predicted_reasons.get(start) == expected_episode["boundary_reason"]
            )

        predicted_membership = _membership(predicted_groups, len(turns))
        expected_membership = _membership(expected_groups, len(turns))
        for left in range(len(turns)):
            for right in range(left + 1, len(turns)):
                predicted_same = (
                    predicted_membership[left] == predicted_membership[right]
                )
                expected_same = expected_membership[left] == expected_membership[right]
                pair_true_positive += int(predicted_same and expected_same)
                pair_false_positive += int(predicted_same and not expected_same)
                pair_false_negative += int(not predicted_same and expected_same)

        for span in _artifact_spans(bundle):
            artifact_source_total += 1
            artifact_user_source += int(source_role.get(span.evidence_id) == "user")
            artifact_lineage_total += 1
            source = source_by_id.get(span.evidence_id)
            artifact_lineage_closed += int(
                source is not None and _span_exact(span, source)
            )
        for name in external_calls:
            external_calls[name] += int(receipt[name])
        canonical_mutations += int(receipt["canonical_mutations"])
        canonical_mutations += int(bundle.canonical_mutation)
        canonical_mutations += int(bundle.semantic_sidecar.canonical_mutation)
        canonical_mutations += int(bundle.state_change_sidecar.canonical_mutation)

    return {
        "raw_span_coverage": _ratio(raw_char_covered, raw_char_total),
        "episode_boundary_precision": _ratio(
            boundary_true_positive,
            boundary_true_positive + boundary_false_positive,
        ),
        "episode_boundary_recall": _ratio(
            boundary_true_positive,
            boundary_true_positive + boundary_false_negative,
        ),
        "episode_boundary_reason_accuracy": _ratio(
            boundary_reason_correct, boundary_reason_total
        ),
        "episode_pairwise_f1": _f1(
            pair_true_positive, pair_false_positive, pair_false_negative
        ),
        "user_semantic_source_precision": _ratio(
            artifact_user_source, artifact_source_total
        ),
        "artifact_lineage_closure": _ratio(
            artifact_lineage_closed, artifact_lineage_total
        ),
        "deterministic_replay": _ratio(deterministic_matches, len(conversations)),
        "boundary_counts": {
            "true_positive": boundary_true_positive,
            "false_positive": boundary_false_positive,
            "false_negative": boundary_false_negative,
        },
        "pairwise_counts": {
            "true_positive": pair_true_positive,
            "false_positive": pair_false_positive,
            "false_negative": pair_false_negative,
        },
        "raw_char_counts": {
            "covered": raw_char_covered,
            "total": raw_char_total,
        },
        "artifact_lineage_counts": {
            "closed": artifact_lineage_closed,
            "total": artifact_lineage_total,
        },
        **external_calls,
        "canonical_mutations": canonical_mutations,
    }


def _checks(
    metrics: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> dict[str, bool]:
    return {
        "raw_span_coverage_one": (
            metrics["raw_span_coverage"] == thresholds["raw_span_coverage"]
        ),
        "episode_boundary_precision_threshold": (
            metrics["episode_boundary_precision"]
            >= thresholds["episode_boundary_precision_min"]
        ),
        "episode_boundary_recall_threshold": (
            metrics["episode_boundary_recall"]
            >= thresholds["episode_boundary_recall_min"]
        ),
        "episode_pairwise_f1_threshold": (
            metrics["episode_pairwise_f1"] >= thresholds["episode_pairwise_f1_min"]
        ),
        "user_semantic_source_precision_one": (
            metrics["user_semantic_source_precision"]
            == thresholds["user_semantic_source_precision"]
        ),
        "artifact_lineage_closure_one": (
            metrics["artifact_lineage_closure"]
            == thresholds["artifact_lineage_closure"]
        ),
        "deterministic_replay_one": (
            metrics["deterministic_replay"] == thresholds["deterministic_replay"]
        ),
        "external_calls_zero": all(
            metrics[name] == thresholds[name]
            for name in (
                "provider_calls",
                "reader_calls",
                "retrieval_calls",
                "database_calls",
            )
        ),
        "canonical_mutations_zero": (
            metrics["canonical_mutations"] == thresholds["canonical_mutations"]
        ),
    }


def _verify_run_lock(
    lock: Mapping[str, Any], fixture_path: Path, fixture: Mapping[str, Any]
) -> None:
    material = dict(lock)
    observed_lock_digest = material.pop("run_lock_digest", None)
    if observed_lock_digest != canonical_sha256(material):
        raise MD01EffectError("MD01_RUN_LOCK_DIGEST_INVALID")
    fixture_identity = _mapping(lock.get("fixture"), "fixture identity")
    if (
        fixture_identity.get("sha256")
        != hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    ):
        raise MD01EffectError("MD01_FIXTURE_DRIFT_AFTER_LABEL_SEAL")
    conversations = _sequence(fixture.get("conversations"), "conversations")
    if fixture_identity.get("conversation_count") != len(conversations):
        raise MD01EffectError("MD01_FIXTURE_DENOMINATOR_DRIFT")
    if fixture.get("formal_holdout") is not False:
        raise MD01EffectError("MD01_FORMAL_HOLDOUT_FORBIDDEN")


def _membership(groups: Sequence[Sequence[int]], turn_count: int) -> list[int]:
    output = [-1] * turn_count
    for group_index, group in enumerate(groups):
        for turn_index in group:
            if turn_index < 0 or turn_index >= turn_count or output[turn_index] != -1:
                raise MD01EffectError("MD01_EPISODE_MEMBERSHIP_INVALID")
            output[turn_index] = group_index
    if any(value == -1 for value in output):
        raise MD01EffectError("MD01_EPISODE_MEMBERSHIP_INCOMPLETE")
    return output


def _artifact_spans(bundle: MemoryFormationBundleV01) -> list[FormationSourceSpanV01]:
    return [
        *[item.span for item in bundle.semantic_sidecar.entity_candidates],
        *[item.span for item in bundle.semantic_sidecar.event_candidates],
        *[
            anchor
            for item in bundle.semantic_sidecar.event_candidates
            for anchor in item.temporal_anchor_spans
        ],
        *[item.span for item in bundle.state_change_sidecar.assertions],
        *[item.span for item in bundle.state_change_sidecar.transitions],
    ]


def _span_exact(span: FormationSourceSpanV01, source: Mapping[str, Any]) -> bool:
    content = str(source["content"])
    return (
        span.source_ref == source["source_ref"]
        and 0 <= span.start < span.end <= len(content)
        and content[span.start : span.end] == span.text
    )


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return 2 * precision * recall / (precision + recall) if precision + recall else 1.0


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MD01_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"MD01_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = ["MD01EffectError", "execute_md01_effect"]
