# DG-17 Q3A Compatibility Disposition

Status: `IMPLEMENTED / INTERNAL TRANSITION ONLY`  
Date: 2026-08-27  
Release boundary: Runtime `CANDIDATE`, schema `EXPERIMENTAL`

## MemoryQueryIR v0.1

`MemoryQueryIR v0.2` is the only executable semantic-plan contract. The deterministic
`MemoryQueryCompiler` owns the final plan, and `QueryPlanner` compiles exactly one v0.2
IR before mechanically adapting its steps to bounded legacy executors.

The v0.1 model remains only as a frozen precursor inside
`memory_query.py -> query_ir_compat.py`. The translator is explicit, deterministic,
digestible, and cannot compete with v0.2 for final route ownership. Product executors
do not accept v0.1. The v0.1 symbols are no longer re-exported from `milai.domain`.

Removal condition: after Q6 receipts no longer require replay comparison with the
precursor, replace `compile_v01()` with a direct v0.2 frontend and delete the translator
and v0.1 domain module in a successor compatibility change.

## EvidenceAtom v0.1

`EvidenceSpan`, `EvidenceInterpretationCandidate`, and `RequirementBinding` are the
primary contracts. `EvidenceAtom` is retained only in `application/evidence_atoms.py`
as a one-way compatibility DTO derived from independent interpretations.

The alias has these enforced boundaries:

- it is not persisted and cannot mutate canonical state;
- it is not exposed as an MCP object or re-exported from `milai.application` or
  `milai.domain`;
- it never embeds a requirement slot or `RequirementBinding`;
- Runtime range-count composition consumes Span -> Interpretation -> Binding directly;
- only focused transition tests consume the alias.

Removal condition: delete `evidence_atoms.py` and the v0.1 `EvidenceAtom` domain types
after all remaining replay tooling has migrated to the three-part model. No product
execution lane is allowed to add a new dependency during Q3B-Q6.

## Measurement bridge

The immutable Q0 labels and receipt are not rewritten. The Q3A crosswalk records their
SHA-256 identities and maps each measurement-only Atom label to an exact expected span,
fallible interpretation, and query-local binding. It provides the new denominators for
`AnswerBearingSpanRecall`, interpretation recall, `RequirementBindingPrecision`, and
required-slot coverage without making eval labels available to the product path.

Receipt: `var/dg17/q3a/dg17-q3a-crosswalk-20260827-001/crosswalk.json`.
