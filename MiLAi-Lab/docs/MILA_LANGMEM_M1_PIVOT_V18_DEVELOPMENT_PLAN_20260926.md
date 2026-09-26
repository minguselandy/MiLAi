# MiLAi v18 开发规划：M1 Pivot — Decision Proposition + Recheck Completion

- 日期：2026-09-26
- 状态：`PLANNED_NOT_STARTED`
- 作用域：`MiLAi-Lab`
- 当前基线：v17 `COMPLETE_WITH_M1_LIMITATIONS`
- v17 决策：`PIVOT_REDESIGN_M1_BEFORE_M2`
- v17 提交：`9438d1349b5f7988ca86f491ad489eefa87becd3`
- v17 source mapping：`392c14287062a92465f74b31e402ea65099a55cb5136a1c3939b05dd1655b66f`
- B1 reference：v16 `3676c511f4c4087453d5bbf54cea3514e57fd948`
- foundation：LangMem `0.0.30` / upstream `9d033b47d9ce53e37e92c92241b0496c0278932e`
- 模型：Qwen3.6-35B-A3B-FP8
- vLLM：**保持当前设置，不修改 parser、thinking、context、服务参数**
- 本文性质：下一阶段开发上位规划；不表示 v18 已执行、验证或提交

---

## 0. 执行摘要

v17 已完成 M1 Sparse Evidence-Grounded Decision State 的工程接入，但结果明确要求 **PIVOT，而不是继续进入 M2 State–Attention**。

v17 已经证明：

- Decision Basis 可以和正常 ReAct action 在同一次 generation 中产生；
- adopted evidence 可以严格绑定到实际 delivered evidence；
- adoption validity 为 `22/22`；
- exact memory revision 变化可以由程序触发 `revision_changed`；
- recheck reason 可以进入真实后续请求；
- 不需要额外独立 State / reflection generation；
- vLLM 设置无需修改。

但 v17 同时证明了当前 M1 的核心语义假设失败：

> **“只要显式记录 adopted exact evidence，并在版本变化时通知模型 recheck，Host 就会自然完成正确重核。”**

受控机制例中：

```text
memory X@1 = 4°C
→ Decision Basis adopts X@1
→ memory externally updated to X@2 = 8°C
→ program correctly emits revision_changed
→ recheck is projected into 2 real requests
→ Host does not read/use X@2
→ Host retains old 4°C interpretation
→ Basis is cleared
→ business action still records 4°C
```

因此：

```text
recheck triggered != recheck completed
```

当前 M1 最大的问题不是“没有提醒模型”，而是：

1. Basis 经常表达主题标签，而不是可被证据修订的实际判断；
2. 机械合法 adoption 不等于 action parameter 的完整 grounding；
3. clear Basis 可以发生在 stale judgment 尚未处理时；
4. recheck reason 虽可见，但协议没有要求 Host 给出可判定的重核结果。

v18 的唯一核心目标是：

> **把 Decision Basis 从“主题/标签状态”收紧为可检验的 action-sensitive proposition，并把 recheck 从“通知”升级为具有明确完成语义的状态转换。**

形式上：

```text
M1' = M1
    + Decision Proposition
    + Explicit Recheck Outcome
    + Completion Contract
```

v18 **不加入 M2 Attention**，不自动 search，不自动阻止业务动作，不增加第二模型调用，不硬编码 MERIT 业务规则。

如果 v18 在受控 `4°C → 8°C` 场景中仍不能让 LLM 在普通 ReAct 调用中完成正确重核，则默认 **停止当前 Decision Basis 主线**，而不是继续叠加 Attention。

---

# 1. v17 终态：哪些已经成立，哪些没有成立

## 1.1 已成立的工程事实

| 项目 | v17 结果 |
|---|---:|
| Adoption validity | `22/22` |
| Controlled revision trigger | 1 |
| Recheck projected requests | 2 |
| Extra independent State generations | 0 |
| Protocol errors in final R2 | 0 |
| MERIT native | `4/5` |
| MERIT dependent | `1/2` |
| Diagnostic semantic | `5/12` |
| Total generations | 101 |
| Generation tokens | 101,810 |
| Embedding tokens | 916 |

