from __future__ import annotations

from pathlib import Path

import pytest
from milai.observability.formation_audit import FormationTraceRecord

from evals.mf01.first_loss import (
    behavior_equivalence_smoke,
    build_passive_traces,
    score_first_loss,
)
from evals.mf01.labels import FormationLabelSeal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def audit() -> tuple[FormationLabelSeal, list[FormationTraceRecord]]:
    return build_passive_traces(ROOT)


def test_passive_trace_has_exact_sealed_denominator(
    audit: tuple[FormationLabelSeal, list[FormationTraceRecord]],
) -> None:
    seal, traces = audit

    assert seal.label_count == 125
    assert len(traces) == 125
    assert len({item.obligation_id for item in traces}) == 125
    assert all(item.source_lineage_ok for item in traces)
    assert all(item.audit_authority is False for item in traces)
    assert all(item.canonical_mutation is False for item in traces)
    assert all(item.provider_calls == 0 for item in traces)


def test_first_loss_distribution_matches_frozen_actual_path(
    audit: tuple[FormationLabelSeal, list[FormationTraceRecord]],
) -> None:
    seal, traces = audit
    behavior = behavior_equivalence_smoke(ROOT, seal)

    score = score_first_loss(seal, traces, behavior)

    assert score["first_loss_distribution"] == {
        "F10_EPISODE_FORMED": 4,
        "F20_MENTION_FORMED": 28,
        "F30_IDENTITY_RESOLVED": 28,
        "F40_EVENT_TIME_GROUNDED": 2,
        "F50_STATE_OR_CHANGE_FORMED": 9,
        "F60_PROPOSAL_EMITTED": 4,
        "TERMINAL_SURVIVAL": 50,
    }
    assert score["status"] == "PASS_FORMATION_FIRST_LOSS_LOCALIZED"


def test_behavior_equivalence_is_exact_and_call_free(
    audit: tuple[FormationLabelSeal, list[FormationTraceRecord]],
) -> None:
    seal, _traces = audit

    behavior = behavior_equivalence_smoke(ROOT, seal)

    assert behavior["exact_match"] is True
    assert all(behavior["checks"].values())
    assert behavior["introduced_provider_calls"] == 0
    assert behavior["canonical_mutations_caused_by_audit"] == 0
