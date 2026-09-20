# Action confirmation binding revalidation

Current decision: `FIXED`

## Diagnosis history

The original Product baseline accepted one fresh `USER_CONFIRMATION` Evidence
record for its original action-sensitive chat request and then accepted the
same Evidence ID and nonce after query, active goal, and requested scope
changed. `ChatRequest` had no action identity or action digest to bind.

That execution remains recorded unchanged in [`receipt.json`](receipt.json):

```text
execution: FAIL
decision: OPEN
Product tree: 77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443
```

The diagnosis receipt is historical evidence. It is validated against its
committed Product manifest but cannot contribute a claim about the current
Product tree.

## Remediation

Chat confirmation and `PrepareContext` `ACTION_PROPOSED` now use the same
canonical action identity helper. The identity binds:

- authenticated tenant;
- query and active goal;
- requested scope and required authority;
- canonical action digest.

Action-sensitive `ChatRequest` values require a lowercase SHA-256
`action_digest`. Confirmation Evidence uses
`chat-confirmation:v2:{nonce}:{action_identity_digest}` and remains subject to
the existing freshness, source type, subject, content, revocation, retention,
permission, and blob-integrity checks.

The regression matrix proves that the exact request succeeds while query,
goal, scope, action, nonce, or binding changes fail closed. Expired, revoked,
and unreadable confirmation Evidence also fails closed.

The passing current-tree evidence is in
[`remediation.receipt.json`](remediation.receipt.json):

```text
execution: PASS
decision: FIXED
Product tree: f9d6f6ebf90712160441c3d57835131851ece12c945670cc607c225e22566344
```

The remediation contributes a `SCOPED PASS` for G7. It does not claim complete
G7 conformance.
