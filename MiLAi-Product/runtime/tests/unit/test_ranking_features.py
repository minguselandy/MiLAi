from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from milai.application.acquisition import rank_evidence_turns


@pytest.mark.parametrize("query", [
    "tea", "How long did tea take?", "How many mugs?", "cost euros", "正文", "",
])
@pytest.mark.parametrize("speakers", [(), ("user",), ("assistant",)])
def test_reusable_text_features_preserve_complete_rows_and_fresh_metadata(
    query: str, speakers: tuple[str, ...],
) -> None:
    rows = [{
        "source_ref": str(i), "content": text, "relevance_score": i % 3,
        "observed_at": str(10 - i), "anchor_match": i == 2,
        "speaker": "user" if i % 2 else "assistant",
        "speaker_source": "STRUCTURED_TURN_METADATA",
    } for i, text in enumerate([
        "tea took 3 hours", "4 mugs cost 10 euros", "first\n正文\nlast", "", None,
        "tea took 3 hours", "3-day plan; 7 hours", "TEA tea café",
    ])]
    cache: dict[tuple[str, str], tuple[int, bool]] = {}
    expected = rank_evidence_turns(rows, query, preferred_speakers=speakers)
    assert rank_evidence_turns(
        rows, query, preferred_speakers=speakers, feature_cache=cache,
    ) == expected
    changed = deepcopy(rows)
    changed[0].update(content="updated 12 mugs", relevance_score=999, anchor_match=True)
    changed[1].update(speaker="assistant", observed_at="earlier")
    changed.reverse()
    assert rank_evidence_turns(
        changed, query, preferred_speakers=speakers, feature_cache=cache,
    ) == rank_evidence_turns(changed, query, preferred_speakers=speakers)


def test_cache_keys_bind_both_query_and_exact_text_without_retaining_result_rows() -> None:
    cache: dict[tuple[str, str], tuple[int, bool]] = {}
    row: dict[str, Any] = {"evidence_id": "same-id", "content": "tea took 3 hours"}
    for query in ["tea", "How long did tea take?", "other"]:
        rank_evidence_turns([row], query, feature_cache=cache)
    row["content"] = "coffee took 4 hours"
    rank_evidence_turns([row], "tea", feature_cache=cache)
    assert len(cache) == 4
    assert cache[("tea", "tea took 3 hours")] == (1, False)
    assert cache[("tea", "coffee took 4 hours")] == (0, False)
    assert all(
        isinstance(covered, int) and isinstance(answer, bool) for covered, answer in cache.values()
    )
