---
document_id: MILA-MEMORY-ACTIVATION-LAYER-DESIGN-PLAN
version: "0.4"
status: SUBORDINATE_TO_DEVELOPMENT_MASTER
date: 2026-09-04
schema_change_authority: NONE
canonical_change_authority: NONE
next_authorized_action: MCP_BASELINE_FIRST
supersedes: MILA-MEMORY-ACTIVATION-LAYER-DESIGN-PLAN@0.3
---

# MiLA Memory Activation Layer 设计开发规划

> 总览入口：`MILA_HOST_COGNITIVE_MEMORY_ACTIVATION_RECONCILIATION_总设计开发文档.md`。

> v0.4 定位：Activation 与 reconciliation 仍是目标架构，但不再先于 Memory MCP 产品
> 基线开发。开发采用 Milestone boundary review；复杂 Event/Basis 正确性按真实 failure、
> 明确指标或 Research Mode claim 增量进入。

## 1. v0.4 定位与既有结论

HC4-A0/A1 的负结果不仅说明 Codex 不会稳定地主动调用 Working State 工具，还暴露了两种
不同能力：

```text
Memory operation
  显式历史需求 -> retrieve/capture/revoke

State transition recognition
  失败、决策、blocker、hypothesis、phase 变化 -> 调整认知状态
```

后者是隐式 meta-cognitive action，不能继续依赖：

```text
事情发生
  -> Codex 自己意识到 State 已变
  -> Codex 自己调用 working_state_update
```

v0.3 已将长期路线改为：

> **Event-grounded checkpoint-based Host Cognitive State reconciliation**

```text
真实执行事件
  -> Host 记录 Event，并将 State 判定为 DIRTY
  -> 到达 checkpoint/resume boundary
  -> Codex 对 Previous State + Frozen Event Window 生成 StateDelta
  -> Host 验证并合并 Delta
  -> MiLA 以 CAS append 新的完整 Working State
```

本规划不独立授权部署、schema 变更或 HC4 效果声明。MA-1 Session Resume launcher 已有
候选实现；其后续开发与验收由总设计 v0.3 的 Milestone B 管理。

## 2. 问题边界

MCP 工具链分为四层：

```text
Discoverability  模型能看到工具
Selection        模型判断现在要不要调用
Execution        参数、认证、调用与结果正确
Workflow         调用后知道下一步
```

当前证据：

```text
Discoverability  PASS
Selection        NEGATIVE for generic resume
Execution        PASS for explicit Working State GET
Workflow         MCP guidance 已具备，但只能在首次调用后生效
```

Activation Layer 只解决 Selection/WHEN；Reconciliation Layer 解决事件边界上的 State
调整。两者都不复制 MCP Execution，不成为新的 authority plane。

## 3. State 定位与核心分工

```text
Evidence / HostExecutionEvent
  = 真实观察与执行记录

Canonical State
  = MiLA 经治理后正式接受的长期状态

RetrievalContinuationState
  = frontier / seen identities / route cursor 等机械状态

Host Cognitive State
  = Codex 对当前任务的可失效、可重建认知缓存
```

因此 Working State 丢更新不等于真实执行记录永久丢失；下次可以在 Event/Evidence 保留区间
内重新 reconcile。若事件已被清理或存在 cursor gap，必须报告 `EVENT_BASIS_GAP`，不得声称
完整重建。

职责冻结为：

```text
WHEN TO RECONCILE = deterministic Host policy
WHAT CHANGED      = Codex semantic comparison
APPLY DELTA       = deterministic Host code
STORE / CAS       = MiLA governed persistence
```

Host 可以确定 session start/end、task switch、compaction、文件修改和测试/命令结果；Codex
负责判断这些事件对 goal、requirement、hypothesis、decision、blocker 和 next action 的语义
影响。MiLA Runtime 不解释这些字段。

## 4. Activation 模式

`activation_mode` 是 MiLA Host policy，不是 MCP 标准 `ToolAnnotations` 字段，也不能由模型
作为工具参数提交。

