from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from milai.application.memory_context_core.activation import (
    _LOCAL_CONTEXT as _LOCAL_CONTEXT,
)
from milai.application.memory_context_core.activation import (
    _MULTI_SESSION as _MULTI_SESSION,
)
from milai.application.memory_context_core.activation import (
    _QUERY_STOPWORDS as _QUERY_STOPWORDS,
)
from milai.application.memory_context_core.activation import _TERM as _TERM
from milai.application.memory_context_core.activation import _VALUE as _VALUE
from milai.application.memory_context_core.activation import (
    _admissible_conditional_gain as _admissible_conditional_gain,
)
from milai.application.memory_context_core.activation import (
    _answer_signal as _answer_signal,
)
from milai.application.memory_context_core.activation import (
    _breadth_first_binding_spans as _breadth_first_binding_spans,
)
from milai.application.memory_context_core.activation import (
    _candidate_item_sort_key as _candidate_item_sort_key,
)
from milai.application.memory_context_core.activation import (
    _canonical_item_identity as _canonical_item_identity,
)
from milai.application.memory_context_core.activation import (
    _canonical_item_sort_key as _canonical_item_sort_key,
)
from milai.application.memory_context_core.activation import (
    _conditional_activation_thresholds as _conditional_activation_thresholds,
)
from milai.application.memory_context_core.activation import (
    _derived_operand_views as _derived_operand_views,
)
from milai.application.memory_context_core.activation import (
    _evidence_views as _evidence_views,
)
from milai.application.memory_context_core.activation import (
    _fallback_decision_snapshot as _fallback_decision_snapshot,
)
from milai.application.memory_context_core.activation import (
    _legacy_session_identity as _legacy_session_identity,
)
from milai.application.memory_context_core.activation import (
    _local_context_activation as _local_context_activation,
)
from milai.application.memory_context_core.activation import (
    _normalized_unit_semantics as _normalized_unit_semantics,
)
from milai.application.memory_context_core.activation import (
    _query_terms as _query_terms,
)
from milai.application.memory_context_core.activation import (
    _required_requirement_ids as _required_requirement_ids,
)
from milai.application.memory_context_core.activation import (
    _stable_evidence_views as _stable_evidence_views,
)
from milai.application.memory_context_core.activation import (
    _structured_source_context as _structured_source_context,
)
from milai.application.memory_context_core.activation import (
    _without_presentation_budget as _without_presentation_budget,
)
from milai.application.memory_context_core.common import (
    _authority_class as _authority_class,
)
from milai.application.memory_context_core.common import (
    _estimated_tokens as _estimated_tokens,
)
from milai.application.memory_context_core.common import (
    _positions as _positions,
)
from milai.application.memory_context_core.common import (
    _sha256 as _sha256,
)
from milai.application.memory_context_core.common import (
    _string_values as _string_values,
)
from milai.application.memory_context_core.common import (
    _sufficiency_status as _sufficiency_status,
)
from milai.application.memory_context_core.common import (
    _unique as _unique,
)
from milai.application.memory_context_core.contracts import (
    ContextCompilation as ContextCompilation,
)
from milai.application.memory_context_core.contracts import (
    ContextPlanCompilation as ContextPlanCompilation,
)
from milai.application.memory_context_core.contracts import (
    ContextTokenAccountingError as ContextTokenAccountingError,
)
from milai.application.memory_context_core.contracts import (
    EvidenceAdjacencyReader as EvidenceAdjacencyReader,
)
from milai.application.memory_context_core.provenance import (
    _canonical_item_sources as _canonical_item_sources,
)
from milai.application.memory_context_core.provenance import (
    _canonical_sources as _canonical_sources,
)
from milai.application.memory_context_core.provenance import (
    _operand_sources as _operand_sources,
)
from milai.application.memory_context_core.provenance import (
    _provenance_values as _provenance_values,
)
from milai.application.memory_context_core.provenance import (
    _required_sources as _required_sources,
)
from milai.application.memory_context_core.receipts import (
    _RECEIPT_ALIAS_HEADER as _RECEIPT_ALIAS_HEADER,
)
from milai.application.memory_context_core.receipts import (
    _RECEIPT_WINDOW_HEADER as _RECEIPT_WINDOW_HEADER,
)
from milai.application.memory_context_core.receipts import (
    _evidence_receipt as _evidence_receipt,
)
from milai.application.memory_context_core.receipts import (
    _receipt_mapping as _receipt_mapping,
)
from milai.application.memory_context_core.receipts import (
    _requires_multiple_sessions as _requires_multiple_sessions,
)
from milai.application.memory_context_core.receipts import (
    _semantic_context_material as _semantic_context_material,
)
from milai.application.memory_context_core.rendering import (
    _derived_context as _derived_context,
)
from milai.application.memory_context_core.rendering import (
    _excerpt_at as _excerpt_at,
)
from milai.application.memory_context_core.rendering import (
    _excerpt_focus as _excerpt_focus,
)
from milai.application.memory_context_core.rendering import (
    _fit_derived as _fit_derived,
)
from milai.application.memory_context_core.rendering import (
    _fit_derived_with_windows as _fit_derived_with_windows,
)
from milai.application.memory_context_core.rendering import (
    _fit_window as _fit_window,
)
from milai.application.memory_context_core.rendering import (
    _fit_windows_together as _fit_windows_together,
)
from milai.application.memory_context_core.rendering import (
    _focused_excerpt as _focused_excerpt,
)
from milai.application.memory_context_core.rendering import (
    _open_issue_ids as _open_issue_ids,
)
from milai.application.memory_context_core.rendering import (
    _reader_derived_completeness as _reader_derived_completeness,
)
from milai.application.memory_context_core.rendering import (
    _reader_derived_value as _reader_derived_value,
)
from milai.application.memory_context_core.rendering import (
    _render_context as _render_context,
)
from milai.application.memory_context_core.rendering import (
    _reserve_required_windows as _reserve_required_windows,
)
from milai.application.memory_context_core.semantics import (
    _OPAQUE_READER_KEYS as _OPAQUE_READER_KEYS,
)
from milai.application.memory_context_core.semantics import (
    _query_ir_enumerates_members as _query_ir_enumerates_members,
)
from milai.application.memory_context_core.semantics import (
    _query_ir_has_temporal_constraint as _query_ir_has_temporal_constraint,
)
from milai.application.memory_context_core.semantics import (
    _query_ir_operator_family as _query_ir_operator_family,
)
from milai.application.memory_context_core.semantics import (
    _reader_semantic_value as _reader_semantic_value,
)
from milai.application.memory_context_core.semantics import (
    _validated_operand as _validated_operand,
)
from milai.application.memory_context_core.trace import (
    _acquired_candidate_trace as _acquired_candidate_trace,
)
from milai.application.memory_context_core.trace import (
    _admitted_evidence_trace as _admitted_evidence_trace,
)
from milai.application.memory_context_core.trace import (
    _bound_evidence_trace as _bound_evidence_trace,
)
from milai.application.memory_context_core.trace import (
    _evidence_lifecycle_trace as _evidence_lifecycle_trace,
)
from milai.application.memory_context_core.trace import (
    _reader_boundary_trace as _reader_boundary_trace,
)
from milai.application.memory_context_core.trace import (
    _reader_visible_trace as _reader_visible_trace,
)
from milai.application.memory_context_core.units import (
    _reader_unit as _reader_unit,
)
from milai.application.memory_context_core.units import (
    _render_infeasible_context as _render_infeasible_context,
)
from milai.application.memory_context_core.units import (
    _render_reader_units as _render_reader_units,
)
from milai.application.memory_context_core.units import (
    _status_unit_text as _status_unit_text,
)
from milai.application.memory_context_core.windows import (
    _SOFT_SESSION_DIVERSITY_PREFIX as _SOFT_SESSION_DIVERSITY_PREFIX,
)
from milai.application.memory_context_core.windows import (
    _SOFT_WINDOW_TOKEN_CAP as _SOFT_WINDOW_TOKEN_CAP,
)
from milai.application.memory_context_core.windows import (
    _WORKSPACE_WRAPPER_TERMS as _WORKSPACE_WRAPPER_TERMS,
)
from milai.application.memory_context_core.windows import (
    _bounded_window_members as _bounded_window_members,
)
from milai.application.memory_context_core.windows import (
    _build_windows as _build_windows,
)
from milai.application.memory_context_core.windows import (
    _instance_preserving_window_order as _instance_preserving_window_order,
)
from milai.application.memory_context_core.windows import (
    _linked_context_neighbor as _linked_context_neighbor,
)
from milai.application.memory_context_core.windows import (
    _marginal_conditional_unit_order as _marginal_conditional_unit_order,
)
from milai.application.memory_context_core.windows import (
    _marginal_window_order as _marginal_window_order,
)
from milai.application.memory_context_core.windows import (
    _order_windows as _order_windows,
)
from milai.application.memory_context_core.windows import (
    _session_landmark as _session_landmark,
)
from milai.application.memory_context_core.windows import (
    _speaker_neighbor as _speaker_neighbor,
)
from milai.application.memory_context_core.windows import (
    _turn_sort as _turn_sort,
)
from milai.application.memory_context_core.windows import (
    _workspace_candidate_provenance as _workspace_candidate_provenance,
)
from milai.application.memory_context_core.windows import (
    _workspace_target_hints as _workspace_target_hints,
)
from milai.application.reader_evidence_plan import (
    DecisionSnapshotRef,
    materialize_decision_snapshot,
)
from milai.domain.memory_context import (
    EvidenceSpeaker,
    MemoryContext,
    MemoryContextWindow,
)
from milai.domain.memory_resolve import MemoryResolveRequest
from milai.domain.reader_evidence_plan import (
    ContextBudgetEnvelope,
    OmittedReaderEvidenceUnit,
    ReaderEvidencePlan,
    ReaderEvidenceRender,
    ReaderEvidenceUnit,
    canonical_digest,
)
from milai.persistence import SessionContext


