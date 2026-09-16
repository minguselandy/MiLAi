"""Compile a query-local execution plan before projecting the public v0.2 DTO.

``QueryTaskContractV01`` describes the requested operation, answer shape,
explicit constraints, and retrieval hints.  It is not proof that a span of Raw
natural language bears a particular semantic relation.  The existing
``MemoryQueryIRV02`` remains the public/executor compatibility shape.
"""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal, cast

from pydantic import JsonValue

from milai.application.current_intent import has_explicit_current_intent
from milai.domain.memory_query_ir import EvidenceRequirement as LegacyRequirement
from milai.domain.memory_query_ir import MemoryQueryIR as LegacyMemoryQueryIR
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
    QueryReferenceTimeOperandV01,
    QueryTaskContractV01,
    RequirementBindingOperandV01,
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
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    EvidenceSourcePolicyV02,
    InterpretationKind,
    LexicalCueSetV01,
    MemoryAnswerShape,
    MemoryCompletenessV02,
    MemoryPlannerTrace,
    MemoryQueryConstraints,
    MemoryQueryIRV02,
    MemoryQueryStep,
    NormalizedTemporalConstraint,
    QueryCueSpan,
    RequirementCardinalityV02,
    RequirementSemanticRolesV02,
    SemanticRoute,
)
from milai.domain.semantic_query import (
    EvidenceSourceProvenance as V02SourceProvenance,
)
from milai.domain.semantic_query import EvidenceSourceSpeaker as V02SourceSpeaker

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_FIRST_PERSON = re.compile(r"\b(?:i|me|my|mine|we|us|our|ours)\b", re.IGNORECASE)
_QUOTED_TEXT = re.compile(
    r"(?:\"(?P<double>[^\"]+)\"|'(?P<single>[^']+)'|"
    r"\u201c(?P<curly_double>[^\u201d]+)\u201d|"
    r"\u2018(?P<curly_single>[^\u2019]+)\u2019)"
)
_OPERATOR_LANGUAGE = re.compile(
    r"\b(?:how\s+many|count|sum|average|compare|timeline)\b|"
    r"(?:多少|计数|总和|平均|比较|时间线)",
    re.IGNORECASE,
)
_IDENTIFIER_ATTRIBUTE = re.compile(
    r"\b(?:identifier|id|code|number)\b(?!\s+of\b)",
    re.IGNORECASE,
)
_EXPLICIT_SOURCE = re.compile(
    r"^\s*(?P<mode>according\s+only\s+to|only\s+(?:use|consider)|"
    r"use\s+only|prefer(?:\s+using)?)\s+"
    r"(?P<speaker>what\s+i\s+said|my\s+messages|assistant\s+messages|"
    r"what\s+the\s+assistant\s+said)\s*[:,]\s*",
    re.IGNORECASE,
)
_EXPLICIT_SOURCE_ZH = re.compile(
    r"^\s*(?P<mode>只根据|只使用|只用|优先使用)"
    r"(?P<speaker>我说的|我的消息|助手说的|助手消息)\s*[\uff0c,:\uff1a]\s*"
)
_NATURAL_ASSISTANT_SOURCE = re.compile(
    r"\bwhat\s+did\s+(?:you|the\s+assistant)\s+(?:say|tell|recommend|suggest|answer)\b|"
    r"\bwhat\b[^?]{0,80}\b(?:you|the\s+assistant)\s+"
    r"(?:provide|share|give|send|provided|shared|gave|sent|recommended|suggested)"
    r"(?:\s+me)?\b|"
    r"\b(?:the\s+assistant|you)\s+"
    r"(?:say|tell|report|state|mention|provide|share|"
    r"said|told|reported|stated|mentioned|provided|shared)\b|"
    r"(?:你|助手)(?:之前|先前)?(?:说|告诉|建议|回答)(?:了)?什么",
    re.IGNORECASE,
)
_NATURAL_USER_SOURCE = re.compile(
    r"\bwhat\s+did\s+i\s+(?:say|tell|ask|mention)\b|"
    r"我(?:之前|先前)?(?:说|提到|问)(?:了)?什么",
    re.IGNORECASE,
)
_RELATIVE_POINT = re.compile(
    r"\b(?P<count>a\s+couple\s+of|couple\s+of|a|an|one|two|three|four|five|"
    r"six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?|years?)\s+ago\b",
    re.IGNORECASE,
)
_RELATIVE_RANGE = re.compile(
    r"\b(?:in|during|over|within|for)?\s*(?:the\s+)?(?P<window>past|last)\s+"
    r"(?:(?P<count>a\s+couple\s+of|couple\s+of|a|an|one|two|three|four|five|"
    r"six|seven|eight|nine|ten|few|several|\d+)\s+)?"
    r"(?P<unit>days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_CALENDAR_MONTH = re.compile(
    r"\b(?:in|during)\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b(?:\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_LAST_WEEKEND = re.compile(r"\blast weekend\b", re.IGNORECASE)
_SOURCE_TIME_REPORTING = re.compile(
    r"\b(?:said|told|asked|mentioned|discussed|wrote|shared|messaged|"
    r"talked\s+about|spoke\s+about)\b|(?:说|告诉|问|提到|讨论|写|分享|消息)",
    re.IGNORECASE,
)
_BINARY_BETWEEN = re.compile(
    r"\bbetween\s+(?P<left>.+?)\s+and\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_BINARY_COMPARE = re.compile(
    r"\bcompare\s+(?P<left>.+?)\s+(?:and|with|to)\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_BINARY_OR = re.compile(
    r"\b(?:which|what|who)\b.+?\b(?:first|earlier)\s*,?\s*"
    r"(?P<left>.+?)\s+or\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_COUNT_MEMBER_SUBJECT = re.compile(
    r"\bhow\s+many\s+(?P<subject>.+?)\s+"
    r"(?:do|did|are|were|have|has|need|must|should|can|could|will|would)\b",
    re.IGNORECASE,
)
_COUNT_MEMBER_SUBJECT_ZH = re.compile(
    r"(?:有)?多少(?:个|件|次|位|只|辆|本|场)?"
    r"(?P<subject>[\u3400-\u9fff]{1,24}?)(?:在|要|需要|已经|仍|还|\?|\uff1f|$)"
)
_COUNT_MEMBER_OBJECT_ZH = re.compile(
    r"多少(?:个|件|次|位|只|辆|本|场)?"
    r"(?P<subject>[\u3400-\u9fff]{1,24}?)(?:\?|\uff1f|$)"
)
_QUESTION_PREFIX = re.compile(
    r"^\s*(?:what|which|who|where|when|why|how\s+many|how\s+much|how\s+long|"
    r"can|could|did|do|does|has|have|is|are|was|were|will|would|"
    r"什么|哪个|哪一个|谁|哪里|何时|为什么|多少|是否)\b\s*",
    re.IGNORECASE,
)
_GRAMMAR_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "can",
        "could",
        "did",
        "do",
        "does",
        "each",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "per",
        "the",
        "there",
        "that",
        "these",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "you",
        "your",
    }
)
_LOOKUP_NON_SUBJECT_TERMS = _GRAMMAR_WORDS.union(
    {
        # Requested value/attribute words are part of the retrieval surface,
        # not necessarily the entity that owns the answer.
        "amount",
        "code",
        "color",
        "colour",
        "date",
        "identifier",
        "name",
        "number",
        "password",
        "phone",
        "speed",
        "time",
        # Conversational/source and recency wording describes how the user is
        # asking, not what the remembered subject is.  Keeping it as a hard
        # Binding entity made long natural questions require near-verbatim
        # evidence.  All terms remain available in RetrievalHintsV01.
        "again",
        "already",
        "answer",
        "answered",
        "confirm",
        "earlier",
        "gave",
        "give",
        "given",
        "mentioned",
        "planning",
        "previously",
        "provide",
        "provided",
        "recall",
        "recommend",
        "recommended",
        "remember",
        "said",
        "sent",
        "shared",
        "suggest",
        "suggested",
        "tell",
        "told",
        "wanted",
        "want",
    }
)
_NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "a couple of": 2,
    "couple of": 2,
    "few": 3,
    "several": 4,
}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_OPERATION = {
    "LOOKUP": QueryOperation.LOOKUP,
    "STATE_AT_TIME": QueryOperation.STATE_AS_OF,
    "TEMPORAL_FILTER": QueryOperation.TEMPORAL_FILTER,
    "TEMPORAL_ORDER": QueryOperation.TEMPORAL_ORDER,
    "TEMPORAL_DISTANCE": QueryOperation.TEMPORAL_DISTANCE,
    "COUNT_DISTINCT": QueryOperation.COUNT,
    "SUM_VALUES": QueryOperation.SUM,
    "DIVIDE_VALUES": QueryOperation.DIVIDE,
    "COMPARE_VALUES": QueryOperation.COMPARE,
    "MULTI_EVIDENCE_JOIN": QueryOperation.MULTI_JOIN,
    "PREFERENCE_RESOLVE": QueryOperation.PREFERENCE_RESOLVE,
    "VERSION_DIFF": QueryOperation.VERSION_DIFF,
}
_OPERATOR_FAMILY = {
    QueryOperation.LOOKUP: "LOOKUP",
    QueryOperation.COLLECT_SET: "LOOKUP",
    QueryOperation.COUNT: "COUNT",
    QueryOperation.SUM: "SUM",
    QueryOperation.DIVIDE: "DIVIDE",
    QueryOperation.COMPARE: "COMPARE",
    QueryOperation.TEMPORAL_FILTER: "TEMPORAL_FILTER",
    QueryOperation.TEMPORAL_ORDER: "TEMPORAL_ORDER",
    QueryOperation.TEMPORAL_DISTANCE: "TEMPORAL_DISTANCE",
    QueryOperation.MULTI_JOIN: "MULTI_JOIN",
    QueryOperation.PREFERENCE_RESOLVE: "PREFERENCE_RESOLVE",
    QueryOperation.STATE_AS_OF: "LOOKUP",
    QueryOperation.VERSION_DIFF: "WHY_CHANGE",
}


