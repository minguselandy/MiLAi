# MiLAi Lean V1 实施合同

> 文档版本：`0.1.0 CANDIDATE`  
> 文档类型：近期实施合同，不是新的逻辑架构版本  
> 适用范围：MiLAi Lean V1 产品底座与 OSPC 离线研究  
> Schema 状态：`0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`  
> 默认部署：本地单用户、单 tenant  
> 编制日期：2026-08-13

本合同把以下三份文档收敛成一个可执行的 Lean V1 开发边界：

- [`MiLAi_Lean_V1_产品底座与研究核心.md`](./MiLAi_Lean_V1_产品底座与研究核心.md)
- [`MiLAi技术升级需求说明_v2.md`](./MiLAi技术升级需求说明_v2.md)
- [`MiLAi开发实施与使用流程_v1.md`](./MiLAi开发实施与使用流程_v1.md)

本合同解决近期实现中的术语、最小数据、操作映射、OpenIssue 生命周期、安全边界、删除语义和
OSPC 评测口径问题。2026-08-16 用户明确：MiLAi Logical Architecture 不是待下载的外部原件，
而应由本项目基于现有实现和已有项目自行设计、实现。当前上位设计为
`MiLAi_Logical_Architecture_v1_设计文档.md` 和 `architecture/v1.0/`；精确
`1.0.0-candidate.5` 已由同一 independent reviewer `ACCEPT`，F01–F12 全部关闭，并单独提升为
`1.0.0 FROZEN` Logical Architecture。本合同与冻结设计发生
冲突时，必须提交显式架构决策并同步 crosswalk，不得静默择一。

当前工作区已包含 G1–G9、I-01～I-12、frozen bundle、machine crosswalk、验证脚本、外部
trust anchor 与独立 acceptance。因此：

```text
允许：按本合同开发实验性 Runtime、Migration、API 和测试
禁止：把 Logical Architecture freeze 扩大宣称为 Schema frozen、Runtime/Production ready
```

---

# 1. 规范层级与用词

## 1.1 文档优先级

出现冲突时按以下顺序处理：

1. 已发布的 `architecture/v1.0/` MiLAi Logical Architecture frozen 版本；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. 本合同对 Lean V1 的具体实施约束；
4. `MiLAi_Lean_V1_产品底座与研究核心.md`；
5. 其他需求与流程文档中未暂停的部分。

本合同只能收缩实现范围或细化实验性 Schema，不能改变冻结对象的身份、单写者边界和不变量。

## 1.2 规范词

| 词 | 含义 |
| --- | --- |
| 必须 / MUST | Lean V1 完成条件，缺失即失败 |
| 禁止 / MUST NOT | 违反即阻止合并或发布 |
| 应 / SHOULD | 默认实现；偏离时需要 ADR 和测试证据 |
| 可以 / MAY | 可选实现，不是完成条件 |
| 暂停 / PARKED | 不进入 Lean V1 在线路径和 Definition of Done |

## 1.3 上位材料

以下材料已位于可访问、仓库相对的位置并由 manifest 记录校验值：

```text
architecture/v1.0-candidate/README.md
architecture/v1.0-candidate/BASELINE.md
architecture/v1.0-candidate/OBJECTS.md
architecture/v1.0-candidate/PERMISSIONS.md
architecture/v1.0-candidate/INVARIANTS.md
architecture/v1.0-candidate/TRANSACTIONS.md
architecture/v1.0-candidate/RETRIEVAL_CONTEXT.md
architecture/v1.0-candidate/DELETION_RECOVERY.md
architecture/v1.0-candidate/THREAT_MODEL.md
architecture/v1.0-candidate/FREEZE_REVIEW.md
architecture/v1.0-candidate/CROSSWALK.md
architecture/v1.0-candidate/crosswalk.json
architecture/v1.0-candidate/architecture_manifest.json
architecture/v1.0-candidate/scripts/validate_bundle.py
architecture/v1.0-candidate/scripts/verify_lock.py
architecture/v1.0-candidate/tests/
```

不得把 `C:\Users\...` 绝对路径写入 Runtime 合同、CI 或 Migration。文档和脚本统一使用仓库相对路径或显式配置变量。

---

# 2. Lean V1 交付边界

## 2.1 产品交付

Lean V1 必须提供一条不依赖外部 memory engine 的纵向闭环：

```text
Evidence Ingest
→ DeriveAndDiagnose
→ Validated OperationProposal
→ CommitPolicy / User Review
→ Versioned Claim 或 OpenIssue
→ Exact / FTS / pgvector Retrieval
→ Canonical Gate
→ Minimal ContextCapsule
→ Answer with Trace
→ Evidence Revocation and Fail-Closed Cleanup
```

产品底座的定义是：

> 一个 evidence-first、versioned、conflict-aware、可追溯且删除可传播的本地个人记忆系统。

## 2.2 在线必须运行

```text
Flask API
PostgreSQL
one background worker
LLM/embedding client
local content-addressed blob store

EvidenceRecord
Claim / ClaimVersion / ClaimHead
VersionTransition
GroundingRelation / GroundingBlock
EffectiveClaimState
OpenIssue
OperationProposal / StewardDecision
OutboxEvent / IndexWatermark
SearchDocument / SearchEmbedding
RetrievalTrace / OperationalEvent
Minimal ContextCapsule
```

## 2.3 只在离线运行

```text
AuditRecord
OSPC compression experiments
baseline and ablation runs
paper metrics
policy release evaluation
```

Audit Runner 必须使用与在线 Runtime 不同的数据库角色。Audit 结果不能自动修改 Production policy 或 canonical state。

## 2.4 暂停项

以下能力统一标记为 `PARKED`：

