# Memory Opportunity Ledger v1

Status: implementation and offline proof; real bounded-run proof pending.
Work package: `MILAI-POST-CLEANUP-DEVELOPMENT-01 / 3B-2`. Lab-only accounting,
not Product routing, a research allocation or a mechanism-benefit claim.

## Contract and ownership

`milai_lab.analysis.opportunity_ledger` consumes validated owner facts from the
[Trace Ownership contract](../../MiLAi-Product/docs/reference/trace-ownership-v2.md)
and a separately declared observation document. `export_owner_attempts` exposes
validated join-input facts; the existing `assemble_owner_attempts` joined-output
API remains unchanged. No Product private import or canonical write is involved.

The observation schema is `milai-memory-opportunity-ledger-v1`. Unknown properties
are rejected without echoing their contents. Inputs contain identities, hashes,
counts, reason codes and support references, not prompts, answers, hidden scores
or credentials. References alone do not prove their external evidence exists.

Each attempt binds run, arm, logical task, Host attempt/retry, Product lock, method
hash/version, policy, arm kind and usage kind. Product owners supply actual
acquisition, selection, dispatch, request usage and exact version facts. Lab owns
declared alternatives, explicit decisions, task outcomes and supported revision
lineage. A successful transport is not a task-quality score.

## Pre-outcome opportunities

`freeze_opportunity` seals the task-input digest, sequence, ordered available
versions, ordered alternative bundles and optional prior comparison reference.
The caller must persist that snapshot before the corresponding outcome. Hashes
and sequence checks detect inconsistency; they do not authenticate chronology.

Availability means the **observed authorized/materialized pool for this attempt**,
not all memories in the database or all theoretically retrievable candidates.
Fresh reads count actual acquired versions. Validated cache reuse preserves the
origin's selected versions as available, but contributes zero fresh candidates
and zero fresh retrieval calls. Equal text does not establish cache provenance.

Alternatives must be nonempty, distinct, exact-version subsets of that pool. The
caller declares their task relevance before the outcome; the validator cannot
infer semantic meaningfulness from distinct hashes. A matched selection comparison
requires the same logical task, task-input digest, ordered pool and alternatives,
with a different arm and an already observed baseline. Without one, selection
change remains UNKNOWN, not false. Full matched-effect validity additionally needs
the frozen model/tools/budgets/feedback protocol required by Phase 3C.

Every Provider request retains exposure status, Context digest and ordered versions;
flattened exposure preserves repetitions. Adoption is explicit selected-version
support, rejection is explicit available-version support, and neither is inferred
from selection or success. Observable use requires the trace contract's successful
request/exact exposed-version support. Otherwise use remains UNKNOWN. All rows have
`causal_attribution=NOT_ESTABLISHED`.

## Revision and accounting

Revisions bind predecessor and new exact version, policy, type, supporting evidence
references and a declared revision opportunity. Creation must follow its source
outcome and precede every observed reuse of the new version. Later fresh retrieval,
exposure and supported use remain separate; independent logical tasks are marked.
An unused revision is retained, not reported as an effect. Corrections and scope
narrowing must remain distinct from scope expansion, example refresh and retirement.

Known failed-request usage is counted. A partially unknown token sum stays null,
alongside the known subtotal and unknown request count; unknown embedding, latency
or maintenance counters need explicit reasons. Host and Provider failures retain
their separate owner identities, not an inflated count of independent task failures.
Fixture token units are not model tokens, and fixture mode requires zero model
generations. Maintenance costs include unused revisions.

The funnel reports distinct logical tasks, attempts, independently observed stage
counts, unknown comparisons and eligible attempts per arm. It is not a forced
monotone conversion funnel. The initial `mechanism_effect_denominator` is only
selection opportunity (at least two observed candidates and two declared bundles),
not a research-effect sample size. Utility discrimination and matched protocols
are additional admission gates. Revision research must separately count independent
later exposure of the named revisions. No-opportunity attempts stay in total
quality/cost accounting.

## Real capture path

`tools/run_trace_ownership_probe.py --canonical-cache --opportunity-ledger` reuses
the existing actual Runtime/HTTP/PostgreSQL/MCP/Host probe. The model endpoint is
never contacted; the transport is a controlled in-process fixture. Ceilings remain
10 Host attempts, 10 fixture invocations and 120 seconds, in a fresh synthetic tenant
on an explicitly isolated, already migrated database with separate role URLs.

Before any fixture response or intentional transport failure,
`OpportunityCapture.before_transport` reads the public Runtime owner exports and
writes an exclusive `opportunity-NN.json`. The initial empty-pool controls are
sealed before Host execution, before any fixture Evidence/Claim has been inserted.
Final owner facts must agree with those declarations. Outcomes are saved separately
after Host completion and bind the snapshot's file hash. The method source hashes,
Product lock, input hash and zero-model ceilings are frozen in the run manifest.

Outputs: `ledger-owner-facts.json`, `ledger-observations.json`,
`opportunity-ledger.json`, per-attempt snapshots/outcome records, existing producer
exports and compact summary/failure metadata. Files are private, new-per-run and
outside Git. Snapshot edits, missing pre-outcome capture and unobserved cache origins
fail rather than being reconstructed after the result.

This probe leaves task outcome and use UNKNOWN and embedding calls unobserved. Its
single-candidate/cache path is not a Utility comparison. Canonical supersession in
the trace fixture does not by itself supply a Lab revision-opportunity/evidence
record, and is not silently counted as research revision. The offline matrix covers
multiple choices, supported use, known/unknown failure costs and revision reuse;
synthetic evidence is not relabeled as real model behavior.

## Narrow verification

From `MiLAi-Lab/`, run the changed-module Ruff/mypy checks and:

```bash
.venv/bin/pytest -q tests/unit/test_opportunity_ledger.py \
  tests/unit/test_opportunity_capture.py tests/unit/test_owner_exports.py \
  tests/unit/test_trace_join.py tests/unit/test_trace_cache_join.py --tb=short
.venv/bin/milai-lab-check-boundary
.venv/bin/milai-lab-check-tools-boundary
```

The 107 targeted tests passed. The first added cache test had a test-module import
collection error; correcting the import required no production change. Changed
Ruff/mypy and both boundaries pass. CLI `--help` passes in the pinned public-testkit
environment. No Product suite, model request, historical replay or full composition
is needed for this Lab-only increment. Actual run identity/results remain pending.
