---
document_id: MILA-PRODUCT-06
version: "1.0"
status: PLANNED_AWAITING_EXECUTION_AUTHORIZATION
created_at: "2026-09-03T07:48:12+08:00"
parent: MILA-PRODUCT-GOALS@1.9
predecessor: MILA-PRODUCT-05
execution_authorized: false
opened_development_lme_authorized: false
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
database_migration_authorized: false
canonical_authority_change_authorized: false
local_vllm_qwen_planned: true
---

# MILA-PRODUCT-06：Reader 集合证据消费与最小执行闭环

## 1. 目标

Product-06 只解决一个已经由 Product-05 定位的问题：

> 当所需 Evidence 已经进入 Reader-visible Context 时，怎样让本地 vLLM Qwen 稳定地读取多条证据、保留成员身份，并完成必要的集合或数值操作。

目标路径是：

```text
固定且可追溯的 Reader-visible Evidence
→ 判断失败来自 Context、模型理解还是计算
→ 只实现一个被诊断支持的最小机制
→ 真实 OpenWorker MCP 多类型验证
→ 选择可用的最简单产品路径
```

本 Goal 不重做 Product-05 已通过的持久化、租户隔离和写入生命周期，不恢复
TypeBinding，也不以增加 Prompt、Top-k 或规则枚举代替根因定位。

## 2. 当前机器事实

Product-05 的权威终态是：

```text
PARTIAL_PRODUCT05_MEMORY_LIFECYCLE_USABLE_READER_CONSUMPTION_UNRESOLVED
```

已经建立的事实：

- 两个 tenant 的真实 PostgreSQL → MCP → OpenWorker → Qwen 闭环通过；
- capture、projection、restart recall、source identity 和 support lineage 通过；
- 跨 tenant 读写/投影泄漏、重复写入、自放大和 Canonical mutation 均为 0；
- `direct` 固定 Context baseline 为 8/12；
- `inventory` 为 7/12；
- one-pass grounded 在 scorer 修正后仍为 8/12；
- ledger 最终可执行对比为 7/9 对 6/9，只新增 1 个正确 case，且只来自
  `STATE_UPDATE`；
- ledger 最终运行另有 4 个 `EVIDENCE_USE_CALCULATION_INVALID` Host 拒绝，随后发生
  4 次可见 transport repeat；
- 三轮 Prompt/schema 方向的通用修复没有达到跨能力族增益门，因此 direct 继续为默认；
- formal LongMemEval 500-case 未使用。

这组证据否定的是：

```text
继续叠加一个统一 structured answer Prompt
→ 就能稳定解决所有集合、比较、时间和更新问题
```

它没有区分以下四种不同原因：

```text
CONTEXT_PRESENTATION
READER_MODEL_CAPABILITY
MEMBER_EXTRACTION_OR_IDENTITY
DETERMINISTIC_OPERATION
```

Product-06 先做这个区分，再写产品代码。

## 3. 范围与硬边界

### 3.1 本轮负责

- 固定 EvidenceSet 上的 Reader 因果诊断；
- lossless Context 表达、Reader 模型选择或最小计算辅助中的一个必要机制；
- 真实 OpenWorker MCP 下的多类型效果；
- 删除或隔离未被选择的 Product-05 Reader 实验分支，避免继续扩张 Host；
- 保持 direct 作为始终可用的 fallback。

### 3.2 本轮不负责

```text
Evidence 没有被检索到
temporal range completeness proof
Canonical Claim promotion
Formation / Graph / active refinding
自由搜索 Agent
数据库 Schema 或 migration
public MCP/API shape
formal LongMemEval 500-case
```

如果一个 case 的 answer-bearing Evidence 不在 Reader-visible Context，首损记为
`EVIDENCE_NOT_VISIBLE` 并路由给后续 retrieval Goal；不得在 Product-06 内用 Reader Prompt
掩盖。

### 3.3 继续冻结的 authority

模型和 Reader 辅助层都不能：

