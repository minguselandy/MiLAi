---
document_id: MILA-MVP-01
version: "0.1"
status: READY_FOR_MASTER_ACTIVATION
document_type: PRODUCT_USABILITY_GOAL
created_at: "2026-09-01T10:57:22+08:00"
architecture_baseline: MILA-ML-ARCH@1.0
execution_order_authority: MILA-ML-MASTER
execution_authorized: false
activation_requirement: MILA-ML-MASTER_EXPLICITLY_ACTIVATES_MILA-MVP-01_WITH_EXACT_STAGE_AND_RUN_SCOPE
continuous_execution_after_activation: true
continuous_execution_policy: PASS_OR_SIMPLIFIED_WINNER_AUTO_ADVANCE
current_active_goal_at_creation: MILA-GDPM-01@0.3
current_active_attempt_at_creation: var/gdpm/gdpm-b0-20260901-003/terminal.json
current_active_attempt_status: FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED
handoff_required_before_activation: true
intended_successor_scope: USABILITY_FIRST_READ_PATH
preserves_sealed_history: true
formal_holdout_authorized: false
product_default_enable_authorized: false
canonical_schema_change_authorized: false
public_mcp_change_authorized: false
benchmark_reader_backend: LOCAL_VLLM_QWEN
benchmark_judge_backend: LOCAL_VLLM_QWEN
leaderboard_equivalence_claimed: false
development_control: LEAN_REPAIR_SIMPLIFY_CONTINUE
audit_policy: MINIMUM_SUFFICIENT_EVIDENCE
does_not_supersede:
  - architecture/v1.0
  - MILA-ML-ARCH@1.0
  - sealed_GDPM_DG_MF_MD_ML-CLOSURE_ML-R01_ML-R02_artifacts
does_not_authorize:
  - execution_before_master_activation
  - formal_holdout
  - product_default_enablement
  - public_MCP_or_canonical_schema_change
  - automatic_canonical_or_profile_promotion
  - free_search_agent_or_multi_round_refinding
---

# MiLAi MVP-01：高效可用 Memory 最小闭环 Goal

本 Goal 的首要任务不是完成全部 Memory Lifecycle 研究设计，而是尽快交付一条稳定、快速、可以实际使用和回退的个人记忆路径。复杂能力只有在最小路径已经可用、并且真实失败数据证明有必要时，才另立后续 Goal。

---

## 1. 核心目标

在不修改冻结架构、不新增第二套状态系统、不依赖 Formation 或搜索 Agent 的前提下，完成：

~~~text
OpenWorker / Host
→ existing MCP
→ Evidence capture
→ official FTS + Dense + Canonical exact retrieval
→ small quota union + identity dedup + RRF
→ true-session local context
→ whole-unit token admission
→ MemoryContext
→ one Reader call
→ answer with visible Evidence references or explicit insufficiency
~~~

这条路径必须同时满足：

- 写入后可在有界时间内检索；
- 普通事实、旧对话内容、多 session 记忆和当前 Canonical 状态可以被召回；
- scope、permission、revocation 和删除不能泄漏；
- 模型不可用时，exact / Canonical / FTS 路径仍可运行；
- 一次请求最多一次 Answer 模型调用；
- 不使用模型 planner、模型 reranker、多轮搜索或自动 retry 掩盖问题；
- 单一 feature flag 可以立即回到现有简单路径。

## 2. 什么叫“可用”

MVP 可用性由真实产品路径定义，不由架构对象数量定义。

