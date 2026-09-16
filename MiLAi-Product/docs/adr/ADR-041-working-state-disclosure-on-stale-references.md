# ADR-041: Withhold Working State content with unreadable declared Evidence

- Status: Accepted for local candidate implementation
- Date: 2026-09-06
- Schema migration: none
- Canonical authority: unchanged

## Observed failure

A real, isolated public MCP probe saved a canary in State with an exact Evidence reference,
revoked that Evidence, and fetched State again. Both GET and an idempotent replay of the old
update returned the derived canary. GET carried a stale-reference warning, which did not prevent
disclosure. The evidence is retained in Lab's `eng-20260906a/revocation-before` artifacts.

## Decision

For any returned State version with a currently missing, revoked or unreadable declared Evidence
reference, return an empty payload and `payload_withheld=true`, retaining the existing warnings
and version/lineage identity. Apply the same rule to GET and update receipts, including replay.
Active eligible versions return their full original payload and `payload_withheld=false`.

The Runtime does not infer which opaque fields depend on which reference, so suppression covers
the entire payload. It does not infer that the content is false or that an unresolved task is
resolved. Historical versions, references, digests, CAS and idempotency remain unchanged.
This supersedes ADR-034's warning-only disclosure decision. A successful operation and whether
its historical content can currently be returned remain different facts.

## Limits and compatibility

This protects dependencies declared through the reserved reference contract. It does not discover
undeclared provenance, erase material already delivered to an old session, or revoke independent
files. Host-managed derivative files require a trusted provenance/eligibility check at their own
disclosure boundary; returning their content with a warning is insufficient.

The response flag is additive. Clients must not interpret empty withheld content as semantic
deletion or overwrite it as a replacement. No API input, database structure, canonical procedure,
or authority changes are required. Reverting code reopens the demonstrated disclosure route for
future responses; it does not restore or modify historical content. No public deployment occurs
as part of the local repair. Schema remains EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE.

## Verification

Require real PostgreSQL tests for eligible GET/replay, revoked GET/replay, immutable history,
unchanged operation/version identity, and denied new writes referencing revoked Evidence.
Also recheck the actual public MCP route; unit tests alone cannot establish this boundary.
