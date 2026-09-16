---
document_id: MILA-ML-R01
version: "0.3"
status: ACTIVE_R2_EFFICIENCY_AND_COVERAGE_DIAGNOSIS
document_type: REPAIR_AND_REVALIDATION_GOAL
updated_at: 2026-08-31T11:46:41+08:00
architecture_baseline: MILA-ML-ARCH@1.0
predecessor_program: MILA-ML-CLOSURE@0.2
predecessor_terminal: PARKED_ML_CLOSURE_LONGMEMEVAL_BELOW_TARGET
active_run: ml-r01-20260831-001
execution_authority: USER_EXPLICIT_20260831_MLR01_EXECUTE
future_protocol_amendment_required: true
formal_holdout_authorized: false
product_default_enable_authorized: false
benchmark_judge_backend: VLLM_HTTP_ONLY
leaderboard_equivalence_claimed: false
---

# MiLAi ML-R01：产品送达、简单读取与 LongMemEval 重验 Goal

> 本文 v0.3 保留 `ml-r01-20260831-001` 的 R0、R1、R2-A 机器事实，只替代尚未执行的 R2-B～R4 导航。继续执行前写一份绑定本文 digest 的轻量 protocol amendment；不得重复已成功的 case、数据库测试或模型调用。

---

# 1. Goal

先恢复可测量、可扩展的产品读取，再回答 Candidate F 是否有效：

```text
Evidence ingest / projection works
→ Raw and Formed reads share one snapshot
→ ordinary recall uses soft semantic selection
→ strict operators retain typed proof
→ fixed Qwen Reader/Judge evaluates matched outputs
```

本 Goal 分开判定：

```text
Engineering delivery
Memory representation / retrieval effect
Strict completion safety
Reader answer effect
Release decision
```

工程修复可以 PASS，而 Candidate F 仍然 unsupported 并保持 OFF。

---

# 2. 当前进度

权威制品：

```text
var/ml_repair/ml-r01-20260831-001/run-lock.json
var/ml_repair/ml-r01-20260831-001/results.json
var/ml_repair/ml-r01-20260831-001/terminal.json
var/ml_repair/ml-r01-20260831-001/repair-log.jsonl
```

## 2.1 原始结果表

| Stage | Context success | Formation applied | P50 / P95 | Disposition |
| --- | ---: | ---: | ---: | --- |
| ML-CLOSURE Candidate | 23/500 | 0 | invalid for method inference | product-path failure |
| R0 | deterministic reproduction | N/A | N/A | `PASS_MECHANISM_LOCALIZED` |
| R1 | slow batch 32/32 | N/A | N/A | `PASS_WORKER_CONTINUITY_AND_STATE_SAFETY` |
| R2-A iteration 1 | 28/32 | 0 | unsealed | repair as-of / latency contract |
| R2-A iteration 2 | 16/32 | 1 | unsealed | repair cleanup / timeout envelope |
| R2-A final | 32/32 | 2 | 51.329s / 125.271s | `PASS_R2_A_DELIVERY` |

R1 机器事实：

```text
migration head                    0048_projection_lease_renewal
focused unit / fresh PG tests     18 / 20 passed
unexpected worker exits          0
escaped LEASE_LOST               0
stale-owner durable completion   0
duplicate durable side effects   0
watermark gap violations         0
```

R2-A final：

```text
Context terminal                 32/32
Formation eligible              32
Formation attempted/applied     2/2
Formation applied rate          0.0625
Raw fallback                    30/32
max latency                     140.948s
bounded readiness retries       3
authority/scope/revoke failure  0
answer/judge calls              0/0
```

## 2.2 解释

1. Lease ownership 缺陷已经关闭；R1 不再重跑或扩张成通用 framework。
2. 当前主要工程成本是 case 级 ingest、projection readiness 与同步物理清理，不是模型推理。
3. Candidate F 当前是稀疏 treatment，不是全部 query 的通用替代路径。
4. 上次 500-case 的 `formation_applied=0`，不能支持 Formation 正负结论。
5. Goal v0.2 的 512-token 主预算与正式 harness 的 1024 不一致；v0.3 以 1024 为主预算。

---

