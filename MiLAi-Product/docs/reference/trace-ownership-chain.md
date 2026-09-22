# Same-execution owner trace probe

Status: `FRESH_CHAIN_PASS_CACHE_ORIGIN_NOT_PROVEN`, 2026-09-22. This is a bounded
engineering proof within 3B-1, not completion of that work package or a model-effect run.

## Executed path and result

The explicit Host observer delegates to the actual query-first Adapter and gateway,
real Unix-socket broker and `milai-mcp` subprocess, authenticated loopback HTTP Runtime,
and isolated PostgreSQL 16.14. One synthetic Evidence is captured through `/v1/evidence`
and projected by the real role-separated `milai-worker --once` CLI. Lab then joins the
owner exports from those exact invocations. No private Product imports are added to Lab.

Provider is a **controlled in-process fixture**, not vLLM, Qwen or an external service.
The gateway retains its normal budgets and settlement. Its model identifier is required
configuration only; the tokenizer is synthetic WordLevel. Neither is an inference claim.

| Observed case | Provider invocations | Exact-version exposure | Usage |
| --- | ---: | --- | --- |
| no memory and same-query repeat | 2 | none | fixture-known |
| required recall on empty tenant | 0 | none; Host abstains | no invocation |
| successful recall and explicit retry | 2 | one version each | fixture-known |
| failure before dispatch | 1 | prepared, not exposed | unknown |
| dispatched, response lost | 1 | one version | unknown |
| unknown transport state | 1 | exposure unknown | unknown |

All eight actual Runtime observations are fresh retrievals. The two repeats do **not**
prove a cache hit. All seven provider records retain `observable_use=UNKNOWN` and causal
attribution `NOT_ESTABLISHED`. Five joins are structurally COMPLETE; three are PARTIAL
because native response/usage or dispatch is unknown. Structural completeness is not
model use, accounting completeness, answer quality or general Product conformance.

Final execution: 8 Host attempts, 7 fixture invocations, 3.195 seconds. Known synthetic
usage is 20 input / 12 output units, with three unknown fixture usages; these are not
an actual token total. Real model requests/tokens and new experiment allocations are zero.
Runtime resolves may write audit/receipt records; no database-zero-write claim is made.
Owned Host/broker/MCP/HTTP processes exited. The dedicated PostgreSQL container was stopped;
its database and each run's artifacts are retained. Only the per-run synthetic bearer file
was removed after execution; no user credential or historical artifact was deleted.

## Identity and artifacts

- Exact source commit (Product plus Lab method):
  `717da6e74aba02e296e30ac4f037c208b753ab18`.
- Product: 425 files; tree
  `90a900fef01ccca5b54cc4a558e3c530cf7a8b421f859d764761a8d6c4f75511`;
  manifest SHA `668dc365f1fb4cf8c6961e6fb490e1a1a6b18f47592c2c096af34b88f350f729`.
- Run-specific Product lock digest:
  `94d20026ace278e7642fd88bb393b26dc4e58d7c6bd813c351e1d5b7a4776ba0`.
  The independent-Product Git field is null in this monorepo; the runner separately
  verifies and records the exact containing commit, clean Product/method paths, manifest
  and public-interface hashes. It also checks installed CLI import locations.
- Final external root:
  `/cra/memory/mx_memory/evidence/post-cleanup-3b1-chain-20260922-r4`.
- `owner-facts.json` SHA:
  `7bd46d1b81d6a8ce5775f135d5e4b359ccb15ee1aedb113d4c066aefad960ddf`.
- `joined.json` SHA:
  `3662d2d16b1f3d35dcb339bb48fddd8534b0c6cb29c0ad50bf52043523d37336`.
- `summary.json` SHA:
  `491cbe3f97fb2dce6e54976c364ed34e6dc9701308ed0dea8c8698b4e970b296`.

