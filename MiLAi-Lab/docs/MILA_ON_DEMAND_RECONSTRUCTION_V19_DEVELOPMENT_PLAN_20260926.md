# MiLAi v19 开发规划：On-Demand Evidence Reconstruction

- 日期：2026-09-26
- 状态：`PLANNED_NOT_STARTED`
- 作用域：`MiLAi-Lab`
- 当前终态：v18 `STOPPED_M1_RECHECK_NOT_JUSTIFIED`
- v18 提交：`90ac0b35e95b0371106cb05fb66b1f933af7f432`
- v18 source mapping：`657b0060d8c31385fc6bbe99fdb1a42b9d4815376103983348b4038d9ef6533e`
- 公共 matched baseline：v16 B1 `COMPLETE_WITH_INSTRUMENTED_BASELINE`
- B1 提交：`3676c511f4c4087453d5bbf54cea3514e57fd948`
- foundation：LangGraph + LangMem `0.0.30`
- 模型：Qwen3.6-35B-A3B-FP8
- vLLM：**保持现有配置与启动参数，不修改 parser、thinking、context、max output 或服务容器**
- 本文性质：后续开发上位规划，不表示 v19 已执行、验证或提交

---

## 0. 执行摘要

v17 和 v18 已经给出足够证据停止“持续维护显式 Decision Basis”这条主线。

v17 证明：

```text
exact adoption
+ revision_changed notification
```

工程上可达，但 Host 在真实受控重核中仍沿用旧值。

v18 进一步收紧为：

```text
proposition
+ action_scope
+ support_role
+ explicit completion
```

结果却是三个小实例都未能稳定建立初始 Basis：两个在无 pending recheck 时虚假声明 completion，一个开放结构生成退化并达到 4096-token 截断；0/3 完整机制实例，0 accepted Basis，0 accepted adoption，0 recheck trigger，0 business execution。v18 因而结项 `STOPPED_M1_RECHECK_NOT_JUSTIFIED`，M2 不准入。

下一阶段不再问“如何让一个持续维护的 Decision State 更严格”，而改问：

> **是否根本不需要长期维护 Decision State，而只在当前任务确实需要形成行动判断时，从当前可用证据即时重建？**

v19 提出 **On-Demand Evidence Reconstruction（ODR）**：

```text
B1 exact observations / revisions / deliveries / receipts
                    ↓
      request-time freshness inspection
                    ↓
  only when a decision is actually needed
                    ↓
       ephemeral reconstruction
                    ↓
 answer / search / read / business action
                    ↓
        reconstruction discarded
```

核心变化：

```text
No maintained semantic decision state.
```

每个判断只在需要时临时形成。下一轮如果仍需判断，再从当前证据重新构建，而不是恢复上轮 proposition。

这直接消除了 M1 的三类负担：stale Decision State、state churn / protocol synchronization、以及“State 本身必须维护正确”这一额外认知任务。

v19 不进入旧 M2 State–Attention；它先验证 **On-demand reconstruction 是否比 maintained Decision State 更稳、更简单、更便宜**。

---

# 1. 为什么现在应该转向 On-Demand Reconstruction

## 1.1 v17/v18 失败不是普通字段缺失

已经尝试过：

```text
decision
scope
adopted exact evidence
critical gap
program-owned recheck
```

以及更严格的：

```text
proposition
action scope
support role
explicit completion
```

问题不是“还差一个字段”，而是维护 State 本身已成为 Agent 的额外任务。模型需要同时完成业务推理、memory CRUD/search、业务工具、State 创建/更新、evidence adoption、revision recheck 与 completion bookkeeping。

## 1.2 持续 State 天然存在 stale-state 问题

即使 exact revision 可追踪：

```text
State adopted X@1
memory becomes X@2
```

仍需：

```text
notify → model recheck → acknowledge → replace/retain state
```

这条维护链本身会失败。

ODR 改为：

```text
需要判断时 → 从当前 evidence 重建
```

没有旧 Decision State 需要同步。

## 1.3 B1 已经提供足够好的事实底座

v16 已经提供：

