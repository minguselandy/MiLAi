from __future__ import annotations

import json

from scripts import build_dg10_review_bundle as bundle


def test_review_materials_are_closed_secret_free_and_digest_stable() -> None:
    entries, raw = bundle._source_entries(bundle.ROOT / "runtime/.env")
    assert len(entries) == len(bundle.MATERIALS)
    assert len(raw) == len(bundle.MATERIALS)
    assert len(bundle._canonical_entries_sha256(entries)) == 64
    assert {entry["path"] for entry in entries} == set(bundle.MATERIALS.values())
    assert all(not entry["path"].startswith("/") for entry in entries)
    assert all(".git" not in entry["path"] for entry in entries)
    assert all(".env" not in entry["path"] for entry in entries)


def test_review_schema_and_prompt_pin_exact_sol_max() -> None:
    schema = json.loads(
        (bundle.ROOT / "docs/reviews/schemas/dg10-review.schema.json").read_text()
    )
    prompt = (
        bundle.ROOT / "docs/reviews/prompts/dg10-independent-review.md"
    ).read_text()
    assert schema["properties"]["model"]["enum"] == ["gpt-5.6-sol"]
    assert schema["properties"]["reasoning_effort"]["enum"] == ["max"]
    assert schema["properties"]["acceptance_authorized"]["const"] is False
    assert "gpt-5.6-sol" in prompt
    assert "reasoning_effort` to `max" in prompt
    assert "never candidate acceptance" in prompt
