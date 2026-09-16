from milai_lab.product03_opportunity import (
    OpportunityCase,
    channel_candidate_refs,
    compare_mechanisms,
    select_allowed_treatment,
)


def _case(
    case_id: str,
    *,
    query_type: str,
    refs: dict[str, tuple[str, ...]],
) -> OpportunityCase:
    return OpportunityCase(
        case_id=case_id,
        family="F1_DISCOVERY",
        query_type=query_type,
        answer_turn_refs=(f"gold-{case_id}",),
        required_role_groups=((f"gold-{case_id}",),),
        candidate_refs=refs,
        candidate_count=sum(len(values) for values in refs.values()),
        duplicate_occurrence_count=0,
    )


def test_channel_candidate_refs_uses_official_lineage_only() -> None:
    refs = channel_candidate_refs(
        [
            {
                "source_turn_ref": "turn-a",
                "channel_ranks": {"FTS_RAW": 1, "EVIDENCE_DENSE": 2},
                "expansion_origin": None,
            },
            {
                "source_turn_ref": "turn-b",
                "channel_ranks": {"ADJACENT_TURNS": 1},
                "expansion_origin": "ADJACENT_TURNS",
            },
        ]
    )

    assert refs == {
        "ADJACENT_TURNS": ("turn-b",),
        "ALL": ("turn-a", "turn-b"),
        "EVIDENCE_DENSE": ("turn-a",),
        "FTS_RAW": ("turn-a",),
    }


def test_comparison_gate_requires_three_groups_and_two_query_types() -> None:
    baseline = [
        _case("a", query_type="type-a", refs={"ALL": ()}),
        _case("b", query_type="type-b", refs={"ALL": ()}),
        _case("c", query_type="type-b", refs={"ALL": ()}),
    ]
    diagnostic = [
        _case("a", query_type="type-a", refs={"EVIDENCE_DENSE": ("gold-a",)}),
        _case("b", query_type="type-b", refs={"EVIDENCE_DENSE": ("gold-b",)}),
        _case("c", query_type="type-b", refs={"EVIDENCE_DENSE": ("gold-c",)}),
    ]

    result = compare_mechanisms(baseline, diagnostic)

    dense = result["A1_EVIDENCE_DENSE"]
    assert isinstance(dense, dict)
    assert dense["new_required_role_group_count"] == 3
    assert dense["lost_required_role_group_count"] == 0
    assert dense["selected_family_role_recovery"] == 1.0
    assert dense["acquired_exact_turn_recall_delta"] == 1.0
    assert dense["acquired_role_coverage_delta"] == 1.0
    assert dense["new_required_role_query_types"] == ["type-a", "type-b"]
    assert dense["selection_gate_pass"] is True
    assert select_allowed_treatment(result) == "A2_FTS_DENSE_UNION"


def test_comparison_reports_lost_groups_and_paired_global_deltas() -> None:
    baseline = [
        _case("a", query_type="type-a", refs={"ALL": ("gold-a",)}),
        _case("b", query_type="type-b", refs={"ALL": ()}),
    ]
    diagnostic = [
        _case("a", query_type="type-a", refs={"EVIDENCE_DENSE": ()}),
        _case("b", query_type="type-b", refs={"EVIDENCE_DENSE": ("gold-b",)}),
    ]

    result = compare_mechanisms(baseline, diagnostic)

    dense = result["A1_EVIDENCE_DENSE"]
    assert isinstance(dense, dict)
    assert dense["new_required_role_group_count"] == 1
    assert dense["lost_required_role_group_count"] == 1
    assert dense["acquired_exact_turn_recall_delta"] == 0.0
    assert dense["acquired_role_coverage_delta"] == 0.0
