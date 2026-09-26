# MiLAi v17 开发规划：Sparse Evidence-Grounded Decision State（M1）

- 日期：2026-09-26
- 状态：`PLANNED_NOT_STARTED`
- 作用域：`MiLAi-Lab`
- 当前基线：v16 `COMPLETE_WITH_INSTRUMENTED_BASELINE`
- v16 提交：`3676c511f4c4087453d5bbf54cea3514e57fd948`
- B1 source mapping：`ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea`
- foundation：LangMem `0.0.30` / upstream commit `9d033b47d9ce53e37e92c92241b0496c0278932e`
- 模型：Qwen3.6-35B-A3B-FP8
- vLLM：**保持现有设置，不修改 parser、thinking、context、服务参数**
- 本文性质：下一阶段开发上位规划；不表示 v17 已执行、验证或提交

---

## 0. 执行摘要

v15 已完成公开 LangGraph / LangMem foundation；v16 已完成 B1 的模型不可见 provenance / revision / search-delivery / action-receipt instrumentation，并通过同输出 raw-wire parity。当前研究第一次拥有了一个适合方法开发的公开、可追踪 baseline：

```text
B0 = public LangMem baseline

B1 = B0
   + Observation tracking
   + exact MemoryRevision tracking
   + SearchDelivery tracking
   + ActionReceipt linking
```

v16 最终真实运行仍保持 baseline 的原有语义失败：

- diagnostic：`7/12`
- MERIT：`4/5`
- dependent：`1/2`
- 首次约定漏存；
- 已存 memory 不一定被搜索；
- 空搜索后可能写入无依据 memory；
- 错误 memory 可能驱动真实业务动作；
- 成功业务动作后 persistent memory 可能保持 stale。

这些失败现在已经可以被机械 trace 精确观察，但 **B1 不知道当前决策实际依赖了哪些材料**。

v17 的唯一核心目标是实现 M1：

> **Sparse Evidence-Grounded Decision State：在正常 ReAct 过程中，用一个很小的 task-local Decision Basis 显式记录“当前行动相关判断是什么、实际采用了哪些已交付证据、是否存在会改变下一步行动的信息缺口”，并在已采用 memory 的准确 revision 变化时触发 selective recheck。**

形式上：

\[
M1 = B1 + Sparse\ Decision\ Basis + Explicit\ Adopted\ Evidence + Program-Owned\ Recheck
\]

v17 **不加入 State–Attention**，不修改 LangMem search ranking/query，不增加额外 reflection Agent，不增加 Jev，也不消费未见 MERIT seeds。

v17 成功的标准不是把 `7/12` 或 `4/5` 修高，而是证明：

1. Decision Basis 能自然、稀疏地进入真实 ReAct；
2. adopted evidence 必须是模型实际见过的 B1 evidence；
3. exact revision 改变后，程序能产生 recheck，而不会自动改写 decision；
4. recheck 能在下一次正常 LLM 调用中被处理；
5. 不需要额外模型调用；
6. State 不退化为每轮必填的 structured scratchpad；
7. 机制成本可测、可控。

---

# 1. v16 之后已经成立的研究前提

## 1.1 B1 已完成的事实层

v16 已经可以准确回答：

- 哪个 user / business Observation 实际发生；
- 哪个 memory ID 实际产生了哪个 revision；
- 哪次 search 返回了哪些 memory revision；
- 哪些 ToolMessage 实际进入了哪个 Provider request；
- 哪个 business call 得到了什么 receipt；
- 当前 LangMem Store 最终保存什么。

但 B1 **不能**回答：

```text
Agent 当前为什么准备做这个动作？
Agent 实际采用了 search 返回的哪条 memory？
哪个 memory 只是看见了但没有采用？
哪个新 observation 会改变当前判断？
```

这正是 M1 的增量。

---

## 1.2 v16 的保守边界必须保留

v16 的 source provenance 仍然是：

```text
UNKNOWN_NOT_DECLARED
```

当 upstream tool 本身没有 source 参数时，程序不会把“当时可见 observation”推断成 memory 的语义来源。

v17 也不能修改这个事实。

因此：