# 3. 方法基线：Progressive Semantic Commitment

> 可逆读取宽进、软排；答案支持需 grounded；只有严格 operator 与 Canonical 提交进入完整 proof。

## 3.1 Ordinary recall

适用：普通事实、偏好、单事件、简单 lookup。

```text
tenant/scope/permission/revocation/lineage gate
→ BM25 / Dense / Formed candidates
→ union + dedup + soft ranking
→ coherent Evidence context
→ Reader
```

Semantic relevance 是排序信号，不是进入 Reader 前的硬真值判断。

## 3.2 Strict typed path

适用：

```text
COUNT / bounded range completeness
current versus historical version
conflict resolution
authority-bearing action
Canonical mutation
```

这些 query 继续执行：

```text
RequirementState
→ Binding
→ proof obligations / Sufficiency
→ typed Operator or abstention
```

## 3.3 Authority levels

```text
Context Evidence
  governance + lineage pass; may enter Reader

Answer Support
  grounded span / source identity; may support an answer

State Authority
  typed time/conflict/provenance contract; may affect COMPLETE/Operator/Canonical
```

不允许由低层级自动升级到高层级。

---

# 4. 不可变边界与范围

硬边界仅保留：

1. tenant、scope、permission、revocation；
2. Raw Evidence preservation 与 source lineage；
3. Canonical single-writer、append-only、exact-head CAS；
4. projection ownership、idempotency 与 watermark gap；
5. strict typed completion、Wrong COMPLETE 与 benchmark label isolation。

本 Goal 不做：

```text
new retrieval round or model action planner
StateView reranking revival
SemanticEpisode V02 retuning
Top-k / Prompt / seed sweep
model training or fine-tuning
durable Formation object approval
new Canonical object/write path
formal holdout or DEFAULT_ON
```

---

# 5. Hypotheses

## MLR01-H1 — Delivery repair

一个有界 lease-aware worker 和简化的 benchmark 生命周期，可以在不改变检索语义或 Canonical authority 的情况下稳定完成 128-case 产品送达。

最小证据：

```text
128/128 context terminals
worker/transport/readiness failures = 0
stale-owner/watermark/duplicate effects = 0
cross-case Evidence leak = 0
Formation applied > 0
```

R0/R1 与 32-case 子命题已经支持；完整 H1 等待 R2-B。

## MLR01-H2 — Formed simple-read utility

在同一 snapshot、Reader、Judge 和 token budget 下，Candidate F 是否改善 evidence selection 或答案，且不破坏 strict completion。

最小证据：

```text
Formation applied > 0 and reported separately from fallback
ordinary ContextEvidenceRecall reported
strict AcceptedBindingPrecision = 1.0 when applicable
Wrong COMPLETE = 0
CorrectCaseRegression = 0
paired F-minus-R Judge Accuracy and CI reported
```

Anti-hypothesis：不得把 Raw fallback、重复 ingest、逐 case 物理清理、不同预算、identity-integrity Boolean 或事后参数调整解释为 Formation 增益。

---

# 6. 后续执行 Blocks

## R2-E — Profile 与 harness 简化

先从现有 32-case checkpoint 计算：

```text
Evidence ingest latency
projection readiness latency
Formation build/hydration latency
memory resolve latency
namespace cleanup latency
```

不重新 ingest。随后只做一次由最大耗时阶段决定的通用优化，默认方案：

```text
one fresh ephemeral database per stateful shard
unique subject/source namespace per case
ingest and project once per case
Raw and Formed reads share the immutable snapshot
no per-case physical purge in the timed path
one cleanup/revocation witness per shard
drop the exact database after shard terminal
```

这仍执行正式 ingest、projection、governance 和 read path；只把与 QA 因果比较无关的物理销毁移到 shard 末尾。

R2-E PASS：

```text
stage latency share reported
shared snapshot identity exact
cross-case leak = 0
cleanup witness = PASS
projected 500-case wall time reported
```

## R2-B — 128-case label-free capacity

```text
default: 4 stateful shards
if projected 500-case product window > 2h:
  compare 4 vs 8 shards on a 32-case subset only
never repeat the full 128 denominator for a concurrency sweep
```

