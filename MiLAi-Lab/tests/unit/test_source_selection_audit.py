"""Semantic alternative sources must be included even when native support missed them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from audit_source_selection import overlap, panel


def test_reviewed_alternative_and_partial_sources_participate_in_boundary():
    def record(row, entries):
        return {"metadata": {"row": row}, "source": {"question": f"q{row}", "paragraphs": [
            {"idx": i, "title": title, "paragraph_text": body, "is_supporting": support}
            for i, (title, body, support) in enumerate(entries)]}}

    train = record(1, [("native", "native body", True), ("alternative", "fact", False),
                       ("partial", "premise", False), ("background", "shared", False)])
    dev = record(2, [("alternative", "fact", False), ("partial", "different extract", False),
                     ("background", "shared", False)])
    reviews = {1: {"complete_proofs": [[1]], "qualified_alternative_proofs": [],
                   "useful_partial_evidence": [2]}}
    result = overlap(panel([train], reviews), panel([dev], {}))
    assert result["left_target_in_right_pool"] == ["alternative"]
    assert result["left_target_title_in_right_pool"] == ["alternative", "partial"]
    assert result["shared_literal_background_or_target"] == 2
    assert "background" not in result["left_target_title_in_right_pool"]
