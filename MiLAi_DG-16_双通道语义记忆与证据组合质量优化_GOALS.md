# MiLAi DG-16：双通道语义记忆与证据组合质量优化 Goal

> Goal ID：`DG-16`
> 文档版本：`0.1.0 READY FOR IMPLEMENTATION`
> 生效日期：`2026-08-26`（Asia/Shanghai）
> 当前状态：`SEMANTIC QUALITY REPAIR / OPENED DEVELOPMENT ONLY`
> 产品前置：`DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE`
> 效率并行 lane：`DG-15 受治理记忆流水线与投影效率优化`
> 质量基线：`DG-14 LongMemEval opened-development characterization`
> Runtime / Schema：`0.1.x CANDIDATE / 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

---

# 0. Goal 决定

DG-16 不继续扩大 Task/Need/Route 架构，也不优先替换 embedding、向量数据库或完整 Memory Engine。

DG-16 只解决 DG-14 已经隔离出的第二个独立瓶颈：

```text
请求已经到达 Memory
但系统没有找齐、组合并正确使用回答所需 Evidence
```

目标是把当前：

```text
Raw conversation
→ 1,600-byte chunks
→ 每 chunk 提升为独立 canonical Claim
→ untyped SEARCH
→ FTS + weak/unknown dense path
→ Top-3 chunks
→ reader
```

修正为：

```text
Raw Evidence Lane
        ├── turn/session identity
        ├── adjacency
        ├── time/entity/quantity projection
        └── Evidence Applicability Gate

Canonical State Lane
        └── 只有真正的长期状态候选才进入 Proposal/Review/ClaimVersion

Query-conditioned Composition Lane
        ├── typed operator
        ├── required Evidence slots
        ├── retrieve/expand/join/deduplicate
        ├── completeness validation
        └── deterministic result + provenance
```

本 Goal 的第一原则：

> 先让两个已知失败 case 在不泄露 label、不猜测答案、保留完整 provenance 的条件下正确，再抽象通用 Semantic Memory 能力。

本 Goal 禁止以更多架构对象替代纵向质量修复。

---

# 1. DG-14 正式开发结论

DG-14 的开发 verdict 冻结为：

```text
DG14 Development Verdict

QUALITY:
NON_SUPERIOR_TO_BM25_T_ON_OPENED_DEV

CURRENT RETRIEVAL FORM:
GOVERNED FLAT-CHUNK HYBRID RETRIEVAL

CANONICAL STATE UTILIZATION:
NOT MATERIALLY EXERCISED

PRIMARY QUALITY BOTTLENECK:
QUERY PLANNING
+ RETRIEVAL REPRESENTATION
+ EVIDENCE-SET COMPLETENESS
+ EVIDENCE COMPOSITION

PRIMARY COST BOTTLENECK:
GOVERNANCE AND PROJECTION APPLIED AT CHUNK GRANULARITY

SCALE-OUT DECISION:
NO-GO FOR MORE CASES UNDER THE SAME DESIGN

