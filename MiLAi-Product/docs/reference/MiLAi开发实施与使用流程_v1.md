# MiLAi 开发实施与使用流程 v1.0

> **2026-08-16 架构更新：** Logical Architecture 改为由 MiLAi 项目自行设计和实现；当前
> candidate 见 `MiLAi_Logical_Architecture_v1_设计文档.md`。本文中旧的“既有 frozen
> architecture”措辞仅保留为历史流程背景。

> 文档类型：配套实施手册，非规范性实现展开  
> 上位需求：`MiLAi技术升级需求说明_v2.md`  
> 逻辑架构：MiLAi Logical Architecture `1.0.0 FROZEN`  
> 数据 Schema：`0.1.x EXPERIMENTAL`  
> 当前实施门：`CANDIDATE / NO-GO FOR DB FREEZE`  
> 编制日期：2026-08-11

本手册把 MiLAi 的架构设计展开为可执行的开发顺序、测试门、运行方式和日常使用流程。它不修改六个核心对象、两条派生路径、单写者原则或 12 条冻结 invariant。若本文与 `C:\Users\Mingx\Documents\mila\architecture\v1.0` 冲突，以冻结架构为准。

近期开发优先级以 [`MiLAi_Lean_V1_产品底座与研究核心.md`](./MiLAi_Lean_V1_产品底座与研究核心.md) 为准。本手册继续保存长期完整路线；其中 ReMe、Hindsight、Graphiti、Memory Intention、Scope Evolution 和 Multi-Agent 相关阶段目前暂停，不属于 Lean V1 的完成条件。

当前 `C:\Users\Mingx\Documents\mila` 已有冻结架构、实验性 Schema、验证器和测试，但尚未形成生产 Runtime。本流程从 Runtime 脚手架开始，不假定已经存在可运行的 MiLAi 服务。

---

# 1. 最终要交付什么

第一个可用版本应交付一个本地优先的模块化单体，而不是一组相互依赖的微服务：

```text
MiLAi Runtime
├─ Flask API
├─ Canonical Memory Core
├─ Retrieval Service
├─ Context Service
├─ Outbox Worker
├─ Memory Steward Workflow
└─ Audit/Evaluation Runner

Infrastructure
├─ PostgreSQL
├─ PostgreSQL FTS
├─ pgvector
├─ Local/Object Blob Store
└─ Optional External Adapters
   ├─ ReMe
   ├─ Hindsight
   └─ Graphiti
```

首个可用版本必须在不安装 ReMe、Hindsight、Graphiti 的情况下完成以下闭环：

```text
Evidence Ingest
→ Governed Claim Commit
→ Exact/Hybrid Retrieval
→ ContextCapsule
→ Episode Settlement
→ Deletion/Revocation
→ Audit Trace
```

外部项目只能增强召回、上下文组织或时间关系查询，不能成为 Runtime 正确性的前置条件。

---

# 2. 开发中不可突破的边界

1. PostgreSQL Canonical Core 是唯一正式状态来源。
2. `EvidenceRecord` 表示观察，不表示系统已经接受该事实。
3. `ClaimVersion` 只新增版本，不原地覆盖。
4. `ContextCapsule` 不是 Evidence，也不能触发 canonical commit。
5. `OpenIssue` 与 `MemoryIntention` 是两个不同对象。
6. `OperationProposal` 只是写入建议，不是正式状态。
7. 只有 Memory Steward 的受控 procedure 可以提交 Claim 状态变化。
8. confidence、authority、freshness、epistemic status 分别存储和判断。
9. Scope 是条件谓词，不是简单的 session/project/domain 等级。
10. Evidence 撤销必须先同步阻断 action-safe 使用，再异步清理派生副本。
11. Production 运行记录与 Audit 实验记录物理或权限隔离。
12. ReMe、Hindsight、Graphiti、Mem0 等永远不持有 canonical 写凭据。

如果某项实现需要绕过这些边界，必须停止实现并回到架构层处理，不能用临时代码静默改变语义。

---

# 3. 推荐代码结构

在 `C:\Users\Mingx\Documents\mila` 下新增 `runtime`，保留 `architecture` 和 `paper` 不变：

```text
mila/
├─ architecture/                 # 已冻结的逻辑与实现合同
├─ paper/                        # 文献库
└─ runtime/
   ├─ pyproject.toml
   ├─ .env.example
   ├─ compose.yaml
   ├─ alembic.ini
   ├─ migrations/
   ├─ src/milai/
   │  ├─ api/                    # Flask routes、认证、请求边界
   │  ├─ domain/                 # 六对象语义、值对象、错误类型
   │  ├─ application/
   │  │  ├─ ingest/
   │  │  ├─ state_derivation/
   │  │  ├─ steward/
   │  │  ├─ retrieval/
   │  │  ├─ context/
   │  │  ├─ settlement/
   │  │  └─ deletion/
   │  ├─ persistence/
   │  │  ├─ models/
   │  │  ├─ repositories/
   │  │  ├─ procedures/
   │  │  └─ effective_state/
   │  ├─ adapters/
   │  │  ├─ embeddings/
   │  │  ├─ reme/
   │  │  ├─ openviking/
   │  │  ├─ hindsight/
   │  │  └─ graphiti/
   │  ├─ workers/
   │  │  ├─ outbox/
   │  │  ├─ purge/
   │  │  └─ settlement/
   │  ├─ observability/
   │  └─ config/
   ├─ tests/
   │  ├─ unit/
   │  ├─ contract/
   │  ├─ integration/
   │  ├─ concurrency/
   │  ├─ failure/
   │  ├─ security/
   │  └─ e2e/
   ├─ evals/
   ├─ scripts/
   └─ docs/
```

