# ADR-043: Preserve Evidence content across typed capture and Runtime ingestion

Status: ACCEPTED FOR IMPLEMENTATION / Schema remains NO-GO FOR SCHEMA FREEZE.

The P2 worker-off save/read check observed a lost final newline. Runtime EvidenceIngestRequest
and SDK EvidenceCaptureRequest both applied model-wide whitespace stripping to content.
That normalizes source observations before the content hash and stored blob are created.

Override whitespace stripping for the content field in both typed boundaries. Preserve leading
and trailing whitespace, tabs, line endings and Unicode exactly as the submitted JSON string.
Identifier normalization and permission checks remain unchanged. Empty strings remain invalid;
nonempty whitespace-only observations are preserved rather than silently discarded. Runtime byte
limits apply to the preserved UTF-8 content, including all boundary whitespace.

This changes new capture fingerprints when previously stripped content was supplied. Old Evidence
and outbox records remain immutable; previously removed bytes cannot be reconstructed. Replaying
an old operation with now-distinct content may return IDEMPOTENCY_CONFLICT: retain the conflict,
never silently rewrite historical evidence or claim equivalent operation identity. Plain content
without boundary whitespace retains its existing behavior. No migration or Canonical change.

Rollback would restore lossy ingestion and must withdraw the fidelity claim. Public cold-process
readback and direct PG fault checks cover current content/receipt behavior, not semantic truth.
