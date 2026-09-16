# DG-18 Runtime architecture and operator runbook

Status: `DG-18 COMPLETE WITH RESIDUAL PARKED / R3 PROVIDER CONTRACT FAILED / R4-R5 NOT EXECUTED / CANDIDATE / NO-GO FOR SCHEMA FREEZE`

This note is the implementation-facing companion to the DG-18 Goal. It does
not replace the Lean V1 contract or authorize production, remote MCP, formal
holdout, canonical writes, a provider restart, or a schema freeze.

## Runtime ownership and decision chain

```text
MCP memory.resolve
  -> MemoryResolveService
  -> QueryPlanner / MemoryQueryIR v0.2
  -> AcquisitionPlan v0.1
  -> governed deterministic acquisition
       hard tenant/principal/permission/retention/revoke/scope/time filters
       -> turn-first channel rank and fusion
       -> Runtime-owned bounded local expansion
  -> EvidenceSpan -> Interpretation -> RequirementBinding
  -> deterministic SufficiencyDecision
  -> requirement-aware MemoryContextCompiler
  -> ContextReceipt / AccessTrace
```

When the deterministic decision still has required missing slots, DG-18 may
build a bounded `AcquisitionObservation`. The provider wire contract is the
flat, untrusted `ResidualCueProposal`; Runtime derives provenance, rationale,
source preference, and inherited temporal bounds before constructing the
historical `ResidualSearchHint` domain object. In R3 this remains shadow-only:
an offline evaluator may simulate one bounded acquisition action, while the
product response remains byte-for-byte the deterministic response. R4 is
disabled unless a new sealed R3 receipt passes treatment-delivery, mediator,
and safety gates.

The controller can propose a cue or structural action. It cannot choose final
Evidence, bind a requirement, declare `COMPLETE`, replace an operator, widen a
scope or temporal interval, change authority or permissions, answer the user,
or mutate canonical memory. Every live candidate must still pass the existing
hard filters, Evidence Gate, Binding, and Sufficiency chain.

## Contract and component map

| Concern | Runtime owner | Contract / implementation |
| --- | --- | --- |
| Query semantics | Query planner | `MemoryQueryIR v0.2` |
| Executable search | Acquisition compiler | `AcquisitionPlan v0.1` |
| Candidate provenance | Acquisition fusion | `CandidateEnvelope v0.1` |
| Cross-pass memory | Acquisition-state service | `AcquisitionState v0.1`, resolve-local only |
| Accepted span pointer | Acquisition-state service | `EvidenceReferenceNote v0.1` |
| Controller input | Residual-refinding service | `AcquisitionObservation v0.1` |
| Provider wire output | local structured provider | flat `ResidualCueProposal v0.1` |
| Runtime-normalized hint | Residual-refinding service | historical `ResidualSearchHint v0.1` |
| Hint authority | Runtime validator | allowlist, budget, plan identity, inherited scope/time |
| Evidence validity | Evidence semantics | span verification, interpretation, Binding |
| Completion | Sufficiency service | `SufficiencyDecision`, never the model |
| Reader input | Memory-context compiler | required-source reserve, then optional context |
| Auditability | Retrieval / Access trace | digests, counts, dispositions; no full private text by default |

`matched_slots` in a candidate envelope is acquisition provenance only. It is
not a Binding result and must never be used as proof that a required slot is
covered. Likewise, an `EvidenceReferenceNote` is a query-local pointer to an
exact verified span; it is not a new Evidence object or canonical fact.

## Local context and MCP compatibility

Evidence capture may include an optional structured source context with stable
session, turn, and round identities plus adjacency pointers. Old clients that
omit it remain valid and receive no adjacency expansion. Runtime must not infer
session or turn structure by parsing Evidence body text or legacy `source_ref`
strings.

The MCP change is additive:

- existing required request fields and response fields do not change;
- `source_context` is optional and strict when supplied;
- legacy rows hydrate with unknown lineage and do not expand;
- exact/current resolution performs no adjacency hydration;
- local expansion uses the authenticated session and the original immutable
  scope, `as_of`, permission, retention, and revoke filters;
- clients do not need to know about residual actions to call `memory.resolve`.

Schema additions remain experimental. Downgrade must remove only the optional
source-context projection and hydration function; it must not rewrite Evidence
or canonical history.

## R3/R4 budgets and degraded behavior

V0.1 hard ceilings are one controller call, one additional acquisition pass,
zero automatic retries, at most 12 observation candidates, at most 600
characters per snippet, and at most 192 controller completion tokens. Concrete
latency and total-token thresholds are frozen only after an R3 profile reports
p50 and p95.

Already-complete and exact/current queries use zero controller calls and zero
additional searches. Provider unavailable, malformed output, rejected action,
budget exhaustion, repeated action/window/region, or unsupported temporal
capability all return the deterministic-only result with a typed trace. There
is no hidden provider, regex repair, retry, or last-hit fallback.

The provider wire schema contains only `requirement_id`, `action`, and bounded
`cues`. It deliberately contains no `uniqueItems`, top-level action `oneOf`,
nested semantic `anyOf`, empty-array/null scaffold, provider-supplied
provenance, rationale, source role, scope, or authority. Those omissions do not
weaken the Runtime business validator; they separate guided-decoding transport
compatibility from domain and policy enforcement.

