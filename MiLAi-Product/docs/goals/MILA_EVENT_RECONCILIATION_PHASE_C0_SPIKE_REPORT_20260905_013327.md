---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C0-SPIKE
version: "1.1"
status: PASS_EVENT_RECONCILIATION_VALUE_SIGNAL
date: 2026-09-05
milestone: PHASE_C0_NO_MIGRATION_USEFULNESS_SPIKE
schema_change_authority: NONE
canonical_change_authority: NONE
---

# MiLA Event Reconciliation Phase C0 Spike 报告

## 1. 目的

在写 Event Journal migration 之前，先验证最小产品假设：

```text
previous Host Working State
  + sparse observation-first events from real failures
  -> tool-free Codex StateDelta
  -> useful corrected Working State
```

本阶段不写数据库、不更新真实 Working State、不改 public MCP schema，也不声明模型效果。

## 2. 固定输入

输入包含本轮开发中三个真实失败/修复轨迹：

1. 公网 endpoint 的 proxy `502` 被误判为服务故障；
2. fresh `CODEX_HOME` 被误当成 zero-Skill 证明；
3. Proposal 只做顶层 project check，遗漏 nested Evidence refs。

Event 只使用 `DIALOGUE/MESSAGE`、`EXECUTION/COMMAND_RESULT`、`FILES_CHANGED` 与
`TEST_RESULT` 等观察词汇，不预先声明 requirement、decision、hypothesis 或 blocker 的变化。
Dialogue 在该离线 fixture 中直接附带被 reviewer 观察到的 bounded content；C1 产品设计仍要求
通过 exact Evidence ref 获取内容，不复制 raw dialogue。

工件：

- `artifacts/phase-c0/reconciliation-input-v1.json`
- `artifacts/phase-c0/state-delta-output-schema-v1.json`
- `artifacts/phase-c0/state-delta-codex-output-v1.json`
- `artifacts/phase-c0/reconciliation-input-case2-v2.json`
- `artifacts/phase-c0/state-delta-output-schema-case2-v2.json`
- `artifacts/phase-c0/state-delta-codex-output-case2-v2.json`

## 3. 执行边界

Dedicated Codex 调用使用：

```text
skills.include_instructions=false
skills.bundled.enabled=false
skill_search/recommended_plugins/enable_mcp_apps/multi_agent disabled
user config ignored
project rules ignored
MCP servers 0
shell/tool calls 0
strict structured output
read-only sandbox
```

`StateDelta` 只允许预注册字段，以及 `REPLACE/CLEAR`。缺失字段语义为 KEEP；每个变化必须引用
本 case 的 `reason_event_ids`。C0 wire format 将 replacement value 表达为 JSON 编码字符串，
用于避免在价值 spike 前建立完整认知字段 Schema；它不是最终 Product wire contract。

case2-v2 修正运行 receipt：

```text
model       gpt-5.6-sol
thread_id   01a06d7e-7281-7a30-8f58-37b5be46b271
exit        0
tool calls  0
```

## 4. 机械验证

初次 v1 三 case 输出：

```text
cases                                   3
valid changed fields                   19
valid event references                 43
invalid/out-of-window references        0
duplicate changed fields                0
invalid operations                      0
unparseable replacement values          0
authority/scope/cursor changes           0
Canonical or Retrieval mutation         0
```

zero-Skill case2-v2 修正输出：

```text
cases                                   1
valid changed fields                    6
valid event references                 15
invalid/out-of-window references        0
duplicate changed fields                0
invalid operations                      0
unparseable replacement values          0
authority/scope/cursor changes           0
Canonical or Retrieval mutation         0
still-valid prior established item lost 0
```

以上只证明 base identity、字段、operation、JSON value 和 Event-window reference 的机械有效性，
不把 reference validity 冒充成 semantic grounding。

## 5. 候选语义结果

### PUBLIC_PROXY_DIAGNOSIS

Delta 将“服务 down”假设移入 invalidated，记录 direct no-proxy 200 与三服务 active，清除
endpoint blocker，并把 next action 改为仅在仍需代理时诊断 proxy path。

候选判断：`USEFUL`。它避免重复重启健康服务。

### ZERO_SKILL_EVIDENCE_CORRECTION（v1，未采用）

