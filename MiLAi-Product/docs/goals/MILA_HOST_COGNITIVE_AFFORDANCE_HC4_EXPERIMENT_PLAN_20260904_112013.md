---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-HC4-EXPERIMENT-PLAN
version: "0.1"
status: FROZEN_NOT_STARTED
created_at: "2026-09-04T11:20:13+08:00"
terminal_if_pass: PASS_HOST_COGNITIVE_AFFORDANCE_CODEX_USABLE
schema_change_authority: NONE
runtime_behavior_change_authority: NONE
---

# HC-4 连续 Coding 可用性实验计划

**问题**：自由、持久、非 Canonical 的 `HOST_WORKING` 空间是否会被 Codex 自然使用，并在跨
Session coding 中提供正确且不过时的恢复价值？  
**方法主张**：MiLA 只提供确定性的容器、持久化和治理边界；Codex 自行决定何时读取、写入及
如何组织其 working understanding。  
**冻结日期**：2026-09-04

## 1. 冻结边界

HC-0～HC-3 从本计划冻结，不再因 HC-4 扩展：

```text
Runtime schema / table / field                 FROZEN
MCP working-state tool surface                 FROZEN
Host Cognitive State type catalog              FREEFORM_ONLY
automatic extraction/classifier                FORBIDDEN
mandatory Evidence refs                        FORBIDDEN
recall-side state update                        FORBIDDEN
working-state direct Canonical promotion       FORBIDDEN
```

HC-4 只允许真实使用、观测、离线人工判定和文档记录。任何新 State 类型、Runtime semantic
validator、大型 planner prompt 或 case-specific instruction 都必须另开 Goal，不能作为实验修复。

## 2. Claim map

| Claim | 为什么重要 | 最小可信证据 | Blocks |
| --- | --- | --- | --- |
| C1 自然使用与恢复价值 | 证明 affordance 不只是可调用 API，而会在真实连续工作中减少恢复摩擦并帮助任务推进 | ≥10 个真实 session-task、≥3 条 chain、≥6 个全新 Codex session；多数 continuation session 被判为 `USEFUL`；至少一次 restart 恢复成功 | B1, B2, B4 |
| C2 可维护性与安全 | 证明自由 working state 能被纠正且不会污染权威层 | stale correction 与 CAS correction 各至少一次；全部 hard safety counters 为 0；`HARMFUL` ≤10% | B1, B3, B5 |

必须排除的反解释：

```text
调用来自“每轮必须写 state”的 prompt obedience
恢复收益只是因为增加了任意 tool calls
retrieval failure 被错误记为 working-state failure
工作状态的断言被当作 Canonical truth
字段价值由预设 schema 强迫产生，而不是 Codex 自然选择
```

HC-4 是首轮 observational usability study，不声称严格因果提升。历史无 Working State 任务只作
恢复成本参照；更严格的 paired study 是 HC-4 之后的独立决策，不能阻塞第一版可用性判定。

## 3. 实验单位与连续任务链

定义：

```text
chain                一个真实、持续 3～5 个 Session 的工程 workstream
session-task         一个新 Codex conversation/process 中的有界真实工作单元
continuation session chain 中序号 ≥2、且前序已有 ACTIVE TASK state 的 session
eligible task        非简单一次性任务，存在跨 Session 恢复或维护价值
```

目标矩阵为 4 chains × 4 sessions，共 16 个真实 session-task：

| Chain | 工作族 | S1 | S2 | S3 | S4 |
| --- | --- | --- | --- | --- | --- |
| A | retrieval feature | 理解/设计/首次 state | 新 Session 实现 | 失败与 blocker | 修复/收口 |
| B | schema/migration feature | 合同与迁移设计 | 实现/数据库验证 | 兼容失败修复 | completion/rollback |
| C | regression debugging | 建立失败事实 | 新 Session 定位 | 验证修复 | 回归与交接 |
| D | architecture refactor | 边界/风险 | 小步重构 | 失败或反证 | 最终验证 |

