"""Offline Laya Impact adapter contract tests; no weights or GPU are required."""
from __future__ import annotations

import json

import httpx
import pytest

from milai_lab.methods.laya_impact import LayaImpactClient

SCHEMA = {
    "type": "object",
    "properties": {
        "roots": {"type": "array", "items": {"type": "string", "enum": ["u1", "u2", "u3"]}},
        "preserve": {"type": "array", "items": {"type": "string", "enum": ["u1", "u2", "u3"]}},
    },
    "required": ["roots", "preserve"],
}
MESSAGES = [
    {"role": "system", "content": "Locate affected units."},
    {"role": "user", "content": json.dumps({
        "observed_date": "2026-10-16",
        "delivery": {"current_event": "Project A contact Zhao; B remains Wang.",
                     "memory": "u1 A contact Li; u2 B contact Wang; u3 email approval"},
        "response_schema": SCHEMA,
    })},
]


def fake_client(seen, choices=("direct_root", "preserve_successor", "other"), status=200):
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert request.url.path == "/v1/systemone"
        assert payload["state"]["observed_date"] == "2026-10-16"
        assert "response_schema" not in payload["state"]
        assert payload["model"] == "multilingual"
        assert len(payload["questions"]) == 3
        answers = {
            f"unit_{i}": {"type": "choice", "choice": label, "confidence": 0.9}
            for i, label in enumerate(choices)
        }
        return httpx.Response(status, json={
            "model": "multilingual", "answers": answers,
            "usage": {"input_tokens": 178, "output_tokens": 0},
        })

    return LayaImpactClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_maps_choices_to_existing_impact_schema_and_tracks_receipt():
    seen = []
    receipts = []
    client = fake_client(seen)
    client.on_receipt = receipts.append
    assert client.decide("impact:child", MESSAGES, SCHEMA) == {
        "roots": ["u1"], "preserve": ["u2"],
    }
    assert len(seen) == 1
    assert receipts[0]["stage"] == "impact:child"
    assert receipts[0]["usage"] == {"input_tokens": 178, "output_tokens": 0}


def test_other_model_stages_unchanged():
    seen, called = [], []
    client = fake_client(seen)

    def original(stage, *_):
        called.append(stage)
        return {"original": True}

    wrapped = client.wrap(original)
    assert wrapped("edit", MESSAGES, SCHEMA) == {"original": True}
    assert wrapped("impact:work-7", MESSAGES, SCHEMA)["roots"] == ["u1"]
    assert called == ["edit"]
    assert len(seen) == 1


def test_empty_roots_does_not_cancel_a_writer_stage():
    client = fake_client([], choices=("other", "other", "other"))
    assert client.decide("impact", MESSAGES, SCHEMA) == {
        "roots": [], "preserve": [],
    }
    wrapped = client.wrap(lambda *_: {"proposal": "write a new fact"})
    assert wrapped("edit", MESSAGES, {}) == {"proposal": "write a new fact"}


def test_provider_failure_is_not_silently_no_change():
    client = fake_client([], status=503)
    with pytest.raises(httpx.HTTPStatusError):
        client.decide("impact", MESSAGES, SCHEMA)
    assert not client.receipts


def test_unrecognized_decision_fails():
    client = fake_client([], choices=("unexpected", "other", "other"))
    with pytest.raises(ValueError, match="Unrecognized"):
        client.decide("impact", MESSAGES, SCHEMA)
    assert not client.receipts