```text
MemoryIntention scheduler
ReMe production route
OpenViking production route
Hindsight production route
Graphiti/Zep production route
automatic Scope Evolution
automatic Pattern/Profile Promotion
LoRA personalization
multimodal/family sharing
multi-agent memory governance
```

暂停对象可以保留接口占位，但不得：

- 成为启动依赖；
- 出现在 Lean V1 发布门槛中；
- 获得 canonical 写凭据；
- 以未运行的能力出现在产品 UI 中；
- 在没有 ADR 的情况下占用在线数据迁移成本。

---

# 3. 统一术语与命名

## 3.1 应用组件与持久对象

| 名称 | 类型 | Lean V1 责任 |
| --- | --- | --- |
| `DeriveAndDiagnose` | 应用模块 | 提取候选 Claim，查询当前状态，分类关系，提出 OpenIssue |
| `ValidatedProposal` | 内部 typed contract | 在持久化 proposal 前执行确定性检查 |
| `CommitPolicy` | 应用策略 | 返回自动提交、用户审核、拒绝或无变化 |
| `OperationProposal` | 持久对象 | 保存一次可回放的 canonical mutation 建议 |
| `StewardDecision` | 持久对象 | 保存正式批准或拒绝及其策略、actor 和理由 |
| `Canonical Procedure` | 数据库边界 | 唯一执行 Claim/OpenIssue 正式变化的写入口 |

应用模块不是独立微服务。Lean V1 可以在同一 Flask 进程中承载它们，但代码模块、数据库角色和事务边界必须分离。

## 3.2 名称归一

以下名称在 Lean V1 中统一：

| 旧称或简写 | 规范名称 | 说明 |
| --- | --- | --- |
| `claim_evidence_edge` | `grounding_relation` | 前者仅视为 ClaimVersion–Evidence 子集的别名 |
| `commit_decision` | `steward_decision` | 数据库存储统一使用后者 |
| `CommitPolicyDecision` | 应用层决策结果 | 不等同于持久化的 StewardDecision |
| `current Claim` | `EffectiveClaimState` | 不能绕过 revocation、block、scope 和 authority 判断 |
| `CONFLICT` | 诊断结果 | 不是直接覆盖 Claim 的 canonical operation |
| `UPDATE` | 产品级结果 | 必须映射到一个明确的内部 operation |

禁止在新 Schema 中同时创建同义表。

## 3.3 Evidence、Claim 与 Context

```text
EvidenceRecord = 实际观察及来源
ClaimVersion   = 系统经治理后的一版 belief
OpenIssue      = 尚未合法解决的问题状态
ContextCapsule = 当前 token budget 下的工作集
```

必须保持：

- Evidence 不因提炼成 Claim 而消失；
- Claim 不因被放入 Context 而提高 authority；
- Summary、压缩结果和模型回复不能伪装成原始 Evidence；
- 模型回复只有在后续成为独立、可识别的系统事件时，才可按明确 source type 记录，且不能自动成为 truth。

## 3.4 Authority 的 Lean 判定

保留上位文档中的取值：

```text
INFORMATIONAL
ACTION_SAFE
USER_CONFIRMED
```

这三个值不是简单的全序。Lean V1 使用以下匹配规则：

| 查询要求 | 可接受条件 |
| --- | --- |
| `INFORMATIONAL` | 任一未被阻断的有效 authority |
| `USER_CONFIRMED` | effective authority 明确为 `USER_CONFIRMED` |
| `ACTION_SAFE` | effective authority 明确为 `ACTION_SAFE`；仅有用户确认不自动满足 |
| 同时要求确认和安全执行 | `ACTION_SAFE` 加一条 live `USER_CONFIRMATION` Evidence |

`confidence` 永远不能自动提升 authority。`USER_CONFIRMATION` 是 Evidence source/role；`USER_CONFIRMED` 是 Claim 的治理结果，两者必须可追溯但不得混用。

如果冻结架构将 authority 定义为全序或其他结构，应在 Schema freeze 前以冻结定义替换本节。

## 3.5 Scope 与时间

Lean V1 将适用范围与时间分开：

```yaml
scope_predicate:
  scope_kind: CONTEXTUAL
  project_ids: [milai]
  task_domains: [research]
  interaction_modes: []
  exclusions: []

valid_time:
  from: null
  to: null
```

规范来源：

- `scope_predicate` 决定在哪些项目、任务域和交互模式下适用；
- `valid_time` 是 ClaimVersion 的有效时间；
- `system_time` 由数据库记录版本何时进入系统；
- 兼容输入若在 Scope JSON 中携带 `valid_time`，必须在边界层规范化；若与 ClaimVersion 字段不一致，返回 `SCOPE_TIME_CONFLICT`。

---

# 4. Lean 逻辑流

## 4.1 唯一写路径

```text
Observation
→ EvidenceRecord
→ DeriveAndDiagnose
→ ValidatedProposal
→ CommitPolicy
→ StewardDecision when required
→ Canonical Procedure
→ ClaimVersion / ClaimHead / OpenIssue
→ OutboxEvent
```

禁止路径：

```text
LLM / Prompt             → direct canonical DML
ContextCapsule / Summary → EvidenceRecord or Claim commit
Search / Vector result   → authority escalation
External memory engine  → canonical commit
Audit result             → automatic production policy update
OpenIssue compression    → issue resolution
```

## 4.2 读路径

```text
Query
→ QueryPlan
→ L0 exact or L1 hybrid or guarded L2 reconstruction
→ candidate canonical-ID resolution
→ Canonical Gate
→ Evidence Bundle
→ Minimal ContextCapsule
→ Model
→ Answer + trace summary
```

所有二级检索结果只是 candidate。返回给模型前必须重新读取或验证 canonical 状态。

---

# 5. 最小数据合同