| 维度 | MVP 门槛 |
| --- | --- |
| 首次运行 | 一个面向本地用户的 init/start/doctor 入口；无需手工填写 JSON、UUID 或多组服务 token |
| 写入可靠性 | Evidence capture terminal rate = 100%；不因派生索引失败丢失 Raw Evidence |
| 可检索时效 | 本地 read-after-write searchable P95 ≤ 5 秒；最大等待不超过 60 秒 |
| Context 可靠性 | 24-case = 24/24；100-request warm soak = 100/100；后续 128/500 benchmark terminal rate ≥ 99% |
| 身份真实性 | subject/session/source/turn identity integrity = 1.0；跨真实 session adjacency = 0 |
| Reader 输入 | visible trace exactness 和 serialization replay = 1.0 |
| 基础答案质量 | 24 个产品场景 task success ≥ 0.90；后续 128-case QwenJudgeAccuracy ≥ 0.20 |
| 检索覆盖 | answerable slice ReaderVisibleGoldSessionRecall ≥ 0.50 |
| 性能 | retrieval + Context P95 ≤ 2 秒；本地 Qwen 端到端 P95 ≤ 30 秒 |
| Memory 开销 | warm memory-control P95 单独报告且目标 ≤ 500 毫秒，不能被生成时延掩盖 |
| Token 效率 | Evidence hard cap = 8192 tokens；平均目标 ≤ 4096 tokens |
| 调用效率 | planner/reranker model calls = 0；Answer model calls ≤ 1 |
| 降级 | model outage deterministic fallback success = 1.0 |
| 安全 | CrossScopeLeak、RevokedEvidenceLeak、CanonicalMutationFromReadPath = 0 |
| 数据模式 | 默认 SYNTHETIC_ONLY；LOCAL_PERSONAL_DATA 只有 AES-256-GCM、备份与 key recovery doctor gate 通过后才允许 |
| 运维 | 每个请求都有 typed terminal；单一 flag 可恢复 baseline |

这些是产品可用门，不是论文排行榜声明。产品 golden flow 和 warm soak 先于 128/500 benchmark；500-case 的置信区间和显著性只用于描述泛化，不阻止已经通过本地产品门的 MVP。

## 3. 当前事实与为什么要新建本 Goal

历史实验已经提供足够的收敛依据：

| 事实 | 对 MVP 的含义 |
| --- | --- |
| ML-CLOSURE 500-case 中 Candidate 有 477/500 context failures | 先修交付与 worker，不先优化语义架构 |
| 旧 R4 折叠真实 session identity，trace 也不等于 Reader 实际可见内容 | 旧 R4 不作答案基线；先恢复输入真实性 |
| GDPM B0 targeted fixtures 的 identity、trace、serialization 六项门已通过 | 直接复用有效修复，不重新设计 |
| DG-24 发现 6 个 channel 未调用、1 个 cutoff loss | 简单 official multi-channel 已有明确机会 |
| DG-28 official union 将候选 4/7 提高到 7/7 | 先产品化简单 union，不建 planner |
| DG-26 StateView reranking 无稳定独立增益 | MVP 不引入 state-aware reranker |
| DG-19 residual cue 没有可靠 mediator gain | MVP 不引入 residual Provider 或多轮 refinding |
| DG-27 复杂 Binding 仍出现 Wrong COMPLETE 与回归 | 普通 recall 不依赖完整 typed completion |
| Formation 在历史 500-case 实际 applied = 0 | Formation 不能成为 MVP 启动依赖 |
| Canonical、Evidence、权限、撤销和版本骨架已经存在 | 保留，不重写 |
| 当前 GDPM 24-case attempt-003 仅 4/24 PASS | 先修缺 ContextReceipt 与 MCP output limit，不把当前 canary 描述成已通过 |
| Master/canary contract 仍引用 GDPM 0.2，而最新 Goal 为 0.3 | 新 Goal 激活前先统一 authority snapshot，不继承漂移身份 |
| 既有 OpenWorker/MCP 已有中文 recall、真实 write→chat 和 broker 恢复证据 | MVP 从现有产品链收窄，不从零开发 |

因此本 Goal 的方法命题只有一句：

> 先把现有 Raw、Canonical、FTS、Dense 和真实 session Context 接成一条可靠的简单产品路径，并把启动、记住、询问、纠正、忘记收敛成一个普通用户能完成的流程；如果最简单的合格实现已经可用，就停止增加复杂性。