NEXT DECISION:
GO FOR MINIMAL SEMANTIC VERTICAL REPAIR
```

边界：

1. 当前不是纯 BM25，而是 BM25/FTS 主导、vector 补充、运行中无实际 rerank、无类型化 Evidence composition 的 governed hybrid retrieval。
2. 五个 opened-dev case 足以支持“不要继续用同一设计扩大运行”的开发资源决定，但不足以证明 Canonical State 或治理永远不能提高质量。
3. 512-token 的局部提升只能记录为待复验的 context-selection signal，不能形成质量主张。
4. DG-14 是 opened-development characterization，不是正式 benchmark、generalization 或论文结果。

## 1.1 Raw comparison

来源：

```text
var/dg14/runs/dg14-matched-001-20260826/analysis.md
var/dg14/runs/dg14-matched-001-20260826/comparison.json
var/dg14/runs/dg14-matched-001-20260826/contexts.json
```

2048-token opened-dev：

| Metric | DG14-MILAI-MCP | LME-BM25-T | Delta |
| --- | ---: | ---: | ---: |
| Exact Match | `0.60` | `0.60` | `0.00` |
| normalized F1 | `0.60` | `0.60` | `0.00` |
| Hit@K | `0.80` | `0.80` | `0.00` |
| session-level Evidence Coverage | `0.80` | `0.80` | `0.00` |
| multi-session success | `0.50` | `0.50` | `0.00` |
| query p95 | `92.29 ms` | `11.49 ms` | MiLA 约 `8.0×` |

512-token opened-dev：

| Metric | DG14-MILAI-MCP | LME-BM25-T | Interpretation |
| --- | ---: | ---: | --- |
| Exact Match | `0.20` | `0.00` | `N=5`，不能形成主张 |
| normalized F1 | `0.358` | `0.00` | 待复验 packing signal |
| session-level Coverage | `0.50` | `0.80` | MiLA 更低 |
| query p95 | `118.23 ms` | `24.25 ms` | MiLA 约 `4.9×` |

五 case、单次确定性运行没有方差估计。所有 DG-16 结果必须继续报告样本数和 paired case outcome，禁止只报告 aggregate。

---

# 2. 与其他 Goal 的关系

## 2.1 DG-12：Access Reachability 诊断

DG-12 已证明第一类失败：

```text
Memory 存在 / 可寻址
但 Task / Need / Route 没把 execution 送入正确路径
```

这属于：

```text
Memory Access Reachability
```

DG-16 不否定该结论，也不重开 frozen DG-12 candidate。

## 2.2 DG-13：MCP Memory 可用性

DG-13 已使普通 MCP client 可以在没有完整 TaskIdentity 时通过 query 进入 Memory。DG-16 复用现有：

- MCP authentication、principal、capability 和 scope；
- Evidence capture；
- Proposal/Review；
- Memory resolve；
- Canonical Gate；
- Context receipt、trace 与 typed failure。

DG-16 不建立第二套 direct-client Memory semantics。

## 2.3 DG-14：质量 failure slice

DG-14 通过 `Recall:` 前缀强制五个问题进入 `SEARCH`，临时绕过 reachability 障碍，却仍与 BM25-T 持平。因此 DG-16 接管：

```text
Candidate Recall
Evidence-Set Completeness
Evidence Composition
Reader Utilization
```

DG-14 历史 artifact 保持只读。

## 2.4 DG-15：Systems Efficiency Lane

DG-15 负责：

```text
persistent worker
event→projection applicability
watermark barrier
batch ingest
bounded MCP concurrency
DB microbatch
namespace cleanup
```

DG-16 负责：

```text
query operator
retrieval unit
temporal completeness
answer-bearing Evidence
operand join
neighbor expansion
reader utilization
```

两者可以并行，但使用独立 gate：

```text
DG-15 = same semantics, lower lifecycle cost
DG-16 = better Evidence correctness and answer quality
```

任何一条 lane 都不能用另一条 lane 的指标宣称完成。

---

# 3. 完整失败模型

Answer Success 作为条件链诊断：

```text
P(Answer Success)
= P(Access Reachable)
× P(Candidate Recalled | Reachable)
× P(Evidence Set Complete | Recalled)
× P(State/Evidence Applicable | Complete)
× P(Reader Uses Correctly | Applicable)
```

这不是五个相互独立概率的统计假设，而是 failure localization framework。

| Factor | 主要 owner | 当前状态 |
| --- | --- | --- |
| Access Reachability | Task/Need/Route + MCP query entry | DG-12/DG-13 已显著推进 |
| Candidate Recall | FTS/vector/reranker/partition | DG-14 仍存在明显 miss |
| Evidence-Set Completeness | adjacency、slot retrieval、temporal scan、join | 当前主要缺口 |
| State/Evidence Applicability | ClaimVersion/OpenIssue/Canonical Gate 或 Evidence Gate | Canonical lane 较完整，Evidence lane待明确 |
| Reader Utilization | Context selection/packing/prompt/model | 一例已隔离为 Context 不完整后的合理 abstention |

重要边界：

- Canonical Gate 可以拒绝无效 candidate，但不能召回遗漏 Evidence；
- reranker 可以改变候选顺序，但不能证明 COUNT 的全集完整性；
- reader 可以使用完整 Evidence，但不应猜测缺失 operand；
- session-level hit 不等于 answer-bearing Evidence 已进入 Context。

---

# 4. 当前真实失败证据

## 4.1 Flat chunk promotion

当前 adapter：

```text
evals/dg14/milai_mcp_adapter.py
  _CANONICAL_CHUNK_TEXT_BYTES = 1600
  _create_and_review_session_claim()
```

每个 chunk：

```text
Evidence
→ milai_proposal_create
→ reviewer milai_proposal_get
→ milai_memory_review APPROVE
→ SESSION_MEMORY_CHUNK ClaimVersion
```

这些 Claim：

- 使用按 session/chunk 构造的独立 subject/predicate；
- 没有共享 StateKey；
- 没有把相同语义状态建成 version trajectory；
- 没有把时间事件、数量 operand 或更新关系结构化；
- 最终仍作为文本候选进入 Top-k。

结论：治理施加在 physical search chunk，而不是 semantic state promotion 边界。

## 4.2 Untyped query

当前 DG-14 query：

```text
runtime_query = "Recall: " + question
```

`MemoryQueryInterpreter` 主要识别：

```text
CURRENT_STATE
HISTORY
CONFLICT
EXPLANATION
```

两个中心失败均出现：

```text
requested_intent = null
resolution_dimensions = null
sufficiency = UNTYPED_NEED_REQUIRES_FULL_PIPELINE
```

因此实际路线是：

```text
FTS
→ vector
→ candidate fusion
→ Top-3
```

不是 query-specific evidence plan。

## 4.3 Temporal constraint was not propagated

DG-14 adapter 解析 `question_at`，但当前 `milai_memory_resolve` arguments 没有传入问题中的 `March` range 或相应 `valid_at/range`。医生预约问题在整个历史中搜索，返回智能手机、鞋子和 Provence 美食片段。

## 4.4 Session coverage overstates evidence completeness

咖啡杯问题需要：

```text
TOTAL_PRICE = $60
ITEM_COUNT  = 5
UNIT_PRICE  = 60 / 5 = $12
```

当前报告按 session ID 计算 coverage：

- 命中了包含 `$60` 的 session；
- 实际选择的是该 session 的 `chunk/1`；
- `$60` 位于未进入 Context 的 `chunk/0`；
- Context 只包含另一个 session 中的 `5 mugs`。

所以当前 session-level Coverage=`1.0`，真实 RequiredOperandCoverage=`0.5`。

## 4.5 Reader abstention is correct

冻结 prompt 要求：没有相关、充分 Memory 时返回 `UNKNOWN`。在 operand 缺失时，reader abstention 是正确行为。

DG-16 禁止通过放宽 prompt、鼓励猜测或把模型先验当 Evidence 来提高 EM。

## 4.6 Retrieval configuration identity

Observed：

```text
reranker_calls = 0
vector_search_calls = 1
all five MiLA cases route = SEARCH
```

Code default 是 deterministic low-dimensional embedding 与 `reranker=none`，但 DG-14 manifest 没有绑定实际 retrieval model identity。因此：

```text
Actual DG-14 embedding identity: [UNKNOWN]
Actual reranker execution: OBSERVED 0 calls
```

DG-16 必须补齐 retrieval configuration receipt，不能把代码默认值写成已运行事实。

---

# 5. 修正后的 Memory 读取架构

## 5.1 三条 Lane

```text
                      MCP memory.resolve
                              │
                       Query Interpreter
                              │
                         Typed QuerySpec
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
          ▼                   ▼                    ▼
  Canonical State Lane  Episodic Evidence Lane  Composition Lane
          │                   │                    │
      StateView          EvidenceView       RequiredEvidenceSet
                                                   │
                                           OperatorExecution
          │                   │                    │
          └───────────────────┴────────────────────┘
                              │
                    Evidence Sufficiency
                              │
                        MemoryContext
                              │
                            Agent