因此 v18 **不重新解决**：

- exact ref binding；
- delivered-evidence validation；
- state persistence；
- JSON-action integration；
- recheck trigger detection；
- vLLM decoder compatibility；
- B1 instrumentation。

这些继续作为共享底座。

## 1.2 未成立的核心语义

### A. Decision 不是 proposition

大量 Basis 更接近：

```text
holding_temperature
refund_amount
parity_check
```

这类标签不能直接回答：

> 当前到底认为“什么是真的”，以及这个判断会如何改变下一步动作？

### B. Adoption validity 不等于 sufficient grounding

即使：

```text
all adopted refs are valid
```

仍然不能推出：

```text
action parameter is fully grounded
```

### C. Recheck 只有 trigger，没有完成语义

v17 可以记录：

```text
memory:X@1
→ current memory:X@2
→ revision_changed
```

但协议没有强制 Host 说明：

```text
retained
changed
unresolved
```

### D. 受控例直接证明当前 M1 不足

```text
4°C → 8°C
```

最终：

```text
new version body read = 0
recheck acknowledgement = 0
semantic change = 0
stale business action = 4°C
```

这是 v18 的唯一主要机制修复目标。

---

# 2. v18 的研究问题

v18 只回答：

> **如果 Decision State 表达一个具体、可被证据支持或修订的 action-sensitive proposition，并要求 pending recheck 得到显式 outcome，LLM 是否能在正常 ReAct 调用中完成正确重核？**

拆成四个问题：

1. Host 能否生成真正的 proposition，而不是 topic label？
2. adopted evidence 是否足以支持 proposition 中的 action-critical slots？
3. exact revision change 后，Host 是否能给出显式 recheck outcome？
4. 不增加独立 LLM call、不强制 search、不 hard-block action 时，受控重核是否能完成？

---

# 3. v18 明确不做什么

v18 禁止：

- State–Attention；
- gap-directed retrieval；
- automatic search；
- candidate expansion；
- adaptive stop；
- retrieval ranking 改动；
- `pending recheck → force search`；
- `pending recheck → block all business actions`；
- `no evidence → block action`；
- 自动 memory update；
- 自动 memory reconciliation；
- semantic dependency graph；
- support graph；
- 第二 reviewer；
- reflection Agent；
- Jev；
- 新训练；
- Product 修改；
- MERIT seeds 3/4；
- fresh formal MemSyco；
- 针对 4°C/8°C 写具体值规则。

v18 只修：

```text
State semantics
+
Recheck completion semantics
```

---

# 4. M1' 最小状态

建议：

```text
DecisionBasis
  decision_id
  revision
  task_id

  proposition
  action_scope

  adopted_evidence[]
  unresolved_gap

  host_status
  recheck_reasons[]
  recheck_outcome
```

其中：

```text
host_status ∈ {active, deferred}

recheck_outcome ∈ {
  null,
  retained,
  changed,
  unresolved
}
```

`needs_recheck` 仍由程序根据 `recheck_reasons` 投影，不由 Host 直接填写。

---

# 5. Decision Proposition

`proposition` 必须是当前可检验判断，其真假或具体值会影响 meaningful action。

正确：

```text
If dispatch is approved now, crate Lumen-42 should be held at 4°C.
```

```text
The currently justified refund amount for ORD-197802 is 1774 cents.
```

```text
The pickup should remain unbooked until the documents-accepted condition is observed.
```

错误：

```text
holding_temperature
refund task
need to check memory
remember user preference
```

定义：

```text
P -> A(P)
```

若 proposition 的不同合理取值不会改变 meaningful action，则不应成为 active Basis。

---

# 6. Action Scope

将旧 `scope` 收紧为：

```text
action_scope:
  subject
  item
  action_type
  critical_parameters[]
```

例如：

