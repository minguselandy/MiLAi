"""Source-grounded time options do not turn report clocks into event facts."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from milai_lab.memory.source_times import bind_applicability, source_time_choices


def source(text: str, **metadata: Any) -> dict[str, Any]:
    return {"text": text, "start": 11, "occurred_at": "2030-10-14T10:00:00+08:00", **metadata}


def test_literal_and_relative_choices_keep_precision_and_exclusive_day_end() -> None:
    values = {"e1": source("仅2030年10月21日当天生效,明天再确认。"),
              "e2": source("Scheduled at 2030-10-22T14:30:00+08:00."),
              "e3": source("The appointment is on October 23, 2030.")}
    before = copy.deepcopy(values)
    choices = source_time_choices(values)
    assert [item["value"] for item in choices] == [
        "2030-10-21", "2030-10-15", "2030-10-22T14:30:00+08:00", "2030-10-23"]
    assert choices[0]["quote"] == "2030年10月21日" and choices[0]["range"][0] == 12
    assert choices[1]["basis"] == "report_relative_candidate"
    assert choices[1]["anchor_report_time"] == values["e1"]["occurred_at"]
    assert "day_end_exclusive" not in choices[2]
    assert bind_applicability({"effective_from": "t1", "effective_until": "t1:end"},
                              choices, ["e1"]) == {
        "effective_from": "2030-10-21", "effective_until": "2030-10-22"}
    assert values == before


def test_vague_or_unanchored_time_never_uses_capture_or_commit_clock() -> None:
    assert source_time_choices({"e1": source("最近开始考虑,还未决定。")}) == []
    assert source_time_choices({"e1": source("明天再讨论。", occurred_at=None,
        observed_at="2030-10-14T10:00:00+08:00", committed_at="2030-10-14")}) == []
    assert source_time_choices({"e1": source("Starts on 2030-02-31.")}) == []
    choices = source_time_choices({"e1": source("Starts on 2030-10-20.")})
    with pytest.raises(ValueError, match="EDIT_TIME_SOURCE_NOT_SELECTED"):
        bind_applicability({"event_at": "t1"}, choices, ["e2"])
