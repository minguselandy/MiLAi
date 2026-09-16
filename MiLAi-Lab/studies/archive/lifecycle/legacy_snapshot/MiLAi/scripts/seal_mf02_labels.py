#!/usr/bin/env python3
"""Seal MF-02 repair-dev and independent validation before scorer creation."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPAIR_FIXTURE = ROOT / "evals/mf02/fixtures/repair-dev.v0.1.json"
SEALED_FIXTURE = ROOT / "evals/mf02/fixtures/sealed-validation.v0.1.json"
SCORER = ROOT / "evals/mf02/four_arm_effect.py"
SEMANTIC_BUILDER = ROOT / "runtime/src/milai/application/memory_formation.py"
MD01_TERMINAL = (
    ROOT / "var/md01/md01-memory-formation-bundle-20260830-001/terminal.json"
)
RUN_DIR = ROOT / "var/mf02/mf02-semantic-episode-four-arm-20260830-001"
RUN_LOCK = RUN_DIR / "run-lock.json"

REQUIRED_FAMILIES = {
    "LONG_GAP_SAME_TOPIC",
    "SHORT_GAP_TRUE_TOPIC_SHIFT",
    "LEXICAL_DISJOINT_EVENT_CONTINUATION",
    "LEXICAL_OVERLAP_TOPIC_SHIFT",
    "UNCUED_CORRECTION",
    "PRONOUN_NEW_TOPIC",
    "ASSISTANT_ANECDOTE_COMPETITION",
    "MULTIPLE_MEMORIES_ONE_SESSION",
}


def seal() -> dict[str, Any]:
    if SCORER.exists():
        raise RuntimeError("MF02_SCORER_MUST_NOT_EXIST_BEFORE_LABEL_SEAL")
    repair = _object(REPAIR_FIXTURE)
    sealed = _object(SEALED_FIXTURE)
    repair_summary = _validate_fixture(repair, expected_split="repair-dev")
    sealed_summary = _validate_fixture(sealed, expected_split="sealed-validation")
    if repair_summary["conversation_count"] != 8:
        raise RuntimeError("MF02_REPAIR_DEV_DENOMINATOR_INVALID")
    if sealed_summary["conversation_count"] < 24 or sealed_summary["turn_count"] < 96:
        raise RuntimeError("MF02_SEALED_VALIDATION_DENOMINATOR_TOO_SMALL")
    family_counts = Counter(sealed_summary["family_counts"])
    if set(family_counts) != REQUIRED_FAMILIES or any(
        family_counts[family] < 3 for family in REQUIRED_FAMILIES
    ):
        raise RuntimeError("MF02_SEALED_COUNTEREXAMPLE_COVERAGE_INVALID")
    if not MD01_TERMINAL.is_file():
        raise RuntimeError("MF02_MD01_PREDECESSOR_MISSING")

    payload: dict[str, Any] = {
        "schema": "milai.mf02.run-lock.v0.1",
        "run_id": RUN_DIR.name,
        "sealed_at": datetime.now(UTC).isoformat(),
        "execution_authority": "USER_EXPLICIT_20260830_MF02_EXECUTE",
        "predecessor_terminal": _identity(MD01_TERMINAL),
        "semantic_builder_at_label_seal": _identity(SEMANTIC_BUILDER),
        "scorer_present_at_label_seal": False,
        "fixtures": {
            "repair_dev": {
                **_identity(REPAIR_FIXTURE),
                **repair_summary,
            },
            "sealed_validation": {
                **_identity(SEALED_FIXTURE),
                **sealed_summary,
            },
        },
        "arms": {
            "A_TURN": "one complete Raw turn per unit",
            "B_FIXED_WINDOW_2": "session-local non-overlapping two-turn windows; singleton tail allowed",
            "C_SESSION": "all turns in one session per unit",
            "D_SEMANTIC_EPISODE": "runtime SemanticEpisodeCandidateV01 builder",
        },
        "thresholds": {
            "semantic_episode_pairwise_f1_min": 0.85,
            "semantic_vs_strongest_simple_pairwise_delta_min": 0.05,
            "semantic_vs_strongest_simple_support_closure_auc_delta_min": 0.05,
            "semantic_distractor_turn_rate_delta_max": 0.02,
            "raw_span_coverage": 1.0,
            "source_order_preservation": 1.0,
            "user_semantic_source_precision": 1.0,
            "artifact_lineage_closure": 1.0,
            "canonical_mutations": 0,
            "database_writes": 0,
            "provider_calls": 0,
            "reader_calls": 0,
            "model_calls": 0,
            "formal_holdout_used": False,
            "product_feature_flags": "OFF",
        },
        "protocol": {
            "raw_turn_ceilings": list(range(1, 9)),
            "official_raw_fts_calls_per_probe": 1,
            "anchor_ranking_shared_across_arms": True,
            "unit_atomicity": True,
            "budget_unit": "unique hydrated Raw turns",
            "acquisition_rounds_per_probe": 1,
            "official_protocol_valid_effect_attempts": 1,
            "bootstrap": {
                "unit": "conversation",
                "seed": 20260830,
                "resamples": 2000,
                "confidence": 0.95,
            },
            "md01_historical_replay_in_main_denominator": False,
            "builder_visible_fields": [
                "evidence_id",
                "source_ref",
                "session_id",
                "speaker",
                "speaker_source",
                "observed_at",
                "content",
                "permission_snapshot",
                "retention_state",
                "revoked_at",
            ],
            "builder_forbidden_fields": [
                "conversation_id",
                "counterexample_families",
                "expected_episodes",
                "memory_probes",
                "required_support_evidence_ids",
                "distractor_evidence_ids",
            ],
        },
        "scope": {
            "formal_holdout_used": False,
            "gpu_hours": 0,
            "model_provider_reader_database_calls": 0,
            "experimental_feature_flags": "OFF",
            "canonical": False,
        },
    }
    payload["run_lock_digest"] = _canonical_sha256(payload)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    _write_exclusive(RUN_LOCK, payload)
    return payload


def _validate_fixture(
    value: Mapping[str, Any], *, expected_split: str
) -> dict[str, Any]:
    if value.get("schema") != "milai.mf02.episode-validation.v0.1":
        raise RuntimeError("MF02_FIXTURE_SCHEMA_INVALID")
    if value.get("split") != expected_split or value.get("formal_holdout") is not False:
        raise RuntimeError("MF02_FIXTURE_SCOPE_INVALID")
    conversations = _sequence(value.get("conversations"), "conversations")
    if not conversations:
        raise RuntimeError("MF02_FIXTURE_EMPTY")
    conversation_ids: set[str] = set()
    evidence_ids: set[str] = set()
    source_refs: set[str] = set()
    probe_ids: set[str] = set()
    family_counts: Counter[str] = Counter()
    turn_count = 0
    episode_count = 0
    probe_count = 0
    for raw_conversation in conversations:
        conversation = _mapping(raw_conversation, "conversation")
        conversation_id = _nonempty(
            conversation.get("conversation_id"), "conversation_id"
        )
        if conversation_id in conversation_ids:
            raise RuntimeError("MF02_CONVERSATION_ID_DUPLICATED")
        conversation_ids.add(conversation_id)
        families = _sequence(conversation.get("counterexample_families"), "families")
        if not families:
            raise RuntimeError("MF02_COUNTEREXAMPLE_FAMILY_REQUIRED")
        for family in families:
            family_counts[_nonempty(family, "counterexample family")] += 1

        turns = _sequence(conversation.get("turns"), "turns")
        expected = _sequence(conversation.get("expected_episodes"), "expected episodes")
        probes = _sequence(conversation.get("memory_probes"), "memory probes")
        if len(turns) < 2 or not expected or not probes:
            raise RuntimeError("MF02_CONVERSATION_DENOMINATOR_INVALID")
        local_ids: list[str] = []
        observed_times: list[datetime] = []
        roles: dict[str, str] = {}
        for raw_turn in turns:
            turn = _mapping(raw_turn, "turn")
            evidence_id = _nonempty(turn.get("evidence_id"), "evidence_id")
            source_ref = _nonempty(turn.get("source_ref"), "source_ref")
            if evidence_id in evidence_ids or source_ref in source_refs:
                raise RuntimeError("MF02_SOURCE_IDENTITY_DUPLICATED")
            evidence_ids.add(evidence_id)
            source_refs.add(source_ref)
            local_ids.append(evidence_id)
            role = _nonempty(turn.get("speaker"), "speaker").casefold()
            if role not in {"user", "assistant"}:
                raise RuntimeError("MF02_SOURCE_ROLE_INVALID")
            roles[evidence_id] = role
            timestamp = datetime.fromisoformat(
                _nonempty(turn.get("observed_at"), "observed_at").replace("Z", "+00:00")
            )
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise RuntimeError("MF02_SOURCE_TIME_NOT_AWARE")
            observed_times.append(timestamp)
            if (
                turn.get("permission_snapshot") != {"readable": True}
                or turn.get("retention_state") != "READABLE"
                or turn.get("revoked_at") is not None
            ):
                raise RuntimeError("MF02_SEALED_SOURCE_NOT_READABLE")
        if observed_times != sorted(observed_times):
            raise RuntimeError("MF02_SOURCE_ORDER_INVALID")

        groups: list[list[int]] = []
        for raw_episode in expected:
            episode = _mapping(raw_episode, "expected episode")
            indexes = [
                int(item)
                for item in _sequence(episode.get("turn_indexes"), "turn indexes")
            ]
            if not indexes:
                raise RuntimeError("MF02_EXPECTED_EPISODE_EMPTY")
            groups.append(indexes)
        if [index for group in groups for index in group] != list(range(len(turns))):
            raise RuntimeError("MF02_EXPECTED_EPISODE_PARTITION_INVALID")
        if (
            _mapping(expected[0], "first episode").get("boundary_reason")
            != "CONVERSATION_START"
        ):
            raise RuntimeError("MF02_INITIAL_BOUNDARY_REASON_INVALID")
        membership = {
            index: group_index
            for group_index, group in enumerate(groups)
            for index in group
        }
        same_pair = any(
            membership[left] == membership[right]
            for left in range(len(turns))
            for right in range(left + 1, len(turns))
        )
        cross_pair = any(
            membership[left] != membership[right]
            for left in range(len(turns))
            for right in range(left + 1, len(turns))
        )
        if not same_pair or not cross_pair:
            raise RuntimeError("MF02_PAIRWISE_DENOMINATOR_UNINFORMATIVE")

        for raw_probe in probes:
            probe = _mapping(raw_probe, "memory probe")
            probe_id = _nonempty(probe.get("probe_id"), "probe_id")
            if probe_id in probe_ids:
                raise RuntimeError("MF02_PROBE_ID_DUPLICATED")
            probe_ids.add(probe_id)
            _nonempty(probe.get("query_text"), "query_text")
            required = {
                _nonempty(item, "required support")
                for item in _sequence(
                    probe.get("required_support_evidence_ids"), "required support"
                )
            }
            distractors = {
                _nonempty(item, "distractor")
                for item in _sequence(
                    probe.get("distractor_evidence_ids"), "distractors"
                )
            }
            if len(required) < 2 or not required.issubset(local_ids):
                raise RuntimeError("MF02_PROBE_SUPPORT_IDENTITY_INVALID")
            if not distractors.issubset(local_ids) or required & distractors:
                raise RuntimeError("MF02_PROBE_DISTRACTOR_IDENTITY_INVALID")
            if any(roles[item] != "user" for item in required):
                raise RuntimeError("MF02_REQUIRED_SUPPORT_MUST_BE_USER_EVIDENCE")
        turn_count += len(turns)
        episode_count += len(expected)
        probe_count += len(probes)
    return {
        "conversation_count": len(conversations),
        "turn_count": turn_count,
        "episode_count": episode_count,
        "probe_count": probe_count,
        "family_counts": dict(sorted(family_counts.items())),
        "formal_holdout": False,
    }


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def _nonempty(value: object, source: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"MF02_NONEMPTY_TEXT_REQUIRED:{source}")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2, sort_keys=True))