```text
memory provenance
```

与：

```text
decision adoption
```

必须严格分开。

M1 可以让 Host 声明：

> “当前 decision 采用 memory X@2。”

但不能据此倒推：

> “memory X@2 的正文一定由 observation O 正确支持。”

---

# 2. v17 的研究问题

主问题：

> **在一个已经具备公开长期 memory CRUD/search、持久化、业务执行、恢复和精确 instrumentation 的 Agent 上，显式维护当前决策采用的证据，是否能够形成稳定、稀疏、可修订的决策控制状态？**

v17 是机制开发阶段，不做最终效果结论。

更具体地回答五个问题：

1. LLM 是否会自然建立有意义的 current decision，而不是重复任务摘要？
2. adopted evidence 是否真的对应当前请求中已交付的 observation / memory revision？
3. exact memory revision 变化能否机械触发 recheck？
4. 新 observation 到来时，系统能否让 Host 重新考虑，而不依赖旧 dependency edge？
5. M1 是否可以在不增加独立模型调用的情况下完成？

---

# 3. v17 明确不做什么

本轮禁止：

- 自动修改 LangMem query；
- gap-directed retrieval；
- candidate expansion；
- adaptive stopping；
- retrieval ranking 改动；
- 自动 search；
- 自动阻止业务 action；
- “没有 adopted evidence 就禁止执行”的 hard guard；
- future commitment 强制保存；
- 自动 memory reconciliation；
- 自动 UPDATE / DELETE；
- support graph；
- dependency graph 扩展；
- 第二审核模型；
- reflection Agent；
- Jev；
- 新训练；
- Product 改动；
- 未见 MERIT seeds 3/4；
- fresh formal MemSyco。

这些属于 M2 或后续正式评价。

---

# 4. B1 与 M1 的严格差异

## 4.1 B1

```text
B1 knows:
- what observations happened
- what memories/revisions exist
- what searches returned
- what materials entered a request
- what business actions actually happened
```

## 4.2 M1

```text
M1 additionally knows:
- what current decision matters
- which delivered evidence the decision actually adopts
- what action-changing uncertainty remains
- whether an adopted exact revision changed
```

核心区别：

\[
Delivered\ Evidence \neq Adopted\ Evidence
\]

B1 解决前者。

M1 首次引入后者。

---

# 5. M1 的最小状态

首版只允许 **一个 active decision slot**。

```text
DecisionBasis
  decision_id
  revision
  task_id

  decision
  scope

  adopted_evidence[]
  critical_gap

  host_status
  recheck_reasons[]
```

其中：

```text
host_status ∈ {active, deferred}
```

`needs_recheck` 不由 Host 直接写。

它由程序根据 `recheck_reasons` 投影得到。

---

# 6. 字段语义

## 6.1 decision

必须表达一个可能影响下一步 meaningful action 的当前判断。

正确例子：

```text
The refund amount currently justified for order X is 1774 cents.
```

错误例子：

```text
The user asked about a refund.
```

后者只是任务摘要。

## 6.2 scope

保持很小：

```text
scope:
  subject
  item
  context
```

例如：

```text
subject = current_user
item = ORD-197802
context = refund execution
```

scope 用于解释 decision，不承担完整实体图职责。

## 6.3 adopted_evidence

只允许指向 B1 已知的 **准确、实际交付材料**：

```text
memory:<uuid>@<revision>
observation:<event_id>
```

首版最多建议：

```text
max 8
```

每项内部保存：

```text
ref
kind
content_sha256
delivery/request identity
```

Host 只输出短 ref。

程序负责绑定准确对象。

## 6.4 critical_gap

类型：

```text
string | null
```

它不是“任何不知道的事情”。

只有满足：

> 如果这个问题的不同答案会改变下一项 meaningful action、关键参数或是否行动，

才可以成为 `critical_gap`。

例：

```text
What is the currently agreed refund amount?
```

不是：

```text
Why did the user originally choose this amount?
```

如果后者不改变当前 action，就不应成为 active gap。

## 6.5 host_status

Host 只允许：

```text
active
deferred
```

Host **不能输出**：

```text
needs_recheck
```

