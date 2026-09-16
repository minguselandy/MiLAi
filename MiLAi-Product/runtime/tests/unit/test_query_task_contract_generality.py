from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from milai.application.query_execution import derive_query_execution_plan_v01
from milai.application.query_task_compiler import (
    QueryTaskCompilerV01,
    project_query_task_contract_v01,
)
from milai.domain.query_execution import CompletionMode, CountSemantics
from milai.domain.query_task_contract import (
    CollectionClosureBasis,
    CollectionContractV01,
    CollectionKind,
    EvidenceRole,
    EvidenceSpeaker,
    EvidenceTopology,
    OutputContractV01,
    OutputShape,
    OutputValueType,
    ParseDisposition,
    ParticipantConstraintV01,
    ParticipantRole,
    ProofObligation,
    QueryOperation,
    QueryTaskContractV01,
    RequirementValueType,
    RetrievalHintsV01,
    SourceConstraintProvenance,
    SourceContractV01,
    SubjectContractV01,
    TemporalAxis,
    TemporalBoundary,
    TemporalContractV01,
    TemporalKind,
    TypedRequirementV01,
    ValueContractV01,
)


def _lookup_requirement(
    *,
    requirement_id: str = "answer",
    role_key: str = "answer",
    relation: str = "has_label",
    participants: tuple[ParticipantConstraintV01, ...] = (),
    source: SourceContractV01 | None = None,
) -> TypedRequirementV01:
    return TypedRequirementV01(
        requirement_id=requirement_id,
        role_key=role_key,
        evidence_role=EvidenceRole.ANSWER_VALUE,
        subject=SubjectContractV01(identity="requested_object"),
        relation=relation,
        participants=participants,
        value=ValueContractV01(value_type=RequirementValueType.TEXT),
        source=source or SourceContractV01(),
    )


def _lookup_contract(
    *,
    requirement: TypedRequirementV01 | None = None,
    hints: RetrievalHintsV01 | None = None,
    disposition: ParseDisposition = ParseDisposition.EXECUTABLE,
) -> QueryTaskContractV01:
    selected_requirement = requirement or _lookup_requirement()
    return QueryTaskContractV01(
        parse_disposition=disposition,
        operation=QueryOperation.LOOKUP,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.TEXT,
        ),
        evidence_topology=EvidenceTopology.SINGLE_ITEM,
        requirements=(selected_requirement,),
        proof_obligations=(ProofObligation.GROUNDED_RELATION,),
        retrieval_hints=((hints,) if hints is not None else ()),
        reason_code="GROUNDED_LOOKUP",
    )


def _member_count_contract(*, temporal: TemporalContractV01) -> QueryTaskContractV01:
    return QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COUNT,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.INTEGER,
        ),
        evidence_topology=EvidenceTopology.MEMBER_SET,
        requirements=(
            TypedRequirementV01(
                requirement_id="members",
                role_key="members",
                evidence_role=EvidenceRole.COLLECTION_MEMBER,
                subject=SubjectContractV01(identity="user"),
                relation="attended",
                participants=(
                    ParticipantConstraintV01(
                        role=ParticipantRole.EXPERIENCER,
                        identity="user",
                    ),
                ),
                value=ValueContractV01(value_type=RequirementValueType.ENTITY),
                temporal=temporal,
                collection=CollectionContractV01(
                    kind=CollectionKind.MEMBER_SET,
                    minimum=0,
                    maximum=None,
                    distinct=True,
                    identity_key="event_identity",
                    closure_basis=CollectionClosureBasis.QUERY_RANGE,
                ),
            ),
        ),
        proof_obligations=(
            ProofObligation.RANGE_CLOSURE,
            ProofObligation.IDENTITY_DEDUP,
        ),
        reason_code="COUNT_DISTINCT_RANGE_MEMBERS",
    )


