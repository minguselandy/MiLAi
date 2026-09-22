# Revision / Attention — zero-model readiness, 2026-09-23

Status: **preparation only; model execution NOT_ADMITTED**. Base/rollback is
`fcefea3f8944755b555f60817f6ba007290ae184`, verified against remote main. No new
task allocation, experiment, Provider probe, embedding, generation, maintenance,
Judge or shared-service change. The Utility batch is closed, not a budget pool.

This document closes a concrete input/implementation question for Goal 3C-2/3C-3;
it does not substitute a readiness document for either mechanism's required effect
evidence or honest terminal. No overall Goal completion is claimed.

## 1. Revision: what the inspected inputs actually support

Read only the already exposed DB/OS banks used during Utility preparation, their
completed-task memory events and v0.7 Provider receipts. Membership was checked
against frozen DEV/VALID in `experience-optimization-20260916/splits.json`, SHA
`45d48b75bac9dff70cd858bb1ff3f76ee41aa464f7dc814ebf22e3495aa389f9`.
No TEST, main confirmation, Travel, RESERVE, SUPPORT bank or wider source search.
All paths below are relative to `/cra/memory/mx_memory/evidence/`.

| Bank | Completed positions | Current cards | Historical cards | Changed patches |
| --- | ---: | ---: | ---: | ---: |
| `experience-optimization-20260916/native-validation-v06/valid-db_bench-milai` | 12 VALID | 19 | 0 | 0 |
| `experience-optimization-20260916/native-validation-v06/valid-os_interaction-milai` | 8 VALID | 14 | 0 | 0 |
| `evidence-utility-improvement-20260916/d1-native-smoke/d1-db_bench` | 2 DEV | 2 | 0 | 0 |
| `evidence-utility-improvement-20260916/d1-native-smoke/d1-os_interaction` | 2 DEV | 2 | 0 | 0 |

All 37 cards are revision 1. The v0.7 banks have four registered versions and zero
predecessor links. DB has seven settled Actor exposure records (three nonempty);
OS has five (all empty). All 12 were joined by task/role/request ID to SETTLED
Provider entries and the actual request-byte SHA. Native feedback is null under H.
Those three nonempty DB exposures concern an original version, not a correction.
The v0.6 banks lack v0.7 utility-state records: that absence is **not** a claim of
zero historical exposure. Zero changed patches was checked in their memory events.

Content identity, in table order (`bank.json` SHA-256):

```text
de1fc0eb17769df6c77f967f71f305d9a83498d399ba2cc33167e9db49d31b51
36dbd50ecf49b3f0da0a18b693bbfb1bd18ca5a007158a63b4af552b836384be
2ea351c83dffc6c815da8987f2260c241db880a41fd569eb5c02f153154b69ad
0a0e960fac146f0594a2483c216b7274945e7d80ebf1b627baee81986918f4bb
```

Completed-task event counts are 12/8/2/2. Aggregate event identities below hash
UTF-8 `json.dumps({absolute_path: file_sha256}, sort_keys=True, separators=(',', ':'))`:

```text
72df2e2eb5a7043e4d049a072613cd7b9af8a532b5281d46cfcd72c8fb2ed25d
542018169c79cd2ebb54ab154cecd1ccf3cc7a137e1361eb20beb710b8b2bc83
a1d689da8d03fcc17c2d2af266d051b3e7addceb554229723dc4e3a63574ffec
92efce67ed87ee9991bf7ba41411e4acffd8b13bdb3627e57ee0e78320224a7d
```

v0.7 DB/OS Provider-ledger SHAs respectively:
`66a7078db1f3cd941d9d8c5150da51d41060930e0199560f312e5b967f892678` /
`2994ce4a9d19aade784e77e80c32607b8e3b8ce5ad170d06495db19f732ad990`.

**Admission finding:** these four inspected banks have no existing revised-version
later-exposure opportunity. Do not launch a model comparison by relabeling original
version reuse, adoption, or shorter projection as correction. This is a bounded
input finding, not exhaustive absence across the frozen pool, a negative mechanism
result, or a terminal for all of 3C-2. Historical Travel later-use claims were not
imported into the DB/OS denominator.

