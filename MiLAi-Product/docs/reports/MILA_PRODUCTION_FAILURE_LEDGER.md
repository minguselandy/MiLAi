---
document_id: MILA-PRODUCTION-FAILURE-LEDGER
version: "1.0"
status: ACTIVE
created_at: "2026-09-05T09:33:00+08:00"
baseline: MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1
open_failures: 0
fixed_failures: 1
---

# MiLA Production Failure Ledger

## 1. 用途

本 Ledger 是功能基线之后新增产品机制的默认入口。它只记录真实 Codex/用户任务中可观察的失败，
不把 benchmark proposal、未来风险或架构偏好伪装成 production failure。

Phase A--D2 开发过程中已经修复的问题保留在各 completion report，不回填为尚未解决的
production failure。基线冻结后的真实使用 observation 从本文件顺序记录。

## 2. 分类

| Layer | 判定问题 | 归属 |
| --- | --- | --- |
| `ACTIVATION` | 应访问 memory，但 Host/model 没有访问 | Activation Policy |
| `ACQUISITION` | 已访问 memory，但 coarse source 未找到 | retrieval routing/acquisition |
| `FINE_COVERAGE` | source 已找到，但正确 turn/span 未暴露 | D2 explicit intra-source acquisition |
| `CONTINUATION` | first Context 不足，continuation 无 novel useful Evidence | persisted frontier/selection |
| `RECONCILIATION` | Evidence 正确，但跨 Session State stale/wrong | Event reconciliation |
| `HOST_REASONING` | Evidence/State 均正确可见，Codex 仍答错或执行错 | Host；不得继续修改 MiLA |

分类发生在证据采集之后。初始记录允许 `layer: UNCLASSIFIED`，不能为了匹配待开发机制提前归因。

## 3. 最小记录格式

```yaml
failure_id: MFL-YYYYMMDD-NNN
baseline_tree_sha256:
task_ref:
observed_at:

layer: UNCLASSIFIED | ACTIVATION | ACQUISITION | FINE_COVERAGE | CONTINUATION | RECONCILIATION | HOST_REASONING
symptom:
expected:
observed:

evidence_refs: []
context_or_state_refs: []
reproducible: true | false | pending
reproduction:

candidate_mechanism:
smallest_safe_change:
status: OPEN | REPRODUCED | FIXING | FIXED | NOT_MILA | NON_REPRODUCIBLE | PARKED
verification:
```

不得在 Ledger 中保存 token、credential、原始个人数据或 hidden reasoning。正文需要保留时先进入
governed Evidence，Ledger 只引用 exact identity。

## 4. 开发准入

```text
OPEN observation
  -> reproduce
  -> classify by earliest failing layer
  -> propose smallest mechanism
  -> implement/test
  -> verify against the same failure
  -> FIXED or PARKED
```

单个不可复现 observation 默认不触发新机制；安全/跨 scope/authority 失败例外，首次可靠复现即可
进入修复。`HOST_REASONING` 条目不能用于授权 MiLA retrieval/state 变更。

## 5. Active entries

```text
NONE
```

## 6. Resolved entries

### MFL-20260905-001 — empty Runtime envelope was exposed as an Evidence HIT

```yaml
failure_id: MFL-20260905-001
baseline_tree_sha256: f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1
task_ref: real-use-r1-history
observed_at: 2026-09-05T09:53:00+08:00

layer: UNCLASSIFIED
component: MCP_RESULT_RENDERING
symptom: MCP reported retrieval_status=HIT for an ABSENT/ABSTAINED Runtime envelope.
expected: retrieval_status=MISS and evidence=[] when Runtime has no Host-visible Evidence.
observed: the bounded memory_status envelope became one EVIDENCE_CONTEXT with evidence_ids=[].

evidence_refs: []
context_or_state_refs:
  - 61f28475-b589-4bc1-9eb4-dc4038a8acd3
  - f50cabdf-2014-4734-86cd-9570106d93cc
reproducible: true
reproduction: fresh zero-Skill Codex received both ABSTAINED and ABSENT empty envelopes as HIT.

candidate_mechanism: none; correct the existing MCP projection boundary.
smallest_safe_change: do not render ABSENT/ABSTAINED Runtime control envelopes as Evidence units.
status: FIXED
verification:
  - focused renderer suite 6 passed
  - complete MCP suite 156 passed, 1 skipped
  - Ruff and mypy passed
  - package build passed
  - deployed public no-match probe returned MISS with zero Evidence
  - fresh positive-HIT Codex task still returned eight governed Evidence units and answered correctly
```

The layer remains `UNCLASSIFIED` because the defect occurred after Runtime acquisition but before Host
reasoning; it is not relabeled as `ACQUISITION` merely to fit the existing six-layer taxonomy. The
repair removed a false presentation promotion and did not change retrieval, continuation, D2,
Canonical state, scope, authority, or the public tool input schema.
