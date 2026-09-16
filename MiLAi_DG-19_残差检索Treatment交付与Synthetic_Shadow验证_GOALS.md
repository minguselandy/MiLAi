# MiLAi DG-19：残差检索 Treatment 交付与 Synthetic Shadow 闭环验证 Goal

> Goal ID：`DG-19`  
> 文档版本：`0.2.0 CONTINUOUS EXECUTION`  
> 生效日期：`2026-08-28`（Asia/Shanghai）  
> 当前状态：`AUTHORIZED FOR CONTINUOUS S0–S8 EXECUTION WITH HARD GATES`  
> 前置 Goal：`DG-17` deterministic acquisition baseline；`DG-18` residual provider RCA  
> Provider：operator-owned vLLM `http://127.0.0.1:7860` / `Qwen3.6-35B-A3B-FP8` / observed `vLLM 0.27.1`  
> 产品边界：`LOCAL MCP / SYNTHETIC OR DEIDENTIFIED DATA ONLY`  
> Runtime / Schema：`CANDIDATE / EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> 禁止范围：`FORMAL HOLDOUT / R5 TWO-ROUND / PRODUCTION OR REMOTE RELEASE`

---

# 0. Goal 指令

执行本 Goal，完成一个真实但隔离的 synthetic treatment-delivery 闭环：

```text
deterministic acquisition leaves a typed missing requirement
        ↓
Runtime builds AcquisitionObservation
        ↓
real vLLM returns ResidualCueProposal v0.1
        ↓
Pydantic parse + Runtime normalization/validation
        ↓
one additional acquisition pass actually executes
        ↓
new governed candidates are measured
        ↓
Binding / Sufficiency are recomputed in shadow
        ↓
sealed synthetic treatment-delivery receipt
```

本 Goal 不执行 DG-17，也不重新实现 DG-17 的 QueryIR、deterministic acquisition、
Binding 或 Sufficiency。DG-17 只作为固定 baseline 被复用。

本 Goal 不回写 DG-18 历史 receipt，不修改 `architecture/v1.0/`，不把 provider
conformance PASS 伪装成 residual 算法质量 PASS。

第一阶段先回答：

> **当前 successor contract 能否在真实 vLLM 调用下，把一个合法 cue 交给 Runtime，
> 并让 Runtime 真正执行一次有界的额外证据获取？**

本 Goal 不回答：

```text
是否需要第二轮 refinding
是否形成论文贡献
是否可以发布生产版本
```

## 0.1 连续执行指令

本 Goal 不是完成 synthetic receipt 后停止的短任务。只要上一阶段 hard gate 通过，且下一阶段
仍在本文授权范围内，执行器必须自动继续，不等待新的用户确认：

```text
S0–S3  Synthetic treatment delivery
        ↓ PASS
S4     Opened-dev residual shadow / mediator measurement
        ↓ mediator gate PASS
S5     One-call live residual Runtime integration
        ↓ product safety gate PASS
S6     MCP + OpenWorker real local composition
        ↓ usability gate PASS
S7     Matched opened-dev quality / cost evaluation
        ↓
S8     Terminal disposition and sealing
```

完成一个 work package 不是停止条件。单项失败也不是立即将 Goal 标记为 `BLOCKED` 的理由；
必须先按第 9.2 节定位最小 owner、修复并复测。只有确实需要外部状态变化或新增授权，且在当前
范围内已无法继续时，才报告 blocker。

条件分支：

```text
S3 treatment delivery FAIL
→ 留在 S0–S3，单项修复，不进入 LME

S3 PASS, S4 valid treatment but mediator gate FAIL
→ PARKED_NO_MEDIATOR_GAIN
→ 跳到 S8 封存，不实现 live residual

S4 mediator gate PASS
→ 自动进入 S5–S7

