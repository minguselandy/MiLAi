---
document_id: MILA-ML-R01
version: "0.2"
status: DESIGN_COMPLETE_AWAITING_EXECUTION_AUTHORIZATION
document_type: REPAIR_AND_REVALIDATION_GOAL
created_at: 2026-08-31T08:35:50+08:00
updated_at: 2026-08-31T09:00:08+08:00
architecture_baseline: MILA-ML-ARCH@1.0
predecessor_program: MILA-ML-CLOSURE@0.2
predecessor_terminal: PARKED_ML_CLOSURE_LONGMEMEVAL_BELOW_TARGET
selected_candidate: CANDIDATE_F
development_policy: MINIMAL_INVARIANT_KERNEL
formal_holdout_authorized: false
product_default_enable_authorized: false
execution_authority: NONE
benchmark_judge_backend: VLLM_HTTP_ONLY
leaderboard_equivalence_claimed: false
---

# MiLAi ML-R01 Projection Worker 租约、Formation 送达与 Binding 闭环修复 Goal

> 本文只定义修复与重验路径，不授权立即改代码、新建 Migration、调用模型、写入 PostgreSQL 或重跑 LongMemEval。执行前必须产生新的 superseding run-lock；不得改写已封存的 `ml-closure-20260830-001` 制品。

---

# 1. 修复结论

前置 500-case 试验的首损不是 Formation 语义效果，而是正式产品路径的处理送达失败：

```text
32-item projection batch
→ 30-second lease expires during processing
→ complete_projection_event_routed = LEASE_LOST
→ fail_projection_event on the same stale ownership = LEASE_LOST
→ persistent worker exits
→ most cases cannot build/query context
→ Candidate F formation_applied = 0
→ Binding/Reader/effect denominators lose meaning
```

因此 ML-R01 的方法命题是：

> **先用最小的 lease-aware worker 语义恢复正式路径容量，再证明 Formation 确实送达、Binding 确实发生，最后才重新评估 Candidate F。**

本 Goal 不预设 Candidate F 有效。它将两件事分开判定：

```text
Engineering repair:
  worker / projection / treatment delivery 是否恢复

Method effect:
  在 treatment 真实送达后 Candidate F 是否产生有用增益
```

即使第二项为负，第一项仍可以正常 PASS；Candidate 继续 OFF，而不是把整个修复 Goal 判为失败。

---

# 2. 前置机器事实

权威前置制品：

```text
run_id:
  ml-closure-20260830-001

lifecycle terminal:
  PARKED_ML_CLOSURE_LONGMEMEVAL_BELOW_TARGET
  digest = 552854da06d0b7fad4845fcbaa6824f2c3b1548cd1cf1d0bf9e3325596942fe2

selected method:
  CANDIDATE_F
  digest = e73a7403997bea7174c7a54cf16d92e25d7b269be9adff561176b5a709de07e0

release decision:
  KEEP_FLAG_OFF

formal holdout:
  NOT_RUN
```

500-case 已观测事实：

```text
QA terminal records                   = 500/500 per arm
Retrieval denominator                 = 470
Candidate normalized F1              = 0.013160976
Raw normalized F1                    = 0.00992
Paired delta                         = +0.003240976
95% CI                               = [-0.004, 0.011148618]

Candidate context success            = 23/500
Raw context success                  = 15/500
Candidate formation applied          = 0
Candidate Raw fallback               = 23
Candidate hydrated Evidence units    = 0
Unexpected persistent worker exits   = 5
Worker lease                         = 30 seconds
Projection batch                     = 32
CorrectCaseRegression                = 2
Wrong COMPLETE                       = 0
```

还必须保留两个不能作为正式分数的故障诊断事实：

```text
Candidate context-success subset     = 23
subset judged correct                = 8/23 = 34.8%
subset normalized F1                 = 0.2861
failed-context abstention judged OK  = 27 cases
```

23 个成功样本不是随机子集，因此 `34.8%` 和 `0.2861` 只能用于定位“链路成功时 Reader 并非完全无能”，不得代替 `500` 例全分母成绩。前置 `7.0%` Judge Accuracy 中还混入了部分失败后拒答/兜底收益。

该运行只能支持：

> 正式路径的 lease/capacity 失败压倒了质量分母；它既不支持也不否定 Candidate F 的语义效果。

## 2.1 官方参照和本轮可声称边界

