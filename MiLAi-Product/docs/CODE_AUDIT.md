# MiLAi Product Code Audit

> Audit date: 2026-09-01  
> Source: `/cra/memory/mx_memory/MiLAi`  
> Target: `/cra/memory/mx_memory/MiLAi-Product`  
> Method: copy-first, no legacy mutation

## 1. Outcome

The mixed legacy workspace contained usable product code, extensive experimental code, generated
artifacts, caches, model environments, and years of Goal/receipt history in one mostly untracked
tree. The Product split keeps the working product closure while removing the obvious repository
weight and preventing new Product-to-Lab imports.

Initial target after mechanical copy was 502 files and 7.9 MiB before adding frozen architecture
evidence closure and authored product documentation. The source workspace's large `var`, virtual
environments, build output, logs, wheelhouse, benchmark harnesses, and root experiment runners were
not copied.

## 2. Product assets retained

- `runtime/src/milai`: complete current Runtime source closure;
- `runtime/tests`: product tests except two DG22 unit tests that imported `evals` directly;
- `runtime/migrations/versions/0001_*` through `0049_*`;
- Runtime configuration, Docker, Compose, Alembic, locks, and operations files;
- all six integration package sources, locks, tests, and packaging metadata;
- frozen `architecture/v1.0` and the repo-relative evidence needed by its crosswalk validator;
- Agent contracts, examples, product ADRs, security notes, and operational runbooks.

The OpenWorker provider-fault test that imported a legacy root `scripts` fixture was removed from
the Product copy. Existing gateway unit coverage remains; the removed network-fault fixture belongs
in Lab unless its helper is later promoted into a package-owned test utility.

## 3. Assets deliberately excluded

```text
.git and legacy Git state
.venv and package-local environments
__pycache__, pytest/mypy/ruff caches
var, runtime data, checkpoints and model files
dist, build, wheelhouse and stale wheels
backups and logs
.env and credentials
root evals, research, scripts and tests
Goal/Master history and benchmark receipts
profile and refinement outputs
```

Exception: a small set of historical reports/reviews and candidate architecture artifacts is
retained because the frozen architecture crosswalk uses those exact repo-relative identities. This
is validation evidence, not active experiment code.

## 4. Runtime entry points

| Entry point | Implementation | Purpose |
| --- | --- | --- |
| `milai-api` | `milai.api.cli:main` | loopback Flask/Waitress API |
| `milai-worker` | `milai.workers.main:main` | projection, purge and background jobs |
| `milai-db-check` | `milai.persistence.cli:main` | database connectivity/role check |
| `milai-ops` | `milai.operations.cli:main` | init/doctor/start/stop/smoke/backup operations |
| `milai-mcp` | `milai_mcp.server:main` | authenticated Streamable HTTP MCP; loopback default and stdio compatibility |
| `milai-codex-user` | `milai_mcp.remote_registration:main` | issue/list/revoke JSON-only remote Host credentials; automatic first-use audit |
| `milai-oauth-user` | `milai_mcp.oauth_admin:main` | issue/list/revoke one-time OAuth user enrollments; token-free Codex client onboarding |
| `milai-mcp-broker` | `milai_openworker_mcp.broker:main` | host-owned MCP child broker |
| `milai-mcp-relay` | `milai_openworker_mcp.relay:main` | read-only Worker socket relay |
| `milai-openworker-adapter` | `milai_openworker_mcp.host_adapter:main` | OpenWorker Host integration |

## 5. Structural findings

### Eager import closure

Importing `milai.api.app` in the source workspace loaded roughly 128 `milai.*` modules; importing
the worker loaded roughly 119. The main causes are eager barrel exports in:

```text
milai.application.__init__
milai.domain.__init__
milai.adapters.__init__
```

This makes a premature physical split of stable and experimental Runtime modules risky. The Product
therefore copies the full Runtime source first. A later narrow refactor should make API/worker
composition roots import explicit interfaces.

### Oversized orchestration modules

Largest audited source files included:

```text
application/retrieval.py                  ~4,230 lines
application/memory_context.py             ~2,559 lines
application/query_operators.py            ~1,937 lines
application/evidence_acquisition.py       ~1,716 lines
application/evidence_semantics.py         ~1,537 lines
persistence/retrieval_repository.py       ~1,495 lines
application/memory_query.py               ~1,483 lines
observability/retrieval_audit.py           ~1,263 lines
```

`RetrievalService` combines baseline product behavior, multiple historical DG strategies,
Formation canaries, typed operators, and audit/replay concerns. This is the largest maintenance and
test-selection cost in Product.

