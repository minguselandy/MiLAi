# MILA-PRODUCT-01 S2 grounded simple recollection

Status: `PASS_S2_SIMPLE_RECALL_READY_FOR_LOCAL_USABILITY`

- Arm kind: paired `PRODUCT_BLACK_BOX`; repaired untreated `B0` versus one-flag
  `B1_SIMPLE_RECALL`.
- Product behavior commit: `fd9674e9ff0abe4db0449dc2a987710fea014c47`.
- Product lock logical digest:
  `7b3039e7ca99631417a967835aa390add55e92d4c56de385d7fb0305e2a10dd7`.
- Historical lock: `data/locks/product01-s2-product.lock.json`.
- Candidate flag: `MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED=true` in B1;
  the Product default remains OFF and setting the flag to `false` restores B0.
- Workload: five synthetic truth/false-relation/scope/revocation controls and three frozen
  DG28 manipulation-opportunity cases per arm. The 500-case formal holdout was not consumed.
- Calls: Reader 0, Answer 0, Judge 0, provider/model policy 0; automatic semantic retries 0.
- Capability boundary: Evidence Dense remained disabled and was not represented as executed;
  deterministic recovery remained disabled; exactly one acquisition phase ran.

## Terminal result

- Run: `artifacts/product01-s2-20260901-003`.
- Run ID: `product01-s2-20260901T135122Z`.
- B0 asserted binding precision: `0.375`; known-false relations accepted: `5`;
  DG28 opportunities admitted: `4/7`.
- B1 asserted `SemanticBindingPrecision`: `1.0`; true-binding coverage: `3/3`;
  known-false relations accepted: `0`; strict Wrong COMPLETE: `0`.
- B1 DG28 opportunities admitted: `6/7`; target bindings: `5`; stable mediator gain: PASS.
- B1 accepted-reference integrity, exact source spans, EvidenceSet binding exactness,
  scope/revocation isolation, and canonical read immutability: all `1.0`/PASS.
- Terminal SHA-256: `4fc6332393bafd5fe07edd0eec462a939776fc4ebbaa65412278212cf84d9373`.
- Cases SHA-256: `0bacdb778b1c40b9e809dd7ee5528721b70592954bad1473681757244267358a`.

Two earlier attempts are retained as audit history. `-001` is an invalid preflight protocol
implementation and has no semantic outcome. `-002` exposed an empty accepted-state decision bug;
its failed result was preserved, the general boundary was repaired with a regression test, and
`-003` is the independent final rerun against the new Product commit.

Disposition: select B1 for S3 local-usability testing while retaining default OFF. This stage
supports a grounded-recollection method-effect claim only. It does not establish end-to-end answer
quality, local usability, default enablement, or formal-holdout performance.
