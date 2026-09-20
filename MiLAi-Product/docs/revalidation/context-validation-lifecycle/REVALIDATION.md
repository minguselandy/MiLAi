# Context validation lifecycle revalidation

Decision: `OPEN`

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

The result does not decide whether renewal should be forbidden or should be a
formal new validation lease. Either contract requires an explicit upper bound
and proof that expiry, revocation, canonical movement, issue revision, and
context identity interrupt unsafe reuse. The current implicit behavior is
therefore `OPEN`. No production lifecycle change is included here.

The machine-readable failed execution record is [`receipt.json`](receipt.json).
It attaches scoped failed evidence to G7 while leaving G7 `UNVERIFIED`; it does
not assert an Architecture 1.0 `DEVIATION`.
