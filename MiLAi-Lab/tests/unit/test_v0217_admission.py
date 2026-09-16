"""Zero-model guards do not count as model presentation or benchmark success."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0217_admission_contract import (
    checkpoint_session_prefix,
    exposure_receipt,
    local_provider_config,
    online_question,
    online_sessions,
)


def test_coverage_window_is_not_a_history_reset():
    sample = {"sessions": [{"_v2_session_id": name} for name in ("A", "B", "C", "D")]}
    assert checkpoint_session_prefix(sample, ["B", "C"]) == ["A", "B", "C"]
    assert checkpoint_session_prefix(sample, ["A", "B"]) == ["A", "B"]
    for invalid in ([], ["UNKNOWN"], ["B", "B"]):
        with pytest.raises(ValueError, match="REFERENCES"):
            checkpoint_session_prefix(sample, invalid)


def provider():
    return {"base_url": "http://127.0.0.1:7860/v1", "model": "Qwen3.6-35B-A3B-FP8",
        "api_key_env": "MILAI_LOCAL_VLLM_API_KEY", "allow_gold_fallback": False,
        "allow_remote_fallback": False}


@pytest.mark.parametrize("key,value", [("base_url", "https://example.com/v1"),
    ("base_url", "http://127.0.0.1:7860/v1/v1"), ("allow_gold_fallback", True),
    ("allow_remote_fallback", True), ("model", "other-model"), ("api_key_env", "")])
def test_bad_configuration_fails_without_provider_call(key, value):
    cfg = provider()
    cfg[key] = value
    with pytest.raises(ValueError):
        local_provider_config(cfg)


def test_exact_provider_mapping():
    assert local_provider_config(provider()) == provider()


def test_gold_category_future_and_trace_do_not_cross_whitelist():
    sample = {"sessions": [
        {"_v2_session_id": "S00", "dialogue": [{"role": "user", "content": "Earlier fact",
            "gold": "SECRET_GOLD", "raw_trace": "SECRET_TRACE"}]},
        {"_v2_session_id": "S01", "dialogue": [{"role": "user", "content": "SECRET_FUTURE"}]}],
        "memory_points": "SECRET_POINTS", "qa_checkpoints": "SECRET_ANSWERS"}
    view = online_sessions(sample, ["S00"])
    view.update(online_question({"question": "Which fact?", "answer": "SECRET_ANSWERS",
        "gold_answer": "SECRET_GOLD", "question_type_abbrev": "SECRET_CATEGORY"}))
    assert "SECRET_" not in json.dumps(view)
    assert "Earlier fact" in json.dumps(view)
    with pytest.raises(ValueError, match="PREFIX"):
        online_sessions(sample, ["S01"])


def test_modality_is_never_silently_removed_or_generated():
    sample = {"sessions": [{"_v2_session_id": "S00", "dialogue": [{"role": "user",
        "content": "Inspect image", "attachments": [{"image_id": "I1", "caption": "Official",
            "file_path": "/private/file", "gold": "SECRET_GOLD"}]}]}]}
    with pytest.raises(ValueError, match="MODALITY"):
        online_sessions(sample, ["S00"])
    view = online_sessions(sample, ["S00"], profile="official_caption_diagnostic")
    assert not view["images_presented"] and not view["native_multimodal_equivalence"]
    assert "Official" in json.dumps(view) and "SECRET" not in json.dumps(view)
    assert "/private" not in json.dumps(view)


def test_assembly_does_not_count_as_send_or_use():
    payload = b"known fixture"
    digest = hashlib.sha256(payload).hexdigest()
    assert exposure_receipt(payload, expected_sha256=digest, transport_ack=False)[
        "status"] == "ASSEMBLED_ONLY"
    assert not exposure_receipt(payload, expected_sha256=digest, transport_ack=True)[
        "understanding_or_use_proved"]
    with pytest.raises(ValueError, match="CHANGED"):
        exposure_receipt(b"other", expected_sha256=digest, transport_ack=True)
