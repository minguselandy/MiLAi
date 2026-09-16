# MiLAi DG-17：语义记忆读取与证据集执行 Goal

> Goal ID：`DG-17`  
> 文档版本：`0.3.1 GENERALIZABLE ACQUISITION REBASE`  
> 生效日期：`2026-08-27`（Asia/Shanghai）  
> 当前状态：`Q6 PARTIAL / Q8 CHARACTERIZED / A1–A2 PROTOTYPE UNVERIFIED / A3 REBASE REQUIRED / RELEASE BLOCKED`  
> 产品前置：`DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE`  
> 直接前置：`DG16 terminal architecture finding`  
> 并行但独立 successor：`DG-18 Lifecycle Efficiency`（未由本文授权）  
> Provider：operator-owned vLLM `http://127.0.0.1:7860` / `Qwen3.6-35B-A3B-FP8`  
> Runtime / Schema：`CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`

---

# 0. Goal 决定

DG-17 正式接收并冻结 DG-16 的 terminal architecture finding：

> **MiLA 的 Memory Governance Plane 基本成立，但 Semantic Read Plane 尚未完成。**

当前系统不得再被描述为已经完成通用语义记忆读取。更准确的当前状态是：

```text
Governed flat Raw-Evidence retrieval
+
two focal evidence-composition operators
```

DG-17 的目标是将其推进为：

```text
MCP-native governed semantic memory read
→ typed query planning
→ query-specific Evidence requirements
→ evidence-set acquisition and completion
→ lane-specific applicability gates
→ deterministic operator or bounded reader Context
```

本 Goal 的第一个 behavior-changing change 固定为：

```text
删除：
any evidence_results
→ sufficient = true

替换为：
query-specific SufficiencyDecision
→ COMPLETE 才允许终止 completeness-required query
```

在此变更完成并通过 matched test 之前，禁止优先开展：

```text
Reader prompt tuning
larger context budget
embedding replacement
reranker rollout
graph engine
autonomous reconstruction
larger benchmark scale-out
```

DG-17 不削弱现有治理，不把所有 Evidence 提升为 Claim，也不把所有 Memory Query 强制解释成 State query。

2026-08-27 的开发检查进一步确认：当前 `EvidenceAtom v0.1` 同时混合 source span、
semantic interpretation 和 query-slot binding；`MemoryQueryIR v0.1` 又使用封闭枚举和英文
regex 默认将未识别问题降级为 `EPISODIC/LOOKUP/TOP_K_ACCEPTABLE`。这些对象可以
作为执行中的 typed DTO，但不得成为封闭的 Memory ontology。

因此本版本增加一次明确的 architecture ownership correction：

```text
Raw Evidence remains primary and lossless

EvidenceSpan
!= EvidenceInterpretationCandidate
!= RequirementBinding

SemanticQueryHint
!= executable MemoryQueryIR

vLLM may suggest semantics
but deterministic Runtime owns:
plan synthesis, applicability, binding, completeness and execution
```

vLLM 只能进入一条有界、最多一次调用的 `Semantic Repair` 路径。Exact State、普通
Episodic LOOKUP 和已受支持的 deterministic operator 继续保持 `auxiliary LLM calls = 0`。

Q1 matched characterization 之后的逐 case / prompt-byte 复核进一步确认：2048-token F1
`0.20 → 0.10` 由一个 temporal case 的单次 Reader 输出翻转造成；两个 arm 的检索来源、顺序和
语义正文相同，Reader-visible Context 只因重新 ingest 生成的随机 Evidence UUID 而不同。该结果
不能作为“query-specific sufficiency 降低检索质量”的因果证据，但暴露了 Reader-visible identity
污染、matched runner 不完全配对，以及 typed temporal requirement 被压成 generic lookup slot 的问题。

因此当前下一个 behavior-changing unit 固定为：

```text
Q1R Context Stability and Matched Causality Repair
→ remove volatile opaque IDs from Reader-visible Context
→ retain true Evidence IDs in ContextReceipt / provenance
→ replay both policies against one immutable Evidence snapshot
→ distinguish prompt-contract identity from exact prompt-byte identity

then

Q3A Contract Rebase
→ separate Span / Interpretation / Binding
→ establish one deterministic planner owner
→ preserve v0.1 compatibility only at an explicit translator
```

Q1R 与 Q3A 的历史前置已闭合；Q3C 证明“让模型直接提升 route/operator”的错误率过高，
因此 Q3D 保持 `PARKED_NOT_NEEDED`。本版本不重开 full-plan SemanticRepair，而是基于 Q6/Q8
证据建立一条权限更小的 acquisition successor lane。

## 0.1 Q8 后的 successor 决定

Q6-003 与 Q8-002 共同冻结下列阶段判断：

```text
Semantic Planning      PARTIAL PASS
Candidate Acquisition  FAIL
Requirement Binding    STARVED BUT SAFE
Operator               ORACLE PASS / LIVE FAIL
Sufficiency            SAFETY PASS
Reader                 SECONDARY BOTTLENECK
```

Observed：

```text
Q6-003 typed path coverage       = 7/23
Q8 strong-dense coverage         = 18/23
Q6-003 EM / F1                   = 2/10 / 0.227338130
Q8 strong-dense EM / F1          = 2/10 / 0.277685951
wrong COMPLETE                   = 0/N
```

这证明：

1. `MemoryQueryIR v0.2` 已能表达主要 requirement，不是当前首要重写对象；
2. Binding 与 Sufficiency 正确拒绝了缺失 operand 的结果，不得为提高 F1 而放松；
3. 主要缺口在 `MemoryQueryIR → candidate set` 之间；
4. strong dense 证明 Raw Evidence 召回可大幅提升，但它没有独立关闭 typed composition、
   completeness 或 answer-shape，因此 Q8 不授权默认产品 dense rollout；
5. 下一个 behavior-changing unit 必须修复 Candidate Acquisition，而不是 Reader prompt、
   Canonical Gate 或 public MCP contract。

新 successor 目标：

```text
MemoryQueryIR
→ AcquisitionPlan
→ query-wide + per-slot + structured probes
→ turn-first multi-channel candidates
→ query-conditioned structural expansion
→ deterministic interpretation / binding / sufficiency
→ optional one-call residual lexical cue only when slots remain missing
```

开发优先级固定为：

```text
P0  ordinary MCP resolve can acquire the answer-bearing Evidence safely
P1  Required Evidence Set / operator readiness materially improves
P2  acquisition work is bounded and query path remains usable
P3  final answer stability and wording normalization
P4  release-boundary audit and broader research characterization
```

不允许以更多内部合同、重复校验或开发阶段的反复审计代替 P0–P2。所有新检索机制
必须通过同一次 `milai_memory_resolve` 产品路径可用，而不是只在 LME adapter 中有效。

本版本进一步冻结“泛化优先”：

```text
examples belong in tests and failure analysis
semantic contracts belong in the planner
retrieval executes typed constraints; it does not reinterpret natural language
unknown semantics produce neutral retrieval, not guessed policy
weights are measured policy parameters, not inline magic constants
```

禁止将 Goal 中的某个 focal case、问法、动词或答案类型直接转写为产品 regex/词表。
Goal 中的例子只用于说明 failure class，不是 implementation recipe。

历史 Q0–Q8 编号、receipt 和结论保持不变。新工作使用 `A0–A11` 编号，避免将
Q8 diagnostic 追溯改写为产品实现授权。

---

# 1. DG-16 Terminal Architecture Finding

以下结论作为 DG-17 的不可回写前置事实：

```text
MCP / permission / Evidence persistence       PASS
revoke / provenance / governed write         PASS
Raw Evidence basic retrieval                 PARTIAL
query semantic planning                      FAIL / UNDER-SPECIFIED
required-evidence completion                 FAIL
temporal event reasoning                     FAIL
general evidence composition                 PROTOTYPE-ONLY
Canonical State contribution to LME          NOT EVALUATED
lifecycle scalability                        FAIL
```

## 1.1 最新独立 public-dev 证据

权威 receipt：

```text
var/dg16/lme10/dg16-lme10-compare-20260827-002/receipt-rescored.json
SHA-256:
e02a647ee4ffbcf70b7a92d8245770d5533219a54e5ccb23b06520c28e686afd
```

10 个独立 LongMemEval public-dev case，formal holdout overlap=`0`：

| Budget | Method | EM | normalized F1 | Hit@K | AnswerSessionCoverage |
| --- | --- | ---: | ---: | ---: | ---: |
| 512 | DG16 MiLA | `1/10` | `0.1194` | `0.70` | `0.50` |
| 512 | BM25-T | `0/10` | `0.0857` | `0.60` | `0.45` |
| 2048 | DG16 MiLA | `2/10` | `0.2000` | `0.70` | `0.60` |
| 2048 | BM25-T | `0/10` | `0.0857` | `0.60` | `0.45` |

重要纠偏：此前报告中的 `Evidence Recall` 实际由：

```text
answer_session_ids
→ score_retrieval(... relevant_sessions ...)
```

计算，必须重命名为：

```text
AnswerSessionCoverage
```

它不证明 answer-bearing turn、Evidence atom、required operand 或 temporal range 已完整进入 Context。

实现证据：

```text
evals/dg16/lme10.py::_score_records()
```

## 1.2 2048-token failure decomposition

| Failure slice | Cases | Interpretation |
| --- | ---: | --- |
| relevant session 完全未命中 | `3/10` | candidate acquisition failure |
| 仅覆盖部分 relevant sessions | `2/10` | evidence-set incomplete |
| session coverage=`1` 但回答错误 | `3/10` | turn/span/binding、operator 或 reader residual |
| 正确 | `2/10` | end-to-end chain success |

因此“Hit@K=`0.70` 但 EM=`0.20`”不能归因为单一 Reader 措辞问题。

## 1.3 当前真实读取控制流

Observed：

```text
Query
→ eval adapter 固定添加 "Recall previous history evidence:"
→ Raw Evidence OR-FTS
→ 按 session 内单个最高 turn score 选择 session
→ 回填 session Evidence
→ 任意 Evidence 命中即 sufficient
→ stop at EVIDENCE_FTS
→ eval adapter 最多选择 3 个 windows
→ vLLM reader
```

核心实现位置：

```text
evals/dg15/milai_mcp_adapter.py::DG15MiLAIMCPAdapter.query()
runtime/src/milai/persistence/retrieval_repository.py::evidence_query_terms()
runtime/migrations/versions/0036_dg15_evidence_session_retrieval.py
runtime/src/milai/application/retrieval.py::RetrievalService.retrieve()
evals/dg15/milai_mcp_adapter.py::_windows()
evals/dg15/milai_mcp_adapter.py::_compile_context()
```

P0 correctness evidence：

```text
runtime/src/milai/application/retrieval.py

if evidence_composition is not None:
    sufficient = True
elif evidence_results:
    sufficient = True
    reason = "EVIDENCE_LEXICAL_SUFFICIENT"
```

即使 `EvidenceCompositionResult.status != COMPLETE`，当前分支仍可能终止 progressive retrieval。

## 1.4 两个 focal operator 的边界

当前 Raw Evidence composition contract 仅实现：

```text
DIVIDE_EVIDENCE_VALUES
TEMPORAL_COUNT_DISTINCT
```

实现证据：

```text
runtime/src/milai/domain/evidence_composition.py
  QuerySpec: "Only the two operator shapes exercised by the focal verticals."
```

DG-16 的 5-case 成功只证明两个定制 vertical 与原有正确 case 可以闭环，不证明：

```text
unseen temporal wording
unseen event type
unseen entity
unseen operand distribution
unseen multi-session composition
```

能够通过同一语义合同泛化。

## 1.5 Canonical State 尚未被本次 LME 评估

最新 adapter 和 receipt 均报告：

```text
claim_count = 0
candidate_kind = EVIDENCE_OBSERVATION
canonical = false
authority = EVIDENCE_ONLY
```

因此本次 10-case 不能支持：

```text
Canonical State architecture is ineffective
```

只能支持：

```text
Canonical State was not materially exercised by this workload/path.
```

ClaimVersion、ClaimHead、OpenIssue 和 StateAddress 的质量贡献必须在真正的 State query benchmark 中单独评估。

## 1.6 生命周期证据独立处理

```text
online query mean         = 53.5 ms
answer path mean          = 286.9 ms
full lifecycle mean       = 66.0 s/case
cleanup mean              = 53.6 s/case
cleanup lifecycle share   ≈ 81%
```

结论：

```text
Semantic Quality Lane
!=
Lifecycle Efficiency Lane
```

DG-17 只约束在线语义读取成本。批量 ingest、set-based cleanup、persistent worker 和 projection throughput 属于独立 DG-18 successor，不得以更快运行当前错误语义替代 DG-17 质量闭环。

## 1.7 vLLM 语义介入可行性探针

2026-08-27 使用当前 operator-owned vLLM 对 12 个中英混合合成问题进行了三组
strict-JSON-schema ad-hoc probe。调用没有修改 vLLM 配置，`automatic retry=0`，并发为 4。

| vLLM 职责 | Mean | Observed p95 | 开发结论 |
| --- | ---: | ---: | --- |
| 直接生成完整执行计划 | `2029.9 ms` | `2528.5 ms` | 出现冗余/错误 step，禁止进入产品路径 |
| 生成 route + requirements + 半完整 plan | `885.6 ms` | `1009.7 ms` | 仍会对普通 recall 强行选择错误 operator |
| 只分类 route/operator，32–38 completion tokens | `427.1 ms` | `507.3 ms` | 12 个 probe 中 11 个给出预期粗粒度分类；average query 仍不一致 |

第三组 12 次调用在 concurrency=4 下总 wall time 为 `1314.2 ms`。这表明 continuous
batching 可提高吞吐，但不会消除约 400–500 ms 的单请求附加延迟。

该探针只用于校准设计：

```text
AD-HOC FEASIBILITY SIGNAL
NOT A DG17 RECEIPT
NOT A QUALITY GATE
NOT A BENCHMARK RESULT
```

它支持的唯一开发决定是：

> **vLLM 只输出最小 SemanticQueryHint 或对当前 missing slots 的修复建议，不直接生成最终执行计划。**

## 1.8 Q1 2048-token F1 回归复盘

权威 artifacts：

```text
var/dg17/q1/dg17-q1-p0-matched-20260827-002/receipt.json
SHA-256:
d9c9d304fef3c9d5becf71d875f5d48df4242813bd289dadd338f9f948ac94cb

var/dg17/q1/dg17-q1-p0-matched-20260827-002/contexts.json
SHA-256:
05d61896d11e56f053c6fcefafd7e81154ae03ed07df6d0326946b202671301a

var/dg17/q0/dg17-q0-oracle-corrected-20260827-005/receipt.json
SHA-256:
2de98f601495d59476c5a9d44d6f51254e952eb1292131a0389bdb3b43bef5bf
```

逐 case 对照确认：

| Budget | DG16 F1 | Q1 F1 | 真实变化 |
| --- | ---: | ---: | --- |
| 512 | `0.119417476` | `0.122807018` | preference case 的措辞 overlap 小幅变化；没有新增完整 evidence set |
| 2048 | `0.200000000` | `0.100000000` | 仅 `9a707b82` 从 `1.0 → 0.0`；其余 case 没有正分损失 |

