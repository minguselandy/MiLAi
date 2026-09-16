# V02-14 Host acquisition and end-to-end usability

Date: 2026-09-09. **D0–D7 completed in the authorized local scope; Client helper opt-in only.**

Goal: `MiLAi-Product/docs/goals/MILA_V02_14_Host记忆取得与端到端可用性开发_GOAL_20260909.md`.
Raw evidence is outside Git at `evidence/v0214/`. All materials in the new development and
confirmation pools are explicitly synthetic. Horizon's 55 protected confirmation clusters,
the 16 unrun accepted queries and V02-13's protected Mem2Act allocation remain untouched.

## Scope and baseline

- Public installed Product: MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.4. Delivery SHA256
  `18344e991596de27c8033b8a5ebb69de235ea98bfee0f0008061900d5fd49b41`.
- `configs/v0214-baseline-manifest.json` and `evidence/v0214/d0-scope-review.json` preserve
  actual dirty-source versions, installed wheel hashes, MCP catalog, model and tokenizer pins.
  Each real run additionally verifies the installed pin and captures the public catalog.
- Qwen3.6-35B-A3B-FP8, context 65,536, output reservation 4,096, temperature 0, seed 213.
  No model switch, automatic generation retry or cumulative raw-token cap. Model transport is
  default-off in the baseline and explicitly enabled only by each sealed experiment allocation.
- All Product writes use isolated public interfaces. Business outputs are draft action intents:
  no business service execution, automatic source ingestion, new State policy or Runtime change.

## Engineering increments and review cards

| Increment | Behavior and evidence | Boundary / remaining limitation |
| --- | --- | --- |
| D0 | 517 real public calls across three isolated PG/MCP instances; exact scoped reads, CAS one winner/one stale loser, deletion/revocation withholding | Zero model calls. No SQL-level parallelism or saturation rejection claim. |
| D1 | Generic binding, versioned ordinary pages, bounded scan, request correlation, current qualification, separate acquired/presented receipts | `SourceBackend` is an opt-in Lab prototype; no benchmark IDs or automatic file ingestion. |
| D2 | Host readiness plus required/optional/type/enum/current-input delivery checks | Schema validity is not semantic correctness. Explicit defaults are not synthesized. |
| D3 | Durable per-allocation reservation lock; pending usage stops future sends across processes; final-slot reserve | Historic two-case replay predicts earlier final slots, not better answers. New runs do not restore the historical 20k cap. |
| D4 | Exact read → bounded short scan → fixed lexical metadata → actual selected reads | BM25 uses question/schema names only; 200-word chunks, overlap 40, k=4. No unbounded EOF for long sources. |
| D5 smoke v1 | No-memory succeeds; short-source task incorrectly clarifies before reading | 2 requests / 11,898 raw. Failure retained, not an infrastructure exclusion. |
| D5 smoke v2 | Acquisition-before-missing-input instruction makes both cases correct | 3 requests / 18,812 raw. Two development cases, not independent confirmation. |
| D5 full v2 | 32 cold phases across A0/H; real optional Note save/recovery and two-task overlap | 49 requests / 310,950 raw. H has ambiguity and duplicate-operation errors; not D5 PASS. |
| D5 full v3 | Stronger generic instructions, full H regression | 29 requests / 186,895 raw. Same two errors retained: text clarification with a contradictory business action; duplicate business calls. |
| D5 smoke v4 | Public readiness assessment before typed delivery; consistency and requested-count checks | Four phases correct, 7 requests / 47,261 raw. No answer repair or evaluator-derived routing. |
| D5 full v4 | Full H regression: 15 correct deliveries and one correct clarification | **D5_REAL_HOST_E2E_DEV_PASS**; 29 requests / 194,186 raw, all settled. |

