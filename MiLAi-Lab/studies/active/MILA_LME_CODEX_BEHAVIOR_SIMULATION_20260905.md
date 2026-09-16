---
document_id: MILA-LME-CODEX-BEHAVIOR-SIMULATION-20260905
version: "1.1"
status: COMPLETE_EXPLORATORY_BEHAVIOR_AND_D2_SHADOW_SIMULATION
executed_at: "2026-09-05T10:38:46+08:00"
evaluation_mode: ENGINEERING_SIMULATION
formal_holdout_consumed: false
skills_loaded: false
product_effect_claim: NOT_MADE
---

# LME case Codex / MiLA MCP behavior simulation

## 1. Question and boundary

This experiment used opened-development LongMemEval cases to observe how a fresh Codex process uses
the MiLA HTTP MCP, especially whether it consumes Product-11 D1 continuation when the first Context
is incomplete.

Each counted Codex process was ephemeral and received exactly one external MCP server with only
`milai_memory_resolve` enabled. User configuration, rules, Skill instructions, bundled Skills, Skill
search, plugins, MCP apps and multi-agent were disabled. Codex could make at most two focused Memory
calls and could not use files, shell or web as historical evidence.

The Runtime used a fresh PostgreSQL database; all captured history was removed with its run-owned
volume. No Canonical row was created. The selected cases were already-opened development cases;
Formal 500 was neither scored nor used for a claim.

## 2. Primary arms

| Arm | Cases | D1 | Codex policy | Purpose |
| --- | ---: | --- | --- | --- |
| `NATURAL-D1` | 4 | on | no continuation trigger instruction | observe natural behavior |
| `GUIDED-D1-COUNT` | 1 | on | when incomplete and `available=true`, repeat the exact query with the returned `context_id` | isolate activation from frontier utility |

Two preceding D1-off runs were instrumentation/configuration probes only. They are retained in
`var/product09` but are not treatment evidence.

## 3. Natural D1 behavior

Artifact: `var/product09/lme-behavior-sim-20260905c.json`  
SHA-256: `7670a991fc86a46865a0e95592d116edc706bf2888e4633748400c07c554d977`

```text
cases                                      4
history Evidence                           1,772
first results with continuation.available  4 / 4
natural continuation calls                 0 / 4
all required source/session recall          4 / 4
all exact answer-turn recall                3 / 4
exact match                                 2 / 4
mean normalized F1                          0.66666675
Canonical mutation                          0
```

All four first calls reported `continuation.available=true` with reason `UNEXPANDED_FRONTIER`.
Codex nevertheless made no second call. This is an activation observation, not a D1 execution
failure.

Per-case interpretation:

- `8550ddae`: the exact answer turn was visible and the answer was semantically correct, but strict
  EM rejected the natural sentence `You tried a lavender gin fizz recipe.` against the short label
  `lavender gin fizz`; normalized F1 was `0.666667`.
- `71a3fd6b`: exact answer and answer-turn visibility passed.
- `852ce960`: current-state update answer and answer-turn visibility passed.
- `0a995998`: all three required source sessions were present, but only one of four annotated answer
  turns was visible; Codex answered only the one directly supported item instead of continuing.

## 4. Guided COUNT behavior

Artifact: `var/product09/lme-behavior-sim-20260905d.json`  
SHA-256: `d95b598d125ff3749f57c5315b55cbae4e1c65c8ade934346e3a021a3feac862`

The single changed condition was one bounded workflow sentence telling Codex how to consume an
available continuation. Codex then made a second call with:

```text
same query as Call 1                         true
previous_context_id present                 true
previous_context_id matches Call 1 context  true
Call-2 Evidence identities novel            20 / 20
Call-2 turn refs novel                       20 / 20
fresh reacquisition-shaped calls             0
```

The public MCP deliberately exposes only `available` and `reason`; it does not expose the internal
`candidate_origin` assertion. Therefore this simulation does not claim direct public proof of
`PERSISTED_FRONTIER`, even though the D1 treatment was enabled and the second page used the exact
same query/predecessor with disjoint identities.

The second page did not recover any of the three still-missing annotated answer turns. Cumulative
answer-turn visibility remained `1/4`, and Codex correctly abstained: `I don’t have enough memory
evidence to determine the total.`

## 5. Findings

