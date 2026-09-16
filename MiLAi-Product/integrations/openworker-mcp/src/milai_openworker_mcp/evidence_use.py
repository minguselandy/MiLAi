from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

EvidenceDisposition = Literal["ANSWERED", "PARTIAL", "INSUFFICIENT", "AMBIGUOUS"]
EvidenceUseMode = Literal["direct", "inventory", "grounded", "ledger", "model-native"]

_DISPOSITIONS = frozenset({"ANSWERED", "PARTIAL", "INSUFFICIENT", "AMBIGUOUS"})
_NUMBER_TYPES = (int, float)
_RESULT_NUMBER = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w.])"
)
_INVENTORY_POLICY = """Before answering a memory question, make a compact internal inventory of
the Reader-visible evidence aliases and distinct relevant members. Merge only
explicitly identical referents, use only visible aliases, and do not infer that a
partial set is complete. Return only the final user-facing answer."""
_GROUNDED_POLICY = """For this memory answer, return exactly one
GroundedEvidenceUseV01 JSON object. Copy aliases exactly from the Reader-visible
alias inventory; never invent or alter one. Put every grounding claim in support.
Answer the exact relation asked; if an entity, event, or arithmetic operand is
missing, do not substitute a nearby fact. For repeated values of the same fact, use
the latest explicit user update unless the question asks for an earlier state. For
current or latest state, chronology outranks narrative detail: a newer explicit
value supersedes an older value even when the older discussion is longer or more
detailed. For wording such as before, after, between, since, until, from, or to,
identify every
required relation endpoint and require visible support for each one before using
ANSWERED. A standalone duration, amount, or career length cannot substitute for an
unsupported endpoint; use a non-ANSWERED disposition instead. For
temporal questions, an observation timestamp plus explicit relative-time wording
such as "just", "today", or "yesterday" may locate the event. For elapsed-time
questions, treat explicit onset wording such as "started", "began", "just
downloaded", or "just signed up" as an event at that observation timestamp, then
calculate from it to the supplied reference date. Convert calendar dates to an
elapsed whole-day quantity before filling the schema; never put a date string or a
YYYYMMDD encoding in the expression. Express the result in the requested unit, for
example elapsed_days / 7 for weeks. Keep event and calendar-date descriptions in
support; for elapsed time, members contain only the converted numeric operands used
in the expression. A question asking for a count, percentage,
duration, numeric difference, or numeric comparison requires non-empty members and
calculation.
Use members only for distinct set/count/compare/arithmetic operands: merge repeated
mentions of one member into one entry and attach all of its supporting aliases. For
an ordinary non-arithmetic lookup, members must be [] and calculation must be
{\"expression\":null,\"result\":null}. For a count, use quantity 1 per distinct
member and an addition expression containing every quantity exactly once. For any
other calculation, give every member a numeric quantity, use only numeric literals
and +, -, *, / in expression, and put every member quantity in that expression. Put
only the numeric result in result. If there is
no calculation, both calculation fields must be null. The result may round the
expression to the decimal precision it displays. Use PARTIAL, INSUFFICIENT, or
AMBIGUOUS with a non-empty uncertainties list when the visible evidence does not
support a complete answer. answer_text is the final user-facing response; the Host
validates structure and arithmetic but does not certify truth or completeness."""
_LEDGER_POLICY = """This is pass one of a two-pass evidence-use workflow. Return
exactly one EvidenceLedgerV01 JSON object and do not answer the question yet. Scan
the entire Reader-visible Context for every distinct entity, event, update, and
numeric operand relevant to the exact question; do not stop at the first matching
alias. Copy aliases exactly and put every grounded claim in support. For repeated
values, record the visible chronology; a newer explicit value supersedes an older
one for current/latest questions even when the older discussion is more detailed.
For before, after, between, since, until, from, or to, record every required
endpoint and state a missing endpoint in uncertainties rather than substituting a
nearby duration or amount. Members are only distinct set/count/compare/arithmetic
operands. A count, percentage, duration, numeric difference, or numeric comparison
requires non-empty members and calculation. For a count use quantity 1 per member.
For any other calculation give every member a numeric quantity, use only numeric
literals and +, -, *, /, and put
every member quantity in the expression. Convert dates to elapsed whole-day
quantities before doing duration arithmetic. If calculation is present, both
expression and result are non-null; otherwise both are null. The Host validates
aliases, shape, and arithmetic but does not certify truth or completeness."""
_LEDGER_FINAL_POLICY = """This is pass two of a two-pass evidence-use workflow.
The JSON below is a provisional ledger whose aliases, shape, and arithmetic were
validated by the Host; its truth and completeness were not certified. Re-read the
original question and the entire Reader-visible Context, audit the ledger for
omitted distinct members, obsolete values, wrong temporal anchors, and wrong
relations. Independently verify that every endpoint required by before, after,
between, since, until, from, or to is visibly supported even when the provisional
ledger says ANSWERED. For a current or latest value, use visible chronology rather
than preferring an older, more detailed discussion. Then recompute any requested
count, total, percentage, comparison, or duration. Return exactly one
GroundedEvidenceUseV01 JSON object. Its answer_text must be the concise final
user-facing answer; do not describe this workflow."""


class EvidenceUseValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SupportAssertion:
    assertion: str
    evidence_aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceMember:
    member: str
    quantity: int | float | None
    evidence_aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceCalculation:
    expression: str | None
    result: str | int | float | None


@dataclass(frozen=True, slots=True)
class GroundedEvidenceUseV01:
    disposition: EvidenceDisposition
    answer_text: str
    support: tuple[SupportAssertion, ...]
    members: tuple[EvidenceMember, ...]
    calculation: EvidenceCalculation
    uncertainties: tuple[str, ...]

    @property
    def evidence_aliases(self) -> tuple[str, ...]:
        aliases = [alias for item in self.support for alias in item.evidence_aliases]
        aliases.extend(alias for item in self.members for alias in item.evidence_aliases)
        return tuple(dict.fromkeys(aliases))

    def to_api(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "answer_text": self.answer_text,
            "support": [
                {
                    "assertion": item.assertion,
                    "evidence_aliases": list(item.evidence_aliases),
                }
                for item in self.support
            ],
            "members": [
                {
                    "member": item.member,
                    "quantity": item.quantity,
                    "evidence_aliases": list(item.evidence_aliases),
                }
                for item in self.members
            ],
            "calculation": {
                "expression": self.calculation.expression,
                "result": self.calculation.result,
            },
            "uncertainties": list(self.uncertainties),
        }


@dataclass(frozen=True, slots=True)
class EvidenceLedgerV01:
    support: tuple[SupportAssertion, ...]
    members: tuple[EvidenceMember, ...]
    calculation: EvidenceCalculation
    uncertainties: tuple[str, ...]

    @property
    def evidence_aliases(self) -> tuple[str, ...]:
        aliases = [alias for item in self.support for alias in item.evidence_aliases]
        aliases.extend(alias for item in self.members for alias in item.evidence_aliases)
        return tuple(dict.fromkeys(aliases))

    def to_api(self) -> dict[str, Any]:
        grounded = GroundedEvidenceUseV01(
            disposition="PARTIAL",
            answer_text="provisional-ledger",
            support=self.support,
            members=self.members,
            calculation=self.calculation,
            uncertainties=self.uncertainties,
        ).to_api()
        return {
            name: grounded[name]
            for name in ("support", "members", "calculation", "uncertainties")
        }


def grounded_evidence_response_format(
    *, visible_aliases: Sequence[str] = ()
) -> dict[str, Any]:
    alias_items: dict[str, Any] = {"type": "string"}
    if visible_aliases:
        alias_items["enum"] = list(dict.fromkeys(visible_aliases))
    aliases = {
        "type": "array",
        "items": alias_items,
        "minItems": 1,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "GroundedEvidenceUseV01",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "disposition": {
                        "type": "string",
                        "enum": sorted(_DISPOSITIONS),
                    },
                    "answer_text": {"type": "string", "minLength": 1},
                    "support": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "assertion": {"type": "string", "minLength": 1},
                                "evidence_aliases": aliases,
                            },
                            "required": ["assertion", "evidence_aliases"],
                            "additionalProperties": False,
                        },
                    },
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "member": {"type": "string", "minLength": 1},
                                "quantity": {"type": ["number", "null"]},
                                "evidence_aliases": aliases,
                            },
                            "required": ["member", "quantity", "evidence_aliases"],
                            "additionalProperties": False,
                        },
                    },
                    "calculation": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": ["string", "null"]},
                            "result": {"type": ["string", "number", "null"]},
                        },
                        "required": ["expression", "result"],
                        "additionalProperties": False,
                    },
                    "uncertainties": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": [
                    "disposition",
                    "answer_text",
                    "support",
                    "members",
                    "calculation",
                    "uncertainties",
                ],
                "additionalProperties": False,
            },
        },
    }


def evidence_ledger_response_format(
    *, visible_aliases: Sequence[str] = ()
) -> dict[str, Any]:
    result = grounded_evidence_response_format(visible_aliases=visible_aliases)
    result["json_schema"]["name"] = "EvidenceLedgerV01"
    schema = result["json_schema"]["schema"]
    schema["properties"] = {
        name: schema["properties"][name]
        for name in ("support", "members", "calculation", "uncertainties")
    }
    schema["required"] = ["support", "members", "calculation", "uncertainties"]
    return result