---

# 7. 一个重要调整：Basis 不要求始终有 gap

与旧 contextual 实验不同，v17 不把：

```text
critical_gap = null
```

自动解释成：

```text
clear basis
```

原因是：

> 一个已经得到证据支持、当前仍会影响后续行动的 decision，即使暂时没有 gap，也可能需要在 adopted memory revision 变化后重新检查。

因此允许：

```text
decision = ...
adopted_evidence = [memory:X@1]
critical_gap = null
host_status = active
```

只有 decision 不再影响当前/后续 task action 时，才 clear。

---

# 8. Sparse Activation 原则

M1 不能变成 always-on state。

只有满足至少一个条件才应存在 Basis：

### 条件 A：Action-sensitive uncertainty

存在两个合理状态：

\[
h_1,h_2
\]

使：

\[
a(h_1) \neq a(h_2)
\]

### 条件 B：Ongoing grounded decision

当前已有一个会继续影响后续 action 的判断，并且它依赖具体外部 evidence。

例如：

```text
refund amount = 1774
```

即使当前 gap 已解决，只要任务尚未结束，它仍可保持 active。

### 不应激活的情况

- 普通闲聊；
- 纯格式任务；
- 当前动作与未知信息无关；
- 只是“记住用户说了什么”；
- task summary；
- 已经完全结束、不再影响后续动作的旧判断。

---

# 9. M1 输出协议

Decision state 必须和正常 ReAct action **同一次 generation** 输出。

不允许：

```text
LLM call 1: update State
LLM call 2: decide action
```

建议扩展现有 JSON-action envelope：

```json
{
  "decision_delta": null,
  "calls": [...]
}
```

或：

```json
{
  "decision_delta": {
    "op": "set",
    "decision": "...",
    "scope": {
      "subject": "...",
      "item": "...",
      "context": "..."
    },
    "adopted_evidence": ["e1", "e2"],
    "critical_gap": "...",
    "status": "active"
  },
  "calls": [...]
}
```

最终回答：

```json
{
  "decision_delta": null,
  "answer": "..."
}
```

clear：

```json
{
  "decision_delta": {
    "op": "clear"
  },
  "answer": "..."
}
```

---

# 10. State delta 设计

首版只支持：

```text
null
set
clear
```

不增加复杂 patch。

理由：

- Basis 很小；
- v17 首先验证机制；
- sparse activation 已经减少状态量；
- patch 会增加 grammar / reducer / recovery 复杂度。

如果 v17 实测 state output 成本仍明显过高，再在后续版本研究 patch。

---

# 11. Evidence handle 投影

M1 需要把 B1 的 model-hidden exact identity 转成**最小模型可见 handle**。

例如：

```text
Available evidence:
e0 = observation:user:...
e1 = memory:550e...@1
e2 = receipt:refund-call-7
```

正文仍使用原 LangMem ToolMessage / user / business result。

handle 只提供：

```text
short ref
kind
exact revision identity
```

不要重复大段 content。

## 11.1 首次 adoption

只有当前 request 中实际交付的 evidence 才能首次 adopt。

程序校验：

```text
adopted_ref ∈ delivered_evidence(current_request)
```

否则拒绝：

```text
DECISION_EVIDENCE_NOT_DELIVERED
```

## 11.2 continuation adoption

Basis 跨下一次 request 持续时，可以保留已经采用的 exact ref：

```text
c0 = memory:X@1
```

即使该正文没有再次完整送入模型，也可以在 Decision Context 中显示它的短 ref 和简短 label。

但：

> continued ref 不等于重新读取正文。

如果 revision 已变化，Host 必须 search/read/重新获取材料才能采用新 revision。

---

# 12. Decision Context 投影

每次模型调用最多投影一个紧凑块：

```text
Decision state:
decision: ...
scope: ...
adopted:
  c0 memory:X@1
gap: null
status: needs_recheck

recheck:
  c0 has current revision X@2

new observations:
  o7
```

不重复：

- 全部 revision history；
- 全部 sidecar；
- 所有 search results；
- 全部 receipts；
- 完整 B1 trace。

目标是：

