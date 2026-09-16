---
document_id: MILA-PRODUCT-05
version: "1.0"
status: ACTIVE
created_at: "2026-09-02T22:49:41+08:00"
parent: MILA-PRODUCT-GOALS@1.7
predecessor: MILA-PRODUCT-04
execution_authorized: true
opened_development_lme_authorized: true
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
database_migration_authorized: false
canonical_authority_change_authorized: false
local_vllm_qwen_authorized: true
---

# MILA-PRODUCT-05：OpenWorker 记忆闭环、用户隔离与集合证据可靠消费

## 1. 目标

本 Goal 把 MiLAi Product 收敛为一个真实可用的 OpenWorker Memory 产品：

```text
OpenWorker 对话
→ Host 按真实 user/session/turn 捕获 Raw Evidence
→ submitter MCP
→ PostgreSQL-backed Evidence / Projection 持久化
→ 重启后 reader MCP 仍可召回
→ Qwen 对已召回的单条或集合证据做 grounded 消费
→ 返回答案和可追溯的 Evidence use
```

开发顺序是“先能记、能找、能用，再压缩成本和引入复杂机制”。本 Goal
不重建 Canonical Core，不恢复 TypeBinding，不为单个 LongMemEval case 写专用规则。

## 2. 当前机器事实与审计结论

### 2.1 已经可复用的能力

| 领域 | 当前代码事实 | Product-05 处置 |
| --- | --- | --- |
| 数据持久化 | `content_blob`/`evidence_record`/投影/Canonical 对象已由 PostgreSQL 交易管理；正文 bytes 按冻结架构位于 tenant-scoped CAS | 复用，不建第二套 store |
| 用户安全边界 | 所有 tenant 行包含 `tenant_id`，表开启并强制 RLS；API 从受信运行配置得到 tenant | 一个本地用户一个 tenant/runtime namespace |
| 语义主体 | `subject_id` 表示记忆内容讲述的主体 | 不用作安全用户边界 |
| MCP 权限 | `reader-lite` 与 `submitter` 已是独立 socket/profile；`capture_evidence()` 已是公开适配器能力 | 由 Host facade 组合，不暴露 submitter 给模型 |
| 写入原语 | `MemoryWriteIntent` / `MemoryWriteHandoff` 已具备准入、去重、脱敏和 Evidence-only 边界 | 接入真实 OpenWorker 会话生命周期 |
| 读取链 | OpenWorker → Host → UDS broker → MCP → Runtime → Qwen 已运行 | 保留 query-first 路径 |
| 自然语言权威 | Product-04 已撤回 Raw TypeBinding，`QueryTaskContract` 只是规划信息 | 不恢复手写语义类型机 |

### 2.2 当前三个真正缺口

1. **OpenWorker 只有稳定读路径，没有完整宿主写入闭环。**  
   `MemoryWriteHandoff` 只在单元测试中使用，`host_adapter` 没有在每次真实交互结算后
   持久化 user/assistant turn。

2. **数据库已有 tenant 隔离，但尚未用真实双用户 OpenWorker 路径证明。**  
   当前 Runtime 是每进程一个 `tenant_id`；这适合本地个人 Memory，但不能被写成
   “单进程多用户已支持”。

3. **集合证据已进入 Reader，Qwen 仍会漏成员。**  
   Product-04 后的真实复测中，assistant-source lookup 成功；multi-session count 的
   两组必需证据都在同一 Reader Context，Qwen 却漏掉一组成员。首损位于
   `READER_EVIDENCE_CONSUMPTION`，不是继续增加 Top-k 能解决的召回问题。

### 2.3 文档与代码冲突

- Product-04 Goal 在 terminal 时记录“未运行 Product-04 真实 replay”；之后 Lab 已运行
  2-case replay，导航文档尚未同步。历史 terminal 不重写，Product 状态页应记录
  post-terminal 事实。
- `host_adapter.py` 和 Runtime 多个检索模块体积很大。本 Goal 只增加小的 facade/
  protocol 边界，不做平台级重写。
- Product 不得读取 LME case ID、reference answer、gold term 或实验分层；这些只存在 Lab。

## 3. 两个主要假设

### P05-H1 — 真实、持久、按用户隔离的 OpenWorker Memory

