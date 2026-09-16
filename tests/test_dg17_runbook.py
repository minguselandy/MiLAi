from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/runbooks/dg17-semantic-read.md"


def test_dg17_runbook_freezes_semantic_read_and_legacy_atom_boundaries() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "EvidenceSpan" in text
    assert "EvidenceInterpretationCandidate" in text
    assert "RequirementBinding" in text
    assert "EvidenceAtom v0.1` transition disposition" in text
    assert "not a persisted or public MCP object" in text
    assert "embeds no final requirement slot" in text
    assert "EVIDENCE_ONLY / DERIVED_VIEW" in text
    assert "Top-k never proves completeness" in text
    assert "PARKED_NOT_NEEDED" in text
    assert "frozen scorer unchanged" in text
    assert "must not be mixed into Q6" in text
    assert "Neither lane may receive the deterministic route" in text
    assert "counterfactual cost overlay" in text
    assert "exact source-turn plus normalized span identity" in text
    assert "execution_authorized=true" in text
    assert "semantic_context_digest" in text
    assert "reader_context_digest" in text
    assert "receipt_mapping" in text
    assert "immutable Evidence snapshot" in text
    assert "historical answers are rejected" in text
    assert "CONFOUNDED / EXCLUDED FROM CAUSAL CLAIM" in text
    assert "exactly three independent" in text
    assert "no repeat may replace the primary" in text
    assert "run_dg17_q1r_matched.py" in text