case 由 question ID hash 与 history-size strata 选择；answer、answer-session 和 Judge label 不进入路径。

R2-B PASS：

```text
context terminals                    128/128
transport/readiness/worker failure   0
cross-case leak                      0
Formation eligible/applied           >0 / >0
successes due only to fallback       false
authority/scope/revoke violation     0
P50/P95/throughput/projected wall    reported
```

## R3 — Progressive correctness boundary

比较：

```text
uniform-strict historical boundary
vs
ordinary governance admission + strict typed escalation
```

第一版不调用模型解释器，不新增 Requirement schema，不改变 Canonical Gate。

R3 PASS：

```text
AcceptedEvidenceIdentityIntegrity = 1.0
ReaderEvidenceSubsetIntegrity     = 1.0
ordinary ContextEvidenceRecall    >= historical boundary
strict Binding precision          = 1.0 when denominator > 0
Wrong COMPLETE                    = 0
CorrectCaseRegression             = 0
ReaderGroundingViolation          = 0
```

普通 QA 没有 strict Binding 分母时报告 `NOT_APPLICABLE`，不阻断外部 QA 评分。

## R4 — LongMemEval staged characterization

### Arms

```text
MLR01-BM25-T   official-style BM25 turn baseline
MLR01-DENSE    frozen flat-Contriever baseline
MLR01-R        Raw + Canonical Simple
MLR01-F        Formed + Raw fallback + Canonical Simple
```

产品 R/F 共享同一 case snapshot；BM25/Dense 是 evaluation baselines，不拥有 MiLA Canonical authority。

### Reader/Judge/token contract

```text
dataset/order             LongMemEval-S cleaned 500
memory context budget     1024 primary
answer max output         500, thinking disabled
judge max output          10
Reader/Judge              Qwen3.6-35B-A3B-FP8 via local vLLM
judge prompt              upstream get_anscheck_prompt body
judge temperature         0
answer/judge windows      separate, 8-way each
OpenAI/GPT-4o calls       0
leaderboard equivalence   false
```

LongMemEval 官方 generation 使用模型窗口减 generation reserve，不使用固定 512-token memory context。`512` 只作对已封存 1024 context 的离线截断压力诊断，不新增 retrieval、answer 或主结论 Judge arm。

### Staircase

```text
1. capability and identity seal
2. 128 × 4 contexts
3. require 128/128 terminals per arm and zero product execution failure
4. 128 × 4 answers; seal
5. separate 128 × 4 Qwen judges
6. compute viability, coverage, paired effects and cost
7. if viable, extend checkpoints to 500 × 4
8. reuse the first 128 cells; do not call them again
```

full-run viability：

```text
all 128 context and model cells terminal
product delivery success = 1.0
zero isolation/safety violation
projected 500-case wall within frozen resource window
Formation applied rate and projected full denominator reported
```

若 Formation applied rate `<10%`，F 被解释为 sparse specialist treatment；报告全分母 ITT 与 applied subset，但 applied subset 不是独立因果估计。

Primary：

```text
VLLMJudgeAccuracy@128/@500
paired F-minus-R JudgeAccuracy delta + 95% CI
```

Secondary：Recall/NDCG/MRR、EM/F1、ability strata、Formation coverage、cost。只有 F-R 支持 Formation 归因；与 BM25/Dense 的差异只是本地系统比较。

---

# 7. Metrics scorecard

## Delivery

```text
ContextTerminalRate
Transport/Readiness/WorkerFailureCount
ProjectionTerminalRate
LeaseLostEscapedCount
DuplicateDurableSideEffectCount
WatermarkGapViolationCount
CrossCaseEvidenceLeakCount
```

## Representation / retrieval

```text
FormationEligible/Attempted/Applied
RawFallbackByReason
HydratedEvidenceUnitCount
ContextEvidenceRecall
AnswerSessionRecall@K / NDCG / MRR
```

## Strict safety

```text
StrictAcceptedBindingCorrect/Total/Precision
StrictValidBindingRecall
OperatorReadyRate
TemporalCompletenessRate
Wrong COMPLETE
AuthorityScopeRevocationViolation
```

## Reader

```text
VLLMJudgeAccuracy
EM / normalized F1
CorrectCaseRegression
ReaderGroundingViolation
```

