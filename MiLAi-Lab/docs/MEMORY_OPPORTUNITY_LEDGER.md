# Memory Opportunity Ledger v1

Status: 3B-2 PASS for the declared engineering/accounting scope; PR #39 merged,
exact-head CI, candidate/merge tree and main identity verified.
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
is needed for this Lab-only increment.

## Actual bounded execution, 2026-09-22

[Compact proof manifest](../data/manifests/memory-opportunity-ledger-proof-20260922.json)
binds source `7dbaeeca27f3515542f111bdb0ab699e0cbf7982`, the unchanged Product tree
`847967d2e212b974d92b0b08d6e0f8b135a3c1080adf61790dcb771b9c832311`, verified
run-specific lock and all five method-source digests. Raw artifacts are outside Git
at `/cra/memory/mx_memory/evidence/post-cleanup-3b2-20260922-PSUMpe/claim-cache`.

The actual chain passed: 10 Host attempts, 9 fixture invocations, 5 fresh Runtime
reads, 5 cache validations, 4.696 seconds. Ten snapshots were persisted before their
outcomes; original owner facts and observation inputs deterministically regenerate
the exact saved ledger. Governed Canonical supersession invalidates the original
cache and yields a fresh exact version, followed by actual validated reuse.

Funnel: 2 logical query tasks / 10 attempts; 7 with memory available; 0 multi-choice
selection opportunities; 5 with known exposure. All task outcomes and observable
use stay UNKNOWN. All 10 attempts remain in accounting despite the zero selection
denominator. The controlled fixture reports 30 input / 18 output units, with 3
failed/unknown requests retaining unknown usage. Embedding counters are not exported
and remain null on every row; zero model requests/tokens is not used to fabricate
zero embedding calls. There is no matched mechanism or quality-effect claim.

This run proves real pre-outcome capture and fresh/cache accounting. The additional
multiple-choice, supported-use and revision-effect cases remain **simulation-only**
proof, explicitly separated in the manifest; no synthetic support is attached to the
real rows. New model research requires the Phase 3C preflight and finite authority.

Only the dedicated synthetic database container was started; migration
`0056_host_notes` and role-separated connections were checked. It was stopped after
execution with data retained. The newly generated capability file was removed;
public/shared services and Product executable source were unchanged.

Reproduction uses the existing trace-probe command with the exact source commit
above plus `--canonical-cache --opportunity-ledger`, fresh output and isolated role
URLs. Do not reuse a historical random port without inspecting the container.

## Remote closure

PR #39 tested head `e72c2370d915ff3db2d2f483a479331b1eccca94`; fast workflow
`35717333297` PASS. Classified Lab verification: 4,657 PASS / 137 SKIP / 4 DESELECTED,
461.49 seconds, plus package static/build and archive integrity checks. Skips concern
optional SDK/external historical inputs, not the 107 targeted accounting tests.
Product Runtime/integration suites and full composition were not run.

Expected-head squash merge `53e13c47c72a3f49f4cd66007320083babdc07be` has the same
tree `897f16db73433f212a98ab4fc9e992c6477d0c13` as the tested candidate. Local main
was fast-forwarded to origin/main; main identity fast `35718296416` PASS. The compact
proof manifest remains the immutable local-run snapshot; this section supplies the
later delivery closure. Phase 3C is subject to the
[unallocated research preflight](POST_CLEANUP_RESEARCH_PREFLIGHT.md), not automatically started.
