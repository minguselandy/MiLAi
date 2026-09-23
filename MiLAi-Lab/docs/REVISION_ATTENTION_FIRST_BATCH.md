# Revision / Attention: authorized joint finite batch

2026-09-23. **SCHEDULE_FROZEN / METHOD_NOT_ADMITTED / zero new requests**.
The user explicitly confirmed the complete new finite contract, then repeated its
data/formation/model confirmation. No further budget confirmation is required.
This is a new joint allocation, not reopening Utility or any historical allocation.
Allocation base: `39dc657a5967c0586355b6bea23c56e9a1812ee3` (PR #46 main).
Input correction base/rollback: `0e4af327fa8ddeedd15cc12ff3738eeb0a36d29a` (PR #47).

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
  rerank **0**. Exact instructed-query caches exist for 21 of 24 queries (below).
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

**Correction to PR #47:** only 21 exact instructed-query vectors are reusable.
The producer stores `vectors[0]` (raw query) in bank records, but calls retrieval
with `vectors[1]` (`Instruct: ...\nQuery: ...`). Matching model, dimension and bank
instruction metadata cannot make these distinct encodings interchangeable. The
raw-only first requests for OS 120/226/2 do not establish an instructed cache.
The bank fallback has been removed; these positions now explicitly carry
`MISSING_INSTRUCTED_QUERY_CACHE`, a null vector and their exact required embedding
input. No own-task bank/card/outcome is imported by query preparation.

The frozen IDs, mechanism assignment, order and arms are unchanged. Missing caches
are not zero-opportunity observations, grounds for replacement or permission to
change retrieval encoding. Filling them may use only the authorized existing bge-m3
contract, after full method admission, with a verified token upper bound and the
single global request/token/time guard. No embedding call has been made yet.

Private output outside Git:
`/cra/memory/mx_memory/evidence/post-cleanup-revision-attention-20260923/input-review-instructed-v2/review-inputs.json`
SHA-256: `a1847b9d36bce3fdc8fc6668d57ea4da1dec37c8be76422b3805075041445edc`.
It retains all 24 queries and 39 windows, with 21 exact instructed caches and three
explicit gaps. Preparation cost is not total review/formation cost.

The prior `input-review-complete/review-inputs.json` (SHA-256
`7c8f7c2fcd51a4327123a28c5e43e88fdaef74bde656b9fd530d2d289c6e86bb`) is preserved
but **SUPERSEDED_INVALID_QUERY_ENCODING**, not an admissible execution input.
Its `candidate-preflight.json` (SHA-256
`8834c2d160b026a883d1c1fc49fb803b693990699ba79616a081977840c3ce8a`) is also superseded:
its top-1 rankings and seven-of-twelve structural-opportunity total must not be
used as verified results. `method-admission-design.json` remains an unadmitted
draft; any ranking-dependent counts require corrected vectors. The earlier
`input-review/` output also remains untouched. No historical evidence is rewritten.

## Remaining execution admission (not another permission request)

The [native runtime candidate](JOINT_NATIVE_RUNTIME.md) now connects the real
guarded Provider request path, existing revision engine/exposure bridge and
Attention state/expansion to the native Actor adapter. Its 117 local tests use
synthetic HTTP/native fixtures, not external models or effect runs. A complete
source-pinned batch driver and actual semantic admission are still required.

1. Review exact sources/visible feedback; fix the revision proposal/source-check
   procedure and classify CORRECTION/SCOPE_NARROWING separately from refresh or
   unsupported changes. Preserve top-1 retrieval; do not enlarge it to force reuse.
2. Freeze the explicit Attention state producer, independent relevance/conflict/
   coverage labels, baseline and expansion rule. Neither historical adoption nor
   a query-vector match is a semantic review.
3. Complete the batch driver around the integrated native runtime and global budget
   guard. Pin native environment, method/policies, common conditions and exact inputs
   before first request. Preserve exact old/new exposures and all failed costs.
4. Predeclare quality, cost, safety, opportunity and stop rules. An ineligible or
   no-reuse position is not replaced; no mechanism effect is inferred from unchanged
   arms. All measurements retain the assigned positions, incomplete pairs and
   clustered/repeated nature of the data. No holdout or promotion admission follows
   from DEV observations alone.

Six narrow preparation tests and changed-file Ruff pass. Tests cover schedule/cap
preservation, reversed fixed repeats, exact frozen identity, transitive source-cluster
exclusion, raw-versus-instructed request provenance, no own-bank fallback and private
output boundary. Package checks/build belong to classified Lab fast CI, not repeated
Product full suites. No Product API/Schema/permission/Canonical behavior changes;
Schema remains EXPERIMENTAL / NO-GO, and the overall Goal remains incomplete.