第一阶段只运行三个进程：

```text
milai-api
milai-worker
postgres
```

Scheduler 可以先作为 Worker 内部周期任务。只有出现独立扩缩容需求后才拆分服务。

---

# 4. 推荐基础技术栈

| 能力 | 建议 |
| --- | --- |
| API | Flask，保持与当前设计一致 |
| ORM/SQL | SQLAlchemy + psycopg；关键事务使用显式 SQL/procedure |
| Migration | Alembic |
| 数据验证 | JSON Schema + Pydantic 或等价边界模型 |
| Canonical Store | PostgreSQL |
| 字面检索 | PostgreSQL FTS |
| 语义检索 | pgvector |
| Blob | V1 本地 content-addressed store；接口兼容 S3-compatible storage |
| 后台任务 | PostgreSQL Outbox Worker；V1 不强制 Kafka/RabbitMQ |
| 测试 | pytest + 现有 unittest 架构测试 |
| 运行 | Docker Compose 提供 PostgreSQL；Python服务本地运行或容器运行 |
| 日志 | JSON structured log + correlation ID |
| 密钥 | 环境变量或本地 secret store，不写入仓库 |

依赖版本必须在 `pyproject.toml` 和 lock file 中固定。开发机、测试和生产使用相同 Python minor version，不依赖系统全局 Python 包。

---

# 5. 项目在开发流程中的位置

| 接口 | 默认实现 | 进入时间 | 生产权限 |
| --- | --- | --- | --- |
| Canonical Core | PostgreSQL | Step 2 | 唯一正式状态 |
| L1 Retrieval | PostgreSQL FTS + pgvector | Step 6 | 只返回候选；最终经过 canonical gate |
| ContextBackend | 自研 ContextCapsule | Step 7 | 不能提交 Claim |
| ContextBackend 对照 | ReMe | Step 7 后 | 不能提交 Claim |
| ContextBackend 实验 | OpenViking | ReMe 对照完成后 | 默认关闭 |
| ShadowMemoryBackend | Hindsight | Step 10 | 只返回 candidate/proposal |
| Shadow baseline | Mem0、MemOS、EverMemOS | Evaluation 环境 | 不接 Production 写路径 |
| TemporalGraphBackend | Graphiti | Step 11 | 只返回时间关系 candidate |
| 托管替代 | Zep | 需要托管部署时 | 与 Graphiti 二选一 |
| RetrievalPolicy | 自研确定性 Router | Step 6 | 输出 QueryPlan |
| Policy 实验 | SelRoute、RF-Mem、TA-Mem、MRAgent | Step 12 | Audit 环境先验证 |
| EvaluationAdapter | LongMemEval、HorizonBench、Memora、MemConflict | Step 12 | 只写 AuditRecord |

禁止第一天同时部署 ReMe、OpenViking、Hindsight、Graphiti 和多个 autonomous agents。

---

# 6. 总开发顺序

```text
Step 0  冻结基线与测试
  ↓
Step 1  Runtime 脚手架与本地环境
  ↓
Step 2  PostgreSQL Canonical Schema、Role、RLS
  ↓
Step 3  Evidence Ingest
  ↓
Step 4  Proposal、Steward 与 Claim 事务
  ↓
Step 5  删除、GroundingBlock 与权限负向测试
  ↓
Step 6  Outbox、FTS、pgvector 与 L0/L1 Retrieval
  ↓
Step 7  ContextCapsule 与压缩
  ↓
Step 8  Episode 与 Settlement
  ↓
Step 9  API 闭环与最小 UI
  ↓
Step 10 Hindsight Shadow
  ↓
Step 11 Graphiti Temporal Experiment
  ↓
Step 12 Evaluation 与上线门
  ↓
Step 13 Profile、多模态、家庭与 Multi-Agent
```

每个 Step 只有在自己的完成条件通过后才能进入下一步。外部引擎接入不能用来掩盖 Canonical Core 的测试缺口。

---

# 7. Step 0：冻结基线与测试

## 目标

证明开发起点与 `architecture/v1.0` 一致，并建立以后每次提交都必须运行的架构门。

## 执行

在 Windows PowerShell 中运行：

