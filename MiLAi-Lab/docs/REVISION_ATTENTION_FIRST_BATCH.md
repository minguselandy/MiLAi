# Revision / Attention: authorized joint finite batch

2026-09-23. **SCHEDULE_FROZEN / METHOD_NOT_ADMITTED / zero new requests**.
The user explicitly confirmed the complete new finite contract, then repeated its
data/formation/model confirmation. No further budget confirmation is required.
This is a new joint allocation, not reopening Utility or any historical allocation.
Base/rollback: `39dc657a5967c0586355b6bea23c56e9a1812ee3` (PR #46 main).

## Frozen allocation and authority

[Allocation](../data/manifests/revision-attention-allocation-20260923.json) SHA-256:
`02d316916799358ca39e37559037400919b5abb5228f56e769dc3799b5117576`.
It preserves the old exposed task/cluster metadata and frozen split identity, not
the old batch's arms, execution permission or unused allowance.

| Mechanism | DB independent IDs | OS independent IDs | Arms |
| --- | --- | --- | --- |
| Revision | 33, 62, 94, 134, 159, 163 | 120, 194, 226, 428, 2, 16 | APPEND_ONLY / REVISION |
| Attention | 175, 223, 240, 246, 248, 256 | 47, 211, 242, 250, 355, 467 | STATIC / ATTENTION |

These are development-use positions from the existing frozen **DEV/VALID** pools,
not a claim that every source partition is named DEV. Each domain retains repeat
positions 0/3/6/9: DB 33/134/175/246 and OS 120/428/47/250. Totals shared by both
mechanisms: **24 independent + 8 repeat pairs; at most 32 pairs / 64 arm executions**.
Each mechanism has 12 independent + 4 repeat pairs, not another full allocation.

The first-six/last-six assignment follows the pre-outcome preparation proposal.
Positions interleave `0,6,1,7,2,8,3,9,4,10,5,11` so neither mechanism is wholly behind
the other in the finite allowance. At each position run DB then OS; its fixed repeat
immediately follows that two-domain block. Original arm order is counterbalanced by
position/domain parity, with reversed order on its repeat. The JSON lists all 32 pairs
explicitly. No ID, allocation, repeat or arm-order replacement based on results.

Allowed: new revisions and explicit working state derived from existing frozen,
already exposed, task-visible DB/OS feedback. This is not permission to use hidden
native correctness, fabricate correction opportunities or treat adoption as use,
coverage or causal utility. No TEST, main-confirmation, Travel, RESERVE, SUPPORT,
new solver, reranker, endpoint or changed common execution conditions.

## One shared hard ceiling

- Qwen3.6-35B-A3B-FP8 at `http://127.0.0.1:7860/v1`, unchanged M1: seed 213,
  top_p 1, thinking off, Actor temperature 0/output cap 4096; existing memory-role
  caps/temperatures and 65,536 context cap are explicit in the allocation.
- Existing bge-m3 endpoint/1024-dimensional query-instruction contract only;
  rerank **0**. Cached vectors are available for all 24 queries (below).
- Text generation at most **400 requests / 3,000,000 reported tokens**; embedding
  at most **128 requests / 50,000 tokens**; all outbound model/embedding requests
  combined at most **528**. Failures, retries and maintenance count. Unknown usage
  retains a verified upper bound, never zero.
- Existing `FiniteResearchBudget` and gated transports are reused with one new
  admission-bound ledger, never the closed Utility ledger. Auxiliary tokenizer and
  model-info requests conservatively consume text request slots, as before.
- At most **14,400 wall-clock seconds from the first new external request**. Stop
  new requests at the deadline; preserve completed, failed and unfinished entries;
  no extension, reset, makeup, independent per-mechanism budget or second batch.

The timer has **not started**: preparation used no Provider, embedding, generation,
maintenance or endpoint probes. No new budget ledger has been opened yet.

## Actual offline input preparation

[prepare_revision_attention.py](../tools/prepare_revision_attention.py) validates
the exact frozen schedule, old metadata/split hashes and exposure receipts. It
exports private source-pinned review material; it does not declare semantic support.
The four existing development banks supply **39 structural old-card/later-visible-
feedback windows**, not 39 independent examples or supported corrections. Original
formation trace refs and complete retrieved-source ancestry are carried separately;
target clusters present in that ancestry cannot count as independent later reuse.

All 24 exact query vectors are now reusable with **zero new embedding requests**.
Twenty-one come from previously matched instructed-query request/response files.
The three missing standalone caches (OS 120/226/2) are recovered from their own
already exposed historical bank's exact query record, only after matching domain,
DEV/VALID scope, query bytes, bge-m3 dimension/encoding and retrieval-instruction SHA.
OS 120 uses its existing `dev-current-v03-os_interaction-milai` bank solely for that
query-vector projection; it is not an additional candidate-memory bank. No own-task
cards, extraction, self-judgment or native outcomes cross this boundary. The producer
stores the original `start()` query vector in its record; it is not outcome-derived.
This resolves cache availability, not revision/state semantic eligibility.

Private output outside Git:
`/cra/memory/mx_memory/evidence/post-cleanup-revision-attention-20260923/input-review-complete/review-inputs.json`
SHA-256: `7c8f7c2fcd51a4327123a28c5e43e88fdaef74bde656b9fd530d2d289c6e86bb`.
It pins 76 source files, 24 queries/vectors and 39 windows; automated preparation
took 0.069 s. This is **not** total review/formation cost. The earlier window-only
preparation remains preserved under `input-review/`, not overwritten.

A separate `candidate-preflight.json` beside that report evaluates the common
four-bank pool (matching domain, whole-source-cluster exclusion, stable top-1 cosine).
All 24 positions have eligible candidates. Seven of the 12 independent Revision
positions have an independent visible-feedback window for a top-1 card; five do
not. This is still **structural review eligibility, not seven supported corrections**.
The common pool/routing must enter the final method seal; this preflight is not a
live effect run or permission to alter fixed repeats to favor opportunities.

## Remaining execution admission (not another permission request)

1. Review exact sources/visible feedback; fix the revision proposal/source-check
   procedure and classify CORRECTION/SCOPE_NARROWING separately from refresh or
   unsupported changes. Preserve top-1 retrieval; do not enlarge it to force reuse.
2. Freeze the explicit Attention state producer, independent relevance/conflict/
   coverage labels, baseline and expansion rule. Neither historical adoption nor
   a query-vector match is a semantic review.
3. Complete and verify the minimal runner using the existing revision engine,
   eligibility bridge, Attention policy/capture, native M1 adapter and global budget
   guard. Pin native environment, method/policies, common conditions and exact inputs
   before first request. Preserve exact old/new exposures and all failed costs.
4. Predeclare quality, cost, safety, opportunity and stop rules. An ineligible or
   no-reuse position is not replaced; no mechanism effect is inferred from unchanged
   arms. All measurements retain the assigned positions, incomplete pairs and
   clustered/repeated nature of the data. No holdout or promotion admission follows
   from DEV observations alone.

Five narrow preparation tests and changed-file Ruff pass. Tests cover schedule/cap
preservation, reversed fixed repeats, exact frozen identity, transitive source-cluster
exclusion, query-vector-only provenance, changed encoding/scope rejection and private
output boundary. Package checks/build belong to classified Lab fast CI, not repeated
Product full suites. No Product API/Schema/permission/Canonical behavior changes;
Schema remains EXPERIMENTAL / NO-GO, and the overall Goal remains incomplete.
