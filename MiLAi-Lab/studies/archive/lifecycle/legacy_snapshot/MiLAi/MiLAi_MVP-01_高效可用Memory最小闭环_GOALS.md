---
document_id: MILA-MVP-01
version: "0.1"
status: ACTIVE_U0_WARM_002_FAILURE_REPAIR
document_type: PRODUCT_USABILITY_GOAL
created_at: "2026-09-01T10:57:22+08:00"
architecture_baseline: MILA-ML-ARCH@1.0
execution_order_authority: MILA-ML-MASTER
execution_authorized: true
authority_snapshot: MILA-ML-MASTER@2.1
activated_at: "2026-09-01T11:11:55+08:00"
activation_authority: USER_EXPLICIT_20260901_EXECUTE_MILA_MVP01
active_stage: U0
execution_scope: U0_WARM_002_FAILURE_REPAIR_PROBE
active_case_scope: MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
active_run_scope: MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE
active_run_lock: var/mvp01/mvp01-u0-warm-repair-probe-20260901-002/run-lock.json
authorized_synthetic_query_class_count: 10
formal_warm_successor_authorized: false
authorized_benchmark_case_count: 0
selection_metadata_access_authorized: false
reader_answer_judge_calls_authorized: false
benchmark_case_execution_authorized: false
latest_u0_repair_terminal: var/mvp01/mvp01-u0-20260901-016/terminal.json
latest_u0_repair_terminal_sha256: b55a5b7c5f7117245a376639b565407c117270311c57b14c6f2f23250a628c48
latest_u0_repair_status: PASS_U0_RAW_ITEM_WIRE_CONSUMER_VIEW_FIXTURES
latest_u0_canary_terminal: var/mvp01/mvp01-u0-20260901-017/terminal.json
latest_u0_canary_terminal_sha256: ba9fedb8ce69c82a927bc57620302391d52dfaaa1f4dd8c54383f610cf79f38a
latest_u0_canary_status: PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY
latest_u0_warm_terminal: var/mvp01/mvp01-u0-warm-20260901-002/terminal.json
latest_u0_warm_terminal_sha256: 51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0
latest_u0_warm_status: FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED
latest_u0_warm_results_sha256: fb8958447c681d1cd80cd8f35085a831d4488804cca99e6b7b47196b077afc1d
latest_u0_warm_checkpoint_sha256: 31b37c8980932f822673c1b4672efccbc01bffe137a93b89b42cba23f0e38c18
latest_u0_warm_run_lock_sha256: de720a2f713e944fdb64a5c73a155ff63bd1353ad7d53fa3369415fdb75cd301
latest_u0_warm_audit_status: NO_GO_SUCCESSOR_REPAIR_REQUIRED
latest_u0_warm_repair_probe_terminal: var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/terminal.json
latest_u0_warm_repair_probe_terminal_sha256: a4b8331d0666824407693a44de9349e69750c5628691169e6e0022505266f775
latest_u0_warm_repair_probe_status: PASS_MVP01_U0_WARM_REPAIR_PRODUCTION_PATH_PROBE
activation_requirement: MILA-ML-MASTER_EXPLICITLY_ACTIVATES_MILA-MVP-01_WITH_EXACT_STAGE_AND_RUN_SCOPE
continuous_execution_after_activation: true
continuous_execution_policy: PASS_OR_SIMPLIFIED_WINNER_AUTO_ADVANCE
continuous_execution_scope: U0_THROUGH_U3_SEQUENTIAL_WITH_EXACT_SCOPE_REFRESH
current_active_goal_at_creation: MILA-GDPM-01@0.3
current_active_attempt_at_creation: var/gdpm/gdpm-b0-20260901-003/terminal.json
current_active_attempt_status: FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED
handoff_required_before_activation: true
handoff_completed_at: "2026-09-01T11:11:55+08:00"
predecessor_terminal_artifact: var/gdpm/gdpm-b0-20260901-003/terminal.json
predecessor_terminal_sha256: bcb6382d3a2b29e6b5712a2a2bbaa4d631a764d5d442e67f70a2e29449b41d78
predecessor_terminal_status: FAIL_B0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED
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

### 12.1 当前激活记录

