from __future__ import annotations

import json
from pathlib import Path

from milai.domain.requirement_state import canonical_sha256

from scripts.run_md02_semantic_episode_shadow import (
    LEGAL_STATUSES,
    OUTPUT_DIR,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]


def test_md02_terminal_artifacts_are_digest_linked_and_protocol_complete() -> None:
    result = validate()

    assert result["valid"] is True
    assert result["status"] in LEGAL_STATUSES
    assert result["safety"]["boundary"]["formal_holdout_used"] is False
    assert result["safety"]["boundary"]["default_feature_flag"] == "OFF"
    assert result["safety"]["shadow"]["formal_holdout_used"] is False
    assert result["safety"]["shadow"]["default_feature_flag"] == "OFF"
    assert result["safety"]["shadow"]["public_mcp_changed"] is False
    assert result["safety"]["shadow"]["schema_changed"] is False
    assert result["safety"]["shadow"]["database_accessed"] is False


def test_md02_effect_keeps_only_the_authorized_artifacts() -> None:
    artifacts = {path.name for path in Path(OUTPUT_DIR).iterdir() if path.is_file()}

    assert artifacts == {
        "run-lock.json",
        "results.json",
        "terminal.json",
        "repair-log.jsonl",
    }


def test_md02_sealed_labels_are_determinable_and_close_over_raw_sources() -> None:
    for relative_path in (
        "evals/md02/fixtures/boundary-repair-dev.v0.1.json",
        "evals/md02/fixtures/shadow-validation.v0.1.json",
    ):
        fixture = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
        for conversation in fixture["conversations"]:
            turns = conversation["turns"]
            episodes = conversation["expected_episodes"]
            indexes = [
                index for episode in episodes for index in episode["turn_indexes"]
            ]
            assert indexes == list(range(len(turns)))
            assert len({turn["evidence_id"] for turn in turns}) == len(turns)
            assert len({turn["source_ref"] for turn in turns}) == len(turns)
            assert all(turn["speaker"] in {"user", "assistant"} for turn in turns)
            assert all(
                turn["speaker_source"] == "STRUCTURED_TURN_METADATA" for turn in turns
            )
            assert all(
                turn["content_hash"] == canonical_sha256(turn["content"])
                for turn in turns
            )
            membership = {
                index: episode_index
                for episode_index, episode in enumerate(episodes)
                for index in episode["turn_indexes"]
            }
            pair_labels = [
                membership[left] == membership[right]
                for left in range(len(turns))
                for right in range(left + 1, len(turns))
            ]
            assert any(pair_labels) and not all(pair_labels)
            source_ids = {turn["evidence_id"] for turn in turns}
            for probe in conversation["memory_probes"]:
                required = set(probe["required_support_evidence_ids"])
                distractors = set(probe["distractor_evidence_ids"])
                assert required <= source_ids
                assert distractors <= source_ids
                assert required.isdisjoint(distractors)