## 2. Revision: minimum seam identified (implemented in the follow-up)

The current [revision engine](../src/milai_lab/methods/experience_revision.py)
already supports `replace` / `append_only`, expected-version checks, original
source references, historical-card retention and task-local updates. The
[v0.7 session](../src/milai_lab/methods/evidence_utility_session.py) links predecessor
and feedback refs; [VersionUtility](../src/milai_lab/methods/experience_utility.py)
keeps a new version uncalibrated and binds exposures to settled requests. Preserve
those implementations and historical policies; do not build another bank engine.

The existing [Opportunity Ledger](../src/milai_lab/analysis/opportunity_ledger.py)
already declares the five revision types, predecessor/new exact versions, policy
and evidence refs. `_bind_revisions` validates chronology and binds later retrieval,
exposure and use; its tests include later exact-version reuse. Do not implement
that accounting again. Its current admission accepts Product/testkit/simulation
owner facts, not RESEARCH_PROTOTYPE facts; `independent_task` means different task
IDs, not verified source-cluster independence. That is an accounting boundary,
not this study's complete semantic-effect admission.

The incremental requirement is an explicit **research eligibility bridge**, reusing
the existing vocabulary and version accounting, with these supplied facts:

- Exact old and new version identities/content hashes, predecessor, originating
  task and source cluster, policy version, original evidence and visible feedback
  refs, plus changed claims/applicability.
- Predeclared type `CORRECTION / SCOPE_NARROWING / SCOPE_EXPANSION /
  EXAMPLE_REFRESH / RETIRE`. Core correction denominator includes only the first
  two; textual change alone does not assign a type or establish support.
- Evidence review is explicit: supported / unsupported / unknown. Missing source
  or feedback is not supported, H cannot import a hidden native correctness label,
  and a retired memory is not a correction exposure. No inherited old-version reward.
- A later **independent** task must retrieve the lineage and expose the exact new
  version in a settled Actor request. Same-task rereads, formation, selection and
  unconfirmed preparation are not later-reuse evidence. Missing cluster identity
  leaves independence UNKNOWN rather than assuming it from different task IDs.

Future matched arms are APPEND_ONLY versus REVISION, sharing original input,
visible feedback, candidate pool and solver/native conditions. The existing append
mode retains old text plus the appended proposal, a declared context-cost difference
to measure, not hide. Charge formation/revision/source reads and every failure even
if no later exposure occurs. No-reuse proposals cannot claim answer effect.
`REVISION_WITHOUT_SOURCE_CHECK` is not admitted by this document.

The follow-up [research eligibility bridge](RESEARCH_REVISION_ELIGIBILITY.md) now
implements this content-free seam, with narrow synthetic contract tests for
type/support/independence/version/receipt rejection and the existing session join.
Synthetic fixtures prove the join, not real correction or benefit. A real run still
needs frozen evidence/feedback, independent later tasks, semantic review, IDs/order,
paired baseline, success/stop criteria, source pins and a new finite authorization.
Do not synthesize benchmark corrections or tune branches for known case IDs. Do not
forge Product owner facts to pass the current ledger, weaken its old contract, or
rewrite the earlier accounting proof as if it established source-group independence.

## 3. Attention: reuse boundaries and proposed state contract

Existing [state_focus](../src/milai_lab/methods/state_focus.py) is a versioned
FULL/FOCUS **projection** over caller-supplied source units. It neither retrieves
nor implements CONFLICT/EXPLORE. Its request builder has seed 42/output cap 1024,
not current M1 seed 213/Actor cap 4096. Do not call it unchanged as the new solver
path or silently edit its historical contract. [state_control](../src/milai_lab/methods/state_control.py)
likewise compares control text with full materials; it is not the requested bounded
state-guided retrieval policy. Representation/eligibility ideas can be reused;
historical effect claims and model envelopes cannot.

