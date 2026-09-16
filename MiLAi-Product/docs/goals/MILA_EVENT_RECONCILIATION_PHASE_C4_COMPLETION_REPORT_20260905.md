---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C4-COMPLETION
version: "1.0"
status: PASS_EXPLICIT_RECONCILIATION_ORCHESTRATION
date: 2026-09-05
milestone: PHASE_C4_EXPLICIT_RECONCILIATION_ORCHESTRATION
public_mcp_schema_change: NONE
automatic_activation: NONE
model_call: NONE
canonical_change_authority: NONE
---

# MiLA Event Reconciliation Phase C4 完成报告

## 1. 结论

C4 已交付一个可真实调用的 trusted Host command：

```text
Host supplies Codex-produced StateDelta
  -> read exact TASK Working State head
  -> read complete bounded Event window
  -> verify expected Event high watermark
  -> C3 validate/merge
  -> no material change: no write
  -> material change: exact Working State CAS
```

终态：

```text
PASS_EXPLICIT_RECONCILIATION_ORCHESTRATION
```

它不新增 public MCP tool，不决定何时 checkpoint，不调用隐藏模型，不持久化 Basis，也不修改
Canonical 或 Retrieval State。

## 2. 已实现

- 新增 `milai_hooks.reconciliation_orchestrator.reconcile_working_state_explicit`；
- 新增 `milai-hook ReconcileState` 内部 Host command；
- principal/project/task binding 只来自 Host environment，stdin 不能覆盖；
- ReconcileState 只依赖 Host scope，不再构造或校验无关的 recall authority/policy；
- 只接受 `ABSENT(null/0)` 或 exact `ACTIVE(id/version)` TASK State；
- Event window 必须完整，并满足
  `after_position <= next_position <= visible_high_watermark`；数字 position gap 合法；
- apply 必须携带 Codex 实际看到的 `expected_event_high_watermark`；晚到 Event 会返回
  `EVENT_WINDOW_CHANGED`，不会被误算入 basis candidate；
- 带 stale/revoked Evidence warning 的 Event 不具备 Delta 引用资格；被引用时返回
  `EVENT_REFERENCE_NOT_ELIGIBLE`；
- `no_material_change=true` 不调用 Working State update；
- material Delta 使用 C3 merge result 的 exact State ID/version 构造 CAS；
- Runtime update response 的 authority、scope、version、chain ID 与 payload 会被重新验证；
- public operation ID 在送入 Runtime 前按 contract/principal/project/task 做 SHA-256 namespace，
  Host receipt 仍保留公共 ID；
- Python client 的只读 Working State POST GET 现在可安全重试瞬时 transport/503；
- CLI 错误返回 `code/problem/fix`；Runtime error 保留安全 details，失效 Evidence、stale State、
  operation conflict 与 transient failure 有不同修复建议。

## 3. 真实 PostgreSQL/HTTP E2E

第一条真实链：

```text
Evidence cb163a45-3d82-4d75-b7ea-6aa27c284a23
Event    72a07d87-fb74-458b-8c40-a72474d09109 / position 11

ABSENT + material Delta
  -> UPDATED / State V1
  -> next_actions = Run the focused C4 regression

same State + no-material Delta
  -> NO_MATERIAL_CHANGE
  -> version remains V1

Event    3d2575d8-72e1-48a3-a154-77fc875b4157 / position 12

old expected watermark 11
  -> REJECTED / EVENT_WINDOW_CHANGED / exit 2
  -> no State write

fresh watermark 12 + fresh Delta
  -> UPDATED / State V2
  -> GET confirms TASK / HOST_WORKING
  -> next_actions = Validate the complete integration suite
```

第二条真实链验证 namespace：同一 Runtime actor、同一 project、相同 public operation ID 下，
两个不同 principal/task 分别使用 Event positions 13/14，各自独立创建 State V1，均为
`UPDATED`，没有 `OPERATION_CONFLICT`。

## 4. 测试与构建

```text
hooks full suite                 52 passed
hooks Ruff                       PASS
hooks mypy                       PASS
hooks wheel                      PASS

python-client full suite         174 passed
python-client Ruff               PASS
python-client mypy               PASS
python-client wheel              PASS

MCP full suite                   148 passed, 1 skipped
MCP Ruff                         PASS
MCP mypy                         PASS
MCP wheel                        PASS

Runtime focused contracts        9 passed, 5 env-skipped
deployed PostgreSQL/HTTP E2E      PASS
public codex-full tool count      unchanged (13)
```

Unit/CLI coverage includes create、update、no-material、State base mismatch、CAS conflict、late
watermark、incomplete window、cursor overrun、numeric gaps、invalid/revoked ref、unusable State、
malformed Runtime response、operation namespace 与 structured error repair。

## 5. Failure reflection

开发中遇到的失败均先归因再修复：

1. `python -m build` 失败是 hooks venv 未安装 `build`，改用项目原生 `uv build`，未新增无关依赖；
2. 首次真实 Evidence capture 403 是部署处于 synthetic data mode，而 hook 默认 PERSONAL；测试
   显式使用 SYNTHETIC，没有放宽 Runtime data policy；
3. 跨 binding E2E 的 jq 夹具使用保留字 `label`，JSON 在产品调用前即生成失败；改用 `name` 并
   用全新 binding 重跑；
4. 审查发现 cursor 可超前、operation ID 可跨 task 碰撞、reconciliation 误依赖 recall policy、
   stale ref 错误含义不准；全部以小型 invariant/namespace/helper 修复，没有增加数据库状态机；
5. C4 最初只绑定 State head，未绑定 Codex 所见 Event high watermark；真实 E2E 前补上 expected
   watermark，避免晚到 Event 被误报为已 reconcile。

## 6. Subagent boundary review

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

三位 reviewer 的 required findings 均已修复并由原 reviewer 复核。没有人工 adjudication。

## 7. 明确延期

- automatic dirty/checkpoint/session-end activation；
- persisted StateBasisCursor 与 freshness claim；
- 超过 200 Events 的分批 reconciliation；
- Event read 与 State CAS 之间的 Evidence revoke 原子重验；
- external whole-command crash 后的 orchestration receipt recovery；
- Codex StateDelta generation host/API harness；
- semantic grounding benchmark 与 Research Mode effect claim。

C4 的 `basis_candidate.persisted=false` 是诚实边界，不能将本阶段解释为完整自动 continuity
lifecycle。下一步 C5 只用少量真实连续任务链验证 StateDelta/Working State 是否实际有用；如果
没有价值，不提前实现上述 hardening。
