from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
recall = importlib.import_module("check_v02_scoped_recall")


@pytest.mark.parametrize("refs", [
    set(), {""}, {"abc", "bc"}, {"a.b", "x|y", "[z]", "\\", "\n"},
    {"约束", "e\u0301", "😀"}, {"forbidden", "forbidden-long"},
])
def test_compiled_disclosure_matches_literal_checks_over_complete_json(refs):
    matcher = recall.compile_forbidden_refs(refs)
    for text in ["clean", "abc", "x|y", "[z]", "aXb", "a.b", "\n", "\\", "约束", "e\u0301", "😀",
                 "prefix-forbidden-long-suffix"]:
        for hidden in [{"trace": {"nested": [text]}}, {text: "in a key"}]:
            value = {"retrieval_status": "HIT", "evidence": [{"evidence_ids": ["allowed"]}],
                     **hidden}
            disclosed = any(ref in json.dumps(value, ensure_ascii=False) for ref in refs)
            if disclosed:
                with pytest.raises(AssertionError, match="CROSS_SCOPE_EVIDENCE_ID_DISCLOSED"):
                    recall.check_result(value, {"allowed"}, matcher)
            else:
                assert recall.check_result(value, {"allowed"}, matcher) == {"allowed"}


@pytest.mark.parametrize("position", [0, 499, 999])
def test_compiled_disclosure_detects_every_position_without_word_boundaries(position):
    refs = {f"source-{i:04d}" for i in range(1000)}
    matcher = recall.compile_forbidden_refs(refs)
    value = {"retrieval_status": "MISS", "evidence": [],
             "trace": {"first": "x" * 8192, "last": f"presource-{position:04d}post"}}
    with pytest.raises(AssertionError, match="CROSS_SCOPE_EVIDENCE_ID_DISCLOSED"):
        recall.check_result(value, set(), matcher, require_hit=False)


def test_sources_preserve_size_boundaries_and_both_projects():
    for i in range(6):
        value = recall.source(i, [512, 2048, 8192])
        assert len(value["content"].encode()) == [512, 2048, 8192][i % 3]
        assert value["content"].startswith(f"rangefixture rangedoc{i:04d}\nfirst\n")
        assert value["content"].endswith("\nlast\n")
        assert value["permission_snapshot"]["project_ids"] == [
            "mixed-project" if i % 2 == 0 else "other-project",
        ]


@pytest.mark.parametrize("value,require_hit", [
    ({"retrieval_status": "HIT", "evidence": [{"evidence_ids": ["allowed"]}]}, True),
    ({"retrieval_status": "MISS", "evidence": []}, False),
])
def test_scoped_hits_and_explicit_misses(value, require_hit):
    recall.check_result(value, {"allowed"}, {"forbidden"}, require_hit=require_hit)


@pytest.mark.parametrize("value,require_hit", [
    ({"retrieval_status": "HIT", "evidence": [{"evidence_ids": ["forbidden"]}]}, True),
    ({"retrieval_status": "HIT", "evidence": [{"evidence_ids": ["unknown"]}]}, True),
    ({"retrieval_status": "HIT", "evidence": [{"evidence_ids": ["allowed"]}],
      "trace": {"source": "forbidden"}}, True),
    ({"retrieval_status": "MISS", "evidence": []}, True),
    ({"retrieval_status": "ERROR", "evidence": []}, False),
    ({"retrieval_status": "DEGRADED", "evidence": [{"evidence_ids": ["allowed"]}]}, True),
    ({}, False),
])
def test_leak_missing_evidence_and_unjudged_responses_do_not_pass(value, require_hit):
    with pytest.raises(AssertionError):
        recall.check_result(value, {"allowed"}, {"forbidden"}, require_hit=require_hit)


def test_budget_limited_view_is_explicit_opt_in_and_keeps_disclosure_check():
    value = {"retrieval_status": "DEGRADED", "evidence": [{"evidence_ids": ["allowed"]}],
             "warnings": [{"code": "RETRIEVAL_DEGRADED", "message":
                 "The returned memory context was limited by the context budget."}]}
    with pytest.raises(AssertionError):
        recall.check_result(value, {"allowed"}, {"forbidden"})
    assert recall.check_result(
        value, {"allowed"}, {"forbidden"}, allow_budget_limited=True,
    ) == {"allowed"}
    value["trace"] = "forbidden"
    with pytest.raises(AssertionError):
        recall.check_result(value, {"allowed"}, {"forbidden"}, allow_budget_limited=True)


@pytest.mark.parametrize("warnings", [[], [{"code": "RETRIEVAL_DEGRADED"}],
    [{"code": "RETRIEVAL_DEGRADED", "message": "index unavailable"}]])
def test_other_degradation_never_uses_budget_exception(warnings):
    with pytest.raises(AssertionError):
        recall.check_result(
            {"retrieval_status": "DEGRADED", "evidence": [{"evidence_ids": ["allowed"]}],
             "warnings": warnings},
            {"allowed"}, {"forbidden"}, allow_budget_limited=True,
        )


@pytest.mark.parametrize("outcome", ["success", "leak", "cancel", "expected_rejection"])
def test_response_boundary_excludes_checks_without_weakening_failures(outcome):
    class Result:
        is_error = outcome == "expected_rejection"

        def __init__(self):
            self.structured_content = {
                "retrieval_status": "HIT",
                "evidence": [{"evidence_ids": ["forbidden" if outcome == "leak" else "allowed"]}],
            }

        def model_dump(self, **kwargs):
            return {"isError": self.is_error, "structuredContent": self.structured_content}

    class Client:
        calls = 0

        async def call_tool(self, tool, args):
            self.calls += 1
            assert tool == "milai_memory_resolve" and args == {"query": "query"}
            if outcome == "cancel":
                raise asyncio.CancelledError
            return Result()

    event = {"start_s": 10.0}
    clock_values = iter([10.25] if outcome == "cancel" else [10.125, 10.25])
    client = Client()
    call = recall.observe_resolve(
        client, event, "query", {"request_timeout_seconds": 1}, {"allowed"}, {"forbidden"},
        expect_error=outcome == "expected_rejection", clock=lambda: next(clock_values),
    )
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(call)
    elif outcome == "leak":
        with pytest.raises(AssertionError, match="CROSS_SCOPE"):
            asyncio.run(call)
    else:
        asyncio.run(call)
    assert client.calls == 1
    assert event["elapsed_ms"] == 250.0
    if outcome == "cancel":
        assert event["call_to_response_ms"] is None
        assert event["post_response_checks_ms"] is None
    else:
        assert event["call_to_response_ms"] == 125.0
        assert event["post_response_checks_ms"] == 125.0
    assert event["status"] == {
        "success": "COMPLETED", "expected_rejection": "EXPECTED_REJECTION",
        "leak": "FAILED_OR_CANCELLED", "cancel": "FAILED_OR_CANCELLED",
    }[outcome]