在不修改 public MCP shape 和数据库 Schema 的前提下，Host-owned Memory facade
能将真实 OpenWorker user/assistant turns 按 tenant、session、message/turn 持久化；重启后
仍能召回，两个用户共用同一 PostgreSQL 实例时不会交叉读写。

### P05-H2 — 模型可靠消费多条已召回证据

在固定的 governed Reader-visible Context 上，简洁的 grounded evidence-use protocol
能改善集合、计数、比较或时间/更新任务，且不使普通 lookup 回归。协议只约束
证据引用与答案组装，不产生 Binding、`COMPLETE` 或 Canonical mutation。

### 明确不主张

本 Goal 不主张：

```text
单进程 SaaS 多用户已完成
LongMemEval 正式 500-case 或排行榜水平
模型能证明 temporal completeness
Formation/Graph/active refinding 已应该默认开启
更大预算本身就是语义正确性
```

## 4. 目标产品路径

### 4.1 宿主侧存取 facade

新增一个小的 `OpenWorkerMemoryFacade` （最终名称以代码语境为准）：

```text
trusted OpenWorker Host
  ├─ recall_for_operation(...)
  │    └─ reader-lite McpUnixClient
  └─ settle_exchange(...)
       └─ independent submitter McpUnixClient
            └─ MemoryWriteHandoff
                 └─ milai_evidence_capture
```

一次操作的顺序：

```text
1. 以当前 turn 之前的持久化 snapshot 召回
2. 调用 Qwen 回答
3. 由 Host 结算本次 user + final assistant exchange
4. 通过 submitter MCP 写 Raw Evidence
5. 投影异步完成；下一轮需要时使用一个明确 readiness wait
```

该顺序避免当前 query 成为自己的 retrieval distractor。

只允许写入：

- 原始 user message；
- 最终 assistant answer，但必须保留 `speaker=assistant` 与本轮 `memory_support_refs`；
- 显式 allowlist 中的 tool result（后续小步骤）。

禁止写入：

- `MILAI_CONTEXT` 注入内容；
- system/developer prompt、tool schema、隐藏 reasoning；
- bearer token、database URL 和其他 secret；
- 模型自行选择的 tenant/scope/retention。

assistant Evidence 可回答“你之前告诉我什么”，但它不能作为其所复述的 user fact 的
第二个独立支持。召回与形成路径必须能看到这条血统，避免“模型输出 → 再写入
→ 更高置信”的自我强化。

每个 Evidence 使用真实：

```text
tenant_id          由 Runtime deployment 身份决定
source session     OpenWorker sessionID
source message     OpenWorker message/part identity
turn ordinal       session-scoped ordinal
speaker            user | assistant | allowlisted tool
subject_id         语义主体，不是 tenant
idempotency key    tenant + session + message + content hash
```

### 4.2 用户隔离与数据库持久化

Product-05 的第一阶段用户模型是：

```text
one local user
= one configured tenant
= one Runtime/broker credential namespace
```

两个用户可以使用同一 PostgreSQL database，但通过两套 tenant-bound Runtime/broker
配置访问。模型、query 和 `subject_id` 都不能改变 tenant。

持久化合同：

```text
PostgreSQL:
  Evidence identity / metadata / permission / retention
  idempotency / outbox / retrieval projection
  Canonical State / version / issue

tenant-scoped local CAS:
  Raw content bytes
  hash, URI and encryption identity bound back to PostgreSQL
```

这是已冻结的 Evidence Plane，不是进程内 Memory。本 Goal 要证明 restart 后从数据库与
CAS 恢复读取。若未来需要“单 Runtime 进程动态服务多用户”，必须单独设计受信
identity-to-tenant routing；本轮不通过新增一个重复 `user_id` 列解决。

### 4.3 集合证据的可靠消费

当前 Prompt 已告诉 Qwen 枚举成员，但真实 count case 仍失败，因此 Product-05 不再
增加一段更长的提示词，而是尝试一个非权威、通用的中间输出：

```yaml
GroundedEvidenceUseV01:
  disposition: ANSWERED | PARTIAL | INSUFFICIENT | AMBIGUOUS
  answer_text: string

  support:
    - assertion: string
      evidence_aliases: [string]

  members:
    - member: string
      quantity: number | null
      evidence_aliases: [string]

  calculation:
    expression: string | null
    result: string | number | null

  uncertainties: [string]
```