```text
Observation
MemoryRevision
SearchDelivery
RequestMaterial
ActionReceipt
```

因此不需要为了“记住模型以前怎么想”再维持第二层长期语义状态。

---

# 2. v19 的研究问题

主问题：

> **在公开、可版本化、可追踪的长期记忆 Agent 上，取消持续 Decision State，改为按需从当前证据即时重建行动判断，能否更可靠地应对证据变化，同时减少协议和状态维护开销？**

需要回答：

1. Agent 能否在真正需要时形成临时 action-sensitive judgment？
2. 历史 ToolMessage 中存在 stale memory 时，request-time freshness metadata 是否足以促使 Agent 重新取材？
3. ephemeral reconstruction 是否比 maintained Basis 更少出现 label/state bookkeeping 错误？
4. changed / retained / irrelevant revision 三种情形能否正确处理？
5. 是否保持普通任务 non-intervention？
6. 是否不需要额外独立 model/controller call？

---

# 3. 方法定义：什么叫 On-Demand Reconstruction

ODR 不保存以下语义状态跨 turn 持久存在：

```text
DecisionBasis
proposition state
adoption state
recheck pending
```

允许长期保存的仍只有事实层：

```text
B1 observations
memory revisions
search deliveries
business receipts
```

以及纯机械、每 request 重算的：

```text
freshness annotations
```

## 3.1 Reconstruction 是 ephemeral 的

一次 reconstruction 只属于一个 Provider request / response：

```text
Reconstruction:
  proposition
  action_scope
  evidence_used
  unresolved_gap
```

响应结束后丢弃，不写入跨轮 Decision DB。

## 3.2 下一轮重新构建

```text
current user request
+ current memory/tool evidence
+ freshness metadata
→ new reconstruction
```

不会读取上轮 reconstruction，因此没有 old proposition、recheck reason、clear/ack 等生命周期。

---

# 4. ODR 与 Maintained M1 的差异

| 维度 | Maintained M1 | ODR |
|---|---|---|
| Decision 生命周期 | 跨 turn | 单 request |
| adopted evidence | 持久 | 临时 |
| revision change | recheck old Basis | request-time freshness |
| stale semantic state | 可能 | 默认不存在 |
| completion protocol | 需要 | 不需要 |
| clear / ack | 需要 | 不需要 |
| semantic state DB | 需要 | 不需要 |
| 认知负担 | 持续维护 | 仅需要时重建 |
| future Attention | persistent state | ephemeral gap |

---

# 5. v19 明确不做什么

v19 禁止：

- 恢复 persistent Decision Basis；
- 保存 proposition/adopted evidence/unresolved gap 跨 turn；
- recheck pending state；
- retained / changed / unresolved completion bookkeeping；
- State–Attention；
- automatic gap search；
- automatic search；
- retrieval ranking 改动；
- candidate expansion；
- second reviewer / reflection Agent；
- Jev；
- training；
- Product 修改；
- MERIT seeds 3/4；
- fresh formal MemSyco；
- 把 v18 state schema 搬进 ODR；
- benchmark-specific 温度/金额/订单规则。

---

# 6. Request-Time Freshness Inspection

这是 ODR 的第一个核心机制。

LangGraph thread 可能仍包含：

```text
memory X@1 = 4°C
```

而当前 Store 已为：

```text
memory X@2 = 8°C
```

程序利用 B1 exact revision sidecar，在发送 Provider request 前对**本 request 实际包含的 memory material**做机械检查：

```text
CURRENT
SUPERSEDED
DELETED
UNKNOWN
```

## 6.1 Freshness metadata 只能陈述事实

允许：

```text
memory:X@1 is superseded; current revision is X@2.
The body of X@2 is not included in this request.
```

禁止：

```text
Therefore 4°C is wrong.
You must use 8°C.
Search now.
Do not execute the action.
```

## 6.2 Sparse freshness block

只有 stale/deleted material 实际进入当前 request 时才注入：

```text
Evidence freshness:
- m1 = memory:X@1 is superseded by memory:X@2.
- X@2 content has not been delivered in this request.
```

没有 stale evidence 时不生成动态 freshness block。

---