def test_retrieval_wording_changes_do_not_change_operator_or_completion_semantics() -> None:
    english = _lookup_contract(
        hints=RetrievalHintsV01(
            requirement_id="answer",
            phrases=("folder label",),
            surface_terms=("folder", "label"),
            language_tags=("en",),
        )
    )
    multilingual = _lookup_contract(
        hints=RetrievalHintsV01(
            requirement_id="answer",
            phrases=("folder label", "文件夹标签"),
            surface_terms=("folder", "label", "文件夹", "标签"),
            language_tags=("en", "zh"),
        )
    )

    english_plan = derive_query_execution_plan_v01(english)
    multilingual_plan = derive_query_execution_plan_v01(multilingual)

    assert english_plan.operator.model_dump(exclude={"source_contract_digest"}) == (
        multilingual_plan.operator.model_dump(exclude={"source_contract_digest"})
    )
    assert english_plan.completion.model_dump(exclude={"source_contract_digest"}) == (
        multilingual_plan.completion.model_dump(exclude={"source_contract_digest"})
    )
    assert english_plan.binding.requirements == multilingual_plan.binding.requirements
    assert english_plan.acquisition.targets[0].retrieval_hints != (
        multilingual_plan.acquisition.targets[0].retrieval_hints
    )


def test_actor_identity_is_not_rewritten_when_evidence_speaker_policy_changes() -> None:
    actor = ParticipantConstraintV01(role=ParticipantRole.ACTOR, identity="user")
    unrestricted = _lookup_contract(
        requirement=_lookup_requirement(
            relation="performed_action",
            participants=(actor,),
        )
    )
    assistant_preferred = _lookup_contract(
        requirement=_lookup_requirement(
            relation="performed_action",
            participants=(actor,),
            source=SourceContractV01(
                preferred_speakers=(EvidenceSpeaker.ASSISTANT,),
                provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
            ),
        )
    )

    base_requirement = derive_query_execution_plan_v01(unrestricted).binding.requirements[0]
    sourced_requirement = derive_query_execution_plan_v01(assistant_preferred).binding.requirements[
        0
    ]

    assert base_requirement.participants == sourced_requirement.participants == (actor,)
    assert base_requirement.source.allowed_speakers is None
    assert sourced_requirement.source.allowed_speakers is None
    assert sourced_requirement.source.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)


def test_explicit_hard_source_policy_changes_admission_not_semantic_participants() -> None:
    actor = ParticipantConstraintV01(role=ParticipantRole.ACTOR, identity="user")
    soft = _lookup_requirement(
        relation="performed_action",
        participants=(actor,),
        source=SourceContractV01(
            preferred_speakers=(EvidenceSpeaker.ASSISTANT,),
            provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
        ),
    )
    hard = soft.model_copy(
        update={
            "source": SourceContractV01(
                preferred_speakers=(EvidenceSpeaker.ASSISTANT,),
                allowed_speakers=(EvidenceSpeaker.ASSISTANT,),
                provenance=SourceConstraintProvenance.EXPLICIT_QUERY,
            )
        }
    )

    assert soft.participants == hard.participants == (actor,)
    assert soft.source.allowed_speakers is None
    assert hard.source.allowed_speakers == (EvidenceSpeaker.ASSISTANT,)


def test_multi_operand_roles_remain_separate_through_every_execution_projection() -> None:
    left = _lookup_requirement(
        requirement_id="left-price",
        role_key="left",
        relation="left_item_price",
    ).model_copy(update={"evidence_role": EvidenceRole.LEFT_OPERAND})
    right = _lookup_requirement(
        requirement_id="right-price",
        role_key="right",
        relation="right_item_price",
    ).model_copy(update={"evidence_role": EvidenceRole.RIGHT_OPERAND})
    contract = QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.COMPARE,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.TEXT,
        ),
        evidence_topology=EvidenceTopology.MULTI_OPERAND,
        requirements=(left, right),
        proof_obligations=(ProofObligation.ALL_REQUIRED_ROLES,),
        retrieval_hints=(
            RetrievalHintsV01(
                requirement_id="left-price",
                phrases=("desk lamp price",),
            ),
            RetrievalHintsV01(
                requirement_id="right-price",
                phrases=("floor lamp price",),
            ),
        ),
        reason_code="COMPARE_INDEPENDENT_OPERANDS",
    )

    plan = derive_query_execution_plan_v01(contract)

    assert plan.operator.operand_role_keys == ("left", "right")
    assert [target.requirement.requirement_id for target in plan.acquisition.targets] == [
        "left-price",
        "right-price",
    ]
    assert [item.role_key for item in plan.binding.requirements] == ["left", "right"]
    assert plan.completion.required_role_keys == ("left", "right")
    assert plan.acquisition.targets[0].retrieval_hints != (
        plan.acquisition.targets[1].retrieval_hints
    )


