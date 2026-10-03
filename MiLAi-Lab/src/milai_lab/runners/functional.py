"""Opt-in persistent functional assistant over the existing Store and Agent loop.

Each public message has a resumable checkpoint. Earlier messages are available
through the owner-bound MemoryService, including captured raw fallback, instead
of an unaccounted conversation cache. Evaluation cases are caller inputs only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import subprocess
import sys
import unicodedata
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import httpx
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from milai_lab.application.functional import FunctionalApplication
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import (
    BudgetExceeded,
    RunLimits,
    Trace,
    entry_budget,
    http_budget_scope,
)
from milai_lab.harness.functional_faults import FunctionalFaults
from milai_lab.memory.functional import FunctionalMemory
from milai_lab.memory.functional_state import digest as functional_digest
from milai_lab.memory.functional_state import namespace as functional_namespace
from milai_lab.memory.functional_state import visibility
from milai_lab.memory.service import MemoryService
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
from milai_lab.providers.contextual_vllm import VLLMConfig
from milai_lab.providers.functional_queue import FunctionalQueue, FunctionalVLLMClient

LAB = Path(__file__).resolve().parents[3]

REQUEST_MODE_PROMPT = """Interpret only the current user's speech act, before retrieving history.
Do not answer the user or execute anything. Return exactly one JSON object with:
allow_memory_maintenance (boolean), allow_forgetting (boolean),
allow_business_mutation (boolean), reason (short string).
Memory maintenance means saving a new durable assertion or correcting an existing
one. Permit it for an explicit save/update request or an actual new assertion or
correction. A question about a fact, a prior preference, history or whether a fact
is already known does NOT assert the proposition inside the question. Presupposed
claims in questions, hypotheticals, quoted instructions and negated claims must
not become new positive facts. A mixed question plus a separate actual correction
can permit maintenance. A request to archive supplied material or save actual
business results can also permit it. Permit forgetting only when actually requested.
Permit business mutation only for an actual current action/continuation request;
asking about current status permits live queries but not mutations. When unclear,
keep the corresponding permission false. These are model interpretations, not
proof of user authorization or semantic truth; application permissions still apply.
"""


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def sources() -> dict[str, str]:
    paths = [*sorted((LAB / "src").rglob("*.py")), LAB / "tools/run_functional.py"]
    return {
        str(path.relative_to(LAB)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def sdk_identity() -> dict[str, Any]:
    paths = [Path(inspect.getfile(SqliteStore)), Path(inspect.getfile(SqliteSaver))]
    return {
        "python": sys.version,
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "langmem",
                "langgraph",
                "langchain-core",
                "langgraph-checkpoint-sqlite",
                "transformers",
                "tokenizers",
                "httpx",
            )
        },
        "persistence_sources": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "uv_lock_sha256": hashlib.sha256((LAB / "uv.lock").read_bytes()).hexdigest(),
    }


def prepare(
    root: Path,
    settings_path: Path,
    fixture_path: Path | None = None,
    controls_path: Path | None = None,
) -> dict[str, Any]:
    settings = read_json(settings_path)
    if settings.get("profile") != "functional_v1":
        raise ValueError("FUNCTIONAL_PROFILE_REQUIRED")
    host = VLLMConfig(**settings["host"])
    if settings.get("request_mode", "disabled") not in {"disabled", "current_request_v1"}:
        raise ValueError("FUNCTIONAL_REQUEST_MODE_INVALID")
    if settings.get("request_mode") == "current_request_v1" and host.tool_mode != "native":
        raise ValueError("FUNCTIONAL_REQUEST_MODE_NATIVE_REQUIRED")
    if any(
        type(settings.get(key)) is not int or settings[key] <= 0
        for key in (
            "max_calls_per_message",
            "ordinary_material_tokens",
            "additional_reads",
        )
    ):
        raise ValueError("FUNCTIONAL_CAPACITY_POLICY_INVALID")
    if (
        settings.get("format_reproposals") not in {0, 1}
        or type(settings.get("format_reproposals")) is not int
        or host.max_calls != settings["max_calls_per_message"]
        or host.max_tokens != settings["capacity"]["output_tokens"]
    ):
        raise ValueError("FUNCTIONAL_CAPACITY_POLICY_INCONSISTENT")
    FunctionalQueue(root / "queue-admission.json", **settings["queue_limits"])
    # This validates pinned local identity without any model HTTP.
    capacity = HostCapacity(settings["capacity"])
    ledger = read_json(Path(settings["budget_path"]))
    config_sha = _hash(settings)
    fixture = read_json(fixture_path) if fixture_path else None
    controls = read_json(controls_path) if controls_path else None
    frozen = {
        "schema": "functional_input_freeze_v1",
        "config": settings,
        "config_sha256": config_sha,
        "source_sha256": sources(),
        "sdk_identity": sdk_identity(),
        "fixture": fixture,
        "evaluator_controls": controls,
        "evaluator_controls_sha256": _hash(controls),
        "fixture_sha256": _hash(fixture),
        "fixture_file_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if fixture_path
        else None,
        "capacity_identity": capacity.identity,
        "budget_before": ledger,
        "run_id": root.resolve().name,
        "backend": "public_sdk_sqlite",
        "formation": "host_tool_commit_before_final",
        "format_reproposals": settings["format_reproposals"],
        "ordinary_material_tokens": settings["ordinary_material_tokens"],
        "additional_reads": settings["additional_reads"],
        "queue_limits": settings["queue_limits"],
        "semantic_correctness": "requires_separate_evaluation",
    }
    root.mkdir(parents=True, exist_ok=True)
    target = root / "input-freeze.json"
    if target.exists():
        existing = read_json(target)
        for name in (
            "config_sha256",
            "source_sha256",
            "fixture_sha256",
            "evaluator_controls_sha256",
            "sdk_identity",
        ):
            if existing[name] != frozen[name]:
                raise ValueError("FUNCTIONAL_EXISTING_FREEZE_CHANGED:" + name)
        return cast(dict[str, Any], existing)
    write_json(target, frozen)
    return frozen


def frozen(root: Path) -> dict[str, Any]:
    value = read_json(root / "input-freeze.json")
    if value["source_sha256"] != sources() or value["config_sha256"] != _hash(value["config"]):
        raise ValueError("FUNCTIONAL_SOURCE_OR_CONFIG_CHANGED_AFTER_FREEZE")
    if value["fixture_sha256"] != _hash(value["fixture"]):
        raise ValueError("FUNCTIONAL_FIXTURE_CHANGED_AFTER_FREEZE")
    if value["evaluator_controls_sha256"] != _hash(value["evaluator_controls"]):
        raise ValueError("FUNCTIONAL_EVALUATOR_CONTROLS_CHANGED_AFTER_FREEZE")
    if value["sdk_identity"] != sdk_identity():
        raise ValueError("FUNCTIONAL_SDK_CHANGED_AFTER_FREEZE")
    return cast(dict[str, Any], value)


def _status(error: Exception) -> tuple[str, str]:
    text = str(error).upper()
    if isinstance(error, IncompleteChatResponse):
        return "FAILED", "provider_protocol"
    if isinstance(error, BudgetExceeded) or "GENERATION_CAPACITY_EXCEEDED" in text:
        return "BUDGET_EXHAUSTED", "budget"
    if isinstance(error, httpx.HTTPError):
        return "PROVIDER_ERROR", "provider"
    if isinstance(error, CapacityExceeded):
        return "FAILED", "request_capacity"
    if "UNKNOWN" in text or isinstance(error, OSError):
        return "UNKNOWN", "storage_or_business_unknown"
    return "FAILED", "input_or_runtime"


def final_delivery(content: Any) -> dict[str, Any]:
    """Minimal delivery check, not a truth, relevance or task-completion judge."""
    if not isinstance(content, str):
        reason = "no_text_content"
    elif not content.strip():
        reason = "empty_content"
    elif not any(c.isalnum() or unicodedata.category(c) == "So" for c in content):
        reason = "no_answer_text"
    else:
        return {"status": "available", "structural_check": "text_present",
                "semantic_quality": "unchecked"}
    return {"status": "unavailable", "reason": reason, "semantic_quality": "unchecked"}


def request_mode(
    model: LangMemRecipeChatModel, path: Path, binding: dict[str, Any],
    content: str, format_reproposals: int, trace: Trace,
) -> dict[str, Any]:
    """Persist one focused model interpretation; catalog enforcement is deterministic.

    This call sees only the current user input. It shares the actual provider,
    ledger and durable generation quota, and is never a semantic correctness oracle.
    """
    flags = {"allow_memory_maintenance", "allow_forgetting", "allow_business_mutation"}

    def valid(value: Any) -> bool:
        return (isinstance(value, dict) and set(value) == flags | {"reason"}
                and all(type(value[key]) is bool for key in flags)
                and isinstance(value["reason"], str) and bool(value["reason"].strip()))

    state: dict[str, Any] = (read_json(path) if path.exists()
                             else {"binding": binding, "attempts": 0})
    if state["binding"] != binding:
        raise ValueError("FUNCTIONAL_REQUEST_MODE_BINDING_CHANGED")
    if "decision" in state:
        if not valid(state["decision"]) or state.get("decision_sha256") != _hash(state["decision"]):
            raise ValueError("FUNCTIONAL_REQUEST_MODE_DECISION_CHANGED")
    else:
        if state["attempts"] >= 1 + format_reproposals:
            raise ValueError("FUNCTIONAL_REQUEST_MODE_REPROPOSAL_EXHAUSTED")
        state["attempts"] += 1
        write_json(path, state)  # Reserve before dispatch; failures do not refund a call.
        response = model.invoke([
            SystemMessage(content=REQUEST_MODE_PROMPT), HumanMessage(content=content),
        ], tools=[], tool_choice="none")
        try:
            decision = json.loads(response.content) if isinstance(response.content, str) else None
        except ValueError as error:
            raise IncompleteChatResponse("FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID") from error
        if not valid(decision) or not isinstance(response, AIMessage) or response.tool_calls:
            raise IncompleteChatResponse("FUNCTIONAL_REQUEST_MODE_SCHEMA_INVALID")
        state.update(decision=decision, decision_sha256=_hash(decision))
        write_json(path, state)
    summary = {**{key: state["decision"][key] for key in sorted(flags)},
               "interpretation": "same_host_model_current_request_only",
               "semantic_correctness": "unchecked",
               "format_reproposals_used": max(0, state["attempts"] - 1)}
    trace({"event": "functional_request_mode", **summary,
           "decision_sha256": state["decision_sha256"]})
    return summary


def operation_status(
    output: dict[str, Any], *, thread_id: str, execution_started: bool,
) -> dict[str, Any]:
    """Report durable receipts for this message independently of final prose.

    The application snapshot is produced by the actual open facade, never model
    text or memory retrieval. Counts describe listed operations only: saving A
    cannot certify that an unattempted B or the whole user request was satisfied.
    """
    capture = output.get("capture", {})
    raw = {"status": "stored" if capture.get("ok") else
           "unknown" if output.get("capture_attempted") else "not_attempted"}
    if capture.get("ok"):
        raw["source_ref"] = capture["source_ref"]
    snapshot = output.get("world")
    if not isinstance(snapshot, dict):
        status = "unknown" if execution_started else "not_executed"
        return {"schema": "functional_operation_status_v1", "raw_event": raw,
                "semantic_memory": {"status": status, "operations": []},
                "business": {"status": status, "operations": [], "observations": []},
                "request_completion": "unchecked", "receipt_snapshot_available": False}
    memory: list[dict[str, Any]] = []
    visibility_effects: list[dict[str, Any]] = []
    expected = {"owner": output["owner"], "thread_id": thread_id,
                "session": output["session"], "turn_id": output["message_id"]}
    for row in snapshot.get("receipt_progress", {}).values():
        identity = row.get("identity", {})
        if any(identity.get(k) != v for k, v in expected.items()):
            continue
        name = identity.get("name")
        if name not in {"save_memory", "update_memory", "forget_memory"}:
            continue
        receipt = row.get("semantic_maintenance")
        if receipt is None and row.get("memory_response"):
            try:
                receipt = json.loads(row["memory_response"]["content"])
            except (ValueError, TypeError, KeyError):
                receipt = None
        receipt = receipt if isinstance(receipt, dict) else {}
        status = "unknown"
        if receipt.get("ok") is True:
            if (name == "forget_memory" and receipt.get("status") == "visibility_revoked"
                    and receipt.get("effect") == "visibility_only"):
                status = "visibility_revoked"
            elif (name != "forget_memory" and isinstance(receipt.get("id"), str)
                  and type(receipt.get("revision")) is int):
                if receipt.get("status") == "committed" and receipt.get("effect") == "memory_only":
                    status = "committed"
                elif (receipt.get("status") == "no_change"
                      and receipt.get("effect") in {"none", "memory_only"}):
                    status = "no_change"
            if (status == "no_change" and receipt.get("effect") == "memory_only"
                    and receipt.get("replayed") is True
                    and receipt.get("original_status") == "committed"):
                status = "committed"
        elif receipt.get("effect") == "none":
            status = "not_committed"
        operation = {"tool": name, "receipt_ref": identity["call_id"], "status": status,
                     **{k: receipt[k] for k in ("id", "revision", "effect", "replayed",
                                                "original_status", "phase", "error_type",
                                                "duplicate_request", "existing_record",
                                                "duplicate_of_operation")
                        if k in receipt}}
        (visibility_effects if name == "forget_memory" else memory).append(operation)
    semantic_states = {row["status"] for row in memory}
    semantic = ("unknown" if "unknown" in semantic_states else
                "partial" if "committed" in semantic_states and "not_committed" in semantic_states
                else "committed" if "committed" in semantic_states else
                "not_committed" if "not_committed" in semantic_states or not semantic_states
                else "no_change")
    business: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    journal = snapshot.get("journal", {})
    for key, row in journal.items():
        if (not isinstance(row, dict) or row.get("thread_id") != thread_id
                or row.get("owner") != output["owner"]
                or row.get("public_turn", {}).get("session") != output["session"]
                or row.get("public_turn", {}).get("turn_id") != output["message_id"]):
            continue
        query = row["name"] in {"get_reservation", "get_document_status"}
        effect = row.get("effect", "unknown")
        operation = {"tool": row["name"], "receipt_ref": row["call_id"],
                     "journal_ref": key, "effect": effect,
                     "execution_receipt_status": row.get("status", "unknown"),
                     "executed": row.get("executed", False),
                     "effect_basis": "original_receipt" if row.get("status") == "complete"
                     else "public_read_contract" if query else "unconfirmed"}
        recoveries = journal.get("_native_recoveries", {}).get(key, {})
        if recoveries:
            recovery = next(reversed(recoveries.values()))
            operation.update(observed_effect=recovery["effect"],
                             observation_receipt_ref=recovery["query_journal_key"],
                             observation_basis=recovery["effect_source"])
        (observations if query else business).append(operation)
    effects = {row.get("observed_effect", row["effect"]) for row in business}
    business_status = ("unknown" if "unknown" in effects else
                       "partial" if "partial" in effects or {"confirmed", "none"} <= effects
                       else "completed" if "confirmed" in effects else
                       "no_effect" if effects else "not_executed")
    return {"schema": "functional_operation_status_v1", "raw_event": raw,
            "semantic_memory": {"status": semantic, "operations": memory},
            "visibility": {"operations": visibility_effects},
            "business": {"status": business_status, "operations": business,
                         "observations": observations},
            "receipt_snapshot_available": True, "request_completion": "unchecked",
            "status_scope": "listed_current_message_operations_only",
            "reads_are_new_writes": False,
            "successful_operation_proves_unattempted_request_parts": False}


def format_failures(messages: list[Any]) -> list[str]:
    """Count actual structural rejection receipts, never infer semantic correctness."""
    rejected = []
    for row in messages:
        if not isinstance(row, ToolMessage):
            continue
        try:
            body = json.loads(str(row.content))
        except ValueError:
            continue
        if isinstance(body, dict) and (
            body.get("origin") in {"jsonschema", "pydantic"}
            or body.get("error_category") == "schema"
        ):
            rejected.append(row.tool_call_id)
    return list(dict.fromkeys(rejected))


def memory_effects(messages: list[Any]) -> dict[str, Any]:
    """Summarize paired current-message receipts, without reading more memory.

    This is operation evidence, not a judgment about user intent, field support
    or the truth of the Host's free-text answer. Forget projection runs first.
    """
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), len(messages))
    names = {"save_memory", "update_memory", "forget_memory"}
    calls: dict[str, str] = {}
    receipts = []
    confirmed = []
    for row in messages[start:]:
        if isinstance(row, AIMessage):
            for call in row.tool_calls:
                ref = call.get("id")
                if call["name"] in names and isinstance(ref, str) and ref:
                    calls[ref] = call["name"]
        elif isinstance(row, ToolMessage):
            name = calls.pop(row.tool_call_id, None)
            if name is None or row.name != name:
                continue
            try:
                value = json.loads(str(row.content))
            except ValueError:
                value = None
            if not isinstance(value, dict):
                value = {"ok": False, "status": "receipt_unreadable", "effect": "unconfirmed"}
            receipt = {key: value[key] for key in (
                "ok", "status", "effect", "formation_status", "id", "revision",
                "replayed", "original_status", "content_verification", "duplicate_request",
                "existing_record", "duplicate_of_operation",
            ) if key in value}
            receipts.append({"tool": name, "receipt_ref": row.tool_call_id,
                             "transport_status": row.status, **receipt})
            if (row.status == "success" and value.get("ok") is True
                    and name in {"save_memory", "update_memory"}
                    and value.get("effect") == "memory_only"
                    and (value.get("status") == "committed"
                         or (value.get("status") == "no_change"
                             and value.get("replayed") is True
                             and value.get("original_status") == "committed"))):
                confirmed.append(row.tool_call_id)
    return {
        "schema": "functional_memory_effects_v1",
        "scope": "visible_checkpoint_of_current_public_message",
        "mutation_receipts": receipts,
        "pending_mutation_call_refs": list(calls),
        "confirmed_semantic_commit_receipt_refs": confirmed,
        "confirmed_semantic_commit_count": len(confirmed),
        "raw_capture_is_semantic_save": False,
        "reads_perform_semantic_writes": False,
        "semantic_completion": "unchecked",
        "interpretation": "Only actual mutation receipts confirm write effects. Raw fragments "
        "and read-only search hits do not confirm semantic saving. An existing semantic record "
        "may satisfy a request without a new write; assess its actual delivered content.",
    }


def seed_sources(
    service: MemoryService, rows: list[dict[str, Any]], path: Path
) -> list[dict[str, Any]]:
    """Capture supplied events once; a later import cannot resurrect forgotten text."""
    identity = _hash(rows)
    if path.exists():
        saved = read_json(path)
        if saved["input_sha256"] != identity:
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_SET_CHANGED")
        return cast(list[dict[str, Any]], saved["receipts"])
    receipts = []
    for row in rows:
        if row.get("object_ref") is not None:
            raise ValueError("FUNCTIONAL_IMPORTED_OBJECT_AUTHORITY_FORBIDDEN")
        if row["role"] == "user":
            capture = service.capture_user(row["session_id"], row["event_key"], row["content"])
        elif row["role"] == "assistant":
            capture = service.capture_assistant(row["session_id"], row["event_key"], row["content"])
        elif row["role"] == "tool":
            capture = service.capture_tool(
                row["session_id"], row["event_key"], row["origin"], row["content"], None
            )
        else:
            raise ValueError("FUNCTIONAL_IMPORTED_ROLE_INVALID")
        if not capture.get("ok"):
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_UNAVAILABLE")
        actual = service.source(capture["source_ref"])
        if actual is None or (
            row.get("content_sha256") and actual["content_sha256"] != row["content_sha256"]
        ):
            raise ValueError("FUNCTIONAL_IMPORTED_SOURCE_HASH_CHANGED")
        receipts.append(
            {
                "original_event_id": row.get("original_event_id"),
                "original_observed_at": row.get("observed_at"),
                "receipt": capture,
            }
        )
    write_json(path, {"input_sha256": identity, "receipts": receipts})
    return receipts


def _replay_evidence_ids(value: Any) -> set[str]:
    """Inspect archived structured evidence; do not infer semantic copies from prose."""
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_ref", "event_id", "record_id", "id"} and isinstance(child, str):
                refs.add(child)
            elif key == "source_refs" and isinstance(child, list):
                refs.update(ref for ref in child if isinstance(ref, str) and ref.startswith("src-"))
            refs.update(_replay_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_replay_evidence_ids(child))
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except ValueError:
            pass
        else:
            refs.update(_replay_evidence_ids(decoded))
    return refs


def _visibility_replay(
    service: MemoryService, archived: dict[str, Any], *, session: str, message_id: str,
) -> dict[str, Any] | None:
    """An archived receipt is not permission to redisclose now-revoked bodies.

    A user input is not derived from prefetch. Its archived response/cache can
    nevertheless contain the material actually delivered during that input.
    """
    visible = visibility(service)
    hidden = set(visible["sources"])
    hidden_records = set(visible["records"])
    if not hidden and not hidden_records:
        return None
    public_ref = service.event_id(session, message_id, "user")
    dependencies = _replay_evidence_ids(archived) | {
        public_ref, service.event_id(session, message_id + ":final", "assistant")}
    exposed = service.store.get(functional_namespace(service), "exposure:" + public_ref)
    if exposed is not None:
        dependencies.update(exposed.value["source_refs"])
    revoked = sorted(dependencies.intersection(hidden))
    revoked_records = sorted(dependencies.intersection(hidden_records))
    if not revoked and not revoked_records:
        return None
    return {
        "status": "VISIBILITY_REVOKED", "original_status": archived.get("status"),
        "replayed": True, "forget_epoch": service.forget_epoch,
        "revoked_source_refs": revoked, "revoked_ids": revoked_records,
        "final_answer": None, "messages": [],
        "records": [], "sources": [], "historical_artifact_retained": True,
        "visibility_scope": "archived_response_dependencies_not_independent_user_facts",
        "reason": "Archived response contains now-revoked source dependencies.",
    }


class _VisibilityReplayRevoked(Exception):
    def __init__(self, receipt: dict[str, Any]) -> None:
        super().__init__("FUNCTIONAL_REPLAY_VISIBILITY_REVOKED")
        self.receipt = receipt


def _verified_forget_continuation(
    service: MemoryService, app: FunctionalApplication, messages: list[Any],
    blocked: dict[str, Any], *, thread_id: str, session: str, message_id: str,
) -> bool:
    """Only an actual same-message forget receipt can authorize its recovery.

    The checkpoint call, durable wrapper progress and Store visibility operation
    must agree. Other messages' revocations cannot be excused by a hidden input.
    """
    generated = {row.id: row for row in messages if isinstance(row, AIMessage)}
    operations = visibility(service)["operations"]
    verified: set[str] = set()
    source_refs: set[str] = set()
    record_ids: set[str] = set()
    for progress in app.progress.snapshot().values():
        identity = progress["identity"]
        if (identity.get("thread_id") != thread_id
                or identity.get("session") != session or identity.get("turn_id") != message_id
                or identity.get("owner") != service.owner
                or identity.get("name") != "forget_memory"):
            continue
        row = generated.get(identity["generation_id"])
        if row is None or not any(
            call["id"] == identity["call_id"] and call["name"] == "forget_memory"
            and call["args"] == identity["args"] for call in row.tool_calls
        ):
            continue
        actual = operations.get(functional_digest([session, identity["call_id"]]))
        response = progress.get("delivery_response", progress.get("memory_response"))
        if actual is None or response is None:
            continue
        if response.get("tool_call_id") != identity["call_id"]:
            continue
        try:
            receipt = json.loads(response["content"])
        except (ValueError, TypeError, KeyError):
            continue
        # Replaying the same operation may add only its explicit replay marker.
        original = {key: value for key, value in receipt.items() if key != "replayed"}
        if (original != actual["receipt"] or not receipt.get("ok")
                or receipt.get("status") != "visibility_revoked"):
            continue
        verified.add(identity["call_id"])
        source_refs.update(receipt["revoked_source_refs"])
        record_ids.update(receipt["revoked_ids"])
    if not verified or not set(blocked["revoked_source_refs"]).issubset(source_refs):
        return False
    if not set(blocked["revoked_ids"]).issubset(record_ids):
        return False
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and last.tool_calls:
        # A crashed W3 batch must first restore only proven forget receipts;
        # do not execute unrelated stale arguments from the same generation.
        return all(call["id"] in verified for call in last.tool_calls)
    # A model-node continuation must already hold the actual receipt, which
    # context_hook projects before it admits another generation.
    return any(isinstance(row, ToolMessage) and row.name == "forget_memory"
               and row.tool_call_id in verified for row in messages)


def message(
    root: Path,
    *,
    bank: str,
    owner: str,
    session: str,
    message_id: str,
    content: str,
    workflow: str = "reservation",
    initial_world: dict[str, Any] | None = None,
    initial_sources: list[dict[str, Any]] | None = None,
    retrieval_candidates: list[dict[str, Any]] | None = None,
    evaluator_control: dict[str, Any] | None = None,
    message_index: int = 0,
    resume: bool = False,
) -> dict[str, Any]:
    freeze = frozen(root)
    workflow = {"reservation_v1": "reservation", "document_publication_v1": "document"}.get(
        workflow, workflow
    )
    if workflow not in {"reservation", "document"}:
        raise ValueError("FUNCTIONAL_WORKFLOW_INVALID")
    profile_state = root / "profile-state.json"
    if profile_state.exists() and read_json(profile_state).get("disabled"):
        raise ValueError("FUNCTIONAL_PROFILE_DISABLED")
    settings = freeze["config"]
    bank_root = root / "banks" / _hash([bank, owner])[:24]
    bank_root.mkdir(parents=True, exist_ok=True)
    public = {
        "owner": owner,
        "session": session,
        "message_id": message_id,
        "content": content,
        "workflow": workflow,
    }
    identity = _hash([session, message_id])
    result_path = bank_root / (identity + "-result.json")
    input_path = bank_root / (identity + "-input.json")
    if input_path.exists() and read_json(input_path) != public:
        raise ValueError("FUNCTIONAL_PUBLIC_MESSAGE_IDENTITY_CHANGED")
    namespace = ("functional", freeze["run_id"], bank, owner)
    if result_path.exists() and not resume:
        archived = cast(dict[str, Any], read_json(result_path))
        if not (bank_root / "memory.sqlite").exists():
            raise ValueError("FUNCTIONAL_REPLAY_VISIBILITY_STATE_MISSING")
        with SqliteStore.from_conn_string(str(bank_root / "memory.sqlite")) as replay_store:
            replay_service = MemoryService(
                replay_store, namespace, owner, bank_root / "memory.lock",
                functional_contract="functional_v1")
            blocked = _visibility_replay(
                replay_service, archived, session=session, message_id=message_id)
        return blocked if blocked is not None else archived
    write_json(input_path, public)
    attempt = len(list(bank_root.glob(identity + "-attempt-*.json")))
    trace = Trace(bank_root / f"{identity}-trace-{attempt}.jsonl", "functional_v1")
    output: dict[str, Any] = {
        **public,
        "bank": bank,
        "process_id": os.getpid(),
        "attempt": attempt,
        "status": "UNKNOWN",
        "capture_attempted": False,
    }
    execution_started = False
    scope = FoundationScope(freeze["run_id"], bank, owner, session + ":" + message_id)
    cfg: RunnableConfig = cast(RunnableConfig, scope.config())
    cfg["configurable"].update(
        v13_session=session,
        v13_turn_id=message_id,
        v13_support_config_sha256=freeze["config_sha256"],
    )
    with ExitStack() as stack:
        stack.enter_context(
            http_budget_scope(
                settings,
                RunLimits(**freeze["budget_before"]["limits"]),
                client_configs=[asdict(VLLMConfig(**settings["host"]))],
            )
        )
        budget = entry_budget(
            RunLimits(**freeze["budget_before"]["limits"]), Path(settings["budget_path"])
        )
        before = json.loads(json.dumps(budget.state))
        try:
            store = stack.enter_context(
                SqliteStore.from_conn_string(str(bank_root / "memory.sqlite"))
            )
            saver = stack.enter_context(
                SqliteSaver.from_conn_string(str(bank_root / "checkpoints.sqlite"))
            )
            service = MemoryService(
                store,
                namespace,
                owner,
                bank_root / "memory.lock",
                functional_contract="functional_v1",
                receipt_profile=(
                    "document_publication_v1"
                    if workflow in {"document", "document_publication_v1"}
                    else "reservation_v1"
                ),
                observer=trace,
            )
            seed_receipts = (
                seed_sources(service, initial_sources, bank_root / "source-imports.json")
                if initial_sources
                else []
            )
            if seed_receipts:
                output["source_import_receipts"] = seed_receipts
            output["capture_attempted"] = True
            capture = service.capture_user(session, message_id, content)
            output["capture"] = capture
            trace({"event": "functional_capture", "receipt": capture})
            if not capture.get("ok"):
                raise ValueError("FUNCTIONAL_SOURCE_CAPTURE_UNAVAILABLE:" + str(capture))
            service.bind_source_boundary(session, message_id, [capture["source_ref"]])
            capacity = HostCapacity(settings["capacity"])
            memory = FunctionalMemory(
                service,
                capacity.text_tokens,
                read_limit=settings["additional_reads"],
                material_limit=settings["ordinary_material_tokens"],
                retrieval_candidates=[
                    {
                        **row,
                        "source_ref": next(
                            receipt["receipt"]["source_ref"]
                            for receipt in seed_receipts
                            if receipt["original_event_id"] == row["source_ref"]
                        ),
                    }
                    for row in retrieval_candidates
                ]
                if retrieval_candidates is not None
                else None,
            )
            world_settings = {
                "initial_" + key if not key.startswith("initial_") else key: value
                for key, value in (initial_world or {}).items()
            }
            faults = FunctionalFaults(
                bank_root / "evaluator-control-state.json", evaluator_control or {}, message_index
            )
            app = stack.enter_context(
                FunctionalApplication.open(
                    bank_root / "applications" / workflow,
                    workflow,
                    owner,
                    response_hook=faults.after_native,
                    **world_settings,
                )
            )
            faults.before_message(app)
            client = FunctionalVLLMClient(
                VLLMConfig(**settings["host"]), emit=trace, budget=budget, capacity=capacity
            )
            stack.enter_context(client)
            client.queue = FunctionalQueue(
                root / "queue-admission.json", **settings["queue_limits"]
            )
            model = LangMemRecipeChatModel(
                client=client,
                capacity_path=bank_root / "message-admission.json",
                max_calls_per_message=settings["max_calls_per_message"],
                generation_admission_profile="durable_shared_v1",
                tool_schema_communication="shape_feedback_v1",
            )
            admission_path = bank_root / "message-admission.json"
            prior_admission = next(
                (
                    row
                    for row in (
                        read_json(admission_path).get("messages", {}).values()
                        if admission_path.exists()
                        else []
                    )
                    if row["identity"]["owner"] == owner
                    and row["identity"]["bank"] == list(namespace)
                    and row["identity"]["session"] == session
                    and row["identity"]["public_message_id"] == message_id
                ),
                None,
            )
            model.begin_public_message(
                message_id,
                admission_phase="resume" if prior_admission else "start",
                admission_scope={
                    "owner": owner,
                    "bank": list(namespace),
                    "session": session,
                    "request_ref": capture["source_ref"],
                    "request_sha256": _hash(public),
                    "config_sha256": freeze["config_sha256"],
                },
            )
            mode: dict[str, Any] | None = None
            mode_path = bank_root / f"{identity}-request-mode.json"
            if settings.get("request_mode", "disabled") == "current_request_v1":
                # Before any fresh interpretation HTTP, deny replay of a now
                # revoked input. An accepted cached mode makes no HTTP; the graph
                # then applies its existing precise forget-continuation checks.
                cached_mode = read_json(mode_path) if mode_path.exists() else {}
                if "decision" not in cached_mode:
                    blocked = _visibility_replay(
                        service, read_json(result_path) if result_path.exists() else {},
                        session=session, message_id=message_id)
                    if blocked is not None:
                        raise _VisibilityReplayRevoked(blocked)
                mode = request_mode(model, mode_path, {
                    "source_ref": capture["source_ref"], "public_sha256": _hash(public),
                    "config_sha256": freeze["config_sha256"],
                }, content, settings["format_reproposals"], trace)
                output["request_mode"] = mode
            selected_memory = tuple(tool for tool in memory.tools() if mode is None or (
                mode["allow_memory_maintenance"] if tool.name in {"save_memory", "update_memory"}
                else mode["allow_forgetting"] if tool.name == "forget_memory" else True))
            selected_business = tuple(tool for tool in app.tools if mode is None or
                                      mode["allow_business_mutation"] or tool.name in {
                                          "get_reservation", "get_document_status"})
            allowed_tools = {tool.name for tool in (*selected_memory, *selected_business)}
            mode_reproposals = mode["format_reproposals_used"] if mode else 0
            tool_catalog = [convert_to_openai_tool(tool)
                            for tool in (*selected_memory, *selected_business)]
            trace({"event": "functional_tool_catalog", "tools": tool_catalog})

            def context_hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
                messages = list(state["messages"])
                blocked = _visibility_replay(service, {
                    "status": "PENDING", "messages": [row.model_dump(mode="json")
                                                         for row in messages]},
                    session=session, message_id=message_id)
                if blocked is not None and not _verified_forget_continuation(
                    service, app, messages, blocked,
                    thread_id=cfg["configurable"]["thread_id"],
                    session=session, message_id=message_id,
                ):
                    raise _VisibilityReplayRevoked(blocked)
                material = memory.context(
                    session, message_id, freeze["config_sha256"], query=content
                )
                rejected = format_failures(messages)
                if len(rejected) + mode_reproposals > settings["format_reproposals"]:
                    trace({"event": "functional_format_budget_exhausted", "calls": rejected})
                    raise ValueError("FUNCTIONAL_FORMAT_REPROPOSAL_EXHAUSTED")
                # A successful forget invalidates previously delivered memory within
                # this public message too. Other public messages have distinct checkpoints.
                forgotten_at = None
                for index, row in enumerate(messages):
                    if isinstance(row, ToolMessage) and row.name == "forget_memory":
                        try:
                            receipt = json.loads(str(row.content))
                        except ValueError:
                            continue
                        if receipt.get("ok"):
                            forgotten_at = index
                if forgotten_at is not None:
                    forgotten = messages[forgotten_at]
                    # Keep only the matching forget call from a possible multi-call
                    # generation; unrelated arguments can contain revoked text.
                    matching = []
                    for generated in reversed(messages[:forgotten_at]):
                        if isinstance(generated, AIMessage):
                            calls = [
                                call
                                for call in generated.tool_calls
                                if call["id"] == forgotten.tool_call_id
                            ]
                            if calls:
                                matching = [
                                    AIMessage(content="", id=generated.id, tool_calls=calls)
                                ]
                                break
                    messages = [
                        HumanMessage(content=content, id=message_id),
                        *matching,
                        *messages[forgotten_at:],
                    ]
                trace({"event": "functional_material_delivery", "material": material})
                effects = memory_effects(messages)
                trace({"event": "functional_memory_effects", "effects": effects})
                return {
                    "llm_input_messages": [
                        SystemMessage(
                            content=settings["system_prompt"]
                            + ("\nCurrent request interpretation and enforced tool limits: "
                               + json.dumps(mode, ensure_ascii=False) if mode else "")
                            + "\n"
                            + json.dumps(effects, ensure_ascii=False)
                            + "\n"
                            + json.dumps(material, ensure_ascii=False)
                        ),
                        *messages,
                    ]
                }

            call_wrapper = app.call_wrapper(
                service, session, message_id, trace, cfg, boundary_hook=faults.boundary
            )

            def dispatch(request: Any, execute: Any) -> Any:
                if request.tool_call["name"] not in allowed_tools:
                    return ToolMessage(name=request.tool_call["name"],
                                       tool_call_id=request.tool_call["id"], status="error",
                                       content=json.dumps({"ok": False,
                                           "status": "request_mode_rejected", "effect": "none"}))
                def native(current: Any) -> Any:
                    faults.before_native(current)
                    return execute(current)

                return call_wrapper(request, native)

            agent = build_agent(
                model,
                store,
                saver,
                selected_business,
                memory_tools=selected_memory,
                system_prompt=settings["system_prompt"],
                benchmark_view_hook=context_hook,
                tool_schema_communication="shape_feedback_v1",
                business_call_wrapper=dispatch,
            )
            snapshot = agent.get_state(cfg)
            prior = snapshot.values.get("messages", []) if snapshot.values else []
            if prior:
                blocked = _visibility_replay(service, {
                    "status": "PENDING" if snapshot.next else "COMPLETED", "messages": [
                        row.model_dump(mode="json") for row in prior]},
                    session=session, message_id=message_id)
                if blocked is not None and (not snapshot.next or not _verified_forget_continuation(
                    service, app, prior, blocked,
                    thread_id=cfg["configurable"]["thread_id"],
                    session=session, message_id=message_id,
                )):
                    trace({"event": "functional_checkpoint_replay_visibility_revoked", **blocked})
                    # Preserve old attempts/checkpoints; deny before any recovery
                    # tool dispatch or new model request can receive their bodies.
                    return blocked
            execution_started = True
            app.recover_pending(agent, scope, call_wrapper)
            snapshot = agent.get_state(cfg)
            prior = snapshot.values.get("messages", []) if snapshot.values else []
            recovery_path = bank_root / f"{identity}-answer-recovery.json"
            previous_result = read_json(result_path) if result_path.exists() else {}
            invalid_provider_content = (
                previous_result.get("error") in {
                    "VLLM_CHAT_INVALID_CONTENT", "VLLM_CHAT_TRUNCATED"}
                and previous_result.get("error_category") == "provider_protocol"
            )
            pending_answer_repair = bool(snapshot.next) and (
                invalid_provider_content or recovery_path.exists())
            if prior and (not snapshot.next or (resume and pending_answer_repair)):
                last = prior[-1]
                bad_checkpoint_text = (isinstance(last, AIMessage) and not last.tool_calls
                                       and final_delivery(last.content)["status"] == "unavailable")
                if resume and (bad_checkpoint_text or pending_answer_repair):
                    recovery = (read_json(recovery_path) if recovery_path.exists()
                                else {"attempts": 0})
                    if (recovery["attempts"] + len(format_failures(prior)) + mode_reproposals
                            >= settings["format_reproposals"]):
                        raise ValueError("FUNCTIONAL_FINAL_ANSWER_REPAIR_BUDGET_EXHAUSTED")
                    # Explicit resume can repair delivery once. Reserve it before
                    # dispatch; the shared generation/queue budgets apply too.
                    # No tool catalog or dispatcher is available in this path.
                    recovery.update(attempts=recovery["attempts"] + 1, status="attempted",
                                    tools_available=False, prior_message_id=last.id)
                    write_json(recovery_path, recovery)
                    output["answer_recovery"] = recovery
                    repair_history = prior[:-1] if bad_checkpoint_text else prior
                    repair_input = context_hook({"messages": repair_history}, cfg)[
                        "llm_input_messages"]
                    repair_input.insert(1, SystemMessage(content=(
                        "The preceding final response was unusable. Report the already observed "
                        "operation results and any unfinished request parts. Tools are unavailable "
                        "during this answer-only recovery; no new operations will be executed."
                    )))
                    repaired = model.invoke(repair_input, tools=[], tool_choice="none")
                    if not isinstance(repaired, AIMessage) or repaired.tool_calls:
                        raise ValueError("FUNCTIONAL_FINAL_ANSWER_REPAIR_MUST_BE_TEXT")
                    if bad_checkpoint_text and not last.id:
                        raise ValueError("FUNCTIONAL_FINAL_ANSWER_CHECKPOINT_ID_REQUIRED")
                    replacement = ([RemoveMessage(id=last.id), repaired]
                                   if bad_checkpoint_text else [repaired])
                    agent.update_state(cfg, {"messages": replacement}, as_node="agent")
                    messages = agent.get_state(cfg).values["messages"]
                    recovery.update(status="response_received", delivery=final_delivery(
                        repaired.content))
                    write_json(recovery_path, recovery)
                    trace({"event": "functional_answer_only_recovery", **recovery})
                else:
                    messages = prior
            else:
                result = agent.invoke(
                    None if prior else {"messages": [HumanMessage(content=content, id=message_id)]},
                    cfg,
                    durability="sync",
                )
                messages = result["messages"]
            output.update(
                status="COMPLETED",
                messages=[row.model_dump(mode="json") for row in messages],
                final_answer=next(
                    (
                        row.content
                        for row in reversed(messages)
                        if isinstance(row, AIMessage) and not row.tool_calls
                    ),
                    None,
                ),
                generation_calls=model.calls_in_message,
            )
            output["final_delivery"] = final_delivery(output["final_answer"])
            if output["final_delivery"]["status"] != "available":
                output.update(status="FAILED", error_category="final_delivery",
                              error_type="FinalAnswerUnavailable",
                              error=output["final_delivery"]["reason"])
            checkpointed_calls = {
                row.tool_call_id for row in messages if isinstance(row, ToolMessage)
            }
            for key, progress in app.progress.snapshot().items():
                if (
                    progress["identity"]["thread_id"] == cfg["configurable"]["thread_id"]
                    and progress["identity"]["call_id"] in checkpointed_calls
                    and "delivery_response" in progress
                ):
                    app.progress.acknowledge_delivery(key)
            mutation_receipts = []
            for position, row in enumerate(messages):
                if isinstance(row, ToolMessage) and row.name in {
                    "save_memory",
                    "update_memory",
                    "forget_memory",
                }:
                    mutation_receipts.append(
                        {
                            "position": position,
                            "tool": row.name,
                            "tool_call_id": row.tool_call_id,
                            "receipt": row.content,
                        }
                    )
            # Capture assistant speech as its real role, never as new user evidence.
            if output["final_delivery"]["status"] == "available":
                service.capture_assistant(session, message_id + ":final", output["final_answer"])
            output.update(
                records=service.records(),
                sources=service.sources(),
                world=app.snapshot(),
                memory_mutation_receipts=mutation_receipts,
                formation_stage="host_tools_before_final",
                snapshot_before_close=True,
            )
        except _VisibilityReplayRevoked as revoked:
            trace({"event": "functional_pre_model_visibility_revoked", **revoked.receipt})
            return revoked.receipt
        except Exception as error:
            status, category = _status(error)
            output.update(
                status=status,
                error_category=category,
                error_type=type(error).__name__,
                error=str(error),
            )
            trace(
                {
                    "event": "functional_failure",
                    "status": status,
                    "category": category,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            if "service" in locals():
                try:
                    output.update(
                        records=service.records(),
                        sources=service.sources(),
                        snapshot_before_close=True,
                    )
                except Exception as snapshot_error:
                    output["snapshot_error"] = (
                        type(snapshot_error).__name__ + ":" + str(snapshot_error)
                    )
            if "app" in locals():
                try:
                    output["world"] = app.snapshot()
                except Exception as snapshot_error:
                    output["application_snapshot_error"] = (
                        type(snapshot_error).__name__ + ":" + str(snapshot_error)
                    )
            if "agent" in locals():
                try:
                    checkpoint = agent.get_state(cfg)
                    output["messages"] = [
                        row.model_dump(mode="json") for row in checkpoint.values.get("messages", [])
                    ]
                    output["pending_nodes"] = list(checkpoint.next)
                except Exception as checkpoint_error:
                    output["checkpoint_snapshot_error"] = (
                        type(checkpoint_error).__name__ + ":" + str(checkpoint_error)
                    )
            if "model" in locals():
                output["generation_calls"] = model.calls_in_message
        output.setdefault("final_delivery", final_delivery(output.get("final_answer")))
        output["operation_status"] = operation_status(
            output, thread_id=cfg["configurable"]["thread_id"],
            execution_started=execution_started,
        )
        if "faults" in locals() and evaluator_control:
            output["evaluator_control_state"] = faults.state
        output.update(
            usage=trace.usage,
            budget_before=before,
            budget_after=json.loads(json.dumps(budget.state)),
        )
        write_json(bank_root / f"{identity}-attempt-{attempt}.json", output)
        write_json(result_path, output)
    return output


def step(root: Path, case_id: str, index: int, *, resume: bool = False) -> dict[str, Any]:
    freeze = frozen(root)
    case = next(row for row in freeze["fixture"]["cases"] if row["case_id"] == case_id)
    public = case["messages"][index]
    return message(
        root,
        bank=case_id,
        owner=case["owner"],
        session=public["session_id"],
        message_id=public["message_id"],
        content=public["content"],
        workflow=case.get("workflow", "reservation"),
        initial_world=case.get("initial_world"),
        initial_sources=case.get("initial_sources"),
        retrieval_candidates=case.get("retrieval_candidates"),
        evaluator_control=next(
            (
                row
                for row in (freeze.get("evaluator_controls") or {}).get("cases", [])
                if row["case_id"] == case_id
            ),
            None,
        ),
        message_index=index,
        resume=resume,
    )


def run(root: Path) -> list[dict[str, Any]]:
    results = []
    queue_blocked = False
    for case in frozen(root)["fixture"]["cases"]:
        blocked = False
        for index, _ in enumerate(case["messages"]):
            if blocked or queue_blocked:
                results.append(
                    {
                        "case_id": case["case_id"],
                        "message_index": index,
                        "status": "NOT_RUN",
                        "reason": "queue_budget_exhausted"
                        if queue_blocked
                        else "prior_message_incomplete",
                    }
                )
                continue
            child = subprocess.run(  # noqa: S603 -- fixed local executable and argv, no shell
                [
                    sys.executable,
                    str(LAB / "tools/run_functional.py"),
                    "step",
                    "--root",
                    str(root),
                    "--case-id",
                    case["case_id"],
                    "--index",
                    str(index),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                result = json.loads(child.stdout)
            except ValueError:
                result = {"status": "UNKNOWN", "stderr": child.stderr, "stdout": child.stdout}
            results.append(
                {
                    "case_id": case["case_id"],
                    "message_index": index,
                    "returncode": child.returncode,
                    **result,
                }
            )
            intended_interruption = (
                result["status"] == "UNKNOWN"
                and result.get("error_type") == "InjectedInterruption"
                and result.get("evaluator_control_state", {}).get("fault", {}).get("applied")
                and result["evaluator_control_state"]["fault"].get("message_index") == index
                if result.get("evaluator_control_state", {}).get("fault")
                else False
            )
            blocked = result["status"] != "COMPLETED" and not intended_interruption
            queue_blocked = result["status"] == "BUDGET_EXHAUSTED" and (
                "FUNCTIONAL_QUEUE" in result.get("error", "")
            )
            write_json(root / "results.json", {"results": results})
    write_json(root / "results.json", {"results": results})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "message", "step", "run", "inspect", "disable", "enable")
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--index", type=int)
    parser.add_argument("--bank", default="personal")
    parser.add_argument("--owner")
    parser.add_argument("--session")
    parser.add_argument("--message-id")
    parser.add_argument("--text")
    parser.add_argument("--workflow", choices=("reservation", "document"), default="reservation")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.command in {"disable", "enable"}:
        if not (args.root / "input-freeze.json").exists():
            parser.error("profile root has not been prepared")
        result = {"disabled": args.command == "disable", "persistent_data_deleted": False}
        write_json(args.root / "profile-state.json", result)
    elif args.command == "prepare":
        if args.config is None:
            parser.error("prepare requires --config")
        result = prepare(args.root, args.config, args.fixture, args.controls)
        result = {
            "status": "PREPARED",
            "config_sha256": result["config_sha256"],
            "source_files": len(result["source_sha256"]),
        }
    elif args.command == "step":
        if args.case_id is None or args.index is None:
            parser.error("step requires --case-id and --index")
        result = step(args.root, args.case_id, args.index, resume=args.resume)
    elif args.command == "message":
        if not all((args.owner, args.session, args.message_id, args.text)):
            parser.error("message requires --owner --session --message-id --text")
        result = message(
            args.root,
            bank=args.bank,
            owner=args.owner,
            session=args.session,
            message_id=args.message_id,
            content=args.text,
            workflow=args.workflow,
            resume=args.resume,
        )
    elif args.command == "inspect":
        result = frozen(args.root)
    else:
        result = {"results": run(args.root)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
