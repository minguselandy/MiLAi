# MiLAi Lab agent instructions

## Scope

This repository owns experiments, evaluation contracts, benchmark adapters, scoring,
analysis, and historical research source. It does not own MiLAi product behavior or
canonical memory state.

## Hard boundaries

1. `src/milai_lab` must never import `milai`, `milai_client`, `evals`, `scripts`, or any
   legacy source module.
2. A `PRODUCT_BLACK_BOX` arm uses only interfaces pinned by `product.lock.json`.
3. A `PRODUCT_TESTKIT` arm may use only a separately published public testkit or
   read-only trace contract. Private product helpers remain forbidden.
4. `RESEARCH_PROTOTYPE` and `SIMULATION` results must not be described as product
   behavior.
5. Benchmark corpora, model weights, venvs, caches, raw Provider transcripts, and run
   artifacts stay outside Git. Git stores manifests and compact terminal results.
6. Archived code is historical evidence, not an active dependency. Do not add archive
   paths to `sys.path`.
7. The Lab never writes canonical product tables directly. Stateful product experiments
   use isolated instances through published interfaces.
8. Preserve failed experimental evidence, but prefer one compact failure record over
   duplicating environments or source trees per attempt.

## Efficient development

- Start with the smallest falsifiable slice, then scale only after execution validity.
- Fail a case, not the whole development program, when a local repair is safe and
  generalizable.
- Diagnose infrastructure failures separately from semantic misses.
- Do not add case IDs, gold terms, benchmark-specific synonyms, or post-outcome routing.
- Use parallel execution only within declared service and database capacity.
- Keep product and research claims tied to the declared `ExperimentArmKind`.

## Required checks

Before handoff, run:

```bash
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

The product pin verifier is required before any product-backed effect run.

