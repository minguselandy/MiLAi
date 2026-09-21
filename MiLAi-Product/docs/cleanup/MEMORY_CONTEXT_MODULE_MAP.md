# Memory Context internal module map

## Compatibility boundary

The supported Runtime imports remain:

```python
from milai.application.memory_context import ContextCompilation
from milai.application.memory_context import MemoryContextCompiler
```

`runtime/src/milai/application/memory_context.py` is now a 268-line compatibility facade.
`memory_context_core` remains internal and is not a new public API. The facade preserves every
inventoried moved symbol, including `_reader_semantic_value` and `_order_windows`, as the same
object exported by its owning internal module.

The facade also preserves three historical monkeypatch observation points:

- compiler calls to `_evidence_views`;
- fitting calls to `_render_context`;
- fitting calls to `_excerpt_focus`.

The owning modules resolve those three callables through the loaded facade only at call time. This
keeps existing test/private-consumer instrumentation working without changing the underlying
selection, rendering, or fitting behavior.

## Final responsibility map

| Module | Responsibility | Principal symbols |
| --- | --- | --- |
| `memory_context_core/contracts.py` | Immutable compilation results, adjacency protocol, typed token-accounting failure | `ContextCompilation`, `ContextPlanCompilation`, `EvidenceAdjacencyReader`, `ContextTokenAccountingError` |
| `memory_context_core/common.py` | Identity, token estimate, authority, position and sufficiency primitives | `_estimated_tokens`, `_authority_class`, `_positions`, `_sufficiency_status`, `_sha256` |
| `memory_context_core/semantics.py` | Query-IR classification, Reader-safe semantic projection and operand validation | `_query_ir_operator_family`, `_reader_semantic_value`, `_validated_operand` |
| `memory_context_core/provenance.py` | Derived/canonical Evidence and source-reference collection | `_required_sources`, `_operand_sources`, `_canonical_item_sources`, `_canonical_sources` |
| `memory_context_core/units.py` | Reader unit construction and bounded envelope rendering | `_reader_unit`, `_render_reader_units`, `_render_infeasible_context` |
| `memory_context_core/activation.py` | Activation signals, fallback snapshot, Evidence views and derived operand recovery | `_local_context_activation`, `_conditional_activation_thresholds`, `_fallback_decision_snapshot`, `_evidence_views`, `_derived_operand_views` |
| `memory_context_core/windows.py` | Adjacency windows, marginal/instance-preserving ordering and locality helpers | `_build_windows`, `_marginal_window_order`, `_instance_preserving_window_order`, `_order_windows` |
| `memory_context_core/rendering.py` | Context serialization, excerpt focus and budget fitting | `_render_context`, `_derived_context`, `_fit_window`, `_fit_windows_together`, `_fit_derived` |
| `memory_context_core/receipts.py` | Evidence receipt mapping and semantic context-material projection | `_evidence_receipt`, `_receipt_mapping`, `_semantic_context_material` |
| `memory_context_core/trace.py` | Candidate-to-reader lifecycle trace projections | `_acquired_candidate_trace`, `_reader_boundary_trace`, `_reader_visible_trace`, `_evidence_lifecycle_trace` |
| `memory_context_core/compiler.py` | Compile/plan/render orchestration | `MemoryContextCompiler` |

## Equivalence evidence

The final extraction baseline is Product commit
`f57cdcf043f81e945b35046913cc7a1df6455777`, where
`memory_context.py` contained 3,716 lines.

A local AST comparison against that baseline inspected all 54 top-level class/function
definitions and all 10 policy/regex/constants moved by C3:

```text
definitions compared: 54
AST-equivalent after compatibility-call-name normalization: 54
definition mismatches: 0
constants compared: 10
constant mismatches: 0
```

The normalization is limited to the three compatibility call names documented above. Function
signatures, defaults, class constants, ordering keys, threshold expressions, receipt regexes and
serialization literals remain part of the compared AST.

`test_memory_context_core_compatibility.py` fixes facade-to-owner object identity for the
compiler, contracts, constants and extracted helpers. Direct behavior suites cover activation,
Evidence views, expansion, window packing, excerpt focus, receipt projection and resolve
integration.

## Preserved boundaries

- `MemoryContextCompiler` keeps the same constructor and `compile`/`plan`/`render` entry
  points.
- Context bytes, budget math, activation thresholds, ordering keys, receipt mapping and exact-token
  accounting are unchanged.
- No schema, migration, MCP, CLI, HTTP, Lab, Frozen Architecture or historical receipt changed.
- The C3 candidate contains only Runtime internal modularization, compatibility tests, module-map
  documentation and regenerated current Product identity.
