"""Reversible workspace control; model policy remains separate from mechanics.

The previous CONTROL_0 implementation is retained. Both new policies use this
same serial loop, immutable receipt reader, projection and checkpoint contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from milai_lab.methods.hiagent import HiAgentError, ModelCall, Pair, Segment
from milai_lab.methods.workspace_control import WorkingControl, WorkspaceControlHost

METHOD_VERSION = "milai-rwc-v0.4"


@dataclass
class MemoryCard:
    handle: str
    text: str
    source_refs: list[str]
    revision: int = 1
    retired: bool = False


@dataclass
class FocusFrame:
    question: str = ""
    intent: str = ""
    selected_refs: list[str] = field(default_factory=list)


@dataclass
class WorkspaceSnapshot:
    working_note: str = ""
    cards: dict[str, MemoryCard] = field(default_factory=dict)
    frame: FocusFrame = field(default_factory=FocusFrame)
    revision: int = 0


@dataclass(frozen=True)
class WorkspacePatch:
    workspace: WorkspaceSnapshot
    next_card: int
    created: list[str]
    route: dict[str, Any]
    classification: str
    changed: bool
    explicit_dispatch: bool


def validate_workspace_refs(refs: Any, *, known: set[str]) -> list[str]:
    if (
        not isinstance(refs, list)
        or any(not isinstance(ref, str) for ref in refs)
        or len(refs) != len(set(refs))
        or not set(refs) <= known
    ):
        raise HiAgentError("UNPUBLISHED_WORKSPACE_REFERENCE")
    return list(refs)


def apply_workspace_patch(
    raw: str,
    previous: WorkspaceSnapshot,
    *,
    evidence_refs: set[str],
    known_refs: set[str],
    next_card: int,
    max_cards: int = 64,
    page_chars: int = 16000,
    max_read_chars: int | None = None,
    catalog_page_size: int = 64,
    draft_available: bool = False,
) -> WorkspacePatch:
    """Pure sparse proposal: validate the whole patch before either Host commits it."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise HiAgentError("INVALID_WORKSPACE_PROPOSAL")
    known = known_refs
    incoming_frame = value.get("frame")
    if incoming_frame is not None and not isinstance(incoming_frame, dict):
        raise HiAgentError("INVALID_FOCUS_FRAME")
    frame = {
        key: (incoming_frame or {}).get(key, old)
        for key, old in asdict(previous.frame).items()
    }
    if any(not isinstance(frame[k], str) for k in ("question", "intent")):
        raise HiAgentError("INVALID_FOCUS_FRAME")
    selected = frame["selected_refs"]
    if not isinstance(selected, list) or any(not isinstance(r, str) for r in selected):
        raise HiAgentError("UNPUBLISHED_WORKSPACE_REFERENCE")
    frame["selected_refs"] = validate_workspace_refs(list(dict.fromkeys(selected)), known=known)
    dispatch = value.get("dispatch", {"kind": "ACT"})
    if not isinstance(dispatch, dict) or dispatch.get("kind") not in (
        "ACT",
        "RECALL",
        "DELIVER",
    ):
        raise HiAgentError("INVALID_CONTROL_DISPATCH")
    route: dict[str, Any] = {"kind": dispatch["kind"], "refs": [], "delivery": None}
    if route["kind"] == "RECALL":
        route["refs"] = validate_workspace_refs(dispatch.get("refs", []), known=known)
        if not route["refs"] or len(route["refs"]) > catalog_page_size:
            raise HiAgentError("INVALID_RECALL_REQUEST")
        for key, default, low, high in (
            ("start", 0, 0, 2**31),
            ("length", page_chars, 1, max_read_chars or page_chars),
        ):
            v = dispatch.get(key, default)
            if type(v) is not int or not low <= v <= high:
                raise HiAgentError("INVALID_RECALL_RANGE")
            route[key] = v
    elif route["kind"] == "DELIVER":
        route["delivery"] = dispatch.get("delivery")
        if not draft_available or not isinstance(
            route["delivery"], (str, type(None))
        ):
            raise HiAgentError("DELIVER_REQUIRES_FINAL_PROPOSAL")

    update = value.get("workspace_update")
    workspace = replace(previous, frame=FocusFrame(**frame))
    created: list[str] = []
    normalized_update: dict[str, Any] | None = None
    if update is not None:
        if not isinstance(update, dict):
            raise HiAgentError("INVALID_WORKSPACE_UPDATE")
        note = update.get("working_note")
        puts = update.get("put_cards", [])
        if not isinstance(note, (str, type(None))) or not isinstance(puts, list):
            raise HiAgentError("INVALID_WORKSPACE_UPDATE")
        retired = validate_workspace_refs(
            update.get("retire_cards", []), known=set(workspace.cards)
        )
        normalized_update = {"working_note": note, "put_cards": [], "retire_cards": retired}
        if note is not None:
            workspace.working_note = note
        # Reuse unchanged cards; replacement objects keep rejection atomic.
        if puts or retired:
            workspace.cards = dict(workspace.cards)
        changed: set[str] = set()
        for item in puts:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise HiAgentError("INVALID_MEMORY_CARD")
            handle = item.get("handle")
            old = None
            if handle is None:
                handle = f"card:{next_card}"
                next_card += 1
                created.append(handle)
            elif not isinstance(handle, str) or handle not in previous.cards:
                raise HiAgentError("UNKNOWN_CARD_HANDLE")
            else:
                old = previous.cards[handle]
            if handle in changed or handle in retired:
                raise HiAgentError("CONFLICTING_CARD_UPDATE")
            refs = validate_workspace_refs(
                item.get("source_refs", old.source_refs if old else []), known=evidence_refs
            )
            normalized_update["put_cards"].append(
                {"handle": item.get("handle"), "text": item["text"], "source_refs": refs}
            )
            if old is None or (old.text, old.source_refs, old.retired) != (
                item["text"],
                refs,
                False,
            ):
                workspace.cards[handle] = MemoryCard(
                    handle, item["text"], refs, 1 if old is None else old.revision + 1
                )
            changed.add(handle)
        for handle in retired:
            old = workspace.cards[handle]
            if not old.retired:
                workspace.cards[handle] = replace(old, retired=True, revision=old.revision + 1)
        if sum(not c.retired for c in workspace.cards.values()) > max_cards:
            raise HiAgentError("ACTIVE_CARD_CAPACITY")
    normalized = {"workspace_update": normalized_update, "frame": frame, "dispatch": route}
    # Read defaults are optional in the complete wire form too.
    direct = dict(normalized)
    if route["kind"] == "RECALL":
        direct["dispatch"] = {
            k: v for k, v in route.items() if k in dispatch or k in ("kind", "refs", "delivery")
        }
    classification = "DIRECT" if value == direct else "NORMALIZED"
    changed_content = workspace != previous
    if changed_content:
        workspace.revision += 1
    else:
        workspace = previous

    return WorkspacePatch(
        workspace, next_card, created, route, classification, changed_content, "dispatch" in value
    )


