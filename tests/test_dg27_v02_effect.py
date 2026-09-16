from __future__ import annotations

import json
from pathlib import Path

from milai.domain.decision_boundary import GroundedSpanV02

from evals.dg27.decision_boundary import (
    frozen_candidate_manifest,
    historical_baseline_accepted_sources,
    historical_wrong_complete_occurrences,
    score_effect,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = (
    ROOT
    / "var/dg24/s0/dg24-s0-freeze-20260829-008/scorer-only/"
    "gold-equivalence-registry-v0.1.json"
)


def test_v02_freeze_denominators_are_exact() -> None:
    manifest = frozen_candidate_manifest(ROOT)
    replay = historical_wrong_complete_occurrences(ROOT)

    assert len(manifest) == 15
    assert sum(len(row["candidates"]) for row in manifest) == 110
    assert len({row["case_id"] for row in manifest}) == 10
    assert len(replay) == 16
    assert [row["arm_id"] for row in replay[::2]] == [
        "R1",
        "R2",
        "R3",
        "R4",
        "R5_NO_SYNONYM_NORMALIZATION",
        "R_FINAL_DROP_OPTIONAL_CHANNEL_UNION",
        "R_FINAL_DROP_ROLE_RESERVATION",
        "R_FINAL_DROP_SOFT_LEXICAL_FEATURES",
    ]
    assert {row["requirement_id"] for row in replay} == {
        "MATCHING_EVENTS_IN_RANGE"
    }


def test_wrong_complete_requires_all_gold_groups_not_any_binding() -> None:
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    accepted = {
        "requirement_id": "MATCHING_EVENTS_IN_RANGE",
        "evidence_id": "fixture",
        "source_ref": "2e6d26dc:s4:session-8db436507bbd8c1802a6c586:t0",
    }
    record = {
        "case_id": "2e6d26dc",
        "decision": {
            "operator_ready": True,
            "provisional_bindings": [],
            "sufficiency_decision": {"status": "COMPLETE"},
        },
        "accepted_sources": [accepted],
    }
    unscored = {
        "D0_replay": historical_wrong_complete_occurrences(ROOT),
        "D0_baseline_accepted_sources": historical_baseline_accepted_sources(ROOT),
        "arms": {arm: [record] for arm in ("D1", "D2", "D3")},
    }

    scores = score_effect(unscored, gold)

    assert scores["arms"]["D1"]["wrong_complete"] == 1
    assert scores["arms"]["D2"]["wrong_complete"] == 1
    assert scores["arms"]["D3"]["wrong_complete"] == 1


def test_unicode_offsets_use_python_character_boundaries() -> None:
    content = "用户说：我喜欢咖啡☕。"
    quote = "我喜欢咖啡☕"
    start = content.index(quote)

    span = GroundedSpanV02(
        start=start,
        end=start + len(quote),
        text=quote,
    )

    assert content[span.start : span.end] == quote
