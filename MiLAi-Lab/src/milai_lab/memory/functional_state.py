"""Opt-in functional source fragments and visibility, stored in the existing Store.

Visibility revocation is not physical deletion. Fragment identities prove exact
provenance only, never semantic support or permission for a business mutation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast


class FunctionalRejection(ValueError):
    """Explicit contract refusal before a semantic/visibility mutation is entered."""


class FunctionalReviewRejection(FunctionalRejection):
    """An identified precommit review outcome, distinct from semantic falsity."""

    def __init__(self, message: str, review_status: str, evidence_sha256: str,
                 failure_type: str | None = None) -> None:
        super().__init__(message)
        self.review_status = review_status
        self.evidence_sha256 = evidence_sha256
        self.failure_type = failure_type


class FunctionalMaintenanceRejection(FunctionalRejection):
    """A durable maintenance allowance refused this proposal before commit."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


class FunctionalIntegrityError(ValueError):
    """Stored identity or visibility integrity failed; not an ordinary input refusal."""


class FunctionalOperationError(RuntimeError):
    """A persistence boundary was entered; an exception cannot certify no effect."""

    def __init__(self, phase: str, cause: Exception) -> None:
        super().__init__(phase)
        self.phase, self.cause = phase, cause


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def body_text(event: dict[str, Any]) -> str:
    content = event["content"]
    return content if isinstance(content, str) else canonical(content)


def namespace(service: Any) -> tuple[str, ...]:
    return (*service.namespace, "v13_5_functional")


def visibility(service: Any) -> dict[str, Any]:
    item = service.store.get(namespace(service), "visibility")
    if item is None:
        return {
            "owner": service.owner,
            "bank": list(service.namespace),
            "epoch": 0,
            "records": [],
            "sources": [],
            "operations": {},
        }
    value = item.value
    if (
        value.get("owner") != service.owner
        or value.get("bank") != list(service.namespace)
        or type(value.get("epoch")) is not int
        or value["epoch"] < 0
        or not isinstance(value.get("records"), list)
        or not isinstance(value.get("sources"), list)
        or not isinstance(value.get("operations"), dict)
    ):
        raise FunctionalIntegrityError("V13_5_VISIBILITY_INTEGRITY_FAILED")
    return cast(dict[str, Any], value)


def source_hidden(service: Any, source_ref: str) -> bool:
    return source_ref in visibility(service)["sources"]


def record_hidden(service: Any, record_id: str) -> bool:
    return record_id in visibility(service)["records"]


def note_exposure(
    service: Any,
    public_source: str,
    source_refs: list[str],
    *,
    kind: str = "input_context",
) -> None:
    """Input precedes retrieval; only a generated assistant output can follow its exposure."""
    if kind not in {"input_context", "assistant_output"}:
        raise FunctionalRejection("V13_5_EXPOSURE_KIND_INVALID")
    key = "exposure:" + public_source
    old = service.store.get(namespace(service), key)
    if old is not None and old.value.get("edge_kind") != kind:
        raise FunctionalIntegrityError("V13_5_EXPOSURE_KIND_CHANGED")
    value = {
        "owner": service.owner,
        "bank": list(service.namespace),
        "public_source": public_source,
        "edge_kind": kind,
        "source_refs": list(
            dict.fromkeys(
                [
                    *(old.value["source_refs"] if old is not None else []),
                    *(ref for ref in source_refs if ref != public_source),
                ]
            )
        ),
        "meaning": "material_exposure_not_semantic_support",
    }
    if old is None or old.value != value:
        service.store.put(namespace(service), key, value, index=False)
    state = visibility(service)
    if (
        kind == "assistant_output"
        and set(value["source_refs"]).intersection(state["sources"])
        and public_source not in state["sources"]
    ):
        service.store.put(
            namespace(service),
            "visibility",
            {**state, "epoch": state["epoch"] + 1, "sources": [*state["sources"], public_source]},
            index=False,
        )


def validate_source(source_ref: str, event: dict[str, Any], owner: str) -> None:
    role, origin, ref = event.get("role"), event.get("origin"), event.get("object_ref")
    if (
        event.get("event_id") != source_ref
        or event.get("owner") != owner
        or not isinstance(event.get("session"), str)
        or not event["session"]
        or role not in {"user", "assistant", "tool"}
        or not isinstance(origin, str)
        or not origin
        or (role == "user" and origin != "public_user_message")
        or (role == "assistant" and origin != "public_assistant_message")
        or (role == "tool" and origin in {"public_user_message", "public_assistant_message"})
        or (
            ref is not None
            and (
                role != "tool"
                or not isinstance(ref, dict)
                or ref.get("owner") != owner
                or ref.get("source_ref") != source_ref
                or not isinstance(ref.get("external_id"), str)
                or ref.get("id") != source_ref + ":" + ref["external_id"]
            )
        )
    ):
        raise FunctionalIntegrityError("V13_5_SOURCE_IDENTITY_INVALID")


