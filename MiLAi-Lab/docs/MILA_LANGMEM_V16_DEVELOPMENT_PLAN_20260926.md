# MiLAi v16 开发规划：Provenance-Preserving Versioned LangMem Baseline

- 日期：2026-09-26
- 状态：`PLANNED_NOT_STARTED`
- 作用域：`MiLAi-Lab`
- 上一阶段基线：v15 `COMPLETE_WITH_BASELINE_FAILURES`
- v15 提交：`46b8a925385e7b38a7111c7c32283af0eb28467e`
- v15 foundation decision：`GO`
- 研究阶段：从 **baseline migration** 进入 **method construction**
- 本文性质：下一轮开发上位规划，不表示 v16 已经执行、验证或提交

---

## 0. 执行摘要

v15 已经完成最关键的工程迁移：在保持原 vLLM 设置不变的前提下，通过独立 JSON-action 适配器，将固定 upstream LangGraph / LangMem 接入 MiLAi-Lab，并完成持久 Store、独立 checkpoint、业务工具执行与恢复、MERIT 原生评测和连续成本记录。

v15 的公开 baseline B0 已经成立：

- 12 个冻结语义诊断：`7/12`
- MERIT arc0：`4/5`
- dependent episodes：`1/2`
- 技术接入：GO
- 语义可靠性：未达标
- B1 / M1 / M2：尚未开始

v15 暴露的关键 baseline failure 包括：

1. 首次未来约定漏存；
2. 后续检索为空后编造错误的 5000 cents 约定，并真实执行错误退款；
3. 正确执行 6595 cents 退款后，长期记忆仍保留 “Do NOT process yet” 的过时状态；
4. 部分已保存跨轮信息后续没有被搜索或使用。

这些失败**不能在 v16 中通过语义规则直接修复**。否则 B1 将不再是公平 baseline，而会提前吸收 MiLAi 的方法贡献。

v16 的唯一核心目标是：

> **在不改变 B0 语义决策和工具行为的前提下，为 LangMem baseline 增加可追溯的 Observation、Memory Revision、Search Delivery 与 Action Receipt instrumentation，使未来 M1 能准确表达“当前判断实际采用了哪个记忆版本／来源”。**

因此：

\[
\boxed{B1 = B0 + \text{model-neutral provenance/version instrumentation}}
\]

而不是：

\[
\boxed{B1 = B0 + \text{更聪明的记忆策略}}
\]

Decision Basis、Selective Recheck、State–Attention 全部留到后续阶段。

---

## 1. 当前事实基线

### 1.1 v15 已经解决的问题

| 能力 | 当前状态 |
|---|---|
| LangGraph ReAct | 已接入 |
| LangMem `manage_memory` | 已真实调用 |
| LangMem `search_memory` | 已真实调用 |
| 原 vLLM 设置 | 保持 |
| JSON-action transport adapter | 已实现 |
| Postgres long-term Store | 已实现 |
| SQLite thread checkpoint | 已实现 |
| business tool journal / recovery | 已实现 |
| MERIT 原生工具 | 未改 |
| MERIT world / checker | 未改 |
| 12-case diagnostic | 已完成 |
| 完整 exposed MERIT arc0 | 已完成 |
| 连续成本账本 | 已完成 |
| 新未见 seed | 未消费 |
| Product | 未修改 |

因此，v16 **不再处理 foundation 可用性问题**。

### 1.2 v15 仍然存在的问题

#### A. Memory miss

真实未来约定可能不进入 Store。

```text
用户约定 1774
→ B0 未保存
→ 后续 search 空
→ Agent 缺少真实依据
```

#### B. Unsupported memory creation

```text
search 为空
→ 编造 5000
→ create memory "5000"
```

#### C. Action grounding error

```text
错误 memory 5000
→ refund 5000
→ world state 被错误修改
```

#### D. Stale persistent memory

```text
memory: do not process yet
→ refund 6595 succeeded
→ memory still: do not process yet
```

#### E. Memory non-use

即使 memory 已成功持久化，Agent 也可能不主动搜索。

这些都是真实 baseline behavior。

**v16 不修复上述行为，只要求以后可以准确观测它们。**

---

## 2. v16 的研究定位

v16 不是新的 MiLAi 方法实验，而是：

> **Matched baseline instrumentation phase**

其目的只有一个：

> 为未来的 Decision Basis / Selective Recheck 提供精确、可版本化、可追踪的证据对象。

v16 结束时必须能回答：