`MILA-ML-MASTER@2.1` 已于 `2026-09-01T11:11:55+08:00` 完成接管并只打开
`U0_GOLDEN_AND_KNOWN_FAILURE_FIXTURES`：先执行一个 golden MemoryContext 请求，随后针对
`ContextReceipt` 缺失与 MCP wire output-limit 两个已知根因运行结构化正负 fixtures。此 scope
不执行 benchmark case、Reader、Answer 或 Judge。

前驱 `gdpm-b0-20260901-003` 保持不可改写：4/24 PASS、20/24
`PROTOCOL_IMPLEMENTATION`，其中 14 个缺 `ContextReceipt`、6 个超过 MCP wire output limit；
Reader/Answer/Judge 调用均为 0，formal holdout 未消费。GDPM 未执行的 Formation、联想、
Accessibility、Thread 与多轮 refinding 分支不迁移到 MVP 关键路径，继续 default OFF。

one-golden 已于 `2026-09-01` 通过真实临时 PostgreSQL → Runtime → persistent
projection worker → stdio MCP 路径：520 条合成 Evidence 全部达到 projection terminal，
96,822-byte resolve 在不裁剪 Reader Context 和严格状态的前提下压缩为 57,985 bytes，
Context truth 九项指标全部达标；worker 运行中无意外退出且清理返回码为 0。封存制品为
`var/mvp01/mvp01-u0-golden-20260901-002/environment-witness.json`（SHA-256
`59a1b7013d492fff90a26606b8eb5e3465dcf004a8b52b45214e8c02f79df2d6`）；benchmark case 与
Reader/Answer/Judge 调用仍为 0。

两类已知根因 fixtures 已于 `2026-09-01T11:37:30+08:00` 全部通过：
ContextReceipt 5/5（含 3 个结构差异的 positive 与 2 个 negative），MCP wire
compaction 6/6（含 5 个 positive 与 1 个 Reader Context 本身超限的 typed negative）。
封存 terminal 为 `var/mvp01/mvp01-u0-20260901-002/terminal.json`（SHA-256
`43835b3bc157922383821ca187c48da8f9122349b529854ef682bfe144bdbd9e`），状态
`PASS_U0_GOLDEN_AND_KNOWN_FAILURE_FIXTURES`。根据连续执行授权，当前唯一 scope 已刷新为
`MVP01_U0_24_CASE_CONTEXT_ONLY_CANARY`，evidence hard cap 固定为 8192 tokens；本 scope
只允许 outcome-blind development metadata 选择与 24 个 Context cell，Reader/Answer/Judge、128/500、
formal holdout、default-on、Schema 和公开 MCP 变更仍未授权。

首个 MVP 24-case attempt `mvp01-u0-20260901-003` 已完整终结并封存为
`FAIL_MVP01_U0_24_CONTEXT_ONLY_CANARY_REPAIR_REQUIRED`（terminal SHA-256
`584c493f23a823976d38baf6aa0040f1e60d775a670ec6b5a64d7bc7ba208aa6`）。24/24 均在
Runtime HTTP request validation 边界拒绝：MVP 锁定的 8192 token hard cap 超过了旧
`MemoryResolveBudget`/`MemoryContext`/`ContextBudgetEnvelope` 上限 8000。这是通用预算契约不一致，
不是 case-specific 逻辑；4/4 shard 的 worker 在清理前均为 RUNNING，清理返回码均为 0，
projection 全部 terminal，Reader/Answer/Judge 为 0。当前权限因此收窄为
`MVP01_U0_8192_RUNTIME_BUDGET_CONTRACT_REPAIR`；benchmark metadata/case 访问已关闭，只允许修复
三处通用上限并运行 8192/8193 边界 fixtures。

`mvp01-u0-20260901-004` 已将三处上限统一为 8192，并以 63 项 Context/resolve/compiler
回归、Ruff 与 strict mypy 封存为 `PASS_U0_8192_RUNTIME_BUDGET_CONTRACT_FIXTURES`；8193
仍 fail closed。terminal 为 `var/mvp01/mvp01-u0-20260901-004/terminal.json`（SHA-256
`b569aaa855864bc95fc265d21daaee6c5f5571d16402dcc2b0e2b2e9abc07e29`）。当前唯一授权已刷新为
fresh attempt `mvp01-u0-20260901-005` 的 24-case context-only canary；其他禁止项不变。

