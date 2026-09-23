"""Native Actor integration for the separately authorized joint finite study.

Not an execution entrypoint or admission grant. The caller must seal the method,
inputs, reviews, plan and native environment before using this runtime. No old
Utility run/ledger is opened. Raw receipts belong in the caller's private run root.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from finite_budget_transport import FiniteBudgetTransport
from milai_lab.analysis.revision_eligibility import assess_revision_reuse, freeze_revision_review
from milai_lab.methods.attention_expansion import AttentionExpansion, RetrievedSources
from milai_lab.methods.evidence_utility_session import messages_digest
from milai_lab.methods.experience_utility import VersionUtility, version_key
from milai_lab.methods.reasoning_bank import ExperienceBank
from milai_lab.methods.state_attention import (
    DEFAULT_LIMITS,
    AttentionState,
    CoverageReview,
    StateField,
    question_digest,
)
from milai_lab.methods.state_focus import SourceSnapshot, SourceUnit
from reasoningbank_runtime_policy import action_budget, actor_runtime_context
from replay_v0213_cost import save
from run_utility_proxy_batch import COMMON, LAB
from v02_local_provider import append_event, read_events

OPEN_TAG = "<milai_attention>"
CLOSE_TAG = "</milai_attention>"
STATE_INSTRUCTION = """Optional memory review, not a business action or factual authority:
Before your normal native action/answer, emit one compact <milai_attention>JSON</milai_attention>.
Use exactly selected_source_ids (relevant memory IDs), conflict_source_ids (all sides of any
unresolved memory conflict; [] if reviewed absent), coverage (SUFFICIENT, GAP or UNKNOWN).
IDs must come from the supplied memory pool. Coverage describes the union of selected and
conflicting sources. If the full pool is not visible, use UNKNOWN; do not invent a review.
Keep JSON below 4096 UTF-8 bytes. Then give the normal native action with its original grammar.
This fallible state can guide only the next turn, before its new tool feedback is reconsidered.
"""


class Timeline:
    """One append-only runner chronology, including intentional formation/review phases."""

    def __init__(self, path: Path):
        self.path = path
        rows = read_events(path)
        if [r["sequence"] for r in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("JOINT_TIMELINE_CHANGED")
        self.sequence = len(rows)

    def emit(self, event: str, **fields) -> dict:
        self.sequence += 1
        row = {**fields, "event": event, "sequence": self.sequence, "at_unix": time.time()}
        append_event(self.path, row)
        return row

    def reference(self, row: dict) -> str:
        return f"{self.path}#sequence={row['sequence']}"


def render_source(unit: SourceUnit) -> str:
    return f"[memory {unit.source_id} version={unit.version}]\n{unit.content}\n[/memory]"


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_STATE_KEY")
        value[key] = item
    return value


def parse_state(raw: str, snapshot: SourceSnapshot) -> tuple[str, dict | None, str]:
    """Strip only a complete leading state frame; leave native action bytes intact.

    Malformed/unbounded/foreign assertions yield UNKNOWN, never a repair call.
    A missing closing tag is left for the unchanged native parser to handle.
    """
    prefix = raw.lstrip()
    if not prefix.startswith(OPEN_TAG):
        return raw, None, "ABSENT"
    end = prefix.find(CLOSE_TAG, len(OPEN_TAG))
    if end < 0:
        return raw, None, "UNTERMINATED"
    body = prefix[len(OPEN_TAG) : end]
    native = prefix[end + len(CLOSE_TAG) :].lstrip("\r\n")
    try:
        if len(body.encode()) > 4096 or OPEN_TAG in native or CLOSE_TAG in native:
            raise ValueError("UNBOUNDED_OR_DUPLICATE_FRAME")
        value = json.loads(body, object_pairs_hook=_unique)
        if not isinstance(value, dict) or set(value) != {
            "selected_source_ids",
            "conflict_source_ids",
            "coverage",
        }:
            raise ValueError("STATE_FIELDS")
        known = {s.source_id for s in snapshot.units}
        for key in ("selected_source_ids", "conflict_source_ids"):
            refs = value[key]
            if (
                not isinstance(refs, list)
                or any(not isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs)
                or not set(refs) <= known
            ):
                raise ValueError("STATE_REFERENCES")
        if len(value["conflict_source_ids"]) == 1:
            raise ValueError("CONFLICT_REQUIRES_ALL_SIDES")
        if value["coverage"] not in ("SUFFICIENT", "GAP", "UNKNOWN"):
            raise ValueError("STATE_COVERAGE")
        selected = set(value["selected_source_ids"]) | set(value["conflict_source_ids"])
        if (
            len(selected) > DEFAULT_LIMITS.max_sources
            or sum(len(s.content.encode()) for s in snapshot.units if s.source_id in selected)
            > DEFAULT_LIMITS.max_bytes
        ):
            raise ValueError("STATE_SELECTION_OVER_BOUND")
        return native, value, "PARSED_NOT_SEMANTICALLY_VERIFIED"
    except (ValueError, TypeError):
        return native, None, "MALFORMED_OR_UNBOUNDED"


def bind_state(value, *, task_id, question, snapshot, turn, artifact_ref):
    units = {s.source_id: s for s in snapshot.units}
    state = AttentionState(
        task_id,
        snapshot.scope,
        question_digest(question),
        snapshot.sha256,
        tuple(
            StateField(
                name, "ACTOR", turn, turn + 1, artifact_ref, tuple(units[ref] for ref in value[key])
            )
            for name, key in (
                ("memory_intentions", "selected_source_ids"),
                ("open_conflicts", "conflict_source_ids"),
            )
        ),
    )
    selected = set(value["selected_source_ids"]) | set(value["conflict_source_ids"])
    coverage = CoverageReview(
        state.sha256,
        snapshot.sha256,
        tuple(s.source_id for s in snapshot.units if s.source_id in selected),
        value["coverage"],
        artifact_ref,
        turn,
        turn + 1,
    )
    return state, coverage


class JointMemory:
    """Task-private source projection, real Actor state and exact revision exposure.

    ranked_expansion is already source-cluster-filtered and ordered by the frozen
    unchanged-query cosine retriever. Its construction/authentication is an admission
    responsibility, not an outcome-driven choice here. No embedding is called here.
    """

    def __init__(
        self,
        *,
        root: Path,
        admission_sha256: str,
        row: dict,
        snapshot: SourceSnapshot,
        ranked_expansion: tuple[SourceUnit, ...],
        timeline: Timeline,
        bank: ExperienceBank | None = None,
        revision_reviews: tuple[dict, ...] = (),
        source_handles: dict[str, str] | None = None,
    ):
        self.root, self.row, self.timeline = root, copy.deepcopy(row), timeline
        self.snapshot = snapshot
        self.baseline_ids = tuple(s.source_id for s in snapshot.units)
        self.ranked_expansion = ranked_expansion
        self.original_sources = {s.source_id: s for s in (*snapshot.units, *ranked_expansion)}
        if len(self.original_sources) != len(snapshot.units) + len(ranked_expansion):
            raise ValueError("DUPLICATE_FROZEN_SOURCE")
        if any(s.scope != snapshot.scope for s in ranked_expansion):
            raise ValueError("EXPANSION_SCOPE_CHANGED")
        if len(snapshot.units) > 8 or sum(len(s.content.encode()) for s in snapshot.units) > 8192:
            raise ValueError("COMMON_BASELINE_OVER_BOUND")
        if row["arm"] not in {"APPEND_ONLY", "REVISION", "STATIC", "ATTENTION"}:
            raise ValueError("UNKNOWN_JOINT_ARM")
        if question_digest(row["query"]) != row["query_sha256"]:
            raise ValueError("FROZEN_QUERY_CHANGED")
        self.state, self.coverage = None, None
        self.turn = 0
        self.exposures = []
        self.bank = copy.deepcopy(bank)
        self.reviews = copy.deepcopy(revision_reviews)
        self.source_handles = dict(source_handles or {})
        if self.bank is not None:
            if row["arm"] not in {"APPEND_ONLY", "REVISION"} or ranked_expansion:
                raise ValueError("REVISION_OVERLAY_ON_WRONG_ARM")
            if set(self.source_handles) != set(self.baseline_ids):
                raise ValueError("REVISION_SOURCE_BINDING_REQUIRED")
            for unit in snapshot.units:
                card = self.bank.cards[self.source_handles[unit.source_id]]
                if unit.content != card.text or unit.version != str(card.revision) or card.retired:
                    raise ValueError("REVISION_PROJECTION_CHANGED")
            for review in self.reviews:
                if freeze_revision_review(self.bank, review["review"]) != review:
                    raise ValueError("REVISION_REVIEW_CHANGED")
                if (
                    review["review"]["support"] != "SUPPORTED"
                    or review["review"]["kind"] not in {"CORRECTION", "SCOPE_NARROWING"}
                    or not review["review"]["lineage_clusters"]
                    or row["cluster"] in review["review"]["lineage_clusters"]
                ):
                    raise ValueError("SUPPORTED_INDEPENDENT_REVISION_REQUIRED")
                if review["review"]["review_sequence"] > timeline.sequence:
                    raise ValueError("REVIEW_NOT_YET_RECORDED")
        elif revision_reviews or source_handles:
            raise ValueError("REVISION_BANK_REQUIRED")
        event = timeline.emit(
            "JOINT_RETRIEVED",
            attempt_id=row["attempt_id"],
            snapshot_sha256=snapshot.sha256,
            sources=[s.reference() for s in snapshot.units],
        )
        self.retrieval_event = event
        self.expansion = (
            AttentionExpansion(
                root / "attention.sqlite",
                admission_sha256=admission_sha256,
                execution_id=row["attempt_id"],
                task_id=row["attempt_id"],
                scope=snapshot.scope,
                question=row["query"],
            )
            if row["arm"] == "ATTENTION"
            else None
        )

    def eligible(self, source):
        return "ELIGIBLE" if self.original_sources.get(source.source_id) == source else "DENIED"

    def retrieve(self, intent):
        start = time.monotonic()
        if intent["query"] != self.row["query"] or intent["scope"] != self.snapshot.scope:
            raise ValueError("ATTENTION_RETRIEVAL_BINDING_CHANGED")
        # The review preview must fit the same cap as the common baseline.
        available = min(
            intent["max_bytes"], 8192 - sum(len(s.content.encode()) for s in self.snapshot.units)
        )
        selected = []
        for source in self.ranked_expansion:
            if source.source_id in intent["exclude_source_ids"]:
                continue
            size = len(source.content.encode())
            if (
                len(selected) < min(intent["limit"], 8 - len(self.snapshot.units))
                and size <= available
            ):
                selected.append(source)
                available -= size
        row = self.timeline.emit(
            "CACHED_QUERY_EXPANSION",
            attempt_id=self.row["attempt_id"],
            intent=intent,
            sources=[s.reference() for s in selected],
            seconds=time.monotonic() - start,
            external_requests=0,
            embedding_requests=0,
            cost_basis="local frozen vectors; formation/embedding charged separately",
        )
        return RetrievedSources(tuple(selected), self.timeline.reference(row))

    def context(self, budget):
        budget.remaining_seconds()
        self.turn += 1
        preview = False
        if self.expansion is not None:

            def step():
                return self.expansion.step(
                    sequence=self.turn,
                    snapshot=self.snapshot,
                    baseline_ids=self.baseline_ids,
                    state=self.state,
                    coverage=self.coverage,
                    check_source=self.eligible,
                    before_dispatch=budget.remaining_seconds,
                    retrieve=self.retrieve,
                )

            decision, pool = step()
            if pool == self.snapshot and decision["action"] == "RETRIEVE_ONCE":
                # Empty retrieval still spends the durable attempt. Re-decide with
                # the spent count; the old intent is not an Actor-ready decision.
                decision, pool = step()
            if pool != self.snapshot:
                # Expansion invalidates old assertions. Show its bounded results once
                # for the next real Actor review; do NOT call this sufficient coverage.
                self.snapshot, self.state, self.coverage = pool, None, None
                preview = True
            if preview:
                selected = self.snapshot.units
            else:
                ids = {s["source_id"] for s in decision["selected_sources"]}
                selected = tuple(s for s in self.snapshot.units if s.source_id in ids)
        else:
            selected = self.snapshot.units
            decision = {"action": "CONTEXT", "reason": "FROZEN_BASELINE", "coverage": "UNKNOWN"}
        event = self.timeline.emit(
            "JOINT_PROJECTION",
            attempt_id=self.row["attempt_id"],
            turn=self.turn,
            decision=decision,
            preview_for_review=preview,
            preview_coverage="UNKNOWN" if preview else None,
            snapshot_sha256=self.snapshot.sha256,
            sources=[s.reference() for s in selected],
        )
        self.projected = selected
        self.projection_ref = self.timeline.reference(event)
        parts = (
            [(LAB / "configs/policies/reasoning_bank/consume.txt").read_text().strip()]
            if selected
            else []
        )
        parts.extend(render_source(s) for s in selected)
        if self.expansion is not None:
            parts.append(STATE_INSTRUCTION)
            parts.append(
                "Memory pool IDs: " + json.dumps([s.source_id for s in self.snapshot.units])
            )
            if preview:
                parts.append(
                    "New retrieval preview: coverage UNKNOWN; review before later selection."
                )
        return "\n\n".join(parts)

    def settled(self, raw, receipt: dict, messages: list[dict]) -> str:
        if (
            receipt is None
            or receipt.get("status") != "SETTLED"
            or receipt.get("session") != self.row["attempt_id"]
            or receipt.get("role") != "actor"
            or receipt.get("messages_sha256") != messages_digest(messages)
            or not receipt.get("request_id")
            or len(receipt.get("payload_sha256", "")) != 64
            or any(e["receipt"]["request_id"] == receipt["request_id"] for e in self.exposures)
        ):
            raise ValueError("ACTOR_RECEIPT_BINDING_MISMATCH")
        contents = [m["content"] for m in messages if isinstance(m.get("content"), str)]
        exposed = [s for s in self.snapshot.units if any(render_source(s) in c for c in contents)]
        if not set(self.projected) <= set(exposed):
            raise ValueError("PROJECTED_SOURCE_MISSING_FROM_REQUEST")
        event = self.timeline.emit(
            "JOINT_ACTOR_SETTLED",
            attempt_id=self.row["attempt_id"],
            turn=self.turn,
            receipt=receipt,
            projection_ref=self.projection_ref,
            sources=[s.reference() for s in exposed],
            observable_use="UNKNOWN",
        )
        self.exposures.append(
            {
                "receipt": {**receipt, "sequence": event["sequence"]},
                "sources": [s.source_id for s in exposed],
            }
        )
        if not isinstance(raw, str):
            self.state, self.coverage = None, None
            raise ValueError("NATIVE_TEXT_ACTOR_RETURNED_NO_TEXT")
        if self.expansion is None:
            return raw
        native, value, status = parse_state(raw, self.snapshot)
        # An ID list or prior assertion is not the omitted source body. Refresh
        # whole-pool claims only when all exact bodies were in this settled input.
        if {s.source_id for s in exposed} != {s.source_id for s in self.snapshot.units}:
            value, status = None, "WHOLE_POOL_NOT_EXPOSED"
        state_event = self.timeline.emit(
            "ACTOR_STATE",
            attempt_id=self.row["attempt_id"],
            turn=self.turn,
            producer_request_id=receipt["request_id"],
            messages_sha256=receipt["messages_sha256"],
            snapshot_sha256=self.snapshot.sha256,
            status=status,
            value=value,
            claim="fallible Actor assertion; one-turn lag; not independent evaluation labels",
        )
        self.state, self.coverage = (
            bind_state(
                value,
                task_id=self.row["attempt_id"],
                question=self.row["query"],
                snapshot=self.snapshot,
                turn=self.turn,
                artifact_ref=self.timeline.reference(state_event),
            )
            if value is not None
            else (None, None)
        )
        return native

    def finish(self, *, result_ref, costs):
        eligible = []
        if self.bank is not None:
            utility = VersionUtility(self.bank.utility_state)
            for source in self.snapshot.units:
                utility.register(self.bank.cards[self.source_handles[source.source_id]])
            sequence = []
            for exposure in self.exposures:
                utility.confirm(
                    sequence,
                    receipt=exposure["receipt"],
                    task_id=self.row["attempt_id"],
                    versions=[
                        (
                            self.source_handles[ref],
                            self.bank.cards[self.source_handles[ref]].revision,
                        )
                        for ref in exposure["sources"]
                    ],
                )
            utility.finish(
                task_id=self.row["attempt_id"],
                scope=self.bank.scope,
                selector_version="joint-frozen-top1-v1",
                feedback_regime="H",
                sequence=sequence,
                result_ref=result_ref,
                native_result=None,
                costs=costs,
                decision_ref=self.timeline.reference(self.retrieval_event),
            )
            self.bank.completed_tasks.append(self.row["attempt_id"])
            for review in self.reviews:
                retrieval = {
                    "ref": self.timeline.reference(self.retrieval_event),
                    "sequence": self.retrieval_event["sequence"],
                    "task_id": self.row["attempt_id"],
                    "scope_sha256": review["scope_sha256"],
                    "version_keys": [
                        version_key(self.source_handles[s.source_id], int(s.version))
                        for s in self.snapshot.units
                    ],
                }
                for exposure in self.exposures:
                    eligible.append(
                        assess_revision_reuse(
                            self.bank,
                            review,
                            later_task_id=self.row["attempt_id"],
                            later_cluster=self.row["cluster"],
                            retrieval=retrieval,
                            actor_receipt=exposure["receipt"],
                        )
                    )
            save(self.root / "revision-bank.json", self.bank.checkpoint())
        result = {
            "revision_reuse": eligible,
            "settled_actor_requests": len(self.exposures),
            "expansion": self.expansion.receipt() if self.expansion else None,
            "observable_use": "UNKNOWN",
        }
        save(self.root / "memory-terminal.json", result)
        return result

    def close(self):
        if self.expansion:
            self.expansion.close()


def actor_step(*, provider, budget, memory, native_messages, system_prompt, runtime):
    """The sole solver dispatch path; tested through the real guarded HTTP provider."""
    transport = provider.client._transport
    if not isinstance(transport, FiniteBudgetTransport) or transport.budget is not budget:
        raise ValueError("JOINT_ACTOR_REQUIRES_SHARED_BUDGET_TRANSPORT")
    context = memory.context(budget)
    messages = [
        {
            "role": "system",
            "content": "\n\n".join(text for text in (system_prompt, context, runtime) if text),
        },
        *native_messages,
    ]
    response = provider.generate_message(memory.row["attempt_id"], messages)
    return memory.settled(response.get("content"), provider.last_receipt, messages)


def execute_arm(*, run_root, row, provider, budget, admission_sha256, timeline, memory_args):
    """Run the unchanged native DB/OS tasks with task-private method projection.

    Benchmark sys.path, pinned images and prompt construction are owned by the
    admitted caller, as in the previous native adapter. No endpoint calls on import.
    """
    from src.agents.instance.language_model_agent import LanguageModelAgent
    from src.factories.chat_history_item import ChatHistoryItemFactory
    from src.language_models import LanguageModel
    from src.tasks.instance.db_bench import task as db_module
    from src.tasks.instance.os_interaction import task as os_module
    from src.typings import ChatHistoryItem, Role, SampleStatus, Session, TaskName

    arm_root = run_root / "arms" / row["attempt_id"]
    arm_root.mkdir(parents=True, exist_ok=False)
    save(arm_root / "claim.json", row)
    started, before = time.monotonic(), budget.status()
    task, session, memory = None, None, None
    result = {"attempt_id": row["attempt_id"], "status": "STARTED", "outcome": None}
    try:
        budget.remaining_seconds()
        memory = JointMemory(
            root=arm_root,
            admission_sha256=admission_sha256,
            row=row,
            timeline=timeline,
            **memory_args,
        )
        domain = row["domain"]
        if domain not in {"db_bench", "os_interaction"}:
            raise ValueError("JOINT_DOMAIN_NOT_AUTHORIZED")
        klass = db_module.DBBench if domain == "db_bench" else os_module.OSInteraction
        kwargs = {
            "task_name": TaskName(domain),
            "chat_history_item_factory": ChatHistoryItemFactory(
                str(run_root / "native-prompts" / f"{domain}.json")
            ),
            "data_file_path": str(run_root / f"native-{domain}.json"),
            "max_round": 3 if domain == "db_bench" else 5,
        }
        if domain == "os_interaction":
            kwargs["command_execution_timeout"] = 20
        task = klass(**kwargs)
        session = Session(task_name=task.task_name, sample_index=row["task_id"])
        task.reset(session)
        if (
            session.sample_status == SampleStatus.RUNNING
            and question_digest(session.chat_history.get_item_deep_copy(-1).content)
            != row["query_sha256"]
        ):
            raise ValueError("NATIVE_QUERY_CHANGED")

        class NativeLanguageModel(LanguageModel):
            def __init__(self):
                super().__init__({"user": "user", "agent": "assistant"})

            def _inference(self, batch_chat_history, inference_config_dict, system_prompt):
                responses = []
                for history in batch_chat_history:
                    runtime = actor_runtime_context(
                        LAB,
                        COMMON,
                        action_budget(
                            task.max_round, task.current_round, unit="native interaction"
                        ),
                    )
                    content = actor_step(
                        provider=provider,
                        budget=budget,
                        memory=memory,
                        runtime=runtime,
                        system_prompt=system_prompt,
                        native_messages=self._convert_chat_history_to_message_list(history),
                    )
                    responses.append(ChatHistoryItem(role=Role.AGENT, content=content))
                return responses

        agent = LanguageModelAgent(NativeLanguageModel())
        while session.sample_status == SampleStatus.RUNNING:
            budget.remaining_seconds()
            agent.inference(session)
            task.interact(session)
        task.complete(session)
        result.update(
            status=str(session.sample_status),
            outcome=str(session.evaluation_record.outcome),
            finish_reason=session.finish_reason,
        )
    except BaseException as error:
        result.update(status="FAILED", error_type=type(error).__name__, reason=str(error))
        raise
    finally:
        # Persist failed/settled native facts even if release or memory accounting fails.
        result.update(
            seconds=time.monotonic() - started,
            budget_before=before,
            budget_after=budget.status(),
            provider_usage=provider.task_usage(row["attempt_id"]),
        )
        failures = []

        def finalize(name, callback):
            try:
                callback()
            except BaseException as error:
                failures.append((name, error))

        finalize("save_native_result", lambda: save(arm_root / "result.json", result))
        if session is not None:
            finalize(
                "save_native_session",
                lambda: save(arm_root / "native-session.json", session.model_dump(mode="json")),
            )
        if memory is not None:
            finalize(
                "memory_accounting",
                lambda: memory.finish(
                    result_ref=str(arm_root / "result.json"), costs=result["provider_usage"]
                ),
            )
            finalize("memory_close", memory.close)
        if task is not None:
            finalize("native_release", task.release)
        result["seconds"] = time.monotonic() - started
        if failures:
            result["finalization_failures"] = [
                {"step": name, "error_type": type(error).__name__, "reason": str(error)}
                for name, error in failures
            ]
            if result["status"] != "FAILED":
                result["status"] = "FINALIZATION_FAILED"
        save(arm_root / "result.json", result)
        if failures:
            raise failures[0][1]
    return result