```

## 5.2 Canonical State Lane

适用：

```text
CURRENT_STATE
HISTORICAL_STATE
KNOWLEDGE_UPDATE
PREFERENCE_STATE
CONFLICT
```

路径：

```text
StateKey / Claim ID
→ ClaimHead / ClaimVersion
→ valid time / system time
→ OpenIssue / GroundingBlock
→ Canonical Gate
→ StateView
```

只有这条 lane 赋予 ClaimVersion、ClaimHead、OpenIssue 和 authority 语义。

## 5.3 Episodic Evidence Lane

适用：

```text
某次发生了什么
用户说过什么
助手推荐过什么
某个时间范围有哪些事件
```

路径：

```text
EvidenceRecord / source_ref
→ turn/session/temporal/entity projection
→ candidate
→ source-turn + adjacency recovery
→ Evidence Applicability Gate
→ EvidenceView
```

Evidence Applicability Gate 至少检查：

```text
tenant
principal permission
retention readability
revocation
scope
valid/event time
source identity
provenance
```

它不移动 ClaimHead，也不提升 authority。

## 5.4 Evidence Composition Lane

适用：

```text
COUNT
SUM
DIVIDE
COMPARE
MULTI-EVIDENCE JOIN
WHY CHANGE
```

路径：

```text
Typed QuerySpec
→ required slots / bounded domain
→ per-slot retrieval
→ adjacency/session/entity expansion
→ join / deduplicate
→ completeness validation
→ deterministic operator
→ EvidenceCompositionResult
```

`EvidenceCompositionResult` 是 turn-local、query-conditioned 的派生结果，不是持久化 truth。

## 5.5 最终返回

```text
MemoryContext
= optional StateView
+ optional EvidenceView
+ optional OperatorResult
+ provenance
+ completeness/currentness status
```

不是所有问题都返回 StateView，也不是所有 Evidence 都成为 Claim。

---

# 6. 最小对象与持久化边界

DG-16 第一阶段禁止直接新增五套 authoritative table。

## 6.1 复用现有 EvidenceRecord

逻辑 `TurnEvidence` 优先由现有字段与 source metadata 构成：

```yaml
evidence_id:
session_id:
turn_ordinal:
speaker:
observed_at:
raw_content_ref:
previous_turn_ref:
next_turn_ref:
source_ref:
```

如果当前 EvidenceRecord/source_ref 足以确定恢复这些字段，不新增 authoritative turn table。

## 6.2 Projection DTO

以下对象第一阶段均为可重建 projection 或 query-time DTO：

```text
EpisodeSegment
EventCandidate
QuantityCandidate
EntityAliasCandidate
EvidenceSlot
```

只有出现以下任一事实，才允许提议持久化专用 projection：

- query-time extraction 超出冻结 latency/cost budget；
- 同一 deterministic extraction 被重复计算并成为已测热点；
- bounded exhaustive scan 需要可证明的 projection watermark；
- 20–50 case 开发集证明结构可复用；
- ADR、Migration、回填、撤销和回滚合同完整。

## 6.3 ClaimVersion promotion boundary

只有以下内容进入 Canonical State：

```text
稳定长期状态
当前偏好
项目/配置状态
经确认的事实更新
需要版本轨迹的状态
冲突与 OpenIssue
```

普通 raw turn、assistant recommendation、一次性事件或 search chunk 默认不创建 ClaimVersion。

---

# 7. 最小 QuerySpec

DG-16 不先建设完整通用 Operator Framework。第一阶段只实现支持两个 focal case 的最小 typed contract：

```yaml
QuerySpec:
  schema_version: query-spec-v0.1

  answer_type:
    SCALAR

  operator:
    TEMPORAL_COUNT_DISTINCT
    DIVIDE_EVIDENCE_VALUES

  entities: []
  predicates: []

  temporal_range:
    start: null
    end: null
    boundary: CLOSED_OPEN

  required_slots: []

  completeness:
    ALL_MATCHES_IN_RANGE
    ALL_REQUIRED_SLOTS

  evidence_policy:
    source_roles: []
    adjacency_hops: 0
    provenance_required: true