## 4. MVP 架构边界

### 4.1 写入路径

~~~text
OpenWorker / MCP capture
→ Raw Evidence durable commit
→ projection delivery queue
→ FTS / Dense projection
~~~

写入确认以 Raw Evidence 成功落盘为准。Embedding、Formation 或其他派生处理失败只能降低后续 recall，不能使 Raw Evidence 写入失败或消失。

必须复用现有：

- EvidenceRecord / ContentBlob；
- source、session、turn、actor 和时间身份；
- scope、permission、retention、revocation；
- projection queue 与 worker lease renewal；
- PostgreSQL 与正式 RetrievalRepository。

不新增：

- 新 Memory Store；
- 新消息总线；
- 新 workflow engine；
- 同步大模型抽取；
- 自动 Canonical promotion。

### 4.2 读取路径

~~~text
query + subject/scope
→ Canonical exact probe
→ Raw FTS and Dense in parallel
→ per-channel small quotas
→ Evidence identity dedup
→ rank-based fusion
→ true-session local expansion
→ session-diverse whole-unit packing
→ existing governance validation
→ MemoryContext
→ Host / local Qwen Reader
~~~

第一版只使用一个固定配置，不做网格调参：

~~~text
FTS quota             8
Dense quota           8
fused candidate cap  16
hydrated unit cap     16
unique session cap     8
adjacency radius       1
evidence token cap  8192
answer reserve      capability-derived and frozen in run-lock
~~~

若 capability probe 证明某个硬上限不可执行，只能在打开 case label 前修改一次并冻结；不得按 accuracy 结果调预算。

### 4.3 最小 grounding

普通 recall 不再经过完整 Event/State/COUNT 类型体系，也不声明 strict COMPLETE。Reader 输出只需要：

~~~yaml
answer:
disposition:
  ANSWER
  INSUFFICIENT
visible_evidence_ids: []
~~~

Runtime 只验证：

- 引用的 Evidence 确实在 Reader-visible Context；
- Evidence 当前可访问且未撤销；
- Evidence identity、source role 和 span/window 真实；
- INSUFFICIENT 与系统失败分开。

语义答案正确性由 targeted fixtures、产品场景和 Qwen Judge 评价；引用完整性不冒充 SemanticBindingPrecision。

已有且已验证的 deterministic operator 可以继续使用。尚未闭合的 verified COUNT、范围完备性、复杂比例和 temporal proof 返回普通检索证据或 INSUFFICIENT，不得伪造 COMPLETE；它们在 Post-MVP 单独处理。

### 4.4 权威边界

MVP 只保留五个硬边界：

1. 原始 subject/session/source/turn identity 必须真实；
2. scope、permission、revocation 和删除不得泄漏；
3. Reader-visible trace 必须等于真实序列化内容；
4. Reader 引用只能来自可见且仍合法的 Evidence；
5. read path、模型和 evaluation 不能修改 Canonical State。

其余排序、quota、packing 和提示词都是可替换策略，不在每层重复建立 digest、validator、receipt 或状态机。

## 5. 明确后置的复杂设计

以下内容全部退出 MVP 关键路径，并保持 default OFF：

~~~text
SemanticEpisode / Formation bundle product integration
entity / event / time / state-change extraction
Formation → Evolution automatic bridge
CognitiveWorkspace as a durable contract
N-best QueryTaskContract
full typed RequirementState for ordinary recall
state-aware reranker
model action ranking
ResidualCue
multi-round ReFind
AssociativeBranchLedger
Accessibility decay
AttentionThread
Focus / Explore / Resume modes
global cue graph
automatic profile or Canonical promotion
~~~

已有 Formation、Evolution 和 GDPM 制品继续保留为研究资产，不删除、不改写，但它们不阻塞 MVP 可用性 terminal。

## 6. 两个主张

### MVP-H1 — Operational Usability

