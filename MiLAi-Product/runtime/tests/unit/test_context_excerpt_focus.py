from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest

from milai.application import memory_context as context
from milai.domain.memory_context import MemoryContextWindow


@pytest.mark.parametrize("text,terms", [
    ("no matching words here", frozenset({"absent"})),
    ("heading\nlate target and 42 days\nfooter", frozenset({"target"})),
    ("first 7 then later target", frozenset({"target", "later"})),
    ("Straße İ and 中文目标 near the end", frozenset({"目标", "end"})),
    ("prefix\n" + "x" * 8192 + "\nsuffix", frozenset()),
    ("one", frozenset({"one"})),
])
def test_every_excerpt_length_keeps_previous_focus_and_boundaries(
    text: str, terms: frozenset[str],
) -> None:
    # Frozen pre-change focus rule, including its casefold index convention.
    # This guards presentation fidelity; changing that convention is separate work.
    folded = text.casefold()
    positions = [folded.find(term) for term in sorted(terms) if term in folded]
    value = re.search(context._VALUE, text)
    if value is not None:
        positions.append(value.start())
    focus = min((position for position in positions if position >= 0), default=0)
    for length in range(1, len(text) + 2):
        start = max(0, min(len(text) - length, focus - length // 3))
        end = start + length
        expected = text if length >= len(text) else (
            ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
        )
        assert context._excerpt_at(text, context._excerpt_focus(text, terms), length) == expected
        # Retained compatibility entry point is also used for minimal required windows.
        assert context._focused_excerpt(text, terms, length) == expected


def _window(identity: str) -> MemoryContextWindow:
    return MemoryContextWindow(
        window_id=identity, session_id=identity, evidence_ids=[identity],
        source_turn_refs=[f"source://{identity}"], speakers=["USER"],
        text="prefix " + "long content " * 200 + " target 17\nsuffix",
        source_rank=1, query_overlap=1, answer_signal=True, requirement_priority=True,
    )


@pytest.mark.parametrize("together", [False, True])
def test_fitting_scans_each_window_once_and_keeps_budget(together: bool) -> None:
    windows = [_window("first"), _window("second")] if together else [_window("first")]
    original = [window.model_dump() for window in windows]
    outcome: dict[str, object] = {"status": "HIT", "open_issue_ids": []}
    with patch.object(context, "_excerpt_focus", wraps=context._excerpt_focus) as focus:
        if together:
            result = context._fit_windows_together(
                outcome, windows, None, frozenset({"target"}), 256,
            )
            assert result is not None
        else:
            fitted = context._fit_window(
                outcome, [], [], windows[0], None, frozenset({"target"}), 256,
            )
            assert fitted is not None
            result = [fitted]
        assert focus.call_count == len(windows)
    assert context._estimated_tokens(context._render_context(outcome, [], result, None)) <= 256
    assert [window.model_dump() for window in windows] == original
    assert [window.evidence_ids for window in result] == [window.evidence_ids for window in windows]


def _fit_by_rendering_each_candidate(
    outcome: dict[str, Any], canonical: list[dict[str, Any]], selected: list[MemoryContextWindow],
    window: MemoryContextWindow, derived: str | None, budget: int,
) -> MemoryContextWindow | None:
    """Pre-optimization fitter: render and measure each complete candidate."""
    low, high = 1, len(window.text)
    focus = context._excerpt_focus(window.text, frozenset({"target"}))
    fitted = None
    while low <= high:
        middle = (low + high) // 2
        candidate = window.model_copy(update={
            "text": context._excerpt_at(window.text, focus, middle), "truncated": True,
        })
        rendered = context._render_context(outcome, canonical, [*selected, candidate], derived)
        if context._estimated_tokens(rendered) <= budget:
            fitted = candidate
            low = middle + 1
        else:
            high = middle - 1
    return fitted


@pytest.mark.parametrize("text", [
    "first target last", "首字段\n目标和🙂正文\n尾字段", "Straße İ é\n17 days",
    "x" * 8192, "🙂a" * 60,
])
@pytest.mark.parametrize("with_prefix", [False, True])
@pytest.mark.parametrize("with_canonical", [False, True])
def test_fixed_byte_fitting_matches_full_render_search(
    text: str, with_prefix: bool, with_canonical: bool,
) -> None:
    window = _window("candidate").model_copy(update={"text": text})
    selected = [_window("selected")] if with_prefix else []
    canonical = [{"claim_version_id": "c-1", "value": '中文 "quoted"'}] if with_canonical else []
    outcome = {"status": "PARTIAL", "open_issue_ids": ["issue-1"]}
    for derived in [None, "derived 🙂 data"]:
        for budget in [1, 64, 96, 128, 256, 512, 2048, 8192]:
            expected = _fit_by_rendering_each_candidate(
                outcome, canonical, selected, window, derived, budget,
            )
            with patch.object(context, "_render_context", wraps=context._render_context) as render:
                actual = context._fit_window(
                    outcome, canonical, selected, window, derived, frozenset({"target"}), budget,
                )
            assert actual == expected
            assert render.call_count == 1
