# ADR-027: DG-17 Raw Evidence dense projection

## Status

Candidate, default disabled. The A6 matched productization gate decides promotion.

## Decision

Raw Evidence dense retrieval owns a separate, rebuildable `vector(128)` projection keyed by
tenant, Evidence ID, embedding model, and input-projection version. Stored Evidence remains the
lossless turn. Only a versioned UTF-8 prefix of at most 32,768 bytes is embedded; the prefix never
replaces or mutates `lexical_text` or the governed Blob.

Dense search executes only after tenant, permission, retention, requested scope, source-observed
time and `as_of` filters. A query is projection-ready only when every eligible Evidence document
has an embedding for the exact model/version and source outbox sequence. Partial projection state
is explicit and the Runtime falls back to deterministic acquisition.

The existing Canonical ClaimVersion vector and reranker paths are not evidence for this lane.
Exact/current-state retrieval does not call the Evidence dense projection. Dense and reranker
results cannot prove `ALL_MATCHES_IN_RANGE` or mutate canonical state.

## Rebuild and backfill

`read_evidence_dense_backfill_batch` enumerates live projected Evidence missing the exact
model/version. The Runtime embedding provider embeds the versioned bounded input and
`upsert_evidence_dense_128` writes idempotently. Online ingestion performs the same upsert after
the lossless Evidence document is committed. Absence or failure leaves dense readiness PARTIAL
without hiding the FTS Evidence projection.

## Purge, watermark, and rollback

The dense row has an `ON DELETE CASCADE` foreign key to `evidence_search_document`, so the existing
governed Evidence purge removes it in the same deletion path. Readiness binds each row to the
Evidence source outbox sequence; no dense-specific watermark may overstate coverage. Downgrade is
allowed only while the product flag is disabled: drop the three functions and the rebuildable
table, leaving governed Evidence and Canonical state unchanged. Roll-forward consists of applying
the migration and rerunning the bounded backfill.
