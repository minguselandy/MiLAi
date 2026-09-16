---
document_id: MILA-PRODUCT-09
version: "1.1"
status: PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE
created_at: "2026-09-03T21:00:00+08:00"
product_version: 0.1.0-candidate
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
predecessor: MILA-PRODUCT-08@1.1
---

# Product-09：Codex HTTP 持久记忆生命周期

## 1. Goal

在 P08 已通过的 Streamable HTTP MCP 产品面上，完成最短、真实、可重启的 coding-agent
memory 闭环：

```text
trusted HostAgentEvent
→ Raw Evidence in PostgreSQL
→ official projection worker
→ milai-mcp HTTP
→ Codex tool call
→ evidence-grounded answer
```

本 Goal 优先证明实际可用性，不开发新的 Reader、EvidenceLedger、vLLM、QueryIR 类型系统、
EvidenceSet 算法或 Canonical 自动写入。

## 2. 产品边界

```text
Host owns:
  whether to call memory
  semantic sufficiency
  residual query
  final answer

MiLAi owns:
  trusted principal and project scope
  Raw Evidence persistence
  session / source / turn identity
  permission / revocation / temporal validity
  retrieval, dedup and Context rendering
  retrieval trace
```

模型参数继续仅允许：

```text
query
previous_context_id (optional)
```

`HostAgentEvent` 由可信 hook 提交，不注册为 Codex 可见 MCP write tool。

## 3. 交付范围

### P09-0 — 一步式 Codex HTTP 配置

扩展 `milai-ops agent-config`：

```bash
milai-ops agent-config \
  --transport streamable-http \
  --profile agent-memory \
  --url http://127.0.0.1:7337/mcp
```

输出 secret-free Codex 配置，只引用 `MILAI_MCP_HTTP_BEARER_TOKEN`，不复制 Runtime token、
tenant、subject 或 project scope。

### P09-1 — Host capture 与幂等性

通过正式 `milai-hook AgentEvent` 写入至少两类 coding history：

- design decision；
- verified tool/fix outcome。

每个事件保留真实 session/source/turn identity。重复提交同一 event 必须复用相同 Evidence，且
`canonical_mutation=false`。

### P09-2 — PostgreSQL restart recall

在独立临时 PostgreSQL 上运行 migration、API 和 projection worker，等待正式 Evidence projection
ready；停止并重启 API、worker 和 HTTP MCP 后，Codex 必须仍能通过 `/mcp` 找回已写入内容。

### P09-3 — 最小真实可用性切片

使用 Codex 运行以下通用场景：

1. 找回一个 coding design decision；
2. 重启后找回一个 verified command/fix；
3. 无历史依赖问题不调用 memory；
4. 固定 project scope 不返回另一 project 的 marker。

测试内容运行时随机生成，不写入产品源码，不使用 LongMemEval case ID、gold quote 或同义词补丁。

## 4. PASS 条件

```text
CaptureSuccess                         = 100%
ProjectionReady                       = 100%
DuplicateEventCreatesNewEvidence      = 0
RestartRecallSuccess                  = 100%
MemoryRequiredToolInvocation          = 100%
NoMemoryToolInvocation                = 0
CrossProjectEvidenceLeak              = 0
CanonicalMutation                     = 0
ModelVisibleWriteTools                = 0
InternalReaderCalls                   = 0
vLLMCalls                             = 0
AutomaticSemanticRetries              = 0
```

这些门只适用于本 Goal 的小型 usability slice，不构成正式 benchmark、Schema freeze 或生产发布声明。

## 5. 高效失败循环

阶段通过后自动进入下一阶段。阶段失败时不立即终止 Goal：

```text
失败
→ 定位 capture / projection / retrieval / MCP / Host reasoning 首个边界
→ 保留一条紧凑失败记录
→ 修复可泛化根因
→ 只重跑失败场景
→ 通过后继续
```

禁止以以下方式追求通过：

```text
增加 case-specific term / synonym
硬编码答案或 marker
对同一模型错误自动重试
只扩大 Top-k 掩盖 identity / projection 错误
把 Host sufficiency 重新塞回 Runtime
为每次失败新增 schema、receipt 层或 Goal 编号
```

若一个失败需要改变 public API、数据库 Schema、Canonical authority 或 P08 MCP contract，先记录为
successor issue；本 Goal 不在现场扩大范围。

## 6. 验证与制品

只保留：

```text
Goal + Tracker
一份机器可读 summary
必要的首次失败记录
最终 Product/Lab pin
```

验证采用受影响单测、Ruff、strict mypy、构建、Lab boundary，以及一轮真实 PostgreSQL + Codex
HTTP E2E。Formal 500-case holdout 不运行。

## 7. 终态

```text
PASS_PRODUCT09_CODEX_HTTP_PERSISTENT_MEMORY_USABLE
PARTIAL_PRODUCT09_RUNTIME_USABLE_HOST_REASONING_UNRESOLVED
PARKED_PRODUCT09_PERSISTENCE_OR_SCOPE_UNRESOLVED
FAIL_PRODUCT09_AUTHORITY_OR_DATA_LEAK
```

只有泄漏、越权或 Canonical 非授权写入直接进入 FAIL。普通实现/模型失败按第 5 节修复循环推进。

## 8. 执行结果

Product-09 已完成。正式生命周期 run `product09-e2e-003` 通过：4 次 HostAgentEvent 提交形成
3 条唯一 Evidence，重复 event 幂等；3/3 Evidence 及 projection 持久化，API、worker 和 HTTP
MCP 重启后仍可召回。Codex 在 design、verified fix、no-memory、cross-project 四场景中分别
产生 1/1/0/1 次 memory tool call，答案与隔离均正确。Canonical mutation、内部 Reader、vLLM、
模型可见写工具和自动语义重试均为 0。

随后使用 4 个 opened-development LongMemEval case 进行非 formal 诊断。1,772 个真实历史 turn
经 HostAgentEvent 写入，8 路并发 capture、4 路并发 Codex；普通用户 lookup、assistant answer
lookup、跨 session COUNT、state update 四类中 3/4 精确正确，必需 gold session 4/4 全部可见。
answer-turn 级复核显示 3/4 case 的全部标注 turn 可见；COUNT case 为 3/4，其中缺失 turn 是已由
另一个可见 turn 覆盖的 blazer 重复陈述。Codex 仍将三个待处理实例回答为两个，故不把该失败
伪装成检索或产品 PASS。

一次通用的长 server-instruction treatment 将结果从 3/4 降至 2/4，并让 state update 选择旧值，
因此已撤回。产品保留较短的 P08 Host/MiLA 职责说明，不引入 EvidenceLedger 或新的回答协议。

权威制品：

```text
MiLAi-Lab/var/product09/e2e-003.json
MiLAi-Lab/var/product09/lme-002.json
MiLAi-Lab/var/product09/lme-003-count.json
MiLAi-Lab/var/product09/lme-004-host-guidance.json  # rejected treatment evidence
MiLAi-Lab/data/locks/product09-product.lock.json
```

该结果证明 Codex HTTP MCP 的持久化产品闭环可用；不构成 LongMemEval 排行榜、formal holdout、
完整多证据聚合或生产发布声明。
