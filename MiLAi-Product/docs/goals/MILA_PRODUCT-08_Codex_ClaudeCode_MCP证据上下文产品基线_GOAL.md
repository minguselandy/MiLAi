---
document_id: MILA-PRODUCT-08
version: "1.1"
status: PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE
created_at: "2026-09-03T18:00:00+08:00"
updated_at: "2026-09-03T20:15:00+08:00"
product_version: 0.1.0-candidate
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
---

# Product-08：Codex Streamable HTTP MCP 证据上下文产品基线

## 1. Goal

将 MiLAi 从“内部 Reader 实验系统”收敛为可被 Codex 通过常驻 Streamable HTTP MCP
直接使用的持久记忆控制面：

```text
Host owns semantic sufficiency.
MiLAi owns memory correctness.
```

本 Goal 优先完成真实可用的最短闭环，不开发新检索算法。正常 MCP read path 不运行 MiLAi 内部
Reader、EvidenceLedger、生成式 `COMPLETE` 或 vLLM。

## 2. 规范关系

本文件是 Product-08 唯一执行导航。此前以 Product-08 名义记录的 Additive Recall / Informational
Admission 候选降为：

```text
P08-PREBASE-CONTEXT-CANDIDATE
default OFF
retained as diagnostic implementation
not Product-08 execution authority
```

ADR-029 和对应代码不删除；它们只有在独立 read-path Goal 中重新获得 effect 证据后才能启用。
Product-07 terminal、Product-05/06 Reader 失败事实和 Product-03 OpenWorker 可用性事实保持不变。

## 3. 职责边界

| 能力 | Host Agent | MiLAi MCP/Runtime |
| --- | ---: | ---: |
| 判断是否调用记忆 | ✓ | 可提供说明 |
| 理解证据、判断普通回答是否充分 | ✓ | |
| residual query、工具循环、最终回答 | ✓ | |
| principal/tenant/project scope | | ✓ |
| Evidence 持久化与身份 | | ✓ |
| canonical currentness / as-of validity | | ✓ |
| permission / retention / revocation | | ✓ |
| routing / FTS / Dense / dedup | | ✓ |
| retrieval/context trace | | ✓ |
| 生成式 Reader / EvidenceLedger | 不需要 | 不需要 |
| vLLM | Host 自身模型 | `none` by default |

Host 的 sufficiency 判断不能覆盖 MiLAi 的 memory correctness。Host 不得通过 prompt 把 revoked、
cross-scope、historical 或 contested Evidence 宣告为当前合法状态。

## 4. MCP read contract

### 4.1 Profile 与输入

`agent-memory` 只注册：

```text
milai_memory_resolve(query, previous_context_id?)
```

禁止成为 tool argument：

```text
tenant_id
principal_id
project_id
repo/worktree identity
authority
consistency
budget/profile
```

这些值来自可信 Host 环境或进程启动参数。

### 4.2 输出

权威 Schema：

- `contracts/agent/v1/memory-evidence-context-v1.schema.json`

```json
{
  "schema_version": "memory-evidence-context-v1",
  "retrieval_status": "HIT",
  "context_id": "ctx-123",
  "snapshot": {"canonical_position": 42},
  "continuation": null,
  "evidence": [],
  "warnings": [],
  "profile": {
    "requested": null,
    "resolved": "MCP_INTERACTIVE_STANDARD_V01"
  }
}
```

`retrieval_status` 只表达检索执行：

```text
HIT       有 Host-visible governed evidence
MISS      正常执行但没有 Host-visible evidence
DEGRADED  存在明确 retrieval/canonical degradation
ERROR     access denied 或 Runtime unavailable
```

它不表达答案是否完整。Runtime 内部 `PARTIAL` 不能直接变成 Host-facing semantic `PARTIAL`。

`continuation` 只转发 Runtime 明确证明的 frontier。当前 Runtime 没有该证明时必须为 `null`，即使
Context 被截断也不能据此虚构 continuation。以后若实现 `FRONTIER_EXHAUSTED`，必须来自可重放的
Runtime 状态，而不是模型判断。

