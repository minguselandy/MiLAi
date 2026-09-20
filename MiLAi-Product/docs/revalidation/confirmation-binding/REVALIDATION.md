# Action confirmation binding revalidation

Decision: `OPEN`

The current Product was tested without changing the confirmation mechanism.
One fresh `USER_CONFIRMATION` Evidence record was first accepted for its
original action-sensitive chat request, then replayed with a different query
and active goal and again with a different requested scope.

## Observed behavior

- the original request was accepted with `live_confirmation: true`;
- the same Evidence ID and nonce were accepted after query and goal changed;
- the same Evidence ID and nonce were accepted after requested scope changed;
- neither replay was rejected as `LIVE_CONFIRMATION_REQUIRED`;
- `ChatRequest` has no action identity or action digest to bind.

The current check proves freshness, tenant-local Evidence lookup, source type,
nonce-shaped source reference, fixed subject, and exact content. It does not
bind the confirmation to the server's current query fingerprint, goal, scope,
required authority, or a specific action. This is a current replay gap, so the
technical debt is `OPEN`. No production fix is included in this diagnostic
change.

The machine-readable failed execution record is [`receipt.json`](receipt.json).
It attaches scoped failed evidence to G7 while leaving G7 `UNVERIFIED`; it does
not assert an Architecture 1.0 `DEVIATION`.
