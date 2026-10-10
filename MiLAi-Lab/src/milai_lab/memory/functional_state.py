"""Opt-in functional source fragments and visibility, stored in the existing Store.

Visibility revocation is not physical deletion. Fragment identities prove exact
provenance only, never semantic support or permission for a business mutation.
"""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any, cast


class FunctionalRejection(ValueError):
    """Explicit contract refusal before a semantic/visibility mutation is entered."""


class FunctionalReviewRejection(FunctionalRejection):
    """An identified precommit review outcome, distinct from semantic falsity."""

    def __init__(
        self, message: str, review_status: str, proposal_id: str, failure_type: str | None = None
    ) -> None:
        super().__init__(message)
        self.review_status = review_status
        self.proposal_id = proposal_id
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


def reference_key(identifiers: Any) -> str:
    """Readable lookup key of explicit identifiers and versions."""
    return canonical(identifiers)


def body_text(event: dict[str, Any]) -> str:
    content = event["content"]
    return content if isinstance(content, str) else canonical(content)


def namespace(service: Any) -> tuple[str, ...]:
    return (*service.namespace, "v13_5_functional")


def request_target_mapping(service: Any, binding: dict[str, Any]) -> dict[str, Any]:
    """Load an exact request's reference table, or prepare an unissued table.

    Preparing a table never writes or registers a credential. The random request
    nonce prevents a target from another turn/bank being interpreted as an ordinal
    in this turn. The complete owner/bank/public-turn binding is also checked.
    """
    key = "request-targets:" + reference_key([binding["session"], binding["message_id"]])
    stored = service.store.get(namespace(service), key)
    if stored is None:
        return {
            "owner": service.owner, "bank": list(service.namespace),
            "binding": copy.deepcopy(binding), "scope": "q" + uuid.uuid4().hex[:12],
            "targets": {},
        }
    value = stored.value
    if (
        value.get("owner") != service.owner
        or value.get("bank") != list(service.namespace)
        or value.get("binding") != binding
        or not isinstance(value.get("scope"), str)
        or not isinstance(value.get("targets"), dict)
    ):
        raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_BINDING_CHANGED")
    return copy.deepcopy(cast(dict[str, Any], value))


def add_request_target(mapping: dict[str, Any], row: dict[str, Any]) -> str:
    """Plan one exact reference without issuing it; navigation has no credentials."""
    kind = row.get("kind")
    credentials = row.get("credentials")
    expected = {"delivered_record": "read_handle", "delivered_source": "fragment_handle"}
    if (
        kind not in {*expected, "read_only_navigation"}
        or not isinstance(row.get("identity"), dict)
        or not isinstance(credentials, dict)
        or (kind == "read_only_navigation" and credentials)
        or (kind in expected and (
            set(credentials) != {expected[kind]}
            or not isinstance(credentials.get(expected[kind]), str)
            or not credentials[expected[kind]]
        ))
    ):
        raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_CREDENTIAL_INVALID")
    for target, old in mapping["targets"].items():
        if old == row:
            return str(target)
        if credentials and old.get("credentials") == credentials:
            raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_IDENTITY_CHANGED")
    target = mapping["scope"] + ":" + str(len(mapping["targets"]) + 1)
    mapping["targets"][target] = copy.deepcopy(row)
    return str(target)


