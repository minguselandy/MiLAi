from __future__ import annotations

import ast
import hashlib
import json
import math
import tokenize
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from io import StringIO
from typing import Any

SAFETY_LIMITS = {
    "max_response_bytes": 32_768,
    "max_calls_per_step": 32,
    "max_keyword_arguments_per_call": 64,
    "max_literal_depth": 12,
    "max_ast_nodes": 4_096,
    "max_aggregate_container_items": 2_048,
    "max_container_items": 256,
    "max_string_bytes": 16_384,
    "max_integer_digits": 256,
}


class SafetyGateError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(slots=True)
class _Budget:
    nodes: int = 0
    container_items: int = 0

    def node(self) -> None:
        self.nodes += 1
        if self.nodes > SAFETY_LIMITS["max_ast_nodes"]:
            raise SafetyGateError("AST_NODE_LIMIT", "AST node budget exceeded")

    def items(self, count: int) -> None:
        if count > SAFETY_LIMITS["max_container_items"]:
            raise SafetyGateError(
                "CONTAINER_ITEM_LIMIT", "single container item budget exceeded"
            )
        self.container_items += count
        if self.container_items > SAFETY_LIMITS["max_aggregate_container_items"]:
            raise SafetyGateError(
                "AGGREGATE_ITEM_LIMIT", "aggregate container item budget exceeded"
            )


@dataclass(frozen=True, slots=True)
class GateAttestation:
    canonical_calls: tuple[Mapping[str, Any], ...]
    execution_calls: tuple[str, ...]
    raw_response_sha256: str


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reject_comments(source: str, stage: str) -> None:
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        if any(token.type == tokenize.COMMENT for token in tokens):
            raise SafetyGateError(
                f"{stage}_COMMENT_FORBIDDEN", "comments are not executable calls"
            )
    except (IndentationError, tokenize.TokenError) as exc:
        raise SafetyGateError(f"{stage}_TOKENIZE_FAILURE", str(exc)) from exc


def _parse_eval(source: str, stage: str) -> ast.Expression:
    if not isinstance(source, str):
        raise SafetyGateError(f"{stage}_NON_STRING", "source must be a string")
    size = len(source.encode("utf-8"))
    if size == 0 or size > SAFETY_LIMITS["max_response_bytes"]:
        raise SafetyGateError(
            f"{stage}_SIZE_BOUNDARY", f"source size {size} is outside the boundary"
        )
    _reject_comments(source, stage)
    try:
        parsed = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, MemoryError) as exc:
        raise SafetyGateError(f"{stage}_SYNTAX", str(exc)) from exc
    if not isinstance(parsed, ast.Expression):
        raise SafetyGateError(f"{stage}_EXPRESSION_REQUIRED", "not an expression")
    return parsed