`mvp01-u0-20260901-005` 已越过 8192 request boundary 并完整终结，结果为 9/24 PASS、
12 个 MCP wire output-limit 与 3 个缺 ContextReceipt；terminal 为
`var/mvp01/mvp01-u0-20260901-005/terminal.json`（SHA-256
`f5e0ee90498330c87c2557090280da3d2042e446cbeb6bd8115e589c1d219857`）。4/4 shard 的
projection、worker-running-before-close 与 cleanup 仍全部 PASS，Reader/Answer/Judge 为 0。当前权限
已收窄为 `MVP01_U0_ACTUAL_RECEIPT_AND_WIRE_COMPACTION_REPAIR`；不得读取或执行新 case，
只允许从封存 trace 提取通用失败形态并补结构 fixtures。

`mvp01-u0-20260901-006` 已通过 124 项相关回归并封存为
`PASS_U0_ACTUAL_RECEIPT_AND_WIRE_COMPACTION_FIXTURES`：Reader text 与 strict proof 保持不变，
只将重复 window presentation 降为 identity/session/adjacency/digest wire view；Reader text 本身
超限时仍 typed `TRUNCATED`。whole-unit 不可行且零 Evidence 入选时显式终结为
`ABSTAINED/CONTEXT_BUDGET_INFEASIBLE`，不伪造 receipt。terminal 为
`var/mvp01/mvp01-u0-20260901-006/terminal.json`（SHA-256
`292cc725e57d57875fc26b89da2397d823f5b64f303f1355b9d09d7d57e39268`）。当前唯一授权
已刷新为 fresh `mvp01-u0-20260901-007` 24-case context-only canary。

`mvp01-u0-20260901-007` 已完整终结为 15/24 PASS；3 个 missing ContextReceipt 全部解除，
12 个 wire-limit 中 3 个解除，剩余 9 个 wire-limit。terminal 为
`var/mvp01/mvp01-u0-20260901-007/terminal.json`（SHA-256
`a6cce3d97a1081da5d4351dae5f09ac1d71468c6524b2543d2b9d27cfae1c506`）；4/4 shard lifecycle
仍 PASS，Reader/Answer/Judge 为 0。当前权限收窄为 `MVP01_U0_TOP_LEVEL_WIRE_DEDUP_REPAIR`：
只允许将已在上下文/严格决策中重复的顶层 diagnostics 改为保留决策字段的 SHA 指针，
不得删除 Reader text、strict completeness、operator result、ContextReceipt 或 session/adjacency proof。

`mvp01-u0-20260901-008` 已以 MCP profile 46/46、Ruff 和 strict mypy 封存为
`PASS_U0_TOP_LEVEL_WIRE_DEDUP_FIXTURES`。Reader text、strict terminal facts、operator completeness、
ContextReceipt 与 session/adjacency proof 未改变；完整 replayable material 以 SHA-256 指针保留，
wire limit 未增大。terminal 为 `var/mvp01/mvp01-u0-20260901-008/terminal.json`（SHA-256
`7e4ed590da4b225d6870301699c2520e36e03d19f8311359a9e87266f538f22a`）。当前唯一授权
已刷新为 fresh `mvp01-u0-20260901-009` 24-case context-only canary。

`mvp01-u0-20260901-009` 已完整终结为 15/24 PASS；缺 ContextReceipt 保持为 0，
剩余 9 个 case 均为 MCP wire output-limit。terminal 为
`var/mvp01/mvp01-u0-20260901-009/terminal.json`（SHA-256
`8c7d6ff1118652a0c54de33c89ef71eeaaa71f031bf4dfd4acb732ce94e56148`）；4/4 shard lifecycle
继续 PASS，Reader/Answer/Judge 为 0。当前权限收窄为
`MVP01_U0_DERIVED_TRACE_WIRE_COMPACTION_REPAIR`：不得读取或执行新 case，只允许对通用
`derived_result.trace` 冗余证明分支做可回放 SHA 指针化，并在 typed output-limit 中增加
仅含字节数的结构诊断；Reader text、operator result/completeness、ContextReceipt、
session/adjacency proof 均不得删除。

`mvp01-u0-20260901-010` 已以 MCP profile 47/47、DG15 adapter 17/17、DG14 adapter 5/5、
canary contracts 15/15、Ruff 和 strict mypy 封存为
`PASS_U0_DERIVED_TRACE_WIRE_COMPACTION_FIXTURES`。顶层 operator result/completeness、Reader text、
ContextReceipt 与 session/adjacency proof 保持；重复 slots/applicability 以 terminal summary、count
和 SHA-256 receipt 表达。如仍超限，typed failure 仅携带结构字节数，不携带 payload
内容。terminal 为 `var/mvp01/mvp01-u0-20260901-010/terminal.json`（SHA-256
`ee2b97a7c1f7147b6a832035ce84f4a908b0bce665215635a42f25be542771ec`）。当前唯一授权已刷新为
fresh `mvp01-u0-20260901-011` 24-case context-only canary；其他禁止项不变。

