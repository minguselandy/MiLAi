from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

MAX_OFFICIAL_STEPS = 20
DEFAULT_TOOL_RESULT_BYTES_MAX = 4096
DEFAULT_ROLLING_SUMMARY_BYTES_MAX = 8192
DEFAULT_NO_PROGRESS_LIMIT = 2
DECISIONS = frozenset({"REQUIRED", "OPTIONAL", "NO_CALL"})


class ToolLoopError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _compact_value(value: object, *, depth: int = 0) -> object:
    if depth > 6:
        raise ToolLoopError("TOOL_RESULT_DEPTH_LIMIT", "tool result nesting exceeds six")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        encoded = value.encode()
        if len(encoded) <= 512:
            return value
        prefix = encoded[:512].decode(errors="ignore")
        return {
            "truncated_text": prefix,
            "original_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise ToolLoopError("TOOL_RESULT_FIELD_LIMIT", "tool result has too many fields")
        return {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        materialized = list(value)
        prefix = materialized[:32]
        result: dict[str, object] = {
            "items": [_compact_value(item, depth=depth + 1) for item in prefix],
            "count": len(materialized),
        }
        if len(materialized) > len(prefix):
            result["omitted_count"] = len(materialized) - len(prefix)
            result["full_sha256"] = _sha256(materialized)
        return result
    raise ToolLoopError("TOOL_RESULT_TYPE_FORBIDDEN", "tool result contains an unknown type")


def compact_tool_result(
    result: Mapping[str, Any],
    *,
    allowed_fields: Sequence[str],
    max_bytes: int = DEFAULT_TOOL_RESULT_BYTES_MAX,
) -> dict[str, Any]:
    if max_bytes <= 0:
        raise ToolLoopError("TOOL_RESULT_BYTE_LIMIT", "tool result limit must be positive")
    allowed = frozenset(allowed_fields)
    if not allowed or any(not isinstance(item, str) or not item for item in allowed):
        raise ToolLoopError("TOOL_RESULT_ALLOWLIST_INVALID", "field allowlist is invalid")
    selected = {
        str(key): _compact_value(value)
        for key, value in sorted(result.items())
        if key in allowed
    }
    envelope = {
        "schema": "milai.dg10.compact-tool-result.v1",
        "allowed_fields": sorted(allowed),
        "result": selected,
        "source_sha256": _sha256(result),
    }
    size = len(_canonical_bytes(envelope))
    if size > max_bytes:
        raise ToolLoopError(
            "TOOL_RESULT_BYTE_LIMIT",
            f"compacted tool result is {size} bytes, limit is {max_bytes}",
        )
    return envelope


def _state_patch(state: dict[str, Any], patch: Mapping[str, Any]) -> bool:
    before = _sha256(state)
    for key, value in patch.items():
        if not isinstance(key, str) or not key:
            raise ToolLoopError("STATE_PATCH_INVALID", "state key is invalid")
        state[key] = _compact_value(value)
    return _sha256(state) != before


@dataclass(slots=True)
class ToolLoopController:
    required_outcomes: frozenset[str]
    allowed_result_fields: frozenset[str]
    max_steps: int = MAX_OFFICIAL_STEPS
    max_tool_result_bytes: int = DEFAULT_TOOL_RESULT_BYTES_MAX
    max_summary_bytes: int = DEFAULT_ROLLING_SUMMARY_BYTES_MAX
    no_progress_limit: int = DEFAULT_NO_PROGRESS_LIMIT
    step_count: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    resolved_outcomes: set[str] = field(default_factory=set)
    terminal_code: str | None = None
    last_call_fingerprint: str | None = None
    no_progress_count: int = 0
    _fingerprints: list[str] = field(default_factory=list)
    _state_hashes: list[str] = field(default_factory=list)
    _result_hashes: list[str] = field(default_factory=list)
    _missing_function_recoveries: set[str] = field(default_factory=set)
    _missing_parameter_recoveries: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.max_steps != MAX_OFFICIAL_STEPS:
            raise ToolLoopError("STEP_LIMIT_DRIFT", "official max step must remain 20")
        if self.no_progress_limit < 1:
            raise ToolLoopError("NO_PROGRESS_POLICY_INVALID", "no-progress limit must be positive")
        if not self.allowed_result_fields:
            raise ToolLoopError("TOOL_RESULT_ALLOWLIST_INVALID", "field allowlist is empty")

    def triage(self, available_functions: Sequence[str]) -> str:
        if self.terminal_code is not None:
            return "NO_CALL"
        pending = self.required_outcomes - self.resolved_outcomes
        if pending:
            if not available_functions:
                raise ToolLoopError(
                    "MISSING_FUNCTION",
                    "required outcome remains but no function is available",
                )
            return "REQUIRED"
        return "OPTIONAL" if available_functions else "NO_CALL"

    def recover_missing_function(self, function_name: str) -> dict[str, Any]:
        if function_name in self._missing_function_recoveries:
            self.terminal_code = "MISSING_FUNCTION_UNRECOVERABLE"
            raise ToolLoopError(self.terminal_code, function_name)
        self._missing_function_recoveries.add(function_name)
        return {"action": "REQUEST_FUNCTION_EXPOSURE", "function_name": function_name}

    def recover_missing_parameter(self, function_name: str, parameter: str) -> dict[str, Any]:
        key = f"{function_name}:{parameter}"
        if key in self._missing_parameter_recoveries:
            self.terminal_code = "MISSING_PARAMETER_UNRECOVERABLE"
            raise ToolLoopError(self.terminal_code, key)
        self._missing_parameter_recoveries.add(key)
        return {
            "action": "REQUEST_PARAMETER",
            "function_name": function_name,
            "parameter": parameter,
        }

    def process_step(
        self,
        *,
        calls: Sequence[Mapping[str, Any]],
        tool_results: Sequence[Mapping[str, Any]],
        state_patch: Mapping[str, Any],
        resolved_outcomes: Sequence[str] = (),
    ) -> dict[str, Any]:
        if self.terminal_code is not None:
            raise ToolLoopError("TERMINAL_STATE", "cannot process after terminal state")
        if self.step_count >= self.max_steps:
            self.terminal_code = "STEP_LIMIT_BOUNDARY_FORCE_QUIT"
            raise ToolLoopError(self.terminal_code, "step 20 has already been consumed")
        if len(calls) != len(tool_results):
            raise ToolLoopError("CALL_RESULT_COUNT_MISMATCH", "each call requires one result")
        if not calls:
            if self.required_outcomes - self.resolved_outcomes:
                self.terminal_code = "REQUIRED_CALL_MISSING"
                raise ToolLoopError(self.terminal_code, "required outcomes remain")
            self.terminal_code = "SUCCESS_EXPLICIT_NO_CALL"
            return {
                "status": self.terminal_code,
                "step_count": self.step_count,
                "rolling_state_summary": self.rolling_state_summary(),
            }

        self.step_count += 1
        call_fingerprint = _sha256(list(calls))
        before_state = _sha256(self.state)
        changed = _state_patch(self.state, state_patch)
        for outcome in resolved_outcomes:
            if outcome not in self.required_outcomes:
                raise ToolLoopError("UNKNOWN_OUTCOME", outcome)
            self.resolved_outcomes.add(outcome)
        after_state = _sha256(self.state)
        changed = changed or before_state != after_state or bool(resolved_outcomes)
        compacted = [
            compact_tool_result(
                result,
                allowed_fields=self.allowed_result_fields,
                max_bytes=self.max_tool_result_bytes,
            )
            for result in tool_results
        ]
        result_hash = _sha256(compacted)

        if not changed and (
            call_fingerprint == self.last_call_fingerprint
            or result_hash in self._result_hashes
        ):
            self.no_progress_count += 1
        else:
            self.no_progress_count = 0
        self.last_call_fingerprint = call_fingerprint
        self._fingerprints.append(call_fingerprint)
        self._state_hashes.append(after_state)
        self._result_hashes.append(result_hash)

        if self.no_progress_count >= self.no_progress_limit:
            self.terminal_code = "NO_PROGRESS_BOUNDED_FAIL"
            raise ToolLoopError(self.terminal_code, "consecutive calls did not advance state")
        if self._has_two_or_three_state_cycle():
            self.terminal_code = "STATE_CYCLE_BOUNDED_FAIL"
            raise ToolLoopError(self.terminal_code, "two-state or three-state cycle detected")
        if self.step_count == self.max_steps and self.required_outcomes - self.resolved_outcomes:
            self.terminal_code = "STEP_LIMIT_BOUNDARY_FORCE_QUIT"
            raise ToolLoopError(self.terminal_code, "required outcomes remain at step 20")

        return {
            "status": "STATE_ADVANCED" if changed else "NO_PROGRESS_OBSERVED",
            "step_count": self.step_count,
            "call_fingerprint": call_fingerprint,
            "compacted_tool_results": compacted,
            "rolling_state_summary": self.rolling_state_summary(),
        }

    def _has_two_or_three_state_cycle(self) -> bool:
        pairs = list(zip(self._fingerprints, self._state_hashes, strict=True))
        for cycle_size in (2, 3):
            if len(pairs) < cycle_size * 2:
                continue
            if pairs[-cycle_size:] == pairs[-2 * cycle_size : -cycle_size]:
                return True
        return False

    def rolling_state_summary(self) -> dict[str, Any]:
        value = {
            "schema": "milai.dg10.bfcl-rolling-state.v1",
            "step_count": self.step_count,
            "state": self.state,
            "resolved_outcomes": sorted(self.resolved_outcomes),
            "pending_outcomes": sorted(self.required_outcomes - self.resolved_outcomes),
            "last_call_fingerprint": self.last_call_fingerprint,
            "last_result_sha256": self._result_hashes[-1] if self._result_hashes else None,
            "no_progress_count": self.no_progress_count,
        }
        size = len(_canonical_bytes(value))
        if size > self.max_summary_bytes:
            raise ToolLoopError(
                "ROLLING_SUMMARY_BYTE_LIMIT",
                f"rolling summary is {size} bytes, limit is {self.max_summary_bytes}",
            )
        return value
