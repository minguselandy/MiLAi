---
document_id: MILA-EVENT-GROUNDED-HOST-COGNITIVE-STATE-RECONCILIATION-PLAN
version: "0.3"
status: TARGET_ARCHITECTURE_HARDENING_REFERENCE
date: 2026-09-04
schema_change_authority: NONE
canonical_change_authority: NONE
next_authorized_action: MCP_BASELINE_FIRST
parent_plan: MILA-HOST-COGNITIVE-MEMORY-ACTIVATION-RECONCILIATION-MASTER@0.3
supersedes: MILA-EVENT-GROUNDED-HOST-COGNITIVE-STATE-RECONCILIATION-PLAN@0.2
---

# Event-grounded Host Cognitive State Reconciliation 设计开发规划

> 总览入口：`MILA_HOST_COGNITIVE_MEMORY_ACTIVATION_RECONCILIATION_总设计开发文档.md`。

> v0.3 定位：本文保留 Event reconciliation 的长期正确性目标和 hardening 参考，不再把
> MAR-0A～MAR-6 全部作为第一版实现前置条件。实际开发顺序、Milestone 授权与最小可用
> 范围以总设计 v0.3 为准；当前先完成 Memory MCP Functional Baseline。

## 1. 目标与可证伪 Claim

本规划不再要求 Codex 持续、主动地意识到自身 State 变化并调用 MCP。目标改为：

> Host 根据真实执行事件确定何时需要检查 State；Codex 根据旧 State 与冻结事件窗口判断
> 具体变化；MiLA 将经 Host 验证和合并后的完整 State 与 basis cursor 原子 CAS append。

```text
MAR-C1 Event continuity
  eligible Host events can be durably and exactly windowed by TASK binding.

MAR-C2 Delta reconciliation
  Codex can identify material state changes from Previous State + Events,
  without rewriting or dropping unchanged state.

MAR-C3 Recoverable continuity
  a missed checkpoint can be repaired at the next resume from unconsumed events.
```

不声称 Event 是 Canonical truth、cursor 是语义完整性证明、Runtime 理解认知字段，或代码存在
就证明 cross-session usefulness。

## 2. 四种对象必须分离

| Object | 回答的问题 | Owner | Authority |
| --- | --- | --- | --- |
| Evidence / HostExecutionEvent | 真实观察或执行了什么 | MiLA/Host | provenance only |
| Canonical State | MiLA 正式接受什么 | governed MiLA | Canonical |
| RetrievalContinuationState | 一次 recall 已经搜到哪里 | Runtime | mechanical |
| Host Cognitive State | Codex 当前如何理解任务 | Codex semantics + MiLA persistence | HOST_WORKING |

Working State 是 reconstructable cognitive cache。可重建性受 Event/Evidence retention、scope、
permission 和 cursor gap 限制；任何缺口都必须显式报告。

## 3. 处理链与职责

```text
REAL EXECUTION
      |
      v
HostExecutionEvent append
      |
      +---------------------> optional exact Evidence ref
      |
      v
derived DIRTY
      |
      v
Checkpoint / Resume Gate
      |
      +------ Previous State Vn
      +------ Frozen events in (B0, B1]
      |
      v
Codex structured StateDelta
      |
      v
Host validate + deterministic apply
      |
      v
MiLA CAS append(State Vn+1, Basis B1)
```

```text
WHEN TO RECONCILE = Host
WHAT CHANGED      = Codex
APPLY             = Host
STORE / CAS       = MiLA
```

## 4. HostExecutionEvent

### 4.1 与审计事件分离

现有 `milai.operational_event` 是默认自动写入的安全审计元数据，不是 AgentEvent journal。
不得复用它来冒充完整 reconciliation source：

- 审计 payload 不保证包含任务状态调整需要的语义；
- 当前没有 TASK-scoped basis cursor 合同；
- GET/audit/keepalive 若参与 dirty，会形成自激活循环；
- audit retention/disclosure 与 semantic event retention 的目的不同。

`HostExecutionEvent` 是新的 append-only 输入记录，不是新的 State 类型，也没有 Canonical
authority。

### 4.2 候选事件包络