The copied tree also has pre-existing formatter drift: the current locked Ruff formatter reports
122 Runtime files and six OpenWorker package files that would be reformatted. The split does not
create a broad mechanical formatting diff. Product CI enforces Ruff lint and strict mypy where the
package configures it; repository-wide format normalization is deferred to a dedicated maintenance
commit.

Recommended extraction order:

```text
stable query/recollection facade
→ candidate generation ports
→ governance/hydration boundary
→ EvidenceSet selector
→ lookup/strict readiness
→ trace observer
```

Do not rewrite these modules in one change.

The HC-4 Chain-D maintenance work completed only the first step. A query-only
`application.recollection.RecollectionFacade` now owns the structural `retrieve` boundary and the
execution/replay value types; legacy imports remain identical, concrete trace/status and testkit
access stay on `RetrievalService`, and the application barrel resolves its existing 48 exports
lazily. Importing the facade loads two application modules rather than the prior 63. The final
fresh-PostgreSQL Runtime gate passed 912 tests with one declared optional cross-package skip. No
candidate-generation or policy logic moved. The next extraction, when separately authorized,
remains candidate-generation ports.

### Test coupling

Three copied tests had direct Lab dependencies:

- `runtime/tests/unit/test_dg22_accuracy_acquisition.py` → `evals.dg22`;
- `runtime/tests/unit/test_dg22_temporal_applicability.py` → `evals.dg22`;
- one OpenWorker provider-fault fixture → `scripts.dg13u_u1_provider_fault`.

The two DG22 files were excluded during copy; the single script-coupled OpenWorker test was removed
from its otherwise product-owned test module. Product CI adds an AST import-boundary check to prevent
regression.

One remaining OpenWorker test referenced a tokenizer below the excluded legacy `runtime/var`
model cache. It now creates a minimal exact tokenizer in its own temporary test directory; Product
does not copy private model artifacts merely to satisfy a test.

One compatibility-only `test_sufficiency.py` wrapper imported tests through the legacy repository
package name and contained no unique assertions; it was removed while retaining its underlying
`test_dg17_sufficiency.py` tests. The Agent contract test's direct PyYAML dependency is now declared
in the Runtime development group instead of relying on an optional embedding dependency.

### Packaging

The legacy Runtime `dist` wheel was stale and was not copied. Product builds from current source.
The OpenWorker wheel already packages only `src/milai_openworker_mcp`; an explicit sdist exclusion
now prevents `.venv`, caches, `dist`, `build`, and `wheelhouse` from entering source artifacts.

### Documentation drift

The copied Runtime README named migration 0032 as head while the repository contains 0049. Product
README now names `0049_namespace_cleanup_terminal_counts` and lists all six adapters.

## 6. Database and product risks

- Fifty migrations are now part of product compatibility and must remain ordered; migration 0050
  adds the Host cognitive working-state plane after this repository-split audit.
- Some downgrade paths are intentionally unavailable; operational rollback relies on backup/restore
  and forward repair rather than destructive schema history rewriting.
- A clean current-head PostgreSQL run is still required after the split.
- Worker lease loss dominated a prior large benchmark run; worker recovery is a product reliability
  priority before a new quality claim.
- The Source workspace contained no project `LICENSE`; redistribution and external release remain
  unresolved.
- The OpenWorker base image license/source identity is unresolved, so images remain local-only.
- Personal data requires encryption/key-recovery and deletion-propagation validation.

## 7. Migration risk for the repository split

| Risk | Mitigation |
| --- | --- |
| hidden relative path to legacy root | Product import-boundary scan and package builds |
| architecture validator missing crosswalk evidence | copied exact repo-relative evidence; validator run |
| stale built artifact | excluded all `dist`; rebuild in Product |
| wheelhouse or secret leak | explicit copy excludes, `.gitignore`, sdist excludes, artifact inspection |
| experiment code silently becoming product | default-off status retained; Product goals require explicit admission |
| source provenance ambiguity | legacy path retained; Product manifest records source and public surfaces |
| broad refactor breaks behavior during split | copy full source closure first; decouple incrementally |

## 8. Recommended next audit depth

Do not recreate the legacy audit burden. The next useful checks are operational:

1. clean install and build every package;
2. current-head PostgreSQL tests with real roles;
3. `milai-ops init/doctor/start/smoke/stop` on an isolated local database;
4. MCP/OpenWorker local end-to-end smoke;
5. artifact content scan;
6. only then a repaired, identity-correct memory-quality benchmark in Lab.
