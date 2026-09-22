# ADR-058: deterministic resolver language boundaries

Date: 2026-09-22

Status: accepted for local implementation; final-candidate verification and remote closure pending.

## Context

The frozen [3A-3D diagnosis](../revalidation/resolver-language/REVALIDATION.md) records
13 desired-behavior failures across two distinct owners: compatibility client typed
prefetch and Runtime query interpretation. No retrieval/exposure/model effect was
measured. The current query-first Host does not call the legacy typed resolver.

Unrestricted natural-language understanding is not an existing deterministic contract.
The Goal forbids fixture synonyms, gold terms, hidden retrieval, a model controller,
and unreviewed API/schema changes. The exact three-family aliases remain frozen by
`contracts/agent/v1/dg13u-u1-interface-freeze.md` and must still precede broader rules.

## Decision

Keep the existing interfaces, signatures, enums, reason codes and alias priority.

1. Preserve structured owner signals: Runtime `exact_target` and `EXPLICIT_READ`
   remain above automatic no-memory heuristics. No default Host route changes.
2. Normalize typed query matching with NFKC. Prefer literal known predicate/subject
   identifiers before lexical matching. Return original canonical field strings;
   matching normalization does not rewrite persisted identity or authorize a read.
3. Use Unicode key-derived terms, with Han substring matching where whitespace is
   not a word boundary and alphabetic boundaries elsewhere. Preserve lexical
   weights 6/2/1 and the existing action preference 8. Do not translate identifiers.
4. Treat distinct equal-scored or equal-address keys as unresolved, regardless of
   input order. A subject can qualify an otherwise ambiguous exact predicate.
   Duplicate identical keys do not create false ambiguity. An unrelated single
   known Claim does not resolve a mentioned ambiguous predicate.
5. Retry may reuse a compatible intent/address, never override a newly stated
   history/conflict/current need or different key. Preserve the prior route:
   repeating history must not turn L1 into L0, nor NONE into a retrieval route.
6. Reuse the existing Product bilingual intent vocabulary for minimal fallback.
   Standalone English/Chinese greeting/arithmetic and explicit Memory opt-out
   wording can classify no-memory. A greeting/arithmetic prefix followed by a
   Memory request must not suppress that request. These are interpretation
   heuristics, not an authorization or privacy-policy parser.

Client frozen aliases still precede those general heuristics. Runtime explicit reads
still override query-only no-memory wording. This work does not change either
compatibility promise. The query-only client shadow shares no-memory classification
but remains non-routing observability. Package independence is preserved; Runtime
does not acquire a dependency on the client or Lab to share a small regex.

## Remaining capabilities and evidence discipline

The same frozen corpus continues to test every original expectation. C06's undeclared
synonym interpretation and C21's Chinese-to-English predicate translation remain
unsatisfied; no expectation is weakened. C21 now safely requests L1 without inventing
an exact key. Do not add a datastore synonym or transplant the frozen alias vocabulary
to arbitrary subjects merely to make these examples green.

The debt remains OPEN. Partial improvement is not a completed resolver capability,
architecture PASS, or permission to drop these cases. Any later semantic extension
must be separately justified, general, bounded and compatible with the Goal; new
model/API authority is not implied. Historical diagnosis corpus/results/receipt remain
immutable, and a separate current-tree receipt must preserve the two failures.

## Impact and rollback

Product behavior changes only in the declared deterministic interpretation/matching
surfaces. No schema, migration, public payload, tool/route, Canonical, authorization,
RLS, persistence, retrieval scoring/budget, Provider or Lab policy change. Resolver
output remains a request that Runtime must authorize; it is not accepted truth.

Verification: original corpus, frozen alias compatibility, independent identifiers
and languages, key-order ambiguity, retry route/intent/key, no-memory whole-query
versus prefix, and structured Runtime precedence. First narrow tests/static checks;
one full composition only on the final material candidate, not intermediate edits.
No database test is needed for these pure functions; CI still owns package gates.

Rollback to pre-remediation source `87aa53c73ec0a67ff412923e2151c71def575130`
restores the diagnosed gaps. No database rollback or deployment is involved.
Runtime is CANDIDATE; Schema remains EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE.
