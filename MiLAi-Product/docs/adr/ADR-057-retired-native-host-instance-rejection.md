# ADR-057: Retired native Host instances cannot reactivate

- Status: Accepted for candidate implementation
- Date: 2026-09-22
- Schema / Canonical authority: unchanged

## Context

The [3A-2D diagnosis](../revalidation/host-continuity/REVALIDATION.md) reproduced
A/op-1 → B/op-2 → retired A/op-1. Replacing the native instance cleared replay
history, so the old instance was accepted again and caused duplicate MCP/Provider
work. This violates the process-local native graph boundary, not Runtime authority.

## Decision

Remember retired native instance IDs for the lifetime of `SameProcessTaskRegistry`.
Under its existing lock, reject a retired instance before any generation, session,
operation or Host graph/cache mutation. This precedes synchronous tool-continuation
handling, so an old tool result cannot revive the retired graph. A genuinely new
instance still starts a new generation; the active instance retains ordinary
continuation and duplicate rejection. Existing conflict/error mapping is unchanged.

The retirement set is process-local, not persistent Memory identity or a new truth
store. Its size follows the number of replaced Host instances during one Adapter
lifetime; entries must not be evicted while that lifetime is active. A new Adapter
starts a new registry and retains the existing independently rotated ingress
capability boundary. No caller can regain execution rights by returning to an old
instance within the live registry.

## Verification and compatibility

Remove the two strict XFAIL annotations, keep their original assertions, and retain
the immutable FAIL receipt. Verify rejection with old and fresh operations/sessions,
including tool-continuation requests; verify unchanged current graph and legitimate
later replacement. Actual Adapter rejection must occur before MCP/Provider calls.
Re-run the affected real Host restart/cache-miss paths on the new Product identity.
Create a separate remediation receipt and run full composition once for the final
candidate, not on intermediate edits.

No wire shape, migration, Runtime cache policy, permission, Canonical authority or
persistent memory behavior changes. The intentional compatibility change is rejection
of formerly accepted retired-instance requests. Rollback to `e760434` restores that
known replay defect; it does not modify persisted memory. Schema remains NO-GO.