```text
AUTO
  模型选择；best effort

HOST
  Host 生命周期或高精度 gate 决定；用于必须发生的操作

EXPLICIT
  当前用户明确意图是最低前提；Runtime 权限仍须独立通过
```

### 4.1 工具归类

| Tool | Activation | 约束 |
| --- | --- | --- |
| `milai_working_state_get` | HOST | 新 Session 对绑定 TASK 读取一次 |
| `milai_working_state_update` | HOST | Host 触发 reconciliation；Codex 只生成 WHAT CHANGED |
| `milai_memory_resolve` | HOST/AUTO | 明确历史依赖 Host 预取；探索/continuation 由 Codex 决定 |
| `milai_memory_get` | AUTO | 已知 identity 后精确读取 |
| `milai_evidence_capture` | HOST/EXPLICIT | 当前用户明确要求记住/捕获 |
| `milai_proposal_create` | EXPLICIT | 当前用户授权的 Canonical change workflow |
| `milai_proposals_list/get` | AUTO | 只读治理检查 |
| `milai_memory_review` | EXPLICIT | 当前用户授权的治理决定 |
| `milai_evidence_revoke` | EXPLICIT | 当前用户授权撤销 |
| `milai_deletion_status_get` | AUTO | 已知 deletion request 后只读查询 |
| `milai_namespace_cleanup_submit` | EXPLICIT | 当前会话明确要求 namespace cleanup |
| `milai_namespace_cleanup_status` | AUTO | 已知 cleanup job 后只读查询 |

## 5. 总体架构

```text
                         REAL EXECUTION
                               |
                               v
                   append-only HostExecutionEvent
                               |
                               v
                         derived DIRTY
                               |
                               v
                  Checkpoint / Resume Host Gate
                               |
             +-----------------+-----------------+
             |                                   |
             v                                   v
     Previous Working State            Frozen Event Window
             |                                   |
             +-----------------+-----------------+
                               |
                               v
                        Codex StateDelta
                               |
                               v
                    Host validate + apply
                               |
                               v
                  MiLA State + Basis CAS append
```

不会在每个 turn 自动 resolve。激活梯度冻结为：

```text
L0 NONE
L1 TASK STATE PREFETCH
L2 HISTORICAL MEMORY PREFETCH
L3 CODEX RESIDUAL CONTINUATION
```

详细 Event、StateBasisCursor、StateDelta、dirty/gate、失败恢复和验收合同见
`MILA_EVENT_GROUNDED_HOST_COGNITIVE_STATE_RECONCILIATION_设计开发规划.md`。

## 6. Legacy Research/Hardening 分解

本节保留原严格研究路径，供 Research Mode 或真实 failure 触发的 hardening 使用，不是当前
Memory MCP Baseline 的前置授权链。

### MA-0 — Activation Contract

目标：冻结 `AUTO/HOST/EXPLICIT`、工具归类、安全边界和指标。

交付：

- Activation Policy 合同；
- ADR；
- 失败归因树；
- 阶段授权与停止条件。

Gate：合同审查通过后，才允许复核 MA-1 候选。

### MA-1 — Session Resume Gate

目标：新 Codex Session 在首次推理前确定性读取 TASK Working State。

```text
resolve cwd/repo/worktree/branch
  -> obtain stable task_ref
  -> start/bind private HTTP MCP
  -> Host call working_state_get(TASK)
  -> validate and bound State
  -> bootstrap as non-canonical data
  -> launch Codex
```

必须满足：

- GET 成功前 Codex 不启动；
- `ABSENT/EXPIRED/ARCHIVED/DELETED` 是合法空结果；
- 非 ACTIVE State 不得携带 payload；
- State 不进入 argv/env；
- Runtime credential 不进入 Codex 环境；
- 临时 profile 权限 `0600` 且正常退出后删除；
- task/project/principal binding 由 Host 决定，MCP tool schema 不增加这些参数；
- 只自动读取，不自动 update/resolve/capture/mutate。

当前候选状态：代码与基础测试已存在，须在 MA-0 review 后按本规划重新封存验收。