```yaml
HostExecutionEvent:
  event_id: UUID
  event_position: bigint
  journal_epoch: opaque string
  event_type: enum
  observed_at: timestamptz
  principal_binding_digest: server-owned
  project_id: server-owned
  task_ref: server-owned
  source_session_ref: server-owned
  payload: bounded JSON data
  payload_digest: sha256
  evidence_refs: []
```

Event type 只能描述 Host 客观观察，不得预先解释 requirement、correction、decision、
hypothesis 或 blocker。`event_position` 是单调 high-watermark，允许 sequence/transaction
gap，不是事件计数。读取必须同时按 tenant、principal、project、task 完整约束。

### 4.3 Observation-first Event taxonomy

```text
DIALOGUE_TURN_OBSERVED
FILE_SET_CHANGED
TEST_RESULT_OBSERVED
COMMAND_RESULT_OBSERVED
GIT_COMMIT_OBSERVED
TOOL_RESULT_OBSERVED
TASK_BOUNDARY_OBSERVED
SESSION_BOUNDARY_OBSERVED
CONTEXT_COMPACTION
```

`USER_REQUIREMENT_CHANGED` 和 `USER_CORRECTION` 被删除：Host 只观察
`DIALOGUE_TURN_OBSERVED`，由 Codex 在 reconciliation 中判断它是否构成 requirement change、
correction、decision 或其他 State transition。

Dialogue Event 必须包含 `role=user|assistant` 与 exact Evidence ref，不复制 raw dialogue。
Assistant Evidence 只能是 Host 本来可观察的 final message、tool-visible action summary 或
host-visible output；hidden reasoning、private scratchpad 和 chain-of-thought 禁止进入 Event
或 Evidence。

### 4.4 Change candidate 与 boundary 分离

可产生 dirty 的 change candidate：

```text
DIALOGUE_TURN_OBSERVED
FILE_SET_CHANGED
TEST_RESULT_OBSERVED
COMMAND_RESULT_OBSERVED
GIT_COMMIT_OBSERVED
TOOL_RESULT_OBSERVED
```

只触发“现在检查 dirty”的 boundary：

```text
TASK_BOUNDARY_OBSERVED
SESSION_BOUNDARY_OBSERVED
CONTEXT_COMPACTION
```

Boundary 本身绝不能制造 dirty。`HOST_WORKING_STATE_ACCESSED`、readiness、keepalive、纯读取
和纯审计事件也不产生 dirty。

### 4.5 Sparse journal

HostExecutionEvent 是认知 reconciliation 的稀疏索引，不是完整 execution log：

- 同一窗口内文件写入聚合为 `FILE_SET_CHANGED` 与有界 path/digest set；
- 测试保留 first material failure、final result 和必要状态转移，不复制完整输出；
- 命令只记录 failure 或 material side effect，不记录成功的 `ls`/`pwd` 等读取；
- Tool result 只记录可能改变任务认知的结果；
- 大文本只通过当前可读 exact Evidence ref 获取。

Host 可派生 `dirty_classes=dialogue/files/tests/commands/git/tools`，防止单一高频事件占满阈值。
这是 deterministic aggregation，不是 Host 对语义 State change 的判断。

## 5. StateBasisCursor

```yaml
StateBasisCursor:
  event_journal_epoch: opaque string
  event_position: bigint
  event_contract_version: string
  reconciled_at: timestamptz
```

`event_position=P` 仅表示该 StateVersion 已审查当前 binding 下位置 `<=P` 的 eligible
HostExecutionEvent。MAR v1 不记录 `canonical_position`；在 Canonical change 被正式纳入
reconciliation input/dirty contract 之前，不建立一个没有闭环语义的 cursor。

Basis 必须是 server-owned StateVersion metadata。禁止：

- 让 Codex 在 payload、MCP 参数或 StateDelta 中决定 cursor；
- Delta/model/CAS 失败后单独推进 cursor；
- 用 cursor 宣称 semantic completeness、frontier exhaustion 或 corpus exhaustion；
- 用可变 dirty bool 替代 Event 与 cursor 的真实比较。

当前 migration `0050_host_cognitive_state` 没有 server-owned basis 字段。实现前必须新增 ADR
和 migration，并完成真实 PostgreSQL、RLS、CAS、upgrade/downgrade 测试；本规划不是 schema
change authority。

