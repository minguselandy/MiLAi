---
document_id: MILA-ALL-EXPERIMENTS-COMPLETION-AUDIT
version: "1.3"
status: ALL_ELIGIBLE_EXPERIMENTS_TERMINAL_PRODUCT11_X0_PARKED_SUBAGENT_OPPORTUNITY
audited_at: "2026-09-05T12:31:30+08:00"
active_goal: continue experiments using subagents instead of human review
formal_holdout_consumed: false
---

# MiLA All-experiments Completion Audit

## 1. Scope

This audit treats current trackers, terminal reports, live services, test results and external-human
submission files as authoritative. Historical stages that reached a preregistered PASS, PARKED,
PARTIAL or negative terminal are completed experiments; a non-PASS scientific result is not reopened
merely to obtain a favorable outcome.

## 2. Terminal experiment families

| Family | Terminal evidence | Current result |
| --- | --- | --- |
| Product-01 | superseded tracker | handed to Product-02; Formal stage not entered by terminal rule |
| Product-02 | Product-02 tracker | `PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE` |
| Product-03 | Product status + completion evidence | OpenWorker MCP experiment terminal |
| Product-04 | Product status + completion evidence | implementation terminal |
| Product-05 | Product-05 tracker | `PARTIAL_*_READER_CONSUMPTION_UNRESOLVED` |
| Product-06 | Product-06 tracker | `PARTIAL_*_READER_GAIN_UNRESOLVED` |
| Product-07 | Product-07 tracker | `PARKED_*_NO_GENERAL_EVIDENCE_GAIN` |
| Product-08 | Product-08 tracker | `PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE` |
| Product-09 | Product-09 tracker | `PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE` |
| Product-10 | Product-10 tracker | `PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED` |
| HC4 A0 | HC4 tracker | passive adoption negative, `0/8` |
| HC4 A1 | HC4 tracker | guided adoption negative, `0/4`; prompt escalation stopped |
| MCP S0-S3 | affordance contract | explicit callability passes; generic activation `0/3` |
| Phase A | Memory MCP Phase A completion | functional baseline PASS |
| Phase B | Host Continuity completion | deterministic prefetch PASS |
| Phase C0-C5 | six Phase C reports | Event reconciliation engineering chain PASS |
| Product-11 D1 | D1 completion report | persisted-frontier engineering baseline PASS |
| Product-11 D2 | D2 completion report | lexical intra-source SHADOW engineering baseline PASS |
| R1 | R1 report | three zero-Skill MCP-only read tasks complete; one real facade failure fixed |
| LME behavior simulation | Lab simulation report | opened-development D1 natural/guided behavior executed; activation and fine-coverage failures localized; no Research effect claim |
| Memory performance baseline | performance report v1.1 | observational baseline expanded with 7-task LME capture/projection/rendering costs; no PASS gate or SLO claim |

These terminals are not rerun simply because the active goal says “all”: doing so would violate their
stopping rules, consume held-out data, or erase legitimate negative findings.

The performance baseline is telemetry rather than an unterminated effect experiment. Its unavailable
token and call-level latency fields are explicitly `NOT_CAPTURED` instead of being treated as a gate;
new measurement is added only by real task windows, not by manufacturing success traffic.

The later LME behavior simulation is an independent Engineering simulation, not a substitute for the
Product-11 X0 human seal. It used no Skills and only the public `milai_memory_resolve` MCP tool for
Codex. Natural D1 continuation use was `0/4` despite four available frontiers; a guided COUNT replay
made a valid same-query successor call and received a disjoint 20-turn page, but recovered none of
the three missing annotated answer turns. The result admits follow-up diagnostics for Activation and
D2 SHADOW, while leaving X0-X4 eligibility unchanged.

That follow-up D2 SHADOW diagnostic subsequently executed on the same four opened-development LME
families. Public first Contexts contained `6/7` model-assisted exact answer turns; D2 found `7/7` and
recovered the sole missing turn at intra-session rank `2` / global rank `53`, with Context/frontier
change, global reacquisition, hidden model calls and Canonical mutation all zero. This is positive
mechanism evidence and a warning against naive global top-k integration, not a HUMAN-sealed P11-C2
effect result. X0-X4 eligibility remains unchanged.

The resulting first-novel-per-source/global-cap-20 selector was then presealed and evaluated once on
the 21 S2 opened-development cases not used to design it. Public coverage was `23/32`; nine exact
turns were missing across seven cases. D2 contained two missing turns, but the selector recovered
`0/9` and produced zero gain/loss cases. It is therefore rejected as a Product integration policy;
D2 remains SHADOW. This negative engineering result does not alter the X0 human dependency or
consume Formal 500.