# 7. 为什么 Freshness 不等于 maintained State

Freshness 只陈述：

```text
old revision != current revision
```

它不记录 agent 的旧 decision，也不要求 retain/change/clear/ack。下一 request 会重新计算，因此本身不会 stale。

---

# 8. Ephemeral Reconstruction

当 Agent 当前确实在形成 action-sensitive judgment 时，可以在同一次 JSON-action response 中输出：

```text
reconstruction
```

最小结构：

```text
reconstruction:
  proposition
  action_scope
  evidence_used[]
  unresolved_gap
```

没有：

```text
decision_id
state revision
status
recheck reason
recheck outcome
clear
```

---

# 9. Reconstruction 不是每轮必填

简单任务允许：

```json
{
  "reconstruction": null,
  "answer": "..."
}
```

只有当前判断会影响 meaningful action / critical parameter 时才建议 reconstruction。

目标是：

```text
on-demand, not always-on
```

---

# 10. Reconstruction 字段语义

## 10.1 proposition

具体、当前、action-sensitive，例如：

```text
If approved now, crate Lumen-42 should be held at 8°C.
```

## 10.2 action_scope

```text
subject
item
action_type
critical_parameters[]
```

## 10.3 evidence_used

只允许当前 Provider request 实际 delivered evidence：

```text
observation
memory revision
business receipt
```

可保留轻量 `support_role`：

```text
supports_value
constrains_applicability
records_execution
contextual
```

但仅活一轮。

## 10.4 unresolved_gap

```text
string | null
```

必须是可能改变 meaningful action 的信息缺口。v19 不根据 gap 自动 retrieval。

---

# 11. Currentness 规则

Reconstruction 采用 memory evidence 时必须指向实际 delivered revision。

如果某 revision 在 request-time 已知为 `SUPERSEDED`：

- 可以作为 `contextual` 历史背景；
- **不能作为 `supports_value`**。

这是机械 currentness contract，不判断旧正文语义真假。

---

# 12. Current Evidence 获取仍由普通 ReAct 决定

程序不会自动：

```text
search X@2
```

如果 freshness block 告知：

```text
X@1 superseded by X@2; X@2 body unavailable
```

Host 可以自行调用普通 `search_memory`，随后下一次正常 generation 从真实返回的 X@2 重建。

这会增加普通 ReAct generation，必须计入方法成本，但不新增独立 State/reflection controller。

---

# 13. changed / retained / irrelevant 不再维护 completion state

## changed

```text
stale X@1 appears
→ freshness warning
→ Host searches current X@2
→ ephemeral reconstruction uses X@2
→ action uses current value
```

无需输出 `recheck_outcome=changed`。

## retained

```text
X@1 old note
X@2 same action-critical value
→ obtain X@2
→ reconstruction still says 8°C
```

“retained”由离线分析比较两次 reconstruction 得出。

## irrelevant

Y revision changed但不参与当前判断时，不存在旧 adoption dependency。若 Y 不进入 current request，则无 freshness block；若历史 Y 恰好进入 request，可以标 stale，但不应改变目标 action reconstruction。

---

# 14. v19 的关键简化：不追踪旧 adoption

Maintained M1 问：

```text
What did I adopt before?
Did it change?
```

ODR 问：

```text
What evidence is current and available now?
What judgment should I reconstruct now?
```

从：

```text
maintain → detect → repair
```

转为：

```text
reconstruct from current evidence
```

---

# 15. JSON-action 结构

建议：

```json
{
  "reconstruction": null,
  "calls": [...]
}
```

或：

```json
{
  "reconstruction": {
    "proposition": "...",
    "action_scope": {
      "subject": "...",
      "item": "...",
      "action_type": "...",
      "critical_parameters": ["..."]
    },
    "evidence_used": [
      {
        "ref": "e1",
        "support_role": "supports_value"
      }
    ],
    "unresolved_gap": null
  },
  "calls": [...]
}
```

最终回答同样可以携带 reconstruction。

没有 `set / clear / ack / outcome`。

---

# 16. 工具执行边界

程序只验证：

