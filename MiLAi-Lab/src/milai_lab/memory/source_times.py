"""Date choices from delivered wording; report clocks only anchor explicit relative days."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_DATETIME = re.compile(
    r"(?<!\d)\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:\d{2})?(?!\d)"
)
_DATE = re.compile(
    r"(?<!\d)(?P<year>\d{4})(?:年|[-/])(?P<month>\d{1,2})"
    r"(?:月|[-/])(?P<day>\d{1,2})(?:日|号)?(?!\d)"
)
_ENGLISH_DATE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4}\b", re.IGNORECASE,
)
_RELATIVE = re.compile(
    r"今天|昨天|明天|前天|后天|\btoday\b|\byesterday\b|\btomorrow\b", re.IGNORECASE)
_DAY_OFFSETS = {"今天": 0, "昨天": -1, "明天": 1, "前天": -2, "后天": 2,
                "today": 0, "yesterday": -1, "tomorrow": 1}


def _report_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        for pattern in ("%b %d, %Y, %H:%M:%S", "%B %d, %Y, %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                continue
    return None


def source_time_choices(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Offer literal calendar days and unambiguous relative days only.

    This does not assign any date to an event or decide whether a claim is true.
    Vague periods such as 'recently', standalone month/day without a year and
    recurring weekdays stay in the original text. No capture/commit clock is used.
    """
    choices: list[dict[str, Any]] = []
    for alias, source in evidence.items():
        text = source["text"]
        spans: list[tuple[int, int, date | datetime, str]] = []
        for match in _DATETIME.finditer(text):
            try:
                instant = datetime.fromisoformat(match.group().replace("Z", "+00:00"))
            except ValueError:
                continue
            spans.append((*match.span(), instant, "literal_datetime"))
        for match in _DATE.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end, _, _ in spans):
                continue
            try:
                day = date(int(match["year"]), int(match["month"]), int(match["day"]))
            except ValueError:
                continue
            spans.append((*match.span(), day, "literal_date"))
        for match in _ENGLISH_DATE.finditer(text):
            words = match.group().replace(",", "").split()
            try:
                day = datetime.strptime(f"{words[0][:3]} {words[1]} {words[2]}", "%b %d %Y").date()
            except ValueError:
                continue
            spans.append((*match.span(), day, "literal_date"))
        anchor = _report_day(source.get("occurred_at"))
        if anchor is not None:
            for match in _RELATIVE.finditer(text):
                day = anchor + timedelta(days=_DAY_OFFSETS[match.group().lower()])
                spans.append((*match.span(), day, "report_relative_candidate"))
        for start, end, day, basis in sorted(spans):
            choices.append({"id": f"t{len(choices) + 1}", "evidence": alias,
                            "quote": text[start:end],
                            "range": [source["start"] + start, source["start"] + end],
                            "value": day.isoformat(),
                            **({"day_end_exclusive": (day + timedelta(days=1)).isoformat()}
                               if not isinstance(day, datetime) and day != date.max else {}),
                            "basis": basis,
                            **({"anchor_report_time": source["occurred_at"]}
                               if basis == "report_relative_candidate" else {})})
    return choices


def bind_applicability(
    value: dict[str, Any], time_choices: list[dict[str, Any]], evidence: list[str],
) -> dict[str, Any]:
    """Expand already validated short choices at the proposal decode boundary."""
    from milai_lab.memory.functional_state import FunctionalRejection

    result = dict(value)
    times = {item["id"]: item for item in time_choices}
    for field in ("event_at", "effective_from", "effective_until"):
        if field not in result:
            continue
        alias, separator, endpoint = result[field].partition(":")
        item = times[alias]
        if item["evidence"] not in evidence:
            raise FunctionalRejection("EDIT_TIME_SOURCE_NOT_SELECTED")
        result[field] = (item["day_end_exclusive"] if separator and endpoint == "end"
                         else item["value"])
    return result