两行都是 observed score decomposition，不是 mechanism-level causal estimate；512 的小幅上升也受同一
跨 run prompt-identity 混杂约束，不得作为 Q1 quality gain。

`9a707b82` 的事实链是：

```text
question:
I mentioned cooking something for my friend a couple of days ago. What was it?

gold:
chocolate cake

same source turn contains:
banana bread → for the dinner party
chocolate cake → for my friend's birthday party
```

Observed：

```text
DG16 answer                         = chocolate cake
DG17 Q1 answer                     = banana bread
selected_source_refs               = identical
retrieval rank/order               = identical
RequiredEvidenceSetCoverage        = 1.0 in both arms
AnswerSessionCoverage / Hit@K      = 1.0 in both arms
provider seed                      = identical
Reader-visible semantic prose      = identical
```

完整 Context diff 只包含重新 ingest 后变化的 `evidence_ids=[UUID...]`。把 UUID 规范化为稳定占位符后，
两个 Context byte-for-byte 相同；随机 UUID 的 tokenizer 分词还使 provider 侧 memory token count
出现 `850 → 851`。因此：

```text
Q1 safety mediator:
premature terminal 7 → 3 at 2048
typed abstention     0 → 4

Q1 quality attribution:
CAUSALLY INCONCLUSIVE / VOLATILE-PROMPT CONFOUNDED
```

这不意味着 Reader 可以忽略。相反，同一个 Raw Evidence turn 同时包含两个可作答实体，说明当前
Context 没有把 query-conditioned binding 清晰表达给 Reader；微小的无语义 prompt 扰动即可翻转答案。
但该翻转不能归因于 candidate recall 或 Q1 stop policy，因为 answer-bearing 内容没有变化。

同时观察到第二个独立 correctness 缺口：receipt 的外层 operator 是 `TEMPORAL_FILTER`，而
`SufficiencyDecision` 却报告：

```text
covered_slots = [LOOKUP_ANSWER]
status        = COMPLETE
stop_reason   = REQUIREMENT_SATISFIED
```

当前 `runtime/src/milai/application/sufficiency.py::_evidence_lookup_decision()` 主要依据 query term 与
Evidence content 的 lexical intersection 判断 answer-bearing。它没有证明：

```text
TARGET_EVENT
AND friend-role compatibility
AND relative-time compatibility
AND cooked-item predicate compatibility
```

因此正式开发决定为：

1. 保留 Q1 的安全性结论，不回滚 query-specific stop；
2. 撤销把 Q1 `0.20 → 0.10` 解释为语义质量因果退化的资格；
3. 在下一次 matched quality run 前先完成 Q1R Context/experiment repair；
4. 在 Q3A/Q3B 中禁止 typed operator 静默坍缩为 `LOOKUP_ANSWER`；
5. 只有稳定 Reader Context、有效 RequirementBinding 和 current Q6 receipt 才能决定最终 F1。

---

# 2. 与其他 Goal 的关系

## 2.1 DG-13

DG-13 已获得 scoped label：

```text
DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE
```

DG-17 保留：

- MCP 是 MiLA 第一产品接口；
- 普通 MCP client 不提供 TaskIdentity 也能 query memory；
- principal、scope、capability、permission 和 typed errors；
- Evidence capture、Proposal、Review、ClaimVersion、revoke、retention 和 audit；
- OpenWorker 是 MCP client，不是 MiLA Canonical Core。

DG-17 不建立 Direct/HTTP 第二套 memory semantics。

## 2.2 DG-14

DG-14 historical artifacts 保持只读。其 5-case matched characterization 是旧架构基线，不允许回写或重评分以制造 successor improvement。

## 2.3 DG-15

DG-15 的 worker、batch、watermark 和流水线实现可以复用，但其性能指标不能作为 DG-17 Semantic Read PASS 的替代品。

## 2.4 DG-16

DG-16 状态冻结为：

```text
FOCAL VERTICALS COMPLETE
GENERALIZATION FAILED ON INDEPENDENT PUBLIC-DEV
TERMINAL ARCHITECTURE FINDING ACCEPTED
```

DG-17 是 successor，不继续把第三、第四个 benchmark wording regex 追加到 DG-16。

## 2.5 DG-18

DG-18 预留给：

```text
batch ingest
persistent worker
set-based benchmark namespace cleanup
set-based projection purge
watermark and projection throughput
```

本文不授权 DG-18 实现，也不允许 DG-18 阻塞 DG-17 当前 10-case 的语义修复。

---

# 3. 产品边界与不可破坏不变量

## 3.1 产品边界

MiLA 继续定义为：

> MCP-native governed Agent Memory Runtime。

MiLA 负责：

```text
memory query interpretation
memory state/evidence addressing
evidence acquisition and composition
current/historical state resolution
context compilation
memory lifecycle governance
```

MiLA 不负责：

```text
Agent planning
Provider orchestration
complete Host Task registry
workflow state machine
answer generation policy
```

## 3.2 基础不变量

```text
Evidence != Claim
EvidenceAtom != Claim
EvidenceSpan != EvidenceInterpretationCandidate
EvidenceInterpretationCandidate != RequirementBinding
Projection != Canonical State
Proposal != Commit
Context != Truth
Confidence != Authority
Retrieval Result != Belief
SemanticQueryHint != executable plan
Model suggestion != SufficiencyDecision
TaskContext is optional for informational read
```

## 3.3 Lane-specific applicability

禁止让 Raw Evidence 假装通过 Canonical State Gate。

统一概念：

```text
MemoryApplicabilityGate
```

内部必须区分：

```text
EvidenceApplicabilityGate
  tenant
  principal permission
  scope
  retention
  revoke
  provenance
  source identity

CanonicalStateGate
  ClaimVersion applicability
  valid-time / system-time
  authority
  lifecycle
  Grounding / OpenIssue
  currentness
```

## 3.4 Eval ownership

遵循 repository 合同：

```text
evals/ may own:
  dataset mapping
  protocol
  scorer
  case scheduling
  artifact export

evals/ MUST NOT own:
  product retrieval behavior
  window selection semantics
  evidence sufficiency
  context compilation semantics
  operator execution
```

DG-17 必须把当前 eval adapter 中的 turn pairing、window ranking、neighbor recovery、Top-k packing 和 Context compilation 迁回 Runtime product path。

---

# 4. 目标读取架构

```text
                           MCP memory.resolve
                                    │
                                    ▼
                      Authenticated Principal Gate
                                    │
                                    ▼
                   Deterministic Query Frontend
                                    │
                                    ▼
                            MemoryQueryIR v0.2
                                    │
                                    ▼
                       AcquisitionPlanCompiler
                                    │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
       query-wide probes     per-slot probes      structured filters
              │                 │                 │
              └─────────────────┼─────────────────┘
                                    ▼
             FTS_RAW / FTS_ENRICHED / EVIDENCE_DENSE /
               TEMPORAL_EVENT / CANONICAL_STATE
                                    │
                                    ▼
                     turn-first per-slot fusion
                                    │
                                    ▼
                 query-conditioned structural expansion
                                    │
                                    ▼
             CanonicalStateGate / EvidenceApplicabilityGate
                                    │
                                    ▼
              Interpretation → Binding → preliminary Sufficiency
                         │                    │
                      COMPLETE             required slot missing
                         │                    │
                         │                    ▼
                         │          optional one-call residual cue
                         │                    │
                         │          one extra acquisition pass
                         │                    │
                         └──────────┼──────────┘
                                    ▼
                     final SufficiencyDecision
                                    │
                   ┌────────────────┴────────────────┐
                   │                                 │
                COMPLETE                    PARTIAL / UNSATISFIED
                   │                                 │
                   ▼                                 ▼
       StateView / EvidenceView /          typed abstention; no second
              OperatorResult               model retry or answer guess
                   │
                   ▼
            Context Compiler
                   │
                   ▼
            MemoryContext + ContextReceipt
                   │
                   ▼
                  Agent
```

`AcquisitionPlan` 是 Runtime 内部 DTO，不是新 MCP public contract。它将已经冻结的
`MemoryQueryIR` 编译为可执行的 probe、硬约束、quota、fusion、expansion 和成本上限。
IR 不得在 retrieval 边界退化为一个全局 OR query。

`ResidualLexicalHint` / `ResidualAcquisitionHint` 是 Runtime 内部可选辅助，不是新
MCP tool，也不是 Q3C `SemanticQueryHint` 的 full-plan promotion。一次
`milai_memory_resolve` 的 residual vLLM call 总数不得超过 1。

调用触发固定为：

```text
deterministic AcquisitionPlan has executed
AND deterministic Binding still has required missing slots
AND residual policy explicitly allows one hint
AND latency/candidate/token budget remains
```

以下路径必须保持 `auxiliary LLM calls = 0`：

```text
explicit StateKey / Claim ID exact read
safe current-state address lookup
ordinary supported episodic lookup
deterministic temporal/count/divide operator that reaches COMPLETE without residual
```

## 4.1 Canonical State Lane

适用：

```text
CURRENT_STATE
HISTORICAL_STATE
KNOWLEDGE_UPDATE
PREFERENCE_STATE
CONFLICT
VERSION_DIFF
```

路径：

```text
StateKey / Claim ID
→ ClaimHead / ClaimVersion trajectory
→ valid-time / system-time
→ Grounding / OpenIssue
→ CanonicalStateGate
→ StateView
```

## 4.2 Episodic Evidence Lane

适用：

```text
past conversation recall
event recall
assistant recommendation recall
bounded temporal event retrieval
source-context recovery
```

路径：

```text
Turn Evidence
→ turn/span independent ranking
→ EvidenceApplicabilityGate
→ query-conditioned neighbor/episode expansion
→ EvidenceView
```

## 4.3 Evidence Composition Lane

适用：

```text
COUNT
SUM
AVERAGE
DIVIDE
COMPARE
TEMPORAL_ORDER
TEMPORAL_DISTANCE
MULTI_SESSION_JOIN
PREFERENCE_RESOLVE
WHY_CHANGE
```

路径：

```text
MemoryQueryIR
→ required EvidenceRequirement slots
→ per-slot acquisition
→ structural expansion
→ join / deduplicate
→ completeness proof
→ deterministic operator or structured reader input
```

---

# 5. 最小内部合同

第一阶段冻结的是 Runtime 内部 versioned DTO，不扩大 MCP public tool 数量。外部主读取接口继续是一次粗粒度：

```text
milai_memory_resolve
```

只有 MCP response shape 必须变化时，才单独进行 contract versioning 和 compatibility test。

## 5.1 `SemanticQueryHint v0.1`

vLLM 只允许输出最小、不可执行的语义提示：

```yaml
schema_version: semantic-query-hint-v0.1

route:
  STATE
  EVIDENCE
  COMPOSE
  AMBIGUOUS

operator_family:
  LOOKUP
  TEMPORAL_FILTER
  TEMPORAL_ORDER
  TEMPORAL_DISTANCE
  COUNT
  SUM
  AVERAGE
  DIVIDE
  COMPARE
  MULTI_JOIN
  WHY_CHANGE

cue_spans:
  - start:
    end:
    text:

temporal_spans: []
requires_complete_set: false
ambiguities: []
```

`model_trace` 不由模型生成，由调用 adapter 在输出外包中附加，避免浪费 completion tokens 或让
模型伪造调用身份：

```yaml
SemanticHintReceipt:
  hint:
  provider:
  model:
  prompt_digest:
  schema_digest:
  seed:
  prompt_tokens:
  completion_tokens:
  tokenizer_latency_ms:
  queue_ttft_decode_total_ms:
```

强制规则：

```text
cue_spans / temporal_spans must be exact substrings of the query
hint cannot contain final answer
hint cannot contain Claim/Evidence authority decision
hint cannot declare SufficiencyDecision.COMPLETE
hint cannot emit executable SQL/retrieval stages
hint cannot mutate canonical state
numeric self-confidence is not an authority or promotion signal
```

schema invalid、timeout、cue span 不匹配或无法映射时，返回 typed `SEMANTIC_ASSIST_UNAVAILABLE` 或
`QUERY_AMBIGUOUS`。只有在普通 Evidence browsing 仍然语义安全时，才允许继续返回明确标记的
`PARTIAL / UNSTRUCTURED_EVIDENCE`；completeness-required query 必须 abstain。

## 5.2 `MemoryQueryIR v0.2`

`MemoryQueryIR` 保留为 Runtime 执行 IR，但不再把一个封闭 operator 枚举当成完整 Memory
ontology。它必须由 deterministic Plan Synthesizer 产生；vLLM 不得直接 instantiate 该对象。

```yaml
schema_version: memory-query-ir-v0.2

mode:
  STATE
  EVIDENCE
  COMPOSE
  AMBIGUOUS

answer_shape:
  SCALAR
  LIST
  STATE
  TIMELINE
  EXPLANATION
  SUMMARY

constraints:
  cue_spans: []
  state_addresses: []
  temporal_expressions: []
  normalized_temporal: null
  scope: null

requirements: []

steps:
  - kind:
      RETRIEVE
      FILTER
      EXPAND_NEIGHBOR
      EXPAND_EPISODE
      TEMPORAL_SCAN
      BIND_SLOT
      JOIN
      DEDUPLICATE
      REDUCE
      COMPARE
    inputs: []
    outputs: []
    constraints: {}
    budget: {}

completeness:
  TOP_K_ACCEPTABLE
  ALL_REQUIRED_BINDINGS
  ALL_MATCHES_IN_RANGE
  COMPLETE_VERSION_CHAIN
  SUPPORT_THRESHOLD
  UNSTRUCTURED_EVIDENCE_ALLOWED

planner_trace:
  source: DETERMINISTIC | SEMANTIC_REPAIR | AMBIGUOUS
  compiler_version:
  hint_digest: null
  auxiliary_model_calls: 0
```

典型组合：

```text
count:
RETRIEVE → TEMPORAL_SCAN → FILTER → DEDUPLICATE → REDUCE(count)

unit price:
RETRIEVE → BIND_SLOT(money) → BIND_SLOT(count)
→ JOIN(same entity/episode) → REDUCE(divide)

why change:
RETRIEVE versions → RETRIEVE transition evidence
→ JOIN → COMPARE → explanation context
```

`MemoryQueryIR v0.1` 是当前已实现 precursor。Q3A 允许在内部使用一个明确 compatibility translator，
但 matched transition 结束后只能有一个 planner owner，不允许 legacy operator 与 v0.2 IR 竞争决定实际执行路径。

### 5.2A `AcquisitionPlan v0.1`

`AcquisitionPlan` 是 `MemoryQueryIR` 与 retrieval repository 之间的唯一执行合同：