- reconstruction schema 合法；
- evidence ref 确实 delivered；
- superseded memory 不能作为 `supports_value`；
- exact revision identity 正确。

v19 **不要求所有 business action 必须有 reconstruction**。

若模型直接执行 action 且 reconstruction 为 null：

```text
允许实际执行
```

同时记录：

```text
ACTION_WITHOUT_RECONSTRUCTION
```

作为离线指标。

这样避免把 deterministic action gate 的收益误算成 ODR 收益。

若 reconstruction 非 null 但协议自相矛盾，则该响应工具零执行，保持现有“非法结构不产生副作用”原则。

---

# 17. Reconstruction Trace，但不作为运行输入

reconstruction 要进入 append-only trace：

```text
request_id
proposition
action_scope
evidence refs
support roles
gap
tool calls
answer
```

但下一 request 的运行逻辑**不得读取历史 reconstruction**。

如果为了分析使用 SQLite 表，该表只能是日志表，不是 semantic state store。

---

# 18. 代码组织建议

从 `methods/milai_m1` 分离新方向：

```text
MiLAi-Lab/
  src/milai_lab/
    methods/
      on_demand_reconstruction/
        __init__.py
        schema.py
        freshness.py
        evidence_view.py
        controller.py
        metrics.py

    runners/
      langmem_odr_mechanism.py

  configs/
    milai-odr-v19.json

  data/fixtures/
    milai_odr_v19_changed.json
    milai_odr_v19_retained.json
    milai_odr_v19_irrelevant.json

  data/locks/
    milai-odr-v19.lock.json

  tests/unit/
    test_milai_odr.py

  tools/
    run_milai_odr.py
    inspect_milai_odr.py

  docs/
    MILA_ON_DEMAND_RECONSTRUCTION_GOAL_v19.md
```

不再继续扩展 `methods/milai_m1/`。v17/v18 保持历史实现。

---

# 19. Work Package A：冻结 v18

锁定：

- commit `90ac0b3`；
- v18 source mapping；
- v18 lock/final freeze；
- R1 schema-combination failure；
- R2 三个实例失败；
- 16 generations / 19237 tokens；
- 267 embedding tokens；
- truncation = 1；
- V4/V5 `NOT_RUN_GATE_NOT_MET`；
- M2 not admitted。

Gate：

```text
No v18 result rewrite.
No publication rerun.
No M1 semantic rescue.
```

---

# 20. Work Package B：Freshness Inspector

输入：

```text
actual Provider request materials
+ B1 exact revision store
```

输出：

```text
memory:X@1
status=SUPERSEDED
current_ref=X@2
current_body_delivered=false
```

V0 覆盖：

- current；
- superseded；
- deleted；
- unknown；
- same-content new revision；
- irrelevant memory absent from request；
- duplicate historical ToolMessage；
- request contains multiple revisions。

---

# 21. Work Package C：Sparse Freshness Projection

只有 `SUPERSEDED / DELETED` 才生成动态 freshness 文本。

目标：

```text
freshness overhead ≈ 0 on unaffected requests
```

无 stale material 的请求不增加动态 freshness block。

---

# 22. Work Package D：Ephemeral Reconstruction Schema

实现：

```text
null
or
{
  proposition,
  action_scope,
  evidence_used,
  unresolved_gap
}
```

Gate：

- delivered evidence only；
- exact revision；
- superseded ref不能 `supports_value`；
- observation/receipt evidence 合法；
- duplicate refs normalize；
- reconstruction 不持久化。

---

# 23. Work Package E：Adapter Integration

扩展 JSON-action：

```text
reconstruction + calls
reconstruction + answer
```

要求：

```text
same generation
no independent reconstruction call
```

若 reconstruction 非法，该响应工具零执行；`reconstruction=null` 始终合法。

---

# 24. Work Package F：No-Persistence Invariant

必须测试证明：

```text
request N reconstruction
```

不会作为：

```text
request N+1 model-visible semantic state
```

下一轮可见的只有 normal conversation、normal tool history、B1 current facts 和 request-time freshness。

---

# 25. Work Package G：恢复与重放

必须验证：

