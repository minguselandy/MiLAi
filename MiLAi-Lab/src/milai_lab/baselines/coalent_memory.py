"""Native Coalent pool research adapter on the registered MiLAi retrieval lifecycle."""
from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from milai_lab.baselines.coalent_store import SourceRetriever, StoreCognitionStore
from milai_lab.memory.functional import normalize_read_goal
from milai_lab.memory.functional_state import (
    FunctionalRejection,
    body_text,
    canonical,
    namespace,
    note_exposure,
    reference_key,
)
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.methods.evidence_reading import project_packs
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory, retrieval_packet


class CoalentRetrievalMemory(IntentRetrievalMemory):
    """Use upstream pool selection while keeping native admission/snapshots/refs.

    One cache-interface read and each actual source retrieval/original reopening
    consume ordinary read admission and the declared operation limit. Upstream
    synthesis additionally uses the Host's existing model-call admission. These
    are composite cache operations, not learned finite-action decisions.
    """

    def __init__(self, *args: Any,
                 coalent_factory: Callable[[SourceRetriever, StoreCognitionStore], Any],
                 coalent_settings: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.replay_initial_observation is not None or self.control_intervention is not None:
            raise ValueError("COALENT_FINITE_ACTION_REPLAY_UNSUPPORTED")
        self.coalent_factory = coalent_factory
        self.coalent_artifact_scope = coalent_settings.get("source_artifact_scope", "session")
        self.policy["coalent"] = canonical({**coalent_settings,
                                            "source_artifact_scope": self.coalent_artifact_scope})

    def _execute_retrieval(self, config: RunnableConfig, call_id: str,
                           request: RetrievalRequest, key: str,
                           bound: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        limit = min(self.material_limit, request.limits.max_return_tokens or self.material_limit)
        steps = min(self.control_steps, request.limits.max_control_steps
                    if request.limits.max_control_steps is not None else self.control_steps)
        saved: dict[str, Any] = {"schema": "milai_retrieval_snapshot_v1", "status": "started",
                                "request": request.project(), "return_limit": limit}
        self.service.store.put(namespace(self.service), key, saved, index=False)
        trace: list[dict[str, Any]] = []
        exposed: set[str] = set()
        known: list[dict[str, Any]] = []
        rejections = 0

        def admitted(kind: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
            if len(trace) >= steps:
                raise FunctionalRejection("COALENT_OPERATION_LIMIT_EXHAUSTED")
            index = len(trace)
            entry: dict[str, Any] = {"step": index, "selected": kind,
                "selection_mode": "external_method", "actions": []}
            trace.append(entry)
            receipt = self._read(config, f"{call_id}:coalent:{index}",
                {"tool": "search_memory" if kind == "source_search" else "memory_control",
                 "request": request.project(), "operation": kind},
                lambda _: action(), deliver_material=False)
            entry["result"] = receipt
            return receipt

        def search(query: str, scope: str | None) -> list[str]:
            def run() -> dict[str, Any]:
                found = self.service.search_sources(query, limit=self.source_top_k,
                    excluded_source_refs=(bound["source_ref"],),
                    tokenization=self.source_tokenization)
                refs = list(dict.fromkeys(span["source_ref"]
                    for item in found["source_materials"] for span in item["source_ranges"]))
                exposed.update(refs)
                return {"ok": True, "source_refs": refs}
            receipt = admitted("source_search", run)
            if not receipt["ok"]:
                raise FunctionalRejection(receipt["status"])
            return cast(list[str], receipt["source_refs"])

        def usage() -> dict[str, Any]:
            return {"control_steps": len(trace), "known_reference_reads": len(known),
                    "operations": len(trace),
                    "read_operations": sum(t["selected"] in {"source_search", "original_read"}
                                           for t in trace),
                    "material_budget_rejections": rejections}

        def fits(materials: list[dict[str, Any]], rejected: int) -> bool:
            upper = {"control_steps": steps, "known_reference_reads": len(known),
                     "operations": steps, "read_operations": steps,
                     "material_budget_rejections": rejected}
            return self.return_tokens(retrieval_packet(key, materials,
                list(range(len(materials))), list(range(len(materials))),
                "external_cache_handoff", upper)) <= limit

        def run_cache() -> dict[str, Any]:
            nonlocal rejections
            persistence = StoreCognitionStore(self.service)
            cache = self.coalent_factory(SourceRetriever(self.service, search, self.control_record,
                artifact_scope=self.coalent_artifact_scope),
                                         persistence)
            sync = persistence.sync_sources(cache, excluded_source_refs=(bound["source_ref"],))
            exposed.update(sync["checked_source_refs"])
            self.control_record({"event": "coalent_source_sync", **sync})
            # Literal public request and actual known receipts retain rich information.
            # No task labels, hidden requirements or source-family identifiers are added.
            query = canonical({"request": request.project(),
                               "known_evidence": project_packs(known, list(range(len(known))))})
            result = cache.get(query, namespace=self.coalent_artifact_scope)
            units = {claim.unit_id: persistence.get(claim.unit_id) for claim in result.pool}
            bindings_by_unit = {}
            for uid, unit in units.items():
                bindings = {}
                for span in unit.provenance.source_spans:
                    for binding in persistence.source_bindings(span.artifact_id, span.version):
                        bindings[binding["source_ref"], binding["source_revision"]] = binding
                bindings_by_unit[uid] = list(bindings.values())
            source_refs = list(dict.fromkeys(binding["source_ref"]
                for bindings in bindings_by_unit.values() for binding in bindings))
            exposed.update(source_refs)
            goal = normalize_read_goal(request.read_goal)
            originals = isinstance(goal, dict) and "original_source" in goal.get("evidence", [])
            raw_artifacts = dict.fromkeys((c.artifact_id, c.version) for c in result.evidence)
            raw_refs = list(dict.fromkeys([
                *(binding["source_ref"] for artifact, version in raw_artifacts
                  for binding in persistence.source_bindings(artifact, version)), *source_refs]))
            max_rejections = len(result.pool) + len(raw_refs)
            materials: list[dict[str, Any]] = []
            if not originals:
                view: dict[str, Any] = {"kind": "query_structure", "id": key + ":coalent",
                    "revision": 1, "query_time": request.task_context.as_of or "",
                    "body_delivered": True, "visibility": "visible", "source_bindings": {},
                    "semantics": "Coalent model-derived claims with unit-level source provenance; "
                                 "not original quotations or verified entailment. "
                                 "Conditions remain "
                                 "in the literal claim text. Immutable per-call material snapshot.",
                    "structure": {"scope": "Upstream Coalent selected claim pool",
                                  "nodes": {}, "rules": {}, "unresolved": []}}
                if result.needs_retrieval:
                    view["structure"]["unresolved"].append("Upstream cache reports undercoverage.")
                for claim in result.pool:
                    candidate = copy.deepcopy(view)
                    bindings = candidate["source_bindings"]
                    aliases = {value["source_ref"]: name for name, value in bindings.items()}
                    evidence = []
                    for binding in bindings_by_unit[claim.unit_id]:
                        alias = aliases.setdefault(binding["source_ref"], f"e{len(aliases)}")
                        bindings[alias] = {**binding, "unit_metadata": copy.deepcopy(
                            units[claim.unit_id].source_meta)}
                        evidence.append(alias)
                    candidate["structure"]["nodes"][f"n{len(view['structure']['nodes'])}"] = {
                        "text": claim.claim, "kind": "inferred", "evidence": evidence}
                    if fits([candidate], max_rejections):
                        view = candidate
                    else:
                        rejections += 1
                if view["structure"]["nodes"]:
                    materials.append(view)
            if originals or result.escalated:
                refs = raw_refs
                def read_originals() -> dict[str, Any]:
                    grouped: dict[str, list[dict[str, Any]]] = {}
                    for ref in refs:
                        source = self.service.source(ref)
                        if source is not None:
                            grouped.setdefault(source["session"], []).append({
                                "source_ref": ref,
                                "source_revision": source.get("source_revision", 1),
                                "start": 0, "end": len(body_text(source))})
                    packs = [{"kind": "original_source",
                              "id": reference_key(["coalent_originals", session]),
                              "session_id": session, "turn_range": [0, len(spans)],
                              "source_ranges": spans} for session, spans in grouped.items()]
                    exposed.update(refs)
                    return {"ok": True, "materials": self.service.read_source_materials(packs)}
                receipt = admitted("original_read", read_originals)
                if not receipt["ok"]:
                    raise FunctionalRejection(receipt["status"])
                for item in receipt["materials"]:
                    # Session artifacts govern cache freshness, not return granularity.
                    # Keep complete messages in retrieved order within the full wire budget.
                    turns: list[dict[str, Any]] = []
                    spans: list[dict[str, Any]] = []
                    selected = None
                    for turn, span in zip(json.loads(item["text"]), item["source_ranges"],
                                          strict=True):
                        candidate = {**item, "text": json.dumps([*turns, turn],
                                                                ensure_ascii=False),
                            "source_ranges": [*spans, span], "unavailable_source_ranges": [],
                            "turn_range": [0, len(turns) + 1],
                            "date": (turns[0] if turns else turn)["timestamp"],
                            "body_delivered": True, "visibility": "visible", "truncated": False}
                        if fits([*materials, candidate], max_rejections):
                            turns.append(turn)
                            spans.append(span)
                            selected = candidate
                        else:
                            rejections += 1
                    if selected is not None:
                        materials.append(selected)
            self.control_record({"event": "coalent_cache_result", "cache_hit": result.cache_hit,
                "coverage": result.coverage, "needs_retrieval": result.needs_retrieval,
                "escalated": result.escalated, "upstream_pool": [
                    {"claim": c.claim, "unit_id": c.unit_id, "score": c.score}
                    for c in result.pool],
                "raw_source_refs": raw_refs,
                "raw_artifacts": list(raw_artifacts),
                "stats": cache.stats(), "usage": usage()})
            return {"ok": True, "materials": materials}

        receipt: dict[str, Any] = {"ok": True, "materials": []}
        cache_attempted = False
        if request.task_context.known_evidence_refs and steps:
            receipt = admitted("known_read", lambda: {
                "ok": True, "materials": self._known_materials(request)})
            if receipt["ok"]:
                known = receipt["materials"]
                exposed.update(span["source_ref"] for item in known for span in [
                    *item.get("source_ranges", []), *item.get("source_bindings", {}).values()])
                receipt = {"ok": True, "materials": []}
        if receipt["ok"] and len(trace) < steps:
            cache_attempted = True
            receipt = admitted("cache_read", run_cache)
        reason = ("external_cache_handoff" if receipt["ok"] and cache_attempted
                  else "budget_exhausted" if receipt["ok"] else "operation_outcome_unknown"
                  if receipt["status"] == "read_outcome_unknown" else receipt["status"])
        saved.update(status="completed", ok=receipt["ok"], reason=reason,
            materials=receipt.get("materials", []) if receipt["ok"] else [],
            usage=usage(), wall_seconds=time.perf_counter() - started, engine_receipt=receipt)
        packet = self._retrieval_result(key, saved)
        saved["delivered_indices"] = [item["ref"]["item_index"] for item in packet["evidence"]]
        self.service.store.put(namespace(self.service), key, saved, index=False)
        with self.service._locked():
            note_exposure(self.service, bound["source_ref"], sorted(exposed))
        self.control_record({"event": "milai_retrieve_result", "call_id": call_id,
            "request": request.project(), "result": packet,
            "retrieval_wall_seconds": saved["wall_seconds"],
            "control": {"engine": "coalent_native_pool", "trace": trace,
                        "state": {"views": [], "known_evidence": project_packs(
                            known, list(range(len(known))))}}})
        return packet