```yaml
schema_version: acquisition-plan-v0.1
query_ir_digest:

global_constraints:
  principal_scope:
  semantic_scope:
  authority_floor:
  source_observed_range: null
  event_occurrence_range: null

probes:
  - probe_id:
    requirement_slot: null
    channel:
      FTS_RAW
      FTS_ENRICHED
      EVIDENCE_DENSE
      TEMPORAL_EVENT
      CANONICAL_STATE
    semantic_subject:
      actor: null
      experiencer: null
      beneficiary: null
    evidence_source_policy:
      preferred_speakers: []
      allowed_speakers: null
      provenance:
        EXPLICIT_QUERY
        TYPED_HINT
        SEMANTIC_PARSER
        NONE
    lexical_terms: []
    phrases: []
    predicate_family: null
    entities: []
    temporal_axis:
      SOURCE_OBSERVED_TIME
      EVENT_OCCURRENCE_TIME
      BOTH
      NONE
    candidate_limit:
    expansion_policy:
      NONE
      ADJACENT_TURNS
      SAME_EPISODE
      SAME_SESSION

fusion:
  policy_identity:
  per_slot_quota: {}
  global_cap:

residual_policy:
  allowed: false
  max_model_calls: 0
  max_extra_passes: 0

budget:
  latency_ms:
  candidate_count:
  hydrate_count:
  context_tokens:
```

强制规则：

```text
all required slots receive an explicit probe disposition
hard scope/permission/time constraints execute before ranking
event actor/subject is not conflated with the speaker that supplied Evidence
evidence-source policy is per requirement/probe, never one query-global role guess
allowed_speakers is populated only by explicit source constraints; otherwise source preference is soft or empty
missing/ambiguous role semantics produce neutral retrieval, not a guessed hard filter
lexical enrichment is stored and queried separately from dense text
fusion preserves probe/slot/channel/rank provenance
session/episode is expansion scope, not the primary relevance score
fusion policy (including RRF experiments) is configured and traced, not frozen into IR semantics
```

### 5.2B `CandidateEnvelope v0.1`

候选在 Interpretation 之前必须保留来源身份和 acquisition provenance：

```yaml
candidate_id:
source_evidence_id:
source_turn_ref:
session_id:
speaker:
speaker_source:
  STRUCTURED_TURN_METADATA
  AUTHORITATIVE_BACKFILL
  UNKNOWN
source_observed_at:
event_occurrence_interval: null

matched_probes: []
matched_slots: []
channel_ranks: {}
channel_scores: {}
fusion_rank:
fusion_score:
expansion_origin: null
matched_fields: []

body_ref:
body_hydrated: false
```

候选阶段先排 metadata，通过 fusion/cutoff 后才 hydrate 正文。不得在 session grouping
或早期 dedup 时丢失 `requirement_slot` 和 channel rank。

`speaker` 必须来自 ingest 时的结构化 turn envelope 或可验证的 source metadata。历史数据若无
结构化 speaker，则为 `UNKNOWN`；禁止通过 `content.startswith("user:")` 等正文前缀把猜测写回
CandidateEnvelope。

### 5.2C `AcquisitionLossRecord v0.1` — eval-only

`AcquisitionLossRecord` 只存在 development/eval artifact，不进入 Runtime 决策，不进入
MCP result，不得被产品代码读取：

```yaml
case_id:
requirement_slot:
gold_session_id:
gold_turn_id:
gold_span:

query_terms_generated:
lexical_match_possible:
temporal_filter_included:
role_filter:

raw_fts_rank: null
enriched_fts_rank: null
dense_rank: null
temporal_rank: null
rank_after_fusion: null

survived_candidate_cutoff:
survived_session_grouping:
recovered_by_expansion:
retained_by_context_packing:
interpretation_created:
binding_created:
sufficiency_effect:

first_loss_stage:
  TERM_GENERATION
  CHANNEL_SELECTION
  LEXICAL_MATCH
  DENSE_MATCH
  TEMPORAL_FILTER
  ROLE_FILTER
  RANKING
  SESSION_CUTOFF
  FUSION
  EXPANSION
  PACKING
  INTERPRETATION
  BINDING
```

Gold labels 只能用于运行后归因。例如 `9a707b82` 当前只能冻结为“正确 source turn/session
未进入最终候选集”；在 A0 ledger 产生前，禁止预先将其 `first_loss_stage` 写成
`LEXICAL_MATCH` 或任一其他特定阶段。

### 5.2D Residual hint contracts

Q3C `SemanticQueryHint v0.1` 作为历史 shadow 合同保留，但不再是 successor 产品接入对象。
新 residual lane 首先只冻结更小的：

```yaml
ResidualLexicalHintV0_1:
  missing_slot:
  predicate_aliases: []
  entity_aliases: []
  morphological_variants: []
  confidence: null
```

`confidence` 只进入 trace，不是促成 promotion 的 authority。每个 alias 必须保留：

```text
source = deterministic_lexicon | model_residual
model/prompt/schema identity when applicable
target missing_slot
validation outcome
```

v0.1 禁止输出：

```text
route / operator / Evidence ID / final answer / COMPLETE
time range / scope / permission / authority / canonical applicability
```

只有 A8 shadow 通过后，才可在后续 ADR 中评估：

```yaml
ResidualAcquisitionHintV0_2:
  missing_slot:
  predicate_aliases: []
  entity_aliases: []
  temporal_search_axis:
    SOURCE_OBSERVED_TIME
    EVENT_OCCURRENCE_TIME
    BOTH
    NO_CHANGE
  acquisition_action:
    EXPAND_LEXICAL
    ADD_DENSE_PROBE
    SEARCH_EVENT_INDEX
    EXPAND_ADJACENT_TURNS
    EXPAND_SAME_EPISODE
    NO_ACTION
```

v0.2 也不得选择 Evidence、修改 scope 或声明 COMPLETE。运行后仍由确定性
Interpretation、Binding 和 Sufficiency 重新验证。

## 5.3 Evidence 三分模型

### `EvidenceSpan v0.1`

```yaml
span_id:
source_evidence_id:
source_turn_ref:
session_id:
speaker:
start:
end:
text:
source_timestamp:
provenance:
```

`EvidenceSpan` 只表示可校验的 source pointer，不表示语义事实或 query slot。

### `EvidenceInterpretationCandidate v0.1`

```yaml
interpretation_id:
span_id:
kind:
  EVENT
  QUANTITY
  STATE_OBSERVATION
  PREFERENCE_SIGNAL
  DECISION
  RELATION
value: null
unit: null
entities: []
event_time: null
time_basis:
  EXPLICIT_EVENT_TIME
  INFERRED_EVENT_TIME
  SOURCE_OBSERVED_TIME
extractor_identity:
confidence: null
```

一个 span 可以有 0..N 个 interpretation candidates。`SOURCE_OBSERVED_TIME` 只是回退时间信息，
不得在没有额外证明时当成 event time。

### `RequirementBinding v0.1`

```yaml
requirement_id:
interpretation_id:
status:
  MATCH
  POSSIBLE
  REJECTED
compatibility:
  type:
  entity:
  unit:
  temporal:
  episode:
reason_code:
```

slot role 属于 `RequirementBinding`，不属于 `EvidenceSpan` 或抽取出的原始 quantity。例如同一句
`I paid $60 for 5 mugs` 必须先独立解释为 `MONEY=60 USD` 和 `INTEGER=5`，然后再由 binding
validator 判断 `TOTAL_PRICE` 与 `ITEM_COUNT`。禁止 requirement × sentence numbers 的无类型交叉乘积。

`EvidenceAtom v0.1` 作为当前 query-time precursor 可在 Q3A transition 内部存在，但必须满足：

```text
not persisted as canonical state
not exposed as a stable public MCP object
not used as both interpretation and final requirement binding
removed or reduced to an internal compatibility alias after matched transition
```

模型或规则抽取的 interpretation 不能直接提升 authority，不能自动修改 ClaimHead，也不能
自行宣告 requirement 已满足。

## 5.4 `EvidenceRequirement v0.2`

```yaml
slot_id:
interpretation_kind:
entity_constraints: []
predicate_constraints: []
temporal_constraints: null
value_type: null
cardinality:
join_key: null
required: true
```

Requirement 是 query-conditioned 的，不持久化为 truth。`interpretation_kind` 是对
`EvidenceInterpretationCandidate.kind` 的类型约束，不得用来反向制造相同类型的 Atom。v0.1
compatibility translator 可读取旧 `atom_type`，但 v0.2 新代码不再以该名称表达 slot 类型。

## 5.5 `SufficiencyDecision v0.1`

```yaml
status:
  COMPLETE
  PARTIAL
  UNSATISFIED
  CONTESTED
  UNBOUNDED

covered_slots: []
missing_slots: []

proof:
  bounded_scan_completed: false
  source_partition_closed: false
  projection_watermark: null
  deduplication_completed: false
  version_chain_complete: false

stop_reason:
  REQUIREMENT_SATISFIED
  SEARCH_SPACE_EXHAUSTED
  BUDGET_EXHAUSTED
  PROJECTION_NOT_READY
  QUERY_AMBIGUOUS
  ACCESS_DENIED
  MEMORY_UNAVAILABLE
```

禁止任何内部代码把以下条件单独作为 COMPLETE：

```text
candidate_count > 0
session_hit = true
FTS_score > threshold
context_nonempty = true
TTL_not_expired = true
```

## 5.6 `EvidenceView` 与 `ContextReceipt`

Raw Evidence 必须拥有正式、非 canonical 的 Context receipt：

```yaml
ContextReceipt:
  context_id:

  authority_class:
    EVIDENCE_ONLY
    CANONICAL_STATE
    MIXED

  query_ir_digest:
  requirement_digest:

  source_evidence_ids: []
  claim_versions: []
  issue_revisions: []

  sufficiency_status:
  missing_slots: []

  canonical_position: null
  projection_watermarks: {}
  issued_at:
```

Reader-visible Context 与结构化 provenance 必须分离。真实 `evidence_id`、`claim_version_id`、
`trace_id`、content hash 和其他高熵 opaque identifier 继续完整保存在 MCP structured result、
`ContextReceipt` 和 `AccessTrace` 中，但默认不进入给 vLLM 的自然语言正文。

Reader-visible 引用使用当次 Context 内稳定、短小且确定性的 alias：

```yaml
reader_context:
  text: "[E1] ... [E2] ..."
  reader_context_digest:
  semantic_context_digest:

receipt_mapping:
  E1:
    evidence_ids: []
    source_turn_refs: []
  E2:
    claim_versions: []
```

要求：

```text
alias ordering is deterministic from selected source order
same semantic Context produces the same Reader-visible bytes
re-ingest-generated UUID changes do not change Reader-visible bytes
true ID mapping remains lossless and auditable in the receipt
explicit provenance/explain query returns resource links or structured refs
opaque IDs are rendered into prose only when the IDs themselves are query-relevant
```

`semantic_context_digest` 必须排除允许变化的 execution identity，并覆盖实际 evidence prose、
speaker、event/source time、scope/authority marker、binding annotation 和 selected order；
`reader_context_digest` 覆盖真正发送给 Provider 的精确 Context bytes。两者均不能替代
`ContextReceipt` 中真实 provenance。

Receipt 证明：

```text
what was returned
under which authority class
with which dependencies and completeness status
```

Receipt 不证明 Evidence 自动成为 canonical truth。

---

# 6. Query-specific Sufficiency Contracts

| Operator | `COMPLETE` 条件 |
| --- | --- |
| `LOOKUP` | 至少一个通过 applicability 且与 query 约束匹配的 answer-bearing span/binding，或唯一合法 State |
| `TEMPORAL_FILTER` | `TARGET_EVENT` binding 存在，且 event/entity/role/predicate 与归一化 temporal constraint 均兼容；同 turn 中另一个可回答实体不能替代该 binding |
| `STATE_AT_TIME` | 指定时间点存在合法 ClaimVersion，冲突被解析或显式暴露 |
| `DIVIDE_VALUES` | required operands 均存在、实体一致、单位兼容 |
| `COUNT_DISTINCT` | 时间/作用域范围已解析，范围扫描完整，事件已去重 |
| `TEMPORAL_ORDER` | 两个 required events 均检出且 event time 可比较 |
| `TEMPORAL_DISTANCE` | 两个时间点或区间足以按指定 boundary/unit 计算 |
| `MULTI_EVIDENCE_JOIN` | 所有 required slots 存在且 join relation 成立 |
| `PREFERENCE_RESOLVE` | 支持证据达到 threshold，更新、冲突和 currentness 已处理 |
| `VERSION_DIFF` | old/new version 与合法 transition evidence 均存在 |
| `EXPLANATION` | 结论、支持来源和必要 lineage 均可追溯 |

`TOP_K_ACCEPTABLE` 只允许用于开放式 episodic recall 或建议性 evidence browsing；不得用于 count、range completeness、required operands、current state 或 authority-sensitive decision。

Typed operator 的 requirement identity 必须端到端保留：

```text
TEMPORAL_FILTER / TARGET_EVENT
must not become
LOOKUP / LOOKUP_ANSWER
```

只有 QueryIR 本身就是安全的普通 episodic `LOOKUP` 时，`LOOKUP_ANSWER` 才是合法 slot。compatibility
translator 无法无损翻译 typed requirement 时必须返回 `AMBIGUOUS/PARTIAL`，不得为兼容旧路径而扩大
`COMPLETE`。

---

# 7. Evidence 粒度与 Temporal Representation

## 7.1 五种粒度必须分离

| 粒度 | 当前目标 |
| --- | --- |
| Storage unit | 原始 turn/message，无损保存 provenance |
| Governance unit | EvidenceRecord 或真正的 semantic State candidate |
| Retrieval unit | turn、episode、event、Claim，按 QueryIR 选择 |
| Composition unit | EvidenceInterpretationCandidate + validated RequirementBinding |
| Context unit | 满足 requirements 的最小窗口集合 |

禁止：

```text
one matched turn
→ whole session gets one rank
→ arbitrary session backfill
→ sufficient
```

改为：

```text
turn / span independent ranking
→ applicability filtering
→ query-conditioned structural expansion
```

## 7.2 允许的 expansion

```text
same-turn span recovery
adjacent user/assistant turn
same episode
same entity
same temporal interval
same version trajectory
cross-session required-slot join
```

每种 expansion 必须记录：

```text
trigger
source candidate
expanded candidates
cost
coverage delta
stop reason
```

Session diversity 只能由明确的 multi-session requirement 启用，不再是统一 Context packing 目标。

## 7.3 Temporal dual representation

MiLA 使用轻量双表示：

```text
Turn Timeline
  raw source timestamp and adjacency

Event Timeline
  normalized event interval and source refs
```

必须区分：

```text
source/observed time
event/valid time mentioned in content
system/captured time
```

### Ingest-time cheap projection

仅抽取高置信显式信息：

```text
explicit date/time
amount
quantity
named entity
explicit event phrase
source turn
```

### Query-time targeted extraction

仅对 bounded candidates 处理：

```text
relative time
implicit event type
attendance/completion state
event identity and deduplication
cross-turn operands
```

第一阶段优先使用 query-time DTO 和现有 PostgreSQL projection。只有 profile 或 completeness proof 证明必须持久化，才允许新增 Event/Interpretation projection table。RequirementBinding 保持 query-local，不持久化为 truth。

新增 Schema 必须同时交付：

```text
ADR
Alembic migration
upgrade/downgrade or irreversible rationale
backfill/rebuild
projection epoch/watermark
permission/revoke/purge propagation
real PostgreSQL integration test
rollback plan
```