本节定义逻辑必需的数据，不冻结具体 PostgreSQL DDL。字段类型、索引和表拆分可以在 Schema `0.1.x` 中迭代，但语义和约束不得省略。

## 5.1 通用字段

所有 tenant-owned 记录必须包含：

```text
tenant_id
object_id
created_at
created_by_actor_id
```

所有可重试写操作还必须包含：

```text
idempotency_key
request_fingerprint
```

相同 tenant、operation family、idempotency key：

- fingerprint 相同：返回第一次的结果；
- fingerprint 不同：返回 `IDEMPOTENCY_CONFLICT`；
- 不得产生第二份 canonical side effect。

## 5.2 Evidence Plane

### `content_blob`

至少包含：

```text
tenant_id
blob_id
content_hash
storage_uri
byte_length
media_type
encryption/key reference when applicable
created_at
physical_delete_state
```

Blob 去重只允许发生在同一 tenant 内。相同内容的不同观察仍然必须创建不同 EvidenceRecord。

### `evidence_record`

至少包含：

```text
tenant_id
evidence_id
source_type
source_ref
subject_id
observed_at
captured_at
blob_id or bounded inline content
content_hash
permission_snapshot
retention_state
revoked_at
revocation_reason
ingest_idempotency_key
request_fingerprint
```

`revoked_at` 等生命周期字段可以变化；原始 capture identity、source、observed time 和 content hash 不得被覆盖。

## 5.3 Canonical State Plane

### `claim`

保存稳定 identity：

```text
tenant_id
claim_id
subject_id
predicate
claim_type
created_at
```

### `claim_version`

必须 append-only，至少包含：

```text
tenant_id
claim_version_id
claim_id
version_number
value/payload
scope_predicate
valid_time_from / valid_time_to
system_time
lifecycle
epistemic_status
freshness
authority
confidence
derivation_policy_id
model_id / template_id when applicable
steward_decision_id
canonical_commit_seq
```

任何语义、scope、grounding、authority 或状态变化都必须创建新版本，不能修改旧版本字节。

### `claim_head`

保存 `claim_id → current_claim_version_id`，只允许 exact-head CAS：

```text
UPDATE succeeds only when current_claim_version_id = expected_version_id
```

### `version_transition`

append-only，记录 old/new version、transition type、proposal、decision、时间和 commit sequence。创建 V1 时不得生成虚构的 old version。

### `grounding_relation`

必须能够表示：

```text
ClaimVersion ↔ Evidence: SUPPORTS | CONTRADICTS | DERIVED_FROM
OpenIssue    ↔ Evidence: SUPPORT_BRANCH | CONTRADICT_BRANCH | RESOLUTION_CANDIDATE
Claim/OpenIssue dependency: DEPENDS_ON when frozen architecture permits
```

可物理拆表，但 API 和评测必须使用统一 relation 语义。

### `grounding_block`

记录 Evidence 撤销、权限不明、retention 不可读或关键依赖失效导致的阻断。Block 不得直接物理删除；恢复必须指向新 Evidence、新 ClaimVersion、TX-06 和 StewardDecision。

### `effective_claim_state`

实现为 view、SQL function 或受测 repository 均可，但必须统一计算：

```text
ClaimHead
+ requested historical version
+ Evidence revocation
+ live GroundingBlock
+ Scope match
+ valid time
+ epistemic/freshness
+ required authority
= EffectiveClaimState
```

API、Retrieval、Context 和 Steward 不得各自复制一套不一致的 current-state 判断。

## 5.4 Control Plane

### `operation_proposal`

至少包含：

```text
tenant_id
proposal_id
target_claim_id nullable
operation
expected_version_id nullable
proposed_patch
supporting_evidence_refs
contradicting_evidence_refs
scope_predicate
requested_authority
derivation policy/model/template/snapshot
proposer_actor_id
canonical_commit_authorized = false
status
idempotency_key / request_fingerprint
```

### `steward_decision`

append-only，至少包含：

```text
tenant_id
decision_id
proposal_id
decision: APPROVE | REJECT
decision_actor_type: POLICY | USER | STEWARD
decision_actor_id
policy_version
reason_code
decided_at
resulting_claim_version_id nullable
resulting_open_issue_id nullable
canonical_commit_seq nullable
```

`REQUEST_USER_CONFIRMATION` 和 `DEFER` 是 proposal workflow 状态，不伪造 APPROVE/REJECT 决定。提交结果可作为 StewardDecision 的结果字段或独立 `commit_result` 表实现，不得与 `commit_decision` 再建同义事实源。

## 5.5 OpenIssue

`open_issue` 至少包含：

```text
tenant_id
issue_id
target_claim_id nullable
issue_type
status
revision
scope_predicate
discharge_rule
required_authority
created_from_proposal_id
resolved_by_decision_id nullable
resolved_at nullable
```

Issue 的每次状态变化必须使用 revision CAS，并产生 append-only transition 或等价的 canonical OperationalEvent。正反 Evidence branch 必须通过结构化 relation 保存，不能只放在自然语言描述中。

## 5.6 Integration、Context 与 Trace

Lean 在线最小集合还必须包含：

| 对象 | 必需语义 |
| --- | --- |
| `outbox_event` | 与 canonical transaction 原子提交的投影或清理事件 |
| `index_watermark` | 每个 projection 独立、不能跨 dead-letter gap 推进 |
| `search_document` | FTS 派生表示，携带 canonical ID/version/commit sequence |
| `search_embedding` | 带模型、维度和 projection version 的向量表示 |
| `context_capsule` | 可选持久化、带 TTL 的当前工作集 |
| `retrieval_trace` | query plan、snapshot、route、watermark、reject、fallback |
| `operational_event` | 不含敏感正文的运行、权限和故障事件 |

`audit_record` 只存在于隔离 Audit 域，不进入在线 Runtime 写凭据。

