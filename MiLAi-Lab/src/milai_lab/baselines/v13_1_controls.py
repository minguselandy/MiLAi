"""Opt-in finite B0-B6 controls over the existing Store, Agent and provider APIs.

Archive evidence is immutable original data. Summaries/NL cards are model output,
never verified prose. Receipt projection describes observations, not live state,
object authority or the unknown original execution's missing receipt.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from milai_lab.baselines.benchmark_memories import RawChunk, archived_turns
from milai_lab.baselines.langmem_agent import build_agent
from milai_lab.contracts.scope import FoundationScope
from milai_lab.harness.contextual_artifacts import digest
from milai_lab.methods.contextual_memory.retrieval import IndexEntry, hybrid_order
from milai_lab.methods.langmem_recipe import LangMemRecipeChatModel
from milai_lab.methods.local_state_attention.summary import parse_summary, summary_request

ARMS = frozenset(f"B{index}" for index in range(7))
MATERIAL_HEADER = "[Archived memory material]\n"


def event_id(row: dict[str, Any]) -> str:
    value = row.get("event_id") or row.get("id")
    if type(value) is not str or not value:
        raise ValueError("CONTROL_ORIGINAL_EVENT_ID_REQUIRED")
    return value


def _closed_turns(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # The existing boundary helper requires event_id. An SDK id is an existing
    # identity, not a newly fabricated event_id in the original data carrier.
    aliases = [{**row, "event_id": event_id(row)} for row in records]
    originals = {id(alias): row for alias, row in zip(aliases, records, strict=True)}
    turns, unclosed = archived_turns(aliases)
    if turns and unclosed and all(row["role"] == "system" for row in unclosed):
        # Preserve a leading original system prelude with the first closed turn.
        turns[0]["messages"] = [*unclosed, *turns[0]["messages"]]
        turns[0]["source_ids"] = [event_id(row) for row in turns[0]["messages"]]
        unclosed = []
    for turn in turns:
        turn["messages"] = [originals[id(row)] for row in turn["messages"]]
    return turns, [originals[id(row)] for row in unclosed]


def _summary_turns(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    turns, unclosed = _closed_turns(records)
    completed: list[dict[str, Any]] = []
    for turn in turns:
        if turn["messages"][-1].get("tool_calls"):
            unclosed.extend(turn["messages"])
        else:
            completed.append({**turn, "ordinal": len(completed)})
    return completed, unclosed


def generation_cap(config: dict[str, Any]) -> int:
    cap = config.get("max_calls_per_message", 12)
    if "generation_cap_profile" in config:
        if (
            config["generation_cap_profile"] != "lifecycle_quality_24_v1"
            or type(cap) is not int
            or cap != 24
        ):
            raise ValueError("CONTROL_GENERATION_CAP_PROFILE_INVALID")
    elif type(cap) is not int or not 1 <= cap <= 12:
        raise ValueError("CONTROL_GENERATION_CAP_INVALID")
    return int(cap)


def validate_config(config: dict[str, Any]) -> None:
    controls = config["controls"]
    if type(controls["material_max_tokens"]) is not int or controls["material_max_tokens"] < 1:
        raise ValueError("CONTROL_MATERIAL_BUDGET_INVALID")
    rag, summary = controls["raw_rag"], controls["summary"]
    for name in ("chunk_chars", "chunk_step", "rrf_k", "top_k", "material_max_chars"):
        if type(rag[name]) is not int or rag[name] < 1:
            raise ValueError("CONTROL_RAG_POLICY_INVALID")
    if rag["chunk_step"] > rag["chunk_chars"] or rag["bm25_k1"] != 1.2 or rag["bm25_b"] != 0.75:
        raise ValueError("CONTROL_RAG_POLICY_INVALID")
    for name in ("window_completed_turns", "content_max_chars", "max_tokens"):
        if type(summary[name]) is not int or summary[name] < (
            0 if name == "window_completed_turns" else 1
        ):
            raise ValueError("CONTROL_SUMMARY_POLICY_INVALID")
    for name in (
        "writer_system_prompt",
        "formation_instruction",
        "reader_system_prompt",
        "prompt_only_instruction",
    ):
        if type(config[name]) is not str or not config[name].strip():
            raise ValueError("CONTROL_PROMPT_INVALID:" + name)
    generation_cap(config)


def receipt_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    documents: dict[str, Any] = {}
    unknown: list[dict[str, Any]] = []
    for row in records:
        if row["role"] != "tool":
            continue
        try:
            body = json.loads(row["content"])
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        if body.get("status") == "ORIGINAL_CALL_OUTCOME_UNKNOWN":
            unknown.append({"source_id": event_id(row), "original_record": row})
            # Nested query_receipt is not a new SourceEvent. Only an independently
            # supplied actual query row below can add a query observation.
            continue
        native = body.get("receipt", body)
        tool = row.get("name", row.get("origin"))
        if (
            tool
            in {
                "create_or_update_draft",
                "approve_document_version",
                "publish_approved_document",
                "get_document_status",
            }
            and isinstance(native, dict)
            and type(native.get("document_id")) is str
        ):
            from milai_lab.contracts.memory import RECEIPT_PROFILES

            fields = {
                key: native[key]
                for key, dtype in RECEIPT_PROFILES["document_publication_v1"]["fields"].items()
                if type(native.get(key)) is (int if dtype == "integer" else str)
            }
            observed = {
                "source_id": event_id(row),
                "fields": fields,
                "original_record": row,
                "field_path_prefix": "receipt." if "receipt" in body else "",
            }
            projected = documents.setdefault(native["document_id"], {"history": []})
            projected["history"].append(observed)
            projected["latest_observation"] = observed
            continue
        if (
            tool not in {"reserve_and_label", "complete_label", "get_reservation"}
            or not isinstance(native, dict)
            or type(native.get("reservation_id")) is not str
        ):
            continue
        fields = {
            key: native[key] for key in ("status", "label_status") if type(native.get(key)) is str
        }
        observed = {
            "source_id": event_id(row),
            "fields": fields,
            "original_record": row,
            "field_path_prefix": "receipt." if "receipt" in body else "",
        }
        object_id = native["reservation_id"]
        projected = objects.setdefault(object_id, {"history": []})
        projected["history"].append(observed)
        projected["latest_observation"] = observed
    return {
        "objects": objects,
        **({"documents": documents} if documents else {}),
        "unknown": unknown,
        "contract": "original_observations_only; no live applicability or object authorization",
    }


class ControlsBackend:
    def __init__(
        self,
        store: BaseStore,
        saver: BaseCheckpointSaver[Any],
        run_id: str,
        arm: str,
        owner: str,
        config: dict[str, Any],
        model: LangMemRecipeChatModel,
        embeddings: Any,
    ) -> None:
        validate_config(config)
        if arm not in ARMS or not all((run_id, owner)):
            raise ValueError("CONTROL_SCOPE_INVALID")
        self.store, self.saver, self.run_id, self.arm, self.owner = store, saver, run_id, arm, owner
        self.config, self.model, self.embeddings = config, model, embeddings
        if (
            model.client.budget is None
            or model.client.capacity is None
            or model.capacity_path is None
            or model.max_calls_per_message != config.get("max_calls_per_message", 12)
        ):
            raise ValueError("CONTROL_METERED_PERSISTENT_ADMISSION_REQUIRED")
        self.namespace = ("v13_1_controls", run_id, arm, owner)
        self.nl_namespace = ("langmem", run_id, arm, owner)
        self.identity = digest({"arm": arm, "owner": owner, "config": config})

    def _owner(self, owner: str) -> None:
        if owner != self.owner:
            raise ValueError("CONTROL_OWNER_SCOPE_MISMATCH")

    def _state(self) -> dict[str, Any]:
        item = self.store.get(self.namespace, "state")
        if item is None:
            return {
                "identity": self.identity,
                "archive": [],
                "boundaries": {},
                "index": {},
                "summary": "",
                "covered_ordinal": -1,
                "projection": {},
            }
        if item.value["identity"] != self.identity:
            raise ValueError("CONTROL_PERSISTENT_IDENTITY_CHANGED")
        return item.value

    def _put(self, value: dict[str, Any]) -> None:
        self.store.put(self.namespace, "state", value, index=False)

    def _records(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.store.search(self.nl_namespace, limit=100, offset=offset)
            result.extend(
                {"id": item.key, "value": item.value}
                for item in page
                if item.namespace == self.nl_namespace
            )
            if len(page) < 100:
                return result
            offset += len(page)

    def snapshot(self, owner: str) -> dict[str, Any]:
        self._owner(owner)
        state = (
            self._state()
            if self.arm != "B0"
            else {"archive": [], "boundaries": {}, "projection": {}}
        )
        return {**state, "records": self._records() if self.arm in {"B4", "B5"} else []}

    def _chunks(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        policy = self.config["controls"]["raw_rag"]
        chunks: list[dict[str, Any]] = []
        for row in records:
            if self.arm == "B6" and row["role"] != "tool":
                continue
            text = json.dumps(row, ensure_ascii=False)
            for start in range(0, len(text), policy["chunk_step"]):
                end = min(start + policy["chunk_chars"], len(text))
                chunks.append(
                    asdict(
                        RawChunk(
                            digest([event_id(row), start, end, text[start:end]]),
                            event_id(row),
                            start,
                            end,
                            text[start:end],
                        )
                    )
                )
                if end == len(text):
                    break
        return chunks

    def ingest(self, owner: str, boundary_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Only closed past records. No query/question/task/gold argument exists."""
        return self._ingest(owner, boundary_id, records, archive_fragment=False)

    def ingest_archive(
        self, owner: str, boundary_id: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Opt-in original past archive fragments, including orphan/unclosed rows.

        The caller supplies chronological past data only. No task or reader
        question is accepted; rows are never repaired or synthetically closed.
        """
        return self._ingest(owner, boundary_id, records, archive_fragment=True)

    def _ingest(
        self,
        owner: str,
        boundary_id: str,
        records: list[dict[str, Any]],
        *,
        archive_fragment: bool,
    ) -> dict[str, Any]:
        self._owner(owner)
        if not boundary_id or not records:
            raise ValueError("CONTROL_CLOSED_BOUNDARY_REQUIRED")
        records = json.loads(json.dumps(records, ensure_ascii=False, allow_nan=False))
        for row in records:
            event_id(row)
            if (
                row.get("role") not in {"user", "assistant", "tool", "system"}
                or type(row.get("content")) is not str
                or row.get("owner", owner) != owner
            ):
                raise ValueError("CONTROL_ORIGINAL_RECORD_INVALID")
        if not archive_fragment:
            turns, unclosed = _closed_turns(records)
            if (
                unclosed
                or not turns
                or any(turn["messages"][-1].get("tool_calls") for turn in turns)
            ):
                raise ValueError("CONTROL_UNCLOSED_EVENT_BOUNDARY")
        if self.arm == "B0":
            return {
                "status": "COMPLETED",
                "persistent_memory": False,
                "source_sha256": digest(records),
            }
        state = self._state()
        source_hash = digest(records)
        old_boundary = state["boundaries"].get(boundary_id)
        if old_boundary is not None:
            if old_boundary["source_sha256"] != source_hash:
                raise ValueError("CONTROL_BOUNDARY_CHANGED")
            return {
                "status": "no_change"
                if old_boundary["status"] == "COMPLETED"
                else "MAINTENANCE_INCOMPLETE",
                "boundary": old_boundary,
            }
        seen = {event_id(row): row for row in state["archive"]}
        added: list[dict[str, Any]] = []
        for row in records:
            key = event_id(row)
            if key in seen and seen[key] != row:
                raise ValueError("CONTROL_ORIGINAL_EVENT_CHANGED")
            if key not in seen:
                added.append(row)
                seen[key] = row
        state["archive"].extend(added)
        state["boundaries"][boundary_id] = {"status": "RAW_CAPTURED", "source_sha256": source_hash}
        if archive_fragment:
            state["boundaries"][boundary_id]["input_mode"] = "past_archive_fragment"
        self._put(state)
        agent = None
        try:
            if self.arm in {"B2", "B6"}:
                chunks = self._chunks(state["archive"])
                previous = state["index"]
                retained = dict(
                    zip(
                        (c["id"] for c in previous.get("chunks", [])),
                        previous.get("vectors", []),
                        strict=True,
                    )
                )
                missing = [c for c in chunks if c["id"] not in retained]
                vectors = self.embeddings.embed_documents([c["content"] for c in missing])
                retained.update(zip((c["id"] for c in missing), vectors, strict=True))
                state["index"] = {"chunks": chunks, "vectors": [retained[c["id"]] for c in chunks]}
                if self.arm == "B6":
                    state["projection"] = receipt_projection(state["archive"])
            elif self.arm == "B3":
                all_turns, _ = _summary_turns(state["archive"])
                policy = self.config["controls"]["summary"]
                stop = max(0, len(all_turns) - policy["window_completed_turns"])
                newly_covered = all_turns[state["covered_ordinal"] + 1 : stop]
                if newly_covered:
                    messages, schema = summary_request(
                        state["summary"], newly_covered, policy["content_max_chars"]
                    )
                    self.model._reserve_request()
                    client, original = self.model.client, self.model.client.config
                    try:
                        client.config = replace(original, max_tokens=policy["max_tokens"])
                        receipt = client.chat(messages, response_format=schema)
                    finally:
                        client.config = original
                    state["summary"] = parse_summary(receipt, policy["content_max_chars"])
                    state["covered_ordinal"] = newly_covered[-1]["ordinal"]
            elif self.arm in {"B4", "B5"}:
                scope = FoundationScope(self.run_id, self.arm, owner, "writer:" + boundary_id)
                prompt = self.config["writer_system_prompt"]
                if self.arm == "B5":
                    prompt += "\n" + self.config["prompt_only_instruction"]
                agent = build_agent(
                    self.model,
                    self.store,
                    self.saver,
                    memory_contract="strict",
                    system_prompt=prompt,
                )
                result = agent.invoke(
                    {
                        "messages": [
                            HumanMessage(
                                content=(
                                    self.config["formation_instruction"]
                                    + "\n\n[Archived conversation data]\n"
                                    + json.dumps(records, ensure_ascii=False)
                                ),
                                id="archive-" + boundary_id,
                            )
                        ]
                    },
                    config=scope.config(),
                    durability="sync",
                )
                state["boundaries"][boundary_id]["writer_messages"] = [
                    row.model_dump(mode="json") for row in result["messages"]
                ]
            state["boundaries"][boundary_id]["status"] = "COMPLETED"
            self._put(state)
            return {"status": "COMPLETED", "boundary": state["boundaries"][boundary_id]}
        except Exception as error:
            state["boundaries"][boundary_id].update(
                status="MAINTENANCE_INCOMPLETE", error_type=type(error).__name__, error=str(error)
            )
            if agent is not None:
                try:
                    state["boundaries"][boundary_id]["writer_messages"] = [
                        row.model_dump(mode="json")
                        for row in agent.get_state(scope.config()).values.get("messages", [])
                    ]
                except Exception as readback_error:
                    state["boundaries"][boundary_id]["readback_error"] = str(readback_error)
            self._put(state)
            raise

    def _material(self, value: Any) -> str:
        return MATERIAL_HEADER + json.dumps(value, ensure_ascii=False)

    def _fits(self, text: str) -> bool:
        capacity = self.model.client.capacity
        if capacity is None:
            raise ValueError("CONTROL_HOST_TOKENIZER_CAPACITY_REQUIRED")
        return bool(
            len(text) <= self.config["controls"]["raw_rag"]["material_max_chars"]
            and capacity.text_tokens(text) <= self.config["controls"]["material_max_tokens"]
        )

    def recall(self, owner: str, query: str) -> dict[str, Any]:
        self._owner(owner)
        if self.arm == "B0":
            return {"material": "", "delivered_ids": [], "omitted_ids": [], "material_tokens": 0}
        state = self._state()
        rows: list[dict[str, Any]] = []
        omitted: list[str] = []
        ranked: list[str] = []
        ranked_rows: list[dict[str, Any]] = []
        if any(row["status"] != "COMPLETED" for row in state["boundaries"].values()):
            raise ValueError("CONTROL_MAINTENANCE_INCOMPLETE")
        if self.arm in {"B1", "B3"}:
            if self.arm == "B1":
                value = {"original_records": state["archive"]}
            else:
                turns, unclosed = _summary_turns(state["archive"])
                recent_ids = {event_id(row) for row in unclosed}
                recent_ids.update(
                    event_id(row)
                    for turn in turns
                    if turn["ordinal"] > state["covered_ordinal"]
                    for row in turn["messages"]
                )
                value = {
                    "model_generated_summary": state["summary"],
                    "covered_ordinal": state["covered_ordinal"],
                    "recent_original_records": [
                        row for row in state["archive"] if event_id(row) in recent_ids
                    ],
                }
            material = self._material(value)
            if not self._fits(material):
                raise ValueError("CONTROL_MATERIAL_CAPACITY_EXCEEDED")
            delivered = (
                [event_id(row) for row in state["archive"]]
                if self.arm == "B1"
                else [event_id(row) for row in value["recent_original_records"]]
            )
            omitted, ranked = [], []
        else:
            if self.arm in {"B4", "B5"}:
                page = self.store.search(
                    self.nl_namespace,
                    query=query,
                    limit=self.config["controls"]["raw_rag"]["top_k"],
                )
                ranked_rows = [
                    {"id": item.key, "value": item.value}
                    for item in page
                    if item.namespace == self.nl_namespace
                ]
            else:
                index = state["index"]
                chunks = index.get("chunks", [])
                order = (
                    hybrid_order(
                        [IndexEntry(c["id"], c["source_id"], c["content"]) for c in chunks],
                        query,
                        index.get("vectors", []),
                        self.embeddings.embed_query(query),
                        rrf_k=self.config["controls"]["raw_rag"]["rrf_k"],
                    )
                    if chunks
                    else []
                )
                ranked_rows = [chunks[i] for i in order]
            ranked = [row["id"] for row in ranked_rows]
            rows, omitted = [], []
            for row in ranked_rows[: self.config["controls"]["raw_rag"]["top_k"]]:
                proposed = {**row}
                if self.arm == "B6":
                    source_id = row["source_id"]
                    proposed["observed_projection"] = {
                        "objects": {
                            key: obj
                            for key, obj in state["projection"]["objects"].items()
                            if any(h["source_id"] == source_id for h in obj["history"])
                        },
                        "unknown": [
                            u for u in state["projection"]["unknown"] if u["source_id"] == source_id
                        ],
                    }
                    if "documents" in state["projection"]:
                        proposed["observed_projection"]["documents"] = {
                            key: obj
                            for key, obj in state["projection"]["documents"].items()
                            if any(h["source_id"] == source_id for h in obj["history"])
                        }
                if self._fits(self._material([*rows, proposed])):
                    rows.append(proposed)
                else:
                    omitted.append(row["id"])
            material = self._material(rows)
            if not self._fits(material):
                raise ValueError("CONTROL_MATERIAL_CAPACITY_EXCEEDED")
            delivered = [row["id"] for row in rows]
        capacity = self.model.client.capacity
        assert capacity is not None
        return {
            "material": material,
            "query": query,
            "delivered_ids": delivered,
            "omitted_ids": omitted,
            "ranked_ids": ranked,
            "material_tokens": capacity.text_tokens(material),
            "semantic_evidence": False,
        }

    def read_text(
        self, owner: str, question: str, *, system_prompt: str | None = None
    ) -> dict[str, Any]:
        material = self.recall(owner, question)
        prompt = system_prompt or self.config["reader_system_prompt"]
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": material["material"] + "\n\n" + question},
        ]
        self.model._reserve_request()
        result = self.model.client.chat(messages)
        choice = result["choices"][0]
        if choice["finish_reason"] != "stop" or type(choice["message"].get("content")) is not str:
            raise ValueError("CONTROL_READER_RESPONSE_INCOMPLETE")
        return {
            **material,
            "response": result,
            "answer": result["choices"][0]["message"]["content"],
        }

    def reader_agent(
        self,
        *,
        business_tools: Sequence[BaseTool] = (),
        business_call_wrapper: Any = None,
        environment_rules: str = "",
        observer: Any = None,
    ) -> Any:
        if self.model.client.config.tool_mode == "json_action" and not business_tools:
            raise ValueError(
                "CONTROL_READER_AGENT_PUBLIC_TOOLS_REQUIRED; use read_text for text only"
            )
        selected: dict[str, Any] = {}

        def hook(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
            cfg = config["configurable"]
            if (cfg["foundation_run_id"], cfg["arm_id"], cfg["user_id"]) != (
                self.run_id,
                self.arm,
                self.owner,
            ):
                raise ValueError("CONTROL_OWNER_SCOPE_MISMATCH")
            messages = state["messages"]
            start = next(
                i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)
            )
            key = str(cfg["thread_id"]) + ":" + str(messages[start].id)
            if key not in selected:
                selected[key] = self.recall(self.owner, str(messages[start].content))
                if self.model.client.emit is not None:
                    self.model.client.emit(
                        {
                            "event": "control_material",
                            "message_key": key,
                            "arm": self.arm,
                            **selected[key],
                        }
                    )
            prompt = self.config["reader_system_prompt"] + (
                "\n" + environment_rules if environment_rules else ""
            )
            if selected[key]["material"]:
                prompt += "\n" + selected[key]["material"]
            # The native episode/thread is lawful short-term context for every
            # arm, including B0. Only retrieval query selection uses latest Human.
            return {"llm_input_messages": [SystemMessage(content=prompt), *messages]}

        return build_agent(
            self.model,
            self.store,
            self.saver,
            business_tools,
            business_call_wrapper=business_call_wrapper,
            observer=observer,
            memory_tools=(),
            benchmark_view_hook=hook,
        )


def merit_adapters(
    runtime: Any, run_id: str, arm: str, config: dict[str, Any], embeddings: Any
) -> tuple[Callable[..., Any], Callable[..., None]]:
    """Direct agent_factory/public_turn_callback injection into existing langmem_merit.

    No dataset/scorer import, future episode query or hidden world read. The native
    caller supplies its unchanged tools, journal and environment rules.
    """
    backends: dict[str, ControlsBackend] = {}

    def factory(
        model: Any,
        store: BaseStore,
        checkpointer: Any,
        business_tools: Any,
        *,
        user_id: str,
        environment_rules: str,
        **kwargs: Any,
    ) -> Any:
        backend = backends[user_id] = ControlsBackend(
            store, checkpointer, run_id, arm, user_id, config, model, embeddings
        )
        return backend.reader_agent(
            business_tools=business_tools, environment_rules=environment_rules, **kwargs
        )

    def completed(
        agent: Any,
        scope: FoundationScope,
        public_index: int,
        status: str,
        business_calls: list[dict[str, Any]],
    ) -> None:
        if status != "COMPLETED":
            return
        messages = agent.get_state(scope.config()).values["messages"]
        starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
        end = starts[public_index + 1] if public_index + 1 < len(starts) else len(messages)
        original = []
        for message in messages[starts[public_index] : end]:
            row = message.model_dump(mode="json")
            # Keep every original SDK field; add a mechanical role field for the
            # canonical data carrier, without rewriting content/tool results/time.
            role_types = (
                (HumanMessage, "user"),
                (AIMessage, "assistant"),
                (ToolMessage, "tool"),
                (SystemMessage, "system"),
            )
            role = next((role for cls, role in role_types if isinstance(message, cls)), None)
            if role is None:
                raise ValueError("CONTROL_ORIGINAL_MESSAGE_ROLE_UNSUPPORTED")
            row["role"] = role
            original.append(row)
        key = str(scope.config()["configurable"]["thread_id"]) + f":{public_index}"
        backends[scope.user_id].ingest(scope.user_id, key, original)

    return factory, completed