```text
宣告 Requirement COMPLETE
接受或拒绝 Canonical truth
选择 tenant/scope/permission
修改 ClaimVersion/OpenIssue
把模型输出重新当作独立 user evidence
```

## 4. 两个主要假设

### P06-H1 — 固定 Evidence 上的最小通用消费机制

在 Evidence identity、EvidenceSet、source spans 和总预算固定的情况下，经因果诊断选择的
一个最小机制，能够相对当前 direct Reader 新增至少 3 个正确 case，增益横跨至少 2 个
能力族，同时 ordinary lookup 正确病例不回归。

### P06-H2 — 真实 OpenWorker 产品可用性

通过 P06-H1 的最小机制在真实 OpenWorker → MCP → Runtime → local vLLM Qwen 路径上，
能相对 direct 新增至少 4 个正确 case、净增至少 3 个、增益横跨至少 3 个能力族；Host
拒绝、OpenCode transport repeat、新 unsupported answer、跨 tenant 泄漏和 Canonical mutation
均为 0。

### 不主张

本 Goal 不主张 100% QA、官方 LongMemEval 等价、模型能证明集合完备，或一种 Reader
协议适用于所有 memory query。

## 5. 先定位瓶颈：固定 Context 诊断矩阵

Product-05 已打开的 12 个固定 Context 只用于诊断，不再承担独立验证。

### 5.1 诊断单元

每个 case 同时保存：

```text
source Evidence identities
Reader-visible exact bytes
aliases and span offsets
model/tokenizer/chat-template identity
direct answer
gold evidence roles（仅 Lab scorer 可见）
```

### 5.2 最小矩阵

| 诊断 | 输入与执行 | 只回答什么 |
| --- | --- | --- |
| D0 | 当前 Qwen + 完整固定 Context + direct | 当前真实基线 |
| D1 | 当前 Qwen + gold-supported 最小 Context + direct | Context 噪声/定位是否是瓶颈 |
| D2 | 至多一个本地可用的替代 Qwen Reader + D0 完整 Context | 当前 Reader 模型能力是否是瓶颈 |
| D3 | 当前 Qwen 只列 grounded observations/members，不要求最终计算 | 模型是否已经找全成员而只在计算阶段失败 |

D1 是带标签的诊断上界，不是产品 treatment，不能进入 P06-H1/P06-H2 效果分数。D2 只有
在本机已有兼容 vLLM Qwen endpoint 时执行；不下载新模型不会阻塞其余开发。

### 5.3 唯一 first-loss taxonomy

```text
EVIDENCE_NOT_VISIBLE
CONTEXT_LOCALIZATION
MODEL_EVIDENCE_EXTRACTION
MEMBER_IDENTITY_OR_DEDUP
NUMERIC_OR_TIME_NORMALIZATION
OPERATION_SELECTION
OPERATION_EXECUTION
FINAL_ANSWER_REALIZATION
HOST_PROTOCOL_REJECTION
SCORER_OR_JUDGE
INFRASTRUCTURE
UNRESOLVED
```

一个 case 先记录最早可证实层，不在同一记录里同时归因给检索、Reader 和 scorer。

## 6. 允许选择的三个最小修复路径

诊断完成后按证据选择一个主路径；没有证据的路径不实现。

### Path A — Lossless Evidence Cards

进入条件：同一 Qwen 在 D1 明显优于 D0。

只改变 Context 表达：

```text
原始 Evidence span
+ stable alias
+ speaker/session/time/source lineage
+ compact boundary
```

不做生成式 summary，不删除 Raw span，不建立 ontology。借鉴 OpenViking 的分层可见性，
但不引入新的虚拟文件系统或持久格式。

### Path B — Reader Model Configuration

进入条件：D2 在相同完整 Context 上明显优于 D0，而 D1 不能解释主要差距。

Product 只形成可配置、可探测的 Reader backend/profile；不把某个模型名写入语义逻辑。
测试使用本地 vLLM Qwen，不使用 OpenAI GPT-4o。模型不可用时回到 direct 当前配置。

### Path C — Query-local Evidence Worktable + Safe Reducer