A further label-directed engineering diagnostic used seven fresh zero-Skill Codex processes on the
known public-gap LME cases, with D1 enabled and only the public resolve MCP tool available. All seven
made a correct predecessor-bound second call and received 152 novel turn refs, but within-run exact
required-turn gain was `0/6`; complete cases remained `2/7` before and after continuation. This is a
terminal negative diagnosis of one-more-page utility for those known misses, not the HUMAN-sealed X1
effect experiment. It leaves X0-X4 eligibility unchanged.

## 3. Product-11 Research stages not yet terminal

The only current experiment dependency chain without a terminal is:

```text
X0 two-independent-human 24-case adjudication
  -> X1 persisted-frontier quantitative effect
  -> X2 explicit intra-source quantitative effect
  -> X3 frontier/renderer integration when X1 and X2 pass
  -> X4 Host attribution when memory-complete cases exist
```

Current authoritative X0 state:

```text
annotator completed submission files       0
reviewer completed submission files        0
required distinct real humans              2
human COMPLETE cases                       0 / 24
proxy continuation opportunities           0 / required >= 8
proxy intra-source opportunities            8 / required >= 8
proxy control opportunities                16 / required >= 8
Formal files accessed / cases scored       false / 0
```

Only the two PENDING templates exist. Re-running both validators on 2026-09-05 failed closed with exit
1 for `ANNOTATOR` and `INDEPENDENT_REVIEWER`, confirming that neither template can be mistaken for a
completed submission. The targeted Lab human-workflow regression passed `6` tests. No AI/model identity
was promoted to `HUMAN`.

## 4. Why X1-X4 cannot be executed yet

The Product-11 Goal and frozen acceptance contract require treatment-independent, dual-human labels
before any effect arm reads labels or computes coverage. X1/X2 would otherwise lack a valid denominator
and violate the experiment's leakage contract. X3 is explicitly ineligible until both X1 and X2 pass;
X4 is ineligible until memory-complete membership is presealed.

The active user goal authorizes continued execution but does not itself provide two independently
completed semantic judgments. Formal 500 also remains explicitly unconsumed and is not used to repair
the opened-development opportunity shortage.

## 5. Exact resume condition

Provide two files produced from the existing role-specific templates:

```text
MiLAi-Lab/data/labels/product11-annotator.submission-template.v0.1.jsonl
MiLAi-Lab/data/labels/product11-reviewer.submission-template.v0.1.jsonl
```

Each must cover all 24 cases, use a distinct stable human identity, and be completed independently from
the source-only packets. After those files exist, execution resumes without rebuilding A0:

```text
validate each submission
  -> exact-agreement merge or conflict report
  -> X0 opportunity seal
  -> insufficient-opportunity terminal OR X1/X2 effect runs
  -> eligible X3/X4 stages
```

## 6. Completion determination

```text
all currently eligible automated/engineering experiments   COMPLETE
bounded R1 experiment                                      COMPLETE
Product-11 X0                                              BLOCKED_EXTERNAL_HUMAN_ADJUDICATION
Product-11 X1-X4                                           NOT_ELIGIBLE_BY_X0
overall active goal                                        NOT COMPLETE
```

No additional autonomous experiment can make X0 true without fabricating human provenance. The active
goal must remain open until the external submissions arrive or the user explicitly changes the
scientific claim/contract; the latter would define a different experiment, not complete this one.

## 7. Superseding subagent-sealed execution update

The user later explicitly changed the evaluation contract by authorizing a separate
`SUBAGENT_SEALED` branch. The preceding external-human conclusion remains accurate for the historical
HUMAN branch; it is not rewritten as complete.

Two role-specific subagents completed 24/24 source-only cases and reached exact agreement on 60
normalized groups and 70 acceptable turn refs. The seal keeps
`human_adjudication_status=NOT_PERFORMED` and limits claims to
`OPENED_DEVELOPMENT_MODEL_ADJUDICATED`.

The frozen A0 join produced `0 continuation / 8 intra-source / 16 control` opportunities. Because X0
requires at least `8/8/8`, Product-11 Research is now terminal for this slice as
`PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`. X1--X4 were not entered and Formal
files/cases remain `false/0`. See
`MILA_PRODUCT-11_X0_SUBAGENT_SEAL_AUDIT_20260905.md`.

### 7.1 Verified-chain correction

An architecture review of the first subagent receipt found two workflow-provenance weaknesses: it
reused HUMAN-oriented packets and allowed sealing without requiring the merge summary. No treatment
had run, so no effect result was rolled back. A new `20260905c` execution used dedicated source-only
subagent packets, an orchestration manifest sealed before two fresh invocations, empty Evidence IDs,
and seal-time deterministic recomputation of both proposals. The independent architecture re-review
returned `PASS` with no required fixes. Its v0.2 receipt append-only supersedes the preserved v0.1
receipt and reaches the same `0/8/16` parked terminal; Formal remains unconsumed.