def apply_evidence_use_protocol(
    payload: Mapping[str, Any],
    *,
    mode: EvidenceUseMode,
    visible_aliases: Sequence[str],
) -> dict[str, Any]:
    """Prepare one provider request; caller decides whether memory-answer gating applies."""

    result = dict(payload)
    if mode in {"direct", "model-native"}:
        return result
    messages = result.get("messages")
    if not isinstance(messages, list):
        raise EvidenceUseValidationError("EVIDENCE_USE_MESSAGES_INVALID")
    policy = (
        _INVENTORY_POLICY
        if mode == "inventory"
        else _LEDGER_POLICY
        if mode == "ledger"
        else _GROUNDED_POLICY
    )
    alias_inventory = ", ".join(visible_aliases) if visible_aliases else "(none)"
    instruction = f"{policy}\n\nReader-visible alias inventory: {alias_inventory}"
    result["messages"] = _messages_with_instruction(messages, instruction)
    if mode in {"grounded", "ledger"}:
        if result.get("response_format") is not None:
            raise EvidenceUseValidationError("EVIDENCE_USE_RESPONSE_FORMAT_CONFLICT")
        result["response_format"] = (
            evidence_ledger_response_format(visible_aliases=visible_aliases)
            if mode == "ledger"
            else grounded_evidence_response_format(visible_aliases=visible_aliases)
        )
    return result