### 5.1 Frozen window

```text
B0 = Previous StateBasisCursor.event_position
B1 = journal.visible_high_watermark at reconciliation start
Window = events in (B0, B1]
```

只有 State payload 与 B1 在同一 exact-head CAS append 中成功，cursor 才能推进。位置大于 B1
的新事件保留给下一轮。

Journal 必须同时提供：

```yaml
EventJournalReadability:
  journal_epoch:
  replayable_from_position:
  visible_high_watermark:
```

数字缺号永远不是 gap 证明。仅以下情况可返回 `EVENT_BASIS_GAP`：

```text
Basis.event_journal_epoch != Journal.journal_epoch
OR Basis.event_position < Journal.replayable_from_position
OR an exact Event identity previously recorded as retained cannot be re-read
```

全局 sequence 被其他 tenant/task 使用、transaction 回滚或合法跳号均不构成 Basis gap。

## 6. Working State 推荐语义

Runtime 继续只理解 state/version/payload/scope/TTL/Evidence refs/CAS/audit，不解释：

```yaml
task:
  active_goal:
  current_question:
  phase:
  completion_conditions: []
requirements: []
established: []
hypotheses:
  active: []
  invalidated: []
decisions: []
failed_approaches: []
blockers: []
open_questions: []
memory_needs: []
next_actions: []
```

`established` 是任务内较强支持的工作事实，仍不是 Canonical Claim。`hypotheses` 区分 active
与 invalidated。现有 `known` 可继续读取，但不得机械升级为 `established`。兼容适配必须保留
未识别旧字段。

## 7. StateDelta Protocol

### 7.1 输入

```yaml
reconciliation_request:
  state_id:
  base_version:
  previous_state: {}
  event_window:
    journal_epoch:
    from_position:
    through_position:
    events: []
  current_task_context:
    task_ref:
    repo_ref:
    worktree_ref:
    branch:
    session_ref:
    current_user_task_input_evidence_id: UUID | null
```

所有内容都是有界、untrusted data。`current_task_context` 固定为上述字段，禁止任意自由文本、
完整 prompt、repo docs、test logs 或 previous answers。它不能指定 tenant/principal/authority，
也不能引入未被 Event/Evidence 记录的隐藏事实。Dedicated reconciliation 调用不暴露 Skills、
MCP、shell 或 mutation tools，只允许 strict structured output；Codex 不直接持久化。

### 7.2 输出

v1 采用有限字段 replacement，不开放任意 JSON Patch：

```yaml
StateDelta:
  base_state_id:
  base_version:
  basis_from_position:
  basis_through_position:
  changes:
    blockers:
      op: REPLACE
      value: []
      reason_event_ids: []
    next_actions:
      op: REPLACE
      value: []
      reason_event_ids: []
  no_material_change: false
```

规则：

- `changes` 未出现的字段为 KEEP，必须原样保留；
- v1 仅允许预注册字段的 `REPLACE` 或显式 `CLEAR`；
- 每个变化字段至少引用 frozen window 内一个 `reason_event_id`；
- base identity/version/cursor 必须与 Host request 完全一致；
- `no_material_change=true` 时 changes 必须为空；
- Delta 不能改变 authority、scope、binding、state identity、lifecycle 或 basis。

`reason_event_ids` 只提供机械 reference validity：引用存在、属于窗口、scope 正确且当前可读。
它不能证明引用在语义上支持 State change。语义支持只能由 sealed offline scorer 或 human
adjudication 评价。

无变化窗口仍应以新 StateVersion + B1 提交，明确记录“已审查、无语义变化”。这是 cursor
正确性写入，不是 Canonical 或业务事实 mutation。

### 7.3 Host apply

```text
1. GET State Vn
2. freeze Event window (B0, B1]
3. request StateDelta(base=Vn, window=B0..B1)
4. validate strict schema, field allowlist and event membership
5. apply Delta to Previous full payload
6. validate payload size and all Evidence refs
7. CAS append full payload + Basis B1
8. keep events > B1 dirty
```