`mvp01-u0-20260901-011` 已完整终结为 15/24 PASS，剩余 9 个仍为 MCP wire
output-limit；terminal 为 `var/mvp01/mvp01-u0-20260901-011/terminal.json`（SHA-256
`f7028ca34bd8016d7a0b7213145dbdda05c6b977d89eb166ab22b9373b6897b4`）。typed 字节诊断
证明 `derived_result` 仅约 0.5–2 KB，不是主载荷；大载荷是保留的约 23–24 KB Reader text
与 MemoryContext/items/receipt 中重复的 source/session/turn lineage。4/4 shard lifecycle PASS，
Reader/Answer/Judge 为 0。当前权限收窄为 `MVP01_U0_WIRE_LINEAGE_DEDUP_REPAIR`：不得读取
或执行新 case；仅允许在 ContextReceipt 与 selected refs 完整保留的前提下，将 window 的
第三份 source-ref 副本与 raw-item adjacency diagnostics 换为 session/turn identity + SHA，并将
typed 诊断排序为最大字段优先。

`mvp01-u0-20260901-012` 已以 MCP profile 47/47、DG14/DG15 adapters 22/22、Ruff 和
strict mypy 封存为 `PASS_U0_WIRE_LINEAGE_DEDUP_FIXTURES`。Reader text、ContextReceipt、
selected refs、raw exact source_ref、session/turn identity 与 window expansion adjacency proof 全部保留；只将
previous/next adjacency diagnostics 与 window 内第三份 source-ref 副本改为 count + SHA-256。
terminal 为 `var/mvp01/mvp01-u0-20260901-012/terminal.json`（SHA-256
`3c29a23fc3710a78c235dcad5ed4ad54533d8fead81806b7b02669f6c74fd387`）。当前唯一授权已刷新为
fresh `mvp01-u0-20260901-013` 24-case context-only canary；其他禁止项不变。

`mvp01-u0-20260901-013` 已完整终结为 16/24 PASS，剩余 8 个 wire-limit；terminal 为
`var/mvp01/mvp01-u0-20260901-013/terminal.json`（SHA-256
`1608770a80afbb0205fd066f54586aa84e33cd3109c668909178022fecd02cc1`）。失败的 compacted
payload 为 66,322–76,734 bytes，每个 `items` 约 15.1 KB，window 约 5.7–11.1 KB；
4/4 shard lifecycle PASS，Reader/Answer/Judge 为 0。当前权限收窄为
`MVP01_U0_MINIMAL_WIRE_IDENTITY_VIEW_REPAIR`：不得读取或执行新 case；仅允许将 raw
item pointer 收窄为 exact source_ref、Evidence ID、score、subject/session/turn/speaker/time/retention
身份与 full-item SHA，并将 window 逐项 digest 合并到已有的聚合 windows receipt。Reader text、
ContextReceipt、selected refs、window Evidence/session/expansion adjacency 不得改变。

`mvp01-u0-20260901-014` 已以 MCP profile 47/47、DG14/DG15 adapters 22/22、Ruff 和
strict mypy 封存为 `PASS_U0_MINIMAL_WIRE_IDENTITY_VIEW_FIXTURES`。raw exact source_ref、
Evidence ID、score/channel、subject/session/turn/speaker/time/retention 与 full-item SHA 保留；window
session/Evidence/expansion adjacency 保留，逐项 digest 合并为 aggregate windows receipt。terminal 为
`var/mvp01/mvp01-u0-20260901-014/terminal.json`（SHA-256
`fd9ea4531261e39d57ccd704b71caf2544ff1af43455b95e74a368936b1c2a83`）。当前唯一授权已刷新为
fresh `mvp01-u0-20260901-015` 24-case context-only canary；其他禁止项不变。