```powershell
$py = 'C:\Users\Mingx\Documents\idea\.venv\Scripts\python.exe'
$arch = 'C:\Users\Mingx\Documents\mila\architecture\v1.0'

& $py -X utf8 "$arch\scripts\validate_bundle.py" `
  --bundle "$arch\examples\v0_1_bundle.example.json"

& $py -X utf8 -m unittest discover `
  -s "$arch\tests" -p 'test_*.py' -v

& $py -X utf8 "$arch\scripts\verify_lock.py"
```

同时完成：

1. 建立 `memory_test` 脱敏数据集；
2. 记录旧 SQLite/JSON/FAISS 的数据量、查询和已知行为；
3. 为旧数据生成只读 manifest、checksum 和 source ID；
4. 保存 No-Memory、关键词检索和旧 FAISS 基线结果；
5. 将冻结架构测试接入 CI。

如果旧 Runtime 源码或数据尚未提供，只建立迁移接口和 fixture，不虚构迁移成功。

## 完成条件

- lock 验证通过；
- Schema/bundle 验证通过；
- 全部现有架构测试通过；
- 基线数据可重复运行；
- 旧数据只读快照可验证。

---

# 8. Step 1：Runtime 脚手架与本地环境

## 目标

建立可以启动、测试和迁移的最小 Runtime，不实现业务智能。

## 工作项

1. 创建 `runtime` 目录结构；
2. 建立 `pyproject.toml`、lock file 和 `.env.example`；
3. 建立 PostgreSQL + pgvector 的 `compose.yaml`；
4. 创建 Flask application factory；
5. 创建 Worker 主循环；
6. 配置 Alembic；
7. 加入 JSON 日志、request ID、tenant ID 和 actor ID；
8. 添加 `/health/live` 与 `/health/ready`；
9. 建立 `dev`、`test`、`staging`、`production` 配置边界。

目标启动命令在脚手架完成后应统一为：

```powershell
Set-Location C:\Users\Mingx\Documents\mila\runtime
Copy-Item .env.example .env
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m milai.api
.\.venv\Scripts\python.exe -m milai.workers
```

这些是目标命令；在对应文件实际创建前不能宣称已经可运行。

## 完成条件

- 空数据库可以一条命令建立；
- API 与 Worker 可以独立启动和优雅停止；
- readiness 会检查数据库，而不仅是进程存活；
- 配置缺失时启动失败，不使用隐式生产默认值；
- 测试数据库与开发数据库隔离。

---

# 9. Step 2：PostgreSQL Canonical Core

## 目标

将冻结逻辑映射为实验性数据库合同，并首先解决 `G2` 至 `G9` 的阻塞项。此阶段允许迭代 DDL，但不得标记 Schema frozen。

## 最小 Schema 域

```text
evidence
├─ content_blob
├─ evidence_record
├─ evidence_permission
└─ retention_state

state
├─ claim
├─ claim_version
├─ claim_head
├─ version_transition
├─ grounding_relation
├─ grounding_block
└─ effective_claim_state

control
├─ operation_proposal
├─ steward_decision
├─ commit_result
├─ open_issue
└─ memory_intention

context
└─ context_capsule

integration
├─ outbox_event
└─ index_watermark

observability
└─ operational_event

audit
└─ audit_record
```

## 必须实现的数据库保证

1. 所有 tenant-owned row 包含 `tenant_id`；
2. `ClaimVersion`、`VersionTransition`、`StewardDecision` append-only；
3. `ClaimHead` 只能 CAS 更新；
4. `canonical_commit_seq` 单调、不复用；
5. canonical mutation 与 OutboxEvent 原子提交；
6. app login 不拥有表；
7. 非 Steward 不能执行 Claim commit；
8. Steward 只能执行受控 procedure，不能直接 DML；
9. Production role 不能写 `AuditRecord`；
10. tenant RLS 不能只信任客户端传入的 tenant ID；
11. `EffectiveClaimState` 统一计算 current、revocation、GroundingBlock 和 effective authority。

## 必须先写的数据库测试

```text
CREATE absence-CAS 两连接竞争
Revision exact-head CAS 两连接竞争
Idempotency replay
Idempotency fingerprint conflict
NO_CHANGE 不产生新版本
SPLIT fail closed
旧 ClaimVersion byte immutability
非 Steward commit denied
Steward direct DML denied
Production AuditRecord write denied
跨 tenant SELECT/commit denied
Outbox atomic rollback
```

## 完成条件

- `G2` 至 `G9` 不再存在 BLOCKING witness；
- 两个真实 PostgreSQL connection 的并发测试通过；
- 所有权限测试使用真实 login role，而不是 mock；
- migration 有 upgrade、downgrade 或明确不可逆说明；
- schema dump 和 migration history 可重建同一结构。

在这一步完成以前，不冻结生产 DDL。

---

# 10. Step 3：Evidence Ingest

## 目标

让用户消息、文件和工具结果以独立、可追溯、幂等的 observation 进入系统。

## API

```text
POST /v1/evidence
GET  /v1/evidence/{evidence_id}
GET  /v1/evidence/{evidence_id}/lineage
```

