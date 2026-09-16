from __future__ import annotations

import re
from calendar import monthrange
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import JsonValue

from milai.application.current_intent import has_explicit_current_intent
from milai.application.query_intent import (
    count_intent_spans,
    has_count_intent,
    strip_count_intent,
)
from milai.domain.memory_query_ir import (
    EvidenceRequirement,
    MemoryQueryIR,
    QueryParserTrace,
    RequirementCardinality,
    TemporalConstraint,
)
from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    EvidenceSourcePolicyV02,
    EvidenceSourceSpeaker,
    MemoryQueryIRV02,
    MemoryQueryStep,
    RequirementCardinalityV02,
    RequirementSemanticRolesV02,
)

if TYPE_CHECKING:
    from milai.domain.query_task_contract import QueryTaskContractV01

_PREFIX = re.compile(r"^\s*recall previous history evidence\s*:\s*", re.IGNORECASE)
_SOURCE_POLICY_PREFIX = re.compile(
    r"^\s*(?P<mode>according\s+only\s+to|use\s+only|prefer(?:\s+using)?)\s+"
    r"(?P<speaker>what\s+i\s+said|my\s+messages|assistant\s+messages|"
    r"what\s+the\s+assistant\s+said)\s*[:,]\s*",
    re.IGNORECASE,
)
_CN_SOURCE_POLICY_PREFIX = re.compile(
    r"^\s*(?P<mode>只根据|优先使用)(?P<speaker>我说的|我的消息|助手说的|助手消息)\s*[，,:：]\s*"  # noqa: RUF001 -- intentional CJK delimiters.
)
_QUOTED_OPERATOR_CUE = re.compile(
    r"[\"“][^\"”]*(?:how\s+many|count|average|sum|timeline|多少次|有多少|平均|总和)[^\"”]*[\"”]",
    re.IGNORECASE,
)
_NEGATED_OPERATOR_CUE = re.compile(
    r"\b(?:did\s+not|do\s+not|don't)\s+(?:ask\s+for\s+)?(?:a\s+)?"
    r"(?:count|sum|comparison|timeline)\b",
    re.IGNORECASE,
)
_INDEPENDENT_MULTI_INTENT = re.compile(
    r"\b(?:current|latest)\b[^?]*\band\s+(?:how\s+many|count|what|who|when|where|which)\b",
    re.IGNORECASE,
)
_EVENT_REPORTING_CUE = re.compile(
    r"\b(?:i|we)\s+(?:mentioned|said|told\s+you|asked\s+about|"
    r"talked\s+about|spoke\s+about|discussed)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_UNSUPPORTED = re.compile(r"\b(?:average|percentage|percentile|median)\b", re.IGNORECASE)
_UNSAFE_MULTI_ORDER = re.compile(
    r"\b(?:order|sequence|timeline)\b.*\b(?:three|four|all|every)\b|"
    r"\b(?:three|four|all|every)\b.*\b(?:earliest|latest|order|sequence)\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"\b(?:prefer(?:ences?)?|favorite|favourite|suggestions?|"
    r"recommend(?:ation)?s?)\b",
    re.IGNORECASE,
)
_PREFERENCE_CUE_TERMS = frozenset(
    {
        "favorite",
        "favourite",
        "fit",
        "planning",
        "plan",
        "considering",
        "currently",
        "going",
        "hope",
        "hoping",
        "intend",
        "intending",
        "preference",
        "preferences",
        "prefer",
        "recommendation",
        "recommendations",
        "suggestion",
        "suggestions",
        "soon",
        "there",
        "thinking",
        "trip",
        "travelling",
        "traveling",
        "visiting",
        "returning",
        "would",
    }
)
_COUNT_EVENT_CUE_TERMS = frozenset(
    {
        "event",
        "events",
        "family",
        "friend",
        "friends",
        "member",
        "members",
        "time",
        "times",
    }
)
_EXPLANATION = re.compile(
    r"\b(?:why|explain|what changed|difference between versions?)\b", re.IGNORECASE
)
_VERSION = re.compile(r"\b(?:changed|previously|before|old|new|version)\b", re.IGNORECASE)
_CURRENT = re.compile(r"\b(?:current|currently|now|latest)\b", re.IGNORECASE)
_MOST_RECENT = re.compile(r"\b(?:most recent(?:ly)?|recently purchased)\b", re.IGNORECASE)
_DIVIDE = re.compile(r"\b(?:how much|what)\b.*\b(?:each|per)\b|\bunit price\b", re.IGNORECASE)
_DIVIDE_ENTITY = re.compile(
    r"\b(?:each|per)\s+(?P<entity>[a-z][a-z0-9 _-]{1,100}?)"
    r"(?:\s+for\b|\s+from\b|\s*\?|$)",
    re.IGNORECASE,
)
_SCALAR_STATE_COUNT = re.compile(
    r"\bhow many\b.*(?:"
    r"\bdo i (?:currently\s+)?(?:own|have|lead)\b|"
    r"\b(?:have|did) i (?:already\s+)?(?:bought|completed|got|have|tried|own)\b|"
    r"\bare (?:there )?(?:in|on) my\b|"
    r"\bwere (?:released|produced|sold)\b|"
    r"\bso far\b)",
    re.IGNORECASE,
)
_SUM = re.compile(r"\b(?:sum|total|altogether|in all)\b", re.IGNORECASE)
_COMPARE = re.compile(r"\b(?:compare|difference|more than|less than)\b", re.IGNORECASE)
_DISTANCE = re.compile(
    r"\bhow many\s+(?P<unit>days?|weeks?|months?|years?)\b|\bhow long\b|"
    r"\b(?:elapsed time|time elapsed|days? separated)\b",
    re.IGNORECASE,
)
_FIRST = re.compile(
    r"\b(?:who|what|which)\b[^?]*?\b(?:first|earlier)\s*,?\s*"
    r"(?P<left>.+?)\s+or\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_BETWEEN = re.compile(
    r"\bbetween\s+(?P<left>.+?)\s+and\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_BEFORE_DID = re.compile(
    r"\bbefore\s+(?P<right>.+?)\s+did\s+i\s+(?P<left>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_SINCE_WHEN = re.compile(
    r"\bsince\s+(?P<left>.+?)\s+when\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_FROM_TO = re.compile(
    r"\bfrom\s+(?P<left>.+?)\s+to\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_SINCE_REFERENCE = re.compile(r"\bsince\s+(?P<event>[^?]+?)\s*\??$", re.IGNORECASE)
_DID_EVENT_AGO = re.compile(
    r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did\s+i\s+"
    r"(?P<event>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_AGO_WHEN = re.compile(
    r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did\s+i\s+"
    r"(?P<left>.+?)\s+when\s+i\s+(?P<right>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_UNANCHORED_TWO_EVENTS = re.compile(
    r"\b(?:between|separating)\s+(?:the\s+)?(?:two|2)\s+events?\b",
    re.IGNORECASE,
)
_EVENT_RELATION = re.compile(
    r"\b(?P<direction>before|after)\s+(?P<anchor>[^?]+?)\s*\??$",
    re.IGNORECASE,
)
_RELATIVE_POINT = re.compile(
    r"\b(?P<count>a\s+couple\s+of|couple\s+of|a|an|one|two|three|four|five|"
    r"six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?|years?)\s+ago\b",
    re.IGNORECASE,
)
_RANGE = re.compile(
    r"\b(?:in|during|over|within|for)?\s*(?:the\s+)?(?P<window>past|last)\s+"
    r"(?:(?P<count>a\s+couple\s+of|couple\s+of|a|an|one|two|three|four|five|"
    r"six|seven|eight|nine|ten|few|several|\d+)\s+)?"
    r"(?P<unit>days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_IN_MONTH = re.compile(
    r"\b(?:in|during)\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b(?:\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_LAST_WEEKEND = re.compile(r"\blast weekend\b", re.IGNORECASE)
_JOIN = re.compile(r"\b(?:combine|using both|based on both|across sessions?)\b", re.IGNORECASE)
_SAFE_LOOKUP = re.compile(
    r"\b(?:what|who|where|which|when)\b|"
    r"\bhow (?:long did it take|much [^?]+ did i (?:earn|pay|spend))\b|"
    r"^\s*(?:can|could|did|do|does|has|have|is|are|was|were|will|would)\b",
    re.IGNORECASE,
)
_UNSAFE_COMPLETENESS = re.compile(
    r"\b(?:all|average|compare|count|difference|each|every|median|order|"
    r"percentage|percentile|sequence|sum|timeline|total)\b|"
    r"\bhow many\b|\bacross (?:all|every|sessions?)\b",
    re.IGNORECASE,
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_CN_UNSUPPORTED = re.compile(r"(?:平均值|百分比|百分位|中位数|完整时间线|全部排序)")
_CN_DIVIDE = re.compile(r"(?:每(?:个|件|台|本|份|只|辆|张).*(?:多少钱|花费|价格)|单价)")
_CN_COUNT = re.compile(
    r"(?:(?:有)?多少(?:个|件|次|位|只|辆|本|场)?|数量(?:是|为)?多少)"
)
_CN_DISTANCE = re.compile(
    r"(?:相隔|间隔|过去了|过了).*多少(?:天|周|个月|月|年)|"
    r"之间.*多少(?:天|周|个月|月|年)"
)
_CN_ORDER = re.compile(
    r"(?:哪(?:一)?(?:件|个)?.*(?:更早|先)|谁先|先发生的是|(?:还是|或者|或).*(?:先发生|更早))"
)
_CN_JOIN = re.compile(r"(?:结合|综合|根据).*(?:两个|两段|两次|多段|跨).*(?:会话|记录|证据)|跨会话")
_CN_CURRENT = re.compile(r"(?:目前|当前|现在|最新)")
_CN_SAFE_LOOKUP = re.compile(r"(?:什么|谁|哪里|哪儿|哪个|哪一|何时|什么时候)")
_CN_UNSAFE_COMPLETENESS = re.compile(
    r"(?:全部|所有|每个|总和|总计|总共|平均|排序|顺序|时间线|比较|差值|多少次|有多少)"
)
_CN_RELATIVE_POINT = re.compile(
    r"(?P<count>[一二两三四五六七八九十百\d]+)"
    r"(?P<unit>天|周|星期|个月|月|年)前"
)
_CN_RANGE = re.compile(
    r"(?:过去|最近|近)"
    r"(?P<count>[一二两三四五六七八九十百\d]+)"
    r"(?P<unit>天|周|星期|个月|月|年)(?:内|里|期间)?"
)
_STOPWORDS = frozenset(
    {
        "a",
        "ago",
        "an",
        "and",
        "any",
        "before",
        "between",
        "couple",
        "days",
        "did",
        "do",
        "evidence",
        "few",
        "for",
        "friends",
        "history",
        "how",
        "i",
        "in",
        "it",
        "last",
        "many",
        "me",
        "months",
        "participation",
        "much",
        "my",
        "of",
        "on",
        "past",
        "previous",
        "recall",
        "since",
        "something",
        "the",
        "to",
        "was",
        "what",
        "when",
        "which",
        "who",
        "with",
        "years",
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
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}
_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_STOP_PHRASES = tuple(
    sorted(
        {
            "我",
            "我们",
            "的",
            "了",
            "吗",
            "呢",
            "是",
            "把",
            "从",
            "到",
            "和",
            "与",
            "还是",
            "或者",
            "发生",
            "买",
            "买了",
            "花了",
            "支付",
            "结合",
            "综合",
            "根据",
            "会话",
            "记录",
            "证据",
            "什么",
            "谁",
            "哪里",
            "哪儿",
            "哪个",
            "哪一个",
            "哪件事",
            "多少",
            "多少钱",
            "多少次",
            "有多少",
            "更早",
            "先",
            "相隔",
            "间隔",
            "之间",
            "过去",
            "最近",
            "目前",
            "当前",
            "现在",
            "最新",
            "每个",
            "每件",
            "单价",
        },
        key=len,
        reverse=True,
    )
)


class MemoryQueryCompiler:
    """Deterministic sole owner of executable MemoryQueryIR v0.2 plans."""

    VERSION = "deterministic-memory-query-compiler-v0.2-native-synthesis-v1"
    V01_VERSION = "deterministic-memory-query-compiler-v0.1"

    def __init__(self, *, preference_current_intent_enabled: bool = True) -> None:
        self._preference_current_intent_enabled = preference_current_intent_enabled

    def compile(
        self,
        query: str,
        *,
        reference_time: datetime,
        scope: Mapping[str, JsonValue] | None = None,
    ) -> MemoryQueryIRV02:
        from milai.application.query_task_compiler import (
            project_query_task_contract_v01,
        )

        contract = self.compile_contract(query, reference_time=reference_time)
        return project_query_task_contract_v01(
            contract,
            query=query,
            scope=scope,
        )

    def compile_contract(
        self,
        query: str,
        *,
        reference_time: datetime,
    ) -> QueryTaskContractV01:
        """Compile the authoritative internal contract before public projection."""

        from milai.application.query_task_compiler import QueryTaskCompilerV01

        return QueryTaskCompilerV01(
            preference_current_intent_enabled=self._preference_current_intent_enabled
        ).compile(query, reference_time=reference_time)

    def compile_v01(self, query: str, *, reference_time: datetime) -> MemoryQueryIR:
        """Read-only compatibility entry for historic v0.1 artifacts/tests."""

        return self._compile_semantic_spec(query, reference_time=reference_time)

    def _compile_semantic_spec(
        self, query: str, *, reference_time: datetime
    ) -> MemoryQueryIR:
        """Build the deterministic internal semantic specification."""

        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("reference_time must include a timezone offset")
        text = _PREFIX.sub("", query).strip()
        reference = reference_time.astimezone(UTC)
        if (
            _QUOTED_OPERATOR_CUE.search(text)
            or _NEGATED_OPERATOR_CUE.search(text)
            or _INDEPENDENT_MULTI_INTENT.search(text)
        ):
            return _ambiguous(reference, "CONFLICTING_OR_NON_EXECUTABLE_OPERATOR_CUE")
        if _CJK.search(text) is not None:
            return _compile_chinese_v01(text, reference)
        terms = _terms(text)
        if not terms or _UNSUPPORTED.search(text) or _UNSAFE_MULTI_ORDER.search(text):
            return _ambiguous(reference, "UNSUPPORTED_OR_UNDERSPECIFIED_QUERY")
        count_intent = has_count_intent(text)
        if len(count_intent_spans(text)) > 1:
            return _ambiguous(reference, "MULTI_QUESTION_COUNT_AMBIGUOUS")

        if _PREFERENCE.search(text):
            preference_terms = [term for term in terms if term not in _PREFERENCE_CUE_TERMS]
            requirement = EvidenceRequirement(
                slot_id="PREFERENCE_SIGNAL_SET",
                atom_type="PREFERENCE_SIGNAL",
                entity_constraints=preference_terms,
                predicate_constraints=["supports_preference"],
                value_type="STRING",
                cardinality=RequirementCardinality(minimum=1, maximum=None, distinct=True),
                join_key="preference_subject",
            )
            return _ir(
                "PREFERENCE",
                "LIST",
                "PREFERENCE_RESOLVE",
                preference_terms,
                TemporalConstraint(reference_time=reference),
                [requirement],
                "SUPPORT_THRESHOLD",
                "PREFERENCE_SIGNAL",
            )

        if _EXPLANATION.search(text):
            operator = "VERSION_DIFF" if _VERSION.search(text) else "MULTI_EVIDENCE_JOIN"
            requirements = [
                EvidenceRequirement(
                    slot_id="CONCLUSION",
                    atom_type="STATE_OBSERVATION",
                    entity_constraints=terms,
                    predicate_constraints=["conclusion"],
                    value_type="STRING",
                    join_key="explanation_subject",
                ),
                EvidenceRequirement(
                    slot_id="SUPPORT",
                    atom_type="RELATION",
                    entity_constraints=terms,
                    predicate_constraints=["supports"],
                    value_type="STRING",
                    join_key="explanation_subject",
                ),
            ]
            return _ir(
                "EXPLANATION",
                "EXPLANATION",
                operator,
                terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "COMPLETE_VERSION_CHAIN" if operator == "VERSION_DIFF" else "ALL_REQUIRED_SLOTS",
                "EXPLANATION_QUERY",
            )

        if _DIVIDE.search(text):
            entity_match = _DIVIDE_ENTITY.search(text)
            entity_terms = (
                _terms(entity_match.group("entity")) if entity_match is not None else terms
            )
            requirements = [
                _quantity_requirement("TOTAL_PRICE", entity_terms, "total", "join_entity"),
                _quantity_requirement("ITEM_COUNT", entity_terms, "count", "join_entity"),
            ]
            return _ir(
                "AGGREGATION",
                "SCALAR",
                "DIVIDE_VALUES",
                entity_terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "ALL_REQUIRED_SLOTS",
                "DIVIDE_PER_ENTITY",
            )

        range_constraint = _range_constraint(text, reference)
        if (
            count_intent
            and _DISTANCE.search(text) is None
            and _SCALAR_STATE_COUNT.search(text)
            and range_constraint is None
        ):
            requirement = EvidenceRequirement(
                slot_id="CURRENT_COUNT_FACT",
                atom_type="QUANTITY",
                entity_constraints=terms,
                predicate_constraints=["scalar_count_fact"],
                value_type="NUMBER",
            )
            return _ir(
                "STATE",
                "SCALAR",
                "COUNT_DISTINCT",
                terms,
                TemporalConstraint(reference_time=reference),
                [requirement],
                "ALL_REQUIRED_SLOTS",
                "SCALAR_COUNT_FACT",
            )
        if count_intent and _DISTANCE.search(text) is None:
            temporal = range_constraint or TemporalConstraint(
                reference_time=reference, boundary="UNBOUNDED"
            )
            event_terms = _event_count_terms(text, temporal)
            requirement = EvidenceRequirement(
                slot_id="MATCHING_EVENTS_IN_RANGE",
                atom_type="EVENT",
                entity_constraints=event_terms,
                predicate_constraints=[
                    "matches_range",
                    "deduplicate",
                    *_event_count_predicates(text),
                    *(
                        ["event_type:doctor_appointment"]
                        if re.search(r"\b(?:doctor|appointment)s?\b", text, re.I)
                        else []
                    ),
                ],
                temporal_constraints=temporal,
                value_type="ENTITY",
                cardinality=RequirementCardinality(minimum=1, maximum=None, distinct=True),
                join_key="event_identity",
            )
            return _ir(
                "AGGREGATION",
                "SCALAR",
                "COUNT_DISTINCT",
                event_terms,
                temporal,
                [requirement],
                "ALL_MATCHES_IN_RANGE",
                "BOUNDED_EVENT_COUNT" if range_constraint else "UNBOUNDED_EVENT_COUNT",
            )

        if _DISTANCE.search(text):
            anchors = _distance_anchors(text)
            unit = _distance_unit(text)
            since = _SINCE_REFERENCE.search(text)
            ago_event = _DID_EVENT_AGO.search(text)
            if (since is not None or ago_event is not None) and not _confident_event_anchors(
                anchors
            ):
                matched = since or ago_event
                assert matched is not None
                event_terms = _terms(matched.group("event"))
                requirement = EvidenceRequirement(
                    slot_id="REFERENCE_EVENT",
                    atom_type="EVENT",
                    entity_constraints=event_terms,
                    predicate_constraints=[
                        "event_time",
                        "distance_mode:from_reference",
                        f"distance_unit:{unit}",
                    ],
                    value_type="DATETIME",
                )
                return _ir(
                    "TEMPORAL",
                    "SCALAR",
                    "TEMPORAL_DISTANCE",
                    event_terms,
                    TemporalConstraint(reference_time=reference),
                    [requirement],
                    "ALL_REQUIRED_SLOTS",
                    "EVENT_TO_REFERENCE_TEMPORAL_DISTANCE",
                )
            if not _confident_event_anchors(anchors):
                if _UNANCHORED_TWO_EVENTS.search(text) is None:
                    return _ambiguous(reference, "TEMPORAL_DISTANCE_ANCHOR_AMBIGUOUS")
                anchors = [[], []]
            requirements = _event_requirements(
                anchors,
                reference,
                "temporal_pair",
                extra_predicates=[f"distance_unit:{unit}"],
            )
            return _ir(
                "TEMPORAL",
                "SCALAR",
                "TEMPORAL_DISTANCE",
                _unique(term for anchor in anchors for term in anchor) or terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "ALL_REQUIRED_SLOTS",
                "TWO_EVENT_TEMPORAL_DISTANCE",
            )

        first = _FIRST.search(text)
        if first is not None:
            raw_anchors = [first.group("left"), first.group("right")]
            anchors = [_terms(value) for value in raw_anchors]
            if not _confident_event_anchors(anchors) or _bare_named_anchors(raw_anchors):
                return _ambiguous(reference, "TEMPORAL_EVENT_ANCHOR_AMBIGUOUS")
            return _ir(
                "TEMPORAL",
                "STATE",
                "TEMPORAL_ORDER",
                _unique(term for anchor in anchors for term in anchor),
                TemporalConstraint(reference_time=reference),
                _event_requirements(anchors, reference, "temporal_pair"),
                "ALL_REQUIRED_SLOTS",
                "TWO_EVENT_TEMPORAL_ORDER",
            )

        relative = _RELATIVE_POINT.search(text)
        if relative is not None:
            count = _count(relative.group("count"))
            unit = relative.group("unit").casefold().rstrip("s")
            target = _shift(reference, count, unit)
            temporal = TemporalConstraint(
                reference_time=reference,
                start=target,
                end=target,
                boundary="POINT",
                normalized_from=relative.group(0),
            )
            requirement = EvidenceRequirement(
                slot_id="TARGET_EVENT",
                atom_type="EVENT",
                entity_constraints=_relative_event_terms(text, relative.group(0)),
                predicate_constraints=["event_at_time"],
                temporal_constraints=temporal,
                value_type="STRING",
            )
            return _ir(
                "TEMPORAL",
                "STATE",
                "TEMPORAL_FILTER",
                terms,
                temporal,
                [requirement],
                "ALL_REQUIRED_SLOTS",
                "RELATIVE_TEMPORAL_POINT",
            )

        relation = _EVENT_RELATION.search(text)
        if (
            relation is not None
            and re.search(r"\bhow much (?:more|less)\b", text, re.I) is None
            and (
                re.search(r"\bwhat happened (?:before|after)\b", text, re.I) is not None
                or re.search(r"\bwhat\b.*\bdid i\b.*\bbefore\b", text, re.I) is not None
            )
        ):
            direction = relation.group("direction").casefold()
            anchor_terms = _terms(relation.group("anchor"))
            requirements = [
                EvidenceRequirement(
                    slot_id="RELATED_EVENT",
                    atom_type="EVENT",
                    entity_constraints=terms,
                    predicate_constraints=[f"relation:{direction}"],
                    value_type="STRING",
                    join_key="temporal_relation",
                ),
                EvidenceRequirement(
                    slot_id="REFERENCE_EVENT",
                    atom_type="EVENT",
                    entity_constraints=anchor_terms,
                    predicate_constraints=["event_time"],
                    value_type="DATETIME",
                    join_key="temporal_relation",
                ),
            ]
            return _ir(
                "TEMPORAL",
                "STATE",
                "TEMPORAL_FILTER",
                terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "ALL_REQUIRED_SLOTS",
                f"EVENT_RELATION_{direction.upper()}",
            )

        if _JOIN.search(text):
            requirements = [
                EvidenceRequirement(
                    slot_id="LEFT_EVIDENCE",
                    atom_type="RELATION",
                    entity_constraints=terms,
                    join_key="query_entity",
                ),
                EvidenceRequirement(
                    slot_id="RIGHT_EVIDENCE",
                    atom_type="RELATION",
                    entity_constraints=terms,
                    join_key="query_entity",
                ),
            ]
            return _ir(
                "AGGREGATION",
                "STATE",
                "MULTI_EVIDENCE_JOIN",
                terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "ALL_REQUIRED_SLOTS",
                "EXPLICIT_MULTI_EVIDENCE_JOIN",
            )

        if _SUM.search(text):
            requirement = _quantity_requirement(
                "VALUES", terms, "sum_operand", "query_entity", maximum=None
            )
            return _ir(
                "AGGREGATION",
                "SCALAR",
                "SUM_VALUES",
                terms,
                TemporalConstraint(reference_time=reference),
                [requirement],
                "ALL_REQUIRED_SLOTS",
                "SUM_VALUES",
            )

        if _COMPARE.search(text):
            requirements = [
                _quantity_requirement("LEFT_VALUE", terms, "value", "comparison"),
                _quantity_requirement("RIGHT_VALUE", terms, "value", "comparison"),
            ]
            return _ir(
                "AGGREGATION",
                "SCALAR",
                "COMPARE_VALUES",
                terms,
                TemporalConstraint(reference_time=reference),
                requirements,
                "ALL_REQUIRED_SLOTS",
                "COMPARE_VALUES",
            )

        if _CURRENT.search(text) or _MOST_RECENT.search(text):
            predicates = ["current_state"]
            if re.search(r"\b(?:i|my)\b", text, re.I):
                predicates.append("user_fact")
            requirement = EvidenceRequirement(
                slot_id="CURRENT_STATE",
                atom_type="STATE_OBSERVATION",
                entity_constraints=terms,
                predicate_constraints=predicates,
                value_type="ANY",
            )
            return _ir(
                "STATE",
                "STATE",
                "LOOKUP",
                terms,
                TemporalConstraint(reference_time=reference),
                [requirement],
                "ALL_REQUIRED_SLOTS",
                "CURRENT_STATE_LOOKUP",
            )

        if _UNSAFE_COMPLETENESS.search(text) or _SAFE_LOOKUP.search(text) is None:
            return _ambiguous(reference, "UNSAFE_GENERIC_LOOKUP_FALLBACK")

        temporal = (
            _last_weekend_range(reference)
            if _LAST_WEEKEND.search(text)
            else TemporalConstraint(reference_time=reference)
        )
        requirement = EvidenceRequirement(
            slot_id="LOOKUP_ANSWER",
            atom_type=(
                "EVENT"
                if temporal.start is not None
                else "STATE_OBSERVATION"
            ),
            entity_constraints=_lookup_subject_terms(terms),
            predicate_constraints=["answer_bearing"],
            temporal_constraints=temporal if temporal.start is not None else None,
            value_type="STRING",
        )
        return _ir(
            "EPISODIC",
            "STATE",
            "LOOKUP",
            terms,
            temporal,
            [requirement],
            "TOP_K_ACCEPTABLE",
            "EPISODIC_LOOKUP",
        )


def _expand_preference_current_intent(
    query_ir: MemoryQueryIRV02,
    query: str,
) -> MemoryQueryIRV02:
    """Add an independent value slot for explicit current preference context."""

    if not has_explicit_current_intent(query):
        return query_ir
    preference_requirements = [
        requirement
        for requirement in query_ir.requirements
        if requirement.slot_id == "PREFERENCE_SIGNAL_SET"
        and requirement.interpretation_kind == "PREFERENCE_SIGNAL"
    ]
    if len(preference_requirements) != 1 or any(
        requirement.slot_id == "CURRENT_INTENT" for requirement in query_ir.requirements
    ):
        return query_ir
    preference = preference_requirements[0]
    current_intent = EvidenceRequirementV02(
        slot_id="CURRENT_INTENT",
        interpretation_kind="DECISION",
        entity_constraints=list(preference.entity_constraints),
        predicate_constraints=["current_intent"],
        semantic_roles=RequirementSemanticRolesV02(experiencer="USER"),
        value_type="STRING",
        cardinality=RequirementCardinalityV02(
            minimum=1,
            maximum=1,
            distinct=False,
        ),
        join_key=preference.join_key or "preference_subject",
        required=True,
    )
    payload = query_ir.model_dump(mode="python")
    payload["requirements"] = [
        *query_ir.requirements,
        current_intent,
    ]
    payload["steps"] = [
        *query_ir.steps,
        MemoryQueryStep(
            kind="BIND_SLOT",
            inputs=["candidate_spans"],
            outputs=["CURRENT_INTENT"],
            constraints={
                "interpretation_kind": "DECISION",
                "binding_owner": "DETERMINISTIC_RUNTIME",
            },
        ),
    ]
    payload["planner_trace"] = query_ir.planner_trace.model_copy(
        update={"reason_code": f"{query_ir.planner_trace.reason_code}+CURRENT_INTENT_EXPLICIT"}
    )
    return MemoryQueryIRV02.model_validate(payload)


def _extract_source_policy(
    query: str,
) -> tuple[EvidenceSourcePolicyV02 | None, str]:
    """Parse explicit speaker policy and mask only its directive at stable offsets."""
    matched = _SOURCE_POLICY_PREFIX.search(query)
    if matched is None:
        matched = _CN_SOURCE_POLICY_PREFIX.search(query)
    if matched is None:
        return None, query
    mode = matched.group("mode").casefold()
    speaker_text = matched.group("speaker").casefold()
    speaker: EvidenceSourceSpeaker = (
        "ASSISTANT" if "assistant" in speaker_text or "助手" in speaker_text else "USER"
    )
    hard = "only" in mode or mode == "只根据"
    policy = EvidenceSourcePolicyV02(
        allowed_speakers=[speaker] if hard else None,
        preferred_speakers=[] if hard else [speaker],
        provenance="EXPLICIT_QUERY",
    )
    masked = " " * matched.end() + query[matched.end() :]
    return policy, masked


def _apply_source_policy(
    query_ir: MemoryQueryIRV02,
    source_policy: EvidenceSourcePolicyV02,
) -> MemoryQueryIRV02:
    if query_ir.mode == "AMBIGUOUS":
        return query_ir
    return query_ir.model_copy(
        update={
            "requirements": [
                requirement.model_copy(update={"evidence_source": source_policy})
                for requirement in query_ir.requirements
            ]
        }
    )


def _compile_chinese_v01(text: str, reference: datetime) -> MemoryQueryIR:
    terms = _terms(text)
    if not terms or _CN_UNSUPPORTED.search(text):
        return _ambiguous(reference, "UNSUPPORTED_CHINESE_QUERY")

    if _CN_DIVIDE.search(text):
        requirements = [
            _quantity_requirement("TOTAL_PRICE", terms, "total", "join_entity"),
            _quantity_requirement("ITEM_COUNT", terms, "count", "join_entity"),
        ]
        return _ir(
            "AGGREGATION",
            "SCALAR",
            "DIVIDE_VALUES",
            terms,
            TemporalConstraint(reference_time=reference),
            requirements,
            "ALL_REQUIRED_SLOTS",
            "ZH_DIVIDE_PER_ENTITY",
        )

    range_constraint = _cn_range_constraint(text, reference)
    if _CN_COUNT.search(text) and _CN_DISTANCE.search(text) is None:
        temporal = range_constraint or TemporalConstraint(
            reference_time=reference, boundary="UNBOUNDED"
        )
        requirement = EvidenceRequirement(
            slot_id="MATCHING_EVENTS_IN_RANGE",
            atom_type="EVENT",
            entity_constraints=terms,
            predicate_constraints=["matches_range", "deduplicate"],
            temporal_constraints=temporal,
            value_type="ENTITY",
            cardinality=RequirementCardinality(minimum=1, maximum=None, distinct=True),
            join_key="event_identity",
        )
        return _ir(
            "AGGREGATION",
            "SCALAR",
            "COUNT_DISTINCT",
            terms,
            temporal,
            [requirement],
            "ALL_MATCHES_IN_RANGE",
            "ZH_BOUNDED_EVENT_COUNT" if range_constraint else "ZH_UNBOUNDED_EVENT_COUNT",
        )

    if _CN_DISTANCE.search(text):
        anchors = _cn_distance_anchors(text)
        if not _confident_event_anchors(anchors):
            return _ambiguous(reference, "ZH_TEMPORAL_DISTANCE_ANCHOR_AMBIGUOUS")
        requirements = _event_requirements(
            anchors,
            reference,
            "temporal_pair",
            extra_predicates=[f"distance_unit:{_cn_distance_unit(text)}"],
        )
        return _ir(
            "TEMPORAL",
            "SCALAR",
            "TEMPORAL_DISTANCE",
            _unique(term for anchor in anchors for term in anchor),
            TemporalConstraint(reference_time=reference),
            requirements,
            "ALL_REQUIRED_SLOTS",
            "ZH_TWO_EVENT_TEMPORAL_DISTANCE",
        )

    if _CN_ORDER.search(text):
        anchors = _cn_order_anchors(text)
        if not _confident_event_anchors(anchors):
            return _ambiguous(reference, "ZH_TEMPORAL_EVENT_ANCHOR_AMBIGUOUS")
        return _ir(
            "TEMPORAL",
            "STATE",
            "TEMPORAL_ORDER",
            _unique(term for anchor in anchors for term in anchor),
            TemporalConstraint(reference_time=reference),
            _event_requirements(anchors, reference, "temporal_pair"),
            "ALL_REQUIRED_SLOTS",
            "ZH_TWO_EVENT_TEMPORAL_ORDER",
        )

    relative = _CN_RELATIVE_POINT.search(text)
    if relative is not None:
        target = _shift(
            reference,
            _chinese_count(relative.group("count")),
            _cn_unit(relative.group("unit")),
        )
        temporal = TemporalConstraint(
            reference_time=reference,
            start=target,
            end=target,
            boundary="POINT",
            normalized_from=relative.group(0),
        )
        requirement = EvidenceRequirement(
            slot_id="TARGET_EVENT",
            atom_type="EVENT",
            entity_constraints=terms,
            predicate_constraints=["event_at_time"],
            temporal_constraints=temporal,
            value_type="STRING",
        )
        return _ir(
            "TEMPORAL",
            "STATE",
            "TEMPORAL_FILTER",
            terms,
            temporal,
            [requirement],
            "ALL_REQUIRED_SLOTS",
            "ZH_RELATIVE_TEMPORAL_POINT",
        )

    if _CN_JOIN.search(text):
        requirements = [
            EvidenceRequirement(
                slot_id="LEFT_EVIDENCE",
                atom_type="RELATION",
                entity_constraints=terms,
                join_key="query_entity",
            ),
            EvidenceRequirement(
                slot_id="RIGHT_EVIDENCE",
                atom_type="RELATION",
                entity_constraints=terms,
                join_key="query_entity",
            ),
        ]
        return _ir(
            "AGGREGATION",
            "STATE",
            "MULTI_EVIDENCE_JOIN",
            terms,
            TemporalConstraint(reference_time=reference),
            requirements,
            "ALL_REQUIRED_SLOTS",
            "ZH_EXPLICIT_MULTI_EVIDENCE_JOIN",
        )

    if _CN_CURRENT.search(text):
        requirement = EvidenceRequirement(
            slot_id="CURRENT_STATE",
            atom_type="STATE_OBSERVATION",
            entity_constraints=terms,
            predicate_constraints=["current_state"],
            value_type="ANY",
        )
        return _ir(
            "STATE",
            "STATE",
            "LOOKUP",
            terms,
            TemporalConstraint(reference_time=reference),
            [requirement],
            "ALL_REQUIRED_SLOTS",
            "ZH_CURRENT_STATE_LOOKUP",
        )

    if _CN_UNSAFE_COMPLETENESS.search(text) or _CN_SAFE_LOOKUP.search(text) is None:
        return _ambiguous(reference, "ZH_UNSAFE_GENERIC_LOOKUP_FALLBACK")
    requirement = EvidenceRequirement(
        slot_id="LOOKUP_ANSWER",
        atom_type="STATE_OBSERVATION",
        entity_constraints=_lookup_subject_terms(terms),
        predicate_constraints=["answer_bearing"],
        value_type="STRING",
    )
    return _ir(
        "EPISODIC",
        "STATE",
        "LOOKUP",
        terms,
        TemporalConstraint(reference_time=reference),
        [requirement],
        "TOP_K_ACCEPTABLE",
        "ZH_EPISODIC_LOOKUP",
    )


def _ir(
    query_class: str,
    answer_type: str,
    operator: str,
    entities: list[str],
    temporal: TemporalConstraint,
    requirements: list[EvidenceRequirement],
    completeness: str,
    reason: str,
) -> MemoryQueryIR:
    return MemoryQueryIR.model_validate(
        {
            "query_class": query_class,
            "answer_type": answer_type,
            "operator": operator,
            "entities": entities,
            "predicates": _unique(
                predicate
                for requirement in requirements
                for predicate in requirement.predicate_constraints
            ),
            "temporal": temporal,
            "requirements": requirements,
            "completeness": completeness,
            "parser": QueryParserTrace(
                kind="DETERMINISTIC",
                version=MemoryQueryCompiler.V01_VERSION,
                confidence=0.95,
                hidden_model_calls=0,
                reason_code=reason,
            ),
        }
    )


def _ambiguous(reference: datetime, reason: str) -> MemoryQueryIR:
    return MemoryQueryIR(
        query_class="EPISODIC",
        answer_type="STATE",
        operator="LOOKUP",
        temporal=TemporalConstraint(reference_time=reference),
        requirements=[
            EvidenceRequirement(
                slot_id="AMBIGUOUS_QUERY",
                atom_type="RELATION",
                value_type="ANY",
            )
        ],
        completeness="ALL_REQUIRED_SLOTS",
        parser=QueryParserTrace(
            kind="AMBIGUOUS",
            version=MemoryQueryCompiler.V01_VERSION,
            confidence=0.0,
            hidden_model_calls=0,
            reason_code=reason,
        ),
    )


def _quantity_requirement(
    slot: str,
    terms: list[str],
    predicate: str,
    join_key: str,
    *,
    maximum: int | None = 1,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        slot_id=slot,
        atom_type="QUANTITY",
        entity_constraints=terms,
        predicate_constraints=[predicate],
        value_type="NUMBER",
        cardinality=RequirementCardinality(minimum=1, maximum=maximum, distinct=True),
        join_key=join_key,
    )


def _lookup_subject_terms(terms: list[str]) -> list[str]:
    """Keep lookup subject/relation anchors separate from requested value words."""

    value_cues = {
        "amount",
        "color",
        "colour",
        "how",
        "name",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "什么",
        "何时",
        "名字",
        "哪里",
        "哪儿",
        "多少",
        "怎么",
        "谁",
        "颜色",
    }
    anchored = [term for term in terms if term.casefold() not in value_cues]
    return anchored or list(terms)


def _event_requirements(
    anchors: list[list[str]],
    reference: datetime,
    join_key: str,
    *,
    extra_predicates: list[str] | None = None,
) -> list[EvidenceRequirement]:
    padded = [*anchors, [], []][:2]
    return [
        EvidenceRequirement(
            slot_id=f"EVENT_{index + 1}",
            atom_type="EVENT",
            entity_constraints=anchor,
            predicate_constraints=["event_time", *(extra_predicates or [])],
            temporal_constraints=TemporalConstraint(reference_time=reference),
            value_type="DATETIME",
            join_key=join_key,
        )
        for index, anchor in enumerate(padded)
    ]


def _event_count_predicates(query: str) -> list[str]:
    """Preserve explicit event-participant qualifiers outside flat entity terms."""
    predicates: list[str] = []
    if re.search(
        r"\b(?:friends?|family|aunts?|uncles?|cousins?|relatives?)\b|"
        r"(?:朋友|家人|亲属|亲戚|表亲|堂亲)",
        query,
        re.IGNORECASE,
    ):
        predicates.append("participant_relation:social_circle")
    return predicates


def _distance_anchors(query: str) -> list[list[str]]:
    for pattern in (_AGO_WHEN, _BETWEEN, _BEFORE_DID, _SINCE_WHEN, _FROM_TO):
        matched = pattern.search(query)
        if matched is not None:
            return [_terms(matched.group("left")), _terms(matched.group("right"))]
    return [[], []]


def _distance_unit(query: str) -> str:
    matched = re.search(r"\b(days?|weeks?|months?|years?)\b", query, re.IGNORECASE)
    return matched.group(1).casefold().rstrip("s") if matched is not None else "day"


def _confident_event_anchors(anchors: list[list[str]]) -> bool:
    """Both operands must have at least one deterministic lexical anchor."""

    return len(anchors) == 2 and all(anchors)


def _bare_named_anchors(raw_anchors: list[str]) -> bool:
    return len(raw_anchors) == 2 and all(
        re.fullmatch(r"\s*[A-Z][a-z]{1,30}\s*", value) is not None for value in raw_anchors
    )


def _range_constraint(query: str, reference: datetime) -> TemporalConstraint | None:
    matched = _RANGE.search(query)
    if matched is not None:
        unit = matched.group("unit").casefold().rstrip("s")
        raw_count = matched.group("count")
        if matched.group("window").casefold() == "last" and raw_count is None:
            start, end = _previous_calendar_interval(reference, unit)
        else:
            count = _count(raw_count or "one")
            start, end = _shift(reference, count, unit), reference
        return TemporalConstraint(
            reference_time=reference,
            start=start,
            end=end,
            boundary="CLOSED_OPEN",
            normalized_from=matched.group(0),
        )
    calendar_month = _IN_MONTH.search(query)
    if calendar_month is None:
        return None
    month = _MONTHS[calendar_month.group("month").casefold()]
    year = int(calendar_month.group("year") or reference.year)
    start = datetime(year, month, 1, tzinfo=UTC)
    end = _shift_months(start, 1)
    return TemporalConstraint(
        reference_time=reference,
        start=start,
        end=end,
        boundary="CLOSED_OPEN",
        normalized_from=calendar_month.group(0),
    )


def _cn_range_constraint(query: str, reference: datetime) -> TemporalConstraint | None:
    matched = _CN_RANGE.search(query)
    if matched is None:
        return None
    return TemporalConstraint(
        reference_time=reference,
        start=_shift(
            reference,
            _chinese_count(matched.group("count")),
            _cn_unit(matched.group("unit")),
        ),
        end=reference,
        boundary="CLOSED_OPEN",
        normalized_from=matched.group(0),
    )


def _cn_distance_anchors(query: str) -> list[list[str]]:
    patterns = (
        re.compile(
            r"从(?P<left>.+?)到(?P<right>.+?)"
            r"(?:相隔|间隔|过去了|过了|有)?多少(?:天|周|个月|月|年)"
        ),
        re.compile(
            r"(?P<left>.+?)(?:和|与)(?P<right>.+?)之间"
            r"(?:相隔|间隔|有)?多少(?:天|周|个月|月|年)"
        ),
    )
    for pattern in patterns:
        matched = pattern.search(query)
        if matched is not None:
            return [_terms(matched.group("left")), _terms(matched.group("right"))]
    return [[], []]


def _cn_order_anchors(query: str) -> list[list[str]]:
    patterns = (
        re.compile(
            r"(?P<left>[^\uff0c\u3002\uff1f?]+?)(?:和|与|还是|或)"
            r"(?P<right>[^\uff0c\u3002\uff1f?]+?)[\uff0c,]\s*"
            r"(?:哪(?:一)?(?:件|个)?.*?(?:更早|先)|谁先)"
        ),
        re.compile(
            r"(?:哪(?:一)?(?:件|个)?.*?)?"
            r"(?P<left>[^\uff0c\u3002\uff1f?]+?)(?:还是|或)"
            r"(?P<right>[^\uff0c\u3002\uff1f?]+?)(?:更早|先)"
        ),
    )
    for pattern in patterns:
        matched = pattern.search(query)
        if matched is not None:
            return [_terms(matched.group("left")), _terms(matched.group("right"))]
    return [[], []]


def _cn_distance_unit(query: str) -> str:
    matched = re.search(r"多少(?P<unit>天|周|个月|月|年)", query)
    return _cn_unit(matched.group("unit")) if matched is not None else "day"


def _cn_unit(value: str) -> str:
    return {
        "天": "day",
        "周": "week",
        "星期": "week",
        "个月": "month",
        "月": "month",
        "年": "year",
    }[value]


def _chinese_count(value: str) -> int:
    if value.isdecimal():
        return int(value)
    if value == "十":
        return 10
    if "十" in value:
        tens, ones = value.split("十", maxsplit=1)
        return (10 if not tens else _CN_DIGITS[tens] * 10) + (0 if not ones else _CN_DIGITS[ones])
    if value == "百":
        return 100
    if value.endswith("百") and len(value) == 2:
        return _CN_DIGITS[value[0]] * 100
    return _CN_DIGITS[value]


def _last_weekend_range(reference: datetime) -> TemporalConstraint:
    days_since_monday = reference.weekday()
    most_recent_monday = (reference - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return TemporalConstraint(
        reference_time=reference,
        start=most_recent_monday - timedelta(days=2),
        end=most_recent_monday,
        boundary="CLOSED_OPEN",
        normalized_from="last weekend",
    )


def _previous_calendar_interval(
    reference: datetime,
    unit: str,
) -> tuple[datetime, datetime]:
    """Resolve singular ``last <unit>`` as the prior local calendar unit."""

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


def _shift(value: datetime, count: int, unit: str) -> datetime:
    if unit == "day":
        return value - timedelta(days=count)
    if unit == "week":
        return value - timedelta(days=count * 7)
    if unit == "month":
        return _shift_months(value, -count)
    if unit == "year":
        return _shift_months(value, -count * 12)
    raise ValueError(f"unsupported temporal unit: {unit}")


def _shift_months(value: datetime, months: int) -> datetime:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return value.replace(
        year=year,
        month=month,
        day=min(value.day, monthrange(year, month)[1]),
    )


def _count(value: str) -> int:
    normalized = " ".join(value.casefold().split())
    if normalized.isdecimal():
        return int(normalized)
    return _NUMBER_WORDS[normalized]


def _terms(value: str) -> list[str]:
    if _CJK.search(value) is not None:
        normalized = value
        normalized = _CN_RELATIVE_POINT.sub(" ", normalized)
        normalized = _CN_RANGE.sub(" ", normalized)
        for phrase in _CN_STOP_PHRASES:
            normalized = normalized.replace(phrase, " ")
        return _unique(
            token
            for token in re.findall(r"[\u3400-\u9fff]{2,}|[a-zA-Z0-9]+", normalized)
            if len(token) > 1
        )[:16]
    return _unique(
        token
        for token in _WORD.findall(value.casefold())
        if token not in _STOPWORDS and len(token) > 1
    )[:16]


def _event_count_terms(query: str, temporal: TemporalConstraint) -> list[str]:
    value = strip_count_intent(query)
    if temporal.normalized_from:
        value = re.sub(
            re.escape(temporal.normalized_from),
            " ",
            value,
            flags=re.IGNORECASE,
        )
    return [
        term
        for term in _terms(value)
        if term not in _COUNT_EVENT_CUE_TERMS and term not in _NUMBER_WORDS and not term.isdecimal()
    ]


def _relative_event_terms(query: str, relative_phrase: str) -> list[str]:
    value = re.sub(
        re.escape(relative_phrase),
        " ",
        query,
        flags=re.IGNORECASE,
    )
    # Reporting language identifies where the memory was expressed, not what
    # happened.  Keep the event payload while removing only the reporting cue.
    value = _EVENT_REPORTING_CUE.sub(" ", value)
    return [term for term in _terms(value) if not term.isdecimal()]


def _unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["MemoryQueryCompiler"]
