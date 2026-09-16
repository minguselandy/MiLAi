from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from milai_lab.product10 import InstanceGroup

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _module():
    path = TOOLS / "run_product10_context.py"
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("run_product10_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_redaction_preserves_identities_and_removes_text() -> None:
    module = _module()
    redacted = module._sanitize_mcp(
        {
            "schema_version": "memory-evidence-context-v1",
            "retrieval_status": "HIT",
            "context_id": "context-1",
            "snapshot": {"as_of": "2026-09-03T00:00:00Z"},
            "continuation": None,
            "evidence": [
                {
                    "id": "e1",
                    "kind": "EVIDENCE",
                    "text": "private evidence body",
                    "evidence_ids": ["e1"],
                    "source": {
                        "type": "agent_session",
                        "id": "s1",
                        "turn_refs": ["t1"],
                    },
                }
            ],
            "warnings": [],
            "profile": {"resolved": "MCP_INTERACTIVE_WIDE_V01"},
        }
    )

    assert redacted["raw_evidence_text_emitted"] is False
    assert redacted["evidence"][0]["evidence_ids"] == ["e1"]
    assert redacted["evidence"][0]["source"]["turn_refs"] == ["t1"]
    assert "private evidence body" not in str(redacted)


def test_join_requires_exact_ordered_mcp_identity_match() -> None:
    module = _module()
    report = {
        "mcp_join_expectation": {
            "selected_evidence_ids": ["e1", "e2"],
            "selected_source_turn_refs": ["t1", "t2"],
        }
    }
    mcp = {
        "evidence": [
            {
                "evidence_ids": ["e1", "e2"],
                "source": {"turn_refs": ["t1", "t2"]},
            }
        ]
    }

    assert module._join_matches(report, mcp) is True
    mcp["evidence"][0]["evidence_ids"] = ["e2", "e1"]
    assert module._join_matches(report, mcp) is False


def test_operational_reference_time_is_fixed_and_timezone_aware() -> None:
    module = _module()

    assert module._operational_reference_time(
        "2026-09-03T16:02:35.243987Z"
    ) == "2026-09-03T16:02:35.243987+00:00"


def test_projection_readiness_is_chunked_at_public_contract_limit(monkeypatch) -> None:
    module = _module()
    calls: list[list[str]] = []

    def wait(_environment, outbox_ids):
        calls.append(outbox_ids)
        return {"status": "READY"}

    monkeypatch.setattr(module.p09, "_wait_projection", wait)
    result = module._wait_projection_batches({}, [str(value) for value in range(1_025)])

    assert [len(value) for value in calls] == [512, 512, 1]
    assert result["status"] == "READY"
    assert result["target_count"] == 1_025
    assert result["readiness_batch_count"] == 3


def test_decisive_admission_step_uses_context_omission_reason() -> None:
    module = _module()
    group = InstanceGroup(
        group_id="case:g1",
        acceptable_evidence_ids=("evidence-2",),
        acceptable_turn_refs=("turn-2",),
        required_for_answer=True,
    )

    result = module._decisive_step(
        group,
        "DISCOVERED_NOT_ADMITTED",
        {},
        {
            "selected_unit_ids": ["evidence:window-1"],
            "omitted_unit_reasons": {
                "evidence:window-2": "AVAILABLE_MEMORY_BELOW_UNIT_ACTIVATION_THRESHOLD"
            },
            "conditional_activation_thresholds": {"evidence:window-2": 20_000},
            "budget_envelope": {"available_memory_tokens": 16_384},
            "candidate_window_trace": [
                {
                    "window_id": "window-2",
                    "evidence_ids": ["evidence-2"],
                    "source_turn_refs": ["turn-2"],
                    "source_rank": 7,
                }
            ],
        },
    )

    assert result["stage_id"] == "C50"
    assert result["reason_code"] == (
        "AVAILABLE_MEMORY_BELOW_UNIT_ACTIVATION_THRESHOLD"
    )
    assert result["source_rank"] == 7


def test_decisive_admission_step_uses_pre_context_lifecycle_rejection() -> None:
    module = _module()
    group = InstanceGroup(
        group_id="case:g1",
        acceptable_evidence_ids=(),
        acceptable_turn_refs=("turn-2",),
        required_for_answer=True,
    )

    result = module._decisive_step(
        group,
        "DISCOVERED_NOT_ADMITTED",
        {
            "occurrences": [
                {
                    "occurrence_id": "occurrence-2",
                    "evidence_record_identity": {"source_ref": "turn-2"},
                }
            ],
            "candidate_lifecycles": [
                {
                    "candidate_identity": "evidence-2",
                    "occurrence_id": "occurrence-2",
                    "lifecycle": [
                        {
                            "stage_id": "S43",
                            "disposition": "REJECTED",
                            "reason_code": "REQUIREMENT_UNSATISFIED",
                            "decision_digest": "d" * 64,
                        }
                    ],
                }
            ],
        },
        {"candidate_window_trace": []},
    )

    assert result == {
        "stage_id": "S43",
        "reason_code": "REQUIREMENT_UNSATISFIED",
        "decision_digest": "d" * 64,
    }


def test_h1_guard_is_full_case_loss_not_partial_case_group_loss() -> None:
    module = _module()

    def row(
        case_id: str,
        covered: tuple[bool, ...],
        shapes: tuple[str, ...] = ("ENUMERATION",),
    ) -> dict[str, object]:
        numerator = sum(covered)
        return {
            "case_id": case_id,
            "distinct_instance_coverage": {
                "numerator": numerator,
                "denominator": len(covered),
                "value": numerator / len(covered),
            },
            "groups": [
                {
                    "group_id": f"{case_id}:g{index}",
                    "covered": value,
                    "first_loss": None if value else "DISCOVERED_NOT_ADMITTED",
                }
                for index, value in enumerate(covered, start=1)
            ],
            "capability_shapes": list(shapes),
        }

    a0_rows = [row("case-00", (True, False))]
    b1_rows = [row("case-00", (False, True), ("ENUMERATION", "COUNTING"))]
    for index in (1, 2):
        case_id = f"case-{index:02d}"
        a0_rows.append(row(case_id, (False,)))
        b1_rows.append(row(case_id, (True,), ("ENUMERATION", "COUNTING")))
    for index in range(3, 24):
        case_id = f"case-{index:02d}"
        a0_rows.append(row(case_id, (True,)))
        b1_rows.append(row(case_id, (True,)))

    result = module._summarize_h1(a0_rows, b1_rows)

    assert result["status"] == "PASS_PRODUCT10_H1"
    assert result["previously_covered_instance_groups_lost"] == 1
    assert result["previously_full_coverage_cases_lost"] == 0
    assert result["lost_full_coverage_case_ids"] == []
    assert result["thresholds"]["previously_full_coverage_cases_lost_eq"] == 0
    assert "lost_groups_eq" not in result["thresholds"]