## 写入流程

```text
Authenticate tenant/actor
→ validate source permission
→ normalize capture metadata
→ calculate content hash
→ claim ingest idempotency key
→ create/reuse tenant-scoped ContentBlob
→ create independent EvidenceRecord
→ allocate canonical_commit_seq
→ OperationalEvent
→ OutboxEvent
→ commit
```

内容相同不能自动复用 EvidenceRecord，因为两次观察可能有不同时间、来源和权限。只有同一次 capture 的幂等重试可以返回原 Evidence ID。

## 最小输入

```json
{
  "tenant_id": "tenant-1",
  "source_type": "USER_MESSAGE",
  "source_ref": "conversation-22/message-81",
  "observed_at": "2026-08-11T10:00:00+08:00",
  "content": "项目运行环境已升级到 Python 3.12",
  "ingest_idempotency_key": "conversation-22-message-81"
}
```

## 完成条件

- 同 key 同 payload 返回同一 EvidenceRecord；
- 同 key 不同 payload 返回 `IDEMPOTENCY_CONFLICT`；
- 同内容不同观察产生两个 EvidenceRecord；
- 跨 tenant blob 不去重；
- summary、ContextCapsule 和 model inference 不能伪装为 observation source。

---

# 11. Step 4：State Derivation、Proposal 与 Steward Commit

## 目标

形成唯一、可审计的正式状态写路径。

## 服务边界

```text
State Deriver
→ 读取 Evidence 和 EffectiveClaimState
→ 生成 Candidate Relation

Diagnoser
→ SUPPORT / CONTRADICT / WEAKEN / REVALIDATE /
  REGROUND / SUPERSEDE / CONTEXTUALIZE / NO_CHANGE

Proposal Service
→ 创建 OperationProposal

Steward Workflow
→ APPROVE / REJECT / REQUEST_USER_CONFIRMATION / DEFER

Canonical Procedure
→ TX-02 / TX-03 / TX-04 / TX-06
```

## API

```text
POST /v1/proposals
GET  /v1/proposals/{proposal_id}
POST /v1/proposals/{proposal_id}/review
GET  /v1/claims/{claim_id}
GET  /v1/claims/{claim_id}/versions
GET  /v1/open-issues
GET  /v1/memory-intentions
```

## 关键行为

- `CREATE` 要求 `expected_version_id=null`，生成 V1，不生成虚构 transition；
- revision 要求 exact current head；
- `NO_CHANGE` 不产生版本、transition、head movement 或 issue discharge；
- `SPLIT` 在 V1 中拒绝；
- grounding 变化即使文本不变，也必须创建新 ClaimVersion；
- OpenIssue effect 与 Claim transaction 原子提交；
- `REQUEST_USER_CONFIRMATION` 和 `DEFER` 只保持 proposal pending，不写 StewardDecision。

## 完成条件

- operation matrix 的每个 enabled 分支都有成功和失败测试；
- stale proposal 返回 `VERSION_CONFLICT`；
- retry 不产生第二个版本；
- rejected proposal 不改变 canonical state；
- issue 不能因 Claim 更新而隐式关闭；
- 所有 Claim 都能回放到 Evidence、derivation policy 和 StewardDecision。

---

# 12. Step 5：删除、权限与 Fail-Closed

## 目标

在外部索引尚未清理时，正式读取已经停止使用被撤销 Evidence。

## API

```text
POST /v1/evidence/{evidence_id}/revoke
GET  /v1/deletions/{request_id}
POST /v1/grounding-blocks/{block_id}/restore-proposal
```

## TX-05 同步边界

```text
authorize deletion
→ mark EvidenceRecord revoked
→ find dependent ClaimVersions from canonical relations
→ create GroundingBlocks
→ evict resident Context references
→ OperationalEvent
→ purge/re-ground OutboxEvents
→ commit
```

## 异步清理

```text
FTS purge
pgvector purge
Context artifact purge
Hindsight purge
Graphiti purge
object derivative purge
backup expiry tracking
```

## 完成条件

- revocation commit 后立即阻断 action-safe 读取；
- 外部索引即使还返回旧 candidate，也会被 canonical gate 拒绝；
- 共享 ContentBlob 仍有 live Evidence 引用时不能物理删除；
- legal hold 或 retention 状态不可读取时 fail closed；
- `TX-06` 必须用新 admissible Evidence 创建新版本后才能解除 GroundingBlock；
- API 区分 logical revocation、primary erase 和 backup expiry。

---

# 13. Step 6：Outbox、FTS、pgvector 与 L0/L1 Retrieval

## 目标

完成第一个真正可用的记忆检索闭环。

## Outbox Worker

```text
PENDING
→ PROCESSING with lease
→ DELIVERED
→ PENDING with backoff
→ DEAD_LETTER
```

要求：

- 使用 `outbox_id` 作为下游幂等 key；
- projection 按 canonical object/version ID upsert；
- worker crash 后可安全重试；
- 每个投影维护独立 `IndexWatermark`；
- dead-letter gap 未处理前 watermark 不能越过；
- worker 没有 canonical DML 权限。

