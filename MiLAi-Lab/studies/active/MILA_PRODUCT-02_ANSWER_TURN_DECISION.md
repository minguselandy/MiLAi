# MILA-PRODUCT-02 answer-turn and U3 decision

Status: `COMPLETED_PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE`

This study executed Product-02's U0–U3 staged gates. It does not authorize a public API or schema
change, default enablement of an experimental retrieval profile, or use of the formal 500-case
holdout.

## Frozen identities

- Product Git provenance: `1b5e4a7122da2b38b9a57bba143215cc0afa3387`.
- Product behavior tree: `3c7cc1b1304263d1bb41d60952efe2feadfb0a9db86087e86fd017780e5df5ba`.
- Product manifest: `4088a605f6d5b2767c286985468c20500c2797feae0e52863cc40d9d1a577db2`.
- Product-02 lock logical digest: `6f2869254659bf1c5f7710785a65016cb21b36d06b5411da978e9ffe98c68d1b`.
- Product-02 lock file SHA-256: `792db4da0c8582e45e4176842c122b18289ccc94e1e0b8e3f0f14daf0502fbe2`.
- Dataset: pinned LongMemEval-S cleaned 500, SHA-256
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- Decision label manifest: `data/labels/product02-longmemeval-answer-turns-qwen36-v4.json`, SHA-256
  `6238c10cb7d6203715043a1437add55e3cd8114d20cec9e7ceded11c92831412`.

The v4 labels are model-assisted exact-turn evaluation labels, not independently human-adjudicated
benchmark ground truth or leaderboard-equivalent labels. The annotator used only question, date,
reference answer and oracle sessions; it did not inspect Product/Reader output or native
`has_answer`. Qwen3.6-35B-A3B-FP8 ran at temperature 0 with no semantic retry or voting. Label
versions v1–v3 are diagnostic contract-development outputs and were not joined to the decision run.
Creating the 500-case label list was evaluation preparation, not a 500-case Product/Answer/Judge
run; `formal_holdout_consumed=false`.

## Development gates

- U0 repaired strict completion so raw lookup cannot independently grant `COMPLETE`, and replaced
  the session proxy with exact answer-turn and optional exact-span metrics.
- U1 evaluated direct Dense and bounded same-session expansion. A0/A1/A2 each scored 0.625 on the
  opened-development 8-case slice, so A1/A2 were parked and A0 was selected; its 24-case gate passed.
- U2 introduced an internal LeanRecallPlan/EvidenceSet prototype, AcceptedOperatorInputs-only
  strict operators, ordinary/strict sufficiency separation, and role-first atomic Context. Its
  targeted 8-case and outcome-blind 24-case gates passed.
- Superseded 128 runs exposed three strict false-COMPLETE cases and a provider-classification issue.
  General temporal-anchor/event-compatibility repairs and matched-success hard gates removed them.
- A final anti-special-case audit removed a fixture-shaped entity expansion. The first fresh run on
  that generalized tree (`128-005`) preserved one strict entity-only event failure; a general
  action-anchor/entity-overlap repair plus a negative control removed it before the authoritative
  fresh run.
- Completion audit then found historical Product tests containing real case identities, exact
  sealed quotes, and explicit instance-to-category mappings. They were replaced with synthetic
  fixtures or removed. A machine comparison against all 500 case IDs and exact label quotes found
  zero Product matches; the Product and lock were frozen again before the final local/sealed runs.

After that final freeze, the named deterministic stage gates were repeated: A0 passed 24/24 in
`product02-u1-selected-a0-24-002`; B2 passed 8/8 in `product02-u2-micro-b2-004` and 24/24 in
`product02-u2-b2-24-003`. All three runs made zero Reader/Judge calls and zero canonical mutations.

## Local Product gate

Authoritative artifact: `artifacts/product02-u3-local-final-006`.