The follow-up [Attention policy seam](STATE_ATTENTION_POLICY.md) implements the
pure deterministic decision described here; real retrieval integration, reviewed
state opportunities and effect evidence remain outstanding. The intended seam is over explicitly supplied
Lab state and eligible references, with **no Provider, model, storage or dispatch**.
It must not infer semantic relevance or conflicts from hidden scores or test outcomes.

| State | Owner / source | Freshness | Absence semantics |
| --- | --- | --- | --- |
| Current question / active goal | Current authorized task/Host input | Bind task + input hash at each decision | Missing question blocks decision; absent goal is not an inferred goal |
| Hypotheses / next actions / memory intentions | Explicit visible Actor/Host working artifact | Bind producer turn + source refs; never carry across task reset implicitly | UNKNOWN, not empty verified state |
| Failed approaches / unresolved constraints | Visible native tool feedback or explicit working artifact | Only observations preceding the decision | No hidden evaluator label; missing is UNKNOWN |
| Uncertainty / open conflicts | Explicit fallible working assertions with supporting refs | Recheck exact versions/scope/availability now | Missing/stale is UNKNOWN, not confidence or resolved conflict |
| Recent evidence | Exact-version source/observation references | Revalidate eligibility at preparation and dispatch | Denied excluded; unknown eligibility fails closed |

Implemented candidate priority: supported current conflict → CONFLICT; otherwise an
explicit current coverage gap → bounded EXPLORE; otherwise FOCUS. This is a design
candidate, not a frozen live experiment protocol. Stale, absent or unsupported state falls back
to the declared simple baseline without invented certainty. Unknown coverage does
not authorize unbounded expansion. FOCUS selects current relevant references;
CONFLICT preserves both eligible sides; EXPLORE can make at most one extra bounded
retrieval before convergence/abstention. Exact query formation, candidate limits,
coverage rule and the baseline must be frozen before a real comparison.

Initial checks should measure unnecessary retrieval, irrelevant exposure, evidence/
conflict coverage and complete token/latency cost before any answer-effect expansion.
Coverage/relevance labels require task-visible evidence review independent of arm
outcomes; unsupported labels remain UNKNOWN. Cached text/byte replay can demonstrate
policy or projection differences, not server token costs or native quality. No extra
controller LLM. No adoption proxy is silently promoted to coverage or causal utility.

## 4. Admission and remaining Goal scope

At the readiness checkpoint, the next safe work was zero-model contract implementation
in separate scoped Revision and Attention work packages. Revision's engineering seam
and Attention's pure decision seam are now linked above. The next gate is real-input
and finite-run admission, not further scope-free implementation. Do not first re-run
old suites or broaden the data scan.
Before any real execution, ask for a separate finite data/model/request/token/time
allocation and freeze missing protocol fields. Previously closed Utility/legacy
allocations remain closed; no TEST/confirmation/Travel/RESERVE expansion is implied.

Utility's scoped KEEP_SIMPLE terminal is closed through PR #42: exact-head fast
`35748269576`, identical candidate/merge tree `0831c6594385ab0fd0561ee4c3d80e2bc8e20f94`,
merge `fcefea3`, and main fast `35749519699` PASS. Lab CI 4,693 PASS / 137 SKIP /
4 DESELECTED; [remote closure](https://github.com/minguselandy/MiLAi/pull/42#issuecomment-5779535907).
Revision and Attention have no effect terminal yet. RL-like adaptation, transfer,
second solver and promotion remain unadmitted; the limited Utility selection changes
do not alone establish the matched repeatable signal required for transfer.

The original readiness package (PR #43) changed documentation only; the linked
follow-up adds Lab-only eligibility code, not an effect run. No Schema/API/permissions/Canonical or
Product executable change; C06/C21 remain explained OPEN debt, Conformance remains
UNVERIFIED and Schema remains NO-GO. The original documentation-only validation
was L0 links/diff, boundary, Product identity and Conformance freshness, without
package, benchmark or full-composition reruns. Follow-up checks are in its own receipt.