## FTS 投影

索引适合精确关键词、实体名、错误码和文件名的字段。保存 canonical ID、tenant、scope、valid time 和 commit sequence，不把搜索文档当 truth。

## pgvector 投影

Embedding worker 保存：

```text
canonical_object_id
canonical_version_id
content_hash
embedding_model_id
embedding_dimension
embedding
commit_seq
```

Embedding 模型或维度变化时建立新 projection version，不原地混合不同向量空间。

## Query API

```text
POST /v1/memory/query
GET  /v1/retrieval-traces/{trace_id}
```

## QueryPlan

```yaml
intent: string
entities: []
time_constraint: null
scope_predicate: {}
required_authority: INFORMATIONAL
complexity: L0|L1|L2
consistency_mode: EVENTUAL|READ_YOUR_WRITES|CANONICAL_REQUIRED
minimum_outbox_sequence: null
context_budget: 8000
routes: []
```

## L0/L1 执行

```text
L0 exact/current
→ subject + predicate + scope
→ ClaimHead
→ EffectiveClaimState

L1 hybrid
→ metadata/time/scope filter
→ FTS + pgvector
→ score normalization
→ deduplicate by canonical ID/version
→ canonical resolution gate
→ Evidence Bundle
```

## 完成条件

- current-state query 不依赖向量索引；
- 所有 secondary candidate 都解析回 canonical ID；
- revoked、unknown、cross-tenant、wrong-scope candidate 被拒绝；
- READ_YOUR_WRITES 在 pgvector 落后时回退 canonical lane；
- CANONICAL_REQUIRED 不因索引不可用而返回旧 action-safe 状态；
- RetrievalTrace 记录 snapshot、watermark、route、reject 和 fallback。

达到这一步即可发布“Core Alpha”，不需要任何外部 memory engine。

---

# 14. Step 7：ContextCapsule 与压缩

## 目标

把检索结果转成当前 Agent 可安全使用的有限工作集。

## 固定分区

```text
[1] ACTIVE GOAL
[2] ACTIVE STATE
[3] OPEN ISSUES
[4] CONSTRAINTS
[5] RETRIEVED EVIDENCE
[6] TRACE POINTERS
```

## Context 操作

```text
KEEP       当前目标、硬约束、OpenIssue、关键依赖
STRUCTURE  重复内容转成结构化状态
POINTER    大文件和工具日志保留 Evidence/Trace 引用
EVICT      已完成且可恢复内容退出当前窗口
RECOVER    根据 pointer 重新载入原始内容
```

## 压缩流程

```text
collect candidate items
→ mark protected items
→ query/scope filter
→ deduplicate
→ structure stable state
→ replace recoverable bulk with pointers
→ allocate per-section token budget
→ validate goal/constraint/open-issue/dependency preservation
→ persist ContextCapsule and CompressionTrace
```

## 自研基线先行

先完成一个确定性的 `ContextBackend`，再接 ReMe：

```text
ContextBackend interface
├─ LocalStructuredContextBackend
└─ ReMeContextBackend
```

两者接收相同输入、生成相同逻辑输出 Schema，使用 feature flag 或实验分流。OpenViking只在 ReMe 基线稳定后作为独立实验，不能与 ReMe 同时成为生产 Context writer。

## 完成条件

- compression 不能产生 EvidenceRecord；
- recursive compression 保留相同 OpenIssue identity；
- pointer 必须验证目标、hash、权限和 retention；
- 压缩失败回退到更高预算或 canonical minimal capsule；
- 大型 tool output 能退出 prompt 并按 pointer 恢复；
- ContextBackend 故障不改变 canonical state。

---

# 15. Step 8：Episode 与 Settlement

## 目标

任务结束时分类处理经验，而不是总结后全部写入长期记忆。

## API

```text
POST /v1/episodes
POST /v1/episodes/{episode_id}/events
POST /v1/episodes/{episode_id}/settle
GET  /v1/episodes/{episode_id}/settlement
```

## Settlement 流程

```text
close Episode capture
→ archive raw trace
→ expire transient working state
→ generate 0–3 candidate Claims/Lessons
→ diagnose conflicts and missing evidence
→ propose OpenIssue/MemoryIntention changes
→ send durable changes through Steward
```

## V1 限制

- 不自动形成 Pattern；
- 不自动进行 Scope Promotion；
- 不把当前语气要求写成稳定 profile；
- 不因摘要删除 OpenIssue；
- Boundary Utility 只在 Audit 环境评估；
- settlement retry 必须幂等。

## 完成条件

- 原始 Episode 可以完整回放；
- temporary state 不进入下一 Episode 默认检索；
- 候选 residual 有 Evidence 和 scope；
- settlement 失败不产生半提交 Claim；
- 同一 Episode 重试不会重复创建候选。

---

# 16. Step 9：API 闭环与最小 UI

## API 闭环