```text
subject = current_user
item = crate:Lumen-42
action_type = record_holding_instruction
critical_parameters = ["temperature_celsius"]
```

退款：

```text
item = ORD-197802
action_type = refund
critical_parameters = ["amount_cents"]
```

`action_scope` 只描述 decision 会影响什么，不授予动作权限。

---

# 7. Adopted Evidence 与 Support Role

v17 已保证 adoption 的机械合法性。v18 不让程序判断自然语言支持关系，而要求 Host 对每个 adoption 声明：

```text
support_role ∈ {
  supports_value,
  constrains_applicability,
  records_execution,
  contextual
}
```

例如：

```text
memory:X@1
support_role = supports_value
```

表示 Host 声明该 evidence 提供 proposition 的 action-critical value。

程序继续只保证：

```text
ref actually delivered
exact revision exists
body hash matches
not silently rebound
```

程序**不**保证该 evidence 的语义真的支持 proposition。

若 upstream memory 没有显式 source 参数：

```text
source_refs = UNKNOWN_NOT_DECLARED
```

继续保持 unknown。

---

# 8. 不引入 Claim Graph

v18 不建立：

```text
proposition graph
support graph
logical dependency graph
```

只维护：

```text
one proposition
small adopted evidence list
support_role
```

如果这一最小形式仍不能完成可靠重核，不再通过增加图结构救机制。

---

# 9. Recheck Completion Contract

这是 v18 最重要的变化。

当：

```text
recheck_reasons != []
```

Host 下一次有效 `set` 必须明确给出：

```text
recheck_outcome
```

## 9.1 retained

表示 Host 已处理 recheck evidence，并认为 proposition 仍成立。

最低机械条件：

- 必须 adopt 至少一个与本次 recheck 相关的 current/new evidence；
- 如果旧 adopted memory 已更新，不能仅采用 superseded revision 后声称 retained。

例如：

```text
X@1 → X@2
```

若 retained：

```text
adopted must include X@2
```

或另一个当前可见、被 Host 声明支持当前 proposition 的独立 evidence。

程序只检查 current/new evidence 是否真的 delivered，不判断它语义上是否足够。

## 9.2 changed

表示 proposition 已根据新 evidence 改变。

要求：

- proposition 发生变化；
- 至少采用一项 current/new evidence；
- pending recheck 被明确 acknowledged。

例如：

```text
old: use 4°C
new: use 8°C
adopted: X@2
support_role: supports_value
recheck_outcome: changed
```

## 9.3 unresolved

表示 Host 已意识到旧 Basis 不能安全视为已确认，但当前材料不足。

允许 proposition 暂时保留，但：

```text
host_status = deferred
```

并继续保留 unresolved recheck。

---

# 10. clear 的新限制

v17 暴露：

```text
clear
→ stale action
```

因此如果存在 pending recheck，`clear` 只有两类合法情况。

### 情况 A：任务判断真的结束

例如：

```text
task cancelled
item no longer relevant
action no longer needed
```

必须给出：

```text
clear_reason = task_ended
```

### 情况 B：同一 delta 已明确完成 recheck

先有：

```text
recheck_outcome = retained / changed
```

再结束 Basis 生命周期。

非法：

```text
pending recheck
→ clear
→ continue using old parameter
```

这种情况作为协议错误处理，同响应中的工具调用不执行。

这是 state consistency guard，不是业务真值 gate：程序仍不知道 4°C 或 8°C 谁正确。

---

# 11. Pending Recheck 时是否允许业务动作

默认允许。

v18 不做：

```text
if pending_recheck:
    block_business_action()
```

如果 Host 给：

```text
recheck_outcome = unresolved
```

但仍选择执行业务动作，允许实际发生并完整记录。

这样才能测出真实控制失败，而不是通过程序拦截制造成功。

只有**协议自相矛盾**才拒绝，例如：

```text
pending recheck
+ clear without completion
+ business call
```

---

# 12. 新 decision_delta 示例

普通 set：

