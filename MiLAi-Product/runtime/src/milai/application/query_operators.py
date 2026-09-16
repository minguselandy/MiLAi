from __future__ import annotations

import json
import re
from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from milai.application.operator_binding_authority import (
    operator_operands_from_raw_bindings,
)
from milai.domain.retrieval import QueryOperator, QueryPlan
from milai.domain.semantic_query import (
    EvidenceInterpretationCandidate,
    EvidenceSpan,
    RequirementBinding,
)

_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])")
_UNIT = re.compile(
    r"(?:[$£€]\s*)?[-+]?\d+(?:,\d{3})*(?:\.\d+)?\s*"
    r"(?P<unit>postcards?|dollars?|usd|pounds?|gbp|euros?|eur|days?|weeks?|months?|years?)?",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_MONTH_DATE = re.compile(
    r"\b(?:(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?|"
    r"(?P<day_first>\d{1,2})(?:st|nd|rd|th)?\s+of\s+"
    r"(?P<month_after>January|February|March|April|May|June|July|August|September|"
    r"October|November|December))(?:,?\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(
    r"(?<![\d/])(?P<month>1[0-2]|0?[1-9])/(?P<day>3[01]|[12]\d|0?[1-9])"
    r"(?:/(?P<year>\d{2}|\d{4}))?(?![\d/])"
)
_NON_EVENT_DATE_SUFFIX = re.compile(r"^\s+(?:edition|issue|model|release|version)\b", re.IGNORECASE)
_RELATIVE_AGO = re.compile(
    r"\b(?:(?:about|around)\s+)?"
    r"(?P<count>a|an|few|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?P<unit>days?|weeks?|months?|years?)\s+ago\b",
    re.IGNORECASE,
)
_RELATIVE_DAY = re.compile(r"\b(?P<day>today|yesterday)\b", re.IGNORECASE)
_RELATIVE_WEEKDAY = re.compile(
    r"\b(?:(?P<last>last)\s+)?"
    r"(?P<weekday>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_LAST_WEEKEND = re.compile(r"\blast weekend\b", re.IGNORECASE)
_MONTH_ONLY = re.compile(
    r"\b(?:in|during)\s+"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
    r"(?:\s+(?P<year>\d{4}))?\b",
    re.IGNORECASE,
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
    "few": 3,
}
_COUNT_TOKEN = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"\d+(?:,\d{3})*)(?!\w)",
    re.IGNORECASE,
)
_COUNT_VALUE_VERBS = frozenset(
    {
        "added",
        "attended",
        "bought",
        "completed",
        "finished",
        "got",
        "had",
        "has",
        "have",
        "met",
        "own",
        "owned",
        "seen",
        "tried",
        "watched",
    }
)
_COUNT_VALUE_FOLLOWERS = frozenset({"of", "time", "times"})
_MONTHS = {
    name.casefold(): index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
_WEEKDAYS = {
    name: index
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    )
}
_EVENT_TERM_NORMALIZATION = {
    "baked": "bake",
    "baking": "bake",
    "cooking": "bake",
    "celebration": "festival",
    "met": "meet",
    "meeting": "meet",
    "painted": "paint",
    "painting": "paint",
    "planted": "plant",
    "planting": "plant",
    "purchased": "buy",
    "bought": "buy",
    "got": "buy",
    "visited": "visit",
    "visiting": "visit",
}


@dataclass(frozen=True, slots=True)
class _DatedEvent:
    item: Mapping[str, Any]
    at: datetime
    sentence: str
    basis: str
    score: int
    result_index: int
    sentence_index: int


@dataclass(frozen=True, slots=True)
class AcceptedOperatorInput:
    """One MATCH Binding operand with its exact span and governed source."""

    requirement_id: str
    span: EvidenceSpan
    interpretation: EvidenceInterpretationCandidate
    source: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptedOperatorInputs:
    """The only source collection a strict deterministic operator may inspect."""

    required_requirement_ids: tuple[str, ...]
    operands: tuple[AcceptedOperatorInput, ...]

    @property
    def filled_requirement_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.requirement_id for item in self.operands}))

    @property
    def complete(self) -> bool:
        return set(self.filled_requirement_ids) == set(self.required_requirement_ids)

    def options(
        self,
    ) -> dict[
        str,
        list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ]:
        values: dict[
            str,
            list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
        ] = {requirement_id: [] for requirement_id in self.required_requirement_ids}
        for item in self.operands:
            values[item.requirement_id].append(
                (item.span, item.interpretation, item.source)
            )
        return values

    def governed_sources(self) -> list[Mapping[str, Any]]:
        values: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for item in self.operands:
            identity = item.span.source_evidence_id
            if identity not in seen:
                values.append(item.source)
                seen.add(identity)
        return values


def _parsed_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _timestamp(item: Mapping[str, Any]) -> datetime | None:
    return _parsed_timestamp(item.get("valid_time_from") or item.get("observed_at"))


def _payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("payload")
    if isinstance(value, Mapping):
        return value
    content = item.get("content")
    return {"memory_text": content} if isinstance(content, str) else {}