`mvp01-u0-20260901-015` 已完整终结为 22/24 PASS，仅剩 2 个 wire-limit，compacted
payload 分别为 66,192 与 70,229 bytes；terminal 为
`var/mvp01/mvp01-u0-20260901-015/terminal.json`（SHA-256
`e2654d13eacd3db497d023715ac754a291fe28bbe8ba2611e555a6307c5b8053`）。4/4 shard lifecycle
PASS，Reader/Answer/Judge 为 0。当前权限收窄为
`MVP01_U0_RAW_ITEM_WIRE_CONSUMER_VIEW_REPAIR`：不得读取或执行新 case；raw item
逐项只保留 adapter 实际消费的 kind/canonical/Evidence ID/exact source_ref/relevance score
与 full-item SHA，被移除的 identity diagnostics 必须以 aggregate raw-items SHA/count 保留；
Reader text、ContextReceipt、selected refs 和 window session/adjacency proof 不得改变。

`mvp01-u0-20260901-016` 已以 MCP profile 47/47、DG14/DG15 adapters 22/22、Ruff 和
strict mypy 封存为 `PASS_U0_RAW_ITEM_WIRE_CONSUMER_VIEW_FIXTURES`。逐项 consumer fields 与
source identity 交叉验证所需值完整；每项与整体均有 SHA-256，不删除 Context/window/receipt 材料。
terminal 为 `var/mvp01/mvp01-u0-20260901-016/terminal.json`（SHA-256
`b55a5b7c5f7117245a376639b565407c117270311c57b14c6f2f23250a628c48`）。当前唯一授权已刷新为
fresh `mvp01-u0-20260901-017` 24-case context-only canary；其他禁止项不变。

`mvp01-u0-20260901-017` 已以 24/24 一次 Context cell 完整终结并封存为
`PASS_MVP01_U0_24_CONTEXT_ONLY_CANARY`；terminal 为
`var/mvp01/mvp01-u0-20260901-017/terminal.json`（SHA-256
`ba9fedb8ce69c82a927bc57620302391d52dfaaa1f4dd8c54383f610cf79f38a`）。Context truth 九项
均达标，missing ContextReceipt 与 MCP output-limit 均为 0；4/4 shard 在关闭前 worker
均为 RUNNING，projection 全部 terminal，清理返回码均为 0，Reader/Answer/Judge 为 0。
21/24 请求以明确的 `CONTEXT_BUDGET_INFEASIBLE` 语义弃答终结；这些只计入 U0
Context 交付门，不作答案质量 PASS 声明，且 `SystemFailureAsSemanticAbstention=0`。

首个 100-request warm attempt `mvp01-u0-warm-20260901-001` 已不可变封存为
`FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED`。terminal 为
`var/mvp01/mvp01-u0-warm-20260901-001/terminal.json`（SHA-256
`babf44c832e77c36940293dc4e80f8360adf862db331eb531c36925952893fef`）；results、checkpoint、run-lock
SHA-256 依次为 `90f8bbb4091af371a9940fd4fbb5bd814ffff44a7e8b092259e7293b9820740e`、
`b4dcb90829c83a25fd26fcdae301ef2571ddc1908e9bd761dada2b71173bf089`、
`5a60715910008bd7445d3f7d43c61c61c92fffde0aefb074627f3d584819cc72`。该 attempt 封存 100 个 typed
failure terminal、0 个 logical Context attempt、1 个 Runtime attempt、0 个 Context terminal、
0 个 Evidence archive，Reader/Answer/Judge 为 0，formal holdout 未消费；不得 resume、重放或覆盖。

根因是 adapter 把 immutable evaluation Event 的 `session_ordinal` 混入 strict Runtime
`EvidenceSourceContext`；该模型使用 `extra="forbid"`，所以首个并发波 4/4 capture 均以 HTTP 400
失败。旧 cleanup helper 还错误要求 0-ingest failure 必须出现 20 个 cleanup item，形成次生诊断噪声。
修复坚持不改公开 MCP/Runtime schema：wire `source_context` 仅保留 Runtime 合法字段，ordinal 移入独立
eval-only `source_event_identity`；同时补上 20-payload Runtime model preflight、mixed-wave 完整 outcome
drain/unknown sealing、0-denominator cleanup、projection 原始零值保留、diagnostic exception 仍必须产出
FAIL terminal、固定 Runtime artifact 重读以及 Runtime/ownership/drop database identity 交叉门禁。
独立审计随后发现 ownership 文件虽已有哈希，但正式门禁尚未将 Runtime 返回的
API/worker PID、冻结 launcher/interpreter/cwd 身份与关闭后 exact process 缺席逐字段交叉绑定。
已补上两份 process mapping 封存、PID/runtime cross-link 和 seal-time `/proc` 复验；只有
`FileNotFoundError` 或同 PID 的 start ticks 已变更才证明原进程缺席，权限/读取/解析异常均
fail closed。

