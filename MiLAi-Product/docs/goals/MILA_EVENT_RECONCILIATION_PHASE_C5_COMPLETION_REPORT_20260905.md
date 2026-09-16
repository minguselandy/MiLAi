---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C5-COMPLETION
version: "1.0"
status: PASS_REAL_CROSS_SESSION_USEFULNESS_ENGINEERING_SIGNAL
date: 2026-09-05
milestone: PHASE_C5_REAL_CROSS_SESSION_TASKS
evaluation_mode: ENGINEERING
skills_loaded: false
public_mcp_schema_change: NONE
automatic_reconciliation_activation: NONE
session_start_prefetch_activation: HOST_REQUIRED
canonical_change_authority: NONE
---

# MiLA Event Reconciliation Phase C5 完成报告

## 1. 结论

C5 使用两个真实只读 coding task chain、六个全新 Codex Session 验证了现有闭环：

```text
explicit C4 checkpoint
  -> PostgreSQL TASK Working State
  -> fresh zero-Skill Codex Session
  -> deterministic Host prefetch before reasoning
  -> persisted next action changes actual work
  -> observed outcome becomes Evidence/Event
  -> explicit StateDelta reconciliation
```

终态：

```text
PASS_REAL_CROSS_SESSION_USEFULNESS_ENGINEERING_SIGNAL
```

这是 Engineering Mode 的产品可用性信号，不是模型效果或统计显著性声明。C5 没有新增 Runtime
机制、public MCP tool、State schema、自动 checkpoint、持久化 Basis、Canonical mutation 或
Retrieval behavior。

## 2. 运行边界

- 两条独立 TASK chain；
- 六个 fresh Codex Session，每次使用新的临时 `CODEX_HOME`；
- `skills.include_instructions=false`、bundled Skills disabled，并关闭 skill search、plugins、
  MCP apps 与 multi-agent；
- 每个 Session 都由现有 `milai codex` launcher 在推理前得到 `ACTIVE` TASK State；
- Session prompt 只要求继续既有任务和执行当前 next action，没有重复注入具体文件、测试名或
  旧失败细节；
- 所有 reconciliation 均通过内部 `milai-hook ReconcileState` 与 exact State/Event window；
- 任务只读，未授权或执行源代码修改。

## 3. Chain A：失败保留与重复失败避免

任务：验证 C4 late-Event watermark protection，不修改文件。

```text
principal  c5-chain-a-host
task_ref   c5-chain-a-20260905-0310
state_id   dc6f62e2-5de8-436f-bc65-943fa08adb6e
state      V1 -> V2 -> V3 -> V4
```

### Session A1

```text
thread 01a06dd3-5ab2-7b62-967c-93a59a2e0550
prefetch ACTIVE V1
```

Codex 从 Working State 恢复目标，定位到 `reconciliation_orchestrator.py` 与对应 regression，
确认 expected watermark 在 CAS 前校验；直接 Python 与 system Python3 没有项目 pytest 环境，
因此没有虚报通过。该失败被 checkpoint 到 V2，next action 改成 package `uv` 命令。

### Session A2

```text
thread 01a06dd4-cdde-7333-bd64-756ecf64bf78
prefetch ACTIVE V2
```

Codex 直接执行 V2 中的 `uv run pytest`，没有重复 A1 的 direct-Python 失败。只读 sandbox 阻止
`uv` 使用缓存，测试未运行。该新失败被写入 V3，next action 改为已有 venv、禁 bytecode 与
pytest cache 的命令。

### Session A3

```text
thread 01a06dd7-b9ad-7f11-a7b6-75a32554fd8a
prefetch ACTIVE V3
```

Codex 执行 V3 的命令，发现 pytest 默认 capture 仍需要可写临时目录，随后在同一 Session
做最小修正 `-s`：

```text
1 passed in 0.19s
exit 0
```

V4 将 task phase 改为 completed、清空 next action，并保留 deferred post-check/pre-CAS race。

## 4. Chain B：stale hypothesis 与 blocker 修正

任务：验证 Working State GET 的 POST transport 是否安全重试，不修改文件。

```text
principal  c5-chain-b-host
task_ref   c5-chain-b-20260905-0336
state_id   fa75983e-82e2-4608-b702-aca9750bd270
state      V1 -> V2 -> V3 -> V4
```

V1 有意保留可证伪 hypothesis：

```text
Working State GET may not retry because the HTTP operation uses POST.
```

### Session B1

```text
thread 01a06dd9-f8ec-7530-a9a2-97736a8f1e95
prefetch ACTIVE V1
```

Codex 用 exact code/test 证据否定 hypothesis：`get_working_state` 显式传入
`read_only_retry_safe=true`，contract test 定义 timeout 后成功重试。V2 清除 hypothesis 与原
inspection blocker。受管 read-only sandbox 内的 asyncio test 挂起，被诚实记录为新 blocker。

### Session B2

```text
thread 01a06ddd-27ad-7672-89fb-2950592b6f43
prefetch ACTIVE V2
```

