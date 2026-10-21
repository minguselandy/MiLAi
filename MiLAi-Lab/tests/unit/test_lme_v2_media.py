"""Public projection and real Store delivery; no benchmark content or model calls."""
import copy
import json

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.datasets.longmemeval_v2 import bind_media, public_question, trajectory_sources
from milai_lab.memory.functional_state import namespace
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import retrieval_packet
from milai_lab.runners.multimodal_evidence import delivered_image_context


def trajectory():
    return {"id": "trajectory-A", "goal": "Inspect the screen", "domain": "web",
        "metadata": {"release_field": [1, True, None]}, "outcome": "Recorded completion",
        "states": [{"step": 0, "accessibility_tree": "Literal first\u2028line\u2029second",
            "thought": "Recorded interpretation, not authority", "action": "click('a')",
            "screenshot": "screens/0.png", "extra_released_field": {"x": [1, 2]}},
            {"step": 1, "accessibility_tree": "Later screen", "action": None,
             "screenshot": None}]}


def test_projection_preserves_all_fields_states_order_and_literal_unicode():
    original = trajectory()
    rows, media = trajectory_sources(original)
    restored = copy.deepcopy(rows[0]["content"])
    restored["states"] = [json.loads(row["content"].split("\n", 1)[1]) for row in rows[1:]]
    assert restored == original
    assert [r["event_key"] for r in rows] == ["trajectory", "state-0", "state-1"]
    assert len(media) == 1
    assert rows[1]["content"][slice(*media[0]["range"])] == media[0]["locator_text"]
    assert all(r["role"] == "tool" and r["occurred_at"] is None for r in rows)
    rows[0]["content"]["metadata"]["release_field"].append("changed")
    assert original["metadata"]["release_field"] == [1, True, None]


def test_public_query_never_reads_reference_fields(tmp_path):
    (tmp_path / "q.png").write_bytes(b"synthetic image")

    class PublicOnly(dict):
        def __getitem__(self, key):
            assert key in {"question", "image"}, "Offline reference field was accessed"
            return super().__getitem__(key)

        def __iter__(self):
            raise AssertionError("Whole reference record cannot be copied into the online path")

    row = PublicOnly(question="Unchanged question", image="q.png", answer="offline secret",
                     id="offline-question-id", eval_function="offline specification")
    assert public_question(row, tmp_path) == ("Unchanged question", str(tmp_path / "q.png"))
    row["image"] = None
    assert public_question(row, tmp_path) == ("Unchanged question", None)


def original_packet(service, ref, start, end):
    material = {"kind": "original_source", "id": "material-0", "session_id": "trajectory-A",
        "date": None, "turn_range": [0, 1], "source_ranges": [{"source_ref": ref,
            "source_revision": 1, "start": start, "end": end}]}
    opened = service.read_source_materials([material])
    service.store.put(namespace(service), "receipt", {"schema": "milai_retrieval_snapshot_v1",
        "materials": opened, "indices": [0], "delivered_indices": [0]}, index=False)
    return retrieval_packet("receipt", opened, [0], [0], "policy_handoff", {})


@pytest.mark.parametrize("condition", ["full", "locator_only", "partial_locator", "body_only"])
def test_only_actual_delivered_locator_attaches_original_image(tmp_path, condition):
    image = tmp_path / "screens/0.png"
    image.parent.mkdir()
    image.write_bytes(b"original synthetic bytes")
    rows, assets = trajectory_sources(trajectory())
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("media", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        imports = [{"original_event_id": row["original_event_id"], "receipt": service.capture_tool(
            row["session_id"], row["event_key"], row["origin"], row["content"], None,
            occurred_at=None)} for row in rows]
        media = bind_media(assets, imports, tmp_path)
        ref = imports[1]["receipt"]["source_ref"]
        length, prefix = len(rows[1]["content"]), len(assets[0]["locator_text"])
        ranges = {"full": (0, length), "locator_only": (0, prefix),
                  "partial_locator": (0, prefix-1), "body_only": (prefix+1, length)}
        packet = original_packet(service, ref, *ranges[condition])
        context = delivered_image_context(service, packet, media)
        assert json.loads(context[0]["value"]) == packet
        images = [c["value"] for c in context if c["type"] == "image"]
        assert images == ([str(image)] if condition in {"full", "locator_only"} else [])
        if images:
            label = json.loads(context[1]["value"])
            assert label["image_for_delivered_material"] == packet["evidence"][0]["ref"]


def test_navigation_only_view_does_not_deliver_its_cited_image(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("media", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        # A body-unavailable View is a real navigation marker, not opened original evidence.
        material = {"kind": "query_structure", "body_delivered": False, "visibility": "unavailable"}
        service.store.put(namespace(service), "receipt", {
            "schema": "milai_retrieval_snapshot_v1", "materials": [material],
            "indices": [0], "delivered_indices": [0]}, index=False)
        packet = retrieval_packet("receipt", [material], [0], [0], "policy_handoff", {})
        context = delivered_image_context(service, packet, {})
        assert [item["type"] for item in context] == ["text"]


def test_missing_image_is_retained_as_failure_not_a_text_only_success(tmp_path):
    rows, assets = trajectory_sources(trajectory())
    imports = [{"original_event_id": row["original_event_id"],
                "receipt": {"source_ref": f"source-{i}"}} for i, row in enumerate(rows)]
    with pytest.raises(FileNotFoundError):
        bind_media(assets, imports, tmp_path)
