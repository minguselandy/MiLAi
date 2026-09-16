"""Cluster exclusion reaches the full history, and accepted failures cannot be replaced."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0213_cases import normalize_schema, prepare
from replay_v0213_cost import save
from seal_v0213_pool import freeze


def test_shared_history_propagates_exposure_and_seals_disjoint_partitions(tmp_path):
    save(tmp_path / "pre-open-protocol.json", {
        "goal": "test", "seed": 213, "screening_limit": 30, "accepted_limit": 4})
    sessions = [{"session_id": f"s{i}", "original_conversation_ids": [f"c{i}"]}
                for i in range(8)]
    sessions[1]["original_conversation_ids"].append("protected")
    sessions[2]["original_conversation_ids"].append("protected")
    queries = [{"qa_id": f"q{i}", "source_conversation_ids": [f"c{i}"],
                "evolution_source_ids": []} for i in range(8)]
    save(tmp_path / "toolmem_conversation-metadata.json", sessions)
    save(tmp_path / "qa_dataset-metadata.json", queries)
    save(tmp_path / "release-manifest.json", {"release": "fixed"})
    receipt = tmp_path / "exposure.json"
    save(receipt, {"excluded_source_ids": ["protected"]})
    result = freeze(tmp_path, {"protected"}, receipt)
    assert len(result["excluded_clusters"]) == 1
    assert result["excluded_clusters"][0]["qa_ids"] == ["q1", "q2"]
    discovery = {s for c in result["discovery"] for s in c["source_ids"]}
    confirmation = {s for c in result["confirmation"] for s in c["source_ids"]}
    assert not discovery & confirmation
    assert len(result["confirmation"]) == 2
    assert freeze(tmp_path, {"protected"}, receipt) == result


def test_existing_accepted_set_survives_failed_or_later_changed_materials(tmp_path):
    original = {"status": "ACCEPTED", "accepted": [{"qa_id": "q1", "outcome": "FAILED"}]}
    save(tmp_path / "accepted.json", original)
    # No corpus or alternative task is present: reopening must reuse the accepted set.
    assert prepare(tmp_path) == original
    assert json.loads((tmp_path / "accepted.json").read_text()) == original


def test_unresolved_lineage_quarantines_the_entire_known_associated_cluster(tmp_path):
    save(tmp_path / "pre-open-protocol.json", {
        "goal": "test", "seed": 213, "screening_limit": 30, "accepted_limit": 4})
    save(tmp_path / "toolmem_conversation-metadata.json", [
        {"session_id": "s", "original_conversation_ids": ["known"]}])
    save(tmp_path / "qa_dataset-metadata.json", [
        {"qa_id": "missing", "source_conversation_ids": ["known", "unmapped"],
         "evolution_source_ids": []},
        {"qa_id": "related", "source_conversation_ids": ["known"], "evolution_source_ids": []}])
    save(tmp_path / "release-manifest.json", {})
    receipt = tmp_path / "exposure.json"
    save(receipt, {})
    result = freeze(tmp_path, set(), receipt)
    assert result["discovery"] == result["confirmation"] == []
    assert result["excluded_clusters"][0]["qa_ids"] == ["related"]
    assert result["excluded_clusters"][0]["reason"] == "ASSOCIATED_UNRESOLVED_LINEAGE"


def test_python_type_aliases_preserve_parameter_names_defaults_and_requirements():
    original = {"type": "dict", "properties": {"days": {"type": "int", "default": 3}},
                "required": ["days"]}
    result = normalize_schema(original)
    assert result == {"type": "object", "properties": {
        "days": {"type": "integer", "default": 3}}, "required": ["days"]}
    assert original["type"] == "dict"