Codex 不选择 expected version、operation ID、binding 或 cursor。CAS conflict 时丢弃 stale
Delta，不套用到新 head；v1 不做无界语义自动重试，保留 pending，下一 gate 从新 head 对账。

## 8. Dirty 与 Gate

```text
state_dirty =
  exists unreconciled visible change-candidate Event
  where event_position > StateBasisCursor.event_position
```

Host 可以缓存 dirty hint，但 Event + cursor 才是正确性来源。

### 8.1 Checkpoint

```text
CheckpointRequired =
  active_task_exists
  AND has_unreconciled_change_candidate
  AND (
       session_boundary
    OR task_boundary
    OR context_compaction
    OR distinct_dirty_class_count >= profile_owned_class_threshold
    OR bounded_change_candidate_count >= profile_owned_event_threshold
  )
```

Boundary Event 本身不计入 change candidate。不得在每个 turn/tool call 后 reconcile。“phase
变化”通常是 Delta 结论；除非 Host 有明确 workflow event，否则不是 deterministic trigger。

### 8.2 Resume

```text
Session start
  -> GET Previous State
  -> compare visible Event watermark with Basis
     |-- equal: inject current State
     +-- newer: Resume Reconciliation before marking FRESH
```

默认 interactive coding 采用 task-availability fail-open：

```text
reconciliation success
  -> inject FRESH State

reconciliation unavailable
  -> optionally inject old State
  -> freshness=STALE_PENDING_RECONCILIATION
  -> launch Codex without claiming freshness
```

Strict continuity profile 可以选择阻止启动。无论哪种模式，memory injection 对 authority、
scope、payload safety 均 fail closed：不安全数据绝不注入，Basis 绝不推进。

`STALE_PENDING_RECONCILIATION` 是 bootstrap freshness，不是 Runtime lifecycle，不能覆盖
`ACTIVE/EXPIRED/ARCHIVED/DELETED`。

### 8.3 New task

```text
if meaningful pre-start change-candidate Event exists:
    optional bootstrap reconciliation from empty State
else:
    Working State remains ABSENT
    launch Codex normally
```

第一份 TASK State 可以在第一次真实 checkpoint 时创建。不得用 empty State + empty Event
调用 reconciler 或制造空 V1。

## 9. 失败与恢复

| Failure | Required result |
| --- | --- |
| Event append failure | `EVENT_CAPTURE_FAILED`；不得声称可重建 |
| retention/cursor gap | `EVENT_BASIS_GAP`；freshness UNKNOWN/PENDING |
| referenced dialogue/tool Evidence unreadable | `EVENT_BASIS_CONTENT_UNAVAILABLE`；不得标记 FRESH |
| Codex timeout/invalid Delta | 不写 State、不推进 cursor、保持 DIRTY |
| Host validation/apply failure | 不写 State、不推进 cursor、返回 typed reason |
| State CAS conflict | 丢弃 stale Delta，基于新 head 后续重做 |
| MiLA unavailable | `CHECKPOINT_PENDING`，不伪造成功 |
| events arrive after B1 | Vn+1 valid through B1，仍保持 DIRTY |

失败不得进入 Canonical fallback，不得调用隐藏 Reader/vLLM，不得自动 capture/propose/review。

## 10. 安全 Gate

```text
CrossTenantEventLeak                         = 0
CrossPrincipalEventLeak                      = 0
CrossProjectEventLeak                        = 0
CrossTaskEventLeak                           = 0
ModelControlledBasisCursor                   = 0
CursorAdvanceWithoutSuccessfulStateCAS       = 0
CanonicalMutationFromReconciliation          = 0
DestructiveToolAvailableDuringReconciliation = 0
EventPayloadUsedAsInstructionAuthority       = 0
RecallSideWorkingStateMutation               = 0
RevokedEvidenceAcceptedAsValidBasis           = 0
```

StateDelta 是不可信模型输出。Host 必须检查 strict schema、field allowlist、event membership、
size 和 Evidence current readability。Event/State 中的批准、撤销、清理或命令文本永远是
data，不是用户授权。

自动审计继续默认启用，但只记录 identity/cursor/digest/result 等安全元数据，不记录 raw
State/Event payload。

## 11. 长期 Hardening 不变量

