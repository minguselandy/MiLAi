"""One current memory view, OM page mechanics and independently scheduled control.

The OM superclass supplies event paging, source checks and omission ranges only.
Its observe/reflect/step/checkpoint algorithms are not used. Both adaptive policies
share this loop and the pure workspace patch also used by the historical RWC Host.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from milai_lab.methods.controlled_workspace import (
    FocusFrame,
    MemoryCard,
    WorkspaceSnapshot,
    apply_workspace_patch,
    validate_workspace_refs,
)
from milai_lab.methods.hiagent import HiAgentError, ModelCall
from milai_lab.methods.observational_memory import ObservationalMemoryHost, OMConfig, encoded

METHOD_VERSION = "milai-adaptive-memory-v0.1"
PROFILES = frozenset({"ADAPTIVE_MEMORY_SIMPLE", "ADAPTIVE_MEMORY_CANDIDATE"})
MODES = ("OBSERVE", "COMPACT", "REVISE", "REVIEW")


def _object(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


_TEXT = {"type": "string"}
_REFS = {"type": "array", "items": _TEXT, "maxItems": 64}
_NULLABLE_TEXT = {"type": ["string", "null"]}
_WORKSPACE_SCHEMA = _object({
    "working_note": _NULLABLE_TEXT,
    "put_cards": {"type": "array", "maxItems": 64, "items": _object({
        "handle": _NULLABLE_TEXT, "text": _TEXT, "source_refs": _REFS,
    }, ("text",))},
    "retire_cards": _REFS,
})
_FRAME_SCHEMA = _object({"question": _TEXT, "intent": _TEXT, "selected_refs": _REFS})
ADAPTIVE_OUTPUT_SCHEMA = _object({
    "observations": _TEXT,
    "group_updates": {"type": "array", "maxItems": 64, "items": _object({
        "handle": _TEXT, "text": {"type": "string", "minLength": 1},
    }, ("handle", "text"))},
    "workspace_update": {"anyOf": [_WORKSPACE_SCHEMA, {"type": "null"}]},
    "frame": {"anyOf": [_FRAME_SCHEMA, {"type": "null"}]},
    "dispatch": _object({
        "kind": {"enum": ["ACT", "RECALL", "DELIVER"]}, "refs": _REFS,
        "start": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 1, "maximum": 16000},
        "delivery": _NULLABLE_TEXT,
    }, ("kind",)),
})


@dataclass(frozen=True)
class AdaptiveMemoryConfig(OMConfig):
    maintenance_output_tokens: int = 2048
    max_delivery_reviews: int = 1
    max_recall_expansions: int = 2
    catalog_page_size: int = 64
    max_cards: int = 64

    def __post_init__(self) -> None:
        base = {name: getattr(self, name) for name in OMConfig.__dataclass_fields__}
        OMConfig(**base)
        if (
            type(self.max_delivery_reviews) is not int
            or self.max_delivery_reviews not in (0, 1)
            or any(type(n) is not int or n < 1 for n in (
                self.maintenance_output_tokens, self.max_recall_expansions,
                self.catalog_page_size, self.max_cards,
            ))
            or self.maintenance_output_tokens >= self.context_tokens
            or self.catalog_page_size > 64
        ):
            raise HiAgentError("INVALID_ADAPTIVE_CAPACITY")


@dataclass(frozen=True)
class MemoryView:
    """A disposable projection, never a second persistent writer or checkpoint."""

    brief: str
    frame: dict[str, Any]
    entries: list[dict[str, Any]] = field(default_factory=list)
    materials: list[dict[str, Any]] = field(default_factory=list)
    raw_pages: list[dict[str, Any]] = field(default_factory=list)
    selected_materials: list[dict[str, Any]] = field(default_factory=list)
    recalls: list[dict[str, Any]] = field(default_factory=list)
    pending_ranges: dict[str, Any] = field(default_factory=dict)
    source_index: dict[str, Any] = field(default_factory=dict)
    omitted_pages: list[dict[str, Any]] = field(default_factory=list)


class AdaptiveMemoryHost(ObservationalMemoryHost):
    config: AdaptiveMemoryConfig

    def __init__(
        self, *, profile: str, config: AdaptiveMemoryConfig | None = None, **kwargs: Any
    ) -> None:
        if profile not in PROFILES:
            raise HiAgentError("UNKNOWN_ADAPTIVE_PROFILE")
        super().__init__(config=config or AdaptiveMemoryConfig(), reflector_policy="", **kwargs)
        self.profile = profile
        self.calls = {"actor": 0, "maintenance": 0}
        self.mode_calls = dict.fromkeys(MODES, 0)
        self.workspace = WorkspaceSnapshot(frame=FocusFrame(question=self.goal))
        self.next_card = self.next_group = 1
        self.new_card_handles: list[str] = []
        self.compacted_groups: dict[str, dict[str, Any]] = {}
        self.pending_request: dict[str, Any] | None = None
        self.pending_control: dict[str, Any] | None = None
        self.pending_final: dict[str, Any] | None = None
        self.review_count = 0
        self.delivery_status: str | None = None
        self.feedback_revision = 0
        self.request_serial = 0
        self.state_revision = 0
        self.maintenance_attempts: dict[str, str] = {}
        self.recalls: list[dict[str, Any]] = []
        self.actor_seen_recalls = 0
        self.segments: list[dict[str, Any]] = []
        self.usage: dict[str, int | float] | None = None

    def _event(self, event: str, **fields: Any) -> None:
        super()._event(event.replace("OM_EVENT_APPENDED", "AM_EVENT_APPENDED"), **fields)

    def _remaining(self) -> int:
        return self.max_calls - sum(self.calls.values())

    def record_usage(self, prompt: int, completion: int, seconds: float) -> None:
        if self.usage is None:
            self.usage = {"input_tokens": 0, "output_tokens": 0, "provider_seconds": 0.0}
        self.usage["input_tokens"] += prompt
        self.usage["output_tokens"] += completion
        self.usage["provider_seconds"] += seconds

    def _fits(self, messages: tuple[dict[str, str], ...], role: str) -> bool:
        reserve = (self.config.actor_output_tokens if role == "actor"
                   else self.config.maintenance_output_tokens)
        return self.count_messages(messages) + reserve <= self.config.context_tokens

    def _messages(self, policy: str, body: dict[str, Any]) -> tuple[dict[str, str], ...]:
        # Public transport canonicalizes object keys. Stable wire serialization
        # preserves the same input after an otherwise unchanged process handoff.
        return ({"role": "system", "content": policy}, {"role": "user", "content": self.goal},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False, sort_keys=True,
                                                       separators=(",", ":"))})

    def _call(
        self, role: str, messages: tuple[dict[str, str], ...], *, mode: str | None = None
    ) -> str:
        self._assert_sources()
        if role not in self.calls or not self._fits(messages, role):
            raise HiAgentError("ADAPTIVE_INPUT_CAPACITY_OR_ROLE")
        if self._remaining() < 1:
            raise HiAgentError("TOTAL_MODEL_CALL_LIMIT")
        self.calls[role] += 1
        if mode is not None:
            self.mode_calls[mode] += 1
        request = ModelCall("actor" if role == "actor" else "maintenance", messages,
                            json_output=True)
        self._event("MODEL_CALL_ATTEMPT", call=sum(self.calls.values()), mode=mode,
                    request=asdict(request))
        self.phase = "MODEL_ACTOR" if role == "actor" else "MODEL_MAINTENANCE"
        output = self.generate(request)
        self._event("MODEL_RETURN", call=sum(self.calls.values()), kind=role, mode=mode,
                    output=output)
        if not isinstance(output, str):
            raise HiAgentError("NON_TEXT_MODEL_OUTPUT")
        self._assert_sources()
        self.phase = "ACTOR" if role == "actor" else "MAINTENANCE"
        return output

    def observe(self, observation: str) -> None:
        super().observe(observation)
        self.feedback_revision += 1
        self._invalidate_draft()

    def set_goal(self, goal: str) -> None:
        if self.phase != "IDLE" or self.halted or not isinstance(goal, str):
            raise HiAgentError("GOAL_UPDATE_REQUIRES_KNOWN_QUIESCENT_HOST")
        if goal == self.goal:
            return
        self.goal, self.goal_revision = goal, self.goal_revision + 1
        self.workspace = replace(self.workspace, frame=FocusFrame(question=goal),
                                 revision=self.workspace.revision + 1)
        self.pending_final = self.pending_control = self.pending_request = None
        self.review_count, self.finished, self.delivery_status = 0, False, None
        self.feedback_revision += 1
        self.state_revision += 1
        self._append("goal", goal)
        if self.observation_groups or self.workspace.cards or self.workspace.working_note:
            self._request("Current user goal changed; reconsider the existing work.", [])
        self._event("GOAL_CHANGED", goal_revision=self.goal_revision)

    def _invalidate_draft(self) -> None:
        if self.pending_final and self.pending_final["feedback_revision"] != self.feedback_revision:
            self.pending_final = None
            if self.pending_control and self.pending_control["mode"] == "REVIEW":
                self.pending_control = None
            self._event("DELIVERY_DRAFT_INVALIDATED", reason="NEW_FEEDBACK")

    def _known(self) -> set[str]:
        return ({e["ref"] for e in self.source_entries()}
                | {f"event:{e['id']}" for e in self.events}
                | set(self.workspace.cards) | {g["handle"] for g in self.observation_groups}
                | set(self.compacted_groups)
                | {"catalog:sources", "catalog:cards", "catalog:observations"})

    def _catalog(self, name: str) -> list[dict[str, Any]]:
        if name == "cards":
            return [{"ref": c.handle, "revision": c.revision, "retired": c.retired,
                     "preview": c.text[:150]} for c in sorted(
                         self.workspace.cards.values(), key=lambda c: int(c.handle.split(":")[1]))]
        if name == "observations":
            return ([{"ref": g["handle"], "revision": g["revision"], "preview": g["text"][:150]}
                     for g in self.observation_groups]
                    + [{"ref": h, "status": "COMPACTED", "replaced_by": g["replaced_by"]}
                       for h, g in sorted(self.compacted_groups.items(),
                                          key=lambda pair: int(pair[0].split(":")[1]))])
        return [*self.source_entries(), *[
            {"ref": f"event:{e['id']}", "kind": e["kind"], "total_chars": len(e["text"])}
            for e in self.events
        ]]

    def _read_intent(self, args: dict[str, Any]) -> tuple[list[str], int, int]:
        """Validate the request without reading bodies or performing the intent."""
        refs = validate_workspace_refs(args.get("refs"), known=self._known())
        start, length = args.get("start", 0), args.get("length", self.config.page_chars)
        if (not refs or len(refs) > self.config.catalog_page_size
                or type(start) is not int or start < 0 or type(length) is not int
                or not 1 <= length <= 16000):
            raise HiAgentError("INVALID_ADAPTIVE_READ_RANGE")
        return refs, start, length

    def _read(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        self._assert_sources()
        refs, start, length = self._read_intent(args)
        output = []
        active = {g["handle"]: g for g in self.observation_groups}
        for ref in refs:
            if ref.startswith("catalog:"):
                entries = self._catalog(ref.split(":", 1)[1])
                end = min(start + length, start + self.config.catalog_page_size)
                output.append({"ref": ref, "entries": entries[start:end], "start": start,
                               "total_entries": len(entries),
                               "next_start": end if end < len(entries) else None})
                continue
            if ref in self.compacted_groups:
                output.append({"ref": ref, "status": "COMPACTED",
                               **copy.deepcopy(self.compacted_groups[ref])})
                continue
            if ref in self.workspace.cards:
                card = self.workspace.cards[ref]
                text, revision = card.text, str(card.revision)
            elif ref in active:
                text, revision = active[ref]["text"], str(active[ref]["revision"])
            elif ref.startswith("event:"):
                text = self.events[int(ref.split(":", 1)[1])]["text"]
                revision = hashlib.sha256(text.encode()).hexdigest()
            else:
                page = self.read_source(ref, start, length)
                output.append({**page, "length": len(page["text"])})
                continue
            output.append({"ref": ref, "revision": revision, "start": start,
                           "text": text[start:start + length],
                           "length": len(text[start:start + length]),
                           "total_chars": len(text),
                           "next_start": start + length if start + length < len(text) else None})
        return output

    def _request(self, reason: str, refs: list[str]) -> None:
        validate_workspace_refs(refs, known=self._known())
        self.request_serial += 1
        self.pending_request = {"id": self.request_serial, "reason": reason, "refs": refs}
        self._event("MAINTENANCE_REQUESTED", request=self.pending_request)

    @staticmethod
    def _material_key(page: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(page.get(k) for k in ("ref", "revision", "start", "length"))

    def _view(
        self, role: str, *, mode: str | None = None, batch: list[int] | None = None,
        compact: list[str] | None = None,
    ) -> tuple[tuple[dict[str, str], ...], dict[str, Any]]:
        """One body bank, with omission metadata included in every capacity trial."""
        self._assert_sources()
        batch, compact = batch or [], compact or []
        unseen = [i for i in self.raw_tail if i not in self.actor_seen_pages]
        view = MemoryView(
            brief=self.workspace.working_note, frame=asdict(self.workspace.frame),
            pending_ranges={"unobserved": self._omissions(self.raw_tail),
                            "not_presented_to_actor": self._omissions(unseen)},
            source_index={name: {"entries": self._catalog(name)[:self.config.catalog_page_size],
                                 "total": len(self._catalog(name)), "read_ref": f"catalog:{name}"}
                          for name in ("sources", "cards", "observations")},
            omitted_pages=self._omissions(self.raw_tail),
        )
        body: dict[str, Any] = {
            "memory": asdict(view), "feedback": self.feedback, "goal_revision": self.goal_revision,
            "state_revision": self.state_revision,
            "call_budget": {"remaining": self._remaining(), "closing": self._remaining() <= 1},
            "mode": mode, "processing_pages": batch, "processing_groups": compact,
            "request": copy.deepcopy(self.pending_request), "request_materials_presented": False,
            "delivery_proposal": self.pending_final["text"] if self.pending_final else None,
            "delivery_review_active": mode == "REVIEW",
            "delivery_reviews_remaining": self.config.max_delivery_reviews - self.review_count,
        }
        policy = self.actor_policy if role == "actor" else self.summary_policy
        included: list[int] = []
        groups_shown: list[str] = []
        recalled_shown: list[int] = []

        def admit(mutator: Any, page_id: int | None = None) -> bool:
            candidate = copy.deepcopy(body)
            mutator(candidate["memory"])
            ids = included if page_id is None else [*included, page_id]
            candidate["memory"]["omitted_pages"] = self._omissions(
                [i for i in self.raw_tail if i not in ids]
            )
            if not self._fits(self._messages(policy, candidate), role):
                return False
            body["memory"] = candidate["memory"]
            return True

        def material(memory: dict[str, Any], page: dict[str, Any], slot: str) -> None:
            if "text" not in page:
                memory[slot].append(copy.deepcopy(page))
                return
            key = self._material_key(page)
            if not any(self._material_key(p) == key for p in memory["materials"]):
                memory["materials"].append(copy.deepcopy(page))
            memory[slot].append({k: page[k] for k in ("ref", "revision", "start", "length")})

        def raw_page(i: int) -> bool:
            if i in included:
                return True
            p = self.pages[i]
            page = {**p["source"], "text": p["text"], "page_id": i,
                    "event": p["event"], "action": p["action"]}
            if admit(lambda m: material(m, page, "raw_pages"), i):
                included.append(i)
                return True
            return False

        def group_entry(group: dict[str, Any]) -> bool:
            page = {"ref": group["handle"], "revision": str(group["revision"]),
                    "start": 0, "length": len(group["text"]), "text": group["text"],
                    "total_chars": len(group["text"]), "next_start": None}
            if admit(lambda m: material(m, page, "entries")):
                groups_shown.append(group["handle"])
                return True
            return False

        # The latest real feedback precedes optional memory. A mandatory batch
        # that cannot coexist with it is reduced by the planner, never hidden.
        if unseen and not raw_page(unseen[-1]):
            raise HiAgentError("ADAPTIVE_UNSEEN_INPUT_CAPACITY")
        for group in self.observation_groups:
            if group["handle"] in compact and not group_entry(group):
                raise HiAgentError("COMPACT_GROUP_INPUT_CAPACITY")
        for i in batch:
            if not raw_page(i):
                raise HiAgentError("MAINTENANCE_BATCH_INPUT_CAPACITY")
        for index in range(self.actor_seen_recalls, len(self.recalls)):
            def recalled(memory: dict[str, Any], index: int = index) -> None:
                for page in self.recalls[index]["results"]:
                    if page["ref"].startswith(("card:", "obs:")):
                        # A prior derived-body read must not resurrect a superseded
                        # default view. Raw immutable source reads remain unchanged.
                        page = self._read({"refs": [page["ref"]],
                                           "start": page.get("start", 0),
                                           "length": max(1, page.get("length", 4000))})[0]
                    material(memory, page, "recalls")
            if admit(recalled):
                recalled_shown.append(index)
            else:
                break
        refs = list(dict.fromkeys([
            *(self.pending_request or {}).get("refs", []), *self.workspace.frame.selected_refs,
            *self.new_card_handles,
        ]))
        presented_refs: set[str] = set()
        for ref in refs:
            pages = self._read({"refs": [ref], "length": 16000})
            def selected(memory: dict[str, Any], pages: list[dict[str, Any]] = pages) -> None:
                for page in pages:
                    material(memory, page, "selected_materials")
            if admit(selected):
                presented_refs.add(ref)
        for group in self.observation_groups:
            if group["handle"] not in groups_shown:
                group_entry(group)
        for i in dict.fromkeys([*reversed(unseen), *reversed(self.raw_tail)]):
            raw_page(i)
        body["request_materials_presented"] = bool(self.pending_request) and set(
            (self.pending_request or {}).get("refs", [])
        ) <= presented_refs
        messages = self._messages(policy, body)
        if not self._fits(messages, role):
            raise HiAgentError("ADAPTIVE_VIEW_METADATA_CAPACITY")
        # Selected/recalled current groups are also published in this input.
        active = {g["handle"]: str(g["revision"]) for g in self.observation_groups}
        for p in body["memory"]["materials"]:
            if p["ref"] in active and str(p["revision"]) == active[p["ref"]]:
                groups_shown.append(p["ref"])
        return messages, {
            "pages": included, "groups": list(dict.fromkeys(groups_shown)),
            "recalls": recalled_shown, "request_presented": body["request_materials_presented"],
            "body": body,
        }

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        return self._view("actor")[0]

    def _identity(self, mode: str, batch: list[int], compact: list[str]) -> str:
        value = [mode, batch, compact, self.goal_revision, self.feedback_revision,
                 self.workspace.revision, self.pending_request,
                 [(g["handle"], g["revision"]) for g in self.observation_groups]]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _plan(self, completed: set[str]) -> dict[str, Any] | None:
        if self.pending_control:
            return {**self.pending_control, "batch": [], "compact": []}
        groups = self.observation_groups
        total = self.count_text("\n".join(g["text"] for g in groups))
        _, projected = self._view("actor")
        omitted_groups = {g["handle"] for g in groups} - set(projected["groups"])
        if groups and "COMPACT" not in completed and (
            total >= self.config.reflection_tokens or omitted_groups
        ):
            compact: list[str] = []
            for group in groups:
                trial = [*compact, group["handle"]]
                try:
                    self._view("maintenance", mode="COMPACT", compact=trial)
                except HiAgentError as exc:
                    if "CAPACITY" not in str(exc):
                        raise
                    break
                compact = trial
            if compact and self._identity("COMPACT", [], compact) not in self.maintenance_attempts:
                return {"mode": "COMPACT", "batch": [], "compact": compact, "recalls": 0}
        if "OBSERVE" not in completed and self.count_text(
            encoded([self.pages[i] for i in self.raw_tail])
        ) >= self.config.observation_tokens:
            cutoff = len(self.events) - self.config.recent_events
            eligible = [i for i in self.raw_tail if i in self.actor_seen_pages
                        and self.pages[i]["event"] < cutoff]
            batch: list[int] = []
            for i in eligible:
                try:
                    self._view("maintenance", mode="OBSERVE", batch=[*batch, i])
                except HiAgentError as exc:
                    if "CAPACITY" not in str(exc):
                        raise
                    break
                batch.append(i)
            if batch and self._identity("OBSERVE", batch, []) not in self.maintenance_attempts:
                return {"mode": "OBSERVE", "batch": batch, "compact": [], "recalls": 0}
        if self.pending_request and "REVISE" not in completed:
            identity = self._identity("REVISE", [], [])
            if identity not in self.maintenance_attempts:
                return {"mode": "REVISE", "batch": [], "compact": [], "recalls": 0}
        return None

    def _dependencies(self, context: dict[str, Any]) -> tuple[list[int], list[dict[str, Any]]]:
        pages = set(context["pages"])
        ranges = [dict(self.pages[i]["source"]) for i in pages]
        for group in self.observation_groups:
            if group["handle"] in context["groups"]:
                pages.update(group["pages"])
                ranges.extend(copy.deepcopy(group["source_ranges"]))
        for p in context["body"]["memory"]["materials"]:
            if not p["length"]:
                # EOF metadata discloses no body range, including requests whose
                # start lies beyond the end of the immutable source.
                continue
            if p["ref"].startswith("event:") or p["ref"] in {
                e["ref"] for e in self.source_entries()
            }:
                ranges.append({k: p[k] for k in ("ref", "revision", "start", "length",
                                                "total_chars")})
        unique = {encoded(r): r for r in ranges}
        return sorted(pages), list(unique.values())

    def _accept(
        self, raw: str, *, mode: str, context: dict[str, Any],
        batch: list[int], compact: list[str],
    ) -> dict[str, Any]:
        from jsonschema import ValidationError, validate  # type: ignore[import-untyped]

        value = json.loads(raw)
        try:
            validate(value, ADAPTIVE_OUTPUT_SCHEMA)
        except ValidationError as exc:
            raise HiAgentError(f"INVALID_ADAPTIVE_PROPOSAL: {exc.message}") from exc
        text = value.get("observations", "").strip()
        if text and mode not in {"OBSERVE", "COMPACT"}:
            raise HiAgentError("OBSERVATIONS_REQUIRE_DECLARED_BATCH")
        patch = apply_workspace_patch(
            encoded({k: v for k, v in value.items() if k not in {"observations", "group_updates"}}),
            self.workspace, evidence_refs=self._known(), known_refs=self._known(),
            next_card=self.next_card, max_cards=self.config.max_cards,
            page_chars=self.config.page_chars, max_read_chars=16000,
            catalog_page_size=self.config.catalog_page_size, draft_available=self._draft_current(),
        )
        updates = value.get("group_updates", [])
        handles = [u["handle"] for u in updates]
        if (len(handles) != len(set(handles)) or not set(handles) <= set(context["groups"])
                or set(handles) & set(compact)):
            raise HiAgentError("INVALID_OR_CONFLICTING_GROUP_UPDATE")
        if (not set(batch) <= set(context["pages"]) or not set(batch) <= set(self.raw_tail)
                or not set(batch) <= self.actor_seen_pages
                or not set(compact) <= set(context["groups"])):
            raise HiAgentError("UNPRESENTED_MAINTENANCE_BATCH")
        groups = copy.deepcopy(self.observation_groups)
        archived = copy.deepcopy(self.compacted_groups)
        deps, ranges = self._dependencies(context)
        changed = patch.changed
        for update in updates:
            group = next(g for g in groups if g["handle"] == update["handle"])
            if group["text"] != update["text"]:
                group["text"], group["revision"] = update["text"], group["revision"] + 1
                group["pages"] = sorted(set(group["pages"]) | set(deps))
                union = {encoded(r): r for r in [*group["source_ranges"], *ranges]}
                group["source_ranges"] = list(union.values())
                changed = True
        workspace, next_group = patch.workspace, self.next_group
        covered: list[int] = []
        if text:
            if (mode == "OBSERVE" and not batch) or (mode == "COMPACT" and not compact):
                raise HiAgentError("EMPTY_MAINTENANCE_BATCH")
            handle = f"obs:{next_group}"
            next_group += 1
            if mode == "COMPACT":
                replaced = [g for g in groups if g["handle"] in compact]
                for group in replaced:
                    archived[group["handle"]] = {
                        "revision": group["revision"], "replaced_by": handle,
                        "source_ranges": group["source_ranges"], "pages": group["pages"],
                    }
                groups = [g for g in groups if g["handle"] not in compact]
                deps = sorted(set(deps) | {i for g in replaced for i in g["pages"]})
                union = {encoded(r): r for r in [*ranges, *[
                    r for g in replaced for r in g["source_ranges"]
                ]]}
                ranges = list(union.values())
                selected = list(dict.fromkeys(
                    handle if ref in compact else ref for ref in workspace.frame.selected_refs
                ))
                if selected != workspace.frame.selected_refs:
                    workspace = replace(workspace, frame=replace(workspace.frame,
                                        selected_refs=selected))
                    if not patch.changed:
                        workspace.revision += 1
            else:
                covered = batch
            groups.append({"handle": handle, "revision": 1, "text": text, "pages": deps,
                           "source_ranges": ranges, "mapping": "coarse_actual_input_union"})
            changed = True
        # Commit only after schema, patch, groups and source coverage all validate.
        self.workspace, self.next_card = workspace, patch.next_card
        self.observation_groups, self.compacted_groups = groups, archived
        self.next_group = next_group
        self.new_card_handles = list(dict.fromkeys([*self.new_card_handles, *patch.created]))
        self.raw_tail = [i for i in self.raw_tail if i not in covered]
        self.covered_ranges.extend(covered)
        self.state_revision += int(changed)
        self._event("ADAPTIVE_PATCH_ACCEPTED", mode=mode, changed=changed,
                    workspace_revision=workspace.revision, groups=groups, covered=covered,
                    created_cards=patch.created, compacted=compact if text else [],
                    frame=asdict(workspace.frame), route=patch.route)
        return {**patch.route, "changed": changed, "explicit_dispatch": patch.explicit_dispatch}

    def _recall(self, args: dict[str, Any], *, role: str) -> None:
        results = self._read(args)
        self.recalls.append({"role": role, "results": results})
        self._event("SOURCE_RECALLED", role=role, results=results)

    def _maintain(self, plan: dict[str, Any]) -> dict[str, Any]:
        mode, batch, compact = plan["mode"], plan["batch"], plan["compact"]
        messages, context = self._view("maintenance", mode=mode, batch=batch, compact=compact)
        if ((plan["recalls"] and len(self.recalls) - 1 not in context["recalls"])
                or (mode == "REVISE" and self.pending_request
                    and not context["request_presented"])):
            raise HiAgentError("PENDING_MATERIAL_INPUT_CAPACITY")
        identity = self._identity(mode, batch, compact)
        self.maintenance_attempts[identity] = "ATTEMPTED"
        self._event("MAINTENANCE_INPUT", mode=mode, pages=context["pages"],
                    groups=context["groups"], recalls=context["recalls"],
                    request_presented=context["request_presented"], remaining=self._remaining())
        raw = self._call("maintenance", messages, mode=mode)
        try:
            route = self._accept(raw, mode=mode, context=context, batch=batch, compact=compact)
            self.feedback = ""
        except ValueError as exc:
            route = {"kind": "ACT", "rejected": True, "changed": False,
                     "explicit_dispatch": False}
            self.feedback = "Maintenance proposal rejected; prior memory and raw pages retained."
            self._event("ADAPTIVE_PATCH_REJECTED", mode=mode, reason=str(exc), pages=batch)
        if context["request_presented"]:
            self.pending_request = None
        self.maintenance_attempts[identity] = "REJECTED" if route.get("rejected") else "SETTLED"
        # The resulting state is not a fresh reason to process the same scope.
        self.maintenance_attempts[self._identity(mode, batch, compact)] = "SETTLED"
        if mode == "COMPACT":
            current = [g["handle"] for g in self.observation_groups]
            self.maintenance_attempts[self._identity(mode, [], current)] = "SETTLED"
        self.pending_control = None
        return route

    def _draft_current(self) -> bool:
        return bool(self.pending_final and
                    self.pending_final["feedback_revision"] == self.feedback_revision)

    def _submit(self, text: str, *, status: str, reason: str) -> None:
        self._assert_sources()
        action = {"action": "final", "arguments": {"text": text}}
        self.validate_action(action)
        self.phase = "DISPATCH"
        self._event("REAL_DISPATCH_ATTEMPT", action=action)
        result = self.dispatch(action)
        self._event("REAL_OBSERVATION", action=action, observation=result)
        self.pending_final = self.pending_control = None
        self.finished, self.delivery_status = True, status
        self._event("DELIVERY_COMPLETED", status=status, reason=reason, text=text)

    def _incomplete(self, reason: str) -> None:
        self._submit(
            "The model-call budget is exhausted. Task completion is not established. "
            "The last proposed action was not executed. Recorded work remains available "
            "for continuation in the same task environment.",
            status="INCOMPLETE", reason=reason,
        )

    def _parse_actor(self, raw: str) -> tuple[dict[str, Any], str | None]:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise HiAgentError("INVALID_ACTION_ENVELOPE")
        name, args = value.get("action"), value.get("arguments")
        if not isinstance(name, str) or not isinstance(args, dict):
            raise HiAgentError("INVALID_ACTION_ENVELOPE")
        if name in {"retrieve", "maintain"}:
            allowed = {"refs", "start", "length"} if name == "retrieve" else {"reason", "refs"}
            if not set(args) <= allowed:
                raise HiAgentError("INVALID_INTERNAL_ACTION_ARGUMENTS")
            if name == "retrieve":
                self._read_intent(args)
            elif not isinstance(args.get("reason"), str):
                raise HiAgentError("INVALID_MAINTENANCE_REQUEST")
            else:
                validate_workspace_refs(args.get("refs", []), known=self._known())
        else:
            self.validate_action({"action": name, "arguments": args})
            if name == "read":
                self._read_intent({"refs": [args["ref"]], "start": args.get("start", 0),
                                   "length": args.get("length", self.config.page_chars)})
        subgoal = value.get("subgoal")
        if subgoal is not None and not isinstance(subgoal, str):
            raise HiAgentError("INVALID_SUBGOAL_METADATA")
        return {"action": name, "arguments": args}, subgoal

    def _seen_input(self, context: dict[str, Any]) -> None:
        self.actor_seen_pages.update(context["pages"])
        for material in context["body"]["memory"]["materials"]:
            for page in self.pages:
                source = page["source"]
                if (material["ref"] == source["ref"]
                        and str(material["revision"]) == str(source["revision"])
                        and material["start"] <= source["start"]
                        and material["start"] + material["length"] >=
                        source["start"] + source["length"]):
                    self.actor_seen_pages.add(page["id"])
        if context["recalls"]:
            self.actor_seen_recalls = max(context["recalls"]) + 1
        self._event("ACTOR_INPUT", pages=sorted(self.actor_seen_pages),
                    presented_pages=context["pages"], groups=context["groups"],
                    materials=[{k: p[k] for k in ("ref", "revision", "start", "length")}
                               for p in context["body"]["memory"]["materials"]])

    def step(self) -> None:
        if self.halted or self.finished or self.phase != "IDLE":
            raise HiAgentError("HOST_NOT_ACTIVE")
        try:
            self.phase = "MAINTENANCE"
            self._assert_sources()
            self._invalidate_draft()
            if self._draft_current() and not self.pending_control:
                if (self.review_count >= self.config.max_delivery_reviews
                        or self._remaining() < 2):
                    assert self.pending_final is not None
                    self._submit(self.pending_final["text"], status="UNREVIEWED",
                                 reason="REVIEW_UNAVAILABLE")
                    return
                self.pending_control = {"mode": "REVIEW", "recalls": 0}
                self.review_count += 1
            if self._remaining() == 0:
                self._incomplete("NO_ENDING_CALL_REMAINS")
                return
            completed: set[str] = set()
            while self._remaining() > 1:
                plan = self._plan(completed)
                if plan is None:
                    break
                try:
                    route = self._maintain(plan)
                except HiAgentError as exc:
                    if "CAPACITY" not in str(exc) or self.phase != "MAINTENANCE":
                        raise
                    self.feedback = "Maintenance input did not fit; pending work retained."
                    self._event("MAINTENANCE_DEFERRED", mode=plan["mode"], reason=str(exc))
                    if plan["mode"] == "REVIEW" and self._draft_current():
                        assert self.pending_final is not None
                        self._submit(self.pending_final["text"], status="UNREVIEWED",
                                     reason="REVIEW_INPUT_UNAVAILABLE")
                        return
                    break
                completed.add(plan["mode"])
                if plan["mode"] == "OBSERVE":
                    # Compaction precedes observation at a boundary. Newly created
                    # groups can be compacted at the next applicable boundary.
                    completed.add("COMPACT")
                if plan["mode"] == "REVIEW" and self._draft_current() and (
                    route.get("rejected") or
                    (not route["explicit_dispatch"] and not route["changed"])
                ):
                    assert self.pending_final is not None
                    self._submit(self.pending_final["text"], status="UNREVIEWED",
                                 reason="REVIEW_UNUSABLE_OR_UNCHANGED")
                    return
                if route["kind"] == "DELIVER":
                    assert self.pending_final is not None
                    self._submit(route["delivery"] if route["delivery"] is not None
                                 else self.pending_final["text"], status="REVIEWED",
                                 reason="EXPLICIT_DELIVER")
                    return
                if route["kind"] == "RECALL":
                    if plan["recalls"] < self.config.max_recall_expansions:
                        self._recall(route, role="maintenance")
                        self.pending_control = {
                            "mode": "REVIEW" if plan["mode"] == "REVIEW" else "REVISE",
                            "recalls": plan["recalls"] + 1,
                        }
                        if self._remaining() > 1:
                            # A known boundary makes the pending continuation resumable.
                            return
                    else:
                        self.feedback = "RECALL_LIMIT_REACHED_NOT_EVIDENCE_EXHAUSTION"
                    break
                if plan["mode"] in {"REVISE", "REVIEW"} or route.get("rejected"):
                    break
            self.phase = "ACTOR"
            closing = self._remaining() == 1
            messages, context = self._view("actor")
            raw = self._call("actor", messages)
            self._seen_input(context)
            self.initialized = True
            self.new_card_handles.clear()
            self.pending_final = None
            # An ACT decision hands control back, ending the prior review opportunity.
            self.pending_control = None
            self.feedback = ""
            try:
                action, subgoal = self._parse_actor(raw)
            except ValueError as exc:
                self.feedback = "Actor output rejected; no action executed."
                self._event("ACTOR_REJECTED", reason=str(exc))
                if closing:
                    self._incomplete("ENDING_ACTOR_INVALID")
                return
            if closing and action["action"] != "final":
                self._event("ENDING_ACTION_NOT_EXECUTED", action=action)
                self._incomplete("ENDING_ACTOR_DID_NOT_DELIVER")
                return
            if subgoal is not None and (not self.segments or
                                        self.segments[-1]["subgoal"] != subgoal):
                self.segments.append({"subgoal": subgoal, "event": len(self.events),
                                      "call": sum(self.calls.values())})
                self._event("WORK_SEGMENT_CHANGED", subgoal=subgoal)
            name, args = action["action"], action["arguments"]
            if name == "maintain":
                self._request(args["reason"], args.get("refs", []))
            elif name == "retrieve":
                self._recall(args, role="actor")
                self.feedback_revision += 1
            elif name == "final":
                self.pending_final = {"text": args["text"],
                                      "feedback_revision": self.feedback_revision}
                self._event("DELIVERY_PROPOSED", text=args["text"])
                if self.review_count >= self.config.max_delivery_reviews or self._remaining() < 2:
                    self._submit(args["text"], status="UNREVIEWED", reason="REVIEW_UNAVAILABLE")
            else:
                self.phase = "DISPATCH"
                self._event("REAL_DISPATCH_ATTEMPT", action=action)
                observation = self.dispatch(action)
                self._append("tool", observation, action)
                self.feedback_revision += 1
                self._event("REAL_OBSERVATION", action=action, observation=observation)
        except BaseException as exc:
            self.halted = True
            self._event("HOST_STOPPED", error=str(exc), phase=self.phase)
            raise
        finally:
            self.phase = "FAILED" if self.halted else "IDLE"

    def _contract(self) -> dict[str, Any]:
        return {"method": METHOD_VERSION, "profile": self.profile,
                "config": asdict(self.config), "model_profile": self.model_profile,
                "max_calls": self.max_calls, "policy_hash": hashlib.sha256(
                    encoded([self.actor_policy, self.summary_policy]).encode()).hexdigest()}

    def snapshot(self) -> dict[str, Any]:
        names = (
            "phase", "halted", "finished", "initialized", "calls", "mode_calls", "events",
            "pages", "raw_tail", "covered_ranges", "observation_groups", "compacted_groups",
            "next_card", "next_group", "new_card_handles", "pending_request", "pending_control",
            "pending_final", "review_count", "delivery_status", "feedback_revision",
            "request_serial", "state_revision", "maintenance_attempts", "recalls",
            "actor_seen_recalls", "segments", "usage", "feedback", "goal_revision",
        )
        return copy.deepcopy({"method": METHOD_VERSION, "profile": self.profile,
                              **{name: getattr(self, name) for name in names},
                              "workspace": asdict(self.workspace),
                              "actor_seen_pages": sorted(self.actor_seen_pages)})

    def checkpoint(self) -> dict[str, Any]:
        if self.phase != "IDLE" or self.halted:
            raise HiAgentError("CHECKPOINT_REQUIRES_KNOWN_QUIESCENT_BOUNDARY")
        self._assert_sources()
        return {"contract": self._contract(), "goal": self.goal, "state": self.snapshot()}

    def restore(self, checkpoint: dict[str, Any]) -> None:
        if self.initialized or any(self.calls.values()) or self.halted or self.phase != "IDLE":
            raise HiAgentError("RESTORE_REQUIRES_FRESH_HOST")
        if checkpoint.get("contract") != self._contract():
            raise HiAgentError("CHECKPOINT_CONTRACT_MISMATCH")
        candidate = copy.copy(self)
        candidate.emit = None
        try:
            state = copy.deepcopy(checkpoint["state"])
            if (state["phase"] != "IDLE" or state["halted"] is not False
                    or state["method"] != METHOD_VERSION or state["profile"] != self.profile):
                raise HiAgentError("CHECKPOINT_HAS_UNRESOLVED_OPERATIONS")
            for key in self.snapshot():
                if key not in {"method", "profile", "workspace", "actor_seen_pages"}:
                    setattr(candidate, key, state[key])
            workspace = state["workspace"]
            candidate.workspace = WorkspaceSnapshot(
                working_note=workspace["working_note"], revision=workspace["revision"],
                frame=FocusFrame(**workspace["frame"]),
                cards={h: MemoryCard(**c) for h, c in workspace["cards"].items()},
            )
            candidate.actor_seen_pages = set(state["actor_seen_pages"])
            candidate.goal = checkpoint["goal"]
            candidate._validate_restored()
            candidate._assert_sources()
            if candidate.goal != self.goal:
                candidate.set_goal(self.goal)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise HiAgentError(f"INVALID_ADAPTIVE_CHECKPOINT: {exc}") from exc
        candidate.emit = self.emit
        self.__dict__.update(candidate.__dict__)
        self._event("CHECKPOINT_RESTORED", method=METHOD_VERSION,
                    goal_revision=self.goal_revision, calls=self.calls)

    def _validate_restored(self) -> None:
        ids = set(range(len(self.pages)))
        groups = {g["handle"]: g for g in self.observation_groups}
        handles = set(groups) | set(self.compacted_groups)
        if (
            [p["id"] for p in self.pages] != list(range(len(self.pages)))
            or [e["id"] for e in self.events] != list(range(len(self.events)))
            or len(set(self.raw_tail)) != len(self.raw_tail)
            or len(set(self.covered_ranges)) != len(self.covered_ranges)
            or set(self.raw_tail) & set(self.covered_ranges)
            or set(self.raw_tail) | set(self.covered_ranges) != ids
            or not set(self.covered_ranges) <= self.actor_seen_pages <= ids
            or set(self.calls) != {"actor", "maintenance"} or set(self.mode_calls) != set(MODES)
            or any(type(n) is not int or n < 0 for n in [*self.calls.values(),
                                                      *self.mode_calls.values()])
            or sum(self.calls.values()) > self.max_calls
            or sum(self.mode_calls.values()) != self.calls["maintenance"]
            or len(groups) != len(self.observation_groups)
            or set(groups) & set(self.compacted_groups)
            or handles != {f"obs:{i}" for i in range(1, self.next_group)}
            or set(self.workspace.cards) != {f"card:{i}" for i in range(1, self.next_card)}
            or not 0 <= self.review_count <= self.config.max_delivery_reviews
            or not 0 <= self.actor_seen_recalls <= len(self.recalls)
            or self.delivery_status not in {None, "REVIEWED", "UNREVIEWED", "INCOMPLETE"}
            or self.finished != (self.delivery_status is not None)
            or (self.pending_final is not None and not self._draft_current())
        ):
            raise HiAgentError("INVALID_ADAPTIVE_STATE")
        known = self._known()
        if (not isinstance(self.goal, str) or not isinstance(self.workspace.working_note, str)
                or type(self.workspace.revision) is not int or self.workspace.revision < 0
                or not isinstance(self.workspace.frame.question, str)
                or not isinstance(self.workspace.frame.intent, str)
                or any(type(n) is not int or n < 0 for n in (
                    self.feedback_revision, self.request_serial, self.state_revision,
                    self.goal_revision - 1,
                ))):
            raise HiAgentError("INVALID_WORKSPACE_STATE")
        validate_workspace_refs(self.workspace.frame.selected_refs, known=known)
        for handle, card in self.workspace.cards.items():
            validate_workspace_refs(card.source_refs, known=known)
            if (type(card.revision) is not int or card.revision < 1 or card.handle != handle
                    or not isinstance(card.text, str) or type(card.retired) is not bool):
                raise HiAgentError("INVALID_CARD_REVISION")
        if sum(not c.retired for c in self.workspace.cards.values()) > self.config.max_cards:
            raise HiAgentError("ACTIVE_CARD_CAPACITY")
        if self.pending_request:
            validate_workspace_refs(self.pending_request["refs"], known=known)
        if self.pending_control and (
            self.pending_control["mode"] not in {"REVIEW", "REVISE"}
            or not 0 <= self.pending_control["recalls"] <= self.config.max_recall_expansions
        ):
            raise HiAgentError("INVALID_PENDING_CONTROL")
        if self.pending_control and self.pending_control["mode"] == "REVIEW" and (
            not self._draft_current() or not self.review_count
        ):
            raise HiAgentError("REVIEW_WITHOUT_CURRENT_DRAFT")
        regenerated = copy.copy(self)
        regenerated.emit = None
        regenerated.pages, regenerated.events, regenerated.raw_tail = [], [], []
        for event in self.events:
            regenerated._append(event["kind"], event["text"], event["action"])
        if regenerated.pages != self.pages or regenerated.events != self.events:
            raise HiAgentError("EVENT_PAGE_ARCHIVE_MISMATCH")
        available = {e["ref"]: e for e in self.source_entries()}
        available.update({f"event:{e['id']}": {
            "revision": hashlib.sha256(e["text"].encode()).hexdigest(),
            "total_chars": len(e["text"]),
        } for e in self.events})
        for page in self.pages:
            source = page["source"]
            entry = available[source["ref"]]
            if (source["revision"] != entry["revision"]
                    or source["total_chars"] != entry["total_chars"]
                    or source["length"] != len(page["text"])
                    or not 0 <= source["start"] <= entry["total_chars"]
                    or source["start"] + source["length"] > entry["total_chars"]
                    or page["event"] not in range(len(self.events))):
                raise HiAgentError("INVALID_SOURCE_PAGE")
            actual = self._read({"refs": [source["ref"]], "start": source["start"],
                                 "length": max(1, source["length"])})[0]
            if actual["text"] != page["text"]:
                raise HiAgentError("SOURCE_PAGE_CONTENT_MISMATCH")
        for group in [*groups.values(), *self.compacted_groups.values()]:
            if (type(group["revision"]) is not int or group["revision"] < 1
                    or not set(group["pages"]) <= ids):
                raise HiAgentError("INVALID_GROUP_DEPENDENCY")
            for source in group["source_ranges"]:
                entry = available[source["ref"]]
                if (source["revision"] != entry["revision"]
                        or not 0 <= source["start"] <= entry["total_chars"]
                        or not 0 <= source["length"] <= entry["total_chars"] - source["start"]):
                    raise HiAgentError("INVALID_GROUP_SOURCE_RANGE")
        if any(g["replaced_by"] not in handles for g in self.compacted_groups.values()):
            raise HiAgentError("INVALID_COMPACTED_GROUP_TARGET")
        if any(int(g["replaced_by"].split(":")[1]) <= int(h.split(":")[1])
               for h, g in self.compacted_groups.items()):
            raise HiAgentError("CYCLIC_COMPACTION_HISTORY")
