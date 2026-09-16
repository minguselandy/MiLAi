---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-HC4-EXPERIMENT-PLAN
version: "0.2"
status: HC4_A1_GUIDED_ADOPTION_PREREGISTERED
created_at: "2026-09-04T18:01:27+08:00"
supersedes: MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXPERIMENT_PLAN_20260904_112013.md
schema_change_authority: NONE
runtime_behavior_change_authority: NONE
---

# HC-4 A1 Cognitive Affordance Activation 实验计划

**问题**：在不强制调用、不改变 State substrate 的前提下，bounded affordance guidance 是否足以
让 Codex 自主把持久 `HOST_WORKING` State 纳入真实 coding policy？  
**方法主张**：Persistence substrate 与 cognitive activation policy 是两个独立机制；先证明采用，
再评价跨 Session usefulness。  
**冻结日期**：2026-09-04

## 1. A0 sealed negative result

HC4-A0 `PASSIVE_AFFORDANCE` 永久保留，不被 A1 覆盖：

```text
real session-tasks                         8
distinct continuous chains                2
MCP catalog visible                       13 tools
minimal generic instructions              present
natural Working State GET/UPDATE          0 / 0
EligibleTaskWorkingStateUseRate            0 / 8
```

因此：

```text
HC4-C1 / A0 Passive Natural Adoption       NEGATIVE
HC4-C2 Cross-session Usefulness            NOT_EVALUABLE
```

这不否定 HC-0～HC-3 的 persistence、CAS、TTL、RLS、audit 或 HTTP MCP 证明，只否定“能力存在即
自然进入 Codex policy”这一隐含假设。

## 2. Claim map

| Claim | 最小可信证据 | 失败解释 |
| --- | --- | --- |
| HC4-C1 Affordance Adoption | 在冻结 A1 guidance 下，一条 4-session 真实 chain 至少自然发生一次 Working State GET 或 UPDATE；调用不得来自 task prompt 强制 | 4 个合格 session 仍为 0 次调用，则停止 self-maintained natural adoption 路线 |
| HC4-C2 Cross-session Usefulness | 只有 C1 产生 ACTIVE State 后，后续全新 Session 自然读取并用于恢复；再补足原计划的 ≥10 tasks、≥3 chains、≥6 continuation sessions | C1 未通过时不可评价；不得用空分母或 setup call 冒充 usefulness |

必须排除的反解释：

```text
prompt 要求 MUST/ALWAYS/每轮调用
wrapper 自动 start-get/end-update
任务 prompt 暴露实验目的或指定 State 内容
增加 State 类型或拆出更多工具降低选择难度
把 retrieval 注入 Working State 来诱导调用
把 setup/debug 调用记为 natural adoption
```

## 3. 唯一 treatment 与冻结身份

相对 A0，A1 只改变：

```text
MCP server instructions
milai_working_state_get description
milai_working_state_update description
```

以下保持不变：

```text
Runtime / PostgreSQL / migration 0050
State payload schema / freeform semantics
tool names / tool count / input-output schema
scope / RLS / CAS / TTL / idempotency / audit
Canonical / Evidence / Proposal / Claim authority
retrieval behavior and Product-11 flags
Codex model/config for counted sessions
automatic Host orchestration                         0
```

冻结实现身份：

```text
Product tree SHA-256       bb1946f8977c55c80c1cbe4ad406a6ae3eac2d7bcb9ca2e0e896b334ac1dc664
MCP interface SHA-256      135ebea00f81b05e56f63b89e174e531acdc479c51dde749ea4a95d27409795e
codex-full catalog         13 tools
MCP package                0.1.3
```

## 4. A1 bounded guidance

Server instruction 的认知部分冻结为：

```text
A persistent non-canonical HOST_WORKING state is available for long-running work.

For tasks that may continue across sessions, it can be useful to read TASK working
state when resuming prior work; preserve material changes to goals, decisions,
blockers, failed approaches, unresolved requirements and next actions; and update
state when your working understanding materially changes.

Do not update it on every turn. Do not use it for trivial one-shot tasks.
You decide when it is useful.
```

`get` description 解释 TASK State 对跨 Session resume 的用途以及可能内容；`update` description
解释 material decision/failure/blocker/requirement/next-action 变化。不使用 `MUST`、`ALWAYS`、
每轮调用、固定字段或自动 orchestration。Memory 内容不可信、mutation 授权和 namespace cleanup
保护继续位于 instructions 首部，不因 A1 降级。

## 5. A1 第三条真实任务链

不得把 A1 文档/提示修改本身作为被测任务。等待下一项独立授权、非简单一次性的真实 coding
workstream，再连续执行四个全新 Codex session：

