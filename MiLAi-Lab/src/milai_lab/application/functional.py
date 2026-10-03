"""Opt-in application boundary shared by functional runners.

The caller supplies trusted operation authorization and owns model execution.
Receipts, raw sources, literal projections, semantic maintenance and delivery
are separate facts. Only the two local backends' cooperative lock/transactions
are covered; this is not an arbitrary external exactly-once protocol.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO, Self

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from milai_lab.application.document_publication import DOCUMENT_NAMES, DocumentPublicationWorld
from milai_lab.application.journal import BusinessActionJournal
from milai_lab.application.native_journal import NativePublicActionJournal, recover_native_pending
from milai_lab.application.recovery import recover_pending_application_call
from milai_lab.application.refs import (
    observation_profile,
    verified_document_ref,
    verified_reservation_ref,
)
from milai_lab.application.tools import BUSINESS_NAMES, _business_tools, document_business_tools
from milai_lab.application.world import ApplicationWorld
from milai_lab.contracts.memory import ObservationProfile, VerifiedObjectRef
from milai_lab.harness.artifact_io import read_json, write_json


class ReceiptProgressJournal:
    """Replay markers under the facade's lifetime cooperative lock.

    A ready delivery does not prove that a Host saw it. The runner acknowledges
    delivery only after observing its durable checkpoint. Memory tools registered
    for replay must themselves commit idempotently by the same tool-call ID.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def snapshot(self) -> dict[str, Any]:
        return read_json(self.path) if self.path.exists() else {}

    def begin(self, identity: dict[str, Any]) -> str:
        key = BusinessActionJournal._hash(identity)
        rows = self.snapshot()
        if key not in rows:
            # Detect reused call IDs even when changed arguments give a new hash.
            call_identity = (identity["thread_id"], identity["generation_id"], identity["call_id"])
            for row in rows.values():
                old = row["identity"]
                if (old["thread_id"], old["generation_id"], old["call_id"]) == call_identity:
                    raise ValueError("FUNCTIONAL_CALL_IDENTITY_CHANGED")
            rows[key] = {"identity": identity, "delivery": "pending"}
            write_json(self.path, rows)
        return key

    def record(self, key: str, field: str, value: Any) -> None:
        rows = self.snapshot()
        prior = rows[key].get(field)
        if field in rows[key] and prior != value:
            raise ValueError("FUNCTIONAL_RECEIPT_STAGE_CHANGED:" + field)
        rows[key][field] = value
        write_json(self.path, rows)

    def acknowledge_delivery(self, key: str) -> None:
        """Trusted runner acknowledgment after checkpointed tool delivery."""
        rows = self.snapshot()
        if "delivery_response" not in rows[key]:
            raise ValueError("FUNCTIONAL_DELIVERY_NOT_READY")
        rows[key]["delivery"] = "checkpointed"
        write_json(self.path, rows)


