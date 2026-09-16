from __future__ import annotations

from milai.application.recall_workspace import RecallCandidate, marginal_evidence_order


def _candidate(
    candidate_id: str,
    *,
    targets: tuple[str, ...],
    rank: int,
    session: str,
    terms: frozenset[str],
    tokens: int = 100,
) -> RecallCandidate:
    return RecallCandidate(
        candidate_id=candidate_id,
        evidence_ids=(f"e-{candidate_id}",),
        session_id=session,
        region_ids=(f"{session}:r{rank}",),
        channel_ids=("FTS_RAW",),
        target_hints=targets,
        semantic_terms=terms,
        base_rank=rank,
        query_overlap=len(targets),
        answer_signal=True,
        estimated_tokens=tokens,
    )


def test_soft_target_frontier_promotes_uncovered_hint_and_retains_backbone() -> None:
    candidates = (
        _candidate(
            "parents",
            targets=("age", "parents"),
            rank=1,
            session="s1",
            terms=frozenset({"age", "parents", "fifty"}),
        ),
        _candidate(
            "age-distractor",
            targets=("age",),
            rank=2,
            session="s2",
            terms=frozenset({"age", "equipment", "history"}),
        ),
        _candidate(
            "grandparents",
            targets=("grandparents",),
            rank=3,
            session="s3",
            terms=frozenset({"grandparents", "grandma", "grandpa"}),
            tokens=300,
        ),
    )

    selected = marginal_evidence_order(
        "average age of parents and grandparents",
        ("age", "parents", "grandparents"),
        candidates,
    )

    assert selected.ordered_candidate_ids == (
        "parents",
        "grandparents",
        "age-distractor",
    )
    assert selected.promoted_candidate_ids == ("grandparents",)
    assert set(selected.ordered_candidate_ids) == {
        item.candidate_id for item in candidates
    }
    assert selected.workspace.uncovered_target_hints == ()


def test_soft_target_frontier_falls_back_to_original_order_without_gain() -> None:
    candidates = (
        _candidate(
            "anchor",
            targets=("project",),
            rank=1,
            session="s1",
            terms=frozenset({"project", "analysis"}),
        ),
        _candidate(
            "implicit-member",
            targets=(),
            rank=2,
            session="s2",
            terms=frozenset({"competition", "presentation"}),
        ),
    )

    selected = marginal_evidence_order(
        "projects I led",
        ("projects", "led"),
        candidates,
    )

    assert selected.ordered_candidate_ids == ("anchor", "implicit-member")
    assert selected.promoted_candidate_ids == ()
    assert selected.workspace.uncovered_target_hints == ("projects", "led")

