---
document_id: MILA-PRODUCT-06
version: "1.1"
status: COMPLETE_PARTIAL
created_at: "2026-09-03T08:00:31+08:00"
supersedes: MILA-PRODUCT-06@1.0
parent: MILA-PRODUCT-GOALS@1.9
predecessor: MILA-PRODUCT-05
execution_authorized: true
opened_development_lme_authorized: true
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
database_migration_authorized: false
canonical_authority_change_authorized: false
local_vllm_qwen_planned: true
---

# MILA-PRODUCT-06：vLLM 语义证据工作区与可靠回答

## 1. 修正后的目标

Product-06 解决的不是数据库 Ledger，也不是再增加一种 Query Type，而是替换 Product-05
失败的模型证据消费合同：

> 让 Qwen 在 vLLM 承载的有界 Reader 会话中，自主理解 Reader-visible Evidence、形成临时语义草稿，并在需要时调用通用安全工具；Host 只治理输入、工具、引用、预算和最终交付，不规定模型必须用哪一种结构思考。

目标路径：

```text
Question + governed Reader-visible Evidence
→ model-native semantic reasoning
→ direct answer OR optional safe tool call
→ tool result returned to the same Reader session
→ final answer with visible Evidence references
→ one OpenWorker terminal delivery
```

这是一条可用性优先的 Reader 路径。它不恢复 TypeBinding，不要求先把自然语言变成固定
operand，不让模型获得 Canonical authority，也不把 vLLM cache 当作 Memory State。

## 2. Product-05 真正证明了什么

### 2.1 Memory lifecycle 已通过

Product-05 已建立两 tenant 的真实 PostgreSQL → MCP → OpenWorker → Qwen 闭环。capture、
projection、restart recall、source identity、assistant support lineage 和 tenant isolation 均
通过；Canonical mutation、重复写入和自放大均为 0。本轮不重开这些问题。

### 2.2 `EvidenceLedgerV01` 是模型草稿，不是数据库账本

当前 Ledger 由模型在正式回答前生成：

```json
{
  "support": [],
  "members": [],
  "calculation": {"expression": "1 + 1 + 1", "result": 3},
  "uncertainties": []
}
```

Host 要求模型同时满足：

```text
固定 support/member/calculation schema
每个 member.quantity 必须出现在表达式
表达式只含数字与 + - * /
Host 重算结果必须完全一致
普通查询 calculation 必须为 null
```

第一遍生成 Ledger，第二遍再读取 Ledger 和 Context 生成最终答案。这个设计把以下不同任务
绑成了一份强制中间表示：

```text
语义理解
相关证据识别
成员身份与去重
数值归一化
运算表达
回答状态
```

最终实验中有 4 个 case 被 `EVIDENCE_USE_CALCULATION_INVALID` 拒绝，并触发 4 次可见
transport repeat；完成的 9 对中只比 direct 多 1 个正确 case，且只来自一个能力族。

因此当前问题不是“Host 还缺几个算术规则”，而是：

> 一个固定 Ledger schema 被错误地当成了模型必须遵循的通用认知过程，结构差异又被升级成整次回答失败。

### 2.3 vLLM 的正确作用

vLLM 是本地模型执行后端。泛化能力来自 Qwen 的语义判断；vLLM 提供 OpenAI-compatible
chat、guided output/tool-call compatibility、连续批处理和有界推理执行。Product-06 利用
这些能力让模型选择自己的推理路径，而不是让 vLLM 或 Host 决定事实成立。

## 3. 新 Reader 设计：Model-native, Host-governed

### 3.1 `VllmEvidenceReaderSession`

内部工作名，最终名称服从代码语境：

```yaml
ReaderSessionInput:
  question:
  reader_visible_context:
  visible_evidence_aliases:
  source_identity_digest:
  model_profile:
  max_turns:
  token_budget:

ReaderSessionResult:
  answer_text:
  valid_cited_aliases: []
  tool_calls: []
  stop_reason:
  provider_usage:
```

这不是新的 Memory State。Session 在一次回答后销毁；只持久化最终答案、有效引用、工具
调用摘要和执行 identity，不持久化隐藏 reasoning 或自由草稿。

最终回答可以是自然语言。Host 始终记录本轮 Context digest；模型给出的有效 alias 只用于
收窄 support lineage。缺少 citation 不应令一次可用答案失败，伪造或不可见 citation 也不会
被写入 support lineage。

### 3.2 模型拥有的语义自由

模型可以：