class FunctionalApplication:
    """Two distinct actual worlds with one owner-bound execution interface."""

    root: Path
    workflow: str
    owner: str
    world: ApplicationWorld
    tools: list[BaseTool]
    tool_names: tuple[str, ...]
    observation_profile: ObservationProfile
    journal: BusinessActionJournal
    progress: ReceiptProgressJournal
    _closed: bool
    _lock: BinaryIO

    @classmethod
    def open(
        cls, root: Path, workflow: str, owner: str, *,
        initial_label_available: bool = True,
        initial_publication_available: bool = True,
        response_hook: Callable[[dict[str, Any], ToolMessage], None] | None = None,
        authorization_mode: str = "native_public_v1",
        attempt_policy: str = "legacy",
    ) -> Self:
        workflow = {"reservation": "reservation_v1", "document": "document_publication_v1"}.get(
            workflow, workflow
        )
        if workflow not in {"reservation_v1", "document_publication_v1"} or not owner:
            raise ValueError("FUNCTIONAL_APPLICATION_SCOPE_INVALID")
        if authorization_mode not in {"native_public_v1", "scripted_v1"}:
            raise ValueError("FUNCTIONAL_APPLICATION_AUTHORIZATION_MODE_INVALID")
        if attempt_policy not in {"legacy", "single_phase_per_public_turn_v1",
                                  "single_phase_with_history_v2", "fresh_query_with_history_v3"}:
            raise ValueError("FUNCTIONAL_APPLICATION_ATTEMPT_POLICY_INVALID")
        if attempt_policy != "legacy" and authorization_mode != "native_public_v1":
            raise ValueError("FUNCTIONAL_ATTEMPT_POLICY_REQUIRES_NATIVE_MODE")
        if (type(initial_label_available) is not bool
                or type(initial_publication_available) is not bool):
            raise ValueError("FUNCTIONAL_APPLICATION_AVAILABILITY_INVALID")
        app = cls()
        app.root, app.workflow, app.owner = Path(root), workflow, owner
        app.root.mkdir(parents=True, exist_ok=True)
        app._closed = False
        app._lock = (app.root / "application.lock").open("a+b")
        try:
            fcntl.flock(app._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity_path = app.root / "application-identity.json"
            identity = {"workflow": workflow, "owner": owner, "contract": "functional_v13_5",
                        "authorization_mode": authorization_mode}
            if attempt_policy != "legacy":
                identity["attempt_policy"] = attempt_policy
            if identity_path.exists() and read_json(identity_path) != identity:
                raise ValueError("FUNCTIONAL_APPLICATION_IDENTITY_CHANGED")
            if not identity_path.exists():
                write_json(identity_path, identity)
            if workflow == "document_publication_v1":
                app.world = DocumentPublicationWorld(
                    app.root / "application.sqlite", initial_publication_available
                )
                app.tools = document_business_tools(app.world, owner)
                app.tool_names = tuple(DOCUMENT_NAMES)
            else:
                app.world = ApplicationWorld(
                    app.root / "application.sqlite", initial_label_available
                )
                app.tools = _business_tools(app.world, owner)
                app.tool_names = tuple(BUSINESS_NAMES)
            app.observation_profile = observation_profile(workflow)
            if attempt_policy != "legacy":
                for tool in app.tools:
                    if tool.name not in {"get_reservation", "get_document_status"}:
                        tool.description += (
                            " Per public request and exact object, each business phase may be "
                            "attempted only once, including a failed/no-effect attempt. "
                            "reserve_and_label already attempts both reservation and labeling. "
                            "Read current state or await a new user request before another attempt."
                        )
                    elif attempt_policy in {"single_phase_with_history_v2",
                                            "fresh_query_with_history_v3"}:
                        tool.description += (
                            " Also returns up to 16 original operation receipt summaries for "
                            "this exact owner/object in journal order, with an omission count. "
                            "Past unknown receipts stay unknown; current state is separate."
                        )
            journal_class = (NativePublicActionJournal if authorization_mode == "native_public_v1"
                             else BusinessActionJournal)
            app.journal = journal_class(
                app.root / "business-journal.json", app.tool_names,
                **({"owner": owner, "world": app.world,
                    "single_phase_per_turn": attempt_policy != "legacy",
                    "include_attempt_history": attempt_policy in {
                        "single_phase_with_history_v2", "fresh_query_with_history_v3"},
                    "require_fresh_query": attempt_policy == "fresh_query_with_history_v3"}
                   if authorization_mode == "native_public_v1"
                   else {"application_protection": True}),
                response_hook=response_hook,
                application_workflow=workflow,
            )
            app.progress = ReceiptProgressJournal(app.root / "receipt-progress.json")
        except BaseException:
            if hasattr(app, "world"):
                app.world.close()
            app._lock.close()
            raise
        return app

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            try:
                self.world.close()
            finally:
                self._closed = True
                self._lock.close()

    def bind_request(self, binding: Mapping[str, Any]) -> None:
        if isinstance(self.journal, NativePublicActionJournal):
            raise ValueError("FUNCTIONAL_SCRIPTED_BINDING_REQUIRES_SCRIPTED_MODE")
        if binding.get("owner") != self.owner:
            raise ValueError("FUNCTIONAL_APPLICATION_OWNER_CHANGED")
        self.journal.bind_request(binding)

    def verified_ref(
        self, source_ref: str, tool_name: str, receipt: str, *,
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> VerifiedObjectRef | None:
        binder = (verified_document_ref if self.workflow == "document_publication_v1"
                  else verified_reservation_ref)
        return binder(self.world, self.owner, source_ref, tool_name, receipt, observer=observer)

    def recover_pending(self, agent: Any, scope: Any, runtime: Any) -> None:
        if isinstance(self.journal, NativePublicActionJournal):
            recover_native_pending(self, agent, scope, runtime)
            return
        recover_pending_application_call(
            agent, scope, self.journal, self.world, runtime, application_workflow=self.workflow
        )

    def snapshot(self) -> dict[str, Any]:
        """Evaluator/diagnostic sidecar; never a Host tool or authorization source."""
        return {"workflow": self.workflow, "owner": self.owner,
                "world": self.world.snapshot(), "journal": self.journal._entries(),
                "receipt_progress": self.progress.snapshot()}

    def call_wrapper(
        self, service: Any, session: str, turn_id: str,
        trace: Callable[[dict[str, Any]], None] | None = None,
        runtime_config: Mapping[str, Any] | None = None, *,
        boundary_hook: Callable[[str, dict[str, Any]], None] | None = None,
        memory_mutation_names: Sequence[str] = ("save_memory", "update_memory", "forget_memory"),
        inline_fragment_content: bool = False,
    ) -> FunctionalCallWrapper:
        """Wrap ToolNode calls before delivery, with no model/network calls here.

        Register only memory tools whose exact tool-call ID is an idempotent
        commit identity. Unknown business calls are never automatically replayed.
        """
        if runtime_config is not None and (
            runtime_config.get("max_concurrency") != 1
            or runtime_config.get("configurable", {}).get("user_id") != self.owner
        ):
            raise ValueError("FUNCTIONAL_CALL_CONFIGURATION_INVALID")
        if isinstance(self.journal, NativePublicActionJournal):
            source = service.source(service.event_id(session, turn_id, "user"))
            if (source is None and runtime_config is not None
                    and getattr(service, "functional_contract", "legacy") == "functional_v1"):
                cfg = runtime_config.get("configurable", {})
                digest = cfg.get("v13_support_config_sha256")
                if (cfg.get("v13_session") != session or cfg.get("v13_turn_id") != turn_id
                        or not isinstance(digest, str) or not digest):
                    raise ValueError("FUNCTIONAL_PUBLIC_TURN_CONFIGURATION_INVALID")
                # Forget may hide this exact in-flight trigger. Its persisted
                # session/message/config binding permits continuation only;
                # normal source retrieval and fragment issuance stay revoked.
                source = service.active_public_input(session, turn_id, digest)
            if source is None:
                raise ValueError("FUNCTIONAL_ACTUAL_PUBLIC_SOURCE_REQUIRED")
            self.journal.bind_public_turn(session, turn_id, source)
        return FunctionalCallWrapper(self, service, session, turn_id, trace,
                                     boundary_hook, frozenset(memory_mutation_names),
                                     inline_fragment_content)


class FunctionalCallWrapper:
    def __init__(
        self, app: FunctionalApplication, service: Any, session: str, turn_id: str,
        trace: Callable[[dict[str, Any]], None] | None,
        boundary_hook: Callable[[str, dict[str, Any]], None] | None,
        memory_mutation_names: frozenset[str],
        inline_fragment_content: bool = False,
    ) -> None:
        if service.owner != app.owner or not session or not turn_id:
            raise ValueError("FUNCTIONAL_MEMORY_SCOPE_INVALID")
        if service.mutation_contract != "event_bound_v1":
            raise ValueError("FUNCTIONAL_MEMORY_EVENT_BOUND_REQUIRED")
        self.app, self.service, self.session, self.turn_id = app, service, session, turn_id
        self.trace = trace or (lambda event: None)
        self.boundary_hook = boundary_hook or (lambda window, event: None)
        self.memory_mutation_names = memory_mutation_names
        self.inline_fragment_content = inline_fragment_content

    def _source_fragment_index(self, source_ref: str) -> list[dict[str, Any]]:
        if getattr(self.service, "functional_contract", "legacy") != "functional_v1":
            return []
        fields = (
            "fragment_handle", "source_ref", "role", "origin", "start", "end",
            "source_total_codepoints", "range_basis",
        ) + (("content", "semantic_support") if self.inline_fragment_content else ())
        return [{field: fragment[field] for field in fields}
                for fragment in self.service.source_fragments(source_ref)]

    def note_delivered_sources(self, source_refs: list[str]) -> None:
        if getattr(self.service, "functional_contract", "legacy") != "functional_v1":
            return
        self.service.note_tool_delivery(self.session, self.turn_id, source_refs)

    def query_source_delivery(self, query_journal_key: str) -> dict[str, Any]:
        """Attach only the captured actual discovery source, never an original receipt."""
        row = self.app.journal._entries().get(query_journal_key)
        if (row is None or not row.get("executed") or row.get("status") != "complete"
                or row.get("name") not in {"get_reservation", "get_document_status"}):
            raise ValueError("FUNCTIONAL_ACTUAL_DISCOVERY_RECEIPT_REQUIRED")
        source_ref = self.service.event_id(self.session, "application:" + query_journal_key, "tool")
        source = self.service.source(source_ref)
        if (source is None or source.get("origin") != row["name"]
                or source.get("role") != "tool"
                or source.get("content") != row["result"]["content"]):
            raise ValueError("FUNCTIONAL_ACTUAL_DISCOVERY_SOURCE_REQUIRED")
        return {"source_ref": source_ref, "origin": source["origin"],
                "source_fragment_index": self._source_fragment_index(source_ref)}

    def _identity(self, request: Any) -> dict[str, Any]:
        generated, call = request.state["messages"][-1], request.tool_call
        config = request.runtime.config["configurable"]
        if not isinstance(generated, AIMessage) or not generated.id or not call.get("id"):
            raise ValueError("FUNCTIONAL_CALL_IDENTITY_REQUIRED")
        if config.get("user_id") != self.app.owner:
            raise ValueError("FUNCTIONAL_CALL_OWNER_CHANGED")
        if request.runtime.config.get("max_concurrency") != 1:
            raise ValueError("FUNCTIONAL_CALL_SERIAL_EXECUTION_REQUIRED")
        return {"thread_id": config["thread_id"], "generation_id": generated.id,
                "call_id": call["id"], "name": call["name"], "args": call["args"],
                "owner": self.app.owner, "session": self.session, "turn_id": self.turn_id}

    def capture(self, request: Any, response: ToolMessage, *, wrap: bool = True) -> ToolMessage:
        """Capture only an executed durable business receipt, including discovery."""
        identity = self._identity(request)
        row = self.app.journal.entry_for_call(
            identity["thread_id"], identity["generation_id"], identity["call_id"]
        )
        if row is None or not row.get("executed") or row["status"] != "complete":
            return response
        if row["result"] != response.model_dump(mode="json"):
            raise ValueError("FUNCTIONAL_ACTUAL_RECEIPT_CHANGED")
        key = self.app.progress.begin(identity)
        self.app.progress.record(key, "business_receipt", row["result"])
        event_key = "application:" + row["journal_key"]
        source_ref = self.service.event_id(self.session, event_key, "tool")
        body = str(response.content)
        existing = self.service.source(source_ref)
        ref = (VerifiedObjectRef(**existing["object_ref"])
               if existing is not None and existing.get("object_ref") else
               self.app.verified_ref(source_ref, identity["name"], body, observer=self.trace)
               if existing is None else None)
        captured = self.service.capture_tool(
            self.session, event_key, identity["name"], body, ref
        )
        if not captured.get("ok"):
            raise RuntimeError("FUNCTIONAL_SOURCE_CAPTURE_FAILED")
        # Formation can change after capture; it is not part of raw event identity.
        source_capture = {name: captured[name] for name in ("ok", "source_ref", "observed_at")}
        source_capture["status"] = "captured"
        self.app.progress.record(key, "raw_capture", source_capture)
        self.service.bind_source_boundary(self.session, self.turn_id, [source_ref], append=True)
        self.boundary_hook("W2", {"key": key, "tool": identity["name"],
                                  "source_ref": source_ref, "receipt": row["result"]})
        projection = self.service.observe(source_ref, self.app.observation_profile)
        if not projection.get("ok"):
            self.trace({"event": "functional_projection_incomplete", "key": key,
                        "projection": projection})
            raise RuntimeError("FUNCTIONAL_OBSERVATION_PROJECTION_INCOMPLETE")
        # The persisted original receipt stays stable when observe returns no_change.
        projection = self.service.projection_receipt(source_ref, self.app.observation_profile)
        self.app.progress.record(key, "observation_projection", projection)
        self.boundary_hook("W3", {"key": key, "tool": identity["name"], "source_ref": source_ref,
                                  "observation_projection": projection})
        content = {"receipt": json.loads(body), "source_ref": source_ref,
                   "object_ref": ref.id if ref else None, "observation_only": True,
                   "raw_capture": source_capture, "observation_projection": projection,
                   "semantic_maintenance": {"status": "not_requested"},
                   "business_outcome": {"confirmed": "confirmed", "partial": "partial",
                       "none": "known_no_effect", "unknown": "outcome_unknown",
                       "observed": "observed"}[row["effect"]]}
        if getattr(self.service, "functional_contract", "legacy") == "functional_v1":
            # These fragments identify the original tool body already delivered
            # above. Ordinary retrieval remains on its original fixed snapshot;
            # the Host need not spend another read just to obtain evidence handles.
            content["source_fragment_index"] = self._source_fragment_index(source_ref)
            if self.inline_fragment_content:
                content["memory_evidence_selection"] = (
                    "Each handle covers only its adjacent original content. Select every "
                    "fragment needed for the saved claims. A user request supports what was "
                    "requested, not what actually happened; use these actual tool observations "
                    "for outcome claims. Omit details unsupported by your selected fragments. "
                    "Source observed_at is receipt capture time, not the exact business event "
                    "time; event timestamps require their own selected receipt fields. "
                    "These handles require no extra read; semantic support remains unchecked.")
        delivery = response.model_copy(update={"content": json.dumps(content, ensure_ascii=False)})
        self.app.progress.record(key, "delivery_response", delivery.model_dump(mode="json"))
        self.trace({"event": "functional_application_receipt_ready", "key": key,
                    "source_ref": source_ref, "business_outcome": content["business_outcome"],
                    "actual_tool_receipt": row["result"], "origin": row["origin"],
                    "generation_requests": 0})
        if wrap:
            self.note_delivered_sources([source_ref])
        return delivery if wrap else response

    def __call__(self, request: Any, execute: Callable[[Any], Any]) -> Any:
        name = request.tool_call["name"]
        if name in self.app.tool_names:
            response = self.app.journal(request, execute)
            return (self.capture(request, response)
                    if isinstance(response, ToolMessage) else response)
        if name not in self.memory_mutation_names:
            return execute(request)
        key = self.app.progress.begin(self._identity(request))
        row = self.app.progress.snapshot()[key]
        if "delivery_response" in row:
            return ToolMessage.model_validate(row["delivery_response"])
        # A process may die after the memory commit but before this marker. In
        # that window the explicitly registered tool must replay its own receipt.
        response = (ToolMessage.model_validate(row["memory_response"])
                    if "memory_response" in row else execute(request))
        if not isinstance(response, ToolMessage):
            raise TypeError("FUNCTIONAL_MEMORY_EXPECTED_TOOL_MESSAGE")
        self.app.progress.record(key, "memory_response", response.model_dump(mode="json"))
        receipt = json.loads(str(response.content))
        self.app.progress.record(key, "semantic_maintenance", receipt)
        if receipt.get("ok") and receipt.get("status") in {
            "committed", "no_change", "visibility_revoked",
        }:
            self.boundary_hook("W3", {"key": key, "tool": name, "semantic_maintenance": receipt})
        self.app.progress.record(key, "delivery_response", response.model_dump(mode="json"))
        return response

    @property
    def observer(self) -> Self:
        return self

    def begin_public_message(self, scope: Any, public_index: int, content: str) -> None:
        self.trace({"event": "functional_recovery_discovery", "owner": scope.user_id,
                    "public_index": public_index, "generation_requests": 0})

    def run_tool(self, request: Any, execute: Callable[[Any], Any],
                 business_journal: Any = None) -> Any:
        response = execute(request)
        return (self.capture(request, response, wrap=False)
                if isinstance(response, ToolMessage) else response)
