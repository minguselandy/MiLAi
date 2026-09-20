# MiLAi codebase cleanup baseline

This is the exact green baseline for the behavior-preserving cleanup program.
It records current identity and verification only; it does not modify or
reinterpret Frozen Architecture 1.0.

## Identity

| Field | Value |
| --- | --- |
| `CLEANUP_BASELINE_COMMIT` | `798b7cac21957873791afff6122d3f06a82214c5` |
| `CLEANUP_BASELINE_RUN` | Run `#29`, ID `35519772754`, attempt `2` |
| `PRODUCT_TREE_SHA256` | `2dddd26130943834468e7944f3b422c2aa81e64611256cb7f497e7f96e32b0a1` |
| `PRODUCT_MANIFEST_SHA256` | `28abb4b6b711ec49b5880825afd247d88526487ff87d47608b1f9e06c7e872f8` |
| `ARCHITECTURE_VERSION` | `1.0.0` |
| `CONFORMANCE_COUNTS` | `9 PASS / 35 UNVERIFIED / 0 DEVIATION / 0 NOT_APPLICABLE` |
| `TECH_DEBT_COUNTS` | `5 FIXED / 5 NEEDS_REVALIDATION / 0 OPEN / 0 OBSOLETE` |
| `RUNTIME_TEST_COUNT` | `1234 passed / 3 skipped` |
| `LAB_FAST_COUNT` | `4541 passed / 137 skipped / 4 deselected` |
| `LAB_REPLAY_STATUS` | four shards PASS |

Immutable baseline Git tree objects:

| Scope | Git tree object |
| --- | --- |
| `MiLAi-Product/architecture/v1.0` | `fb9f953e07e9a06bd08695827dd91ccb0d21be38` |
| `MiLAi-Lab/studies/archive` | `b69ac4d6ebca0a52ae3ec6edff5dce914816f157` |
| `MiLAi-Artifact-Archive` | `36ac04b4b0562265250bb15f01a4d40c4ac4f710` |

The Conformance receipt intentionally records its Product source commit as
`6fbb717ba2e9c77fd8be071725b2f25a0d771cb4`; documentation/evidence commits
after that source commit do not change the Product tree digest above.

## Remote gate

Run #29 attempt 2 completed with 17 successful jobs, including Runtime,
Product identity, Conformance, Archive, six integrations, Lab fast, four
historical replay shards, and an actually executed Product/Lab/Archive
composition gate.

The first attempt's Lab fast job exposed a load-sensitive 40ms deadline test
failure before reservation. No Product or Lab code was changed: only that
failed job was rerun, it completed `4541 passed`, and composition then ran and
passed. This event is retained as baseline provenance rather than hidden.

## Local gate

Before creating `cleanup/00-baseline-inventory`:

```text
local main == origin/main == 798b7cac21957873791afff6122d3f06a82214c5
working tree clean
```

## Inventory

The machine inventory is [`module-inventory.json`](module-inventory.json), and
its human summary is [`MODULE_INVENTORY.md`](MODULE_INVENTORY.md). The checked
inventory generator is [`tools/build_module_inventory.py`](../../tools/build_module_inventory.py).
