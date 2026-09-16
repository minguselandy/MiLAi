from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

LAB = Path(__file__).resolve().parents[2]
TOOLS = LAB / "tools"


def _module() -> ModuleType:
    path = TOOLS / "run_product09_codex_lme.py"
    spec = importlib.util.spec_from_file_location("product09_codex_lme", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(TOOLS))
    return module


def test_visible_session_coverage_uses_host_visible_evidence_only() -> None:
    module = _module()
    run = {
        "calls": [
            {
                "structured_content": {
                    "evidence": [
                        {"source": {"id": "session-a"}},
                        {"source": {"id": "session-b"}},
                    ]
                }
            }
        ]
    }
    assert module._visible_sessions(run) == {"session-a", "session-b"}


def test_visible_turn_coverage_uses_serialized_source_refs() -> None:
    module = _module()
    run = {
        "calls": [
            {
                "structured_content": {
                    "evidence": [
                        {
                            "source": {
                                "id": "session-a",
                                "turn_refs": ["turn-a", "turn-b"],
                            }
                        },
                        {"source": {"id": "session-b", "turn_refs": ["turn-c"]}},
                    ]
                }
            }
        ]
    }
    assert module._visible_turn_refs(run) == {"turn-a", "turn-b", "turn-c"}


def test_behavior_trace_distinguishes_stateful_continuation_from_fresh_repeat() -> None:
    module = _module()
    run = {
        "calls": [
            {
                "arguments": {"query": "Which items?"},
                "structured_content": {
                    "context_id": "ctx-1",
                    "retrieval_status": "HIT",
                    "continuation": {"available": True},
                    "evidence": [
                        {
                            "id": "e-1",
                            "source": {"turn_refs": ["turn-a"]},
                        }
                    ],
                },
            },
            {
                "arguments": {
                    "query": "Which items?",
                    "previous_context_id": "ctx-1",
                },
                "structured_content": {
                    "context_id": "ctx-2",
                    "retrieval_status": "HIT",
                    "continuation": {
                        "available": False,
                        "candidate_origin": "PERSISTED_FRONTIER",
                        "reason": "FRONTIER_EXHAUSTED",
                    },
                    "evidence": [
                        {
                            "id": "e-2",
                            "source": {"turn_refs": ["turn-b"]},
                        }
                    ],
                },
            },
        ]
    }

    behavior = module._behavior_trace(run, expected_query="Which items?")

    assert behavior["stateful_continuation_used"] is True
    assert behavior["valid_lineage_call_count"] == 1
    assert behavior["persisted_frontier_call_count"] == 1
    assert behavior["fresh_reacquisition_after_first_count"] == 0
    assert behavior["novel_turn_refs_after_first"] == 1
    assert behavior["calls"][1]["same_query_as_first"] is True
    assert behavior["calls"][0]["query_matches_expected"] is True
    assert behavior["calls"][0]["query_sha256"] == (
        "c97058b4a7b189901dd782092775edf8427fee289948218976ffc315bbd8b8de"
    )


def test_behavior_trace_marks_second_fresh_query_as_reacquisition() -> None:
    module = _module()
    run = {
        "calls": [
            {
                "arguments": {"query": "first"},
                "structured_content": {"context_id": "ctx-1", "evidence": []},
            },
            {
                "arguments": {"query": "second"},
                "structured_content": {"context_id": "ctx-2", "evidence": []},
            },
        ]
    }

    behavior = module._behavior_trace(run)

    assert behavior["stateful_continuation_used"] is False
    assert behavior["persisted_frontier_call_count"] == 0
    assert behavior["fresh_reacquisition_after_first_count"] == 1
    assert behavior["calls"][1]["same_query_as_first"] is False


def test_wait_projection_batches_large_lme_sessions() -> None:
    module = _module()
    observed: list[list[str]] = []
    module.p09._wait_projection = lambda _environment, ids: observed.append(ids)

    module._wait_projection_batched({}, [str(index) for index in range(1025)])

    assert [len(batch) for batch in observed] == [512, 512, 1]


def test_score_case_records_exact_required_turn_gain_by_call() -> None:
    module = _module()
    record = {
        "question_id": "case",
        "question_type": "multi-session",
        "answer": "two",
    }
    run = {
        "answer": "two",
        "latency_ms": 1.0,
        "returncode": 0,
        "calls": [
            {
                "arguments": {"query": "items"},
                "structured_content": {
                    "context_id": "ctx-1",
                    "evidence": [
                        {"id": "e-1", "source": {"id": "s-1", "turn_refs": ["t-1"]}}
                    ],
                },
            },
            {
                "arguments": {"query": "items", "previous_context_id": "ctx-1"},
                "structured_content": {
                    "context_id": "ctx-2",
                    "evidence": [
                        {"id": "e-2", "source": {"id": "s-2", "turn_refs": ["t-2"]}}
                    ],
                },
            },
        ],
    }

    result = module._score_case(
        record,
        {"capability_family": "MULTI_SESSION_SET_COUNT"},
        run,
        {"s-1", "s-2"},
        {"t-1": {}, "t-2": {}},
    )

    assert result["first_call_required_turn_count"] == 1
    assert result["required_turns_recovered_after_first_count"] == 1
    assert result["all_answer_turns_visible_on_first_call"] is False
    assert result["required_turn_coverage_by_call"] == [
        {
            "call_index": 1,
            "required_turn_count_in_call": 1,
            "new_required_turn_count": 1,
            "cumulative_required_turn_count": 1,
            "all_required_turns_cumulative": False,
        },
        {
            "call_index": 2,
            "required_turn_count_in_call": 1,
            "new_required_turn_count": 1,
            "cumulative_required_turn_count": 2,
            "all_required_turns_cumulative": True,
        },
    ]
