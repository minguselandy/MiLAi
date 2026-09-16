# ADR-040: Preserve Working State JSON payload content

- Status: Accepted for candidate implementation
- Date: 2026-09-06
- Schema authority: none
- Canonical authority: none

## Context

The binding model's global Pydantic whitespace stripping was inherited by State update
requests. It silently altered arbitrary payload strings and nested object keys, including
Markdown terminal newlines and code indentation. Opaque host content therefore could not
roundtrip faithfully, and distinct submitted content could collapse before fingerprinting.

## Decision

Apply whitespace normalization explicitly to the principal binding digest, project ID and
scope reference. Preserve arbitrary JSON payload strings and keys exactly through validation.
Keep reserved evidence-reference validation, permission checks, CAS and receipt semantics.
Keep the canonical JSON, digest and request-fingerprint algorithms unchanged; their input
now reflects the submitted payload. This preserves JSON values, not request wire formatting
or object key order.

## Compatibility and verification

No API shape, database schema or migration changes are required. Existing stored values and
receipts remain unchanged. Bytes lost by previous normalization cannot be recovered without
the original content. Reusing an old operation ID with a whitespace-bearing request can now
produce an operation conflict because the effective payload differs; clients must inspect the
existing receipt and current head rather than blindly retry or rewrite prior operations.

Rolling back restores the lossy input behavior for later writes; it does not undo stored data.
Direct tests cover Unicode, CRLF, Markdown, code, empty strings, whitespace-only strings,
nested keys, normalized binding identifiers, digest distinctions, replay and CAS conflicts.
Real PostgreSQL integration and public MCP roundtrips verify persisted content and receipts.
Schema remains EXPERIMENTAL and NO-GO FOR SCHEMA FREEZE.