在真实 OpenWorker → MCP → Runtime 路径中，简单 Memory profile 能稳定完成写入、检索、Context 和一次 Reader 消费，并满足第 2 节的可用性、安全和性能门。

最小证据：

- 一个从 clean local setup 开始的 golden flow；
- 100-request warm reliability soak；
- 24 个真实产品场景；
- model outage、revocation、cross-scope、deletion 与 worker restart 负控；
- request-level latency、token、queue lag 和 terminal 分类。

### MVP-H2 — Grounded Memory Utility

在相同 query、token、Reader 和调用预算下，产品同构的简单 Memory 必须优于 NoMemory，并且不劣于一次 Lexical RAG；Dense、Canonical exact 和 session diversity 只有在带来可观测收益时才保留。

候选选择采用最简单胜者规则：

1. 先淘汰未达到可用性与安全门的方案；
2. development slice 中，Memory 方案相对 NoMemory 的 QwenJudgeAccuracy 点增益至少 0.02；
3. 在合格 Memory 方案中，选择 QwenJudgeAccuracy 距最优不超过 0.01、visible recall 距最优不超过 0.05 的最简单方案；
4. 若 Lexical 合格，选择 Lexical；
5. 只有 MiLA-Simple 明确越过上述等价带时，才保留 Dense、Canonical exact 和 session-diverse packing；
6. 500-case 才要求 Memory 相对 NoMemory 的 paired 95% CI lower bound > 0。

这使“没有独立算法增益”成为简化信号，而不是项目失败。

## 7. 三个 baseline family

| Family | 定义 | 用途 |
| --- | --- | --- |
| NoMemory | 相同 OpenWorker / Reader 路径，memory call = 0 | 证明记忆本身有用 |
| Lexical | official Raw FTS / BM25 + whole-unit packing | 最小 Memory reference |
| MiLA-Simple | Canonical exact + FTS 8 + Dense 8 + dedup + RRF + true-session packing + 现有 governance | 产品候选 |

不得加入第四个 baseline family。Dense-off、Canonical-off 或 adjacency-off 只在 24-case 中做一次机制诊断，不进入 500-case 笛卡尔积。

## 8. 四个执行阶段

“阶段”表示一组有共同交付物和通过条件的任务，不是新增 Runtime 对象。

### U0 — 当前契约修复与最小容量

目标：先让一个小而真实的 Context 请求稳定通过。当前真实 next step 是 repair，不是继续扩大 benchmark。

必须完成：

- 封存当前 GDPM active cell，再由 Master 统一 Goal version、Goal digest 和 canary contract；
- 修复当前 24-case 中缺 ContextReceipt 的 14 个失败；
- 修复 MCP wire output limit 的 6 个失败，优先返回 compact MemoryContext reference 或有界内容，不盲目增大 wire limit；
- 复用 GDPM B0 已通过的真实 identity、whole-unit Context 和三层 trace；
- 修复 projection worker 的 lease renewal、terminal writeback 与意外退出；
- 每个 logical cell exactly once；基础设施中断可从 checkpoint 继续；
- system failure 不得记为 semantic abstention；
- 旧 R4 只保留为 diagnostic artifact。

执行顺序：

~~~text
one golden MemoryContext request
→ known failure fixtures
→ 24-case context-only canary
→ 100-request warm reliability soak
~~~

通过条件：

~~~text
Goal/Master/contract identity aligned = 1.0
SessionIdentityIntegrity = 1.0
CrossSourceSessionAdjacencyExpansion = 0
ReaderVisibleTraceExactness = 1.0
ContextSerializationReplayEquivalence = 1.0
SystemFailureAsSemanticAbstention = 0
24-case ContextTerminalRate = 1.0
100-request warm terminal rate = 1.0
MCP output-limit failure = 0
missing ContextReceipt = 0
worker unexpected exit = 0
expired lease after drain = 0
~~~

