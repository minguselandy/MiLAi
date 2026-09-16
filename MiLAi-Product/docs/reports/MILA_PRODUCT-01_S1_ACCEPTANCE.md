# MiLA Product-01 S1 acceptance

Date: 2026-09-01  
Stage: S1 — Identity and Reader-visible evidence truthfulness  
Result: **PASS**

## Frozen run identity

- Product behavior commit: `959060c5a6453bf61d537b1245f99fd67395e689`
- Product behavior tree: `8b5bfa1d49555529c046d9c8f0e39d1caaf11fae7616676cb41227b820d7cb72`
- Lab Product lock digest: `a140f52811a37839b9e17bb7070847d2c4cc958f1175e1b798f1eb787dd4a6d8`
- LongMemEval-S cleaned-500 digest: `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- Outcome-blind selection digest: `79ab9097282c096932832c1057d77d263daaba1b20b98c317cf9e3e208d1d180`
- Lab artifact: `MiLAi-Lab/artifacts/product01-s1-20260901-005`
- Run ID: `product01-s1-20260901T131530Z`

The 24-case selection used only structural strata and context-length tails. No Reader, Answer,
Judge, answer text, or lexical gold material participated in selection or context validation.

## Exit gate

| Metric | Required | Observed |
| --- | ---: | ---: |
| StructuredIdentityOnCapableCaptures | 1.0 | 1.0 |
| SessionIdentityIntegrity | 1.0 | 1.0 |
| CrossSourceSessionAdjacencyExpansion | 0 | 0 |
| ReaderVisibleTraceExactness | 1.0 | 1.0 |
| ContextSerializationReplayEquivalence | 1.0 | 1.0 |
| InfrastructureFailureAsSemanticAbstention | 0 | 0 |
| ContextConstructionSystemFailure | 0 | 0 |
| AtomicUnitTruncationCount | 0 | 0 |
| LongTurnSplitCount | 0 | 0 |
| RankFirstPrefixViolationCount | 0 | 0 |
| Reader / Answer / Judge calls | 0 / 0 / 0 | 0 / 0 / 0 |
| Canonical mutation count | 0 | 0 |
| Passed cases | 24 | 24 |

The run emitted 21 honest semantic abstentions. These are not construction failures and were never
substituted for infrastructure or protocol errors.

## Artifact integrity

| File | SHA-256 |
| --- | --- |
| `run.json` | `a03af0ae299279d91cefbaa5351edb314850bc47f6f7278236f046afa2f5a641` |
| `cases.jsonl` | `9371062df9af433ca2fd64fab773ccb73efb178fe7df8c5fa757272c20f35493` |
| `metrics.json` | `585a044f4e0783d607d2efc5fc2c055b8b3a8d776c2a1a19f3916cb6705c2a39` |
| `terminal.json` | `a62701f1d8a2668961f62a41666ba51b634e6612f4ce65db2b35d439364d0ba7` |

## Repairs proved by the run

- Capable capture paths preserve supplied speaker/session/turn identity; UNKNOWN identity remains
  ineligible for semantic adjacency effects.
- Raw retrieval, admitted Evidence, and Reader-visible serialization have separate trace layers.
- Normal and budget-infeasible terminal contexts expose replayable character and UTF-8 byte ranges.
- Admission is whole-unit only; receipt aliases map exactly to Reader-visible Evidence units.
- Duplicate source session IDs receive a structural occurrence discriminator before hashing, and
  empty source turns are omitted without renumbering material source turns.
- Projection readiness uses bounded public-contract waits and never becomes semantic abstention.

## Disposition

S1 authorizes a **new repaired untreated baseline** identified by the Product commit, Product lock,
dataset digest, selection digest, and terminal artifact above. The pre-repair R4 baseline is not
resumed. S2 starts from this identity and may compare only B0 (repaired untreated) with B1 (simple
quota union, EvidenceSet, and grounded Binding) under matched budgets.

The exact synthetic S1 Compose project, database volume, generated environment file, and blob root
were removed after artifact verification. No pre-existing or production database was addressed.
