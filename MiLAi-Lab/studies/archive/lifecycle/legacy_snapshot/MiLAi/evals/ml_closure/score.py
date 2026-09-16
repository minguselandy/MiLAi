"""Direct semantic Formation scorer for the sealed lifecycle contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from milai.domain.formation_artifact import FormationArtifactSidecarV01
from milai.domain.formation_state import FormationStateChangeSidecarV01
from milai.domain.requirement_state import canonical_sha256

COMPONENTS = (
    "EntityMentionF1",
    "IdentityPairwiseF1",
    "EventMentionF1",
    "EventIdentityPairwiseF1",
    "OccurrenceTimeF1",
    "StateAssertionF1",
    "TransitionRelationMacroF1",
)
RELATIONS = (
    "ESTABLISHES",
    "UPDATES",
    "CORRECTS",
    "REVOKES",
    "TEMPORARILY_CONSTRAINS",
)


class FormationScoreError(RuntimeError):
    """Frozen labels, inputs, or unscored outputs do not agree."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FormationScoreError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _f1(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _overlaps(label: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    span = candidate["span"]
    return (
        span["evidence_id"] == label["evidence_id"]
        and span["start"] <= label["span_start"]
        and span["end"] >= label["span_end"]
    )


def _best(
    label: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    predicate: Callable[[Mapping[str, Any]], bool] | None = None,
) -> Mapping[str, Any] | None:
    matches = [
        candidate
        for candidate in candidates
        if _overlaps(label, candidate) and (predicate is None or predicate(candidate))
    ]
    return min(
        matches,
        key=lambda candidate: (
            candidate["span"]["end"] - candidate["span"]["start"],
            candidate["artifact_digest"],
        ),
        default=None,
    )