```text
compact control state
```

不是另一个 transcript。

---

# 13. Program-owned Selective Recheck

## 13.1 确定性 trigger

如果当前 Basis adopted：

```text
memory:X@1
```

而 B1 观察到：

```text
memory:X@2
```

则：

```text
recheck_reason:
  adopted_ref = X@1
  current_ref = X@2
  reason = revision_changed
```

Basis 投影状态：

```text
needs_recheck
```

但 Host 原始 `host_status` 仍保存 active/deferred。

## 13.2 Delete / tombstone

如果 adopted revision 被删除：

```text
X@1 -> tombstone X@2
```

同样：

```text
reason = deleted_or_tombstoned
```

不自动删除 decision。

## 13.3 不自动 rebind

绝对禁止：

```text
X@1 changed to X@2
→ adopted_evidence silently becomes X@2
```

正确行为：

```text
adopted = X@1
recheck = true
```

直到 Host 真正看到 X@2 并显式重新采用。

---

# 14. 新 Observation 的处理

一个重要边界：

> 没有 dependency edge，不代表新 observation 与当前 decision 无关。

因此所有 active Basis 都必须在下一次正常请求中看到：

```text
new_observation_refs
```

但是程序不能仅凭 subject/hash 自动说：

```text
decision invalid
```

Host 在正常 ReAct 中决定：

```text
keep basis
change basis
search
act
clear
```

首版不做 semantic overlap classifier。

---

# 15. Recheck 的完成语义

recheck 不是 Revision 的同义词。

正确转移：

```text
revision changed
        ↓
needs_recheck
        ↓
Host reviews
        ├── keep same decision
        ├── change decision
        ├── search/read more
        ├── update memory
        ├── no-op
        └── clear decision
```

只要 Host 在实际看到新材料后提交新的合法 `decision_delta`，对应 recheck reason 才能 acknowledged。

---

# 16. 与 Memory CRUD 的关系

LangMem CRUD 保持 upstream。

M1 不重新实现：

```text
CREATE
UPDATE
DELETE
SEARCH
```

Decision Basis 只提供决策上下文。

典型关系：

```text
缺材料
→ Host 选择 search

新 durable info
→ Host 选择 manage_memory(create/update)

重复确认
→ no memory write

memory revision changed
→ recheck
```

M1 不拥有物理删除权限。

---

# 17. Action Receipt 的使用边界

M1 可以 adopt：

```text
business observation / receipt
```

例如：

```text
refund call succeeded
```

作为当前 decision 的 evidence。

但：

```text
receipt succeeded
```

只证明该调用结果。

不能推导：

```text
the action was semantically correct
```

v15/v16 的 5000-cents refund 就是直接反例。

---

# 18. 不增加 hard action gate

v17 不加入：

```text
if adopted_evidence empty:
    block business action
```

也不加入：

```text
if critical_gap != null:
    force search
```

否则无法区分：

- Decision State 表示价值；
- deterministic policy gate 价值。

v17 只让 M1 State 影响正常 LLM reasoning。

M2 才研究显式控制。

---

# 19. 代码组织建议

新代码与旧 contextual method 隔离：

```text
MiLAi-Lab/
  src/milai_lab/
    baselines/
      langmem_*                  # B0/B1 existing

    methods/
      milai_m1/
        __init__.py
        decision_basis.py
        evidence_view.py
        recheck.py
        state_store.py

    runners/
      langmem_m1.py
      langmem_m1_merit.py
      langmem_m1_diagnostic.py

    providers/
      langmem_chat.py            # 仅必要 envelope extension

  configs/
    langmem-b1-v16.json
    milai-m1-v17.json

  data/locks/
    langmem-b1.lock.json
    milai-m1-v17.lock.json

  tests/unit/
    test_milai_m1_basis.py
    test_milai_m1_recheck.py
    test_milai_m1_transport.py

  tools/
    prepare_milai_m1.py
    run_milai_m1.py
    inspect_milai_m1.py

  docs/
    MILA_LANGMEM_M1_GOAL_v17.md
```

默认不修改：

```text
contextual_user_memory.py
contextual_host.py
contextual_maintenance.py
old decision_basis.py
state_attention.py
```