- process restart 不需要 semantic state restore；
- business completed call 不重复；
- B1 revision history准确；
- freshness每次重算；
- reconstruction日志不影响运行；
- completed turn replay不重复业务效果。

---

# 26. V0：确定性测试

不调用真实模型。

### Freshness

- current；
- superseded；
- tombstone；
- irrelevant；
- multiple revisions；
- stale content same text；
- historical ToolMessage stale。

### Reconstruction

- null；
- proposition/action scope；
- observation evidence；
- memory evidence；
- receipt evidence；
- superseded `supports_value` rejected；
- current evidence accepted；
- no cross-turn persistence。

### Transport

- reconstruction + answer；
- reconstruction + search call；
- reconstruction + business call；
- null + business call；
- invalid reconstruction zero side effect；
- no independent model call。

---

# 27. V1：Decoder Probe

最少验证当前 vLLM 能生成：

```text
null reconstruction + answer
null reconstruction + calls
reconstruction + answer
reconstruction + search call
reconstruction + business call
```

不测试复杂的 maintained-state completion shape。

如果开放字符串再次出现空白退化：

> 优先缩短文本上限和 schema，而不是修改 vLLM 设置。

---

# 28. V2：Changed Revision Diagnostic

沿用 development family：

```text
4°C → 8°C
```

但建立新的 v19 fixture/freeze。

目标链：

```text
message 1
→ ordinary search obtains X@1
→ optional ephemeral reconstruction uses X@1
→ fixture updates Store to X@2

message 2
→ old X@1 may remain in thread
→ request-time freshness marks X@1 superseded
→ Host searches/reads X@2 through ordinary tools
→ new reconstruction uses X@2

message 3 approval
→ business action uses 8°C
```

成功必须全部满足：

1. X@1 实际进入过 Provider request；
2. X@2 external update 真实完成；
3. 后续 request 真实看到 freshness warning；
4. Host 普通工具取得 X@2；
5. final reconstruction 使用 X@2；
6. X@1 不作为 `supports_value`；
7. approved action = 8°C；
8. 无额外独立 model/reviewer call；
9. 无程序自动 search；
10. 无 hard-coded 4/8 规则。

---

# 29. V3：Retained Revision Control

```text
X@1 = 8°C + note A
X@2 = 8°C + note B
```

目标：

```text
freshness warns old revision
→ Host obtains current X@2
→ reconstructed judgment remains 8°C
→ approved action 8°C
```

不要求 Host 输出 retained 标签，离线比较 reconstruction 即可。

---

# 30. V4：Irrelevant Revision Control

```text
primary X unchanged
auxiliary Y@1 → Y@2
```

如果 current request 不包含旧 Y：

```text
no freshness block
```

如果历史 Y 恰好进入 request，可标 stale，但不应改变 temperature reconstruction，也不应无必要搜索 Y。

---

# 31. V5：Freshness-Only Ablation

如果 V2–V4 通过，必须加入：

### F-only

```text
B1 + request-time freshness
without reconstruction field
```

### ODR

```text
B1 + freshness + ephemeral reconstruction
```

目的：

> 判断收益来自“stale evidence 提醒”，还是 reconstruction 表示本身。

如果 F-only 已完全解决 changed/retained：

> 删除 reconstruction，保留更简单机制。

---

# 32. V6：原 12-case exposed diagnostic

只有三个机制例通过后运行。

关注：

- memory search rate；
- stale warning；
- reconstruction activation；
- label-like reconstruction；
- action-critical evidence use；
- non-intervention；
- protocol rejection；
- truncation；
- task completion。

历史 B1 7/12、M1 5/12 只能作开发背景，不是 matched causal comparison。

---

# 33. V7：exposed MERIT arc0

只有 V6 无明显退化才运行。

ODR **不负责自动修复 memory formation**。因此首次 1774 漏存仍可能发生，这是方法边界，不应伪装为实现 bug。

重点观察：

### empty search → fabricated 5000

- 当前是否有实际 evidence？
- reconstruction 是否存在？
- evidence 不足时是否形成 unresolved gap？
- 是否仍凭空生成 5000？

### 6595

