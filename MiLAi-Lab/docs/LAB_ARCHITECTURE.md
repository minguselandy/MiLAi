# MiLAi Lab architecture

Status: `ACTIVE_LAB_BASELINE`  
Version: `0.1`  
Date: `2026-09-01`

## Purpose

MiLAi Lab is a research consumer of MiLAi Product. The split removes experiment history,
benchmark harnesses, local model adapters, and generated receipts from the product
delivery repository.

```text
External benchmark or small fixture
              │
              ▼
      MiLAi Lab protocol
              │
      ┌───────┴────────┐
      │                │
      ▼                ▼
public pinned      Lab-owned method
MiLAi Product      or baseline
      │                │
      └───────┬────────┘
              ▼
      common result record
              ▼
      scorer and analysis
              ▼
 compact terminal artifacts
```

## One-way product dependency

The product does not import this repository. An official product arm is addressed by
`product.lock.json` and calls a published interface. The lock binds:

- product candidate version;
- selected behavior-bearing product tree paths;
- optional Git commit when one exists;
- each public interface path and digest.

The active package cannot import product Python modules. This is stricter than merely
avoiding private symbols: it prevents in-process shortcuts from silently becoming a
different product path. If a public Python client is later distributed as a versioned
artifact, it may be added as an explicit dependency in a successor Lab version.

## Experiment authority classes

| Kind | Execution boundary | Permitted conclusion |
| --- | --- | --- |
| `PRODUCT_BLACK_BOX` | pinned public product interface | product effect |
| `PRODUCT_TESTKIT` | published read-only testkit | engineering diagnosis |
| `RESEARCH_PROTOTYPE` | Lab-owned implementation | method prototype |
| `SIMULATION` | synthetic or surrogate | mechanism only |

Every active study declares one kind per arm. A mixed comparison does not promote the
lower-authority arm to product evidence.

## Active versus archived source

Only `src/milai_lab` is importable maintained infrastructure. Legacy source is copied
under `studies/archive/lifecycle/legacy_snapshot` with its relative paths and a manifest.
It is intentionally excluded from builds, active tests, and `sys.path`.

The archive is useful for causal history and porting. It is not a compatibility layer.
Reusable behavior must be rewritten against current Lab contracts and covered by active
tests before use.

## Data and artifact boundaries

Benchmark corpora and models remain external. `data/manifests` contains identities and
expected hashes; `data/fixtures` contains only small reviewable samples.

A normal run emits at most:

```text
run.json
cases.jsonl
metrics.json
terminal.json
events.jsonl       optional
```

Large traces and Provider payloads belong in external content-addressed storage. The
result index stores references rather than duplicating environments or inputs.