def scope_leaves(scope: dict[str, Any], prefix: str = "scope") -> dict[str, Any]:
    """Explicit JSON scope; dots separate dictionary paths, arrays are literal leaves."""
    if not isinstance(scope, dict):
        raise FunctionalRejection("V13_5_SCOPE_OBJECT_REQUIRED")
    result: dict[str, Any] = {}
    reserved = {
        "event_id",
        "source_ref",
        "source_refs",
        "source_bindings",
        "field_support",
        "functional_support",
        "fragment_handles",
        "quotes",
        "object_ref",
        "content_sha256",
    }
    for key, value in scope.items():
        if not isinstance(key, str) or not key or "." in key or key in reserved:
            raise FunctionalRejection("V13_5_SCOPE_KEY_INVALID")
        path = prefix + "." + key
        if isinstance(value, dict) and value:
            result.update(scope_leaves(value, path))
        else:
            if isinstance(value, list) and any(isinstance(item, (list, dict)) for item in value):
                raise FunctionalRejection("V13_5_SCOPE_ARRAY_LITERAL_VALUES_REQUIRED")
            canonical(value)
            result[path] = value
    return result


def issue_fragment_range(service: Any, source_ref: str, start: int, end: int) -> dict[str, Any]:
    event = service.source(source_ref)
    if event is None:
        raise FunctionalRejection("V13_5_SOURCE_UNAVAILABLE")
    body = body_text(event)
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
        raise FunctionalRejection("V13_5_FRAGMENT_RANGE_INVALID")
    part = body[start:end]
    bound = {
        "owner": service.owner,
        "bank": list(service.namespace),
        "source_ref": source_ref,
        "source_sha256": event["content_sha256"],
        "body_text_sha256": text_hash(body),
        "start": start,
        "end": end,
        "span_sha256": text_hash(part),
        "role": event["role"],
        "origin": event["origin"],
        "observed_at": event["observed_at"],
        "source_total_codepoints": len(body),
        "range_basis": "body_text_unicode_codepoints_half_open",
    }
    handle = "frag-" + digest(bound)
    prior = service.store.get(namespace(service), handle)
    if prior is not None and prior.value != bound:
        raise FunctionalIntegrityError("V13_5_FRAGMENT_COLLISION")
    if prior is None:
        service.store.put(namespace(service), handle, bound, index=False)
    return {"fragment_handle": handle, **bound, "content": part, "semantic_support": "unchecked"}


def issue_fragments(service: Any, source_ref: str, max_chars: int) -> list[dict[str, Any]]:
    if type(max_chars) is not int or not 1 <= max_chars <= 16000:
        raise FunctionalRejection("V13_5_FRAGMENT_SIZE_INVALID")
    event = service.source(source_ref)
    if event is None:
        raise FunctionalRejection("V13_5_SOURCE_UNAVAILABLE")
    body = body_text(event)
    result = []
    start = 0
    while start < len(body):
        end = min(len(body), start + max_chars)
        if end < len(body):
            # Prefer a complete public paragraph/line; preserve every original codepoint.
            boundary = body.rfind("\n", start, end)
            if boundary >= start:
                end = boundary + 1
        result.append(issue_fragment_range(service, source_ref, start, end))
        start = end
    return result


def resolve_fragment(service: Any, handle: str) -> dict[str, Any]:
    if not isinstance(handle, str) or not handle.startswith("frag-"):
        raise FunctionalRejection("V13_5_FRAGMENT_NOT_ISSUED")
    item = service.store.get(namespace(service), handle)
    if item is None:
        raise FunctionalRejection("V13_5_FRAGMENT_NOT_ISSUED")
    bound = item.value
    if (
        handle != "frag-" + digest(bound)
        or bound.get("owner") != service.owner
        or bound.get("bank") != list(service.namespace)
    ):
        raise FunctionalIntegrityError("V13_5_FRAGMENT_BINDING_CHANGED")
    event = service.source(bound["source_ref"])
    if event is None:
        raise FunctionalRejection("V13_5_SOURCE_UNAVAILABLE")
    body = body_text(event)
    start, end = bound["start"], bound["end"]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(body)
        or event["content_sha256"] != bound["source_sha256"]
        or text_hash(body) != bound["body_text_sha256"]
        or text_hash(body[start:end]) != bound["span_sha256"]
        or any(event[k] != bound[k] for k in ("role", "origin", "observed_at"))
    ):
        raise FunctionalIntegrityError("V13_5_FRAGMENT_SOURCE_CHANGED")
    return {
        "fragment_handle": handle,
        **bound,
        "content": body[start:end],
        "semantic_support": "unchecked",
    }


def fragment_support(service: Any, handles: list[str]) -> dict[str, Any]:
    if (
        not isinstance(handles, list)
        or not handles
        or not all(isinstance(h, str) for h in handles)
        or len(set(handles)) != len(handles)
    ):
        raise FunctionalRejection("V13_5_FRAGMENT_SELECTION_REQUIRED")
    fragments = [resolve_fragment(service, handle) for handle in handles]
    return {
        "fragment_handles": handles,
        "source_refs": list(dict.fromkeys(fragment["source_ref"] for fragment in fragments)),
        "quotes": [
            {
                k: f[k]
                for k in (
                    "fragment_handle",
                    "source_ref",
                    "source_sha256",
                    "body_text_sha256",
                    "start",
                    "end",
                    "span_sha256",
                    "content",
                )
            }
            for f in fragments
        ],
        "semantic_support": "unchecked",
    }
