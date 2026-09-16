---
document_id: MILA-ML-ARCH
version: "1.0"
status: ACTIVE_PROGRAM_BASELINE
normative_scope: program_and_plane_boundaries_only
execution_order_authority: MILA-ML-MASTER
supersedes:
  - previous project-level retrieval-centric framing
---

# MiLAi Memory Lifecycle：项目级架构与主程序 Master

> 日期：2026-08-30（Asia/Shanghai）
> 上位规范：architecture/v1.0 与 MiLAi Logical Architecture 1.0.0 FROZEN
> 执行顺序：[MiLAi Memory Lifecycle 总 Goal](./MiLAi_Memory_Lifecycle_总_GOALS.md)
> 变更性质：Program/Plane 基线，不修改冻结对象、事务、权限或 Schema

---

# 1. 规范权威

本文件只规范：

~~~text
Program boundaries
Plane responsibilities
cross-Plane interfaces and authority
Raw-preserving lifecycle DAG
Formation sidecar runtime semantics
revocation and freshness behavior
architecture-vNext boundary
~~~

本文件不规范：

~~~text
当前执行入口
Goal 状态
实验运行顺序
entry / effect gate
terminal disposition
~~~

规范链：

~~~text
architecture/v1.0 + frozen Logical Architecture
  ↓
MiLA Lean V1 实施合同
  ↓
MILA-ML-ARCH@1.0                 Program / Plane baseline
  ↓
MILA-ML-MASTER                   execution order and gates
  ↓
Program / local Goal contracts
  ↓
historical DG method documents
~~~

任何下位文档不得扩大本文件的 authority，也不得改写 architecture/v1.0。

---

# 2. Phase 1 范围

当前架构基线限定为文本个人记忆：

~~~text
user-assistant textual interaction
personal facts
preferences
events
state and state changes
textual corrections and revocations
~~~

当前不进入：

~~~text
multimodal sensor formation
procedural skill formation
agent trajectory gotcha formation
tool workflow learning
multi-agent shared memory formation
~~~

因此 LongMemEval-V2 只作为后续扩展候选，不进入 Phase 1 的 research hypothesis 或完成门。

---

# 3. 三个 Program

| Program | 核心责任 | Authority |
| --- | --- | --- |
| A — Memory Formation | 从 Raw Evidence 构造可修正的 episode、identity、event-time、state/change 与 retrieval representation | noncanonical derivation |
| B — Memory Evolution | 将合法 state/change candidate 映射为 Proposal，并治理更新、冲突、撤销与回滚 | sole canonical evolution |
| C — Memory Recollection | 针对 query 从 Raw、Formed、Canonical lanes 读取、组合和执行 typed completion | query-local read |

DG-26～DG-30 仅属于 Program C 的 Read Path / Recollection 子计划。

---

# 4. Raw-preserving 生命周期 DAG

~~~text
                              Raw Evidence
                                   │
               ┌───────────────────┼────────────────────┐
               │                   │                    │
               ▼                   ▼                    ▼
        Raw Projection       Formation Plane      Direct governed
                                  │                proposal path
                                  ├─ Episode
                                  ├─ Identity / Event / Time
                                  ├─ State / Change Candidate
                                  └─ Formed Projection
                                       │
                                       ▼
                              Evolution Bridge
                                       │
                              OperationProposal
                                       │
                              Canonical Evolution
                                       │
                              Canonical Projection

Raw Projection ───────────────────────┐
Formed Projection ────────────────────┼→ Requirement-aware Recollection
Canonical State / Projection ─────────┘
~~~

不是所有 Evidence 都必须进入 Formation 或 Canonical Evolution。Raw Evidence 可以直接形成 Raw Projection，也可以经现有受治理路径产生 OperationProposal。

---

# 5. 五个 Plane

## 5.1 Evidence Plane

记录系统观察到的来源内容：

~~~text
ContentBlob / EvidenceRecord / EvidenceSpan
SourceIdentity / Actor
source time / ingestion time
scope / permission / retention / revocation
artifact and tool lineage
~~~