---

# 8. Runtime Ownership 与实现边界

## 8.1 主要现有 owner

| Responsibility | Current location | DG-17 direction |
| --- | --- | --- |
| Query planning | `runtime/.../query_planner.py` | deterministic Plan Synthesizer 是唯一最终 owner；生成 `MemoryQueryIR v0.2`，禁止 benchmark case wording ownership |
| Deterministic query parsing | `runtime/.../memory_query.py` | 保留快路；未识别 completeness signal 不得静默降级为 safe LOOKUP |
| Acquisition planning | new Runtime application boundary | 将 `MemoryQueryIR` 编译为 `AcquisitionPlan`；拥有 slot probes、channel、quota、fusion、expansion 和 budget；不扩大 MCP contract |
| Turn-first candidate acquisition | `runtime/.../retrieval.py` + `runtime/.../retrieval_repository.py` | 以 turn/span 为 rank unit，session/episode 只做结构扩展；保留 slot/channel/rank provenance |
| Lexical enrichment | new rebuildable projection/lexicon boundary | raw/enriched FTS 分离；predicate bridge 必须通用化并有 provenance；不污染 dense text |
| Temporal acquisition | existing observed-time scan + successor event-time projection | 显式分离 `SOURCE_OBSERVED_TIME` 与 `EVENT_OCCURRENCE_TIME`；完整性查询必须有 bounded-scan proof |
| Raw Evidence dense/rerank | Q8 diagnostic runner + successor Runtime path | Q8 仅是诊断；产品路径必须对 Evidence turn 排名，并在硬约束之后运行 |
| Residual semantic assist | explicit Runtime adapter boundary | 只产生 missing-slot lexical/acquisition cue；最多一次调用和一次额外 acquisition；无 canonical/completeness authority |
| Evidence interpretation/binding | `runtime/.../evidence_atoms.py` successor | 拆分 Span、InterpretationCandidate 和 RequirementBinding；禁止 requirement×number 交叉绑定 |
| Progressive retrieval | `runtime/.../retrieval.py` | 由 SufficiencyDecision 控制 stop/escalation |
| Raw Evidence FTS | `runtime/.../retrieval_repository.py` | turn/span ranking 与 structural expansion 分离 |
| Evidence composition | `runtime/.../evidence_composition.py` | 从两个 focal operator 泛化到最小 operator family |
| Resolve facade | `runtime/.../memory_resolve.py` | 返回统一 MemoryContext/Receipt |
| MCP facade | `integrations/mcp/.../server.py` | 维持单次 `milai_memory_resolve` 产品入口 |
| Window/context logic | `evals/dg15/milai_mcp_adapter.py` | 移入 Runtime；eval 仅消费 product response |

## 8.2 Historical P0 implementation rule

以下是 Q1 已执行的历史边界，用于解释现有 receipt；它不再是当前下一实现单元。

第一 change set 只允许完成：

```text
SufficiencyDecision contract
current retrieval branch integration
PARTIAL/INCOMPLETE no longer terminal COMPLETE
trace and focused tests
```

第一 change set 禁止同时加入：

```text
new embedding
new reranker
new tables
model query parser
graph
large context compiler rewrite
```

原因：必须先用 matched replay 独立测出 premature-stop correction 的 mediator effect。

Q1 matched 结果已证明 wrong-complete 减少，但 RequiredEvidenceSetCoverage 没有提高。其 2048 F1
下降又受到随机 Evidence UUID 进入 Reader prompt 的明确混杂，不能用于评价 stop-policy 的质量因果效应。
因此当前顺序是先完成 Q1R，再继续 Q3A contract rebase；不得继续扩大 Q1 stop-policy patch，也不得
用旧 Q1 F1 代表 Q2–Q4 后续实现。

## 8.3 Runtime Context Compiler

Runtime 必须接管：

```text
turn pairing
answer-bearing span preservation
neighbor expansion
window construction
window ranking
requirement-aware packing
Context rendering
provenance/receipt construction
```

Context 编译目标不是 session diversity 最大化，而是：

```text
minimum sufficient governed context
```

Reader Context 编译还必须遵守：

```text
source prose and semantically relevant metadata remain visible
answer-bearing span is preserved before surrounding window expansion
competing facts in one turn retain explicit role/time/binding annotations
random UUID/hash/trace identity is replaced by stable local aliases
true identifiers remain outside prose in ContextReceipt
same semantic input and budget produce deterministic selected order and bytes
```

禁止为“保留 provenance”把完整 UUID 列表直接塞入 Provider prompt。provenance 的权威载体是
structured receipt/resource link，不是高熵自然语言 token。

## 8.4 vLLM Residual Acquisition ownership

Q3C 已经冻结：当模型可以建议 route/operator 时，minimal hint 在 25 个 declared-supported
fixture 上只正确 `17/25`，且 wrong promotion=`7`。因此 successor 不允许模型重新规划
query，只允许它针对已存在的 missing slot 补充有界 search cue。

Runtime 内的 model boundary 只能是一个显式 application/adapters 边界，不得进入 canonical
transaction，不得放入 eval adapter，也不得由 OpenWorker 维护另一套读取逻辑。

逻辑合同：

```text
deterministic MemoryQueryIR
→ deterministic AcquisitionPlan
→ execute all authorized deterministic probes in parallel
→ deterministic Interpretation / Binding
→ required slots still missing
→ zero or one ResidualLexicalHint call
→ strict schema / scope / named-entity / alias-count validation
→ zero or one additional acquisition pass
→ deterministic Interpretation / Binding / Sufficiency again
```

Residual input 只允许：

```text
query
reference-time identity
missing requirement identities
deterministic predicate/entity cues already known
bounded capability/action enum
budgets
```

第一版不把 candidate Evidence body 给模型，以防止它隐式选择 Evidence 或生成答案。只有
A8 shadow 证明 lexical cue 不足，才能通过独立 ADR 评估 bounded candidate preview。

默认上限：

```text
auxiliary model calls <= 1 per logical resolve
extra acquisition passes <= 1
aliases per category <= configured cap
automatic retry = 0
```

不允许输出：

```text
route or operator
Evidence/Claim ID
final answer
SufficiencyDecision.COMPLETE
canonical applicability/currentness
scope, authority or permission decision
direct RequirementBinding acceptance
canonical proposal/review/commit
```

所有 model aliases 必须通过 schema、capability、named-entity set、scope 和 alias budget 校验。无效
输出被忽略时，产品行为必须与 deterministic-only 等价；不得 silent widening，不得自动重试。

## 8.5 语义提示复用

只允许复用与 Memory truth 无关的 deterministic parse 和经验证 residual cue，不允许复用最终
StateView、Evidence binding 或 SufficiencyDecision。

可选 cache key 必须包含：

```text
normalized query digest
Residual hint schema version
model identity
prompt digest
supported capability digest
```

相对时间不在 cache 内预先归一化为绝对时间；每次 resolve 必须用当轮 `reference_time`
重新计算。该 cache 只在 shadow/matched profile 证明有实际命中与收益后才可进入默认路径。

---

# 9. Work Packages

## Q0 — Terminal Finding 与 Measurement Closure

目标：不改产品语义，先使 failure localization 可信。

必须完成：

```text
freeze DG16 terminal finding receipt identity
rename Evidence Recall → AnswerSessionCoverage
label answer-bearing turns/spans/atoms for current 10 opened-dev cases
label required slots and join relations
implement RequiredEvidenceSetCoverage
implement OperatorExecutionAccuracy
implement ContextBoundaryLossRate
implement typed per-stage failure trace
```

Oracle ladder：

```text
A. Gold Evidence + Gold IR
   → Reader ceiling

B. Actual Evidence + Gold IR
   → acquisition/composition failure

C. Gold Evidence + Predicted IR
   → query compiler/operator failure

D. Actual Evidence + Predicted IR
   → end-to-end
```

禁止将 gold IR、gold atom、answer 或 scoring label 传入 product path。

## Q1 — P0 Sufficiency Correctness

目标：删除任意 Evidence 命中即 sufficient。

必须完成：

```text
SufficiencyDecision v0.1
operator-specific completion
PARTIAL != COMPLETE
INCOMPLETE composition cannot terminate as success
same-call bounded escalation
typed abstention when completion cannot be proven
full AccessTrace of attempted stages and stop reason
```

Matched run 的历史意图：使用当前 10-case frozen inputs、同一 provider、同一 reader prompt
contract、同一预算和无自动重试，对比：

```text
DG16 current stop policy
vs
DG17 query-specific stop policy
```

历史 Q1 receipt 只保留为 safety characterization。由于两个 arm 不是在同一 immutable Evidence
snapshot 上同时重放，且 Reader prompt 包含不同的随机 Evidence UUID，其 F1 delta 不再作为质量因果证据。

## Q1R — Reader Context Stability 与 Matched Causality Repair

目标：先消除无语义 prompt 漂移和不完整配对，再允许新的质量判断。

必须完成：

```text
Reader-visible stable evidence aliases
true ID → local alias lossless receipt mapping
opaque UUID/hash/trace fields absent from ordinary Reader prose
semantic_context_digest + exact reader_context_digest
one immutable Evidence snapshot shared by both policy arms
both provider arms executed in the same planned run window
same model/prompt contract/generation/budget/case order/seed
exact prompt-byte diff and allowlisted semantic mediator diff
predeclared stability probe for changed or previously-correct cases
```

Matched 语义：

```text
same prompt contract
!=
same prompt bytes
```

若两个 policy arm 选择了完全相同的 source refs、顺序、正文和 semantic annotations，则
`semantic_context_digest` 与 Reader prompt bytes 必须相同。若 policy 的预期机制确实改变了 acquired
evidence、binding、status 或 ordering，则 receipt 必须逐字段记录该 mediator；无法解释的 prompt diff
使该 cell 的 quality attribution 为：

```text
CONFOUNDED / EXCLUDED FROM CAUSAL CLAIM
```

vLLM stability diagnostic 不是 automatic retry。主结果每个 cell 仍只使用一个预先指定输出；只有发生：

```text
previously-correct regression
or
semantically equivalent Context with different answers
```

时，才对该冻结 prompt 执行预先声明的 3 次独立诊断重复，报告全部结果和 answer agreement，不得选最好
一次替换主结果。

Q1R 不新增数据库表、transport、cache、retriever、reranker 或模型路由；只修改 Runtime Context
rendering、receipt mapping 和 matched runner。真实 provenance、permission、revoke、scope 与 audit 语义
必须保持不变。

2026-08-27 的 live closure 已完成：

```text
Context archive:
var/dg17/q1r/dg17-q1r-contexts-20260827-004/contexts.json
sha256=35007cb9c653dff5e792c2e495cf8627c8d89309e18f1958821bf32527a95c1e

Matched Provider receipt:
var/dg17/q1r/dg17-q1r-matched-20260827-003/receipt.json
sha256=10a23068424379d0d42842223ce74b1ba98fe8e5a1537299a72e541f946ea2d1

Local deterministic gate:
var/dg17/local-gate/dg17-local-gate-20260827-019/receipt.json
sha256=e1909ba0115ef65bb2e6ad5dfa0b06f38c42c819883aceb06417f4e9ef780a43
```

该 closure 的固定事实为：10 个 immutable Evidence snapshots、40 个 fresh 主 Provider calls、
20/20 matched blocks 因果有效、automatic retry=`0`、historical answer reuse=`0`、普通 Reader
Context opaque UUID/hash/true provenance 泄漏=`0/40`。2048-token 的 legacy/current observed F1 为
`0.208355795/0.227338130`，EM 为 `1/10` 与 `2/10`；这是 Q1R stop-policy characterization，
不是 Q6 或发布质量结论。`9a707b82@2048` 在 speaker-aware typed binding 下不再把
assistant closing `happy cooking` 误标为 COMPLETE，但 live acquisition 未取得 session 12 的 cake
Evidence，因此安全 ABSTAIN。预声明的 3 次冻结 prompt 诊断均为 `UNKNOWN`、
agreement=`1.0`，主结果未被替换。`dg17-q1r-matched-20260827-002` 因严格 JSON
输出截断而 fail-closed，未评分、未重试、且已保留 failure receipt；后续 runner 增加了
label-free 逐调用 progress 与 failure receipt，不改变 Reader prompt/generation contract。

## Q2 — Runtime EvidenceView 与 Context Compiler

目标：移除 eval-owned product semantics。

必须完成：

```text
turn-level independent ranking
source-turn recovery
speaker-aware adjacency
query-conditioned episode/session expansion
requirement-aware packing
Runtime-owned MemoryContext
Evidence-only ContextReceipt
thin eval adapter
```

Eval adapter 必须不再实现自有 Top-3 windows、quantity signal 或 session-diversity product rule。

## Q3 — Query/Interpretation Contract Rebase 与 Generic Planning

Q3 拆分为四个有顺序的子包。禁止在 Q3A 完成前继续向 v0.1 regex/Atom ontology 追加
benchmark wording branch。

### Q3A — Contract rebase

必须完成：

```text
SemanticQueryHint v0.1
MemoryQueryIR v0.2 compositional step contract
EvidenceSpan v0.1
EvidenceInterpretationCandidate v0.1
RequirementBinding v0.1
v0.1 compatibility translator
single final planner owner
immutable Q0 atom-label receipt preserved
explicit atom-label → span/interpretation/binding measurement crosswalk
typed operator/requirement identity preserved across compatibility translation
TEMPORAL_FILTER/TARGET_EVENT never collapsed to LOOKUP/LOOKUP_ANSWER
```

必须实现的反例：

```text
one sentence contains money and count
one number could satisfy multiple semantic roles
money and count occur in adjacent turns
source time differs from event time
same source span has multiple interpretations
unsupported language/surface form does not silently become safe TOP_K lookup
one turn contains two plausible answer entities but only one satisfies role/time binding
```

### Q3B — Deterministic generic planning

第一批必须支持：

```text
LOOKUP
TEMPORAL_FILTER
TEMPORAL_ORDER
TEMPORAL_DISTANCE
COUNT_DISTINCT
DIVIDE_VALUES
MULTI_EVIDENCE_JOIN
```

要求：

```text
same operator supports unseen entity
same operator supports unseen event type where semantics permit
same operator supports Chinese and English fixtures
same operator supports paraphrased wording
no case_id / gold answer / benchmark-source branch
unsafe generic LOOKUP fallback = 0/N
AMBIGUOUS produces typed outcome, not guessed completeness policy
```

`PREFERENCE_RESOLVE` 先做 oracle/contract characterization；只有 current 10-case 的基础 operator path 稳定后才进入产品实现。

### Q3C — vLLM SemanticQueryHint shadow

在不改变产品 route 的 shadow lane 中对比：

```text
deterministic compiler
vs
minimal structured vLLM hint
```

数据至少包含：

```text
current 10 opened-dev queries
unseen English paraphrases
unseen Chinese paraphrases
multiple numbers in one span
implicit temporal comparisons
ordinary episodic lookups
unsupported/ambiguous queries
```

报告：

