"""Explicit consolidation and full request continuation in an existing Host bank.

Uses the Host's frozen configuration, Store, queue, ledger and common editor.
Business continuation first discovers actual effects and uses current permissions.
Old sources are not captured again, and no background work is scheduled.
"""

from __future__ import annotations

import argparse
import json
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.functional import FunctionalApplication
from milai_lab.application.recovery import (
    UnknownModelRequest,
    UnknownSemanticCommit,
    resume_request,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunLimits, Trace, entry_budget, http_budget_scope
from milai_lab.memory.episodes import EpisodeIndex
from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.methods.consolidation import consolidate
from milai_lab.methods.edit_features import EditFeatures
from milai_lab.methods.edit_maintenance import MaintenanceRecipe, parse_object
from milai_lab.methods.functional_edit_memory import FUNCTIONAL_ARMS, FunctionalEditMemory
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.providers.embedding_capacity import MeteredEmbeddings
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient
from milai_lab.runners.functional import _bank_reference, _message_reference, frozen


def run(
    root: Path, *, bank: str, owner: str, session: str, request_id: str, text: str,
    episode_ids: list[str] | None = None, record_ids: list[str] | None = None,
    prior_episode_ids: list[str] | None = None, limit: int = 20,
    prior_request_id: str | None = None, new_attempt_id: str | None = None,
    readonly: bool = False, operation: str = "consolidate", workflow: str = "reservation",
    resume_request_id: str | None = None, requirements: dict[str, Any] | None = None,
    allowed_operations: list[str] | None = None, allow_memory: bool = True,
    allow_feedback: bool = True, can_read: bool = True,
) -> dict[str, Any]:
    """The caller supplies current permission and an actual new command identity."""
    if operation not in {"consolidate", "resume"}:
        raise ValueError("MEMORY_OPERATION_INVALID")
    if operation == "consolidate" and (readonly or not allow_memory):
        return {"status": "not_authorized_current_request", "model_calls": 0,
                "semantic_write_performed": False}
    freeze = frozen(root)
    profile_state = root / "profile-state.json"
    if profile_state.exists() and read_json(profile_state).get("disabled"):
        raise ValueError("FUNCTIONAL_PROFILE_DISABLED")
    settings = freeze["config"]
    bank_root = root / "banks" / _bank_reference(root, freeze["run_id"], bank, owner)
    if not (bank_root / "memory.sqlite").exists():
        raise FileNotFoundError(bank_root / "memory.sqlite")
    identity = _message_reference(bank_root, session, request_id)
    command_path = bank_root / f"{identity}-memory-operation-input.json"
    repeated_command = command_path.exists()
    if repeated_command:
        if read_json(command_path)["operation"] != operation:
            raise ValueError("MEMORY_OPERATION_COMMAND_CHANGED")
    else:
        write_json(command_path, {"operation": operation, "request_id": request_id,
                                  "session": session, "text": text,
                                  "resume_request_id": resume_request_id,
                                  "new_attempt_id": new_attempt_id})
    attempt = len(list(bank_root.glob(f"{identity}-memory-operation-attempt-*.json")))
    trace = Trace(bank_root / f"{identity}-memory-operation-{attempt}.jsonl",
                  "unified_memory_operation")
    with ExitStack() as stack:
        stack.enter_context(http_budget_scope(
            settings, RunLimits(**freeze["budget_before"]["limits"]),
            client_configs=[asdict(VLLMConfig(**settings["host"])), *(
                [asdict(VLLMConfig(**settings["embedding"]))] if "embedding" in settings else []
            )],
        ))
        budget = entry_budget(
            RunLimits(**freeze["budget_before"]["limits"]), Path(settings["budget_path"])
        )
        store = stack.enter_context(SqliteStore.from_conn_string(str(bank_root / "memory.sqlite")))
        retriever = None
        if "embedding" in settings:
            embedding_client = stack.enter_context(VLLMClient(
                VLLMConfig(**settings["embedding"]), emit=trace, budget=budget,
            ))
            retriever = SemanticRetriever(MeteredEmbeddings(
                embedding_client, settings["embedding"]["model"], settings["embedding_capacity"],
                dimension=settings["embedding_dimension"],
                batch_size=settings["embedding_batch_size"],
            ), settings["embedding_dimension"])
        service = MemoryService(
            store, ("functional", freeze["run_id"], bank, owner), owner,
            bank_root / "memory.lock", functional_contract="functional_v1",
            memory_profile=settings.get("memory_profile", "ordinary"), semantic_retriever=retriever,
            memory_ranking=settings.get("memory_ranking", "dense"),
            observer=trace,
        )
        capture = service.capture_user(session, request_id, text)
        if not capture["ok"]:
            return capture
        service.bind_source_boundary(session, request_id, [capture["source_ref"]])
        service.bind_public_turn(
            session, request_id, capture["source_ref"], config_version=freeze["config_version"],
            phase="start",
        )
        capacity = HostCapacity(settings["capacity"])
        client = FunctionalVLLMClient(
            VLLMConfig(**settings["host"]), emit=trace, budget=budget, capacity=capacity,
        )
        stack.enter_context(client)
        client.queue = FunctionalQueue(root / "queue-admission.json", **settings["queue_limits"])
        model = LangMemRecipeChatModel(
            client=client, capacity_path=bank_root / "message-admission.json",
            max_calls_per_message=settings["max_calls_per_message"],
            generation_admission_profile="durable_shared_v1",
        )
        admission_path = bank_root / "message-admission.json"
        prior_admission = any(
            row["identity"]["owner"] == owner and row["identity"]["session"] == session
            and row["identity"]["public_message_id"] == request_id
            for row in (read_json(admission_path).get("messages", {}).values()
                        if admission_path.exists() else [])
        )
        model.begin_public_message(request_id,
                                  admission_phase="resume" if prior_admission else "start",
                                  admission_scope={
            "owner": owner, "bank": list(service.namespace), "session": session,
            "request_ref": capture["source_ref"], "request_revision": 1,
            "config_version": freeze["config_version"],
        })
        features = EditFeatures.from_settings(settings.get("edit_features", {}))
        arm = FUNCTIONAL_ARMS[settings["memory_method"]]
        memory = FunctionalEditMemory(
            service, capacity.text_tokens, arm=arm, interface_version="I2", features=features,
            maintenance_recipe=settings.get("maintenance_recipe", "single_pass"),
            read_limit=settings["additional_reads"],
            material_limit=settings["ordinary_material_tokens"],
        )
        config = cast(RunnableConfig, {"max_concurrency": 1, "configurable": {
            "user_id": owner, "thread_id": "memory-operation:" + identity,
            "v13_session": session, "v13_turn_id": request_id,
            "v13_config_version": freeze["config_version"],
        }})
        recipe = cast(MaintenanceRecipe, settings.get("maintenance_recipe", "single_pass"))

        def fit(messages: list[dict[str, str]]) -> bool:
            try:
                capacity.check(messages)
            except CapacityExceeded:
                return False
            return True

        def call(
            stage: str, messages: list[dict[str, str]], schema: dict[str, Any],
        ) -> dict[str, Any]:
            response = model.invoke(messages, tools=[], tool_choice="none")
            if not isinstance(response, AIMessage) or not isinstance(response.content, str):
                raise ValueError("FUNCTIONAL_MAINTENANCE_RESPONSE_MISSING")
            envelope = parse_object(response.content, reject_duplicate_keys=True)
            trace({"event": "functional_maintenance_envelope", "stage": stage,
                   "envelope": envelope})
            return envelope

        def maintain(
            *, delivery: dict[str, Any], record_ids: list[str], episode_ids: list[str],
            request_id: str,
        ) -> dict[str, Any]:
            kwargs: dict[str, Any] = dict(
                request_id=request_id,
                date=service.clock().isoformat(), recipe=recipe, model_call=call, fit=fit,
                selected_record_ids=record_ids or None, allowed=True,
                prior_request_id=prior_request_id, new_attempt_id=new_attempt_id,
            )
            return memory.maintain_delivery(config, delivery, **kwargs)

        if operation == "consolidate":
            result = consolidate(
                EpisodeIndex(service), request_id=request_id, maintain=maintain,
                episode_ids=episode_ids, record_ids=record_ids or [],
                prior_episode_ids=prior_episode_ids or [], limit=limit,
            )
            result["business_operations_executed"] = 0
        else:
            app = stack.enter_context(FunctionalApplication.open(
                bank_root / "applications" / workflow, workflow, owner,
                attempt_policy=settings.get("business_attempt_policy", "legacy"),
            ))
            adapter = app.adapter(
                service, session, request_id, runtime_config=config,
                allowed_operations=(
                    [] if readonly or repeated_command else (allowed_operations or [])
                ),
                can_read=can_read,
            )

            def save_result(operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
                delivery = memory.writer.prepare(
                    [capture["source_ref"], *progress["source_refs"]], "",
                    selected_records=[], redelivered_ranges=[],
                )
                try:
                    outcome = memory.maintain_delivery(
                        config, delivery, request_id=operation_id, date=service.clock().isoformat(),
                        recipe=recipe, model_call=call, fit=fit, allowed=True,
                    )
                except Exception as error:
                    saved = service.store.get(
                        (*service.namespace, "edit_maintenance"),
                        json.dumps([session, operation_id], ensure_ascii=False),
                    )
                    if saved is not None and saved.value["phase"].endswith("_pending"):
                        raise UnknownModelRequest(str(error)) from error
                    raise
                return _maintenance_receipt(outcome)

            def reconcile(operation_id: str) -> dict[str, Any] | None:
                saved = service.store.get(
                    (*service.namespace, "edit_maintenance"),
                    json.dumps([session, operation_id], ensure_ascii=False),
                )
                if saved is None:
                    return None
                binding = saved.value["binding"]
                delivery = memory.writer.prepare(
                    list(dict.fromkeys(row["source_ref"] for row in binding["sources"])), "",
                    selected_records=[], source_ranges=[
                        {k: row[k] for k in ("source_ref", "start", "end")}
                        for row in binding["sources"]
                    ], redelivered_ranges=[],
                )
                outcome = memory.maintain_delivery(
                    config, delivery, request_id=operation_id, prior_request_id=operation_id,
                    date=saved.value["date"], recipe=recipe, model_call=call, allowed=True,
                    execute=False, selected_record_ids=binding.get("selected_record_ids"),
                )
                if outcome["status"] != "completed":
                    return None
                return _maintenance_receipt(outcome)

            def feedback(operation_id: str, progress: dict[str, Any]) -> dict[str, Any]:
                destination = bank_root / f"{identity}-feedback-{attempt}.json"
                write_json(destination, {"operation_id": operation_id, "result": progress})
                return {"ok": True, "destination": str(destination),
                        "receipt_kind": "local_output_file", "host_seen": False}

            result = resume_request(
                app, adapter, resume_request_id or request_id, requirements=requirements,
                current={"readonly": readonly or repeated_command, "allow_memory": allow_memory,
                         "allow_feedback": allow_feedback,
                         "new_semantic_attempt": (
                             new_attempt_id is not None and not repeated_command
                         )},
                save_result=save_result, reconcile_memory=reconcile, feedback=feedback,
            )
            if can_read:
                result["application_snapshot"] = app.world.snapshot()
        result.update(usage=trace.usage, budget_after=budget.state,
                      repeated_command_observation_only=repeated_command and operation == "resume")
        write_json(bank_root / f"{identity}-memory-operation-attempt-{attempt}.json", result)
        first_result = bank_root / f"{identity}-memory-operation-result.json"
        if not first_result.exists():
            write_json(first_result, result)
        return result


def _maintenance_receipt(outcome: dict[str, Any]) -> dict[str, Any]:
    """A finished batch is a save receipt only when actual semantic commits exist."""
    if outcome.get("outcome") == "semantic_outcome_unconfirmed":
        raise UnknownSemanticCommit("Maintenance proposal outcome is unconfirmed")
    if outcome["phase"].endswith("_pending"):
        raise UnknownModelRequest("Maintenance model response is unconfirmed")
    committed = outcome["status"] == "completed" and outcome["semantic_write_performed"]
    return {"ok": committed, "status": "committed" if committed else "failed",
            "effect": "memory_only" if committed else "none", "maintenance": outcome}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bank", default="personal")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--text", required=True, help="Actual current operator/user request")
    parser.add_argument("--episode-id", action="append")
    parser.add_argument("--record-id", action="append")
    parser.add_argument("--prior-episode-id", action="append")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--prior-request-id")
    parser.add_argument("--new-attempt-id")
    parser.add_argument("--readonly", action="store_true")
    parser.add_argument("--operation", choices=("consolidate", "resume"), default="consolidate")
    parser.add_argument("--workflow", choices=("reservation", "document"), default="reservation")
    parser.add_argument("--resume-request-id", help="Original complete-request identity")
    parser.add_argument("--requirements", type=Path, help="Trusted current request plan, not gold")
    parser.add_argument("--allow-operation", action="append", default=[])
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-feedback", action="store_true")
    parser.add_argument("--no-read", action="store_true")
    args = parser.parse_args()
    result = run(
        args.root, bank=args.bank, owner=args.owner, session=args.session,
        request_id=args.request_id, text=args.text, episode_ids=args.episode_id,
        record_ids=args.record_id, prior_episode_ids=args.prior_episode_id, limit=args.limit,
        prior_request_id=args.prior_request_id, new_attempt_id=args.new_attempt_id,
        readonly=args.readonly, operation=args.operation, workflow=args.workflow,
        resume_request_id=args.resume_request_id,
        requirements=read_json(args.requirements) if args.requirements else None,
        allowed_operations=args.allow_operation, allow_memory=not args.no_save,
        allow_feedback=not args.no_feedback, can_read=not args.no_read,
    )
    print(json.dumps(result, ensure_ascii=False))