```text
直接回答普通 lookup
自行浏览完整 Context
在内部形成自由格式 evidence sketch
识别、比较和合并相关成员
决定是否需要计算器
根据工具结果修正最终答案
在证据不足时自然地说明不足
```

模型不必输出：

```text
support 数组
members 数组
calculation proof
Requirement enum
typed operand
COMPLETE
```

### 3.3 Host 只控制五件事

```text
1. 传给模型的 Evidence 已通过权限和 revocation 边界
2. 可调用工具来自固定 allowlist
3. 工具参数不会执行任意代码或访问外部资源
4. 引用 alias 必须属于 Reader-visible Evidence
5. 最大轮数、token、timeout 和一次 OpenWorker 终态交付
```

Host 不再检查：

```text
每个语义成员是否被表示为 quantity
每个 quantity 是否逐字出现在 expression
模型是否按预设步骤思考
模型的集合是否已经完备
自然语言事实是否应该成为 Claim
```

### 3.4 一个通用安全工具

第一版只提供 adapter-internal 的 `calculator`，不新增 MCP tool，也不暴露给 OpenWorker
Agent 的普通工具列表：

```yaml
calculator:
  input:
    expression: string
  output:
    value: decimal
```

它只做安全、纯函数的数值计算。Host 可以限制 AST、长度、非有限数和除零，但不要求
表达式复述整个语义 Ledger。语义映射、是否调用、如何使用结果由模型负责。

例如：

```text
模型从 Context 识别三件衣物
→ 自己决定调用 calculator("1 + 1 + 1")
→ Host 返回 3
→ 模型用自然语言回答并引用相关 Evidence
```

百分比、差值和单位换算使用同一个工具，不新增 `COUNT`、`PERCENTAGE`、`DURATION` 专用
协议。日期解析、集合完备性和身份判断仍是语义问题，calculator 不假装解决。

### 3.5 有界会话

```text
Round 1:
  Qwen reads question + Context
  → final answer
  OR one/multiple calculator calls

Round 2（只有发生 tool call）:
  Qwen receives exact tool results
  → final answer
```

默认最大两次 Provider 调用，不做投票、换 seed 或语义 retry。一个 round 可包含多个
calculator calls；不允许工具结果再次触发第三轮开放式 Agent loop。

### 3.6 vLLM capability adapter

执行前探测本机 endpoint：

```text
model identity / revision
tokenizer / chat template
native tool parser availability
named/auto tool behavior
structured-output fallback
thinking/reasoning profile availability
max context / output
timeout and concurrency
```

优先使用本机已支持的 native tool call。若 endpoint 没有可用 tool parser，adapter 可以用
一个最小 action envelope：

```yaml
action: ANSWER | CALCULATE
answer_text: optional
evidence_aliases: []
expression: optional
```

这个 envelope 只解决传输，不规定模型如何组织证据。它与 `EvidenceLedgerV01` 不同：没有
成员 ontology、算术证明、完成状态或领域类型。

## 4. 两个主要假设

### P06-H1 — Model-native Reader 泛化增益

在 source Evidence、Reader-visible Context、模型 identity 和预算匹配的独立 12-case 上，
model-native vLLM Reader 相对 direct 新增至少 3 个正确 case，增益横跨至少 2 个能力族；
普通 lookup 不回归，Host protocol rejection 和新 unsupported answer 为 0。

### P06-H2 — 真实 OpenWorker 可用性

通过 P06-H1 的 Reader 在 24 个新的 non-holdout case 上经真实 OpenWorker → MCP → Runtime
→ vLLM 路径，相对 direct 新增至少 4 个正确 case、净增至少 3 个、覆盖至少 3 个能力族；
transport repeat、tenant leak、Canonical mutation 和 semantic retry 为 0。

## 5. 五个连续开发阶段

阶段是执行顺序，不是五套审批。用户一次授权后，可恢复失败会自动反思、修复并继续。

### R0 — Ledger 失败复盘与 vLLM capability probe

- 只读复盘 Product-05 已打开 case 的原始 Ledger、final answer 和 Host rejection；
- 将失败压缩为五类：`EVIDENCE_MISREAD / SEMANTIC_OMISSION / TOOL_PROTOCOL /
  FINAL_REALIZATION / INFRASTRUCTURE`；
- 用 2 个普通 lookup、2 个集合/计算 case 探测 native tool、structured fallback 和可选
  reasoning profile；
- 确认工具结果能以 `tool` role 回注且 OpenWorker 只收到一个最终终态；
- 不修改 Product 默认行为。