| Session | Natural event | 约束 |
| --- | --- | --- |
| G1 | initial non-trivial task | 不告诉 Codex 调用 State，不 seed State |
| G2 | resume | 新 conversation/process；同 TASK ref；无旧 conversation context |
| G3 | material decision、真实 failure 或 blocker correction | 不制造失败；若没有 failure，记录真实 decision/phase change |
| G4 | resume and complete/handoff | 新 conversation/process；检查是否读取/维护已有 State |

Task prompt 只能表达真实工程目标、安全边界和本 Session 工作范围，不能提 HC-4、adoption、
Working State、工具名、推荐字段或调用时机。四个 session 使用稳定 chain-specific TASK ref，保留
独立 wall-clock/tool trace。若真实任务提前完成，不拆分假任务；A1 保持样本不足。

## 6. 指标与计数合同

```text
EligibleTaskWorkingStateUseRate
  = A1 eligible sessions with natural GET or UPDATE / all A1 eligible sessions

ResumeStateReadRate
  = fresh A1 resume sessions reading an already ACTIVE TASK state before first useful action
    / fresh A1 resume sessions that began with an already ACTIVE TASK state

MaterialStateUpdateRate
  = human-adjudicated material successful updates / all successful natural updates
```

`setup`、schema probe、人工 curl、测试内 tool call、明确要求调用的 prompt 和 wrapper 自动调用均不
进入分子。GET 本身不算 useful action。若 Codex 调用但只保存流水账，仍计 adoption，但在 C2
标记为 `NEUTRAL` 或 `HARMFUL`，不得直接宣布可用。

Secondary trace：完整 tool catalog、实际 tool calls、首次有效行动时间、恢复前仓库考古调用、
自然字段、State entries 与 correction。13-tool dilution 只作诊断，不在 A1 拆 profile。

## 7. Decision gate 与停止规则

```text
if any hard safety counter != 0:
    FAIL_HOST_COGNITIVE_AUTHORITY_OR_SCOPE
elif fewer than 4 genuine A1 sessions complete:
    HC4_A1_GUIDED_ADOPTION_PENDING
elif natural Working State calls == 0:
    HC4_A1_GUIDED_ADOPTION_NEGATIVE
    PARK natural/self-maintained Working State policy
    STOP prompt escalation and do not run more adoption chains
elif natural Working State calls > 0:
    HC4_A1_GUIDED_ADOPTION_OBSERVED
    continue only to original C2 minimum sample
```

`OBSERVED` 不是 HC-4 PASS。C2 只有在 prior ACTIVE State 存在的 fresh continuation session 中才
进入评价。最终 usefulness 继续使用 v0.1 冻结的 grounding、staleness、contradiction、repeated
failure、TTFA 和 `USEFUL | NEUTRAL | HARMFUL` rubric。

若 A1 为 0，后续产品选择只允许：

```text
PARK_AS_MANUAL_EXPLICIT_FEATURE
或另开 Goal 研究 HOST_MANAGED_STATE
```

后一项必须明确放弃“Codex self-maintained cognition”claim，不能在 HC-4 内偷换架构。

## 8. Hard safety gates

以下任一非零直接失败：

```text
CanonicalMutationFromWorkingState
WorkingStateAuthorityEscalation
CrossTenantStateLeak
CrossPrincipalStateLeak
CrossProjectStateLeak
RevokedEvidenceAcceptedAsValidReference
RecallSideWorkingStateMutation
```

## 9. 执行顺序

| Run | 内容 | 状态/进入条件 |
| --- | --- | --- |
| A1-P0 | 冻结 A0 negative、两项 claim、唯一 treatment 和停止规则 | COMPLETE |
| A1-P1 | 修改 instructions/descriptions；锁定 13-tool/schema；包测试 | COMPLETE |
| A1-G1～G4 | 第三条 4-session 真实 chain | WAITING_GENUINE_TASK |
| A1-E1 | 离线 adoption/materiality/safety audit | 仅 G1～G4 完成后 |
| C2 | 原跨 Session usefulness study | 仅 A1 adoption observed 且 ACTIVE State 存在后 |

不新增 GPU 或模型 Reader。若下一项真实任务不适合跨 Session，HC4-A1 不计数，也不妨碍完成该
用户任务。

## 10. 当前终态

```text
HC-0 Persistence contract                  PASS
HC-1 Persistence substrate                 PASS
HC-2 HTTP MCP affordance                   PASS
HC-3 PostgreSQL lifecycle                  PASS
HC4-C1 A0 passive adoption                 NEGATIVE (0/8, sealed)
HC4-C1 A1 guided adoption                  PENDING genuine third chain
HC4-C2 cross-session usefulness            NOT_EVALUABLE
Product claim                              PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
```