class QueryTaskCompilerV01:
    """Compile an authoritative plan without claiming Raw-language truth."""

    VERSION = "query-task-contract-compiler-v0.1"

    def __init__(self, *, preference_current_intent_enabled: bool = True) -> None:
        self._preference_current_intent_enabled = preference_current_intent_enabled

    def compile(
        self,
        query: str,
        *,
        reference_time: datetime,
        legacy_spec: LegacyMemoryQueryIR | None = None,
    ) -> QueryTaskContractV01:
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("reference_time must include a timezone offset")
        source, semantic_query = _source_contract(query)
        if not semantic_query.strip():
            return QueryTaskContractV01(
                parse_disposition=ParseDisposition.UNSUPPORTED,
                reason_code="EMPTY_QUERY",
            )
        if _quoted_operator_metalinguistic(semantic_query):
            return _best_effort_contract(
                semantic_query,
                source=source,
                reason="BEST_EFFORT:METALINGUISTIC_OPERATOR_QUOTE",
            )
        if legacy_spec is None:
            # Local import avoids making the compatibility parser an import-time
            # dependency of the planning contract or creating a module cycle.
            from milai.application.memory_query import MemoryQueryCompiler

            legacy_spec = MemoryQueryCompiler(
                preference_current_intent_enabled=False
            ).compile_v01(semantic_query, reference_time=reference_time)
        if legacy_spec.parser.kind == "AMBIGUOUS":
            if _IDENTIFIER_ATTRIBUTE.search(semantic_query):
                return _lookup_contract(
                    semantic_query,
                    source=source,
                    disposition=ParseDisposition.EXECUTABLE,
                    reason=f"NORMALIZED_IDENTIFIER_LOOKUP:{legacy_spec.parser.reason_code}",
                    value_type=RequirementValueType.TEXT,
                )
            return _best_effort_contract(
                semantic_query,
                source=source,
                reason=f"BEST_EFFORT:{legacy_spec.parser.reason_code}",
            )
        if (
            legacy_spec.operator == "PREFERENCE_RESOLVE"
            and source.provenance == SourceConstraintProvenance.SEMANTIC_INTERPRETATION
            and source.preferred_speakers == (EvidenceSpeaker.ASSISTANT,)
            and _NATURAL_ASSISTANT_SOURCE.search(semantic_query)
        ):
            # A question about an earlier assistant utterance is historical
            # source-role recall, even when its content contains words such as
            # "recommend" that the legacy frontend also uses for preferences.
            # Other operators (for example COUNT over assistant-reported
            # events) retain their semantic operation and merely prefer that
            # evidence source.
            return _lookup_contract(
                semantic_query,
                source=source,
                disposition=ParseDisposition.EXECUTABLE,
                reason="NORMALIZED_ASSISTANT_UTTERANCE_RECALL",
            )
        return self._from_legacy(
            legacy_spec,
            query=semantic_query,
            reference_time=reference_time,
            source=source,
        )

    def compile_to_v02(
        self,
        query: str,
        *,
        reference_time: datetime,
        scope: Mapping[str, JsonValue] | None = None,
    ) -> MemoryQueryIRV02:
        contract = self.compile(query, reference_time=reference_time)
        return project_query_task_contract_v01(contract, query=query, scope=scope)

    def _from_legacy(
        self,
        legacy: LegacyMemoryQueryIR,
        *,
        query: str,
        reference_time: datetime,
        source: SourceContractV01,
    ) -> QueryTaskContractV01:
        operation = _OPERATION[legacy.operator]
        if (
            operation == QueryOperation.LOOKUP
            and legacy.query_class == "STATE"
            and any(
                "current_state" in item.predicate_constraints
                for item in legacy.requirements
            )
        ):
            operation = QueryOperation.STATE_AS_OF
        global_temporal = _temporal_contract(query, reference_time, operation)
        requirements = _requirements(
            legacy,
            query=query,
            operation=operation,
            source=source,
            global_temporal=global_temporal,
        )
        if (
            self._preference_current_intent_enabled
            and operation == QueryOperation.PREFERENCE_RESOLVE
            and has_explicit_current_intent(query)
        ):
            shared_subject_terms = next(
                (
                    item.subject.surface_forms
                    for item in requirements
                    if item.subject.surface_forms
                ),
                (),
            )
            requirements = (
                *requirements,
                _current_intent_requirement(
                    source,
                    subject_terms=shared_subject_terms,
                ),
            )
        requirements = _relate_temporal_operands(requirements, operation, reference_time)
        operator_operands = _operator_operands(operation, requirements, reference_time)
        hints = _retrieval_hints(legacy, requirements, query)
        reason = f"NORMALIZED:{legacy.parser.reason_code}"
        if any(item.role_key == "CURRENT_INTENT" for item in requirements):
            reason = f"{reason}+CURRENT_INTENT_EXPLICIT"
        return QueryTaskContractV01(
            parse_disposition=ParseDisposition.EXECUTABLE,
            operation=operation,
            output=_output_contract(legacy, operation),
            evidence_topology=_topology(operation, requirements),
            requirements=requirements,
            operator_operands=operator_operands,
            proof_obligations=_proof_obligations(operation, requirements, global_temporal),
            retrieval_hints=hints,
            reason_code=reason,
        )