退出条件：选择一种 endpoint-compatible transport；明确 Ledger schema failure 与模型语义
failure 的比例，不再把二者合并为“Qwen 错答”。

### R1 — 实现一个 model-native Reader boundary

- 新逻辑从 `host_adapter.py` 分离为小的 Reader session 组件；
- 删除“先强制 Ledger 再强制 Grounded JSON”的控制流；
- direct 继续 fallback；
- calculator 只在 Reader session 内可用，不进入 MCP/OpenWorker tool surface；
- 引用非法、工具参数非法或响应不完整时，Host 返回一个单次 fallback/insufficient 终态，
  不抛出导致 native operation 重发的异常；
- 不修改 QueryIR、Binding、Sufficiency、数据库或 Canonical Core。

### R2 — 12-case 固定 Context 验证

从 formal holdout 外 outcome-blind 地冻结 12 个新 case，至少覆盖：

```text
ordinary user lookup
assistant-source recall
set/count
comparison/percentage/unit conversion
temporal/state update
insufficient/abstention
```

比较：

```text
B0 current direct
B2 model-native vLLM Reader
```

Product-05 的 strict Ledger 结果只进入 R0 根因复盘，不在新的 V0 上重复消耗；它不是
Product-06 的候选臂。

B0/B2 必须共用 exact Context identities、model、sampling 和 token ceiling。若 R0 证明可选
reasoning profile 是必要变量，则在冻结 V0 前选定，不在结果后切换。

P06-H1 门：

```text
paired completed cases                         12/12
new correct                                    >= 3
gain families                                  >= 2
ordinary lookup correct regression               0
new unsupported answer                           0
invalid visible citation                         0
Host protocol rejection                          0
transport repeat                                 0
semantic retry                                   0
```

### R3 — 24-case 真实 OpenWorker 确认

仅 R2 通过后进入，与 R2 不重叠：

```text
historical sessions
→ Host-owned capture
→ submitter MCP
→ PostgreSQL + projection
→ native OpenWorker operation
→ reader MCP / Runtime Context
→ model-native vLLM Reader
→ deterministic scorer + local Qwen judge for open text
```

P06-H2 门：

```text
new correct                                    >= 4
net correct                                    >= 3
gain families                                  >= 3
ordinary lookup correct losses                   0
all correct-case losses                        <= 1
new unsupported answer                           0
Host rejection / transport repeat              0/0
tenant leak / Canonical mutation               0/0
semantic retry                                   0
```

### R4 — 收口、简化与交付

若 R3 通过：

- 将 model-native Reader 设为 memory-answer 默认，direct 为服务不可用/协议不兼容 fallback；
- 从支持表面移除 `inventory/grounded/ledger`，历史实现可留在 Lab 或删除未使用 Product
  分支；
- 更新 OpenWorker 配置、运行手册和 Product/Lab 状态；
- 跑受影响 package tests、Ruff、strict mypy、build 和一次 fresh PostgreSQL real-chain smoke。

若 R2/R3 未通过：保留 direct，仍完成 Ledger 问题定位和 Host transport 简化，终态为
PARTIAL；不把普通效果 miss 误写成 safety failure。

## 6. 失败后的灵活修复

```text
失败 case
→ 判断是 evidence misread、tool protocol 还是 final realization
→ 检查同族另一个 case
→ 修一个共享机制
→ 单点测试
→ 同族 replay
→ 当前 slice replay
→ 通过后自动继续
```

允许的修复：

- 调整一次通用 Reader system contract；
- 修 vLLM tool/structured-output adapter；
- 对工具结果使用标准 `tool` role；
- 在诊断支持时选择 bounded reasoning profile；
- 修 Context 中 alias/source boundary 的通用表达；
- 修 Host “协议错误 → operation 重发”的交付语义。

禁止的修复：

```text
添加 Ledger 字段或新的能力族 schema
要求每个 member.quantity 进入表达式
恢复 TypeBinding / typed operand / COMPLETE
COUNT、衣物、电话、百分比等关键词规则
case ID / gold answer / gold phrase
统一扩大 retrieval 预算修 Reader-visible 错答
seed search、投票、隐藏 retry
```

同一 model-native 机制允许两次跨 case 修正；之后若仍无增益，保留 direct 并诚实 PARTIAL，
不再进入新的 Prompt 格式循环。

## 7. 预算与高效执行

```yaml
max_candidates: 240
max_reader_context_tokens: 32768
provider_context_limit: 65536
answer_output_tokens: 4096
max_provider_rounds: 2
max_tool_calls_in_round: 4
semantic_retry: 0
votes: 0
```