通过后自动进入 U1。未通过则留在 U0 修复，不运行 Answer/Judge，也不扩大到 128/500。

### U1 — 简单读取与最简单胜者

目标：实现并比较 NoMemory、Lexical 和 MiLA-Simple，不引入 Formation、planner 或复杂 Binding。

必须完成：

- official FTS 和 Dense 并行；
- Canonical exact 作为低成本优先 probe；
- identity dedup 与 RRF；
- 同一 session 最多先取两个窗口，随后优先未覆盖 session；
- adjacency 只能在真实 session 内半径 1 扩展；
- exact Qwen tokenizer/chat template accounting；
- 一个固定 Context 序列化格式；
- 一个 Answer 调用，零 retrieval-policy 模型调用。

执行顺序：

~~~text
targeted positive / negative fixtures
→ 24-case matched Context / Answer / Judge canary
→ select a provisional simplest family
~~~

24-case 交付门：

~~~text
ContextTerminalRate = 1.0
AnswerTerminalRate = 1.0
JudgeTerminalRate = 1.0
AcceptedReferenceIntegrity = 1.0
CrossScopeLeak = 0
RevokedEvidenceLeak = 0
CanonicalMutationFromReadPath = 0
planner/reranker model calls = 0
Answer calls <= 1 per case
P95 retrieval + Context <= 2 seconds
mean evidence tokens <= 4096
~~~

24-case 只用于确认 delivery、grounding、明显退化和初步选择，不要求显著性。若 MiLA-Simple 无明显独立增益，记录 RESOLVED_NO_GAIN，选择 Lexical 并自动进入 U2；不得为了保留 MiLA 名称增加更多组件。NoMemory 只作效用负控，不是 Memory 产品候选。

### U2 — 产品同构可用性

目标：证明所选最简单方案可由普通用户通过一个入口完成，不要求用户理解 Evidence、Proposal、Claim、UUID、token 或 trace。

MVP 只验收一个 connector：现有 OpenWorker/MCP。Web Console、LangGraph、AutoGen 和 Generic Client 可以保留，但不进入本 Goal 的产品完成门。

必须形成一个 golden flow：

~~~text
one local init/start/doctor command
→ user says “记住……”
→ Raw Evidence committed and projection becomes ready
→ restart Runtime/worker
→ user asks in a new turn/session
→ answer returns with one inspectable source
→ user explicitly corrects or updates the memory
→ current answer changes without erasing history
→ user asks to forget it
→ revoke/delete completes
→ later query no longer returns it
→ stop/start preserves the expected state
~~~

默认界面只显示简短状态和可操作错误。治理 JSON、内部 UUID、role token、Proposal payload 和 trace digest 只在 Advanced / diagnostic 输出出现。

必须通过同一 OpenWorker → MCP → Runtime 路径验证：

~~~text
capture and immediate recall
cross-session personal fact recall
assistant-answer recall
current Canonical state lookup
memory update without silent overwrite
insufficient-evidence abstention
revoked Evidence exclusion
cross-scope identity isolation
deletion propagation
model outage fallback
worker restart and queue drain
no-memory-needed request
~~~

产品场景固定为 24 个 outcome-blind cases，覆盖中文、英文、短对话、长对话、单 session、多 session、更新、撤销和无记忆需求。

另运行 100-request warm soak，覆盖 restart、DB/FTS/Runtime/vLLM unavailable、timeout、malformed response 和 projection lag。Memory control、vLLM queue/prefill/decode 与总 E2E latency 分开报告。

数据模式：

- SYNTHETIC_ONLY 是默认可用预览；
- DEIDENTIFIED_ALLOWED 必须显示明显 data-mode banner；
- LOCAL_PERSONAL_DATA 必须复用现有 AES-256-GCM、0700 Blob root、加密备份和 key recovery doctor gate；
- 未通过 LOCAL_PERSONAL_DATA gate 时，不得把本地预览描述成真实个人数据可用。

