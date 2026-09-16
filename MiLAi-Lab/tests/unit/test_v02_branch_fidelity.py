from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
state = importlib.import_module("v02_e2e_state")
sources = importlib.import_module("v02_lme_sources")
provider = importlib.import_module("v02_local_provider")


def test_only_declared_reference_fields_are_rebound():
    payload = {
        "evidence_refs": ["old"],
        "nested": [{"evidence_id": "old"}],
        "text": "Keep old literally",
        "other": ["old", False, 0, None],
    }
    new = state.remap_declared_refs(payload, {"old": "new"})
    assert new["evidence_refs"] == ["new"]
    assert new["nested"] == [{"evidence_id": "new"}]
    assert new["text"] == payload["text"] and new["other"] == payload["other"]
    assert payload["evidence_refs"] == ["old"]
    with pytest.raises(KeyError):
        state.remap_declared_refs(payload, {})


def test_singular_state_reference_is_included_in_disclosure_checks():
    observed = []

    def metadata(ref):
        observed.append(ref)
        return {
            "evidence_id": ref,
            "retention_state": "READABLE",
            "permission_snapshot": {"readable": True, "project_ids": ["p"]},
        }

    guard = state.FileDisclosure("p", {}, metadata)
    guard.acquired(
        {
            "schema_version": "host-cognitive-state-v1",
            "payload": {"nested": [{"evidence_id": "one"}], "text": "not-a-ref"},
        }
    )
    assert observed == ["one"]
    guard.created("output")
    assert guard.file_refs["output"] == ["one"]


def test_original_session_time_and_message_order_are_separate():
    source = {
        "schema_version": "v02-lme-source-only-v1",
        "case_id": "opened",
        "question": "not supplied to G",
        "question_date": "unused",
        "sessions": [
            {
                "session_ordinal": 0,
                "session_id": "session-0",
                "observed_at": "2026/09/06 10:00",
                "turns": [
                    {"turn_ordinal": 0, "role": "user", "content": "first"},
                    {"turn_ordinal": 1, "role": "assistant", "content": "last"},
                ],
            }
        ],
    }
    before = sources.history_events(source, "a")
    after = sources.history_events(source, "b", preserve_session_time=True)
    assert before[0]["observed_at"] != before[1]["observed_at"]  # historical default unchanged
    assert after[0]["observed_at"] == after[1]["observed_at"]
    assert after[0]["next_turn_id"] == after[1]["turn_id"]
    assert after[1]["previous_turn_id"] == after[0]["turn_id"]
    assert [e["content"] for e in after] == ["first", "last"]


def test_mock_only_profile_cannot_construct_real_transport(tmp_path):
    config = {
        "provider_base_url": provider.ENDPOINT,
        "model": provider.MODEL,
        "paid_model_allocations_authorized": 0,
        "transport_kind": "MOCK_ONLY",
    }
    with pytest.raises(provider.LocalGateError, match="MOCK_PROFILE"):
        provider.LocalProvider(config, tmp_path, "G")


def test_representation_variants_preserve_text_except_declared_deletion():
    module = importlib.import_module("check_v02_representation_chain")
    import json

    raw = "  first\r\n中间\nlast\n"
    for case in module.variants(raw):
        value = json.loads(case["content"]) if case["format"] == "json" else case["content"]
        restored = module.restored_text(case, value)
        assert (restored == raw) is (case["name"] != "deleted")
        if case["name"] == "deleted":
            assert case["kind"] == "INFORMATION_DELETION_NOT_EQUIVALENT"


def test_deletion_fixture_requires_a_multiline_mother():
    module = importlib.import_module("check_v02_representation_chain")
    with pytest.raises(ValueError, match="Mother artifact"):
        module.variants("one line")