```text
POST /v1/chat
→ open/resume Episode
→ ingest user Evidence
→ build QueryPlan
→ retrieve Evidence Bundle
→ assemble ContextCapsule
→ call model
→ ingest tool/user observations
→ return answer + trace summary
```

Agent 回复本身默认是 model output，不自动成为独立事实 Evidence。只有明确的工具观察、用户陈述或受允许的系统事件按相应 source type 进入 Evidence。

## 最小 UI

1. Chat 页面；
2. Evidence 查看与来源定位；
3. Claim 当前版本和历史时间线；
4. OpenIssue 与 MemoryIntention 队列；
5. Proposal 审核；
6. 删除与导出；
7. Outbox lag、watermark 和 degraded 状态；
8. RetrievalTrace 查看。

## 完成条件

- 普通用户可以聊天、纠正、确认和删除；
- Steward 可以审核 proposal，但不能通过 UI 绕过 procedure；
- 每个回答可以查看使用了哪些 Evidence；
- degraded retrieval 会显示，不伪装为完整结果。

达到这一步可发布“Local Beta”。

---

# 17. Step 10：Hindsight ShadowMemoryBackend

## 目标

在不改变 canonical correctness 的前提下测试更强的长期召回和经验候选。

## Adapter 合同

```text
Canonical Outbox/Snapshot
→ Hindsight retain
→ recall / observation / reflect
→ canonical ID candidate or OperationProposal
→ Canonical Resolution Gate
```

要求：

1. bank/namespace 按 tenant 和 subject 隔离；
2. retain 使用稳定 canonical ID 和 outbox idempotency key；
3. recall 返回 source facts 或可解析 lineage；
4. unknown candidate 直接拒绝；
5. reflect 仅离线产生候选；
6. purge 支持 deletion propagation；
7. Hindsight 使用独立 watermark；
8. Hindsight credential 无法连接 canonical writer role。

## 上线门

对比：

```text
PostgreSQL only
vs
PostgreSQL + Hindsight
vs
PostgreSQL + Mem0 baseline
```

只有在正确率或召回显著提高，同时 stale/conflict/latency/cost 未越过门槛时，才默认开启 Hindsight route。

---

# 18. Step 11：Graphiti TemporalGraphBackend

## 目标

只为时间、关系和多跳查询验证时间图的独立增益。

## 投影

```text
ClaimVersion
VersionTransition
Evidence observed/valid time
→ Outbox
→ structured temporal episode
→ Graphiti
```

## 适用查询

```text
项目什么时候从 Python 3.11 升级到 3.12？
某条偏好在哪个项目和时间段有效？
一条状态变化影响了哪些后续计划？
```

## 限制

- Graphiti fact invalidation 只能产生 candidate/proposal；
- canonical current state 仍由 EffectiveClaimState 决定；
- action-safe query 必须 canonical revalidation；
- Graphiti 与 Zep 二选一；
- 普通相似度查询不进入图路线。

## Go/No-Go

与 PostgreSQL VersionTransition、Hindsight 和无图 baseline 比较。如果 temporal correctness、多跳证据或维护成本没有实质增益，保持关闭。

---

# 19. Step 12：Evaluation 与上线门

## 独立 Audit 流程

```text
Production immutable snapshot
→ Experiment Runner
→ baseline/adapters
→ metrics + failure cases
→ AuditRecord
→ human/governed release decision
```

Audit role 不能执行 Production commit，Production role 不能写 AuditRecord。

## 最小评测矩阵

| 维度 | 最低对照 |
| --- | --- |
| 长期记忆 | No Memory、FTS、pgvector、LongMemEval |
| 当前状态 | exact canonical route |
| 冲突 | MemConflict 类样本 |
| 偏好变化 | HorizonBench、Memora 类样本 |
| Context 压缩 | raw、structured capsule、ReMe |
| Shadow | PostgreSQL only、Hindsight、Mem0 |
| 时间 | VersionTransition、Graphiti |
| 删除 | stale index、purge failure、GroundingBlock |
| 安全 | tenant/RLS、authority、audit isolation |

## 必须记录的指标

```text
task success
answer correctness
evidence grounding rate
unsupported claim rate
stale-memory error
conflict-preservation rate
open-issue loss rate
deletion propagation lag
cross-tenant leakage
p50/p95 latency
token use
index lag
fallback rate
```

## 硬失败条件

- 跨 tenant 泄漏；
- revoked Evidence 被用于 action-safe 回答；
- Context 压缩关闭未解决问题；
- Shadow/Graph 直接改变 canonical state；
- retrieval 无法追溯到 Evidence；
- idempotent retry 创建重复 ClaimVersion；
- 并发 revision 出现两个成功 head；
- canonical store 不可用时仍生成 authority-bearing 回答。

任何一项出现即阻止上线，不能用平均 benchmark 分数抵消。

---

# 20. Step 13：后续功能

核心闭环稳定后再开发：

## Profile

```text
EffectiveClaimState
→ context-conditioned Profile Projection
→ user review/correction/delete
```