def project_query_task_contract_v01(
    contract: QueryTaskContractV01,
    *,
    query: str,
    scope: Mapping[str, JsonValue] | None = None,
) -> MemoryQueryIRV02:
    """Project the internal task plan into the existing public v0.2 envelope.

    Planning details remain in ``contract``; neither shape is semantic proof
    about Raw Evidence.  The projection uses existing executor vocabulary and
    never invents a wider permission or capability.
    """

    if contract.parse_disposition == ParseDisposition.UNSUPPORTED:
        return MemoryQueryIRV02(
            mode="AMBIGUOUS",
            answer_shape="STATE",
            constraints=MemoryQueryConstraints(scope=dict(scope) if scope else None),
            requirements=[],
            lexical_cues=[],
            steps=[],
            completeness="UNSTRUCTURED_EVIDENCE_ALLOWED",
            planner_trace=MemoryPlannerTrace(
                source="AMBIGUOUS",
                compiler_version=QueryTaskCompilerV01.VERSION,
                auxiliary_model_calls=0,
                reason_code=f"QUERY_TASK_CONTRACT:{contract.reason_code}",
            ),
        )
    assert contract.operation is not None
    assert contract.output is not None
    requirements = [
        _project_requirement(item, contract.operation) for item in contract.requirements
    ]
    hint_by_id = {item.requirement_id: item for item in contract.retrieval_hints}
    lexical_cues = [
        _project_hint(item, hint_by_id.get(item.requirement_id))
        for item in contract.requirements
    ]
    normalized_temporal = _project_global_temporal(contract.requirements)
    return MemoryQueryIRV02(
        mode=_project_mode(contract),
        answer_shape=_project_answer_shape(contract.output.shape),
        constraints=MemoryQueryConstraints(
            cue_spans=_query_cue_spans(query, contract.retrieval_hints),
            temporal_expressions=_temporal_cue_spans(query),
            normalized_temporal=normalized_temporal,
            scope=dict(scope) if scope else None,
        ),
        requirements=requirements,
        lexical_cues=lexical_cues,
        steps=_project_steps(contract, requirements, normalized_temporal),
        completeness=_project_completeness(contract),
        planner_trace=MemoryPlannerTrace(
            source="DETERMINISTIC",
            compiler_version=QueryTaskCompilerV01.VERSION,
            auxiliary_model_calls=0,
            reason_code=f"QUERY_TASK_CONTRACT:{contract.reason_code}",
        ),
    )


def _best_effort_contract(
    query: str,
    *,
    source: SourceContractV01,
    reason: str,
) -> QueryTaskContractV01:
    return _lookup_contract(
        query,
        source=source,
        disposition=ParseDisposition.BEST_EFFORT_RECALL,
        reason=reason,
    )


def _lookup_contract(
    query: str,
    *,
    source: SourceContractV01,
    disposition: ParseDisposition,
    reason: str,
    value_type: RequirementValueType = RequirementValueType.ANY,
) -> QueryTaskContractV01:
    requirement_id = "requirement:1:lookup-answer"
    terms = _surface_terms(query)
    subject_terms = _lookup_subject_terms(query)
    requirement = TypedRequirementV01(
        requirement_id=requirement_id,
        role_key="LOOKUP_ANSWER",
        evidence_role=EvidenceRole.ANSWER_VALUE,
        subject=_subject(subject_terms),
        relation=_relation_description(query),
        participants=(),
        value=ValueContractV01(value_type=value_type),
        source=source,
    )
    return QueryTaskContractV01(
        parse_disposition=disposition,
        operation=QueryOperation.LOOKUP,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=(
                OutputValueType.TEXT
                if value_type == RequirementValueType.TEXT
                else OutputValueType.ANY
            ),
        ),
        evidence_topology=EvidenceTopology.SINGLE_ITEM,
        requirements=(requirement,),
        proof_obligations=(ProofObligation.GROUNDED_RELATION,),
        retrieval_hints=(
            RetrievalHintsV01(
                requirement_id=requirement_id,
                phrases=(query.strip(),),
                surface_terms=terms,
                language_tags=_language_tags(query),
            ),
        ),
        reason_code=reason,
    )


def _requirements(
    legacy: LegacyMemoryQueryIR,
    *,
    query: str,
    operation: QueryOperation,
    source: SourceContractV01,
    global_temporal: TemporalContractV01,
) -> tuple[TypedRequirementV01, ...]:
    if operation == QueryOperation.VERSION_DIFF:
        return _version_requirements(legacy, query, source)
    operands = _binary_operands(query) if operation in {
        QueryOperation.COMPARE,
        QueryOperation.TEMPORAL_ORDER,
        QueryOperation.TEMPORAL_DISTANCE,
    } else None
    legacy_subjects = tuple(
        _semantic_subject_terms(tuple(item.entity_constraints))
        for item in legacy.requirements
    )
    result: list[TypedRequirementV01] = []
    for index, legacy_requirement in enumerate(legacy.requirements):
        role = _evidence_role(operation, index, legacy_requirement)
        role_key = _role_key(operation, index, legacy_requirement)
        identifier = f"requirement:{index + 1}:{_slug(role_key)}"
        terms = tuple(legacy_requirement.entity_constraints)
        if (
            operands is not None
            and index < len(operands)
            and (
                not _semantic_subject_terms(terms)
                or legacy_subjects.count(_semantic_subject_terms(terms)) > 1
            )
        ):
            # The deterministic frontend already isolates requirement-local
            # anchors when it can do so confidently.  Replacing them with the
            # complete operand phrase turns descriptive wording into hard
            # semantic constraints (for example ``participation`` versus the
            # grounded verb ``participated``).  Operand text remains available
            # in RetrievalHints; it is only a subject fallback here.
            operand_terms = _surface_terms(operands[index])
            if operand_terms:
                terms = operand_terms
        collection = _collection_contract(operation, legacy_requirement, global_temporal)
        temporal = _requirement_temporal(operation, global_temporal, legacy_requirement)
        relation = _requirement_relation(operation, role, legacy_requirement, query)
        if role == EvidenceRole.COLLECTION_MEMBER:
            semantic_terms = (
                _count_member_subject_terms(query)
                or _semantic_subject_terms(terms)
            )
        elif role == EvidenceRole.EVENT:
            # Event operands are already isolated by the legacy grammar or by
            # the binary-operand extractor.  They are not the global query bag.
            semantic_terms = _semantic_subject_terms(terms)
        elif operation in {QueryOperation.LOOKUP, QueryOperation.STATE_AS_OF}:
            semantic_terms = _lookup_subject_terms(query)
        else:
            semantic_terms = _semantic_subject_terms(terms)
        participants: tuple[ParticipantConstraintV01, ...] = ()
        if (
            not participants
            and "user_fact" in legacy_requirement.predicate_constraints
            and _FIRST_PERSON.search(query)
        ):
            # ``user_fact`` identifies the semantic subject of the remembered
            # state.  It is deliberately not a source-speaker restriction:
            # assistant or tool Evidence may still report a state about the
            # user.  The public V02 compatibility DTO cannot safely encode this
            # abstract query-local identity, so consumers use the plan metadata.
            participants = (
                ParticipantConstraintV01(
                    role=ParticipantRole.EXPERIENCER,
                    identity="QUERY_SUBJECT",
                ),
            )
        subject_identity = (
            "QUERY_SUBJECT"
            if "user_fact" in legacy_requirement.predicate_constraints
            and _FIRST_PERSON.search(query)
            else None
        )
        result.append(
            TypedRequirementV01(
                requirement_id=identifier,
                role_key=role_key,
                evidence_role=role,
                subject=_subject(semantic_terms, identity=subject_identity),
                relation=relation,
                participants=participants,
                value=ValueContractV01(
                    value_type=_requirement_value_type(legacy_requirement)
                ),
                temporal=temporal,
                source=source,
                collection=collection,
                required=legacy_requirement.required,
            )
        )
    return tuple(result)


def _version_requirements(
    legacy: LegacyMemoryQueryIR,
    query: str,
    source: SourceContractV01,
) -> tuple[TypedRequirementV01, ...]:
    terms = _semantic_subject_terms(tuple(legacy.entities))
    hints = _subject(terms)
    roles = (
        ("PRIOR_STATE", EvidenceRole.PRIOR_STATE, "prior_state"),
        ("CURRENT_STATE", EvidenceRole.CURRENT_STATE, "current_state"),
        ("TRANSITION", EvidenceRole.TRANSITION, "state_transition"),
    )
    return tuple(
        TypedRequirementV01(
            requirement_id=f"requirement:{index + 1}:{_slug(role_key)}",
            role_key=role_key,
            evidence_role=role,
            subject=hints,
            relation=relation,
            participants=(),
            value=ValueContractV01(value_type=RequirementValueType.STATE),
            temporal=TemporalContractV01(
                kind=(
                    TemporalKind.CURRENT
                    if role == EvidenceRole.CURRENT_STATE
                    else TemporalKind.NONE
                ),
                axis=TemporalAxis.VALID_TIME if role == EvidenceRole.CURRENT_STATE else None,
                reference_time=(
                    legacy.temporal.reference_time
                    if role == EvidenceRole.CURRENT_STATE
                    else None
                ),
                timezone=(
                    _timezone_name(legacy.temporal.reference_time)
                    if role == EvidenceRole.CURRENT_STATE
                    and legacy.temporal.reference_time is not None
                    else None
                ),
            ),
            source=source,
        )
        for index, (role_key, role, relation) in enumerate(roles)
    )


