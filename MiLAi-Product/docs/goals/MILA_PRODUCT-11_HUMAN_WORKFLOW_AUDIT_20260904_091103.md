---
document_id: MILA-PRODUCT-11-HUMAN-WORKFLOW-AUDIT
version: "0.1"
status: READY_AWAITING_TWO_INDEPENDENT_HUMANS
created_at: "2026-09-04T09:11:03+08:00"
goal: MILA-PRODUCT-11@0.5
formal_holdout_authorized: false
---

# Product-11 X0 human workflow audit

## Outcome

The remaining X0 human gate is executable and fail-closed. It is not complete: no real human has
signed either submission, so Product behavior, migration, X1--X4, and the final MCP continuation
wrapper remain unentered.

## Frozen inputs and outputs

```text
source fixture file SHA-256     c1fee1f4e9f68e7d9a0b082984c4ed5e4952e1e3f72ae009afd264640ba4c709
A0 trace SHA-256                eef498d36c35b102ca6943469c7b203113237b1bf63c3cb17cd8c95f9dd27a95
annotator template SHA-256      9ea92661a0d0791d3b009fae830b6de85cec51cda8dbc37aad2d5c38eea520de
reviewer template SHA-256       bb357e087b4942e8960aecd013c05632d79f9ec8e6e5c801b0aa01c45bfe5842
source review view SHA-256      ccc583cf7b4b262714f3f49f81269f10e44da6c09acd1fb1ddb0dc85cb399d77
submission rows                 25 + 25 (manifest + 24 cases per role)
human COMPLETE                  0/24
Formal files/cases              false/0
```

The submission templates contain no model-proposed groups and no opportunity fields. The compact
review view contains source text only and no Product identity sets or A0 output. Deterministic
index-only distractors are compacted to preview plus SHA; full role-specific source packets remain
available for inspection.

## Merge behavior

The merger requires:

- two different `kind=HUMAN` identities with non-empty timestamps and attestations;
- 24/24 COMPLETE rows in fixture order with unchanged capability shapes;
- exact valid turn identities and zero required cross-group Evidence/turn overlap;
- exact group-semantic agreement while allowing human-local group IDs to differ.

Any disagreement produces `BLOCKED_HUMAN_RECONCILIATION_REQUIRED` and no adjudicated output. Exact
agreement produces deterministic group IDs/provenance and only then derives continuation,
intra-source, and control fields from the frozen label-blind A0 trace. It cannot trust or accept
human-entered opportunity flags.

## Verification

```text
active boundary                    PASS
Lab tests                          89 PASS
Ruff                               PASS
strict mypy                        PASS (29 source files)
wheel + source distribution        PASS
Product final baseline lock        PASS
Product logical lock digest        4bf9ee438c92a5c4545bbcd05e940136d6f0e477f89a10cf5366663640b6d68b
Product observed tree              0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5
blank-template merge               REJECTED AS EXPECTED
```

The first lock invocation omitted the explicit Product root required by a lock stored below
`data/locks`; it failed before verification. Re-running the same immutable lock with
`--product-root ../MiLAi-Product` passed with the exact frozen digest and tree above. No lock or
Product behavior was changed.

## Remaining gate

Follow the Lab `docs/PRODUCT11_X0_HUMAN_REVIEW_RUNBOOK.md`. Only two real independent completions can
resolve the current gate. If the resulting frozen A0 opportunity counts remain below 8/8/8, seal the
human result and use `PARKED_PRODUCT11_INSUFFICIENT_HUMAN_SEALED_OPPORTUNITY`; do not reshape A0 or
start Product implementation.
