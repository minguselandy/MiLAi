from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
chain = importlib.import_module("run_v02_e2e_generality")


def encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=3) + "\n").encode()


@pytest.fixture
def material(tmp_path):
    content = "首部\nThe package still awaits collection.\n尾部\n"
    source = {
        "question": "Which package is pending?", "question_date": "2026/09/06 (Sun) 10:00",
        "sessions": [{"session_ordinal": 7, "turns": [
            {"turn_ordinal": 3, "role": "user", "content": content},
        ]}],
    }
    source_bytes = encoded(source)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    contract = {
        "schema_version": "v02-source-evaluation-v1", "source_sha256": source_hash,
        "question": source["question"], "question_date": source["question_date"],
        "first_use_boundary": "First delivered decision", "necessary_conditions": ["Use source"],
        "source_assertions": [{"statement": "EVALUATOR_ONLY_expected", "spans": [{
            "session_ordinal": 7, "turn_ordinal": 3, "role": "user",
            "start": 0, "end": len(content), "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }]}],
    }
    config = {
        "source_mode": "PUBLIC_SOURCE_SNAPSHOT", "source_path": "source.json",
        "source_sha256": source_hash, "task_evaluation": "SOURCE_ASSERTIONS_FROZEN",
        "evaluation_contract": {
            "path": "contract.json", "sha256": hashlib.sha256(encoded(contract)).hexdigest(),
        },
        "data_mode": "DEIDENTIFIED_ALLOWED", "model_transport_enabled": False,
        "new_model_allocations_authorized": 0, "new_model_tokens_authorized": 0,
    }
    (tmp_path / "source.json").write_bytes(source_bytes)
    (tmp_path / "contract.json").write_bytes(encoded(contract))
    (tmp_path / "config.json").write_bytes(encoded(config))
    return config, source, contract


def test_frozen_contract_verifies_source_positions_without_scoring(material):
    config, source, contract = material
    assert chain.evaluation_contract(config, encoded(source), encoded(contract)) == contract


@pytest.mark.parametrize("mode", [
    "flag_only", "changed_contract", "changed_source", "wrong_question", "wrong_date",
    "wrong_role", "unknown_session", "unknown_turn", "bad_offset", "wrong_span_hash",
    "empty_assertions", "empty_spans", "empty_boundary",
])
def test_invalid_evaluation_contract_is_rejected(material, mode):
    config, source, contract = material
    ref = contract["source_assertions"][0]["spans"][0]
    if mode == "flag_only":
        config.pop("evaluation_contract")
    elif mode == "changed_contract":
        contract["first_use_boundary"] += "changed"
    elif mode == "changed_source":
        source["question_date"] = "changed"
    elif mode == "wrong_question":
        contract["question"] = "different question"
    elif mode == "wrong_date":
        contract["question_date"] = "different date"
    elif mode == "wrong_role":
        ref["role"] = "assistant"
    elif mode == "unknown_session":
        ref["session_ordinal"] = 8
    elif mode == "unknown_turn":
        ref["turn_ordinal"] = 8
    elif mode == "bad_offset":
        ref["end"] += 1
    elif mode == "wrong_span_hash":
        ref["sha256"] = "0" * 64
    elif mode == "empty_assertions":
        contract["source_assertions"] = []
    elif mode == "empty_spans":
        contract["source_assertions"][0]["spans"] = []
    elif mode == "empty_boundary":
        contract["first_use_boundary"] = " "
    if mode not in {"flag_only", "changed_contract", "changed_source"}:
        config["evaluation_contract"]["sha256"] = hashlib.sha256(encoded(contract)).hexdigest()
    with pytest.raises(chain.LocalGateError):
        chain.evaluation_contract(config, encoded(source), encoded(contract))


def test_prepare_preserves_exact_frozen_bytes_and_rejects_before_services(
    tmp_path, material, monkeypatch,
):
    _config, source, contract = material
    calls = []
    monkeypatch.setattr(chain.base, "LAB", tmp_path)
    monkeypatch.setattr(chain.base, "pin", lambda _: {"valid": True})
    monkeypatch.setattr(chain.base, "prepare", lambda *a, **k: calls.append("service"))
    monkeypatch.setattr(chain, "prepare_snapshot", lambda *a: calls.append("snapshot"))
    compose = tmp_path / "test-compose.yaml"
    compose.write_text("services: {}\n")
    root = tmp_path / "prepared"
    chain.prepare(root, tmp_path / "config.json", compose_override=compose)
    assert (root / "input-source.json").read_bytes() == encoded(source)
    assert (root / "evaluation-contract.json").read_bytes() == encoded(contract)
    assert calls == ["service", "snapshot"]
    assert not (root / "G/workspace/evaluation-contract.json").exists()
    (tmp_path / "contract.json").write_text("changed")
    with pytest.raises(chain.LocalGateError, match="IDENTITY_CHANGED"):
        chain.prepare(tmp_path / "invalid", tmp_path / "config.json", compose_override=compose)
    assert calls == ["service", "snapshot"]
    assert not (tmp_path / "invalid").exists()


def test_run_keeps_zero_authorization_and_rechecks_frozen_artifacts(
    tmp_path, material, monkeypatch,
):
    config, source, contract = material
    calls = []
    monkeypatch.setattr(chain, "run_chain", lambda _: calls.append("chain"))
    monkeypatch.setattr(chain.base, "pin", lambda _: {"valid": True})
    with pytest.raises(chain.LocalGateError, match="NO_NEW_MODEL_AUTHORIZATION"):
        chain.run(tmp_path)
    assert calls == []
    # Positive authorization exists only in this isolated, network-free unit fixture.
    config.update(model_transport_enabled=True, new_model_allocations_authorized=3,
                  new_model_tokens_authorized=60000)
    (tmp_path / "config.json").write_bytes(encoded(config))
    (tmp_path / "input-source.json").write_bytes(encoded(source))
    (tmp_path / "evaluation-contract.json").write_bytes(encoded(contract))
    chain.run(tmp_path)
    assert calls == ["chain"]
    (tmp_path / "evaluation-contract.json").write_bytes(encoded(contract) + b" ")
    with pytest.raises(chain.LocalGateError, match="IDENTITY_CHANGED"):
        chain.run(tmp_path)
    assert calls == ["chain"]


@pytest.mark.parametrize("date", [None, "", " ", False])
def test_missing_question_time_stops_before_generator(tmp_path, date):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "input-source.json").write_bytes(
        encoded({"question": "Continue", "question_date": date})
    )
    calls = []
    result = chain.run_chain(tmp_path, launch=lambda *a: calls.append(a))
    assert calls == []
    assert result["status"] == "STOPPED_WITH_FAILURE"
    assert result["error"] == "CONTINUATION_QUESTION_AND_DATE_REQUIRED"
    assert result["semantic_task_effect"] == "NOT_EVALUATED"
