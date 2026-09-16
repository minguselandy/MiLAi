# ADR-046: Bounded working-state provenance capacity

Status: accepted for experimental development; NO-GO FOR SCHEMA FREEZE.

A real task produced a compact reusable note supported by more than 256 distinct
Evidence records. The public State API rejected its provenance before saving.
Dropping citations would weaken disclosure checks and is not an acceptable repair.

Raise the API and PostgreSQL procedure limit to 1024 unique references. Keep the
existing 64 KiB payload bound and all per-reference identity, scope, readability,
revocation, CAS and idempotency checks. This changes resource capacity only; it
introduces no semantic schema, new authority or automatic memory operation.

Migration 0055 replaces only the installed procedure's capacity guard and fails
if that guard is unexpected. It preserves owner, grants, tables and immutable
history. Deploy the migration before the new API. Downgrade restores the 256
write limit without deleting larger historical versions; old clients cannot
rewrite those larger payloads unchanged. Reads and disclosure checks continue.

Validate the API boundary, real PostgreSQL save/read and late-reference denial,
plus downgrade/upgrade behavior. Larger reference sets can cost more to check;
measure real save/recovery separately from model inference and do not infer
semantic memory quality from successful storage.