通过条件：

~~~text
task success >= 0.90
golden flow end-to-end = PASS
100-request warm terminal rate = 1.0
read-after-write searchable P95 <= 5 seconds
retrieval + Context P95 <= 2 seconds
warm memory-control P95 <= 500 milliseconds
local Qwen end-to-end P95 <= 30 seconds
model outage deterministic fallback = 1.0
all requests have typed terminal = 1.0
scope/revocation/deletion leak = 0
Canonical mutation from read path = 0
one feature flag restores baseline = 1.0
~~~

U2 通过即形成 PASS_MVP_LOCAL_USABLE，不等待 Formation、联想慢路径或 LongMemEval 128/500。若 LOCAL_PERSONAL_DATA gate 同时通过，可进一步形成 CANARY_PERSONAL_DATA_ELIGIBLE；否则只能声明 SYNTHETIC/DEIDENTIFIED local preview。

### U3 — LongMemEval 128/500 后续确认

目标：在本地 MVP 已可用后，确认 benchmark 质量和成本，不让研究确认阻塞 golden flow 或 local preview。

协议：

- LongMemEval-S cleaned 500 cases；
- 470 answerable 与 30 abstention 分开报告；
- NoMemory、Lexical、最终所选 MiLA-Simple 三臂；
- 同一 Context budget、Reader、Judge、tokenizer 和 chat template；
- Answer 全部封存后再运行 Judge；
- Reader/Judge 使用本地 vLLM Qwen，不使用 OpenAI；
- QwenJudgeAccuracy 不声称 GPT-4o leaderboard 等价；
- labels 在 Answer seal 前不可见；
- formal holdout 继续未使用。

执行楼梯：

~~~text
128-case development characterization
→ freeze final simplest family and budgets
→ 500-case confirmation
~~~

128-case 必须先达到：

~~~text
all terminal rates >= 0.99
selected memory QwenJudgeAccuracy >= 0.20
selected memory minus NoMemory point delta >= 0.02
selected memory not worse than Lexical by more than 0.01
ReaderVisibleGoldSessionRecall >= 0.50
~~~

若未达到，只在独立 repair-dev 定位 first loss；不得在 128 sealed results 上按 case 调 Prompt、K、token 或 synonym。

主要报告：

~~~text
Context / Answer / Judge terminal rates
QwenJudgeAccuracy
Exact Match and normalized F1
GoldSessionRecall@k
ReaderVisibleGoldSessionRecall
multi-session all-required coverage
abstention accuracy
P50 / P95 latency
tokens and calls per case
CostPerCorrectAnswer
~~~

确认门：

~~~text
all three terminal rates >= 0.99
selected family QwenJudgeAccuracy >= 0.20
selected memory family minus NoMemory >= 0.02
paired bootstrap lower 95% bound for memory minus NoMemory > 0
selected family not worse than Lexical by more than 0.01
all MVP safety gates remain zero
~~~

500-case paired bootstrap 置信区间必须报告，但只用于研究解释。若额外 MiLA-Simple 策略没有增益，最终产品继续采用 Lexical；不把可用系统判为失败。

## 9. 自动执行、失败反思与简化

本 Goal 激活后采用连续执行：

| 结果 | 动作 |
| --- | --- |
| PASS | 封存当前阶段，刷新 exact next scope 和 run-lock，自动执行下一阶段 |
| RESOLVED_NO_GAIN | 保留负结果，删除或关闭无增益增量，采用更简单胜者并继续 |
| REPAIR_REQUIRED | 留在当前阶段，定位一个 owner，完成最小通用修复和 fresh attempt 后继续 |
| INFRA_FAILURE | 修服务、lease、timeout 或资源；配置未变化时只恢复失败 cells |
| HARD_SAFETY_BREACH | 当前 run 失效并隔离；修复后重放安全负控，以 fresh run 继续 |

修复规则：

