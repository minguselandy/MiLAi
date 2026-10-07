"""Synthetic meeting -> explicit preference -> cancellation -> source forgetting.

Run with PYTHONPATH=src. Uses real, reopened SQLite and the shared editor/commit
path with three scripted model envelopes. No model, embedding or business HTTP.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional_state import FunctionalRejection
from milai_lab.memory.service import MemoryService
from milai_lab.methods.consolidation import consolidate
from milai_lab.methods.edit_maintenance import MaintenanceRecipe, maintain_event, resume_maintenance
from milai_lab.methods.edit_memory import EditMemory

SESSION = "meeting-example"


@contextmanager
def opened(root: Path) -> Iterator[tuple[MemoryService, EpisodeIndex, EditMemory]]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("episode-example", "owner"),
            "owner",
            root / "memory.lock",
            functional_contract="functional_v1",
            memory_profile="unified_v1",
        )
        yield service, EpisodeIndex(service), EditMemory(service, "M", interface_version="I2")


def capture(service: MemoryService, key: str, text: str) -> tuple[str, str]:
    receipt = service.capture_user(SESSION, key, text)
    source_ref = str(receipt["source_ref"])
    service.bind_public_turn(
        SESSION, key, source_ref, config_version="episode-example-v1", phase="start"
    )
    return source_ref, str(receipt["episode_id"])


class ScriptedMaintenance:
    """Bind caller resources to the same maintain_event used by Host/benchmark."""

    def __init__(self, method: EditMemory, proposal: dict[str, Any], calls: list[str]) -> None:
        self.method, self.proposal, self.calls = method, proposal, calls
        self.inspections: list[str] = []

    def __call__(
        self,
        *,
        delivery: dict[str, Any],
        record_ids: list[str],
        episode_ids: list[str],
        request_id: str,
    ) -> dict[str, Any]:
        def transport(
            stage: str, messages: list[dict[str, str]], schema: dict[str, Any]
        ) -> dict[str, Any]:
            self.calls.append(stage)
            return {"proposals": [self.proposal]}

        def selected_delivery(located: dict[str, Any]) -> dict[str, Any]:
            # The existing prepare_delivery seam keeps this explicit scope.
            selected = self.method.prepare(
                [source["source_ref"] for source in delivery["sources"]],
                "",
                selected_records=[self.method.service.read(record_id) for record_id in record_ids],
                redelivered_ranges=[],
            )
            return {
                **located,
                "records": selected["records"],
                "historical_evidence": selected["historical_evidence"],
            }

        return maintain_event(
            self.method,
            delivery,
            session=SESSION,
            request_id=request_id,
            date=delivery["sources"][0]["observed_at"],
            recipe="single_pass",
            model_call=transport,
            prepare_delivery=selected_delivery,
        )

    def reconcile(self, *, request_id: str) -> dict[str, Any] | None:
        """Read the original checkpoint, without issuing evidence or model calls."""
        self.inspections.append(request_id)
        saved = self.method.service.store.get(
            (*self.method.service.namespace, "edit_maintenance"),
            json.dumps([SESSION, request_id], ensure_ascii=False),
        )
        if saved is None:
            return None
        binding = saved.value["binding"]

        def forbidden_transport(
            stage: str,
            messages: list[dict[str, str]],
            schema: dict[str, Any],
        ) -> dict[str, Any]:
            raise AssertionError("Read-only consolidation recovery invoked transport")

        return resume_maintenance(
            self.method,
            {"sources": deepcopy(binding["sources"])},
            session=SESSION,
            prior_request_id=request_id,
            date=saved.value["date"],
            recipe=cast(MaintenanceRecipe, binding["recipe"]),
            model_call=forbidden_transport,
            selected_record_ids=binding.get("selected_record_ids"),
            new_attempt_id=None,
        )


def saved_id(result: dict[str, Any]) -> str:
    assert result["status"] == "completed", result
    receipt = result["receipts"][0]
    assert receipt["ok"] and receipt["status"] == "committed", receipt
    return str(receipt["id"])


def example(root: Path) -> dict[str, Any]:
    calls: list[str] = []
    with opened(root) as (service, episodes, method):
        meeting, meeting_episode = capture(
            service, "meeting", "10月8日14:00, 林和梅开计划会; 目标是确认下一周安排。"
        )
        episodes.register(
            meeting_episode,
            [meeting],
            descriptions=[
                {
                    "kind": "event",
                    "basis": "reported",
                    "text": "一次计划会安排",
                    "source_refs": [meeting],
                    "occurred_at": "2026-10-08T14:00:00+08:00",
                },
                {
                    "kind": "participant",
                    "basis": "reported",
                    "text": "林和梅",
                    "source_refs": [meeting],
                },
                {
                    "kind": "context",
                    "basis": "reported",
                    "text": "确认下一周安排",
                    "source_refs": [meeting],
                },
                {
                    "kind": "outcome",
                    "basis": "uncertain",
                    "text": "会议是否已经举行未知",
                    "source_refs": [meeting],
                },
            ],
        )
        meeting_callback = ScriptedMaintenance(
            method,
            {
                "action": "create",
                "units": [
                    {
                        "text": "计划会: 2026年10月8日14:00; 参与者林和梅; 目标确认下一周安排。",
                        "evidence": ["e1"],
                    },
                ],
            },
            calls,
        )
        committed: dict[str, Any] = {}

        def commit_then_interrupt(**kwargs: Any) -> dict[str, Any]:
            committed.update(meeting_callback(**kwargs))
            raise RuntimeError("Interrupted before outer consolidation result was saved")

        try:
            consolidate(
                episodes,
                request_id="meeting-maintain",
                episode_ids=[meeting_episode],
                maintain=commit_then_interrupt,
            )
        except RuntimeError as error:
            assert str(error) == "Interrupted before outer consolidation result was saved"
        else:
            raise AssertionError("The actual commit interruption did not occur")
        meeting_id = saved_id(committed)
        pending = service.store.get((*service.namespace, "consolidation"), "meeting-maintain")
        assert pending is not None and pending.value["result"]["phase"] == "maintenance_pending"
        assert episodes.select(pending_only=True)[0]["episode_id"] == meeting_episode
        source_count = len(service.sources())
        original_history = service.history_index(meeting_id)["revisions"]
        original_records = [row["value"] for row in service.records()]
    with opened(root) as (service, episodes, method):

        def forbidden_maintain(**kwargs: Any) -> dict[str, Any]:
            raise AssertionError("A replay called generating maintenance")

        recovered_callback = ScriptedMaintenance(method, {}, calls)
        try:
            consolidate(
                episodes,
                request_id="meeting-maintain",
                episode_ids=[meeting_episode],
                record_ids=[meeting_id],
                maintain=forbidden_maintain,
                reconcile=recovered_callback.reconcile,
            )
        except FunctionalRejection as error:
            assert str(error) == "CONSOLIDATION_REQUEST_SELECTION_CHANGED"
        else:
            raise AssertionError("Reconciliation accepted a changed original selection")
        assert recovered_callback.inspections == []
        first = consolidate(
            episodes,
            request_id="meeting-maintain",
            episode_ids=[meeting_episode],
            maintain=forbidden_maintain,
            reconcile=recovered_callback.reconcile,
        )
        assert first["status"] == "completed" and first["replayed"] and first["reconciled"]
        assert saved_id(first) == meeting_id and first["receipts"][0]["revision"] == 1
        assert recovered_callback.inspections == ["meeting-maintain"]
        assert service.history_index(meeting_id)["revisions"] == original_history
        assert [row["value"] for row in service.records()] == original_records
        assert len(calls) == 1 and len(service.sources()) == source_count
        replay = consolidate(
            episodes,
            request_id="meeting-maintain",
            episode_ids=[meeting_episode],
            maintain=forbidden_maintain,
            reconcile=recovered_callback.reconcile,
        )
        assert replay["replayed"] and len(calls) == 1
        assert recovered_callback.inspections == ["meeting-maintain"]
        assert len(service.sources()) == source_count
        meeting_view = episodes.read(meeting_episode)
        assert meeting_view is not None and meeting_view["actual_outcomes"] == []
        assert episodes.associated_records(meeting_episode)[0]["id"] == meeting_id
        assert episodes.select(pending_only=True) == []
    with opened(root) as (service, episodes, method):
        meeting_view = episodes.read(meeting_episode)
        assert meeting_view is not None and meeting_view["sources"][0]["content"] == (
            "10月8日14:00, 林和梅开计划会; 目标是确认下一周安排。"
        )
        preference, preference_episode = capture(
            service, "preference", "以后都按这种“时间、参与者、目标”格式记录会议。"
        )
        episodes.register(
            preference_episode,
            [preference],
            descriptions=[
                {
                    "kind": "event",
                    "basis": "reported",
                    "text": "明确的未来会议记录格式偏好",
                    "source_refs": [preference],
                },
            ],
        )
        preferred = consolidate(
            episodes,
            request_id="preference-maintain",
            episode_ids=[preference_episode],
            prior_episode_ids=[meeting_episode],
            maintain=ScriptedMaintenance(
                method,
                {
                    "action": "create",
                    "units": [
                        {"text": "未来会议都按时间、参与者、目标的格式记录。", "evidence": ["e1"]},
                    ],
                },
                calls,
            ),
        )
        preference_id = saved_id(preferred)
        assert service.read(preference_id)["value"]["source_refs"] == [preference]
        cancellation, cancellation_episode = capture(
            service, "cancel", "取消这项未来格式偏好; 已经记录的会议安排请保留。"
        )
        episodes.register(
            cancellation_episode,
            [cancellation],
            descriptions=[
                {
                    "kind": "event",
                    "basis": "reported",
                    "text": "撤销未来格式偏好, 保留会议历史",
                    "source_refs": [cancellation],
                },
            ],
        )
        cancellation_callback = ScriptedMaintenance(
            method,
            {
                "action": "edit",
                "target": "r1",
                "edits": [{"operation": "retract", "target_unit": "u1", "evidence": ["e1"]}],
            },
            calls,
        )
        canceled = consolidate(
            episodes,
            request_id="cancellation-maintain",
            episode_ids=[cancellation_episode],
            record_ids=[preference_id],
            maintain=cancellation_callback,
        )
        assert canceled["status"] == "completed", canceled
        assert service.read(preference_id)["status"] == "retracted"
        assert service.read(preference_id, 1)["ok"]
        cancellation_replay = consolidate(
            episodes,
            request_id="cancellation-maintain",
            episode_ids=[cancellation_episode],
            record_ids=[preference_id],
            maintain=cancellation_callback,
        )
        assert cancellation_replay["status"] == "completed" and cancellation_replay["replayed"]
        assert len(calls) == 3
        assert service.read(meeting_id)["value"]["revision"] == 1
        assert episodes.read(meeting_episode) is not None

        def unknown_maintain(**kwargs: Any) -> dict[str, Any]:
            def lose_model_reply(
                stage: str,
                messages: list[dict[str, str]],
                schema: dict[str, Any],
            ) -> dict[str, Any]:
                calls.append(stage)
                raise OSError("Scripted original model reply unknown")

            return maintain_event(
                method,
                kwargs["delivery"],
                session=SESSION,
                request_id=kwargs["request_id"],
                date=kwargs["delivery"]["sources"][0]["observed_at"],
                recipe="single_pass",
                model_call=lose_model_reply,
                selected_record_ids=kwargs["record_ids"],
            )

        try:
            consolidate(
                episodes,
                request_id="unknown-maintain",
                episode_ids=[cancellation_episode],
                record_ids=[meeting_id],
                maintain=unknown_maintain,
            )
        except OSError as error:
            assert str(error) == "Scripted original model reply unknown"
        else:
            raise AssertionError("The unknown model window did not occur")
        assert len(calls) == 4
        unchanged_history = service.history_index(meeting_id)["revisions"]
        unchanged_sources = service.sources()
    with opened(root) as (service, episodes, method):
        unknown_callback = ScriptedMaintenance(method, {}, calls)
        unknown = consolidate(
            episodes,
            request_id="unknown-maintain",
            episode_ids=[cancellation_episode],
            record_ids=[meeting_id],
            maintain=forbidden_maintain,
            reconcile=unknown_callback.reconcile,
        )
        assert unknown["status"] == "incomplete" and unknown["phase"] == "edit_pending"
        assert unknown["unprocessed"][0]["reason"] == "model_outcome_unconfirmed"
        assert len(calls) == 4 and service.sources() == unchanged_sources
        assert service.history_index(meeting_id)["revisions"] == unchanged_history
        cancellation_view = episodes.read(cancellation_episode)
        assert cancellation_view is not None
        assert cancellation_view["consolidation_request_id"] == "cancellation-maintain"
        handle = service.read(meeting_id)["candidate_handle"]
        assert service.forget(
            SESSION, "forget-record-only", candidate_handle=handle, scope="record"
        )["ok"]
        assert service.source(meeting) is not None
        hidden_record = consolidate(
            episodes,
            request_id="unknown-maintain",
            episode_ids=[cancellation_episode],
            record_ids=[meeting_id],
            maintain=forbidden_maintain,
            reconcile=unknown_callback.reconcile,
        )
        assert hidden_record["status"] == "visibility_revoked"
        assert unknown_callback.inspections == ["unknown-maintain"]
        fragment = service.source_fragments(meeting)[0]["fragment_handle"]
        capture(service, "forget", "忘掉那次会议的来源和相应记忆。")
        forgotten = service.forget(SESSION, "forget-meeting", fragment_handles=[fragment])
        assert forgotten["ok"], forgotten
        assert service.source(meeting) is None
        assert episodes.read(meeting_episode) is None
        assert episodes.associated_records(meeting_episode) == []
        assert not service.read(meeting_id)["ok"]
        hidden = consolidate(
            episodes,
            request_id="meeting-maintain",
            episode_ids=[meeting_episode],
            maintain=forbidden_maintain,
            reconcile=unknown_callback.reconcile,
        )
        assert hidden["status"] == "visibility_revoked" and len(calls) == 4
        assert unknown_callback.inspections == ["unknown-maintain"]
        try:
            consolidate(
                episodes,
                request_id="new-meeting-replay",
                episode_ids=[meeting_episode],
                maintain=forbidden_maintain,
            )
        except FunctionalRejection as error:
            assert str(error) == "CONSOLIDATION_EPISODE_UNAVAILABLE"
        else:
            raise AssertionError("Forgotten episode entered maintenance")
    with opened(root) as (service, episodes, method):
        assert episodes.read(meeting_episode) is None
        assert service.source(meeting) is None
        assert service.read(preference_id)["status"] == "retracted"
        return {
            "engineering_example": "completed",
            "scripted_editor_calls": len(calls),
            "completed_callback_interruption_recovered": True,
            "unknown_model_not_regenerated": True,
            "selected_record_revocation_precedes_reconciliation": True,
            "real_model_or_embedding_calls": 0,
            "meeting_history_preserved_on_preference_cancellation": True,
            "source_forget_revoked_episode_and_derived_access": True,
            "replay_added_independent_support": False,
            "persistent_preference_status": service.read(preference_id)["status"],
            "visible_episode_ids": [row["episode_id"] for row in episodes.select()],
        }


def main() -> None:
    with TemporaryDirectory(prefix="milai-episodes-") as directory:
        print(json.dumps(example(Path(directory)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