---

# 6. 操作与事务合同

## 6.1 产品结果到内部操作的映射

| 产品级结果 | 内部 OperationProposal | Canonical 行为 |
| --- | --- | --- |
| `CREATE` | `CREATE` | TX-02 创建 Claim、V1、Head |
| `UPDATE` | `SUPPORT` | TX-03 创建更强 grounding 的新版本 |
| `UPDATE` | `WEAKEN` | TX-03 创建降低 epistemic/authority 的新版本 |
| `UPDATE` | `REVALIDATE` | TX-03 创建经新 Evidence 重验的版本 |
| `UPDATE` | `REGROUND` | TX-06 以新 Evidence 恢复 grounding |
| `UPDATE` | `SUPERSEDE` | TX-03 创建替代当前值的新版本 |
| `UPDATE` | `CONTEXTUALIZE` | TX-03 创建收窄或明确 Scope 的新版本 |
| `CONFLICT` | `CONTRADICT` | 默认 TX-04 保持 Head，并创建/更新 OpenIssue |
| `NO_CHANGE` | `NO_CHANGE` | TX-04 记录判断，不移动 Head |

`UPDATE` 不能直接出现在数据库 operation 字段中；必须先选择一个精确的内部 operation。`SPLIT` 可以保留在接口 enum 中，但 Lean Runtime 必须返回 `OPERATION_NOT_ENABLED`。

## 6.2 CommitPolicy 映射

| CommitPolicy 结果 | 持久行为 |
| --- | --- |
| `AUTO_COMMIT` | 由版本化 policy actor 产生 APPROVE StewardDecision，再执行 TX |
| `USER_REVIEW` | Proposal 保持 pending；产生 review event，不提交 Claim |
| `REJECT` | 产生 REJECT StewardDecision，不改变 ClaimHead |
| `NO_CHANGE` | 建立/复用 NO_CHANGE proposal，经允许后执行 TX-04 |

自动提交只允许同时满足：

```text
INFORMATIONAL
low-risk policy class
Scope 明确
Evidence live and permitted
无 live conflict/OpenIssue
无 authority escalation
expected head 当前有效
```

以下情况必须进入用户或 Steward 审核：

```text
ACTION_SAFE
全局或显著扩大 Scope
用户身份、健康、资产、关系等敏感信息
现有 Claim 冲突
OpenIssue discharge
Evidence revoke / deletion
authority escalation
```

## 6.3 TX-01 Evidence Ingest

同一事务必须完成：

```text
idempotency claim
→ create/reuse tenant-scoped ContentBlob
→ create independent EvidenceRecord
→ allocate outbox_sequence；canonical_commit_seq 保持 NULL（Evidence 不是 belief commit）
→ OperationalEvent
→ OutboxEvent
→ commit
```

事务中不得调用 LLM、embedding 服务或远程存储推理 API。

## 6.4 TX-02 Claim Create

前置条件：

```text
expected_version_id = null
target Claim identity 尚不存在或 absence-CAS 成功
至少一条 live admissible Evidence
ValidatedProposal
APPROVE StewardDecision
```

同一事务创建 Claim、V1、grounding relation、ClaimHead、decision result、OpenIssue effect 和 OutboxEvent。

## 6.5 TX-03 Claim Revision

前置条件：`expected_version_id` 必须等于当前 Head。事务必须：

```text
insert immutable Vn+1
insert VersionTransition
insert new GroundingRelation
CAS ClaimHead Vn → Vn+1
apply governed OpenIssue effect
insert OutboxEvent
```

CAS 失败时整个事务回滚并返回 `VERSION_CONFLICT`。

## 6.6 TX-04 No Change / Conflict Preserve

TX-04 可以记录：

- proposal 已检查但没有足够条件更新；
- 新 Evidence 与当前 Claim 冲突；
- Scope 或 authority 仍不明确；
- 用户审核被请求或决定延期。

TX-04 禁止创建 ClaimVersion、VersionTransition 或移动 ClaimHead；可以原子创建/更新 OpenIssue 和相应 branch relation。

## 6.7 TX-05 Evidence Revoke

同一事务必须：

```text
authorize request
→ mark Evidence revoked
→ locate directly dependent ClaimVersions/OpenIssues
→ create live GroundingBlock
→ invalidate resident Context pointers
→ emit purge/re-ground OutboxEvents
→ OperationalEvent
→ commit
```

同步事务只负责立即失去可用 authority；物理 blob、FTS、vector 和备份清理可以异步完成。

## 6.8 TX-06 Grounding Restore

只有新 admissible Evidence 和 APPROVE StewardDecision 可以恢复 grounding。TX-06 必须创建新的 ClaimVersion；不得仅删除 GroundingBlock 或重新启用旧版本。

---

# 7. OpenIssue 状态机

## 7.1 类型

Lean V1 至少支持：

```text
CONFLICT
MISSING_EVIDENCE
SCOPE_UNCERTAIN
AUTHORITY_UNCERTAIN
DEPENDENCY_INVALIDATED
```

## 7.2 状态

```text
OPEN
WAITING_EVIDENCE
WAITING_USER
READY_FOR_REVIEW
RESOLVED
DISMISSED
```

## 7.3 合法迁移

| 当前状态 | 事件 | 下一状态 |
| --- | --- | --- |
| 新建 | 需要外部证据 | `WAITING_EVIDENCE` |
| 新建 | 需要用户确认 | `WAITING_USER` |
| `OPEN/WAITING_*` | 收到候选 Evidence | `READY_FOR_REVIEW` 或保持原状态 |
| `READY_FOR_REVIEW` | discharge 检查通过且 APPROVE | `RESOLVED` |
| 任一非终态 | 治理性判定问题不适用 | `DISMISSED` |
| `RESOLVED` | resolution Evidence 被撤销 | `OPEN` 或 `WAITING_EVIDENCE`，保留原 issue ID |