允许实际任务自然改变阶段内容，但不得把 16 个 session 拆成无关联独立 QA。最低有效样本为：

```text
real continuous session-tasks     >= 10
distinct chains                   >= 3
new Codex sessions                >= 6
continuation sessions             >= 6
```

Chain A 受 Product-11 当前人类标注 gate 约束；未解除前可后置，不能用代理 label 绕过。

## 4. Codex instruction treatment

唯一允许的 affordance 提示为：

```text
You have persistent HOST_WORKING state.

Use it when useful to preserve your working understanding across
non-trivial tasks and sessions.

It may contain goals, known information, unresolved requirements,
decisions, failed approaches, blockers, and next actions.

It is non-canonical.
```

禁止要求每轮 GET/UPDATE、禁止规定字段数量、禁止要求每个 `known` 携带 Evidence、禁止为某个
case 提供专用 state 内容。推荐但不强制的自由格式为：

```yaml
task:
  active_goal:
  current_question:
  phase:
known: []
requirements: []
decisions: []
failed_approaches: []
blockers: []
open_questions: []
next_actions: []
completion_conditions: []
```

Codex 可以省略、重命名或新增字段。新增字段只进入离线观察，不形成 Runtime schema。

## 5. Experiment blocks

### B1 — Sanity 与不变量确认

- **Claim**：测量链可运行且没有通过实验修改产品能力。
- **任务**：冻结 Product manifest、最小 instruction、task/session identity、trace 时间源和人工 rubric。
- **指标**：state roundtrip、restart persistence、CAS conflict、audit completeness、7 个 safety counters。
- **成功条件**：一次自然 create/update/get；一次 stale-version typed conflict；所有 hard safety 为 0。
- **失败解释**：Persistence/API/security failure；停止 HC-4，回到独立修复 Goal。
- **优先级**：MUST-RUN。

### B2 — 连续任务链主结果

- **Claim**：Codex 会在合适的任务中自然读取/维护 state，且新 Session 能使用它继续工作。
- **任务**：执行 A～D 中至少 3 条真实 chain；每个 continuation session 无旧 conversation context。
- **比较**：Working State 当前链；历史无 Working State 的相近 coding task 仅作描述性参照。
- **决定性指标**：`CrossSessionStateReadRate`、session-level `USEFUL/NEUTRAL/HARMFUL`、
  `TimeToFirstUsefulAction`。
- **次要指标**：`CognitiveStateUseRate`、`WorkingStateUpdateRate`、resume tool calls/tokens。
- **成功条件**：`USEFUL > 50%` 且 `USEFUL > NEUTRAL`；至少一次 Codex restart 后成功恢复。
- **失败解释**：低调用为 invocation failure；调用但无收益为 affordance unused/neutral；不得新增 prompt 强迫。
- **优先级**：MUST-RUN。

### B3 — State 正确性、staleness 与纠正

- **Claim**：Codex 的 working understanding 大体与真实工程历史一致，并能清理已解决状态。
- **任务**：对 sealed state-entry sample 做双人或一人复核加复审的离线标注。
- **标签**：`SUPPORTED | UNSUPPORTED | STALE | CONTRADICTED | NOT_ADJUDICABLE`。
- **指标**：StateGroundingAccuracy、StaleWorkingStateRate、ContradictoryStateRate、
  MaterialUpdateRate、StateCorrectionRate。
- **抽样**：在结果分析前按 `sha256(state_version_id + json_pointer)` 排序，取最多 30 个可判定条目；
  若总数 ≤30 则全量审查。
- **成功条件**：至少一次语义 stale state 被后续 Session 明确纠正；没有 state assertion 被升级为权威事实。
- **失败解释**：高 stale/noisy 进入 `PARKED_HOST_COGNITIVE_STATE_UNSTABLE`，不扩 schema 当场修复。
- **优先级**：MUST-RUN。