1. 每次只处理一个可解释根因；
2. 修复必须通过至少两个结构不同正例和一个反例；
3. 不使用 case ID、gold answer、gold span 或专用 synonym；
4. 不靠扩大 token、Top-k、retry 或模型调用掩盖失败；
5. 同一根因两次实质修复仍失败时，优先删除该增量或退回更简单实现；
6. mandatory U0 可靠性不能跳过，必须替换为更简单可行实现后继续；
7. valid sealed effect 无增益不在原数据调参，直接选择更简单方案；
8. 只有数据损坏、跨 scope/撤销泄漏、未授权 Canonical 写入或需要破坏性恢复时才暂停请求新授权。

## 10. 高效开发与测试

### 10.1 只改最短纵向路径

优先修改：

~~~text
LongMemEval identity adapter
projection worker lease lifecycle
official RetrievalService fusion
MemoryContext whole-unit packing
OpenWorker/MCP product route
Qwen Answer/Judge harness
~~~

不为 MVP 新建通用 orchestrator、plugin system、第二套 QueryIR、第二套 Binding、第二套 Context compiler 或第二套 audit framework。

### 10.2 分层测试

| 时点 | 必跑 |
| --- | --- |
| 每次编辑 | touched unit/contract、edited-file Ruff/mypy |
| repair 完成 | 对应 positive/negative fixtures |
| U0 terminal | identity/context/worker targeted + 24 context-only + 100 warm |
| U1 terminal | 24-case matched Context/Answer/Judge |
| U2 terminal | golden flow、100 warm、Runtime full unit、相关 PostgreSQL/security、OpenWorker/MCP E2E |
| U3 terminal | 128 development + 500 confirmation scorer consistency 与结果复算 |

无关历史 DG suite、独立 reviewer、全仓库 source manifest 和重复 witness 不在每次 repair 运行。

### 10.3 计算资源

运行前只做一次 capability probe，然后冻结：

~~~text
stateless context/retrieval: up to 16-way
stateful PostgreSQL lanes: 4 isolated processes, one worker each
Answer: start at 8 in-flight
Judge: start at 8 in-flight, after Answer window closes
transport retry: at most one identical retry
semantic retry: zero
~~~

429、OOM 或持续 timeout 只允许按 8→4→2 下调并发，不根据 accuracy 修改并发或方法。

### 10.4 最小制品

每个阶段只保存：

~~~text
run-lock.json
results.json
terminal.json
repair-log.jsonl  only when a material repair occurred
checkpoint/       only for resumable case cells
~~~

不默认生成：

~~~text
per-stage receipts
transitive source manifests
deliverable indexes
duplicate runbooks
one failure file per cell
repeated reviewer/witness reports
~~~

## 11. Post-MVP 复杂能力进入条件

MVP terminal 后，复杂能力必须另立 Goal，且由真实 first-loss 或产品遥测触发：

| 后续能力 | 进入条件 |
| --- | --- |
| Formation | Lexical/MiLA-Simple 的主要首损明确来自记忆碎片化，且 query-independent oracle 有可观测增益 |
| typed temporal proof | COUNT/range/ORDER 是重要失败 slice，普通 Reader 无法安全解决 |
| bounded associative retrieval | 一轮 MiLA-Simple 后仍有稳定 residual，且 official oracle 能由一个额外动作恢复 |
| state-aware reranker | 固定候选池存在真实 cutoff loss，query-only reranker 明显不足 |
| Accessibility / Thread | 产品遥测证明恢复中断任务或访问衰减是实际用户问题 |
| durable Formation objects | sidecar 已有下游增益并通过 freshness/revocation，再走 architecture-vNext ADR |

不得因为“架构图完整”或“模型可以做到”而进入这些能力。

## 12. 权威、激活与历史关系

本文件是新 Goal 设计，不自行取得执行权。激活时 MILA-ML-MASTER 必须：