def _item_identity(item: Mapping[str, Any]) -> str:
    for key in ("claim_version_id", "evidence_id", "source_ref"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return ""


def _display_value(item: Mapping[str, Any], query_terms: frozenset[str] = frozenset()) -> Any:
    payload = _payload(item)
    for key in ("value", "answer", "state"):
        if key in payload:
            return payload[key]
    memory_text = payload.get("memory_text")
    if isinstance(memory_text, str):
        sentences = [value.strip() for value in _SENTENCE.split(memory_text) if value.strip()]
        if not sentences:
            return ""
        selected = max(
            enumerate(sentences),
            key=lambda value: (
                len(query_terms.intersection(word.casefold() for word in _WORD.findall(value[1]))),
                -value[0],
            ),
        )[1]
        return selected[:600].rstrip()
    return payload


def _latest_state_count_value(
    item: Mapping[str, Any],
    query_terms: frozenset[str],
    required_qualifiers: frozenset[str],
) -> str | None:
    display = _display_value(item, query_terms)
    if not isinstance(display, str):
        return None
    matches = list(_COUNT_TOKEN.finditer(display))
    display_numbers = {match.group(0).replace(",", "").casefold() for match in matches}
    if not required_qualifiers.issubset(display_numbers):
        return None
    candidates: list[str] = []
    for match in matches:
        value = match.group(0)
        normalized = value.replace(",", "").casefold()
        if normalized in required_qualifiers:
            continue
        before_char = display[match.start() - 1 : match.start()]
        after_char = display[match.end() : match.end() + 1]
        if before_char == "-" or after_char == "-":
            # A mint/year identifier such as pre-1920 or 1915-S is not a
            # scalar collection count.
            continue
        line_start = display.rfind("\n", 0, match.start()) + 1
        line_end = display.find("\n", match.end())
        line_end = len(display) if line_end < 0 else line_end
        line = display[line_start:line_end]
        relative_end = match.end() - line_start
        if value.isdecimal() and re.match(r"\s*\.", line[relative_end:]):
            # Do not interpret an assistant list marker (``1.``) as memory.
            continue
        before_words = [
            word.casefold() for word in _WORD.findall(line[: match.start() - line_start])
        ]
        after_words = [word.casefold() for word in _WORD.findall(line[relative_end:])]
        previous = before_words[-3:]
        following = after_words[:4]
        follows_subject = bool(query_terms.intersection(following))
        follows_count_relation = bool(following) and following[0] in _COUNT_VALUE_FOLLOWERS
        follows_count_verb = bool(set(previous).intersection(_COUNT_VALUE_VERBS))
        if not (follows_subject or follows_count_relation or follows_count_verb):
            continue
        if (
            not value.isdecimal()
            and previous
            and previous[-1] not in _COUNT_VALUE_VERBS
            and not follows_subject
            and not follows_count_relation
        ):
            # Reject pronominal uses such as ``an amazing one at a festival``.
            continue
        candidates.append(value)
    # Preserve the source spelling (for example ``five``) so the deterministic
    # result does not make the answering model gratuitously rewrite it as ``5``.
    return candidates[0] if len(candidates) == 1 else None


def _pointer(
    item: Mapping[str, Any],
    *,
    derived_time: datetime | None = None,
    time_basis: str | None = None,
    source_span: str | None = None,
    time_axis: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(item)
    evidence_only = item.get("evidence_id") is not None
    system_timestamp = _parsed_timestamp(item.get("captured_at") or item.get("system_time"))
    result: dict[str, Any] = {
        "claim_id": str(item.get("claim_id")) if item.get("claim_id") else None,
        "claim_version_id": (
            str(item["claim_version_id"]) if item.get("claim_version_id") is not None else None
        ),
        "evidence_ids": sorted(
            {
                *(str(value) for value in item.get("evidence_ids", []) if value is not None),
                *([str(item["evidence_id"])] if item.get("evidence_id") is not None else []),
            }
        ),
        "valid_time_from": (
            timestamp.isoformat() if timestamp is not None and not evidence_only else None
        ),
        "source_timestamp": (
            timestamp.isoformat() if timestamp is not None and evidence_only else None
        ),
        "system_timestamp": (
            system_timestamp.isoformat() if system_timestamp is not None else None
        ),
        "source_ref": item.get("source_ref"),
        "authority_class": "EVIDENCE_ONLY" if evidence_only else "CANONICAL_STATE",
    }
    if derived_time is not None:
        result["derived_time"] = derived_time.isoformat()
        result["time_basis"] = time_basis
    if time_axis is not None:
        result["time_axis"] = time_axis
    if source_span is not None:
        result["source_span"] = source_span
    return result


def _abstain(plan: QueryPlan, operator: QueryOperator, reason: str) -> dict[str, Any]:
    return {
        "status": "ABSTAINED",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": operator,
        "reason": reason,
        "route_reason": plan.operator_arguments.get("route_reason"),
        "slot_schema_version": plan.operator_arguments.get("slot_schema_version"),
        "operands": [],
        "hidden_model_calls": 0,
        "canonical_mutation": False,
    }


def _partial_result(
    plan: QueryPlan,
    operator: QueryOperator,
    reason: str,
    *,
    operand_pointers: Sequence[Mapping[str, Any]],
    filled_slots: Sequence[str],
) -> dict[str, Any]:
    """Retain proven operands without promoting an incomplete operator result."""

    return {
        "status": "PARTIAL",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": operator,
        "value": None,
        "unit": None,
        "reason": reason,
        "route_reason": plan.operator_arguments.get("route_reason"),
        "slot_schema_version": plan.operator_arguments.get("slot_schema_version"),
        "operands": [dict(pointer) for pointer in operand_pointers],
        "date_boundary": str(plan.operator_arguments.get("date_boundary", "inclusive")),
        "hidden_model_calls": 0,
        "canonical_mutation": False,
        "completeness": {
            "required_slots": _required_slot_ids(plan),
            "filled_slots": list(dict.fromkeys(filled_slots)),
            "unresolved_reasons": [reason],
        },
    }


def _numeric(item: Mapping[str, Any]) -> tuple[Decimal, str | None] | None:
    payload = _payload(item)
    for key in ("amount", "count", "total", "value"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float, Decimal)):
            try:
                return Decimal(str(value)), str(payload.get("unit")) if payload.get(
                    "unit"
                ) else None
            except InvalidOperation:
                continue
    text = str(payload.get("memory_text", ""))
    matches = list(_NUMBER.finditer(text))
    if len(matches) != 1:
        return None
    try:
        value = Decimal(matches[0].group(0).replace(",", ""))
    except InvalidOperation:
        return None
    unit_match = _UNIT.search(text[matches[0].start() :])
    unit = unit_match.group("unit").casefold() if unit_match and unit_match.group("unit") else None
    return value, unit


def _compatible_scope(plan: QueryPlan, results: Sequence[Mapping[str, Any]]) -> bool:
    requested = json.dumps(plan.scope_predicate, sort_keys=True, separators=(",", ":"))
    scopes = {
        json.dumps(item.get("scope_predicate", {}), sort_keys=True, separators=(",", ":"))
        for item in results
        if item.get("scope_predicate")
    }
    return len(scopes) <= 1 and (not scopes or requested in scopes)


def _integer(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    return int(value) if value.isdecimal() else _NUMBER_WORDS.get(value.casefold())


def _shift_months(value: datetime, months: int) -> datetime:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def _shift(
    value: datetime, count: int, unit: str, *, sign: int = -1
) -> datetime | None:
    """Shift a bounded civil timestamp, rejecting unrepresentable dates.

    Evidence can mention geological or historical spans that are legitimate
    prose but outside Python's ``datetime`` year range.  Such a phrase is not
    a usable personal-event timestamp and must not abort the complete read.
    """

    try:
        if unit == "day":
            return value + timedelta(days=sign * count)
        if unit == "week":
            return value + timedelta(days=sign * count * 7)
        if unit == "month":
            return _shift_months(value, sign * count)
        if unit == "year":
            return _shift_months(value, sign * count * 12)
    except (OverflowError, ValueError):
        return None
    raise ValueError(f"unsupported temporal unit: {unit}")


def _date_with_inferred_year(
    reference: datetime, month: int, day: int, year: int | None
) -> datetime | None:
    inferred_year = year if year is not None else reference.year
    try:
        return reference.replace(year=inferred_year, month=month, day=day)
    except ValueError:
        return None


def _dates_in_sentence(
    sentence: str,
    reference: datetime,
    *,
    source_is_evidence: bool,
) -> list[tuple[datetime, str]]:
    values: list[tuple[datetime, str]] = []
    relative_basis = (
        "RELATIVE_TO_SOURCE_OBSERVED_TIME"
        if source_is_evidence
        else "RELATIVE_TO_CANONICAL_VALID_TIME"
    )
    for match in _MONTH_DATE.finditer(sentence):
        if _NON_EVENT_DATE_SUFFIX.search(sentence[match.end() :]) is not None:
            continue
        month_name = match.group("month") or match.group("month_after")
        day_value = match.group("day") or match.group("day_first")
        year_value = match.group("year")
        parsed = _date_with_inferred_year(
            reference,
            _MONTHS[month_name.casefold()],
            int(day_value),
            int(year_value) if year_value else None,
        )
        if parsed is not None:
            values.append((parsed, "EXPLICIT_CALENDAR_DATE"))
    for match in _NUMERIC_DATE.finditer(sentence):
        raw_year = match.group("year")
        year = None
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000
        parsed = _date_with_inferred_year(
            reference,
            int(match.group("month")),
            int(match.group("day")),
            year,
        )
        if parsed is not None:
            values.append((parsed, "EXPLICIT_NUMERIC_DATE"))
    for match in _RELATIVE_AGO.finditer(sentence):
        count = _integer(match.group("count"))
        if count is not None:
            shifted = _shift(
                reference,
                count,
                match.group("unit").casefold().rstrip("s"),
            )
            if shifted is not None:
                values.append((shifted, relative_basis))
    relative_day = _RELATIVE_DAY.search(sentence)
    if relative_day is not None:
        values.append(
            (
                reference
                if relative_day.group("day").casefold() == "today"
                else reference - timedelta(days=1),
                relative_basis,
            )
        )
    weekend = _LAST_WEEKEND.search(sentence)
    if weekend is not None:
        week_start = reference - timedelta(days=reference.weekday())
        values.append((week_start - timedelta(days=2), relative_basis))
    weekday = _RELATIVE_WEEKDAY.search(sentence)
    if weekday is not None and not values:
        target = _WEEKDAYS[weekday.group("weekday").casefold()]
        delta = (reference.weekday() - target) % 7 or 7
        values.append((reference - timedelta(days=delta), relative_basis))
    for match in _MONTH_ONLY.finditer(sentence):
        year_raw = match.group("year")
        year = int(year_raw) if year_raw else reference.year
        parsed = _date_with_inferred_year(
            reference,
            _MONTHS[match.group("month").casefold()],
            1,
            year,
        )
        if parsed is not None:
            values.append(
                (
                    parsed,
                    "EXPLICIT_MONTH" if year_raw else relative_basis,
                )
            )
    deduplicated: dict[datetime, str] = {}
    for at, basis in values:
        deduplicated.setdefault(at, basis)
    return list(deduplicated.items())


def _query_terms(plan: QueryPlan) -> frozenset[str]:
    raw = plan.operator_arguments.get("query_terms")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(value.casefold() for value in raw if isinstance(value, str) and value)


def _required_qualifiers(plan: QueryPlan) -> frozenset[str]:
    raw = plan.operator_arguments.get("required_qualifiers")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        value.replace(",", "").casefold() for value in raw if isinstance(value, str) and value
    )


def _item_query_overlap(item: Mapping[str, Any], query_terms: frozenset[str]) -> int:
    display = _display_value(item, query_terms)
    if not isinstance(display, str):
        return 0
    words = {value.casefold() for value in _WORD.findall(display)}
    return len(query_terms.intersection(words))


def _source_sentences(text: str) -> list[str]:
    """Split source text without inferring lineage from rendered prefixes."""

    result: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for sentence in _SENTENCE.split(line):
            if sentence.strip():
                result.append(sentence.strip())
    return result


def _latest_state_value(plan: QueryPlan, item: Mapping[str, Any]) -> Any | None:
    payload = _payload(item)
    for key in ("value", "answer", "state"):
        if key in payload:
            return payload[key]
    memory_text = payload.get("memory_text")
    if not isinstance(memory_text, str):
        return None
    if _requires_typed_participant(plan):
        # Rendered labels such as ``user:`` are not authoritative participant
        # annotations.  The legacy body therefore cannot satisfy a typed actor
        # requirement; a structured canonical value above remains valid.
        return None
    query_terms = _query_terms(plan)
    candidates = _source_sentences(memory_text)
    ranked = [
        (
            len(query_terms.intersection(word.casefold() for word in _WORD.findall(sentence))),
            index,
            sentence,
        )
        for index, sentence in enumerate(candidates)
    ]
    if not ranked:
        return None
    overlap, _index, sentence = max(
        ranked,
        key=lambda value: (value[0], -value[1]),
    )
    if query_terms and overlap == 0:
        return None
    return sentence[:600].rstrip()


def _requires_typed_participant(plan: QueryPlan) -> bool:
    if plan.query_task_contract is not None:
        return any(
            requirement.required and bool(requirement.participants)
            for requirement in plan.query_task_contract.requirements
        )
    query_ir = plan.memory_query_ir
    if query_ir is None:
        return False
    return any(
        requirement.semantic_roles.actor is not None
        or requirement.semantic_roles.experiencer is not None
        or requirement.semantic_roles.beneficiary is not None
        for requirement in query_ir.requirements
    )


def _latest_state_overlap(plan: QueryPlan, item: Mapping[str, Any]) -> int:
    value = _latest_state_value(plan, item)
    material = [
        value if isinstance(value, str) else "",
        *(str(item.get(key) or "") for key in ("subject_id", "predicate", "claim_type")),
    ]
    payload = _payload(item)
    material.extend(
        str(payload.get(key) or "") for key in ("state_key", "predicate", "subject_id")
    )
    words = {
        word.casefold()
        for candidate in material
        for word in _WORD.findall(candidate)
    }
    return len(_query_terms(plan).intersection(words))


def _best_relevant_timed(
    plan: QueryPlan, items: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    ranked = [
        (_latest_state_overlap(plan, item), _timestamp(item), index, item)
        for index, item in enumerate(items)
        if _timestamp(item) is not None
    ]
    if not ranked:
        return None
    overlap, _at, _index, selected = max(
        ranked,
        key=lambda value: (value[0], value[1], -value[2]),
    )
    return selected if not _query_terms(plan) or overlap > 0 else None


def _typed_slots_valid(plan: QueryPlan, operator: QueryOperator) -> bool:
    arguments = plan.operator_arguments
    if (
        arguments.get("slot_schema_version") != "typed-operator-v1"
        or not isinstance(arguments.get("route_reason"), str)
        or not arguments.get("route_reason")
        or not isinstance(arguments.get("operand_type"), str)
        or not isinstance(arguments.get("query_terms"), list)
    ):
        return False
    required = arguments.get("required_operand_count")
    minimum = arguments.get("minimum_operand_count")
    if required is not None and (
        not isinstance(required, int) or isinstance(required, bool) or required < 1
    ):
        return False
    if minimum is not None and (
        not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1
    ):
        return False
    if operator == "LATEST_VALID_STATE":
        return required == 1 and arguments.get("selection_basis") in {
            "valid_time_from",
            "source_observed_then_event_time",
        }
    if operator == "COUNT_DISTINCT":
        return (
            minimum == 1
            and arguments.get("count_mode") == "scalar_fact"
            and isinstance(arguments.get("required_qualifiers"), list)
        )
    if operator == "SUM_VALUES":
        return minimum == 2 and arguments.get("aggregation") == "sum"
    if operator == "COMPARE_EVENTS":
        return required == 2 and arguments.get("comparison_mode") == "difference"
    if operator == "COMPARE_EVENT_IDENTITY":
        slots = arguments.get("required_slots")
        return (
            required == 2
            and arguments.get("comparison_mode") == "identity_equality"
            and isinstance(slots, list)
            and len(slots) == 2
        )
    if operator == "COMPOSE_STATE":
        slots = arguments.get("required_slots")
        return (
            required == 2
            and arguments.get("composition_mode") == "preference_plus_short_lived_state"
            and slots == ["PREFERENCE_SIGNAL_SET", "SHORT_LIVED_STATE"]
        )
    if operator == "DIVIDE_EVIDENCE_VALUES":
        return (
            required == 2
            and arguments.get("required_slots") == ["TOTAL_PRICE", "ITEM_COUNT"]
            and arguments.get("completeness") == "ALL_REQUIRED_SLOTS"
            and isinstance(arguments.get("entity_terms"), list)
        )
    if operator == "TEMPORAL_COUNT_DISTINCT":
        temporal_range = arguments.get("temporal_range")
        return (
            arguments.get("required_slots") == ["MATCHING_EVENTS_IN_RANGE"]
            and arguments.get("event_type") in {"DOCTOR_APPOINTMENT", "GENERIC_EVENT"}
            and (
                arguments.get("event_type") != "DOCTOR_APPOINTMENT"
                or arguments.get("attendance_status") == "ATTENDED"
            )
            and (
                arguments.get("event_type") != "GENERIC_EVENT"
                or isinstance(arguments.get("event_terms"), list)
            )
            and arguments.get("completeness") == "ALL_MATCHES_IN_RANGE"
            and arguments.get("dedup_key_version")
            == (
                "appointment-event-v1"
                if arguments.get("event_type") == "DOCTOR_APPOINTMENT"
                else "generic-event-v0.2-binding"
            )
            and isinstance(temporal_range, dict)
            and isinstance(temporal_range.get("start"), str)
            and isinstance(temporal_range.get("end"), str)
            and temporal_range.get("boundary") == "CLOSED_OPEN"
            and arguments.get("time_axis") in {"SOURCE_OBSERVED_TIME", "EVENT_OCCURRENCE_TIME"}
        )
    if operator == "TEMPORAL_DISTANCE":
        mode = arguments.get("distance_mode")
        return (
            mode in {"between_events", "from_reference"}
            and required == (2 if mode == "between_events" else 1)
            and arguments.get("distance_unit") in {"day", "week", "month", "year"}
        )
    if operator == "TEMPORAL_BEFORE_AFTER":
        mode = arguments.get("target_mode")
        if mode == "binary_ordering":
            anchors = arguments.get("event_anchor_terms")
            return (
                required == 2
                and arguments.get("direction") == "before"
                and arguments.get("ordering") == "earliest"
                and isinstance(anchors, list)
                and len(anchors) == 2
                and all(
                    isinstance(anchor, list)
                    and bool(anchor)
                    and all(isinstance(term, str) and bool(term) for term in anchor)
                    for anchor in anchors
                )
            )
        return (
            mode in {"relative_point", "event_relation"}
            and required == (1 if mode == "relative_point" else 2)
            and arguments.get("direction") in {"before", "after"}
            and arguments.get("time_axis", "EVENT_TIME") in {"EVENT_TIME", "SOURCE_OBSERVED_TIME"}
        )
    return False


def _dated_events(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    *,
    allow_unmatched: bool = False,
) -> list[_DatedEvent]:
    query_terms = _query_terms(plan)
    events: list[_DatedEvent] = []
    for result_index, item in enumerate(results):
        reference = _timestamp(item)
        if reference is None:
            continue
        text = str(_payload(item).get("memory_text", ""))
        if not text.strip():
            events.append(
                _DatedEvent(
                    item=item,
                    at=reference,
                    sentence="",
                    basis="CANONICAL_VALID_TIME",
                    score=1,
                    result_index=result_index,
                    sentence_index=0,
                )
            )
            continue
        for sentence_index, sentence in enumerate(_SENTENCE.split(text)):
            sentence = sentence.strip()
            if not sentence:
                continue
            words = {value.casefold() for value in _WORD.findall(sentence)}
            overlap = len(query_terms.intersection(words))
            if query_terms and overlap == 0 and not allow_unmatched:
                continue
            dated = _dates_in_sentence(
                sentence,
                reference,
                source_is_evidence=item.get("evidence_id") is not None,
            )
            for at, basis in dated:
                events.append(
                    _DatedEvent(
                        item=item,
                        at=at,
                        sentence=sentence[:600],
                        basis=basis,
                        score=overlap * 10 + (3 if basis.startswith("EXPLICIT") else 1),
                        result_index=result_index,
                        sentence_index=sentence_index,
                    )
                )
    return sorted(
        events,
        key=lambda event: (
            -event.score,
            event.result_index,
            event.sentence_index,
            event.at,
        ),
    )


def _source_observation_events(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
) -> list[_DatedEvent]:
    query_terms = frozenset(_event_term(term) for term in _query_terms(plan))
    minimum_overlap = 1 if len(query_terms) <= 1 else (len(query_terms) + 1) // 2
    events: list[_DatedEvent] = []
    for result_index, item in enumerate(results):
        if item.get("evidence_id") is None:
            continue
        reference = _timestamp(item)
        if reference is None:
            continue
        text = str(_payload(item).get("memory_text", ""))
        candidates = _source_sentences(text)
        for sentence_index, sentence in enumerate(candidates):
            words = {_event_term(value) for value in _WORD.findall(sentence)}
            overlap = len(query_terms.intersection(words))
            if query_terms and overlap < minimum_overlap:
                continue
            events.append(
                _DatedEvent(
                    item=item,
                    at=reference,
                    sentence=sentence[:600],
                    basis="SOURCE_OBSERVED_TIME",
                    score=overlap * 10,
                    result_index=result_index,
                    sentence_index=sentence_index,
                )
            )
    return sorted(
        events,
        key=lambda event: (
            -event.score,
            event.result_index,
            event.sentence_index,
            event.at,
        ),
    )


def _event_anchor_terms(plan: QueryPlan) -> tuple[frozenset[str], frozenset[str]] | None:
    raw = plan.operator_arguments.get("event_anchor_terms")
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    anchors: list[frozenset[str]] = []
    for value in raw:
        if not isinstance(value, list):
            return None
        terms = frozenset(_event_term(term) for term in value if isinstance(term, str) and term)
        if not terms:
            return None
        anchors.append(terms)
    return anchors[0], anchors[1]


def _event_term(value: str) -> str:
    normalized = value.casefold()
    return _EVENT_TERM_NORMALIZATION.get(normalized, normalized)


def _anchored_events(
    results: Sequence[Mapping[str, Any]], anchor_terms: frozenset[str]
) -> list[_DatedEvent]:
    events: list[_DatedEvent] = []
    required_overlap = 1 if len(anchor_terms) == 1 else 2
    for result_index, item in enumerate(results):
        reference = _timestamp(item)
        if reference is None:
            continue
        text = str(_payload(item).get("memory_text", ""))
        for sentence_index, sentence in enumerate(_SENTENCE.split(text)):
            sentence = sentence.strip()
            if not sentence:
                continue
            words = {_event_term(value) for value in _WORD.findall(sentence)}
            overlap = len(anchor_terms.intersection(words))
            if overlap < required_overlap or overlap / len(anchor_terms) < 0.5:
                continue
            dated = _dates_in_sentence(
                sentence,
                reference,
                source_is_evidence=item.get("evidence_id") is not None,
            )
            if not dated:
                if item.get("evidence_id") is not None:
                    continue
                dated = [(reference, "CANONICAL_VALID_TIME")]
            for at, basis in dated:
                events.append(
                    _DatedEvent(
                        item=item,
                        at=at,
                        sentence=sentence[:600],
                        basis=basis,
                        score=(
                            overlap * 100
                            + round(10 * overlap / len(anchor_terms))
                            + (3 if basis.startswith("EXPLICIT") else 1)
                        ),
                        result_index=result_index,
                        sentence_index=sentence_index,
                    )
                )
    return sorted(
        events,
        key=lambda event: (
            -event.score,
            event.result_index,
            event.sentence_index,
            event.at,
        ),
    )


def _binary_anchor_pair(
    plan: QueryPlan, results: Sequence[Mapping[str, Any]]
) -> tuple[_DatedEvent, _DatedEvent] | None:
    anchors = _event_anchor_terms(plan)
    if anchors is None:
        return None
    left = _anchored_events(results, anchors[0])
    right = _anchored_events(results, anchors[1])
    pairs = [
        (left_event, right_event)
        for left_event in left
        for right_event in right
        if (
            left_event.result_index,
            left_event.sentence_index,
            left_event.at,
        )
        != (
            right_event.result_index,
            right_event.sentence_index,
            right_event.at,
        )
    ]
    if not pairs:
        return None
    return max(
        pairs,
        key=lambda pair: (
            min(pair[0].score, pair[1].score),
            pair[0].score + pair[1].score,
            -pair[0].result_index,
            -pair[1].result_index,
        ),
    )


def _partial_anchor_operands(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep independently resolved anchor evidence when a pair is incomplete.

    Each physical event can fill at most one slot.  This avoids turning one
    ambiguous sentence into a fabricated two-event pair while preserving
    trustworthy provenance for whichever anchor was actually recovered.
    """

    anchors = _event_anchor_terms(plan)
    if anchors is None:
        return [], []
    required_slots = _required_slot_ids(plan)
    pointers: list[dict[str, Any]] = []
    filled_slots: list[str] = []
    claimed_events: set[tuple[int, int, datetime]] = set()
    for index, anchor_terms in enumerate(anchors):
        event = next(
            (
                candidate
                for candidate in _anchored_events(results, anchor_terms)
                if (candidate.result_index, candidate.sentence_index, candidate.at)
                not in claimed_events
            ),
            None,
        )
        if event is None:
            continue
        claimed_events.add((event.result_index, event.sentence_index, event.at))
        pointers.append(
            _pointer(
                event.item,
                derived_time=event.at,
                time_basis=event.basis,
                source_span=event.sentence,
            )
        )
        if index < len(required_slots):
            filled_slots.append(required_slots[index])
    return pointers, filled_slots


def _distinct_anchor_pair(events: Sequence[_DatedEvent]) -> tuple[_DatedEvent, _DatedEvent] | None:
    if not events:
        return None
    first = events[0]
    different_item = next(
        (
            event
            for event in events[1:]
            if event.result_index != first.result_index and event.at.date() != first.at.date()
        ),
        None,
    )
    second = different_item or next(
        (event for event in events[1:] if event.at.date() != first.at.date()),
        None,
    )
    return (first, second) if second is not None else None


def _distance_value(left: datetime, right: datetime, unit: str) -> int:
    if unit == "month":
        earlier, later = sorted((left, right))
        return (later.year - earlier.year) * 12 + later.month - earlier.month
    if unit == "year":
        earlier, later = sorted((left, right))
        return later.year - earlier.year
    days = abs((right.date() - left.date()).days)
    return round(days / 7) if unit == "week" else days


def _matched_binding_options(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
) -> dict[
    str,
    list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
]:
    slots = _required_slot_ids(plan)
    options: dict[
        str,
        list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ] = {slot: [] for slot in slots}
    span_by_id = {span.span_id: span for span in spans}
    interpretation_by_id = {
        interpretation.interpretation_id: interpretation for interpretation in interpretations
    }
    result_by_evidence_id = {
        str(item["evidence_id"]): item
        for item in results
        if isinstance(item.get("evidence_id"), str)
    }
    accepted_bindings = operator_operands_from_raw_bindings(bindings)
    for binding in accepted_bindings:
        if binding.requirement_id not in options:
            continue
        interpretation = interpretation_by_id.get(binding.interpretation_id)
        if interpretation is None:
            continue
        span = span_by_id.get(interpretation.span_id)
        if span is None:
            continue
        item = result_by_evidence_id.get(span.source_evidence_id)
        if item is not None:
            options[binding.requirement_id].append((span, interpretation, item))
    return {
        slot: sorted(values, key=lambda value: _binding_option_order(plan, value))
        for slot, values in options.items()
    }


def build_accepted_operator_inputs(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
) -> AcceptedOperatorInputs:
    """Close strict operands over exact MATCH Binding lineage."""

    required = tuple(_required_slot_ids(plan))
    options = _matched_binding_options(
        plan,
        results,
        spans,
        interpretations,
        bindings,
    )
    operands = tuple(
        AcceptedOperatorInput(
            requirement_id=requirement_id,
            span=span,
            interpretation=interpretation,
            source=source,
        )
        for requirement_id in required
        for span, interpretation, source in options.get(requirement_id, ())
    )
    return AcceptedOperatorInputs(
        required_requirement_ids=required,
        operands=operands,
    )


def _binding_option_order(
    plan: QueryPlan,
    option: tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]],
) -> tuple[int, datetime, str, int, str]:
    span, interpretation, _item = option
    basis_rank = 0 if interpretation.time_basis == "EXPLICIT_EVENT_TIME" else 1
    source_time = span.source_timestamp or datetime.max.replace(tzinfo=plan.time_reference.tzinfo)
    return (
        basis_rank,
        source_time,
        span.source_turn_ref,
        span.start,
        interpretation.interpretation_id,
    )


def _formation_state_result(
    plan: QueryPlan,
    options: Mapping[
        str,
        Sequence[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ],
) -> dict[str, Any]:
    slots = _required_slot_ids(plan)
    if len(slots) != 1:
        return _abstain(plan, "LATEST_VALID_STATE", "OPERATOR_SLOT_SCHEMA_INVALID")
    candidates = [
        option
        for option in options.get(slots[0], ())
        if option[1].kind == "STATE_OBSERVATION"
        and isinstance(option[1].value, Mapping)
        and isinstance(option[1].value.get("state_predicate"), str)
    ]
    if not candidates:
        return _abstain(plan, "LATEST_VALID_STATE", "STATE_VALUE_MISSING")
    latest = max(
        candidates,
        key=lambda option: (
            option[0].source_timestamp or datetime.min.replace(tzinfo=plan.time_reference.tzinfo),
            option[0].source_turn_ref,
            option[0].start,
            option[1].interpretation_id,
        ),
    )
    _latest_span, latest_interpretation, _latest_item = latest
    assert isinstance(latest_interpretation.value, Mapping)
    predicate = str(latest_interpretation.value["state_predicate"])
    relation = latest_interpretation.value.get("transition_relation")
    state_value = latest_interpretation.value.get("state_value")
    value = {
        "state_predicate": predicate,
        "state_value": state_value,
        "current_status": (
            "NO_CURRENT_STATE_ON_RECORD"
            if relation == "REVOKES" and state_value is None
            else "CURRENT_EVIDENCE_STATE"
        ),
        "transition_relation": relation,
    }
    supporting = _unique_binding_options(candidates)
    return _base_success(
        plan,
        "LATEST_VALID_STATE",
        [item for _span, _interpretation, item in supporting],
        value=value,
        operand_pointers=[_binding_pointer(option) for option in supporting],
    )


def _formation_event_identity_result(
    plan: QueryPlan,
    options: Mapping[
        str,
        Sequence[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ],
) -> dict[str, Any]:
    slots = _required_slot_ids(plan)
    if len(slots) != 2:
        return _abstain(
            plan,
            "COMPARE_EVENT_IDENTITY",
            "OPERATOR_SLOT_SCHEMA_INVALID",
        )
    resolved: list[
        tuple[
            str,
            tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]],
        ]
    ] = []
    for slot in slots:
        by_identity: dict[
            str,
            list[
                tuple[
                    EvidenceSpan,
                    EvidenceInterpretationCandidate,
                    Mapping[str, Any],
                ]
            ],
        ] = {}
        for option in options.get(slot, ()):
            value = option[1].value
            if (
                option[1].kind != "EVENT"
                or not isinstance(value, Mapping)
                or value.get("event_status") != "OCCURRED"
                or not isinstance(value.get("event_identity"), str)
            ):
                continue
            by_identity.setdefault(str(value["event_identity"]), []).append(option)
        if len(by_identity) != 1:
            return _abstain(
                plan,
                "COMPARE_EVENT_IDENTITY",
                "EVENT_IDENTITY_AMBIGUOUS" if by_identity else "OPERAND_MISSING",
            )
        identity, candidates = next(iter(by_identity.items()))
        resolved.append((identity, candidates[0]))
    left, right = resolved
    supporting = _unique_binding_options([left[1], right[1]])
    return _base_success(
        plan,
        "COMPARE_EVENT_IDENTITY",
        [item for _span, _interpretation, item in supporting],
        value={
            "same_event": left[0] == right[0],
            "left_event_identity": left[0],
            "right_event_identity": right[0],
        },
        operand_pointers=[_binding_pointer(option) for option in supporting],
    )


def _formation_temporal_order_result(
    plan: QueryPlan,
    options: Mapping[
        str,
        Sequence[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ],
) -> dict[str, Any]:
    slots = _required_slot_ids(plan)
    if len(slots) != 2:
        return _abstain(
            plan,
            "TEMPORAL_BEFORE_AFTER",
            "OPERATOR_SLOT_SCHEMA_INVALID",
        )
    resolved: list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]] = []
    for slot in slots:
        grouped: dict[
            tuple[str, datetime, datetime | None],
            list[
                tuple[
                    EvidenceSpan,
                    EvidenceInterpretationCandidate,
                    Mapping[str, Any],
                ]
            ],
        ] = {}
        for option in options.get(slot, ()):
            interpretation = option[1]
            value = interpretation.value
            if (
                interpretation.kind != "EVENT"
                or interpretation.event_time is None
                or interpretation.event_time.start is None
                or not isinstance(value, Mapping)
                or value.get("event_status") != "OCCURRED"
            ):
                continue
            identity = value.get("event_identity")
            if not isinstance(identity, str):
                identity = interpretation.interpretation_id
            grouped.setdefault(
                (
                    identity,
                    interpretation.event_time.start,
                    interpretation.event_time.end,
                ),
                [],
            ).append(option)
        if len(grouped) != 1:
            return _abstain(
                plan,
                "TEMPORAL_BEFORE_AFTER",
                "TIME_UNCERTAIN" if grouped else "OPERAND_MISSING",
            )
        resolved.append(next(iter(grouped.values()))[0])
    left, right = resolved
    left_time = left[1].event_time
    right_time = right[1].event_time
    assert left_time is not None and left_time.start is not None
    assert right_time is not None and right_time.start is not None
    if left_time.start == right_time.start:
        return _abstain(plan, "TEMPORAL_BEFORE_AFTER", "TIME_UNCERTAIN")
    selected = left if left_time.start < right_time.start else right
    supporting = _unique_binding_options([left, right])
    return _base_success(
        plan,
        "TEMPORAL_BEFORE_AFTER",
        [item for _span, _interpretation, item in supporting],
        value={
            "selected": selected[0].text,
            "ordering": "earliest",
            "events": {
                slots[0]: left_time.start.isoformat(),
                slots[1]: right_time.start.isoformat(),
            },
        },
        operand_pointers=[_binding_pointer(option) for option in supporting],
    )


def _formation_composed_state_result(
    plan: QueryPlan,
    options: Mapping[
        str,
        Sequence[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
    ],
) -> dict[str, Any]:
    preference_options = [
        option
        for option in options.get("PREFERENCE_SIGNAL_SET", ())
        if option[1].kind == "PREFERENCE_SIGNAL"
        and isinstance(option[1].value, Mapping)
        and isinstance(option[1].value.get("preferred"), str)
    ]
    short_options = [
        option
        for option in options.get("SHORT_LIVED_STATE", ())
        if option[1].kind == "STATE_OBSERVATION"
        and isinstance(option[1].value, Mapping)
        and isinstance(option[1].value.get("state_predicate"), str)
    ]
    if not preference_options or not short_options:
        pointers = [
            *(_binding_pointer(option) for option in preference_options[:1]),
            *(_binding_pointer(option) for option in short_options[:1]),
        ]
        return (
            _partial_result(
                plan,
                "COMPOSE_STATE",
                "OPERAND_MISSING",
                operand_pointers=pointers,
                filled_slots=[
                    *(["PREFERENCE_SIGNAL_SET"] if preference_options else []),
                    *(["SHORT_LIVED_STATE"] if short_options else []),
                ],
            )
            if pointers
            else _abstain(plan, "COMPOSE_STATE", "OPERAND_MISSING")
        )
    preference = max(
        preference_options,
        key=lambda option: (
            option[0].source_timestamp or datetime.min.replace(tzinfo=plan.time_reference.tzinfo),
            option[0].source_turn_ref,
            option[0].start,
        ),
    )
    short_lived = max(
        short_options,
        key=lambda option: (
            option[0].source_timestamp or datetime.min.replace(tzinfo=plan.time_reference.tzinfo),
            option[0].source_turn_ref,
            option[0].start,
        ),
    )
    assert isinstance(preference[1].value, Mapping)
    assert isinstance(short_lived[1].value, Mapping)
    state_predicate = str(short_lived[1].value["state_predicate"])
    value = {
        "preference": preference[1].value["preferred"],
        state_predicate: short_lived[1].value.get("state_value"),
    }
    supporting = _unique_binding_options([preference, short_lived])
    return _base_success(
        plan,
        "COMPOSE_STATE",
        [item for _span, _interpretation, item in supporting],
        value=value,
        operand_pointers=[_binding_pointer(option) for option in supporting],
    )


def _binding_pointer(
    option: tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]],
) -> dict[str, Any]:
    span, interpretation, item = option
    event_time = interpretation.event_time
    return _pointer(
        item,
        derived_time=(event_time.start if event_time is not None else None),
        time_basis=(
            str(interpretation.time_basis)
            if event_time is not None and event_time.start is not None
            else None
        ),
        source_span=span.text,
    )


def _unique_binding_options(
    options: Sequence[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]],
) -> list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]]:
    values: list[tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for option in options:
        evidence_id = option[0].source_evidence_id
        if evidence_id not in seen:
            values.append(option)
            seen.add(evidence_id)
    return values


def _execute_legacy_operator_from_accepted_inputs(
    plan: QueryPlan,
    accepted_inputs: AcceptedOperatorInputs,
) -> dict[str, Any] | None:
    operator = plan.operator
    if operator is None:
        return None
    options = accepted_inputs.options()
    if not accepted_inputs.operands:
        return _abstain(plan, operator, "REQUIRED_SLOT_MISSING")
    if not accepted_inputs.complete:
        selected = [
            values[0]
            for requirement_id in accepted_inputs.required_requirement_ids
            if (values := options.get(requirement_id, []))
        ]
        return _partial_result(
            plan,
            operator,
            "REQUIRED_SLOT_MISSING",
            operand_pointers=[_binding_pointer(value) for value in selected],
            filled_slots=list(accepted_inputs.filled_requirement_ids),
        )
    if operator == "DIVIDE_EVIDENCE_VALUES":
        # The quantity composer is retained as a value implementation, but its
        # candidate universe is now the accepted operand set rather than the
        # wider retrieval pool.
        from milai.application.quantity_composition import (
            compose_divide_evidence_values,
        )

        return compose_divide_evidence_values(
            plan,
            accepted_inputs.governed_sources(),
        )
    return execute_query_operator(plan, accepted_inputs.governed_sources())


def execute_binding_backed_query_operator(
    plan: QueryPlan,
    results: Sequence[Mapping[str, Any]],
    spans: Sequence[EvidenceSpan],
    interpretations: Sequence[EvidenceInterpretationCandidate],
    bindings: Sequence[RequirementBinding],
) -> dict[str, Any] | None:
    accepted_inputs = build_accepted_operator_inputs(
        plan,
        results,
        spans,
        interpretations,
        bindings,
    )
    result = _execute_binding_backed_query_operator(
        plan,
        accepted_inputs,
    )
    if result is None:
        return None
    payload = {
        **result,
        "accepted_input_requirement_ids": list(
            accepted_inputs.filled_requirement_ids
        ),
        "accepted_input_evidence_ids": sorted(
            {item.span.source_evidence_id for item in accepted_inputs.operands}
        ),
    }
    if accepted_inputs.complete:
        payload["operand_authority"] = "ACCEPTED_BINDING_ONLY"
    return payload


def _execute_binding_backed_query_operator(
    plan: QueryPlan,
    accepted_inputs: AcceptedOperatorInputs,
) -> dict[str, Any] | None:
    """Execute value operators from typed MATCH bindings when supported.

    Retrieval candidates and operator operands are deliberately separate
    concepts. Legacy value implementations may be reused only after this
    boundary has reduced their inputs to governed MATCH Binding sources.
    """

    operator = plan.operator
    supported = (
        operator
        in {
            "LATEST_VALID_STATE",
            "COMPARE_EVENT_IDENTITY",
            "COMPOSE_STATE",
        }
        or (
            operator == "TEMPORAL_BEFORE_AFTER"
            and plan.operator_arguments.get("target_mode") == "binary_ordering"
        )
        or (
            operator == "TEMPORAL_DISTANCE"
            and plan.operator_arguments.get("distance_mode") == "between_events"
        )
    )
    if not supported:
        return _execute_legacy_operator_from_accepted_inputs(plan, accepted_inputs)
    assert operator is not None
    if not _typed_slots_valid(plan, operator):
        return _abstain(plan, operator, "OPERATOR_SLOT_SCHEMA_INVALID")
    accepted_results = accepted_inputs.governed_sources()
    if any(item.get("open_issue_ids") for item in accepted_results):
        return _abstain(plan, operator, "OPEN_ISSUE_PRESENT")
    if not _compatible_scope(plan, accepted_results):
        return _abstain(plan, operator, "SCOPE_INCONSISTENT")
    options = accepted_inputs.options()
    if operator == "LATEST_VALID_STATE":
        return _formation_state_result(plan, options)
    if operator == "COMPARE_EVENT_IDENTITY":
        return _formation_event_identity_result(plan, options)
    if operator == "TEMPORAL_BEFORE_AFTER":
        return _formation_temporal_order_result(plan, options)
    if operator == "COMPOSE_STATE":
        return _formation_composed_state_result(plan, options)

    required_slots = _required_slot_ids(plan)
    if len(required_slots) != 2:
        return _abstain(plan, "TEMPORAL_DISTANCE", "OPERATOR_SLOT_SCHEMA_INVALID")
    temporal_options: dict[
        str,
        list[
            tuple[
                EvidenceSpan,
                EvidenceInterpretationCandidate,
                Mapping[str, Any],
            ]
        ],
    ] = {slot: [] for slot in required_slots}
    for operand in accepted_inputs.operands:
        if operand.requirement_id not in temporal_options:
            continue
        interpretation = operand.interpretation
        if (
            interpretation.kind != "EVENT"
            or interpretation.event_time is None
            or interpretation.event_time.start is None
        ):
            continue
        temporal_options[operand.requirement_id].append(
            (operand.span, interpretation, operand.source)
        )

    def option_order(
        option: tuple[EvidenceSpan, EvidenceInterpretationCandidate, Mapping[str, Any]],
    ) -> tuple[int, datetime, str, int, str]:
        span, interpretation, _item = option
        basis_rank = 0 if interpretation.time_basis == "EXPLICIT_EVENT_TIME" else 1
        source_time = span.source_timestamp or datetime.max.replace(
            tzinfo=plan.time_reference.tzinfo
        )
        return (
            basis_rank,
            source_time,
            span.source_turn_ref,
            span.start,
            interpretation.interpretation_id,
        )

    ordered = {
        slot: sorted(slot_options, key=option_order)
        for slot, slot_options in temporal_options.items()
    }
    pairs = [
        (left, right)
        for left in ordered[required_slots[0]]
        for right in ordered[required_slots[1]]
        if left[0].span_id != right[0].span_id
    ]
    if not pairs:
        pointers: list[dict[str, Any]] = []
        filled_slots: list[str] = []
        claimed_spans: set[str] = set()
        for slot in required_slots:
            selected = next(
                (value for value in ordered[slot] if value[0].span_id not in claimed_spans),
                None,
            )
            if selected is None:
                continue
            span, interpretation, item = selected
            assert interpretation.event_time is not None
            assert interpretation.event_time.start is not None
            claimed_spans.add(span.span_id)
            pointers.append(
                _pointer(
                    item,
                    derived_time=interpretation.event_time.start,
                    time_basis=str(interpretation.time_basis),
                    source_span=span.text,
                )
            )
            filled_slots.append(slot)
        if pointers:
            return _partial_result(
                plan,
                "TEMPORAL_DISTANCE",
                "TIME_UNCERTAIN",
                operand_pointers=pointers,
                filled_slots=filled_slots,
            )
        return _abstain(plan, "TEMPORAL_DISTANCE", "TIME_UNCERTAIN")

    left, right = min(
        pairs,
        key=lambda pair: (option_order(pair[0]), option_order(pair[1])),
    )
    left_span, left_interpretation, left_item = left
    right_span, right_interpretation, right_item = right
    left_time = left_interpretation.event_time
    right_time = right_interpretation.event_time
    assert left_time is not None
    assert right_time is not None
    assert left_time.start is not None
    assert right_time.start is not None
    unit = str(plan.operator_arguments.get("distance_unit", "day"))
    value = _distance_value(
        left_time.start,
        right_time.start,
        unit,
    )
    return _base_success(
        plan,
        "TEMPORAL_DISTANCE",
        [left_item, right_item],
        value=value,
        unit=f"{unit}s",
        operand_pointers=[
            _pointer(
                left_item,
                derived_time=left_time.start,
                time_basis=str(left_interpretation.time_basis),
                source_span=left_span.text,
            ),
            _pointer(
                right_item,
                derived_time=right_time.start,
                time_basis=str(right_interpretation.time_basis),
                source_span=right_span.text,
            ),
        ],
    )


def _query_reference_time_operand(plan: QueryPlan) -> datetime:
    raw_value = plan.operator_arguments.get("query_reference_time")
    if not isinstance(raw_value, str):
        return plan.time_reference
    try:
        value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return plan.time_reference
    return value if value.utcoffset() is not None else plan.time_reference


def _target_time(plan: QueryPlan) -> datetime | None:
    mode = plan.operator_arguments.get("target_mode")
    if mode == "relative_point":
        target_time = plan.operator_arguments.get("target_time")
        if isinstance(target_time, str):
            try:
                parsed = datetime.fromisoformat(target_time.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.utcoffset() is not None else None
        count = _integer(plan.operator_arguments.get("offset_count"))
        unit = plan.operator_arguments.get("offset_unit")
        if count is None or not isinstance(unit, str):
            return None
        return _shift(plan.time_reference, count, unit)
    if mode == "last_weekday":
        weekday = plan.operator_arguments.get("target_weekday")
        if not isinstance(weekday, str) or weekday not in _WEEKDAYS:
            return None
        delta = (plan.time_reference.weekday() - _WEEKDAYS[weekday]) % 7 or 7
        return plan.time_reference - timedelta(days=delta)
    return None


def _base_success(
    plan: QueryPlan,
    operator: QueryOperator,
    operands: Sequence[Mapping[str, Any]],
    *,
    value: Any,
    unit: str | None = None,
    operand_pointers: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    required_slots = _required_slot_ids(plan)
    return {
        "status": "OK",
        "kind": "DERIVED_QUERY_RESULT",
        "operator": operator,
        "value": value,
        "unit": unit,
        "route_reason": plan.operator_arguments["route_reason"],
        "slot_schema_version": plan.operator_arguments["slot_schema_version"],
        "operands": (
            [dict(pointer) for pointer in operand_pointers]
            if operand_pointers is not None
            else [_pointer(item) for item in operands]
        ),
        "date_boundary": str(plan.operator_arguments.get("date_boundary", "inclusive")),
        "hidden_model_calls": 0,
        "canonical_mutation": False,
        "completeness": {
            "required_slots": required_slots,
            "filled_slots": required_slots,
            "unresolved_reasons": [],
        },
    }


def _required_slot_ids(plan: QueryPlan) -> list[str]:
    if plan.memory_query_ir is not None:
        slots = [
            requirement.slot_id
            for requirement in plan.memory_query_ir.requirements
            if requirement.required
        ]
        if slots:
            return slots
    count = plan.operator_arguments.get("required_operand_count")
    if isinstance(count, int) and count > 0:
        return [f"OPERAND_{index + 1}" for index in range(count)]
    return []


def execute_query_operator(
    plan: QueryPlan, results: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    operator = plan.operator
    if operator is None:
        return None
    if not _typed_slots_valid(plan, operator):
        return _abstain(plan, operator, "OPERATOR_SLOT_SCHEMA_INVALID")
    if any(item.get("open_issue_ids") for item in results):
        return _abstain(plan, operator, "OPEN_ISSUE_PRESENT")
    if not _compatible_scope(plan, results):
        return _abstain(plan, operator, "SCOPE_INCONSISTENT")
    if not results:
        return _abstain(plan, operator, "OPERAND_MISSING")

    timed = sorted(
        (item for item in results if _timestamp(item) is not None),
        key=lambda item: (_timestamp(item), _item_identity(item)),
    )
    if operator == "LATEST_VALID_STATE":
        if not timed:
            # A single current canonical Claim has already been selected by the
            # bitemporal Canonical Gate. An omitted ``valid_time_from`` denotes
            # an unbounded current interval, so it does not make that one value
            # temporally ambiguous. Multiple untimed candidates remain unsafe.
            canonical = [item for item in results if item.get("claim_version_id") is not None]
            if len(canonical) == 1:
                latest = canonical[0]
            else:
                ranked = sorted(
                    (
                        (_latest_state_overlap(plan, item), _item_identity(item), item)
                        for item in canonical
                    ),
                    key=lambda candidate: (candidate[0], candidate[1]),
                    reverse=True,
                )
                if (
                    not ranked
                    or ranked[0][0] <= 0
                    or (len(ranked) > 1 and ranked[0][0] == ranked[1][0])
                ):
                    return _abstain(plan, operator, "TIME_UNCERTAIN")
                latest = ranked[0][2]
        else:
            latest = _best_relevant_timed(plan, timed) or timed[-1]
        value = _latest_state_value(plan, latest)
        if value is None:
            return _abstain(plan, operator, "STATE_VALUE_MISSING")
        return _base_success(
            plan,
            operator,
            [latest],
            value=value,
        )
    if operator == "TEMPORAL_BEFORE_AFTER":
        if plan.operator_arguments.get("target_mode") == "binary_ordering":
            pair = _binary_anchor_pair(plan, results)
            if pair is None:
                return _abstain(plan, operator, "OPERAND_MISSING")
            left, right = pair
            if left.at == right.at:
                return _abstain(plan, operator, "TIME_UNCERTAIN")
            selected = left if left.at < right.at else right
            return _base_success(
                plan,
                operator,
                [left.item, right.item],
                value={"selected": selected.sentence, "ordering": "earliest"},
                operand_pointers=[
                    _pointer(
                        left.item,
                        derived_time=left.at,
                        time_basis=left.basis,
                        source_span=left.sentence,
                    ),
                    _pointer(
                        right.item,
                        derived_time=right.at,
                        time_basis=right.basis,
                        source_span=right.sentence,
                    ),
                ],
            )
        target = _target_time(plan)
        if target is not None:
            time_axis = str(plan.operator_arguments.get("time_axis", "EVENT_TIME"))
            events = (
                _source_observation_events(plan, results)
                if time_axis == "SOURCE_OBSERVED_TIME"
                else _dated_events(plan, results, allow_unmatched=True)
            )
            if not events:
                return _abstain(plan, operator, "TIME_UNCERTAIN")
            selected_event = min(
                events,
                key=lambda event: (
                    abs((event.at - target).total_seconds()),
                    -event.score,
                    event.result_index,
                    event.sentence_index,
                ),
            )
            date_distance_days = abs((selected_event.at.date() - target.date()).days)
            if date_distance_days != 0:
                return _abstain(plan, operator, "RELATIVE_POINT_NOT_FOUND")
            return _base_success(
                plan,
                operator,
                [selected_event.item],
                value={
                    "selected": selected_event.sentence,
                    "relation": "at_relative_point",
                    "target_date": target.date().isoformat(),
                    "selected_date": selected_event.at.date().isoformat(),
                    "date_distance_days": date_distance_days,
                },
                operand_pointers=[
                    _pointer(
                        selected_event.item,
                        derived_time=selected_event.at,
                        time_basis=selected_event.basis,
                        source_span=selected_event.sentence,
                        time_axis=time_axis,
                    )
                ],
            )
        if len(timed) < 2:
            return _abstain(plan, operator, "OPERAND_MISSING")
        direction = str(plan.operator_arguments.get("direction", "before"))
        selected_item = timed[-2] if direction == "before" else timed[-1]
        anchor_item = timed[-1] if direction == "before" else timed[0]
        return _base_success(
            plan,
            operator,
            [selected_item, anchor_item],
            value={
                "selected": _display_value(selected_item, _query_terms(plan)),
                "direction": direction,
            },
        )
    if operator == "TEMPORAL_DISTANCE":
        anchors = _event_anchor_terms(plan)
        if anchors is not None:
            anchored_pair = _binary_anchor_pair(plan, results)
            events = []
        else:
            anchored_pair = None
            events = _dated_events(plan, results)
        mode = plan.operator_arguments.get("distance_mode")
        unit = str(plan.operator_arguments.get("distance_unit", "day"))
        if mode == "from_reference":
            if not events:
                return _abstain(plan, operator, "TIME_UNCERTAIN")
            anchor_event = events[0]
            distance_value = _distance_value(
                anchor_event.at,
                _query_reference_time_operand(plan),
                unit,
            )
            return _base_success(
                plan,
                operator,
                [anchor_event.item],
                value=distance_value,
                unit=f"{unit}s",
                operand_pointers=[
                    _pointer(
                        anchor_event.item,
                        derived_time=anchor_event.at,
                        time_basis=anchor_event.basis,
                        source_span=anchor_event.sentence,
                    )
                ],
            )
        pair = anchored_pair or _distinct_anchor_pair(events)
        if pair is None:
            if anchors is not None:
                operand_pointers, filled_slots = _partial_anchor_operands(plan, results)
                if operand_pointers:
                    return _partial_result(
                        plan,
                        operator,
                        "TIME_UNCERTAIN",
                        operand_pointers=operand_pointers,
                        filled_slots=filled_slots,
                    )
            return _abstain(plan, operator, "TIME_UNCERTAIN")
        left, right = pair
        distance_value = _distance_value(left.at, right.at, unit)
        return _base_success(
            plan,
            operator,
            [left.item, right.item],
            value=distance_value,
            unit=f"{unit}s",
            operand_pointers=[
                _pointer(
                    left.item,
                    derived_time=left.at,
                    time_basis=left.basis,
                    source_span=left.sentence,
                ),
                _pointer(
                    right.item,
                    derived_time=right.at,
                    time_basis=right.basis,
                    source_span=right.sentence,
                ),
            ],
        )
    if operator == "COUNT_DISTINCT":
        query_terms = _query_terms(plan)
        required_qualifiers = _required_qualifiers(plan)
        count_candidates = [
            (item, count_value)
            for item in results
            if _timestamp(item) is not None
            if (
                count_value := _latest_state_count_value(
                    item,
                    query_terms,
                    required_qualifiers,
                )
            )
            is not None
            and (not query_terms or _item_query_overlap(item, query_terms) > 0)
        ]
        if not count_candidates:
            return _abstain(plan, operator, "NUMERIC_OPERAND_MISSING")
        count_item, count_value = max(
            count_candidates,
            key=lambda candidate: (
                _timestamp(candidate[0]),
                _item_query_overlap(candidate[0], query_terms),
                _item_identity(candidate[0]),
            ),
        )
        return _base_success(plan, operator, [count_item], value=count_value)

    numeric = [
        (item, numeric_value) for item in results if (numeric_value := _numeric(item)) is not None
    ]
    if operator == "SUM_VALUES":
        minimum_raw = plan.operator_arguments["minimum_operand_count"]
        assert isinstance(minimum_raw, int) and not isinstance(minimum_raw, bool)
        minimum = minimum_raw
        if len(numeric) < minimum:
            return _abstain(plan, operator, "NUMERIC_OPERAND_MISSING")
        units = {value[1] for _item, value in numeric if value[1] is not None}
        if len(units) > 1:
            return _abstain(plan, operator, "UNIT_INCONSISTENT")
        total = sum((value[0] for _item, value in numeric), Decimal(0))
        return _base_success(
            plan,
            operator,
            [item for item, _value in numeric],
            value=float(total),
            unit=next(iter(units), None),
        )
    if operator == "COMPARE_EVENTS":
        if len(numeric) < 2:
            return _abstain(plan, operator, "NUMERIC_OPERAND_MISSING")
        if len(numeric) > 2:
            return _abstain(plan, operator, "OPERAND_AMBIGUOUS")
        units = {value[1] for _item, value in numeric if value[1] is not None}
        if len(units) > 1:
            return _abstain(plan, operator, "UNIT_INCONSISTENT")
        ordered = sorted(
            numeric,
            key=lambda pair: (
                _timestamp(pair[0]) or datetime.min.replace(tzinfo=plan.time_reference.tzinfo),
                _item_identity(pair[0]),
            ),
        )
        difference = ordered[-1][1][0] - ordered[0][1][0]
        return _base_success(
            plan,
            operator,
            [ordered[0][0], ordered[-1][0]],
            value=float(difference),
            unit=next(iter(units), None),
        )
    if operator in {"DIVIDE_EVIDENCE_VALUES", "TEMPORAL_COUNT_DISTINCT"}:
        return _abstain(plan, operator, "RAW_EVIDENCE_COMPOSER_REQUIRED")
    raise ValueError(f"unsupported query operator: {operator}")
