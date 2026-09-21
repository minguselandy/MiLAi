# Memory Context internal module map

## Compatibility boundary

The supported Runtime imports remain:

```python
from milai.application.memory_context import ContextCompilation
from milai.application.memory_context import MemoryContextCompiler
```

`runtime/src/milai/application/memory_context.py` remains the orchestration module and
compatibility facade. Existing private consumers of `_reader_semantic_value` and test-only
consumers of `_order_windows` continue to resolve from that module. `memory_context_core` is
internal and is not a new public API.

## Foundation extraction

| Module | Responsibility | Extracted symbols |
| --- | --- | --- |
| `memory_context_core/contracts.py` | Immutable compilation results, adjacency reader protocol and typed token-accounting failure | `ContextCompilation`, `ContextPlanCompilation`, `EvidenceAdjacencyReader`, `ContextTokenAccountingError` |
| `memory_context_core/common.py` | Pure identity, token estimate, authority, position and sufficiency primitives | `_string_values`, `_estimated_tokens`, `_authority_class`, `_positions`, `_sufficiency_status`, `_unique`, `_sha256` |
| `memory_context_core/semantics.py` | Query-IR classification, Reader-safe semantic projection and operand validation | `_OPAQUE_READER_KEYS`, `_query_ir_operator_family`, `_query_ir_has_temporal_constraint`, `_query_ir_enumerates_members`, `_reader_semantic_value`, `_validated_operand` |
| `memory_context_core/provenance.py` | Derived/canonical Evidence and source-reference collection | `_required_sources`, `_operand_sources`, `_provenance_values`, `_canonical_item_sources`, `_canonical_sources` |
| `memory_context_core/units.py` | Reader unit construction, status text and bounded envelope rendering | `_reader_unit`, `_status_unit_text`, `_render_reader_units`, `_render_infeasible_context` |

All 25 moved class/function definitions are AST-identical to the pre-extraction
`77ef5be43c05016d122a128144f635b130b8dc2d` baseline. The moved
`_OPAQUE_READER_KEYS` expression is also identical. A dedicated compatibility test fixes the
facade-to-core object identity for every symbol extracted in this round.

## Preserved boundaries

- `MemoryContextCompiler` remains in `memory_context.py` and keeps the same constructor and
  compile/plan/render entry points.
- Context budget, activation thresholds, window selection/order, semantic projection,
  serialization and receipt behavior are unchanged.
- Public imports and existing underscore compatibility imports are preserved at both runtime and
  mypy export boundaries.
- No schema, migration, MCP, CLI, HTTP, Lab, Frozen Architecture or historical receipt changed.

## Second bounded extraction

The next Memory Context PR may move activation, windows, ordering, rendering, receipt composition
and the compiler implementation after their dependency closure is explicit. The facade must retain
`MemoryContextCompiler`, `_reader_semantic_value`, `_order_windows` and any other inventoried
compatibility import. This map does not authorize threshold, budget, ordering or treatment changes.
