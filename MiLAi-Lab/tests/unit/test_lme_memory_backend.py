"""Real existing given-request runner and isolated Stores, with synthetic public materials."""
import json

import pytest
from test_lme_v2_media import trajectory
from test_retrieval_feedback_without_fingerprints import forbid_fingerprints
from test_v13_5_functional_integration import prepared, scripted

from milai_lab.runners.lme_v2 import LmeMemoryBackend


def backend(tmp_path, monkeypatch):
    forbid_fingerprints(monkeypatch)
    prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        edit_interface_version="I2", edit_features={"source_metadata": True},
        memory_profile="unified_v1", evidence_policy="question_pack_v1",
        retrieval_tool="rich", business_tools=[], memory_view_mode="staged",
        memory_control={"policy": "fixed_context", "reads": 4, "max_control_steps": 6})
    images = tmp_path / "assets/screens"
    images.mkdir(parents=True)
    (images / "0.png").write_bytes(b"synthetic image retained byte-for-byte")
    wires = scripted(monkeypatch, lambda *_: pytest.fail("This rule query needs no model request"),
                     native=True)
    value = LmeMemoryBackend(tmp_path / "settings.json", tmp_path / "assets",
                             tmp_path / "memory", source_version="mechanical")
    value.insert(trajectory())
    return value, wires


def test_real_queries_return_selected_image_and_never_reuse_earlier_question(tmp_path, monkeypatch):
    memory, wires = backend(tmp_path, monkeypatch)
    first = memory.query("Inspect the screen: first-private-question")
    assert any(item["type"] == "image" for item in first)
    original = next(memory.template.glob("banks/*/memory.sqlite"))
    initial_bytes = original.read_bytes()
    second = memory.query("Inspect the screen: second-private-question",
                          str(tmp_path / "assets/screens/0.png"))
    assert any(item["type"] == "image" for item in second)
    assert "first-private-question" not in json.dumps(second)
    result_path = next((memory.output / "cases/0001").glob("banks/*/*-result.json"))
    result = json.loads(result_path.read_text())
    assert "first-private-question" not in json.dumps(result["sources"])
    assert "second-private-question" in json.dumps(result["sources"])
    assert original.read_bytes() == initial_bytes
    assert len(wires) == 0
    report = json.loads((memory.output / "cases/0001/query.json").read_text())
    assert report["status"] == "COMPLETED" and report["reader_called"] is False
    assert report["query_image_consumed_by_retriever"] is False
    assert report["query_image"] == str(tmp_path / "assets/screens/0.png")
    assert report["source_index_cache"]["builds"] == 1
    assert report["source_index_cache"]["hits"] == 3
    assert memory.source_search_cache._entry is not None
    assert "first-private-question" not in str(memory.source_search_cache._entry.texts)
    assert "second-private-question" not in str(memory.source_search_cache._entry.texts)
    assert json.loads((memory.output / "orchestration-compute.json").read_text())["cpu_seconds"] > 0


def test_failed_image_input_retains_first_failure_and_stops_further_queries(tmp_path, monkeypatch):
    memory, wires = backend(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        memory.query("Question with an absent original image", "missing.png")
    assert json.loads((memory.output / "cases/0000/query.json").read_text())["status"] == "FAILED"
    with pytest.raises(ValueError, match="automatic retry"):
        memory.query("Question with an absent original image", "missing.png")
    assert not (memory.output / "cases/0001").exists() and not wires
