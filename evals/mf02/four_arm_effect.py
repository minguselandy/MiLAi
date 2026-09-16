"""MF-02 sealed four-arm Semantic Episode representation evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from milai.application.memory_formation import build_memory_formation_bundle
from milai.domain.formation_artifact import FormationSourceSpanV01
from milai.domain.memory_formation import (
    MemoryFormationBundleV01,
    MemoryFormationReceiptV01,
)
from milai.domain.requirement_state import canonical_sha256

ArmName = Literal[
    "A_TURN",
    "B_FIXED_WINDOW_2",
    "C_SESSION",
    "D_SEMANTIC_EPISODE",
]

ARM_NAMES: tuple[ArmName, ...] = (
    "A_TURN",
    "B_FIXED_WINDOW_2",
    "C_SESSION",
    "D_SEMANTIC_EPISODE",
)
SIMPLE_ARMS: tuple[ArmName, ...] = ARM_NAMES[:3]
REPAIR_FIXTURE = Path("evals/mf02/fixtures/repair-dev.v0.1.json")
SEALED_FIXTURE = Path("evals/mf02/fixtures/sealed-validation.v0.1.json")
RUN_LOCK = Path("var/mf02/mf02-semantic-episode-four-arm-20260830-001/run-lock.json")
MD01_FIXTURE = Path("evals/md01/fixtures/contrasting-episodes.v0.1.json")
MD01_RESULTS = Path("var/md01/md01-memory-formation-bundle-20260830-001/results.json")

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_FTS_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "still",
        "the",
        "that",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
    }
)


class MF02EffectError(RuntimeError):
    """The sealed MF-02 protocol or a scored invariant was violated."""


@dataclass(frozen=True, slots=True)
class ArmBuildResult:
    arms: dict[ArmName, dict[str, Any]]
    semantic_bundle: MemoryFormationBundleV01
    semantic_receipt: MemoryFormationReceiptV01


class RawFtsAcquirer:
    """One deterministic Raw-turn lexical ranking call per probe."""

    def __init__(self) -> None:
        self.calls = 0

    def rank(
        self, query_text: str, turns: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        self.calls += 1
        query_terms = _terms(query_text)
        turn_terms = [_terms(str(turn["content"])) for turn in turns]
        document_frequency = Counter(
            term for terms in turn_terms for term in set(terms)
        )
        scored: list[tuple[int, float, str]] = []
        for index, (turn, terms) in enumerate(zip(turns, turn_terms, strict=True)):
            frequencies = Counter(terms)
            score = sum(
                frequencies[term]
                * (math.log((len(turns) + 1) / (document_frequency[term] + 1)) + 1)
                for term in set(query_terms)
            )
            scored.append((index, score, str(turn["evidence_id"])))
        scored.sort(key=lambda item: (-item[1], item[0]))
        payload: dict[str, Any] = {
            "schema": "milai.mf02.raw-fts-anchor-ranking.v0.1",
            "query_digest": canonical_sha256(query_text),
            "ranked_evidence_ids": [item[2] for item in scored],
            "scores": [
                {"evidence_id": item[2], "score": round(item[1], 12)} for item in scored
            ],
            "acquisition_rounds": 1,
            "database_calls": 0,
            "provider_calls": 0,
            "reader_calls": 0,
            "model_calls": 0,
        }
        payload["anchor_digest"] = canonical_sha256(payload)
        return payload


def build_representation_arms(
    source_records: Sequence[Mapping[str, Any]],
) -> ArmBuildResult:
    """Build all four query-independent arms from the same complete Raw turns."""

    turns = [dict(_mapping(item, "turn")) for item in source_records]
    if not turns:
        raise MF02EffectError("MF02_SOURCE_SNAPSHOT_EMPTY")
    semantic = build_memory_formation_bundle(turns)
    index_by_id = {str(turn["evidence_id"]): index for index, turn in enumerate(turns)}
    turn_groups = [[index] for index in range(len(turns))]
    fixed_groups = [
        session_group[index : index + 2]
        for session_group in _session_groups(turns)
        for index in range(0, len(session_group), 2)
    ]
    session_groups = _session_groups(turns)
    semantic_groups = [
        [index_by_id[span.evidence_id] for span in episode.source_spans]
        for episode in semantic.bundle.episode_candidates
    ]
    groups_by_arm: dict[ArmName, list[list[int]]] = {
        "A_TURN": turn_groups,
        "B_FIXED_WINDOW_2": fixed_groups,
        "C_SESSION": session_groups,
        "D_SEMANTIC_EPISODE": semantic_groups,
    }
    arms = {
        arm: _arm_snapshot(arm, groups, turns, semantic.bundle)
        for arm, groups in groups_by_arm.items()
    }
    return ArmBuildResult(
        arms=arms,
        semantic_bundle=semantic.bundle,
        semantic_receipt=semantic.receipt,
    )


def execute_mf02_effect(root: Path) -> dict[str, Any]:
    """Run the sole sealed-validation effect after prediction/acquisition freeze."""

    root = root.resolve()
    lock = _object(root / RUN_LOCK)
    fixture = _object(root / SEALED_FIXTURE)
    _verify_run_lock(root, lock, fixture, "sealed_validation")
    conversations = _sequence(fixture.get("conversations"), "conversations")
    predictions, prediction_digest, raw_fts_calls = _predict(conversations)
    metrics = _score(conversations, predictions, raw_fts_calls, lock)
    thresholds = _mapping(lock.get("thresholds"), "thresholds")
    checks = _checks(metrics, thresholds)
    h1_pass = all(
        checks[name]
        for name in (
            "semantic_pairwise_f1_threshold",
            "semantic_pairwise_delta_threshold",
            "raw_span_coverage_one",
            "source_order_preservation_one",
            "user_semantic_source_precision_one",
            "artifact_lineage_closure_one",
        )
    )
    h2_pass = all(
        checks[name]
        for name in (
            "support_closure_auc_delta_threshold",
            "distractor_turn_rate_noninferiority",
            "one_raw_fts_call_per_probe",
            "shared_anchor_ranking",
        )
    )
    safety_pass = all(
        checks[name]
        for name in (
            "raw_span_coverage_one",
            "source_order_preservation_one",
            "user_semantic_source_precision_one",
            "artifact_lineage_closure_one",
            "external_and_model_calls_zero",
            "database_writes_zero",
            "canonical_mutations_zero",
            "formal_holdout_false",
            "product_feature_flags_off",
        )
    )
    semantic_pairwise = float(
        metrics["direct"]["by_arm"]["D_SEMANTIC_EPISODE"]["episode_pairwise_f1"]
    )
    strongest_simple_pairwise = float(
        metrics["direct"]["strongest_simple_baseline"]["value"]
    )
    if not safety_pass:
        status = "FAIL_MF02_RAW_OR_AUTHORITY_BOUNDARY"
    elif h1_pass and h2_pass:
        status = "PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION"
    elif h1_pass:
        status = "PASS_MF02_REPRESENTATION_ONLY_NO_READ_GAIN"
    elif strongest_simple_pairwise >= semantic_pairwise:
        status = "PARKED_MF02_SIMPLE_SEGMENTATION_SUFFICIENT"
    else:
        status = "PARKED_MF02_DATA_OR_REPRESENTATION_UNRESOLVED"

    output: dict[str, Any] = {
        "schema": "milai.mf02.four-arm-effect.v0.1",
        "run_id": str(lock["run_id"]),
        "run_lock_digest": str(lock["run_lock_digest"]),
        "fixture_sha256": hashlib.sha256(
            (root / SEALED_FIXTURE).read_bytes()
        ).hexdigest(),
        "source_scope": {
            "conversation_count": len(conversations),
            "turn_count": sum(
                len(_sequence(_mapping(item, "conversation").get("turns"), "turns"))
                for item in conversations
            ),
            "probe_count": sum(
                len(
                    _sequence(
                        _mapping(item, "conversation").get("memory_probes"),
                        "memory probes",
                    )
                )
                for item in conversations
            ),
            "repair_dev_in_main_denominator": False,
            "md01_in_main_denominator": False,
            "formal_holdout_used": False,
            "builder_visible_labels": False,
            "raw_fts_visible_support_labels": False,
            "experimental_feature_flags": "OFF",
        },
        "predictions": predictions,
        "prediction_digest_before_scoring": prediction_digest,
        "metrics": metrics,
        "checks": checks,
        "hypotheses": {
            "MF02-H1": (
                "SUPPORTED_ON_SEALED_NON_HOLDOUT_VALIDATION"
                if h1_pass
                else "NOT_SUPPORTED"
            ),
            "MF02-H2": (
                "SUPPORTED_ON_SEALED_NON_HOLDOUT_VALIDATION"
                if h2_pass
                else "NOT_SUPPORTED"
            ),
        },
        "status": status,
        "md01_scorer_sanity": md01_scorer_sanity(root),
        "safety": metrics["safety"],
    }
    output["results_digest"] = canonical_sha256(output)
    return output


def evaluate_repair_dev(root: Path) -> dict[str, Any]:
    """Development-only scorer path; never opens sealed-validation labels."""

    root = root.resolve()
    lock = _object(root / RUN_LOCK)
    fixture = _object(root / REPAIR_FIXTURE)
    _verify_run_lock(root, lock, fixture, "repair_dev")
    conversations = _sequence(fixture.get("conversations"), "conversations")
    predictions, prediction_digest, raw_fts_calls = _predict(conversations)
    return {
        "schema": "milai.mf02.repair-dev-evaluation.v0.1",
        "split": "repair-dev",
        "prediction_digest_before_scoring": prediction_digest,
        "metrics": _score(conversations, predictions, raw_fts_calls, lock),
    }


def hand_scorer_sanity() -> dict[str, float]:
    """Small exact example whose pairwise answers are calculable by inspection."""

    expected = [[0, 1], [2]]
    perfect = _direct_conversation(expected, expected, 3)
    turn = _direct_conversation([[0], [1], [2]], expected, 3)
    session = _direct_conversation([[0, 1, 2]], expected, 3)
    return {
        "perfect_pairwise_f1": perfect["episode_pairwise_f1"],
        "turn_pairwise_f1": turn["episode_pairwise_f1"],
        "session_pairwise_f1": session["episode_pairwise_f1"],
    }


def md01_scorer_sanity(root: Path) -> dict[str, Any]:
    """Replay the new direct scorer over MD-01's already frozen predictions."""

    root = root.resolve()
    fixture = _object(root / MD01_FIXTURE)
    results = _object(root / MD01_RESULTS)
    predictions = {
        str(item["conversation_id"]): _mapping(item, "prediction")
        for item in _sequence(results.get("predictions"), "MD-01 predictions")
    }
    rows: list[dict[str, float]] = []
    for raw_conversation in _sequence(
        fixture.get("conversations"), "MD-01 conversations"
    ):
        conversation = _mapping(raw_conversation, "MD-01 conversation")
        turns = _sequence(conversation.get("turns"), "MD-01 turns")
        expected = [
            [
                int(index)
                for index in _sequence(
                    _mapping(item, "episode").get("turn_indexes"), "turn indexes"
                )
            ]
            for item in _sequence(
                conversation.get("expected_episodes"), "expected episodes"
            )
        ]
        bundle = MemoryFormationBundleV01.model_validate(
            predictions[str(conversation["conversation_id"])]["bundle"]
        )
        index_by_id = {
            str(_mapping(turn, "turn")["evidence_id"]): index
            for index, turn in enumerate(turns)
        }
        groups = [
            [index_by_id[span.evidence_id] for span in episode.source_spans]
            for episode in bundle.episode_candidates
        ]
        rows.append(_direct_conversation(groups, expected, len(turns)))
    pairwise_f1 = mean(row["episode_pairwise_f1"] for row in rows)
    return {
        "conversation_count": len(rows),
        "episode_pairwise_f1": pairwise_f1,
        "expected_episode_pairwise_f1": 1.0,
        "passed": pairwise_f1 == 1.0,
        "included_in_mf02_main_denominator": False,
    }


