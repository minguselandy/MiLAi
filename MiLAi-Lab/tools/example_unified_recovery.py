"""Two real SQLite sandboxes, one adapter, no model/embedding network calls.

Run from MiLAi-Lab with PYTHONPATH=src python tools/example_unified_recovery.py.
The temporary databases prove effects and persistence, not natural-language quality.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.document_publication import DocumentPublicationWorld
from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.recovery import UnknownModelRequest, resume_request
from milai_lab.contracts.memory import VerifiedObjectRef
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.service import MemoryService


@contextmanager
def opened(
    root: Path,
    workflow: str,
    turn: str,
) -> Iterator[tuple[FunctionalApplication, FunctionalMemory, RunnableConfig]]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("recovery_example", "alice"),
            "alice",
            root / "memory.lock",
            functional_contract="functional_v1",
            receipt_profile=workflow,
        )
        memory = FunctionalMemory(service, len, read_limit=16, material_limit=16000)
        service.capture_user(
            "example", turn, "Continue the requested work and save its actual result."
        )
        memory.context("example", turn, "recovery_example_v1")
        config: RunnableConfig = {
            "configurable": {
                "user_id": "alice",
                "v13_session": "example",
                "v13_turn_id": turn,
                "v13_config_version": "recovery_example_v1",
            }
        }
        with FunctionalApplication.open(
            root / "application",
            workflow,
            "alice",
            initial_label_available=False,
            initial_publication_available=False,
        ) as app:
            yield app, memory, config


def save_actual_result(memory: FunctionalMemory, config: RunnableConfig) -> Any:
    def save(operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
        # Only an actual currently visible receipt supports this example's text.
        result = progress["business"]["observation"]
        for step in progress["business"]["steps"]:
            for attempt in step["attempts"]:
                if attempt.get("result", {}).get("receipt", {}).get("ok"):
                    result = attempt["result"]
        source_ref = result["source_ref"]
        receipt = result["receipt"]
        fields = (
            (
                "document_id",
                "title",
                "document_version",
                "approval_status",
                "publication_status",
                "audience",
            )
            if "document_id" in receipt
            else (
                "reservation_id",
                "item_key",
                "quantity",
                "destination",
                "packing",
                "label_status",
            )
        )
        assertion = json.dumps({field: receipt[field] for field in fields}, ensure_ascii=False)
        handles = [
            fragment["fragment_handle"] for fragment in memory.service.source_fragments(source_ref)
        ]
        return memory.save(config, operation_id, assertion, handles)

    return save


def actual_feedback(_operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "available",
        "business": progress["business"]["status"],
        "memory": progress["memory"]["status"],
        "source_refs": progress["source_refs"],
    }


def reservation(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True)
    arguments = {
        "item_key": "example parcel",
        "quantity": 2,
        "destination": "front desk",
        "packing": "box",
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
    with opened(root, "reservation_v1", "start") as (app, memory, config):
        adapter = app.adapter(
            memory.service,
            "example",
            "start",
            allowed_operations=("reserve_and_label", "complete_label"),
        )
        partial = resume_request(
            app,
            adapter,
            "reservation",
            requirements=requirements,
            current={"allow_memory": True},
            save_result=save_actual_result(memory, config),
            feedback=actual_feedback,
        )
        assert partial["business"]["status"] == "partial"
        assert partial["business"]["steps"][0]["status"] == "completed"
        assert partial["memory"]["status"] == "pending"
        receipt = partial["business"]["steps"][0]["attempts"][0]["result"]
        old_ref = VerifiedObjectRef(**receipt["object_ref"])
        assert old_ref.fields["label_status"] == "not_created"
        assert len(app.world.snapshot()["attempts"]) == 1

    with opened(root, "reservation_v1", "status-only") as (app, memory, _config):
        readonly = app.adapter(memory.service, "example", "status-only")
        observed = resume_request(app, readonly, "reservation", current={"readonly": True})
        assert observed["business"]["status"] == "partial"
        assert observed["business"]["execution"]["status"] == "observed_only"
        assert not observed["business"]["execution"]["can_execute"]
        assert len(app.world.snapshot()["attempts"]) == 1 and not memory.service.records()
        denied = readonly.execute("complete_label", {}, attempt_id="denied", ref=old_ref)
        assert denied["status"] == "operation_not_authorized_current_request"

    with opened(root, "reservation_v1", "continue") as (app, memory, config):
        app.world.set_label_available("labels-back", True)
        adapter = app.adapter(
            memory.service, "example", "continue", allowed_operations=("complete_label",)
        )
        complete = resume_request(
            app,
            adapter,
            "reservation",
            current={"allow_memory": True},
            save_result=save_actual_result(memory, config),
            feedback=actual_feedback,
        )
        assert complete["complete"] and complete["memory"]["status"] == "committed"
        assert [row["operation"] for row in app.world.snapshot()["attempts"]] == [
            "reserve_and_label",
            "complete_label",
        ]
        assert len(memory.service.records()) == 1
        fresh = adapter.observe(old_ref, attempt_id="fresh-state")
        assert fresh["current_state"]["label_status"] == "created"
        assert old_ref.fields["label_status"] == "not_created"
        again = resume_request(
            app,
            adapter,
            "reservation",
            current={"allow_memory": True},
            save_result=save_actual_result(memory, config),
            feedback=actual_feedback,
        )
        assert again["complete"] and len(memory.service.records()) == 1
        revoked = app.adapter(memory.service, "example", "continue", can_read=False)
        hidden = resume_request(app, revoked, "reservation")
        assert hidden["status"] == "access_revoked" and hidden["source_refs"] == []
        return {
            "business": complete["business"]["status"],
            "memory": complete["memory"]["status"],
            "business_attempts": 2,
            "semantic_records": 1,
            "readonly_mutations": 0,
        }


def document(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True)
    title, body, audience = "Example agenda", "Discuss the release on Friday.", "project team"
    requirements = {
        "target": {"title": title},
        "steps": [
            {
                "id": "draft",
                "operation": "create_or_update_draft",
                "arguments": {"title": title, "content": body, "document_version": 0},
                "completed": {"title": title, "content": body},
            },
            {
                "id": "approve",
                "operation": "approve_document_version",
                "arguments": {},
                "arguments_from_state": {"document_version": "document_version"},
                "completed": {"approval_status": "approved", "approved_version": 1},
            },
            {
                "id": "publish",
                "operation": "publish_approved_document",
                "arguments": {"audience": audience},
                "arguments_from_state": {"document_version": "document_version"},
                "completed": {
                    "publication_status": "published",
                    "published_version": 1,
                    "audience": audience,
                },
            },
        ],
        "save_result": True,
        "feedback": True,
    }
    with opened(root, "document_publication_v1", "start") as (app, memory, config):
        adapter = app.adapter(
            memory.service,
            "example",
            "start",
            allowed_operations=(
                "create_or_update_draft",
                "approve_document_version",
                "publish_approved_document",
            ),
        )
        partial = resume_request(
            app,
            adapter,
            "document",
            requirements=requirements,
            current={"allow_memory": True},
            save_result=save_actual_result(memory, config),
            feedback=actual_feedback,
        )
        assert partial["business"]["status"] == "partial"
        assert [step["status"] for step in partial["business"]["steps"]] == [
            "completed",
            "completed",
            "incomplete",
        ]

    with opened(root, "document_publication_v1", "continue") as (app, memory, _config):
        cast(DocumentPublicationWorld, app.world).set_publication_available(
            "publication-back", True)
        adapter = app.adapter(
            memory.service, "example", "continue", allowed_operations=("publish_approved_document",)
        )

        def unknown_model(_operation_id: str, _progress: dict[str, Any]) -> dict[str, Any]:
            raise UnknownModelRequest("scripted model response lost before semantic proposal")

        uncertain = resume_request(
            app,
            adapter,
            "document",
            current={"allow_memory": True},
            save_result=unknown_model,
            feedback=actual_feedback,
        )
        assert uncertain["business"]["status"] == "completed"
        assert uncertain["memory"]["status"] == "model_unknown" and not memory.service.records()

    with opened(root, "document_publication_v1", "new-semantic-attempt") as (app, memory, config):
        adapter = app.adapter(memory.service, "example", "new-semantic-attempt")
        complete = resume_request(
            app,
            adapter,
            "document",
            current={
                "allow_memory": True,
                "new_semantic_attempt": True,
            },
            save_result=save_actual_result(memory, config),
            feedback=actual_feedback,
        )
        assert complete["complete"] and len(memory.service.records()) == 1
        assert [attempt["status"] for attempt in complete["memory"]["attempts"]] == [
            "model_unknown",
            "committed",
        ]
        world = app.world.snapshot()["documents"][0]
        assert len(world["versions"]) == len(world["approvals"]) == len(world["publications"]) == 1
        return {
            "business": complete["business"]["status"],
            "memory": complete["memory"]["status"],
            "draft_versions": 1,
            "approvals": 1,
            "publications": 1,
            "old_model_unknown_preserved": True,
            "semantic_records": 1,
        }


def main() -> None:
    with TemporaryDirectory(prefix="milai-unified-recovery-") as directory:
        root = Path(directory)
        output = {
            "reservation": reservation(root / "reservation"),
            "document": document(root / "document"),
            "model_http_requests": 0,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