LongMemEval 官方 QA 主指标是 LLM Judge Accuracy，检索指标是 Recall/NDCG；论文官方评分使用 `gpt-4o-2024-08-06`。以下数值只是论文参照，不是 ML-R01 的直接通过阈值：

| 官方设置 | 模型 / 方法 | Accuracy / Recall |
| --- | --- | ---: |
| LongMemEval-S 全历史 Direct / CoN | GPT-4o | 60.6% / 64.0% |
| LongMemEval-S 全历史 Direct / CoN | Llama 3.1 70B | 33.4% / 28.6% |
| LongMemEval-S 全历史 Direct / CoN | Llama 3.1 8B | 45.4% / 42.0% |
| LongMemEval-S 附录 Direct / CoN | Qwen2.5-7B | 12.8% / 14.4% |
| LongMemEval-M Stella Round / Session, `K=V` | Recall@5 | 58.2% / 70.6% |
| LongMemEval-M Round RAG Top-5 | GPT-4o / Llama 70B / 8B QA | 61.5% / 60.0% / 51.8% |

参考：[LongMemEval 论文](https://arxiv.org/html/2410.10813)、[官方仓库](https://github.com/xiaowu0162/LongMemEval)。

ML-R01 的正式本地评估统一使用 vLLM Judge，因而只能声称：

```text
LOCAL_VLLM_JUDGE_CHARACTERIZATION
leaderboard_equivalence_claimed = false
official_gpt4o_judge = false
```

官方数值用于判断数量级差距；不与本地 Qwen Judge 分数做统计显著性比较。独立 GPT-4o Judge 如今后需要，必须另建正式外部对比 Goal 并获得新授权，不属于 ML-R01。

权威引用：

- [`lifecycle-terminal.json`](./var/ml_closure/ml-closure-20260830-001/lifecycle-terminal.json)
- [`block-c4-results.json`](./var/ml_closure/ml-closure-20260830-001/block-c4-results.json)
- [`longmemeval-summary.json`](./var/ml_closure/ml-closure-20260830-001/longmemeval-summary.json)
- [`release-decision.json`](./var/ml_closure/ml-closure-20260830-001/release-decision.json)

---

# 3. 范围

## 3.1 In Scope

```text
projection lease lifecycle
long-running batch lease renewal or equivalent bounded ownership
nonfatal ownership-loss handling
worker continuity and idempotent recovery
watermark/dead-letter gap correctness
Candidate F product-path treatment delivery
Formation apply/fallback reason accounting
Binding numerator/denominator semantics
product-path context capacity
post-repair public LongMemEval characterization
evaluation-only official BM25-turn and flat-Contriever baselines
one frozen local vLLM Reader/Judge protocol across all benchmark arms
```

## 3.2 Out of Scope

```text
changing SemanticEpisode V02 boundary policy
tuning synonyms, Top-k, Dense configuration, ranking weights or Reader prompt
new retrieval rounds or adaptive planner
Graphiti/Zep/Hindsight/OpenViking production routes
durable Formation object approval
ADR-028 approval
default-ON release
formal holdout
model training or fine-tuning
new Canonical object or Canonical write path
```

## 3.3 不可破坏边界

仅保留五类硬边界：

```text
1. tenant / scope / permission / revocation
2. Raw Evidence preservation and lineage
3. Canonical single-writer / append-only / exact-head CAS
4. watermark gap, idempotency and stale-owner fencing
5. Binding/Sufficiency authority, Wrong COMPLETE and label isolation
```

不为普通内部函数新增 digest echo、envelope、独立 receipt 或重复 validator。

---

# 4. 研究假设与反假设

## MLR01-H1 — Product-path delivery repair

> 一个有界的 lease-aware worker 修复，可以在不改变 Canonical 和 retrieval 语义的前提下，消除过期租约导致的 worker 退出，并恢复完整的 Formation/Projection/Context 送达。

最小说服证据：

```text
induced slow-processing reproducer passes
unexpected worker exits = 0
escaped LEASE_LOST = 0
stale owner durable commits = 0
duplicate durable side effects = 0
watermark crosses unresolved gap = 0
all planned context cells terminalize
```

## MLR01-H2 — Candidate F effect after real delivery

> 只有在 Candidate F 实际应用且形成非零 Evidence/Binding 分母后，才能判定它对 public LongMemEval 的 mediator 和答案影响；答案主指标为固定本地 vLLM Judge Accuracy。

最小说服证据：

```text
formation eligible > 0
formation applied > 0
hydrated Evidence units > 0
internal sealed accepted Binding denominator > 0
internal sealed AcceptedBindingPrecision = 1.0
public AnswerSessionBindingPrecision is reported as a proxy
Wrong COMPLETE = 0
CorrectCaseRegression = 0
paired answer and mediator effects reported
Candidate-minus-Raw paired vLLM-Judge delta and CI reported
```

## Anti-hypothesis

必须排除：

```text
收益只来自把 lease_seconds 调大
收益只来自降低并发或增加 retry
失败被 Raw fallback 伪装成 treatment success
Evidence identity-integrity Boolean 被误叫为 Binding precision
空 Binding 分母被伪造为 0 或 1
结果来自事后 Top-k/prompt/scorer 调整
测试路径绕过正式 MCP/Runtime/Projection
```

---

# 5. 最小修复设计

## 5.1 Lease 语义

先用可重现用例确定耗时点，再在以下两种最小实现中选择一种：

```text
A. renew current batch/item leases before expiry
B. lease only work that can finish inside the measured bound
```

优先 A；仅当单个原子 handler 无法安全续租时选 B。禁止只把 30 秒改成一个更大常数就宣称修复。

如需数据库函数，创建新 Migration，不修改历史 Migration。最小 API 应只能：

```text
renew an existing PROCESSING lease
for the current tenant + projection + outbox_id/batch + owner
without changing attempt_count, state or watermark
```

## 5.2 Ownership loss 是并发 disposition，不是 worker crash

```text
completion returns LEASE_LOST
→ mark local item OWNERSHIP_LOST
→ do not call fail_projection_event with the same stale ownership
→ do not advance watermark
→ continue the worker loop
→ allow current owner/re-lease path to finish idempotently
```

对真正的 handler 失败仍使用现有 bounded retry/dead-letter 语义。`LEASE_LOST` 不得被当作 handler failure 再进入同一条失败回写路径。

## 5.3 Treatment delivery 必须是显式机器事实

对 Candidate F 每个 case 最少记录：

```text
formation_eligible
formation_attempted
formation_applied
formed_artifact_count
hydrated_source_count
raw_fallback_taken
fallback_reason
projection_freshness
```

`fallback_reason` 使用少量固定枚举：

```text
NOT_ELIGIBLE
FORMATION_EMPTY
PROJECTION_NOT_READY
STALE_OR_INCOMPLETE
PRODUCT_PATH_FAILURE
```

Raw fallback 是产品安全机制，但不计为 Candidate F treatment delivered。

## 5.4 Binding 指标修正

当前 context runner 的 `accepted_binding_precision` 实际计算：

```python
accepted_evidence_ids.issubset(known_evidence_ids)
```

它是 Evidence identity/lineage 完整性布尔值，不是语义 Binding precision。当前 scorer 又对所有 cell 取 `min(...)`，任一 product-path failure 都会把它压成 0。

后续必须拆成三类：

```text
1. Runtime identity integrity
   AcceptedEvidenceIdentityIntegrity
   ReaderEvidenceSubsetIntegrity

2. Internal sealed exact Binding metrics
   AcceptedBindingCorrectCount
   AcceptedBindingTotalCount
   AcceptedBindingPrecision = correct / total
   BindingEligibleRequirementCount
   ValidBoundRequirementCount
   ValidBindingRecall = valid / eligible

3. LongMemEval public proxy after label opening
   AnswerSessionBoundCount
   TotalBoundCount
   AnswerSessionBindingPrecision = answer-session-bound / total-bound
```

LongMemEval 当前只提供 `answer_session_ids`，没有 exact answer-turn/span labels。因此在 R4 中：

```text
ExactAcceptedBindingPrecision = NOT_MEASURABLE_EXACT_LABELS_UNAVAILABLE
```

不得把 session-level proxy 写成 exact Binding precision。任何 precision 在分母为 0 时必须报 `null / UNDEFINED_ZERO_DENOMINATOR`，不得填 0 或 1。

---

# 6. 修复开发原则

## 6.1 Repair iteration，不是一次失败即终止

每个 Block 采用：

```text
reproduce
→ classify one dominant mechanism
→ make one general repair
→ run the narrowest causal test
→ expand only after it passes
```

单次 protocol/implementation 失败只记入 `repair-log.jsonl`，不直接 terminalize Goal。同一机制最多连续 3 次无进展时，才需要重新定义因果假设或终结该分支。

下列情况才立即停止扩大运行：

```text
cross-tenant or permission leak
revoked Evidence becomes readable/authoritative
Canonical mutation outside governed procedure
watermark crosses an unresolved gap
duplicate non-idempotent durable side effect
benchmark label enters ingest/retrieval/context
```

## 6.2 减少防御性编程

只新增对本次因果链必需的逻辑和测试：

```text
不新建通用 lease framework
不为每个 event 生成 receipt
不复制整套 worker 状态机
不为评测专用实现 projection/retrieval
不在每个 repair edit 后跑全量 Runtime
不新增 case-ID 规则
不把传输失败隐藏成语义 abstention
```

先复用：

- [`runtime/src/milai/workers/main.py`](./runtime/src/milai/workers/main.py)
- [`runtime/src/milai/persistence/projection_repository.py`](./runtime/src/milai/persistence/projection_repository.py)
- [`evals/ml_closure/longmemeval_contexts.py`](./evals/ml_closure/longmemeval_contexts.py)
- [`evals/ml_closure/longmemeval_score.py`](./evals/ml_closure/longmemeval_score.py)

---

# 7. 五个核心 Block

## R0 — Failure Reproducer and Baseline Freeze

### 目标

用可控 slow-handler 在真实 PostgreSQL 租约路径重现：

```text
lease expires
→ completion loses ownership
→ stale failure bookkeeping also loses ownership
→ current worker exits
```

### 执行

```text
R0-01 新建隔离 PostgreSQL test database
R0-02 冻结当前 worker/batch/lease 身份
R0-03 使用短租约 + 可控 handler delay 构造确定性重现
R0-04 记录退出点、事件状态、attempt_count 和 watermark
R0-05 清理精确测试库
```

### 进入 R1 的门

```text
reproducer deterministically observes ownership loss
no Canonical mutation
no product database mutation
failure is localized to lease/completion/failure bookkeeping
```

若当前故障无法重现，先定位差异，不得盲目实现续租。

## R1 — Minimal Lease-Aware Worker Repair

### 目标

恢复 worker 连续性、幂等恢复和 watermark 正确性。

### 必须覆盖

```text
R1-01 current-owner renewal or equivalent bounded lease strategy
R1-02 nonfatal OWNERSHIP_LOST disposition
R1-03 no fail() call using already-lost ownership
R1-04 stale worker cannot mark DELIVERED or advance watermark
R1-05 re-leased work remains idempotent
R1-06 worker continues processing later events
R1-07 dead-letter gap remains blocking
```

### 测试顺序

```text
unit: ownership-loss classification
real PostgreSQL: renew/complete/fail/re-lease concurrency
worker integration: slow batch beyond original lease
existing projection/revocation focused regression
```

### PASS

```text
unexpected worker exits                 = 0
escaped LEASE_LOST                      = 0
stale-owner durable completion          = 0
duplicate durable side effects          = 0
watermark gap violations                = 0
all induced events terminal             = 1.0
```

## R2 — Formation Treatment Delivery and Capacity Gate

### 目标

证明 Candidate F 通过正式 `OpenWorker → MCP → Runtime` 路径真正应用，不再由 Raw fallback 代替。

### 执行阶梯

```text
R2-A  32-case deterministic context-only smoke
R2-B  128-case context-only capacity rehearsal
R2-C  concurrency probe: 4 vs 8 stateful processes, before scoring
```

case 按 `sha256(question_id)` 与 history-size strata 确定性选取，不使用 answer 或 answer-session label。

### R2 PASS

```text
planned context terminals               = 100%
DG14TransportError                      = 0
DG14ReadinessError                      = 0
unexpected persistent worker exit       = 0
formation eligible denominator          > 0
formation applied                       > 0
formed artifact count                   > 0
hydrated Evidence units                 > 0
candidate successes due only to fallback = false
authority/scope/revocation violations   = 0
```

R2 不评分答案正确性，也不调 retrieval/Reader。

## R3 — Binding Semantics and Correctness Closure

### 目标

在 treatment-delivered 候选上确认丢失位置，并修正 Binding 指标语义。

### 执行

```text
R3-01 split boundary-health Boolean from aggregate precision/recall
R3-02 record exact accepted/eligible numerators and denominators
R3-03 classify first loss as hydration / interpretation / binding / sufficiency
R3-04 repair only the first general semantic-contract defect, if one exists
R3-05 rerun focused repair-dev cases
R3-06 run one sealed non-holdout effect after repair is frozen
```

允许修复：

```text
generic span grounding
role/type mapping
event/source-time distinction
duplicate binding identity
zero-denominator scorer semantics
```

禁止修复：

```text
case-specific answer rules
gold-aware candidate acceptance
lowering Binding validation
marking incomplete cases COMPLETE
increasing Top-k or context budget to hide the defect
```

### R3 PASS

```text
AcceptedEvidenceIdentityIntegrity       = 1.0
ReaderEvidenceSubsetIntegrity           = 1.0
internal AcceptedBindingTotalCount      > 0
internal AcceptedBindingPrecision       = 1.0
internal ValidBindingRecall reported with denominator
LongMemEval session-level proxy contract frozen
Wrong COMPLETE                          = 0
CorrectCaseRegression                   = 0
ReaderGroundingViolation                = 0
```

## R4 — One Post-Repair Four-Arm LongMemEval Characterization

### 入口

```text
R1 PASS
R2 PASS
R3 PASS
flag-OFF identity PASS
ImplementationRollback PASS
all temporary databases from prior stages cleaned
```

### 重要定位

LongMemEval 500-case 公开数据已在前置运行后打开 label。因此 R4 是：

```text
POST_REPAIR_PUBLIC_BENCHMARK_CHARACTERIZATION
```

它不是 independent holdout，不得宣称新的独立泛化证据或 leaderboard equivalence。但 ingest、Formation、retrieval 和 Context 仍必须 label-free，answer/judge 继续分窗口执行。

### 四臂设计

```text
MLR01-BM25-T  preregistered official-style BM25 turn baseline
MLR01-DENSE   preregistered flat-Contriever baseline
MLR01-R       Raw + Canonical Simple product arm
MLR01-F       Candidate F + Raw fallback product arm
```

`MLR01-BM25-T` 和 `MLR01-DENSE` 必须复用已预注册配置
[`longmemeval-baselines.json`](./var/dg11/paper/method-configs/longmemeval-baselines.json)：

```text
BM25:
  rank-bm25==0.2.2
  k1=1.5, b=0.75, epsilon=0.25
  literal-space split
  top_k=3

Dense:
  facebook/contriever
  snapshot=2bd46a25019aeea091fd42d1f0fd4801675cf699
  attention-mask mean pooling
  unnormalized dot product
  top_k=3

Packing:
  rank top-k
  chronological render
  exact-tokenizer prefix truncation
```

基线检索必须直接使用冻结的 LongMemEval 官方仓库
`src/retrieval/run_retrieval.py` 语义。项目 wrapper 只可负责输入/输出转换、checkpoint 和并发分片；若不能直接调用，必须用小型固定 fixture 证明 ranking 与官方实现完全一致，不得使用评估层自建的简化 BM25/Dense。

四臂共享：

```text
same 500 cases and question order
same answer Reader/model/prompt/decoding
same local vLLM Judge/prompt/decoding
same memory_token_budget = 512
same answer/judge timeout and concurrency ceilings
one logical attempt per case/arm
```

`512` 是预注册 baseline 的 controlled memory budget。因此新四臂必须全部使用 `512`，不得把前置 `1024`-token 结果直接并入新统计。

产品两臂 `MLR01-R/F` 额外共享：

```text
same official OpenWorker/MCP/Runtime path
same repaired worker implementation
same product max_results/action ceilings
same stateful concurrency
```

BM25/Dense 是 evaluation baseline，不假装拥有 MiLA 的 Governance/Canonical 合同。它们可与产品臂比较 retrieval 和 QA，但不参与 Candidate 的 Canonical safety 声称。

### vLLM Reader/Judge 合同

R4 按 LongMemEval 方法执行，只替换 Judge 的服务后端和模型：

```text
Official LongMemEval retained:
  longmemeval_s_cleaned 500-case denominator and order
  question type and reference-answer semantics
  answer generation contract
  answer seal before judge/label scoring
  exact upstream evaluate_qa.py get_anscheck_prompt body
  official yes/no judgment parsing semantics
  retrieval Recall@K / NDCG@K family

Intentional replacement:
  OpenAI GPT-4o judge
    → local vLLM OpenAI-compatible endpoint
    → Qwen3.6-35B-A3B-FP8
```

不得用自定义 judge prompt、自定义规则 scorer 或 F1 替代 LongMemEval Judge Accuracy。R4 不调用 GPT-4o 或任何外部 Judge。新 run-lock 在任何 500-case 调用前必须 probe 并冻结：

```text
backend                         = VLLM_HTTP
base_url                        = loopback endpoint from capability probe
intended model                  = Qwen3.6-35B-A3B-FP8
served model identity/revision  = exact /v1/models response identity
tokenizer identity              = exact digest
answer prompt digest            = frozen
judge prompt                    = upstream LongMemEval get_anscheck prompt
judge temperature              = 0
answer/judge concurrency        = 8 / 8
answer_and_judge_overlap        = false
leaderboard_equivalence_claimed = false
```

若指定 vLLM 模型或 endpoint 不可用，R4 记为 `PARKED_VLLM_JUDGE_UNAVAILABLE`；不得静默替换模型、调用外部 Judge 或把 lexical scorer 伪装成 Judge。

答案主指标：

```text
VLLMJudgeAccuracy@500
paired Candidate-minus-Raw JudgeAccuracy delta
paired 95% bootstrap CI
```

EM 和 normalized F1 是次要、可重算指标。检索指标保留 Recall@K/NDCG/MRR。同一 Qwen 模型生成与评判的 self-judge bias 必须披露。

### 运行顺序

```text
R4-01 freeze a new superseding run-lock
R4-02 probe BM25/Dense/vLLM capabilities and seal exact identities
R4-03 run all 2000 context cells first: 500 cases × 4 arms
R4-04 require 500/500 valid context executions in every arm;
      also verify product delivery/capacity/binding gates
R4-05 run 2000 answer calls only if R4-04 passes
R4-06 seal all answers
R4-07 run 2000 vLLM judge calls in a separate service window
R4-08 aggregate paired effects, retrieval, first loss and cost
R4-09 emit engineering, Candidate and baseline dispositions separately
```

若 R4-04 未过，不消耗 answer/judge 调用。产品臂失败返回 R1–R3 的对应 repair loop；基线臂失败则先修复基线 adapter/capacity。两者都不得直接生成方法负效果结论。

### 归因边界

```text
Primary causal product comparison:
  MLR01-F vs MLR01-R

Contextual local system comparisons:
  MLR01-R/F vs MLR01-BM25-T/DENSE

Literature-only reference:
  official paper numbers judged by GPT-4o
```

Candidate 优于 Raw 只能由配对 `F-R` 结果支持。与 BM25/Dense 的差异只表明本地相同 Reader/Judge/budget 下的系统级差异，不能归因于 Formation 单一机制。

---

# 8. 高效并发和资源合同

## 8.1 Context/Stateful lane

R2 在 4 和 8 个 stateful processes 之间作一次无标签容量 probe，选择满足以下条件的最高并发：

```text
worker exits = 0
lease ownership loss does not escape
DB connection ceiling not exceeded
P95 context latency does not degrade >20% relative to 4-process lane
```

选定后在 R4 run-lock 冻结，两个产品臂不得使用不同并发。BM25/Dense 是独立的 stateless baseline lane，但必须使用相同 case order 和全局资源上限。

## 8.2 Stateless/model lanes

| Lane | Parallelism | Rule |
| --- | ---: | --- |
| BM25 / deterministic packing/scoring | 8 | CPU |
| flat-Contriever Dense | 2 deterministic shards | GPU2/3 after capability probe; CPU fallback only if frozen before run |
| answer generation | 8 | vLLM GPU0/1 |
| judge | 8 | answer seal 后单独窗口 |
| global active ceiling | 16 | resource probe 可以降低，不得超过 |

Candidate F 仍不含 Dense。GPU2/3 只执行预注册 `MLR01-DENSE` 评估基线，不改变 Candidate 产品组成。若 GPU2/3 不可用，必须在新 run-lock 前二选一：

```text
A. freeze exact CPU Dense implementation and rerun capability probe
B. mark MLR01-DENSE = BASELINE_UNAVAILABLE and do not fabricate a score
```

## 8.3 Checkpoint

checkpoint 必须位于：

```text
var/ml_repair/<run-id>/checkpoints/
```

禁止把唯一可恢复副本保存在 `/tmp`。恢复只执行 missing/corrupt cells，不重复已成功的外部模型调用。

---

# 9. 指标和决策门

## 9.1 Engineering delivery

```text
ProjectionTerminalRate
UnexpectedWorkerExitCount
LeaseLostEscapedCount
LeaseRenewalFailureCount
ReprocessedEventCount
DuplicateDurableSideEffectCount
WatermarkGapViolationCount
ContextTerminalRate
ContextExecutionSuccessRateByArm
TransportFailureRate
FormationEligible/Attempted/Applied counts
RawFallback counts by reason
HydratedEvidenceUnitCount
```

## 9.2 Binding and safety

```text
AcceptedEvidenceIdentityIntegrity
ReaderEvidenceSubsetIntegrity
InternalAcceptedBindingCorrectCount
InternalAcceptedBindingTotalCount
InternalAcceptedBindingPrecision
InternalValidBoundRequirementCount
InternalBindingEligibleRequirementCount
InternalValidBindingRecall
PublicAnswerSessionBoundCount
PublicTotalBoundCount
PublicAnswerSessionBindingPrecision
OperatorReadyRate
TemporalCompletenessRate
Wrong COMPLETE
CorrectCaseRegression
AuthorityScopeRevocationViolation
ReaderGroundingViolation
```

## 9.3 Answer/effect

```text
VLLMJudgeAccuracy@500                 # primary local QA metric
normalized F1 / EM                    # secondary deterministic metrics
paired Candidate-minus-Raw JudgeAccuracy delta and CI
paired Candidate-minus-Raw F1/EM delta and CI
ability-level delta
answer-bearing session Recall@K / NDCG / MRR
BM25/Dense/Raw/Candidate local ranking table
TreatmentMediatedBindingGain
cost per successful context
cost per useful Binding
```

`official local accuracy` 这一模糊名称停用。本轮一律写为 `VLLMJudgeAccuracy`，并显式附带 Judge backend/model/prompt identity。

## 9.4 Engineering repair PASS

```text
R1 + R2 + R3 PASS
worker exits = 0
context product-path transport/readiness failure = 0
treatment delivery denominator > 0
internal exact Binding denominator > 0
all safety counters = 0
```

## 9.5 Candidate support

Candidate F 只在同时满足以下条件时获得 post-repair public-benchmark support：

```text
Engineering repair PASS
formation applied > 0
TreatmentMediatedBindingGain > 0
internal AcceptedBindingPrecision = 1.0
public AnswerSessionBindingPrecision >= Raw arm
Wrong COMPLETE = 0
CorrectCaseRegression = 0
paired VLLMJudgeAccuracy observed delta > 0
paired VLLMJudgeAccuracy CI lower >= -0.02
no ability-family delta < -0.05
```

这是“有 mediator 的安全非劣倾向”候选支持，不是优越性或 formal generalization 声称。只有配对 Judge Accuracy CI 下界 `> 0` 时，才可额外写入 `LOCAL_VLLM_JUDGE_SUPERIORITY_SUPPORTED`。任何情况都不授权 default-ON。

---

# 10. 测试策略

## 开发阶段

```text
edit
→ touched unit test
→ one real-PostgreSQL focused concurrency/integration test when DB semantics change
→ affected worker/projection regression
```

## Block 边界

```text
R1: worker + projection + outbox focused suite
R2: product-path context capacity suite
R3: decision-boundary/scorer + focused lifecycle suite
R4 entry: one full Runtime/contract/PostgreSQL/E2E gate
```

全量 Runtime 只在 R4 入口前跑一次，不在每个 repair iteration 重复运行。

如新增 Migration，最少验证：

```text
upgrade on fresh database
lease renewal authorization
stale owner negative case
concurrent renew/complete/re-lease
downgrade, or explicit experimental irreversibility reason
```

---

# 11. 最小制品

新 run 只保留：

```text
var/ml_repair/<run-id>/
  run-lock.json
  repair-log.jsonl
  results.json
  terminal.json
  release-decision.json

  longmemeval-run-lock.json          # only if R4 entered
  longmemeval-context-results.jsonl
  longmemeval-answer-results.jsonl
  longmemeval-summary.json
  longmemeval-terminal.json
  checkpoints/                       # resumable, workspace-local
```

禁止新增：

```text
per-case receipt
per-stage deliverable index
transitive source manifest for every repair edit
multiple reviewer loops
duplicate runbook
500 individual audit documents
```

`results.json` 可用 Block 字段记录 R0–R4，不需要每个 Block 独立 receipt。

---

# 12. 终态决策

```text
if authority/scope/revocation/Canonical/watermark safety fails:
  FAIL_MLR01_AUTHORITY_OR_STATE_SAFETY

elif worker and treatment delivery are repaired,
     Binding gates pass,
     and Candidate F receives post-repair support:
  PASS_MLR01_EXECUTION_REPAIRED_CANDIDATE_SUPPORTED

elif worker and treatment delivery are repaired,
     Binding gates pass,
     but Candidate F has no gain or nonregression misses:
  PASS_MLR01_EXECUTION_REPAIRED_CANDIDATE_NOT_SUPPORTED

elif worker is repaired but a distinct Binding defect remains
     after bounded general repair:
  PARTIAL_MLR01_WORKER_REPAIRED_BINDING_UNRESOLVED

elif the same external environment blocker repeats through
     three evidence-bearing repair iterations:
  PARKED_MLR01_ENVIRONMENT_UNAVAILABLE

elif the frozen local vLLM Qwen endpoint cannot be probed or
     cannot complete the official LongMemEval judge contract:
  PARKED_VLLM_JUDGE_UNAVAILABLE

elif treatment cannot be made to execute without changing
     frozen architecture or obtaining new authority:
  PARKED_MLR01_TREATMENT_REQUIRES_ARCHITECTURE_AUTHORITY
```

发布决策：

| Repair | Candidate effect | Decision |
| --- | --- | --- |
| MISS | unscored | `KEEP_FLAG_OFF` |
| PASS | unsupported/regressed | `KEEP_FLAG_OFF` |
| PASS | supported | `SHADOW_ONLY_READY` |

本 Goal 不能产生 `DEFAULT_ON` 或 `PRODUCTION_READY`。ADR-028 未批准、formal holdout 未运行、Runtime/Schema 仍为 Candidate/Experimental。

---

# 13. 执行顺序与预算

| Milestone | Work | Entry | Exit | Main cost |
| --- | --- | --- | --- | --- |
| M0 | R0 deterministic reproducer | new run-lock | mechanism localized | CPU + isolated PostgreSQL |
| M1 | R1 lease-aware repair | R0 localized | worker continuity PASS | CPU + PostgreSQL concurrency |
| M2 | R2 32/128 capacity staircase | R1 PASS | treatment delivered | 4–8 stateful processes |
| M3 | R3 Binding closure | R2 PASS | precision/recall denominators valid | CPU, model not required by default |
| M4 | full quality gate | R3 PASS | code/runtime identity frozen | tests only |
| M5 | R4 capability + contexts | M4 PASS | all 2000 context cells valid | stateful product + BM25/Dense baseline lanes |
| M6 | R4 answer/judge | context gate PASS | four-arm local-vLLM characterization | 2000 answers + 2000 Qwen judge calls, 8-way separated windows |

成本原则：

```text
training = 0
formal holdout calls = 0
answer/judge calls before context gate = 0
automatic semantic retries = 0
successful external calls are checkpoint-reused
OpenAI/GPT-4o calls = 0
```

---

# 14. 当前授权

```text
Goal document design:          AUTHORIZED_AND_COMPLETE
Code changes:                  NOT_AUTHORIZED_BY_THIS_REQUEST
Migration/schema changes:      NOT_AUTHORIZED_BY_THIS_REQUEST
Ephemeral PostgreSQL:          NOT_AUTHORIZED_BY_THIS_REQUEST
Provider/Reader calls:         NOT_AUTHORIZED_BY_THIS_REQUEST
LongMemEval rerun:             NOT_AUTHORIZED_BY_THIS_REQUEST
Formal holdout:                FORBIDDEN
Product flag enablement:       FORBIDDEN
```

后续若用户明确要求执行本 Goal，应：

```text
1. 新建 superseding execution identity
2. 保留 ml-closure-20260830-001 不变
3. 从 R0 开始，不直接重跑 500-case
4. 按 R1→R2→R3 因果门推进
5. 只在送达与 Binding 闭合后进入 R4
```
