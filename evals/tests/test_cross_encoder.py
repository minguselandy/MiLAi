from __future__ import annotations

import pytest

from evals.benchmark.dg11_cross_encoder import blend_scores


def test_blend_scores_normalizes_both_sources_and_preserves_order() -> None:
    assert blend_scores([1.0, 3.0], [10.0, 0.0], cross_encoder_weight=0.8) == pytest.approx(
        [0.2, 0.8]
    )


def test_blend_scores_rejects_invalid_shapes_and_weight() -> None:
    with pytest.raises(ValueError, match="equal length"):
        blend_scores([1.0], [], cross_encoder_weight=1.0)
    with pytest.raises(ValueError, match="between zero and one"):
        blend_scores([1.0], [1.0], cross_encoder_weight=1.1)