Evidence 只来自真正 Reader-visible window/context 或 canonical item；不暴露 BM25/Dense/rerank
score、内部 requirement、Binding 或 operator trace。

### 4.3 HTTP transport 与身份

P08 产品 endpoint：

```text
http://127.0.0.1:7337/mcp
```

```text
Codex bearer token
  → HTTP authentication
  → server-owned principal
  → fixed non-empty project scope
  → Runtime authorization
```

`MILAI_MCP_HTTP_BEARER_TOKEN` 是 Codex 到 MCP 的入站凭据；`MILAI_AGENT_TOKEN` 是 MCP 到
Runtime 的独立凭据。`/healthz` 是存活探针，`/readyz` 验证 Runtime capabilities，
`/mcp` 必须有 Bearer 认证。stdio 仅保留给 OpenWorker 兼容、SDK 单测和本地调试，不计入 P08 验收。

### 4.4 Budget profile

```text
MCP_INTERACTIVE_STANDARD_V01  50/120 candidates, 8192 tokens, 2000 ms, calls≈3
MCP_INTERACTIVE_WIDE_V01      50/120 candidates, 16384 tokens, 5000 ms, calls≈3
MCP_RESEARCH_V01              50/120 candidates, 16384 tokens, 5000 ms, calls≈5
```

调用数是 server instruction 中的 Host guidance，不是协议硬停止。旧 OpenWorker 名称保持 alias，
不得改变原预算。

## 5. 两种产品等级

### MCP Interactive

```text
User → Host decides whether to call → MiLAi evidence → Host answer
```

保证 memory 可用；不保证 Host 在所有历史依赖任务上主动调用。

### Host-Prefetch

```text
User → trusted wrapper resolves memory → evidence block → Host reasoning
```

用于必须访问 memory 的部署。Interactive 与 Prefetch 的 invocation、retrieval 和 answer 指标必须
分开报告。

## 6. Host capture contract（后续 write-path）

权威 Schema：

- `contracts/agent/v1/host-agent-event-v1.schema.json`

`HostAgentEventV1` 由 Host hook 创建，不是模型可调用的 MCP read 参数。它记录真实 user message、
assistant message、tool result、artifact change 或 session marker，然后通过现有 Evidence capture
路径写入 Raw Evidence：

```text
HostAgentEvent → EvidenceRecord
```

它不能自动创建 Claim、OpenIssue 或 Canonical mutation。assistant 输出可作为发生过的交互 Evidence，
但不能自动提升为用户事实。该 schema 和适配器保留；真实 PostgreSQL capture/restart
属于后续 write-path Goal，不是 P08 HTTP read-path PASS 的前置。

## 7. 执行阶段

### P08-0 — HTTP facade 与 authority（PASS）

交付：

- `agent-memory` profile；
- `memory-evidence-context-v1` renderer/schema；
- neutral budget profiles 与 deprecated aliases；
- OpenWorker stdio `reader-lite` 输出兼容；
- Streamable HTTP `/mcp`、Bearer principal binding、`/healthz` 和 `/readyz`。

通过条件：

```text
agent-memory only exposes milai_memory_resolve
model arguments exactly query / previous_context_id
raw scores/Binding/Sufficiency/Reader output absent
continuation not inferred
unauthenticated /mcp rejected
fixed server-owned scope reaches Runtime
reader-lite compatibility tests pass
```

当前证据：MCP 62 passed；包含真实子进程 HTTP smoke、Bearer 拒绝、就绪探针、tool discovery、
facade 输出和固定 scope；Ruff、strict mypy 通过。

### P08-1 — Codex real Streamable HTTP E2E（PASS）

至少覆盖：

```text
tool discovery
one memory-required invocation
facade schema parse
evidence-grounded final answer
one no-memory-needed control
one focused follow-up when context_id exists
```

必须区分：Host 未调用、MiLA MISS、MiLA 返回正确证据但 Host 错答。