def _current_intent_requirement(
    source: SourceContractV01,
    *,
    subject_terms: Sequence[str],
) -> TypedRequirementV01:
    return TypedRequirementV01(
        requirement_id="requirement:current-intent",
        role_key="CURRENT_INTENT",
        evidence_role=EvidenceRole.CURRENT_STATE,
        subject=_subject(
            subject_terms,
            identity="QUERY_SUBJECT",
        ),
        relation="current_intent",
        participants=(
            ParticipantConstraintV01(
                role=ParticipantRole.EXPERIENCER,
                identity="QUERY_SUBJECT",
            ),
        ),
        value=ValueContractV01(value_type=RequirementValueType.TEXT),
        temporal=TemporalContractV01(
            kind=TemporalKind.CURRENT,
            axis=TemporalAxis.VALID_TIME,
            reference_time=None,
            timezone=None,
        ),
        source=source,
    )


def _relate_temporal_operands(
    requirements: tuple[TypedRequirementV01, ...],
    operation: QueryOperation,
    reference_time: datetime,
) -> tuple[TypedRequirementV01, ...]:
    if operation not in {QueryOperation.TEMPORAL_ORDER, QueryOperation.TEMPORAL_DISTANCE}:
        return requirements
    identities = tuple(item.requirement_id for item in requirements if item.required)
    if len(identities) < 2:
        return requirements
    temporal = TemporalContractV01(
        kind=TemporalKind.RELATION,
        axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
        reference_time=reference_time,
        timezone=_timezone_name(reference_time),
        related_requirement_ids=identities,
    )
    return tuple(item.model_copy(update={"temporal": temporal}) for item in requirements)


def _operator_operands(
    operation: QueryOperation,
    requirements: Sequence[TypedRequirementV01],
    reference_time: datetime,
) -> tuple[RequirementBindingOperandV01 | QueryReferenceTimeOperandV01, ...]:
    """Declare operator inputs without turning runtime values into Evidence roles."""

    if operation != QueryOperation.TEMPORAL_DISTANCE:
        return ()
    event_requirements = tuple(
        item
        for item in requirements
        if item.required and item.evidence_role == EvidenceRole.EVENT
    )
    operands: list[RequirementBindingOperandV01 | QueryReferenceTimeOperandV01] = [
        RequirementBindingOperandV01(
            operand_id=f"operand:{item.role_key.casefold()}",
            requirement_id=item.requirement_id,
        )
        for item in event_requirements
    ]
    if len(event_requirements) == 1:
        operands.append(
            QueryReferenceTimeOperandV01(
                operand_id="operand:query-reference-time",
                value=reference_time,
                timezone=_timezone_name(reference_time),
            )
        )
    return tuple(operands)


def _retrieval_hints(
    legacy: LegacyMemoryQueryIR,
    requirements: Sequence[TypedRequirementV01],
    query: str,
) -> tuple[RetrievalHintsV01, ...]:
    operands = _binary_operands(query)
    result: list[RetrievalHintsV01] = []
    for index, requirement in enumerate(requirements):
        legacy_terms = (
            tuple(legacy.requirements[index].entity_constraints)
            if index < len(legacy.requirements)
            else tuple(legacy.entities)
        )
        phrase = (
            operands[index]
            if operands is not None and index < len(operands)
            else query.strip()
        )
        terms = _unique((*legacy_terms, *_surface_terms(phrase)))[:64]
        result.append(
            RetrievalHintsV01(
                requirement_id=requirement.requirement_id,
                phrases=(phrase.strip(),) if phrase.strip() else (),
                surface_terms=terms,
                morphological_variants=_morphological_variants(terms),
                language_tags=_language_tags(phrase or query),
            )
        )
    return tuple(result)


def _output_contract(
    legacy: LegacyMemoryQueryIR,
    operation: QueryOperation,
) -> OutputContractV01:
    if operation == QueryOperation.COUNT:
        return OutputContractV01(shape=OutputShape.SCALAR, value_type=OutputValueType.INTEGER)
    if operation in {QueryOperation.SUM, QueryOperation.DIVIDE, QueryOperation.COMPARE}:
        return OutputContractV01(shape=OutputShape.SCALAR, value_type=OutputValueType.NUMBER)
    if operation == QueryOperation.TEMPORAL_DISTANCE:
        return OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.DURATION,
            unit=_distance_output_unit(legacy),
        )
    if operation == QueryOperation.TEMPORAL_ORDER:
        return OutputContractV01(
            shape=OutputShape.ORDERED_LIST,
            value_type=OutputValueType.ENTITY,
        )
    if operation == QueryOperation.VERSION_DIFF:
        return OutputContractV01(
            shape=OutputShape.EXPLANATION,
            value_type=OutputValueType.EXPLANATION,
        )
    if operation == QueryOperation.LOOKUP:
        value_type = legacy.requirements[0].value_type if legacy.requirements else None
        return OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=(
                OutputValueType.TEXT if value_type == "STRING" else OutputValueType.ANY
            ),
        )
    if legacy.query_class == "STATE" or operation == QueryOperation.STATE_AS_OF:
        return OutputContractV01(shape=OutputShape.STATE, value_type=OutputValueType.STATE)
    if legacy.answer_type == "LIST" or operation == QueryOperation.PREFERENCE_RESOLVE:
        return OutputContractV01(shape=OutputShape.LIST, value_type=OutputValueType.ANY)
    if legacy.answer_type == "EXPLANATION":
        return OutputContractV01(
            shape=OutputShape.EXPLANATION,
            value_type=OutputValueType.EXPLANATION,
        )
    return OutputContractV01(shape=OutputShape.SCALAR, value_type=OutputValueType.ANY)


def _distance_output_unit(legacy: LegacyMemoryQueryIR) -> str:
    for requirement in legacy.requirements:
        for predicate in requirement.predicate_constraints:
            if predicate.startswith("distance_unit:"):
                return predicate.partition(":")[2]
    return "day"


def _topology(
    operation: QueryOperation,
    requirements: Sequence[TypedRequirementV01],
) -> EvidenceTopology:
    if operation == QueryOperation.VERSION_DIFF:
        return EvidenceTopology.VERSION_CHAIN
    if operation in {
        QueryOperation.DIVIDE,
        QueryOperation.COMPARE,
        QueryOperation.TEMPORAL_ORDER,
        QueryOperation.TEMPORAL_DISTANCE,
        QueryOperation.MULTI_JOIN,
    } or len([item for item in requirements if item.required]) > 1:
        return EvidenceTopology.MULTI_OPERAND
    if any(item.collection.kind == CollectionKind.MEMBER_SET for item in requirements):
        return EvidenceTopology.MEMBER_SET
    return EvidenceTopology.SINGLE_ITEM


def _proof_obligations(
    operation: QueryOperation,
    requirements: Sequence[TypedRequirementV01],
    temporal: TemporalContractV01,
) -> tuple[ProofObligation, ...]:
    if operation == QueryOperation.LOOKUP:
        return (ProofObligation.GROUNDED_RELATION,)
    if operation == QueryOperation.VERSION_DIFF:
        return (ProofObligation.ALL_REQUIRED_ROLES, ProofObligation.VERSION_CHAIN)
    if operation == QueryOperation.COUNT:
        member_set = next(
            (item for item in requirements if item.collection.kind == CollectionKind.MEMBER_SET),
            None,
        )
        if member_set is None:
            return (ProofObligation.GROUNDED_RELATION,)
        closure = (
            ProofObligation.RANGE_CLOSURE
            if member_set.collection.closure_basis == CollectionClosureBasis.QUERY_RANGE
            else ProofObligation.PARTITION_CLOSURE
        )
        return (
            ProofObligation.ALL_REQUIRED_ROLES,
            ProofObligation.IDENTITY_DEDUP,
            closure,
        )
    obligations = [ProofObligation.ALL_REQUIRED_ROLES]
    if any(item.collection.kind == CollectionKind.MEMBER_SET for item in requirements):
        obligations.append(
            ProofObligation.RANGE_CLOSURE
            if temporal.kind == TemporalKind.RANGE
            else ProofObligation.PARTITION_CLOSURE
        )
    return tuple(obligations)