def test_member_count_keeps_zero_semantics_and_local_calendar_across_dst() -> None:
    local_zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 1, tzinfo=local_zone)
    end = datetime(2026, 4, 1, tzinfo=local_zone)
    temporal = TemporalContractV01(
        kind=TemporalKind.RANGE,
        axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
        reference_time=datetime(2026, 4, 15, 9, tzinfo=local_zone),
        start=start,
        end=end,
        boundary=TemporalBoundary.CLOSED_OPEN,
        timezone="America/New_York",
    )

    plan = derive_query_execution_plan_v01(_member_count_contract(temporal=temporal))
    target = plan.acquisition.targets[0].requirement

    assert target.collection.minimum == 0
    assert target.collection.maximum is None
    assert target.temporal.start == start
    assert target.temporal.end == end
    assert target.temporal.start.utcoffset() != target.temporal.end.utcoffset()
    assert target.temporal.timezone == "America/New_York"
    assert plan.operator.count_semantics == CountSemantics.MEMBER_SET
    assert plan.completion.mode == CompletionMode.MEMBER_SET_CLOSED


def test_best_effort_lookup_is_executable_but_unsupported_has_no_plan() -> None:
    best_effort = _lookup_contract(disposition=ParseDisposition.BEST_EFFORT_RECALL)
    best_effort_plan = derive_query_execution_plan_v01(best_effort)
    unsupported = QueryTaskContractV01(
        parse_disposition=ParseDisposition.UNSUPPORTED,
        reason_code="UNSUPPORTED_OPERATION",
    )

    assert best_effort_plan.operator.operation == QueryOperation.LOOKUP
    assert best_effort_plan.completion.mode == CompletionMode.LOOKUP_READINESS
    assert best_effort_plan.completion.proof_obligations == (ProofObligation.GROUNDED_RELATION,)
    with pytest.raises(ValueError, match="no executable plan"):
        derive_query_execution_plan_v01(unsupported)


REFERENCE = datetime(2026, 4, 15, 9, tzinfo=ZoneInfo("America/New_York"))


def _compile(query: str) -> QueryTaskContractV01:
    return QueryTaskCompilerV01().compile(query, reference_time=REFERENCE)


def _semantic_shape(contract: QueryTaskContractV01) -> tuple[object, ...]:
    return (
        contract.parse_disposition,
        contract.operation,
        contract.output,
        contract.evidence_topology,
        tuple(
            (
                item.evidence_role,
                item.value.value_type,
                item.collection.kind,
                item.collection.minimum,
                item.collection.maximum,
                item.temporal.kind,
            )
            for item in contract.requirements
        ),
        frozenset(contract.proof_obligations),
    )


@pytest.mark.parametrize(
    ("identifier_query", "cardinality_query"),
    [
        (
            "What is the serial number of the telescope?",
            "How many telescopes are in storage?",
        ),
        (
            "Which tracking number belongs to the parcel?",
            "What is the number of parcels waiting for pickup?",
        ),
    ],
)
def test_identifier_and_cardinality_minimal_pairs_do_not_share_an_operator(
    identifier_query: str,
    cardinality_query: str,
) -> None:
    identifier = _compile(identifier_query)
    cardinality = _compile(cardinality_query)

    assert identifier.operation == QueryOperation.LOOKUP
    assert identifier.evidence_topology == EvidenceTopology.SINGLE_ITEM
    assert cardinality.operation == QueryOperation.COUNT
    assert cardinality.evidence_topology == EvidenceTopology.MEMBER_SET


def test_scalar_fact_count_and_member_set_count_have_distinct_zero_semantics() -> None:
    scalar = _compile("How many engineers do I lead?")
    members = _compile("How many parcels are waiting for pickup or return?")

    assert scalar.operation == members.operation == QueryOperation.COUNT
    assert scalar.evidence_topology == EvidenceTopology.SINGLE_ITEM
    assert scalar.requirements[0].collection.kind == CollectionKind.SCALAR_FACT
    assert scalar.requirements[0].collection.minimum == 1
    assert ProofObligation.IDENTITY_DEDUP not in scalar.proof_obligations

    assert members.evidence_topology == EvidenceTopology.MEMBER_SET
    assert members.requirements[0].collection.kind == CollectionKind.MEMBER_SET
    assert members.requirements[0].collection.minimum == 0
    assert members.requirements[0].collection.maximum is None
    assert members.requirements[0].collection.closure_basis == (
        CollectionClosureBasis.SOURCE_PARTITION
    )
    assert ProofObligation.IDENTITY_DEDUP in members.proof_obligations
    assert ProofObligation.PARTITION_CLOSURE in members.proof_obligations


