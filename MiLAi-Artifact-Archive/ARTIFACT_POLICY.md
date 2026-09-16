# Artifact Policy

## Purpose

The archive separates experimental evidence retention from both the MiLAi
Product source tree and the MiLAi Lab source tree. It keeps large historical
outputs addressable without making either future repository dirty or slow.

## Initial storage model

The initial archive is **index-backed**:

1. authoritative control artifacts remain at their absolute legacy paths;
2. the catalog records logical run, role, reported status, byte length,
   modification time and SHA-256;
3. large raw payloads, databases, model caches and environments are not copied;
4. a missing legacy path or hash mismatch is a validation failure, not an
   invitation to silently rewrite the catalog.

## Catalog inclusion

The control-artifact catalog includes JSON/JSONL files whose names identify
receipts, terminals, run locks, results, manifests, summaries, decisions,
ledgers or failure indexes beneath legacy `var/`.

Raw contexts, answers, model responses, databases and checkpoint payloads are
excluded unless their filename also satisfies the control-artifact rule. Their
parent run remains discoverable through the indexed receipt/manifest.

## Source classification

Every retained source/configuration/document file is classified at file
granularity and SHA-256 hashed. Large generated or external dependency trees
are represented by aggregate directory records. Categories are:

- `product`: runtime, all six current integrations (python-client, MCP,
  OpenWorker-MCP, hooks, LangGraph and AutoGen), contracts, frozen architecture
  and operational documentation intended for the product repository;
- `lab`: evaluation, benchmark, research and experiment harness sources;
- `archive`: historical goals, reviews, superseded architecture candidates and
  run artifacts retained as evidence;
- `generated`: caches, logs, build outputs, databases, projections and other
  reproducible or operational outputs;
- `external`: virtual environments, wheelhouses and third-party tool material.

Classification is migration guidance, not proof that a file is production
ready. Ambiguous root documents default to `archive` rather than silently
entering Product.

## Secrets and private data

- `.env` files are metadata-only entries: size and mode are recorded, content
  hashes are intentionally omitted.
- no runtime database, content blob, credential, token, model cache or private
  memory payload is copied here;
- preserved user work is limited to the two explicitly identified tracked
  source/test files and their Git diff;
- future byte migration requires a separate access-controlled storage plan.

## User modifications

Pre-existing modifications are preserved before any split:

- current exact snapshots;
- `HEAD` base snapshots;
- one `git diff --binary` patch;
- a manifest binding all copies by SHA-256 and file mode.

These files remain user-owned. The archive does not merge, reset, stage or
commit them in the legacy repository.

## Immutability and correction

Catalog records are snapshot evidence. After a snapshot is cited or committed,
corrections create a new version; they do not overwrite the old catalog.
Validation never updates a digest automatically.

## Repository policy

This catalog repository may be initialized as Git, but generation does not
stage or commit anything. Large artifact bytes remain outside Git. Product and
Lab may reference catalog identities but must not depend on the legacy path at
runtime.