所有迁移必须：

- 使用 `expected_issue_revision` CAS；
- 保存 actor、proposal、decision、Evidence 和 policy version；
- 与相关 Claim transaction 原子提交；
- 保留历史 transition；
- 失败重试不重复迁移。

## 7.4 DischargeRule

最小结构：

```json
{
  "rule_version": "1",
  "required_evidence_kinds": ["RUNTIME_OBSERVATION"],
  "required_scope": {"project_ids": ["milai"]},
  "required_authority": "ACTION_SAFE",
  "minimum_independent_sources": 1,
  "must_address_branches": ["SUPPORT_BRANCH", "CONTRADICT_BRANCH"],
  "review_required": true
}
```

满足字段结构不等于自动解决。Validator 只判断确定性条件，CommitPolicy/Steward 负责治理决定。

以下行为永远不能关闭 OpenIssue：

```text
被摘要省略
Context 被回收
某一 branch 检索不到
模型输出单值结论
时间经过
向量相似度更高
旧 resolution Evidence 已撤销
```

---

# 8. Retrieval 与 Context 合同

## 8.1 QueryPlan

```yaml
intent: string
entities: []
time_constraint: null
scope_predicate: {}
required_authority: INFORMATIONAL
require_user_confirmation: false
complexity: L0
consistency_mode: EVENTUAL
minimum_outbox_sequence: null
context_budget: 8000
routes: []
```

QueryPlan 必须由受版本控制的确定性规则加可选模型解释生成。模型输出必须通过 Schema 校验；失败时回退到安全的 L0/L1 默认计划。

## 8.2 路线

### L0 Exact / Current

用于当前状态、精确实体、编号和已确认信息。直接查询 subject、predicate、scope、ClaimHead 和 EffectiveClaimState，不依赖向量索引。

### L1 Hybrid

```text
metadata/time/scope pre-filter
→ PostgreSQL FTS + pgvector
→ score normalization
→ deduplicate by canonical ID/version
→ Canonical Gate
→ Evidence Bundle
```

### L2 Reconstructive

只用于复杂时间、来源、冲突或多跳问题。Lean V1 在 L0/L1 稳定前默认关闭 L2 自动升级；显式启用时仍不得依赖 Graphiti。

## 8.3 Canonical Gate

每个 candidate 必须检查：

```text
tenant and subject
permission and retention readability
Evidence revocation
current or explicitly requested historical version
GroundingBlock
Scope predicate
valid time
epistemic/freshness state
OpenIssue/conflict state
required authority
Evidence lineage
```

未知 ID、跨 tenant、无 lineage、已撤销或无法读取 retention 状态的 candidate 必须拒绝。索引故障只能降低 recall，不能降低 gate。

## 8.4 Consistency

| Mode | Lean 行为 |
| --- | --- |
| `EVENTUAL` | 可使用落后索引，必须记录 watermark 和 degraded 状态 |
| `READ_YOUR_WRITES` | 等待目标 watermark；超时后由 canonical lane 补齐 |
| `CANONICAL_REQUIRED` | 当前状态、权限、删除和 action-safe 查询只使用 canonical ECS |

Canonical store 不可用时，要求 authority 的回答必须 abstain；不得用缓存或 shadow 伪装为当前正式状态。

## 8.5 Minimal ContextCapsule

固定分区：

```text
[1] ACTIVE GOAL
[2] ACTIVE STATE
[3] OPEN ISSUES
[4] CONSTRAINTS
[5] RETRIEVED EVIDENCE
[6] TRACE POINTERS
```

最小规则：

- Goal、硬约束、当前 ECS 和 live OpenIssue 是 protected items；
- 每个 OpenIssue 保留 issue ID、target、status、branch refs 和 discharge rule；
- 大型正文和工具日志优先替换成带 hash、权限和 retention 校验的 pointer；
- Context 不能创建 Evidence 或 canonical mutation；
- 压缩失败时回退到 canonical minimal capsule 或明确 `CONTEXT_BUDGET_INFEASIBLE`；
- ContextBackend 故障不能改变 Claim/OpenIssue 状态。

Lean 产品默认使用 `LocalStructuredContextBackend`。ReMe/OpenViking 只在离线对照中使用。

---

# 9. 删除、权限与故障关闭

## 9.1 删除状态

API 和 UI 必须区分：

```text
logical_revocation
canonical_block_applied
derived_purge_progress
primary_bytes_erased
backup_expiry_pending/completed
legal_hold_or_retention_block
```

不得用“已删除”一个状态掩盖仍在异步传播的副本。

## 9.2 同步正确性

TX-05 提交后，即使 FTS、pgvector 或缓存仍含 stale bytes：

- candidate 必须被 Canonical Gate 拒绝；
- 依赖 Claim 不得满足 `ACTION_SAFE`；
- Context 中的 active pointer 必须失效；
- 无法判断权限或 retention 时 fail closed。

## 9.3 物理清理

后台 worker 负责：

```text
FTS purge
pgvector purge
Context artifact purge
eligible blob erase
future adapter purge when enabled
backup expiry tracking
```

共享 Blob 仍被 live Evidence 引用时不得物理删除。每个清理动作必须幂等、可重试并产生 trace。

---

# 10. Outbox 与 Worker

## 10.1 投影范围

Lean Worker 只处理：

```text
FTS projection
pgvector projection
Context pointer invalidation
deletion/purge
settlement background jobs when enabled
```

不建设 Kafka、通用 Projection Registry 或多个 memory database。

## 10.2 状态机

```text
PENDING
→ PROCESSING with lease
→ DELIVERED
→ PENDING with bounded backoff
→ DEAD_LETTER
```