进入条件：D3 已正确提取成员/数值，而最终答案主要在计数、去重、求和、差值、排序或
时长计算失败。

模型只输出带可见 Evidence alias 的临时 rows；Host 对显式 rows 执行小型通用 reducer：

```text
COUNT_ROWS
COUNT_DISTINCT
SUM
DIFFERENCE
ORDER
DURATION
```

这是一次 query-local 计算，不是 TypeBinding：

- 不预先把 Raw prose 绑定为领域 operand；
- 不产生 Requirement status 或 `COMPLETE`；
- 不证明集合已穷尽；
- 不改变 Evidence acceptance 或 Canonical State；
- reducer 失败时返回一次明确 fallback，不抛出导致 OpenCode 重发的 Host rejection。

若 operation 或 rows 不足，直接使用 direct answer/明确不足，不猜测缺失输入。

### 6.4 不允许的组合

第一轮不得把 A+B+C 全部叠加。只有单一路径通过独立验证后，机械 reducer 才能作为
已证明 Reader 的附属执行器；不得用组合掩盖哪一项真正有效。

## 7. 五个连续开发阶段

这里的“阶段”只是工作顺序，不是每一步都要新增审批、receipt 或环境。获得一次执行授权
后，非硬停止失败会自动进入反思、修复和后续阶段。

### R0 — 固定 Context 瓶颈诊断

任务：

- 复用 Product-05 已打开的 12-case Context 与 scorer；
- 执行 D0–D3；
- 每个失败 case 只写一条 compact first-loss 记录；
- 形成 Path A/B/C 的排序及明确排除理由；
- 不修改 Product 行为。

完成条件：12/12 都有 `first_loss` 或诚实的 `UNRESOLVED`，并且 oracle、产品臂和模型
探针不会混为同一种证据。

### R1 — 实现一个最小机制

任务：

- 只实现 R0 排名第一且有跨 case 支持的 Path；
- 逻辑放入一个小的 Reader strategy 边界，不继续膨胀 `host_adapter.py`；
- direct 保留为 fallback；
- 失败的 `inventory/grounded/ledger` 不再扩展。若新路径通过，旧路径从支持表面移除或
  明确隔离为 Lab history；
- 添加同族正例、改写正例和无关负例的 targeted tests。

完成条件：无 public API/Schema/DB/Canonical 变化；Host 失败只产生一个终态响应，不触发
native operation 重发。

### R2 — 独立 12-case 固定 Evidence 验证

从非 formal holdout 中 outcome-blind 地冻结 12 个新 case，六个能力族各 2 个：

```text
ordinary user lookup
assistant-source recall
set/count
comparison/arithmetic
temporal/state update
insufficient/abstention
```

direct 与 treatment 共用 source Evidence、EvidenceSet、alias、Reader token ceiling、sampling
和 scorer。只有 Context 表达是 treatment 时，序列化 bytes 才允许不同，但 underlying
Evidence identities 必须完全相同。

P06-H1 门：

```text
completed paired cases                         12/12
new correct cases                              >= 3
gain families                                  >= 2
ordinary lookup correct-case regression         0
new unsupported answers                         0
visible alias/span validity                   1.0
Host protocol rejection                         0
automatic semantic retry                        0
```

### R3 — 24-case 真实 OpenWorker 确认

仅当 R2 通过才进入。使用与 R2 不重叠的 24 个 outcome-blind non-holdout case：

```text
historical sessions
→ Host-owned capture and PostgreSQL projection
→ real OpenWorker operation
→ reader MCP / Runtime MemoryContext
→ local vLLM Qwen
→ deterministic scorer; Qwen judge only for open text
```

两臂使用隔离 tenant namespace 和相同历史输入。允许按实际资源最多 4 个 case stack 并发，
vLLM 并发由 capability probe 决定；不得以并发改变 sampling 或 Context。

P06-H2 门：

```text
new correct cases                              >= 4
net correct gain                               >= 3
gain families                                  >= 3
lost correct ordinary lookups                    0
total lost correct cases                       <= 1
new unsupported answers                         0
Host rejection / transport repeat             0 / 0
cross-tenant leak / Canonical mutation         0 / 0
automatic semantic retry                        0
```