```text
current memory returned
→ reconstruction uses correct revision
→ refund 6595
```

业务后 stale memory 仍可能存在，ODR 不自动 reconcile Store。

---

# 34. v19 不消费未见数据

默认：

```text
MERIT seeds 3/4 = NOT_RUN
fresh MemSyco = NOT_RUN
StateMemBench = NOT_RUN
```

只有 ODR 核心机制出现可信信号后，再决定是否进入 `ODR + Attention` 或直接做 matched evaluation。

---

# 35. v19 核心指标

## Reconstruction Activation Rate

```text
requests with reconstruction / all model requests
```

接近 1 则 on-demand claim 失败。

## Freshness Intervention Rate

```text
requests with dynamic freshness block / all requests
```

应只在 stale/deleted material 实际进入 request 时非零。

## Current Evidence Use

action-sensitive reconstruction 中实际使用 current exact memory revision 的比例。

## Stale Supports-Value Violations

```text
superseded memory used as supports_value
```

机械目标为 0。

## Reconstruction Grounding Coverage

有 `critical_parameters` 的 reconstruction 中，是否至少有一个 `supports_value` evidence。

## Unresolved Discipline

证据不足时是否形成 `unresolved_gap`，而不是凭空生成关键参数。

## Non-Intervention

不需要 action-sensitive judgment 时：

```text
reconstruction = null
```

## Freshness Utility

changed/retained 中：

```text
freshness → current evidence acquisition → current action
```

---

# 36. 成本指标

必须单列：

```text
fixed ODR protocol input tokens
dynamic freshness input tokens
reconstruction output tokens
ordinary ReAct generations caused by search
extra independent generations = 0
protocol rejection
truncation
local trace/storage bytes
```

普通 search tool cycle 会增加正常 ReAct generation，这是实际方法成本，不能因为不是专用 State call 就忽略。

---

# 37. 与 Maintained M1 的描述性成本比较

关注：

```text
tokens per public message
generations per public message
protocol rejection rate
truncation
persistent semantic state bytes
```

M1：

```text
persistent Decision Context
+ state delta
+ recheck lifecycle
```

ODR：

```text
no persistent semantic state
+ dynamic freshness only when needed
+ ephemeral reconstruction
```

---

# 38. v19 GO / PIVOT / KILL

| 结果 | 决策 |
|---|---|
| changed/retained/irrelevant 全工作，F-only 不足而 ODR 有增量 | **GO：ODR 成为候选主机制** |
| Freshness-only 已足够 | **PIVOT：保留 freshness，删除 reconstruction** |
| ODR 只有 hard action gate 才有效 | **PIVOT → evidence-gated action** |
| ODR 只有 automatic search 才有效 | **PIVOT → retrieval control / Attention-first** |
| changed 仍使用 stale evidence | **KILL ODR reconstruction** |
| reconstruction 每轮都生成 | **KILL on-demand claim** |
| 仍大量 protocol error / truncation | **KILL structured reconstruction** |
| ODR 改善 revision adaptation 但不能修漏存 | **允许：这是 method boundary** |

---

# 39. 关键科学消融：Freshness-only vs Reconstruction

v19 不预设 reconstruction 必要。

可能最终发现：

```text
exact version instrumentation
+ request-time stale warning
```

已经足够。

如果如此，应选择更简单机制：

> **persistent semantic state is unnecessary; lightweight request-time freshness signaling is sufficient for selective adaptation.**

这比为了方法复杂度而保留 reconstruction 更合理。

---

# 40. 后续研究路径

## Path A：ODR 已足够

直接做 matched evaluation：

```text
A0 = B1
A1 = B1 + Freshness
A2 = B1 + Freshness + ODR
```

## Path B：ODR 仍有 retrieval miss

再增加：

```text
A3 = A2 + Gap-Directed Attention
```

Attention 输入来自当前 ephemeral `unresolved_gap`，而不是 persistent State。

归因：

```text
A1 - A0 = freshness feedback value
A2 - A1 = reconstruction value
A3 - A2 = attention/control value
```

---

# 41. 实现边界

允许修改：

