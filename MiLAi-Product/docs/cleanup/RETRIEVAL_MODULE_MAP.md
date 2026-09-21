# Retrieval internal module map

## Compatibility boundary

The supported Runtime import remains:

```python
from milai.application.retrieval import RetrievalService
```

`runtime/src/milai/application/retrieval.py` remains the orchestration module and compatibility
facade. Existing test-only imports of extracted underscore helpers continue to resolve from that
module. `retrieval_core` is internal and is not a new public API.

## Current extraction

| Module | Responsibility | Extracted symbols |
| --- | --- | --- |
| `retrieval_core/policy.py` | Query policy, candidate-floor and deadline arithmetic | `_retrieval_policy`, `_candidate_pool_floor`, `_remaining_timeout_ms`, `_deadline_exhausted` |
| `retrieval_core/candidates.py` | Candidate fusion, evidence deduplication/diversity, shared turn ranking and result identity | `_merge_candidates`, `_deduplicate_evidence`, `_diversify_evidence_by_subject`, `_rank_evidence_turns`, `_result_identity` |
| `retrieval_core/temporal.py` | Binary-event coverage, relative-point resolution and temporal reranking | `_binary_event_anchor_terms`, `_binary_event_anchor_queries`, `_binary_anchor_cover`, `_relative_point_target`, `_relative_point_cover`, `_temporal_tokens`, `_temporal_text`, `_temporal_timestamp`, `_temporal_subject_indices`, `_relative_target`, `_rerank_by_reference`, `_relative_event_dates`, `_intent_tokens`, `_relative_event_intent_overlap`, `_relative_event_distance`, `_temporal_rerank` |
| `retrieval_core/selection.py` | Context budgeting, weighted set cover and deterministic lexical MMR | `_apply_context_budget`, `_context_candidate_budget`, `_context_budget_view`, `_set_cover_text`, `_set_cover_tokens`, `_weighted_set_cover_select`, `_mmr_select`, `_mmr_tokens`, `_jaccard` |
| `retrieval_core/acquisition.py` | Formation/raw result composition, acquisition envelopes and query-local evidence material | `_merge_evidence_results`, `_formation_candidate_results`, `_union_formation_and_raw`, `_acquisition_candidate_envelopes`, `_acquisition_reference_material`, `_use_acquisition_composition` |
| `retrieval_core/operators.py` | Compound-subject matching, scalar-state coverage, accepted-input execution and operator provenance | `_explicit_compound_subject_matches`, `_state_count_cover`, `_execute_operator_with_accepted_inputs`, `_operator_support_refs` |
| `retrieval_core/assembly.py` | Governed result assembly, response payloads, decision snapshots and accepted evidence/span projection | `_assemble_results`, `_response_body`, `_contains_evidence_observation`, `_projection_state_payload`, `_decision_snapshot`, `_requirement_evidence_set`, `_decision_requirement_ids`, `_decision_accepted_evidence_ids`, `_accepted_binding_spans`, `_binding_span_provenance_order`, `_result_evidence_ids` |
| `retrieval_core/trace.py` | Matched replay capture, public acquisition trace projection, execution-stage abstraction, latency/cost accounting and access-trace serialization | `_canonical_sha256`, `_build_matched_retrieval_replay`, `_stage_metrics`, `_public_acquisition_probe_disposition`, `_public_temporal_acquisition_trace`, `_abstract_stage_sequence`, `_execution_trace`, `_latency_spans`, `_structural_cost`, `_access_trace_view`, `_unavailable_access_trace` |

The policy values, regexes, reciprocal-rank constant, sorting keys, deadline behavior, candidate
limits, temporal ordering, Context budget, selection weights, acquisition composition and assembly
and trace semantics were moved without modification. AST comparisons against each pre-extraction
`retrieval.py` baseline confirmed all 66 extracted function bodies are unchanged. The trace-stage
mapping and `_LegacyReplayPrefix` contract are also AST-identical to the pre-extraction baseline.

## Preserved boundaries

- `RetrievalService` stays in `retrieval.py`.
- Retrieval route, ranking, threshold, weight and timeout semantics are unchanged.
- Public Runtime imports and existing private compatibility imports are unchanged.
- No schema, migration, MCP, CLI, HTTP, Context budget or Lab code changed.
- Frozen Architecture and historical receipts are unchanged.

## Remaining planned seams

Trace extraction is complete. A later Retrieval-only assessment may extract `system_status()` and
bounded execution phases from the still-large `retrieve()` orchestration. Any such work remains
independently gated; this map does not authorize behavior changes or a wholesale
`RetrievalService` rewrite.
