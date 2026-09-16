# DG-16 Evidence composition runbook

Status: opened-development runbook for local MCP only. Runtime remains
`CANDIDATE`; Schema remains `EXPERIMENTAL`.

## Supported operators

DG-16 v0.1 supports exactly two query-conditioned, non-canonical operators:

| Query shape | Operator | Required slots | Completeness proof |
|---|---|---|---|
| `how much ... each` | `DIVIDE_EVIDENCE_VALUES` | `TOTAL_PRICE`, `ITEM_COUNT` | every required slot is uniquely filled |
| `how many ... appointments ... in <month>` | `TEMPORAL_COUNT_DISTINCT` | `MATCHING_EVENTS_IN_RANGE` | closed-open range scan is complete and its projection watermark covers the target |

An ordinary lookup or unsupported compound query does not emit a composition
result. It stays on governed Evidence recall. Do not add a generic operator or
guess a scalar to make such a query complete.

## Product path

1. Open one exact tenant/principal/project scope through MCP.
2. Capture label-free history as Raw Evidence. Verify `claim_count == 0`.
3. Wait for the Evidence projection barrier; the barrier is readiness-only.
4. Call `milai_memory_resolve` with the user query, `CURRENT` freshness,
   `CANONICAL_REQUIRED` consistency, an explicit reference time, and a bounded
   context budget.
5. Inspect `derived_result.trace` before invoking the reader. It must contain:
   `query_spec`, every required slot, Evidence applicability decisions,
   retrieval attempts, bounded expansion, join, completeness, and one terminal
   reason.
6. Accept a deterministic result only when every required slot and independent
   completeness condition passes. `top_k` is never a completeness proof.
7. Render the result into `MemoryContext` with all selected Evidence IDs and
   source-turn refs. The result must declare `canonical_mutation=false` and
   `hidden_model_calls=0`.
8. Invoke the frozen loopback reader once. Reader failure is terminal for that
   answer attempt and must not change Memory state.
9. Submit exact namespace cleanup, wait for Evidence/FTS/vector/purge lanes, and
   verify that the revoked Evidence no longer resolves.

## Typed terminal handling

| Condition | Required outcome |
|---|---|
| missing or ambiguous quantity slot | `PARTIAL`, no value |
| zero/invalid divisor or incompatible unit | typed partial/contested result, no guessed value |
| unresolved month/year | typed partial, no range scan |
| projection gap/unavailable | `PARTIAL` with `bounded_scan_complete=false`, no count |
| denied, revoked, wrong-scope Evidence | excluded; never accepted as an operand |
| unsupported operator | no composition result; governed recall or explicit abstention |
| reader unavailable | provider failure, automatic retry `0`, Memory state unchanged |

Do not widen scope, increase top-k/token budget, load labels, or retry a failed
cell to hide one of these terminal outcomes. Debug one case, operator, slot, and
stage under a new run ID.

## Reproduction

Run focused contract tests:

```bash
runtime/.venv/bin/python -m pytest \
  runtime/tests/unit/test_dg16_evidence_composition_contract.py \
  runtime/tests/unit/test_dg16_coffee_composition.py \
  runtime/tests/unit/test_dg16_appointment_composition.py \
  tests/test_dg15_lme_mcp_adapter.py \
  tests/test_dg16_q6.py
```

Run the isolated operability matrix. Always choose a fresh run ID:

```bash
runtime/.venv/bin/python scripts/run_dg16_operability.py \
  --run-id dg16-operability-YYYYMMDD-NNN
```

The matrix compares `c1/b32`, `c4/b16`, and `c4/b32` on the same synthetic
two-slot query. Its receipt must prove concurrency invariance, batch invariance,
one slot retrieval, a complete typed trace, reader-failure state invariance,
denied-Evidence rejection, all-lane cleanup, and zero successful reader calls.

Run the five-case matched confirmation only at the release boundary:

```bash
runtime/.venv/bin/python scripts/run_dg16_q6.py \
  --run-id dg16-q6-product-YYYYMMDD-NNN \
  --mcp-concurrency 4 \
  --projection-batch-size 32
```

The Q6 gate is opened-development evidence only. It must preserve all failed
attempt directories, use five isolated databases, keep label loading after all
ten product records are sealed, perform zero automatic retries, leave DG-14
hashes unchanged, and finish every cleanup.

## Current evidence

- Q6: `var/dg16/q6/dg16-q6-product-20260827-006/receipt.json`
- Operability: `var/dg16/operability/dg16-operability-20260827-002/receipt.json`
- Runtime restart/provenance: `var/dg14/runs/dg14-integration-001-20260826/integration-smoke.json`

The availability-first release candidate is `mcp_concurrency=4` and
`projection_batch_size=32`. Batch size 64 was faster in the initial sweep but
was demoted after a later fixed all-lane timeout failure; do not promote it
without new reliability evidence.
