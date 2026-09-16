# MiLAi

MiLAi is an experimental, governed memory system for agent applications. The
current repository contains the Lean V1 architecture, contracts, runtime,
agent integrations, evaluation harnesses, research utilities, tests, and the
development records that define their boundaries.

## Repository layout

- `architecture/` — frozen architecture bundles and validators.
- `contracts/` — agent, MCP, OpenWorker, and API contracts.
- `runtime/` — experimental Flask/PostgreSQL runtime, migrations, and runtime tests.
- `integrations/` — Python client, MCP, OpenWorker, LangGraph, AutoGen, and hooks integrations.
- `evals/` — evaluation protocols, fixtures, scorers, and benchmark adapters.
- `research/` — isolated research implementations and harnesses.
- `examples/` — integration examples.
- `scripts/` — experiment, validation, packaging, and audit utilities.
- `tests/` — cross-component and experiment-level tests.
- `docs/` — ADRs, runbooks, reports, reviews, contracts, and release records.

## Included first-party bundles

- `MiLAi-Product/` — deployable product tree, product contracts, runtime, and integrations.
- `MiLAi-Lab/` — independent research, evaluation, and benchmarking tree.
- `MiLAi-Artifact-Archive/` — index-backed archive catalog and preservation tools for legacy artifacts.

These bundles are included as ordinary directories in this monorepo. Their original
`.git` metadata is intentionally omitted; the surrounding `mx_memory` workspace and
all unrelated repository checkouts remain outside this repository.

## Local setup

This project uses `uv` for dependency management. The repository intentionally
tracks each component's `pyproject.toml` and `uv.lock`, but does not track local
virtual environments, uv caches, downloaded models, wheelhouses, logs, runtime
state, or generated experiment output.

For the runtime:

```bash
cd runtime
cp .env.example .env
# Edit .env with local PostgreSQL credentials.
uv sync --frozen --dev --python 3.11
uv run pytest -q
```

For an integration package, run the same commands from its directory, for
example `integrations/python-client` or `integrations/mcp`.

## Scope and provenance

The parent `mx_memory` directory is a working area containing multiple
independent repositories and local experiment environments. This repository
publishes the MiLAi core together with the three first-party bundles listed
above. Third-party checkouts and unrelated sibling working copies are
deliberately kept outside this Git history.

See `AGENTS.md`, `MANIFEST.md`, and the Lean V1 design/implementation documents
for the current execution boundaries and evidence policy.