1. 将 active_goal 指向 MILA-MVP-01；
2. 封存当前 GDPM B0 active attempt，记录最新 4/24 通过、20/24 repair-required 事实和未执行复杂分支的处置；
3. 写入 exact active stage、case scope 和 run scope；
4. 如授予连续执行权，则每个阶段解除后自动刷新 Reader/Judge、128/500 和产品 canary 的 exact scope，不再逐次请示；
5. 保持 formal holdout、default-on、Schema 和公开 MCP 变化未授权。

可复用：

- 已通过且实现身份兼容的 GDPM B0 fixtures；
- 已封存的 DG-24 first-loss；
- official DG-28 union；
- 现有 worker lease renewal；
- 现有 OpenWorker/MCP/Runtime、FTS、Dense、Canonical 和 Context 代码。

不得复用：

- 语义 identity 无效的旧 R4 Context/Answer/Judge；
- 被修复代码影响的旧 candidate/Context cells；
- ML-CLOSURE 的 7% 作为正常语义 baseline；
- sealed effect 后按结果调整的配置。

## 13. Terminal 与产品决策

| 条件 | Terminal |
| --- | --- |
| U0、U1、U2 通过，选择 Lexical | PASS_MVP_LOCAL_USABLE_LEXICAL |
| U0、U1、U2 通过，MiLA-Simple 有必要增益 | PASS_MVP_LOCAL_USABLE_MILA_SIMPLE |
| U2 且 LOCAL_PERSONAL_DATA gate 通过 | PASS_MVP_PERSONAL_DATA_CANARY_ELIGIBLE |
| U0～U3 通过 | PASS_MVP_USABLE_LONGMEMEVAL_CONFIRMED |
| U2 通过但 U3 尚未授权或未完成 | PASS_MVP_LOCAL_USABLE_BENCHMARK_PENDING |
| 所有简单 family 均低于绝对质量门 | ACTIVE_REPAIR_QUALITY_BELOW_FLOOR |
| 外部模型/硬件不可用但 deterministic path 可用 | PARTIAL_MVP_DETERMINISTIC_ONLY |
| 数据损坏、权限/撤销泄漏或未授权 Canonical 写入未能恢复 | FAIL_MVP_DATA_OR_AUTHORITY_SAFETY |

产品决策与 Goal terminal 分离：

~~~text
KEEP_CURRENT_BASELINE
LOCAL_PREVIEW_ELIGIBLE
PERSONAL_DATA_CANARY_ELIGIBLE
CANARY_ELIGIBLE
KEEP_FLAGS_OFF
REJECT_CANDIDATE
~~~

CANARY_ELIGIBLE 不等于 default-on、Production-ready、Schema freeze 或 formal holdout PASS。

## 14. 完成清单

- [ ] U0 修复 authority/ContextReceipt/MCP output limit，并通过 24 context-only 与 100 warm；
- [ ] U1 完成三 family 24-case comparison，并选择 provisional 最简单方案；
- [ ] U2 完成一键启动 golden flow、24 个产品场景、100 warm、故障降级、安全和性能门；
- [ ] 单一 feature flag 可以立即回到 baseline；
- [ ] Formation、planner、多轮搜索、Accessibility 和 Thread 不阻塞 MVP；
- [ ] U2 通过后先形成 local usability 结论，个人数据资格单独受 encryption/recovery gate 控制；
- [ ] U3 在独立 exact scope 下完成 LongMemEval 128/500 Qwen/vLLM 确认；
- [ ] formal holdout 未消费；
- [ ] 公共 MCP、Canonical schema 和冻结架构未改变；
- [ ] 失败均经过反思、通用修复或简化选择，而不是第一次失败就终止。

---

最终原则：

> 可用优先于完整，稳定优先于聪明，简单胜者优先于 MiLA 专属复杂度。先让记忆能够可靠写入、快速找回、正确进入 Context、由一次 Reader 消费并安全撤销；只有真实数据证明简单路径不足时，再增加 Formation、严格 operator 或受控联想。