Evidence 对来源记录有权威，不对世界事实拥有最终真值权。

## 5.2 Memory Formation Plane

执行 formation-time Semantic Derivation：

~~~text
episode segmentation
mention extraction
entity / event identity hypothesis
event occurrence-time grounding
state assertion / transition hypothesis
formed retrieval projection
~~~

输出必须：

~~~text
noncanonical
versioned
provenance-linked
rebuildable
confidence-bearing
~~~

这里不得使用 query-time 的 Grounded Evidence Interpretation 名称。

## 5.3 Canonical Evolution Plane

复用唯一写入路径：

~~~text
FormationArtifactCandidate
→ Evolution Bridge
→ OperationProposal
→ deterministic validation
→ CommitPolicy / StewardDecision
→ Canonical Procedure
→ ClaimVersion / ClaimHead / OpenIssue
~~~

模型和 sidecar 无 Canonical DML 权限。

## 5.4 Recollection Plane

执行 query-time Grounded Evidence Interpretation：

~~~text
MemoryQueryIR
→ RequirementState
→ Raw / Formed / Canonical acquisition
→ EvidenceCandidate
→ Grounded Evidence Interpretation
→ Binding
→ Sufficiency
→ Typed Operator
~~~

检索结果只能影响候选选择，不能提高 authority。

## 5.5 Context / Action Plane

~~~text
AcceptedBinding
→ Typed OperatorResult
→ Minimal Proof Context
→ Reader
→ Agent action
~~~

Reader 不拥有 Evidence 接受、COMPLETE 或 Canonical commit 权。

---

# 6. Formation sidecar 统一合同

Formation sidecar 可以持久保存用于实验和重建，但：

~~~text
sidecar artifact
≠ durable logical object
≠ canonical memory
≠ authority-bearing Claim
~~~

统一 envelope：

~~~yaml
FormationArtifactEnvelope:
  artifact_id:
  schema_version:
  artifact_kind:

  producer_identity:
  model_revision:
  prompt_or_rule_digest:
  config_digest:

  source_evidence_ids: []
  source_span_refs: []
  source_snapshot_identity:
  access_policy_digest:

  idempotent_build_key:
  build_epoch:
  source_watermark:
  created_at:

  status:
    ACTIVE
    PARTIAL
    STALE
    REVOKED
    FAILED

  supersedes_artifact_ids: []
  derivation_graph:
  confidence:
~~~

confidence 只作 advisory signal。

---

# 7. 异步 Formation 运行语义

Formation worker 必须满足：

~~~text
idempotent build key
at-least-once safe processing
dead-letter visibility
per-projection watermark
stale detection
rebuild from Raw Evidence
feature-off Raw fallback
~~~

同步 TX-01 只保证 Raw Evidence 捕获；Formation 失败不得阻止 Evidence ingest。

运行状态：

| 状态 | 读取行为 |
| --- | --- |
| ACTIVE and fresh | 可作为 noncanonical formed lane |
| PARTIAL | 只补充候选，不能证明 absence/completeness |
| STALE | 必须标记 degraded 并启用 Raw fallback |
| REVOKED | 立即不可读取 |
| FAILED | Raw fallback；不得伪装 formed coverage |

---

# 8. Formation freshness 合同

必须维护：

~~~text
EvidenceWatermark
FormationCoverageWatermark
FormationPendingEvidenceCount
ProjectionFreshnessStatus
RawFallbackActivated
~~~

规则：

~~~text
FormationCoverageWatermark < EvidenceWatermark
→ formed lane = PARTIAL or STALE
→ query 保留 Raw fallback
→ formed lane 不能承担 absence 或 completeness proof
~~~

最近 Evidence 尚未形成时，系统不能因为 formed index 中没有记录而宣布 ABSENT 或 COMPLETE。

---

# 9. Derived Artifact 撤销传播

~~~text
Source Evidence revoked
    ↓
Derived artifact access blocked immediately
    ↓
Raw / Formed projection entries invalidated by lineage and watermark
    ↓
Identity and consolidation support sets recomputed
    ↓