旧实现只做参考。

---

# 20. Work Package A：冻结 B1

目标：

> 保证 M1 的共同底座就是 v16 B1，而不是开发过程中继续变化的 baseline。

必须锁定：

- `3676c51`
- B1 source mapping
- B1 lock
- upstream LangMem
- JSON-action recipe
- vLLM identity
- embedding identity
- business journal contract
- diagnostic / MERIT identity
- v16 costs

### Gate A

```text
B1 identities unchanged
v16 results untouched
no Product change
no holdout consumption
```

---

# 21. Work Package B：M1 State Store

实现：

```text
DecisionBasisStore
```

建议 SQLite sidecar，独立于：

- LangMem Store；
- checkpoint；
- B1 instrumentation sidecar。

Key：

```text
run_id
arm_id
user_id
task_id
```

只存当前 Basis 与历史 delta/ack 事件。

不存完整 memory body。

---

# 22. Work Package C：Evidence View

将 B1 事实投影为 M1 可引用的最小 evidence handles。

来源：

```text
current user Observation
business Observation / receipt
memory search delivery
continued adopted evidence
```

必须区分：

```text
available
delivered
adopted
```

### Gate C

- undelivered ref 不能 adopt；
- search 返回但未进入 request 的材料不能 adopt；
- exact revision 正确；
- observation identity 正确；
- continued old revision 不自动 latest。

---

# 23. Work Package D：JSON-action + decision_delta

扩展 response schema，使：

```text
decision_delta
```

与：

```text
calls / answer
```

共存。

### Gate D

必须验证当前 vLLM / xgrammar：

- schema 可生成；
- calls 顺序不变；
- arguments 仍按原工具 schema validate；
- invalid decision delta 不执行工具；
- invalid tool args 与 state error 有明确回执；
- 不需要修改服务设置。

如果 schema 无法在现有 decoder 下稳定表达：

> 优先调整 envelope / property order / adapter。

不修改 vLLM 服务。

---

# 24. Work Package E：Sparse Basis reducer

实现：

```text
null
set
clear
```

规则：

### null

保持当前 Basis。

### set

完整替换语义字段，但：

- exact evidence 由程序绑定；
- identical normalized state → `NO_STATE_CHANGE`；
- program recheck reasons 不由 Host 覆盖。

### clear

删除当前 task Basis。

---

# 25. Work Package F：Recheck engine

监听 B1 revision events。

首版 trigger：

```text
adopted memory revision superseded
adopted memory deleted/tombstoned
task identity changed
```

不加入：

```text
semantic similarity trigger
scope overlap trigger
LLM recheck classifier
```

新 Observation 通过普通投影交给 Host，而不是程序自动 invalid。

---

# 26. Work Package G：恢复与重放

必须支持：

- process restart；
- same task continuation；
- Decision Basis restore；
- pending recheck restore；
- business journal 不重复；
- LangMem Store 不复制；
- B1 sidecar 不复制。

重放 completed turn：

```text
不得新增 decision revision
不得新增 business action
不得新增 memory operation
```

---

# 27. V0：确定性机械测试

必须先完成，不调用真实模型。

至少覆盖：

### Evidence

- adopt delivered observation；
- adopt delivered memory revision；
- reject undelivered evidence；
- reject stale/latest confusion；
- same text different observation IDs。

### State

- create basis；
- same set → no-op；
- update decision；
- gap null；
- deferred；
- clear；
- restore。

### Recheck

- X@1 → X@2；
- X@1 → tombstone；
- no auto-rebind；
- unrelated revision no trigger；
- recheck acknowledged only after valid delta。

### Transport

- `decision_delta + calls`；
- `decision_delta + answer`；
- invalid delta → no side effect；
- invalid tool call → existing error semantics；
- no second generation required。

---

# 28. V1：受控机制诊断

允许增加一个明确标注的：

```text
M1_MECHANISM_DIAGNOSTIC
```

它不是 benchmark，也不计方法效果。

用途只验证自然链：

```text
memory X@1
→ decision adopts X@1
→ user correction / memory update X@2
→ program marks recheck
→ next normal generation sees reason
→ Host re-evaluates
```