```text
MiLAi-Lab/src/milai_lab/methods/on_demand_reconstruction/
MiLAi-Lab/src/milai_lab/providers/langmem_chat.py       # minimal adapter support
MiLAi-Lab/src/milai_lab/baselines/langmem_*            # exact currentness hook only if needed
MiLAi-Lab/src/milai_lab/runners/langmem_*
MiLAi-Lab/configs/
MiLAi-Lab/data/fixtures/
MiLAi-Lab/data/locks/
MiLAi-Lab/data/manifests/
MiLAi-Lab/tests/unit/
MiLAi-Lab/tools/
MiLAi-Lab/docs/
```

默认禁止继续修改：

```text
methods/milai_m1/
state_attention.py
old contextual runtime
MiLAi-Product/
MiLAi-Artifact-Archive/
```

---

# 42. 里程碑

| Milestone | 内容 | Real Model |
|---|---|---:|
| M0 | freeze v18 | 0 |
| M1 | freshness inspector | 0 |
| M2 | ephemeral schema | 0 |
| M3 | adapter integration | 0 |
| M4 | V0 tests | 0 |
| M5 | decoder probe | minimal |
| M6 | changed diagnostic | small |
| M7 | retained + irrelevant controls | small |
| M8 | freshness-only ablation | conditional |
| M9 | 12-case exposed diagnostic | conditional |
| M10 | exposed MERIT arc0 | conditional |
| M11 | GO / PIVOT / KILL | 0 |

---

# 43. 建议终态

核心机制成立：

```text
COMPLETE_WITH_ODR_MECHANISM_REACHABLE
```

只有 freshness 有价值：

```text
COMPLETE_WITH_FRESHNESS_ONLY_PIVOT
```

结构 reconstruction 不稳定：

```text
STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED
```

需要自动 retrieval：

```text
PIVOT_TO_RETRIEVAL_CONTROL
```

不要使用：

```text
ODR_EFFECTIVE
MILAI_WINS
GENERAL_IMPROVEMENT
```

除非后续未见 matched evaluation 真正支持。

---

# 44. v19 严格停止条件

以下任一发生即停止继续结构化 ODR：

1. 三个受控例仍无法稳定完成初始 evidence acquisition；
2. reconstruction 字段再次产生明显 schema/protocol burden；
3. changed 场景仍把 superseded evidence 当 current action support；
4. 需要第二独立 model call 才能完成 reconstruction；
5. 必须 hard-code search 才能工作；
6. reconstruction activation 接近每轮；
7. Freshness-only 与 ODR 等价或更好。

第 7 条尤其重要：

> **如果更简单的方法一样有效，应删除更复杂的方法。**

---

# 45. 冻结原则

```text
Current evidence > remembered decision state
```

```text
Freshness is a fact, not a semantic verdict
```

```text
Reconstruction is ephemeral
```

```text
No semantic state survives by default
```

```text
No search is forced in v19
```

```text
Simpler mechanism wins when evidence is equal
```

---

# 46. v19 最终目标

v19 要验证一个与 v17/v18 根本不同的假设：

> **Continual-memory Agent 不一定需要持续维护“我当前相信什么”。当实际行动需要判断时，从当前可用、带版本信息的证据重新构建，可能更可靠。**

完整目标链：

```text
persistent factual memory
        ↓
exact revisions
        ↓
current request contains evidence
        ↓
request-time freshness check
        ↓
stale evidence is identified
        ↓
ordinary ReAct may retrieve current evidence
        ↓
ephemeral reconstruction
        ↓
current answer / action
        ↓
reconstruction discarded
```

如果成立，MiLAi 的核心算法将从：

```text
maintain semantic State
→ repair semantic State
→ use semantic State
```

转向：

```text
maintain factual/versioned memory
→ reconstruct only when needed
→ optionally attend only when needed
```

这条路线更简单，也更符合 v15–v18 的真实实验结果。

如果 ODR 仍无法在 changed / retained / irrelevant 三个最小场景中稳定成立，则进一步简化到：

```text
Freshness-only
```

或转向：

```text
evidence-gated action
retrieval control
```

而不是重新引入持续 Decision State。
