"""A matching source ID or one partial page must not count as presented support."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from replay_v0213_cost import sha
from summarize_v0216 import support_coverage


def test_support_requires_current_matching_contiguous_bytes():
    raw = b"background TARGET SUPPORT trailing"
    sources = {"source-03.txt": raw}

    def page(start, end):
        return {"source_id": "source-03.txt", "version": sha(raw), "cursor": start,
                "text": raw[start:end].decode()}

    facts = ["TARGET SUPPORT"]
    assert support_coverage(sources, facts, [page(0, 10)]) == [False]
    assert support_coverage(sources, facts, [page(11, 20), page(20, 30)]) == [True]
    assert support_coverage(sources, facts, [page(11, 18), page(20, 30)]) == [False]
    wrong = page(0, len(raw))
    wrong["version"] = "old"
    assert support_coverage(sources, facts, [wrong]) == [False]
    wrong["version"], wrong["text"] = sha(raw), "TARGET SUPPORT"
    assert support_coverage(sources, facts, [wrong]) == [False]