## Cost

```text
Ingest/Projection/Formation/Resolve/Cleanup latency share
P50/P95 and throughput
model calls/tokens
cost per successful context
cost per useful Binding
```

Delivery failure仍计入端到端产品成绩，但只有 delivery gate 通过后才允许解释语义 treatment 效果。

---

# 8. Development and harness policy

```text
edit
→ touched tests
→ focused real PostgreSQL test only when DB semantics change
→ one causal witness
→ one Block-level regression
→ one full related quality gate before R4
```

不再生成 per-case receipt、stage deliverable index、transitive source manifest、重复 runbook 或 reviewer loop。每个 run 只保留：

```text
run-lock.json
protocol-amendment.json       # only for v0.3 continuation
repair-log.jsonl
results.json
terminal.json
release-decision.json
benchmark checkpoint/summary  # only when R4 enters
```

非安全 protocol/implementation failure：定位一个机制、做一个通用修复、继续同一 Block。同一机制连续三次无进展才重新设计；不会终止无共享根因的 Program。

立即停止受影响 lane 的条件：cross-tenant/revocation leak、uncontrolled Canonical mutation、watermark gap、duplicate non-idempotent durable effect、benchmark label leakage。

---

# 9. Run order and resource budget

| Milestone | Work | Status / gate |
| --- | --- | --- |
| M0 | R0 reproducer | PASS / immutable |
| M1 | R1 lease repair | PASS / immutable |
| M2-A | 32-case delivery | PASS / immutable |
| M2-E | profile + shared snapshot / shard DB witness | NEXT; amendment required |
| M2-B | 128-case capacity | blocked by M2-E |
| M3 | progressive boundary | blocked by M2-B |
| M4 | one related full quality gate | blocked by M3 |
| M5 | 128-case four-arm viability | blocked by M4 |
| M6 | extend to 500 | conditional on M5 |

Resource defaults：

```text
stateful shards              4
stateless CPU workers        8
Dense GPU shards             2 on GPU2/3 after probe
answer / judge concurrency   8 / 8, non-overlapping
global active ceiling        16
training/formal holdout      0
```

成功 checkpoint 必须复用；并发不增加 logical attempt、sample weight 或 hidden retry。

---

# 10. Terminal and release

```text
actual authority/data/watermark safety breach
→ FAIL_MLR01_AUTHORITY_OR_STATE_SAFETY

delivery + progressive boundary PASS; Candidate supported
→ PASS_MLR01_EXECUTION_REPAIRED_CANDIDATE_SUPPORTED

delivery + progressive boundary PASS; Candidate unsupported/regressed
→ PASS_MLR01_EXECUTION_REPAIRED_CANDIDATE_NOT_SUPPORTED

worker repaired; distinct strict-operator defect remains
→ PARTIAL_MLR01_WORKER_REPAIRED_STRICT_PATH_UNRESOLVED

three evidence-bearing iterations cannot restore environment
→ PARKED_MLR01_ENVIRONMENT_UNAVAILABLE

local Qwen vLLM contract unavailable
→ PARKED_VLLM_JUDGE_UNAVAILABLE
```

Release：

| Engineering | Candidate | Decision |
| --- | --- | --- |
| MISS | unscored | `KEEP_FLAG_OFF` |
| PASS | unsupported/regressed | `KEEP_FLAG_OFF` |
| PASS | supported | `SHADOW_ONLY_READY` |

本 Goal 不能产生 `DEFAULT_ON` 或 `PRODUCTION_READY`。Runtime/Schema 保持 `0.1.x CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。

---

# 11. Current authority

```text
Active run                    ml-r01-20260831-001
R0/R1/R2-A                   EXECUTED_AND_IMMUTABLE
Current point                 R2-E_PROTOCOL_AMENDMENT_REQUIRED
Code / Migration / PG         authorized by active run
Provider / Reader             only after future causal gates
LongMemEval                   only after R2/R3/R4 entry gates
Formal holdout                FORBIDDEN
Product enablement            FORBIDDEN
```

继续时必须保留 predecessor 与已成功 evidence，先写 amendment，再从 R2-E 开始；不得从 R0 重启。
