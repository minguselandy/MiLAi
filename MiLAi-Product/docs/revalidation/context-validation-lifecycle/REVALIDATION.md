# Context validation lifecycle revalidation

Current decision: `FIXED`

## Diagnosis history

The validation-token and retained-slot cache path was exercised with a
controlled clock. An initial context was prepared with a ten-second capsule
and token lifetime. At `t0+9s`, cache validation issued a new ten-second token.
At `t0+11s`, after the original capsule's fixed expiry, the renewed token was
accepted again as `VALIDATED_TASK_SLOT_REUSE` without retrieval.

## Observed behavior

- token signature, tenant/profile/binding checks and token expiry remain
  enforced;
- canonical-position and OpenIssue revision changes force refresh;
- cache validation uses the retained canonical and issue snapshot;
- successful cache validation replaces `issued_at` and `expires_at` with a new
  lease derived from the current request;
- the signed state carries capsule ID and context hash, but not the original
  capsule expiry;
- `_validate_cached()` does not validate the capsule row or its status/expiry.

The original failed execution remains unchanged in [`receipt.json`](receipt.json):

```text
execution: FAIL
decision: OPEN
Product tree: 77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443
```

It is historical diagnosis evidence and does not contribute a current-tree
Conformance claim.

## Remediation

Retained task-slot validation now reads the corresponding server-owned
ContextCapsule in the same `REPEATABLE READ` snapshot as canonical position
and OpenIssue revisions. CACHE reuse requires:

- the capsule row exists and is owned by the authenticated actor;
- `status == ACTIVE`;
- `expires_at > now`;
- the authoritative content hash equals the signed token's context hash;
- canonical position and OpenIssue revisions remain unchanged.

A renewed validation lease is capped at the authoritative capsule expiry. A
capsule lifecycle or identity miss does not fail the memory request: it becomes
a typed CACHE miss, then follows the existing exact L0 refresh path to create a
new immutable capsule and validation lease. The capsule itself is never
extended.

The current passing evidence is in
[`remediation.receipt.json`](remediation.receipt.json):

```text
execution: PASS
decision: FIXED
Product tree: a93268d94a73e5aee53150ca4be9bbc5f37f76d0173c5be72633cc54cf2ea382
```

The remediation contributes a `SCOPED PASS` for G7. G7 remains `UNVERIFIED`.