Core review: `evidence/v0214/helper-review/review.json`; 38 core tests and 3 real-checker
unit tests passed. Parent full gates passed at 726 tests before the additional transport-receipt
tests. The latter add tests for disabled transport, observed/unobserved sends with unknown usage,
readiness contracts and terminal gates; final expanded checks are recorded below.

### Coverage, retrieval and final reserve

`COMPLETE` is assigned only at EOF for the relevant page/scan; a selected EOF range is not a
full-history claim. Bounded long scans retain `PARTIAL` and a continuation cursor. Withheld,
unavailable and unknown results do not disclose source bodies. Every outgoing candidate context
rechecks source qualification and current Product reads. Merely selecting or assembling text
does not mark it presented: payload and HTTP receipts corroborate actual transmission, including
responses whose usage cannot be settled. A reservation without a response remains transmission
unknown rather than falsely presented.

Long-history selection retains the original source ID/version/offset and performs ordinary reads
of selected ranges. Search hits are metadata, not implicitly presented support. The two-way
zero-generation replay sends actual model Product queries to the lexical backend and the actual
fixed lexical query to the original public Product backend. These diagnostic outputs are never
fed back into the experiment's model requests.

`d3-replay-20260909-r1/result.json` replays the two original V02-12 stopped trajectories without
generating answers. The historical 20,000 limit is used only to reproduce those trajectories;
with a 9,216 reserve, the second nonfinal request is declined while a final request at that same
input fits. This trades another acquisition opportunity for a deliverable final slot. It does
not establish that either final answer would have been correct. The initial directory-creation
failure is retained separately and incurred zero model requests.

### Performance and concurrency

D0 read P50/P95/P99: 39.47/49.43/50.51 ms; search: 49.80/88.82/94.51 ms. Each has 24 samples.
Repeat P95 ratios 0.920/0.899 fit the predeclared 2× tolerance. These are repeatability numbers,
not candidate efficiency wins. Client overlap and isolated marker checks do not prove parallel
SQL execution or absence of all bottlenecks.

Four local raw-read/helper comparisons satisfy the predeclared
`helper_P95 <= max(4 * raw_P95, raw_P95 + 2ms)` engineering tolerance. The 8 KiB serial case is
nevertheless **5.43× slower** (0.443 → 2.407 ms): qualification costs time. Whole-directory hashing,
cold filesystem caches, remote storage and corpus-scale behavior remain limitations.

Host queue admission is bounded and its overload test has one success/two timeouts. The actual
small-PG-pool load never reached service saturation even after bounded increased load; service
saturation rejection is **unverified**, not passed. DB connection-wait, GPU, currency and physical
network/disk counters not separately observed are unknown, not zero.

## D5 development results so far

Full v2 A0: 11/16 phases correct, plus three insufficient-source clarifications, one ambiguity
failure and one format error. H: 14/16 phases correct, one ambiguity failure and one incorrect
complete plan (two duplicate operations; first operation correct). Repeated phases share a
scenario lineage and must not be treated as independent samples.

The ambiguity failure occurs after the full short source is presented: two active choices were
arbitrarily reduced to an invented default. The duplicate-plan failure also has the needed
support. Neither is repaired by additional retrieval or proves a need for automatic State.
V3 changes the generic Host instructions to clarify between valid alternatives and separate
business operations from an explicitly requested optional memory save.

V3 did not fix the structural/semantic contradiction: the public answer asked for a choice while
`action=business` committed an arbitrary choice. V4 makes a short public assessment precede the
typed delivery object. The model decides readiness and the requested number of business
operations before arguments are emitted. The Host checks assessment/action and count consistency;
it does not infer semantic truth or choose missing values. A self-consistent but wrong assessment
can still fail the task. This is a Host delivery protocol, not automatic State or a Runtime rule.