```text
route/operator classification
wrong promoted hint
typed ambiguity
prompt/completion tokens
queue/TTFT/decode/total latency
provider call count
full-plan vs minimal-hint output-size ablation
```

2026-08-27 修复后 live shadow 已以
`var/dg17/q3c/dg17-q3c-shadow-20260827-004/report.json`
（SHA-256 `29227f554f941d340bbefcf330b4993ef362815df446fd052e059e5a26bc9cb5`）完成：

```text
authored opened-dev fixtures                       29
minimal structured calls / full-plan controls      29 / 29
automatic retries                                  0
product route changes / full-plan consumption      0 / 0
deterministic supported-fixture correctness        25/25
minimal-hint supported-fixture correctness          17/25
wrong promoted hints                                7
schema/span rejections                              3
typed ambiguity                                     1
minimal completion tokens mean                      15.577
full-plan completion tokens mean                    191.517
full-plan/minimal token ratio                        12.295x
minimal provider p95                                265.404 ms
```

该 fixture split 明确为 `AUTHORED_DEV_NO_HELDOUT_CLAIM`。minimal hint 没有超过 deterministic
mediator，且违反 zero-wrong-promotion 条件；因此该结果只关闭 Q3C characterization，不授权产品接入。

### Q3D — one-call Semantic Repair integration

该 work package 是历史决策点。只有 Q3C 证明 minimal hint 在 unseen slice 上改善了可验证的
parser/coverage mediator，才允许进入 product path。Q3C 实际结果为 wrong promotion=`7`，
因此 Q3D 已结束为 `PARKED_NOT_NEEDED`；A8/A9 的 missing-slot residual cue 不得借用
Q3D 名义扩张权限。

调用时机：

```text
AMBIGUOUS parser
unsafe generic LOOKUP
empty/incompatible required anchors
missing slots after bounded acquisition
```

一次 logical resolve 最多一次 SemanticRepair call。模型输出必须经过 deterministic plan synthesis、
binding validation 和 SufficiencyDecision；调用失败不重试，不回退为伪 `COMPLETE`。

## Q4 — Temporal/Event Vertical Generalization

目标：修复当前 10-case 中占主导的 temporal failure slice。

必须覆盖：

```text
relative time normalization
two-event ordering
two-event distance
closed-open range construction
event identity and deduplication
bounded range completeness
source/event/system time separation
```

至少包括当前 7 个 temporal cases 的逐 case trace，但产品实现禁止 case-specific branching。

## Q5 — Multi-session Evidence Composition

目标：支持：

```text
required-slot acquisition across sessions
same-entity / same-event / same-purpose joins
count with bounded source domain
preference evidence synthesis as non-canonical EvidenceView
```

任何 preference result 如果未进入 Canonical State，只能标记：

```text
EVIDENCE_ONLY / DERIVED_VIEW
```

不能伪装为当前 canonical preference。

2026-08-27 当前源码的新鲜 product-vertical 收据为：

```text
Q4: var/dg17/q4/dg17-q4q5-product-20260827-003/report.json
sha256=e0baf2924f6dd95eebc5d16f17961186db8cf95a35b411d101aa1c15598ca524
7/7 operator expected; wrong COMPLETE=0; hidden model calls=0
deterministic p95=5.488986 ms

Q5: var/dg17/q5/dg17-q4q5-product-20260827-003/report.json
sha256=6c11309e4f7d99c4fed094a3bb24436b4763f6cae2ecdbbd4630573861123195
4/4 safety traces expected; wrong COMPLETE=0; canonical mutation=0
deterministic p95=2.588949 ms
```

Q4 使用 frozen opened-dev answer-bearing oracle Evidence 隔离 operator；Q5 同时包含 opened-dev 与
明确 synthetic 的安全边界轨迹。它们证明 Runtime deterministic mechanism/safety vertical，并作为 Q6
前置件；不单独证明 live acquisition、Reader F1 或 held-out generalization。

## Q6 — Current 10-case Matched Confirmation

前置：

```text
Q1R Context Stability and Matched Causality Gate = PASS
Q3 typed operator/requirement identity gate      = PASS
```

冻结：

```text
same 10 public-dev cases
same vLLM provider/model
same prompt/generation identity
same immutable Evidence snapshot per matched block
same 512/2048 budgets
same BM25-T baseline
automatic retry = 0
formal holdout overlap = 0
```

对比：

```text
DG16 current
BM25-T
DG17 deterministic-only
DG17 minimal SemanticQueryHint shadow
DG17 one-call ResidualLexicalHint only when A9 is authorized
```

固定 reader、prompt、Context budget、case order 和 answer seed。按 query class、case 和 stage 报告，
不允许只报告 aggregate。`same prompt/generation identity` 必须拆成：

```text
prompt contract digest
semantic Context digest
exact Reader Context digest
exact serialized prompt digest
generation contract digest
```

不得复用旧 run 的 baseline answer 与新 run 的 candidate answer组成“paired”质量表。历史 DG16 receipt
可以作为冻结 reference，但 Q6 的因果对照 arm 必须在同一计划运行窗口重新执行，并共享稳定 Context
identity policy。ResidualAssist arm 必须额外报告：

```text
auxiliary call rate
per-call prompt/completion tokens
semantic-assist latency
coverage delta after repair
quality per second
queries changed by the hint
wrong promoted hint / invalid schema / timeout
```

任何 previously-correct regression 必须输出：

```text
selected source/binding diff
semantic Context diff
exact prompt diff
provider answer diff
planned stability diagnostic, when triggered
```

若除 volatile execution identity 外没有语义差异，而输出发生翻转，只能记录为 Reader/provider
stability finding，不能归因于 retrieval/planner mechanism。

2026-08-27 首次 sealed Q6 characterization `dg17-q6-sealed-20260827-002`（receipt SHA
`f89bc33dccb10006938e2f847fc58f0484f8ec64af33550f84adaaf78db72127`）为 `PARTIAL`：2048
current EM=`2/10`、F1=`0.216000000`、RequiredEvidenceSetCoverage=`7/23`、wrong COMPLETE=`1`，
且只保留了两个 DG16 previously-correct cases 中的 `a82c026e`。该负结果是修复依据，
不得删除或追溯改写。当前小修复只针对 source-observed temporal event 的 speaker role、
generic event-term normalization 与 entity-majority binding；它不修改 DG16 Top-k/检索参数。新的
Q1R/Q3A/Q3B/Q4/Q5 前置件已封存，允许生成新 preflight 并重跑 sealed Q6。

修复后的 authoritative sealed Q6 `dg17-q6-sealed-20260827-003`（receipt SHA
`c0c98a1afc654b9e734657fd57de19abddb4268de4829320e0bb4af1aa02b4df`）仍为 `PARTIAL`。
2048 current EM=`2/10`、F1=`0.227338130`、RequiredEvidenceSetCoverage=`7/23`、
wrong COMPLETE=`0`、operator safety=`1.0`、answer-path mean=`692.505576 ms`、quality/s=`0.328283464`。
因此 Reader/Exact-Match 小 lane 已成功消除错误 COMPLETE，但 EM/F1/coverage、constrained F1
和两个 previously-correct cases 的全保留仍未过门禁。当前证据将剩余质量瓶颈定位为
acquisition/coverage，不支持继续扩大 Reader 稳定性修复。

Q8 固定控制诊断随后以当前 10 例、同一 deterministic MemoryQueryIR、TURN 原子、2048-token
Context、冻结 Reader/provider 和固定 case order 执行。首次 run
`dg17-q8-retrieval-ablation-20260827-001` 在打开标签或调用 Reader 前 fail closed：一条完整
TURN 的 dense input 为 `9754` tokens，超过 bge-m3 的 `8192` 上限；failure receipt SHA
`a8ba78fe1a640364d5034bb41faf1f5a90c0dbea127ac8236a6fd0dfa7b0f931`，不得删除。修复只增加
`BGE_M3_TOKEN_PREFIX_7680_V1` 索引投影；完整 TURN Evidence 和 Reader Context 内容不变。

authoritative Q8 `dg17-q8-retrieval-ablation-20260827-002`（receipt SHA
`ca4c5dde4bd348f7fe860165c6b7ab4136ce776757864b355e8774dd6e8326ef`）完成 60/60 fresh
Reader calls，retry/reuse/label leakage=`0`。Strong Dense 的 Q8 acquisition coverage=`18/23`
(`0.782608696`)、EM=`2/10`、F1=`0.277685951`、marginal answer path mean=`505.126364 ms`、
quality/s=`0.549735612`；Typed Composition reference 为 coverage=`8/23`、EM=`2/10`、
F1=`0.215503876`。该 acquisition coverage 使用完整 selected TURN source-ref 身份，不等同于
Q6 的 semantic binding coverage。Strong Dense 已完整取得 6/10 case 的要求 Evidence，且三个
temporal-distance case 输出正确裸数值 `21/7/24`，但冻结答案要求带 `days`，因此三例 EM 仍为 0；
两个 count case 仍合计缺 3 个 atom。Q8 因而证明 acquisition materially limiting，但同时证明
只替换 dense/reranker 不能关闭 typed composition/answer-shape 与 Q6 quality gate。任何产品 dense
接入、Q6 successor 或阈值变更均未由本诊断授权。

## Q7 — 20–50 Case Stratified Opened-dev

只有 Q0、Q1、Q1R、Q2–Q6 全部通过后启动。

分层至少包括：

```text
single-session lookup
multi-session lookup/join
temporal order
temporal distance
range count
knowledge update/state
preference
abstention
```

该阶段仍为 opened development，不消费 formal holdout，不形成 paper/generalization claim。

## Q8 — Optional Strong Retrieval Ablation

只在 Q0 oracle 证明 Candidate Recall 仍 materially limiting 后启动：

```text
turn BM25
turn BM25 + neighbor
strong dense
real reranker
hybrid
typed composition
```

固定：

```text
MemoryQueryIR
Evidence units
Context budget
reader
provider settings
case order
```

Dense/reranker 只能改变 candidate acquisition/ranking，不能替代 completeness proof。

当前 Q8 terminal characterization：

```text
TURN_BM25                  coverage=10/23  EM=0/10  F1=0.140259740
TURN_BM25_NEIGHBOR         coverage=10/23  EM=0/10  F1=0.140259740
STRONG_DENSE               coverage=18/23  EM=2/10  F1=0.277685951
REAL_RERANKER              coverage=10/23  EM=1/10  F1=0.154545455
HYBRID                     coverage=16/23  EM=1/10  F1=0.172727273
TYPED_COMPOSITION_REFERENCE coverage=8/23 EM=2/10  F1=0.215503876
```

Strong Dense 的 `89.989727 ms` 是已存在 corpus projection 时的 marginal query retrieval mean；
本次隔离实验仍记录 cold/context-build=`103046.631395 ms`、dense=`92` physical calls / `4943`
items / `86603.888916 ms`、reranker=`20` calls / `400` pairs / `7627.522760 ms`、60-call Reader
window=`23893.178630 ms`。不得把 marginal latency 当作首次建库总成本。

---

# 9A. Q8 Successor—Candidate Acquisition Repair

该 lane 是本版本唯一新授权的 behavior-changing development lane。它不改 public MCP tool set，
不修改 Canonical State 写入治理，不放松 Binding/Sufficiency，不重新打开 Q3D full-plan
SemanticRepair。

当前代码 precursor 必须复用并校正，不得再建一套 eval-only retriever：

```text
Observed:
runtime/src/milai/application/retrieval.py::_rank_evidence_turns()
  已支持 turn 独立排名，但只在 no slot_queries AND no bounded_range 时执行。

Observed:
runtime/src/milai/application/retrieval.py::_evidence_slot_queries()
  已产生 slot query precursor，但当前是无类型 tuple[str]、统一 quota，早期 dedup 丢失 probe provenance。

Observed:
runtime/migrations/versions/0036_dg15_evidence_session_retrieval.py
  当前 SQL 以 session 内 max FTS score 选 session，再回填 session turns；高分噪声 turn
  可能让一个错 session 占用 candidate limit。

Observed:
runtime/migrations/versions/0040_dg16_bounded_evidence_scan.py
  已支持 observed_at 有界扫描及 watermark proof，但尚无独立 event-occurrence index。

Observed:
runtime/migrations/versions/0033_dg15_projection_pipeline.py
  Evidence projection 已分离 lexical_text / semantic_text，可作 raw/enriched/dense 分通道的基础；
  当前未提供 Evidence-turn vector search 与 fielded role index。

Observed:
runtime/src/milai/application/retrieval.py + retrieval_repository.py
  现有 vector/reranker 主要处理 canonical ClaimVersion candidates，Raw Evidence 在 rerank 后才合并。
```

上述 Observed 不自动等于 root cause。A0 必须用 gold-after-the-fact loss ledger 确定每个
answer-bearing source 首次丢失的阶段。

## A0 — Acquisition Loss Ledger

不改产品行为。对当前 10-case immutable snapshot 和 Q8 各 acquisition arm 产生：

```text
per required slot / gold turn:
term generation
→ channel eligibility
→ per-channel rank
→ cutoff/fusion
→ expansion
→ packing
→ interpretation
→ binding
```

退出条件：

```text
10/10 cases annotated
23/23 required Evidence atoms/slots attributable
gold label read by product path = 0/N
first_loss_stage exactly one or explicit NOT_LOST
Q6 and Q8 selected-source identities replayable
```

## A1 — Turn-first Seed Retrieval

将 Raw Evidence FTS 的 primary relevance unit 改为 turn，而不是 session max-score 后全 session 回填。
Session/episode 只作为 expansion/provenance grouping boundary。

实现范围：

```text
turn-ranked repository query or equivalent bounded set-based SQL
CandidateEnvelope with original turn score/rank
scope/revoke/permission filters unchanged
no Context compiler or Reader prompt change
```

必须保留 A0、Q6 和 Q8 的 matched arm，不与 role boost、lexical enrichment、dense 或 reranker 同时上线。

## A2 — Typed Per-slot Probes 与 Provenance-preserving Fusion

实现 `AcquisitionPlanCompiler`，将每个 required slot 编译为显式 probe 和 quota。一个 global
query probe 可以保留作 recall safety net，但不能替代 slot probes。

硬性要求：

```text
every required slot has probe disposition
per-slot candidate quota before global cap
dedup retains matched_slots/matched_probes/channel_ranks
fusion policy identity and inputs are traceable
no Evidence selection from gold labels
```

RRF 是允许的首个 deterministic baseline，但不冻结为 IR 语义。

## A3 — Role-aware Fielded FTS

目标不是“从 query regex 猜一个说话人”，而是让 Query Planner 为每个
`EvidenceRequirement` 产生可选、类型化的 semantic-role 与 evidence-source 约束：

```yaml
RequirementSemantics:
  semantic_roles:
    actor: null
    experiencer: null
    beneficiary: null

  evidence_source:
    preferred_speakers: []
    allowed_speakers: null
    provenance:
      EXPLICIT_QUERY
      TYPED_HINT
      SEMANTIC_PARSER
      NONE
```

必须明确：

```text
event actor != Evidence source speaker
```

某个事件的 actor 是 USER，不代表只有 user turn 才能提供证据；assistant/tool 也可能提供合法
观察。只有 query 显式询问“谁说过/建议过/记录过”时，evidence source 才是问题语义的一部分。