def test_polite_and_direct_identifier_paraphrases_preserve_semantic_shape() -> None:
    queries = (
        "What is the serial number of the telescope?",
        "Which serial number belongs to the telescope?",
        "Please tell me the telescope serial number.",
    )

    contracts = tuple(_compile(query) for query in queries)

    assert all(item.parse_disposition == ParseDisposition.EXECUTABLE for item in contracts)
    assert len({_semantic_shape(item) for item in contracts}) == 1


def test_case_and_whitespace_variations_do_not_change_semantic_shape() -> None:
    queries = (
        "What is the serial number of the telescope?",
        "  What is the serial number of the telescope?  ",
        "WHAT IS THE SERIAL NUMBER OF THE TELESCOPE?",
        "What  is   the serial number of the telescope?",
    )

    assert len({_semantic_shape(_compile(query)) for query in queries}) == 1


def test_runtime_scope_changes_projection_only_not_semantic_contract_identity() -> None:
    query = "What is the serial number of the telescope?"
    contract = _compile(query)
    contract_digest = contract.contract_digest

    personal = project_query_task_contract_v01(
        contract,
        query=query,
        scope={"workspace": "personal"},
    )
    project = project_query_task_contract_v01(
        contract,
        query=query,
        scope={"workspace": "project"},
    )

    assert contract.contract_digest == contract_digest
    assert personal.constraints.scope == {"workspace": "personal"}
    assert project.constraints.scope == {"workspace": "project"}
    assert personal.requirements == project.requirements
    assert personal.lexical_cues == project.lexical_cues
    assert personal.steps == project.steps
    assert personal.completeness == project.completeness
    assert personal.planner_trace == project.planner_trace


@pytest.mark.parametrize(
    ("english", "chinese", "operation", "topology"),
    [
        (
            "What is the serial number of the telescope?",
            "望远镜的序列号是什么?",
            QueryOperation.LOOKUP,
            EvidenceTopology.SINGLE_ITEM,
        ),
        (
            "How many parcels are waiting for pickup?",
            "有多少个包裹在等待取件?",
            QueryOperation.COUNT,
            EvidenceTopology.MEMBER_SET,
        ),
    ],
)
def test_multilingual_paraphrases_preserve_operator_and_topology(
    english: str,
    chinese: str,
    operation: QueryOperation,
    topology: EvidenceTopology,
) -> None:
    contracts = (_compile(english), _compile(chinese))

    assert all(item.parse_disposition == ParseDisposition.EXECUTABLE for item in contracts)
    assert all(item.operation == operation for item in contracts)
    assert all(item.evidence_topology == topology for item in contracts)
    assert all(item.requirements for item in contracts)


def test_source_hint_does_not_invent_actor_binding_authority() -> None:
    contract = _compile("How many tasks did the assistant say I completed?")
    requirement = contract.requirements[0]

    assert requirement.participants == ()
    assert requirement.source.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)
    assert requirement.source.allowed_speakers is None
    assert requirement.source.provenance == (SourceConstraintProvenance.SEMANTIC_INTERPRETATION)


def test_assistant_source_is_soft_unless_the_query_explicitly_says_only() -> None:
    soft = _compile("What did the assistant say I completed?").requirements[0].source
    hard = (
        _compile("According only to what the assistant said: what activity did I complete?")
        .requirements[0]
        .source
    )

    assert soft.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)
    assert soft.allowed_speakers is None
    assert soft.provenance == SourceConstraintProvenance.SEMANTIC_INTERPRETATION
    assert hard.allowed_speakers == (EvidenceSpeaker.ASSISTANT,)
    assert hard.provenance == SourceConstraintProvenance.EXPLICIT_QUERY