- 某条长期 memory 是何时创建的？
- 它来自哪些实际 Observation？
- 当前是 revision 几？
- 一次 search 实际返回了哪个 revision？
- 哪些 memory 被实际送入 Host？
- 哪个业务 action receipt 改变了外部世界？
- 后续 memory update 是否发生？
- 所有 instrumentation 是否在不改变 B0 行为的情况下完成？

---

## 3. v16 明确不解决什么

v16 **禁止**加入以下语义策略：

- future commitment 必须保存；
- unresolved obligation 自动进入 cross-turn；
- business success 自动触发 memory reconciliation；
- search 为空时禁止行动；
- 没有证据时强制 abstain；
- stale memory 自动标记 `needs_reconcile`；
- Decision Basis；
- adopted evidence；
- critical gap；
- State–Attention；
- 自动 recheck；
- Jev；
- 第二审核模型；
- 新 Agent；
- graph memory；
- support group；
- semantic frontier v14 迁移；
- maintenance-v5 迁移。

这些都可能改变 Agent 行为，从而破坏 B0 → B1 的可比性。

---

## 4. v16 的核心假设

v16 不测试“MiLAi 是否有效”，而测试一个基础可行性假设：

> **可以在公开 LangMem B0 上增加足够完整的 provenance / revision / delivery / action instrumentation，同时不改变模型可见信息、CRUD 语义、搜索排序或工具执行。**

对于相同 messages、LLM outputs、tool calls、tool arguments、memory contents、search query/filter/limit/offset 与业务工具结果，要求：

\[
\text{ObservableBehavior}_{B1}
=
\text{ObservableBehavior}_{B0}
\]

允许不同的只有：

\[
\text{HiddenInstrumentation}_{B1}
\]

---

## 5. B0 与 B1 的严格边界

### 5.1 B0

```text
LangGraph
+ LangMem manage_memory
+ LangMem search_memory
+ Postgres Store
+ SQLite checkpoint
+ JSON-action adapter
+ business tools
+ business recovery journal
```

### 5.2 B1

```text
B0
+ ObservationRef
+ MemoryRevision
+ SearchDelivery
+ ActionReceipt trace
```

B1 不增加任何新的语义决策。

---

## 6. v16 最小数据模型

### 6.1 ObservationRef

程序记录真实输入来源，不要求 LLM 填写。

```text
ObservationRef
  observation_id
  run_id
  thread_id
  session_id
  role
  actor_ref
  artifact
  content_sha256
  created_at
```

首版不建立复杂事件图。

### 6.2 MemoryRevision

```text
MemoryRevision
  memory_id
  revision
  content
  content_sha256
  source_refs
  created_at
  supersedes_revision
  operation
```

其中：

```text
operation ∈ {create, update, delete}
```

注意：

- revision 是 instrumentation；
- 不能改变 LangMem 原 memory ID 的使用方式；
- update 后 LangMem Store 的最终行为仍与 B0 相同；
- revision history 可以放 sidecar Store / Lab artifact，不要求塞进 LangMem memory value。

### 6.3 SearchDelivery

```text
SearchDelivery
  request_id
  thread_id
  query
  filter
  limit
  offset
  returned:
    - memory_id
      revision
      score
      content_sha256
```

关键语义：

> “被 search 返回” ≠ “被 Agent 采用”。

B1 只能记录 delivery，不能记录 adopted decision。

### 6.4 ActionReceipt

沿用 v15 business journal 事实：

```text
ActionReceipt
  call_id
  generation_id
  thread_id
  tool_name
  arguments
  status
  output_ref / output_hash
```

程序不从自然语言 answer 推断 action success。

---

## 7. provenance 的保守原则

### 7.1 Known mechanical provenance

可以确定：

```text
Observation O was visible before memory operation M.
Memory M was created/updated in generation G.
Search Q delivered revision R.
Action A returned receipt X.
```

### 7.2 Unknown semantic adoption

不能自动推断：

```text
Memory M was created because of Observation O.
Decision D adopted revision R.
Observation O semantically supports memory text T.
```

如果 upstream tool call 没有显式 source 参数：

```text
source_refs = unknown
```

而不是程序猜测。

后续 M1 才让 Host 明确声明 adopted evidence。

---

## 8. 版本策略

首版 revision 使用简单单调整数：

```text
memory_uuid @ revision
```

例如：

```text
X@1
X@2
X@3
```

创建：

```text
CREATE id=X
→ X@1
```

更新：

```text
UPDATE id=X
→ X@2
```

删除：

```text
DELETE id=X
→ tombstone X@3
```

B1 不要求 LangMem Store 本身保留旧正文。