Ownership：

```text
Query Planner / semantic parser
  → per-requirement semantic roles and source preference

AcquisitionPlanCompiler
  → validates and copies typed constraints

Retrieval
  → executes structured field policy; never reparses query text
```

跨语言或模糊情形可评估受约束语义解析器，包括 vLLM shadow，但 A3 本身不授权
其进入产品路径。shadow 必须满足：

```text
one typed output for all requirements; never one model call per slot
shared auxiliary-call budget with residual acquisition
model output can propose preferred_speakers, not permission or authority
hard allowed_speakers requires an explicit query/source constraint verified by Runtime
parser unavailable/ambiguous → empty preference and neutral retrieval
```

候选 Evidence 使用 ingest 时保留的结构化 `speaker` 字段。历史记录若没有该字段，则为
`UNKNOWN`；禁止在 retrieval 中通过 `content.startswith("user:")` 或其他正文解析伪造结构化
speaker。

排名不允许内联 `+0.05` 或其他未标定常数。允许的实现是：

```text
fielded retrieval channel
or a versioned/calibrated fusion feature
```

权重必须由独立 matched ablation 标定，并报告 per-class recall、noise、calibration identity 和延迟。
测试必须覆盖否定、引用、指代、复合问题、不同 slot 需要不同 source，以及中英文/混合语言；
不能只覆盖四个固定问句。

当前 working-tree 中若存在下列 prototype，必须视为 `REJECTED_DRAFT`，不得据此启动 A3 实验：

```text
business-action regex → query-global speaker
one role copied to every requirement slot
content prefix → speaker
inline constant boost such as +0.05
```

下一步先撤销或替代这组未验证语义，再运行 focused tests。该 disposition 不追溯改写已有 A0/A1/A2
artifact，也不把 working-tree code 自动升级为 `IMPLEMENTED`。

## A4 — Generic Lexical Enrichment Lane

建立独立 `FTS_ENRICHED` 通道，但 enrichment 必须是 planner-owned 的 `LexicalCueSet`，
不是 acquisition 模块内的业务动词表：

```yaml
LexicalCueSet:
  requirement_slot:
  surface_terms: []
  morphological_variants: []
  entity_aliases: []
  relation_cues: []
  language_tags: []
  provenance: []
```

确定性部分只做语言学归一和已知实体 alias，例如 tokenizer/lemma/script normalization；
不得把“某动作等于另一动作”作为无条件代码常量。语义 paraphrase 缺口优先由：

```text
multilingual dense retrieval
or bounded ResidualLexicalHint after deterministic miss
or a versioned domain lexicon with explicit provenance and independent evaluation
```

解决。语义扩展的每个 cue 必须保留 source/schema/model/lexicon version，并受 slot、entity、scope 和
cue-count budget 约束。扩展词不得拼接到 `semantic_text` 或 dense query text。

泛化验收使用分层、未见的 paraphrase/language/entity/word-order 组合，并包含“词面相似但语义不同”的
negative controls。不允许以当前 10-case 中的动词表作为泛化证据。

## A5 — Dual-axis Temporal Acquisition

将 IR temporal semantics 实际执行到两条时间轴：

```text
SOURCE_OBSERVED_TIME    何时说过/看到过
EVENT_OCCURRENCE_TIME   事件何时发生
```

先复用现有 observed-time bounded scan。仅当 declared temporal fixtures 需要事件时间且无法由当轮
bounded candidate parsing 完成时，才新增可重建 `EventProjection`；若新增 schema，必须按
ADR/Migration/backfill/watermark/purge/rollback 套件执行。

`COUNT_DISTINCT` 必须证明时间范围、projection readiness、去重键与 bounded scan 完整；固定 Top-k
不能代替完整性证明。

## A6 — Raw Evidence Dense 与 Conditional Reranker

Q8 已是强 evidence-turn dense 的 authoritative offline diagnostic，因此 A6 不重跑“dense 是否有用”，
而是一个单因素 productization decision：

```text
hard scope/time/permission filter
→ Evidence-turn dense candidates
→ per-slot fusion
→ requirement-aware rerank on a small bounded pool only when needed
```

不得继续使用“rerank ClaimVersion 后再合并 Evidence”作为 Evidence reranker 的证据。默认限制：

```text
dense universe is pre-filtered
reranker pool <= 30
exact/current-state route uses neither dense nor reranker
full TURN remains lossless; embedding projection may be bounded and versioned
```

产品接入需要独立 matched receipt；Q8 本身不是该 receipt。

## A7 — Slot-aware Expansion 与 Context Packing

当 seed candidate 仍缺 requirement 时，按 query/slot 执行有界结构扩展：

```text
same-turn span recovery
→ adjacent turn
→ same episode
→ same entity/temporal interval
→ cross-session required-slot join only when IR requires it
```

Context packing 优先覆盖 required slots，而不是无条件优先 session diversity。已进入 candidate set 的
gold answer-bearing source 不得因 packing bug 丢失；该指标为 `0/N` 硬门禁。

## A8 — `ResidualLexicalHint v0.1` Shadow

只在 deterministic acquisition 完成后仍有 missing slots 的 query 上调用 operator-owned vLLM。
Shadow 结果不改变产品 candidate、binding、answer 或 trace terminal status。

报告：

```text
schema validity
alias provenance and validation
gold-turn rank delta
RequiredSlotCandidateRecall delta
new false-candidate count
wrong-scope/entity candidates
binding delta
wrong COMPLETE
provider/token/latency
```

## A9 — One-call Live Residual Acquisition

只有 A8 同时满足以下条件时启动：

```text
wrong COMPLETE / wrong scope / authority expansion = 0/N
at least 2 missing-slot cases improve gold source rank or binding readiness
already-correct 2/2 cases do not regress
invalid hint behavior is equivalent to deterministic-only
```

实时路径仍只允许：

```text
model calls <= 1
extra acquisition passes <= 1
automatic retry = 0
deterministic Binding/Sufficiency after the extra pass
```

不满足门禁则以 `PARKED_NOT_NEEDED` 结束，不得为完成架构强行开启。

## A10 — Matched Q6 Successor Confirmation

固定当前 10-case immutable snapshot、Reader/provider/prompt/budget/case order，每次只对比一个已授权机制。
必须同时报告 mediator 和 final answer：

```text
GoldTurnCandidateRecall
AnswerBearingTurnRecall
RequiredSlotCandidateRecall
BindingCoverage
RequiredEvidenceSetCoverage
OperatorReadyRate
CandidateNoise
AcquisitionLatency
EM / F1 / answer-shape errors
```

Reader 修正只允许处理 Q8 已确证的有限 answer-shape contract（例如 temporal distance 的 unit rendering），
不得与 acquisition mechanism 同一 matched cell 同时改动。

## A11 — Stratified Opened-dev

只有 A10 通过 acquisition successor gate 且 current 10-case final quality gate 通过后，才解锁 Q7 的
20–50 case 分层评估。禁止在同一 10-case 上无限添加 synonym/operator 后直接形成 generalization
claim。

---

# 10. Claim 与实验地图

本 Goal 是产品开发 Goal，不预设论文 novelty。实验只验证机制和产品行为。

| Claim | Minimum convincing evidence | Blocks |
| --- | --- | --- |
| C1：query-specific sufficiency 修复 premature stop，且不把安全性改善误写成 acquisition/quality 改善 | wrong COMPLETE=`0/N`；typed abstention；matched stop trace；不要求 Q1 单独提高 coverage | Q0, Q1, Q1R, Q6 |
| C2：typed temporal/composition 与有效 RequirementBinding 可以在有界成本下提高 evidence-set completion，并解决 flat Top-k 无法完成的 query | unseen wording/entity tests；operator accuracy；binding precision；coverage mediator；bounded scan/join proof | Q3, Q4, Q5, Q6, A5, A7, A10, A11 |
| C3：只在 deterministic acquisition 后仍缺 slot 时启用 minimal residual lexical cue，可在不扩大模型 authority 的前提下提高 coverage | A8 shadow；A9 deterministic vs residual matched ablation；coverage/rank/binding delta；wrong COMPLETE=`0/N`；quality-per-second | A8, A9, A10 |
| C4：IR 编译为 per-slot AcquisitionPlan，turn-first 排名和 query-conditioned expansion 可以修复当前 acquisition starvation | 23/23 first-loss ledger；per-channel/slot rank；turn/session cutoff ablation；RequiredSlotCandidateRecall；packing loss=`0/N` | A0–A7, A10 |
| Anti-claim：质量变化来自动态 UUID、Reader prompt 漂移或 provider 单次翻转，而不是目标机制 | stable Reader aliases；same-snapshot paired replay；semantic/exact prompt digest；planned stability diagnostic | Q1R, Q6 |
| Anti-claim：提升仅来自更大 Context 或 Reader prompt | fixed provider/prompt/budget；Gold Evidence/IR oracle；无非预期 prompt change matched run | Q0, Q1R, Q6 |
| Anti-claim：提升仅来自 dense/reranker | Q8 已证明 dense coverage 改善但未关闭 quality gate；A1–A7 单因素 mediator | Q6, Q8, A0–A10 |
| Anti-claim：提升来自 benchmark adapter | Runtime-owned Context Compiler；thin eval adapter；MCP E2E | Q2, Q6 |
| Anti-claim：vLLM 收益仅来自让模型直接回答或生成完整 plan | model output 禁止 final answer/route/operator/Evidence selection；Q3C negative control；A8/A9 deterministic revalidation | Q3C, A8, A9, A10 |

当前仅允许结论：

```text
PRODUCT MECHANISM CANDIDATE
OPENED-DEV CHARACTERIZATION
```

禁止：

```text
novelty claim
paper superiority claim
formal benchmark claim
production claim
```

---

# 11. Quality、Correctness 与 Cost Gates

## 11.1 Measurement Gate

```text
AnswerSessionCoverage correctly named                 PASS
AnswerBearingTurnRecall available                     PASS
AnswerBearingAtomRecall available                     PASS (legacy Q0 metric)
Atom→Span/Interpretation/Binding crosswalk             required before Q6
AnswerBearingSpanRecall available                     required before Q6
RequirementBindingPrecision available                 required before Q6
RequiredEvidenceSetCoverage available                 PASS
required-slot labels complete for 10/10 dev cases     PASS
Oracle A–D runnable                                    PASS
label product-path leakage                            0/N
```

## 11.2 P0 Sufficiency Gate

```text
completeness-required query stopped by any-hit only       0/N
PARTIAL composition accepted as COMPLETE                  0/N
UNBOUNDED count returned as complete scalar               0/N
missing required slot hidden from outcome                 0/N
terminal stop without typed reason                        0/N
same-call escalation when budget/availability permit      100%
```

## 11.3 Reader Context Stability 与 Matched Causality Gate

```text
opaque volatile ID in ordinary Reader prose                 0/N
true provenance IDs retained in structured receipt          100%
stable alias mapping round-trip                              100%
same semantic Context after re-ingest → same semantic digest 100%
same semantic Context → same Reader-visible bytes            100%
exact serialized prompt digest recorded                      100%
unexplained prompt diff in causal cells                       0/N
historical-answer reuse as a newly paired arm                 0/N
previously-correct regression without case-level diff artifact 0/N
best-of stability repeats used as primary result              0/N
```

对输出敏感性诊断：

```text
planned repeats per triggered frozen prompt = 3
automatic retry                          = 0
all answers and agreement rate reported  = 100%
```

如果本 Gate 未通过，retrieval/stop/semantic-assist 的 final F1 delta 只能标记：

```text
CHARACTERIZED_WITH_MEASUREMENT_CONFOUND
```

## 11.4 Functional Gate

对于声明支持的 operator fixtures：

```text
QueryIR schema validity                    100%
required-slot construction accuracy        100%
deterministic operator execution accuracy  100%
source provenance completeness             100%
unseen paraphrase/product branch leakage   0/N
unsafe generic LOOKUP promotion             0/N
typed operator → generic LOOKUP slot collapse 0/N
TEMPORAL_FILTER TARGET_EVENT binding accuracy 100% on declared fixtures
EvidenceSpan exact-source verification      100%
wrong quantity/role cross-binding           0/N
source time accepted as event time without proof 0/N
business-action regex used as speaker semantics   0/N
query-global speaker copied to all slots          0/N
body-prefix speaker inference in acquisition      0/N
unversioned inline ranking boost                  0/N
actor/source-speaker conflation                   0/N
```

对未支持或 ambiguous query：

```text
typed PARTIAL / AMBIGUOUS / ABSTAINED
```

不得猜测 operator 或生成 unsupported scalar。

## 11.5 Semantic Assist Gates

Q3C 历史 shadow 已经因 wrong route/operator promotion=`7`而阻断 Q3D；该结论不得被
successor 追溯改写。A8/A9 使用权限更小的 residual gate：

```text
full-plan vLLM generation in product path          0/N
model-generated route/operator                      0/N
model-selected Evidence/Claim ID                    0/N
model-generated final answer                        0/N
model-declared COMPLETE accepted directly           0/N
model authority/currentness decision accepted       0/N
scope/permission/temporal-range widening             0/N
alias for a non-existing missing_slot accepted       0/N
new named entity outside validated query/entity set  0/N
auxiliary calls on exact/safe deterministic path     0/N
auxiliary calls per logical resolve                  <= 1
extra acquisition passes                             <= 1
automatic retry                                      0/N
invalid schema or timeout with silent fallback       0/N
invalid hint behavior != deterministic-only          0/N
```

`ResidualLexicalHint.confidence` 只用于 trace，不允许用 confidence threshold 绕过实体、scope、
Binding 或 Sufficiency 验证。本 Gate 优先保证 cue precision，不以强迫所有 query 进入
模型路径提高 recall。

## 11.5A Acquisition Successor Development Gate

该门禁用于 A1–A9 单因素机制进入 A10，不替代 11.6 的最终质量门禁。当前小样本报告
必须同时给出分子/分母：

```text
Wrong COMPLETE                                      = 0/N
Wrong scope/authority                               = 0/N
current Q6 correct cases retained                   = 2/2
required Evidence atoms acquired                    >= 9/23
answer-bearing source turns acquired                >= 8/21
operator-ready cases                                >= current baseline + 2
gold source entered candidates but lost in packing  = 0/N
automatic retry                                     = 0/N
AcquisitionLossRecord coverage                      = 23/23
structured speaker provenance                        = 100% or explicit UNKNOWN
unseen paraphrase/language/entity regression          reported by stratum
```

`9/23` 和 `8/21` 只是要求新机制同时超过 Q6 typed path 和 fresh legacy mediator 的最小
development boundary，不是发布质量主张。Q8 `18/23` 是 offline strong-dense arm，不自动视为
产品 A6 PASS。

## 11.6 Current 10-case Development Gate

2048-token 主 Gate：

```text
Exact Match                         >= 5/10
normalized F1                       >= 0.50
RequiredEvidenceSetCoverage         >= 0.80
wrong COMPLETE                      = 0/N
Q6-003 EM-correct cases regression  = 0/2
Q1R Context Stability Gate            = PASS
causally valid matched cells          = 100%
```