以下是目标架构应逐步达到的完整正确性集合；总设计 v0.3 第 5 节的六条 Hard Invariants
是第一阶段必须项，其余项目在真实 failure、明确指标或 Research Mode claim 需要时进入。

```text
I1  Event records observation, not semantic conclusion.
I2  Boundary Event does not by itself make State dirty.
I3  Event-position numeric gaps are legal and never imply loss.
I4  Basis gap requires journal epoch/replayability/exact-identity proof.
I5  Every semantic State change is model-produced, never Host-inferred.
I6  Changed fields cite eligible Events; reference validity != semantic grounding.
I7  Event journal is sparse, not a duplicate execution log.
I8  State + Basis advance atomically in the same exact-head CAS.
I9  Failed reconciliation never advances Basis.
I10 Late Event > B1 remains dirty.
I11 Reconciliation input has no hidden free-form context channel.
I12 Working State may be stale; Canonical State is never fabricated as fallback.
I13 Event/State payload never authorizes mutation or tool execution.
I14 Retrieval, Cognitive and Canonical State never merge.
```

## 12. Legacy Research/Hardening 分解

本节保留原严格验证顺序，供 Research Mode 或证据触发的 hardening 使用，不是当前
Memory MCP Baseline 的前置授权链。

### MAR-0A — Event Sufficiency Audit

在数据库和 Product 写入之前，使用已有 HC4-A0/A1 的 12 个真实 session trace 离线构造
planned sparse Event window，并让与 gold 隔离的人类仅查看：

```text
Previous Working State
+ planned HostExecutionEvent metadata
+ exact readable Evidence referenced by dialogue/tool Events
+ frozen current_task_context fields
```

由于既有 HC4 sessions 没有自然产生 ACTIVE State，full-trace adjudicator 先为每个非首窗口
构造一个“截至窗口起点”的 Previous State fixture；该 fixture 仅属于 audit，不写 Product，
也不暴露窗口后的信息。

再与 full-trace human adjudication 的 requirement、decision、hypothesis invalidation、blocker
和 next action 变化比较。

Gate：

```text
SemanticLabelEncodedInEvent        = 0
RawDialogueDuplicatedInJournal     = 0
RequiredTransitionInformationGap  = 0
EventSufficiencyByClass            reported separately
```

若某一关键类别没有足够 opportunity，结果为 `INCONCLUSIVE`，不得借此授权 migration。若存在
information gap，先修改 Event/Evidence contract，再重跑 MAR-0A。

### MAR-0 — Contract Freeze

交付 Event、Basis、Delta、dirty/gate、retention/gap/privacy 合同；提交 proposed ADR 与
migration/interface 设计。审查通过前不建表、不加 cursor、不调用模型。

### MAR-1 — Event Journal + Basis Persistence

实现 append-only scoped Event、server-owned high-watermark、State payload + Basis exact-head
atomic CAS、RLS/retention/deletion/audit；不增加 public MCP tool catalog。

### MAR-2 — Dirty/Gate SHADOW

只记录 `DIRTY_OBSERVED`、`CHECKPOINT_CANDIDATE`、
`RESUME_RECONCILIATION_REQUIRED`；不调用 Codex，不写 State。

### MAR-3 — Offline StateDelta

在 sealed fixtures 上运行 no-Skill/no-tool structured reconciliation；只产出 Delta，不写
Product State。冻结 model/config/prompt/schema，gold label 只供 scorer。

### MAR-4 — Resume Reconciliation

Session start 发现未消费 Event 时先 reconcile；成功才标记 FRESH。纯 CLI 如果不能提供
deterministic structured call，只能返回 `STALE_PENDING_RECONCILIATION`。

### MAR-5 — Checkpoint Reconciliation

在 session end、task switch、compaction、explicit pause 等 gate 使用同一 protocol。失败
保留 pending，由下一次 Resume 修复。

### MAR-6 — Cross-session Usefulness

前置 MAR-4/5 engineering PASS：

```text
real continuous coding tasks  >= 10
distinct task chains          >= 3
continuation sessions         >= 6
```

比较 previous-state-only 与 event-reconciled-state，人工标注
`USEFUL/NEUTRAL/HARMFUL`。工具调用和代码存在不构成 usefulness PASS。

