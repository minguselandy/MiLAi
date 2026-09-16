"""Opt-in workspace hooks for the Lab's text/JSON action Host.

No cognitive state machine, network, storage or product imports. The caller owns
the task contract, current source eligibility, tokenizer and action dispatch.
Native tool-call messages require their original Host's grouping adapter; this
prototype uses complete text-encoded action/result exchanges, not tool messages.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

Mode = Literal["COMMON_CONTEXT", "MANAGED_WORKSET"]
Ref = tuple[str, str]  # Host-issued handle and immutable revision/range identity.
Action = dict[str, object]


class WorkspaceError(ValueError):
    """Mechanical failure; never a judgment about the content of a note."""


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str

    def wire(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Material:
    handle: str
    revision: str
    binding: str
    text: str
    eligible: bool = True

    @property
    def ref(self) -> Ref:
        return self.handle, self.revision


@dataclass(frozen=True)
class Exchange:
    """Indivisible messages with conservative disclosure dependencies.

    The caller strips optional work_update from assistant history, but archives
    its original response elsewhere. New observations may also use this wrapper.
    """

    messages: tuple[Message, ...]
    dependencies: frozenset[Ref] = frozenset()
    body_refs: frozenset[Ref] = frozenset()


@dataclass(frozen=True)
class Workspace:
    binding: str
    text: str = ""
    focus_refs: tuple[str, ...] = ()
    revision: int = 0
    dependencies: frozenset[Ref] = frozenset()


@dataclass(frozen=True)
class Limits:
    work_tokens: int = 512
    focus_refs: int = 4
    recent_exchanges: int = 2
    input_tokens: int = 8192
    output_tokens: int = 2048
    action_reserve: int = 1024
    envelope_reserve: int = 128
    catalog_entries: int = 32

    def __post_init__(self) -> None:
        values = vars(self)
        if any(type(value) is not int or value < 1 for value in values.values()):
            raise WorkspaceError("INVALID_LIMITS")
        if self.output_tokens < self.work_tokens + self.action_reserve + self.envelope_reserve:
            raise WorkspaceError("ACTION_OUTPUT_RESERVE_MISSING")


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class PreparedInput:
    messages: tuple[Message, ...]
    included_refs: frozenset[Ref]
    expanded: tuple[str, ...]
    deferred: tuple[tuple[str, str], ...]
    available_refs: frozenset[Ref]
    workspace_visible: bool
    workspace_revision: int
    binding: str
    input_tokens: int


@dataclass(frozen=True)
class AcceptedResponse:
    workspace: Workspace
    action: Action
    update_status: str
    feedback: str = ""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _data(kind: str, value: object) -> Message:
    # Data never becomes system policy, including text resembling instructions.
    return Message("user", _json({"workspace_data": kind, "value": value}))


def refs_current(refs: frozenset[Ref], registry: Mapping[str, Material], binding: str) -> bool:
    return all(
        (item := registry.get(handle)) is not None
        and item.binding == binding
        and item.eligible is True
        and item.ref == (handle, revision)
        for handle, revision in refs
    )


def before_model(
    *,
    base: tuple[Message, ...],
    policy: str,
    workspace: Workspace,
    registry: Mapping[str, Material],
    new: tuple[Exchange, ...],
    history: tuple[Exchange, ...],
    pending: tuple[Exchange, ...] = (),
    feedback: str = "",
    mode: Mode = "COMMON_CONTEXT",
    limits: Limits = DEFAULT_LIMITS,
    count_messages: Callable[[tuple[Message, ...]], int],
) -> PreparedInput:
    """Assemble, not certify presentation. Protected inputs are never truncated.

    Small published catalogs only. A larger corpus needs its existing paginated
    index, not a new hidden selector. Source versions are supplied by the Host
    immediately before calling; the assembled object is not a reusable permit.
    """
    if mode not in ("COMMON_CONTEXT", "MANAGED_WORKSET"):
        raise WorkspaceError("UNKNOWN_CONTEXT_MODE")
    available = {
        handle: item
        for handle, item in registry.items()
        if item.binding == workspace.binding and item.eligible is True
    }
    if any(handle != item.handle for handle, item in available.items()):
        raise WorkspaceError("INVALID_REFERENCE_REGISTRY")
    if len(available) > limits.catalog_entries:
        raise WorkspaceError("PUBLISHED_CATALOG_TOO_LARGE_USE_HOST_PAGINATION")
    visible = refs_current(workspace.dependencies, registry, workspace.binding)
    selected_history = history if mode == "COMMON_CONTEXT" else history[-limits.recent_exchanges :]
    groups = (*selected_history, *pending, *new)
    if any(not group.body_refs <= group.dependencies for group in groups):
        raise WorkspaceError("UNBOUND_SOURCE_BODY")
    group_refs = frozenset(ref for group in groups for ref in group.dependencies)
    if not refs_current(group_refs, registry, workspace.binding):
        raise WorkspaceError("PROTECTED_INPUT_DISCLOSURE_UNAVAILABLE")
    included = set(group_refs)
    if visible:
        included.update(workspace.dependencies)
    catalog = [{"ref": item.handle, "revision": item.revision} for item in available.values()]
    # The actual model template accepts exactly one system message at the start.
    # Keep the original user task in its role; append the trusted policy to the
    # leading system instruction, never promote user/material text to system.
    if base and base[0].role == "system":
        messages = [Message("system", base[0].content + "\n\n" + policy), *base[1:]]
    else:
        messages = [Message("system", policy), *base]
    messages.append(
        _data(
            "fallible_work_record",
            {
                "text": workspace.text if visible else "",
                "focus_refs": workspace.focus_refs if visible else (),
                "status": "AVAILABLE" if visible else "WITHHELD_DEPENDENCY_CHANGED",
            },
        )
    )
    messages.append(_data("published_source_catalog", catalog))
    if feedback:
        messages.append(_data("previous_update_feedback", feedback))
    for group in groups:
        messages.extend(group.messages)
    # Dependencies are NOT a list of bodies already shown. Deduplicate only
    # explicit source references in the supplied groups, never workspace refs.
    already_shown = {ref for group in groups for ref in group.body_refs}
    candidates = (
        tuple(available) if mode == "COMMON_CONTEXT" else (workspace.focus_refs if visible else ())
    )
    expanded: list[str] = []
    deferred: list[tuple[str, str]] = []
    if count_messages(tuple(messages)) > limits.input_tokens:
        raise WorkspaceError("PROTECTED_INPUT_OVER_BUDGET")
    for handle in candidates:
        item = available.get(handle)
        if item is None:
            deferred.append((handle, "UNAVAILABLE"))
            continue
        if item.ref in already_shown:
            continue
        material_message = _data(
            "source",
            {
                "ref": handle,
                "revision": item.revision,
                "text": item.text,
            },
        )
        if count_messages((*messages, material_message)) > limits.input_tokens:
            if mode == "COMMON_CONTEXT":
                raise WorkspaceError("COMMON_CONTEXT_OVER_BUDGET")
            deferred.append((handle, "INPUT_BUDGET_USE_SOURCE_READ"))
            continue
        messages.append(material_message)
        expanded.append(handle)
        already_shown.add(item.ref)
        included.add(item.ref)
    if deferred:
        messages.append(_data("not_expanded", deferred))
    tokens = count_messages(tuple(messages))
    if tokens > limits.input_tokens:
        # Do not sacrifice protected data to fit even a presentation receipt.
        raise WorkspaceError("INPUT_OVER_BUDGET")
    return PreparedInput(
        tuple(messages),
        frozenset(included),
        tuple(expanded),
        tuple(deferred),
        frozenset(item.ref for item in available.values()),
        visible,
        workspace.revision,
        workspace.binding,
        tokens,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise WorkspaceError("NON_FINITE_JSON_NUMBER")


def decode_action(
    raw: str,
    validate_action: Callable[[Action], None],
    *,
    workspace_enabled: bool = True,
) -> tuple[Action, object]:
    """Parse once, then delegate business meaning/authorization to the old Host."""
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise WorkspaceError("INVALID_COMPLETE_RESPONSE") from exc
    allowed = (
        {"action", "arguments", "work_update"} if workspace_enabled else {"action", "arguments"}
    )
    if (
        not isinstance(value, dict)
        or set(value) - allowed
        or not {"action", "arguments"} <= value.keys()
    ):
        raise WorkspaceError("INVALID_ACTION_ENVELOPE")
    if not isinstance(value["action"], str) or not isinstance(value["arguments"], dict):
        raise WorkspaceError("INVALID_ACTION_ENVELOPE")
    action: Action = {"action": value["action"], "arguments": value["arguments"]}
    validate_action(action)
    return action, value.get("work_update")


def after_model(
    raw: str,
    *,
    workspace: Workspace,
    prepared: PreparedInput,
    registry: Mapping[str, Material],
    limits: Limits,
    count_text: Callable[[str], int],
    validate_action: Callable[[Action], None],
) -> AcceptedResponse:
    """Accept optional text independently of a valid action. Never dispatch here."""
    action, update = decode_action(raw, validate_action)
    if prepared.binding != workspace.binding or prepared.workspace_revision != workspace.revision:
        raise WorkspaceError("WORKSPACE_REQUEST_MISMATCH")
    if update is None:
        return AcceptedResponse(workspace, action, "UNCHANGED")
    try:
        if not isinstance(update, dict) or set(update) != {"text", "focus_refs"}:
            raise WorkspaceError("UPDATE_FIELDS")
        text, handles = update["text"], update["focus_refs"]
        if not isinstance(text, str) or not isinstance(handles, list):
            raise WorkspaceError("UPDATE_TYPES")
        if count_text(text) > limits.work_tokens:
            raise WorkspaceError("UPDATE_TEXT_BUDGET")
        if len(handles) > limits.focus_refs or any(not isinstance(ref, str) for ref in handles):
            raise WorkspaceError("UPDATE_REFERENCE_BUDGET_OR_TYPE")
        if len(set(handles)) != len(handles):
            raise WorkspaceError("UPDATE_DUPLICATE_REFERENCE")
        published = {handle: revision for handle, revision in prepared.available_refs}
        chosen = frozenset((handle, published.get(handle, "")) for handle in handles)
        if not chosen <= prepared.available_refs or not refs_current(
            chosen, registry, workspace.binding
        ):
            raise WorkspaceError("UPDATE_REFERENCE_UNAVAILABLE")
        dependencies = prepared.included_refs | chosen
        if not refs_current(dependencies, registry, workspace.binding):
            raise WorkspaceError("UPDATE_DISCLOSURE_CHANGED")
        if (
            text == workspace.text
            and tuple(handles) == workspace.focus_refs
            and prepared.workspace_visible
        ):
            return AcceptedResponse(workspace, action, "UNCHANGED")
        if not text and not handles:
            dependencies = frozenset()  # Explicitly empty body has nothing to disclose.
        updated = Workspace(
            workspace.binding, text, tuple(handles), workspace.revision + 1, dependencies
        )
        return AcceptedResponse(updated, action, "UPDATED")
    except WorkspaceError as exc:
        return AcceptedResponse(workspace, action, "REJECTED", str(exc))