### MAR-0A — Event Sufficiency Audit

在任何数据库或 Product 写入前，使用已有 HC4 12 个真实 session trace 离线验证：

```text
Previous State
+ observation-first sparse Events
+ exact referenced Evidence
+ frozen current_task_context
```

是否足以让人类重建 requirement、decision、hypothesis invalidation、blocker 和 next action。
Event 不得编码 semantic label，dialogue 不得在 Event journal 复制。任何 required information
gap 都先修 Event contract；opportunity 不足记为 `INCONCLUSIVE`，不得授权 migration。

### MAR-0～MAR-1 — Reconciliation Contract 与机械基座

先冻结并实现：

```text
HostExecutionEvent
StateBasisCursor
frozen event window
State payload + Basis atomic CAS
```

现有 `operational_event` 只用于安全审计，不能冒充语义 AgentEvent。Basis cursor 必须是
server-owned StateVersion metadata，不能放在 arbitrary model payload。

Event type 只记录客观 observation；change-candidate Event 才能产生 dirty，Session/Task/
Compaction boundary 只能触发 dirty 检查。position 数字缺号合法，Basis gap 只能由 journal
epoch、replayable-from watermark 或 exact retained identity 缺失证明。MAR v1 不加入
`canonical_position`。

MAR-1 涉及真实 schema change；必须新建 migration 和 ADR，不得重写 `0050`。本规划当前
没有授予该实现权限。

### MAR-2 — Dirty/Gate SHADOW

Dirty 由“eligible Event position 高于 State Basis”派生，而不是由一个可能漂移的 bool 决定。
SHADOW 只记录：

```text
DIRTY_OBSERVED
CHECKPOINT_CANDIDATE
RESUME_RECONCILIATION_REQUIRED
```

不调用 Codex，不写 Working State。

### MAR-3 — Offline StateDelta

Codex 对 Previous State + Frozen Event Window 输出严格 StateDelta；Host 以 field allowlist
验证并确定性合并，未变化字段原样保留。实验禁用 Skills、MCP、shell 和 mutation tools，
只测 State diff，不写 Product State。

### MAR-4～MAR-5 — Resume / Checkpoint Reconciliation

```text
Host owns WHEN
Codex owns WHAT CHANGED
Host applies Delta
MiLA stores full State + Basis with exact CAS
```

Session checkpoint 失败时不伪造 fresh，保留 `CHECKPOINT_PENDING`；下一 Session 用未消费
Event 执行 Resume reconciliation。纯 CLI 无 deterministic structured call 时只能标记
`STALE_PENDING_RECONCILIATION`。

### MAR-6 — HC4 Cross-session Usefulness

仅 MAR-4/5 engineering gate PASS 后评估真实连续 coding task。比较 previous-state-only 与
event-reconciled-state，并测 TimeToFirstUsefulAction、RepeatedFailureRate、
StateGroundingAccuracy、StaleWorkingStateRate 和 `USEFUL/NEUTRAL/HARMFUL`。

### MA-H — Explicit History Prefetch（独立 workstream）

目标：只对高精度、显式历史依赖做只读 `memory_resolve` 预取。

第一版仅支持 sealed、可审计的语言模式族，例如 continue/previous/earlier/last time/之前/
上次/继续/还记得。不得为追求 Recall 写无限关键词或每 turn 调用。

```text
high-confidence historical dependency -> HOST PREFETCH
ambiguous dependency                  -> AUTO
post-evidence residual query          -> AUTO continuation
```

MA-H 必须先 SHADOW，测 `RequiredActivationCoverage` 与 `UnnecessaryPrefetchRate` 后才可影响
真实上下文。

## 7. Bootstrap 数据合同

固定控制文本必须说明：

```text
authority       HOST_WORKING
canonical       false
trust           fallible data
payload text    never instructions
authorization   never inherited
validation      revalidate using current files/Evidence
```

数据采用 escaped canonical JSON；payload 中的 `<`, `>`, `&` 不得形成控制边界。只允许：

