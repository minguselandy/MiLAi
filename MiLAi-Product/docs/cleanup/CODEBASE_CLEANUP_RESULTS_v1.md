# MiLAi codebase cleanup results v1

## Outcome

The behavior-preserving cleanup program completed its structural implementation through C8 and
refreshed all five current-tree behavior receipts in C9. This document is the C10 final-candidate
record; the final 17-job composition fields remain `PENDING` until the exact PR candidate runs.

Baseline commit: `798b7cac21957873791afff6122d3f06a82214c5`  
Final implementation commit: `432153a0065f6ccc6706d670ba7eafafc002c950`  
Current evidence commit: `2803763f47eb846e7c7de68d96758cf23921dcd7`
Final baseline content commit: `8f179a76166a9506b4fd9d4688478dd498749dc1`

## Hotspot changes

| Compatibility/owner file | Baseline bytes | Current bytes | Current lines | Result |
| --- | ---: | ---: | ---: | --- |
| `runtime/src/milai/application/retrieval.py` | 195,742 | 113,883 | 2,407 | responsibility seams moved to `retrieval_core/` |
| `runtime/src/milai/application/memory_context.py` | 153,970 | 10,266 | 268 | compatibility facade over `memory_context_core/` |
| `integrations/mcp/src/milai_mcp/server.py` | 178,277 | 5,065 | 123 | compatibility facade over seven `server_*` owners |
| `integrations/openworker-mcp/src/milai_openworker_mcp/host/orchestrator.py` | 160,854 | 15,163 | 415 | orchestration over eight `host/` owners |
| `MiLAi-Lab/tools/run_product02_context_gate.py` | 48,627 | 419 | 16 | thin wrapper over `milai_lab.runners` |
| `MiLAi-Lab/tools/run_product03_openworker_usability.py` | 36,784 | 417 | 16 | thin wrapper over `milai_lab.runners` |

The historical OpenWorker entrypoint `host_adapter.py` remains byte-identical at 876 bytes / 27
lines. Public Runtime imports, MCP tool names and schemas, CLI/HTTP contracts, DB schema/migrations,
and Lab study contracts were preserved.

## Compatibility and test identity

- Five compatibility categories and six registry entries have explicit retention dispositions.
- C8 deleted no entry: the sole `INTERNAL_TEMPORARY` candidate still has Product, test, and archive
  consumers.
- All 29 receipt-referenced pytest node IDs remain present.
- Three test support packages replace 45 ordinary sibling-test imports; ordinary direct imports are
  now zero.
- Two active Lab runners use 16-line historical wrappers and typed package implementations.

## Current-tree evidence

Five `post-cleanup.receipt.json` files bind the FIXED technical debts to Product tree
`7135d3388f9360ab3acf7b160ad20451da1883a09d10bf7f51ac9a404942f521`. Runtime/PostgreSQL targeted
execution passed 23 tests and OpenWorker HTTP targeted execution passed 21 tests. Receipt validation
reports 13 total receipts, 5 current receipts, 12 current claims, 3 preserved historical diagnostic
failures, and 0 current failures. Existing scoped claims remain scoped; no claim was broadened.

## Immutable boundaries

The baseline and current Git tree objects are identical for all three immutable scopes:

| Scope | Git tree object |
| --- | --- |
| `MiLAi-Product/architecture/v1.0` | `fb9f953e07e9a06bd08695827dd91ccb0d21be38` |
| `MiLAi-Lab/studies/archive` | `b69ac4d6ebca0a52ae3ec6edff5dce914816f157` |
| `MiLAi-Artifact-Archive` | `36ac04b4b0562265250bb15f01a4d40c4ac4f710` |

## Final verification

The final candidate will run exactly one authoritative full composition covering Runtime with
PostgreSQL, all integrations, Lab fast, four historical replay shards, Archive, Product identity,
Conformance, and composition. Its run ID and final result will be recorded here after completion;
the run will not be repeated for a metadata-only identity update when all executable tree identities
remain unchanged.
