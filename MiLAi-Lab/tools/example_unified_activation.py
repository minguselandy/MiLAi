"""A browsable isolated trajectory through real SQLite and shared public calls.

Run with PYTHONPATH=src python tools/example_unified_activation.py. Transport
copies currently delivered statements into editor proposals; it is synthetic,
not a natural-language model or an evaluator. There are zero HTTP calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.recovery import resume_request
from milai_lab.harness.memory_simulation import (
    MemorySimulation,
    SimulationCallbacks,
    VirtualClock,
    action,
    cancellation,
    correction,
    exception,
    fact,
    gap,
)
from milai_lab.memory.activation import ActivationIndex, rank_candidates
from milai_lab.memory.edit_units import issue_evidence
from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import body_text
from milai_lab.memory.service import MemoryService
from milai_lab.methods.consolidation import consolidate
from milai_lab.methods.edit_maintenance import maintain_event
from milai_lab.methods.edit_memory import EditMemory

OWNER = "isolated-activation-example"
SESSION = "simulation"
CONFIG_VERSION = "activation-example-v1"


class ExampleRuntime:
    """Bind the same calls used by Host; no direct correct-state Store writes."""

    def __init__(self, service: MemoryService, app: FunctionalApplication) -> None:
        self.service, self.app = service, app
        self.index, self.episodes = ActivationIndex(service), EpisodeIndex(service)
        self.method = EditMemory(service, "M", interface_version="I2")
        self.memory = FunctionalMemory(service, len, read_limit=8, material_limit=16000)
        self.sources: dict[str, dict[str, Any]] = {}
        self.records: dict[str, str] = {}
        self.scripted_calls: list[str] = []

    def ingest(self, request_id: str, input: dict[str, Any]) -> dict[str, Any]:
        capture = (
            self.service.capture_assistant
            if input.get("role", "user") == "assistant"
            else self.service.capture_user
        )
        receipt = capture(SESSION, request_id, input["content"])
        self.sources[request_id] = receipt
        if input.get("role", "user") == "user":
            self.service.bind_public_turn(
                SESSION,
                request_id,
                receipt["source_ref"],
                config_version=CONFIG_VERSION,
                phase="start",
            )
        if input.get("feedback_for"):
            receipt["feedback_recording"] = self.index.record_feedback(
                self.records[input["feedback_for"]],
                request_id=request_id,
                source_ref=receipt["source_ref"],
                useful=input.get("useful"),
            )
        return receipt

    def delivered(self, source_ref: str) -> dict[str, Any]:
        event = self.service.source(source_ref)
        assert event is not None
        text = body_text(event)
        return {
            "sources": [
                {
                    **issue_evidence(self.service, source_ref, 0, len(text)),
                    "text": text,
                    "role": event["role"],
                    "observed_at": event["observed_at"],
                    "occurred_at": event.get("occurred_at"),
                    "body_delivered": True,
                }
            ],
            "prior_context": [],
        }

    def maintain(self, request_id: str, input: dict[str, Any]) -> dict[str, Any]:
        source = self.sources[input["source_event_id"]]
        delivery = self.delivered(source["source_ref"])
        selected = [self.records[input["record_of"]]] if input.get("record_of") else []

        def transport(
            stage: str,
            messages: list[dict[str, str]],
            schema: dict[str, Any],
        ) -> dict[str, Any]:
            self.scripted_calls.append(stage)
            statement = delivery["sources"][0]["text"]
            if selected:
                proposal = {
                    "action": "edit",
                    "target": "r1",
                    "edits": [
                        {
                            "operation": "replace",
                            "target_unit": "u1",
                            "text": statement,
                            "evidence": ["e1"],
                        }
                    ],
                }
            else:
                proposal = {
                    "action": "create",
                    "units": [{"text": statement, "evidence": ["e1"]}],
                }
            return {"proposals": [proposal]}

        def selected_delivery(located: dict[str, Any]) -> dict[str, Any]:
            explicit = self.method.prepare(
                [source["source_ref"]],
                delivery["sources"][0]["text"],
                selected_records=[self.service.read(record_id) for record_id in selected],
            )
            return {
                **located,
                "records": explicit["records"],
                "historical_evidence": explicit["historical_evidence"],
            }

        result = maintain_event(
            self.method,
            delivery,
            session=SESSION,
            request_id=request_id,
            date=self.service.clock().isoformat(),
            recipe="single_pass",
            model_call=transport,
            prepare_delivery=selected_delivery,
        )
        for receipt in result["receipts"]:
            if receipt.get("ok"):
                self.records[request_id] = receipt["id"]
        return result

    def recall(self, request_id: str, input: dict[str, Any]) -> dict[str, Any]:
        found = self.service.search(input["query"], include_raw=False)
        views = []
        for record in found["records"]:
            before = self.index.describe(record["id"], pinned=input.get("pinned", False))
            usage = self.index.record_use(
                record["id"],
                request_id=input.get("usage_request_id", request_id),
                cached=input.get("cached", False),
                replay=input.get("replay", False),
            )
            views.append(
                {
                    "before": before,
                    "use_recording": usage,
                    "after": self.index.describe(record["id"]),
                }
            )
        return {"status": found["status"], "records": found["records"], "activation": views}

    def consolidation(self, request_id: str, input: dict[str, Any]) -> dict[str, Any]:
        episode_ids = [self.sources[event_id]["episode_id"] for event_id in input["events"]]

        def maintain(
            *,
            delivery: dict[str, Any],
            record_ids: list[str],
            episode_ids: list[str],
            request_id: str,
        ) -> dict[str, Any]:
            def transport(
                stage: str,
                messages: list[dict[str, str]],
                schema: dict[str, Any],
            ) -> dict[str, Any]:
                self.scripted_calls.append(stage)
                # These sources were already maintained. A normal empty proposal
                # shows that replay neither captures nor counts a fresh event.
                return {"proposals": []}

            return maintain_event(
                self.method,
                delivery,
                session=SESSION,
                request_id=request_id,
                date=self.service.clock().isoformat(),
                recipe="single_pass",
                model_call=transport,
            )

        result = consolidate(
            self.episodes,
            request_id=request_id,
            episode_ids=episode_ids,
            maintain=maintain,
        )
        for record_id in self.records.values():
            self.index.record_use(record_id, request_id=request_id, replay=True)
        return result

    def forget(self, request_id: str, input: dict[str, Any]) -> dict[str, Any]:
        refs = [self.sources[event_id]["source_ref"] for event_id in input["events"]]
        fragments = [
            self.service.source_fragments(source_ref)[0]["fragment_handle"] for source_ref in refs
        ]
        return self.service.forget(SESSION, request_id, fragment_handles=fragments)

    def resume(self, turn_id: str, input: dict[str, Any]) -> dict[str, Any]:
        self.ingest(turn_id, {"content": input["content"]})
        self.memory.context(SESSION, turn_id, CONFIG_VERSION)
        config: RunnableConfig = {
            "configurable": {
                "user_id": OWNER,
                "v13_session": SESSION,
                "v13_turn_id": turn_id,
                "v13_config_version": CONFIG_VERSION,
            }
        }
        if input.get("labels_available"):
            self.app.world.set_label_available(turn_id, True)
        adapter = self.app.adapter(
            self.service,
            SESSION,
            turn_id,
            allowed_operations=input.get("operations", ()),
        )

        def save(operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
            observation = progress["business"]["observation"]
            receipt, ref = observation["receipt"], observation["source_ref"]
            text = json.dumps(
                {
                    key: receipt[key]
                    for key in (
                        "reservation_id",
                        "item_key",
                        "quantity",
                        "destination",
                        "packing",
                        "label_status",
                    )
                }
            )
            handles = [
                fragment["fragment_handle"] for fragment in self.service.source_fragments(ref)
            ]
            return self.memory.save(config, operation_id, text, handles)

        def feedback(operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
            return {
                "ok": True,
                "business": progress["business"]["status"],
                "memory": progress["memory"]["status"],
                "source_refs": progress["source_refs"],
            }

        result = resume_request(
            self.app,
            adapter,
            input["request_id"],
            requirements=input.get("requirements"),
            current=input.get("current"),
            save_result=save,
            feedback=feedback,
        )
        return {**result, "actual_business_attempts": len(self.app.world.snapshot()["attempts"])}

    def callbacks(self) -> SimulationCallbacks:
        return SimulationCallbacks(
            ingest=self.ingest,
            maintain=self.maintain,
            recall=self.recall,
            consolidate=self.consolidation,
            resume=self.resume,
            forget=self.forget,
            snapshot=self.service.export_snapshot,
        )


def run(root: Path) -> dict[str, Any]:
    clock = VirtualClock(datetime(2026, 1, 1, 9, tzinfo=UTC))
    with (
        SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store,
        FunctionalApplication.open(
            root / "application",
            "reservation_v1",
            OWNER,
            initial_label_available=False,
        ) as app,
    ):
        service = MemoryService(
            store,
            ("simulation", OWNER),
            OWNER,
            root / "memory.lock",
            functional_contract="functional_v1",
            memory_profile="unified_v1",
            clock=clock,
        )
        runtime = ExampleRuntime(service, app)
        simulator = MemorySimulation(owner=OWNER, clock=clock, callbacks=runtime.callbacks())
        arguments = {
            "item_key": "reminder cards",
            "quantity": 1,
            "destination": "front desk",
            "packing": "envelope",
        }
        requirements = {
            "target": {"item_key": arguments["item_key"]},
            "steps": [
                {
                    "id": "reserve",
                    "operation": "reserve_and_label",
                    "arguments": arguments,
                    "completed": arguments,
                },
                {
                    "id": "label",
                    "operation": "complete_label",
                    "arguments": {},
                    "arguments_from_state": {"reservation_id": "reservation_id"},
                    "completed": {"label_status": "created"},
                },
            ],
            "save_result": True,
            "feedback": True,
        }
        events = [
            fact("preference", "I use paper reminders for appointments."),
            action("save-preference", "maintain", source_event_id="preference"),
            action("read-first", "recall", query="reminders", usage_request_id="same-request"),
            action("read-page", "recall", query="reminders", usage_request_id="same-request"),
            gap("one-day", days=1),
            action("read-later", "recall", query="reminders"),
            action(
                "positive-feedback",
                "ingest",
                content="That reminder information was useful.",
                feedback_for="save-preference",
                useful=True,
            ),
            action(
                "unknown-feedback",
                "ingest",
                content="I haven't used it yet.",
                feedback_for="save-preference",
                useful=None,
            ),
            action(
                "assistant-summary",
                "ingest",
                role="assistant",
                content="The answer was useful.",
                feedback_for="save-preference",
                useful=True,
            ),
            action("consolidate-sources", "consolidate", events=["preference"]),
            gap("long-gap", days=180),
            action("read-cold", "recall", query="reminders"),
            correction("correction", "From today I use calendar reminders for appointments."),
            action(
                "save-correction",
                "maintain",
                source_event_id="correction",
                record_of="save-preference",
            ),
            exception("exception", "For medical appointments only, use a paper reminder too."),
            action("save-exception", "maintain", source_event_id="exception"),
            cancellation("cancel", "Cancel the extra paper reminder for medical appointments."),
            action("save-cancel", "maintain", source_event_id="cancel"),
            action(
                "partial-business",
                "resume",
                request_id="parcel",
                requirements=requirements,
                operations=["reserve_and_label", "complete_label"],
                current={"allow_memory": True},
                content="Reserve reminder cards, label them, and save the actual result.",
            ),
            gap("interrupted-gap", days=1),
            action(
                "readonly-business",
                "resume",
                request_id="parcel",
                current={"readonly": True},
                content="Just read the reservation status; do not change or save anything.",
            ),
            action(
                "continue-business",
                "resume",
                request_id="parcel",
                labels_available=True,
                operations=["complete_label"],
                current={"allow_memory": True},
                content="Continue the missing label and save the actual completed result.",
            ),
            action(
                "forget-reminders",
                "forget",
                events=["preference", "correction", "exception", "cancel"],
            ),
            action("read-forgotten", "recall", query="appointments"),
        ]
        trajectory = simulator.run(events)
        # Evaluation lives here after the trajectory, outside all runtime calls.
        by_id = {row["event_id"]: row for row in trajectory}
        first = by_id["read-first"]["result"]["activation"][0]["after"]
        repeated = by_id["read-page"]["result"]["activation"][0]
        cold = by_id["read-cold"]["result"]["activation"][0]
        assert len(first["uses"]) == 1 and not repeated["use_recording"]["recorded"]
        assert len(cold["before"]["uses"]) == 2
        assert cold["before"]["cold_storage"]["cold_suggested"]
        assert cold["after"]["activation"] > cold["before"]["activation"]
        assert cold["before"]["utility"]["n"] == 1
        assert by_id["consolidate-sources"]["result"]["new_independent_support"] is False
        assert by_id["save-correction"]["result"]["status"] == "completed"
        corrected_record = by_id["save-correction"]["snapshot"]["records"][0]
        assert corrected_record["value"]["revision"] == 2
        assert "calendar" in corrected_record["value"]["content"]
        assert by_id["partial-business"]["result"]["business"]["status"] == "partial"
        assert by_id["readonly-business"]["result"]["actual_business_attempts"] == 1
        assert by_id["continue-business"]["result"]["complete"]
        assert by_id["continue-business"]["result"]["actual_business_attempts"] == 2
        assert by_id["read-forgotten"]["result"]["records"] == []
        record_id = runtime.records["save-preference"]
        assert runtime.index.describe(record_id) is None
        ranking = rank_candidates(
            [
                {"id": "cold", "dense_score": 0.8, "activation": -4.0},
                {"id": "used", "dense_score": 0.79, "activation": 1.0},
                {
                    "id": "hidden-pinned",
                    "dense_score": 0.99,
                    "activation": 10.0,
                    "visible": False,
                    "pinned": True,
                },
            ]
        )
        assert ranking[0]["id"] == "used" and len(ranking) == 2
        rendered = [
            {
                "event_id": row["event_id"],
                "operation": row["operation"],
                "at": row["at"],
                "status": row["result"].get("status"),
                "visible_sources": len(row["snapshot"]["sources"]),
                "visible_records": len(row["snapshot"]["records"]),
                **(
                    {"activation": row["result"]["activation"]}
                    if "activation" in row["result"]
                    else {}
                ),
                **(
                    {
                        "business": row["result"]["business"]["status"],
                        "memory": row["result"]["memory"]["status"],
                        "actual_business_attempts": row["result"]["actual_business_attempts"],
                    }
                    if "business" in row["result"]
                    else {}
                ),
            }
            for row in trajectory
        ]
        calls = len(runtime.scripted_calls)
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        reopened = MemoryService(
            store,
            ("simulation", OWNER),
            OWNER,
            root / "memory.lock",
            functional_contract="functional_v1",
            memory_profile="unified_v1",
            clock=clock,
        )
        assert ActivationIndex(reopened).describe(record_id) is None
        assert reopened.records() and len([row for row in reopened.records() if row["ok"]]) == 1
    return {
        "engineering_example": "completed",
        "real_model_or_embedding_calls": 0,
        "scripted_editor_calls": calls,
        "activation_ranking": ranking,
        "trajectory": rendered,
        "reopen_forget_preserved": True,
        "method_effectiveness": "not evaluated by scripted transport",
    }


def main() -> None:
    with TemporaryDirectory(prefix="milai-activation-") as directory:
        print(json.dumps(run(Path(directory)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