Codex CLI `0.151.0` 已完成三个独立黑盒场景：

```text
memory-required  1 resolve，精确证据回答
no-memory        0 resolve，Host 自行回答
continuation     2 resolve，第二次只增加 previous_context_id，获得不同 Evidence
```

三场景答案均精确，模型参数键只出现 `query / previous_context_id`；Codex 使用 URL 和
`bearer_token_env_var` 连接独立常驻 `milai-mcp`。该结果证明 Codex/HTTP/facade 工具闭环，
不代表真实数据库检索质量或 LongMemEval 准确率。

### P08-2 — Host 范围收敛（PASS）

P08 仅以 Codex 作为真实 Host 验收面。Claude Code 和其他 Host 可以在后续重用同一 HTTP
contract，但不是 P08 PASS 前置，也不在本 Goal 中声称兼容性。

### P08-3 — HostAgentEvent capture（后续 Goal）

将 Host hook 的事件身份绑定到现有 Evidence capture，验证 user/assistant/tool 三类最小链路、幂等
重放、重启召回和 assistant 非 Canonical。此阶段不增加模型可见写工具。

当前已交付 Host-only `milai-hook AgentEvent` 适配器和三类映射单测。真实 PostgreSQL
capture/replay/restart recall 后移，不影响 P08 HTTP read facade 终态。

### P08-4 — Multi-turn coding usability（后续 Goal）

用小型真实 coding-memory 场景测试：历史决定、失败修复、恢复中断 thread、跨 session 证据与无需
memory 的普通任务。它用于评估真实检索效果，不回溯改变 P08 HTTP transport 结论。

## 8. 仅保留三组指标

```text
Correctness
  CrossScopeLeak = 0
  CanonicalMutationFromRecall = 0

Usability
  MemoryRequiredToolInvocationRate
  FirstRecallUsefulRate
  ContinuationEvidenceGain
  DuplicateEvidenceRate
  AnswerTaskSuccess

Operational
  P50Latency
  P95Latency
```

失败归因顺序：

```text
no invocation       → Host integration
invoked, no evidence → MiLA retrieval
follow-up no gain    → continuation/routing
correct evidence     → Host reasoning
```

## 9. 高效开发与失败处理

每个阶段通过后自动进入下一阶段，不等待重复授权。可修复失败按以下循环处理：

```text
保留一个最小失败样本
→ 定位首次失败边界
→ 修复通用原因
→ 只跑失败样本和邻近回归
→ 通过后继续原阶段
```

最多保留一份 Tracker 和必要测试输出，不建立多层 receipt/manifest。只有 authority、identity、Schema、
跨进程协议或正式方法效果需要额外审查。

禁止：

```text
case ID / gold phrase / benchmark synonym 分支
为单一失败增加 query type
自动重试掩盖失败
用更大 Top-k 替代根因修复
把内部 Reader/vLLM 带回 MCP read path
把 Host sufficiency 写成 Runtime COMPLETE
```

失败时可参考 Hindsight、ReFind、Mem0、Graphiti、OpenViking 的机制，但只吸收能解释当前 first loss
的最小机制，不预先建设 graph、agent planner 或 consolidation platform。

## 10. Terminal

允许终态：

```text
PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE
PARTIAL_PRODUCT08_MCP_FACADE_USABLE_HOST_INVOCATION_UNRESOLVED
FAIL_PRODUCT08_MEMORY_CORRECTNESS_BOUNDARY
```

PASS 要求真实 Codex Streamable HTTP tool discovery、必需记忆调用、无记忆控制、
continuation、Bearer 拒绝、固定 scope、零 recall canonical mutation 全部通过。当前已满足，
终态为 `PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE`。

本 Goal 不授权数据库 migration、non-loopback public MCP、multi-principal issuer、Schema freeze、
formal LongMemEval 500 或默认启用
ADR-029 检索候选。Schema 继续 `NO-GO FOR SCHEMA FREEZE`。