```json
{
  "decision_delta": {
    "op": "set",
    "proposition": "If approval arrives now, use 4°C.",
    "action_scope": {
      "subject": "current_user",
      "item": "crate:Lumen-42",
      "action_type": "record_holding_instruction",
      "critical_parameters": ["temperature_celsius"]
    },
    "adopted_evidence": [
      {
        "ref": "e1",
        "support_role": "supports_value"
      }
    ],
    "unresolved_gap": null,
    "status": "active",
    "recheck_outcome": null
  },
  "calls": []
}
```

revision changed 后：

```json
{
  "decision_delta": {
    "op": "set",
    "proposition": "If approval arrives now, use 8°C.",
    "action_scope": {
      "subject": "current_user",
      "item": "crate:Lumen-42",
      "action_type": "record_holding_instruction",
      "critical_parameters": ["temperature_celsius"]
    },
    "adopted_evidence": [
      {
        "ref": "e2",
        "support_role": "supports_value"
      }
    ],
    "unresolved_gap": null,
    "status": "active",
    "recheck_outcome": "changed"
  },
  "answer": "..."
}
```

仍只支持：

```text
null
set
clear
```

不新增 patch/ack/change 等 operation。

---

# 13. Recheck 投影文本

建议保持紧凑但明确：

```text
Recheck required:
- Your current proposition adopted c0 = memory:X@1.
- The current stored revision is memory:X@2.
- The old proposition has NOT been validated against X@2.
- A version change does not by itself prove the proposition false.
- Complete the recheck as retained, changed, or unresolved.
```

不把 X@2 正文自动注入。

---

# 14. v18 默认不自动读取 Current Revision Body

若：

```text
X@1 → X@2
```

程序只投影变更事实。

普通 LangMem search/read 能力继续存在，但程序不自动调用。

v18 要测试：

> 更清楚的 proposition + completion contract 是否足以让 Host 在正常 ReAct 中主动取得并使用当前 evidence。

如果仍不读：

> 这是机制失败信号。

不要在本轮自动补 search。

---

# 15. New Observation 处理不变

新 Observation 继续进入普通 Agent request。

程序不通过：

- entity overlap；
- embedding similarity；
- scope overlap；

自动制造 semantic invalidation。

v18 的确定性 recheck trigger 仍只基于：

```text
adopted exact memory revision changed
```

---

# 16. Memory 与 Decision 继续解耦

```text
memory X@1 → X@2
```

程序：

```text
Decision needs recheck
```

但不能：

```text
rewrite proposition
```

Host 才能给：

```text
retained
changed
unresolved
```

---

# 17. 实现位置

继续使用：

```text
src/milai_lab/methods/milai_m1/
```

建议最小修改：

```text
decision_basis.py
  proposition
  action_scope
  support_role
  recheck_outcome

controller.py
  protocol wording
  pending-recheck consistency

recheck.py
  completion validation
  acknowledgement

evidence_view.py
  current revision handles
  support-role binding

state_store.py
  persistence/replay
```

如有必要新增：

```text
recheck_contract.py
```

默认不修改：

```text
state_attention.py
old contextual decision_basis.py
contextual_host.py
contextual_maintenance.py
```

---

# 18. Work Package A：冻结 v17 负结果

锁定：

- commit `9438d13`
- v17 source mapping
- final freeze
- mechanism diagnostic
- diagnostic `5/12`
- MERIT `4/5`
- controlled stale `4°C`
- adoption `22/22`
- v17 101 generations / 101810 tokens
- 916 embedding tokens
- R1 schema failures
- R2 protocol-clean result

Gate：

```text
No v17 result rewritten.
No favorable result splicing.
No rerun for publication.
```

---

# 19. Work Package B：Proposition Schema

实现：

```text
proposition
action_scope
```

替换过松的：

```text
decision
scope
```

零模型测试覆盖：

- empty proposition reject；
- action_type 结构合法；
- critical_parameters 合法；
- old v17 persisted state 不 silent reinterpret；
- decoder schema 可表达。

