# MILA-PRODUCT-01 S4 LongMemEval confirmation

Status: `COMPLETED_FAIL_S4_REPAIR_OR_KEEP_BASELINE`

- Arm kind: matched `PRODUCT_BLACK_BOX`; `B0_REPAIRED_UNTREATED` versus the one-flag
  `B1_SIMPLE_RECALL` candidate.
- Product commit: `1b5e4a7122da2b38b9a57bba143215cc0afa3387`.
- Product tree: `c4841be0b637ddf56d35cf2fbab2a9ee15bc26b2a26e46eda7d6e7d38578e30e`.
- Product lock digest: `44f191ca9ea75d697266f42a11a4b22483d5cf7fe470fb84b33eb7656fa2ac5c`.
- Historical lock: `data/locks/product01-s4-product.lock.json`.
- Dataset: pinned LongMemEval-S cleaned 500, SHA-256
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
- Repaired slice: deterministic outcome-blind structural selection of 128 cases. The formal run
  uses the complete frozen source order of 500 cases.
- Provider: existing loopback vLLM `Qwen3.6-35B-A3B-FP8`; Reader and Judge use the same model and
  this self-judge limitation is disclosed. No GPT-4o or leaderboard equivalence is claimed.
- Generation: temperature 0, no semantic retry, no vote. Answer calls are sealed before any Judge
  call. A transport/schema failure permits at most one retry only after a successful health check;
  the initial implementation performs no automatic retry.
- Concurrency: context `8` per isolated arm (`16` global), Reader `8`, Judge `8`. The 128 run is the
  stability witness; these ceilings remain frozen for 500 if it passes.

## Frozen Reader envelope

The evidence budget is calculated once as

```text
min(Product public cap 8192,
    model usable context 65536
    - maximum fixed empty-context prompt tokens across the population
    - answer reserve 1024
    - safety margin 256)
```

It therefore resolves to 8192 tokens, subject to a pre-run exact-tokenizer assertion. Product packs
only complete Evidence units. The harness records the serialized context digest and every rendered
unit's exact token range in the actual Qwen chat-template prompt.

## Gates

The 128 run must meet both-arm SystemContextSuccessRate `>=0.98`, no systemic worker exit, no
cross-session contamination, ReaderVisibleTraceExactness `=1.0`, no strict Wrong COMPLETE, and
default-off candidate control. Only then may the explicitly requested full-goal execution consume
the 500-case formal holdout.

The 500 admission thresholds are SystemContextSuccessRate `>=0.99`, strict Wrong COMPLETE `=0`,
AllRequiredEvidenceGroupCoverage delta `>=+0.05`, QwenJudgeAccuracy point delta `>=+0.02`, paired
10,000-sample bootstrap 95% lower bound `>=-0.01`, candidate P95 resolve latency `<=1.5x` baseline,
and zero scope/revocation/wrong-relation leak. A non-admitted candidate remains default OFF and the
Product is handed off with repaired baseline recall.

## Executed terminal

The matched 128-case run completed as `product01-s4-128-20260901T143318Z`:

```text
SystemContextSuccessRate             B0=1.0, B1=1.0
AllRequiredEvidenceGroupCoverage     0.6015625 → 0.625
QwenJudgeAccuracy                    0.28125 → 0.3125
SessionRecall@5                      0.739583 → 0.729297
SessionNDCG@5                        0.693233 → 0.677722
strict Wrong COMPLETE                3 → 1
terminal                             FAIL_S4_REPAIR_OR_KEEP_BASELINE
```

The 128 entry gate therefore failed and the 500-case confirmation was not entered. The field named
`reader_visible_gold_span_coverage` was later found to use visible/relevant session identities, not
exact answer-bearing spans, so no span-level effect claim is permitted from this run.

Future repair and fresh matched execution are planned by MiLAi Product-02. This study remains as the
Product-01 preregistration plus executed terminal record; it no longer authorizes additional runs.