可用性优先，不用紧预算屏蔽错误。vLLM 运行时按 capability probe 使用连续批处理：最多
4 个隔离 case stack 并发，生成并发由显存/queue probe 决定；不以并发改变采样和输入。
稳定 system/tool schema 可利用 prefix caching，但 cache 只用于性能，不承担 Memory identity。

基础设施失败只有在尚未生成答案时才可按相同输入恢复一次，并单独记为 infra recovery，
不是 semantic retry。

## 8. 指标

### 模型与工具

```text
TaskAccuracy
RelevantEvidenceUseRate
DistinctMemberRecall
FinalArithmeticAccuracy
ToolCallUsefulness
ToolCallValidity
ToolResultConsumptionRate
InvalidCitationRate
UnsupportedAnswerRate
CorrectLookupRegression
```

### 产品路径

```text
OpenWorkerOperationSuccess
ProviderRoundsPerAnswer
HostProtocolRejection
TransportRepeat
SystemFailureRate
CrossTenantLeak
CanonicalMutation
SemanticRetry
```

集合、数字、日期和精确字符串优先使用确定性 scorer。开放文本才使用本地 vLLM Qwen
judge；同模型 self-judge 必须披露，不声称官方 GPT-4o 等价。

## 9. 简洁性纪律

- 一个 Reader session 组件；
- 一个通用 calculator；
- 一个 final-answer delivery path；
- 不新增数据库对象、MCP tool、Runtime domain state 或 QueryIR enum；
- validation 只存在于 Evidence visibility、tool safety、外部 I/O 和 authority 边界；
- 不为内部已验证对象重复做防御式验证；
- targeted test → package quality → real-chain smoke；无影响的 Runtime/migration 套件不重跑；
- 每阶段一个 summary，整个 Goal 一份 tracker、一份 failure ledger、一份 terminal。

## 10. 终态

```text
PASS_PRODUCT06_VLLM_EVIDENCE_READER_USABLE
PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED
FAIL_PRODUCT06_MEMORY_AUTHORITY_OR_TENANT_SAFETY
```

PASS 需要 P06-H1/H2。PARTIAL 表示 Ledger 刻板合同已被定位/隔离，但新 Reader 未建立稳定
增益，direct 继续默认。FAIL 只用于 tenant 泄漏、Raw Evidence 损坏或未授权 Canonical
mutation。

## 11. 当前授权

用户已授权并执行：

```text
document review/edit     AUTHORIZED
R0/vLLM probe            AUTHORIZED / COMPLETE
Product code change      AUTHORIZED / COMPLETE
new LME case lock        AUTHORIZED / COMPLETE
R2 effect                AUTHORIZED / COMPLETE
R3 effect                AUTHORIZED / NOT_ENTERED_BY_GATE
formal 500               NOT AUTHORIZED
```

## 12. 执行终态（2026-09-03）

用户已明确授权 R0–R4。R0 证明 Product-05 的 6 个未成功 Ledger case 中，4 个是
`EVIDENCE_USE_CALCULATION_INVALID` 协议拒绝，另 2 个才是模型语义错误；主因不是 Memory
存储或召回。R1 已交付独立 `VllmEvidenceReaderSession`、最小 action transport、Host 内部安全
calculator、可见引用过滤和单终态 fallback，且没有增加数据库对象、MCP tool、QueryIR enum
或 Canonical authority。

R2 在冻结的 12 个 non-holdout case 上完成 12/12 配对、24 次真实 OpenWorker operation、
12 个隔离 tenant 和 fresh PostgreSQL 审计。更正 deterministic abstention scorer 对合法
“does not contain any information/records”措辞的假阴性后，direct 与 model-native 均为
7/12；新增正确 0、净增 0、正确 case 损失 0，unsupported、非法引用、Host rejection、
transport repeat、semantic retry、tenant leak 和 Canonical mutation 全为 0。

5 个 direct 错例中有 4 个的固定 Reader Context 缺少至少一个标注为必需的 Evidence group；
本 Goal 又明确禁止通过统一扩大 retrieval 预算修 Reader 错答。因此 H1 的 `>=3` 新增正确在
冻结 Evidence 边界内不可安全达到，继续循环 Prompt 不能恢复缺失事实。R3 按门禁未进入，
预冻结 24-case 和 formal 500 均未消费。direct 保持默认，model-native 仅保留为 default-OFF
诊断路径。终态为：

```text
PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED
```