```text
terminal                              PASS_PRODUCT02_U3_LOCAL_USABILITY
golden flow                           PASS
product scenarios                     24/24
warm typed requests                   100/100
read-after-write P95                  1095.955 ms
retrieval + Context P95               60.454 ms
warm control P95                      16.566 ms
deterministic fallback                1.0
governance leaks / read mutations     0 / 0
selected arm                          B0_B1_EQUIVALENT_BASELINE
candidate default enabled             false
```

Artifact file hashes:

```text
run.json       b0bf565b2a99626bd86ac0401c0c3d3a1989339a5f6ef6f0be2a3f2c1b6d223c
cases.jsonl    3525c0ccfdd6dcb9c9b80b8c9dff3588f84f399a0d93fdaefc292fcec493ea3c
metrics.json   2a747ac4138949ce6380ab71b47a470f7f207c1e41e8522534e5f183e0abf94b
terminal.json  6b59d06d630eefd4bb99ceabd218debd5f80b9ab04bc24d148c274f4e42729ca
```

## Sealed 128-case decision

Authoritative artifact: `artifacts/product02-u3-longmemeval-128-007`. B0 is the repaired control,
B1 is the selected A0 configuration and is an exact B0 alias, and B2 enables the U2 EvidenceSet
prototype. There were 384 logical cells, 256 executed Product Context calls because of the exact
B1 alias, and 384 successful Answer plus 384 successful Judge calls.

| Metric | B0/B1 baseline | B2 EvidenceSet | B2 − B1 |
| --- | ---: | ---: | ---: |
| Exact answer-turn coverage | 0.418129 | 0.052632 | -0.365497 |
| Exact answer-span coverage | 0.407738 | 0.053571 | -0.354167 |
| Required-role coverage | 0.354270 | 0.051240 | -0.303030 |
| Qwen Judge accuracy | 0.265625 | 0.078125 | -0.187500 |
| P95 latency | 2153.474 ms | 1837.239 ms | 0.853151x |

All infrastructure, identity, provider, governance, trace/config exactness, zero-mutation and zero
strict-Wrong-COMPLETE hard gates passed. B2 had 1 paired win and 25 losses; the 10,000-sample
bootstrap 95% interval was `[-0.2578125, -0.1171875]`. Only its latency effect check passed.

```text
terminal                     PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE
selected disposition         B0_B1_EQUIVALENT_BASELINE
B2                            PARKED_NO_EFFECT_DEFAULT_OFF
candidate entry              false
500-case confirmation        NOT_ENTERED
formal holdout consumed      false
```

Artifact file hashes:

```text
run.json       59960996ffbb2d4e0414e449510ae7b9e0bfeeb26c67ac0b556be7539ddeedae
cases.jsonl    64acf8c10199ca22956eff8c6955011e1208b5df14b4baa30d4332a35f4e30a2
metrics.json   71d3eacd10a875b34b5fbe5a5ffa1b6c50ba02828f255a95822b1bc7c37d6028
terminal.json  84cf0d596c0ca46b2eef6db21e57186a1ba84ceffd0a05cda5dd52f35724b9c2
```

Runs `128-001` through `128-003` are incomplete or diagnostic; `128-004` predates the final
anti-special-case audit; `128-005` is the preserved strict-hard-gate failure that drove the final
general repair. `128-006` predates the final Product leakage audit. All are superseded by `128-007`
and must not be used for the final treatment-effect conclusion. Likewise, local `final-001` through
`final-004` are incomplete or bound to earlier trees; `final-005` is the preserved F0 incomplete run
created before its fresh stack was started. They are superseded by `local-final-006`.

All Product-02 API and PostgreSQL services were stopped after validation. Their exact experiment
volumes were preserved; no unrelated long-running environment was stopped or deleted.

## Claim boundary

The supported claim is a usable local Lean baseline with the simpler B0/B1-equivalent path. The U2
prototype is not admitted for default use. No production readiness, schema freeze, public API
stability, independent human benchmark adjudication, or leaderboard equivalence is claimed.