模型只能引用 Reader-visible Context 中的稳定 alias。Host 只验证：

```text
alias 存在且可见
support/member 不引用 Context 外对象
calculation 的算术与显式成员一致
schema 可解析
```

Host 不因此宣告：

```text
Evidence 在世界上为真
set 已经完备
Raw prose 是 typed operand
RequirementState = COMPLETE
Canonical State 应更改
```

该协议同时适用 lookup、set/count、compare、temporal/update，但字段可以为空；不为
每个 benchmark query type 创建新 schema。
它只在 Host 已判定本轮是 memory-answer 且 Context 非空时使用；无记忆需求的普通对话、
tool call 和 streaming compatibility 继续原样 pass-through。

## 5. 五个开发 Block

### B0 — 基线和失败边界对齐

目标：不改行为，先将 Product-04 后真实 replay 和当前代码边界写清。

任务：

- 将 2-case post-terminal replay 同步到 Product/Lab 当前状态；
- 冻结当前 direct-answer baseline 和 vLLM Qwen/tokenizer/chat-template identity；
- 定义统一首损集合：`INPUT_IDENTITY / STORAGE / PROJECTION / ACQUISITION /
  ADMISSION / READER_CONSUMPTION / ANSWER_SCORER / INFRASTRUCTURE`；
- 对已开发 LME 数据只冻结 metadata-stratified case manifest，Product 不得接触 ID/gold。

退出：基线可重放，历史记录不再声称 Product-03 是最新真实 replay。

### B1 — OpenWorker Memory facade 与双用户持久化

实现最小纵向路径：

```text
real operation
→ recall previous persisted state
→ provider answer
→ host settlement
→ submitter MCP capture
→ PostgreSQL/outbox/projection
→ restart
→ next real operation recalls it
```

最小完成门：

```text
user and assistant turns captured with exact source identity      100%
assistant memory-derived output retains support lineage           100%
duplicate replay creates additional Evidence rows                 0
restart loses readable memory                                     0
two-tenant cross-read / cross-write / cross-projection leak        0
model-visible submitter/operator tools                             0
captured MILAI_CONTEXT/system/secret payloads                      0
assistant evidence used as independent user-fact support           0
read-path or capture-path Canonical mutation                       0
```

数据库集成测试只需要一套 fresh 库、两个 tenant 上下文和一次 restart，不为每个
小行为重建数据库。

### B2 — 固定 Context 上的 Evidence-use protocol

在**同一 Reader-visible Context**上比较：

```text
A  当前 direct answer
B  A + 简洁 evidence inventory/alias
C  一次 structured GroundedEvidenceUseV01
D  只当 C 仍无法稳定处理集合时：ledger → final answer 两步
```

选择最小通过臂。D 不得因“两步更强”预先默认开启。

开发集至少覆盖：

```text
ordinary user lookup
assistant-answer recall
multi-session member set / count
multi-operand comparison
temporal order or duration
state/update with obsolete distractor
insufficient/abstention
```

P05-H2 的 effect 门：

```text
valid evidence aliases                         100%
explicit arithmetic consistency               100%
ordinary lookup correct-case regression          0
additional correct multi-evidence cases         >= 3
families containing those gains                 >= 2
new unsupported answer caused by treatment        0
```

这是小型 opened-development 机制门，不是统计泛化声明。

### B3 — 多类型 LME 的真实 OpenWorker 修复循环

实验必须使用：

```text
historical sessions
→ OpenWorkerMemoryFacade / submitter MCP
→ real PostgreSQL + projection worker
→ native OpenWorker operation
→ Host query-first
→ reader MCP
→ Runtime MemoryContext
→ local vLLM Qwen
→ deterministic scorer + Qwen judge
```

使用 outcome-blind、metadata-stratified 的 opened-development slice：

```text
S0  6 cases: 6 个不同能力族的单点 smoke
S1  12 cases: 每个主要失败族至少 2 个 case
S2  24 cases: 仅对冻结的最小方法做 paired confirmation
```

覆盖 single-session user/assistant lookup、multi-session set/count、compare、temporal、
knowledge update/state 和 abstention。每 case 都使用独立 tenant/data namespace。