S7 quality/cost gate FAIL
→ 保持 live residual default-disabled
→ PARKED_NO_END_TO_END_PRODUCT_GAIN
→ S8 封存
```

Formal holdout、R5 two-round、生产或远程发布始终需要新的显式 Goal，不在本连续授权内。

---

# 1. 为什么需要 DG-19

## 1.1 当前真实状态

已确认：

| 层级 | 当前结果 | 证据 |
| --- | --- | --- |
| Historical DG-18 R3 | `TREATMENT_NOT_DELIVERED` | 0/10 valid hints；0 extra passes |
| Successor provider transport | `PASS_PROVIDER_CONFORMANCE` | 6/6 cells PASS |
| Successor application proposal | PASS | 4/4 Pydantic + Runtime accepted |
| Typed SSE error | PASS | 顶层 SSE error 不再误报 `EMPTY_OUTPUT` |
| Synthetic treatment delivery | **尚未执行** | 缺少正式 producer/receipt |
| Residual mediator effect | `NOT EVALUATED` | 没有真实额外 acquisition denominator |
| Full LME | disabled | 需要 synthetic receipt |
| Historical DG-18 R4/R5 | disabled | DG-19 可在 S4 PASS 后自动执行等价的 S5 one-call integration；R5 仍 disabled |

绑定证据：

- [DG-18 Provider conformance receipt](./var/dg18/provider-conformance/dg18-provider-conformance-20260828-002/receipt.json)，SHA-256 `2e7bc6f96baa0ba22479c7b952eb8864d6714836c0b13d7783d04d16c750f53e`；
- [Typed SSE error receipt](./var/dg18/provider-conformance/dg18-provider-conformance-20260828-002/typed-sse-error-receipt.json)，SHA-256 `27f5ca90fe894af24b5ef90a74b3308a6ba55c18195d12f1d4d30a29634e0815`；
- [DG-18 Provider RCA calibration](./var/dg18/final/dg18-provider-rca-calibration-20260828-002.json)，SHA-256 `406e4ee215af9821f4f31ea9b936d0867ab6fca21d0185d83576ad6ff9b18c21`；
- [Fresh PostgreSQL gate](./var/dg18/final/dg18-runtime-full-gate-20260828-004.json)，SHA-256 `f04aadc443bde27ac8c57160be216dcd23f09884311b3ea099760a6f6bd892c2`；
- [DG-18 Runtime architecture and operator runbook](./docs/dg18/runtime-architecture-and-operator-runbook.md)。

## 1.2 当前真正缺失的对象

`scripts/run_dg18_r3_shadow.py::_validated_treatment_delivery()` 已经要求：

```text
schema = milai.dg18.synthetic-treatment-delivery-receipt.v0.1
status = PASS_SYNTHETIC_TREATMENT_DELIVERY
schema_valid_hint_count >= 2
runtime_accepted_hint_count >= 2
additional_acquisition_pass_count >= 1
formal_holdout_consumed = false
```

但当前 repository 没有一个正式 runner 生成该 receipt。

因此当前不是：

```text
provider incompatible
DG-17 需要重跑
算法已证明无效
```

而是：

```text
provider contract is compatible
        +
treatment-delivery receipt producer is missing
        +
end-to-end synthetic extra pass has not been executed
```

DG-19 先关闭这个 operational gap；通过后继续验证 opened-dev mediator，再按 hard gate
决定是否把同一 one-call residual 机制接入本地 Runtime/MCP 候选路径。它不重开 DG-17，
也不跳过 treatment-delivery gate 直接修改产品。

---

# 2. 产品与架构边界

## 2.1 MiLA ownership 不变

MiLA 仍是 MCP-native governed memory service。DG-19 只在隔离 Evaluation Plane 验证
Raw Evidence Lane 的 residual acquisition control，不改变：

```text
Evidence identity
Canonical State ownership
permission / scope / retention / revoke
Binding authority
Sufficiency authority
MCP public tool contract
canonical write procedure
```

模型只允许提交：

```yaml
ResidualCueProposal:
  requirement_id:
  action:
    SEARCH_LEXICAL
    SEARCH_TEMPORAL
    EXPAND_NEIGHBORS
    NO_ACTION
  cues: []
