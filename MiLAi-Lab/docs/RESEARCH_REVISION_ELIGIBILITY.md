# Research Revision eligibility bridge

Status: **zero-model engineering slice; no effect execution or terminal**.
Base/rollback: `ba88a572f956f9ef4e96ab04e4ad9d988e95d544` (PR #43 main).
The closed Utility allocation is not reopened. No existing bank, frozen protocol,
historical version contract, Product behavior or Opportunity Ledger schema changes.

## Purpose and API

[revision_eligibility.py](../src/milai_lab/analysis/revision_eligibility.py) adds two
pure functions over the existing `ExperienceBank` / `VersionUtility` checkpoint.
It supports both same-handle replacement and append-only new-handle predecessors.
It neither creates a revision nor dispatches a request, scores quality or assigns
reward. Output is always `RESEARCH_PROTOTYPE`, never a Product owner fact.

1. `freeze_revision_review(bank, review)` validates the exact predecessor/new
   versions, original evidence and registered feedback, then returns a content-free
   review seal. It binds scope, bank contract, card/version hashes, source-content
   hashes, feedback release and review declarations. The caller must persist it
   **before** the later task; the function itself does not persist or prove timing.
2. `assess_revision_reuse(bank, sealed, later_task_id=..., later_cluster=...,
   retrieval=..., actor_receipt=...)` checks the unchanged seal, retrieval chronology,
   completed-task order and the exact version in a confirmed Actor exposure. It
   reuses the existing SETTLED receipt contract, including request ID/payload hash.
   Validation does not mutate the bank. Historical revised versions remain joinable
   after a newer version is published.

The review schema is defined in the module. It requires revision/source-task IDs,
creation reference, policy version, created/review sequence, predeclared type,
changed claims/applicability, exact original evidence refs, feedback visibility,
semantic-support status/reference and complete transitive lineage clusters/reference.
The retrieval fact carries `ref`, `task_id`, `scope_sha256`, integer `sequence` and
an exact `version_keys` array. The Actor receipt adds its integer `sequence` to the
existing NativeProvider receipt. Sequence order is creation < review < retrieval <
Actor exposure; chronology must come from the same authenticated runner timeline.

## Decision and claim limits

| Condition | Result |
| --- | --- |
| Supported CORRECTION/SCOPE_NARROWING, independent later task, retrieved lineage and exact settled exposure | `eligible: true` for structural eligibility only |
| Other type, unsupported correction, metadata-only text, retired version, shared cluster, same task, hidden H outcome, wrong/missing retrieved or exposed version | `eligible: false` |
| Missing support, feedback visibility/release, complete lineage/provenance or confirmed exposure | `eligible: null` / UNKNOWN |
| Invalid schema, mutated seal, invalid lineage/scope/chronology or mismatched existing receipt | validation error; never eligibility credit |

Rejection takes precedence over UNKNOWN. `observable_use` stays UNKNOWN and the
claim ceiling is `STRUCTURAL_ELIGIBILITY_NOT_BENEFIT`, including for `true`.
`SCOPE_EXPANSION`, `EXAMPLE_REFRESH` and `RETIRE` are not core corrections; this
reuses the Opportunity Ledger vocabulary without extending its Product schema.

The module is **not a semantic judge or authenticity service**. A caller must
authenticate creation/retrieval/Provider receipts and resolve support/provenance
references, verify that the declared source task really produced the revision,
and review every transitive original/feedback/formation source cluster. Different
task IDs alone do not establish independence. A checksum binds supplied facts;
it does not prove their truth or that a caller sealed them before seeing results.
Review declarations must use non-private metadata/references; the API does not
redact arbitrary caller strings or make a raw-content-bearing review safe to publish.
Do not count unauthenticated declarations as a real research denominator.
H must use visible evidence only; R can use only an already released native bit.
No old-version reward is inherited, and no adoption proxy becomes observed use.

## Verification and remaining work

[Synthetic tests](../tests/unit/test_revision_eligibility.py) exercise replace and
append lineage, source-content sealing, H/R visibility, unknowns, rejection,
chronology, exact receipts and historical-version reuse. One test uses the existing
session's revision → checkpoint/restore → later Actor exposure path, sealing before
the later session. All text, responses and receipts are fixtures; its synthetic
`TEST` scope comes from the existing helper, not access to protected TEST data.

Local targeted suite: **62 PASS** (new module plus existing VersionUtility and
Opportunity Ledger tests); changed-file Ruff/mypy PASS. Classified Lab fast CI
owns package-wide checks/build; no Product full or historical replay is requested.

The [bounded readiness finding](REVISION_ATTENTION_READINESS.md) still holds:
the four inspected real DB/OS banks contain no revised-version later-exposure
opportunity. These fixtures do not fill that gap. A real matched APPEND_ONLY versus
REVISION comparison still requires authentic pre-outcome review, frozen independent
later tasks, common conditions, complete formation/revision/retrieval/failure costs,
paired native quality, stop criteria and a separate finite authorization. This
bridge alone closes neither 3C-2 nor the overall Goal. Attention implementation is
a separate zero-model work package; transfer/promotion remain unadmitted.