要求：

- 输入在运行前冻结；
- 不使用 MERIT gold；
- 不进入 formal score；
- 一旦用于调机制，永久视为 development。

---

# 29. V2：原 12-case exposed diagnostic

使用现有冻结输入。

目标不是分数提升，而是检查：

- Basis activation rate；
- adoption validity；
- state churn；
- 是否出现 task-summary state；
- 是否出现无意义 gap；
- 是否影响正常业务动作。

重点失败可以用于 diagnosis，但不能作为独立有效性证据。

---

# 30. V3：exposed MERIT arc0

运行完整 5 episodes / 7 messages。

主要观察：

1. 是否在需要金额决策时形成 decision；
2. adopted evidence 是否为空或真实；
3. 空 search 后是否产生 actionable gap；
4. 是否仍会出现无依据 5000；
5. 6595 refund 后 Basis 是否反映真实业务结果；
6. 是否发生自然 memory update/recheck。

即使从 4/5 变 5/5：

> 也只能作为 development signal。

不能作为最终方法效果。

---

# 31. v17 不消费未见任务

默认：

```text
MERIT seeds 3/4 = NOT_RUN
fresh MemSyco = NOT_RUN
StateMemBench = NOT_RUN
```

原因：

> v17 的目标是证明 M1 机制设计值得进入正式比较。

未见样本留给 M2 完成后的 matched evaluation。

---

# 32. v17 核心指标

## 32.1 Basis Activation Rate

\[
rho =
rac{turns\ with\ active\ basis}{all\ model\ turns}
\]

不是越高越好。

若接近 1：

> 很可能退化为 structured scratchpad。

## 32.2 Basis Churn

\[
chi =
rac{semantic\ basis\ revisions}{active\ basis\ turns}
\]

用于发现无意义重复改写。

## 32.3 Adoption Validity

机械目标：

```text
100% adopted refs
must be actually delivered or legally continued exact refs
```

## 32.4 Evidence Selectivity

记录：

```text
delivered evidence count
adopted evidence count
```

如果每次都 adopt 全部 material：

> Decision Basis 没有选择性。

## 32.5 Gap Quality

人工/冻结 rubric 判断：

```text
Would resolving this gap differently change the next meaningful action?
```

## 32.6 Recheck

记录：

```text
recheck triggers
acknowledged
decision changed
decision retained
additional read/search
```

版本变化本身不是成功。

## 32.7 Non-intervention

在不需要 Basis 的任务：

```text
decision_delta = null
```

应成为正常结果。

---

# 33. 成本指标

必须单独报告：

```text
Decision Context input tokens
decision_delta output tokens
basis activation count
basis revisions
recheck projections
extra generations
```

核心要求：

```text
extra generations = 0
```

如果 M1 必须新增独立模型调用才能工作：

> 默认 PIVOT。

---

# 34. v17 Go / Pivot / Kill

| 结果 | 决策 |
|---|---|
| Basis 稀疏、adoption 真实、recheck 可达、无额外 call | **GO → M2** |
| Basis 有用但主要作用是约束“必须有 evidence” | **PIVOT → decision-grounding / action-safety mechanism** |
| 只有 recheck 有价值 | **PIVOT → selective revalidation** |
| 只有 structured representation 有效 | **PIVOT → representation/control separation** |
| Basis 几乎从不自然激活 | **KILL M1** |
| Basis 每轮都激活、等价于 structured scratchpad | **KILL / redesign sparse criterion** |
| adopted evidence 总是全部材料 | **KILL selectivity claim** |
| recheck 只增加错误或重复搜索 | **KILL recheck mechanism** |
| 必须增加第二 LLM call 才稳定 | **PIVOT** |
| 优势来自 hard-coded MERIT 规则 | **KILL method claim** |

---

# 35. M2 的进入条件

只有以下条件同时满足才进入 State–Attention：

1. M1 真实产生非零 adopted evidence；
2. adoption 不是“全材料照单全收”；
3. 至少一个 recheck 链自然/受控可达；
4. sparse activation 不退化；
5. 状态成本可接受；
6. 没有明显降低普通任务完成；
7. 不需要额外模型调用。

