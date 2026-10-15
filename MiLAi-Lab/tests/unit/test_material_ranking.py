"""Ranking changes delivery priority without inventing or renumbering evidence."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from milai_lab.memory.working_set import empty_view, material_ref, select_material_refs
from milai_lab.methods.material_ranking import rank_materials, ranking_messages


def source_material() -> dict[str, Any]:
    return {
        "kind": "original_source", "id": "actual-session", "date": "2026-10-10",
        "text": json.dumps([
            {"role": "user", "content": "项目 A 每周提醒两次, 外部通知先确认。",
             "source_ref": "actual-user", "occurred_at": "2026-10-10"},
            {"role": "assistant", "content": "Perhaps daily?",
             "source_ref": "actual-assistant", "occurred_at": "2026-10-11"},
        ], ensure_ascii=False),
        "source_ranges": [{"source_ref": "actual-user", "source_revision": 1,
                           "start": 0, "end": 24}],
    }


def test_partial_ranking_preserves_canonical_refs_and_source_pool() -> None:
    materials = [source_material(), {"content": "background"}, {"content": "exception"},
                 {"content": "other subject"}]
    before = copy.deepcopy(materials)
    calls = []

    def generate(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        return '{"rank_order":[2,2,-1,99,true,1.5,"1",0]}'

    order = rank_materials("Which reminder applies?", "2026-10-12", materials, generate)
    assert order == [2, 0, 1, 3]
    assert materials == before
    assert len(calls) == 1
    refs = [material_ref("saved/retrieval.json", index) for index in range(len(materials))]
    selected = select_material_refs(empty_view(), refs, order[:2])["resident_refs"]
    assert [ref["item_index"] for ref in selected] == [2, 0]
    assert materials[selected[0]["item_index"]]["content"] == "exception"


def test_probe_delivers_actual_roles_times_text_and_pool_positions() -> None:
    material = source_material()
    messages = ranking_messages("How often?", "2026-10-12", [material])
    request = json.loads(messages[1]["content"])
    assert request["question"] == "How often?"
    assert request["date"] == "2026-10-12"
    assert request["materials"][0]["item_index"] == 0
    delivered = request["materials"][0]["material"]
    assert delivered["turns"] == json.loads(material["text"])
    assert delivered["source_ranges"] == material["source_ranges"]
    assert "text" not in delivered


def test_memsifter_uses_published_role_tags_and_ignores_reasoning_example() -> None:
    materials = [source_material(), {"content": "historical exception"},
                 {"content": "other subject"}]
    calls = []

    def generate(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        return ("<think>Example <ranking>2</ranking></think>"
                "<ranking>1,1,-2,70,oops,0.5</ranking>")

    assert rank_materials("How often?", "2026-10-12", materials, generate,
                          mode="memsifter") == [1, 0, 2]
    assert len(calls) == 1
    content = calls[0][0]["content"]
    assert "<session0> <date>2026-10-10</date>" in content
    assert "<user0>项目 A 每周提醒两次, 外部通知先确认。</user>" in content
    assert "<assistant0>Perhaps daily?</assistant>" in content
    assert '"occurred_at":"2026-10-11"' in content
    assert "Query date: 2026-10-12\nQuery: How often?" in content


@pytest.mark.parametrize("response", ['{"rank_order":"1"}', '{"answer":"guess"}', '[]'])
def test_bad_response_is_not_silently_retried(response: str) -> None:
    calls = []

    def generate(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        return response

    with pytest.raises(ValueError, match="rank_order array"):
        rank_materials("Q", "D", [{"content": "actual material"}], generate)
    assert len(calls) == 1


def test_empty_pool_does_not_spend_a_model_call() -> None:
    def generate(messages: list[dict[str, str]]) -> str:
        pytest.fail("Empty material pool does not require ranking")

    assert rank_materials("Q", "D", [], generate) == []