workspace-write managed sandbox 中同一 test 仍挂起，因此“只发生在 read-only”这一归因被否定。
Host 正常包环境运行相同测试为 `1 passed in 0.30s`。V3 将 blocker 收敛为 managed-sandbox
execution boundary discrepancy，并要求新 Session 做 no-sandbox 隔离。

### Session B3

```text
thread 01a06ddf-a3e9-7833-aa91-84c3ebf036bd
prefetch ACTIVE V3
```

在关闭 Codex managed sandbox 后，相同 test 独立通过：

```text
1 passed in 0.29s
exit 0
```

Git diff/status 与两个 inspected file hash 前后相同。V4 清除 blocker 与 next action，将 task
phase 改为 completed；sandbox 的具体内部机制作为非 MiLA 产品 blocker 的 open question 保留。

## 5. 工程观察

```text
fresh Codex sessions                    6
independent task chains                 2
Host prefetch before reasoning          6 / 6
prefetched State used for next action   6 / 6 observable
State chains reaching completion        2 / 2
stale hypothesis explicitly removed     demonstrated
blocker rewritten then cleared          demonstrated
prior failed path avoided               demonstrated
Canonical mutation                      0
public MCP tool/schema change           0
source change by C5 sessions            0
```

两条链均显示 Working State 对后续 Session 的动作选择有实际影响；不是仅被注入而未消费。失败被
保留后，后续 Session 没有回到最初 direct-Python 或 POST-not-retry 假设。C5 因样本很小，不把
`6/6` 外推为自然 adoption 或一般模型成功率。

## 6. 完成回归

```text
hooks       Ruff / mypy / build PASS; 52 passed
client      Ruff / mypy / build PASS; 174 passed
MCP         Ruff / mypy / build PASS; 148 passed, 1 skipped
Runtime     Ruff / mypy / build PASS; 798 passed, 125 environment-skipped
services    API / worker / public MCP active
Runtime     live / ready PASS
MCP         health / ready PASS
```

Runtime 的 125 项 skip 来自未配置 `MILAI_TEST_*_DATABASE_URL`；C1 已完成 fresh PostgreSQL
`922 passed, 1 skipped` gate，C5 又通过部署中的 PostgreSQL/HTTP 实际完成两条 State/Event
chain，因此没有为了重复同一证明新建数据库审计环境。

## 7. Failure reflection

1. A1 找不到项目 pytest 环境：不改产品，记录失败并把 next action 指向 package runner；
2. A2 的 `uv` 在 read-only sandbox 需要写缓存：不放宽 MiLA policy，改用已有 venv；
3. A3 的 pytest capture 需要临时目录：Codex 自行加 `-s` 后通过；
4. B1/B2 的 asyncio `to_thread` regression 在两种 Codex managed sandbox 中挂起：正常 Host
   与 unrestricted Codex 均在约 0.3 秒通过，因此不为 sandbox-specific behavior 修改客户端；
5. “只读 sandbox 导致 hang”的首次归因被后续 workspace-write 证据推翻，并通过 V3 修正，
   没有把错误归因固化为 established State。

这些失败体现了 reconciliation 的目标价值：Working State 是可修正认知缓存，而非不可变 truth。

## 8. Hard invariants

- 两条 State chain 均绑定独立 principal/project/task；
- 每次 update 都使用 exact head CAS 与 namespaced operation ID；
- State/Event payload 没有提供 scope、authority 或 mutation authorization；
- 每个 changed field 引用 frozen Event window 中的 eligible Event；
- 每份 reconciliation receipt 均为 `canonical_mutation=false`；
- Working State 保持 `HOST_WORKING`，没有写入 Claim/Proposal/Retrieval State；
- Skills 未参与六个 Session，不存在 Skill instructions 稀释或替代 Host bootstrap 的混淆。

## 9. Subagent boundary review

```yaml
functional:
  decision: PASS
  required_fixes: []
architecture:
  decision: PASS
  required_fixes: []
generalization_and_simplicity:
  decision: PASS
  required_fixes: []
```

审计明确将 `6/6` 限定为受控 prompt 下 Host-prefetched State 的可观察消费，不解释为自然
adoption、paired causal gain 或一般成功率。审计建议修正的 pre-C5 历史缺口措辞和 activation
字段歧义已处理；机器可读逐 Session artifact index 仅在未来需要更强可重复审计时再增加。

## 10. 明确延期

- 自动 dirty detection、session-end checkpoint 与 model-forced StateDelta generation；
- persisted `StateBasisCursor` / freshness claim；
- managed sandbox 内 asyncio `to_thread` 的环境机制调查；
- resume token/time paired baseline 与统计效果研究；
- 大规模 task chain、semantic grounding benchmark、人工 gold；
- Event batching、epoch/replayability、retention-gap hardening；
- Product-11 Retrieval Evolution。

Phase C 已为最小 Event -> Delta -> Working State -> fresh Session continuity 闭环提供真实产品
可用性 Engineering signal。后续复杂度应继续由可复现 failure 或独立 Research Mode claim
驱动。