初次 Delta 撤回了旧 zero-Skill 证明，但同时遗漏仍成立的事实：“三个 fresh `CODEX_HOME`
session 确实恢复了 persisted Working State”。输入 Event 也只提供 rollout marker 为 0，没有提供
显式禁用 Skills 的实际配置，因此不足以支持 `completed`、blocker 清除与发布结论。

独立功能审计判断：`HARMFUL`。该输出被保留为失败证据，不进入最终 value signal。

### ZERO_SKILL_EVIDENCE_CORRECTION_V2（最终采用）

修正不是写入预期答案，而是补齐两个通用合同缺口：

1. full-field `REPLACE` 必须保留所有仍有效旧项，只删除被 Event 反驳或已 stale 的项；
2. Event window 增加实际 Codex 配置观察：Skills instructions/bundled Skills 显式关闭，相关 features
   关闭，user config/rules 忽略，并保留 Z1/Z2 rollout 的零命中计数与真实恢复行为。

修正版保留“三个原始 Session 确实恢复 State”，只撤销它们对 zero-Skill 的错误归因；随后以
Z1/Z2 作为有效 zero-Skill 证据，将 phase 收紧为 `validated`，记录 failed approach，清除 blocker，
并把 next action 改为仅发布纠正后的证据。

最终判断：`USEFUL`。它既避免重复使用无效证据，也避免破坏仍成立的恢复事实。

### NESTED_EVIDENCE_SCOPE_REPAIR

Delta invalidates “top-level check 足够”的假设，记录 nested ref 校验、负测与真实双 project
PostgreSQL E2E，保存新的边界 decision，并在 architecture PASS 后清除 blocker/旧 next action。

候选判断：`USEFUL`。它把安全审查发现转为后续可恢复的任务认知。

最终 value set 为：

```text
PUBLIC_PROXY_DIAGNOSIS             USEFUL
ZERO_SKILL_EVIDENCE_CORRECTION_V2  USEFUL
NESTED_EVIDENCE_SCOPE_REPAIR       USEFUL
```

这些是 Engineering Mode 下的独立 subagent 产品价值判断，不是人工 gold，也不构成模型效果或
泛化 Research claim。

## 6. 失败反思

首次执行失败在 CLI 参数位置：`--ignore-user-config` 属于 `codex exec`，放在全局位置时模型未
启动。第二、三次失败分别暴露 strict structured output 不接受无类型 `value` 与动态
`additionalProperties` field map。修复顺序：

```text
CLI option moved to exec scope
  -> replacement value receives explicit string type
  -> changes map becomes fixed-shape change array
```

这些执行失败都发生在模型采样前，因此没有挑选语义输出。

第一次成功采样后的 v1 case2 随后被功能 reviewer 判为 `HARMFUL`。本轮没有隐藏该负结果，
而是按 failure reflection 修复通用 full-field replacement 合同，并补齐此前缺失的客观配置
Event；再以独立 case2-v2 输入重新采样。修正没有向 Runtime/Host 增加 case ID、期望字段或
答案分支。

## 7. Subagent boundary review

| Reviewer | 初次结论 | 修正后结论 | Required fixes |
| --- | --- | --- | --- |
| Functional | case2-v1 `HARMFUL` | case2-v2 `USEFUL`；报告需如实修订 | 已修复 |
| Architecture | `PASS_SPIKE` | `PASS` | 0 |
| Generalization / simplicity | v1 可继续但需收紧 C1 边界 | `PASS / USEFUL` | 0 |

共同结论：C0 已证明“旧 State + 稀疏观察 Event → 有限 StateDelta”值得进入 C1 最小边界设计；
它没有证明自动 checkpoint、通用语义 grounding、长期 freshness，也没有授权 migration。

## 8. 下一边界

本阶段结束为：

```text
PASS_EVENT_RECONCILIATION_VALUE_SIGNAL
```

它只支持提出 C1 最小 schema boundary：append-only sparse Event journal + server-owned binding +
exact Evidence refs + bounded mechanical payload + 最小 read window。C1 仍需冻结 migration、
rollback 与真实 PostgreSQL test 边界；C0 不授权 migration、checkpoint、自动 State update、
Basis hardening 或 Research effect claim。