### R4 — 产品收口与简化

若 R3 通过：

- 将最小方法设为 OpenWorker memory-answer 的选择路径；
- 保留 direct fallback 和模型不可用退化；
- 删除或隔离未选的 Reader 实验分支，减少生产 Host 复杂度；
- 更新安装、配置、运行手册和 Product/Lab 状态；
- 运行受影响包 tests、Ruff、strict mypy、build，以及一次真实 OpenWorker/PostgreSQL smoke。

若 R2 或 R3 未通过：

- direct 继续默认；
- 仍完成失败定位、代码清理和文档交付；
- 终态为 PARTIAL，而不是把普通错答升级成架构安全失败。

## 8. 失败后的反思、修复与自动续跑

### 8.1 通用循环

```text
失败 case
→ 找到 first loss
→ 检查同族另一个 case
→ 形成跨 case root-cause hypothesis
→ 只修最早层
→ 单点测试
→ 同族回归
→ 当前冻结 slice 回归
→ 通过后自动继续下一阶段
```

R0 之后最多实现两个有独立诊断证据的 treatment family；每个 family 最多一次机制修正。
这限制的是盲目调参，不限制修复明确的代码 bug、scorer bug 或基础设施故障。

### 8.2 失败路由

| First loss | Product-06 处理 |
| --- | --- |
| `EVIDENCE_NOT_VISIBLE` | 不改 Reader；登记 retrieval successor |
| `CONTEXT_LOCALIZATION` | Path A |
| `MODEL_EVIDENCE_EXTRACTION` | Path A 或 B，以 D1/D2 区分 |
| `MEMBER_IDENTITY_OR_DEDUP` | 先检查 grounded rows；只做 query-local identity，不建全局 ontology |
| `OPERATION_EXECUTION` | Path C |
| `HOST_PROTOCOL_REJECTION` | 修 Host 终态/fallback；禁止触发重发 |
| `SCORER_OR_JUDGE` | 修评测，旧结果标 invalid，不改 Product |
| `INFRASTRUCTURE` | 同输入恢复失败 case；不计为语义 retry |

### 8.3 只有四类硬停止

```text
跨 tenant 数据泄漏
未授权 Canonical mutation
Raw Evidence 损坏或丢失
目标需要 public API/Schema/migration/destructive change
```

其他 case 错答、模型输出错误、Host protocol bug 和临时服务故障均应诊断后继续。

### 8.4 禁止的刻板修复

```text
case ID / reference answer / gold quote 进入 Product
为某种衣物、电话号码、实体或问句加专用规则
恢复 TypeBinding 或新的 query-type 状态机
按 COUNT/COMPARE 关键词硬路由
固定同义词表修 benchmark
统一增加 Top-k/token 掩盖 Reader miss
第四轮 Prompt/schema 堆叠
换 seed、投票或隐藏 semantic retry
用模型 confidence 宣告证据完整
```

## 9. 数据、预算和评分

### 9.1 数据分层

```text
R0: Product-05 已打开 12 cases，只做诊断
R2: 新的 12-case outcome-blind non-holdout validation
R3: 新的 24-case outcome-blind non-holdout confirmation
formal 500: 不授权、不运行
```

Outcome-blind 允许使用 capability family、answerable flag、session/evidence topology；不允许
用当前答对/答错、gold 词面或 treatment rank 选择 case。

### 9.2 Accuracy-first 预算

可用性优先，预算先作为上限而不是优化目标：

```yaml
max_candidates: 240
max_reader_context_tokens: 32768
provider_context_limit: 65536
answer_output_tokens: 4096
max_model_calls_per_arm: 2
semantic_retry: 0
votes: 0
```

R0/R2 固定 Evidence 时不重新 acquisition。R3 只有当 Evidence 不可见才报告 retrieval miss，
不得自动继续扩大预算。

### 9.3 核心指标

