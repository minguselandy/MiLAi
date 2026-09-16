---
document_id: MILA-MD01
version: "1.0"
status: PASS_MD01_MEMORY_FORMATION_CORE
execution_order_authority: MILA-ML-MASTER@1.4
architecture_baseline: MILA-ML-ARCH@1.0
execution_authority: USER_EXPLICIT_20260830_MD01_EXECUTE
terminal_artifact: var/md01/md01-memory-formation-bundle-20260830-001/terminal.json
---

# MiLAi MD-01：统一 Memory Formation Bundle 与 Semantic Episode Goal

> 日期：2026-08-30（Asia/Shanghai）  
> 主线：Memory Formation / Memory Evolution  
> 性质：已执行的 noncanonical sidecar Goal；implementation 不修改 PostgreSQL/public MCP/frozen architecture  
> Formal holdout：不使用  
> Experimental feature flags：OFF

> **执行授权**：原 design-only 限制已由 2026-08-30 用户明确执行请求取代。本次只授权 CPU、零模型、零数据库的 sidecar implementation/effect；仍不授权修改数据库、公开 MCP、冻结架构、默认 feature flag 或使用 holdout。

## 1. 问题与方法命题

MF-03 和 MF-04 已经分别形成 identity/event/time 与 state/change，但它们仍是彼此分离的 sidecar；当前没有一个 query-independent Memory object 同时表达：

```text
Raw Evidence coverage
semantic episode context
entity / event / occurrence time
state assertion / transition
freshness / watermark
raw fallback and canonical authority boundary
```

MD-01 拟实现：

> **Raw-preserving MemoryFormationBundleV01：以 SemanticEpisode 作为上下文组织单元，复用已验证的 MF-03/MF-04 typed artifacts，并始终将 Raw Evidence 作为可回放底座。**

## 2. Research Hypotheses

| Hypothesis | 最小可信证据 |
| --- | --- |
| MD01-H1 统一 bundle 能正确表达完整 Memory Formation snapshot | Raw span coverage=1.0，source-role leakage=0，sub-artifact lineage=1.0，deterministic replay=1.0，canonical mutations=0 |
| MD01-H2 简单 episode formation 能在真实对照上组织上下文 | 预注册 multi-turn validation 上 BoundaryPrecision/Recall 均≥0.90，episode pairwise F1≥0.90，不使用 case-ID/gold-aware rule |

Anti-claim：不把收益归因于更多 retrieval channel、query-time model、更大 Top-k 或 Canonical 自动写入。

## 3. 对象与边界

### `SemanticEpisodeCandidateV01`

```yaml
episode_digest:
source_spans: []              # 按原始对话顺序，精确回到 Evidence
participant_roles: []
topic_terms: []               # 只是可重建 feature
boundary_reason:
source_time_start:
source_time_end:
producer_identity:
canonical: false
```

### `MemoryFormationBundleV01`

```yaml
bundle_digest:
source_snapshot_digest:
source_evidence_ids: []
source_watermark:
coverage_status: COMPLETE
episode_candidates: []
semantic_sidecar:             # MF-03 entity/event/time
state_change_sidecar:         # MF-04 state/change
raw_fallback_required: true
canonical: false
canonical_mutation: false
```

硬边界：

1. assistant turn 可参与 episode context，但不得被形成为用户个人 state/event。
2. Episode 只是 noncanonical context projection，不等于现有 durable `Episode` aggregate。
3. Bundle 不能直接提升 Claim；仍需 EV-01 和唯一 Proposal/Steward 路径。
4. 任一 formed artifact 失效时必须可从 Raw Evidence 重建。

## 4. 开发 Block 与完成证据

### B1 — Contrasting episode validation（MUST）

- 固定 8–12 个 non-holdout conversations。
- 覆盖 same-topic continuation、explicit topic shift、session change、time gap、pronoun continuation、correction continuation。
- 在执行 scorer 前封存 expected episode membership 和 boundary reason。

完成：封存 10 个 conversations、35 turns、16 episodes，覆盖全部六类要求场景；fixture SHA-256 为 `4877637b0954f59a618ea64dd73996f8b35b558fca49c0b9c048728d90623c97`，run-lock digest 为 `7c520e8c3b997050aa10f05dc7e3bb69115d04744a8a7d1eacf9a0093269a0fe`。

### B2 — Typed memory objects（MUST）

