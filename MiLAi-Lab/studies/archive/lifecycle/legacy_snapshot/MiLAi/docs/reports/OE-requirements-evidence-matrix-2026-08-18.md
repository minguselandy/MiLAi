# MiLAi Agent execution optimization requirements/evidence matrix

Status vocabulary: `PASS` means the stated local/synthetic gate is executable and passed;
`PARTIAL` means implementation exists but the required external/provider proof is absent;
`PENDING` means no acceptance decision exists.

## OE work packages

| Work package | Status | Evidence / remaining boundary |
| --- | --- | --- |
| OE-00 baseline | PASS (offline) | frozen offline fixtures/SHA, 20/100/500 workload, 1/1k/10k/100k generator, concurrency 1/4/16 and retained report; a separate synthetic/de-identified same-model provider A/B workload is frozen, while target pricing remains operator-supplied |
| OE-01 token accounting | PARTIAL | exact counter protocol, adapter injection, split metrics, privacy/no-fabrication tests and fail-closed provider request/usage/component/billing protocol pass; no approved real provider capture/invoice reconciliation yet |
| OE-02 Slot/Delta | PASS | replace/remove/unchanged; cache key binds host policy, canonical/semantic Issue state, compiler/tokenizer/all budgets/constraints/TTL; no public validation override; old checkpoint fail closed; sync/async/Hook/AutoGen regressions |
| OE-03 Router/reader-lite | PASS | deterministic rules, validated CACHE, max three, typed single Claim UUID exact L0, Issue/ambiguous UUID L1, one-tool default and profile non-escalation tests |
| OE-04 Context Compiler | PASS for injected exact counter | strict live OpenIssue identity/type/revision/target/scope/authority/branch/discharge validation, protected minimum, tiers, omission, zero injection and infeasible-budget tests; target-provider tokenizer remains OE-01 boundary |
| OE-05 Runtime read path | PASS with load caveat | persistent HTTP, prewarm/bounds, RRF, default-off MMR; `/tmp` 10k/100k retry gate PASS and contested attempt retained; no projection migration needed |
| OE-06 framework E2E | PASS (local synthetic) | Generic/MCP/LangGraph/AutoGen plus hook tests; official pinned MCP and independent JSON-RPC wire; three-session real PostgreSQL replay |
| OE-07 candidate acceptance | PASS local (candidate.4.6); real provider NO-GO | candidate.4.6 independently closes the local optimization protocol (`A=PASS`) and stopped helper race; final hash now occurs after helper termination. `OE-F06` remains external and blocks Beta/prod. |

## Optimization gates

| Gate | Status | Evidence / caveat |
| --- | --- | --- |
| OG-00 Reproducible Baseline | PASS offline / provider protocol pending re-review | offline fixture/report retained; v3 binds workload/pricing/actual shipped tools/adapter closure/host execution closure/approval/plan/report and fully recomputes capture, but no approved target run exists |
| OG-01 Token Truth | PARTIAL | v3 requires pre-count plus every native call/receipt and leaves provider_usage_verified=false; real capture/reconciliation and independent provider verification are absent |
| OG-02 No Quadratic Growth | PASS | one-slot 500-turn and AutoGen 500-update tests; UNCHANGED injects zero |
| OG-03 Compact Tools | PARTIAL | reader-lite is one tool and under 250 evaluation tokens; runner requires per-request target-tokenizer component count ≤250, but no target provider result exists |
| OG-04 Context Budget | PARTIAL | 512/1,024/1,600 ceilings and infeasible failures pass under exact injected counter; runner enforces per-request target-tokenizer maxima, but target provider is pending |
| OG-05 Session Cost | PASS (evaluation tokenizer) | 100-turn result 10,280 < 30,000; not provider billing |
| OG-06 Warm L0 | PASS on retained retry | 10k p95 20.819 ms < 30 ms; separate contested-host attempt failed and is retained |
| OG-07 Warm L1 | PASS on retained retry | 10k p95 33.596 ms < 100 ms; not an SLO |
| OG-08 Cold Start | PARTIAL | prewarm state/recovery tests and live READY pass; observed prewarm 486.844 ms, but separate post-ready first-query <250 ms gate is not retained as a provider-specific run |
| OG-09 Quality | PARTIAL | governed conflict/revoke/authority/scope safety labels and strict same-model A/B scorer are executable; no external model result exists |
| OG-10 Frameworks | PASS | shared policy/boundary and real E2E across four adapters; hook covered by contract tests |
| OG-11 Failure Safety | PASS for tested faults | policy/budget/TTL change, stale cache, Issue metadata/revision/invalid semantics, embedding failure, Runtime/DB failure, revoke and stale projection fail closed |
| OG-12 Independent Review | PASS local after candidate.4.6; NO-GO provider | local P0/P1/P2 are closed by candidate.4.6 independent re-review; `OE-F06` remains open. |

## Definition of Done disposition

DoD 2–9, 11, 13–15 are satisfied for the local synthetic candidate after candidate.4.6 independent
acceptance. Candidate.4.6 supplies a stricter provider capture path and lifecycle-complete host execution
closure. DoD 10 lacks actual provider token/model-round/billing/end-to-end wall-time results, and DoD 12
lacks an executed same-model provider A/B. Therefore the honest state remains `Optimization Candidate`, not Beta,
Production or Schema freeze.
