# Architecture Baseline

> Bundle：`1.0.0`  
> Captured：`2026-08-17`（Asia/Shanghai）  
> Status：`LOGICAL ARCHITECTURE FROZEN / NO-GO FOR SCHEMA FREEZE`

## MiLAi sources

| Input | SHA-256 at baseline |
| --- | --- |
| `MiLAi_Logical_Architecture_v1_设计文档.md` | `a9e588afc8e71f55334e2fe2bd4b187e0129dc6160f2389e535e81ab83ebbf88` |
| `MiLAi_Lean_V1_实施合同.md` | `395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba` |
| `MiLAi_Lean_V1_设计开发_GOALS.md` | `3dfebe94b58f32772939ac576421a6176dc9419b49e009d7f422fc0de7bc9d42` |
| `runtime/uv.lock` | `4f12bca74846302e734cc2d03f3f3f0573ad2f209c4332fa1d850eeae85d3f4b` |
| `runtime/pyproject.toml` | `0d23d7ee822ac3f95ae41f13abd8c7243ea66165ea0669b505d7b576b2630ce1` |
| `runtime/compose.yaml` | `2d9a46b53912d961f1ef975895de035c6774e705b510b03ed23534ea3de6cb3b` |

Runtime facts:

```text
Python 3.11.13
PostgreSQL 16.14
pgvector 0.8.2
Alembic head 0026_legacy_tx05_time_guard
31 tenant-owned durable tables (32 durable tables including global runtime_metadata)
57 mypy-checked runtime source files
candidate.5 fresh base-to-0026 exact-role runtime suite: 121 passed
19 architecture bundle tests passed
7 strict-typed isolated research source files
9 isolated research tests passed
```

These are independently accepted architecture inputs, not performance SLA, Schema freeze or
production certification.

## External design inputs

### ReMe

```text
local version: 0.4.1.6
git metadata: unavailable
license: Apache-2.0
version file hash: 492b5fa70baa992c8b41668bddbfe5af322fd51cf69e7cf93e4ac39e52434f7c
pyproject hash: b7cc9af7e1f9e93737ab728771631f9e96aeade36139c561686a84ed1de49e91
license hash: cc54d679aaced751c096f120b666355c106d9394d28f93f6df353973f6cd7dbe
```

Borrowed pattern: local-first readable files, progressive hybrid retrieval, component/job/step
composition. Rejected authority: auto-generated memory cannot commit MiLAi Claim.

### Hindsight

```text
git metadata: unavailable
license: MIT
README hash: be5f249cff4ab6ac4cb60961cf2ac0eb831625a89f2b54830f2df1a578219dcb
workspace pyproject hash: 4310866acf638e7e4917bf1a98a5593b3a3e60de30b0ca0bd23ff7174e25c71c
package-lock hash: ea53979d82bcd7ed3d24779b3beda0c6c5d71dc7830912ae5941b4f9569614f1
license hash: 01fde0bedf83bdc185065d7af524a61690efe576a67f922eaff3a1280c17b63a
```

Borrowed pattern: bank isolation, retain/recall/reflect, semantic/keyword/graph/temporal candidate
fusion, operations/observability. Rejected authority: reflect and mental models are candidates.

### Graphiti

```text
version: 0.29.3
commit: 401c59a65bdeb22a44136901ff30231e6998a7fe
worktree: clean
license: Apache-2.0
pyproject hash: ebc4891414a5e2a3677b602551715a5fa307519739f7da1bd686c603b472d624
license hash: 2825300b20d7b951209835a4a331f29e24725a39d65168e4b831df53aa372650
```

Borrowed pattern: Episode provenance, temporal validity, incremental graph construction.
Rejected authority: graph fact invalidation cannot move ClaimHead.

### Mem0

```text
version: 2.0.18
commit: 001c235229be8795e3834520467bd0d661ed8f34
worktree status hash: 400b1a03352ac7d76f0ffeaa2c4174869f653119bcfcfd0db1232ef83526ca36
binary patch hash: 3f13efb5a52a840b519649788c1fdc9b7bb0beaefec1a44f6f642dc89679c8f4
license: Apache-2.0
pyproject hash: a84cfcecb349663aebb15d9b27a85caf81352fc6489c33bc265060a1319c557e
license hash: 0bbcbe931c353293a2fafce08326181dfeea0e568c566afd4ce8337a70f5e219
```

Borrowed pattern: provider abstraction and conventional add/search baseline. Rejected authority:
provider memory ID and vector record are not MiLAi canonical identity.

## Evaluation snapshots

| Asset | Commit |
| --- | --- |
| BEAM | `3e12035532eb85768f1a7cd779832b650c4b2ef9` |
| CUPID | `a8560cab293ae98be4fe260689d58bddf96b51ef` |
| HorizonBench | `4b5076b147c952499b7921f20f811dd5aca7ef0b` |
| LongMemEval | `9e0b455f4ef0e2ab8f2e582289761153549043fc` |
| LongMemEval-V2 | `2cc8c540bdb87fe6761629b585e727e1c4704520` |
| Memora | `a6493188efc836d6511ed5e4163fe3ba87da30ff` |
| PAHF | `7a11213360a82d5f437a035e3a31c92d6307f8cf` |

Benchmark schemas and scores remain Audit inputs; they do not define product objects or policy.

## Baseline rules

1. A missing upstream commit must be recorded as missing, never inferred.
2. A dirty source requires both base commit and patch/status hash.
3. Updating a source lock requires mapping/behavior review, not a mechanical hash refresh.
4. No external asset receives Migration Owner or Steward credentials.
5. No new memory framework is required for candidate freeze.
6. Migrations 0015–0026 are forward-only audit/security evolution; fresh-database replay and explicit
   forward repair replace destructive downgrade claims.
7. Corrected migration 0024 treats populated candidate.1 state as a first-class compatibility input: actual
   immutable provenance permits repair, while unknown or incomplete provenance aborts the whole migration
   and leaves Alembic at 0023. Migration 0025 applies the same proof to already-applied candidate.3/0024
   development state. Both require all six durable TX-05 timestamps to agree exactly. Proof-only migration
   0026 re-certifies already-applied candidate.4/0025 state; unprovable inputs remain at their prior head.
8. Review/release identity is the SHA-256 of `architecture_manifest.json` recorded outside this bundle.