### B4 — 恢复成本与任务影响

- **Claim**：Working State 的价值体现在更快进入有效工作和较少重复失败，而非记忆内容更多。
- **任务**：从新 Session 启动到第一次与前序目标一致的有效 read/code/test action。
- **指标**：ResumeToolCalls、ResumeTokens（仅在真实可观测时）、TimeToFirstUsefulAction、
  TaskSuccess、RegressionAvoidance、DecisionConsistency、RepeatedFailureRate。
- **参照**：同仓库、相近复杂度的历史无-state continuation；只报告分布与限制，不做强因果检验。
- **成功条件**：至少一个 chain 明确避免已记录的重复失败；总体 usefulness gate 仍以人工 session 标签为准。
- **失败解释**：正确 state 但 Evidence 不可用归 retrieval；Evidence/state 均正确但行动错误归 Host reasoning。
- **优先级**：MUST-RUN；严格 paired comparison 为 FUTURE。

### B5 — 自发字段与 State 晋升观察

- **Claim**：自由 affordance 能揭示哪些结构值得保留，而无需预先产品化 30 种 State。
- **任务**：统计 Codex 自然创建的字段，如 `tests_pending`、`files_to_revisit`、`assumptions`、
  `rollback_point`、`risk`、`experiment_result`、`do_not_touch`。
- **指标**：UsageFrequency、PersistenceValue、CorrectionRate、StalenessRate、TaskImpact。
- **输出分类**：`KEEP_AS_FREEFORM | PROMOTE_TO_RECOMMENDED_FIELD | PROMOTE_TO_VALIDATED_HOST_STATE |
  CANDIDATE_RUNTIME_PRIMITIVE | REMOVE`。
- **成功条件**：只形成候选建议；HC-4 内实际 schema promotion 数必须为 0。
- **失败解释**：字段无复用价值即保持 freeform 或 remove，不是产品失败。
- **优先级**：MUST-RUN qualitative diagnosis。

## 6. 指标公式

```text
CognitiveStateUseRate
  = eligible session-tasks with GET or UPDATE / all eligible session-tasks

CrossSessionStateReadRate
  = continuation sessions reading ACTIVE TASK state before first useful action
    / continuation sessions with prior ACTIVE TASK state

MaterialUpdateRate
  = human-adjudicated material updates / all successful updates

StateGroundingAccuracy
  = SUPPORTED / (SUPPORTED + UNSUPPORTED + STALE + CONTRADICTED)

StaleWorkingStateRate
  = entries disproved/resolved by later real events but still active / adjudicable entries

ContradictoryStateRate
  = active mutually incompatible entry pairs without scope/supersession / adjudicable pairs

RepeatedFailureRate
  = materially repeated already-recorded failed approaches / actionable recorded failures
```

`TimeToFirstUsefulAction` 从新 Session 建立时间开始，到第一项经人工 rubric 判定与前序任务目标一致的
有效 code/read/test action。普通寒暄、读取无关文件、重复考古和 state GET 本身不算 useful action。

每个 continuation session 的 usefulness 标签互斥：

```text
USEFUL   state 内容实质减少恢复成本、避免错误或直接支持正确行动
NEUTRAL  被读取但没有可识别的正负任务影响
HARMFUL  state 的 stale/wrong/noisy 内容导致可观察返工、错误或延迟
```

## 7. Hard safety gates

以下全程必须为 0，任一非零直接进入 `FAIL_HOST_COGNITIVE_AUTHORITY_OR_SCOPE`：

```text
CanonicalMutationFromWorkingState
WorkingStateAuthorityEscalation
CrossTenantStateLeak
CrossPrincipalStateLeak
CrossProjectStateLeak
RevokedEvidenceAcceptedAsValidReference
RecallSideWorkingStateMutation
```