def test_compiler_keeps_comparison_operands_lexically_and_semantically_separate() -> None:
    contract = _compile("Compare the desk lamp and the floor lamp.")
    by_role = {item.evidence_role: item for item in contract.requirements}
    hints = {item.requirement_id: item for item in contract.retrieval_hints}

    assert contract.operation == QueryOperation.COMPARE
    assert contract.evidence_topology == EvidenceTopology.MULTI_OPERAND
    assert set(by_role) == {
        EvidenceRole.LEFT_OPERAND,
        EvidenceRole.RIGHT_OPERAND,
    }
    left = by_role[EvidenceRole.LEFT_OPERAND]
    right = by_role[EvidenceRole.RIGHT_OPERAND]
    assert left.requirement_id != right.requirement_id
    assert left.role_key != right.role_key
    assert left.subject.surface_forms != right.subject.surface_forms
    assert hints[left.requirement_id].phrases != hints[right.requirement_id].phrases


@pytest.mark.parametrize(
    "query",
    [
        "Which happened first, I bought the bike or I repaired the car?",
        "How many days passed between when I bought the bike and when I repaired the car?",
    ],
)
def test_multi_event_operands_keep_distinct_requirements_and_retrieval_hints(
    query: str,
) -> None:
    contract = _compile(query)
    requirements = {item.role_key: item for item in contract.requirements}
    hints = {item.requirement_id: item for item in contract.retrieval_hints}

    assert contract.operation in {
        QueryOperation.TEMPORAL_ORDER,
        QueryOperation.TEMPORAL_DISTANCE,
    }
    assert contract.evidence_topology == EvidenceTopology.MULTI_OPERAND
    assert set(requirements) == {"EVENT_1", "EVENT_2"}
    first = requirements["EVENT_1"]
    second = requirements["EVENT_2"]
    assert first.requirement_id != second.requirement_id
    assert "bike" in first.subject.surface_forms
    assert "car" not in first.subject.surface_forms
    assert "car" in second.subject.surface_forms
    assert "bike" not in second.subject.surface_forms
    assert "bought" in hints[first.requirement_id].surface_terms
    assert "repaired" in hints[second.requirement_id].surface_terms
    assert hints[first.requirement_id].phrases != hints[second.requirement_id].phrases


def test_subordinate_action_remains_a_non_authoritative_retrieval_surface() -> None:
    contract = _compile(
        "How many workshops did I attend after visiting Paris last month?"
    )
    requirement = contract.requirements[0]
    hints = contract.retrieval_hints[0]

    assert contract.operation == QueryOperation.COUNT
    assert contract.evidence_topology == EvidenceTopology.MEMBER_SET
    assert requirement.evidence_role == EvidenceRole.COLLECTION_MEMBER
    assert requirement.subject.surface_forms == ("workshops",)
    assert requirement.collection.kind == CollectionKind.MEMBER_SET
    assert requirement.collection.closure_basis == CollectionClosureBasis.QUERY_RANGE
    assert hints.requirement_id == requirement.requirement_id
    assert {"attend", "visiting", "paris"}.issubset(hints.surface_terms)


def test_missed_event_query_plans_a_closed_member_set_without_status_authority() -> None:
    contract = _compile("How many workshops did I miss last month?")
    requirement = contract.requirements[0]
    hints = contract.retrieval_hints[0]

    assert contract.operation == QueryOperation.COUNT
    assert contract.evidence_topology == EvidenceTopology.MEMBER_SET
    assert requirement.evidence_role == EvidenceRole.COLLECTION_MEMBER
    assert requirement.subject.surface_forms == ("workshops",)
    assert requirement.collection.kind == CollectionKind.MEMBER_SET
    assert requirement.collection.closure_basis == CollectionClosureBasis.QUERY_RANGE
    assert ProofObligation.RANGE_CLOSURE in contract.proof_obligations
    assert hints.requirement_id == requirement.requirement_id
    assert "miss" in hints.surface_terms