```text
F1  continuation activation
    available continuation was ignored naturally in 4/4 cases

F3  fine-grained coverage
    guided continuation returned a fully novel page but did not expose the missing
    answer turns even though all required source sessions were already represented

F6  Host reasoning
    not established for the COUNT failure because cumulative exact Evidence was incomplete
```

The simulation therefore supports the existing architecture split:

```text
required continuation timing  -> Host activation policy
which new Evidence to expose   -> retrieval/fine acquisition
aggregation after completeness -> Codex
```

It does not justify changing first-call admission, enabling D2 in the public Context/frontier,
adding Dense retrieval, consuming Formal 500, or relaxing the Product-11 human seal.

## 6. D2 SHADOW exact-turn diagnostic

The follow-up ran the existing D2 SHADOW against the same four opened-development LME families. The
Product query remained label-blind. Model-assisted answer-turn refs were joined only by the Lab
scorer after the Runtime response. D2 remained SHADOW throughout: public Context and frontier change
were `false`, new global acquisition calls and hidden model calls were `0`, and Canonical mutation
was `0`.

```text
cases / history turns                  4 / 1,772
required answer turns                  7
required turns in public first Context 6
missing before D2                      1
required turns found by D2             7
missing turns recovered by D2          1 / 1
all fine candidates / novel            360 / 140
```

The only missing turn was the second navy-blazer mention in COUNT case `0a995998`. D2 found it as a
new direct candidate at intra-session channel rank `2`, but global fine rank `53`. This proves the
explicit intra-source mechanism can recover the observed adjacency loss; it does not prove that a
naive global top-k integration is efficient. Returning all 120 candidates from that case would be
an unacceptable substitute for a selection policy.

Artifacts:

| Case | Family | SHA-256 |
| --- | --- | --- |
| `0a995998` | multi-session count | `1670a7fc441c2cbe4ca2ce5dc914a5c1e89a0a5517e0c72dfa0c64aa7ef3635f` |
| `8550ddae` | ordinary user lookup | `73a64c3e2cc739d68f0d1bf4740697ecc11b7251bc81f0fbf7597abd12590baf` |
| `71a3fd6b` | assistant answer lookup | `2bab13bd50517680a13b21a6dd636249d162129844b0deee4aa30e1be4b14ef6` |
| `852ce960` | state update | `0ec9ce4616b444802bf3a0e6a3db3dfdc04896acf60bb24207d24e4a5af0c0f3` |

## 7. Presealed D2 selection validation

Before reading the remaining S2 outcomes, the Lab froze
`FIRST_NOVEL_PER_SOURCE_THEN_GLOBAL_CAP`: exclude candidates already present in the coarse pool,
retain the first novel turn per `(source_type, session_id)`, globally order those turns, select at
most 20, and union them non-destructively with the public Context. The three previously inspected S2
cases and the separate COUNT mechanism probe were excluded. The remaining 21 S2 cases were then run
once in a fresh Runtime.

Preseal: `var/product11/lme-d2-selection-preseal-20260905a.json`  
SHA-256: `e92d76193993db444791835cab20f50b6a0f3fd3566f343bfaddd0e37354c434`

Result: `var/product11/lme-d2-selection-validation-20260905a.json`  
SHA-256: `d07a08d02d0fbda07337bd57ea179f89c2bd1643683bb9b033d046d8ea6b59dc`

```text
cases / exact-turn-scorable cases             21 / 20
history Evidence / projection rows        10,726 / 10,726
public required-turn coverage                  23 / 32 = 0.71875
cases with a public exact-turn gap               7
missing required turns                           9
D2 candidate-pool required-turn coverage        25 / 32 = 0.78125
missing turns present anywhere in D2 pool        2 / 9
presealed selector recovered missing turns       0 / 9
cases with selector gain / loss                   0 / 0
Canonical mutation                                0
```

The negative result rejects this selector as a general integration policy. The two recoverable
misses also belonged to different mechanisms:

- `d851d5ba`: the missing turn was already in the coarse candidate pool (global rank 25), so its
  absence is an admission/rendering/frontier issue, not novel fine acquisition;
- `gpt4_d6585ce9`: D2 directly found the missing turn, but it was the third novel result within its
  source (global rank 40), so per-source cap 1 discarded it.

The other seven missing exact turns were not in D2's lexical intra-source pool. This means D2 is a
real but narrow mechanism: it recovered the original adjacency-loss probe, yet neither the
presealed selector nor lexical fine acquisition generalizes enough to authorize Product exposure.
D2 remains SHADOW; there is no X2 effect claim and no post-validation retuning on these cases.

