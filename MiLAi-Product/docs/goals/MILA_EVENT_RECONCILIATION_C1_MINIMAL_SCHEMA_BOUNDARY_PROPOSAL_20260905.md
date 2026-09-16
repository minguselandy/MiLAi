---
document_id: MILA-EVENT-RECONCILIATION-C1-MINIMAL-SCHEMA-BOUNDARY
version: "0.2"
status: IMPLEMENTED_PASS
date: 2026-09-05
milestone: PHASE_C1_SIMPLE_EVENT_JOURNAL
schema_change_authority: USER_AUTHORIZED_CURRENT_GOAL
public_mcp_schema_change: NONE
canonical_change_authority: NONE
depends_on: MILA-EVENT-RECONCILIATION-PHASE-C0-SPIKE@1.1
supersedes: MILA-EVENT-RECONCILIATION-C1-MINIMAL-SCHEMA-BOUNDARY@0.1
---

# MiLA Event Reconciliation C1 最小 Schema Boundary 提案

## 1. 结论

C0 已得到产品价值信号。用户随后授权执行当前总目标，C1 已实现为 append-only、稀疏、
observation-first 的 task Event journal，用于以后向 reconciliation 提供 bounded Event window。

```text
Host-visible observation
  -> sparse Event append
  -> task-local Event window read
  -> later C3 reconciliation
```

C1 不生成 StateDelta、不更新 Working State、不自动 checkpoint、不改变 Canonical，也未新增
public MCP tool。

## 2. 当前 failure 所要求的最小能力

C0 证明 Codex 能利用以下输入纠正 Working State：

- Host-visible dialogue Evidence；
- 实际命令/测试/文件/Git 观察；
- 旧 Working State；
- 有限字段、Event-referenced StateDelta。

因此 C1 只需可靠保存“发生过哪些相关观察及其 exact Evidence refs”，无需先实现 journal epoch、
retention-gap proof、late-event reconciliation、dirty-class threshold 或语义 grounding scorer。

## 3. 最小持久化对象

已分配 reversible migration `0051_host_execution_event`。逻辑结构：

```yaml
HostExecutionEvent:
  tenant_id: Runtime credential context
  event_id: server-owned UUID
  position: server-owned monotonic bigint
  principal_binding_digest: trusted Host adapter binding
  project_id: trusted Host adapter binding
  task_ref: trusted Host adapter binding
  event_family: bounded string
  event_type: bounded string
  observed_at: timestamp
  bounded_payload: JSON object
  created_at: server timestamp
  created_by_actor_id: authenticated actor

HostExecutionEventEvidenceRef:
  tenant_id:
  event_id:
  evidence_id:
  ordinal:
```

约束：

- `event_id` 与 `position` 只能由 Runtime 产生，tenant/actor 来自认证 credential；
- principal/project/task 由 trusted Host adapter 选择并通过内部 REST 提交，不能来自 MCP/model
  tool arguments；
- `(tenant_id, event_id)` 为主键，`position` 单调但允许可见序列有数字 gap；
- `event_family/event_type` 为长度受限字符串，不使用封闭数据库 enum；
- `bounded_payload` 必须是对象并受序列化字节上限约束；
- Evidence ref 使用关联表和现有 Evidence identity，Event 不复制 raw dialogue；
- 对话只允许引用 Host 本来可见的 user/assistant Evidence，不保存 hidden reasoning；
- history 行 append-only；修订通过新 Event 表达，不原地改写旧 Event。

## 4. Starter vocabulary，不是封闭 taxonomy

```text
DIALOGUE / MESSAGE
EXECUTION / FILES_CHANGED
EXECUTION / TEST_RESULT
EXECUTION / COMMAND_FAILURE
GIT / COMMIT
LIFECYCLE / SESSION_BOUNDARY
```

adapter 可以增加新的 bounded `event_family/event_type`，但 MiLA core 不理解其领域语义。
`SESSION_BOUNDARY` 只是边界观察，不单独证明 State dirty。

## 5. 最小操作面

C1 只需要内部 Host API/service primitive：

```text
append_event(binding, observation, evidence_refs, operation_id)
read_event_window(binding, after_position, limit)
```

语义：

- append 使用 operation fingerprint 幂等；相同 operation + 相同 payload 返回原结果，不同 payload
  返回 conflict；
- read 只返回当前 server-owned binding 可见的 Event；
- `after_position` 是 exclusive watermark，不要求返回位置连续；
- response 返回 `visible_high_watermark`，但 C1 不声称 retention/replayability completeness；
- 不向 Codex 暴露可提交 tenant/principal/project/task binding 的 MCP 参数；
- C1 默认 SHADOW，不进入 Codex prompt，也不触发 Working State mutation。

是否把该内部面封装成 public MCP tool 不属于 C1。当前更小的实现是 Codex Host adapter 调用
Runtime Host API；13-tool `codex-full` catalog 保持不变。

## 6. Sparse adapter 规则

Event journal 是认知 reconciliation 索引，不是 execution trace 副本：

- 一个窗口内文件路径去重后形成 `FILES_CHANGED`；
- 测试保留重要 failure/pass transition，不保存所有 stdout；
- command 只记录 material failure/side effect identity；
- 对话 Event 只保存 exact Evidence refs 和必要 role metadata；
- 模型文本、reviewer 判断和“正确/因果”说明进入 Evidence，不伪装为 mechanical payload；
- `codex_config`、文件路径、测试状态属于 adapter payload，不升格为 core columns。

## 7. C1 必须验证的最小合同

```text
append/read real PostgreSQL                 PASS
operation retry duplication                0
same operation different payload conflict  PASS
cross-project read/write                    0
cross-principal TASK read/write             0
MCP/model binding override                  0
raw dialogue copied into Event payload      0
Recall/Canonical/Working State mutation     0
numeric position gap treated as loss        0
```

测试以 unit + real PostgreSQL integration + subagent boundary review 为主，不需要人工 gold、
Formal holdout 或 semantic grounding benchmark。

`/v1/host-events/*` 是 trusted Host REST surface，不是 hostile-client-safe public API。持有对应
Bearer capability 的直接 REST Host 可以选择自己的 principal/project/task namespace；RLS 仍强制
tenant/actor isolation，task/project filtering 防止窗口串读。若未来需要防止不可信 HTTP Host
选择 binding，必须增加 server-verifiable binding artifact，但这不由 C1 当前 failure 要求。

## 8. 明确推迟

以下机制只有真实 failure 需要时才进入后续 hardening：

- journal epoch 与 replayable-from proof；
- retention-gap / exact missing identity 体系；
- automatic dirty tracking、threshold 与 checkpoint；
- late Event 合并和 State Basis CAS；
- StateDelta Product wire schema；
- automatic Working State update；
- public MCP tool/schema expansion；
- human adjudication、效果量和泛化声明。

## 9. 授权与完成边界

实际完成范围：

```text
C0 value signal     PASS
C1 boundary         FROZEN
C1 migration/code   IMPLEMENTED
C1 PostgreSQL E2E    PASS
C1 subagent review  PASS
```

用户对当前总目标的执行授权覆盖以下 Milestone 范围：

```text
one reversible migration
append/read Host Event Runtime primitives
SHADOW adapter path
real PostgreSQL tests
no public MCP change
no automatic checkpoint or State mutation
```

完成后已进行一次 subagent milestone review；并发 window 与幂等 namespace 两项 required
finding 已修复并复核为 PASS。完成凭据见
`MILA_EVENT_RECONCILIATION_PHASE_C1_COMPLETION_REPORT_20260905.md`。