def test_calendar_month_is_resolved_as_local_closed_open_range_across_dst() -> None:
    contract = _compile("How many workshops did I attend in March 2026?")
    temporal = contract.requirements[0].temporal

    assert temporal.kind == TemporalKind.RANGE
    assert temporal.axis == TemporalAxis.EVENT_OCCURRENCE_TIME
    assert temporal.boundary == TemporalBoundary.CLOSED_OPEN
    assert temporal.timezone == "America/New_York"
    assert temporal.start == datetime(
        2026,
        3,
        1,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert temporal.end == datetime(
        2026,
        4,
        1,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert temporal.start.utcoffset() != temporal.end.utcoffset()


def test_singular_last_month_is_previous_local_calendar_not_rolling_window() -> None:
    contract = _compile("How many workshops did I attend last month?")
    temporal = contract.requirements[0].temporal

    assert temporal.kind == TemporalKind.RANGE
    assert temporal.start == datetime(
        2026,
        3,
        1,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert temporal.end == datetime(
        2026,
        4,
        1,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert temporal.timezone == "America/New_York"


def test_past_month_remains_a_rolling_interval() -> None:
    contract = _compile("How many workshops did I attend in the past month?")
    temporal = contract.requirements[0].temporal

    assert temporal.start == datetime(
        2026,
        3,
        15,
        9,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert temporal.end == REFERENCE


@pytest.mark.parametrize(
    "query",
    [
        "Only use my messages: what is the access code?",
        "只用我的消息:访问码是什么?",
    ],
)
def test_explicit_only_source_wording_is_a_hard_admission_constraint(query: str) -> None:
    source = _compile(query).requirements[0].source

    assert source.allowed_speakers == (EvidenceSpeaker.USER,)
    assert source.preferred_speakers == ()
    assert source.provenance == SourceConstraintProvenance.EXPLICIT_QUERY


def test_historical_assistant_recommendation_is_source_recall_not_preference_resolution() -> None:
    contract = _compile("What did you recommend for the picnic?")

    assert contract.operation == QueryOperation.LOOKUP
    assert contract.evidence_topology == EvidenceTopology.SINGLE_ITEM
    assert contract.requirements[0].source.preferred_speakers == (
        EvidenceSpeaker.ASSISTANT,
    )


def test_lookup_keeps_full_retrieval_surface_without_making_it_binding_truth() -> None:
    contract = _compile(
        "I'm planning my trip again; what phone number did you provide earlier "
        "for the Speyer tourism board?"
    )
    requirement = contract.requirements[0]
    hints = contract.retrieval_hints[0]

    assert contract.operation == QueryOperation.LOOKUP
    assert requirement.source.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)
    assert set(requirement.subject.surface_forms) == {
        "trip",
        "speyer",
        "tourism",
        "board",
    }
    assert {"phone", "number", "provide", "earlier"}.issubset(hints.surface_terms)


def test_unsegmented_chinese_lookup_does_not_invent_a_hard_entity_bag() -> None:
    contract = _compile("我之前提到的访问码是什么?")

    assert contract.operation == QueryOperation.LOOKUP
    assert contract.requirements[0].subject.surface_forms == ()
    assert contract.retrieval_hints[0].surface_terms


def test_assistant_reported_collection_keeps_count_operation() -> None:
    contract = _compile("How many tasks did the assistant say I completed?")

    assert contract.operation == QueryOperation.COUNT
    assert contract.evidence_topology == EvidenceTopology.MEMBER_SET
    assert contract.requirements[0].source.preferred_speakers == (
        EvidenceSpeaker.ASSISTANT,
    )


def test_chinese_embedded_count_extracts_the_member_subject() -> None:
    contract = _compile("我还需要归还多少本图书?")

    assert contract.parse_disposition == ParseDisposition.EXECUTABLE
    assert contract.operation == QueryOperation.COUNT
    assert contract.evidence_topology == EvidenceTopology.MEMBER_SET
    assert contract.requirements[0].subject.surface_forms == ("图书",)
    assert ProofObligation.PARTITION_CLOSURE in contract.proof_obligations


@pytest.mark.parametrize(
    "query",
    [
        '"How many" was written in the note; what is the note title?',
        "Do not count the receipts; what is the receipt folder's label?",
    ],
)
def test_quoted_or_negated_operator_cues_do_not_activate_count(query: str) -> None:
    contract = _compile(query)

    assert contract.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL
    assert contract.operation == QueryOperation.LOOKUP
    assert contract.evidence_topology == EvidenceTopology.SINGLE_ITEM
    assert contract.proof_obligations == (ProofObligation.GROUNDED_RELATION,)


def test_unknown_memory_computation_still_reaches_best_effort_reader_recall() -> None:
    recall = _compile("Tell me about the blue folder.")
    computation = _compile("Compute the median of every numeric value in memory.")

    assert recall.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL
    assert recall.operation == QueryOperation.LOOKUP
    assert recall.requirements
    assert recall.proof_obligations == (ProofObligation.GROUNDED_RELATION,)

    assert computation.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL
    assert computation.operation == QueryOperation.LOOKUP
    assert computation.requirements
    assert computation.proof_obligations == (ProofObligation.GROUNDED_RELATION,)