```

Runtime 继续派生并拥有：

```text
cue provenance
rationale code
source role
temporal bounds
scope / principal / permission
candidate budget
Evidence eligibility
Binding
Sufficiency
stop / abstain
```

## 2.2 当前实现必须复用

禁止复制第二套 residual domain。直接复用：

- `runtime/src/milai/domain/residual_refinding.py::ResidualCueProposal`；
- `runtime/src/milai/application/residual_refinding.py::ResidualHintShadowService.generate()`；
- `runtime/src/milai/application/residual_refinding.py::normalize_residual_cue_proposal()`；
- `runtime/src/milai/application/residual_refinding.py::validate_residual_search_hint()`；
- `runtime/src/milai/application/residual_refinding.py::build_acquisition_observation()`；
- `runtime/src/milai/application/acquisition_state.py` 的 reservation / transition；
- `runtime/src/milai/adapters/semantic_hint.py::LoopbackVllmSemanticProvider`；
- DG-18 已验证的 flat provider Schema 与 typed transport error。

允许在隔离 evaluator 中实现 synthetic additional acquisition executor，但它必须使用
现有 acquisition action、candidate eligibility、Binding 与 Sufficiency 语义，不得成为
第二套产品 Runtime。

## 2.3 不新增公共接口或持久 Schema

本 Goal 默认不需要：

```text
Alembic migration
新 PostgreSQL table
新 public MCP tool
OpenWorker 改动
canonical procedure 改动
architecture/v1.0 变更
```

若实现过程中发现必须修改上述任一项，立即停止并报告 scope expansion；不得借 DG-19
静默扩大产品架构。

---

# 3. Synthetic fixture 设计

## 3.1 Fixture 目的

Fixture 只证明 control treatment 被实际交付，不用于宣称开放域质量。

最小集合应覆盖 4–6 个去标识 synthetic case：

| Case class | 初始状态 | 允许 action | 应观察的闭环 |
| --- | --- | --- | --- |
| Lexical bridge | query 与 answer-bearing turn 词面不一致 | `SEARCH_LEXICAL` | 新 cue 命中新 turn |
| Observation bridge | initial candidate 暴露新 entity/predicate | `SEARCH_LEXICAL` | cue 来源可判为 observation |
| Temporal bound | requirement 已有 Runtime 时间边界 | `SEARCH_TEMPORAL` | provider 不扩大时间范围 |
| Neighbor recovery | operand 位于合法 anchor 邻接 turn | `EXPAND_NEIGHBORS` | 同 session 邻接恢复 |
| Safe no-op | observation 没有安全新 cue | `NO_ACTION` | 不执行 extra pass |
| Negative scope | 相似文本位于错误 scope | 任意 | candidate 被 Gate 拒绝 |

Fixture 文本不得复制 LME 当前 10-case wording，不得包含真实个人数据、gold session ID、
expected answer substring 或隐藏 prompt 指令。

## 3.2 Product input 与 scorer truth 分离

同一 fixture 文件可以物理共存，但 runner 必须构造两个显式 view：

```text
Product view:
  query
  timestamp
  typed requirements
  initial candidates
  searchable evidence universe
  scope / permission metadata

Scorer-only view:
  expected answer-bearing source refs
  expected action family
  expected missing requirement