def _evidence_role(
    operation: QueryOperation,
    index: int,
    legacy: LegacyRequirement,
) -> EvidenceRole:
    if operation == QueryOperation.LOOKUP:
        return EvidenceRole.ANSWER_VALUE
    if operation == QueryOperation.STATE_AS_OF:
        return EvidenceRole.STATE
    if operation == QueryOperation.COUNT:
        return (
            EvidenceRole.ANSWER_VALUE
            if "scalar_count_fact" in legacy.predicate_constraints
            else EvidenceRole.COLLECTION_MEMBER
        )
    if operation == QueryOperation.DIVIDE:
        return EvidenceRole.NUMERATOR if index == 0 else EvidenceRole.DENOMINATOR
    if operation == QueryOperation.COMPARE:
        return EvidenceRole.LEFT_OPERAND if index == 0 else EvidenceRole.RIGHT_OPERAND
    if operation in {QueryOperation.TEMPORAL_ORDER, QueryOperation.TEMPORAL_DISTANCE}:
        return EvidenceRole.EVENT
    if operation == QueryOperation.MULTI_JOIN:
        return EvidenceRole.OPERAND
    if operation == QueryOperation.PREFERENCE_RESOLVE:
        return EvidenceRole.SUPPORT
    if legacy.atom_type == "STATE_OBSERVATION":
        return EvidenceRole.STATE
    if legacy.atom_type == "EVENT":
        return EvidenceRole.EVENT
    return EvidenceRole.ANSWER_VALUE


def _role_key(operation: QueryOperation, index: int, legacy: LegacyRequirement) -> str:
    if operation == QueryOperation.DIVIDE:
        return "TOTAL_PRICE" if index == 0 else "ITEM_COUNT"
    if operation == QueryOperation.COMPARE:
        return "LEFT_VALUE" if index == 0 else "RIGHT_VALUE"
    return legacy.slot_id


def _collection_contract(
    operation: QueryOperation,
    legacy: LegacyRequirement,
    temporal: TemporalContractV01,
) -> CollectionContractV01:
    if operation == QueryOperation.COUNT:
        if "scalar_count_fact" in legacy.predicate_constraints:
            return CollectionContractV01(kind=CollectionKind.SCALAR_FACT)
        return CollectionContractV01(
            kind=CollectionKind.MEMBER_SET,
            minimum=0,
            maximum=None,
            distinct=True,
            identity_key=(
                "event_identity" if temporal.kind == TemporalKind.RANGE else "member_identity"
            ),
            closure_basis=(
                CollectionClosureBasis.QUERY_RANGE
                if temporal.kind == TemporalKind.RANGE
                else CollectionClosureBasis.SOURCE_PARTITION
            ),
        )
    if operation == QueryOperation.SUM or legacy.cardinality.maximum is None:
        return CollectionContractV01(
            kind=CollectionKind.MEMBER_SET,
            minimum=legacy.cardinality.minimum,
            maximum=None,
            distinct=legacy.cardinality.distinct,
            identity_key="member_identity" if legacy.cardinality.distinct else None,
            closure_basis=(
                CollectionClosureBasis.QUERY_RANGE
                if temporal.kind == TemporalKind.RANGE
                else CollectionClosureBasis.SOURCE_PARTITION
            ),
        )
    return CollectionContractV01()


def _requirement_temporal(
    operation: QueryOperation,
    global_temporal: TemporalContractV01,
    legacy: LegacyRequirement,
) -> TemporalContractV01:
    if operation in {
        QueryOperation.TEMPORAL_FILTER,
        QueryOperation.COUNT,
        QueryOperation.SUM,
    } and global_temporal.kind != TemporalKind.NONE:
        return global_temporal
    if legacy.temporal_constraints is not None and legacy.temporal_constraints.boundary is not None:
        return _legacy_temporal_contract(legacy.temporal_constraints)
    if operation == QueryOperation.LOOKUP and "current_state" in legacy.predicate_constraints:
        reference = (
            legacy.temporal_constraints.reference_time
            if legacy.temporal_constraints
            else None
        )
        return TemporalContractV01(
            kind=TemporalKind.CURRENT,
            axis=TemporalAxis.VALID_TIME,
            reference_time=reference,
            timezone=_timezone_name(reference) if reference is not None else None,
        )
    return TemporalContractV01()


def _requirement_relation(
    operation: QueryOperation,
    role: EvidenceRole,
    legacy: LegacyRequirement,
    query: str,
) -> str:
    if operation == QueryOperation.LOOKUP:
        return _relation_description(query)
    if operation == QueryOperation.DIVIDE:
        return "total_value" if role == EvidenceRole.NUMERATOR else "member_count"
    if operation == QueryOperation.COMPARE:
        return "comparison_value"
    if operation == QueryOperation.COUNT:
        return "stored_count" if role == EvidenceRole.ANSWER_VALUE else "collection_membership"
    meaningful = [
        item
        for item in legacy.predicate_constraints
        if item not in {"answer_bearing", "deduplicate", "matches_range"}
    ]
    return meaningful[0] if meaningful else operation.value.casefold()


def _requirement_value_type(legacy: LegacyRequirement) -> RequirementValueType:
    return {
        "STRING": RequirementValueType.TEXT,
        "NUMBER": RequirementValueType.NUMBER,
        "DATE": RequirementValueType.DATE,
        "DATETIME": RequirementValueType.DATETIME,
        "DURATION": RequirementValueType.DURATION,
        "BOOLEAN": RequirementValueType.BOOLEAN,
        "ENTITY": RequirementValueType.ENTITY,
        "ANY": RequirementValueType.ANY,
        None: RequirementValueType.ANY,
    }[legacy.value_type]