旧 revision 可以写入 Lab sidecar。

最终 current view 仍由 upstream LangMem 决定。

---

## 9. 实现位置建议

```text
MiLAi-Lab/
  src/milai_lab/
    baselines/
      langmem_agent.py              # v15 existing
      langmem_identity.py           # v15 existing
      langmem_instrumentation.py    # NEW
      langmem_revision_store.py     # NEW

    providers/
      langmem_chat.py               # existing; only mechanical fixes

    runners/
      langmem_foundation.py         # existing
      langmem_instrumented.py       # NEW
      langmem_merit.py              # arm selection only

  configs/
    langmem-baseline-v1.json
    langmem-instrumented-v1.json

  data/locks/
    langmem-foundation.lock.json
    langmem-b1.lock.json

  tests/unit/
    test_langmem_foundation.py
    test_langmem_instrumentation.py

  docs/
    MILA_LANGMEM_PROVENANCE_GOAL_v16.md
```

默认不修改：

```text
contextual_user_memory.py
contextual_host.py
contextual_maintenance.py
decision_basis.py
state_attention.py
```

它们保持历史/reference。

---

## 10. Work Package A：冻结 v15

### 目标

建立不可歧义的 B0 reference。

### 工作

1. 锁定 commit：
   `46b8a925385e7b38a7111c7c32283af0eb28467e`
2. 锁定 upstream LangMem commit、resolved dependencies、JSON-action recipe、model/embedding identity、diagnostic SHA、MERIT arc/world SHA、v15 result manifest。
3. 确认 v16 不覆盖 v15 artifacts。

### Gate A

```text
PASS if:
- v15 result/lock hashes match
- no v15 file/result rewritten
- B0 reproduction entry remains valid
```

---

## 11. Work Package B：Observation instrumentation

### 目标

把实际 Host-visible input 转成稳定 ObservationRef。

### 原则

必须从真实 runtime 输入生成，不从 benchmark gold 生成。

### 要求

- user message → ObservationRef；
- business result → ObservationRef；
- memory search result不是新 Observation；
- system prompt不是 user Observation；
- tool schema不是 evidence；
- score/rubric 不进入 provenance。

### Gate B

```text
same input -> same deterministic content identity
different events -> distinct event identity
same text from different events -> distinct event identity
no gold/rubric leakage
```

---

## 12. Work Package C：Memory Revision sidecar

### 目标

让 upstream memory 的 CREATE/UPDATE/DELETE 可追踪。

### 流程

```text
tool call
→ validate arguments
→ execute upstream manage_memory
→ inspect actual result
→ record sidecar revision
```

只有实际成功后记录 revision。

失败调用：

```text
NO REVISION
```

### Gate C

覆盖：

1. CREATE → `@1`
2. UPDATE → `@2`
3. DELETE → tombstone revision
4. tool error → no revision
5. replayed completed result → no duplicate revision
6. cold restart → history still readable

---

## 13. Work Package D：SearchDelivery instrumentation

### 目标

知道 search 实际送出了什么。

记录：

- query；
- filter；
- limit；
- offset；
- returned memory IDs；
- score；
- 当前 revision；
- delivery order。

### 禁止

不修改：

- query；
- ranking；
- threshold；
- top-k；
- filter；
- returned content。

### Gate D

B0 与 B1 对同一 Store snapshot：

```text
returned IDs identical
order identical
scores identical
content identical
```

---

## 14. Work Package E：Action receipt linking

建立：

```text
generation
  ├── memory tool calls
  ├── search deliveries
  └── business receipts
```

不能建立：

```text
receipt caused decision
```

### Gate E

- business success receipt 可恢复；
- unknown 不自动 retry；
- replay 不重复 side effect；
- instrumentation 不改变 v15 journal semantics。

---

## 15. Work Package F：B0/B1 parity gate

这是 v16 最重要的 gate。

### 15.1 Deterministic parity

用 mock / frozen LLM outputs，同输入 B0 与 B1。

比较：

```text
tool calls
tool arguments
LangMem Store final state
search result
business world
assistant final text
```

要求完全相同。

只允许 B1 多：

```text
instrumentation artifacts
```

### 15.2 Real-model parity

不把最终模型文本完全相同作为唯一要求。

重点确认：

- tool set 相同；
- system prompt/model-visible content 相同；
- upstream tool descriptions 相同；
- JSON-action schema 相同；
- search/manage semantics 相同；
- instrumentation model-hidden。

如果 instrumentation 必须注入模型上下文才能工作，则它不再属于 B1，应停止并重新设计。