```

provider、AcquisitionObservation、candidate executor 和 Runtime validator 只能看到 Product
view。先密封 product trace，再读取 scorer-only truth。

这不是 formal holdout protocol；只需一个清晰、可测试的边界，不建立额外 manifest、双人
annotation 或独立评审流程。

## 3.3 不允许 scripted provider 冒充完成

单元测试可以使用 fake provider，但 terminal receipt 必须来自真实 operator-owned vLLM。

禁止：

```text
case_id → fixed cue
expected source text → fixed cue
scripted fake provider 生成 terminal PASS
gold label 进入 prompt
失败后自动 retry
更换模型或隐藏 provider
```

---

# 4. 执行路径

## 4.1 单 case 流程

```text
1. Compile or load deterministic AcquisitionPlan
2. Execute initial deterministic acquisition
3. Recompute Binding / Sufficiency
4. Confirm a typed missing requirement exists
5. Initialize AcquisitionState
6. Reserve exactly one controller call
7. Build bounded AcquisitionObservation
8. Call vLLM once with ResidualCueProposal schema
9. Parse proposal and normalize it into Runtime-owned ResidualSearchHint
10. Validate requirement, action, capability and inherited constraints
11. If ACCEPTED, execute exactly one additional acquisition pass
12. Apply candidate eligibility and deduplication
13. Recompute Binding / Sufficiency in shadow
14. Persist safe trace and score only after sealing
```

`NO_ACTION`、invalid proposal 或 Runtime rejection 均为合法的 typed outcome，但不能计入
`additional_acquisition_pass_count`。

## 4.2 额外 acquisition 必须真实发生

不得仅设置：

```json
{"attempted": true}
```

PASS 至少要形成可核对的状态变化：

```text
accepted action identity
query/cue digest
candidate universe identity
new candidate refs
repeated candidate refs
eligibility outcomes
AcquisitionState pass transition
post-pass Binding / Sufficiency
```

candidate 正文默认不写入 receipt；只保存 source ref、digest、reason code 与计数。

## 4.3 成本合同

S0–S4 shadow 中每个 eligible case：

```text
controller logical calls       <= 1
provider calls                 <= 1
automatic retries              = 0
additional acquisition passes <= 1
candidate cap                  bounded by AcquisitionPlan
canonical mutations            = 0
product response changes       = 0
```

S5 以后只有显式 residual candidate policy 可以改变 memory context；default-disabled、
deterministic-only 和不满足 activation 条件的路径必须保持原结果。

所有 case 可以并行执行，但每个 case 内：

```text
observation
→ provider
→ validation
→ additional acquisition
→ Binding / Sufficiency
```

必须串行。并发不得改变 logical attempts、seed、预算或失败 denominator。

---

# 5. Work Packages

## S0 — Contract 与 Fixture Freeze

目标：建立最小 fixture 和 receipt 合同，不调用 provider。

交付：

```text
evals/dg19/fixtures/synthetic-treatment-cases.v0.1.json
evals/dg19/synthetic_treatment_delivery.py
tests/test_dg19_synthetic_treatment_delivery.py
```

要求：

1. fixture 无真实用户数据；
2. product/scorer 字段分离；
3. 至少四种 action/outcome；
4. receipt 兼容 `run_dg18_r3_shadow.py::_validated_treatment_delivery()`；
5. historical DG-18 receipt hash 不变；
6. 不改 frozen architecture。

退出条件：fixture、schema、negative tests 与 receipt validator tests 通过。

## S1 — Synthetic Treatment Runner

目标：实现唯一 producer：

```text
scripts/run_dg19_synthetic_treatment_shadow.py
```

runner 必须：

- 使用 fresh output directory，存在即失败；
- 验证 provider conformance receipt 的 hash、endpoint、model 与 status；
- 使用 non-streaming provider mode；
- 调用真实 `ResidualHintShadowService`；
- 执行真实 additional acquisition simulation；
- 先写 sealed product trace，再执行 scorer；
- 最终输出已有 entry gate 要求的
  `milai.dg18.synthetic-treatment-delivery-receipt.v0.1`；
- 显式记录 `formal_holdout_consumed=false`、`lme_executed=false`、
  `automatic_retry_count=0`。

不要建立通用 runner framework；一个脚本、一个 evaluator、一个 fixture owner 足够。

## S2 — Real vLLM Synthetic Shadow

固定 provider：

```text
base_url: http://127.0.0.1:7860
model: Qwen3.6-35B-A3B-FP8
transport: non-streaming
```

不得重启、重配或替换 provider。运行前只做：

```text
/version
/v1/models
existing provider-conformance receipt identity check
```

若失败，单项调试顺序：

```text
transport
→ Schema parse
→ Runtime normalization
→ Runtime validation
→ additional acquisition executor
→ Binding
→ scorer
```

禁止直接重跑完整 case 集合碰运气。

## S3 — Terminal Receipt 与后续决定

生成：

```text
var/dg19/synthetic-treatment/<run-id>/
├── sealed-product-shadow.json
├── score.json
├── receipt.json
└── failure-ledger.json  # 仅在存在失败时
```

若通过，receipt 必须能直接通过：

```text
scripts/run_dg18_r3_shadow.py::_validated_treatment_delivery()
```

S3 PASS 后自动进入 S4，不等待新的授权。

## S4 — Opened-dev Residual Shadow

目标：使用已通过的 provider conformance receipt 与 S3 treatment receipt，执行当前
`scripts/run_dg18_r3_shadow.py` 的 10-case opened-dev shadow。该阶段允许使用 opened-dev
scorer，但仍不改变产品响应。

固定输入：

```text
Q1R archive:
  var/dg17/a2/dg17-a2-per-slot-fusion-20260827-004/
  product-contexts-001/contexts.json