Affected Canonical support identified
    ↓
Steward review / OpenIssue / governed transition
~~~

禁止：

~~~text
silent derived retention
silent artifact delete that erases audit lineage
silent Canonical support removal
revoked Evidence returned through stale projection
~~~

必须测量：

~~~text
DerivedArtifactRevocationLeak
RevokedEvidenceRetrievalLeak
StaleProjectionRead
RevocationPropagationLagP95
CanonicalSupportReevaluationCoverage
UnauthorizedRawEvidenceLoss
~~~

合法 retention expiry 或用户授权删除不计为 UnauthorizedRawEvidenceLoss。

---

# 10. Evolution Bridge

Program B 不新增 Store，但必须验证跨 Program 接口：

~~~text
StateAssertionCandidate / StateTransitionCandidate
→ typed OperationProposal mapping
→ deterministic validation
→ Steward replay
→ expected ClaimVersion / OpenIssue disposition
→ as-of current and historical read
→ correction / revocation / rollback replay
~~~

Evolution Bridge 至少传递：

~~~yaml
EvolutionBridgeInput:
  formation_artifact_id:
  source_evidence_ids: []
  grounded_spans: []
  subject_identity:
  predicate:
  proposed_value:
  transition_relation:
  valid_time:
  source_time:
  scope:
  confidence:
~~~

必须区分：

~~~text
ESTABLISHES
UPDATES
CORRECTS
REVOKES
TEMPORARILY_CONSTRAINS
CONTRADICTS
REFINES
~~~

EV-01 最小硬门：

~~~text
UnsupportedCanonicalPromotion = 0
WrongTransitionDisposition = 0
MissingProvenanceClosure = 0
ValidTimeMisassignment = 0
RevocationSupportLeak = 0
RollbackReplayMismatch = 0
~~~

EV-01 只复用现有 OperationProposal、StewardDecision、ClaimVersion、OpenIssue 和 TX-02～TX-06。

---

# 11. 三种 Rollback

必须分别记录：

| 名称 | 含义 | 本阶段要求 |
| --- | --- | --- |
| ImplementationRollback | 关闭实验 feature，恢复既有 Runtime 路径 | 必须验证 |
| ProjectionRebuildRollback | 丢弃/rebuild sidecar 与 projection，回到 Raw | 必须验证 |
| CanonicalStateRollback | 经受治理新版本表达语义恢复，不修改历史字节 | EV-01 验证 replay，不引入自由 undo |

不得用一个 rollback 字段混合三者。

---

# 12. 术语

规范名称：

~~~text
ExperimentalFeatureFlagsDefault = OFF
EvidenceCandidate
FormationArtifactCandidate
OperationProposal
Research Hypothesis: ML-H1 / ML-H2
Formation-time Semantic Derivation
Query-time Grounded Evidence Interpretation
~~~

Claim、ClaimVersion、ClaimHead 只用于 Canonical domain，不用于 Research Hypothesis。

---

# 13. Architecture-vNext 边界

在形成对象进入正式 durable logical objects 前，必须：

~~~text
Formation direct fidelity 通过
EV-01 bridge 通过
representation × retrieval factorial 完成
sidecar revocation and freshness 通过
提出 architecture-vNext ADR
定义 compatibility / migration / downgrade
更新 crosswalk
执行真实 PostgreSQL、role、RLS 和 revoke tests
~~~

在此之前，所有 Formation object 只作为 sidecar / evaluation contract。

---

# 14. 稳定导航

- [执行顺序与实验 Gate：MILA-ML-MASTER](./MiLAi_Memory_Lifecycle_总_GOALS.md)
- [Program A：Memory Formation](./MiLAi_MF-01-MF-06_Memory_Formation_and_Representation_MASTER.md)
- [Program C：Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
- [Program B 现有 Canonical 合同](./MiLAi_Lean_V1_实施合同.md)
- [冻结逻辑对象](./architecture/v1.0/OBJECTS.md)

本文件不保存动态状态；执行状态只存在于 MILA-ML-MASTER。
