# v13.5 execution protocol

The authorized scope is F0–F4 and L0–L4 of the complete 866-line plan. F5 is a
future proposal only. The v13.4 Simplify exit and original 48 requirements retain
their original bytes and statuses; they are not reopened or promoted by this run.
All changes are confined to Lab and opt into `functional_v1`.

## Entry evidence and implementation boundary

The entry base is `1d8cc7e414d0df728215c1ad5d0cbc82b0ac6398`, in a separate
`feat/lab-functional-v13-5-20261003` worktree. Before implementation, 184 affected
tests passed. The old v13.4 worktree's sealed closeout verification passed for
19 tracked and 2,452 local artifacts. Neither check establishes the new functional
profile's acceptance.

F0 records the actual Python/module paths, installed versions, lock hash and
provider model-list responses. The existing Qwen service advertises 65,536 tokens;
the existing BGE service advertises 8,192. No replacement service is deployed.
The initial functional profile uses B1-style source and record reading without
embedding HTTP. All real generation is dispatched by Root, serially, through the
existing provider and continuous ledger.

The implementation composes MemoryService/SqliteStore, actual captured Source,
same-record revision history, SqliteSaver, the existing LangGraph Agent loop,
and the two actual application backends. Derived fragment/read snapshots are
operational indexes in the same Store, not a second memory truth. Application
receipts, observations, semantic commits and checkpoint deliveries are separate.
New natural requests use native owner-bound public business contracts; scripted
operation lists remain an optional historical test path.

## Frozen runs and finite admission

Each queue has one input freeze containing the actual source hashes, configuration,
SDK/version identity, fixture, declared evaluator controls, initial ledger counters,
tokenizer identity and finite queue limits. The runtime rejects changed source,
configuration, SDK or input bytes. A repair requires a new cohort and preserves
the old attempts and costs. Local commits retain runnable source revisions.

The initial bounds are ordinary material 8,192 tokens, output 4,096 tokens,
three explicit reads, 24 generation requests per public message across restart,
one format reproposal, and concurrency one. Each queue permits at most 600
generation reservations and 8,000,000 reserved tokens. Reservations include the
actual final prompt, output allowance and safety margin and survive unknown
outcomes. This quota is a safety counter; usage remains in the existing continuous
ledger. Reaching a bound records exhaustion and remaining `NOT_RUN` inputs instead
of silently extending the queue. A changed bound requires a new declared config.

Raw capture precedes the model. Host memory tools commit before the final answer;
there is no post-answer writer that can retroactively justify a save claim.
Format errors retain the original field paths and at most one new proposal.
Permission, source integrity, CAS, storage unknown and business unknown are
distinct from format errors. Every actual provider request is capacity checked
after its tool protocol and material have been assembled.

## Separate evaluation layers

| Layer | Frozen denominator and interpretation |
| --- | --- |
| L0 | M01–M16 mechanical families, actual SDK and fresh-process evidence. Scripted provider tests are mechanical only. |
| L1 | Original E0 normal 24 trajectories / 48 public messages and original rubric. The 22/24 threshold remains necessary; unresolved core blockers cannot be hidden by it. |
| L2 | 12 new development stories: two workflows × six situations. W1–W3 variants are separate mechanical evidence, not extra independent stories. |
| L3 formation | The actual 57 old failed formation requests, rerun with the declared simpler fragment interface. The new generic archival instruction is an intervention, not an identical-prompt rerun. |
| L3 reading | 26 packing questions and 4 distinct Reader questions, 30 in union. Preserve each actual old source/version/range candidate pool; explicit original-source reads are separately counted. |
| L4 | Approximately 12 new natural interaction stories, authored and frozen only after the functional method has stabilized. Functional confirmation, not an independent benchmark claim. |

The 57 formation requests and 30 reading questions are different units. Their
typed inventory is not an 87-question score. Root/evaluator can read old exposed
outputs; method owners do not receive evaluator gold or future L4 stories.
Companion agents inherit the same model family and are not an independent Judge.

L2 evaluator controls are a separate side channel. They cause actual backend
events or interrupt actual execution before/after the native call; both W1
branches expose the same unknown result. No hidden branch or expected state is
inserted into prompts, memory Sources or application authorization. A fault that
was not reached is not counted as validated. Discovery reads actual public state;
it never rewrites the original unknown execution receipt.

## Results and stopping

Report answer quality, raw/source integrity, semantic formation, same-ID updates,
scope/history, business effects, recovery and costs separately. `COMPLETED` means
the loop returned, not that its answer is correct. Keep `FAILED`,
`BUDGET_EXHAUSTED`, `PROVIDER_ERROR`, `UNKNOWN` and `NOT_RUN` distinct. Record the
earliest evidenced breakpoint and distinguish omitted text from an empty search.

Owner exposure, damaged provenance, replay of an unknown mutation or a false save
confirmation stops affected work when discovered. Fix the shared mechanism and
freeze a new cohort. Ordinary Reader errors may remain explicitly scoped limits;
they cannot be labeled as passing capabilities. Final acceptance requires direct
evidence for every required core capability on the same declared version.

GitHub publication follows verified completion and includes source, tests,
configuration, user/recovery/rollback documentation and compact evidence. Raw
databases, traces, copied corpora, model files and credentials remain excluded.
Publication does not merge the branch or authorize a Product release.

## r2 quality configuration amendment

After r1 produced a save confirmation without a semantic tool call and a separate
valid-JSON but unusable final answer, r2 enables the existing Qwen service's native
thinking mode and reserves 8,192 output tokens. The running server already has
`--reasoning-parser qwen3`; this changes request configuration only. The generic
prompt explicitly requires actual commits for requested temporary/scoped saves.
The model, endpoint, original fixtures/rubrics, ordinary 8,192-token material cap,
three-read limit, 24-call limit, one format reproposal and finite queue limits stay
at their declared values. Full-wire admission includes the increased output
reservation. The combined intervention has no single-change causal attribution.
Original r0/r1 attempts, failures and costs remain separate.

The r2 targeted stage completed four messages. It fixed the tested save/answer
failures, but a current-state follow-up cited historical memory without a live
query. R3 makes this F3 boundary explicit: checking current application state or
continuing prior work first reads the public backend in the current message.
R3 otherwise retains r2's configuration and leaves original rubric bytes intact.
The four r2 messages remain a targeted cohort, not a completed normal24 run.
