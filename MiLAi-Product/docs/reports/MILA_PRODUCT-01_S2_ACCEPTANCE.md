# MiLA Product-01 S2 acceptance

Date: 2026-09-01  
Stage: S2 — grounded simple recollection  
Result: **PASS; B1 selected for S3 with default OFF**

## Frozen run identity

- Product behavior commit: `fd9674e9ff0abe4db0449dc2a987710fea014c47`
- Product behavior tree: `c4841be0b637ddf56d35cf2fbab2a9ee15bc26b2a26e46eda7d6e7d38578e30e`
- Lab Product lock digest: `7b3039e7ca99631417a967835aa390add55e92d4c56de385d7fb0305e2a10dd7`
- Lab artifact: `MiLAi-Lab/artifacts/product01-s2-20260901-003`
- Run ID: `product01-s2-20260901T135122Z`
- Arms: repaired untreated `B0` and one-flag `B1_SIMPLE_RECALL`
- Candidate flag: `MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED`

The final paired run used five synthetic truth/false-relation/governance controls and three frozen
DG28 manipulation-opportunity cases per arm. It did not consume the 500-case formal holdout and did
not call a Reader, Answer model, Judge, policy model, or semantic retry.

## Exit gate

| Metric | Required | B0 | B1 |
| --- | ---: | ---: | ---: |
| AcceptedReferenceIntegrity | 1.0 | 0 | 1.0 |
| asserted SemanticBindingPrecision | >= 0.95 | 0.375 | 1.0 |
| true binding coverage | preserve | 1.0 | 1.0 |
| known-false relation accepted | 0 | 5 | 0 |
| strict Wrong COMPLETE | 0 | 0 | 0 |
| permission/revocation/scope leak | 0 | 0 | 0 |
| DG28 opportunity admitted coverage | >= 6/7 | 4/7 | 6/7 |
| model/provider policy calls | 0 | 0 | 0 |
| automatic semantic retries | 0 | 0 | 0 |
| acquisition phases | exactly 1 | 1 | 1 |
| Canonical mutation from read path | 0 | 0 | 0 |

B1 additionally proved exact source spans, exact EvidenceSet bindings, one enriched probe, no Dense
probe, and no deterministic recovery. Dense was neither configured nor represented as executed.

## Artifact integrity

| File | SHA-256 |
| --- | --- |
| `run.json` | `d5caab6f44197775f1148aaf816fbbd73f325ccc0d1267e779bb4e52a8d0477f` |
| `cases.jsonl` | `0bacdb778b1c40b9e809dd7ee5528721b70592954bad1473681757244267358a` |
| `metrics.json` | `ea0e04ea4753eb6f81f44b25c5bb490b857bfcc48bbf9c7f5a0a0ae1a90e19bd` |
| `terminal.json` | `4fc6332393bafd5fe07edd0eec462a939776fc4ebbaa65412278212cf84d9373` |

## Repair chain and disposition

The first attempt was invalid because its harness demanded B1-only trace fields from B0; it has no
semantic outcome. The next valid run found that an existing but empty acquisition accepted-state
was treated as if no state existed, promoting governed candidates into accepted binding references.
The general decision boundary now distinguishes absent state from an empty accepted set, with a
regression test. A fresh paired rerun then passed every S2 exit check.

B1 is selected for S3 local-usability testing. It remains default OFF; setting its single flag to
`false` restores the repaired baseline. S2 establishes a grounded recollection method effect only,
not answer quality, local readiness, default enablement, or formal-holdout performance.