## 13. 指标

```text
EventCaptureCoverage
  = successfully persisted eligible Host events
    / eligible Host event append attempts

FalseFreshRate
  = states marked FRESH while eligible visible Event exists above Basis
    / all states marked FRESH

ReconciliationCompletionRate
  = successful State+Basis CAS appends
    / required reconciliation gates

DeltaFieldReferenceValidityRate
  = changed fields with >=1 valid event-window reference
    / all changed fields

SemanticGroundingAccuracy
  = semantically supported changed fields
    / adjudicated changed fields

EventSufficiencyByClass(c)
  = reconstructable important transitions in class c
    / adjudicated important transitions in class c

UnsupportedStateChangeRate
  = unsupported changed fields / all changed fields

UnchangedFieldPreservationRate
  = unchanged pre-existing fields retained exactly
    / all unchanged pre-existing fields

StaleStateCorrectionRate
  = stale/contradicted items correctly retired or corrected
    / adjudicated stale/contradicted opportunities

ResumeRecoveryRate
  = sessions consuming all available pre-start Event windows
    / sessions starting with unconsumed Events
```

```text
event/cursor cross-scope leak              = 0
cursor regression                          = 0
cursor advance without State CAS           = 0
events above frozen window lost             = 0
model-generated authority/binding accepted = 0
Canonical/destructive mutation             = 0
false deterministic completion claim       = 0
```

## 14. 测试层次

Unit/contract：

- observation-only event taxonomy、change/boundary split、sparse coalescing；
- journal epoch/replayable-from、legal numeric gaps、frozen window、derived dirty；
- strict Delta、event membership、field allowlist；
- deterministic apply、unchanged preservation、no-op Delta；
- stale Delta/CAS conflict；
- reconciliation 期间到达新 Event 不丢失。

PostgreSQL/integration：

- fresh/populated migration、append-only Event/State；
- tenant/principal/project/task RLS；
- State payload + Basis atomic CAS；
- idempotent replay/operation conflict；
- retention gap、Evidence revocation；
- audit 默认写入且 raw payload disclosure 为 0。

Failure/effect：

- MAR-0A full-trace vs Event-only sufficiency audit；
- Event append、model timeout、invalid JSON、oversize、DB unavailable；
- malicious Event/State instructions；
- no-Skill/no-tool reconciliation；
- 与 Product-11 retrieval failure 分开归因；
- TimeToFirstUsefulAction、RepeatedFailureRate、StateGroundingAccuracy、
  StaleWorkingStateRate、ContradictoryStateRate。

## 15. 实施位置、兼容与停止条件

本文中的 MAR-0A～MAR-6 是可选的研究/硬化分解，不再要求逐项人工授权。总设计 v0.3 的
Milestone C 先实现并验证最小闭环：

```text
sparse Event
  + previous State
  -> Codex StateDelta
  -> validated CAS State
  -> real cross-session usefulness
```

只有真实 failure、明确验收指标或 Research Mode claim 需要时，才提升 journal epoch、
完整 replayability、retention gap 与 full-trace adjudication。

停止：

- 不再用更长 MCP prompt 处理 deterministic state transition；
- 不把 `operational_event` 冒充 AgentEvent journal；
- 不把 semantic conclusion 编进 Host Event type；
- 不让 boundary Event 自己制造 dirty；
- 不用 position 缺号证明 Basis gap；
- 不允许 current_task_context 成为自由文本隐藏通道；
- 不接受 model-authored cursor；
- 不做每-turn reconciliation、case-ID 分支、无界重试或隐藏 Reader；
- 任一 authority/scope/cursor hard gate 非零即停止阶段；
- CLI 无 deterministic structured reconciliation 时如实保持 pending。

当前 `host-cognitive-state-v1`、`codex-cognitive-state-v1`、migration `0050`、13-tool
public MCP catalog 和 Canonical procedures 都不变。未来 MAR-1 必须新增 migration，不得重写
`0050`；行为回滚停止新 Delta/StateVersion，保留 append-only history 和 audit。

```text
Schema          0.1.x EXPERIMENTAL
Implementation  CANDIDATE
Schema freeze   NO-GO
```
