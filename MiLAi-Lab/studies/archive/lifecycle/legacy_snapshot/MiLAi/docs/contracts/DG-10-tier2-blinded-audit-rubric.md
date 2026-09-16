# DG-10 Tier-2 Blinded Human Audit Rubric

Status: pre-frozen rubric; audit not started  
Protocol: `DG10_TIER2_BLINDED_HUMAN_AUDIT_V1`  
Scope: the 12 stratified LongMemEval dev cases frozen in `DG-10-quality-acceptance.yaml`

The audit package must hide arm names, execution order, token counts, model-call counts, and deterministic scores. For each case, randomly permute the three answers using a package-level seed committed before annotation. Annotators may see the public benchmark question and reference answer, but must not see retrieval traces or raw memory until the first-pass labels are locked.

For every blinded answer, record these fields:

1. `answer_correctness`: `CORRECT`, `PARTIALLY_CORRECT`, `INCORRECT`, or `AMBIGUOUS_REFERENCE`.
2. `support_status`: `SUPPORTED`, `UNSUPPORTED`, `CONFLICTING`, or `NOT_ASSESSABLE`.
3. `uncertainty_calibration`: `APPROPRIATE`, `OVERCONFIDENT`, or `UNNECESSARILY_ABSTAINED`.
4. `preference_rank`: a strict rank from 1 to 3 unless two answers are genuinely indistinguishable; ties require a reason code.
5. `reason_code`: one or more of `LATEST_STATE`, `TEMPORAL_ORDER`, `ENTITY_MISMATCH`, `MISSING_DETAIL`, `EXTRA_UNSUPPORTED_DETAIL`, `REFERENCE_AMBIGUITY`, or `OTHER_REDACTED_NOTE`.

After first-pass labels are immutable, reveal only the bounded evidence block for support adjudication. Arm identity remains hidden until all adjudication is complete.

Two independent human annotators are required. Disagreements on correctness, support, or overconfidence go to a third adjudicator. The final report must include per-annotator agreement, conflict counts, adjudication outcomes, the blind-package SHA-256, randomization-manifest SHA-256, and zero raw private data. Codex, the benchmark model, and a same-vLLM judge cannot act as a human annotator.

Tier-2 can reveal deterministic-metric bias or ambiguity, but it cannot override a hard safety failure, hidden model call, test-boundary violation, or Tier-1 deterministic BELOW_TARGET result.