不需要把旧 v17 state 自动迁移到 v18。

---

# 20. Work Package C：Support Role

每个 adopted ref：

```text
ref
support_role
```

Gate：

- ref 仍必须 delivered / legally continued；
- role 不改变 evidence body；
- role 不推导 source provenance；
- UNKNOWN_NOT_DECLARED 仍合法。

---

# 21. Work Package D：Recheck Outcome

实现：

```text
null
retained
changed
unresolved
```

规则：

### 无 pending recheck

```text
recheck_outcome = null
```

### 有 pending recheck

允许：

```text
set + retained
set + changed
set + unresolved
clear + completed outcome + legal clear reason
```

拒绝：

```text
clear + no outcome
set + null
retained using only superseded evidence
changed with no current/new delivered evidence
```

---

# 22. Work Package E：Recheck Acknowledgement

只有合法完成后才 ack。

记录：

```text
triggered_at
projected_requests
completed_at
outcome
new_adopted_refs
```

不能因为：

```text
Basis touched
Basis cleared
new label written
```

而自动 ack。

---

# 23. Work Package F：同响应执行边界

顺序：

```text
1. parse generation
2. validate decision_delta
3. validate recheck completion consistency
4. if invalid:
      execute no tool calls
      return protocol error
5. if valid:
      commit state delta
      execute calls in original order
```

继续保持：

```text
invalid state protocol -> zero side effect
```

---

# 24. Work Package G：恢复与重放

必须验证：

- pending recheck restart 后仍存在；
- completed recheck 不重复 ack；
- completed turn replay 不重复 state transition；
- old exact revision 不 auto-rebind；
- business journal 不重复 side effect；
- B1 instrumentation 与 Decision store 相互独立。

---

# 25. V0：确定性测试

不调用真实模型。

至少覆盖：

### Proposition

- valid proposition；
- action_scope；
- support roles；
- active/deferred；
- unresolved gap。

### Recheck

- X@1 → X@2；
- retained with X@2；
- changed with X@2；
- unresolved；
- retained with only X@1 rejected；
- clear with pending recheck rejected；
- clear after completed recheck allowed；
- unrelated revision no trigger；
- tombstone path。

### Replay

- restart；
- duplicate request；
- duplicate set；
- duplicate completion；
- no duplicate business action。

### Transport

- set + calls；
- set + answer；
- invalid completion → zero tool execution；
- current JSON schema / xgrammar compatibility。

---

# 26. V1：Decoder Probe

只有 schema 变化确实需要时运行。

验证现有 vLLM 设置可生成：

```text
null
normal set
recheck changed
recheck retained
recheck unresolved
clear
```

不修改 parser，不开 thinking。

若 schema 不稳定：

> 简化 schema，不改服务。

---

# 27. V2：Controlled Changed-Recheck Diagnostic

继续使用已暴露的：

```text
4°C → 8°C
```

但创建新的 v18 fixture identity / freeze。

这是 development diagnostic，不是 benchmark。

成功必须完整观察：

```text
X@1 adopted
→ X@2 revision_changed
→ recheck projected
→ Host obtains current evidence
→ proposition becomes 8°C
→ recheck_outcome = changed
→ X@2 adopted as supports_value
→ approved business action uses 8°C
```

只有全部满足才算：

```text
RECHECK_COMPLETED_CORRECT_ACTION
```

以下都不能算成功：

- trigger 了但没有取得 current evidence；
- proposition 变了但 action 仍 4°C；
- action 8°C 但 state 仍 4°C；
- clear before completion；
- 自动 search；
- hard-block 4°C；
- 第二 reflection call 修复；
- 利用 rubric/gold 进入模型。

---

# 28. V3：两个控制例

## Control A：Irrelevant revision

```text
Decision adopts X@1 for temperature.
Unrelated Y@1 → Y@2.
```

要求：

```text
no recheck
```

## Control B：Relevant revision but proposition stays valid

例如：

```text
X@1 = hold at 8°C; note A
X@2 = hold at 8°C; note B
```