否则不要继续增加 Attention。

---

# 36. 后续 M2 的唯一新增职责

M2 只允许在 M1 上增加：

```text
critical_gap
→ retrieval focus / candidate expansion / stop-defer control
```

B1 memory CRUD、Store、business tools、revision sidecar保持相同。

未来主消融：

```text
B1
vs
M1
vs
M2
```

---

# 37. 正式 matched evaluation 的保护

正式比较必须等 M2 冻结后。

统一：

- 相同 LLM；
- 相同 vLLM；
- 相同 LangMem；
- 相同 business tools；
- 相同 Store；
- 相同 B1 instrumentation；
- 相同数据；
- 相同预算规则；
- 相同 scorer。

区别只能是：

```text
B1: no Decision Basis
M1: Decision Basis + recheck
M2: M1 + State–Attention
```

---

# 38. 建议的 v17 终态

成功：

```text
COMPLETE_WITH_M1_MECHANISM_REACHABLE
```

机制成立但有明显限制：

```text
COMPLETE_WITH_M1_LIMITATIONS
```

机制不能形成：

```text
STOPPED_M1_NOT_JUSTIFIED
```

不要使用：

```text
M1_EFFECTIVE
MiLAi_WINS
```

因为 v17 不做未见效果验证。

---

# 39. 里程碑

| Milestone | 内容 | Real Model |
|---|---|---:|
| M0 | v16 freeze / v17 Goal | 0 |
| M1 | DecisionBasis store + reducer | 0 |
| M2 | Evidence View | 0 |
| M3 | JSON-action state/action envelope | decoder probe only |
| M4 | Recheck engine | 0 |
| M5 | V0 deterministic suite | 0 |
| M6 | controlled mechanism diagnostic | small |
| M7 | exposed 12-case diagnostic | small |
| M8 | exposed MERIT arc0 | small |
| M9 | GO / PIVOT / KILL | 0 |

---

# 40. 文件与交付

v17 至少交付：

```text
MILA_LANGMEM_M1_GOAL_v17.md
MILA_LANGMEM_M1_V17_DEVELOPMENT_20260926.md
MILA_LANGMEM_M1_V17_RESULTS_20260926.md
MILA_LANGMEM_M1_V17_REPRODUCTION_20260926.md
```

以及：

```text
m1 lock
final freeze
mechanism diagnostic manifest
cost summary
exposed-run manifests
```

原始 Provider trace / SQLite / Store 数据继续 ignored。

---

# 41. 四条冻结原则

## 原则一：Availability is not adoption

\[
Delivered \neq Adopted
\]

## 原则二：Version change is not semantic falsity

\[
X@1 \rightarrow X@2
\not\Rightarrow
Decision\ is\ false
\]

只触发 recheck。

## 原则三：No edge does not mean unaffected

新 Observation 必须继续进入普通 Host observation path。

M1 不能只看旧 adopted dependency。

## 原则四：State is optional

\[
No\ useful\ Decision\ Basis
\Rightarrow
decision\_delta = null
\]

“不调用 State”不是失败。

---

# 42. v17 最终目标

v17 完成后，MiLAi 应首次具备下面这条完整但最小的控制链：

```text
actual observations / memory revisions / receipts
                ↓
       delivered evidence
                ↓
       explicit adoption
                ↓
      current decision basis
                ↓
 exact adopted revision changes
                ↓
         needs recheck
                ↓
 next ordinary ReAct generation
                ↓
 keep / change / read / search / act / no-op
```

如果这条链在真实 LLM 运行中自然成立，并且保持稀疏、不增加独立模型调用，才值得进入下一阶段 State–Attention。

论文方法的核心问题也由此收敛为：

> **在一个公开、可追踪的长期记忆 Agent 上，显式维护“当前决策实际依据什么”，能否为后续的选择性取材和局部重核提供一个稳定、低开销的控制状态？**

v17 只回答“这个机制是否值得继续”。

真正的质量收益与质量—成本边界，留给 M2 冻结后的未见 matched evaluation。