## 8. Capture/projection critical-path timing

A separate representative timing probe used COUNT case `0a995998` with 484 historical Events and
eight capture workers.

Artifact: `var/product11/lme-d2-shadow-timing-20260905a.json`  
SHA-256: `f57c65a30b4a6e627f7c0128cf94be1581460386c0ee20b849f23857a36d2ac0`

```text
Evidence capture wall time             21,916.423 ms
projection readiness tail wait            951.302 ms
resolve wall time                         685.880 ms
fresh-stack end-to-end                 35,590.032 ms

share of capture+wait+resolve:
  capture                                  93.05%
  projection readiness wait                 4.04%
  resolve                                   2.91%
```

Projection runs asynchronously while capture is still in progress, so readiness time measures only
the remaining read-after-write barrier, not all projection CPU work. It is not redundant: the
lexical, intra-source and adjacency read paths query `evidence-search-v1`, not raw Evidence. The
measured optimization target is capture's per-Event hook/subprocess path; removing projection would
make durable Evidence unavailable to retrieval. The test harness may later batch readiness barriers,
but the underlying projection must remain.

## 9. Guided D1 diagnostic on known public-gap cases

The seven validation cases with at least one public exact-turn miss were frozen as a
label-directed diagnostic set. Fresh zero-Skill Codex processes received only
`milai_memory_resolve` and the bounded guided-continuation sentence. D1 was enabled; D2 remained
off. Case selection is outcome-directed, so this run diagnoses known misses and is not an effect
estimate.

Preseal: `var/product11/lme-d1-guided-gap-preseal-20260905a.json`  
SHA-256: `369737f3d9044e82a9e209c53cdf809af6aade301d95dc07780fa40da766e469`

The first execution was valid but retained only cumulative required-turn coverage. It is preserved
at `var/product11/lme-d1-guided-gap-20260905a.json` (SHA-256
`bd3b860af006674b6e1e21694f86647d77ede7e97341fd23d194cbb7f15c6fce`). A measurement-only repair
froze unchanged behavior and added per-call coverage before rerunning. The repair receipt is
`var/product11/lme-d1-guided-gap-trace-repair-20260905b.json` (SHA-256
`7fc446bb74a59bc23f128cf66e67f74b7380e5d9aa9d15a393216e865c02963f`).

Authoritative recovery-attribution run:
`var/product11/lme-d1-guided-gap-20260905b.json`  
SHA-256: `3ce9ab6090bc484d414a98a84678089ca4828efe6e6f588fd7155564f1fb5e3e`

```text
cases / history Evidence                         7 / 3,419
correct same-query predecessor continuation      7 / 7
fresh reacquisition after Call 1                     0
novel turn refs on Call 2                          152
required exact turns visible on Call 1            7 / 13
required exact turns visible cumulatively         7 / 13
required exact turns recovered after Call 1        0 / 6
all-turn-complete cases, Call 1 / cumulative       2 / 7 -> 2 / 7
strict exact answer                                0 / 7
mean normalized F1                                0.343504
Canonical mutation                                    0
Evidence / projection rows                  3,419 / 3,419
cleanup                                            PASS
```

The second page was highly novel but not useful for the known exact-turn gaps. This rejects the idea
that merely consuming one more persisted page repairs these misses. Two cases were already
exact-turn complete on Call 1 and produced semantically correct natural-language answers that strict
EM rejected; the other five remained memory-incomplete, so they cannot be attributed to Host
reasoning.

The measurement run also strengthens the performance result:

```text
capture wall time             161,367.880 ms (98.25% of capture + wait)
projection readiness wait       2,877.573 ms ( 1.75% of capture + wait)
```

The two identical-configuration executions did not have identical cumulative coverage for
`d851d5ba`. Since the old trace omitted first-query identity, this variation cannot be assigned to
Codex query formulation versus retrieval ordering. Future traces now record query SHA-256 and exact
question-match without exposing additional Product state. No post-outcome rerun is used to make an
effect claim.

## 10. Terminal interpretation

This opened-development engineering simulation is complete. It establishes an activation failure,
a persisted-page coverage failure under both the original COUNT probe and a seven-case guided
diagnostic, a narrow positive D2 mechanism probe, and a negative independent D2 selector validation.
It does not replace Product-11's two-human X0 seal, consume Formal 500, or authorize D2 Product
integration.
