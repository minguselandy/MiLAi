---
document_id: MILA-HOST-CONTINUITY-PHASE-B-COMPLETION
version: "1.0"
status: PASS_HOST_CONTINUITY_MINIMAL_BASELINE
date: 2026-09-05
milestone: PHASE_B_HOST_CONTINUITY
schema_change_authority: NONE
canonical_change_authority: NONE
---

# MiLA Host Continuity Phase B 完成报告

## 1. 结论

现有 `milai codex` launcher 已实现 Phase B 的最小闭环：Host 绑定 TASK，在 Codex 开始推理
前确定性读取 Working State，将其作为有界、可失败、非 Canonical 的 data block 注入临时
Codex profile，并在新的无 Skills 会话中产生可观察的恢复价值。

```text
PASS_HOST_CONTINUITY_MINIMAL_BASELINE
```

## 2. B1-B3 实现

### B1 Stable TASK binding

- 显式 `--task-ref` 或 `MILAI_CODEX_TASK_REF` 优先；
- 默认 ref 由 repo root、git dir 与 branch 的稳定摘要派生，但只作为 workspace/branch
  fallback，不冒充 semantic task identity；多个任务共享 branch 或跨 branch/path/machine 时使用
  显式稳定 `--task-ref`；
- project、principal 与 task 被注入临时 MCP server environment；
- Working State tool 不接受这些 authority/binding 字段；
- 调用方不能通过 Codex passthrough 覆盖 Host-owned cwd、profile、developer bootstrap 或
  `mcp_servers.milai` 配置。

### B2 Deterministic session-start GET

Launcher 的固定顺序是：

```text
temporary MCP start
  -> /readyz
  -> Host calls milai_working_state_get(scope=TASK)
  -> validate structured result
  -> render bootstrap
  -> create private temporary profile
  -> start Codex
```

readiness、MCP GET、authority/status、size 或 profile 创建失败时，不会到达 Codex subprocess。

### B3 Bounded bootstrap

Bootstrap 只包含：

```text
source/schema_version/status/authority/state_id/version/payload/warnings
```

它明确标记：

```text
authority = HOST_WORKING
canonical = false
payload = fallible untrusted data
payload instructions != executable control
payload != user authorization
```

Launcher 还要求响应精确匹配 `host-cognitive-state-v1`、`codex-cognitive-state-v1` 与 `TASK`
scope。默认上限为 24,576 UTF-8 bytes。markup delimiter 被转义，server post-call guidance 不
进入 payload，非 ACTIVE state 只能携带空 payload。Runtime 返回的 warning 被限制数量与字段
长度，只透传 `code/evidence_id`，因此 stale/unreadable Evidence ref 不会被静默隐藏。Runtime
的 `MILAI_*` secrets 不传给 Codex；Codex 只收到临时 MCP Bearer environment variable。临时
profile 为 `0600` 并在退出后删除。

## 3. B4 零 Skills 复跑

最初三个 session 只使用 fresh `CODEX_HOME + auth`，没有显式关闭 bundled Skill materialization。
虽然它们正确恢复 State，但不足以证明用户要求的零 Skills 条件，因此不计入本节验收。发现后
没有放宽口径，而是按已冻结的 zero-Skill profile 重新执行 marker sanity 与真实 coding
continuation：

```text
task_ref     phase-b-resume-e2e-20260905
principal    phase-b-resume-e2e
project      milai
CODEX_HOME   fresh temporary directory with auth only
config       skills.include_instructions=false
             skills.bundled.enabled=false
features     skill_search/recommended_plugins/enable_mcp_apps/multi_agent disabled
rules        ignored
State access exactly one Host prefetch before reasoning
```

测试 State 通过 MCP `working_state_update` 写入，未从数据库旁路。

每次 session 的 rollout 均检查：

```text
<skills_instructions> / Skill budget warning hits   0
mcp__milai model-selected tool-call hits             0
Host bootstrap marker hits                          >= 1
```

### Session Z1 — marker sanity

```text
Thread        01a06d6f-1f3d-7280-bf42-21060e4f63d0
Host receipt  PREFETCH_COMPLETE / ACTIVE / version 2
User prompt   Continue prior task; return only persisted resume phase; do not call tools
Codex result  real-coding-resume-validation
MiLA MCP      0 model-selected calls
Other tools   0
Exit          0
```