class ReversibleWorkspaceHost(WorkspaceControlHost):
    """Controller -> optional recall -> Actor, with protected unseen observations.

    Source callbacks return immutable, scope-checked pages. Business actions keep
    the existing terminal contract. The Host never interprets evidence semantics.
    """

    def __init__(
        self,
        *,
        read_source: Callable[[str, int, int], dict[str, Any]],
        archive_summary_policy: str,
        model_profile: str = "caller-bound",
        max_recall_expansions: int = 2,
        page_chars: int = 16000,
        material_chars: int = 64000,
        catalog_page_size: int = 64,
        max_cards: int = 64,
        use_summary_cache: bool = True,
        feedback_batch_size: int = 1,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("max_delivery_reviews", 1)
        super().__init__(**kwargs)
        for value in (
            max_recall_expansions,
            page_chars,
            material_chars,
            catalog_page_size,
            max_cards,
            feedback_batch_size,
        ):
            if type(value) is not int or value < 1:
                raise HiAgentError("INVALID_WORKSPACE_CAPACITY")
        if page_chars > 16000 or material_chars < page_chars or type(use_summary_cache) is not bool:
            raise HiAgentError("INVALID_WORKSPACE_CAPACITY")
        self.read_source = read_source
        self.archive_summary_policy, self.model_profile = archive_summary_policy, model_profile
        self.max_recall_expansions, self.page_chars = max_recall_expansions, page_chars
        self.material_chars, self.catalog_page_size = material_chars, catalog_page_size
        self.max_cards, self.use_summary_cache = max_cards, use_summary_cache
        self.feedback_batch_size = feedback_batch_size
        self.workspace = WorkspaceSnapshot(frame=FocusFrame(question=self.goal))
        self.next_card = 1
        self.new_card_handles: list[str] = []
        self.recall_observations: list[dict[str, Any]] = []
        self.maintained_recalls = self.actor_seen_recalls = 0
        self.summary_cache: dict[int, str] = {}
        self.resume_pending = False
        self.goal_revision = 1
        self.delivery_status: str | None = None

    def _known(self) -> set[str]:
        return (
            {entry["ref"] for entry in self.source_entries()}
            | {f"seg:{s.number}" for s in self.segments}
            | set(self.workspace.cards)
            | {"catalog:sources", "catalog:cards", "catalog:segments"}
        )

    def _refs(self, refs: Any, *, allowed: set[str] | None = None) -> list[str]:
        universe = self._known() if allowed is None else allowed
        if (
            not isinstance(refs, list)
            or any(not isinstance(ref, str) for ref in refs)
            or len(refs) != len(set(refs))
            or not set(refs) <= universe
        ):
            raise HiAgentError("UNPUBLISHED_WORKSPACE_REFERENCE")
        return list(refs)

    def _accept(self, raw: str) -> dict[str, Any]:
        source_refs = {e["ref"] for e in self.source_entries()}
        evidence_refs = source_refs | {f"seg:{s.number}" for s in self.segments}
        patch = apply_workspace_patch(
            raw, self.workspace, evidence_refs=evidence_refs, known_refs=self._known(),
            next_card=self.next_card, max_cards=self.max_cards, page_chars=self.page_chars,
            catalog_page_size=self.catalog_page_size,
            draft_available=self.delivery_proposal is not None,
        )
        workspace, route = patch.workspace, patch.route
        frame = asdict(workspace.frame)
        self.workspace, self.next_card = workspace, patch.next_card
        self.new_card_handles.extend(patch.created)
        self.expanded = {int(ref[4:]) for ref in frame["selected_refs"] if ref.startswith("seg:")}
        self.control = WorkingControl(
            workspace.working_note, frame["question"], frame["intent"], sorted(self.expanded),
            [ref for ref in frame["selected_refs"] if ref in source_refs],
        )
        self.record, self.record_revision = workspace.working_note, workspace.revision
        self._event(
            "WORKSPACE_ACCEPTED", workspace=asdict(workspace), created=patch.created,
            dispatch=route, classification=patch.classification, changed=patch.changed,
            input_cursor=self._cursor(), goal_revision=self.goal_revision,
        )
        return {**route, "explicit_dispatch": patch.explicit_dispatch, "changed": patch.changed}

    def _cursor(self) -> tuple[int, int, int]:
        return len(self._pairs()), len(self.external_observations), len(self.recall_observations)

    def _remaining_calls(self) -> int:
        return self.max_calls - sum(self.calls.values())

    def _control_reason(self) -> str | None:
        if self.delivery_proposal is not None:
            return "delivery"
        if self.resume_pending:
            return "resume"
        if not self.initialized:
            return "initial"
        if len(self.external_observations) != self.maintained_external:
            return "external_feedback"
        if len(self.recall_observations) != self.maintained_recalls:
            return "recall"
        pairs = self._pairs()
        if len(pairs) - self.maintained_pairs >= self.feedback_batch_size:
            return "feedback"
        # A new subgoal closes an input segment. Maintain before its details
        # leave the normal working set, even when the feedback batch is small.
        maintained_segment = (
            pairs[self.maintained_pairs - 1]["segment"] if self.maintained_pairs else 1
        )
        if pairs and pairs[-1]["segment"] != maintained_segment:
            return "context_boundary"
        return None

    def _summary_once(self, reserve_calls: int = 2) -> None:
        if not self.use_summary_cache:
            return
        for segment in self.segments[:-1]:
            if segment.number in self.expanded:
                continue
            body = {"subgoal": segment.subgoal, "trajectory": [asdict(p) for p in segment.pairs]}
            identity = hashlib.sha256(
                json.dumps(
                    [body, self.archive_summary_policy, self.model_profile],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if self.summary_cache.get(segment.number) == identity:
                self._event("SUMMARY_REUSED", segment=segment.number, source_identity=identity)
                continue
            if self._remaining_calls() <= reserve_calls:
                self._event(
                    "SUMMARY_DEFERRED", reason="RESERVE_ENDING_ACTOR", segment=segment.number
                )
                break
            self._assert_readable_dependencies()
            result = self._call(
                ModelCall(
                    "summary",
                    (
                        {"role": "system", "content": self.archive_summary_policy},
                        {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
                    ),
                    segment.number,
                )
            ).strip()
            segment.summary = result or None
            self.summary_cache[segment.number] = identity
            self._event(
                "SUMMARY_REPLACED",
                segment=segment.number,
                summary=segment.summary,
                degraded_empty=not result,
                source_identity=identity,
            )

    def _catalog(self, name: str) -> list[dict[str, Any]]:
        if name == "sources":
            return self.source_entries()
        if name == "cards":
            return [
                {
                    "ref": c.handle,
                    "preview": c.text[:160],
                    "revision": c.revision,
                    "retired": c.retired,
                }
                for c in sorted(self.workspace.cards.values(), key=lambda c: c.retired)
            ]
        return [
            {"ref": f"seg:{s.number}", "subgoal": s.subgoal, "summary": s.summary}
            for s in self.segments
        ]

    def _projection(self, *, controller: bool) -> dict[str, Any]:
        """Put each source/version/range in one bank; links retain event identity."""
        self._assert_readable_dependencies()
        pairs = self._pairs()
        cursor = self.maintained_pairs if controller else self.actor_seen_pairs
        external_cursor = self.maintained_external if controller else self.actor_seen_external
        recall_cursor = self.maintained_recalls if controller else self.actor_seen_recalls
        materials: dict[tuple[str, str, int, int], dict[str, Any]] = {}
        omitted: list[dict[str, Any]] = []
        used = 0
        known_sources = {e["ref"] for e in self.source_entries()}

        def source(
            ref: str, start: int = 0, length: int | None = None, protected: bool = False
        ) -> dict[str, Any]:
            nonlocal used
            page = self.read_source(ref, start, self.page_chars if length is None else length)
            key = (ref, page["revision"], page["start"], len(page["text"]))
            link = {
                "ref": ref,
                "revision": page["revision"],
                "start": page["start"],
                "length": len(page["text"]),
            }
            if key not in materials:
                if used + len(page["text"]) > self.material_chars:
                    if protected:
                        raise HiAgentError("PROTECTED_INPUT_REQUIRES_SMALLER_SOURCE_PAGES")
                    omitted.append(link)
                    return {
                        **link,
                        "presented": False,
                        "reason": "MATERIAL_CAPACITY_READ_AVAILABLE",
                    }
                materials[key] = page
                used += len(page["text"])
            return {**link, "presented": True}

        rows: dict[int, dict[str, Any]] = {}

        def pair_row(index: int, protected: bool) -> None:
            pair = pairs[index]
            try:
                observation = json.loads(pair["observation"])
            except ValueError:
                observation = None
            ref = observation.get("ref") if isinstance(observation, dict) else None
            view = (
                source(ref, protected=protected)
                if isinstance(ref, str) and ref in known_sources
                else pair["observation"]
            )
            rows[index] = {
                "event": index,
                "segment": pair["segment"],
                "action": json.loads(pair["action"]),
                "observation": view,
            }

        # Latest original observations are admitted before optional history.
        for index in range(cursor, len(pairs)):
            pair_row(index, True)
        recalls = copy.deepcopy(self.recall_observations[recall_cursor:])
        for recall in recalls:
            for page in recall.get("sources", []):
                page.update(source(page["ref"], page["start"], page["length"], True))
        for index, pair in enumerate(pairs):
            if index not in rows and (
                not self.manage_workset
                or pair["segment"] == len(self.segments)
                or pair["segment"] in self.expanded
            ):
                pair_row(index, False)
        selected = []
        for ref in self.workspace.frame.selected_refs:
            if ref in known_sources:
                selected.append(source(ref))
        card_handles = set(self.workspace.frame.selected_refs) | set(self.new_card_handles)
        cards = [asdict(c) for handle, c in self.workspace.cards.items() if handle in card_handles]
        # A recalled card may already be selected. Keep one body per revision,
        # including an older revision when the Controller has just replaced it.
        card_bank = {(card["handle"], card["revision"]): card for card in cards}
        for recall in recalls:
            links = []
            for card in recall.get("cards", []):
                card_bank.setdefault((card["handle"], card["revision"]), card)
                links.append({"handle": card["handle"], "revision": card["revision"]})
            recall["cards"] = links
        catalogs = {}
        for name in ("sources", "cards", "segments"):
            entries = self._catalog(name)
            visible = [e for e in entries if not e["retired"]] if name == "cards" else entries
            catalogs[name] = {
                "entries": visible[: self.catalog_page_size],
                "total": len(entries),
                "read_ref": f"catalog:{name}",
                "archived": len(entries) - len(visible),
            }
        return {
            "workspace": {
                "working_note": self.workspace.working_note,
                "frame": asdict(self.workspace.frame),
                "cards": list(card_bank.values()),
                "revision": self.workspace.revision,
            },
            "control_status": self.maintenance_status,
            "control_feedback": self.control_feedback,
            "pending_maintenance_events": len(pairs) - self.maintained_pairs,
            "initial_observations": self.initial_observations,
            "new_event_ids": list(range(cursor, len(pairs))),
            "observations": [rows[i] for i in sorted(rows)],
            "materials": list(materials.values()),
            "selected_sources": selected,
            "omitted_material": omitted,
            "external_observations": self.external_observations[external_cursor:],
            "recall_observations": recalls,
            "catalogs": catalogs,
            "delivery_proposal": self.delivery_proposal,
            "delivery_reviews_remaining": self.max_delivery_reviews - self.delivery_reviews,
            "delivery_review_active": self.delivery_proposal is not None,
            "call_budget": {
                "remaining": self._remaining_calls(),
                "closing": self._remaining_calls() <= 1,
            },
            "goal_revision": self.goal_revision,
        }

    def actor_messages(self) -> tuple[dict[str, str], ...]:
        return (
            {"role": "system", "content": self.actor_policy},
            {"role": "user", "content": self.goal},
            {
                "role": "user",
                "content": json.dumps(self._projection(controller=False), ensure_ascii=False),
            },
        )

    def _parse(self, raw: str) -> tuple[str | None, dict[str, Any]]:
        value = json.loads(raw)
        if (
            isinstance(value, dict)
            and value.get("action") == "retrieve"
            and isinstance(value.get("arguments"), dict)
            and "refs" in value["arguments"]
        ):
            args = value["arguments"]
            refs = self._refs(args["refs"])
            start, length = args.get("start", 0), args.get("length", self.page_chars)
            if (
                not refs
                or len(refs) > self.catalog_page_size
                or type(start) is not int
                or start < 0
                or type(length) is not int
                or not 1 <= length <= self.page_chars
            ):
                raise HiAgentError("INVALID_RECALL_RANGE")
            return None, {
                "action": "retrieve",
                "arguments": {"refs": refs, "start": start, "length": length},
            }
        if (
            isinstance(value, dict)
            and not self.segments
            and value.get("action") != "retrieve"
            and value.get("subgoal") is None
        ):
            # Segment allocation is bookkeeping. The new Actor contract makes
            # labels optional, so it must not inherit HiAgent's required label.
            value["subgoal"] = self.workspace.frame.intent.strip() or "Task work"
            raw = json.dumps(value, ensure_ascii=False)
        return super()._parse(raw)

    def _control(self, reason: str) -> dict[str, Any]:
        before = (self.goal, self.goal_revision, self._cursor())
        body = {"reason": reason, **self._projection(controller=True)}
        raw = self._call(
            ModelCall(
                "maintenance",
                (
                    {"role": "system", "content": self.summary_policy},
                    {"role": "user", "content": self.goal},
                    {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
                ),
                json_output=True,
            )
        )
        if before != (self.goal, self.goal_revision, self._cursor()):
            raise HiAgentError("CONTROL_INPUT_CHANGED")
        try:
            route = self._accept(raw)
        except (ValueError, TypeError) as exc:
            self.control_feedback = str(exc)
            self.maintenance_status = "REJECTED_PREVIOUS_WORKSPACE_RETAINED"
            self._event("CONTROL_REJECTED", reason=reason, detail=str(exc))
            route = {"kind": "ACT", "refs": [], "delivery": None, "rejected": True}
        else:
            self.control_feedback = ""
            self.maintenance_status = "MODEL_WORKSPACE_NOT_AUTHORITY"
        self.maintained_pairs, self.maintained_external, self.maintained_recalls = self._cursor()
        self.initialized, self.resume_pending = True, False
        return route

    def _recall(self, refs: list[str], start: int, length: int) -> None:
        result: dict[str, Any] = {"refs": refs, "sources": [], "cards": [], "catalogs": {}}
        known_sources = {e["ref"] for e in self.source_entries()}
        for ref in refs:
            if ref in known_sources:
                page = self.read_source(ref, start, length)
                result["sources"].append({"ref": ref, "start": start, "length": len(page["text"])})
            elif ref.startswith("seg:"):
                segment = int(ref[4:])
                self.expanded.add(segment)
                for pair in self.segments[segment - 1].pairs:
                    observation = json.loads(pair.observation)
                    if isinstance(observation, dict) and observation.get("ref") in known_sources:
                        result["sources"].append(
                            {"ref": observation["ref"], "start": start, "length": length}
                        )
            elif ref in self.workspace.cards:
                result["cards"].append(asdict(self.workspace.cards[ref]))
            else:
                name = ref.removeprefix("catalog:")
                entries = self._catalog(name)
                result["catalogs"][name] = {
                    "entries": entries[start : start + self.catalog_page_size],
                    "total": len(entries),
                    "start": start,
                }
        self.recall_observations.append(result)
        self._event("SOURCE_RECALLED", observation=result)

    def _submit(
        self, text: str, subgoal: str | None = None, *,
        status: str = "UNREVIEWED", reason: str = "ACTOR_FINAL",
    ) -> None:
        self._assert_readable_dependencies()
        if not self.segments:
            self.segments.append(Segment(1, subgoal or "Deliver the current task"))
        self._dispatch_real({"action": "final", "arguments": {"text": text}})
        self.delivery_proposal = None
        self.delivery_status = status
        self._event("DELIVERY_COMPLETED", status=status, reason=reason)

    def _draft_current(self) -> bool:
        return self.delivery_proposal is not None and self._cursor() == (
            self.actor_seen_pairs, self.actor_seen_external, self.actor_seen_recalls,
        )

    def _submit_incomplete(self, reason: str) -> None:
        self._submit(
            "This run has reached its model-call limit. Task completion is not established. "
            "No further proposed action was executed; the recorded work and feedback remain "
            "available for continuation in the same task environment.",
            status="INCOMPLETE", reason=reason,
        )

    def _dispatch_real(self, action: dict[str, Any]) -> None:
        self.phase = "DISPATCH"
        self._event(
            "BEFORE_DISPATCH",
            segment=len(self.segments),
            action=action,
            workspace_revision=self.workspace.revision,
            goal_revision=self.goal_revision,
        )
        observation = self.dispatch(action)
        self.segments[-1].pairs.append(Pair(json.dumps(action, ensure_ascii=False), observation))
        self._event(
            "OBSERVATION_RECEIVED",
            segment=len(self.segments),
            action=action,
            observation=observation,
        )
        self.finished = action["action"] == "final"

    def step(self) -> None:
        if self.halted or self.finished or self.phase != "IDLE":
            raise HiAgentError("HOST_HALTED_OR_FINISHED")
        try:
            self.phase = "MAINTENANCE"
            if self.delivery_proposal is not None and not self._draft_current():
                self._event("DELIVERY_DRAFT_INVALIDATED", reason="NEW_FEEDBACK")
                self.delivery_proposal = None
                self.control_feedback = (
                    "New feedback requires a current answer; the old draft is stale."
                )
            if self._draft_current() and (
                self._remaining_calls() < 2 or self.delivery_reviews >= self.max_delivery_reviews
            ):
                assert self.delivery_proposal is not None
                self._submit(
                    self.delivery_proposal["arguments"]["text"], reason="REVIEW_UNAVAILABLE"
                )
                return
            if self._remaining_calls() == 0:
                self._submit_incomplete("NO_ENDING_CALL_REMAINS")
                return
            review = self.delivery_proposal is not None
            reason = self._control_reason()
            if not review:
                self._summary_once(reserve_calls=1 + int(reason is not None))
            if review:
                self.delivery_reviews += 1
            if reason is None and len(self._pairs()) > self.maintained_pairs:
                self._event(
                    "CONTROL_DEFERRED", reason="FEEDBACK_BATCH_PENDING",
                    pending_pairs=len(self._pairs()) - self.maintained_pairs,
                    feedback_batch_size=self.feedback_batch_size,
                )
            route: dict[str, Any] = {"kind": "ACT", "refs": [], "delivery": None}
            recalls = 0
            while reason is not None and self._remaining_calls() > 1:
                route = self._control(reason)
                if review and self._draft_current() and (
                    route.get("rejected")
                    or (not route.get("explicit_dispatch") and not route.get("changed"))
                ):
                    assert self.delivery_proposal is not None
                    self._submit(
                        self.delivery_proposal["arguments"]["text"],
                        reason="REVIEW_UNUSABLE" if route.get("rejected") else "REVIEW_NO_CHANGE",
                    )
                    return
                if route["kind"] != "RECALL":
                    break
                if recalls >= self.max_recall_expansions or self._remaining_calls() < 2:
                    self.control_feedback = (
                        "RECALL_LIMIT_REACHED_NOT_EVIDENCE_EXHAUSTION"
                        if recalls >= self.max_recall_expansions
                        else "RECALL_DEFERRED_FOR_ENDING_ACTOR_NOT_EVIDENCE_SUFFICIENCY"
                    )
                    self._event(
                        "RECALL_LIMIT_REACHED", expansions=recalls, reason=self.control_feedback
                    )
                    route = {"kind": "ACT", "refs": [], "delivery": None}
                    break
                self._recall(
                    route["refs"], route.get("start", 0), route.get("length", self.page_chars)
                )
                recalls += 1
                reason = "recall"
            if route["kind"] == "DELIVER":
                assert self.delivery_proposal is not None
                text = route["delivery"]
                self._submit(
                    self.delivery_proposal["arguments"]["text"] if text is None else text,
                    status="REVIEWED", reason="EXPLICIT_DELIVER",
                )
                return
            self.phase = "ACTOR"
            closing = self._remaining_calls() == 1
            subgoal, action = self._parse(self._call(ModelCall("actor", self.actor_messages())))
            self.actor_seen_pairs, self.actor_seen_external, self.actor_seen_recalls = (
                self._cursor()
            )
            self.new_card_handles.clear()
            self.delivery_proposal = None
            if closing and action["action"] != "final":
                self._event("ENDING_ACTION_NOT_EXECUTED", action=action)
                self._submit_incomplete("ENDING_ACTOR_DID_NOT_DELIVER")
                return
            if action["action"] == "retrieve":
                args = action["arguments"]
                refs = args.get("refs", [f"seg:{i}" for i in args.get("segments", [])])
                self._recall(refs, args.get("start", 0), args.get("length", self.page_chars))
                return
            if action["action"] == "final":
                if (
                    self.delivery_reviews < self.max_delivery_reviews
                    and self._remaining_calls() >= 2
                ):
                    self.delivery_proposal = action
                    self._event("DELIVERY_PROPOSED", action=action)
                else:
                    self._submit(action["arguments"]["text"], subgoal)
                return
            if subgoal is not None:
                self.segments.append(Segment(len(self.segments) + 1, subgoal))
                self._event("SUBGOAL_STARTED", segment=len(self.segments), subgoal=subgoal)
            self._dispatch_real(action)
        except BaseException as exc:
            self.halted = True
            self._event("HOST_STOPPED", error_type=type(exc).__name__, reason=str(exc))
            raise
        finally:
            self.phase = "FAILED" if self.halted else "IDLE"

    def _contract(self) -> dict[str, Any]:
        return {
            **super()._contract(),
            "method": METHOD_VERSION,
            "model_profile": self.model_profile,
            "archive_summary_policy": hashlib.sha256(
                self.archive_summary_policy.encode()
            ).hexdigest(),
            "max_recall_expansions": self.max_recall_expansions,
            "page_chars": self.page_chars,
            "material_chars": self.material_chars,
            "catalog_page_size": self.catalog_page_size,
            "max_cards": self.max_cards,
            "use_summary_cache": self.use_summary_cache,
            "feedback_batch_size": self.feedback_batch_size,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **super().snapshot(),
            "method": METHOD_VERSION,
            "workspace": asdict(self.workspace),
            "next_card": self.next_card,
            "new_card_handles": self.new_card_handles,
            "recall_observations": self.recall_observations,
            "maintained_recalls": self.maintained_recalls,
            "actor_seen_recalls": self.actor_seen_recalls,
            "summary_cache": self.summary_cache,
            "goal_revision": self.goal_revision,
            "delivery_status": self.delivery_status,
        }

    def _assert_readable_dependencies(self) -> None:
        # Summaries and free notes can depend on any prior observation. Check
        # before every model entry and before exporting a resumable checkpoint.
        readable = {entry["ref"] for entry in self.source_entries()}
        for pair in self._pairs():
            try:
                original = json.loads(pair["observation"])
            except ValueError:
                continue
            if isinstance(original, dict) and isinstance(original.get("ref"), str):
                if original["ref"] not in readable:
                    raise HiAgentError("WORKSPACE_SOURCE_DEPENDENCY_NOT_READABLE")
        source_refs = readable | {f"seg:{s.number}" for s in self.segments}
        if any(not set(c.source_refs) <= source_refs for c in self.workspace.cards.values()):
            raise HiAgentError("WORKSPACE_SOURCE_DEPENDENCY_NOT_READABLE")

    def checkpoint(self) -> dict[str, Any]:
        self._assert_readable_dependencies()
        return copy.deepcopy(super().checkpoint())

    def restore(self, checkpoint: dict[str, Any]) -> None:
        # Validate on an isolated candidate. Rejected archives must not leave a
        # half-restored Host or emit a successful restoration event.
        candidate = copy.copy(self)
        candidate.emit = None
        checkpoint = copy.deepcopy(checkpoint)
        try:
            old_contract = checkpoint.get("contract", {})
            if old_contract.get("method") in {"milai-rwc-v0.2", "milai-rwc-v0.3"}:
                # Explicit schema migration for the prior trusted local archive.
                # Policy remains fallible Host advice; capabilities/configuration
                # and policy arm must still match the new constructor contract.
                upgraded = {
                    "feedback_batch_size": 1,
                    **old_contract,
                    "method": METHOD_VERSION,
                    "policy_hash": candidate._contract()["policy_hash"],
                }
                if upgraded != candidate._contract():
                    raise HiAgentError("CHECKPOINT_CONTRACT_MISMATCH")
                checkpoint["contract"] = upgraded
                checkpoint["state"]["method"] = METHOD_VERSION
            WorkspaceControlHost.restore(candidate, checkpoint)
            candidate._restore_workspace(checkpoint)
            candidate._assert_readable_dependencies()
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise HiAgentError(f"INVALID_WORKSPACE_CHECKPOINT: {exc}") from exc
        candidate.emit = self.emit
        self.__dict__.update(candidate.__dict__)
        self._event(
            "HOST_RESTORED",
            call_attempts=dict(self.calls),
            pending_pairs=len(self._pairs()) - self.maintained_pairs,
            goal_updated=self.goal != checkpoint["goal"],
        )

    def _restore_workspace(self, checkpoint: dict[str, Any]) -> None:
        state = checkpoint["state"]
        workspace = state["workspace"]
        cards = {key: MemoryCard(**value) for key, value in workspace["cards"].items()}
        if (
            state["method"] != METHOD_VERSION
            or not isinstance(workspace["working_note"], str)
            or type(workspace["revision"]) is not int
            or workspace["revision"] != state["record_revision"]
            or workspace["working_note"] != self.record
            or type(state["next_card"]) is not int
            or state["next_card"] < 1
            or type(state["goal_revision"]) is not int
            or state["goal_revision"] < 1
            or any(
                card.handle != key
                or re.fullmatch(r"card:[1-9][0-9]*", key) is None
                or int(key[5:]) >= state["next_card"]
                or not isinstance(card.text, str)
                or type(card.revision) is not int
                or card.revision < 1
                or type(card.retired) is not bool
                for key, card in cards.items()
            )
            or sum(not c.retired for c in cards.values()) > self.max_cards
        ):
            raise HiAgentError("INVALID_CARD_CHECKPOINT")
        source_refs = {entry["ref"] for entry in self.source_entries()} | {
            f"seg:{s.number}" for s in self.segments
        }
        for card in cards.values():
            self._refs(card.source_refs, allowed=source_refs)
        frame = FocusFrame(**workspace["frame"])
        if not isinstance(frame.question, str) or not isinstance(frame.intent, str):
            raise HiAgentError("INVALID_FOCUS_FRAME")
        known = source_refs | set(cards) | {"catalog:sources", "catalog:cards", "catalog:segments"}
        self._refs(frame.selected_refs, allowed=known)
        self._refs(state["new_card_handles"], allowed=set(cards))
        recalls = state["recall_observations"]
        if not isinstance(recalls, list):
            raise HiAgentError("INVALID_RECALL_CHECKPOINT")
        for recall in recalls:
            if set(recall) != {"refs", "sources", "cards", "catalogs"}:
                raise HiAgentError("INVALID_RECALL_CHECKPOINT")
            self._refs(recall["refs"], allowed=known)
            for page in recall["sources"]:
                if (
                    page["ref"] not in source_refs
                    or page["ref"].startswith("seg:")
                    or type(page["start"]) is not int
                    or page["start"] < 0
                    or type(page["length"]) is not int
                    or not 0 <= page["length"] <= self.page_chars
                ):
                    raise HiAgentError("INVALID_RECALL_PAGE")
            for saved_card in recall["cards"]:
                card = MemoryCard(**saved_card)
                if (
                    card.handle not in cards
                    or not isinstance(card.text, str)
                    or type(card.revision) is not int
                    or not 1 <= card.revision <= cards[card.handle].revision
                    or type(card.retired) is not bool
                ):
                    raise HiAgentError("INVALID_RECALLED_CARD")
                self._refs(card.source_refs, allowed=source_refs)
            if not isinstance(recall["catalogs"], dict):
                raise HiAgentError("INVALID_RECALL_CATALOG")
        for key in ("maintained_recalls", "actor_seen_recalls"):
            if type(state[key]) is not int or not 0 <= state[key] <= len(recalls):
                raise HiAgentError("INVALID_RECALL_CURSOR")
        self.workspace = WorkspaceSnapshot(
            workspace["working_note"],
            cards,
            frame,
            workspace["revision"],
        )
        self.next_card, self.new_card_handles = state["next_card"], list(state["new_card_handles"])
        self.recall_observations = copy.deepcopy(state["recall_observations"])
        self.maintained_recalls, self.actor_seen_recalls = (
            state["maintained_recalls"],
            state["actor_seen_recalls"],
        )
        self.summary_cache = {int(k): v for k, v in state["summary_cache"].items()}
        if any(
            not 1 <= k <= len(self.segments)
            or not isinstance(v, str)
            or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for k, v in self.summary_cache.items()
        ):
            raise HiAgentError("INVALID_SUMMARY_CACHE")
        for segment, saved in zip(self.segments, state["segments"], strict=True):
            if not isinstance(saved["summary"], (str, type(None))):
                raise HiAgentError("INVALID_SEGMENT_SUMMARY")
            segment.summary = saved["summary"]
        self.goal_revision = state["goal_revision"] + int(self.goal != checkpoint["goal"])
        self.delivery_status = state.get("delivery_status")
        if self.goal != checkpoint["goal"]:
            self.delivery_proposal = None
            self.delivery_reviews = 0
            self.finished = False
            self.delivery_status = None
            self.workspace.frame = FocusFrame(question=self.goal)
            self.control.question, self.control.intent = self.goal, ""
            self.control.focus_refs, self.control.focus_segments = [], []
            self.expanded = set()
        self.resume_pending = True
