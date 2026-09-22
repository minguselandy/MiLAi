# 3A-3D Resolver language diagnosis

Decision: **OPEN / diagnostic FAIL**, 2026-09-22. No Product implementation change.
Frozen corpus and recorder: commit `6f9e34efe6399792b44fc0d51438c742e6e5a1c0`,
Git tree `8f799ab7f094600c8331582f521d8d684f900254`. Product identity remains
425 files, tree `08cd98fea12383fd26cf3f10b39bc04ffea23da2271f45ebe55c772a57ecafe2`;
manifest SHA `44be5e2e93837dcc75b996140f06b10e6142dc34e6a5718a894f79574ddfd352`.

[Plan](DIAGNOSIS_PLAN.md), [frozen corpus](corpus.json), [expected/actual results](results.json),
[scoped receipt](receipt.json). Corpus SHA
`38687d06bb94d25c66977c8c58013c4f6f2974f7826e5e2061eb653ae622d702`;
method SHA `c7758d085f4a2630a67096f621997afd8cfb5f7e9c37a531468ccc47d300b81a`.
Expectations were committed before first execution and were not rewritten afterward.

## Results and ownership

| Surface | Desired-behavior PASS | FAIL | Actual owner/path |
| --- | ---: | ---: | --- |
| Client typed resolver | 11 | 11 | `milai_client.memory_need`, OpenWorker compatibility `memory_mode=prefetch` |
| Runtime interpreter | 6 | 2 | `milai.application.memory_resolve`, current query-first interpretation |

The client query-only shadow does not choose a production route. Runtime interpretation owns
intent/requirement/retrieval-intent, not StateKey selection or an L0/L1 route; those fields remain
`NOT_OWNED`/null. The legacy typed failures are not evidence that the current query-first path
shares them. All 30 expected/actual intent, route, key and reason records are retained.
One C17 reason-only difference (`NO_TYPED_MEMORY_INTENT` versus `NO_MEMORY_DEPENDENCY`) has
the same NONE intent/route/key and is informational, not a fourteenth semantic failure.

| Cases | Observed gap | Source explanation and limit |
| --- | --- | --- |
| C02/C04/C08/C10/C12 | Chinese/full-width typed needs become NONE | General client intent regexes are English and lexical tokens are ASCII; NFKC currently applies only to aliases. |
| C06 | Synonym query becomes NONE | Desired bounded recall is absent; no synonym-based exact key was demanded. This does not authorize fixture synonyms. |
| C14 | Chinese retry remains NONE | Actual previous C02 was already NONE; propagation is observed, independent retry failure is not isolated. |
| C15 | Explicit history + “again” reuses CURRENT_STATE/L0 | Generic retry precedes explicit new intent. C09 and C13 are separate history/pure-retry controls. |
| C18 | Definition/no-personal-memory request becomes CURRENT_STATE/L0 | A database keyword is sufficient; no actual retrieval or exposure was executed. |
| C19 | Tied keys choose north as an exact address | Lexical score ties use canonical JSON order instead of preserving ambiguity. C22's exact-alias ambiguity still rejects. |
| C21 versus C20 | Renamed identifier loses Chinese alias behavior | Existing alias family is intentionally frozen; this measures capability dependence, not a violation of the alias contract. |
| R03/R04 versus R02 | Chinese automatic greeting/arithmetic remain POSSIBLE/SEARCH | Runtime no-memory regex is English. This is unresolved prefetch opportunity, not proof of a retrieval, exposure or model-use event. |

Failure families in the result are diagnostic symptoms and can overlap. Runtime `WRONG_ROUTE`
labels a requirement mismatch under the shared taxonomy, not a measured routing decision.
`FALSE_RECALL` likewise describes intent versus expectation, not an observed retrieval count.
The scoped G7 FAIL does not declare broad architecture DEVIATION; conformance remains UNVERIFIED.

## Execution