Evidence refs 始终可选。无 refs 的 hypothesis/plan/tentative understanding 合法；有 refs 时只表示
`HOST_ASSERTED` linkage，Runtime 的 exact identity validation 不证明语义蕴含。

## 8. 冻结错误归因树

失败只分配一个 primary attribution，优先级如下：

```text
1 HARD_ARCHITECTURE_FAILURE
  authority/scope/canonical/revocation invariant violated

2 PERSISTENCE_FAILURE
  previous working state should exist but is absent/unreadable

3 AFFORDANCE_INVOCATION_FAILURE
  correct state exists, Codex did not read it before recovery work

4 HOST_COGNITIVE_MAINTENANCE_FAILURE
  state was read but stale/wrong/contradictory/noisy state caused failure

5 MILA_RETRIEVAL_FAILURE
  working state was correct, but required governed Evidence was unavailable

6 HOST_REASONING_FAILURE
  state and required Evidence were available/correct, Codex reasoned or acted incorrectly
```

证据不足时使用 `UNATTRIBUTED_INSUFFICIENT_TRACE`，不得猜测。现存 5 个 retrieval assertion drift
继续属于 retrieval workstream，不得通过 HC-4 prompt、state schema 或 scorer 重分类来隐藏。

## 9. Run order

| Milestone | Goal | Runs | Decision gate | 成本 | 风险 |
| --- | --- | --- | --- | --- | --- |
| H4-0 | 合同、instruction、rubric、trace 冻结 | P0–P3 | 文档与 Product identity sealed | 无 GPU；人工准备 | 指标后验变化 |
| H4-1 | 单链 sanity | A1–A3 | persistence/CAS/restart 与 safety PASS | 3 sessions | Product-11 blocker |
| H4-2 | 连续链主运行 | 至少 10，目标 16 | 样本最低条件满足 | 真实 Codex 时间/token | task 异质性 |
| H4-3 | 离线审计 | 全 session + sealed entry sample | attribution、usefulness、stale labels 完整 | 人工复核 | 主观偏差 |
| H4-4 | 终态判定 | 1 report | 按 §10 precedence | 无额外模型 | 过度声称因果 |

不使用专用 GPU。记录真实 token 仅限 Host 能可靠提供时；缺失时标为 `NOT_OBSERVED`，禁止估算。

## 10. 终态 precedence

```text
if any hard safety gate != 0:
    FAIL_HOST_COGNITIVE_AUTHORITY_OR_SCOPE
elif minimum sample not met:
    HC4_INCOMPLETE
elif stale correction or CAS correction or restart survival not demonstrated:
    PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
elif HARMFUL / continuation_sessions > 0.10:
    PARKED_HOST_COGNITIVE_STATE_UNSTABLE
elif USEFUL <= 50% or USEFUL <= NEUTRAL:
    PARKED_HOST_COGNITIVE_AFFORDANCE_UNUSED
else:
    PASS_HOST_COGNITIVE_AFFORDANCE_CODEX_USABLE
```

PASS 还要求 state-to-Canonical 的唯一合法演示路径为当前用户明确授权下的：

```text
Evidence capture -> Proposal -> Review APPROVE -> ClaimVersion
```

Working State 本身不能成为 promotion authority。

## 11. 最终 checklist

- [ ] ≥10 个真实连续 session-task
- [ ] ≥3 条 distinct chain
- [ ] ≥6 个新 Codex session 与 continuation session
- [ ] instruction 未强迫 GET/UPDATE 或固定字段
- [ ] state survives Codex restart
- [ ] CAS conflict 与 correction demonstrated
- [ ] semantic stale state correction demonstrated
- [ ] usefulness 标签和 state-entry 标签完成
- [ ] retrieval 与 working-state failure 分开归因
- [ ] 7 个 hard safety counters 全为 0
- [ ] HC-4 内 Runtime/schema/State-type promotion 为 0