def _normalize_time(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("Z", "+00:00")


def _time_matches(label: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    expected = label["occurrence_time"]
    actual = candidate.get("occurrence_time")
    if expected["start"] is None:
        return actual is None and candidate["time_basis"] == "UNRESOLVED"
    if not isinstance(actual, Mapping):
        return False
    return (
        _normalize_time(actual.get("start")) == _normalize_time(expected["start"])
        and _normalize_time(actual.get("end")) == _normalize_time(expected["end"])
        and candidate["time_basis"] == label["time_basis"]
    )


def _binary_pairs(
    pairs: Iterable[Mapping[str, Any]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    prediction_for: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
    key: str,
) -> tuple[dict[str, Any], int]:
    tp = fp = fn = hard_negative_errors = 0
    for pair in pairs:
        left_label = labels_by_id[pair["left"]]
        right_label = labels_by_id[pair["right"]]
        left = prediction_for(left_label)
        right = prediction_for(right_label)
        predicted_same = (
            left is not None and right is not None and left[key] == right[key]
        )
        if pair["same"] and predicted_same:
            tp += 1
        elif pair["same"]:
            fn += 1
        elif predicted_same:
            fp += 1
            hard_negative_errors += 1
    return _f1(tp, fp, fn), hard_negative_errors


def score(raw_path: Path, labels_path: Path, output_path: Path) -> dict[str, Any]:
    raw_bytes = raw_path.read_bytes()
    labels_bytes = labels_path.read_bytes()
    raw = _object(raw_path)
    labels = _object(labels_path)
    output = _object(output_path)
    if output["raw_sha256"] != hashlib.sha256(raw_bytes).hexdigest():
        raise FormationScoreError("UNSCORED_RAW_IDENTITY_MISMATCH")
    raw_by_conversation = {row["conversation_id"]: row for row in raw["conversations"]}
    label_by_conversation = {
        row["conversation_id"]: row for row in labels["conversations"]
    }
    output_by_conversation = {row["conversation_id"]: row for row in output["rows"]}
    if not (
        raw_by_conversation.keys()
        == label_by_conversation.keys()
        == output_by_conversation.keys()
    ):
        raise FormationScoreError("FORMATION_CONVERSATION_IDENTITY_MISMATCH")

    source_by_id = {
        turn["evidence_id"]: turn
        for conversation in raw["conversations"]
        for turn in conversation["turns"]
    }
    entity_labels = {
        item["entity_id"]: item
        for conversation in labels["conversations"]
        for item in conversation["entity_mentions"]
    }
    event_labels = {
        item["event_id"]: item
        for conversation in labels["conversations"]
        for item in conversation["events"]
    }
    entity_candidates: list[dict[str, Any]] = []
    event_candidates: list[dict[str, Any]] = []
    state_candidates: list[dict[str, Any]] = []
    transition_candidates: list[dict[str, Any]] = []
    validated_rows: dict[
        str, tuple[FormationArtifactSidecarV01, FormationStateChangeSidecarV01]
    ] = {}
    for conversation_id, row in output_by_conversation.items():
        formation = FormationArtifactSidecarV01.model_validate(row["formation"])
        states = FormationStateChangeSidecarV01.model_validate(row["state_changes"])
        validated_rows[conversation_id] = (formation, states)
        entity_candidates.extend(
            item.model_dump(mode="json") for item in formation.entity_candidates
        )
        event_candidates.extend(
            item.model_dump(mode="json") for item in formation.event_candidates
        )
        state_candidates.extend(
            item.model_dump(mode="json") for item in states.assertions
        )
        transition_candidates.extend(
            item.model_dump(mode="json") for item in states.transitions
        )

    entity_prediction = lambda label: _best(label, entity_candidates)
    event_prediction = lambda label: _best(label, event_candidates)

    entity_tp = sum(
        entity_prediction(label) is not None for label in entity_labels.values()
    )
    entity_fp = sum(
        not any(_overlaps(label, candidate) for label in entity_labels.values())
        for candidate in entity_candidates
    )
    entity_metric = _f1(entity_tp, entity_fp, len(entity_labels) - entity_tp)
    identity_pairs = [
        pair
        for conversation in labels["conversations"]
        for pair in conversation["entity_identity_pairs"]
    ]
    identity_metric, unsupported_identity_merge = _binary_pairs(
        identity_pairs,
        entity_labels,
        entity_prediction,
        "identity_key",
    )

    event_tp = sum(
        event_prediction(label) is not None for label in event_labels.values()
    )
    event_fp = sum(
        not any(_overlaps(label, candidate) for label in event_labels.values())
        for candidate in event_candidates
    )
    event_metric = _f1(event_tp, event_fp, len(event_labels) - event_tp)
    event_pairs = [
        pair
        for conversation in labels["conversations"]
        for pair in conversation["event_identity_pairs"]
    ]
    event_identity_metric, distinct_event_collapse = _binary_pairs(
        event_pairs,
        event_labels,
        event_prediction,
        "event_identity_key",
    )

    time_tp = sum(
        (candidate := event_prediction(label)) is not None
        and _time_matches(label, candidate)
        for label in event_labels.values()
    )
    time_fp = sum(
        candidate.get("occurrence_time") is not None
        and not any(
            _overlaps(label, candidate) and _time_matches(label, candidate)
            for label in event_labels.values()
        )
        for candidate in event_candidates
    )
    time_metric = _f1(time_tp, time_fp, len(event_labels) - time_tp)

    state_labels = [
        item
        for conversation in labels["conversations"]
        for item in conversation["state_assertions"]
    ]
    state_prediction = lambda label: _best(
        label,
        state_candidates,
        lambda candidate: (
            candidate["predicate"] == label["predicate"]
            and candidate["value"] == label["value"]
            and candidate["modality"] == label["modality"]
            and candidate["promotion_disposition"] == label["promotion_disposition"]
        ),
    )
    state_tp = sum(state_prediction(label) is not None for label in state_labels)
    state_fp = sum(
        not any(
            _overlaps(label, candidate)
            and candidate["predicate"] == label["predicate"]
            and candidate["value"] == label["value"]
            and candidate["modality"] == label["modality"]
            for label in state_labels
        )
        for candidate in state_candidates
    )
    state_metric = _f1(state_tp, state_fp, len(state_labels) - state_tp)

    transition_labels = [
        item
        for conversation in labels["conversations"]
        for item in conversation["state_transitions"]
    ]
    transition_metrics: dict[str, dict[str, Any]] = {}
    for relation in RELATIONS:
        expected = [row for row in transition_labels if row["relation"] == relation]
        produced = [row for row in transition_candidates if row["relation"] == relation]
        matched = sum(
            _best(
                label,
                produced,
                lambda candidate, label=label: (
                    candidate["predicate"] == label["predicate"]
                    and candidate["previous_value"] == label["previous_value"]
                    and candidate["new_value"] == label["new_value"]
                ),
            )
            is not None
            for label in expected
        )
        false_positive = sum(
            not any(
                _overlaps(label, candidate)
                and candidate["predicate"] == label["predicate"]
                and candidate["previous_value"] == label["previous_value"]
                and candidate["new_value"] == label["new_value"]
                for label in expected
            )
            for candidate in produced
        )
        transition_metrics[relation] = _f1(
            matched,
            false_positive,
            len(expected) - matched,
        )
    transition_macro = sum(row["f1"] for row in transition_metrics.values()) / len(
        transition_metrics
    )

    ambiguous = [
        label
        for label in event_labels.values()
        if label["time_category"] == "AMBIGUOUS"
    ]
    ambiguous_preserved = sum(
        (candidate := event_prediction(label)) is not None
        and candidate["occurrence_time"] is None
        and candidate["time_basis"] == "UNRESOLVED"
        for label in ambiguous
    )
    assistant_ids = {
        evidence_id
        for evidence_id, source in source_by_id.items()
        if source["role"] == "assistant"
    }
    assistant_contamination = sum(
        candidate["span"]["evidence_id"] in assistant_ids
        for candidate in (
            entity_candidates
            + event_candidates
            + state_candidates
            + transition_candidates
        )
    )
    raw_span_failures = sum(
        source_by_id[candidate["span"]["evidence_id"]]["content"][
            candidate["span"]["start"] : candidate["span"]["end"]
        ]
        != candidate["span"]["text"]
        for candidate in (
            entity_candidates
            + event_candidates
            + state_candidates
            + transition_candidates
        )
    )
    source_time_misuse = sum(
        candidate["time_basis"] == "SOURCE_OBSERVED_TIME"
        and candidate["occurrence_time"] is not None
        for candidate in event_candidates
    )

    component_values = {
        "EntityMentionF1": entity_metric["f1"],
        "IdentityPairwiseF1": identity_metric["f1"],
        "EventMentionF1": event_metric["f1"],
        "EventIdentityPairwiseF1": event_identity_metric["f1"],
        "OccurrenceTimeF1": time_metric["f1"],
        "StateAssertionF1": state_metric["f1"],
        "TransitionRelationMacroF1": transition_macro,
    }
    per_conversation = _per_conversation(
        labels,
        entity_labels,
        event_labels,
        entity_prediction,
        event_prediction,
        state_prediction,
        transition_candidates,
    )
    result: dict[str, Any] = {
        "schema": "milai.memory-lifecycle-formation-score.v0.1",
        "split": labels.get("split"),
        "arm": output["arm"],
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "labels_sha256": hashlib.sha256(labels_bytes).hexdigest(),
        "unscored_output_digest": output["output_digest"],
        "metrics": {
            "SemanticFormationMacroF1": sum(component_values.values())
            / len(component_values),
            "MinimumComponentF1": min(component_values.values()),
            **component_values,
            "entity_mentions": entity_metric,
            "identity_pairs": identity_metric,
            "event_mentions": event_metric,
            "event_identity_pairs": event_identity_metric,
            "occurrence_time": time_metric,
            "state_assertions": state_metric,
            "transition_by_relation": transition_metrics,
            "RawSpanGroundingExactness": 1.0 if raw_span_failures == 0 else 0.0,
            "SourceEventTimeSeparationAccuracy": 1.0
            if source_time_misuse == 0
            else 0.0,
            "AmbiguousTimePreservation": (
                ambiguous_preserved / len(ambiguous) if ambiguous else 1.0
            ),
            "AssistantContamination": assistant_contamination,
            "UnsupportedIdentityMerge": unsupported_identity_merge,
            "DistinctEventCollapse": distinct_event_collapse,
            "QueryDependentFormationInput": int(
                output["query_fields_visible_to_formation"] is not False
            ),
        },
        "per_conversation": per_conversation,
        "episode_boundary_policy": "MF02_V01_UNCHANGED_MD02_V02_FORBIDDEN",
        "formal_holdout_used": False,
    }
    result["score_digest"] = canonical_sha256(result)
    return result


def _per_conversation(
    labels: Mapping[str, Any],
    entity_labels: Mapping[str, Mapping[str, Any]],
    event_labels: Mapping[str, Mapping[str, Any]],
    entity_prediction: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
    event_prediction: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
    state_prediction: Callable[[Mapping[str, Any]], Mapping[str, Any] | None],
    transition_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for conversation in labels["conversations"]:
        entity_ids = {item["entity_id"] for item in conversation["entity_mentions"]}
        event_ids = {item["event_id"] for item in conversation["events"]}
        scores: list[float] = []
        scores.extend(
            float(entity_prediction(entity_labels[item]) is not None)
            for item in entity_ids
        )
        scores.extend(
            float(event_prediction(event_labels[item]) is not None)
            for item in event_ids
        )
        scores.extend(
            float(_time_matches(event_labels[item], candidate))
            for item in event_ids
            if (candidate := event_prediction(event_labels[item])) is not None
        )
        scores.extend(
            float(state_prediction(label) is not None)
            for label in conversation["state_assertions"]
        )
        for label in conversation["state_transitions"]:
            scores.append(
                float(
                    _best(
                        label,
                        transition_candidates,
                        lambda candidate, label=label: (
                            candidate["relation"] == label["relation"]
                            and candidate["predicate"] == label["predicate"]
                            and candidate["previous_value"] == label["previous_value"]
                            and candidate["new_value"] == label["new_value"]
                        ),
                    )
                    is not None
                )
            )
        rows.append(
            {
                "conversation_id": conversation["conversation_id"],
                "direct_accuracy": sum(scores) / len(scores) if scores else 1.0,
                "obligation_count": len(scores),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--unscored", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = score(
        args.raw.resolve(),
        args.labels.resolve(),
        args.unscored.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