```

输出：

```yaml
EvidenceCompositionResult:
  status:
    COMPLETE
    PARTIAL
    ABSENT
    CONTESTED
    DENIED
    UNAVAILABLE

  operator:
  result:
  unit:

  operands: []
  evidence_refs: []
  source_turn_refs: []

  completeness:
    required_slots: []
    filled_slots: []
    bounded_scan_complete: false
    projection_position: null
    unresolved_reasons: []

  trace:
```

Operator result：

- 只在完整性条件满足时返回 `COMPLETE`；
- 不写 canonical state；
- 不成为未来 query 的 Evidence，除非作为独立、明确 source type 的执行 trace 被捕获；
- 必须保留每个 operand 的 source Evidence；
- 计算本身 deterministic，hidden model call=`0`。

---

# 8. Focal Vertical A：咖啡杯单价

Opened-dev case：

```text
case_id = 0100672e
question = How much did I spend on each coffee mug for my coworkers?
```

该 case 只作为开发 fixture。产品代码禁止读取 case ID、gold answer 或 scorer output。

## 8.1 Required plan

```yaml
answer_type: SCALAR
operator: DIVIDE_EVIDENCE_VALUES
entities:
  - coffee mug
required_slots:
  - TOTAL_PRICE
  - ITEM_COUNT
completeness: ALL_REQUIRED_SLOTS
```

## 8.2 Required execution

```text
TOTAL_PRICE slot retrieval
→ user Evidence containing $60

ITEM_COUNT slot retrieval
→ user Evidence containing 5 mugs

if slot missing:
  same-session source-turn recovery
  → adjacent turn expansion
  → entity-compatible cross-session join

validate:
  entity compatible
  currency/unit compatible
  both operands provenance-grounded

compute:
  60 / 5 = 12
```

## 8.3 Extraction boundary

第一实现优先使用 deterministic extraction：

- currency/number regex；
- nearby entity tokens；
- source role；
- same turn/session adjacency；
- explicit quantity role assignment。

若需要模型生成 candidate：

- 模型只能产生 `QuantityCandidate`；
- 必须通过 typed schema 和 raw-text span verification；
- 不能直接产生最终答案；
- 不能写 canonical state；
- 模型调用必须单独计量。

## 8.4 Acceptance

```text
QuerySpec.operator              = DIVIDE_EVIDENCE_VALUES
TOTAL_PRICE coverage            = 1/1
ITEM_COUNT coverage             = 1/1
RequiredEvidenceSetCoverage     = 1.0
adjacent/source-turn recovery   = exercised
entity/unit compatibility       = PASS
deterministic operator result   = $12 per mug
evidence provenance             = complete
reader answer                   = correct
hidden answer inference         = 0
label access                    = 0
```

---

# 9. Focal Vertical B：3 月医生预约计数

Opened-dev case：

```text
case_id = 00ca467f
question = How many doctor's appointments did I go to in March?
```

## 9.1 Required plan

```yaml
answer_type: SCALAR
operator: TEMPORAL_COUNT_DISTINCT
event_type: DOCTOR_APPOINTMENT
participant: USER
attendance_status: ATTENDED
temporal_range:
  start: March 1 at 00:00
  end: April 1 at 00:00
  boundary: CLOSED_OPEN