class MemoryContextCompiler:
    """Compile the minimum governed Context from Runtime-owned result views."""

    COMPILER_VERSION = "runtime-context-compiler-v0.3.1-mvp01-receipt-lineage"
    STABLE_ORDER_VERSION = "reader-evidence-stable-order-v0.1"

    def __init__(
        self,
        adjacency_reader: EvidenceAdjacencyReader | None = None,
        *,
        budget_stable_enabled: bool = False,
        exact_token_counter: Callable[[str], int] | None = None,
        exact_tokenizer_identity: str | None = None,
        query_preserving_union_enabled: bool = False,
        evidence_set_selection_enabled: bool = False,
        instance_preserving_admission_enabled: bool = False,
    ) -> None:
        if (exact_token_counter is None) != (exact_tokenizer_identity is None):
            raise ValueError(
                "exact token counter and tokenizer identity must be configured together"
            )
        self._adjacency_reader = adjacency_reader
        self._budget_stable_enabled = budget_stable_enabled
        self._exact_token_counter = exact_token_counter
        self._exact_tokenizer_identity = exact_tokenizer_identity
        self._query_preserving_union_enabled = query_preserving_union_enabled
        self._evidence_set_selection_enabled = evidence_set_selection_enabled
        self._instance_preserving_admission_enabled = instance_preserving_admission_enabled

    @property
    def requires_full_decision_snapshot(self) -> bool:
        return self._budget_stable_enabled or self._evidence_set_selection_enabled

    def compile(
        self,
        request: MemoryResolveRequest,
        outcome: dict[str, Any],
        *,
        session_context: SessionContext | None = None,
        decision_snapshot: DecisionSnapshotRef | None = None,
        allow_adjacent_hydration: bool = True,
    ) -> ContextCompilation:
        """Compatibility entry point; candidate mode delegates to plan/render."""

        if not self._budget_stable_enabled and not self._evidence_set_selection_enabled:
            return self._compile_legacy(
                request,
                outcome,
                session_context=session_context,
                allow_adjacent_hydration=allow_adjacent_hydration,
            )
        planned = self.plan(
            request,
            outcome,
            session_context=session_context,
            decision_snapshot=decision_snapshot,
            allow_adjacent_hydration=allow_adjacent_hydration,
        )
        if self._exact_tokenizer_identity is None:
            envelope = ContextBudgetEnvelope(
                requested_cap=request.budget.max_context_tokens,
                available_memory_tokens=request.budget.max_context_tokens,
                budget_source="CALLER_CAP_ONLY",
            )
        else:
            envelope = ContextBudgetEnvelope(
                requested_cap=request.budget.max_context_tokens,
                model_context_limit=request.budget.max_context_tokens,
                available_memory_tokens=request.budget.max_context_tokens,
                reader_tokenizer_identity=self._exact_tokenizer_identity,
                budget_source="EXACT_READER_ENVELOPE",
            )
        return self.render(planned, envelope)

    def plan(
        self,
        request: MemoryResolveRequest,
        outcome: dict[str, Any],
        *,
        session_context: SessionContext | None = None,
        decision_snapshot: DecisionSnapshotRef | None = None,
        allow_adjacent_hydration: bool = True,
    ) -> ContextPlanCompilation:
        """Compile one budget-free semantic-unit plan from one decision snapshot."""

        raw_items = outcome.get("items")
        items = (
            [dict(item) for item in raw_items if isinstance(item, dict)]
            if isinstance(raw_items, list)
            else []
        )
        items, expansion_trace, expansion_activation = self._expand_items(
            session_context,
            request,
            outcome,
            items,
            allow_adjacent_hydration=allow_adjacent_hydration,
        )
        query_terms = _query_terms(request.query)
        governance_admitted_context = (
            outcome.get("_reader_evidence_boundary") == "GOVERNANCE_ADMITTED_SOFT_RANKED"
        )
        query_ir = outcome.get("memory_query_ir")
        member_enumeration = _query_ir_enumerates_members(query_ir)
        evidence_views = _evidence_views(
            items,
            request.query,
            query_terms,
            member_enumeration=member_enumeration,
        )
        raw_derived = outcome.get("derived_result")
        derived_operand_views = _derived_operand_views(
            raw_derived,
            request.query,
            query_terms,
            existing_views=evidence_views,
            member_enumeration=member_enumeration,
        )
        evidence_views.extend(derived_operand_views)
        if not self._query_preserving_union_enabled:
            evidence_views = _stable_evidence_views(evidence_views)
        derived = _derived_context(raw_derived)
        derived_evidence_ids, derived_source_refs = _required_sources(raw_derived)
        snapshot = (
            materialize_decision_snapshot(decision_snapshot)
            if decision_snapshot is not None
            else _fallback_decision_snapshot(request, outcome, items)
        )
        accepted_binding_spans = _breadth_first_binding_spans(snapshot)
        if accepted_binding_spans:
            required_evidence_ids = _unique(span.evidence_id for span in accepted_binding_spans)
            required_source_refs = _unique(span.source_turn_ref for span in accepted_binding_spans)
        elif decision_snapshot is not None and raw_derived is not None:
            # A Runtime-owned operator result is the authoritative answer/proof
            # boundary.  In particular, an honest PARTIAL result may expose an
            # empty support set after classifying a much larger completeness
            # scan.  Do not promote that audited candidate set back into the
            # untrimmable Reader closure merely because no answer span survived.
            required_evidence_ids = _unique(derived_evidence_ids)
            required_source_refs = _unique(derived_source_refs)
        elif decision_snapshot is not None:
            required_evidence_ids = _unique(
                [*derived_evidence_ids, *snapshot.accepted_evidence_ids]
            )
            required_source_refs = _unique(derived_source_refs)
        else:
            required_evidence_ids = _unique(
                [
                    *derived_evidence_ids,
                    *snapshot.accepted_evidence_ids,
                    *_string_values(outcome.get("evidence_refs")),
                ]
            )
            required_source_refs = _unique(derived_source_refs)
        canonical_items = [item for item in items if item.get("kind") != "EVIDENCE_OBSERVATION"]
        canonical_evidence_ids: list[str] = []
        canonical_source_refs: list[str] = []
        for item in canonical_items:
            item_evidence_ids, item_source_refs = _canonical_item_sources(item)
            canonical_evidence_ids.extend(item_evidence_ids)
            canonical_source_refs.extend(item_source_refs)
        unit_owned_evidence_ids = set(
            [
                *(derived_evidence_ids if derived is not None else []),
                *canonical_evidence_ids,
                *(span.evidence_id for span in accepted_binding_spans),
            ]
        )
        unit_owned_source_refs = set(
            [
                *(derived_source_refs if derived is not None else []),
                *canonical_source_refs,
                *(span.source_turn_ref for span in accepted_binding_spans),
            ]
        )
        # D/C/accepted-Binding units already render and map their source
        # Evidence.  Do not render the same Evidence again as an E window: a
        # repeated alias makes the ContextReceipt many-to-one and prevents an
        # exact Reader-unit provenance replay.
        window_evidence_views = [
            view
            for view in evidence_views
            if view.evidence_id not in unit_owned_evidence_ids
            and view.source_turn_ref not in unit_owned_source_refs
        ]
        window_required_evidence_ids = [
            value for value in required_evidence_ids if value not in unit_owned_evidence_ids
        ]
        window_required_source_refs = [
            value for value in required_source_refs if value not in unit_owned_source_refs
        ]
        windows = _build_windows(
            window_evidence_views,
            required_evidence_ids=window_required_evidence_ids,
            required_source_refs=window_required_source_refs,
            session_landmark_pairing=self._query_preserving_union_enabled,
            optional_member_token_cap=(
                _SOFT_WINDOW_TOKEN_CAP
                if governance_admitted_context and self._query_preserving_union_enabled
                else None
            ),
        )
        multi_session_required = _requires_multiple_sessions(
            request.query,
            query_ir,
            window_evidence_views,
            window_required_evidence_ids,
            window_required_source_refs,
        )
        ordered_windows = _order_windows(
            windows,
            multi_session_required,
            token_efficient=self._query_preserving_union_enabled,
        )
        required_requirements = snapshot.required_requirement_ids
        raw_sufficiency = outcome.get("sufficiency_decision")
        sufficiency_values = raw_sufficiency if isinstance(raw_sufficiency, dict) else {}
        contested = (
            outcome.get("status") == "CONTESTED"
            or _sufficiency_status(sufficiency_values, outcome) == "CONTESTED"
        )

        protected: list[ReaderEvidenceUnit] = [
            _reader_unit(
                unit_id="status",
                kind="STATUS",
                text=_status_unit_text(outcome),
                requirement_ids=required_requirements,
                exact_span=True,
            )
        ]
        conditional: list[ReaderEvidenceUnit] = []
        omitted: list[OmittedReaderEvidenceUnit] = []
        unit_windows: list[tuple[str, MemoryContextWindow]] = []
        unit_canonical: list[tuple[str, dict[str, Any]]] = []
        if derived is not None:
            protected.append(
                _reader_unit(
                    unit_id="derived-result",
                    kind="DERIVED_RESULT",
                    text=derived,
                    requirement_ids=required_requirements,
                    evidence_ids=derived_evidence_ids,
                    source_turn_refs=derived_source_refs,
                    exact_span=True,
                )
            )
        for ordinal, item in enumerate(
            sorted(canonical_items, key=_canonical_item_sort_key),
            start=1,
        ):
            canonical_evidence_ids, canonical_source_refs = _canonical_item_sources(item)
            unit_id = f"canonical:{_sha256(_canonical_item_identity(item))[:20]}"
            text = f"[C{ordinal} CANONICAL STATE / GOVERNED]\n" + json.dumps(
                _reader_semantic_value(item),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            protected.append(
                _reader_unit(
                    unit_id=unit_id,
                    kind="CONFLICT_SIDE" if contested else "REQUIRED_BINDING",
                    text=text,
                    requirement_ids=required_requirements,
                    evidence_ids=canonical_evidence_ids,
                    source_turn_refs=canonical_source_refs,
                    exact_span=True,
                )
            )
            unit_canonical.append((unit_id, item))

        seen_semantics: set[str] = set()
        bound_evidence_ids: set[str] = set()
        bound_source_refs: set[str] = set()
        frontier_requirements: set[str] = set()
        for ordinal, span in enumerate(accepted_binding_spans, start=1):
            unit_id = (
                "binding:"
                + _sha256(
                    "\0".join(
                        (
                            span.source_turn_ref,
                            str(span.start),
                            str(span.end),
                            span.text,
                        )
                    )
                )[:20]
            )
            unit_text = (
                f"[E{ordinal} ACCEPTED BINDING SPAN / NON-CANONICAL "
                f"speaker={span.speaker.upper()} "
                f"observed_at={span.observed_at or 'unknown'}]\n{span.text}"
            )
            new_requirements = tuple(
                requirement_id
                for requirement_id in span.requirement_ids
                if requirement_id not in frontier_requirements
            )
            unit = _reader_unit(
                unit_id=unit_id,
                kind=(
                    "CONFLICT_SIDE"
                    if contested
                    else "REQUIRED_BINDING"
                    if new_requirements
                    else "PROVENANCE"
                ),
                text=unit_text,
                requirement_ids=span.requirement_ids,
                evidence_ids=(span.evidence_id,),
                source_turn_refs=(span.source_turn_ref,),
                incremental_requirement_gain=new_requirements,
                exact_span=True,
            )
            if new_requirements:
                protected.append(unit)
                frontier_requirements.update(new_requirements)
            else:
                conditional.append(unit)
            unit_windows.append(
                (
                    unit_id,
                    MemoryContextWindow(
                        window_id=unit_id,
                        session_id=span.session_id,
                        evidence_ids=[span.evidence_id],
                        source_turn_refs=[span.source_turn_ref],
                        speakers=[cast(EvidenceSpeaker, span.speaker.upper())],
                        observed_at=span.observed_at,
                        text=span.text,
                        source_rank=ordinal,
                        query_overlap=0,
                        answer_signal=True,
                        requirement_priority=True,
                        truncated=False,
                    ),
                )
            )
            bound_evidence_ids.add(span.evidence_id)
            bound_source_refs.add(span.source_turn_ref)
            seen_semantics.add(_normalized_unit_semantics(span.text))

        required_ids = set(required_evidence_ids).difference(bound_evidence_ids)
        required_refs = set(required_source_refs).difference(bound_source_refs)
        for window in ordered_windows:
            reader_ordinal = len(unit_windows) + 1
            unit_id = f"evidence:{window.window_id}"
            text = (
                f"[E{reader_ordinal} EVIDENCE WINDOW / NON-CANONICAL "
                f"observed_at={window.observed_at or 'unknown'}]\n{window.text}"
            )
            required = (
                (contested and not accepted_binding_spans)
                or any(value in required_ids for value in window.evidence_ids)
                or any(value in required_refs for value in window.source_turn_refs)
            )
            semantic_key = _normalized_unit_semantics(window.text)
            if not required and semantic_key in seen_semantics:
                omitted.append(
                    OmittedReaderEvidenceUnit(
                        unit_id=unit_id,
                        reason="SEMANTIC_DUPLICATE_ZERO_GAIN",
                    )
                )
                continue
            seen_semantics.add(semantic_key)
            requirement_gain = required_requirements if required else tuple()
            diagnostic_gain = tuple(
                sorted(
                    {
                        expansion.trigger
                        for expansion in window.expansions
                        if expansion.coverage_delta > 0
                    }
                )
            )
            unit = _reader_unit(
                unit_id=unit_id,
                kind=(
                    "CONFLICT_SIDE"
                    if contested
                    else "REQUIRED_BINDING"
                    if required
                    else "PROVENANCE"
                ),
                text=text,
                requirement_ids=required_requirements if required else (),
                evidence_ids=window.evidence_ids,
                source_turn_refs=window.source_turn_refs,
                incremental_requirement_gain=requirement_gain,
                rejection_diagnostic_gain=diagnostic_gain,
                exact_span=True,
            )
            if required:
                protected.append(unit)
            elif _admissible_conditional_gain(
                window,
                request.query,
                governance_admitted=governance_admitted_context,
            ):
                conditional.append(unit)
            else:
                omitted.append(
                    OmittedReaderEvidenceUnit(
                        unit_id=unit_id,
                        reason="NO_ADMISSIBLE_SEMANTIC_GAIN",
                    )
                )
                continue
            unit_windows.append((unit_id, window))

        recall_workspace_trace: dict[str, object] | None = None
        if self._evidence_set_selection_enabled:
            workspace_input_ids = tuple(unit.unit_id for unit in conditional)
            conditional, recall_workspace_trace = _marginal_conditional_unit_order(
                request.query,
                query_terms,
                conditional,
                unit_windows,
                items,
                request.budget.max_context_tokens,
            )
            workspace_output_ids = tuple(unit.unit_id for unit in conditional)
            if sorted(workspace_input_ids) != sorted(workspace_output_ids):
                raise AssertionError("RECALL_WORKSPACE_CHANGED_CANDIDATE_IDENTITY_SET")
            recall_workspace_trace.update(
                {
                    "input_identity_digest": canonical_digest(sorted(workspace_input_ids)),
                    "output_identity_digest": canonical_digest(sorted(workspace_output_ids)),
                    "input_order_digest": canonical_digest(workspace_input_ids),
                    "output_order_digest": canonical_digest(workspace_output_ids),
                    "identity_set_preserved": True,
                }
            )

        open_issue_ids = _open_issue_ids(outcome, canonical_items)
        if open_issue_ids:
            protected.append(
                _reader_unit(
                    unit_id="open-issue-safety",
                    kind="OPEN_ISSUE",
                    text=(
                        "[I1 OPEN ISSUE / SAFETY]\n"
                        "Governed memory is contested or unresolved; do not assume "
                        "that one side is authoritative."
                    ),
                    requirement_ids=snapshot.unresolved_requirement_ids,
                    exact_span=True,
                )
            )

        plan_material = {
            "schema_version": "reader-evidence-plan-v0.1",
            "decision_snapshot_digest": snapshot.snapshot_digest,
            "compiler_version": self.COMPILER_VERSION,
            "stable_order_version": self.STABLE_ORDER_VERSION,
            "protected_units": [unit.model_dump(mode="json") for unit in protected],
            "conditional_units": [unit.model_dump(mode="json") for unit in conditional],
            "omitted_units": [unit.model_dump(mode="json") for unit in omitted],
        }
        reader_plan = ReaderEvidencePlan(
            plan_digest=canonical_digest(plan_material),
            decision_snapshot_digest=snapshot.snapshot_digest,
            compiler_version=self.COMPILER_VERSION,
            stable_order_version=self.STABLE_ORDER_VERSION,
            protected_units=tuple(protected),
            conditional_units=tuple(conditional),
            omitted_units=tuple(omitted),
        )
        return ContextPlanCompilation(
            reader_evidence_plan=reader_plan,
            request=request,
            outcome=dict(outcome),
            decision_snapshot=snapshot,
            unit_windows=tuple(unit_windows),
            unit_canonical_items=tuple(unit_canonical),
            ordered_windows=tuple(ordered_windows),
            canonical_items=tuple(canonical_items),
            raw_derived=raw_derived,
            expansion_trace=tuple(expansion_trace),
            expansion_activation=expansion_activation,
            evidence_view_count=len(evidence_views),
            derived_operand_view_count=len(derived_operand_views),
            multi_session_required=multi_session_required,
            required_evidence_ids=tuple(required_evidence_ids),
            required_source_refs=tuple(required_source_refs),
            recall_workspace_trace=recall_workspace_trace,
        )

    def render(
        self,
        planned: ContextPlanCompilation,
        envelope: ContextBudgetEnvelope,
    ) -> ContextCompilation:
        """Render one immutable plan through whole-unit, nested admission."""

        reader_plan = planned.reader_evidence_plan
        protected = list(reader_plan.protected_units)
        conditional = list(reader_plan.conditional_units)
        if envelope.budget_source == "EXACT_READER_ENVELOPE":
            if self._exact_token_counter is None or self._exact_tokenizer_identity is None:
                raise ContextTokenAccountingError(
                    "TOKENIZER_UNAVAILABLE",
                    "exact Reader envelope requires its frozen tokenizer counter",
                )
            if envelope.reader_tokenizer_identity != self._exact_tokenizer_identity:
                raise ContextTokenAccountingError(
                    "TOKENIZER_IDENTITY_MISMATCH",
                    "exact Reader envelope does not match the configured tokenizer",
                )
            admission_counter = self._exact_token_counter
            accounting_authority = "READER_EXACT_TOKENIZER"
        else:
            admission_counter = _estimated_tokens
            accounting_authority = "RUNTIME_ESTIMATOR"
        protected_text = _render_reader_units(protected)
        protected_tokens = admission_counter(protected_text)
        activation = _conditional_activation_thresholds(
            protected,
            conditional,
            token_counter=admission_counter,
            soft_ranked=(
                planned.outcome.get("_reader_evidence_boundary")
                == "GOVERNANCE_ADMITTED_SOFT_RANKED"
            ),
        )
        if protected_tokens > envelope.available_memory_tokens:
            readiness: Literal["READY", "BUDGET_INFEASIBLE"] = "BUDGET_INFEASIBLE"
            selected_units: list[ReaderEvidenceUnit] = []
            text = _render_infeasible_context(planned.outcome)
            omitted_reasons = {
                unit.unit_id: "PROTECTED_CLOSURE_EXCEEDS_AVAILABLE_MEMORY"
                for unit in (*protected, *conditional)
            }
            semantic_saturated = False
        else:
            readiness = "READY"
            selected_conditional_ids = {
                unit_id
                for unit_id, threshold in activation.items()
                if threshold <= envelope.available_memory_tokens
            }
            selected_units = [
                *protected,
                *(unit for unit in conditional if unit.unit_id in selected_conditional_ids),
            ]
            text = _render_reader_units(selected_units)
            omitted_reasons = {
                unit.unit_id: "AVAILABLE_MEMORY_BELOW_UNIT_ACTIVATION_THRESHOLD"
                for unit in conditional
                if unit.unit_id not in selected_conditional_ids
            }
            semantic_saturated = len(selected_conditional_ids) == len(conditional)
        selected_unit_ids = tuple(unit.unit_id for unit in selected_units)
        conditional_unit_order = [unit.unit_id for unit in conditional]
        selected_conditional_unit_ids = [
            unit.unit_id for unit in conditional if unit.unit_id in selected_unit_ids
        ]
        prefix_length = len(selected_conditional_unit_ids)
        rank_first_prefix_violation_count = int(
            selected_conditional_unit_ids != conditional_unit_order[:prefix_length]
        )
        estimated_tokens = _estimated_tokens(text)
        admitted_tokens = admission_counter(text)
        if admitted_tokens > envelope.available_memory_tokens:
            raise AssertionError("DG23_ATOMIC_RENDER_EXCEEDED_AVAILABLE_MEMORY")

        window_by_unit = dict(planned.unit_windows)
        canonical_by_unit = dict(planned.unit_canonical_items)
        selected_windows = [
            window_by_unit[unit_id] for unit_id in selected_unit_ids if unit_id in window_by_unit
        ]
        selected_canonical = [
            canonical_by_unit[unit_id]
            for unit_id in selected_unit_ids
            if unit_id in canonical_by_unit
        ]
        selected_evidence_ids = _unique(
            value for unit in selected_units for value in unit.evidence_ids
        )
        selected_source_refs = _unique(
            value for unit in selected_units for value in unit.source_turn_refs
        )
        selected_evidence_set = set(selected_evidence_ids)
        selected_source_set = set(selected_source_refs)
        required_evidence_selected = [
            value for value in planned.required_evidence_ids if value in selected_evidence_set
        ]
        required_source_selected = [
            value for value in planned.required_source_refs if value in selected_source_set
        ]
        claim_versions = _unique(
            str(item["claim_version_id"])
            for item in selected_canonical
            if item.get("claim_version_id") is not None
        )
        open_issue_ids = (
            _open_issue_ids(planned.outcome, selected_canonical)
            if "open-issue-safety" in selected_unit_ids
            else []
        )
        authority_class = _authority_class(
            has_evidence=bool(
                selected_evidence_ids
                or selected_source_refs
                or any(
                    unit.kind
                    in {
                        "DERIVED_RESULT",
                        "REQUIRED_BINDING",
                        "CONFLICT_SIDE",
                        "OPEN_ISSUE",
                        "PROVENANCE",
                    }
                    and unit.unit_id not in canonical_by_unit
                    for unit in selected_units
                )
            ),
            has_canonical=bool(selected_canonical),
        )
        semantic_context_digest = _sha256(
            _semantic_context_material(
                planned.request,
                planned.outcome,
                authority_class,
                selected_canonical,
                selected_windows,
                (planned.raw_derived if "derived-result" in selected_unit_ids else None),
            )
        )
        reader_context_digest = hashlib.sha256(text.encode()).hexdigest()
        acquired_candidate_trace = _acquired_candidate_trace(planned.outcome)
        bound_evidence_trace = _bound_evidence_trace(planned.decision_snapshot)
        reader_boundary_trace = _reader_boundary_trace(
            planned.outcome,
            acquired_candidate_trace,
            planned.decision_snapshot,
        )
        admitted_evidence_trace = _admitted_evidence_trace(
            reader_plan,
            selected_units,
            selected_evidence_ids=selected_evidence_ids,
            selected_source_refs=selected_source_refs,
        )
        reader_visible_trace = _reader_visible_trace(
            text,
            selected_units,
            exact_token_counter=(
                admission_counter if accounting_authority == "READER_EXACT_TOKENIZER" else None
            ),
            token_accounting_method=accounting_authority,
        )
        evidence_lifecycle_trace = _evidence_lifecycle_trace(
            acquired_candidate_trace,
            admitted_evidence_trace,
            reader_visible_trace,
            planned.decision_snapshot,
        )
        render_receipt = ReaderEvidenceRender(
            plan_digest=reader_plan.plan_digest,
            envelope=envelope,
            readiness=readiness,
            selected_unit_ids=selected_unit_ids,
            omitted_unit_reasons=dict(sorted(omitted_reasons.items())),
            text=text,
            reader_context_digest=reader_context_digest,
            exact_tokens=admitted_tokens,
            estimated_tokens=estimated_tokens,
            protected_closure_tokens=protected_tokens,
            semantic_saturated=semantic_saturated,
        )
        memory_context = MemoryContext(
            authority_class=authority_class,
            text=text,
            semantic_context_digest=semantic_context_digest,
            reader_context_digest=reader_context_digest,
            token_budget=envelope.requested_cap,
            estimated_tokens=estimated_tokens,
            available_windows=len(planned.unit_windows),
            selected_windows=len(selected_windows),
            context_truncated=(
                readiness == "BUDGET_INFEASIBLE"
                or len(selected_windows) != len(planned.unit_windows)
                or len(selected_canonical) != len(planned.canonical_items)
            ),
            selected_evidence_ids=selected_evidence_ids,
            selected_source_turn_refs=selected_source_refs,
            claim_versions=claim_versions,
            open_issue_ids=open_issue_ids,
            windows=selected_windows,
            compile_trace={
                "compiler_version": self.COMPILER_VERSION,
                "decision_snapshot_digest": planned.decision_snapshot.snapshot_digest,
                "decision_layer_digests": {
                    "source_snapshot": planned.decision_snapshot.source_snapshot_digest,
                    "query_ir": planned.decision_snapshot.query_ir_digest,
                    "acquisition_plan": planned.decision_snapshot.acquisition_plan_digest,
                    "candidate_snapshot": planned.decision_snapshot.candidate_snapshot_digest,
                    "gate": planned.decision_snapshot.gate_digest,
                    "binding": planned.decision_snapshot.binding_digest,
                    "requirement_state": (planned.decision_snapshot.requirement_state_digest),
                    "sufficiency": planned.decision_snapshot.sufficiency_digest,
                    "operator": planned.decision_snapshot.operator_result_digest,
                },
                "reader_evidence_plan_digest": reader_plan.plan_digest,
                "stable_order_version": reader_plan.stable_order_version,
                "reader_evidence_boundary": planned.outcome.get(
                    "_reader_evidence_boundary", "LEGACY_CONTEXT_BOUNDARY"
                ),
                "lean_recall_mode": planned.decision_snapshot.lean_recall_mode,
                "lean_recall_plan_digest": (planned.decision_snapshot.lean_recall_plan_digest),
                "evidence_set_digest": (planned.decision_snapshot.evidence_set.evidence_set_digest),
                "evidence_set_item_count": len(planned.decision_snapshot.evidence_set.items),
                "evidence_set_covered_requirement_ids": list(
                    planned.decision_snapshot.evidence_set.covered_requirement_ids
                ),
                "evidence_set_missing_requirement_ids": list(
                    planned.decision_snapshot.evidence_set.missing_requirement_ids
                ),
                "reader_readiness": readiness,
                "budget_envelope": envelope.model_dump(mode="json"),
                "protected_unit_count": len(protected),
                "conditional_unit_count": len(conditional),
                "selected_unit_ids": list(selected_unit_ids),
                "omitted_unit_reasons": dict(sorted(omitted_reasons.items())),
                "plan_omitted_units": [
                    unit.model_dump(mode="json") for unit in reader_plan.omitted_units
                ],
                "conditional_activation_thresholds": activation,
                "protected_closure_tokens": protected_tokens,
                "semantic_saturated": semantic_saturated,
                "atomic_unit_truncation_count": 0,
                "long_turn_split_count": sum(int(window.truncated) for window in selected_windows),
                "rank_first_prefix_violation_count": (rank_first_prefix_violation_count),
                "whole_unit_admission": True,
                "conditional_unit_order": conditional_unit_order,
                "selected_conditional_unit_ids": selected_conditional_unit_ids,
                "candidate_window_trace": [
                    {
                        "window_id": window.window_id,
                        "evidence_ids": list(window.evidence_ids),
                        "source_turn_refs": list(window.source_turn_refs),
                        "session_id": window.session_id,
                        "source_rank": window.source_rank,
                        "query_overlap": window.query_overlap,
                        "answer_signal": window.answer_signal,
                        "requirement_priority": window.requirement_priority,
                        "estimated_tokens": _estimated_tokens(window.text),
                    }
                    for window in planned.ordered_windows
                ],
                "candidate_evidence_views": planned.evidence_view_count,
                "derived_operand_source_recoveries": (planned.derived_operand_view_count),
                "expansion_trace": list(planned.expansion_trace),
                "expansion_activation": planned.expansion_activation,
                "multi_session_requirement": planned.multi_session_required,
                "query_preserving_union_enabled": (self._query_preserving_union_enabled),
                "evidence_set_selection_enabled": (self._evidence_set_selection_enabled),
                "recall_workspace_trace": planned.recall_workspace_trace,
                "required_evidence_packing_loss_count": (
                    len(planned.required_evidence_ids) - len(required_evidence_selected)
                    if readiness == "READY"
                    else 0
                ),
                "required_source_turn_packing_loss_count": (
                    len(planned.required_source_refs) - len(required_source_selected)
                    if readiness == "READY"
                    else 0
                ),
                "token_accounting_method": accounting_authority,
                "acquired_candidate_trace": acquired_candidate_trace,
                "bound_evidence_trace": bound_evidence_trace,
                "reader_boundary_trace": reader_boundary_trace,
                # Compatibility aliases retain their prior shapes while the
                # canonical P03 stage names make acquisition and Binding explicit.
                "raw_retrieval_trace": acquired_candidate_trace,
                "admitted_evidence_trace": admitted_evidence_trace,
                "reader_visible_trace": reader_visible_trace,
                "evidence_lifecycle_trace": evidence_lifecycle_trace,
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        )
        receipt = _evidence_receipt(
            planned.request,
            planned.outcome,
            memory_context,
            selected_canonical,
        )
        return ContextCompilation(
            memory_context,
            receipt,
            reader_plan,
            render_receipt,
            planned,
        )

    def _compile_legacy(
        self,
        request: MemoryResolveRequest,
        outcome: dict[str, Any],
        *,
        session_context: SessionContext | None = None,
        allow_adjacent_hydration: bool = True,
    ) -> ContextCompilation:
        raw_items = outcome.get("items")
        baseline_items = (
            [dict(item) for item in raw_items if isinstance(item, dict)]
            if isinstance(raw_items, list)
            else []
        )
        items = list(baseline_items)
        raw_instance_candidates = outcome.get("_instance_preserving_candidate_items")
        instance_candidate_items = (
            raw_instance_candidates if isinstance(raw_instance_candidates, list) else []
        )
        instance_preserving_active = (
            self._instance_preserving_admission_enabled
            and outcome.get("_reader_evidence_boundary") == "GOVERNANCE_ADMITTED_SOFT_RANKED"
            and bool(instance_candidate_items)
        )
        if instance_preserving_active:
            canonical_items = [
                item for item in baseline_items if item.get("kind") != "EVIDENCE_OBSERVATION"
            ]
            seen_evidence_ids: set[str] = set()
            candidate_items: list[dict[str, Any]] = []
            for raw_item in instance_candidate_items:
                if not isinstance(raw_item, dict):
                    continue
                evidence_id = raw_item.get("evidence_id")
                if (
                    raw_item.get("kind") == "EVIDENCE_OBSERVATION"
                    and isinstance(evidence_id, str)
                    and evidence_id
                    and evidence_id not in seen_evidence_ids
                ):
                    seen_evidence_ids.add(evidence_id)
                    candidate_items.append(dict(raw_item))
            if candidate_items:
                items = [*canonical_items, *candidate_items]
        items, expansion_trace, expansion_activation = self._expand_items(
            session_context,
            request,
            outcome,
            items,
            allow_adjacent_hydration=allow_adjacent_hydration,
        )
        query_terms = _query_terms(request.query)
        query_ir = outcome.get("memory_query_ir")
        member_enumeration = _query_ir_enumerates_members(query_ir)
        evidence_views = _evidence_views(
            items,
            request.query,
            query_terms,
            member_enumeration=member_enumeration,
        )
        raw_derived = outcome.get("derived_result")
        derived_operand_views = _derived_operand_views(
            raw_derived,
            request.query,
            query_terms,
            existing_views=evidence_views,
            member_enumeration=member_enumeration,
        )
        evidence_views.extend(derived_operand_views)
        # No expansion or replacement: both views describe the same owned items.
        if len(items) == len(baseline_items) and all(
            item is baseline for item, baseline in zip(items, baseline_items, strict=True)
        ):
            baseline_evidence_views = list(evidence_views)
        else:
            baseline_evidence_views = _evidence_views(
                baseline_items,
                request.query,
                query_terms,
                member_enumeration=member_enumeration,
            )
            baseline_derived_views = _derived_operand_views(
                raw_derived,
                request.query,
                query_terms,
                existing_views=baseline_evidence_views,
                member_enumeration=member_enumeration,
            )
            baseline_evidence_views.extend(baseline_derived_views)
        derived = _derived_context(raw_derived)
        required_evidence_ids, required_source_refs = _required_sources(
            outcome.get("derived_result")
        )
        windows = _build_windows(
            evidence_views,
            required_evidence_ids=required_evidence_ids,
            required_source_refs=required_source_refs,
            session_landmark_pairing=self._query_preserving_union_enabled,
        )
        multi_session_required = _requires_multiple_sessions(
            request.query,
            query_ir,
            evidence_views,
            required_evidence_ids,
            required_source_refs,
        )
        ordered_windows = _order_windows(
            windows,
            multi_session_required,
            token_efficient=self._query_preserving_union_enabled,
        )
        recall_workspace_trace: dict[str, object] | None = None
        if instance_preserving_active:
            baseline_windows = _build_windows(
                baseline_evidence_views,
                required_evidence_ids=required_evidence_ids,
                required_source_refs=required_source_refs,
                session_landmark_pairing=self._query_preserving_union_enabled,
            )
            baseline_multi_session_required = _requires_multiple_sessions(
                request.query,
                query_ir,
                baseline_evidence_views,
                required_evidence_ids,
                required_source_refs,
            )
            baseline_ordered_windows = _order_windows(
                baseline_windows,
                baseline_multi_session_required,
                token_efficient=self._query_preserving_union_enabled,
            )
            ordered_windows, recall_workspace_trace = _instance_preserving_window_order(
                request.query,
                query_terms,
                outcome,
                derived,
                baseline_ordered_windows,
                ordered_windows,
                items,
                request.budget.max_context_tokens,
            )
        required_windows = [window for window in ordered_windows if window.requirement_priority]
        optional_windows = [window for window in ordered_windows if not window.requirement_priority]
        canonical_items = [item for item in items if item.get("kind") != "EVIDENCE_OBSERVATION"]
        selected_canonical: list[dict[str, Any]] = []
        budget = request.budget.max_context_tokens
        required_activation_threshold = _estimated_tokens(
            _render_context(outcome, [], required_windows, derived)
        )
        conditional_activation_thresholds: dict[str, int] = {}
        derived, selected_windows = _reserve_required_windows(
            outcome,
            required_windows,
            derived,
            query_terms,
            budget,
        )

        for item in canonical_items:
            candidate = [*selected_canonical, item]
            rendered = _render_context(
                outcome,
                candidate,
                selected_windows,
                derived,
            )
            if _estimated_tokens(rendered) <= budget:
                selected_canonical.append(item)

        for window in optional_windows:
            rendered = _render_context(
                outcome,
                selected_canonical,
                [*selected_windows, window],
                derived,
            )
            activation_threshold = _estimated_tokens(rendered)
            conditional_activation_thresholds[f"evidence:{window.window_id}"] = activation_threshold
            if activation_threshold <= budget:
                selected_windows.append(window)
                continue
            fitted = (
                None
                if instance_preserving_active
                else _fit_window(
                    outcome,
                    selected_canonical,
                    selected_windows,
                    window,
                    derived,
                    query_terms,
                    budget,
                )
            )
            if fitted is not None:
                selected_windows.append(fitted)

        text = _render_context(
            outcome,
            selected_canonical,
            selected_windows,
            derived,
        )
        estimated_tokens = _estimated_tokens(text)
        if estimated_tokens > budget:
            # The fixed boundary alone is deliberately tiny, so this can only be
            # reached by a derived result. Preserve typed provenance and trim its
            # display body instead of silently exceeding the caller's budget.
            derived = _fit_derived(outcome, selected_canonical, budget, derived)
            selected_windows = []
            text = _render_context(outcome, selected_canonical, [], derived)
            estimated_tokens = _estimated_tokens(text)

        canonical_evidence_ids, canonical_source_refs = _canonical_sources(selected_canonical)
        selected_evidence_ids = _unique(
            [
                *canonical_evidence_ids,
                *(value for window in selected_windows for value in window.evidence_ids),
            ]
        )
        selected_source_refs = _unique(
            [
                *canonical_source_refs,
                *(value for window in selected_windows for value in window.source_turn_refs),
            ]
        )
        required_evidence_ids_selected = [
            value for value in required_evidence_ids if value in set(selected_evidence_ids)
        ]
        required_source_refs_selected = [
            value for value in required_source_refs if value in set(selected_source_refs)
        ]
        claim_versions = _unique(
            str(item["claim_version_id"])
            for item in selected_canonical
            if item.get("claim_version_id") is not None
        )
        open_issue_ids = _open_issue_ids(outcome, selected_canonical)
        authority_class = _authority_class(
            has_evidence=bool(selected_evidence_ids or selected_windows or derived),
            has_canonical=bool(selected_canonical),
        )
        truncated = (
            len(selected_windows) != len(ordered_windows)
            or len(selected_canonical) != len(canonical_items)
            or any(window.truncated for window in selected_windows)
        )
        semantic_context_digest = _sha256(
            _semantic_context_material(
                request,
                outcome,
                authority_class,
                selected_canonical,
                selected_windows,
                raw_derived,
            )
        )
        reader_context_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        selected_window_ids = {window.window_id for window in selected_windows}
        selected_unit_ids = [f"evidence:{window.window_id}" for window in selected_windows]
        conditional_unit_order = [f"evidence:{window.window_id}" for window in optional_windows]
        selected_conditional_unit_ids = [
            unit_id for unit_id in conditional_unit_order if unit_id in selected_unit_ids
        ]
        omitted_unit_reasons = {
            f"evidence:{window.window_id}": (
                "PROTECTED_CLOSURE_EXCEEDS_AVAILABLE_MEMORY"
                if window.requirement_priority
                else "AVAILABLE_MEMORY_BELOW_UNIT_ACTIVATION_THRESHOLD"
            )
            for window in ordered_windows
            if window.window_id not in selected_window_ids
        }
        candidate_window_trace = [
            {
                "window_id": window.window_id,
                "evidence_ids": list(window.evidence_ids),
                "source_turn_refs": list(window.source_turn_refs),
                "session_id": window.session_id,
                "source_rank": window.source_rank,
                "query_overlap": window.query_overlap,
                "answer_signal": window.answer_signal,
                "requirement_priority": window.requirement_priority,
                "estimated_tokens": _estimated_tokens(window.text),
            }
            for window in ordered_windows
        ]
        reader_evidence_plan_digest = canonical_digest(
            {
                "schema_version": "legacy-reader-evidence-plan-trace-v0.1",
                "stable_order_version": self.STABLE_ORDER_VERSION,
                "candidate_windows": candidate_window_trace,
            }
        )
        rank_prefix_length = len(selected_conditional_unit_ids)
        required_omitted = any(
            window.requirement_priority and window.window_id not in selected_window_ids
            for window in ordered_windows
        )
        memory_context = MemoryContext(
            authority_class=authority_class,
            text=text,
            semantic_context_digest=semantic_context_digest,
            reader_context_digest=reader_context_digest,
            token_budget=budget,
            estimated_tokens=estimated_tokens,
            available_windows=len(ordered_windows),
            selected_windows=len(selected_windows),
            context_truncated=truncated,
            selected_evidence_ids=selected_evidence_ids,
            selected_source_turn_refs=selected_source_refs,
            claim_versions=claim_versions,
            open_issue_ids=open_issue_ids,
            windows=selected_windows,
            compile_trace={
                "compiler_version": (
                    "runtime-context-compiler-v0.2.3-product10-instance-preserving"
                    if instance_preserving_active
                    else "runtime-context-compiler-v0.2.2-mvp01-receipt-lineage"
                ),
                "reader_evidence_plan_digest": reader_evidence_plan_digest,
                "stable_order_version": self.STABLE_ORDER_VERSION,
                "reader_evidence_boundary": outcome.get(
                    "_reader_evidence_boundary", "LEGACY_CONTEXT_BOUNDARY"
                ),
                "reader_readiness": ("BUDGET_INFEASIBLE" if required_omitted else "READY"),
                "budget_envelope": {
                    "schema_version": "context-budget-envelope-v0.1",
                    "requested_cap": budget,
                    "model_context_limit": None,
                    "fixed_system_prompt_tokens": 0,
                    "query_tokens": 0,
                    "answer_reserve_tokens": 0,
                    "safety_margin_tokens": 0,
                    "available_memory_tokens": budget,
                    "reader_tokenizer_identity": None,
                    "budget_source": "CALLER_CAP_ONLY",
                },
                "protected_unit_count": len(required_windows),
                "conditional_unit_count": len(optional_windows),
                "selected_unit_ids": selected_unit_ids,
                "omitted_unit_reasons": dict(sorted(omitted_unit_reasons.items())),
                "plan_omitted_units": [],
                "conditional_activation_thresholds": {
                    **{
                        f"evidence:{window.window_id}": required_activation_threshold
                        for window in required_windows
                    },
                    **dict(sorted(conditional_activation_thresholds.items())),
                },
                "protected_closure_tokens": required_activation_threshold,
                "semantic_saturated": len(selected_windows) == len(ordered_windows),
                "atomic_unit_truncation_count": sum(
                    int(window.truncated) for window in selected_windows
                ),
                "long_turn_split_count": 0,
                "rank_first_prefix_violation_count": int(
                    selected_conditional_unit_ids != conditional_unit_order[:rank_prefix_length]
                ),
                "whole_unit_admission": not any(window.truncated for window in selected_windows),
                "conditional_unit_order": conditional_unit_order,
                "selected_conditional_unit_ids": selected_conditional_unit_ids,
                "candidate_window_trace": candidate_window_trace,
                "candidate_evidence_views": len(evidence_views),
                "baseline_candidate_evidence_views": len(baseline_evidence_views),
                "source_turns_recovered": len(evidence_views),
                "derived_operand_source_recoveries": len(derived_operand_views),
                "speaker_adjacency_expansions": sum(
                    len(window.expansions) for window in ordered_windows
                ),
                "expansion_policy": {
                    "version": "runtime-local-context-v0.1",
                    "sequence": ["SAME_ROUND", "ADJACENT_ROUND"],
                    "adjacent_round_distance": 1,
                    "structured_metadata_required": True,
                    "legacy_source_ref_parsing": False,
                },
                "expansion_trace": expansion_trace,
                "expansion_activation": expansion_activation,
                "hydrated_evidence_count": len(expansion_trace),
                "multi_session_requirement": multi_session_required,
                "session_diversity_objective_enabled": multi_session_required,
                "query_preserving_union_enabled": (self._query_preserving_union_enabled),
                "evidence_set_selection_enabled": (self._evidence_set_selection_enabled),
                "instance_preserving_admission_enabled": (instance_preserving_active),
                "recall_workspace_trace": recall_workspace_trace,
                "requirement_evidence_count": len(required_evidence_ids),
                "requirement_source_turn_count": len(required_source_refs),
                "required_windows_available": len(required_windows),
                "required_windows_selected": sum(
                    window.requirement_priority for window in selected_windows
                ),
                "required_evidence_selected_count": len(required_evidence_ids_selected),
                "required_source_turn_selected_count": len(required_source_refs_selected),
                "required_evidence_packing_loss_count": (
                    len(required_evidence_ids) - len(required_evidence_ids_selected)
                ),
                "required_source_turn_packing_loss_count": (
                    len(required_source_refs) - len(required_source_refs_selected)
                ),
                "requirement_provenance": "VALIDATED_DERIVED_RESULT",
                "hidden_model_calls": 0,
                "canonical_mutation": False,
            },
        )
        receipt = _evidence_receipt(
            request,
            outcome,
            memory_context,
            selected_canonical,
        )
        return ContextCompilation(memory_context, receipt)

    def _expand_items(
        self,
        session_context: SessionContext | None,
        request: MemoryResolveRequest,
        outcome: dict[str, Any],
        items: list[dict[str, Any]],
        *,
        allow_adjacent_hydration: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, object]], dict[str, object]]:
        anchors = [
            str(item["evidence_id"])
            for item in items
            if item.get("kind") == "EVIDENCE_OBSERVATION"
            and isinstance(item.get("evidence_id"), str)
            and _structured_source_context(item) is not None
        ][:24]
        activation = _local_context_activation(
            request,
            outcome,
            has_reader=self._adjacency_reader is not None,
            has_session_context=session_context is not None,
            structured_anchor_count=len(anchors),
            query_preserving_union=self._query_preserving_union_enabled,
        )
        if not allow_adjacent_hydration:
            return (
                items,
                [],
                {
                    **activation,
                    "eligible": False,
                    "activated": False,
                    "reason": "PERSISTED_FRONTIER_RENDER_ONLY",
                },
            )
        if not activation["activated"]:
            return items, [], activation
        assert self._adjacency_reader is not None
        assert session_context is not None
        hydrated = self._adjacency_reader.hydrate_evidence_adjacency(
            session_context,
            anchor_evidence_ids=anchors,
            requested_scope=dict(request.requested_scope),
            as_of=request.reference_time or datetime.now(UTC),
            max_items=min(
                120,
                max(1, len(anchors) * 5),
                max(1, 160 - len(items)) if self._query_preserving_union_enabled else 120,
            ),
        )
        evidence_ids = {
            str(item["evidence_id"]) for item in items if isinstance(item.get("evidence_id"), str)
        }
        source_refs = {
            str(item["source_ref"]) for item in items if isinstance(item.get("source_ref"), str)
        }
        anchor_contexts = {
            str(item["evidence_id"]): context
            for item in items
            if isinstance(item.get("evidence_id"), str)
            and isinstance((context := _structured_source_context(item)), dict)
        }
        expanded = list(items)
        trace: list[dict[str, object]] = []
        for item in hydrated:
            evidence_id = item.get("evidence_id")
            source_ref = item.get("source_ref")
            expansion = item.get("context_expansion")
            if (
                item.get("kind") != "EVIDENCE_OBSERVATION"
                or not isinstance(evidence_id, str)
                or not isinstance(source_ref, str)
                or _structured_source_context(item) is None
                or not isinstance(expansion, dict)
            ):
                continue
            if evidence_id in evidence_ids or source_ref in source_refs:
                continue
            trigger = expansion.get("trigger")
            source_evidence_id = expansion.get("source_evidence_id")
            if trigger not in {"SAME_ROUND", "ADJACENT_ROUND"} or not isinstance(
                source_evidence_id, str
            ):
                continue
            source_context = anchor_contexts.get(source_evidence_id)
            candidate_context = _structured_source_context(item)
            if source_context is None or candidate_context is None:
                continue
            source_round = int(source_context["round_ordinal"])
            candidate_round = int(candidate_context["round_ordinal"])
            if (
                candidate_context["session_id"] != source_context["session_id"]
                or (trigger == "SAME_ROUND" and candidate_round != source_round)
                or (trigger == "ADJACENT_ROUND" and abs(candidate_round - source_round) != 1)
            ):
                continue
            expanded.append(dict(item))
            evidence_ids.add(evidence_id)
            source_refs.add(source_ref)
            trace.append(
                {
                    "trigger": trigger,
                    "source_evidence_id": source_evidence_id,
                    "expanded_evidence_ids": [evidence_id],
                    "cost": 1,
                    "coverage_delta": int(item.get("anchor_match") is True),
                    "stop_reason": "EXPANDED",
                }
            )
        return expanded, trace, activation