512-token 作为 constrained-context diagnostic：

```text
normalized F1 >= DG16 512 baseline
RequiredEvidenceSetCoverage reported
ContextBoundaryLossRate reported
```

上述阈值只用于 opened-dev implementation decision，不具有统计推广含义。

## 11.7 Expanded Opened-dev Gate

在 20–50 stratified cases 上：

```text
overall F1 > matched BM25-T
supported operator RequiredEvidenceSetCoverage >= 0.75
per-class results and denominator reported
no class hidden by aggregate
three-stage failure attribution complete
formal holdout overlap = 0
```

若未通过，只能标记：

```text
CHARACTERIZED / PARTIAL
```

不能降低 gate 或删除失败 query class。

## 11.8 Online Cost Contract

### Exact State / LOOKUP

```text
logical MCP resolve calls <= 1
auxiliary LLM calls        = 0
embedding calls            = 0 when exact address exists
vector search              = 0 when exact address exists
reranker calls             = 0 when exact address exists
broad canonical scan       = 0
```

### Typed deterministic query

```text
hidden model calls              = 0
candidate cap                   enforced
Context token budget            enforced
stop immediately after COMPLETE
no full-history scan except a bounded/authorized range scan
probes for independent slots    execute concurrently when safe
hydrate full body               only after fusion/cutoff
dense universe                  scope/time filtered first
reranker candidate pool         <= 30
```

Development latency gate：

```text
basic episodic/lookup query p95       <= 150 ms
deterministic composition query p95   <= 500 ms
```

Q3C/A8/A9 的 query-time structured model 调用必须将 latency/provider/token 单列，不能混入 deterministic p95。

### Model-assisted Residual Acquisition

```text
auxiliary model calls per logical resolve <= 1
extra acquisition passes                  <= 1
automatic retry                          = 0
temperature                              = 0
thinking/reasoning output                = disabled
strict JSON schema                       = required
max completion tokens                    <= 64 for ResidualLexicalHint v0.1
candidate EvidenceSpan body in v0.1       = 0
aliases per missing slot                  bounded by plan
prompt/completion/tokenizer latency       reported separately
queue/TTFT/decode/total latency           reported separately
semantic-assist call rate                 reported
quality per second                        reported
```

基于 2026-08-27 ad-hoc probe，初始 opened-dev development gate 设为：

```text
minimal SemanticQueryHint provider p95 <= 750 ms
```

该门禁是当前设备/模型下的开发阈值，不是产品 SLA。它不包括后续 retrieval 和 reader。
ResidualAssist 只能在 matched ablation 同时满足以下条件时进入默认 residual path：

```text
RequiredEvidenceSetCoverage or operator accuracy materially improves
final F1/EM does not regress on already-correct cases
deterministic exact/basic lookup latency is unchanged
quality-per-second is reported and not worse without an explicit quality tradeoff decision
```

平均成本必须同时报告：

```text
E[query latency]
= deterministic latency
+ ResidualAssistCallRate × (ResidualAssistLatency + ExtraAcquisitionLatency)
```

continuous batching 只能作为吞吐优化，不能用 batch wall time 代替 per-request latency 报告。

## 11.9 Governance/Safety Gate

```text
WrongPrincipalAcceptance             = 0/N
WrongScopeAcceptance                 = 0/N
RevokedEvidenceAcceptance            = 0/N
DeniedEvidenceAcceptance             = 0/N
CrossCaseContamination               = 0/N
EvidenceAtomCanonicalPromotion       = 0/N without governed proposal/review
UnauthorizedAuthorityEscalation      = 0/N
LabelLeakage                         = 0/N
SilentFallback                       = 0/N
```

安全指标必须报告实际 denominator；`N=0` 不是 PASS。

---

# 12. Tests

## 12.1 Unit

```text
SemanticQueryHint strict parsing and exact cue spans
MemoryQueryIR v0.2 plan synthesis
AcquisitionPlan compilation for every required slot
CandidateEnvelope probe/slot/channel/rank preservation
turn-first ordering independent of session grouping
per-slot quota and global cap
per-requirement semantic actor vs Evidence-source separation
structured speaker propagation and UNKNOWN fallback
mixed-slot source preference and multilingual semantic constraints
raw/enriched lexical field separation
LexicalCueSet provenance and unseen paraphrase/negative controls
source-observed/event-occurrence axis selection
ResidualLexicalHint schema and alias validation
temporal normalization
EvidenceRequirement generation
EvidenceSpan exact source verification
EvidenceInterpretationCandidate extraction
RequirementBinding type/entity/unit/time/episode validation
SufficiencyDecision per operator
join/entity/unit compatibility
deduplication
Context packing
stable Reader alias rendering
ContextReceipt alias → true-ID round-trip
semantic/exact Context digest
receipt authority class
Chinese/English unseen paraphrases
multiple-number and cross-turn operand negatives
same-turn competing temporal answer entities
TEMPORAL_FILTER/TARGET_EVENT compatibility translation
```

## 12.2 Property / Invariant

```text
candidate nonempty does not imply COMPLETE
removing a required binding cannot preserve COMPLETE
adding irrelevant Evidence cannot create a missing slot
reordered candidates do not change deterministic operator result
revoked Evidence cannot re-enter through interpretation/neighbor expansion
EvidenceAtom cannot mutate ClaimHead
Top-k cannot prove ALL_MATCHES_IN_RANGE
one EvidenceSpan may have multiple interpretations without satisfying multiple slots
an unbound interpretation cannot satisfy a requirement
model hint cannot change authority/currentness/completeness
model residual cannot change route/operator/scope/time range
invalid residual is behaviorally equivalent to deterministic-only
invalid model cue offsets cannot enter plan synthesis
query action/actor cannot be reinterpreted as Evidence source speaker
missing structured speaker cannot be inferred from body prefix
role/source preference cannot become a hard filter without explicit source constraint
unversioned inline score boost cannot affect ranking
early dedup cannot erase matched slot/channel provenance
session expansion cannot replace original turn relevance score
lexical enrichment cannot mutate dense input text
relative-time parse cache cannot freeze an old absolute time
replacing Evidence UUIDs cannot change Reader-visible Context bytes
stable alias removal cannot remove structured provenance
typed operator identity cannot become a generic LOOKUP requirement
same semantic inputs and budget produce deterministic Context ordering
```

## 12.3 Integration

```text
real PostgreSQL
real migrations when applicable
Evidence capture → projection → resolve
permission/revoke/retention propagation
projection watermark gaps
Runtime Context Compiler
MCP structured response
structured-model adapter timeout/schema-invalid behavior
single-call ceiling and provider call ledger
deterministic planner after accepted SemanticQueryHint
turn-first repository query with permission/revoke/scope filters
per-slot raw/enriched/temporal/dense fusion
structured speaker field end-to-end from ingest/projection to CandidateEnvelope
planner-produced per-slot source preference without retrieval query reparsing
Raw Evidence reranking after hard filters
missing-slot residual cue → one extra acquisition → deterministic revalidation
same immutable Evidence snapshot used by both matched policy arms
Reader Context excludes opaque IDs while MCP receipt retains them
```

## 12.4 E2E

```text
ordinary MCP client without TaskIdentity
OpenWorker → MCP → MiLA → vLLM
same 10-case matched replay
deterministic-only vs one-factor acquisition variants
deterministic-only vs residual-shadow vs one-call residual ablation
new MCP process / empty OpenWorker session memory
no history replay to provider
automatic retry = 0
both causal arms receive fresh planned provider calls
exact prompt/context digest comparison
triggered three-repeat stability diagnostic kept separate from primary score
```

## 12.5 Static and contract gates

```text
ruff
strict mypy for touched packages
MCP contract tests
schema parse tests
focused Runtime tests
full relevant regression suite
```

---

# 13. 开发与调试原则

## 13.1 减少防御性编程

本 Goal 明确要求：

```text
fail fast in development
validate at ownership boundaries
use typed domain outcomes
keep one primary implementation path
keep one Runtime owner for Reader-visible identity/rendering policy
```

禁止：

```text
broad except Exception followed by UNKNOWN
silent fallback to legacy retrieval
duplicated validation at every internal call
feature flags without a real second supported deployment
parallel old/new business semantics after matched comparison ends
extra wrapper layers that only rename existing DTOs
multiple UUID scrubber/redaction wrappers around the same Context
```

MCP 边界、数据库边界和不可信 extractor output 必须校验；同一进程内已经由 owner 构造并类型验证的对象，不重复堆叠防御检查。

## 13.2 单项失败调试

遇到失败时严格执行：

```text
stop batch
→ select one failing case/test
→ identify one failing stage
→ inspect actual IR/candidates/requirements/sufficiency/context
→ for answer regression, diff selected refs, semantic Context, exact prompt and provider output
→ fix one root cause
→ rerun focused test
→ rerun matched slice
→ resume batch only after pass
```

禁止：

```text
失败后自动大批重跑
同时修改 parser/retriever/reader/scorer
用 retry 掩盖不稳定
把 temperature=0 或相同 seed 当成 prompt stability proof
把不同 run 的历史答案拼成新的 paired causal comparison
用宽泛 logging 代替定位
```

## 13.3 并行资源

允许并鼓励并行：

```text
measurement/oracle work
AcquisitionLossRecord generation
turn-first repository implementation
AcquisitionPlan/compiler and contract tests
role/enrichment counterfactual test authoring
temporal parser/operator and projection prototype
dense/reranker offline candidate preparation
independent test authoring
CPU extraction and database fixture preparation
independent case evaluation
```

并行约束：

```text
same case namespace remains isolated
ordered evidence identity remains deterministic
same operator write chain preserves required ordering
independent read-only per-slot probes execute concurrently under one plan budget
provider concurrency starts at 1 and increases only after stable profile
MCP/DB concurrency starts at 4 and is increased by measurement
```

可使用可用 subagent 分块开发、测试和独立审阅，但每个 subtask 必须有单一 owner、互不覆盖的文件范围和明确返回证据。

## 13.4 vLLM Provider

Provider 固定为当前 operator-owned 服务：

```text
endpoint: http://127.0.0.1:7860
model: Qwen3.6-35B-A3B-FP8
```

要求：

```text
do not restart/reconfigure/replace existing vLLM without owner authorization
freeze model/prompt/generation/seed identity in receipts
record semantic Context, exact Reader Context and serialized prompt digests separately
do not expose run-random UUIDs merely to preserve provenance
automatic retry = 0
separate tokenizer and generation latency
record every provider call
```

Reader 只在 MemoryContext 编译后调用。Q3C `SemanticQueryHint` 是已关闭的历史 shadow lane；
Q3D 保持 parked。A8 只允许 `ResidualLexicalHint v0.1` shadow，A9 通过 residual gate 后才
允许针对已存在 missing slot 进行最多一次 query-time residual call。

调用合同固定：

```text
response_format = strict JSON schema
temperature = 0
top_p = 1
thinking = false
include_reasoning = false
stream = false
max_tokens <= 64 for ResidualLexicalHint v0.1
automatic retry = 0
```

优先缩小 structured output，不让 vLLM 生成 retrieval plan、Evidence selection 或 final answer。
当前服务的 continuous batching
可用于并发 shadow/eval 吞吐；任何 prefix caching、speculative decoding、模型替换、量化变更或调度
参数调整都不属于本 Goal 默认授权，必须先有匹配 profile 和 owner authorization。

provider concurrency 使用：

```text
single-call correctness first
→ concurrency 4 shadow profile
→ only increase when queue/TTFT/decode and GPU utilization justify it
```

并发不得增加 logical attempt、retry 或隐藏 Provider call denominator。

`temperature=0`、相同 seed 和相同 prompt template 不证明输出比较已经配对；完整 Reader prompt bytes
仍必须受控。stability diagnostic 是预先声明的独立实验，不得在单次失败后临时重试，也不得采用
best-of-N 结果。

## 13.5 审查最小化

开发阶段不进行重复大审计。每个 work package 使用：

```text
focused tests
matched receipts
code review on changed ownership boundary
```

只有全部 release gates 已通过、准备签发 scoped label 时，才进行一次独立 release-boundary review。

如用户授权使用 `gpt-5.6-sol` / `reasoning_effort=xhigh`，可参考：

```text
/cra/memory/mx_memory/MiLAi/codex_sol_xhigh.md
```

但该文件当前文字范围属于 DG-10 candidate.4。DG-17 必须建立自己的 review prompt、输入 manifest 和 receipt，不得复用或篡改 DG-10 audit 状态。

独立审查只检查：

```text
P0/P1 correctness findings
gate evidence identity
product/eval ownership
security/governance regressions
release-scope wording
```

不重复执行已经有可验证 receipt 的所有实验，也不为追求“零建议”进行无限审查循环。

---

# 14. Non-goals

DG-17 不实现：

```text
production release
remote MCP deployment
real personal data
formal LongMemEval holdout
paper claim or novelty claim
full graph or Neo4j truth store
global DAG tags
autonomous reconstructive agent
new vector database
embedding fine-tuning
Reader fine-tuning
vLLM full-plan generation in the product path
vLLM call on every Memory query
model-declared evidence completeness or canonical applicability
closed business-action regex/lexicon as the production semantic planner
query-global role classification copied across requirement slots
speaker inference from rendered Evidence body prefixes
unmeasured inline ranking constants
EvidenceAtom as a persisted/public Memory ontology
automatic vLLM retry or answer inference inside SemanticRepair
complete Host TaskStateStore
learned Task identity resolver
portable offline CURRENT lease
push invalidation
automatic canonical preference commit
automatic forgetting/delete policy
DG-18 lifecycle optimization
removing structured provenance/audit identity as a Reader-stability shortcut
```

这些内容只有在 DG-17 failure evidence 证明必要后，才能进入新的 successor Goal。

---

# 15. Deliverables

必须交付：

1. DG-16 terminal finding freeze receipt；
2. answer-bearing turn/span/interpretation/binding/slot evaluation schema；
3. Oracle A–D runner 与报告；
4. `SemanticQueryHint v0.1`；
5. `MemoryQueryIR v0.2` 与 v0.1 compatibility disposition；
6. `EvidenceRequirement v0.2`；
7. `EvidenceSpan v0.1`、`EvidenceInterpretationCandidate v0.1`、`RequirementBinding v0.1`；
8. `EvidenceAtom v0.1` transition/removal disposition；
9. `SufficiencyDecision v0.1`；
10. P0 premature-stop fix 与 focused receipt；
11. Runtime `EvidenceView` / Context Compiler；
12. Evidence-only / mixed `ContextReceipt`；
13. minimal-hint shadow 与 full-plan negative-control report；
14. historical Q3C SemanticQueryHint disposition，以及 optional one-call residual adapter/call ledger；
15. temporal order/distance/range-count verticals；
16. multi-session required-slot composition；
17. thin LME eval adapter；
18. current 10-case deterministic/model-assisted matched report；
19. conditional 20–50 case stratified report；
20. optional strong retrieval ablation；
21. Runtime/MCP tests、ruff、strict mypy receipts；
22. Semantic Read operator runbook；
23. Q1 F1 regression postmortem 与 prompt-byte diff receipt；
24. stable Reader alias / ContextReceipt provenance mapping contract；
25. same-snapshot paired runner 与 stability diagnostic receipt；
26. typed temporal requirement 不坍缩为 generic lookup 的 regression receipt；
27. `AcquisitionPlan v0.1` / `CandidateEnvelope v0.1` 内部合同；
28. 23/23 `AcquisitionLossRecord` 与 first-loss taxonomy receipt；
29. turn-first repository path 与 session-first matched disposition；
30. per-slot multi-probe/quota/fusion provenance receipt；
31. per-requirement semantic-role/evidence-source contract、structured speaker lineage、
    calibrated fielded retrieval 与 multilingual/counterfactual regression receipt；