V4 full regression passes all 16 phases across eight development lineages. The no-memory task
does not acquire source pages or save. The short-history path reads ordinary pages; the long path
uses fixed lexical selection, retains PARTIAL and never scans to EOF. The ambiguity phase asks,
and a fresh process uses the user's explicit selection on the next phase. A new observation
replaces the old value. Exactly one requested Note is committed, and a new Host with no file
source reads it through the public Note inventory/read path without receiving a saved ID from the
operator. All other phases are NO_CHANGE. Independent task bindings stay distinct during both
concurrent phases; old cold Host PIDs have exited. No model messages cross the process boundary.

`d5-dev-v4-20260909/stage-gate.json` records the gate checks. A post-run unit fix rejects JSON
boolean operation counts (`true` is not integer 1); the request schema already rejected them and
no v4 actual output used one. It changes neither generated payload nor observed outcomes.

All six D5 allocations, including failed iterations, total **119 requests / 770,002 raw tokens**.
There is no cumulative raw-token cap. This is provider experiment usage, not the total agent
reasoning/preparation labor cost. Earlier V02-13 costs are not folded into this new-goal subtotal.

## Independent confirmation and integration decision

D5 passed before the independent confirmation pool was used. D6 retains all four accepted
clusters and compares A0/H plus LX for the two long cases. The pre-outcome allocation is
`configs/v0214-confirmation.json`: all four H outcomes must be correct, no negative transfer,
both negative controls intact, bounded selective long reads, D5 scope/cold gates, no unknown usage
or unrequested writes, total H raw <= 4× A0, and each H latency <= max(4× A0, A0+10s). These are
small synthetic engineering tolerances, not a production SLO or an efficiency target. The user
prioritizes working behavior over token minimization.

All four fixed confirmation clusters were run without replacement or post-result tuning:

| Scenario | A0 | H | Fixed LX diagnostic |
| --- | --- | --- | --- |
| Short, current inputs sufficient | Correct | Correct, no source acquisition | Not applicable |
| Medium, unresolved required identity | Clarification failure (underlying format error) | Correct clarification | Not applicable |
| Long selective, observation planning | Insufficient-source clarification | Correct | Correct |
| Long selective, audio preview planning | Insufficient-source clarification | Correct | Correct |

Task success: A0 **1/4**, H **4/4** including the required clarification, LX **2/2** long cases.
Valid-intent parameter denominators are separate: A0 1/1, H 3/3, LX 2/2. Abstention, clarification
and format failure are not silently counted as parameter errors or removed from task outcomes.

Six declared long-history facts were available in the original sources in each applicable arm.
H and LX each acquired and actually presented 6/6; A0 presented 0/6. H used four ordinary selected
reads (8,192 received bytes) and three (6,144 bytes), retaining PARTIAL rather than scanning either
~0.86/~0.95 MB source to EOF. First useful H evidence arrived at 7.00/7.22 seconds; corresponding
dispatch upper bounds were 7.12/7.43 seconds. These exact-string diagnostics do not establish
semantic entailment, external generalization or a Product retrieval improvement.

The two-way diagnostic also shows the actual A0 ambiguity query returning two lexical candidate
spans, while enhanced fixed queries to the original Product backend return no material in the
empty-memory scopes. This separates backend/source availability from query wording; it does not
isolate an answer-quality causal effect. Replayed material was not fed to models. Source files
were never automatically ingested to make the Product backend succeed.

D6 uses 14 requests / **107,653 raw tokens**: A0 34,520, H 54,991, LX 18,142. H/A0 total raw ratio
is **1.5930**. Per-task seconds are A0 4.47/6.27/4.95/4.69 and H 5.47/8.86/10.27/10.50, within
the frozen latency bound. No efficiency win is claimed; correctness costs extra Host/model work.
All provider and durable reservation accounting reconciles, unknown usage zero. The null
`expected_intent` clarification contract required an offline summarizer compatibility fix, not
a model rerun, changed gold or an outcome exclusion.