- 新增 episode 和 bundle Pydantic contracts。
- 验证 digest、排序、全量 Raw coverage、timezone-aware watermark、sub-artifact source closure。

完成：新增 `SemanticEpisodeCandidateV01`、`MemoryFormationBundleV01` 与 `MemoryFormationReceiptV01`；Pydantic 合同执行 digest、顺序、完整 turn span、timezone、source closure 和 user-only semantic/state source gate。

### B3 — Query-independent builder（MUST）

- 一次构造 episodes、MF-03 semantic sidecar 和 MF-04 state/change sidecar。
- 状态/事件形成只消费 user Evidence；episode 保留 user/assistant 对话上下文。
- 不调 Provider、Reader、retrieval 或 database。

完成：`MemoryFormationBundleService` 一次生成 episode、MF-03 semantic sidecar 和 MF-04 state/change sidecar；应用模块没有 Provider、Reader、Retrieval 或 persistence 依赖。

### B4 — Matched formation effect（MUST）

- 直接评估 episode boundary/pairwise metrics、Raw coverage、source-role isolation 和 deterministic replay。
- 重放现有 MF-03/MF-04 tests，不重新调整已封存 14-case 规则。

完成：正式 runner 内嵌既有 MF-03/MF-04 与新 bundle 回归，`20 passed`、regression=0；规则未按 case ID/gold 调整。

### B5 — Integration readiness（NICE-TO-HAVE）

- 只生成 application service 和 sidecar receipt。
- 不进入 migration/background worker/product flag，直到更大 validation 证明泛化。

完成：只交付 application service、sidecar contracts 与 receipt；Schema/public MCP/background worker/product flag 均未改变。

## 5. 实际执行顺序

```text
S0 Goal + label seal
→ S1 domain contracts
→ S2 episode/bundle builder
→ S3 matched effect + repair loop
→ S4 regression/static/replay + terminal
```

全部完成；S3 首次 protocol-valid effect 即达到预注册门，没有产生 repair iteration。

中间 protocol/implementation 失败优先修复通用根因，不终止 Program。只有 Raw Evidence 丢失、scope 泄漏、未授权 Canonical mutation 或数据损坏立即停止当次 effect。

## 6. PASS 与负结果

`PASS_MD01_MEMORY_FORMATION_CORE` 需要：

```text
RawSpanCoverage = 1.0
EpisodeBoundaryPrecision >= 0.90
EpisodeBoundaryRecall >= 0.90
EpisodePairwiseF1 >= 0.90
UserSemanticSourcePrecision = 1.0
ArtifactLineageClosure = 1.0
DeterministicReplay = 1.0
Provider/Reader/Retrieval/DB calls = 0
Canonical mutations = 0
existing MF-03/MF-04 regression = 0
```

允许的负结果：

```text
PARKED_EPISODE_BOUNDARY_NO_GENERALIZED_GAIN
PARTIAL_BUNDLE_PASS_EPISODE_UNRESOLVED
FAIL_RAW_OR_AUTHORITY_BOUNDARY
```

## 7. 已完成交付

- domain contracts 与 query-independent builder
- 封存 validation fixture
- unit/effect tests
- `var/md01/.../receipt.json`
- 更新 Program A / MILA-ML-MASTER / 执行报告

以上交付已完成。主制品目录严格保留四个文件：

```text
var/md01/md01-memory-formation-bundle-20260830-001/
  run-lock.json
  results.json
  terminal.json
  receipt.json
```

## 8. Terminal

```text
status                         PASS_MD01_MEMORY_FORMATION_CORE
RawSpanCoverage                1.0
EpisodeBoundaryPrecision       1.0
EpisodeBoundaryRecall          1.0
EpisodePairwiseF1              1.0
UserSemanticSourcePrecision    1.0
ArtifactLineageClosure         1.0
DeterministicReplay            1.0
Provider/Reader/Retrieval/DB   0/0/0/0
Canonical mutations            0
MF-03/MF-04 regression         0
formal holdout                 false
experimental feature flags     OFF
```

MD01-H1/H2 仅在封存的 non-holdout validation 上得到支持；不扩张为产品发布、formal holdout 或普遍泛化主张。终局 receipt digest 为 `3d17a07e39c97a5c338ed514cef57fd8a15c1dbe4c0cae090bc2487079fc4842`。
