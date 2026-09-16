"""Native-agent experience adoption and explicitly requested sparse revision.

Business actions and final delivery remain with the benchmark's original agent.
The existing workspace patch engine applies proposals atomically; this adapter
binds edits to retrieved versions and task-visible sources.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any

from milai_lab.methods.controlled_workspace import WorkspaceSnapshot, apply_workspace_patch
from milai_lab.methods.hiagent import HiAgentError
from milai_lab.methods.reasoning_bank import MemoryCall, MemoryOutputError, ReasoningBankSession

METHOD_VERSION = "milai-experience-revision-v0.6"


class ExperienceRevisionSession(ReasoningBankSession):
    method_version = METHOD_VERSION

    def __init__(
        self,
        *,
        revision_application: str = "replace",
        projection_mode: str = "selected",
        post_task_revision: bool = False,
        action_budget: dict[str, Any] | None = None,
        project_task_facts: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if revision_application not in {"replace", "append_only"}:
            raise ValueError("UNKNOWN_REVISION_APPLICATION")
        self.revision_application = revision_application
        if projection_mode not in {"selected", "legacy_all"}:
            raise ValueError("UNKNOWN_EXPERIENCE_PROJECTION")
        self.projection_mode = projection_mode
        self.post_task_revision = post_task_revision
        self.action_budget = copy.deepcopy(action_budget)
        self.project_task_facts = project_task_facts

    def start(
        self, task_id: str, query: str, *, task_facts: tuple[tuple[str, str], ...] = ()
    ) -> None:
        super().start(task_id, query)
        self.workspace = WorkspaceSnapshot(
            cards={handle: copy.deepcopy(self.working.cards[handle]) for handle in self.selected}
        )
        self.seen: dict[str, int] = {}
        self._projected_versions: dict[str, int] = {}
        self._read_versions: dict[str, int] = {}
        self.adoption_notes: dict[str, str] = {}
        self.task_note = ""
        self.task_focus: dict[str, str] = {}
        self.published = set(self.selected) | set(self.feedback_refs)
        for card in self.workspace.cards.values():
            self.published.update(card.source_refs)
        self.published.update(
            ref
            for ref in self.working.historical_cards
            if any(ref.startswith(handle + "@") for handle in self.selected)
        )
        self.tool_feedback: list[str] = []
        self.fact_catalog: dict[str, str] = {}
        for label, text in task_facts:
            self.publish_task_fact(label, text)
        if self.selected:
            self._maintain("adopt", "Adopt applicable retrieved experience for this new task.")

    def observe(self, kind: str, text: str) -> str:
        ref = super().observe(kind, text)
        if hasattr(self, "published"):
            self.published.add(ref)
        if kind == "tool" and hasattr(self, "tool_feedback"):
            self.tool_feedback.append(ref)
        return ref

    def memory_context(self) -> str:
        self._projected_versions = {}
        if (
            not self.selected
            and not self.fact_catalog
            and not self.task_note
            and not self.task_focus
        ):
            # No retrieved advice or published task source means there is no
            # memory operation to advertise to the otherwise unchanged Actor.
            return ""
        projected = (
            list(self.selected)
            if self.projection_mode == "legacy_all"
            else [ref for ref in self.workspace.frame.selected_refs if ref in self.selected]
        )
        projected = [ref for ref in projected if not self.working.cards[ref].retired]
        current = self._render_memory_context(projected)
        self._projected_versions = {
            handle: self.working.cards[handle].revision for handle in projected
        }
        extras = [self.policies["revision_actor"].strip()]
        if self.projection_mode == "legacy_all":
            if self.workspace.working_note:
                extras.append("Current working note:\n" + self.workspace.working_note)
            if self.workspace.frame.question or self.workspace.frame.intent:
                extras.append("Current focus: " + json.dumps(asdict(self.workspace.frame)))
        else:
            # Legacy free-form notes may repeat excluded advice. Keep them in the
            # maintenance record; only explicitly scoped adoption notes are sent.
            notes = {
                ref: self.adoption_notes[ref] for ref in projected if ref in self.adoption_notes
            }
            if notes:
                extras.append(
                    "Use of selected experience: " + json.dumps(notes, ensure_ascii=False)
                )
            extras.append(
                "Available experience handles (optional read; not automatically adopted): "
                + json.dumps(self.selected)
            )
        if self.task_note:
            extras.append("Current task interpretation: " + self.task_note)
        if self.task_focus:
            extras.append("Current task focus: " + json.dumps(self.task_focus, ensure_ascii=False))
        extras.append("Visible feedback references: " + json.dumps(self.tool_feedback))
        historical = sorted(self.published & self.working.historical_cards.keys())
        if historical:
            extras.append(
                "Superseded experience versions available by source read: " + json.dumps(historical)
            )
        if self.fact_catalog and self.project_task_facts:
            extras.append(
                "Original task facts (also available by source read): "
                + json.dumps(self._task_fact_view(), ensure_ascii=False)
            )
        return "\n\n".join([current, *extras]).strip()

    def publish_task_fact(self, label: str, text: str) -> str:
        """Publish caller-authorized task facts, distinct from extracted advice."""
        if not self.active:
            raise ValueError("NO_ACTIVE_MEMORY_TASK")
        ref = self.working.source(text)
        self.published.add(ref)
        self.fact_catalog[ref] = label
        self._event("TASK_FACT_SOURCE_PUBLISHED", ref=ref, label=label)
        return ref

    def _task_fact_view(self) -> dict[str, dict[str, str]]:
        return {
            ref: {"label": label, "text": self.working.sources[ref]}
            for ref, label in self.fact_catalog.items()
        }

    def set_action_budget(self, budget: dict[str, Any]) -> None:
        self.action_budget = copy.deepcopy(budget)

    def request_revision(self, request: dict[str, Any]) -> dict[str, Any]:
        """Called only for an explicit actor request, never inferred from an error."""
        self._validate_revision_request(request)
        self._event("ACTOR_REVISION_REQUESTED", request=request, seen=self.seen)
        return self._maintain("revise", json.dumps(request, ensure_ascii=False))

    def _validate_revision_request(self, request: dict[str, Any]) -> None:
        refs, feedback = request.get("handles"), request.get("feedback_refs")
        if (
            not isinstance(request.get("reason"), str)
            or not request["reason"].strip()
            or not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) and ref in self.seen for ref in refs)
            or not isinstance(feedback, list)
            or not feedback
            or not all(isinstance(ref, str) and ref in self.tool_feedback for ref in feedback)
        ):
            raise MemoryOutputError("REVISION_REQUIRES_SEEN_EXPERIENCE_AND_REAL_FEEDBACK")
        if any(self.seen[ref] != self.working.cards[ref].revision for ref in refs):
            raise MemoryOutputError("ACTOR_EXPERIENCE_VERSION_STALE")

    def request_task_update(self, request: dict[str, Any]) -> dict[str, Any]:
        """Apply the Actor's task-local judgment without a second semantic call."""
        if not set(request) <= {"kind", "working_note", "frame"}:
            raise MemoryOutputError("TASK_STATE_CANNOT_EDIT_EXPERIENCE")
        frame = request.get("frame", {})
        if not isinstance(frame, dict):
            raise MemoryOutputError("INVALID_TASK_FOCUS")
        proposal = {"frame": frame}
        if "working_note" in request:
            if not isinstance(request["working_note"], str):
                raise MemoryOutputError("INVALID_TASK_NOTE")
            proposal["workspace_update"] = {"working_note": request["working_note"]}
        result = self._apply_proposal(proposal, "task")
        # Do not promote an old adoption note merely because selection changed.
        if "working_note" in request:
            self.task_note = request["working_note"]
        self.task_focus.update({k: frame[k] for k in ("question", "intent") if k in frame})
        self._event("TASK_INTERPRETATION_UPDATED", note=self.task_note, frame=self.task_focus)
        return result

    def read(self, ref: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
        if ref not in self.published:
            raise MemoryOutputError("UNPUBLISHED_MEMORY_SOURCE")
        return super().read(ref, start, length)

    def actor_read(self, ref: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
        page = self.read(ref, start, length)
        if ref in self.working.cards:
            self._read_versions[ref] = self.working.cards[ref].revision
        self._event("ACTOR_MEMORY_READ", ref=ref, start=start, length=length)
        return page

    def confirm_actor_input(self) -> None:
        """Confirm exposure only after the native provider returned a response.

        Assembly and controller reads alone do not prove Actor exposure. An
        explicitly read page is included in the next Actor request's receipt.
        """
        delivered = {**self._read_versions, **self._projected_versions}
        self.seen.update(delivered)
        self._read_versions.clear()
        self._event("ACTOR_EXPERIENCE_EXPOSED", versions=delivered)

    def _extraction_call(self, trajectory: str, successful: bool) -> MemoryCall:
        if not self.post_task_revision:
            return super()._extraction_call(trajectory, successful)
        body = {
            "query": self.query,
            "trajectory": trajectory,
            "seen_experience": {
                ref: asdict(self.working.cards[ref])
                for ref, revision in self.seen.items()
                if self.working.cards[ref].revision == revision
            },
            "visible_tool_feedback": {ref: self.working.sources[ref] for ref in self.tool_feedback},
        }
        return MemoryCall(
            "extract",
            (
                {
                    "role": "system",
                    "content": self.policies[
                        "extract_success" if successful else "extract_failure"
                    ].strip(),
                },
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ),
            self.config.extract_output_tokens,
            1.0,
            True,
        )

    def _memory_items(self, extraction: str) -> list[str]:
        if self.post_task_revision and not extraction.strip():
            return []
        return super()._memory_items(extraction)

    def _extract(self, trajectory: str) -> tuple[bool, str]:
        successful, raw = super()._extract(trajectory)
        if not self.post_task_revision:
            return successful, raw
        try:
            output = json.loads(raw)
            if not isinstance(output, dict) or not isinstance(output.get("new_memory"), str):
                raise MemoryOutputError("INVALID_EXPERIENCE_EXTRACTION_ENVELOPE")
        except ValueError as error:
            raise MemoryOutputError("INVALID_EXPERIENCE_EXTRACTION_ENVELOPE") from error
        revision = output.get("revision")
        if revision is not None:
            try:
                if not isinstance(revision, dict):
                    raise MemoryOutputError("INVALID_POST_TASK_REVISION")
                self._validate_revision_request(revision)
                proposal = revision.get("proposal")
                if not isinstance(proposal, dict):
                    raise MemoryOutputError("INVALID_POST_TASK_REVISION")
                if proposal.get("dispatch", {"kind": "ACT"}) != {"kind": "ACT"}:
                    raise MemoryOutputError("POST_TASK_EXTRACTION_CANNOT_DISPATCH")
                result = self._apply_proposal(proposal, "post_task", revision)
                self._event("POST_TASK_REVISION_APPLIED", request=revision, **result)
            except (ValueError, TypeError, KeyError, AttributeError, HiAgentError) as error:
                self._event("POST_TASK_REVISION_REJECTED", reason=str(error))
        return successful, output["new_memory"]

    def finish(self, trajectory: str, *, commit: bool) -> dict[str, Any]:
        result = super().finish(trajectory, commit=commit)
        if result["status"] == "MAINTENANCE_FAILED" and any(
            self.working.cards[handle] != self.bank.cards.get(handle) for handle in self.selected
        ):
            # An unusable *new extraction* does not revoke earlier accepted edits
            # to an existing experience. F still discards the complete overlay.
            self.working.completed_tasks.append(self.task_id)
            self.working.revision += 1
            if commit:
                self._commit_working()
            result = {**result, "committed": commit, "accepted_revisions_retained": True}
            self._event("EXPERIENCE_REVISIONS_FINISHED_WITHOUT_EXTRACTION", **result)
        return result

    def _apply_proposal(
        self,
        value: dict[str, Any],
        role: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate before committing a sparse patch; contains no model calls."""
        proposal = copy.deepcopy(value)
        adoption_notes = proposal.pop("adoption_notes", None)
        if adoption_notes is not None and (
            not isinstance(adoption_notes, dict)
            or any(
                ref not in self.selected or not isinstance(note, str)
                for ref, note in adoption_notes.items()
            )
        ):
            raise MemoryOutputError("ADOPTION_NOTES_REQUIRE_RETRIEVED_EXPERIENCE")
        update = proposal.get("workspace_update") or {}
        if not isinstance(update, dict) or not isinstance(update.get("put_cards", []), list):
            raise MemoryOutputError("INVALID_REVISION_PROPOSAL")
        puts = update.get("put_cards", [])
        if any(not isinstance(item, dict) for item in puts):
            raise MemoryOutputError("INVALID_REVISION_PROPOSAL")
        if any(item.get("handle") is None for item in puts):
            raise MemoryOutputError("NEW_EXPERIENCE_REQUIRES_POST_TASK_EXTRACTION")
        touched = {item["handle"] for item in puts} | set(update.get("retire_cards", []))
        if role in {"adopt", "task"} and touched:
            raise MemoryOutputError("ADOPTION_ONLY_UPDATES_TEMPORARY_JUDGMENT")
        expected = proposal.pop("expected_revisions", {})
        if (
            not isinstance(expected, dict)
            or touched != set(expected)
            or any(
                handle not in self.workspace.cards
                or expected[handle] != self.workspace.cards[handle].revision
                for handle in touched
            )
        ):
            raise MemoryOutputError("EXPERIENCE_REVISION_MISMATCH")
        if touched:
            if request is None or not touched <= set(request["handles"]):
                raise MemoryOutputError("REVISION_OUTSIDE_REQUESTED_EXPERIENCE")
            # Bind the actual cited feedback as provenance before the common
            # patch engine computes versions. This is a source link, not a
            # claim that the proposed interpretation is necessarily correct.
            for item in puts:
                refs = item.get("source_refs", self.workspace.cards[item["handle"]].source_refs)
                if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                    raise MemoryOutputError("INVALID_REVISION_SOURCES")
                item["source_refs"] = list(dict.fromkeys([*refs, *request["feedback_refs"]]))
        patch = apply_workspace_patch(
            json.dumps(proposal),
            self.workspace,
            evidence_refs=self.published & self.working.sources.keys(),
            known_refs=self.published,
            next_card=self.working.next_card,
            page_chars=self.config.read_chars,
            max_read_chars=16000,
        )
        if patch.route["kind"] == "DELIVER":
            raise MemoryOutputError("NATIVE_ACTOR_OWNS_DELIVERY")
        changed: dict[str, Any] = {}
        for handle, card in patch.workspace.cards.items():
            old = self.working.cards[handle]
            if old != card:
                if request is not None and card.retired:
                    card.source_refs = list(
                        dict.fromkeys([*card.source_refs, *request["feedback_refs"]])
                    )
                if self.revision_application == "replace":
                    old_ref = f"{handle}@{old.revision}"
                    self.working.historical_cards[old_ref] = asdict(old)
                    self.published.add(old_ref)
                self.working.cards[handle] = copy.deepcopy(card)
                changed[handle] = {"before": old.revision, "after": card.revision}
        if self.revision_application == "append_only" and changed:
            for handle in list(changed):
                old = self.workspace.cards[handle]
                proposed = copy.deepcopy(patch.workspace.cards[handle])
                self.working.cards[handle] = copy.deepcopy(old)
                patch.workspace.cards[handle] = copy.deepcopy(old)
                new_handle = f"card:{self.working.next_card}"
                self.working.next_card += 1
                proposed.handle, proposed.revision = new_handle, 1
                if proposed.retired:
                    proposed.text = f"Retirement proposal for {handle}:\n" + proposed.text
                    proposed.retired = False
                self.working.cards[new_handle] = proposed
                patch.workspace.cards[new_handle] = copy.deepcopy(proposed)
                for record in self.working.records:
                    if handle in record["handles"]:
                        record["handles"].append(new_handle)
                self.selected.append(new_handle)
                if handle in patch.workspace.frame.selected_refs:
                    patch.workspace.frame.selected_refs.append(new_handle)
                self.published.add(new_handle)
                changed[handle] = {
                    "before": old.revision,
                    "after": old.revision,
                    "appended": new_handle,
                }
                self._event("REVISION_APPENDED_OLD_RETAINED", old=handle, new=new_handle)
        self.workspace = patch.workspace
        for handle in changed:
            self.adoption_notes.pop(handle, None)
        if adoption_notes is not None:
            self.adoption_notes = adoption_notes
        self._event(
            "EXPERIENCE_PATCH_APPLIED",
            role=role,
            changed=changed,
            route=patch.route,
            selected_refs=list(self.workspace.frame.selected_refs),
        )
        return {"status": "APPLIED", "changed": changed, "route": patch.route}

    def _maintenance_body(self, role: str, request: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "phase": role,
            "task": self.query,
            "request": request,
            "workspace": asdict(self.workspace),
            "visible_feedback": {ref: self.working.sources[ref] for ref in self.feedback_refs[-4:]},
            "published_refs": sorted(self.published),
        }
        revision_request = json.loads(request) if role == "revise" else None
        if revision_request is not None:
            # Keep every feedback reference explicitly cited by the Actor,
            # including an older receipt that is outside the recent four.
            body["visible_feedback"].update(
                {ref: self.working.sources[ref] for ref in revision_request["feedback_refs"]}
            )
        if self.fact_catalog:
            body["task_facts"] = self._task_fact_view()
        if self.action_budget is not None:
            body["native_action_budget"] = self.action_budget
        return body

    def _maintain(self, role: str, request: str) -> dict[str, Any]:
        body = self._maintenance_body(role, request)
        revision_request = json.loads(request) if role == "revise" else None
        messages = [
            {"role": "system", "content": self.policies["revision_controller"].strip()},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]
        while True:
            try:
                raw = self.generate(
                    MemoryCall(
                        role, tuple(messages), self.config.maintenance_output_tokens, 0.0, True
                    )
                )
            except MemoryOutputError as error:
                self._event("EXPERIENCE_MAINTENANCE_UNAVAILABLE", role=role, reason=str(error))
                return {"status": "MAINTENANCE_FAILED", "reason": str(error)}
            try:
                proposal = json.loads(raw)
                if not isinstance(proposal, dict):
                    raise MemoryOutputError("INVALID_REVISION_PROPOSAL")
                result = self._apply_proposal(proposal, role, revision_request)
            except (ValueError, TypeError, KeyError, AttributeError, HiAgentError) as error:
                self._event("EXPERIENCE_PROPOSAL_REJECTED", role=role, reason=str(error))
                return {"status": "MAINTENANCE_FAILED", "reason": str(error)}
            route = result["route"]
            if route["kind"] == "ACT":
                return result
            pages = [self.read(ref, route["start"], route["length"]) for ref in route["refs"]]
            messages.extend(
                [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"source_pages": pages, "current_workspace": asdict(self.workspace)},
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