必须保证：

1. `outbox_id` 或确定性 downstream key 幂等；
2. 同一 aggregate 内保序；
3. durable projection 后才推进 watermark；
4. dead-letter gap 未修复前不得越过；
5. crash、lease timeout 和重复投递可恢复；
6. Worker 无 Claim/OpenIssue canonical DML 权限；
7. embedding model 或维度变化创建新的 projection version。

删除和权限失效任务优先级高于普通 embedding 补建。

---

# 11. 最小 API 合同

## 11.1 Evidence

```text
POST /v1/evidence
GET  /v1/evidence/{evidence_id}
GET  /v1/evidence/{evidence_id}/lineage
POST /v1/evidence/{evidence_id}/revoke
GET  /v1/deletions/{request_id}
```

外部请求中的 tenant 必须来自认证上下文。若 body 为兼容目的携带 `tenant_id`，必须与认证 tenant 完全相等，否则返回 `TENANT_MISMATCH`；绝不能信任 body 切换 tenant。

## 11.2 Claim、Proposal 与 Issue

```text
POST /v1/proposals
GET  /v1/proposals/{proposal_id}
POST /v1/proposals/{proposal_id}/review
GET  /v1/claims/{claim_id}
GET  /v1/claims/{claim_id}/versions
GET  /v1/open-issues
GET  /v1/open-issues/{issue_id}
```

Lean UI 不展示暂停的 MemoryIntention 队列。

## 11.3 Retrieval、Context 与 Chat

```text
POST /v1/memory/query
GET  /v1/retrieval-traces/{trace_id}
POST /v1/chat
GET  /v1/system/watermarks
GET  /v1/system/degraded-routes
```

关键回答至少返回：

```json
{
  "answer": "...",
  "claim_refs": [],
  "evidence_refs": [],
  "open_issue_refs": [],
  "retrieval_trace_id": "...",
  "consistency_mode": "CANONICAL_REQUIRED",
  "degraded": false,
  "abstained": false
}
```

## 11.4 统一错误

至少定义：

```text
AUTHENTICATION_REQUIRED
AUTHORIZATION_DENIED
TENANT_MISMATCH
IDEMPOTENCY_CONFLICT
VERSION_CONFLICT
ISSUE_REVISION_CONFLICT
EVIDENCE_REVOKED
GROUNDING_BLOCKED
SCOPE_MISMATCH
SCOPE_TIME_CONFLICT
AUTHORITY_INSUFFICIENT
OPERATION_NOT_ENABLED
CANONICAL_UNAVAILABLE
CONTEXT_BUDGET_INFEASIBLE
PROJECTION_DEGRADED
```

---

# 12. 本地部署与安全边界

## 12.1 默认网络面

Lean V1 默认：

```text
single local user
single configured tenant
API binds to loopback
PostgreSQL not exposed publicly
Nginx/FRP public route disabled
```

只要启用公网域名、FRP、家庭账号或远程设备，即超出 Lean 默认边界，必须先完成独立 Remote Access Gate：

```text
TLS termination
strong authentication and secure session
device/session revocation
CSRF/CORS/cookie policy
rate limit
secret rotation
security logging
backup and incident procedure
```

## 12.2 基础 tenant 隔离

即使只运行一个 tenant，Lean V1 仍必须：

- 所有 tenant-owned row 带 `tenant_id`；
- 数据库 session 明确设置并在连接归还时清除 tenant/actor context；
- 使用基本 RLS 和真实 login role 负向测试；
- 禁止客户端任意指定 tenant；
- 为未来迁移保留 tenant-scoped unique key。

复杂家庭 sharing grant、成员角色和跨设备授权推迟，不等于取消基础 RLS。

## 12.3 数据库角色

至少分离：

| Role | 权限 |
| --- | --- |
| migration owner | DDL，只在部署迁移时使用 |
| API runtime | Evidence/API 所需最小权限，无 canonical table ownership |
| Steward executor | 只能 execute 受控 canonical procedures |
| Projection worker | 读 Outbox、写自己的 projection/watermark |
| Audit runner | 只读授权 snapshot、写 AuditRecord，不能 Production commit |

应用进程不得使用 migration owner 凭据。

## 12.4 日志隐私

结构化日志默认只记录 ID、hash、状态、耗时和 reason code。禁止记录：

```text
完整用户消息
完整 Evidence 正文
密钥和 token
密码/session cookie
未脱敏的模型 Prompt
敏感 Profile 推断
```

需要调试正文时必须使用显式、短期、可审计的本地开关。

---

# 13. OSPC 离线研究合同

## 13.1 状态

```text
Research question: pending
Novelty: unvalidated
Production dependency: no
Default online integration: disabled
```

研究问题：在相同总上下文预算下，保护 OpenIssue identity、正反 Evidence lineage 和合法 discharge 条件，是否降低 compression-induced false epistemic closure，并改善后续任务。

## 13.2 输入与输出

输入：

```text
immutable Episode/Evidence snapshot
current canonical Claim state
OpenIssue set and branch relations
dependency graph
current goal
token budget B
tokenizer/model/prompt version
```

输出必须使用结构化 Schema：

```json
{
  "status": "OK",
  "stable_state": [],
  "open_issues": [],
  "evidence_pointers": [],
  "evicted_recoverable": [],
  "compression_trace": {}
}
```

## 13.3 预算可行性

先计算：

```text
B_min = 所有 live OpenIssue 的最小无损保护表示
      + 必需 Goal/Constraint
      + branch 和 Evidence pointer
      + discharge rule
```

当 `B < B_min`：

- 返回 `INFEASIBLE_UNDER_BUDGET`；
- 不得伪造满足 `FalseClosure=0`；
- 可以回退到 abstention 或请求增加预算；
- 评测必须报告 infeasible rate，不能删除该样本。

