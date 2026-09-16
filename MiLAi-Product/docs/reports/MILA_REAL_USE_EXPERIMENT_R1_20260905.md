---
document_id: MILA-REAL-USE-EXPERIMENT-R1
version: "1.0"
status: COMPLETE_ENGINEERING_READ_USABILITY_WINDOW
started_at: "2026-09-05T09:50:00+08:00"
evaluation_mode: ENGINEERING
baseline_tree_sha256: f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1
post_fix_tree_sha256: d93bef8bfdf846963dabddf5635ba254dea7442d42e0eee3dcebb3ae87d9199d
formal_holdout_consumed: false
skills_loaded: false
---

# MiLA Real-use Experiment R1 — Window 1

## 1. Purpose and boundary

R1 starts the post-baseline, failure-driven Engineering observation loop. It does not open Product-11
Research X0, does not consume Formal 500, and does not authorize D2 `FRONTIER`, Dense acquisition or
an anchor-first renderer.

Window 1 used three fresh Codex sessions with an empty TASK State and MiLA as the only external MCP
server. Skills instructions, bundled Skills, skill search, plugins, MCP apps and multi-agent were
disabled. Codex was prohibited from reading repository files or using shell tools, so historical
answers had to come from MiLA MCP Evidence or honestly abstain.

## 2. Task H1 — unavailable baseline history

```text
thread                         01a06f46-3c3d-7922-a472-3e581ff01dd1
Host TASK prefetch             ABSENT / version 0
model-selected MiLA calls      3 resolve calls
Skill instruction blocks       0
input/output tokens            92,851 / 456
```

The requested current baseline/D2 authorization summary had not been captured as governed Evidence.
Codex searched once broadly and twice with narrower residual queries. It refused to fabricate the
answer and explicitly noted that missing Evidence does not imply authorization.

This task exposed `MFL-20260905-001`: the MCP facade labeled the empty Runtime envelopes as
`retrieval_status=HIT` because their bounded `memory_status=ABSENT/ABSTAINED` control text was promoted
to an `EVIDENCE_CONTEXT` with no Evidence IDs. Codex compensated correctly, but the structured MCP
contract was misleading.

## 3. Failure repair and same-boundary verification

The smallest repair was made in the existing MCP renderer: Runtime `ABSENT` and `ABSTAINED` envelopes
are no longer Host-visible Evidence units. No query routing, ranking, Context budget, continuation or
D2 logic changed.

```text
focused renderer tests          6 passed
complete MCP tests              156 passed, 1 skipped
Ruff / mypy                     PASS
uv package build                PASS
public 7968 no-match probe      MISS / evidence=[] / context_id=null
public MCP service              restarted / ready
```

## 4. Task H2 — known positive history

```text
thread                         01a06f49-b867-7663-8f65-12018a7f3546
Host TASK prefetch             ABSENT / version 0
model-selected MiLA calls      1 resolve call
Skill instruction blocks       0
retrieval                      HIT / 8 Evidence / frontier exhausted
input/output tokens            96,421 / 498
```

The post-fix positive control asked whether POST-based `working_state_get` is retry-safe and requested
the Host and no-sandbox validation outcomes. The first resolve returned the exact two decisive records
plus related task history. Codex correctly reported `1 passed in 0.30s` outside the managed sandbox
and `1 passed in 0.29s` in a no-sandbox Codex session, retained the unresolved sandbox-mechanism limit,
and cited the exact Evidence IDs. This demonstrates that the empty-envelope fix did not demote a real
HIT.

## 5. Operational observations that are not MiLA product failures

- The same host's public-IP request initially traversed its configured local HTTP proxy and received
  502. A direct/no-proxy connection succeeded. This is client network configuration, not MCP protocol
  failure.
- The first launcher attempt omitted the runbook-required live `MILAI_BASE_URL` override and failed
  closed at readiness with 503 before Codex started. Supplying `http://127.0.0.1:28180` succeeded; no
  product change was made.
- An intentionally mistaken `max_evidence` argument returned a precise MCP error naming allowed
  arguments and a correct example; the retry with the public schema succeeded.
- Fresh temporary `CODEX_HOME` under `/tmp` produced a non-fatal Codex PATH-alias warning. It did not
  affect authentication, MCP initialization, tool selection or task outcome.

## 6. Task H3 — post-fix negative result consumed by fresh Codex

```text
thread                         01a06f51-30db-7bc0-9b41-12ce2b232b3b
Host TASK prefetch             ABSENT / version 0
model-selected MiLA calls      1 resolve call
Skill instruction blocks       0
retrieval                      MISS / evidence=[] / context_id=null
input/output tokens            65,507 / 258
```

A unique marker absent from governed Memory was queried after deployment. The facade returned the
correct empty-result contract and Codex reported that the marker was not found while preserving the
epistemic limit that a retrieval miss is not proof of corpus-wide nonexistence.

## 7. Window result

```text
fresh zero-Skill Codex tasks               3
ordinary historical-query activation       3 / 3
correct evidence-grounded/abstaining answer 3 / 3
write/governance/destructive calls          0
Canonical mutation                          0
real post-baseline failures                 1
failures fixed and redeployed               1
Product-11 Research effect claims           0
Formal 500 consumed                         0
```

R1 is complete as a bounded read-usability experiment. Ongoing genuine task monitoring continues in
the Production Failure Ledger rather than keeping an experiment permanently open. New work is admitted
only when a real observation is reproducible and points to the smallest affected layer.
