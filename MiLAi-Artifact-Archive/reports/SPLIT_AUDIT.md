# MiLAi Split Audit

Captured at: `2026-09-01T00:00:00+00:00`  
Legacy root: `/cra/memory/mx_memory/MiLAi`  
Legacy HEAD: `651099ba8cffc2675961bb9250ba44c158efccb5`

## Result

The legacy directory is not a reproducible product repository: nearly all
current source, configuration, documentation and experiment outputs are outside
its six-file Git index. The split must therefore use curated snapshot commits,
not history rewriting.

This archive preserves an index-backed map of legacy evidence and a complete
classification of retained source material. It does not modify or duplicate
the legacy artifact byte store.

## Source classification

| Category | Represented files | Bytes |
| --- | ---: | ---: |
| archive | 74,715 | 5,922,887,971 |
| external | 31,197 | 1,287,380,314 |
| generated | 2,010 | 1,124,521,958 |
| lab | 1,044 | 14,677,811 |
| product | 512 | 6,965,917 |

- inventory rows: `2,356`
- individually SHA-256 hashed files: `2,216`
- sensitive metadata-only files: `1`
- source inventory SHA-256: `c27b7a08226fe5503daa7b6b9f5b8d491bcb464dd92ac29b55b4fc9a4632f553`

Generated and external dependency trees are aggregated to keep the manifest
small. Source/config/document files remain individually addressable.

## Legacy control artifacts

| Artifact role | Count | Bytes |
| --- | ---: | ---: |
| decision | 25 | 19,717 |
| deliverable-index | 5 | 55,134 |
| failure-index | 7 | 78,718 |
| ledger | 507 | 38,459,054 |
| manifest | 8,350 | 15,058,492 |
| receipt | 4,005 | 66,870,763 |
| results | 61 | 22,717,464 |
| run-lock | 58 | 1,508,289 |
| summary | 7 | 137,561 |
| terminal | 149 | 585,012 |

- indexed artifacts: `13,174`
- indexed bytes: `145,490,204`
- logical run identifiers: `1,020`
- catalog SHA-256: `6257ce873bc729c4b2fb83e91b9e1750cd44e57e21240756a25ca2b8e46b21a5`

The full legacy `var/` tree remains external. A catalog status is the status
reported by the artifact, not a fresh validity judgment.

## Preserved user work

- `scripts/dg13u_u1_review.py`: current `5b297e995a87240b0bb9161a031aa34170bd0db97c10d954c77a4b9ca8b95bad`, HEAD `7d2ff90cbfb423f66d50bddd0608a08bb7561c14e25cfff3a9eedc4df858cdf2`
- `tests/test_dg13u_u1_review.py`: current `3404142e970ea68aa6b418a1d38d8408f46f2e8053cf3463afa8e5950fe0fa25`, HEAD `af7a8c4783c0e6b6f16d8b7cc458c17e1e06c231afc2f209387fb8854e199146`

- binary-safe patch SHA-256: `3dce78dde01f20c7987b0251d1a723487229656584d5a7e3eec6cfb90d23fc11`
- patch bytes: `2780`

The snapshots and patch are copies only. The tracked legacy files were neither
staged nor reset.

## Split recommendation

Create two independent sibling repositories:

1. `MiLAi-Product`: Runtime, python-client, MCP, OpenWorker-MCP, hooks,
   LangGraph and AutoGen packages, contracts, frozen architecture and minimal
   product operations docs.
2. `MiLAi-Lab`: evaluation, benchmark, research, historical Goal material and
   experiment harnesses, pinned to exact Product wheel/contract identities.

Keep the old `MiLAi` directory untouched until both repositories pass parity
checks. Product must never import Lab. Lab's temporary private-runtime access
must be concentrated in an explicitly unstable compatibility adapter and then
removed incrementally.

## Known boundary facts

- `architecture/v1.0` bundle validation passes, while the broader project
  source lock has pre-existing drift.
- Runtime's non-integration core passed when three cross-boundary tests were
  excluded; those tests must be moved or repaired during the split.
- Experiment code has hundreds of direct Runtime imports, including private
  symbols; an immediate public-API-only cut would not be credible.
- Build outputs, virtual environments and operational data account for most
  workspace size and belong in neither new source repository.

## Validation

Run `python3 tools/validate_archive.py --check-legacy` from this repository.
It verifies archive closure, JSONL ordering/schema, all indexed legacy hashes,
the preserved snapshots and that the patch recreates the current user files
from their preserved HEAD bases.
