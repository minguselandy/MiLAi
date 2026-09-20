# Current Architecture Conformance

> This receipt validates the current Product against frozen Logical Architecture 1.0 without modifying `architecture/v1.0/`.
> `UNVERIFIED` is an intentional state; reference presence and aggregate test counts are not conformance proof.

## Result

- Current implementation status: `UNVERIFIED`
- Product source commit: `2ce622b86ec4aa9b6df7dc79243159eca3ceb8a0`
- Verified at: `2026-09-20T07:29:02+00:00`
- Architecture: `1.0.0`
- Migration heads: `0027_embedding_identity, 0045_dg18_adjacency, 0056_host_notes`

The current receipt is not an `ARCHITECTURE_CONFORMANT`, `RELEASE_CANDIDATE`, or `SCHEMA_FREEZE` declaration. Those claims remain blocked until every applicable current item has a recorded behavioral execution receipt and no item is `DEVIATION` or `UNVERIFIED`.

## Identity

| Field | Value |
| --- | --- |
| Product version | `0.1.0-candidate` |
| Product manifest SHA-256 | `eb28065c57b2d518b4e4fa7ca47555ba3039502a20059e42ab17cec2321ad971` |
| Product tree SHA-256 | `77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443` |
| Architecture manifest SHA-256 | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` |
| Runtime / Client / MCP / OpenWorker | `0.1.5` / `0.1.4` / `0.1.15` / `0.1.0` |

## Evidence matrix

| Category | PASS | NOT_APPLICABLE | DEVIATION | UNVERIFIED |
| --- | ---: | ---: | ---: | ---: |
| `goals` | 0 | 0 | 0 | 9 |
| `invariants` | 1 | 0 | 0 | 11 |
| `transactions` | 0 | 0 | 0 | 8 |
| `roles` | 0 | 0 | 0 | 5 |
| `freeze_gates` | 9 | 0 | 0 | 1 |
| **total** | **10** | **0** | **0** | **34** |

The detailed G/I/TX/role/gate mapping is in [`invariant-test-map.json`](invariant-test-map.json). Each current item contains implementation evidence, mapped tests, reference-integrity status, and the separate behavioral-verification status.

## Verification commands

- `PASS` `python3 tools/verify_revalidation_receipts.py --check`
- `PASS` `python3 tools/build_product_manifest.py --check`
- `PASS` `python3 architecture/v1.0/scripts/verify_lock.py --scope bundle --mode release --expected-manifest-sha256 <frozen-anchor>`
- `UNVERIFIED` `python3 architecture/v1.0/scripts/validate_bundle.py` — AF-09 historical submission tarballs are archive-owned and ignored by the Product Git tree; only their tracked archive classification records are available here.

## Behavior revalidation

Receipts are validated against the current Product tree and manifest. `SCOPED` claims are recorded as execution evidence but do not promote the broad frozen item; only `COMPLETE` claims can produce `PASS`.

- Index: [`docs/revalidation/INDEX.md`](../revalidation/INDEX.md)
- Receipt count: `2`
- Explicit claim count: `9`

## Status semantics

- `PASS`: current evidence is behaviorally verified by a recorded execution receipt.
- `NOT_APPLICABLE`: the claim does not apply and the reason is recorded.
- `DEVIATION`: the current implementation or evidence mapping differs from the frozen claim.
- `UNVERIFIED`: the claim applies, but the receipt does not yet contain sufficient behavioral evidence.

The frozen bundle remains the historical logical-architecture authority. This document is the current implementation conformance layer; changing a logical invariant requires a new architecture version rather than an edit to `architecture/v1.0/`.
