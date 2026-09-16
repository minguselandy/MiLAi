from __future__ import annotations

import pytest

from milai_lab.scorers.answers import ScoringInputError, score_normalized_em_f1_v1


def test_normalized_scorer_is_explicitly_non_official() -> None:
    score = score_normalized_em_f1_v1("The Blue Car", ("blue car",))

    assert score["exact_match"] == 1
    assert score["normalized_f1"] == 1.0
    assert "NOT_OFFICIAL_LONGMEMEVAL_SCORE" in str(score["scorer"])


def test_normalized_scorer_requires_reference() -> None:
    with pytest.raises(ScoringInputError):
        score_normalized_em_f1_v1("answer", ())

