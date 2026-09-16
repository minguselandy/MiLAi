"""Fixed simple baseline, disclosed pressure and ordinary paged source capability."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from milai_lab.methods.host_acquisition import AcquisitionHelper, Binding, Coverage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0216 import materials, prepare
from run_v0215 import initial_messages, readiness_action_schema, state_write_arguments
from v0214_source_binding import FileSources
from v0216_support import paged_schema, read_pages


@pytest.mark.parametrize("key", ["trace", "placement"])
def test_pressure_preserves_all_required_support_and_same_task(key):
    for phase in (0, 1, 2):
        low_task, low_sources, low = materials(key, phase, 0)
        high_task, high_sources, high = materials(key, phase, 32)
        assert low_task == high_task
        assert low_task["initial_note"] is None
        assert low["expected_decision"] == high["expected_decision"]
        assert low["required_support"] == high["required_support"]
        for fact in low["required_support"]:
            assert any(fact in source for source in low_sources.values())
            assert any(fact in source for source in high_sources.values())
        assert len(high_sources["source-03.txt"].encode()) > 4096
        assert high["pressure"]["other_object_records"] == 32
    assert materials(key, 0, 0)[1]["source-03.txt"] == materials(key, 1, 0)[1]["source-03.txt"]
    assert (materials(key, 0, 0)[2]["expected_decision"] !=
            materials(key, 2, 0)[2]["expected_decision"])


def test_paging_and_search_inputs_cannot_be_empty():
    schema = paged_schema(readiness_action_schema(["A", "INSUFFICIENT_EVIDENCE"]))
    value = {"assessment": {"basis": "Need current evidence.", "readiness": "NEEDS_SOURCE"},
        "delivery": {"action": "read", "source_ids": ["source-03.txt"], "offset": 4096,
            "query": "", "decision": "", "explanation": "Read the next page.",
            "citations": [], "note": ""}}
    assert Draft202012Validator(schema).is_valid(value)
    final = paged_schema(readiness_action_schema(["A"], final_slot=True))
    assert not Draft202012Validator(final).is_valid(value)
    value["delivery"]["offset"] = -1
    assert not Draft202012Validator(schema).is_valid(value)
    value["delivery"].update(action="search", offset=0, source_ids=[], query=" ")
    assert not Draft202012Validator(schema).is_valid(value)
    value["delivery"]["query"] = "current registry"
    assert Draft202012Validator(schema).is_valid(value)


def test_actual_pages_recover_support_beyond_first_page(tmp_path):
    prepare(tmp_path / "inputs", 32)
    online = tmp_path / "inputs/trace/online/phase-2"
    scope = Binding("person", "project", "task")
    helper = AcquisitionHelper(FileSources({scope: online}))
    with asyncio.Runner() as loop:
        refs = loop.run(helper.resolve_sources(scope))
        selected = tuple(ref for ref in refs if ref.source_id == "source-03.txt")
        pages = loop.run(read_pages(helper, scope, selected, 0))
        assert pages[0].coverage == Coverage.PARTIAL
        while pages[-1].next_cursor is not None:
            pages += loop.run(read_pages(helper, scope, selected, pages[-1].next_cursor))
        text = "".join(page.text for page in pages)
        assert text == (online / "source-03.txt").read_text()
        assert "T92 exclusive critical-path durations" in text
        assert helper.presented == []


def test_no_injected_judgment_and_shared_simple_policy(tmp_path):
    prepare(tmp_path / "inputs", 0)
    config_path = Path(__file__).resolve().parents[2] / "configs/v0216-stress-low.json"
    cfg = json.loads(config_path.read_text())
    assert cfg["arms"] == ["NOTES", "REMINDER"]
    assert "CHECKPOINT" not in cfg["policies"]
    assert cfg["cumulative_raw_cap"] is None
    for task in (tmp_path / "inputs").glob("*/online/*/task.json"):
        value = json.loads(task.read_text())
        assert value["initial_note"] is None and "required_support" not in value
    low = initial_messages(cfg, "REMINDER", {}, [], {})[0]
    cfg["pressure"]["other_object_records"] = 32
    assert initial_messages(cfg, "REMINDER", {}, [], {})[0] == low
    args = state_write_arguments({"status": "ABSENT", "version": 0, "state_id": None},
                                 "model-selected ordinary note", "operation")
    assert args["expected_version"] == 0 and "state_id" not in args