completeness: ALL_MATCHES_IN_RANGE
```

年份必须由 question timestamp、explicit query 或 scoped conversation time 确定。无法确定时返回 `PARTIAL/UNKNOWN`，不能猜测。

## 9.2 Required execution

```text
question timestamp
→ normalize March interval
→ bounded Evidence scan within case/principal/time partition
→ event candidate extraction
→ Evidence Applicability Gate
→ attendance/planned/cancelled distinction
→ event identity deduplication
→ bounded scan completeness proof
→ COUNT_DISTINCT
```

## 9.3 Completeness proof

只有以下条件同时满足才返回 count：

```text
time range resolved
source partition closed and known
all Evidence in range scanned or projection watermark covers range snapshot
event type definition applied
dedup key defined
no unresolved projection gap
no unreadable/denied Evidence whose omission could alter count
```

否则：

```text
status = PARTIAL or DENIED or UNAVAILABLE
result = absent
reason = typed completeness failure
```

## 9.4 Event identity

第一实现使用最小、可解释 dedup key，例如：

```text
normalized appointment date/time
+ provider/location when present
+ source session/turn relation
+ attended status
```

不得仅按文本相似度去重。重复提及与多个真实 appointment 必须在 fixture 中分别测试。

## 9.5 Acceptance

```text
QuerySpec.operator             = TEMPORAL_COUNT_DISTINCT
TemporalRangeParsed           = true
bounded scan                  = complete
appointment classification    = complete for required Evidence
planned/cancelled excluded    = correct
event deduplication           = deterministic
RequiredEvidenceSetCoverage   = 1.0
correct count                 = true
EvidenceTraceComplete         = true
Top-k used as completeness    = false
label access                  = 0
```

---

# 10. Evidence unit 与 Context assembly

## 10.1 Units under test

DG-16 只比较以下最小 variants：

```text
A. current 1,600-byte chunk
B. source turn/round
C. source turn + ±1 adjacency recovery
D. deterministic episode segment
```

不在 Q0–Q3 引入 autonomous episode agent。

## 10.2 Adjacency recovery

候选 turn 命中后，可以在以下有界规则下恢复邻接：

- 相同 session；
- 前后最多一个 round，默认最大 `±2 turns`；
- 保持 source order；
- 每个扩展 turn 保留独立 Evidence ID；
- expansion token/candidate cost 单独计量；
- 邻接内容仍经过 Evidence Applicability Gate。

## 10.3 Field-aware retrieval

索引和排序至少区分：

```text
user assertion
assistant response
tool observation
system metadata
```

用户个人事实 query 不应被冗长、通用 assistant advice 自动压过。字段权重必须通过单因素实验选择，不按 case 写死。

## 10.4 Context contract

Context 中必须显式区分：

```text
[CANONICAL STATE]
[RAW USER EVIDENCE]
[RAW ASSISTANT EPISODE]
[DERIVED OPERATOR RESULT]
[COMPLETENESS STATUS]
[PROVENANCE]
```

Operator result 必须携带 operand refs。Reader 不需要从无序文本中重新猜测组合，但仍可检查 Evidence。

---

# 11. 指标合同

## 11.1 粒度分离

保留但降级 session-level metric：

```text
SessionRecall
```

新增：

```text
AnswerBearingTurnRecall
AnswerBearingChunkRecall
RequiredOperandRecall
RequiredEvidenceSetCoverage
TemporalRangeCompleteness
ContextBoundaryLossRate
EvidenceJoinSuccessRate
OperatorExecutionAccuracy
ReaderUtilizationAccuracy
```

## 11.2 RequiredEvidenceSetCoverage

```text
RequiredEvidenceSetCoverage(q)
= retrieved required Evidence atoms
  / all required Evidence atoms
