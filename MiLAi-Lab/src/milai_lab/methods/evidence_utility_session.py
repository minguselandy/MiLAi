"""v0.7 candidate: rejectable use and evidence-bound, separately calibrated versions.

The native runner owns request receipts, terminal scoring and costs. Semantic
support for a revision remains a fallible model judgment, not a provenance check.
The v0.6 class and policies remain independently runnable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.experience_revision import ExperienceRevisionSession
from milai_lab.methods.experience_utility import VersionUtility, version_key
from milai_lab.methods.reasoning_bank import MemoryCall

METHOD_VERSION = "milai-experience-revision-v0.7-dev"


def messages_digest(messages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class EvidenceUtilitySession(ExperienceRevisionSession):
    method_version = METHOD_VERSION

    def __init__(self, *, task_costs: Callable[[], dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.post_task_revision or self.projection_mode != "selected":
            raise ValueError("UTILITY_CANDIDATE_REQUIRES_SELECTED_POST_TASK_PROTOCOL")
        self.utility_config = json.loads(self.policies["utility_contract"])
        self.feedback_regime = self.utility_config["feedback_regime"]
        self.selector_version = self.utility_config["selector_version"]
        if self.feedback_regime not in {"H", "R"}:
            raise ValueError("UNKNOWN_UTILITY_FEEDBACK_REGIME")
        self.task_costs = task_costs

    def _utility(self) -> VersionUtility:
        return VersionUtility(self.working.utility_state)

    def start(
        self, task_id: str, query: str, *, task_facts: tuple[tuple[str, str], ...] = ()
    ) -> None:
        self.exposure_sequence: list[dict[str, Any]] = []
        self.read_pages: list[tuple[str, int, dict[str, Any]]] = []
        self.pending_exposure: list[tuple[str, int]] = []
        self.pending_messages_digest: str | None = None
        self.result_binding: tuple[str, bool | None] | None = None
        self.decision_ref = f"{task_id}:adoption:{self.selector_version}"
        super().start(task_id, query, task_facts=task_facts)
        for ref in self.selected:
            self._utility().register(self.working.cards[ref])

    def memory_context(self) -> str:
        projected = [
            ref
            for ref in self.workspace.frame.selected_refs
            if ref in self.selected and not self.working.cards[ref].retired
        ]
        self._projected_versions = {ref: self.working.cards[ref].revision for ref in projected}
        parts = []
        if projected:
            parts = [
                self._render_memory_context(projected),
                self.policies["revision_actor"].strip(),
            ]
            notes = {
                ref: self.adoption_notes[ref] for ref in projected if ref in self.adoption_notes
            }
            if notes:
                parts.append("Applicable scope: " + json.dumps(notes, ensure_ascii=False))
            if self.tool_feedback:
                parts.append("Recent feedback references: " + json.dumps(self.tool_feedback[-4:]))
        if self.task_note:
            parts.append("Current task interpretation: " + self.task_note)
        if self.task_focus:
            parts.append("Current task focus: " + json.dumps(self.task_focus, ensure_ascii=False))
        if self.fact_catalog and self.project_task_facts:
            parts.append(
                "Required task facts: " + json.dumps(self._task_fact_view(), ensure_ascii=False)
            )
        return "\n\n".join(parts)

    def read(self, ref: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
        if ref != "experience:catalog":
            return super().read(ref, start, length)
        length = self.config.read_chars if length is None else length
        if (
            type(start) is not int
            or type(length) is not int
            or start < 0
            or not 1 <= length <= 16000
        ):
            raise ValueError("INVALID_MEMORY_SOURCE_RANGE")
        text = json.dumps(
            {
                "candidate_handles": self.selected,
                "feedback_refs": self.tool_feedback,
                "task_fact_refs": self.fact_catalog,
            },
            ensure_ascii=False,
        )
        return {
            "ref": ref,
            "start": start,
            "text": text[start : start + length],
            "total_chars": len(text),
            "has_more": start + length < len(text),
        }

    def actor_read(self, ref: str, start: int = 0, length: int | None = None) -> dict[str, Any]:
        page = super().actor_read(ref, start, length)
        card = self.working.cards.get(ref)
        if card is None and ref in self.working.historical_cards:
            card = MemoryCard(**self.working.historical_cards[ref])
        if card is not None and page["text"]:
            self._utility().register(card)
            page["memory_version"] = version_key(card.handle, card.revision)
            self.read_pages.append((card.handle, card.revision, page))
        return page

    def prepare_actor_input(self, messages: list[dict[str, Any]]) -> None:
        """Locate our projected bodies/read receipts in the actual outgoing messages.

        A source page can remain in native history after a revision. Preserve both
        versions if that page and the new body occur in the same request.
        """
        contents = [m["content"] for m in messages if isinstance(m.get("content"), str)]
        versions = set()
        for ref, rev in self._projected_versions.items():
            card = self.working.cards[ref]
            header = f"[{ref} revision={rev}; sources={','.join(card.source_refs)}]\n"
            if not any(header + card.text in text for text in contents):
                raise ValueError("PROJECTED_EXPERIENCE_MISSING_FROM_REQUEST")
            self._utility().register(card)
            versions.add((ref, rev))
        for ref, rev, page in self.read_pages:
            if any(
                json.dumps(page, ensure_ascii=ascii_only) in text
                for text in contents
                for ascii_only in (False, True)
            ):
                versions.add((ref, rev))
        self.pending_exposure = sorted(versions)
        self.pending_messages_digest = messages_digest(messages)

    def confirm_actor_input(self, receipt: dict[str, Any] | None = None) -> None:
        if self.result_binding is not None:
            raise ValueError("ACTOR_REQUEST_AFTER_TERMINAL_RESULT")
        if (
            receipt is None
            or self.pending_messages_digest is None
            or self.pending_messages_digest != receipt.get("messages_sha256")
        ):
            raise ValueError("ACTOR_RECEIPT_DOES_NOT_MATCH_PREPARED_INPUT")
        self._utility().confirm(
            self.exposure_sequence,
            receipt=receipt,
            versions=self.pending_exposure,
            task_id=self.task_id,
        )
        super().confirm_actor_input()
        self.pending_messages_digest = None
        self._event("UTILITY_ACTOR_INPUT_CONFIRMED", exposure=self.exposure_sequence[-1])

    def seal_result(self, result_ref: str, native_result: bool | None = None) -> None:
        """Runner calls this after saving the native result, before maintenance."""
        if not self.active or self.result_binding is not None or not result_ref:
            raise ValueError("INVALID_TERMINAL_RESULT_BINDING")
        reward_allowed = self.feedback_regime == "R" and not (
            self.bank.scope.get("split") == "TEST" and self.bank.scope.get("protocol") in {"F", "G"}
        )
        if native_result is not None and (type(native_result) is not bool or not reward_allowed):
            raise ValueError("NATIVE_RESULT_NOT_ALLOWED_FOR_METHOD")
        self.result_binding = (result_ref, native_result)

    def _maintenance_body(self, role: str, request: str) -> dict[str, Any]:
        body = super()._maintenance_body(role, request)
        utility = self._utility()
        for ref in self.selected:
            utility.register(self.working.cards[ref])
        body["version_use_evidence"] = utility.selection_view(
            {ref: self.working.cards[ref].revision for ref in self.selected}
        )
        body["selector_version"] = self.selector_version
        body["decision_ref"] = self.decision_ref
        return body

    def _extraction_call(self, trajectory: str, successful: bool) -> MemoryCall:
        call = super()._extraction_call(trajectory, successful)
        body = json.loads(call.messages[-1]["content"])
        refs = {
            source
            for ref in body["seen_experience"]
            for source in self.working.cards[ref].source_refs
        }
        # Exact originals, not invented evidence of what an earlier task did.
        body["original_experience_sources"] = {
            ref: self.working.sources[ref] for ref in sorted(refs)
        }
        body["actual_exposure_sequence"] = self.exposure_sequence
        return replace(
            call,
            messages=(
                *call.messages[:-1],
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ),
        )

    def _apply_proposal(
        self, value: dict[str, Any], role: str, request: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        before = {ref: asdict(card) for ref, card in self.working.cards.items()}
        result = super()._apply_proposal(value, role, request)
        utility = self._utility()
        for ref, change in result["changed"].items():
            old = MemoryCard(**before[ref])
            predecessor = utility.register(old)
            target = change.get("appended", ref)
            utility.register(
                self.working.cards[target],
                predecessor=predecessor,
                reason=(request or {}).get("reason", ""),
                feedback_refs=tuple((request or {}).get("feedback_refs", [])),
            )
        if role == "revise" and not result["changed"]:
            note = (value.get("workspace_update") or {}).get("working_note")
            if note is not None:
                self.task_note = note
            self.task_focus.update(
                {
                    key: value["frame"][key]
                    for key in ("question", "intent")
                    if key in value.get("frame", {})
                }
            )
        return result

    def finish(self, trajectory: str, *, commit: bool) -> dict[str, Any]:
        if self.result_binding is None:
            raise ValueError("UTILITY_FINISH_REQUIRES_TERMINAL_RESULT")
        # Freeze result attribution before post-task extraction can publish v+1.
        result = super().finish(trajectory, commit=False)
        if self.task_id not in self.working.completed_tasks:
            self.working.completed_tasks.append(self.task_id)
            self.working.revision += 1
        utility = self._utility()
        for card in self.working.cards.values():
            utility.register(card)
        sample = utility.finish(
            task_id=self.task_id,
            scope=self.bank.scope,
            selector_version=self.selector_version,
            feedback_regime=self.feedback_regime,
            sequence=self.exposure_sequence,
            result_ref=self.result_binding[0],
            native_result=self.result_binding[1],
            costs=self.task_costs(),
            decision_ref=self.decision_ref,
        )
        if commit:
            self._commit_working()
        self._event("UTILITY_TASK_FINISHED", sample=sample, committed=commit)
        return {**result, "committed": commit, "utility_recorded": True}
