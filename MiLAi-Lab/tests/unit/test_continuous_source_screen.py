"""Offline screening cannot silently select future material or fabricate task coverage."""
import copy
import json

import pytest

from screen_continuous_sources import parse_screen, validate_chunk


def chunk():
    return {"source_rows": [{"source_index": 2, "source": {"content": "original A"}},
                            {"source_index": 3, "source": {"content": "original B"}}],
            "eligible_questions": [{"request": "q", "available_through_source_count": 4}]}


def answer(indices, coverage="selected"):
    return json.dumps({"selections": [{"request": "q", "source_indices": indices,
                                       "coverage": coverage}]})


def test_selection_preserves_unknown_and_does_not_generate_answers():
    original = chunk()
    before = copy.deepcopy(original)
    result = parse_screen(answer([3], "unknown"), original)
    assert result == {"format_error": False, "selections": [
        {"request": "q", "source_indices": [3], "coverage": "unknown"}]}
    assert original == before
    assert parse_screen(answer([], "none"), original)["selections"][0]["coverage"] == "none"


@pytest.mark.parametrize("indices,coverage", [([4], "selected"), ([1], "selected"),
    ([2, 2], "selected"), ([], "selected"), ([2], "none")])
def test_invalid_or_contradictory_selection_is_not_repaired(indices, coverage):
    with pytest.raises(ValueError):
        parse_screen(answer(indices, coverage), chunk())


def test_arrival_cut_and_query_coverage_are_required():
    value = chunk()
    value["eligible_questions"][0]["available_through_source_count"] = 3
    with pytest.raises(ValueError, match="future"):
        validate_chunk(value)
    with pytest.raises(ValueError, match="each declared query"):
        parse_screen('{"selections":[]}', chunk())