def _temporal_contract(
    query: str,
    reference: datetime,
    operation: QueryOperation,
) -> TemporalContractV01:
    timezone = _timezone_name(reference)
    month = _CALENDAR_MONTH.search(query)
    if month is not None:
        month_value = _MONTHS[month.group("month").casefold()]
        year = int(month.group("year") or reference.year)
        start = datetime(year, month_value, 1, tzinfo=reference.tzinfo)
        end = _shift_months(start, 1)
        return TemporalContractV01(
            kind=TemporalKind.RANGE,
            axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
            reference_time=reference,
            start=start,
            end=end,
            boundary=TemporalBoundary.CLOSED_OPEN,
            timezone=timezone,
        )
    relative_range = _RELATIVE_RANGE.search(query)
    if relative_range is not None:
        unit = relative_range.group("unit").casefold().rstrip("s")
        raw_count = relative_range.group("count")
        if relative_range.group("window").casefold() == "last" and raw_count is None:
            start, end = _previous_calendar_interval(reference, unit)
        else:
            count = _count(raw_count or "one")
            start, end = _shift(reference, count, unit), reference
        return TemporalContractV01(
            kind=TemporalKind.RANGE,
            axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
            reference_time=reference,
            start=start,
            end=end,
            boundary=TemporalBoundary.CLOSED_OPEN,
            timezone=timezone,
        )
    if _LAST_WEEKEND.search(query):
        monday = (reference - timedelta(days=reference.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return TemporalContractV01(
            kind=TemporalKind.RANGE,
            axis=(
                TemporalAxis.SOURCE_OBSERVED_TIME
                if operation == QueryOperation.LOOKUP
                else TemporalAxis.EVENT_OCCURRENCE_TIME
            ),
            reference_time=reference,
            start=monday - timedelta(days=2),
            end=monday,
            boundary=TemporalBoundary.CLOSED_OPEN,
            timezone=timezone,
        )
    relative_point = _RELATIVE_POINT.search(query)
    if relative_point is not None:
        start = _shift(
            reference,
            _count(relative_point.group("count")),
            relative_point.group("unit"),
        )
        return TemporalContractV01(
            kind=TemporalKind.POINT,
            axis=(
                TemporalAxis.SOURCE_OBSERVED_TIME
                if _SOURCE_TIME_REPORTING.search(query)
                else TemporalAxis.EVENT_OCCURRENCE_TIME
            ),
            reference_time=reference,
            start=start,
            timezone=timezone,
        )
    if operation == QueryOperation.STATE_AS_OF:
        return TemporalContractV01(
            kind=TemporalKind.AS_OF,
            axis=TemporalAxis.VALID_TIME,
            reference_time=reference,
            start=reference,
            timezone=timezone,
        )
    return TemporalContractV01()


def _legacy_temporal_contract(temporal: object) -> TemporalContractV01:
    reference = cast(datetime | None, getattr(temporal, "reference_time", None))
    start = cast(datetime | None, getattr(temporal, "start", None))
    end = cast(datetime | None, getattr(temporal, "end", None))
    boundary = cast(str | None, getattr(temporal, "boundary", None))
    if boundary == "POINT" and start is not None:
        return TemporalContractV01(
            kind=TemporalKind.POINT,
            axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
            reference_time=reference,
            start=start,
            timezone=_timezone_name(reference or start),
        )
    if boundary in {"CLOSED_OPEN", "CLOSED_CLOSED"} and start is not None and end is not None:
        return TemporalContractV01(
            kind=TemporalKind.RANGE,
            axis=TemporalAxis.EVENT_OCCURRENCE_TIME,
            reference_time=reference,
            start=start,
            end=end,
            boundary=TemporalBoundary(boundary),
            timezone=_timezone_name(reference or start),
        )
    return TemporalContractV01()


def _source_contract(query: str) -> tuple[SourceContractV01, str]:
    matched = _EXPLICIT_SOURCE.search(query) or _EXPLICIT_SOURCE_ZH.search(query)
    if matched is not None:
        speaker_text = matched.group("speaker").casefold()
        speaker = (
            EvidenceSpeaker.ASSISTANT
            if "assistant" in speaker_text or "助手" in speaker_text
            else EvidenceSpeaker.USER
        )
        mode = matched.group("mode").casefold()
        hard = "only" in mode or matched.group("mode").startswith("只")
        source = SourceContractV01(
            preferred_speakers=() if hard else (speaker,),
            allowed_speakers=(speaker,) if hard else None,
            provenance=SourceConstraintProvenance.EXPLICIT_QUERY,
        )
        return source, query[matched.end() :].strip()
    if _NATURAL_ASSISTANT_SOURCE.search(query):
        return (
            SourceContractV01(
                preferred_speakers=(EvidenceSpeaker.ASSISTANT,),
                provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
            ),
            query,
        )
    if _NATURAL_USER_SOURCE.search(query):
        return (
            SourceContractV01(
                preferred_speakers=(EvidenceSpeaker.USER,),
                provenance=SourceConstraintProvenance.SEMANTIC_INTERPRETATION,
            ),
            query,
        )
    return SourceContractV01(), query


def _subject(
    terms: Sequence[str],
    *,
    identity: str | None = None,
) -> SubjectContractV01:
    return SubjectContractV01(identity=identity, surface_forms=_unique(terms)[:16])


def _relation_description(query: str) -> str:
    value = _QUESTION_PREFIX.sub("", query).strip(" ?：:")  # noqa: RUF001
    value = " ".join(value.split())
    return (value or "memory_recall")[:256]


def _semantic_subject_terms(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        item for item in _unique(value.casefold() for value in values) if item not in _GRAMMAR_WORDS
    )[:16]


def _surface_terms(value: str) -> tuple[str, ...]:
    return tuple(
        _unique(
            unicodedata.normalize("NFKC", item).casefold()
            for item in _WORD.findall(value)
            if len(item) > 1 and item.casefold() not in _GRAMMAR_WORDS
        )
    )[:64]


def _lookup_subject_terms(query: str) -> tuple[str, ...]:
    """Return conservative semantic anchors without consuming retrieval cues.

    Deterministic English parsing can safely remove question mechanics and
    requested-value words.  For unsegmented CJK text it cannot identify a
    subject reliably, so the planning contract deliberately carries no hard
    subject constraint; the complete query remains in RetrievalHintsV01 and
    the Reader remains responsible for natural-language interpretation.
    """

    if _CJK.search(query) and not _LATIN.search(query):
        return ()
    return tuple(
        term
        for term in _surface_terms(query)
        if term not in _LOOKUP_NON_SUBJECT_TERMS and not term.isdecimal()
    )[:8]


def _binary_operands(query: str) -> tuple[str, str] | None:
    for pattern in (_BINARY_BETWEEN, _BINARY_COMPARE, _BINARY_OR):
        matched = pattern.search(query)
        if matched is not None:
            return matched.group("left").strip(), matched.group("right").strip()
    return None


def _count_member_subject_terms(query: str) -> tuple[str, ...]:
    matched = _COUNT_MEMBER_SUBJECT.search(query)
    if matched is not None:
        return tuple(
            item
            for item in _surface_terms(matched.group("subject"))
            if item not in {"count", "number", "time", "times"}
        )[:16]
    matched_zh = _COUNT_MEMBER_OBJECT_ZH.search(query)
    if matched_zh is None:
        matched_zh = _COUNT_MEMBER_SUBJECT_ZH.search(query)
    if matched_zh is not None:
        return _surface_terms(matched_zh.group("subject"))[:16]
    return ()


def _quoted_operator_metalinguistic(query: str) -> bool:
    for match in _QUOTED_TEXT.finditer(query):
        body = next(value for value in match.groups() if value is not None)
        if _OPERATOR_LANGUAGE.search(body):
            return True
    return False


def _morphological_variants(terms: Sequence[str]) -> tuple[str, ...]:
    variants: list[str] = []
    for term in terms:
        if not term.isascii() or not term.isalpha() or len(term) < 4:
            continue
        if term.endswith("ies") and len(term) > 4:
            variants.append(f"{term[:-3]}y")
        elif term.endswith("ing") and len(term) > 5:
            stem = term[:-3]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                stem = stem[:-1]
            variants.append(stem)
        elif term.endswith("ed") and len(term) > 4:
            variants.append(term[:-2])
        elif term.endswith("s") and not term.endswith("ss") and len(term) > 4:
            variants.append(term[:-1])
    return _unique(item for item in variants if item not in terms)[:32]


def _language_tags(value: str) -> tuple[str, ...]:
    result: list[str] = []
    if _CJK.search(value):
        result.append("zh-Hans")
    if _LATIN.search(value):
        result.append("und-Latn")
    return tuple(result or ["und"])


def _count(value: str) -> int:
    normalized = " ".join(value.casefold().split())
    return int(normalized) if normalized.isdecimal() else _NUMBER_WORDS[normalized]


def _shift(value: datetime, count: int, unit: str) -> datetime:
    unit = unit.casefold().rstrip("s")
    if unit == "day":
        return value - timedelta(days=count)
    if unit == "week":
        return value - timedelta(weeks=count)
    if unit == "month":
        return _shift_months(value, -count)
    if unit == "year":
        return _shift_months(value, -12 * count)
    raise ValueError(f"unsupported temporal unit: {unit}")


def _previous_calendar_interval(
    reference: datetime,
    unit: str,
) -> tuple[datetime, datetime]:
    """Resolve singular ``last <unit>`` in the query's local calendar."""

    if unit == "day":
        end = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        return end - timedelta(days=1), end
    if unit == "week":
        end = (reference - timedelta(days=reference.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return end - timedelta(days=7), end
    if unit == "month":
        end = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return _shift_months(end, -1), end
    if unit == "year":
        end = reference.replace(
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        return end.replace(year=end.year - 1), end
    raise ValueError(f"unsupported calendar unit: {unit}")


def _shift_months(value: datetime, months: int) -> datetime:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return value.replace(
        year=year,
        month=month,
        day=min(value.day, monthrange(year, month)[1]),
    )


def _timezone_name(value: datetime) -> str:
    zone = getattr(value.tzinfo, "key", None)
    return str(zone or value.tzname() or value.tzinfo)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "role"


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _project_requirement(
    requirement: TypedRequirementV01,
    operation: QueryOperation,
) -> EvidenceRequirementV02:
    source = _project_source(requirement.source)
    temporal = _project_temporal(requirement.temporal)
    predicates = _compatibility_predicates(requirement, operation)
    return EvidenceRequirementV02(
        slot_id=requirement.role_key,
        interpretation_kind=_interpretation_kind(requirement, operation),
        entity_constraints=list(requirement.subject.surface_forms),
        predicate_constraints=predicates,
        temporal_constraints=temporal,
        # Abstract query-local identities remain authoritative in the typed
        # contract.  V02's legacy consumer interprets these strings as literal
        # span terms, so projecting them would create false UNKNOWN bindings.
        semantic_roles=RequirementSemanticRolesV02(),
        evidence_source=source,
        value_type=_project_value_type(requirement.value.value_type),
        cardinality=RequirementCardinalityV02(
            minimum=requirement.collection.minimum,
            maximum=requirement.collection.maximum,
            distinct=requirement.collection.distinct,
        ),
        join_key=(
            operation.value.casefold()
            if operation in {
                QueryOperation.DIVIDE,
                QueryOperation.COMPARE,
                QueryOperation.TEMPORAL_ORDER,
                QueryOperation.TEMPORAL_DISTANCE,
                QueryOperation.MULTI_JOIN,
                QueryOperation.VERSION_DIFF,
            }
            else None
        ),
        required=requirement.required,
    )


def _project_hint(
    requirement: TypedRequirementV01,
    hint: RetrievalHintsV01 | None,
) -> LexicalCueSetV01:
    if hint is None:
        return LexicalCueSetV01(
            requirement_slot=requirement.role_key,
            provenance=["QUERY_TASK_CONTRACT_V01"],
        )
    return LexicalCueSetV01(
        requirement_slot=requirement.role_key,
        surface_terms=list(hint.surface_terms),
        morphological_variants=list(hint.morphological_variants),
        entity_aliases=list(hint.entity_aliases),
        relation_cues=[],
        language_tags=list(hint.language_tags),
        provenance=["QUERY_TASK_CONTRACT_V01", "QUERY_SURFACE_ONLY"],
    )


def _project_source(source: SourceContractV01) -> EvidenceSourcePolicyV02:
    supported: dict[EvidenceSpeaker, V02SourceSpeaker] = {
        EvidenceSpeaker.USER: "USER",
        EvidenceSpeaker.ASSISTANT: "ASSISTANT",
        EvidenceSpeaker.SYSTEM: "SYSTEM",
        EvidenceSpeaker.TOOL: "TOOL",
    }
    preferred: list[V02SourceSpeaker] = [
        supported[item] for item in source.preferred_speakers if item in supported
    ]
    allowed = (
        [supported[item] for item in source.allowed_speakers if item in supported]
        if source.allowed_speakers is not None
        else None
    )
    provenance = cast(
        V02SourceProvenance,
        {
            SourceConstraintProvenance.EXPLICIT_QUERY: "EXPLICIT_QUERY",
            SourceConstraintProvenance.SEMANTIC_INTERPRETATION: "SEMANTIC_PARSER",
            SourceConstraintProvenance.CALLER_HINT: "TYPED_HINT",
            SourceConstraintProvenance.NONE: "NONE",
        }[source.provenance],
    )
    return EvidenceSourcePolicyV02(
        preferred_speakers=preferred,
        allowed_speakers=allowed,
        provenance=provenance,
    )


def _project_temporal(temporal: TemporalContractV01) -> NormalizedTemporalConstraint | None:
    if temporal.kind in {TemporalKind.NONE, TemporalKind.CURRENT, TemporalKind.RELATION}:
        return None
    assert temporal.reference_time is not None
    assert temporal.start is not None
    axis: Literal["EVENT_TIME", "SOURCE_OBSERVED_TIME"] = (
        "SOURCE_OBSERVED_TIME"
        if temporal.axis == TemporalAxis.SOURCE_OBSERVED_TIME
        else "EVENT_TIME"
    )
    if temporal.kind in {TemporalKind.POINT, TemporalKind.AS_OF}:
        return NormalizedTemporalConstraint(
            reference_time=temporal.reference_time,
            start=temporal.start,
            end=temporal.start,
            boundary="POINT",
            time_axis=axis,
            precision="DAY",
            timezone=temporal.timezone or _timezone_name(temporal.reference_time),
        )
    assert temporal.end is not None
    assert temporal.boundary is not None
    return NormalizedTemporalConstraint(
        reference_time=temporal.reference_time,
        start=temporal.start,
        end=temporal.end,
        boundary=temporal.boundary.value,
        time_axis=axis,
        timezone=temporal.timezone or _timezone_name(temporal.reference_time),
    )


def _project_global_temporal(
    requirements: Sequence[TypedRequirementV01],
) -> NormalizedTemporalConstraint | None:
    for requirement in requirements:
        projected = _project_temporal(requirement.temporal)
        if projected is not None:
            return projected
    return None


def _project_mode(contract: QueryTaskContractV01) -> SemanticRoute:
    assert contract.operation is not None
    if contract.operation in {QueryOperation.STATE_AS_OF, QueryOperation.VERSION_DIFF}:
        return "STATE" if contract.operation == QueryOperation.STATE_AS_OF else "COMPOSE"
    if contract.operation == QueryOperation.LOOKUP:
        return "EVIDENCE"
    return "COMPOSE"


def _project_answer_shape(shape: OutputShape) -> MemoryAnswerShape:
    if shape == OutputShape.SCALAR:
        return "SCALAR"
    if shape == OutputShape.LIST:
        return "LIST"
    if shape == OutputShape.ORDERED_LIST:
        return "TIMELINE"
    if shape == OutputShape.STATE:
        return "STATE"
    return "EXPLANATION"


def _project_value_type(
    value_type: RequirementValueType,
) -> Literal[
    "STRING",
    "NUMBER",
    "DATE",
    "DATETIME",
    "DURATION",
    "BOOLEAN",
    "ENTITY",
    "ANY",
]:
    if value_type == RequirementValueType.TEXT:
        return "STRING"
    if value_type in {RequirementValueType.INTEGER, RequirementValueType.NUMBER}:
        return "NUMBER"
    if value_type == RequirementValueType.BOOLEAN:
        return "BOOLEAN"
    if value_type == RequirementValueType.DATE:
        return "DATE"
    if value_type == RequirementValueType.DATETIME:
        return "DATETIME"
    if value_type == RequirementValueType.DURATION:
        return "DURATION"
    if value_type == RequirementValueType.ENTITY:
        return "ENTITY"
    return "ANY"


def _interpretation_kind(
    requirement: TypedRequirementV01,
    operation: QueryOperation,
) -> InterpretationKind:
    if requirement.relation == "current_intent":
        return "DECISION"
    if requirement.evidence_role == EvidenceRole.EVENT:
        return "EVENT"
    if (
        operation == QueryOperation.LOOKUP
        and requirement.temporal.axis == TemporalAxis.EVENT_OCCURRENCE_TIME
    ):
        return "EVENT"
    if requirement.evidence_role == EvidenceRole.COLLECTION_MEMBER:
        return "EVENT" if requirement.temporal.kind == TemporalKind.RANGE else "RELATION"
    if requirement.value.value_type in {RequirementValueType.INTEGER, RequirementValueType.NUMBER}:
        return "QUANTITY"
    if operation == QueryOperation.PREFERENCE_RESOLVE:
        return "PREFERENCE_SIGNAL"
    if requirement.evidence_role in {
        EvidenceRole.STATE,
        EvidenceRole.PRIOR_STATE,
        EvidenceRole.CURRENT_STATE,
    }:
        return "STATE_OBSERVATION"
    if requirement.evidence_role in {EvidenceRole.TRANSITION, EvidenceRole.SUPPORT}:
        return "RELATION"
    return "STATE_OBSERVATION"


def _compatibility_predicates(
    requirement: TypedRequirementV01,
    operation: QueryOperation,
) -> list[str]:
    if operation == QueryOperation.LOOKUP:
        return ["answer_bearing"]
    if operation == QueryOperation.COUNT:
        return (
            ["scalar_count_fact"]
            if requirement.collection.kind == CollectionKind.SCALAR_FACT
            else ["matches_range", "deduplicate"]
        )
    if operation == QueryOperation.DIVIDE:
        return ["total"] if requirement.evidence_role == EvidenceRole.NUMERATOR else ["count"]
    if operation in {QueryOperation.TEMPORAL_ORDER, QueryOperation.TEMPORAL_DISTANCE}:
        return ["event_time"]
    if operation == QueryOperation.TEMPORAL_FILTER:
        if requirement.relation is not None and requirement.relation.startswith("relation:"):
            return [requirement.relation]
        return ["event_at_time"]
    if operation == QueryOperation.PREFERENCE_RESOLVE:
        return (
            ["current_intent"]
            if requirement.relation == "current_intent"
            else ["supports_preference"]
        )
    if requirement.evidence_role == EvidenceRole.CURRENT_STATE:
        return ["current_state"]
    return [requirement.relation] if requirement.relation else []


def _project_completeness(contract: QueryTaskContractV01) -> MemoryCompletenessV02:
    assert contract.operation is not None
    if contract.parse_disposition == ParseDisposition.BEST_EFFORT_RECALL:
        return "TOP_K_ACCEPTABLE"
    if contract.operation == QueryOperation.LOOKUP:
        return "TOP_K_ACCEPTABLE"
    if contract.operation == QueryOperation.VERSION_DIFF:
        return "COMPLETE_VERSION_CHAIN"
    if contract.operation == QueryOperation.PREFERENCE_RESOLVE:
        return "SUPPORT_THRESHOLD"
    if contract.operation == QueryOperation.COUNT and any(
        item.collection.kind == CollectionKind.MEMBER_SET
        for item in contract.requirements
    ):
        # V02 has no source-partition closure literal.  Preserve its historical
        # exhaustive-set sentinel while the typed contract retains the actual
        # QUERY_RANGE versus SOURCE_PARTITION distinction.
        return "ALL_MATCHES_IN_RANGE"
    if ProofObligation.RANGE_CLOSURE in contract.proof_obligations:
        return "ALL_MATCHES_IN_RANGE"
    return "ALL_REQUIRED_BINDINGS"


def _project_steps(
    contract: QueryTaskContractV01,
    requirements: Sequence[EvidenceRequirementV02],
    temporal: NormalizedTemporalConstraint | None,
) -> list[MemoryQueryStep]:
    assert contract.operation is not None
    family = _OPERATOR_FAMILY[contract.operation]
    projected_operands = _project_operator_operands(contract)
    steps = [
        MemoryQueryStep(
            kind="RETRIEVE",
            outputs=["candidate_spans"],
            constraints={
                "operator_family": family,
                "retrieval_unit": "TURN_OR_SPAN",
                "query_task_contract": "v0.1",
            },
            budget={"candidate_cap_required": True},
        )
    ]
    active_input = "candidate_spans"
    if temporal is not None:
        steps.append(
            MemoryQueryStep(
                kind="TEMPORAL_SCAN",
                inputs=[active_input],
                outputs=["temporal_candidates"],
                constraints={"boundary": temporal.boundary},
                budget={"bounded": True},
            )
        )
        active_input = "temporal_candidates"
    if any(item.collection.kind == CollectionKind.MEMBER_SET for item in contract.requirements):
        steps.append(
            MemoryQueryStep(
                kind="FILTER",
                inputs=[active_input],
                outputs=["applicable_members"],
                constraints={
                    "gate": "TYPE_RELATION_SCOPE",
                    "binding_owner": "DETERMINISTIC_RUNTIME",
                },
            )
        )
        active_input = "applicable_members"
    for requirement in requirements:
        if requirement.required:
            steps.append(
                MemoryQueryStep(
                    kind="BIND_SLOT",
                    inputs=[active_input],
                    outputs=[requirement.slot_id],
                    constraints={
                        "interpretation_kind": requirement.interpretation_kind,
                        "binding_owner": "DETERMINISTIC_RUNTIME",
                    },
                )
            )
    required_slots = [item.slot_id for item in requirements if item.required]
    if contract.evidence_topology in {
        EvidenceTopology.MULTI_OPERAND,
        EvidenceTopology.VERSION_CHAIN,
    }:
        steps.append(
            MemoryQueryStep(
                kind="JOIN",
                inputs=required_slots,
                outputs=["joined_bindings"],
                constraints={
                    "join_validation": "TYPE_ENTITY_UNIT_TIME_EPISODE",
                    **(
                        {"operator_operands": projected_operands}
                        if projected_operands
                        else {}
                    ),
                },
            )
        )
    if ProofObligation.IDENTITY_DEDUP in contract.proof_obligations:
        steps.append(
            MemoryQueryStep(
                kind="DEDUPLICATE",
                inputs=required_slots,
                outputs=["distinct_members"],
                constraints={"identity": "QUERY_CONDITIONED_MEMBER_IDENTITY"},
            )
        )
    reduction = {
        QueryOperation.COUNT: "count",
        QueryOperation.SUM: "sum",
        QueryOperation.DIVIDE: "divide",
        QueryOperation.TEMPORAL_DISTANCE: "distance",
    }.get(contract.operation)
    if reduction is not None:
        inputs = (
            ["distinct_members"]
            if contract.operation == QueryOperation.COUNT
            and ProofObligation.IDENTITY_DEDUP in contract.proof_obligations
            else ["joined_bindings"]
            if contract.evidence_topology == EvidenceTopology.MULTI_OPERAND
            else required_slots
        )
        steps.append(
            MemoryQueryStep(
                kind="REDUCE",
                inputs=inputs,
                outputs=["answer"],
                constraints={
                    "operation": reduction,
                    **(
                        {"operator_operands": projected_operands}
                        if projected_operands
                        else {}
                    ),
                    **(
                        {"unit": contract.output.unit}
                        if contract.output is not None and contract.output.unit is not None
                        else {}
                    ),
                },
            )
        )
    elif contract.operation in {
        QueryOperation.COMPARE,
        QueryOperation.TEMPORAL_ORDER,
        QueryOperation.VERSION_DIFF,
    }:
        steps.append(
            MemoryQueryStep(
                kind="COMPARE",
                inputs=["joined_bindings"],
                outputs=["answer"],
                constraints={"operation": family.casefold()},
            )
        )
    return steps


def _project_operator_operands(contract: QueryTaskContractV01) -> list[JsonValue]:
    role_by_requirement = {
        item.requirement_id: item.role_key for item in contract.requirements
    }
    result: list[JsonValue] = []
    for operand in contract.operator_operands:
        if isinstance(operand, RequirementBindingOperandV01):
            result.append(
                {
                    "kind": operand.kind,
                    "operand_id": operand.operand_id,
                    "slot_id": role_by_requirement[operand.requirement_id],
                }
            )
        else:
            result.append(
                {
                    "kind": operand.kind,
                    "operand_id": operand.operand_id,
                    "value": operand.value.isoformat(),
                    "timezone": operand.timezone,
                }
            )
    return result


def _query_cue_spans(
    query: str,
    hints: Sequence[RetrievalHintsV01],
) -> list[QueryCueSpan]:
    """Project bounded local cue spans without persisting the raw query.

    ``RetrievalHintsV01.phrases`` may intentionally retain the complete query
    inside the query-local contract.  ``MemoryQueryIRV02`` is also copied into
    persistent planner traces, so phrases must not cross that compatibility
    boundary.  Only terms that already occur as local substrings are exposed.
    """

    result: list[QueryCueSpan] = []
    seen: set[tuple[int, int]] = set()
    folded_query = query.casefold()
    normalized_query = " ".join(folded_query.split())
    for hint in hints:
        for term in hint.surface_terms:
            normalized_term = " ".join(term.casefold().split())
            if (
                not normalized_term
                or normalized_term == normalized_query
                or len(normalized_term) > 64
            ):
                continue
            start = folded_query.find(normalized_term)
            if start < 0:
                continue
            identity = (start, start + len(normalized_term))
            if identity in seen:
                continue
            seen.add(identity)
            result.append(
                QueryCueSpan(
                    start=start,
                    end=identity[1],
                    text=query[start : identity[1]],
                )
            )
            if len(result) == 32:
                return result
    return result


def _temporal_cue_spans(query: str) -> list[QueryCueSpan]:
    matches = [
        match
        for pattern in (_CALENDAR_MONTH, _RELATIVE_RANGE, _LAST_WEEKEND, _RELATIVE_POINT)
        if (match := pattern.search(query)) is not None
    ]
    return [
        QueryCueSpan(start=item.start(), end=item.end(), text=query[item.start() : item.end()])
        for item in sorted(matches, key=lambda value: value.start())
    ]


__all__ = [
    "QueryTaskCompilerV01",
    "project_query_task_contract_v01",
]
