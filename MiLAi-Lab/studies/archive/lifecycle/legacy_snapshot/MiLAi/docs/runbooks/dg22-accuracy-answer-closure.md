# DG-22 accuracy and answer-correctness runbook

## Scope and default state

DG-22 adds a candidate-disabled, one-pass accuracy-acquisition policy. The
production/default path remains the legacy compatibility profile. No public MCP
schema, frozen architecture file, database table, migration, backfill, or
persistent event projection is changed.

The candidate path is valid only when its policy, QueryIR, RequirementState,
capability, source snapshot, Reader contract, and context identities match their
sealed receipts. A mismatch fails closed; it never falls back to a global probe,
Provider/controller choice, retry, response salvage, or time-axis substitution.

## Preflight

1. Verify the S0 snapshot and quarantine receipt identities.
2. Require `PASS_READER_CONFORMANCE` from S2 before any matched Reader call.
3. Require `PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION` from S7 before S8.
4. Confirm candidate default is `false`, automatic retries are zero, and the
   formal holdout has not been loaded.
5. Use the frozen Qwen3.6 Reader contract, 256 output tokens, model-independent
   matched seed policy, and one call per new identity.

## Failure handling

- Query/requirement ambiguity: return the typed ambiguous disposition.
- Stale query/state/capability/policy identity: reject the action bundle.
- No target, COMPLETE, semantics-owner, exhausted, or no expected gain: skip
  without an auxiliary call.
- Unresolved relevant event time: preserve `POSSIBLE`/partial and never declare
  COUNT complete.
- Invalid Reader output: preserve a typed failure receipt, do not salvage, do
  not retry, and never add it to the reuse index.
- A failed hard gate remains authoritative. Later analysis may supersede an
  input-identity mistake but must retain the earlier receipt in the failure
  index.

## Rollback

Rollback is configuration-only because DG-22 made no schema change:

1. Keep or set the accuracy candidate enablement to `false`.
2. Route all calls through `legacy-v0.1`; do not delete sealed DG-22 evidence.
3. Reject in-flight DG-22 bundles by policy-digest mismatch.
4. Stop issuing new S8 Reader identities; exact successful reuse artifacts may
   remain for audit, while failed outputs remain non-reusable.
5. Run Runtime unit/contract/integration/security tests and verify the frozen
   architecture manifest before restoring service.

No database downgrade, destructive cleanup, or data rewrite is required. The
temporary S9 PostgreSQL database is dropped by the quality runner and its
cleanup receipt must report `PASS`.

## Claim boundary

S7 may claim opened-development retrieval/Binding improvement only. S6 remains
partial for full COUNT event-time representation. A baseline-correct answer
regression makes S8 `FAIL_CORRECT_CASE_REGRESSION`, even when aggregate EM/F1
floors pass, and requires the overall `FAIL_SAFETY_OR_REGRESSION` disposition.
These results do not authorize default-on behavior or a production SLA.