程序仍触发 recheck。

Host 应：

```text
recheck_outcome = retained
```

并采用 current revision/current evidence。

目的：

> 防止系统学成“version changed → decision must change”。

---

# 29. V4：原 12-case exposed diagnostic

只有 V2/V3 通过才运行。

主要检查：

- proposition quality；
- label-like Basis rate；
- non-intervention；
- support-role distribution；
- 是否发生自然 recheck；
- semantic score 是否继续明显退化。

`5/12 → 更高` 只能算 development signal，不是方法效果。

---

# 30. V5：exposed MERIT arc0

只有前序机制不退化才运行。

观察：

- refund proposition 是否具体；
- amount 是否有 `supports_value` evidence；
- empty search 后是否仍会凭空生成 amount；
- 是否保留 unresolved state；
- 6595 后 decision lifecycle 如何结束；
- 是否出现自然 memory revision/recheck。

即使 native 变成 `5/5`，仍不是 formal 方法证据。

---

# 31. 未见数据继续保护

v18 默认：

```text
MERIT seeds 3/4 = NOT_RUN
fresh MemSyco = NOT_RUN
StateMemBench = NOT_RUN
```

不为 M1 pivot 消耗 holdout。

---

# 32. v18 核心指标

## Proposition Quality

```text
valid action-sensitive propositions / active Basis
```

人工冻结 rubric：

> Does the proposition state a concrete current judgment whose alternative could change a meaningful action?

## Label-Like Basis Rate

```text
label_like / active Basis
```

目标是明显低于 v17。

## Action-Critical Grounding Coverage

有 `critical_parameters` 的 Basis 中，是否存在 Host 声明：

```text
support_role = supports_value
```

这是 declared grounding，不是程序真值验证。

## Recheck Completion Rate

```text
completed rechecks / triggered rechecks
```

拆分：

```text
retained
changed
unresolved
```

## Correct Recheck Action

controlled diagnostic 中：

```text
post-recheck business action parameter
```

是否符合 frozen current evidence。

## Non-Intervention

不需要 proposition 时：

```text
decision_delta = null
```

## Extra Calls

```text
independent State calls = 0
reflection calls = 0
```

---

# 33. 成本指标

必须单列：

```text
Decision Context input tokens
decision_delta output tokens
recheck completion tokens
extra generations
Decision SQLite bytes
Decision write transactions
```

与 v17 controlled diagnostic / exposed diagnostic / arc0 同口径比较。

---

# 34. v18 GO / PIVOT / KILL

| 结果 | 决策 |
|---|---|
| 4→8 changed 成功，same-value retained 成功，irrelevant 不触发，无额外 call | **GO：M1' 成立，可讨论 M2** |
| proposition 改善，但 Host 仍不执行 recheck | **PIVOT：recheck execution/control 是独立问题** |
| outcome 形式正确但 action 仍旧值 | **KILL 当前 M1 控制主张** |
| 必须自动 search 才正确 | **PIVOT → retrieval control；不称 M1 成功** |
| 必须 hard-block action 才正确 | **PIVOT → evidence-gated action safety** |
| 必须第二 LLM/reviewer | **PIVOT → verifier/reviewer** |
| label-like State 仍占主导 | **KILL proposition representation** |
| exposed diagnostic 继续严重退化 | **STOP before holdout** |

---

# 35. 严格 Kill Criterion

如果受控 `4°C → 8°C` 在新协议下仍满足：

```text
revision_changed delivered
+
normal LLM request
+
ordinary tools can obtain current evidence
+
no extra-call / no hard gate
```

但最终仍：

```text
stale 4°C action
```

则：

> **停止当前 Decision Basis + Selective Recheck 主线。**

不要继续：

- 加更多 State 字段；
- 加 Attention 来“救” M1；
- 增加 prompt 长度；
- 加第二 reviewer；
- 修改 benchmark；
- 针对温度或金额写规则。

此时重新选择研究方向：