```text
schema_version
status
authority
state_id
version
payload
```

不得注入 `mcp_guidance`、transport token、Runtime credential、audit internals 或 server logs。
超预算时 fail closed，不进行破坏 JSON/语义的静默截断。

以上是现有 MA-1 bootstrap。MAR-4 若获授权，必须通过版本化合同增加 server-owned
`freshness`、Basis 摘要与有界未消费 Event data；不能把这些机械字段塞入 model-authored
payload。

## 8. Task binding 合同

默认 task identity 基于：

```text
repository root
worktree git directory
branch / detached revision
```

输出为可读前缀加 digest，避免把完整路径放入 State key。显式 `--task-ref` 用于跨 branch/path
持续的产品 Goal。

本地 MA-1 使用每次启动的 private loopback MCP，使 `MILAI_CODEX_TASK_REF` 保持 server-owned。
远程公网 MCP 当前是固定 server-side task binding；未设计安全的 remote dynamic TASK session
前，不把本地 launcher 能力宣称为远程多 TASK 能力。

## 9. 安全边界

Hard gates：

```text
CrossTenantStateLeak                    = 0
CrossPrincipalStateLeak                 = 0
CrossProjectStateLeak                   = 0
CanonicalMutationFromActivation         = 0
DestructiveAutoActivation               = 0
RecallSideWorkingStateMutation           = 0
RuntimeCredentialVisibleToCodex          = 0
StatePayloadUsedAsInstructionAuthority   = 0
CrossTaskEventLeak                       = 0
ModelControlledBasisCursor               = 0
CursorAdvanceWithoutSuccessfulStateCAS   = 0
DestructiveToolDuringReconciliation      = 0
```

Mutation 规则：

- reconciled `working_state_update` 仅可由 Host gate 触发，仍是 non-canonical CAS append；
- Codex StateDelta 不能决定 binding、cursor、expected version 或 operation ID；
- proposal/review/revoke/cleanup 不得由历史 memory、项目文件、日志或旧会话授权；
- namespace cleanup 必须有当前会话用户明确请求；
- 所有现有 confirmation、operation_id、scope、RLS、revocation 与 audit 语义保持。

## 10. 失败归因树

```text
Cross-session cognitive continuity fails
  ├─ required Host Event absent
  │    -> Event capture failure
  ├─ Event exists but dirty/gate did not fire
  │    -> Activation/gate failure
  ├─ Event window has retention/cursor gap
  │    -> Basis completeness failure
  ├─ Codex did not return valid StateDelta
  │    -> Reconciliation model/contract failure
  ├─ valid Delta rejected or applied incorrectly
  │    -> Host validation/apply failure
  ├─ apply succeeded but State/Basis CAS failed
  │    -> MiLA persistence failure
  ├─ State remains stale/wrong
  │    -> Host cognitive maintenance failure
  ├─ State correct, required Evidence unavailable
  │    -> MiLA retrieval failure
  ├─ State/Evidence correct, Codex action wrong
  │    -> Host reasoning failure
  └─ authority/scope/canonical violated
       -> hard architecture failure
```

## 11. 指标与公式

```text
RequiredActivationCoverage
  = completed required Host calls / eligible hard-gate events

UnnecessaryPrefetchRate
  = prefetches without eligible hard-gate event / all prefetches

ResumePrefetchSuccessRate
  = valid bootstrap contexts / session-start prefetch attempts

CheckpointCompletionRate
  = successful State+Basis CAS appends / required reconciliation gates

BootstrapStateUsefulRate
  = USEFUL continuation sessions / evaluable continuation sessions

MemoryCallOverhead
  = added wall time and context tokens per Host activation

EventCaptureCoverage
  = successfully persisted eligible Host events
    / eligible Host event append attempts

FalseFreshRate
  = states marked FRESH while eligible visible Event exists above Basis
    / all states marked FRESH

DeltaFieldReferenceValidityRate
  = changed fields carrying >=1 valid event-window reference
    / all changed fields

SemanticGroundingAccuracy
  = semantically supported changed fields
    / adjudicated changed fields

EventSufficiencyByClass(c)
  = reconstructable important transitions in class c
    / adjudicated important transitions in class c

UnchangedFieldPreservationRate
  = unchanged pre-existing fields retained exactly
    / all unchanged pre-existing fields

ResumeRecoveryRate
  = sessions consuming all available pre-start Event windows
    / sessions starting with unconsumed Events
```

