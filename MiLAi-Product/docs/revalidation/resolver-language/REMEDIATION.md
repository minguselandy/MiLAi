# 3A-3R deterministic resolver remediation — partial, debt OPEN

Source: `9b4aa1670dc75dfc2149baeb75719f017267e92a`, Git tree
`3821a0d35cfd7a3092a060f807feb0bdaf1a8198`. Product: 425 files, tree
`847967d2e212b974d92b0b08d6e0f8b135a3c1080adf61790dcb771b9c832311`;
manifest SHA `016df6085fc29d9c201c3f22739397e4f82af128152020318bc2ce4647814096`.

[ADR-058](../../adr/ADR-058-deterministic-resolver-language-boundaries.md),
[separate current-tree receipt](remediation.receipt.json),
[new expected/actual results](remediation.results.json).
The [original diagnostic result](REVALIDATION.md), corpus, method and receipt are unchanged.

## What changed

Client compatibility prefetch now normalizes typed queries with NFKC, matches actual known
predicate/subject identifiers before lexical fallback, and derives Unicode matching terms
from those keys. It never translates a key or rewrites canonical field strings. Existing
weights 6/2/1 and action preference 8 are unchanged. Equal distinct addresses/scores remain
unresolved rather than being selected by JSON ordering; duplicate identical keys do not
cause false ambiguity, and an unrelated known Claim cannot resolve an ambiguous predicate.

Retry must agree with a newly expressed intent/key and preserves the prior route. A repeated
history read stays L1 and NONE stays NONE. Minimal bilingual intent fallback reuses existing
Product vocabulary. Client/Runtime distinguish a standalone greeting/arithmetic request from
one followed by a Memory request, and recognize bounded explicit Memory opt-out wording.

Frozen aliases still precede broader client rules. Runtime structured exact targets and
explicit reads still precede automatic no-memory heuristics. Lexical wording is not an
authorization/privacy-policy parser. Client shadow observability shares the no-memory regex
but does not select a route; current query-first Host still does not call the typed resolver.

## Same-corpus results, with remaining failures

| Owner | Diagnosis | Partial repair |
| --- | --- | --- |
| Client typed resolver | 11 PASS / 11 FAIL | 20 PASS / 2 FAIL |
| Runtime interpreter | 6 PASS / 2 FAIL | 8 PASS / 0 FAIL |

All 30 expectations remain identical: corpus SHA
`38687d06bb94d25c66977c8c58013c4f6f2974f7826e5e2061eb653ae622d702`.
The same recording method SHA is
`c7758d085f4a2630a67096f621997afd8cfb5f7e9c37a531468ccc47d300b81a`.

- C06 still returns NONE rather than inferring a current-state request from an undeclared
  synonym. No datastore/presently fixture synonym was added.
- C21 improves from NONE to CURRENT_STATE/L1, but still cannot translate Chinese wording
  to the demanded English predicate. Safe broad recall is not relabeled as exact success.
- Both remain strict XFAIL in the original test. No case or expectation was deleted or
  weakened. This is partial remediation, not a completed resolver language capability.

The debt stays OPEN with a FAIL receipt and a scoped G7 limitation. No actual retrieval,
Context exposure, authorization bypass, model use or efficacy was measured. A future semantic
extension must have a separate general bounded design; this work authorizes no model, new
public API/schema, translation dictionary, hidden retrieval or fixture-specific rules.

## Verification performed

From repository root:

```bash
MiLAi-Product/integrations/python-client/.venv/bin/pytest -q MiLAi-Product/integrations/python-client/tests/test_memory_need.py MiLAi-Product/integrations/python-client/tests/test_resolver_language_remediation.py MiLAi-Product/integrations/python-client/tests/test_resolver_language_diagnosis.py --tb=short
# 64 PASS / 2 strict XFAIL, 0.33 s
uv run --frozen --offline --project MiLAi-Lab --with-editable MiLAi-Product/runtime --with-editable MiLAi-Product/integrations/python-client python -m pytest -q MiLAi-Product/runtime/tests/unit/test_resolver_language_remediation.py MiLAi-Product/runtime/tests/unit/test_memory_resolve.py MiLAi-Product/runtime/tests/unit/test_resolver_language_diagnosis.py --runxfail --tb=short
# 49 PASS, 1.02 s; the repaired Runtime cases are no longer annotated XFAIL
```

Independent controls use different identifiers, Cyrillic/accented/Han/full-width text,
input-order permutations, duplicate keys, unrelated Claim fallback, changed retry key/intent,
history/NONE route retention, and structured Runtime precedence. Original aliases still pass.
Changed-file Ruff and mypy for each changed source module pass. Initial Ruff complaints
about deliberate Unicode test glyphs were formatting/lint issues, not behavioral evidence;
the initial raw desired-behavior run preserved C06/C21 as failures.

The recorder ran once per owner at the frozen source above, using the commands in
[REVALIDATION.md](REVALIDATION.md#execution) with `--product-commit` replaced by
`9b4aa1670dc75dfc2149baeb75719f017267e92a` and fresh output paths. Client collection exits
0 with behavioral FAIL; Runtime collection is PASS. Full exact identities and external
artifact hashes are in the separate receipt. Lab supplies a cached dependency environment
only; no Lab source is imported. Models/embeddings/retrieval/DB/Provider calls and tokens 0.
The earlier `a7fe051` local collection is retained outside Git as `client.json`/`runtime.json`
in the same evidence directory. Final `*-final.json` collection binds the subsequent
mixed-script boundary fix; neither primary diagnostic nor earlier local evidence was overwritten.

No local full-suite or historical replay duplicate. No persistence/authority behavior was
changed, so pure-function tests are the relevant local evidence. Affected package checks go
to fast CI; one full composition is required on the final material candidate. Remote/full
closure remains pending and the work package remains IN_PROGRESS, not PASS.

No schema/API/permission/Canonical/migration or Provider budget change. No research resumed.
Rollback source: `87aa53c73ec0a67ff412923e2151c71def575130`; no database rollback.
Schema remains EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE.
