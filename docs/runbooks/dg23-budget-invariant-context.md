# DG-23 Budget-Invariant Context Runbook

## Scope and current disposition

DG-23 separates acquisition and deterministic evidence decisions from the Reader presentation ceiling. The candidate remains disabled by default and must not be enabled from these opened-development results.

The sealed DG-23 answer closure is parked as `PARKED_READER_SEMANTIC_NON_MONOTONICITY`: Context/decision, recall/Binding, safety, and execution-identity gates passed, but the predeclared answer-regression gate failed. Formal holdout was not opened.

## Fixed operating contracts

- `max_context_tokens` is a presentation ceiling, not an acquisition budget or fill target.
- Acquisition, Gate, Binding, RequirementState, Sufficiency, and operator execute once per source snapshot.
- Protected semantic units are atomic. A ceiling below the protected closure returns `BUDGET_INFEASIBLE`; the Reader is not called.
- Exact memory cost is the frozen chat-template token count with memory minus the same prompt without memory. Bare Context token count is diagnostic only.
- Reader identity is `(reader_context_digest, reader_contract_digest, sampling_seed, generation_settings_digest)`.
- A sealed result may be restored after interruption only for the same exact identity. Restoration is not a retry and must not issue a new Provider request.
- No case ID, answer label, attempt number, arm, or presentation budget may affect retrieval, decisions, seed, or exact identity.

## Verification sequence

Run stages in order and use fresh, write-once run directories:

1. S0 freezes the DG-22 denominator and predecessor identities.
2. S1 identifies the first budget-dependent divergence without Reader calls.
3. S2 proves decision-layer separation.
4. S3 proves atomic, nested, saturated rendering.
5. S4 proves the frozen Reader boundary, local chat-envelope accounting, and exact-identity reuse.
6. S5 runs synthetic/property mutations with zero Reader calls.
7. S6 performs one acquisition/decision/plan per opened-development case, seals the label-free product, then opens source labels for mediator scoring.
8. S7 calls each unique Reader identity once, seals every Reader output, then opens answer labels.
9. S8 runs quality, real PostgreSQL integration/security, cleanup, and architecture validation.
10. S9 validates identities and seals the honest terminal disposition.

Do not proceed to S7 unless every S0–S6 entry and hard gate passes. S8 must run after a terminal S7 score whether S7 passes or fails.

## Failure handling

On any failure:

1. Preserve the failed run directory, progress, raw Provider metadata allowed by the contract, and failure ledger.
2. Identify the first authoritative loss boundary before changing code.
3. Repair the general ownership or invariant, not a case, gold answer, fixed budget, or prompt phrase.
4. Add a failure-injection or regression test that would have caught the mechanism.
5. Use a fresh run ID. Never overwrite a sealed artifact.
6. Do not retry invalid JSON, timeout, Provider failure, or an answer-regression cell.

For interrupted Reader execution, restore only already sealed exact identities from `reader-progress.json`. Validate Context bytes, seed, Reader contract, generation settings, Provider result, and current frozen token accounting before claiming a restored result. Any mismatch invalidates restoration.

## Observability and diagnosis

Retain and compare:

- decision-layer and ReaderEvidencePlan digests across all budget renders;
- selected unit order, protected loss, nestedness, saturation, and Context digests;
- estimated tokens and exact chat-envelope memory tokens;
- logical cells, unique identities, fresh calls, restored calls, exact reuses, infeasible no-calls, and duplicate calls;
- per-case/per-replicate EM and normalized F1 only after the Reader product is sealed;
- first-loss attribution across acquisition, Binding, Context compilation, token accounting, Reader execution, and scoring.

An execution-level `memory_status` can report an actually degraded projection path even when Sufficiency is COMPLETE. Preserve that observed status; do not rewrite it merely to stabilize a benchmark Context.

## Rollback

The runtime candidate flag `budget_invariant_context_v0_1` remains `false` by default. Rollback is therefore:

1. keep the flag disabled;
2. route production requests through the existing frozen path;
3. retain DG-23 artifacts for diagnosis but do not publish the candidate;
4. do not change the public MCP schema, database schema, architecture v1.0 bundle, Reader contract, or formal-holdout state.

No data migration or canonical mutation is required for rollback because DG-23 changes only internal decision/presentation construction and evaluation artifacts.

## Follow-up research boundary

The sealed failures show two general patterns: a temporal-count answer can lose a required operand before Context construction, or retain all relevant source turns while governed temporal completeness remains unresolved and the Reader abstains. Follow-up work must study requirement-complete acquisition and temporal evidence consumption as separate hypotheses. It must not tune presentation packing, retry the fixed Reader, or introduce runtime case/gold routing.