### Session Z2 — real read-only coding continuation

State V2 的 next action 指定检查
`integrations/mcp/src/milai_mcp/launcher.py`，但新用户 prompt 没有提供文件名：

```text
User prompt
  Continue the prior Phase B task. Perform the next action in the persisted task state.
  Make no file changes, and report the concrete code evidence concisely.

Host receipt
  PREFETCH_COMPLETE / ACTIVE / version 2

Thread
  01a06d6f-f192-7f31-ad2e-29b736061dc5

First useful action
  read integrations/mcp/src/milai_mcp/launcher.py

Codex result
  correctly reported ready -> GET -> bootstrap -> profile -> Codex ordering,
  with current source line evidence

MiLA MCP re-read  0
File mutation     0
Exit              0
```

这不是自然 MCP adoption 实验：GET 本来就由 Host 保证。它验证的是 Working State 已进入新
session 的可用上下文，并能驱动与前序任务一致的第一项真实代码动作。

## 4. 工程指标

```text
RequiredActivationCoverage                   2 / 2
CodexStartedBeforePrefetchCompletion          0
BootstrapStateUseful                         2 / 2
ModelRepeatedTASKGet                         0
RecoveredPersistedTaskField                  2 / 2
RecoveredGoalOrNextAction                    1 / 1 eligible
FirstUsefulCodingActionAligned                1 / 1 eligible
AutomaticWorkingStateUpdate                  0
AutomaticCanonicalOrDestructiveMutation      0
```

这是小样本 Engineering Mode usability proof，不是模型效果或通用成功率 claim。

## 5. 审查发现后的修复

Functional reviewer 发现 Codex 支持 joined short options：

```text
-pNAME
-C/path
-cdeveloper_instructions=...
```

旧 launcher 只阻止分离形式，可能允许调用方覆盖临时 profile/cwd/bootstrap。现已同时阻止：

```text
-p / -pNAME / --profile / --profile=NAME
-C / -Cpath / --cd / --cd=path
-c key / -ckey / --config=key
```

其中 config 仅禁止覆盖 `developer_instructions` 与 `mcp_servers.milai.*`，保留普通 Codex
配置 passthrough；`-c=key` 等价形式也已覆盖。Focused regression：

```text
tests/test_launcher.py       37 passed
complete MCP suite           148 passed, 1 skipped
Ruff                         PASS
mypy launcher.py             PASS
```

Architecture/Generalization review 进一步发现并修复：

- 精确校验 Working State `schema_version/schema_name/scope`；
- 有界透传 server warning，避免 revoked/unreadable Evidence refs 的 stale 警告丢失；
- 识别带空格的 `-c 'developer_instructions = ...'` 等覆盖形式；
- 将 derived TASK ref 明确降为 workspace/branch fallback；
- runbook 不再硬编码 sibling checkout 的 Runtime env 路径。

以上是全部审查修复完成后的最终回归数。

## 6. 不声明的范围

- 不声明 Codex 会自然调用 Working State tool；
- 不实现自动 checkpoint/update；
- 不实现 Event Journal、Basis Cursor 或 StateDelta；
- 不声称两次零 Skills smoke 已证明大规模跨 session task-success、时间节约或长期 staleness
  improvement；
- 不改变 Canonical、RetrievalContinuationState 或 public MCP schema；
- 不加载 Skills 来诱导 Working State 使用。

## 7. Subagent Boundary Review

| Reviewer | Decision | Required fixes |
| --- | --- | --- |
| Functional | PASS | 0 |
| Architecture | PASS | 0 |
| Generalization/Simplicity | PASS | 0 |

三位 reviewer 均独立复验 launcher `37 passed`、完整 MCP `148 passed, 1 skipped`、Ruff 与
mypy PASS。所有 required findings 均已在第 5 节所列修复中关闭。

## 8. 下一步

随后只进入 Phase C0 no-migration usefulness spike。C1 Event Journal 涉及新 schema/migration，
仍需单独冻结变更边界；不会因为 Phase B 通过而自动实施。