provider conformance:
  var/dg18/provider-conformance/
  dg18-provider-conformance-20260828-002/receipt.json

synthetic treatment receipt:
  S3 terminal receipt

provider:
  http://127.0.0.1:7860
  Qwen3.6-35B-A3B-FP8
  non-streaming
```

S4 必须报告：

```text
valid / Runtime-accepted hints
extra passes
new governed candidates
gold-turn rank delta
RequiredSlotCandidateRecall delta
RequiredEvidenceSetCoverage delta
Binding delta
OperatorReady delta
candidate noise
controller tokens / latency
wrong scope / authority / COMPLETE
```

进入 S5 的 hard gate：

```text
valid treatment delivered                         = true
wrong COMPLETE / scope / authority / revoke      = 0/N
already-correct case regression                  = 0/N
missing-slot improved cases                      >= 2
RequiredEvidenceSetCoverage                      non-decreasing
OperatorReady cases                              non-decreasing
automatic retries                                = 0
```

若 valid treatment 已执行但 mediator gate 不通过，结果必须是
`PARKED_NO_MEDIATOR_GAIN`；直接进入 S8，禁止通过调大模型权限、candidate cap 或隐藏轮次
强行进入 S5。

## S5 — One-call Live Residual Runtime Integration

仅在 S4 gate PASS 后执行。

目标：把已验证的 residual slow path 接入本地 `memory.resolve` 应用链，但保持
default-disabled 或显式 candidate flag，直到 S7 结束。

产品路径：

```text
deterministic acquisition
→ Binding / Sufficiency
→ typed missing requirement
→ residual policy enabled
→ one ResidualCueProposal call
→ Runtime normalization / validation
→ one additional acquisition
→ Evidence Gate
→ Binding / Sufficiency recompute
→ Context or typed PARTIAL
```

实现约束：

- 同一次逻辑 MCP resolve 内完成，不要求 Agent 再发一 Turn；
- deterministic `COMPLETE` 时 provider call 必须为 0；
- provider unavailable、invalid proposal、`NO_ACTION` 或 Runtime rejection 时，保留
  deterministic outcome 并写 typed trace；
- residual 是 acquisition optimization，不得被写成 `Need=NONE` 或新的 truth source；
- 不新增 public MCP tool，不改变 canonical write path；
- controller 不能选择最终 Evidence、Binding、Sufficiency 或答案；
- one call、one pass、zero retry、zero hidden fallback；
- feature flag / policy identity 必须进入 trace，但不引入通用 feature-flag framework。

如果完成产品接线必须修改公共 MCP Schema、持久数据库 Schema 或冻结 architecture，停止并
报告 scope expansion；当前 Goal 不授权这些变更。

## S6 — MCP 与 OpenWorker Local Composition

仅在 S5 的 Runtime safety tests 通过后执行。

至少验证：

```text
Generic MCP client
→ milai memory resolve
→ deterministic miss/partial
→ one residual action
→ new governed Evidence
→ recomputed Context