Profile 不是第二套 truth，不能从单次行为自动形成稳定偏好。

## 多模态

文件、图片、音频先保存为 Evidence，检索返回页码、时间戳或区域定位。Caption 和 embedding 都是派生表示。

## 家庭与多设备

先完成 tenant、subject、sharing grant、RLS、备份恢复和儿童最小化数据策略，再开放共享记忆。

## Multi-Agent

多个 Agent 只能提交 Evidence 和 Proposal。后续可扩展 owner、eligible evidence、authority 和 delegated resolution，但不能改变单一 canonical commit 边界。

## Research Track

以下内容保持隔离实验：

```text
Boundary Utility
Scope Evolution
Open-State-Preserving Compression
Memory Intention novelty
Multi-Agent Maintenance Responsibility
```

研究结果必须通过 EvaluationAdapter 和 governed release，不能直接改 Production policy。

---

# 21. 开发完成后的实际使用流程

## 21.1 启动系统

脚手架完成后，目标操作为：

```powershell
Set-Location C:\Users\Mingx\Documents\mila\runtime
docker compose up -d postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m milai.api
.\.venv\Scripts\python.exe -m milai.workers
```

检查：

```text
GET /health/live
GET /health/ready
GET /v1/system/watermarks
GET /v1/system/degraded-routes
```

## 21.2 用户进行一次对话

```text
User message
→ TX-01 Evidence Ingest
→ QueryPlan
→ L0/L1/L2 Retrieval
→ Canonical Gate
→ ContextCapsule
→ Model Reply
→ Episode Event
```

模型回答返回时同时给出可选的 trace summary：

```json
{
  "answer": "项目当前使用 Python 3.12。",
  "evidence_refs": ["E-202", "E-204"],
  "claim_refs": ["M-81-V2"],
  "open_issues": [],
  "retrieval_trace_id": "RT-91",
  "degraded": false
}
```

## 21.3 用户提供新事实

```text
“项目已经升级到 Python 3.12。”
→ 保存 Evidence
→ 生成 Claim Candidate
→ 若旧状态为 3.11，创建 conflict/revision proposal
→ Steward 审核
→ 新 ClaimVersion
→ Outbox 更新索引
```

如果只有用户推测而没有足够证据，可以执行 `NO_CHANGE` 或建立 OpenIssue，不强行更新正式状态。

## 21.4 用户纠正记忆

```text
用户：“不是所有项目都使用 3.12，只有 MiLAi。”
→ Evidence Ingest
→ CONTEXTUALIZE proposal
→ Scope predicate update as new ClaimVersion
→ old broad claim remains historical
```

当前 Session 使用 `READ_YOUR_WRITES`，即使 pgvector 尚未同步，也必须从 canonical lane 读到纠正后的版本。

## 21.5 用户删除记忆

```text
Delete request
→ TX-05 Evidence Revoke
→ GroundingBlock
→ action-safe use immediately blocked
→ Outbox purge ReMe/Hindsight/Graphiti/indexes
→ eligible ContentBlob erase
→ visible deletion status
```

界面必须显示：

```text
logical revocation complete
derived purge progress
primary bytes erased or blocked
backup expiry pending or complete
```

## 21.6 Episode 结束

```text
Close Episode
→ Archive raw trace
→ Expire transient state
→ create 0–3 candidates
→ preserve OpenIssue
→ create/update MemoryIntention proposal
→ Steward handles durable changes
```

## 21.7 Steward 日常工作

Steward Queue 至少显示：

```text
Pending OperationProposal
Expected vs current version
Supporting/contradicting Evidence
Requested authority
Scope change
OpenIssue effect
Approve / Reject / Ask User / Defer
```

Steward 审批动作始终调用受控 procedure，UI 没有 canonical table 编辑器。

---

# 22. 一个完整真实流程

初始状态：

```text
M81 V1：MiLAi 使用 Python 3.11
Evidence：deployment.md
Authority：ACTION_SAFE
```

Coder 读取 `pyproject.toml` 发现 `requires-python >= 3.12`：

```text
1. TX-01 保存 E202。
2. Deriver 发现与 M81 V1 不一致。
3. Diagnoser 产生 CONTRADICT candidate。
4. 系统建立 OpenIssue：配置与部署状态冲突。
5. MemoryIntention 要求检查 CI 和生产 runtime。
6. 暂时执行 NO_CHANGE，不把 3.12 写成正式状态。
```

Tester 随后得到：

```text
E203：CI = Python 3.12
E204：production container = Python 3.12
```

系统执行：

```text
7. 创建 SUPERSEDE/REVALIDATE proposal。
8. Validator 检查 evidence、scope、authority 和 expected V1。
9. Steward APPROVE。
10. TX-03 创建 M81 V2，不修改 V1 bytes。
11. ClaimHead 从 V1 CAS 到 V2。
12. VersionTransition 记录 supersede。
13. OpenIssue 根据 E203/E204 受治理关闭。
14. Canonical commit 与 OutboxEvents 原子提交。
15. Worker 更新 FTS、pgvector、ReMe、Hindsight；Graphiti若启用则更新时间关系。
```

