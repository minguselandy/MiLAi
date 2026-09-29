"""Replay the pre-move request copies and their original failures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from milai_lab.contracts.request import MemoryPlacement, ModelView, RequestContext
from milai_lab.memory.presentation import json_action_calls, render_request, render_system

LAB = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((LAB / "data/diagnostics/code-architecture-v12/request-render-golden.json")
                    .read_text())


def _context(row: dict[str, Any]) -> RequestContext:
    data = copy.deepcopy(row)
    data["model_view"] = ModelView(data["model_view"])
    data["durable_records"] = tuple(data["durable_records"])
    data["messages"] = tuple(data["messages"])
    for key in ("tool_observations", "assistant_call_labels"):
        data[key] = {int(index): value for index, value in data[key].items()}
    return RequestContext(**data)


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda case: case["case_id"])
def test_request_render_matches_pre_move_bytes(case: dict[str, Any]) -> None:
    context = _context(case["context"])
    original = copy.deepcopy(context)
    placement = MemoryPlacement(case["placement"])
    assert render_system(context, placement) == case["expected_system"]
    request = render_request(context, placement)
    assert request == case["expected_request"]
    assert json.dumps(request, ensure_ascii=False, separators=(",", ":")) == (
        case["expected_request_json_bytes"])
    assert context == original


@pytest.mark.parametrize("case", GOLDEN["errors"], ids=lambda case: case["case_id"])
def test_request_render_preserves_pre_move_failures(case: dict[str, str]) -> None:
    with pytest.raises(ValueError) as caught:
        if case["case_id"] == "unknown_protocol":
            RequestContext("", ()).with_protocol("unknown", None)
        elif case["case_id"] == "missing_current_user":
            render_request(RequestContext("", ()), MemoryPlacement.CURRENT_REQUEST)
        else:
            arguments = "[]" if case["case_id"] == "array_tool_arguments" else "{"
            json_action_calls([{"function": {"name": "fixture", "arguments": arguments}}])
    assert type(caught.value).__name__ == case["exception"]
    assert str(caught.value) == case["message"]