```

咖啡杯 case：

```text
required = {$60, 5 mugs}
current retrieved = {5 mugs}
current true coverage = 0.5
```

不能再报告为 `1.0`。

## 11.3 Count completeness

COUNT 类问题必须同时报告：

```text
temporal_range_resolved
bounded_scan_completed
projection_watermark_covered
candidate_events
accepted_events
deduplicated_events
excluded_planned
excluded_cancelled
unreadable_evidence_count
```

普通 Recall@K 不能替代 completeness。

## 11.4 Failure attribution

每个错误只能归入一个首要 terminal layer：

```text
ACCESS_UNREACHABLE
QUERY_PLAN_WRONG_OR_UNTYPED
CANDIDATE_RECALL_MISS
EVIDENCE_BOUNDARY_LOSS
REQUIRED_SLOT_MISSING
TEMPORAL_RANGE_INCOMPLETE
JOIN_OR_DEDUP_FAILURE
APPLICABILITY_REJECTED
CONTEXT_PACKING_LOSS
READER_UTILIZATION_FAILURE
CORRECT_ABSTENTION
```

## 11.5 Oracle ladder

必须运行：

```text
A. Full History → frozen Reader
B. Gold Evidence Set → frozen Reader
C. Gold QuerySpec + Actual Retrieval → frozen Reader
D. Actual QuerySpec + Actual Retrieval → frozen Reader
```

解释：

| Delta | 诊断 |
| --- | --- |
| A fails | Reader/model or task ambiguity |
| A passes, B fails | gold Evidence representation/prompt问题 |
| B passes, C fails | retrieval/composition failure |
| C passes, D fails | QuerySpec planning failure |

Oracle 输入只存在于 Evaluation Plane，不进入 Runtime、projection、Context 或 future query state。

---

# 12. Work Packages

## Q0 — 指标与 oracle diagnosis

目标：先让 metric 能看见真实失败，不改产品行为。

交付：

1. 为五个 opened-dev case建立独立 evaluation-only：
   - answer-bearing turn refs；
   - answer-bearing spans/atoms；
   - required operand slots；
   - temporal event set when applicable；
2. SessionRecall 与 EvidenceSetCoverage 分离；
3. 实现 oracle ladder A–D；
4. 导出 per-case failure attribution；
5. 补齐实际 embedding/reranker/config identity receipt。

Exit：

- 咖啡杯当前 coverage 正确识别为 `0.5`，而不是 `1.0`；
- 医生预约当前识别为 candidate miss/range completeness failure；
- 三个已正确 case 的 evidence atoms 可回放；
- labels/atoms 只存在 Evaluation Plane；
- product path label access=`0/N`。

## Q1 — 咖啡杯最小纵向修复

目标：实现 `DIVIDE_EVIDENCE_VALUES`，不先抽象通用算术框架。

交付：

1. 最小 QuerySpec detection；
2. TOTAL_PRICE/ITEM_COUNT slot retrieval；
3. source-turn 与邻接恢复；
4. deterministic quantity span validation；
5. entity/unit compatibility；
6. deterministic division；
7. EvidenceCompositionResult + Context rendering；
8. unit、integration、E2E tests。

Exit：第 8 节所有 acceptance 成立。

## Q2 — 医生预约最小纵向修复

目标：实现 bounded temporal count，不在 Top-k 上伪造完整性。

交付：

1. month/year interval normalization；
2. bounded time-partition Evidence scan；
3. appointment candidate extraction；
4. attended/planned/cancelled classification；
5. deterministic event dedup；
6. completeness proof；
7. `TEMPORAL_COUNT_DISTINCT`；
8. failure/abstention tests。

Exit：第 9 节所有 acceptance 成立。

## Q3 — 从两个实现提取最小共享合同

只有 Q1/Q2 均通过后，才允许提取：

```text
QuerySpec v0.1
EvidenceSlot
EvidenceApplicabilityResult
EvidenceCompositionResult
OperatorTrace
```

禁止此阶段扩展未被 fixture 使用的 SUM、AVERAGE、COMPARE、VERSION_DIFF 或 generic graph traversal。

Exit：

- Q1/Q2 无 case-specific production code；
- 相同 contract 表达两个 operator；
- 删除抽象后无法保持两个行为时才保留；
- public MCP schema 仅在确有 Agent consumer 时扩展。

## Q4 — Retrieval unit ablation

比较：

```text
chunk
turn
turn + neighbor
episode
```

固定：

```text
QuerySpec
retriever
reader
prompt
token budget
candidate budget
```

报告：

- answer-bearing recall；
- boundary loss；
- Evidence-set completeness；
- token cost；
- query latency；
- duplicated Evidence；
- reader accuracy。

只有重复获益且成本可接受的 unit 成为默认。

## Q5 — Strong retrieval 单因素实验

在 Q1–Q4 稳定后比较：

```text
FTS only
FTS + strong dense
FTS + real reranker
FTS + dense + reranker
```

固定：

```text
same Evidence units
same QuerySpec
same candidate cap
same Context budget
same reader
same five opened-dev cases
```

必须绑定：

```text
model ID
revision
artifact SHA-256
embedding dimensions
projection version
reranker enabled/calls
hardware/process identity
```

目标是判断强模型修复 ranking miss 的边际贡献，不让它代替 temporal/operand completeness。

## Q6 — 五 case matched confirmation

保持 DG-14：

```text
same opened-dev inputs
same frozen vLLM reader
same prompt
same seed policy
same 512/2048 token budgets
same scoring
```

新增 paired report：

```text
old DG14
new DG16
BM25-T
```

五个 case 的 correctness vector 必须逐项显示。

## Q7 — 20–50 case stratified opened-dev

只有 Q6 通过后才启动。

分层：

```text
direct episodic lookup
temporal filtering
temporal aggregation
multi-evidence arithmetic
knowledge update
current/historical state
abstention
```

在打开结果前冻结：

- split identity；
- query-class labels；
- primary/secondary metrics；
- paired comparison；
- failure taxonomy；
- significance/uncertainty报告方式；
- success/futility boundary。

仍不得消费正式 holdout。

---

# 13. 有序实施计划

```text
Q0 metrics + oracle ladder
        ↓
Q1 coffee-mug vertical
        ↓
Q2 March appointment vertical
        ↓
Q3 minimal shared contracts
        ↓
Q4 evidence-unit ablation
        ↓
Q5 strong retrieval ablation
        ↓
Q6 five-case confirmation
        ↓