The run manifest binds runner, owner assembler and joiner source hashes, input hash,
finite ceilings and the synthetic Provider profile. Private artifacts stay outside Git;
legacy Host traces are not relabeled safe to publish. Earlier r1/r2 collection probes and
r3 interim join are preserved. They exposed the missing HIT/ABSENT export vocabulary and
the need to bind the complete Lab method, not only the runner hash. No old evidence changed.

## Reproduction and narrow validation

The caller must provide an already migrated, isolated synthetic database and its
`MILAI_TEST_API_DATABASE_URL`, `MILAI_TEST_STEWARD_DATABASE_URL` and
`MILAI_TEST_WORKER_DATABASE_URL`. Do not use public/shared personal-data services.
From the monorepo root, use a new output path and exact committed source identity:

```bash
uv run --frozen --offline --project MiLAi-Lab \
  --with-editable MiLAi-Product/runtime \
  --with-editable MiLAi-Product/integrations/python-client \
  --with-editable MiLAi-Product/integrations/openworker-mcp \
  python MiLAi-Lab/tools/run_trace_ownership_probe.py \
  --product-root MiLAi-Product \
  --product-commit 717da6e74aba02e296e30ac4f037c208b753ab18 \
  --output /path/to/new-private-run
```

The program rejects dirty Product/method source and existing output directories. Ceilings
are 8 Host attempts, 8 fixture invocations and 120 seconds. The final database endpoint was
`127.0.0.1:32792`, database `milai_worker_once`, migration `0056_host_notes`; its random
published port is not a future configuration default.

Adjacent checks, each from its package root:

```text
Runtime:    .venv/bin/pytest -q tests/unit/test_observed_runtime.py --tb=short
            10 passed; changed-module Ruff/mypy passed
OpenWorker: .venv/bin/pytest -q tests/test_trace_testkit.py --tb=short
            12 passed; changed-module Ruff/mypy passed
Lab:        .venv/bin/pytest -q tests/unit/test_owner_exports.py tests/unit/test_trace_join.py --tb=short
            47 passed; changed-module Ruff/mypy passed
Lab:        .venv/bin/pytest -q tests/contract/test_active_tools_boundary.py --tb=short
            5 passed; both import boundaries passed
```

An initial new assertion used a nonexistent legacy event key (`reader_context_sha256`
instead of `context_sha256`); only the assertion was corrected. Initial formatting and
inventory-line findings were repaired. System Python lacks `tomllib`; the generated
Conformance command uses the existing Runtime Python environment. Package-wide checks
are delegated to path-classified fast CI. No full composition, historical replay or
unrelated PostgreSQL suite is repeated for this additive observation work.

## Contract and remaining limits

`ObservedRuntime` accepts only synthetic test settings and deterministic-hash embeddings.
It observes the actual `/v1/memory/resolve` response and repository execution without extra
retrievals. `reader_gate` is a Runtime-owned projection of the released informational
Context; it is not typed completeness or a new authorization decision. Unknown shapes stay
UNKNOWN and the assembler rejects them. Export errors leave the HTTP result unchanged and
emit only fixed safe gap codes.

The Host binds actual MCP invocation IDs, Runtime trace refs, ordered Evidence refs and
Context SHA to the exact framed system content in a Provider request. Prepared Context
is distinct from known dispatch. Unexpected transport errors preserve UNKNOWN, not a
known empty exposure; no cache provenance is guessed from equal payload hashes.

The Lab assembler currently admits only complete fresh informational Evidence exports.
It rejects cache reuse and incomplete versions. Before 3B-1 closes: implement and prove
cache-origin/reauthorization semantics (including version provenance), complete remaining
owner-path/neutrality evidence, and issue the scoped Product debt closure. Canonical Claim
versions, streams and concurrent observations are not covered here. Before 3B-2 closes:
generate its real opportunity ledger; this probe is not that ledger or a mechanism study.

No Runtime route, public MCP tool, schema, migration, permission, Canonical mutation rule,
retrieval default, ranking, threshold, budget or Prompt policy changes. Rollback is a source
revert to main `6f5ecf6132e81585509d5124cab55e51cc7754f7`; no database rollback is required.
Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