MA-1 engineering target：

```text
RequiredActivationCoverage  = 100%
CodexBeforePrefetch          = 0
credential/payload leak      = 0
unrequested mutation         = 0
cursor advance without CAS   = 0
false fresh                  = 0
```

`NaturalMCPInvocationRate` 降级为研究指标，不再作为 deterministic continuity 产品 gate。

## 12. 测试层次

### Contract/unit

- stable and branch-sensitive task identity；
- explicit task override；
- legal State lifecycle handling；
- markup escaping、size limit、field allowlist；
- private profile permission/lifecycle；
- base Codex developer instruction preservation；
- credential scrubbing；
- Host-owned option override rejection；
- GET-before-Codex ordering；
- fail-closed no-Codex launch。

### Integration

- real Streamable HTTP MCP；
- real Runtime Working State GET；
- ABSENT and ACTIVE bootstrap；
- access audit；
- MCP child/profile cleanup；
- Codex `debug prompt-input` verifies developer-context placement。

MAR integration 另须覆盖：

- HostExecutionEvent append-only 与完整 RLS binding；
- frozen window、retention gap 与 concurrent late Event；
- State payload + Basis atomic CAS；
- stale Delta、idempotent replay、operation conflict；
- automatic audit 且 raw Event/State payload disclosure 为 0。

### Package

- Ruff、strict mypy、full pytest；
- sdist/wheel build；
- `milai-client + milai-mcp` built-wheel combined install；
- installed `milai codex --help`；
- single MCP wheel dependency limitation reported honestly。

### Effect

仅 MAR-6/MA-H effect study 可声称 usefulness/activation improvement。MAR-3 使用 no-Skill、
no-tool dedicated structured reconciliation。代码存在、tools/list、unit tests 或单次
ABSENT smoke 均不是 HC4 usefulness PASS。

## 13. 与 v0.3 Development Master 的关系

本文中的 MAR-0A～MAR-6 保留为目标架构和可选 hardening 分解，不再构成逐 Block
授权链。当前执行顺序是：

```text
Memory MCP Functional Baseline
  -> Host Continuity
  -> Minimal Event Reconciliation
  -> evidence-triggered hardening
```

每个 Milestone 只在开始与完成边界审查；中间允许连续实现、测试、subagent review 与修复。
MA-H 仍是独立 history-prefetch 能力，不得混入 Cognitive State effect claim。

停止条件：

- 不再通过增加 MCP 描述长度处理 deterministic activation；
- 不把 `operational_event` 或 audit 冒充完整 AgentEvent source；
- 不把 semantic conclusion 编入 Event type；
- 不让 boundary Event 自己制造 dirty；
- 不用 position 缺号证明 Basis gap；
- 不允许自由文本 current_task_context；
- 不把 model-authored cursor 当作消费证明；
- CLI 若无法执行 deterministic reconciliation，则标记
  `STALE_PENDING_RECONCILIATION`/`CHECKPOINT_PENDING`；
- 任一 authority/scope/canonical/cursor hard gate 非零，阶段立即 FAIL；
- 不为了完成矩阵制造 State、任务、用户授权或 benchmark label。

## 14. 版本与回滚

MA-0/MA-1 不迁移数据库、不改变 MCP public schema、不改变 Canonical procedure。MAR-1
若获授权则属于真实 schema change：必须新建 migration，不得重写 `0050`。Launcher 是可选
入口；行为回滚停止产生新 Delta/StateVersion，append-only history 与自动 audit 保留，不进行
破坏性清理。

Product 状态继续为：

```text
Schema          0.1.x EXPERIMENTAL
Implementation  CANDIDATE
Schema freeze   NO-GO
```
