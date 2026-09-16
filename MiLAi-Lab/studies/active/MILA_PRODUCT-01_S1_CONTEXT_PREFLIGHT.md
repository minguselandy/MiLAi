# MILA-PRODUCT-01 S1 context preflight

Status: `PASS_REPAIRED_UNTREATED_BASELINE_AUTHORIZED`

- Arm kind: `PRODUCT_BLACK_BOX`
- Product commit: `959060c5a6453bf61d537b1245f99fd67395e689`
- Product lock digest: `a140f52811a37839b9e17bb7070847d2c4cc958f1175e1b798f1eb787dd4a6d8`
- Historical lock: `data/locks/product01-s1-product.lock.json`
- Dataset: `LongMemEval-S-cleaned` population 500, file SHA-256
  `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- Selection: 24 cases, outcome-blind metadata strata only; every question-type / gold-session-count
  stratum covers its short and long history tails. No answer text, gold terms, Product outcome, or
  treatment rank enters selection.
- Product flags: Formation OFF, Dense OFF, reranker OFF, Planner/model calls 0;
  `budget_invariant_context_v0_1=true` and `progressive_context_evidence_v0_1=true` are explicit
  preflight settings and remain default OFF.
- Evidence budget: 4096 tokens. Host prompt accounting uses the local pinned Qwen tokenizer and its
  exact chat template. Reader answer reserve is 1024 tokens and safety margin is 256 tokens.
- Calls: Context only; Reader 0, Answer 0, Judge 0; automatic semantic retries 0.
- Primary gates: structured identity 1.0, session identity integrity 1.0, cross-source adjacency 0,
  Reader-visible trace exactness 1.0, serialization replay equivalence 1.0, infrastructure failure
  counted as semantic abstention 0, system failure 0.
- Permitted claim: S1 Product identity/context preflight validity only. This run cannot support
  recall-quality, Reader-answer, Judge, formal-holdout, default-enablement, or release claims.

## Terminal result

- Run: `artifacts/product01-s1-20260901-005`
- Run ID: `product01-s1-20260901T131530Z`
- Selection digest: `79ab9097282c096932832c1057d77d263daaba1b20b98c317cf9e3e208d1d180`
- Result: 24/24 context cells PASS; 21 honest semantic abstentions; system failures 0.
- All primary gates matched their exact expected values.
- Reader, Answer, Judge, automatic semantic retry, and canonical mutation counts were all 0.
- Terminal SHA-256: `a62701f1d8a2668961f62a41666ba51b634e6612f4ce65db2b35d439364d0ba7`.

Disposition: S2 may construct the repaired untreated B0 from this frozen identity. The old R4 is
not resumed. The current repository-level `product.lock.json` follows the documentation-only
Product S1 acceptance commit; the historical lock above remains the exact S1 behavior pin.