## 13.4 Equal-Budget 协议

所有方法必须使用：

```text
same immutable snapshot
same tokenizer
same downstream model and fixed prompt
same initial retrieval access
same total method-controlled token budget
same maximum recovery/tool calls
```

主比较预算定义为：

```text
total charged tokens
= initial compressed context tokens
+ recovered source tokens
+ method-added structured metadata
```

同时记录 compression latency、模型调用、recovery calls、fallback、CPU/GPU 和 wall time。若另做“初始 prompt budget、恢复免费”的实验，必须单独报告，不能与主结果混合。

## 13.5 指标定义

至少分别测量：

```text
Representation False Closure
Decision False Closure
OpenIssue Identity Recall
Conflict Branch Recall
Discharge Rule Recall
Legal Discharge Accuracy
Authority Escalation Rate
Later-Episode Task Success
Unsupported Claim Rate
```

判定原则：

- raw snapshot 中 issue 非 `RESOLVED/DISMISSED`，压缩表示却省略、标记已解决或生成无条件单值结论，记为 representation false closure；
- 在新 admissible Evidence 出现前，下游任务按“问题已解决”行动，记为 decision false closure；
- 只保留 issue ID 但丢失 target、status、任一 live branch 或 discharge 条件，不算完整 preservation；
- scorer 必须使用冻结 fixture label 或独立标注，不能由被测方法自评。

## 13.6 Pilot 与正式数据

Artifact Gate 的 30–50 个 fixture 只是测量可行性 pilot，不是论文规模结论。正式评测必须另行冻结：

```text
train/dev/test or prompt-development/test separation
synthetic vs real episode proportion
two-domain distribution
annotation protocol and disagreement handling
privacy/de-identification
seed and model version
failure-case taxonomy
```

优先双域：Software Project Memory 与 Personalized Multi-Session Assistant。

## 13.7 Baseline 与消融

最低 baseline：

```text
full raw context where budget permits
naive recursive summary
extractive top-K
hierarchical summary
structured context eviction
typed state summary with OpenIssue fields
static keep-all-open-issues
equal-token oracle selection
ReMe/OpenViking only when runnable and version-pinned
```

最低消融：

```text
without protected subgraph
without discharge rule
without conflict-branch preservation
without validator/fallback
```

外部 baseline 必须固定仓库 commit、依赖版本、许可证快照和 adapter 配置。

## 13.8 Research Go/No-Go

出现以下任一结果，停止算法 novelty 主张：

1. 强 typed-state/structured-eviction baseline 在等预算下达到相同结果；
2. 简单保留 OpenIssue 字段与完整方法等价；
3. 增益来自更多 token、更多 recovery、oracle label 或更强模型；
4. preservation 不改善后续任务或合法 discharge；
5. 真实 Episode 没有可重复差异；
6. validator/fallback 成本抵消收益；
7. prior art 已包含相同机制和评测。

只有产品指标、研究指标和 novelty audit 同时通过后，才可以提议把 OSPC 接入默认 ContextBackend。

---

# 14. 测试合同

## 14.1 数据库与事务

必须使用真实 PostgreSQL connection 和真实 login role 测试：

```text
CREATE absence-CAS race
revision exact-head CAS race
OpenIssue revision CAS race
idempotency replay
idempotency fingerprint conflict
NO_CHANGE creates no version
CONFLICT preserves current head
SPLIT fails closed
old ClaimVersion byte immutability
non-Steward commit denied
Steward direct DML denied
cross-tenant SELECT/write denied
Outbox atomic rollback
dead-letter watermark gap
```

## 14.2 删除与权限

```text
revoke immediately blocks ACTION_SAFE
stale FTS/vector candidate rejected
shared Blob not prematurely erased
unreadable retention fails closed
TX-06 requires new admissible Evidence
Context pointer invalidated
purge retry idempotent
```

## 14.3 Retrieval 与 Context

```text
L0 independent of vector index
unknown/cross-tenant/wrong-scope candidate rejected
READ_YOUR_WRITES canonical fallback
CANONICAL_REQUIRED abstains on DB failure
OpenIssue identity and branches survive recursive compression
pointer hash/permission/retention validation
budget infeasibility explicit
```

## 14.4 E2E 纵向用例

至少冻结以下 Python 版本冲突用例：

```text
E1: deployment evidence says Python 3.11
→ M1 V1 ACTION_SAFE

E2: pyproject says >=3.12
→ CONTRADICT
→ OpenIssue with both branches
→ Head remains V1 / action response shows conflict as policy requires

E3: CI and production runtime both report 3.12
→ READY_FOR_REVIEW
→ APPROVE SUPERSEDE
→ M1 V2
→ governed OpenIssue resolution

revoke E3 runtime evidence
→ GroundingBlock
→ issue reopens
→ stale index cannot return action-safe 3.12
```

每一步必须能回放 proposal、decision、version、Evidence、issue transition、outbox 和 retrieval trace。

---

# 15. 发布门禁

本合同使用 `LG-*`，避免与尚未导入的冻结架构 G1–G9 混淆。

