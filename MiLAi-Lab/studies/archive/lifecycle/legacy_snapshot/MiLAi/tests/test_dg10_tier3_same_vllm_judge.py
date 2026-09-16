from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import run_dg10_tier3_same_vllm_judge as tier3


def test_judge_contract_is_characterization_only_and_hash_stable() -> None:
    contract = tier3._judge_contract()
    assert contract["release_input"] is False
    assert contract["temperature"] == 0
    assert contract["max_output_tokens"] == 256
    assert len(tier3._json_sha256(contract)) == 64


def test_exact_judgment_parser_accepts_schema_and_rejects_extra_text() -> None:
    value = {
        "correctness": "CORRECT",
        "support_status": "SUPPORTED",
        "uncertainty_calibration": "APPROPRIATE",
        "reason_codes": ["LATEST_STATE"],
        "explanation": "The answer matches the reference and bounded evidence.",
    }
    parsed = tier3._parse_judgment(json.dumps(value))
    assert {key: parsed[key] for key in value} == value
    assert parsed["normalization"] == {
        "duplicate_reason_codes_removed": 0,
        "explanation_word_count": 8,
        "explanation_exceeds_advisory_80_words": False,
    }
    with pytest.raises(tier3.Tier3JudgeError, match="exact JSON"):
        tier3._parse_judgment("```json\n" + json.dumps(value) + "\n```")


def test_reason_code_duplicates_are_audited_and_canonicalized() -> None:
    value = {
        "correctness": "CORRECT",
        "support_status": "SUPPORTED",
        "uncertainty_calibration": "APPROPRIATE",
        "reason_codes": ["LATEST_STATE", "LATEST_STATE"],
        "explanation": "The answer matches.",
    }
    parsed = tier3._parse_judgment(json.dumps(value))
    assert parsed["reason_codes"] == ["LATEST_STATE"]
    assert parsed["normalization"] == {
        "duplicate_reason_codes_removed": 1,
        "explanation_word_count": 3,
        "explanation_exceeds_advisory_80_words": False,
    }


def test_empty_reason_codes_and_long_explanation_are_characterization_warnings() -> (
    None
):
    explanation = " ".join(["word"] * 81)
    value = {
        "correctness": "INCORRECT",
        "support_status": "UNSUPPORTED",
        "uncertainty_calibration": "OVERCONFIDENT",
        "reason_codes": [],
        "explanation": explanation,
    }
    parsed = tier3._parse_judgment(json.dumps(value))
    assert parsed["reason_codes"] == []
    assert parsed["normalization"]["explanation_word_count"] == 81
    assert parsed["normalization"]["explanation_exceeds_advisory_80_words"] is True


def test_frozen_subset_has_36_hash_interleaved_records() -> None:
    sidecar = tier3.tier2._load_bound(
        tier3.THREE_ARM_SIDECAR, tier3.THREE_ARM_SIDECAR_SHA256
    )
    records = tier3._ordered_records(sidecar)
    assert len(records) == 36
    assert {record["case_id"] for record in records} == set(tier3.CASE_IDS)
    assert {record["arm"] for record in records} == set(tier3.ARMS)
    assert len({(record["case_id"], record["arm"]) for record in records}) == 36


def test_messages_include_bounded_evidence_but_no_tool_instruction() -> None:
    sidecar = tier3.tier2._load_bound(
        tier3.THREE_ARM_SIDECAR, tier3.THREE_ARM_SIDECAR_SHA256
    )
    record = tier3._ordered_records(sidecar)[0]
    messages = tier3._messages(record)
    assert len(messages) == 2
    assert "Candidate answer:" in messages[1]["content"]
    assert "milai_recall" not in messages[1]["content"]


def test_progress_journal_preserves_native_receipt_before_parsing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "progress.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        tier3._write_journal_line(
            stream,
            {
                "schema": "milai.dg10.tier3-progress-journal.v1",
                "run_id": "journal-test",
            },
        )
        tier3._write_journal_line(
            stream,
            {
                "ordinal": 0,
                "native_request_id": "chatcmpl-test",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )
    summary = tier3._journal_summary(path, "journal-test")
    assert summary["completed_native_model_calls"] == 1
    assert summary["input_tokens"] == 10
    assert summary["output_tokens"] == 2
