# Resolver language diagnosis plan

Work package: 3A-3D. PR #36 is merged as
`3eab81c9e1c23b07e3aead351cc3adfe423470c0`; full composition Run #63
`35685753906` passed all 17 jobs and main fast `35688151840` passed.
This diagnosis changes no Product behavior.

## Scope and interpretation

Freeze the 30 synthetic examples and recording method in a separate diagnosis
branch before their first execution. Expectations are desired diagnostic
behavior, not a claim that all natural-language interpretation is a public
contract. Preserve every actual result, including semantic failures and
reason-only differences; do not adjust expectations after observing outputs.

Two distinct owners must remain separate:

- `client_typed`: the public `DeterministicMemoryNeedResolver`; OpenWorker
  invokes it for compatibility prefetch, not the default query-first path.
  It owns typed intent, requested L0/L1/NONE route and an optional StateKey.
- `runtime_interpreter`: the current Runtime's pure query interpreter.
  It owns intent/requirement/retrieval-intent, not a selected StateKey or
  actual L0/L1 route. Record route as NOT_OWNED. An explicit read is a
  structured Memory request even when the query alone resembles a greeting;
  automatic prefetch is a separate input mode.

The query-only client shadow is not a routing owner and is not substituted
for either surface. No direct Runtime private imports enter Lab code.

## Corpus controls

All queries, keys and scopes are synthetic. No benchmark, formal pool,
historical experiment or private user material is consumed.

- English, Chinese, mixed language, full-width Unicode, paraphrase, synonym,
  short imperative, identifiers, exact state, history, conflict, retry,
  no-memory and ambiguous-key cases are represented.
- Neutral identifiers avoid relying exclusively on the existing hard-coded
  orchid-release aliases. The legacy/renamed pair diagnoses that dependency;
  it does not authorize additional fixture-specific aliases.
- The three exact alias families and their priority are frozen in
  `contracts/agent/v1/dg13u-u1-interface-freeze.md`. C20/C22 are compatibility
  controls. A renamed-key capability gap is not, by itself, a violation of
  that frozen contract or authority to remove its aliases. Keep desired
  diagnostic capability, current compatibility promises and architecture
  conformance separate in the report.
- Retry inputs use the actual prior result. If the prior case failed, report
  propagated failure rather than inventing a successful prior state.
- A new history request containing “again” should not blindly retain a prior
  current-state intent. Pure retry and changed intent are separate cases.
- Tied keys must not be arbitrarily treated as an exact address. The existing
  typed ambiguity exception is an accepted fail-closed alternative.
- The synonym case expects bounded recall, not an invented exact StateKey.

## Execution and evidence

Commit corpus and method first. Record exact commit, corpus/method/manifest
digests and Product executable identity. Use the installed editable Product
packages. A cached Lab environment may supply Python dependencies but must
not supply Lab source or private Lab helpers.

Run each surface once. The recorder's zero exit means collection completed;
`behavior_status`, counts and mismatched fields determine semantic status.
Unexpected collection errors must be retained and corrected as harness
errors, never silently counted as Product failures or passes.

Failure-family labels describe observed symptoms, not established causes.
In particular, FALSE_RECALL means unwanted resolver intent, not proof that a
retrieval or exposure occurred; runtime requirement differences are not
measured route changes. Source analysis may subsequently explain mechanisms,
but pure resolver evidence cannot prove real retrieval, model use or benefit.

No model, embedding, retrieval, database or provider call is part of this
diagnosis. No ranking/weight/budget, permission, schema, Canonical, default
routing or resolver implementation change is authorized by this package.

## Delivery boundary

Add the corpus, method, compact expected/actual evidence, scoped diagnosis
receipt, debt classification and current-status updates in the diagnosis PR.
Use only narrow harness verification and the affected fast CI path. Reuse
PR #36's final composition evidence for its unchanged behavior; do not start
another full historical replay merely for diagnosis metadata.

If failures are reproducible, record OPEN with owner/path/risk/next step.
Any remedy belongs in a separate admitted branch and follows the Goal's
priority: structured Host signal, exact StateKey, Unicode-normalized typed
matching, language-neutral lexical fallback, minimal regex fallback.
Do not add case IDs, gold terms or benchmark-specific synonyms. A desired
natural-language capability does not by itself justify an unbounded parser.

Schema remains EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE. Research allocations
and model requests remain zero.