Q7 stratified opened-dev expansion
```

Q1 与 Q2 在 QuerySpec v0.1 最小字段冻结后可以由隔离 owner 并行实现；共享 runtime/schema 文件必须串行合并。

禁止：

- Q0 未完成就扩大 case；
- 两个 focal case 未通过就建设通用 Operator Framework；
- 用 reranker 试验替代 Q1/Q2；
- 用 DG-15 性能改善宣称 DG-16 质量完成。

---

# 14. 开发与调试原则

## 14.1 减少防御性编程

保留 Canonical/Evidence Gate、权限、CAS、撤销和 completeness invariant；减少的是无证据的复杂保护层：

- 不新增宽泛 `except Exception`；
- 不以多层 fallback 隐藏 QuerySpec 或 slot failure；
- automatic retry 默认 `0`；
- 不为未来 operator 预建 unused abstraction；
- 不在 Runtime 重复 Evaluation Plane label validation；
- 不把 unknown 转成空结果后继续；
- 一个 typed reason 对应一个 terminal failure；
- 只为真实复现的 failure 增加处理。

## 14.2 单项失败调试

失败流程：

```text
停止批次
→ 一个 case
→ 一个 QuerySpec
→ 一个 Evidence slot / event
→ 一个 retrieval/assembly/operator stage
→ 根因修复
→ 单项测试
→ focal vertical
→ 五 case
```

禁止通过扩大 token、增加 Top-k、放宽 prompt 或人工重跑掩盖失败。

## 14.3 并行资源

- Q1/Q2 独立单测、projection build 和无共享 namespace实验可并行；
- concurrency 只改变物理调度，不增加 logical attempts；
- CPU/内存优先用于 extraction、index与 ablation；
- GPU reranker/dense 只在 Q5 使用并绑定设备；
- 不重启、不抢占、不重配 operator-owned vLLM；
- 资源不足时先缩小实验，不改变 method identity。

## 14.4 Provider

Reader 固定：

```text
http://127.0.0.1:7860
Qwen3.6-35B-A3B-FP8
temperature = 0
frozen DG-14 prompt contract
```

Q0–Q5 中无需 reader 的单项测试不调用 vLLM。Q6/Q7 使用相同 reader，禁止针对 method 更改 prompt。

## 14.5 审查最小化

- 每个 Q 不重复制作独立审计包；
- 以 tests、typed trace、metric report 和 run receipt 为开发证据；
- 只在 Q6 release boundary 做一次独立 review；
- 如需要，可使用 `/cra/memory/mx_memory/MiLAi/codex_sol_xhigh.md`；
- external reviewer 工具输出不能自动成为 PASS；
- secret、role、label-boundary 和 provenance 检查不得以“减少审计”为由删除。

---

# 15. Quality Gates

## 15.1 Q0 Measurement Gate

```text
session vs turn/chunk/atom metrics separated = true
coffee-mug current required coverage         = 0.5
doctor current temporal completeness         = false
oracle A–D results                           = complete
retrieval configuration identity             = bound or explicitly UNKNOWN
label fields in product request/context      = 0/N
```

## 15.2 Focal Vertical Gate

```text
coffee-mug DIVIDE result correct          = true
coffee-mug RequiredEvidenceSetCoverage    = 1.0
doctor TemporalRangeParsed                = true
doctor bounded scan complete              = true
doctor COUNT_DISTINCT result correct      = true
doctor RequiredEvidenceSetCoverage        = 1.0
operator provenance                       = complete
hidden answer-model calls                 = 0
```

## 15.3 Five-case Development Gate

2048-token：

- 两个原失败 case 都必须修复；
- DG-14 原三个正确 case 不得回归；
- correctness vector目标为 `5/5`；
- RequiredEvidenceSetCoverage 按 atom/slot 计算；
- MiLA 必须严格高于 DG-14/BM25-T 的 `3/5` opened-dev baseline；
- UNKNOWN 只能来自 typed insufficiency，不得来自缺失 trace；
- session-level Coverage 不作为 primary quality Gate。

`5/5` 只表示 targeted opened-dev repair complete，不是 generalization 或论文结论。

512-token：

- 作为 packing/robustness secondary metric；
- 不得通过优先保留 gold span实现；
- 报告 ContextBoundaryLossRate 和 operand retention；
- 不在 Q6 前冻结 production threshold。

## 15.4 Governance/Safety Gate

```text
WrongScopeAcceptance              = 0/N
CrossCaseContamination            = 0/N
RevokedEvidenceAcceptance         = 0/N
DeniedEvidenceAcceptance          = 0/N
RawEvidenceCanonicalPromotion     = 0/N unless governed proposal exists
UnauthorizedAuthorityEscalation   = 0/N
LabelLeakage                      = 0/N
SilentFallback                    = 0/N
UnsupportedOperatorResult         = 0/N
```

所有 N 必须非零；`0/0` 不得作为 PASS。

## 15.5 Operability Gate

- 单独运行一个 case、一个 operator、一个 slot retrieval；
- typed trace 显示 plan、slots、attempts、expansion、join、completeness和 terminal reason；
- Runtime restart 后 Evidence provenance 可恢复；
- projection unavailable 不会转成伪 complete；
- reader unavailable 不改变 Memory state；
- DG-15 worker/batch 开关不改变 DG-16 semantic output。

---

# 16. Tests

## 16.1 QuerySpec

- `how much ... each` → `DIVIDE_EVIDENCE_VALUES`；
- `how many ... in March` → `TEMPORAL_COUNT_DISTINCT`；
- ambiguous month without year → typed partial；
- ordinary lookup不误分类为 aggregate；
- compound unsupported operator → explicit abstention；
- Chinese equivalent fixtures as development extension, not Q1/Q2 blocker。

## 16.2 Evidence slots

- `$60` recognized as TOTAL_PRICE；
- `5 coffee mugs` recognized as ITEM_COUNT；
- unrelated `$60` rejected by entity incompatibility；
- range price `$10–20` not mistaken for paid total；
- assistant example numbers do not override user assertion；
- source span hash and Evidence ID match。

## 16.3 Adjacency

- answer fact in previous chunk recovered；
- cross-session expansion bounded；
- neighbor denied/revoked fails closed；
- duplicate turn not counted twice；
- token budget overflow returns partial rather than silent drop。

## 16.4 Temporal count

- March closed-open boundary；
- leap year/month/year normalization；
- attended vs planned vs cancelled；
- repeated mention of same appointment deduplicated；
- two distinct appointments on same day remain distinct when identity differs；
- watermark/gap incomplete → no count；
- denied Evidence that may affect count → no complete result。

## 16.5 Composition

- missing one divide operand → partial；
- zero denominator → typed invalid operator；
- currency/unit mismatch → contested/partial；
- all operands present → deterministic result；
- result carries all source refs；
- result cannot commit Claim。

## 16.6 E2E

```text
MCP query
→ typed QuerySpec
→ raw Evidence retrieval
→ adjacency/temporal expansion
→ Evidence Applicability Gate
→ slot/event completeness
→ deterministic operator
→ MemoryContext
→ frozen vLLM reader
→ correct answer with provenance
```

---

# 17. Non-goals

DG-16 不实现：

```text
通用 autonomous retrieval agent
完整 SUM/AVERAGE/COMPARE/VERSION_DIFF framework
Neo4j canonical graph
global DAG tags
新的 vector database
替换 answer model
训练/微调 reader/router/retriever
learned TaskIdentity resolver
全量 session 自动 canonical promotion
自动 preference/persona commit
默认 reconstructive L2
远程 MCP 产品化
Direct/HTTP transport parity
正式 holdout 或论文实验
```

DG-16 不通过以下方式获得质量提升：

- 读取 answer、answer_session_ids 或 scorer output；
- 按 case ID 写规则；
- 把正确数字写入 alias/index；
- 提高 token budget 而不计成本；
- 使用 Full History 作为 product fallback；
- 让 reader 根据常识猜缺失值；
- 取消 UNKNOWN；
- 扩大 scope；
- 绕过 Evidence/Canonical Gate；
- 把 query-time operator result提交为 canonical truth。

---

# 18. Deliverables

1. 本 Goal 文档；
2. DG-14 development verdict amendment/report；
3. answer-bearing atom/operand evaluation schema；
4. oracle ladder A–D runner；
5. `QuerySpec v0.1` 最小合同；
6. `EvidenceCompositionResult` 最小合同；
7. coffee-mug vertical implementation/tests/receipt；
8. March appointment vertical implementation/tests/receipt；
9. Evidence unit ablation report；
10. retrieval model/config identity receipt；
11. strong retrieval单因素报告；
12. five-case matched report；
13. optional 20–50 case stratified development plan/result；
14. operator/evidence composition runbook；
15. 唯一 release-boundary review disposition。

若新增 Schema：

- ADR；
- Alembic Migration；
- upgrade/downgrade 或不可逆理由；
- backfill/compatibility；
- real PostgreSQL integration；
- permission/revoke/purge；
- rollback。

---

# 19. 开发状态板

```text
[ ] Q0 指标与 oracle diagnosis
[ ] Q1 咖啡杯最小纵向修复
[ ] Q2 医生预约最小纵向修复
[ ] Q3 最小共享合同
[ ] Q4 Retrieval unit ablation
[ ] Q5 Strong retrieval 单因素实验
[ ] Q6 五 case matched confirmation
[ ] Q7 20–50 case stratified opened-dev（Q6 后条件启动）
[ ] Governance/Safety Gate
[ ] Operability Gate
[ ] 唯一 release-boundary review
```

状态词：

```text
IMPLEMENTED
TESTED
CHARACTERIZED
DEFERRED
BLOCKED
UNKNOWN
NOT FORMALLY EVALUATED
```

文档、代码或单个正例不能自动把状态升级为 PASS。

---

# 20. Release disposition

只有 Q0–Q6、Quality、Governance/Safety 和 Operability Gate 全部通过，才可标记：

```text
DG16 = OPENED_DEV_TYPED_EVIDENCE_COMPOSITION_VALIDATED
```

该标签严格限定为：

```text
local MCP
five opened-development LongMemEval cases
two implemented typed operators
current frozen vLLM reader
deidentified development data
Runtime CANDIDATE
Schema EXPERIMENTAL
```

它不表示：

```text
Production ready
General Agent Memory accuracy solved
All LongMemEval query classes supported
Formal benchmark superiority
Paper result
Novelty claim
Remote MCP ready
Real personal data ready
Schema frozen
```

Q7 通过后只能新增：

```text
STRATIFIED_OPENED_DEV_CHARACTERIZED
```

仍不能升级为 formal/generalization claim。

---

# 21. 停止条件

完成以下真实闭环后停止 DG-16：

```text
MCP query without required TaskIdentity
→ typed operator
→ answer-bearing Evidence retrieval
→ adjacency or temporal bounded expansion
→ Evidence Applicability Gate
→ Evidence-set completeness proof
→ deterministic operator
→ MemoryContext with operands/provenance
→ frozen vLLM reader
→ correct answer
```

同时满足：

- 咖啡杯与医生预约两个 focal case正确；
- 原三个 DG-14 正确 case不回归；
- 2048-token opened-dev correctness vector为 `5/5`；
- RequiredEvidenceSetCoverage 按 atom/slot 真实计算；
- label leakage、wrong scope、revoked/denied acceptance、unsupported result均为 `0/N`；
- DG-15 效率状态单独报告；
- 唯一 release-boundary review关闭 P0/P1；
- 没有消费正式 holdout；
- Runtime/Schema 仍明确为 `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。

随后停止。不要在本 Goal 中继续扩展完整 operator library、graph、autonomous reconstruction 或论文实验。