OpenWorker local prefetch
→ same MCP tool semantics
→ provider receives governed Context
→ final response
```

必须包含：

1. 一个 residual 找到新 Evidence 的正例；
2. 一个 deterministic COMPLETE、controller 为 0 call 的快路径；
3. 一个 provider unavailable、产品保持 typed deterministic outcome 的失败例；
4. 一个 wrong-scope/revoked candidate 被拒绝的负例；
5. 一个 MCP 客户端不提供 TaskContext 仍能 fresh resolve 的用例；
6. trace 能区分 deterministic pass 与 residual pass。

只使用 synthetic/deidentified memory。不得把 session conversation history 冒充为 MiLA
持久记忆；验证必须能够指向真实 MiLA Evidence/Context refs。

## S7 — Matched Opened-dev Quality 与 Cost

S6 PASS 后自动执行。使用同一 opened-dev cases、同一 reader、同一 prompt、同一 token
budget 与固定执行顺序比较：

```text
deterministic-only
vs
deterministic + one-call residual
```

至少报告：

```text
EM / F1
AnswerBearingTurnRecall
RequiredEvidenceSetCoverage
BindingSuccessRate
OperatorReadyRate
abstention correctness
controller activation rate
provider calls per query
extra acquisition rate
retrieval / controller / end-to-end p50-p95
context tokens
quality per second
```

S7 candidate gate：

```text
F1 >= matched deterministic-only
already-correct case regression = 0/N
wrong COMPLETE / scope / authority / revoke = 0/N
Evidence coverage and OperatorReady non-decreasing
automatic retries = 0
formal holdout consumed = false
```

若 mediator 在 S4 改善、但 S7 没有形成 end-to-end gain，保留实现与实验证据但继续
default-disabled，terminal disposition 为 `PARKED_NO_END_TO_END_PRODUCT_GAIN`。

## S8 — Terminal Disposition 与封存

汇总 S0–S7 的 executable identities、测试、失败和成本，生成唯一 terminal receipt。

允许的终态：

```text
PASS_LOCAL_MCP_ONE_CALL_RESIDUAL_CANDIDATE
PARKED_NO_MEDIATOR_GAIN
PARKED_NO_END_TO_END_PRODUCT_GAIN
FAILED_GOVERNANCE_INVARIANT
FAILED_EXTERNAL_PROVIDER_UNAVAILABLE
```

只有第一项允许把 one-call residual 作为本地 Candidate policy；仍不得升级为 Production、
Schema frozen、formal benchmark PASS 或论文结论。

---

# 6. 状态与错误语义

## 6.1 Treatment-delivery 状态

```text
PASS_SYNTHETIC_TREATMENT_DELIVERY
TREATMENT_NOT_DELIVERED_PROVIDER_UNAVAILABLE
TREATMENT_NOT_DELIVERED_SCHEMA_INVALID
TREATMENT_NOT_DELIVERED_RUNTIME_REJECTED
TREATMENT_NOT_DELIVERED_EXTRA_PASS_NOT_EXECUTED
TREATMENT_DELIVERED_NO_NEW_CANDIDATE
TREATMENT_DELIVERED_WITH_NEW_CANDIDATE
```

terminal receipt 的顶层 `status` 只有达到第 7 节 hard gate 时才可以是：

```text
PASS_SYNTHETIC_TREATMENT_DELIVERY
```

其余状态不得通过空值、降级或 fallback 满足 DG-18 entry gate。

## 6.2 不得混淆的结论

```text
Provider proposal valid
≠ Runtime accepted

Runtime accepted
≠ extra acquisition executed

Extra acquisition executed
≠ new Evidence acquired

New Evidence acquired
≠ opened-dev mediator gain

Synthetic mediator gain
≠ LME quality gain
```

即使 synthetic fixture 全部改善，本 Goal 仍只允许声明 treatment delivery PASS。

---

# 7. Synthetic Hard Gate

## 7.1 必须通过

```text
FixtureCount                              >= 4
EligibleCaseCount                         >= 3
ProviderCallAttempted                     >= 3
SchemaValidHintCount                      >= 2
RuntimeAcceptedHintCount                  >= 2
AdditionalAcquisitionPassCount            >= 1
NewGovernedCandidateCount                 >= 1
SyntheticMissingRequirementImprovedCases  >= 1

