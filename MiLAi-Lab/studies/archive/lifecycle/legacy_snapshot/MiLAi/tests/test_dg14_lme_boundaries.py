from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals.dg14 import (
    DG14ContractError,
    DG14HistoryEvent,
    DG14LabelBoundaryError,
    validate_label_free,
)
from evals.dg14 import benchmark as dg14_benchmark
from evals.dg14.benchmark import (
    OPENED_DEV_INPUT_PATH,
    OPENED_DEV_INPUT_SHA256,
    REJECTED_INPUT_SHA256,
    DG14BenchmarkError,
    load_opened_dev,
)
from evals.dg14.dev_split import (
    DEFAULT_SPLIT_PATH,
    FORMAL_SOURCE_ID_MANIFESTS,
    build_public_dev_split,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_CONSUMPTION_PATHS = (
    PROJECT_ROOT / "var/dg11/splits/v1/paper-test-v1/consumption.json",
    PROJECT_ROOT / "var/dg11/splits/v1/generalization-v2/consumption.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event_payload() -> dict[str, object]:
    return {
        "case_id": "001be529",
        "session_ordinal": 0,
        "original_session_id": "session-repeated",
        "turn_ordinal": 0,
        "role": "user",
        "content": "The observed memory text may say answer or question as ordinary prose.",
        "observed_at": "2026-08-26T01:02:03+00:00",
    }


@pytest.mark.parametrize(
    "poison",
    [
        {"metadata": {"answer": "secret"}},
        {"metadata": [{"ANSWER_SESSION_IDS": ["session-repeated"]}]},
        {"metadata": {"inner": {"question_type": "multi-session"}}},
        {"metadata": {"inner": {"scorer-output": {"f1": 1.0}}}},
        {"metadata": {"holdout_annotations": ["opened"]}},
    ],
)
def test_recursive_label_boundary_rejects_benchmark_control_fields(
    poison: dict[str, object],
) -> None:
    with pytest.raises(DG14LabelBoundaryError, match="forbidden benchmark field"):
        validate_label_free(poison)


def test_history_event_loader_is_an_exact_allowlist_and_does_not_confuse_prose() -> (
    None
):
    payload = _event_payload()

    event = DG14HistoryEvent.from_mapping(payload)

    assert event.content == payload["content"]
    with pytest.raises(DG14ContractError, match="keys mismatch"):
        DG14HistoryEvent.from_mapping(
            {**payload, "label_free_metadata": {"source": "lme"}}
        )
    with pytest.raises(DG14LabelBoundaryError, match="question"):
        DG14HistoryEvent.from_mapping({**payload, "question": "leaked query"})


def test_opened_dev_loader_is_bound_to_the_exact_minus_002_path_and_digest() -> None:
    expected = PROJECT_ROOT / (
        "var/dg11/paper/runs/pe04-harness-smoke-20260824-002/inputs.json"
    )

    assert OPENED_DEV_INPUT_PATH == expected
    assert OPENED_DEV_INPUT_SHA256 == (
        "dd1c6fb5c137b16780965b5637562cdfdc8e69ef8d1f1e02e94ce92c754b5a5b"
    )
    assert _sha256(OPENED_DEV_INPUT_PATH) == OPENED_DEV_INPUT_SHA256
    partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    assert partition == "LME-OPENED-SMOKE"
    assert tuple(case.source_id for case in cases) == (
        "001be529",
        "00ca467f",
        "0100672e",
        "01493427",
        "031748ae",
    )


def test_minus_001_is_rejected_by_path_and_hash_before_parsing_or_product_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = PROJECT_ROOT / (
        "var/dg11/paper/runs/pe04-harness-smoke-20260824-001/inputs.json"
    )
    parsed = False
    product_call_attempted = False

    def forbidden_json_loads(_value: str | bytes, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal parsed
        parsed = True
        raise AssertionError("rejected snapshot must not be parsed")

    def forbidden_product_call() -> None:
        nonlocal product_call_attempted
        product_call_attempted = True
        raise AssertionError("rejected snapshot must not reach product calls")

    assert REJECTED_INPUT_SHA256 == (
        "8d27d36136e2d4b93b1813c31c50733e9c71be0b9f8eaa3bba85c5ef0d79816a"
    )
    assert _sha256(expected) == REJECTED_INPUT_SHA256
    monkeypatch.setattr(json, "loads", forbidden_json_loads)
    with pytest.raises(DG14BenchmarkError, match="rejected|duplicate|-001"):
        load_opened_dev(expected, pre_call_hook=forbidden_product_call)
    assert parsed is False
    assert product_call_attempted is False


def test_question_and_labels_stay_out_of_every_ingest_event() -> None:
    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)

    for case in cases:
        assert case.question
        events = dg14_benchmark._events(case, dg14_benchmark.METHOD_ID)
        dg14_events = tuple(
            event for event in events if isinstance(event, DG14HistoryEvent)
        )
        assert len(dg14_events) == len(events)
        assert all(
            set(event.canonical())
            == {
                "case_id",
                "session_ordinal",
                "original_session_id",
                "turn_ordinal",
                "role",
                "content",
                "observed_at",
            }
            for event in dg14_events
        )
        encoded = json.dumps(
            [event.canonical() for event in dg14_events],
            ensure_ascii=False,
            sort_keys=True,
        )
        assert case.question not in encoded
        assert "answer_session_ids" not in encoded
        assert "question_type" not in encoded
        assert "scorer_output" not in encoded
        assert "holdout_annotations" not in encoded


def test_formal_consumption_paths_remain_absent_without_inspecting_old_holdout_history() -> (
    None
):
    assert all(not path.exists() for path in FORMAL_CONSUMPTION_PATHS)


def test_public_dev_split_is_deterministic_and_excludes_formal_source_ids(
    tmp_path: Path,
) -> None:
    rebuilt = build_public_dev_split(output_path=tmp_path / "source-ids.json")
    frozen = json.loads(DEFAULT_SPLIT_PATH.read_text(encoding="utf-8"))
    excluded = {
        source_id
        for path in FORMAL_SOURCE_ID_MANIFESTS
        for source_id in json.loads(path.read_text(encoding="utf-8"))["source_ids"]
    }

    assert rebuilt["source_ids"] == frozen["source_ids"]
    assert rebuilt["source_ids_sha256"] == frozen["source_ids_sha256"]
    assert len(rebuilt["source_ids"]) == 50
    assert not set(rebuilt["source_ids"]).intersection(excluded)
    assert rebuilt["formal_source_id_overlap"] == []
    assert rebuilt["formal_holdout_consumed"] is False
    assert rebuilt["status"] == "NOT_FORMALLY_EVALUATED"