```text
TaskAccuracy
SetMemberPrecision / SetMemberRecall
MemberIdentityDedupAccuracy
NumericTimeNormalizationAccuracy
OperationSelectionAccuracy
OperationExecutionAccuracy
EvidenceAliasSpanValidity
UnsupportedAnswerRate
CorrectLookupRegression
HostProtocolRejection
TransportRepeat
ProviderCalls
SystemFailureRate
```

数字、集合和精确字符串使用确定性 scorer；开放文本才使用本地 vLLM Qwen judge，并明确
same-model self-judge 不等于官方 LongMemEval Judge。

## 10. 简洁实现与验证纪律

### 10.1 复杂度预算

- 最多新增一个内部 Reader strategy protocol；
- 不新增 Runtime domain state、数据库表或 MCP tool；
- 不为每个能力族建立 schema；
- 优先一个 Provider call；只有诊断证明分离 extraction/finalization 必要时允许两个；
- 不复制 Context、RequirementState 或 Canonical validator；
- validation 只放在模型输出、Host I/O 和 authority 边界；
- Product-05 被否定的 modes 不再继续增加分支。

### 10.2 测试顺序

```text
失败 case 的一个 targeted test
→ 同族 tests
→ OpenWorker MCP package tests / Ruff / mypy / build
→ 真实 OpenWorker + fresh PostgreSQL smoke
```

Runtime、MCP 或数据库没有受影响时，不要求重跑无关全仓库/全 migration 审计。每个阶段只
保存一个 summary；整个 Goal 只需要一个 tracker、一个 failure ledger 和一个 terminal。

## 11. 参考项目只在失败时提供最小机制

| 本地失败 | 可参考项目 | 允许借鉴 | 不引入 |
| --- | --- | --- | --- |
| Context 定位/展开 | OpenViking | lossless 分层 Evidence cards、按需展开 | 新存储系统 |
| Evidence 尚未出现 | Hindsight / ReFind | 后续 Goal 的 multi-channel 或 observation-conditioned opportunity | 在本 Goal 启动搜索 Agent |
| 时间/实体关联 | Graphiti | provenance-linked event/time projection 的设计启发 | 图成为 truth store |
| 用户存取接口 | Mem0 / Hindsight | Product-05 已完成的显式用户 namespace | 第二套用户数据库 |
| harness 混淆 | LongMemEval harness | 固定输入、分开 retrieval/Reader/scorer | 用 Judge 掩盖系统故障 |

借鉴前必须先有本地 first loss；不得因为参考项目具备某功能就直接加入默认架构。

## 12. 终态

### PASS

```text
PASS_PRODUCT06_READER_CONSUMPTION_USABLE
```

P06-H1、P06-H2 均通过，最小方法进入产品选择路径，direct fallback 保留。

### PASS（配置结论）

```text
PASS_PRODUCT06_READER_MODEL_CONFIGURATION_SELECTED
```

若唯一有效变化是同 Context 上的本地 Qwen Reader 配置/模型选择，则只交付配置和 probe，
不制造新的 Memory protocol。

### PARTIAL

```text
PARTIAL_PRODUCT06_BOTTLENECK_LOCALIZED_KEEP_DIRECT
```

瓶颈已定位但两个有依据的最小 treatment 都未建立跨能力族增益。保留 direct，删除未选
复杂性，并把明确的 retrieval、model capacity 或 temporal substrate 缺口路由给后续 Goal。

### FAIL

```text
FAIL_PRODUCT06_MEMORY_AUTHORITY_OR_TENANT_SAFETY
```

只用于跨 tenant 泄漏、Raw Evidence 损坏或未授权 Canonical mutation。普通效果 miss 不用
FAIL 终态。

## 13. 执行授权与下一步

本文件是设计，不构成执行授权。当前允许阅读、评审和修改文档；不得启动 vLLM effect、
新 LME slice 或 Product behavior change。

用户后续一次明确授权即可覆盖 R0–R4 的连续执行。授权后：

```text
阶段通过 → 自动进入下一阶段
可恢复失败 → 通用反思修复后继续
安全硬停止或范围扩张 → 才请求新授权
```