AutomaticRetryCount                       = 0
WrongScopeAcceptance                      = 0/N
UnauthorizedAuthorityExpansion            = 0/N
RevokedEvidenceAcceptance                 = 0/N
ModelSelectedFinalEvidence                = 0/N
ModelDeclaredComplete                     = 0/N
CanonicalMutationCount                    = 0
ProductResultChangeCount                  = 0
FormalHoldoutConsumed                     = false
LMEExecuted                               = false
```

`N=0` 不算安全 PASS。至少包含一个 wrong-scope 或 revoked synthetic negative candidate。

## 7.2 兼容门禁

最终 receipt 必须满足当前消费者的精确条件：

```text
schema = milai.dg18.synthetic-treatment-delivery-receipt.v0.1
status = PASS_SYNTHETIC_TREATMENT_DELIVERY
summary.schema_valid_hint_count >= 2
summary.runtime_accepted_hint_count >= 2
summary.additional_acquisition_pass_count >= 1
formal_holdout_consumed = false
```

不得为了让 receipt 通过而放宽
`scripts/run_dg18_r3_shadow.py::_validated_treatment_delivery()`。

## 7.3 通过后的自动状态迁移

PASS 只把下一状态从：

```text
FULL_R3_SHADOW_BLOCKED_BY_TREATMENT_GATE
```

变为并立即执行：

```text
FULL_R3_OPENED_DEV_SHADOW_AUTHORIZED
→ S4
```

S4 mediator gate PASS 后，本文已经授权自动进入 S5–S7；不再要求额外用户确认。

仍不自动授权：

```text
formal holdout
R5 two-round residual
production / remote MCP release
paper or novelty claim
```

---

# 8. Tests 与验证

## 8.1 最窄测试

至少覆盖：

```text
fixture product/scorer separation
flat ResidualCueProposal parse
unknown requirement rejected
Runtime-derived provenance/rationale/source/time
accepted hint triggers one extra pass
NO_ACTION triggers zero extra passes
invalid hint triggers zero retry and zero pass
wrong-scope/revoked candidate rejected
new/repeated candidate accounting
AcquisitionState transition
receipt compatibility validator
fresh-output immutability
```

## 8.2 扩大顺序

```text
1. focused DG-19 unit tests
2. existing focused DG-18 residual/provider tests
3. Ruff on changed files
4. strict mypy on changed typed modules
5. real vLLM synthetic shadow
6. receipt compatibility check
7. S4 opened-dev shadow
8. S5 focused Runtime application/integration tests
9. Runtime full gate when product code changes
10. MCP tests
11. OpenWorker focused tests and real local composition smoke
12. S7 matched opened-dev evaluation
```

若只新增 `evals/dg19`、runner、fixture 和 tests，不要求为了文档完整性重跑 516-case
PostgreSQL full gate。S5 一旦修改 Runtime 产品行为，必须运行 fresh PostgreSQL full gate、
MCP suite 与受影响的 OpenWorker suite；不要拿 S3 的旧 gate 代替新代码验证。

## 8.3 不运行

```text
formal holdout
Reader model / prompt / answer-normalization changes
R5 two-round controller
production or remote MCP tests
```

DG-17 不整体重跑；S4/S7 只消费已冻结的 deterministic archive 与 opened-dev block。
S7 允许使用已经固定的 reader 做 matched comparison，但不在本 Goal 调 prompt、模型或
答案后处理。

---

# 9. 开发原则

## 9.1 可用性与效率优先

本 Goal 的可用性目标是：

> **一个真实 vLLM cue 能被 MiLA Runtime 接受，并在同一次 synthetic resolve 中触发
> 一次额外 acquisition；不是再增加一层抽象或审计文档。**

优先复用当前实现。避免：

```text
新的 provider abstraction
新的 residual domain hierarchy
多 transport parity
多轮 agent loop
通用 workflow engine
新数据库对象
重复 policy validator
```

## 9.2 减少防御性编程

只在真实边界验证：

```text
fixture/product-label boundary
provider typed output boundary
Runtime scope/permission/budget boundary
fresh artifact boundary
```

禁止：

```text
同一输出多套 parser
invalid JSON regex rescue
catch-all + silent fallback
自动 retry
provider 失败后换模型
case-specific cue patch
用 Reader 猜 missing Evidence
```

失败时保留一个 typed first-loss-stage，然后只调试该项。

## 9.3 计算资源

独立 case 可以受控并行；默认从低并发开始，以 provider 和数据库实测为准。并发不得：

```text
增加每 case provider calls
改变 seed
引入 retry
共用 mutable AcquisitionState
覆盖 artifact directory
```

## 9.4 审查最小化

S0–S7 不要求逐阶段独立审查或重复授权。每个阶段以 executable gate 自动进入下一阶段，
只在 S8 生成一次整体 disposition。

只有以下情况才调用 [`codex_sol_xhigh.md`](./codex_sol_xhigh.md) 做一次独立审查：

```text
receipt 与 executable trace 冲突
需要修改 Runtime safety owner
出现本文未授权的 Schema / MCP / architecture scope expansion
准备申请 formal holdout、R5 或生产发布
```

---

# 10. Deliverables

必须交付：

1. 本 Goal 文档；
2. synthetic fixture；
3. synthetic treatment evaluator；
4. one-command runner；
5. focused tests；
6. sealed product trace；
7. score；
8. terminal receipt；
9. 必要时的最小 failure ledger；
10. S4 opened-dev residual shadow 与 mediator score；
11. 条件执行的 S5 Runtime one-call residual integration；
12. 条件执行的 MCP/OpenWorker local composition receipt；
13. 条件执行的 matched opened-dev quality/cost report；
14. 一段 terminal disposition。

S3 treatment receipt 状态只能是以下之一：

```text
PASS_SYNTHETIC_TREATMENT_DELIVERY
FAILED_PROVIDER_DELIVERY
FAILED_RUNTIME_ACCEPTANCE
FAILED_ADDITIONAL_ACQUISITION_EXECUTION
FAILED_GOVERNANCE_INVARIANT
```

上述是 S3 treatment receipt 的状态。DG-19 最终状态使用 S8 定义的 disposition。不要使用
笼统的 `BLOCKED` 掩盖具体失败层，也不要因为 S3 PASS 就提前把整个 DG-19 标记为完成。

---

# 11. 停止条件

出现以下任一情况，立即停止当前 case，定位单项 owner：

```text
automatic retry > 0
provider/model identity drift
gold/scorer field reaches provider or acquisition
scope or authority expands
revoked Evidence accepted
model selects final Evidence
model declares COMPLETE
canonical mutation occurs
S0–S4 shadow product response changes
S5 default-disabled or ineligible path changes unexpectedly
formal holdout opened
```

若 provider proposal 合法但没有新 candidate，不修改 prompt、candidate cap、Binding、
Sufficiency 和 scorer 五个层面碰运气；只记录：

```text
TREATMENT_DELIVERED_NO_NEW_CANDIDATE
```

并针对该 fixture 的 acquisition channel 做单项检查。

满足第 7 节 synthetic hard gate 后，自动进入 S4。满足 S4 mediator gate 后，自动进入
S5–S7。只有完成 S8 terminal disposition，或命中明确的安全/外部阻断条件，本 Goal 才停止。

---

# 12. 最终成功定义

DG-19 的所有终态都必须先能够用 executable evidence 证明：

```text
1. 真实 vLLM 产生多个 flat ResidualCueProposal；
2. Proposal 通过 Pydantic 和 Runtime validation；
3. Runtime 派生控制字段，而不是信任 provider；
4. 至少一次额外 acquisition 确实执行；
5. 至少取得一个新的、通过治理过滤的 candidate；
6. 至少一个 synthetic missing requirement 得到改善；
7. 无 retry、无 hidden fallback、无产品结果变化、无 canonical mutation；
8. receipt 可被现有 DG-18 R3 entry gate 接受；
9. synthetic 阶段未消费 LME 或 formal holdout。
```

若 S4 mediator gate 通过并进入详细开发，`PASS_LOCAL_MCP_ONE_CALL_RESIDUAL_CANDIDATE`
还必须证明：

```text
10. one-call residual 已进入真实 Runtime read path；
11. deterministic COMPLETE 保持零 controller call；
12. MCP 与 OpenWorker local composition 使用同一 memory semantics；
13. provider/invalid/NO_ACTION 失败保持 typed deterministic outcome；
14. fresh Runtime、MCP、OpenWorker 相关测试通过；
15. matched opened-dev quality 不劣于 deterministic-only；
16. formal holdout、R5 与生产发布仍未执行。
```

PASS 时允许的结论是：

> **MiLA 的 minimal residual provider contract 已完成 synthetic treatment delivery，
> 并在本地 MCP/OpenWorker Candidate 路径中以 one-call、one-pass、zero-retry 方式完成
> opened-dev 验证。**

若 S4 或 S7 门禁失败，允许的结论分别收缩为：

```text
PARKED_NO_MEDIATOR_GAIN
PARKED_NO_END_TO_END_PRODUCT_GAIN
```

这些是有证据的正常终态，不得为了追求 PASS 放松 Binding、Sufficiency 或治理门禁。

仍禁止声明：

```text
Residual refinding improves formal LME holdout
MiLA has general quality improvement
R4 is production-ready
Schema is frozen
Production or remote MCP is ready
Paper or novelty claim is established
```