---

## 16. v16 验证范围

### V0：窄测试

只覆盖：

- observation identity；
- revision lifecycle；
- search parity；
- business receipt；
- restart；
- no gold leak；
- packaging / boundary。

建议约 10–20 个 focused tests，数量不是目标。

### V1：v15 exposed 12-case diagnostic

用途：

```text
wiring / regression / trace inspection
```

不是新独立 evidence。

不要求：

```text
7/12 -> higher
```

如果 B1 明显优于/差于 B0，首先排查 parity bug。

### V2：exposed MERIT arc0

只做 regression。

目标是 trace 完整，而不是：

```text
4/5 -> 5/5
```

### V3：未见 seeds

默认：

```text
MERIT seeds 3/4 = NOT_RUN
```

v16 不消耗 holdout。

---

## 17. v16 指标

### Engineering

```text
instrumentation completeness
revision consistency
search parity
restart consistency
business journal consistency
```

### Baseline behavior

继续记录：

```text
native success
dependent success
diagnostic semantic score
memory writes
searches
business actions
```

但不宣称 improvement。

### Cost

记录：

```text
generation calls
input/output tokens
embedding
instrumentation storage bytes
instrumentation CPU/wall time
```

特别单独报告：

\[
C_{instrumentation}
\]

理想情况下 B1 不增加 generation tokens。

---

## 18. v16 成功定义

v16 成功不是：

```text
diagnostic > 7/12
MERIT > 4/5
```

而是：

\[
oxed{	ext{B1 parity + complete traceability}}
\]

### 必须满足

- B1 可以跑完整公开 baseline；
- provenance/revision/search/action trace 可复核；
- Store/search/business behavior 与 B0 parity；
- 没有 gold/rubric leak；
- 没有改变模型可见语义合同；
- 成本完整记录；
- v15 失败可以被 B1 trace 准确解释。

### 不要求

- 首次约定漏存修复；
- stale memory 修复；
- wrong refund 修复；
- semantic score 提升。

---

## 19. v16 Go / Pivot / Stop

| 结果 | 决策 |
|---|---|
| 完整 instrumentation + parity | **GO → M1** |
| revision 可做，但 source provenance 无法可靠绑定 | **GO with UNKNOWN provenance**；后续只允许 adopted delivered revision |
| instrumentation 需要进入 prompt | **PIVOT**：重做 model-hidden sidecar |
| wrapper 改变 search/ranking/tool semantics | **STOP** |
| 必须 fork/重写 LangMem 大部分实现 | **STOP** |
| 必须恢复 contextual runtime 才能完成 | **STOP** |
| sidecar 成本明显过高 | **PIVOT**：压缩 artifact，不改变 B0 |

---

## 20. 后续 M1：Sparse Decision Basis

v16 不实现，但 B1 应支持未来：

```text
DecisionBasis:
  decision
  scope
  adopted_evidence[]
  critical_gap
  status
```

adopted evidence 指向：

```text
memory_id@revision
or observation_id
```

而不是模糊 memory ID。

---

## 21. 后续 M1 的核心机制

未来 M1：

```text
B1
+ sparse Decision Basis
+ exact adopted evidence
+ program-owned recheck reasons
```

只有存在 action-sensitive uncertainty 才激活。

例如：

```text
h1 -> refund 1774
h2 -> refund 5000

a(h1) != a(h2)
```

当前没有实际证据区分：

```text
critical_gap =
"What is the current agreed refund amount?"
```

这才形成额外信息需求。

---

## 22. 后续 M2：State–Attention

```text
M1
+ gap-directed retrieval
+ selective expansion
+ bounded stop/defer
```

检索优先级：

```text
explicit query
>
critical gap
>
default task query
```

Attention 只控制：

```text
what to inspect next
```

不直接决定：

```text
truth
persistence
delete permission
business authorization
```

---

## 23. 未见实验保护

以下资源继续保护：

```text
MERIT seeds 3/4
MemSyco fresh formal selection
other unopened confirmation slices
```

使用顺序：

1. v16 B1 freeze；
2. M1/M2 implementation；
3. exposed cases 做 reachability/debug；
4. freeze algorithm/prompt/schema/budget；
5. prospective selection；
6. B1 / M1 / M2 matched run。

任何未见 case 一旦用于修算法：

```text
becomes development
```

不能继续作为 formal evidence。

---

## 24. 外部 baseline 计划

当前不立即集成。

优先级：

1. LangMem B0/B1
2. MiLAi M1/M2
3. 若机制成立，再加入：
   - Mem0
   - ReMe