From repository root at the frozen source commit, with a new output path:

```bash
MiLAi-Product/integrations/python-client/.venv/bin/python MiLAi-Product/tools/run_resolver_language_diagnostic.py --corpus MiLAi-Product/docs/revalidation/resolver-language/corpus.json --product-root MiLAi-Product --product-commit 6f9e34efe6399792b44fc0d51438c742e6e5a1c0 --surface client_typed --output <new-private-client.json>
uv run --frozen --offline --project MiLAi-Lab --with-editable MiLAi-Product/runtime --with-editable MiLAi-Product/integrations/python-client python MiLAi-Product/tools/run_resolver_language_diagnostic.py --corpus MiLAi-Product/docs/revalidation/resolver-language/corpus.json --product-root MiLAi-Product --product-commit 6f9e34efe6399792b44fc0d51438c742e6e5a1c0 --surface runtime_interpreter --output <new-private-runtime.json>
```

Each recorder completed with exit 0 and explicit `behavior_status=FAIL`; collection success is
not behavioral success. Lab is only a cached Python 3.11 dependency environment for the second
command; no Lab source/private helper is imported. Zero model/embedding/retrieval calls, database
connections, Provider requests, tokens or experiment allocations. No formal or historical pool.

After primary collection, two parameterized Product-owned tests preserve all 30 expectations.
Known failures use `xfail(strict=True, raises=AssertionError)`; unexpected success fails CI and
unexpected collection exceptions are not hidden. Narrow checks:

```bash
MiLAi-Product/integrations/python-client/.venv/bin/pytest -q MiLAi-Product/integrations/python-client/tests/test_resolver_language_diagnosis.py --tb=short
# 11 PASS / 11 strict XFAIL, 0.24 s
uv run --frozen --offline --project MiLAi-Lab --with-editable MiLAi-Product/runtime --with-editable MiLAi-Product/integrations/python-client python -m pytest -q MiLAi-Product/runtime/tests/unit/test_resolver_language_diagnosis.py --tb=short
# 6 PASS / 2 strict XFAIL, 0.89 s
```

Add `--runxfail` to reproduce raw desired-behavior assertion failures. These annotations were
added after collection and do not modify the immutable expected/actual result or corpus.
Changed-file Ruff passes. No full suite, PostgreSQL test or historical replay is repeated locally.
Affected package verification belongs to fast CI; no full-composition label for this diagnosis.
Receipt verification passes: 19 receipts, 2 current, 3 current scoped claims, 5 preserved
diagnostic failures and 1 current failure. Generated conformance remains `9/35/0`, UNVERIFIED.
Two initial verifier launcher errors (`python` absent; system `python3` lacks `tomllib`)
were environment errors, not Product diagnostics; the existing client virtualenv ran the
verifier successfully. No diagnosis was rerun or relabeled because of these errors.

## Next step and limits

Owner: Product Python client deterministic need resolver and Runtime query interpreter.
Risk: compatibility prefetch language misses, stale intent carry-over, arbitrary exact-key choice,
and unnecessary automatic probing. These pure functions do not establish authority bypass,
Canonical mutation, retrieval quality, model use, efficacy or production readiness.

After diagnostic remote closure, use a separate `fix/resolver-typed-language-boundaries` branch
and separate remediation receipt. Follow the Goal's structured signal → exact key → Unicode
typed matching → language-neutral lexical fallback → minimal regex priority. Preserve frozen
aliases. Do not tune weights/budgets, add case/gold terms, introduce hidden retrieval or a model
controller, or broaden this into an unbounded natural-language parser. Any public API/schema/
authority change needs separate authorization under the Goal.

Remote closure remains pending for this diagnosis. PR #36/full #63/main fast `35688151840`
already closed the unchanged Host repair; its historical receipts are not rewritten.
Rollback is the parent `3eab81c`; this diagnostic PR adds no behavior to roll back and no migration.
Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