def project_request_targets(
    mapping: dict[str, Any], packet: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure preview of actual body credentials and credential-free navigation."""
    planned = copy.deepcopy(mapping)
    result = copy.deepcopy(packet)

    def navigation(tool: str, arguments: dict[str, Any], **identity: Any) -> str:
        if "forget_epoch" in packet:
            identity["forget_epoch"] = packet["forget_epoch"]
        return add_request_target(planned, {
            "kind": "read_only_navigation", "credentials": {},
            "identity": {**identity, "read": {"tool": tool, "arguments": arguments}},
        })

    def history(index: dict[str, Any], record_id: str) -> None:
        if isinstance(index.get("read"), dict):
            target = navigation("read_memory_history", {"record_id": record_id},
                                record_id=record_id)
            index["target"], index["target_kind"] = target, "read_only_navigation"
            index["read"] = {"tool": "read_memory_history", "arguments": {"target": target}}
        index["revision_targets"] = [
            {"revision": revision, "target": navigation(
                "read_memory_revision", {"record_id": record_id, "revision": revision},
                record_id=record_id, revision=revision, version_view="historical_exact_revision",
            ), "target_kind": "read_only_navigation"}
            for revision in index.get("revisions", []) if type(revision) is int and revision > 0
        ]
        cursor = index.get("index_next_cursor", index.get("next_cursor"))
        if isinstance(cursor, str) and cursor:
            index["index_next_target"] = navigation(
                "read_page", {"record_id": record_id, "index_cursor": cursor},
                record_id=record_id, cursor=cursor,
            )
        if "revision_tool" in index:
            index["revision_tool"], index["body_page_tool"] = "read_memory_revision", "read_page"

    for item in result.get("items", []):
        if item.get("type") == "record" and isinstance(item.get("read_handle"), str):
            row = {
                "kind": "delivered_record",
                "identity": {"record_id": item["record_id"], "revision": item["revision"]},
                "credentials": {"read_handle": item["read_handle"]},
            }
        elif item.get("type") == "fragment" and isinstance(item.get("fragment_handle"), str):
            row = {
                "kind": "delivered_source",
                "identity": {key: item[key] for key in (
                    "source_ref", "source_revision", "start", "end"
                ) if key in item},
                "credentials": {"fragment_handle": item["fragment_handle"]},
            }
        else:
            continue
        item["target"] = add_request_target(planned, row)
        item["target_kind"] = row["kind"]
        if isinstance(item.get("stored_history"), dict):
            history(item["stored_history"], item["record_id"])
        for evidence in item.get("revision_evidence", []):
            descriptor = evidence.get("read", {})
            if descriptor.get("tool") == "read_source" and isinstance(
                evidence.get("source_ref"), str
            ):
                identity = {key: evidence[key] for key in (
                    "source_ref", "source_revision"
                ) if key in evidence}
                target = navigation("read_source", {"source_ref": evidence["source_ref"]},
                                    **identity)
                evidence["target"], evidence["target_kind"] = target, "read_only_navigation"
                evidence["read"] = {"tool": "read_source", "arguments": {"target": target}}

    for candidate in result.get("candidates", []):
        if candidate.get("type") == "record_candidate":
            record_id = candidate["record_id"]
            identity = {key: candidate[key] for key in (
                "record_id", "revision", "version_view"
            ) if key in candidate}
            exact = candidate.get("version_view") == "historical_exact_revision"
            tool = "read_memory_revision" if exact else "read_memory"
            arguments = {"record_id": record_id}
            if exact:
                arguments["revision"] = candidate["revision"]
        elif candidate.get("type") == "source_candidate":
            tool, arguments = "read_source", {"source_ref": candidate["source_ref"]}
            identity = {key: candidate[key] for key in (
                "source_ref", "source_revision", "version_view"
            ) if key in candidate}
        else:
            continue
        target = navigation(tool, arguments, **identity)
        candidate["target"], candidate["target_kind"] = target, "read_only_navigation"
        candidate["read"] = {"tool": tool, "arguments": {"target": target}}

    if isinstance(result.get("stored_history"), dict) and isinstance(result.get("record_id"), str):
        history(result["stored_history"], result["record_id"])

    for skipped in result.get("skipped_units", []):
        alternate = skipped.get("alternative")
        if isinstance(alternate, dict) and alternate.get("tool") == "read_source" \
                and isinstance(alternate.get("source_ref"), str):
            target = navigation("read_source", {"source_ref": alternate["source_ref"]},
                                source_ref=alternate["source_ref"])
            alternate["target"], alternate["target_kind"] = target, "read_only_navigation"
            alternate["arguments"] = {"target": target}

    cursor = result.get("next_cursor")
    if isinstance(cursor, str) and cursor:
        result["next_target"] = navigation("read_page", {"cursor": cursor}, cursor=cursor)
        result["next_target_kind"] = "read_only_navigation"
    for continuation in result.get("continuations", []):
        cursor = continuation.get("next_cursor", continuation.get(
            "cursor", continuation.get("arguments", {}).get("cursor")
        ))
        if isinstance(cursor, str) and cursor:
            target = navigation("read_page", {"cursor": cursor}, cursor=cursor)
            continuation["cursor"] = cursor
            continuation["target"], continuation["target_kind"] = target, "read_only_navigation"
            continuation["tool"], continuation["arguments"] = "read_page", {"target": target}
        elif isinstance(continuation.get("target"), str):
            row = planned["targets"].get(continuation["target"])
            if row is None or row["kind"] != "read_only_navigation":
                raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_CONTINUATION_NOT_ISSUED")
    result["target_scope"] = mapping["scope"]
    return result, planned


def commit_request_targets(service: Any, mapping: dict[str, Any]) -> None:
    """Register the final delivered table in the existing Store, never rebind it."""
    if (
        mapping.get("owner") != service.owner
        or mapping.get("bank") != list(service.namespace)
        or not isinstance(mapping.get("binding"), dict)
        or not isinstance(mapping.get("scope"), str)
        or not isinstance(mapping.get("targets"), dict)
        or any(not isinstance(target, str) or not target.startswith(mapping["scope"] + ":")
               for target in mapping["targets"])
    ):
        raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_BINDING_CHANGED")
    binding = mapping["binding"]
    key = "request-targets:" + reference_key([binding["session"], binding["message_id"]])
    scope_key = "request-target-scope:" + mapping["scope"]
    scope_binding = {"owner": service.owner, "bank": list(service.namespace), "binding": binding}
    with service._locked():
        old = service.store.get(namespace(service), key)
        issued_scope = service.store.get(namespace(service), scope_key)
        if issued_scope is not None and issued_scope.value != scope_binding:
            raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_SCOPE_COLLISION")
        if old is not None and (
            old.value.get("scope") != mapping["scope"]
            or any(mapping["targets"].get(target) != row
                   for target, row in old.value["targets"].items())
            or any(old.value.get(field) != mapping[field] for field in ("owner", "bank", "binding"))
        ):
            raise FunctionalIntegrityError("V13_5_REQUEST_TARGET_REBINDING")
        if old is not None and old.value == mapping:
            return
        try:
            if issued_scope is None:
                service.store.put(namespace(service), scope_key, scope_binding, index=False)
            service.store.put(namespace(service), key, mapping, index=False)
        except Exception as error:
            raise FunctionalOperationError("target_binding_commit", error) from error


def resolve_request_target(
    service: Any, binding: dict[str, Any], target: str, *, kind: str | None = None
) -> dict[str, Any]:
    """Resolve only this request's exact reference; service still validates effects."""
    mapping = request_target_mapping(service, binding)
    if not isinstance(target, str) or not target.startswith(mapping["scope"] + ":"):
        raise FunctionalRejection("V13_5_REQUEST_TARGET_NOT_DELIVERED")
    row = mapping["targets"].get(target)
    if row is None:
        raise FunctionalRejection("V13_5_REQUEST_TARGET_NOT_DELIVERED")
    if kind is not None and row.get("kind") != kind:
        raise FunctionalRejection("V13_5_REQUEST_TARGET_KIND_INVALID")
    return copy.deepcopy(cast(dict[str, Any], row))


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
        "source_revision": event.get("source_revision", 1),
        "start": start,
        "end": end,
        "role": event["role"],
        "origin": event["origin"],
        "observed_at": event["observed_at"],
        "source_total_codepoints": len(body),
        "range_basis": "body_text_unicode_codepoints_half_open",
    }
    handle = "frag:" + reference_key(
        [service.namespace, service.owner, source_ref, bound["source_revision"], start, end]
    )
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
    if not isinstance(handle, str):
        raise FunctionalRejection("V13_5_FRAGMENT_NOT_ISSUED")
    item = service.store.get(namespace(service), handle)
    if item is None:
        raise FunctionalRejection("V13_5_FRAGMENT_NOT_ISSUED")
    bound = item.value
    if bound.get("owner") != service.owner or bound.get("bank") != list(service.namespace):
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
        or event.get("source_revision", 1) != bound.get("source_revision", 1)
        or any(event[k] != bound[k] for k in ("role", "origin", "observed_at"))
    ):
        raise FunctionalIntegrityError("V13_5_FRAGMENT_SOURCE_CHANGED")
    return {
        "fragment_handle": handle,
        **bound,
        "source_revision": bound.get("source_revision", 1),
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
                    "source_revision",
                    "start",
                    "end",
                    "content",
                )
            }
            for f in fragments
        ],
        "semantic_support": "unchecked",
    }
