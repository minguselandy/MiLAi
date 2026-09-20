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

The policy values, regexes, reciprocal-rank constant, sorting keys, deadline behavior and candidate
limits were moved without modification. An AST comparison against the pre-extraction
`retrieval.py` confirmed all nine function bodies are unchanged.

## Preserved boundaries

- `RetrievalService` stays in `retrieval.py`.
- Retrieval route, ranking, threshold, weight and timeout semantics are unchanged.
- Public Runtime imports and existing private compatibility imports are unchanged.
- No schema, migration, MCP, CLI, HTTP, Context budget or Lab code changed.
- Frozen Architecture and historical receipts are unchanged.

## Remaining planned seams

Later Retrieval-only PRs may extract acquisition, temporal, selection, operators, assembly and
trace helpers. Each extraction remains independently gated; this map does not authorize behavior
changes or a wholesale `RetrievalService` rewrite.