并发策略：

```text
capture/projection: 每 case 4 路有界并发，批量写入后只等待一次 readiness
case stacks:       最多 4 个隔离 stack 并行
vLLM generation:   以实际 endpoint capacity probe 设为 2–4
judge:             与 answer 分离队列，不阻塞下一 case 的 ingest/retrieval
```

不做同一 case 换 seed、投票或自动语义 retry。计数/数字/精确字符优先使用
确定性 scorer；Qwen judge 用于开放文本，明确记录同模型 judge 不等于官方 GPT-4o。

### B4 — 最小产品决策与交付

当 B1–B3 完成后：

- 选择 direct / inventory / one-pass structured / two-pass 中的最小通过方法；
- 只对出现 acquisition/admission 首损的族决定是否开启 simple FTS+dense quota union、
  local adjacency 或更宽预算；
- 对 Reader-visible-but-wrong 失败不得通过加大 retrieval 预算“修复”；
- 运行受影响包的完整测试、Ruff、strict mypy、build 与一次 fresh PostgreSQL 纵向门；
- 更新 Product/Lab 状态、安装与 OpenWorker 使用文档。

不运行 formal 500-case holdout。只有未来独立授权才能使用。

## 6. 失败后的通用修复和自动续跑

### 6.1 每个可恢复失败的固定循环

```text
失败 case
→ 定位最早失败层
→ 检查同族至少另一个 case
→ 形成一个通用 root-cause hypothesis
→ 实现最小机制修复
→ 添加失败正例 + 改写正例 + 负例
→ 运行单点测试
→ 重跑同族
→ 重跑当前冻结 slice
→ 通过后自动进入下一 Block
```

一个语义 case 失败不得终止整个 Goal。同一失败族最多做 3 轮机制修复；仍无法
解决时将该族标为 `UNRESOLVED` 并继续其他不依赖 Block。

### 6.2 只有五类硬停止条件

```text
跨 tenant 数据泄漏
未授权 Canonical mutation
丢失或破坏原始 Evidence
不确定的破坏性数据操作
必需的 PostgreSQL/vLLM/OpenWorker 外部服务持续不可用
```

遇到硬停止时保留现场并请求授权；普通协议错误、检索 miss、Qwen 错答、评分器错误
都属于可恢复失败。

### 6.3 禁止的刻板修复

```text
case ID / reference answer / gold quote 进 Product
为某个实体或问句增加 synonym/regex
看到 miss 就统一增加 Top-k/token
看到 count 就恢复 TypeBinding
用 subject_id 假装 security user namespace
用 Reader confidence 或结构化输出宣告 COMPLETE
为过测试换 seed、多次投票或隐藏 retry
```

## 7. 参考项目如何进入修复，而不是堆入默认架构

| 失败族 | 先参考 | 只借鉴的最小机制 | 当前不借鉴 |
| --- | --- | --- | --- |
| 用户隔离/存取 API | Hindsight, Mem0 | bank/user namespace；add/search 使用同一显式 scope | 自动事实 promotion、新 truth store |
| 单通道发现 miss | Hindsight, ReFind | 小 quota 的 BM25+dense 并集；真实 session 与 local window | 默认多轮 Agent search |
| Context 太大/不会定位 | OpenViking | L0/L1/L2 分层视图、按需展开的证据 inventory | 用新虚拟文件系统替换 Evidence Plane |
| 新旧状态/时间关系 | Graphiti | episode/time/provenance link 作为非权威投影 | 图成为 Canonical truth |
| 一轮后出现新 cue | ReFind | observation-conditioned 第二次搜索机会 | 没有 oracle opportunity 也强制 refind |

引入参考机制前必须在 failure ledger 记录：

```text
本地 root cause
参考项目的对应机制
借鉴的最小部分
明确拒绝的复杂性
在至少两个同族 case 上的证据
```

## 8. 预算、性能与可用性

本 Goal 先优化完成任务，不用紧预算屏蔽问题。

当且仅当首损位于 acquisition/admission，可从当前 `WIDE_V02` 扩展至本地
`OPENWORKER_ACCURACY_FIRST_V01`：

```yaml
max_candidates: 240
max_context_tokens: 32768
max_latency_ms: 10000
provider_context_limit: 65536
answer_output_tokens: 4096
semantic_retry: 0
vote: 0
```

