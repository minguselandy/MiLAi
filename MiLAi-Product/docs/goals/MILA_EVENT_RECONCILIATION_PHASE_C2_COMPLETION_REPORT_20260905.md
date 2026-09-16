---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C2-COMPLETION
version: "1.0"
status: PASS_MINIMAL_SPARSE_OBSERVATION_ADAPTER
date: 2026-09-05
milestone: PHASE_C2_SPARSE_OBSERVATION_ADAPTER
public_mcp_schema_change: NONE
canonical_change_authority: NONE
working_state_mutation: NONE
---

# MiLA Event Reconciliation Phase C2 完成报告

## 1. 结论

C2 已交付一条默认关闭、显式 `SHADOW` 才启用的最小 Host adapter 路径：

```text
Host-visible AgentEvent
  -> immutable Evidence capture
  -> exact Evidence identity
  -> sparse HostExecutionEvent append
```

终态：

```text
PASS_MINIMAL_SPARSE_OBSERVATION_ADAPTER
```

该路径不新增 MCP tool，不更新 Working State，不触发 reconciliation，也不产生 Canonical mutation。

## 2. 已实现

- Python client 增加 trusted internal Host Event append/window REST passthrough；
- 只读 POST window 显式标记 retry-safe，可重试瞬时 transport/503，409 仍不重试；
- Hook 支持 `MILAI_HOST_EVENT_JOURNAL=OFF|SHADOW`；默认 `OFF`；
- principal/project/task binding 只从 Host 环境读取，AgentEvent JSON 无法覆盖；
- SHADOW 静态配置和 project-in-scope 在任何 Evidence write 前完成验证；
- user/assistant message 映射为 `DIALOGUE/MESSAGE`，只写 role、observed_at 与 exact Evidence ID；
- session marker 映射为 `LIFECYCLE/SESSION_BOUNDARY`，不推断 dirty；
- `TOOL_RESULT`/`ARTIFACT_CHANGE` 暂不逐条写 journal，返回
  `NOT_JOURNALED_REQUIRES_AGGREGATION`；
- Evidence 已提交而 Event 动态失败时返回
  `PARTIAL_EVIDENCE_CAPTURED_JOURNAL_PENDING_RETRY`，保留 Evidence receipt、reason code 与两种
  retry 属性，不伪装整体失败或 Event 成功；
- Evidence/Event operation identity 都稳定，整条 AgentEvent 可安全重放。

## 3. 测试与真实 E2E

```text
python-client full tests     173 passed
hooks full tests              17 passed
Ruff                          PASS
mypy                          PASS
python-client build           PASS
hooks build                   PASS
```

部署 happy path：

```text
USER_MESSAGE
  Evidence d015afc0-6f63-42b9-a057-291549491b02
  Event    ff72e455-17b0-4ee9-94aa-1797aaf7c595
  position 10
```

Window 返回 exact Evidence ref 与 `{"role":"USER"}`，没有消息正文。相同 AgentEvent 再执行时，
Evidence 与 Event 均返回 `replayed=true` 且 identity 不变。

CLI failure tests 还证明：

- project mismatch 时 capture=0、append=0；
- 动态 journal failure 时 capture=1、append attempted=1，并输出 typed partial receipt；
- read-only window TimeoutError 后可成功 retry；409 不进行第二次请求。

## 4. Failure reflection

初版有三个功能问题：

1. Event window 是只读 POST，但通用 client 只把 GET/带 operation ID 的请求视为 retry-safe；
2. SHADOW 配置在 Evidence capture 后才验证，错误配置可能留下已写 Evidence 却整体抛错；
3. 动态 Event append 失败没有告诉调用方 Evidence 已成功提交。

修复遵循最小通用原则：给内部只读调用增加显式 retry-safe flag；抽出 preflight 并前移；用 typed
partial receipt 描述两阶段结果。没有增加 repair queue、事务性跨服务写入或新的数据库状态机。

`event_retry_safe=true` 只表示相同 Event 幂等重放不会重复；调用方只有在
`runtime_retryable=true` 时才应自动重试，认证/配置错误需先修复。

## 5. Subagent review

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

功能 reviewer 的三项 required finding 已修复并由原 reviewer 复核。没有人工 adjudication。

## 6. 明确延期

- tool/file/test/command/Git 的有界聚合；
- repair queue 或跨 Evidence/Event 原子事务；
- automatic dirty、checkpoint 或 resume reconciliation；
- StateDelta apply；
- typed public Event model 与 public MCP Event tools；
- journal retention/replayability hardening。

下一步是 C3：实现纯 Host-side、有限字段的 StateDelta validate/merge primitive。它先处理
KEEP/REPLACE/CLEAR 和 Event reference validity，不调用模型、不写 Working State；实际 Codex Delta
生成与 checkpoint orchestration 留给后续小增量。