`d6-confirmation-v1-20260909/stage-gate.json` records every gate as true and returns
**PRODUCT_INTEGRATION_CANDIDATE**. This permits a narrowly scoped optional mechanical Client
helper, not a Product-default flip. D7 integrates that helper only; lexical ranking, task readiness
semantics and prompts remain in the Lab/Host. Public services and existing default policies stay
unchanged. The Client compatibility/build verification is recorded below.

### Full model cost and cleanup

Seven allocations including every failed iteration: **133 requests / 877,655 raw tokens**.
`evidence/v0214/final-accounting.json` reconciles them and 448 D5/D6 public calls; the separate D0
engineering load adds 517 public calls. Each allocation's owned API is stopped and PG compose
stop succeeds; volumes and all raw evidence are retained. No shared model or public Product
service was restarted by this Goal. Source/response JSON byte sizes and Host CPU timings are
recorded; they do not replace GPU, full network/disk, currency or human/agent labor measurements.

The experiment pin is not the newest public Runtime: read-only active-entrypoint and installed
metadata checks on 2026-09-09 find public **MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.5**.
The experiment deliberately retains its frozen **Runtime 0.1.4** predecessor/hash-backend pin.
No Runtime 0.1.5/BGE effect, public reauthentication or public deployment claim follows.

## Required final answers (Goal §15)

1. **What became generic?** Trusted binding and current inventory, versioned ordinary reads,
   cursor/EOF handling, bounded scan/selective reads, receipts, concurrency, typed delivery and
   durable final reserve. The original unconditional first-page/full-EOF bootstrap is not a
   permanent default; hardcoded task/source IDs and oracle material are not in candidate routing.
2. **How is coverage distinguished?** COMPLETE/PARTIAL/WITHHELD/UNAVAILABLE/UNKNOWN are explicit.
   Source availability, acquired I/O and confirmed prompt presentation have separate receipts.
   Qualification failure masks bodies; a selected EOF range never proves full-history coverage.
3. **How does long retrieval work without EOF?** Fixed Q+schema-name lexical selection chooses
   source/version offsets, then actual ordinary reads deliver evidence. Both independent long
   tasks succeed with three/four pages, not unbounded source presentation.
4. **When clarify?** After checking available inputs, unresolved required identity/values or
   multiple active choices without a preference require a question; unavailable/denied
   prerequisites can be BLOCKED. Public readiness precedes delivery, but self-consistency is not
   semantic truth. No code fills missing arguments from defaults or evaluator labels.
5. **Does reserve reduce budget stops?** The two historical zero-generation replays predict an
   earlier final slot instead of an unsendable third payload. New allocations have no budget stop,
   but that is not a controlled proof of a reduction under the uncapped cumulative policy. The
   cost is giving up another acquisition turn; answer-quality benefit is unproved.
6. **Independent correctness, memory use, negative transfer and cost?** H 4/4 task success versus
   A0 1/4, long support 6/6 presented versus 0/6, no observed negative transfer in this fixed tiny
   synthetic pool, H raw cost 1.59× A0. Parameter and task denominators remain separate.
7. **Concurrency and performance?** Two-user public read/search and two independent real Host
   tasks retain scope. Bounded Host overload and actual CAS/revocation tests pass. Local helper
   overhead fits the frozen tolerance but is sometimes 5.43× raw read latency. SQL parallelism,
   service saturation rejection and large-tenant scaling remain unverified.
8. **Should this become the default?** No default change is justified by four synthetic clusters.
   The evidence supports only optional mechanical Client integration. Original failures were in
   acquisition ordering and readiness/delivery consistency, not a missing Canonical/State layer.
9. **Restart State/attention research?** Not on this evidence. Two development scenarios produced
   different presented-but-wrong delivery failures, which the generic readiness-first protocol
   resolves in development and does not repeat in independent confirmation. No new State causal
   benefit, repeated independent same-kind residual or attention-mechanism evidence exists.