这是上限而非必用量。候选和 Context 已包含完整 evidence set 时，必须保持固定 Context
调试 Reader，不得通过继续放大预算回避消费问题。

记录但不在可用性前设为硬门：

```text
capture/projection throughput
read-after-write latency
retrieval P50/P95
Qwen tokens and latency
hydrated/visible Evidence count
cost per correct operation
```

## 9. 实验指标与证据

### 持久化和用户边界

```text
CaptureSuccessRate
SourceIdentityIntegrity
IdempotentReplayDuplicateRows
RestartRecallRate
ProjectionReadyRate
CrossTenantReadLeak
CrossTenantWriteLeak
CrossTenantProjectionLeak
UnauthorizedCanonicalMutation
```

### 检索和 Context

```text
AnyGoldSessionRecall
AllRequiredEvidenceGroupRecall
ReaderVisibleEvidenceGroupCoverage
FirstGoldRank
NewRegionRate
RepeatedRegionRate
ContextTokenCount
```

### 模型证据消费

```text
TaskAccuracy
Exact / normalized F1 / Qwen Judge
EvidenceAliasValidity
SupportCoverage
SetMemberPrecision / Recall
QuantityAccuracy
DedupAccuracy
ArithmeticConsistency
UnsupportedAnswerRate
CorrectLookupRegression
```

### 运行可用性

```text
OpenWorkerOperationSuccess
McpResolveCalls
McpCaptureCalls
ProviderCalls
SystemFailureRate
AutomaticSemanticRetry = 0
CanonicalMutation = 0
```

## 10. 轻量证据与开发效率

本 Goal 只保留：

```text
1 份 Goal
1 份就地更新的 Tracker
1 份 Lab experiment plan
1 个 append-only failure-ledger.jsonl
每个有意义 run 一个 compact summary.json
终态时 1 个 terminal.json
```

不要求每个小修复建 receipt、manifest、witness 和独立环境。代码变更使用 targeted test；
影响真实路径时跑同族 OpenWorker case；Block 结束时再跑受影响包的完整门。

## 11. 终态决策

### PASS

```text
PASS_PRODUCT05_OPENWORKER_MEMORY_USABLE
```

条件：

- P05-H1 全部通过；
- P05-H2 达到固定 Context effect 门；
- 24-case opened-development 真实 OpenWorker 中，treatment 相对 direct baseline
  至少多 4 个正确 case，增益横跨至少 3 个能力族；
- ordinary lookup 正确 case 回归为 0；
- 跨 tenant 泄漏、未授权 Canonical mutation、隐藏 semantic retry 均为 0。

### PARTIAL

```text
PARTIAL_PRODUCT05_MEMORY_LIFECYCLE_USABLE_READER_CONSUMPTION_UNRESOLVED
```

条件：P05-H1 通过，但 P05-H2 在 3 轮通用修复后仍未建立。这时仍交付可用的
OpenWorker 写入/持久化/召回闭环，保留 direct Reader，不默认开启失败 treatment。

### FAIL

```text
FAIL_PRODUCT05_USER_ISOLATION_OR_MEMORY_AUTHORITY
```

只用于跨 tenant 泄漏、Evidence 损坏或未授权 Canonical mutation。普通 case 错误不得使用该终态。

## 12. 开发完成顺序

```text
B0 对齐当前事实
→ B1 完成 OpenWorker write/read/restart/two-user 闭环
→ B2 固定 Context 证明模型证据消费
→ B3 多类型真实 LME 单点失败修复与逐级扩展
→ B4 选择最小通过方法并交付
```

每个 Block 通过后直接进入下一 Block，不需要新的用户授权。可恢复失败按第 6 节
反思、修复和续跑。只有硬停止条件、public contract/schema 变更或 formal holdout 才需要
新授权。

## 13. 当前不进入

```text
自由搜索 Agent
默认多轮 ReFind
全局 Graph truth store
自动 profile/Claim promotion
single-process dynamic multi-tenant SaaS
物理 blob 全部迁入 PostgreSQL
formal LongMemEval 500-case
Schema freeze / production release
```

这些只在最小产品闭环完成后，由真实失败证据触发后续 Goal。