下一次用户查询：

```text
“MiLAi 当前用什么 Python？”
→ L0 exact/current
→ EffectiveClaimState = M81 V2
→ Evidence Bundle = E202/E203/E204
→ 回答 3.12，并可展开来源
```

Episode 结束：

```text
工具日志 → Archive/Pointer
当前版本 → 已在 Canonical Claim 中
未解决状态 → 无
候选 Lesson → “运行版本需要用 CI/production 验证”
```

该 Lesson 只是 candidate，不因一次经历自动升级为 Pattern。

---

# 23. 测试与提交纪律

每个 Pull Request 至少执行：

```text
architecture lock/schema tests
unit tests
contract tests
real PostgreSQL integration tests
affected concurrency/failure tests
tenant/role negative tests
migration check
lint/type checks
```

修改以下内容时必须额外执行：

| 修改 | 必跑测试 |
| --- | --- |
| Claim transaction | CAS、idempotency、immutability、rollback |
| Evidence/Deletion | GroundingBlock、shared blob、purge lag |
| Retrieval | scope、authority、revocation、fallback |
| Context | goal/constraint/OpenIssue preservation |
| Adapter | idempotency、watermark、unknown ID、tenant isolation |
| RLS/Role | 所有真实 login negative tests |
| Evaluation | Production/Audit isolation |

不得只使用编写功能的同一个模型生成和审核测试。关键并发、安全和删除路径需要独立 review。

---

# 24. 发布阶段与退出条件

| Release | 包含 | 不包含 | 退出条件 |
| --- | --- | --- | --- |
| Core Alpha | Canonical、TX、Outbox、L0/L1、ContextCapsule | 外部 memory engine | G2–G9 通过 |
| Local Beta | Chat、Settlement、UI、删除、备份恢复 | Graph/Multi-Agent | 真实脱敏任务回归通过 |
| Shadow Beta | Hindsight 或一个 shadow backend | 多 shadow 同时生产 | 对照评测 go |
| Temporal Pilot | Graphiti 或 Zep | 默认全查询走图 | temporal 专项 go |
| Personal Release | Profile、用户审核、导出删除 | 自动 profile promotion | 偏好变化和隐私回归通过 |
| Family Pilot | RLS、共享授权、多设备恢复 | 自动跨成员共享 | 安全和恢复演练通过 |

任何阶段出现以下情况应回退：

```text
canonical invariant violation
cross-tenant exposure
deletion fail-open
untraceable answer
outbox unrecoverable gap
adapter direct write
compression open-issue loss
```

---

# 25. 首批开发任务清单

建议按下列 Issue 顺序创建，不并行跨越依赖：

```text
MILA-001  Runtime scaffold and config
MILA-002  PostgreSQL compose and migration harness
MILA-003  Tenant context, roles and RLS test harness
MILA-004  Evidence/ContentBlob schema and TX-01
MILA-005  Claim/ClaimVersion/ClaimHead schema
MILA-006  OperationProposal repository and validator bridge
MILA-007  TX-02 CREATE absence-CAS
MILA-008  TX-03 revision exact-head CAS
MILA-009  TX-04 NO_CHANGE and SPLIT rejection
MILA-010  EffectiveClaimState and authority satisfaction
MILA-011  TX-05 revoke and GroundingBlock
MILA-012  TX-06 grounding restore
MILA-013  Outbox worker and watermark
MILA-014  PostgreSQL FTS projection
MILA-015  pgvector projection and embedding versioning
MILA-016  QueryPlan and exact route
MILA-017  Hybrid retrieval and canonical gate
MILA-018  RetrievalTrace and degraded fallback
MILA-019  ContextCapsule local backend
MILA-020  Compression preservation tests
MILA-021  Episode capture and settlement
MILA-022  Chat API and minimal UI
MILA-023  Backup/restore and operational dashboards
MILA-024  ReMe adapter experiment
MILA-025  Hindsight adapter experiment
MILA-026  Graphiti temporal experiment
MILA-027  Evaluation harness and release report
```

每个 Issue 的 Definition of Done 必须包含：代码、migration、测试、失败路径、日志字段、权限影响、回滚方式和对应架构 trace。

---

# 26. 最终执行原则

```text
先证明 Canonical Core 正确
→ 再证明检索可降级
→ 再证明 Context 不丢开放状态
→ 再接一个外部 backend
→ 用相同快照与 baseline 比较
→ 通过 go/no-go 后才默认启用
```

开发过程中始终保持：

```text
Evidence 可追溯
Claim 可版本化
Issue 不被压缩消失
Intention 不直接执行写入
External Backend 可删除重建
Canonical Failure 必须 abstain/fail closed
Research Result 不能自动进入 Production
```

按此顺序完成后，MiLAi 才从架构规范变成可以长期运行、验证、回滚和扩展的 Memory Runtime。
