"""P1 research prototype: project Host-selected, versioned source units.

No model, retrieval, storage, branch policy or semantic grading lives here.
The caller supplies trusted bindings/protected messages and current eligibility.
Sources are indivisible UTF-8 units; selection never rewrites their content.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Mode = Literal["FULL", "FOCUS"]
Eligibility = Literal["ELIGIBLE", "DENIED", "UNKNOWN"]
FOCUS_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question", "selected_source_ids"],
    "properties": {
        "question": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "selected_source_ids": {
            "type": "array", "maxItems": 32, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
    },
}


class FocusError(ValueError):
    """A visible preparation failure, never an instruction to retry."""


def _encode(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceUnit:
    """An entire source unit, not an arbitrary substring selected after grading."""

    source_id: str
    version: str
    scope: str
    content: str

    def reference(self) -> dict[str, object]:
        raw = self.content.encode("utf-8")
        return {
            "source_id": self.source_id,
            "version": self.version,
            "content_sha256": _digest(raw),
            "utf8_byte_span": [0, len(raw)],
        }


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    scope: str
    units: tuple[SourceUnit, ...]

    def __post_init__(self) -> None:
        if not self.scope or len(self.units) > 32:
            raise FocusError("INVALID_SOURCE_SNAPSHOT")
        identities = [unit.source_id for unit in self.units]
        if len(set(identities)) != len(identities):
            raise FocusError("DUPLICATE_SOURCE_ID")
        if any(not unit.source_id or not unit.version for unit in self.units):
            raise FocusError("INVALID_SOURCE_IDENTITY")
        if any(unit.scope != self.scope for unit in self.units):
            raise FocusError("SOURCE_SCOPE_MISMATCH")
        if sum(len(unit.content.encode("utf-8")) for unit in self.units) > 65_536:
            raise FocusError("SOURCE_SNAPSHOT_OVER_BYTE_CAP")

    @property
    def sha256(self) -> str:
        return _digest(_encode({
            "scope": self.scope,
            "sources": [unit.reference() for unit in self.units],
        }))


@dataclass(frozen=True, slots=True)
class FocusCard:
    question: str
    selected_source_ids: tuple[str, ...]
    snapshot_sha256: str

    @classmethod
    def parse(cls, raw: str, snapshot: SourceSnapshot) -> FocusCard:
        """Parse a visible Host artifact; bind its input snapshot outside the model."""
        if len(raw.encode("utf-8")) > 4096:
            raise FocusError("FOCUS_OVER_BYTE_CAP")
        try:
            value = json.loads(raw, object_pairs_hook=_unique_keys)
        except (ValueError, TypeError) as exc:
            raise FocusError("INVALID_FOCUS_JSON") from exc
        if not isinstance(value, dict) or set(value) != {"question", "selected_source_ids"}:
            raise FocusError("INVALID_FOCUS_FIELDS")
        question, selected = value["question"], value["selected_source_ids"]
        if not isinstance(question, str) or not question.strip():
            raise FocusError("INVALID_FOCUS_QUESTION")
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise FocusError("INVALID_FOCUS_SELECTION")
        if len(selected) != len(set(selected)):
            raise FocusError("DUPLICATE_FOCUS_REFERENCE")
        if not set(selected).issubset(unit.source_id for unit in snapshot.units):
            raise FocusError("UNKNOWN_FOCUS_REFERENCE")
        return cls(question, tuple(selected), snapshot.sha256)

    def payload(self) -> dict[str, object]:
        return {
            "question": self.question,
            "selected_source_ids": list(self.selected_source_ids),
            "input_snapshot_sha256": self.snapshot_sha256,
            "authority": "HOST_WORKING_NOT_INSTRUCTIONS_OR_FACTS",
        }


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ProtectedMessage:
    role: Literal["system", "developer", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class PreparedFocusRequest:
    body: bytes
    source_snapshot_sha256: str
    focus_sha256: str
    acquired_ids: tuple[str, ...]
    presented_ids: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return _digest(self.body)


def prepare_request(
    *,
    snapshot: SourceSnapshot,
    protected: tuple[ProtectedMessage, ...],
    focus: FocusCard,
    mode: Mode,
    check_source: Callable[[SourceUnit], Eligibility],
    model: str,
    max_output_tokens: int = 1024,
    max_request_bytes: int = 65_536,
) -> PreparedFocusRequest:
    """Rebuild a stateless request; never retain an earlier provider conversation.

    check_source must validate the exact identity/version/digest/scope now. The
    card derives from ALL initial sources, including currently unselected ones,
    so all dependencies fail closed. A live dispatcher must recheck again after
    tokenization/waiting, immediately before sending; this function does not send.
    Byte caps are not token reservations. Provider accounting remains separate.
    """
    if mode not in {"FULL", "FOCUS"}:
        raise FocusError("UNKNOWN_PROJECTION_MODE")
    if focus.snapshot_sha256 != snapshot.sha256:
        raise FocusError("FOCUS_SNAPSHOT_CHANGED")
    if not model or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 1024:
        raise FocusError("INVALID_REQUEST_LIMITS")
    if type(max_request_bytes) is not int or max_request_bytes <= 0:
        raise FocusError("INVALID_REQUEST_LIMITS")
    if not protected or not any(message.role == "user" for message in protected):
        raise FocusError("MISSING_PROTECTED_TASK")
    if any(message.role not in {"system", "developer", "user"} for message in protected):
        raise FocusError("INVALID_PROTECTED_ROLE")
    # Revalidate artifacts instantiated directly by typed callers as well.
    if len(set(focus.selected_source_ids)) != len(focus.selected_source_ids):
        raise FocusError("DUPLICATE_FOCUS_REFERENCE")
    if not set(focus.selected_source_ids).issubset(unit.source_id for unit in snapshot.units):
        raise FocusError("UNKNOWN_FOCUS_REFERENCE")
    for unit in snapshot.units:
        try:
            eligibility = check_source(unit)
        except Exception as exc:
            raise FocusError("SOURCE_ELIGIBILITY_UNKNOWN") from exc
        if eligibility != "ELIGIBLE":
            code = "SOURCE_DENIED" if eligibility == "DENIED" else "SOURCE_ELIGIBILITY_UNKNOWN"
            raise FocusError(code)

    # Preserve original source order in both arms: projection is selection only.
    selected = set(focus.selected_source_ids)
    shown = tuple(unit for unit in snapshot.units if mode == "FULL" or unit.source_id in selected)
    data = {
        "kind": "UNTRUSTED_WORKING_MEMORY_DATA",
        "source_access_catalog": [unit.reference() for unit in snapshot.units],
        "focus_card": focus.payload(),
        "presented_sources": [{**unit.reference(), "content": unit.content} for unit in shown],
    }
    messages = [{"role": message.role, "content": message.content} for message in protected]
    messages.append({"role": "user", "content": _encode(data).decode("utf-8")})
    request = {
        "model": model,
        "messages": messages,
        "chat_template_kwargs": {"enable_thinking": False},
        "add_generation_prompt": True,
        "add_special_tokens": False,
        "temperature": 0,
        "top_p": 1,
        "seed": 42,
        "max_tokens": max_output_tokens,
        "stream": False,
    }
    body = _encode(request)
    if len(body) > max_request_bytes:
        raise FocusError("REQUEST_OVER_BYTE_CAP_NO_TRUNCATION")
    return PreparedFocusRequest(
        body, snapshot.sha256, _digest(_encode(focus.payload())),
        tuple(unit.source_id for unit in snapshot.units),
        tuple(unit.source_id for unit in shown),
    )