| Gate | 条件 | 结果 |
| --- | --- | --- |
| `LG-00 Architecture Crosswalk` | 自研 candidate bundle 完整；逐条映射对象、权限和 invariant | 才可进入 freeze review |
| `LG-01 Runtime` | API、Worker、PostgreSQL 可重复启动，配置 fail-fast | Runtime scaffold complete |
| `LG-02 Canonical Core` | TX-01～TX-06、CAS、immutability、roles、RLS 测试通过 | Canonical candidate complete |
| `LG-03 Vertical Slice` | Evidence→Claim/OpenIssue→L0 query 可回放 | Core functional |
| `LG-04 Retrieval` | FTS+pgvector、canonical gate、watermark/fallback 通过 | Core Alpha candidate |
| `LG-05 Context` | Minimal capsule、pointer recovery、OpenIssue preservation 通过 | Context candidate |
| `LG-06 Deletion` | fail-closed、purge、shared blob、backup 状态通过 | Safety candidate |
| `LG-07 Local Beta` | Chat、trace、纠正、删除、备份恢复和脱敏回归通过 | Local Beta candidate |
| `RG-00 Artifact` | scorer、30–50 pilot fixtures、强 baseline 可复现 | 可开始 OSPC prototype |
| `RG-01 Equal Budget` | 预算、成本、消融和失败分布完整 | 可进入 novelty audit |
| `RG-02 Novelty` | 未被最强 absorber/prior art 吸收 | 才形成 paper candidate |

任一情况立即阻止发布：

```text
canonical invariant violation
cross-tenant exposure
deletion fail-open
untraceable authority-bearing answer
outbox unrecoverable gap
adapter direct canonical write
compression closes live OpenIssue
idempotent retry duplicates canonical state
concurrent revisions both move Head
canonical unavailable but system pretends certainty
```

性能 SLA 只能在实际设备和 workload baseline 后冻结，不在本文编造数值。

---

# 16. Lean V1 活跃任务顺序

```text
LC-001  实现自研 Logical Architecture bundle、crosswalk、validator 和 freeze review
LC-002  Runtime scaffold、配置、PostgreSQL 和 Migration harness
LC-003  tenant context、DB roles、基础 RLS 和负向测试
LC-004  ContentBlob、EvidenceRecord 和 TX-01
LC-005  Claim、ClaimVersion、ClaimHead、VersionTransition
LC-006  GroundingRelation、GroundingBlock、EffectiveClaimState
LC-007  OperationProposal、validator、StewardDecision
LC-008  TX-02/TX-03/TX-04/TX-06 与并发/幂等测试
LC-009  OpenIssue 状态机、branch relation 和 revision CAS
LC-010  TX-05 revoke、Context invalidation 和 purge workflow
LC-011  Outbox worker、watermark、FTS projection
LC-012  pgvector projection 和 embedding versioning
LC-013  QueryPlan、L0、L1 和 Canonical Gate
LC-014  RetrievalTrace、degraded/abstention 行为
LC-015  LocalStructuredContextBackend 和 pointer recovery
LC-016  Chat API、最小 UI、纠正/确认/删除流程
LC-017  Episode capture 和不依赖 MemoryIntention 的最小 Settlement
LC-018  backup/restore、运行检查和 Local Beta 报告

RC-001  open-state fixture schema 和标注协议
RC-002  false-closure/discharge scorers
RC-003  naive/extractive/typed-state baselines
RC-004  protected subgraph prototype
RC-005  budget allocator、validator 和 infeasible handling
RC-006  equal-budget ablation
RC-007  prior-art/absorber audit
RC-008  go/hold/abandon decision
```

产品任务 `LC-*` 与研究任务 `RC-*` 使用不同数据库角色、数据输出和发布决策。OSPC 失败不能阻止 Lean Product Core 发布。

---

# 17. 候选决定与未完成门

以下事项必须由 ADR/crosswalk 显式定义；仍未完成的实施门不得被文档决定替代：

1. authority 非全序匹配由 ADR-008 定义；
2. G1–G9/I-01～I-12 machine crosswalk 与 frozen lock 已建立；candidate.1–4 的 AF-09
   决定均为 `REVISE`，candidate.5 已 `ACCEPT` 并提升为 `architecture/v1.0/`；
3. `grounding_relation` v1 单表 XOR owner 由 ADR-004 定义；
4. OpenIssue revision + transition 由 ADR-006 定义；
5. canonical/outbox 双 sequence 由 ADR-009 与 migration 0014 定义；
6. Blob envelope/key 由 ADR-012 定义，但真实数据前实现/轮换/恢复仍未完成；
7. 模型/embedding/device baseline 由 ADR-013 定义，性能阈值未冻结；
8. legacy/real-data protocol 由 ADR-014 定义，source-specific mapping 未执行；
9. OSPC 已按 hard falsifier ABANDON novelty，产品隔离继续有效。

每项决定必须以 ADR、版本、测试和回滚说明关闭。

---

# 18. Definition of Done

MiLAi Lean V1 只有在以下事实同时成立时才算完成：

1. 原始 Evidence 可回放且不等于系统 belief；
2. ClaimVersion 不可变，当前 Head 通过 CAS 演化；
3. 冲突不会自动覆盖，OpenIssue identity、branches 和 discharge rule 可追溯；
4. 所有 Claim 写入都经过 Proposal、Validator、Decision 和受控 procedure；
5. L0/L1 候选进入 Context 前都经过统一 Canonical Gate；
6. 索引失效只降低 recall，不提高 authority；
7. Evidence revoke 同事务触发 fail-closed，异步副本可追踪清理；
8. Context、Summary、模型和外部 backend 都不能制造 canonical truth；
9. 本地单 tenant 仍通过真实 role 和 RLS 负向测试；
10. 关键回答能返回 Claim、Evidence、OpenIssue 和 RetrievalTrace；
11. Canonical 不可用或证据不足时系统明确 abstain；
12. Runtime 不依赖 ReMe、Hindsight、Graphiti、MemoryIntention 或 OSPC；
13. 自研架构 bundle/crosswalk/validator/freeze review 完成前，不宣称 Schema frozen；
14. OSPC 只在等预算、强 baseline、成本和 hard falsifier 下形成研究结论。

最终交付叙事保持为：

```text
Product:
MiLAi is an evidence-first, versioned and conflict-aware personal memory system.

Research candidate:
Can open-state-preserving compression reduce false epistemic closure
under equal total context budgets?
```