32. source-observed/event-occurrence temporal acquisition receipt；
33. Raw Evidence dense/conditional reranker productization decision receipt；
34. slot-aware expansion/packing receipt；
35. `ResidualLexicalHint v0.1` shadow 与 A9 live/park disposition；
36. A10 matched Q6 successor report；
37. single release-boundary review disposition。

若新增 projection/schema，同时交付对应 ADR、Migration、backfill/rebuild、watermark、purge 和 rollback artifacts。

---

# 16. 开发状态板

2026-08-27 当前实现/收据状态：

| Work package | Status | Current evidence / boundary |
| --- | --- | --- |
| Q0 Terminal Finding / Measurement Closure | `CHARACTERIZED / PROVISIONAL` | 三种子、120-call corrected oracle 聚合：`var/dg17/q0/dg17-q0-multiseed-20260827-001/receipt.json`；A/B/C/D F1=`0.6545/0.2000/0.5766/0.2039`；40 个 case×arm 中 6 个 answer unstable、2 个 score unstable；answer-bearing annotation 独立复核仍 `PENDING`，故不授权 Q0 measurement gate |
| Q1 P0 Sufficiency Correctness | `CHARACTERIZED` | focused wrong-COMPLETE gate `0/9`；安全 mediator 成立；2048 F1 `0.20 → 0.10` 仅由 `9a707b82` 翻转且受随机 Evidence UUID prompt drift 混杂，质量因果结论为 `INCONCLUSIVE` |
| Q1R Context Stability / Matched Causality | `TESTED / PASS` | `dg17-q1r-contexts-20260827-004`：10 snapshots/40 Contexts、opaque Reader identity=`0/40`；`dg17-q1r-matched-20260827-003`：20/20 causal blocks、40 fresh calls、retry/reuse/unexplained diff=`0`；2048 legacy/current F1=`0.208355795/0.227338130`、EM=`1/10 → 2/10`；`9a707b82` 的 3 次冻结诊断均为 `UNKNOWN`、agreement=`1.0`；Reader 失败 run 002 已 fail-closed 保留；local gate 019=`365 passed` |
| Q2 Runtime EvidenceView / Context Compiler | `IMPLEMENTED / LIVE PATH EXERCISED` | Q1R live archive 已通过 Runtime-owned Context compiler 生成 40 个 Context 与 lossless receipt mapping；Q2 的最终质量/coverage 仍由 Q4–Q6 约束，不从 Q1R 单独升级为产品质量 PASS |
| Q3A Contract rebase | `IMPLEMENTED_LOCAL / PROVISIONAL` | v0.2 compositional IR、Span/Interpretation/Binding、v0.1 translator 和单一 Runtime planner owner 已实现；`var/dg17/q3a/dg17-q3a-crosswalk-20260827-003/crosswalk.json` 在 current 10 上 operator/compat requirement identity/target-event gate=`10/10`、generic lookup collapse=`0/10`；标签独立复核仍待完成 |
| Q3B Deterministic generic planning | `IMPLEMENTED_LOCAL / DECLARED FIXTURES PASS` | `var/dg17/q3c/dg17-q3b-deterministic-fixtures-20260827-003/report.json`：29 authored opened-dev fixtures，declared-supported `25/25` route/family correct、unsafe generic lookup promotion=`0`、auxiliary model calls=`0`；该结果不宣称 held-out generalization |
| Q3C vLLM SemanticQueryHint shadow | `CHARACTERIZED / COMPLETE` | `dg17-q3c-shadow-20260827-004`：29 minimal + 29 full-plan negative-control calls、retry/product-route-change/full-plan-consumption=`0`；deterministic/minimal supported correctness=`25/25` vs `17/25`，wrong promotion=`7`、schema/span rejection=`3`、typed ambiguity=`1`；minimal p95=`265.404 ms`、completion mean=`15.577`，full/minimal token ratio=`12.295x`；opened-dev authored fixtures，无 held-out claim |
| Q3D one-call SemanticRepair integration | `PARKED_NOT_NEEDED` | Q3C 未证明独立 mediator gain 且 wrong promotion=`7`，不满足 Semantic Assist Gate；不进入产品路径，`SemanticAssist = DISABLED_OR_PARKED` |
| Q4 Temporal/Event Generalization | `TESTED / MECHANISM PASS` | `dg17-q4q5-product-20260827-003` Q4：7/7 operator expected，wrong COMPLETE/model calls/case-specific branches/canonical mutation=`0`，deterministic p95=`5.488986 ms`；oracle-required Evidence，不宣称 live acquisition/held-out quality |
| Q5 Multi-session Evidence Composition | `TESTED / MECHANISM PASS` | 同 run Q5：4/4 safety expected，wrong COMPLETE/model calls/canonical mutation=`0`，deterministic p95=`2.588949 ms`；含明确 synthetic safety traces |
| Q6 Current 10-case Matched Confirmation | `CHARACTERIZED / PARTIAL` | `dg17-q6-sealed-20260827-003`：2048 current EM=`2/10`、F1=`0.227338130`、coverage=`7/23`、wrong COMPLETE=`0`、operator safety=`1.0`、quality/s=`0.328283464`；只保留 `a82c026e`，EM/F1/coverage/constrained-F1/regression gates 均失败；receipt SHA=`c0c98a1a…b4df` |
| Q7 20–50 Stratified Opened-dev | `BLOCKED` | Q6 质量门禁未通过，禁止启动 |
| Q8 Strong Retrieval Ablation | `CHARACTERIZED / TERMINAL DIAGNOSTIC` | `dg17-q8-retrieval-ablation-20260827-002`：Strong Dense acquisition coverage=`18/23`、EM=`2/10`、F1=`0.277685951`、marginal path=`505.126364 ms`；证明 recall limiting 但未过 Q6 quality gate；失败 run 001 与成功 run 002 均保留，未修改产品检索 |
| A0 Acquisition Loss Ledger | `NOT_STARTED / AUTHORIZED` | 下一个工作单元；只产生 eval-only first-loss ledger，不改产品路径 |
| A1–A2 Acquisition precursors | `WORKING_TREE PROTOTYPE / UNVERIFIED` | 已观察到 turn-first、AcquisitionPlan 和 CandidateEnvelope precursor；未因代码存在而升级为 IMPLEMENTED/PASS，仍需聚焦测试与 matched receipt |
| A3 Role/source semantics | `REBASE_REQUIRED / TESTING_PAUSED` | 禁止 business-action regex、query-global role、body-prefix speaker 和 inline magic boost；先改为 planner-owned per-slot typed semantics + structured speaker |
| A4–A7 Acquisition Repair | `NOT_STARTED / SEQUENCED` | planner-owned lexical cues、dual-axis temporal、Raw Evidence dense/rerank、slot-aware expansion；按单因素 receipt 逐项进入 |
| A8 ResidualLexicalHint Shadow | `BLOCKED_BY_A0–A7` | 只在 deterministic missing-slot slice 上运行，不改 product result |
| A9 One-call Residual Live | `BLOCKED_BY_A8_GATE` | 最多 1 次 vLLM cue + 1 次额外 acquisition；不满足门禁则 `PARKED_NOT_NEEDED` |
| A10 Matched Q6 Successor | `BLOCKED_BY_ACQUISITION_GATE` | 同 snapshot/provider/Reader/budget；必须同时报 mediator、EM/F1 和 answer-shape |
| A11 Stratified Opened-dev | `BLOCKED_BY_A10_AND_Q6_GATE` | 通过后才解锁原 Q7；不消费 formal holdout |
| Governance/Safety Gate | `CHARACTERIZED / PARTIAL` | canonical mutation/cross-case contamination/label leakage/opaque Reader identity 的 observed accepted 均为 `0`；denied-Evidence live denominator=`0`，不允许按 PASS 处理 |
| Online Cost Gate | `CHARACTERIZED / PARTIAL` | Q6 已分账：Context production=`289206.836 ms`、Provider window=`17707.476 ms`、Q6 scoring=`9466.839 ms`、Reader calls=`40`、retrieval executions=`20`、retry=`0`；质量门禁未过，故不能单独 PASS |
| Operability Gate | `NOT_STARTED` | 无 successor E2E receipt |
| Single Release-boundary Review | `NOT_STARTED` | 只在全部 release gates 完成后运行 |

2026-08-27 Q8 修复后 deterministic local gate 023 为 `367 passed`（receipt SHA
`f9b80bbb4056889b3a3f8622f7e0a9f2b253f148f979a476b3807098228ea155`），并通过
Runtime/DG17 strict mypy 与 Ruff。该结果连同 Q1R/Q8 receipt 证明 Context-stability 与强检索
诊断 lane 已闭合，但不证明 Q6 quality、最终 LME 或 release gate 已通过。

合法状态：

```text
NOT_STARTED
IN_PROGRESS
IMPLEMENTED
TESTED
CHARACTERIZED
DEFERRED
PARKED_NOT_NEEDED
BLOCKED
FAILED
```

文档、单个正例、单个 unit test 或代码合并都不能自动升级为 PASS。

---

# 17. Release Disposition

只有 Q0、Q1、Q1R、Q2–Q6、A0–A10 的必需项、Acquisition Successor、Correctness、Quality、
Governance/Safety、Online Cost 和 Operability Gate 全部通过，才允许签发：

```text
DG17 = OPENED_DEV_SEMANTIC_READ_PLANE_VALIDATED
```

Q3C shadow characterization 是已完成的历史前置，Q3D product SemanticRepair 已固定为
`PARKED_NOT_NEEDED`。A8 residual shadow 是 successor 前置，但 A9 live residual 不是必须开启的发布前置。
如果 deterministic acquisition 已通过 A10/Q6 质量成本门禁，或 residual assist 没有提供稳定的
matched mediator 收益，A9 必须以：

```text
PARKED_NOT_NEEDED
```

结束，不得为了形成“更完整的架构”强行进入默认路径。如 A9 启用，release receipt 必须显式声明：

```text
SemanticAssist = VALIDATED_RESIDUAL_PATH
```

否则声明：

```text
SemanticAssist = DISABLED_OR_PARKED
```

如果 Q7 通过，可以附加：

```text
STRATIFIED_OPENED_DEV_CHARACTERIZED
```

该标签严格限定为：

```text
local MCP
deidentified opened-development data
implemented operator classes only
current frozen vLLM reader
Runtime CANDIDATE
Schema EXPERIMENTAL
```

它不表示：

```text
Production ready
All memory query classes solved
Canonical State quality proven by LME Raw Evidence cases
Formal benchmark superiority
Paper result
Novelty
Remote MCP ready
Real personal data ready
Schema frozen
```

如果当前 10-case gate 未通过，最终状态必须是：

```text
CHARACTERIZED / PARTIAL / FAILED
```

并保留逐 stage failure taxonomy；禁止降低阈值、删除失败 case 或以 BM25-T 绝对分数低为由宣布完成。

---

# 18. 停止条件

完成以下真实产品闭环后停止 DG-17：

```text
ordinary MCP query without required TaskIdentity
→ deterministic query frontend
→ deterministic Runtime MemoryQueryIR v0.2
→ AcquisitionPlan with explicit slot/channel/quota/budget
→ turn-first multi-channel acquisition
→ query-conditioned neighbor/episode/session expansion
→ query-specific Evidence requirements
→ EvidenceSpan acquisition and interpretation candidates
→ deterministic RequirementBinding
→ evidence-set completeness proof
→ optional one-call ResidualLexicalHint only for measured missing-slot residual
→ at most one extra acquisition pass
→ deterministic Binding/Sufficiency revalidation
→ lane-specific applicability gate
→ deterministic operator or minimal sufficient Context
→ Runtime-owned ContextReceipt
→ frozen vLLM reader
→ answer or typed abstention
```

同时满足：

- `any Evidence hit = sufficient` 已从产品路径移除；
- `MemoryQueryIR → one OR-FTS query` 已从产品路径移除；
- required slot 在 `AcquisitionPlan` 中有明确 probe/disposition；
- turn/span 是 primary relevance unit，session/episode 只是结构扩展边界；
- semantic actor/source speaker 由 planner 按 requirement 表达，acquisition 不重新解析 query；
- Evidence speaker 来自结构化 source metadata，缺失时为 UNKNOWN，不从正文前缀猜测；
- 产品路径中 business-action regex、query-global role 和 unversioned magic boost=`0/N`；
- lexical semantic cue 有 slot/provenance/version/budget，且没有 focal-case 词表分支；
- source-observed time 与 event-occurrence time 不再静默混用；
- CandidateEnvelope 保留 slot/probe/channel/rank/expansion provenance；
- A0 loss ledger 覆盖 23/23 required Evidence，且 gold label 产品路径泄漏=`0/N`；
- ordinary Reader-visible Context 中动态 Evidence UUID/hash/trace identity=`0/N`；
- 真实 Evidence/Claim/Issue provenance 在 structured receipt 中保持 `100%` 可追溯；
- same-snapshot paired runner、semantic/exact Context digest 与 prompt digest gate 通过；
- completeness-required query 的错误 COMPLETE=`0/N`；
- typed operator → generic `LOOKUP_ANSWER` requirement 坍缩=`0/N`；
- `TEMPORAL_FILTER` 的 target event/time/entity/role binding 在声明 fixtures 上通过；
- 当前 10-case 2048-token development gate 通过；
- 原两个正确 case 在无测量混杂的 matched run 中不回归；
- Eval adapter 不再拥有产品 Context 选择/编译业务；
- governance、安全、scope、revoke 和 provenance 不回归；
- 没有自动 retry、silent fallback、label leakage 或 hidden answer inference；
- Exact State、普通 LOOKUP 和已支持 deterministic operator 的 auxiliary model calls=`0/N`；
- 模型不直接生成 route/operator/执行 plan、选择 Evidence、接受 RequirementBinding、
  声明 COMPLETE 或生成 final answer；
- ResidualAssist 若启用，每次 logical resolve 最多一次模型调用和一次额外 acquisition，
  且有独立质量/延迟/调用率收据；
- `EvidenceAtom v0.1` 已有明确的 transition/removal disposition，不再混合 span、interpretation 和 final binding；
- 没有消费 formal holdout；
- DG-18 生命周期状态单独报告；
- 唯一 release-boundary review 关闭 P0/P1；
- Runtime/Schema 仍明确为 `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。

随后停止。不要在本 Goal 中继续扩展 graph、autonomous reconstruction、Reader training、formal paper experiment 或生产部署。