def apply_ledger_final_protocol(
    payload: Mapping[str, Any],
    *,
    ledger: EvidenceLedgerV01,
    visible_aliases: Sequence[str],
) -> dict[str, Any]:
    result = dict(payload)
    messages = result.get("messages")
    if not isinstance(messages, list):
        raise EvidenceUseValidationError("EVIDENCE_USE_MESSAGES_INVALID")
    if result.get("response_format") is not None:
        raise EvidenceUseValidationError("EVIDENCE_USE_RESPONSE_FORMAT_CONFLICT")
    result.pop("response_format", None)
    result["response_format"] = grounded_evidence_response_format(
        visible_aliases=visible_aliases
    )
    serialized = json.dumps(
        ledger.to_api(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    instruction = (
        f"{_LEDGER_FINAL_POLICY}\n\n"
        "MILAI_PROVISIONAL_EVIDENCE_LEDGER_BEGIN\n"
        f"{serialized}\n"
        "MILAI_PROVISIONAL_EVIDENCE_LEDGER_END"
    )
    result["messages"] = _messages_with_instruction(messages, instruction)
    return result


def _messages_with_instruction(
    messages: Sequence[object], instruction: str
) -> list[object]:
    prepared_messages = list(messages)
    first = prepared_messages[0] if prepared_messages else None
    if (
        isinstance(first, Mapping)
        and first.get("role") == "system"
        and isinstance(first.get("content"), str)
    ):
        prepared_messages[0] = {
            **first,
            "content": f"{first['content']}\n\n{instruction}",
        }
    else:
        prepared_messages.insert(0, {"role": "system", "content": instruction})
    return prepared_messages


def parse_evidence_ledger(
    value: str | Mapping[str, Any],
    *,
    visible_aliases: Sequence[str],
) -> EvidenceLedgerV01:
    try:
        raw = json.loads(value) if isinstance(value, str) else dict(value)
    except json.JSONDecodeError as exc:
        raise EvidenceUseValidationError("EVIDENCE_USE_JSON_INVALID") from exc
    if set(raw) != {"support", "members", "calculation", "uncertainties"}:
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    visible = set(visible_aliases)
    support = _parse_support(raw["support"], visible)
    members = _parse_members(raw["members"], visible)
    return EvidenceLedgerV01(
        support=support,
        members=members,
        calculation=_parse_calculation(raw["calculation"], members),
        uncertainties=_nonempty_unique_strings(raw["uncertainties"]),
    )


def parse_grounded_evidence_use(
    value: str | Mapping[str, Any],
    *,
    visible_aliases: Sequence[str],
) -> GroundedEvidenceUseV01:
    try:
        raw = json.loads(value) if isinstance(value, str) else dict(value)
    except json.JSONDecodeError as exc:
        raise EvidenceUseValidationError("EVIDENCE_USE_JSON_INVALID") from exc
    required = {
        "disposition",
        "answer_text",
        "support",
        "members",
        "calculation",
        "uncertainties",
    }
    if set(raw) != required:
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    disposition = raw["disposition"]
    answer_text = raw["answer_text"]
    if (
        disposition not in _DISPOSITIONS
        or not isinstance(answer_text, str)
        or not answer_text.strip()
    ):
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    visible = set(visible_aliases)
    support = _parse_support(raw["support"], visible)
    members = _parse_members(raw["members"], visible)
    calculation = _parse_calculation(raw["calculation"], members)
    uncertainties = _nonempty_unique_strings(raw["uncertainties"])
    return GroundedEvidenceUseV01(
        disposition=disposition,
        answer_text=answer_text.strip(),
        support=support,
        members=members,
        calculation=calculation,
        uncertainties=uncertainties,
    )


def _parse_support(value: object, visible: set[str]) -> tuple[SupportAssertion, ...]:
    if not isinstance(value, list):
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    result: list[SupportAssertion] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"assertion", "evidence_aliases"}:
            raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
        assertion = raw["assertion"]
        if not isinstance(assertion, str) or not assertion.strip():
            raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
        result.append(
            SupportAssertion(
                assertion.strip(),
                _aliases(raw["evidence_aliases"], visible),
            )
        )
    return tuple(result)


def _parse_members(value: object, visible: set[str]) -> tuple[EvidenceMember, ...]:
    if not isinstance(value, list):
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    result: list[EvidenceMember] = []
    identities: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {
            "member",
            "quantity",
            "evidence_aliases",
        }:
            raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
        member = raw["member"]
        quantity = raw["quantity"]
        if not isinstance(member, str) or not member.strip() or not _number_or_none(quantity):
            raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
        identity = " ".join(member.casefold().split())
        if identity in identities:
            raise EvidenceUseValidationError("EVIDENCE_USE_MEMBER_DUPLICATE")
        identities.add(identity)
        result.append(
            EvidenceMember(
                member=member.strip(),
                quantity=quantity,
                evidence_aliases=_aliases(raw["evidence_aliases"], visible),
            )
        )
    return tuple(result)


def _parse_calculation(
    value: object,
    members: tuple[EvidenceMember, ...],
) -> EvidenceCalculation:
    if not isinstance(value, Mapping) or set(value) != {"expression", "result"}:
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    expression = value["expression"]
    result = value["result"]
    if expression is None and result is None:
        return EvidenceCalculation(None, None)
    if not isinstance(expression, str) or not expression.strip() or not (
        isinstance(result, str) or _number_or_none(result)
    ) or result is None:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    quantities = [member.quantity for member in members]
    if not quantities or any(quantity is None for quantity in quantities):
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_MEMBERS_INVALID")
    computed, literals = _evaluate_expression(expression)
    expected, displayed_places = _result_decimal(result)
    if computed != expected and round(computed, displayed_places) != expected:
        raise EvidenceUseValidationError("EVIDENCE_USE_ARITHMETIC_MISMATCH")
    member_literals = Counter(_decimal(quantity) for quantity in quantities)
    if not (Counter(literals) >= member_literals):
        raise EvidenceUseValidationError("EVIDENCE_USE_MEMBER_ARITHMETIC_MISMATCH")
    return EvidenceCalculation(expression.strip(), result)


def _aliases(value: object, visible: set[str]) -> tuple[str, ...]:
    aliases = _nonempty_unique_strings(value)
    if not aliases or not set(aliases).issubset(visible):
        raise EvidenceUseValidationError("EVIDENCE_USE_ALIAS_NOT_VISIBLE")
    return aliases


def _nonempty_unique_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise EvidenceUseValidationError("EVIDENCE_USE_SCHEMA_INVALID")
    return normalized


def _number_or_none(value: object) -> bool:
    return value is None or (
        isinstance(value, _NUMBER_TYPES)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _decimal(value: str | int | float | None) -> Decimal:
    if value is None or isinstance(value, bool):
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID") from exc
    if not parsed.is_finite():
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    return parsed


def _result_decimal(value: str | int | float) -> tuple[Decimal, int]:
    if not isinstance(value, str):
        parsed = _decimal(value)
        exponent = parsed.as_tuple().exponent
        if not isinstance(exponent, int):
            raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
        return parsed, max(0, -exponent)
    stripped = value.strip()
    matches = _RESULT_NUMBER.findall(stripped)
    if len(matches) != 1:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    token = matches[0]
    parsed = _decimal(token.replace(",", ""))
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int):
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    return parsed, max(0, -exponent)


def _evaluate_expression(expression: str) -> tuple[Decimal, tuple[Decimal, ...]]:
    if len(expression) > 256:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    literals: list[Decimal] = []

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, _NUMBER_TYPES)
            and not isinstance(node.value, bool)
        ):
            number = _decimal(node.value)
            literals.append(number)
            return number
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = evaluate(node.operand)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
            return left / right
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")

    try:
        result = evaluate(tree)
    except (InvalidOperation, OverflowError) as exc:
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID") from exc
    if not result.is_finite():
        raise EvidenceUseValidationError("EVIDENCE_USE_CALCULATION_INVALID")
    return result, tuple(literals)
