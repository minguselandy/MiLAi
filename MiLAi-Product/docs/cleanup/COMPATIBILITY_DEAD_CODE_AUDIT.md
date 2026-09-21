# C8 compatibility and dead-code audit

## Result

C8 found no compatibility entry that is safe to delete. The only registered
`INTERNAL_TEMPORARY` candidate, `runtime/src/milai/application/evidence_atoms.py`, remains an active
dependency and is retained. This is a closed audit result, not an incomplete deletion attempt.

The machine-readable evidence is
[`compatibility-dead-code-audit.json`](compatibility-dead-code-audit.json). Its source tree is the C7
merged main commit `ff51e47b8ae8b861002f3975c23c4ca88cc5106e`.

## Deletion decision table

| Registry entry | Category | Decision | Blocking evidence |
| --- | --- | --- | --- |
| `supported-package-apis` | `PUBLIC_API` | RETAIN | Versioned API decision required |
| `modularization-facades` | `PUBLIC_COMPAT` | RETAIN | Historical public imports and executable targets remain supported |
| `dedicated-test-support-seams` | `TEST_COMPAT` | RETAIN | Active test consumers and forwarding identity contracts |
| `receipt-referenced-pytest-nodes` | `HISTORICAL_COMPAT` | RETAIN | 29 immutable receipt node IDs |
| `query-ir-v01-transition` | `HISTORICAL_COMPAT` | RETAIN | Multiple active Product modules, unit tests, and archived replay imports |
| `evidence-atom-v01-alias` | `INTERNAL_TEMPORARY` | RETAIN | Product, test, and immutable archive consumers |

## Internal candidate evidence

The six required consumer dimensions for `evidence-atom-v01-alias` were checked:

| Dimension | Result | Evidence |
| --- | --- | --- |
| Production | BLOCKED | `runtime/src/milai/application/acquisition.py` imports `evidence_requirement_query` |
| Test | BLOCKED | `runtime/tests/unit/test_dg17_evidence_atoms.py` exercises all four exported helpers |
| CLI/plugin entrypoint | CLEAR | No `project.scripts` target resolves to the module |
| Active Lab | CLEAR | No active Lab source, tool, or test imports the module |
| Current receipt | CLEAR | No revalidation receipt names the module or its tests |
| Archive | BLOCKED | Immutable DG-17 snapshot documentation records the v0.1 transition path and removal condition |

Any one blocked dimension is enough to prohibit deletion. C8 therefore leaves the module, its
domain DTOs, and its tests intact. Migrating the Product acquisition consumer would be a behavior
change and requires a separate goal; archive bytes remain immutable regardless.

## Other compatibility surfaces

`query_ir_compat.py` is categorized as `HISTORICAL_COMPAT`, not dead code. It is imported by active
retrieval, acquisition, planning, replay, composition, and sufficiency modules, by multiple unit
tests, and by archived experiment code. Database files named `legacy_*` are applied migrations and
are never dead-code candidates. OpenWorker `tool_compat.py` is part of the current modularized host
implementation and is covered by its facade compatibility tests.

## Verification

`tools/verify_compatibility_registry.py` validates that:

- the five frozen categories and all six registry entries remain present;
- the C8 audit has exactly one disposition for every registry entry;
- a deletion disposition can only target `INTERNAL_TEMPORARY`;
- every retained `INTERNAL_TEMPORARY` entry records at least one real blocking consumer;
- every declared consumer path exists;
- all 29 receipt node IDs, three test-support roots, and the no-sibling-test-import rule remain
  intact.

C8 uses static inventory, collection, boundary, and direct compatibility checks only. It does not
run PostgreSQL, Lab fast, historical replay, or full composition.