def environment_witness() -> str:
    """Seeded CPU witness documented in the MF-02 environment ledger."""

    turns = [
        {
            "evidence_id": f"witness-{index}",
            "source_ref": f"memory://mf02/witness/{index}",
            "session_id": "witness-session",
            "speaker": "assistant" if index == 1 else "user",
            "speaker_source": "STRUCTURED_TURN_METADATA",
            "observed_at": f"2026-08-30T08:0{index}:00+08:00",
            "content": text,
            "permission_snapshot": {"readable": True},
            "retention_state": "READABLE",
            "revoked_at": None,
        }
        for index, text in enumerate(
            (
                "My notebook is stored in the desk drawer.",
                "Which drawer do you mean?",
                "The locked drawer below the printer.",
                "I joined a weekend rowing club.",
            )
        )
    ]
    result = build_representation_arms(turns)
    appearances = sum(
        len(unit["source_spans"])
        for arm in result.arms.values()
        for unit in arm["units"]
    )
    return f"WITNESS {len(result.arms)} {appearances} {result.semantic_receipt.provider_calls}"


def _predict(
    conversations: Sequence[Any],
) -> tuple[list[dict[str, Any]], str, int]:
    predictions: list[dict[str, Any]] = []
    acquirer = RawFtsAcquirer()
    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        turns = [
            dict(_mapping(item, "turn"))
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        forbidden = {
            "conversation_id",
            "counterexample_families",
            "expected_episodes",
            "memory_probes",
            "required_support_evidence_ids",
            "distractor_evidence_ids",
        }
        if any(forbidden & set(turn) for turn in turns):
            raise MF02EffectError("MF02_BUILDER_INPUT_LABEL_LEAKAGE")
        first = build_representation_arms(turns)
        second = build_representation_arms(turns)
        first_payload = {
            "arms": first.arms,
            "semantic_bundle": first.semantic_bundle.model_dump(mode="json"),
            "semantic_receipt": first.semantic_receipt.model_dump(mode="json"),
        }
        second_payload = {
            "arms": second.arms,
            "semantic_bundle": second.semantic_bundle.model_dump(mode="json"),
            "semantic_receipt": second.semantic_receipt.model_dump(mode="json"),
        }
        if first_payload != second_payload:
            raise MF02EffectError("MF02_REPRESENTATION_REPLAY_NONDETERMINISTIC")
        acquisition_inputs = [
            {
                "probe_id": str(_mapping(item, "probe")["probe_id"]),
                "query_text": str(_mapping(item, "probe")["query_text"]),
            }
            for item in _sequence(conversation.get("memory_probes"), "memory probes")
        ]
        anchor_rankings = {
            item["probe_id"]: acquirer.rank(item["query_text"], turns)
            for item in acquisition_inputs
        }
        predictions.append(
            {
                "conversation_id": str(conversation["conversation_id"]),
                **first_payload,
                "anchor_rankings": anchor_rankings,
                "deterministic_replay": True,
            }
        )
    return predictions, canonical_sha256(predictions), acquirer.calls


def _score(
    conversations: Sequence[Any],
    predictions: Sequence[Mapping[str, Any]],
    raw_fts_calls: int,
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    prediction_by_id = {str(item["conversation_id"]): item for item in predictions}
    direct_rows: dict[ArmName, list[dict[str, float]]] = {arm: [] for arm in ARM_NAMES}
    direct_counts: dict[ArmName, Counter[str]] = {arm: Counter() for arm in ARM_NAMES}
    raw_exact = {arm: 0 for arm in ARM_NAMES}
    raw_total = {arm: 0 for arm in ARM_NAMES}
    source_order_matches = {arm: 0 for arm in ARM_NAMES}
    read_rows: dict[ArmName, list[dict[str, Any]]] = {arm: [] for arm in ARM_NAMES}
    pairwise_by_conversation: dict[ArmName, dict[str, float]] = {
        arm: {} for arm in ARM_NAMES
    }
    read_auc_by_conversation: dict[ArmName, dict[str, float]] = {
        arm: {} for arm in ARM_NAMES
    }
    artifact_source_total = 0
    artifact_user_source = 0
    artifact_lineage_total = 0
    artifact_lineage_closed = 0
    assistant_contamination = 0
    external_calls: Counter[str] = Counter()
    canonical_mutations = 0
    failure_cases: dict[str, list[str]] = {
        "over_split": [],
        "over_merge": [],
        "assistant_contamination": [],
        "time_gap_error": [],
        "topic_shift_error": [],
    }
    ceilings = [
        int(item)
        for item in _sequence(
            _mapping(lock.get("protocol"), "protocol").get("raw_turn_ceilings"),
            "raw turn ceilings",
        )
    ]

    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        conversation_id = str(conversation["conversation_id"])
        prediction = prediction_by_id[conversation_id]
        turns = [
            _mapping(item, "turn")
            for item in _sequence(conversation.get("turns"), "turns")
        ]
        expected_groups = [
            [
                int(index)
                for index in _sequence(
                    _mapping(item, "episode").get("turn_indexes"), "turn indexes"
                )
            ]
            for item in _sequence(
                conversation.get("expected_episodes"), "expected episodes"
            )
        ]
        expected_membership = _membership(expected_groups, len(turns))
        source_role = {
            str(turn["evidence_id"]): str(turn["speaker"]).casefold() for turn in turns
        }
        source_by_id = {str(turn["evidence_id"]): turn for turn in turns}
        arms = _mapping(prediction.get("arms"), "predicted arms")
        for arm in ARM_NAMES:
            snapshot = _mapping(arms.get(arm), arm)
            groups, exact_chars, total_chars, ordered = _validate_arm_snapshot(
                snapshot, turns, arm
            )
            row = _direct_conversation(groups, expected_groups, len(turns))
            direct_rows[arm].append(row)
            pairwise_by_conversation[arm][conversation_id] = row["episode_pairwise_f1"]
            direct_counts[arm].update(
                {
                    key: int(row[key])
                    for key in (
                        "pair_true_positive",
                        "pair_false_positive",
                        "pair_false_negative",
                        "boundary_true_positive",
                        "boundary_false_positive",
                        "boundary_false_negative",
                    )
                }
            )
            raw_exact[arm] += exact_chars
            raw_total[arm] += total_chars
            source_order_matches[arm] += int(ordered)

        bundle = MemoryFormationBundleV01.model_validate(prediction["semantic_bundle"])
        receipt = MemoryFormationReceiptV01.model_validate(
            prediction["semantic_receipt"]
        )
        for span in _artifact_spans(bundle):
            artifact_source_total += 1
            artifact_user_source += int(source_role.get(span.evidence_id) == "user")
            artifact_lineage_total += 1
            source = source_by_id.get(span.evidence_id)
            exact = source is not None and _lineage_span_exact(span, source)
            artifact_lineage_closed += int(exact)
            if source_role.get(span.evidence_id) == "assistant":
                assistant_contamination += 1
        external_calls.update(
            {
                "provider_calls": receipt.provider_calls,
                "reader_calls": receipt.reader_calls,
                "retrieval_calls": receipt.retrieval_calls,
                "database_calls": receipt.database_calls,
            }
        )
        canonical_mutations += receipt.canonical_mutations
        canonical_mutations += int(bundle.canonical_mutation)
        canonical_mutations += int(bundle.semantic_sidecar.canonical_mutation)
        canonical_mutations += int(bundle.state_change_sidecar.canonical_mutation)

        semantic_groups = _groups_from_snapshot(
            _mapping(arms["D_SEMANTIC_EPISODE"], "semantic arm")
        )
        semantic_direct = _direct_conversation(
            semantic_groups, expected_groups, len(turns)
        )
        if semantic_direct["boundary_false_positive"]:
            failure_cases["over_split"].append(conversation_id)
        if semantic_direct["boundary_false_negative"]:
            failure_cases["over_merge"].append(conversation_id)
        families = {
            str(item)
            for item in _sequence(
                conversation.get("counterexample_families"), "families"
            )
        }
        if "LONG_GAP_SAME_TOPIC" in families and (
            semantic_direct["boundary_false_positive"]
            or semantic_direct["boundary_false_negative"]
        ):
            failure_cases["time_gap_error"].append(conversation_id)
        if (
            families - {"LONG_GAP_SAME_TOPIC"}
            and semantic_direct["boundary_false_negative"]
        ):
            failure_cases["topic_shift_error"].append(conversation_id)

        probes = [
            _mapping(item, "probe")
            for item in _sequence(conversation.get("memory_probes"), "memory probes")
        ]
        anchor_rankings = _mapping(prediction.get("anchor_rankings"), "anchor rankings")
        conversation_read_rows: dict[ArmName, list[dict[str, Any]]] = {
            arm: [] for arm in ARM_NAMES
        }
        for probe in probes:
            probe_id = str(probe["probe_id"])
            ranking = _mapping(anchor_rankings.get(probe_id), "anchor ranking")
            ranked_ids = [
                str(item)
                for item in _sequence(
                    ranking.get("ranked_evidence_ids"), "ranked Evidence IDs"
                )
            ]
            if set(ranked_ids) != set(source_by_id) or len(ranked_ids) != len(turns):
                raise MF02EffectError("MF02_ANCHOR_RANKING_SOURCE_IDENTITY_INVALID")
            required = {
                str(item)
                for item in _sequence(
                    probe.get("required_support_evidence_ids"), "required support"
                )
            }
            distractors = {
                str(item)
                for item in _sequence(
                    probe.get("distractor_evidence_ids"), "distractors"
                )
            }
            required_indexes = {
                index
                for index, turn in enumerate(turns)
                if str(turn["evidence_id"]) in required
            }
            target_episode_ids = {
                expected_membership[index] for index in required_indexes
            }
            if len(target_episode_ids) != 1:
                raise MF02EffectError("MF02_REQUIRED_SUPPORT_CROSSES_GOLD_EPISODE")
            target_episode = target_episode_ids.pop()
            for arm in ARM_NAMES:
                snapshot = _mapping(arms[arm], arm)
                per_ceiling: dict[str, dict[str, float | bool | int]] = {}
                minimum_turns: int | None = None
                for ceiling in ceilings:
                    hydrated = _hydrate(snapshot, ranked_ids, ceiling)
                    hydrated_set = set(hydrated)
                    support_closed = required.issubset(hydrated_set)
                    if support_closed and minimum_turns is None:
                        minimum_turns = ceiling
                    useful_count = len(required & hydrated_set)
                    distractor_count = len(distractors & hydrated_set)
                    cross_episode_count = sum(
                        expected_membership[index] != target_episode
                        for index, turn in enumerate(turns)
                        if str(turn["evidence_id"]) in hydrated_set
                    )
                    context_size = len(hydrated_set)
                    per_ceiling[str(ceiling)] = {
                        "support_closed": support_closed,
                        "required_evidence_coverage": _ratio(
                            useful_count, len(required)
                        ),
                        "useful_turn_rate": _ratio_zero(useful_count, context_size),
                        "distractor_turn_rate": _ratio_zero(
                            distractor_count, context_size
                        ),
                        "cross_episode_contamination_rate": _ratio_zero(
                            cross_episode_count, context_size
                        ),
                        "hydrated_raw_turns": context_size,
                    }
                read_row: dict[str, Any] = {
                    "conversation_id": conversation_id,
                    "probe_id": probe_id,
                    "anchor_pool_hits_required": bool(required & set(ranked_ids)),
                    "per_ceiling": per_ceiling,
                    "support_closure_auc": mean(
                        float(per_ceiling[str(ceiling)]["support_closed"])
                        for ceiling in ceilings
                    ),
                    "minimum_turns_to_closure": minimum_turns,
                }
                read_rows[arm].append(read_row)
                conversation_read_rows[arm].append(read_row)
        for arm in ARM_NAMES:
            read_auc_by_conversation[arm][conversation_id] = mean(
                float(row["support_closure_auc"]) for row in conversation_read_rows[arm]
            )

    if assistant_contamination:
        failure_cases["assistant_contamination"] = [
            f"artifact_spans:{assistant_contamination}"
        ]
    direct_by_arm: dict[ArmName, dict[str, Any]] = {
        arm: {
            metric: mean(float(row[metric]) for row in direct_rows[arm])
            for metric in (
                "episode_pairwise_precision",
                "episode_pairwise_recall",
                "episode_pairwise_f1",
                "boundary_precision",
                "boundary_recall",
                "boundary_f1",
                "self_containedness",
                "cross_boundary_dependency_rate",
            )
        }
        | {
            "raw_span_coverage": _ratio(raw_exact[arm], raw_total[arm]),
            "source_order_preservation": _ratio(
                source_order_matches[arm], len(conversations)
            ),
            "counts": dict(sorted(direct_counts[arm].items())),
        }
        for arm in ARM_NAMES
    }
    strongest_direct_arm = max(
        SIMPLE_ARMS,
        key=lambda arm: float(direct_by_arm[arm]["episode_pairwise_f1"]),
    )
    semantic_direct_value = float(
        direct_by_arm["D_SEMANTIC_EPISODE"]["episode_pairwise_f1"]
    )
    strongest_direct_value = float(
        direct_by_arm[strongest_direct_arm]["episode_pairwise_f1"]
    )
    direct_deltas = {
        conversation_id: pairwise_by_conversation["D_SEMANTIC_EPISODE"][conversation_id]
        - pairwise_by_conversation[strongest_direct_arm][conversation_id]
        for conversation_id in pairwise_by_conversation["D_SEMANTIC_EPISODE"]
    }
    read_by_arm: dict[ArmName, dict[str, Any]] = {
        arm: _aggregate_read_rows(read_rows[arm], ceilings) for arm in ARM_NAMES
    }
    strongest_read_arm = max(
        SIMPLE_ARMS,
        key=lambda arm: float(read_by_arm[arm]["support_closure_auc"]),
    )
    semantic_read_value = float(
        read_by_arm["D_SEMANTIC_EPISODE"]["support_closure_auc"]
    )
    strongest_read_value = float(read_by_arm[strongest_read_arm]["support_closure_auc"])
    read_deltas = {
        conversation_id: read_auc_by_conversation["D_SEMANTIC_EPISODE"][conversation_id]
        - read_auc_by_conversation[strongest_read_arm][conversation_id]
        for conversation_id in read_auc_by_conversation["D_SEMANTIC_EPISODE"]
    }
    protocol = _mapping(lock.get("protocol"), "protocol")
    bootstrap = _mapping(protocol.get("bootstrap"), "bootstrap")
    seed = int(bootstrap["seed"])
    resamples = int(bootstrap["resamples"])
    probe_count = len(read_rows[ARM_NAMES[0]])
    safety: dict[str, Any] = {
        "raw_span_coverage": min(
            float(value["raw_span_coverage"]) for value in direct_by_arm.values()
        ),
        "source_order_preservation": min(
            float(value["source_order_preservation"])
            for value in direct_by_arm.values()
        ),
        "user_semantic_source_precision": _ratio(
            artifact_user_source, artifact_source_total
        ),
        "artifact_lineage_closure": _ratio(
            artifact_lineage_closed, artifact_lineage_total
        ),
        "canonical_mutations": canonical_mutations,
        "database_writes": 0,
        "database_calls": external_calls["database_calls"],
        "provider_calls": external_calls["provider_calls"],
        "reader_calls": external_calls["reader_calls"],
        "retrieval_calls": external_calls["retrieval_calls"],
        "model_calls": 0,
        "formal_holdout_used": False,
        "product_feature_flags": "OFF",
        "deterministic_replay": float(
            all(bool(item["deterministic_replay"]) for item in predictions)
        ),
    }
    return {
        "direct": {
            "by_arm": direct_by_arm,
            "strongest_simple_baseline": {
                "arm": strongest_direct_arm,
                "value": strongest_direct_value,
            },
            "semantic_pairwise_f1": semantic_direct_value,
            "paired_macro_delta_vs_strongest_simple": (
                semantic_direct_value - strongest_direct_value
            ),
            "paired_macro_delta_bootstrap_95_ci": _bootstrap_ci(
                direct_deltas, seed=seed, resamples=resamples
            ),
        },
        "simple_read": {
            "by_arm": read_by_arm,
            "strongest_simple_baseline": {
                "arm": strongest_read_arm,
                "value": strongest_read_value,
            },
            "semantic_support_closure_auc": semantic_read_value,
            "paired_macro_delta_vs_strongest_simple": (
                semantic_read_value - strongest_read_value
            ),
            "paired_macro_delta_bootstrap_95_ci": _bootstrap_ci(
                read_deltas, seed=seed, resamples=resamples
            ),
            "semantic_distractor_turn_rate_delta_vs_strongest_simple": (
                float(read_by_arm["D_SEMANTIC_EPISODE"]["distractor_turn_rate"])
                - float(read_by_arm[strongest_read_arm]["distractor_turn_rate"])
            ),
            "raw_fts_calls": raw_fts_calls,
            "probe_count": probe_count,
            "raw_fts_calls_per_probe": _ratio(raw_fts_calls, probe_count),
            "shared_anchor_ranking_across_arms": True,
            "acquisition_rounds_per_probe": 1,
        },
        "failure_distribution": failure_cases,
        "safety": safety,
    }


def _checks(
    metrics: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> dict[str, bool]:
    direct = _mapping(metrics.get("direct"), "direct metrics")
    simple_read = _mapping(metrics.get("simple_read"), "simple-read metrics")
    safety = _mapping(metrics.get("safety"), "safety metrics")
    semantic_read_arm = _mapping(
        _mapping(simple_read.get("by_arm"), "read arms").get("D_SEMANTIC_EPISODE"),
        "semantic read arm",
    )
    strongest_read_arm_name = str(
        _mapping(
            simple_read.get("strongest_simple_baseline"), "strongest read baseline"
        )["arm"]
    )
    strongest_read_arm = _mapping(
        _mapping(simple_read.get("by_arm"), "read arms").get(strongest_read_arm_name),
        "strongest read arm",
    )
    return {
        "semantic_pairwise_f1_threshold": (
            float(direct["semantic_pairwise_f1"])
            >= float(thresholds["semantic_episode_pairwise_f1_min"])
        ),
        "semantic_pairwise_delta_threshold": (
            float(direct["paired_macro_delta_vs_strongest_simple"])
            >= float(thresholds["semantic_vs_strongest_simple_pairwise_delta_min"])
        ),
        "support_closure_auc_delta_threshold": (
            float(simple_read["paired_macro_delta_vs_strongest_simple"])
            >= float(
                thresholds["semantic_vs_strongest_simple_support_closure_auc_delta_min"]
            )
        ),
        "distractor_turn_rate_noninferiority": (
            float(semantic_read_arm["distractor_turn_rate"])
            - float(strongest_read_arm["distractor_turn_rate"])
            <= float(thresholds["semantic_distractor_turn_rate_delta_max"])
        ),
        "raw_span_coverage_one": (
            float(safety["raw_span_coverage"]) == float(thresholds["raw_span_coverage"])
        ),
        "source_order_preservation_one": (
            float(safety["source_order_preservation"])
            == float(thresholds["source_order_preservation"])
        ),
        "user_semantic_source_precision_one": (
            float(safety["user_semantic_source_precision"])
            == float(thresholds["user_semantic_source_precision"])
        ),
        "artifact_lineage_closure_one": (
            float(safety["artifact_lineage_closure"])
            == float(thresholds["artifact_lineage_closure"])
        ),
        "external_and_model_calls_zero": all(
            int(safety[name]) == int(thresholds[name])
            for name in ("provider_calls", "reader_calls", "model_calls")
        )
        and int(safety["database_calls"]) == 0
        and int(safety["retrieval_calls"]) == 0,
        "database_writes_zero": (
            int(safety["database_writes"]) == int(thresholds["database_writes"])
        ),
        "canonical_mutations_zero": (
            int(safety["canonical_mutations"]) == int(thresholds["canonical_mutations"])
        ),
        "formal_holdout_false": (
            safety["formal_holdout_used"] is thresholds["formal_holdout_used"] is False
        ),
        "product_feature_flags_off": (
            safety["product_feature_flags"]
            == thresholds["product_feature_flags"]
            == "OFF"
        ),
        "one_raw_fts_call_per_probe": (
            float(simple_read["raw_fts_calls_per_probe"]) == 1.0
        ),
        "shared_anchor_ranking": bool(simple_read["shared_anchor_ranking_across_arms"]),
    }


def _arm_snapshot(
    arm: ArmName,
    groups: Sequence[Sequence[int]],
    turns: Sequence[Mapping[str, Any]],
    semantic_bundle: MemoryFormationBundleV01,
) -> dict[str, Any]:
    semantic_by_group = {
        tuple(
            next(
                index
                for index, turn in enumerate(turns)
                if str(turn["evidence_id"]) == span.evidence_id
            )
            for span in episode.source_spans
        ): episode
        for episode in semantic_bundle.episode_candidates
    }
    units: list[dict[str, Any]] = []
    for unit_index, group in enumerate(groups):
        spans = [
            FormationSourceSpanV01(
                evidence_id=str(turns[index]["evidence_id"]),
                source_ref=str(turns[index]["source_ref"]),
                start=0,
                end=len(str(turns[index]["content"])),
                text=str(turns[index]["content"]),
            ).model_dump(mode="json")
            for index in group
        ]
        material: dict[str, Any] = {
            "arm": arm,
            "unit_index": unit_index,
            "turn_indexes": list(group),
            "source_spans": spans,
            "session_ids": [str(turns[index]["session_id"]) for index in group],
            "canonical": False,
            "canonical_mutation": False,
        }
        if arm == "D_SEMANTIC_EPISODE":
            episode = semantic_by_group[tuple(group)]
            material["semantic_episode_digest"] = episode.episode_digest
            material["boundary_reason"] = episode.boundary_reason
        units.append({"unit_digest": canonical_sha256(material), **material})
    snapshot: dict[str, Any] = {
        "schema": "milai.mf02.representation-arm.v0.1",
        "arm": arm,
        "source_evidence_ids": [str(turn["evidence_id"]) for turn in turns],
        "units": units,
        "raw_fallback_required": True,
        "canonical": False,
        "canonical_mutation": False,
    }
    snapshot["arm_digest"] = canonical_sha256(snapshot)
    return snapshot


def _session_groups(turns: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    groups: list[list[int]] = []
    for index, turn in enumerate(turns):
        session_id = str(turn["session_id"])
        if not groups or str(turns[groups[-1][-1]]["session_id"]) != session_id:
            groups.append([index])
        else:
            groups[-1].append(index)
    return groups


def _validate_arm_snapshot(
    snapshot: Mapping[str, Any],
    turns: Sequence[Mapping[str, Any]],
    arm: ArmName,
) -> tuple[list[list[int]], int, int, bool]:
    material = dict(snapshot)
    observed_digest = material.pop("arm_digest", None)
    if observed_digest != canonical_sha256(material):
        raise MF02EffectError(f"MF02_ARM_DIGEST_INVALID:{arm}")
    groups = _groups_from_snapshot(snapshot)
    flattened = [index for group in groups for index in group]
    ordered = flattened == list(range(len(turns)))
    if not ordered or len(flattened) != len(set(flattened)):
        raise MF02EffectError(f"MF02_ARM_SOURCE_PARTITION_INVALID:{arm}")
    expected_ids = [str(turn["evidence_id"]) for turn in turns]
    if snapshot.get("source_evidence_ids") != expected_ids:
        raise MF02EffectError(f"MF02_ARM_SOURCE_IDENTITY_INVALID:{arm}")
    exact_chars = 0
    total_chars = sum(len(str(turn["content"])) for turn in turns)
    units = _sequence(snapshot.get("units"), "units")
    for group, raw_unit in zip(groups, units, strict=True):
        unit = _mapping(raw_unit, "unit")
        unit_material = dict(unit)
        unit_digest = unit_material.pop("unit_digest", None)
        if unit_digest != canonical_sha256(unit_material):
            raise MF02EffectError(f"MF02_UNIT_DIGEST_INVALID:{arm}")
        spans = [
            FormationSourceSpanV01.model_validate(item)
            for item in _sequence(unit.get("source_spans"), "source spans")
        ]
        if len(spans) != len(group):
            raise MF02EffectError(f"MF02_UNIT_SPAN_CARDINALITY_INVALID:{arm}")
        for index, span in zip(group, spans, strict=True):
            if _raw_turn_span_exact(span, turns[index]):
                exact_chars += len(span.text)
    return groups, exact_chars, total_chars, ordered


def _groups_from_snapshot(snapshot: Mapping[str, Any]) -> list[list[int]]:
    return [
        [
            int(index)
            for index in _sequence(
                _mapping(unit, "unit").get("turn_indexes"), "turn indexes"
            )
        ]
        for unit in _sequence(snapshot.get("units"), "units")
    ]


def _direct_conversation(
    predicted_groups: Sequence[Sequence[int]],
    expected_groups: Sequence[Sequence[int]],
    turn_count: int,
) -> dict[str, float]:
    predicted_membership = _membership(predicted_groups, turn_count)
    expected_membership = _membership(expected_groups, turn_count)
    pair_tp = pair_fp = pair_fn = 0
    for left in range(turn_count):
        for right in range(left + 1, turn_count):
            predicted_same = predicted_membership[left] == predicted_membership[right]
            expected_same = expected_membership[left] == expected_membership[right]
            pair_tp += int(predicted_same and expected_same)
            pair_fp += int(predicted_same and not expected_same)
            pair_fn += int(not predicted_same and expected_same)
    predicted_boundaries = {int(group[0]) for group in predicted_groups[1:]}
    expected_boundaries = {int(group[0]) for group in expected_groups[1:]}
    boundary_tp = len(predicted_boundaries & expected_boundaries)
    boundary_fp = len(predicted_boundaries - expected_boundaries)
    boundary_fn = len(expected_boundaries - predicted_boundaries)
    self_contained = sum(
        any(set(expected).issubset(set(predicted)) for predicted in predicted_groups)
        for expected in expected_groups
    )
    cross_boundary_units = sum(
        len({expected_membership[index] for index in predicted}) > 1
        for predicted in predicted_groups
    )
    return {
        "episode_pairwise_precision": _ratio(pair_tp, pair_tp + pair_fp),
        "episode_pairwise_recall": _ratio(pair_tp, pair_tp + pair_fn),
        "episode_pairwise_f1": _f1(pair_tp, pair_fp, pair_fn),
        "boundary_precision": _ratio(boundary_tp, boundary_tp + boundary_fp),
        "boundary_recall": _ratio(boundary_tp, boundary_tp + boundary_fn),
        "boundary_f1": _f1(boundary_tp, boundary_fp, boundary_fn),
        "self_containedness": _ratio(self_contained, len(expected_groups)),
        "cross_boundary_dependency_rate": _ratio_zero(
            cross_boundary_units, len(predicted_groups)
        ),
        "pair_true_positive": float(pair_tp),
        "pair_false_positive": float(pair_fp),
        "pair_false_negative": float(pair_fn),
        "boundary_true_positive": float(boundary_tp),
        "boundary_false_positive": float(boundary_fp),
        "boundary_false_negative": float(boundary_fn),
    }


def _hydrate(
    snapshot: Mapping[str, Any], ranked_ids: Sequence[str], ceiling: int
) -> list[str]:
    units = [
        _mapping(item, "unit") for item in _sequence(snapshot.get("units"), "units")
    ]
    unit_by_evidence: dict[str, Mapping[str, Any]] = {}
    for unit in units:
        for raw_span in _sequence(unit.get("source_spans"), "source spans"):
            span = _mapping(raw_span, "source span")
            unit_by_evidence[str(span["evidence_id"])] = unit
    hydrated: list[str] = []
    hydrated_set: set[str] = set()
    admitted_units: set[str] = set()
    for evidence_id in ranked_ids:
        unit = unit_by_evidence[evidence_id]
        unit_digest = str(unit["unit_digest"])
        if unit_digest in admitted_units:
            continue
        unit_ids = [
            str(_mapping(span, "span")["evidence_id"])
            for span in _sequence(unit.get("source_spans"), "source spans")
        ]
        new_ids = [item for item in unit_ids if item not in hydrated_set]
        if len(hydrated_set) + len(new_ids) > ceiling:
            break
        admitted_units.add(unit_digest)
        hydrated.extend(new_ids)
        hydrated_set.update(new_ids)
    if len(hydrated_set) > ceiling:
        raise MF02EffectError("MF02_HYDRATION_RAW_TURN_BUDGET_EXCEEDED")
    return hydrated


def _aggregate_read_rows(
    rows: Sequence[Mapping[str, Any]], ceilings: Sequence[int]
) -> dict[str, Any]:
    rates: dict[str, dict[str, float]] = {}
    for ceiling in ceilings:
        ceiling_rows = [
            _mapping(
                _mapping(row.get("per_ceiling"), "per ceiling").get(str(ceiling)),
                "ceiling row",
            )
            for row in rows
        ]
        rates[str(ceiling)] = {
            "support_closure_rate": mean(
                float(item["support_closed"]) for item in ceiling_rows
            ),
            "required_evidence_coverage": mean(
                float(item["required_evidence_coverage"]) for item in ceiling_rows
            ),
            "useful_turn_rate": mean(
                float(item["useful_turn_rate"]) for item in ceiling_rows
            ),
            "distractor_turn_rate": mean(
                float(item["distractor_turn_rate"]) for item in ceiling_rows
            ),
            "cross_episode_contamination_rate": mean(
                float(item["cross_episode_contamination_rate"]) for item in ceiling_rows
            ),
        }
    closed_minimums = [
        int(row["minimum_turns_to_closure"])
        for row in rows
        if row["minimum_turns_to_closure"] is not None
    ]
    return {
        "support_closure_auc": mean(
            rate["support_closure_rate"] for rate in rates.values()
        ),
        "support_closure_rate_by_ceiling": {
            ceiling: value["support_closure_rate"] for ceiling, value in rates.items()
        },
        "required_evidence_coverage_by_ceiling": {
            ceiling: value["required_evidence_coverage"]
            for ceiling, value in rates.items()
        },
        "useful_turn_rate": mean(value["useful_turn_rate"] for value in rates.values()),
        "distractor_turn_rate": mean(
            value["distractor_turn_rate"] for value in rates.values()
        ),
        "cross_episode_contamination_rate": mean(
            value["cross_episode_contamination_rate"] for value in rates.values()
        ),
        "mean_minimum_turns_to_closure": (
            mean(closed_minimums) if closed_minimums else None
        ),
        "unclosed_probe_count": len(rows) - len(closed_minimums),
        "anchor_pool_required_hit_rate": mean(
            float(row["anchor_pool_hits_required"]) for row in rows
        ),
        "probe_count": len(rows),
    }


def _bootstrap_ci(
    deltas_by_conversation: Mapping[str, float], *, seed: int, resamples: int
) -> dict[str, Any]:
    values = [float(value) for _, value in sorted(deltas_by_conversation.items())]
    if not values:
        raise MF02EffectError("MF02_BOOTSTRAP_DENOMINATOR_EMPTY")
    generator = random.Random(seed)
    estimates = sorted(
        mean(generator.choice(values) for _ in values) for _ in range(resamples)
    )
    lower_index = max(0, int(0.025 * resamples) - 1)
    upper_index = min(resamples - 1, int(0.975 * resamples))
    return {
        "lower": estimates[lower_index],
        "upper": estimates[upper_index],
        "seed": seed,
        "resamples": resamples,
        "unit": "conversation",
    }


def _verify_run_lock(
    root: Path,
    lock: Mapping[str, Any],
    fixture: Mapping[str, Any],
    fixture_key: str,
) -> None:
    material = dict(lock)
    observed_digest = material.pop("run_lock_digest", None)
    if observed_digest != canonical_sha256(material):
        raise MF02EffectError("MF02_RUN_LOCK_DIGEST_INVALID")
    identity = _mapping(
        _mapping(lock.get("fixtures"), "fixtures").get(fixture_key),
        "fixture identity",
    )
    fixture_path = root / str(identity["path"])
    if hashlib.sha256(fixture_path.read_bytes()).hexdigest() != identity["sha256"]:
        raise MF02EffectError("MF02_FIXTURE_DRIFT_AFTER_LABEL_SEAL")
    if fixture.get("formal_holdout") is not False:
        raise MF02EffectError("MF02_FORMAL_HOLDOUT_FORBIDDEN")
    conversations = _sequence(fixture.get("conversations"), "conversations")
    if len(conversations) != int(identity["conversation_count"]):
        raise MF02EffectError("MF02_FIXTURE_DENOMINATOR_DRIFT")
    if lock.get("scorer_present_at_label_seal") is not False:
        raise MF02EffectError("MF02_LABEL_SEAL_ORDER_INVALID")


def _membership(groups: Sequence[Sequence[int]], turn_count: int) -> list[int]:
    output = [-1] * turn_count
    for group_index, group in enumerate(groups):
        for turn_index in group:
            if turn_index < 0 or turn_index >= turn_count or output[turn_index] != -1:
                raise MF02EffectError("MF02_EPISODE_MEMBERSHIP_INVALID")
            output[turn_index] = group_index
    if any(value == -1 for value in output):
        raise MF02EffectError("MF02_EPISODE_MEMBERSHIP_INCOMPLETE")
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


def _raw_turn_span_exact(
    span: FormationSourceSpanV01, source: Mapping[str, Any]
) -> bool:
    content = str(source["content"])
    return (
        span.evidence_id == source["evidence_id"]
        and span.source_ref == source["source_ref"]
        and span.start == 0
        and span.end == len(content)
        and span.text == content
    )


def _lineage_span_exact(
    span: FormationSourceSpanV01, source: Mapping[str, Any]
) -> bool:
    content = str(source["content"])
    return (
        span.evidence_id == source["evidence_id"]
        and span.source_ref == source["source_ref"]
        and 0 <= span.start < span.end <= len(content)
        and content[span.start : span.end] == span.text
    )


def _terms(value: str) -> list[str]:
    return [
        term.casefold()
        for term in _WORD.findall(value)
        if len(term) > 1 and term.casefold() not in _FTS_STOP
    ]


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    if precision + recall:
        return 2 * precision * recall / (precision + recall)
    return 1.0 if true_positive == false_positive == false_negative == 0 else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _ratio_zero(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"MF02_JSON_OBJECT_REQUIRED:{path}")
    return value


def _mapping(value: object, source: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MF02_MAPPING_REQUIRED:{source}")
    return value


def _sequence(value: object, source: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"MF02_SEQUENCE_REQUIRED:{source}")
    return value


__all__ = [
    "ARM_NAMES",
    "MF02EffectError",
    "RawFtsAcquirer",
    "build_representation_arms",
    "environment_witness",
    "evaluate_repair_dev",
    "execute_mf02_effect",
    "hand_scorer_sanity",
    "md01_scorer_sanity",
]