```text
retrieval control
evidence-gated action
on-demand state reconstruction
```

---

# 36. M2 重新准入条件

只有全部满足才允许进入 M2：

1. proposition quality 合格；
2. changed recheck `4→8` 成功；
3. irrelevant revision 不触发；
4. same-value revision 正确 retained；
5. clear 不再绕过 pending recheck；
6. 没有独立额外 generation；
7. non-intervention 没明显退化；
8. exposed tasks 没出现严重新语义损害。

---

# 37. 若 M1' 成功，M2 只新增什么

M2 唯一新增：

```text
unresolved_gap
→ gap-directed retrieval
→ candidate expansion
→ stop/defer
```

M2 不重新修改：

- proposition；
- adoption；
- revision；
- recheck completion。

未来主消融：

```text
B1
vs
M1'
vs
M2
```

---

# 38. 文件组织建议

```text
MiLAi-Lab/
  src/milai_lab/methods/milai_m1/
    decision_basis.py
    evidence_view.py
    controller.py
    recheck.py
    state_store.py
    recheck_contract.py      # optional

  configs/
    milai-m1-v18.json

  data/fixtures/
    milai_m1_v18_recheck_changed.json
    milai_m1_v18_recheck_retained.json
    milai_m1_v18_irrelevant_revision.json

  data/locks/
    milai-m1-v18.lock.json

  tests/unit/
    test_milai_m1_v18.py

  tools/
    run_milai_m1_v18.py
    inspect_milai_m1_v18.py

  docs/
    MILA_LANGMEM_M1_PIVOT_GOAL_v18.md
```

尽量参数化已有 v17 runner，不新增第二套完整 runner。

---

# 39. 里程碑

| Milestone | 内容 | Real Model |
|---|---|---:|
| M0 | 冻结 v17 负结果 | 0 |
| M1 | Proposition / ActionScope schema | 0 |
| M2 | SupportRole | 0 |
| M3 | RecheckOutcome contract | 0 |
| M4 | deterministic tests | 0 |
| M5 | decoder probe | minimal |
| M6 | controlled changed-recheck 4→8 | small |
| M7 | retained / irrelevant controls | small |
| M8 | exposed 12-case diagnostic | conditional |
| M9 | exposed MERIT arc0 | conditional |
| M10 | GO / PIVOT / KILL | 0 |

---

# 40. 建议终态

核心机制成立：

```text
COMPLETE_WITH_M1_RECHECK_COMPLETION
```

proposition 改善但重核仍失败：

```text
COMPLETE_WITH_RECHECK_EXECUTION_FAILURE
```

核心机制仍不成立：

```text
STOPPED_M1_RECHECK_NOT_JUSTIFIED
```

不要使用：

```text
M1_EFFECTIVE
MILAI_IMPROVED
M2_READY
```

除非对应 gate 实际满足。

---

# 41. 冻结原则

```text
Recheck Triggered != Recheck Completed
```

```text
Valid Adoption != Sufficient Grounding
```

```text
Decision State != Topic Label
```

```text
Version Changed != Decision Must Change
```

```text
Clear State != Recheck Success
```

---

# 42. v18 最终目标

v18 是当前 Decision Basis 主线的关键判定阶段，而不是“再修一个版本”。

目标链：

```text
exact current evidence
        ↓
concrete action-sensitive proposition
        ↓
explicit adopted support
        ↓
adopted revision changes
        ↓
program recheck trigger
        ↓
Host explicitly completes recheck
        ↓
retained / changed / unresolved
        ↓
subsequent action consistent with completed judgment
```

如果这条链能在正常 ReAct、同一次 generation 协议、无额外 reviewer、无 hard-coded action guard 的条件下完成，那么：

> **M1 才真正从“可追踪状态”升级为“可工作的 selective recheck mechanism”。**

此后才值得研究 M2 State–Attention。

如果这条链仍失败，则应接受：

> **显式 Decision Basis + revision notification 本身不足以驱动可靠重核。**

并停止继续给该机制叠加 Attention。
