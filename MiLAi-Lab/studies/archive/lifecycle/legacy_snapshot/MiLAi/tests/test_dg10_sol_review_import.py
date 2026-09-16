from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import import_dg10_sol_review as review_import


def _review() -> dict[str, object]:
    return {
        "schema_version": "1",
        "review_kind": "AI_ADVERSARIAL_EVIDENCE_AUDIT_NOT_HUMAN_APPROVAL",
        "decision": "NO_GO_EVIDENCE_SUPPORTED",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
        "cli_version": "codex-cli 0.147.0",
        "bundle_entries_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "prompt_sha256": "c" * 64,
        "response_schema_sha256": "d" * 64,
        "acceptance_authorized": False,
        "quality_outcome": "BELOW_TARGET",
        "summary": "The NO-GO disposition is supported.",
        "open_p0_p1_count": 0,
        "findings": [],
        "coverage": {key: "VERIFIED" for key in review_import.EXPECTED_COVERAGE},
        "unverified": [],
    }


def test_review_shape_requires_exact_sol_max_and_no_acceptance() -> None:
    review_import._validate_review_shape(_review())
    invalid = _review()
    invalid["acceptance_authorized"] = True
    with pytest.raises(review_import.ReviewImportError, match="acceptance_authorized"):
        review_import._validate_review_shape(invalid)


def test_event_import_requires_one_provider_thread_and_terminal_turn(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-test"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                ),
            ]
        )
        + "\n"
    )
    result = review_import._events(events)
    assert result["provider_thread_count"] == 1
    assert result["provider_thread_id"] == "thread-test"
    assert result["terminal_turn_count"] == 1


def test_p0_p1_count_mismatch_is_rejected(tmp_path: Path) -> None:
    material = tmp_path / "material.txt"
    material.write_text("supporting line\n")
    review = _review()
    review["findings"] = [
        {
            "id": "DG10-SOL-001",
            "severity": "P1",
            "criterion": "traceability",
            "statement": "A problem exists.",
            "evidence": [
                {
                    "file": "material.txt",
                    "line": 1,
                    "sha256": review_import._sha256(material),
                }
            ],
            "reproduction": "sed -n '1p' material.txt",
            "release_effect": "Keep NO-GO.",
            "recommendation": "Revise evidence.",
        }
    ]
    entries = {
        "material.txt": {
            "path": "material.txt",
            "sha256": review_import._sha256(material),
        }
    }
    with pytest.raises(review_import.ReviewImportError, match="P0/P1"):
        review_import._validate_findings(review, tmp_path, entries)