真实 production-path 修复探针已封存为
`PASS_MVP01_U0_WARM_REPAIR_PRODUCTION_PATH_PROBE`：terminal
`var/mvp01/mvp01-u0-warm-repair-probe-20260901-001/terminal.json`（SHA-256
`a4b8331d0666824407693a44de9349e69750c5628691169e6e0022505266f775`），results SHA-256
`c52bf2496e5492132a49d128f4a3597f83bbff87bae67fb9db7f0fccc3f02c0c`。它使用一个 fresh isolated
PostgreSQL、一个 Runtime API、一个 persistent worker 和真实 stdio MCP，完成跨 session ordinals 0/1 的
2/2 synthetic captures、一次 Context resolve、raw trace → eval-only identity → provenance/window/receipt/archive
闭环验证、actual=2 cleanup 与独立 actual=0 cleanup；API/worker、port、ownership 与 DB drop 均清洁终结，
Reader/Answer/Judge、benchmark、formal holdout 均为 0。该 probe 只证明根因关闭，不替代 100-request gate。

fresh warm `mvp01-u0-warm-20260901-002` 已自然终结并不可变封存为
`FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED`。terminal SHA-256 为
`51e4961de03514d9fe3d79c9c653f6ef49d93849c6bce30a0f1ae63ab4741db0`；results、checkpoint、run-lock
SHA-256 依次为 `fb8958447c681d1cd80cd8f35085a831d4488804cca99e6b7b47196b077afc1d`、
`31b37c8980932f822673c1b4672efccbc01bffe137a93b89b42cba23f0e38c18`、
`de720a2f713e944fdb64a5c73a155ff63bd1353ad7d53fa3369415fdb75cd301`。它封存 100 requests、100 logical
attempts、1 Runtime attempt、90 archives，Reader/Answer/Judge、benchmark、holdout 均为 0；API/worker、
port、ownership、DB、namespace 与 projection lease 清理均通过。

Franklin 独立审计判定 successor `NO-GO`：50 个 `HIT` 是 provenance tuple/list 的 evaluator 假 FAIL；
90 个 archive 的 B0 SessionIdentityIntegrity 使用漏掉 `source_event_identity` 的陈旧 digest；TX-05 后
真实 projection 为 exact 12 deliveries / watermark 60，而 gate 仍冻结为 8 / 40；通用 failure wrapper
还抹掉已有 status、receipt、retry、span 和 context evidence。因此 `0/100 Context terminal` 不得解释为
产品成功率，也不得回填或重封 002。30 个 context-bearing `ABSTAINED` 是真实 typed
semantic-abstention outcome，在 expectation 与 evidence/receipt 完整性成立时不是 U0 delivery failure；
其中 Bicycle 仍有重复 Evidence alias 的 receipt losslessness defect。10 个中文 allergy `ABSENT` 是合法
typed safe-empty terminal，但不满足本 run-lock 的正向 evidence-anchor fixture expectation，receipt 为 N/A；
另有 10 个 Atlas window-count invariant failure。

根据连续执行授权，当前唯一 scope 收缩为
`MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE / mvp01-u0-warm-repair-probe-20260901-002`。只允许在一个 fresh
isolated PostgreSQL、一个 Runtime API、一个 persistent worker 与真实 stdio MCP 上，使用相同固定
SYNTHETIC_ONLY fixture 对 10 个不同 query class 各执行一次 Context。每个请求 exactly once、retry 0，
必须证明 10/10 context、live/JSON archive validation 等价、九项 context metrics exact、projection exact
12/60、Bicycle receipt lossless、Atlas bounded raw response 可审计以及所有资源释放。benchmark、
Reader/Answer/Judge、formal holdout、default-on、Schema 与公开 MCP 变更仍禁止；该 probe PASS 且 Franklin
复审 GO 前，不得授权新的 100-request formal successor。

禁止 resume、重放、覆盖或重新封存 002；禁止把 50 个 replay-valid archive回填成 002 PASS；禁止仅放宽
window/receipt/status 校验；禁止增加 retry、模型调用、benchmark、Reader/Answer/Judge 或 holdout 消耗。

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