10. **What remains unverified?** External/population generalization, unseen model/provider behavior,
    remote/adversarial source adapters, corpus-scale cold caches, service overload rejection,
    SQL/DB-wait/GPU/full-resource accounting, public Runtime 0.1.5/BGE effect, new public Client
    login/deployment and production-default suitability. Protected datasets remain sealed.

## D7 delivered and final checks

The optional mechanical module is now
`MiLAi-Product/integrations/python-client/src/milai_client/host_acquisition.py`.
Import it explicitly; there are no new package-root exports or default Agent-loop calls.
Client is locally versioned **0.1.4**, with six adapter locks updated without new dependencies.
The module uses neutral source types and caller-owned authorized callbacks, not the Lab's file
backend, lexical retrieval, model readiness prompt/schema or evaluator. It changes no HTTP/MCP
schema, ACL/CAS/Canonical semantics, Runtime code or State behavior.

Candidate wheel SHA256:
`58e5d82a1e82ccff1111bea28184ac2958ea62028cf2698e8ef1fb273cab38d4`.
The wheel's helper bytes match the checked source SHA256
`3689b1fe94e36344ab8a8011181c342acbf6b476d10fdadf7445a10d64a391a1`.
It is built locally, **not released or deployed**. Existing installed public Client remains 0.1.3.
Upgrade/rollback, trusted adapter duties and budget/presentation boundaries are documented in
`MiLAi-Product/docs/runbooks/host-source-acquisition.md`.

| Package | Tests | Other required gates |
| --- | --- | --- |
| Lab | **748 passed** | Boundary, Ruff, mypy 39 files, wheel/sdist PASS |
| Client | **209 passed**, including 19 new helper tests | Locked Ruff, mypy 15 files, wheel/sdist PASS |
| MCP | **385 passed, 7 skipped** | Locked Ruff, mypy 21 files, wheel/sdist PASS |
| hooks | **52 passed** | Locked Ruff, mypy 6 files, wheel/sdist PASS |
| OpenWorker MCP | **176 passed** | Locked Ruff, mypy 14 files, wheel/sdist PASS |
| LangGraph | **5 passed** | Locked Ruff, mypy 2 files, wheel/sdist PASS |
| AutoGen | **6 passed** | Locked Ruff, mypy 2 files, wheel/sdist PASS |

Lab commands: `uv run milai-lab-check-boundary`, `uv run ruff check src tests tools`,
`uv run mypy src/milai_lab`, `uv run pytest -q`, `uv build`. Each Product adapter uses
`uv run --locked ruff check src tests`, `uv run --locked mypy`, `uv run --locked pytest -q`,
`uv build` from its own directory. Scoped diff checks pass. Existing dirty work was preserved;
no Git commit/tag, public release or deployment was created.

MCP's seven skips are opt-in PG E2E/auth calibration, not new-wheel PG passes. Runtime source,
permissions, state and transactions were not changed, so no new Runtime/PG migration suite was
required for this pure callback helper. D0's real PG tests remain pinned prior-version evidence;
they are not repackaged as Client 0.1.4 or public BGE validation.

The T01–T28 matrix is covered at the appropriate layer: T01–T09 through helper and scoped public
read/revoke checks; T10–T16 through delivery/reserve tests, historical replay and actual failures;
T17–T19 through deterministic retrieval, cross-replay and confirmed-payload coverage;
T20–T23 through no-memory/save/cold real model chains; T24–T25 through actual PG CAS/multi-user
load and concurrent Hosts; T26 through bounded Host overload (service saturation explicitly
unverified); T27–T28 through private raw-run directories, non-auth public DTO ledgers, versioned
payloads and durable accounting. No unobserved server-level property is marked passed.

Final stage: **PRODUCT_INTEGRATION_CANDIDATE / LOCAL_OPT_IN_CLIENT_HELPER_DELIVERED**.
Default remains A0; no new State/attention mechanism. All declared local development, independent
confirmation, conditional integration and reporting work is complete; broader limitations above
remain explicit future scope, not hidden successes.

Schema remains **0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE**.