## Matched mediator definitions

- `GoldTurnCandidateRecall`: answer-bearing source turns present before packing
  divided by the fixed gold-turn denominator.
- `RequiredSlotCandidateRecall`: required slots with at least one gold source in
  the candidate set divided by the required-slot denominator.
- `RequiredEvidenceCoverage`: distinct required Evidence atoms retained divided
  by the fixed atom denominator.
- `BindingSuccessRate`: required slots with at least one deterministic `MATCH`
  Binding divided by required slots.
- `OperatorReadyRate`: cases whose required operands are bound and usable by the
  deterministic operator divided by cases.
- `PackingLossRate`: gold sources available before packing but absent from the
  Reader Context divided by available gold sources.
- `CandidateNoise`: retained non-gold candidates, reported as count and per-case
  distribution rather than hidden inside a single rate.
- `RepeatedRegionRate`: proposed/acquired regions already inspected for the same
  action and missing-requirement set divided by proposed regions.

Every safety metric is a `count / denominator`; `N=0` is not a passing negative
test. R3 unlocks R4 only with zero wrong COMPLETE, scope/authority expansion,
invalid-output product changes, and already-correct regressions, plus at least
two missing-slot cases improving gold-source rank, Binding readiness, or
OperatorReady.

Before interpreting mediator deltas, the scorer reports
`ProviderCallAttempted`, `ProviderSchemaAccepted`, `ProviderTransportMode`,
`ProviderSSEErrorObserved`, `ProviderErrorClassificationCorrect`,
`SchemaValidHintRate`, `RuntimeAcceptedHintRate`,
`AdditionalAcquisitionPassExecuted`, `NewCandidateCount`, and
`NewGovernedCandidateCount`. If there is no schema-valid hint, Runtime-accepted
hint, or executed extra pass, the outcome is `TREATMENT_NOT_DELIVERED`, the
disposition is `PARKED_PROVIDER_CONTRACT_INCOMPATIBLE`, and residual effect is
not evaluated. `PARKED_NO_MEDIATOR_GAIN` is valid only after treatment was
actually delivered.

## Operator commands

Run root-level evaluation tests with the Runtime virtual environment. Running
`uv run pytest` at repository root is invalid because the root is not the uv
project.

```bash
cd /cra/memory/mx_memory/MiLAi
runtime/.venv/bin/python -m pytest -q tests/test_dg18_r0_baseline.py

cd /cra/memory/mx_memory/MiLAi/runtime
uv run pytest -q tests/unit/test_dg18_context_packing.py \
  tests/unit/test_dg18_acquisition_state.py \
  tests/unit/test_dg18_residual_refinding.py
uv run ruff check src tests/unit
uv run mypy --strict src/milai

cd /cra/memory/mx_memory/MiLAi
runtime/.venv/bin/python scripts/run_dg18_provider_conformance.py \
  --run-id dg18-provider-conformance-YYYYMMDD-NNN \
  --model Qwen3.6-35B-A3B-FP8
```

Before a real R3 or R4 run, perform read-only identity checks. Do not restart or
reconfigure the operator-owned provider.

```bash
curl -fsS http://127.0.0.1:7860/v1/models
curl -fsS http://127.0.0.1:7860/version
ss -ltn '( sport = :5432 )'
```

Use a fresh run ID and output directory. The product/shadow phase must seal its
label-free archive before a separate scorer opens the answer-bearing opened-dev
fixture. Never pass a formal-holdout path to a DG-18 command.

## Failure reflection and adaptive design

The first packing implementation treated acquisition `matched_slots` as if it
were validated coverage and missed source pointers nested in deterministic
operator operands. The correction derives required-source priority only from
safe deterministic operands and verified Binding-compatible references, then
reserves those windows before optional context. This generalizes across query
wording and operators without adding benchmark-specific terms.

A bounded-snippet test also found that prefix/suffix ellipsis markers could push
a 600-character body beyond the 600-character schema. The builder now reserves
marker space inside the same fixed limit; the schema was not relaxed.

The residual validator binds the state digest to the exact acquisition plan and
requires temporal hints to narrow inherited hard bounds. Event-time refinding
fails closed until a governed event-time capability exists. These checks make
the controller adaptable at the cue layer while keeping authority, scope, and
completion deterministic. A no-gain conclusion is permitted only after valid
proposals pass Runtime policy and execute an extra acquisition pass. Otherwise
the correct terminal state is `PARKED_PROVIDER_CONTRACT_INCOMPATIBLE /
RESIDUAL_EFFECT_NOT_EVALUATED`, not more hidden rounds, regexes, or model
authority.

## Executed disposition (2026-08-28)