def _constant(node: ast.Constant) -> Mapping[str, Any]:
    value = node.value
    if value is None:
        return {"type": "none", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        if len(str(abs(value))) > SAFETY_LIMITS["max_integer_digits"]:
            raise SafetyGateError("INTEGER_DIGIT_LIMIT", "integer is too large")
        return {"type": "int", "value": value}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SafetyGateError("NON_FINITE_FLOAT", "float must be finite")
        return {"type": "float", "value": value}
    if isinstance(value, str):
        if len(value.encode("utf-8")) > SAFETY_LIMITS["max_string_bytes"]:
            raise SafetyGateError("STRING_SIZE_LIMIT", "string literal is too large")
        return {"type": "str", "value": value}
    raise SafetyGateError(
        "UNSUPPORTED_CONSTANT",
        f"constant type {type(value).__name__} is not permitted",
    )


def _literal(node: ast.AST, *, depth: int, budget: _Budget) -> Mapping[str, Any]:
    budget.node()
    if depth > SAFETY_LIMITS["max_literal_depth"]:
        raise SafetyGateError("LITERAL_DEPTH_LIMIT", "literal nesting is too deep")
    if isinstance(node, ast.Constant):
        return _constant(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        if not isinstance(node.operand, ast.Constant) or isinstance(
            node.operand.value, bool
        ):
            raise SafetyGateError(
                "UNSAFE_UNARY_LITERAL", "only exact unary-minus numbers are permitted"
            )
        value = node.operand.value
        if not isinstance(value, (int, float)):
            raise SafetyGateError(
                "UNSAFE_UNARY_LITERAL", "only exact unary-minus numbers are permitted"
            )
        return _constant(ast.Constant(value=-value))
    if isinstance(node, (ast.List, ast.Tuple)):
        budget.items(len(node.elts))
        tag = "list" if isinstance(node, ast.List) else "tuple"
        return {
            "type": tag,
            "items": [
                _literal(item, depth=depth + 1, budget=budget) for item in node.elts
            ],
        }
    if isinstance(node, ast.Dict):
        budget.items(len(node.keys))
        pairs: list[tuple[str, Mapping[str, Any]]] = []
        seen: set[str] = set()
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            if key_node is None:
                raise SafetyGateError("DICT_UNPACK_FORBIDDEN", "dict unpack is unsafe")
            if not isinstance(key_node, ast.Constant) or not isinstance(
                key_node.value, str
            ):
                raise SafetyGateError(
                    "DICT_KEY_TYPE", "dictionary keys must be string literals"
                )
            key = key_node.value
            if key in seen:
                raise SafetyGateError("DUPLICATE_DICT_KEY", f"duplicate key: {key}")
            if len(key.encode("utf-8")) > SAFETY_LIMITS["max_string_bytes"]:
                raise SafetyGateError("STRING_SIZE_LIMIT", "dict key is too large")
            seen.add(key)
            pairs.append(
                (key, _literal(value_node, depth=depth + 1, budget=budget))
            )
        return {
            "type": "dict",
            "items": [[key, value] for key, value in sorted(pairs)],
        }
    raise SafetyGateError(
        "NON_LITERAL_ARGUMENT",
        f"AST node {type(node).__name__} is not a permitted literal",
    )


def _canonical_call(
    node: ast.AST,
    *,
    exposed_function_names: frozenset[str],
    budget: _Budget,
) -> Mapping[str, Any]:
    budget.node()
    if not isinstance(node, ast.Call):
        raise SafetyGateError("CALL_REQUIRED", "every list element must be a call")
    if not isinstance(node.func, ast.Name):
        raise SafetyGateError(
            "BARE_FUNCTION_NAME_REQUIRED", "attribute and computed calls are forbidden"
        )
    name = node.func.id
    if name not in exposed_function_names:
        raise SafetyGateError("FUNCTION_NOT_EXPOSED", f"function is not exposed: {name}")
    if node.args:
        raise SafetyGateError(
            "POSITIONAL_ARGUMENT_FORBIDDEN",
            "official decoding drops positional arguments",
        )
    if len(node.keywords) > SAFETY_LIMITS["max_keyword_arguments_per_call"]:
        raise SafetyGateError("KEYWORD_LIMIT", "too many keyword arguments")
    keywords: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for keyword in node.keywords:
        if keyword.arg is None:
            raise SafetyGateError("KEYWORD_UNPACK_FORBIDDEN", "**kwargs is forbidden")
        if keyword.arg in seen:
            raise SafetyGateError(
                "DUPLICATE_KEYWORD", f"duplicate keyword: {keyword.arg}"
            )
        seen.add(keyword.arg)
        keywords.append(
            (
                keyword.arg,
                _literal(keyword.value, depth=1, budget=budget),
            )
        )
    return {
        "function": name,
        "keywords": [[key, value] for key, value in sorted(keywords)],
    }


def _raw_calls(
    raw_response: str, exposed_function_names: frozenset[str]
) -> tuple[Mapping[str, Any], ...]:
    stripped = raw_response.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        raise SafetyGateError(
            "RAW_EXPLICIT_LIST_REQUIRED",
            "response must be only an explicit top-level list",
        )
    expression = _parse_eval(raw_response, "RAW")
    if not isinstance(expression.body, ast.List):
        raise SafetyGateError(
            "RAW_EXPLICIT_LIST_REQUIRED", "top-level expression is not a list"
        )
    if len(expression.body.elts) > SAFETY_LIMITS["max_calls_per_step"]:
        raise SafetyGateError("CALL_LIMIT", "too many calls in one response")
    budget = _Budget()
    return tuple(
        _canonical_call(
            item,
            exposed_function_names=exposed_function_names,
            budget=budget,
        )
        for item in expression.body.elts
    )


def _decoded_calls(
    execution_calls: Any, exposed_function_names: frozenset[str]
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(execution_calls, list) or any(
        not isinstance(item, str) for item in execution_calls
    ):
        raise SafetyGateError(
            "DECODED_LIST_OF_STRINGS_REQUIRED",
            "official decoder must return a list of execution strings",
        )
    if len(execution_calls) > SAFETY_LIMITS["max_calls_per_step"]:
        raise SafetyGateError("DECODED_CALL_LIMIT", "decoder returned too many calls")
    canonical: list[Mapping[str, Any]] = []
    budget = _Budget()
    for source in execution_calls:
        expression = _parse_eval(source, "DECODED")
        canonical.append(
            _canonical_call(
                expression.body,
                exposed_function_names=exposed_function_names,
                budget=budget,
            )
        )
    return tuple(canonical)


def attest_dual_gate(
    raw_response: str,
    exposed_function_names: Sequence[str] | set[str] | frozenset[str],
    official_decoder: Callable[[str], Any],
) -> GateAttestation:
    exposed = frozenset(exposed_function_names)
    if not exposed or any(
        not isinstance(name, str) or not name.isidentifier() for name in exposed
    ):
        raise SafetyGateError(
            "INVALID_EXPOSURE_SET", "exposed functions must be identifiers"
        )
    raw = _raw_calls(raw_response, exposed)
    try:
        execution_calls = official_decoder(raw_response)
    except Exception as exc:
        raise SafetyGateError("OFFICIAL_DECODER_FAILURE", str(exc)) from exc
    decoded = _decoded_calls(execution_calls, exposed)
    if raw != decoded:
        raise SafetyGateError(
            "RAW_DECODED_CANONICAL_MISMATCH",
            "official decoder changed typed call semantics",
        )
    return GateAttestation(
        canonical_calls=raw,
        execution_calls=tuple(execution_calls),
        raw_response_sha256=_sha256_text(raw_response),
    )


@dataclass(slots=True)
class SafeTurnStateMachine:
    exposed_function_names: frozenset[str]
    official_decoder: Callable[[str], Any]
    executor: Callable[[Sequence[str]], Sequence[str]]
    max_execution_steps: int = 20
    execution_steps: int = 0
    complete: bool = False
    failure_code: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def process_native_step(
        self, raw_response: str, native_receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self.complete or self.failure_code is not None:
            raise SafetyGateError(
                "TERMINAL_STATE", "cannot process a step after turn termination"
            )
        record: dict[str, Any] = {
            "native_step_index": len(self.records),
            "native_receipt": dict(native_receipt),
            "raw_response_sha256": _sha256_text(raw_response),
            "raw_response_size": len(raw_response.encode("utf-8")),
            "execution_permitted": False,
            "tool_results_emitted": False,
        }
        self.records.append(record)
        if self.execution_steps >= self.max_execution_steps:
            self.failure_code = "STEP_LIMIT_BOUNDARY_FORCE_QUIT"
            record["status"] = self.failure_code
            return record
        try:
            attestation = attest_dual_gate(
                raw_response, self.exposed_function_names, self.official_decoder
            )
        except SafetyGateError as exc:
            self.failure_code = exc.code
            record["status"] = "SAFETY_GATE_FAILURE"
            record["failure_code"] = exc.code
            return record
        record["canonical_calls"] = list(attestation.canonical_calls)
        record["decoded_execution_calls"] = list(attestation.execution_calls)
        record["decoded_execution_call_count"] = len(attestation.execution_calls)
        if not attestation.execution_calls:
            self.complete = True
            record["status"] = "TURN_COMPLETE_EXPLICIT_EMPTY_LIST"
            return record
        record["execution_permitted"] = True
        try:
            results = self.executor(attestation.execution_calls)
        except Exception as exc:
            self.failure_code = "EXECUTOR_EXCEPTION"
            record["status"] = self.failure_code
            record["executor_error_type"] = type(exc).__name__
            return record
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            self.failure_code = "EXECUTOR_RESULT_SHAPE_FAILURE"
            record["status"] = self.failure_code
            return record
        materialized = list(results)
        if len(materialized) != len(attestation.execution_calls) or any(
            not isinstance(item, str) for item in materialized
        ):
            self.failure_code = "EXECUTOR_RESULT_SHAPE_FAILURE"
            record["status"] = self.failure_code
            return record
        self.execution_steps += 1
        record["status"] = "EXECUTED_ATTESTED_CALLS"
        record["tool_results_emitted"] = True
        record["tool_result_sha256"] = [_sha256_text(item) for item in materialized]
        record["execution_step_count_after"] = self.execution_steps
        return {**record, "tool_results": materialized}


def _function_docs(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SafetyGateError("INVALID_FUNCTION_DOCS", f"{label} must be a list")
    docs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise SafetyGateError(
                "INVALID_FUNCTION_DOCS", f"{label} entries must be objects"
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.isidentifier():
            raise SafetyGateError(
                "INVALID_FUNCTION_NAME", f"invalid function doc name in {label}"
            )
        docs.append(item)
    return docs


def build_case_turn_schedule(
    populated_case: Mapping[str, Any],
    additional_function_prompt_template: str,
) -> dict[str, Any]:
    questions = populated_case.get("question")
    if not isinstance(questions, list) or not questions:
        raise SafetyGateError("INVALID_QUESTION_TURNS", "question turns are required")
    initial_docs = _function_docs(populated_case.get("function"), "initial functions")
    initial_names = [item["name"] for item in initial_docs]
    if len(initial_names) != len(set(initial_names)):
        raise SafetyGateError("DUPLICATE_FUNCTION_DOC", "duplicate initial function")
    holdout = populated_case.get("missed_function", {})
    if not isinstance(holdout, dict):
        raise SafetyGateError("INVALID_HOLDOUT_MAP", "missed_function must be a map")
    reveal_by_turn: dict[int, list[dict[str, Any]]] = {}
    all_names = set(initial_names)
    for raw_index, raw_docs in holdout.items():
        if not isinstance(raw_index, str) or not raw_index.isdigit():
            raise SafetyGateError("INVALID_HOLDOUT_TURN", "holdout turn must be numeric")
        turn_index = int(raw_index)
        if turn_index < 0 or turn_index >= len(questions):
            raise SafetyGateError("INVALID_HOLDOUT_TURN", "holdout turn out of range")
        docs = _function_docs(raw_docs, f"holdout turn {turn_index}")
        if not docs:
            raise SafetyGateError("EMPTY_HOLDOUT", "holdout reveal cannot be empty")
        names = [item["name"] for item in docs]
        if len(names) != len(set(names)) or all_names.intersection(names):
            raise SafetyGateError(
                "DUPLICATE_FUNCTION_DOC", "function exposure must be monotonic and unique"
            )
        all_names.update(names)
        reveal_by_turn[turn_index] = docs
    exposed = set(initial_names)
    turns: list[dict[str, Any]] = []
    for turn_index, messages in enumerate(questions):
        if not isinstance(messages, list):
            raise SafetyGateError(
                "INVALID_QUESTION_TURN", f"turn {turn_index} must be a message list"
            )
        revealed_docs = reveal_by_turn.get(turn_index, [])
        if revealed_docs:
            if messages:
                raise SafetyGateError(
                    "HOLDOUT_TURN_NOT_EMPTY",
                    "official missed-function turns must have no user message",
                )
            effective_messages = [
                {
                    "role": "user",
                    "content": additional_function_prompt_template.format(
                        functions=revealed_docs
                    ),
                }
            ]
            exposed.update(item["name"] for item in revealed_docs)
        else:
            effective_messages = messages
        turns.append(
            {
                "turn_index": turn_index,
                "revealed_function_names": sorted(
                    item["name"] for item in revealed_docs
                ),
                "exposed_function_names": sorted(exposed),
                "effective_messages": effective_messages,
                "effective_messages_sha256": hashlib.sha256(
                    json.dumps(
                        effective_messages,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )
    return {
        "initial_function_names": sorted(initial_names),
        "all_function_names": sorted(all_names),
        "turns": turns,
    }