Graphiti / Letta / MemOS 暂不作为早期主比较。

---

## 25. Jev 的位置

Jev 保持：

```text
POST-METHOD EFFICIENCY OPTIMIZATION
```

只有 LLM-only M1/M2 先证明方法价值后，才比较：

```text
same algorithm
LLM controller
vs
Jev controller
```

Jev 不参与 v16，也不参与核心方法成立条件。

---

## 26. 代码纪律

### 允许修改

```text
MiLAi-Lab/src/milai_lab/baselines/
MiLAi-Lab/src/milai_lab/runners/langmem_*
MiLAi-Lab/configs/langmem-*
MiLAi-Lab/data/locks/
MiLAi-Lab/data/manifests/
MiLAi-Lab/tests/unit/test_langmem_*
MiLAi-Lab/tools/*langmem*
MiLAi-Lab/docs/
```

### 默认禁止修改

```text
MiLAi-Product/
MiLAi-Artifact-Archive/
contextual_user_memory.py
contextual_host.py
contextual_maintenance.py
state_attention.py
decision_basis.py
```

---

## 27. 测试建议

### Revision

- create；
- update；
- delete；
- failed op；
- replay；
- cold restart。

### Search

- same results；
- same order；
- same score；
- same filter；
- same limit/offset。

### Observation

- same text different events；
- tool vs user；
- cross-session；
- no gold leak。

### Business

- succeeded；
- failed；
- unknown；
- replay；
- no duplicate side effect。

### Packaging

- optional dependency group；
- no private DSN；
- no raw artifacts；
- lock included。

---

## 28. 结果文档模板

v16 最终报告至少包含：

```text
Status
Foundation identity
B0/B1 parity
Observation trace coverage
Revision trace coverage
Search delivery parity
Business receipt parity
12-case exposed diagnostic
MERIT arc0 exposed regression
Cost
Failures
Unproven claims
Next gate
```

明确写：

> v16 does not establish MiLAi method benefit.

---

## 29. v16 建议终态名称

若成功：

```text
COMPLETE_WITH_INSTRUMENTED_BASELINE
```

若 instrumentation 可用但 parity 有残余问题：

```text
COMPLETE_WITH_PARITY_LIMITATIONS
```

若 foundation 无法保持：

```text
STOPPED_FOUNDATION_INSTRUMENTATION_INVALID
```

---

## 30. 里程碑

| Milestone | 内容 | Model Calls |
|---|---|---:|
| M0 | v15 freeze / v16 Goal | 0 |
| M1 | observation/revision/search sidecar | 0 |
| M2 | deterministic parity tests | 0 |
| M3 | package/boundary/static checks | 0 |
| M4 | exposed 12-case B1 regression | limited |
| M5 | exposed MERIT arc0 B1 regression | limited |
| M6 | final parity report | 0 |
| M7 | decide next GO/PIVOT/STOP | 0 |

---

## 31. 总体研发顺序

```text
v15
Public LangMem foundation
        ↓
v16
B1 instrumentation
        ↓
M1
Sparse Evidence-Grounded Decision State
        ↓
M2
State-Attention
        ↓
Matched unseen evaluation
        ↓
External baselines
        ↓
Optional Jev efficiency backend
```

---

## 32. 四条必须冻结的原则

### 原则一

\[
oxed{
	ext{Instrumentation is not policy}
}
\]

记录事实，不替 Agent 做语义决定。

### 原则二

\[
oxed{
	ext{Delivered evidence} 
eq 	ext{Adopted evidence}
}
\]

B1 只记录前者。

### 原则三

\[
oxed{
	ext{Revision identity} 
eq 	ext{Semantic invalidation}
}
\]

版本变化只提供未来 recheck 的机械基础。

### 原则四

\[
oxed{
	ext{Baseline failure is data, not a bug to hide}
}
\]

如果 B0/B1 漏存、误用或产生 stale memory，应如实保留。

---

## 33. v16 最终目标

v16 完成以后，MiLAi 应拥有一个真正适合方法研究的 matched baseline：

```text
公开 memory framework
+
公开 CRUD/search
+
固定 Agent runtime
+
固定 LLM
+
固定 business environment
+
model-neutral provenance
+
exact memory revision identity
+
complete action/search trace
```

然后才正式回答：

> **在相同 memory 能力、相同信息、相同工具和相同执行保障下，显式维护当前决策究竟采用了什么证据，是否能减少错误适应、漏适应和重复取材？**

这才是 MiLAi 方法研究的正式起点。