| Stage | Result | Bound evidence |
| --- | --- | --- |
| R0 | `PASS` | 33 predevelopment artifacts frozen; receipt SHA-256 `a4df3c…3b66` |
| R1 | `PASS` | fresh PostgreSQL/MCP LME archive `003`; 10 cases, 40 records |
| R2 | `PASS` | resolve-local typed state, exact Evidence notes, bounded trace; zero model calls |
| R3 | `TREATMENT_NOT_DELIVERED / PARKED_PROVIDER_CONTRACT_INCOMPATIBLE` | historical receipts preserve their old disposition string; 0/10 valid hints and 0 extra passes mean residual effect was not evaluated |
| R4 | `NOT_EXECUTED_NOT_AUTHORIZED` | R3 hard gate did not pass |
| R5 | `NOT_EXECUTED_PARKED_NOT_NEEDED` | no evidence that a second round is justified |

The final opened-dev LME product archive is
`var/dg18/r1/dg18-r1-q1r-contexts-20260828-003/contexts.json` with SHA-256
`3d98d1…b4de`. It was sealed before evaluation labels opened. Both 512- and
2048-token policies acquired 11/23 required atoms and retained the same 11/23,
so packing loss is `0`; wrong COMPLETE and wrong scope/authority are also `0`.
This closes R1 without claiming that retrieval recall itself is solved.

The final fresh-database Runtime gate passed `508` tests with one optional
client-package skip and successful database cleanup. Runtime unit tests passed
`379/379`; MCP tests passed `37/37`; the focused root DG-17/DG-18 evidence suite
passed `18/18`. Strict mypy and Ruff passed for the Runtime and MCP sources.
Formal holdout consumption remains false.

### Post-closure provider-contract calibration

The synthetic, deidentified conformance run
`var/dg18/provider-conformance/dg18-provider-conformance-20260828-001/receipt.json`
was retained after its summary counted flat-action JSON parsing under the
`PydanticParsed` label. The corrected final run is
`var/dg18/provider-conformance/dg18-provider-conformance-20260828-002/receipt.json`
and is `PASS_PROVIDER_CONFORMANCE`. It binds vLLM `0.27.1` and model
`Qwen3.6-35B-A3B-FP8`; all six flat action/lexical/temporal transport cells pass,
four application proposal cells pass Pydantic plus Runtime acceptance, and the
two action-only cells are separately recorded as JSON-object parses. The deliberately
historical `uniqueItems` negative returns HTTP 500 in non-streaming mode and a
top-level SSE `InternalServerError` code 500 in streaming mode. The latter is
classified as `SEMANTIC_HINT_PROVIDER_SSE_ERROR`, not `EMPTY_OUTPUT`, in
`typed-sse-error-receipt.json`.

This calibration does not rewrite either historical R3 receipt and did not run
the 10-case LME, consume formal holdout, execute an extra acquisition pass, or
authorize R4. It only permits a separately sealed synthetic shadow fixture as
the next gate; full LME remains disabled until multiple valid, Runtime-accepted
hints truly execute additional acquisition in shadow.

The post-calibration fresh PostgreSQL gate `004` passes `516` tests with one
optional client-package skip and successful database cleanup. Attempt `003` is
retained as a failed receipt: one 25 ms retrieval-deadline integration case
crossed its cold-start boundary (`515` passed); the immediate independent fresh
database run passed the same full suite. No retrieval code was changed to hide
that timing observation.

## Failure ledger and learning

1. The first real Q1R attempt failed because the public MCP schema accepted
   `source_context` while the strict server argument allowlist rejected it.
   The partial run was preserved, the allowlist was aligned, and a direct MCP
   forwarding regression was added. Fresh runs `002` and `003` then succeeded.
2. R1 initially reported one 2048-token and two 512-token packing losses. The
   packer was correctly reserving available required windows; the missing
   windows were deterministic operator operands omitted from final result
   `items`. Runtime now recovers only an exact, timestamped `EVIDENCE_ONLY`
   operand span with a unique Evidence/source reference. It does not synthesize
   missing text, and a no-span operand still reports loss. This is independent
   of case IDs, benchmark synonyms, language, operator, and session layout.
3. R3 run `001` made five one-shot provider calls whose nonempty content failed
   Runtime validation; the exact historical validation field is unknown because
   it was not persisted. Run `002` recorded five `EMPTY_OUTPUT` failures. The
   later transport reproduction proved that the historical guided schema's
   `uniqueItems` is unsupported by xgrammar: non-streaming returns HTTP 500,
   while streaming returns HTTP 200 plus a top-level error event that the old
   parser ignored. Therefore 0 valid hints and 0 extra passes are treatment
   delivery failure, not evidence of zero residual gain.
4. The first final full gate found one real observability defect and eight stale
   migration-head assertions. Evidence-dense embedding used the shared batch
   provider without incrementing the shared inference-batch metric; accounting
   now covers both evidence and window projection. Tests that explicitly
   upgraded to `head` now expect `0045`, while historical intermediate and
   downgrade assertions remain unchanged. The failed gate report is retained;
   the fresh `002` gate passes.

The general design lesson is to keep adaptability in query-local, typed
mediators: new cue wording or structural actions can be proposed without
changing tenant, principal, permission, time, authority, Binding, Sufficiency,
or canonical state. Provider incompatibility or weak model behavior therefore
parks an optional optimization instead of degrading the deterministic product.
