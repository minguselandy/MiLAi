---
title: MiLAi 后续开发规划 v5.0：先修评价合同，再修真实的 Memory-to-Action 消费问题
date: 2026-09-28
status: DRAFT_PLAN_NOT_EXECUTED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_report_commit: 676fe4d32005cefbfb01daa4fe24425edf5a5e21
baseline_method_commit: 24ef49945cd12eccbd85792fee3c256bf3fe6d2a
baseline_pr: 67
baseline_fast_ci: success
baseline_full_ci: skipped
goal_status: PAUSED
research_goal: NOT_ACHIEVED
product_status: NO_GO
execution_authorization: NOT_STARTED
---

# MiLAi 后续开发规划 v5.0

## 0. 规划目的

本计划承接 v4 的工程收敛结果，但**不继续沿“失败一个样本 → 修改一段提示 → 再跑同一批样本”的循环开发**。

v4 已完成：

- Event / Source、Durable Memory、Working State、Business World 的工程边界；
- strict CRUD 与 exact read；
- 真实 ToolMessage / operation audit；
- 去除默认模型自证 `receipt_refs`；
- Working State 的临时范围；
- 小 bank 默认 `all`，不强制启动 State–Attention；
- 两轮完整暴露回归，各 5/6；
- Fast CI 通过。

但是 v4 的 R2 暴露出一个更基础的问题：**评分合同本身与用户显式任务要求并不完全对齐。**

R2 `field_plan` 的实际用户问题是：

> “What is my current sample-delivery plan, including quantity, destination and packing? Do not book anything.”

实际回答正确给出：

- quantity；
- destination；
- packing。

离线 rubric 另外要求：

> “accurately states all plan fields”

并因为未再次复述 `Harbor sampler trays` 将其判为完整 later-use 失败。

因此：

> **旧 R2 的 5/6 必须原样保留，因为这是预先冻结 rubric 下的真实结果；但不能把这一个失败直接升级成“模型已经证明存在 Memory 消费不完整 bug”。**

当前至少存在两种竞争解释：

1. Host 确实应该把“current sample-delivery plan”理解为完整计划，即使用户只点名三个字段；
2. 离线 rubric 对用户可见请求施加了额外的隐藏完整性要求。

在区分这两个解释前继续修改模型输入、Working State 或 answer schema，会再次出现“为了评分器修模型”的风险。

所以 v5 的第一原则是：

> **先修评价合同，使失败定义只来自用户可见任务和事前声明的 Memory 生命周期要求；然后在新的、前瞻冻结的小样本上验证当前 v4 方法。只有真实失败再次出现，才修改 runtime。**

这不是降低验收标准，而是让“什么算失败”本身可证伪、可复现、对模型公平。

---

# 1. 当前冻结基线

## 1.1 Git / PR 身份

| 项 | 当前身份 |
| --- | --- |
| v4 总报告提交 | `676fe4d32005cefbfb01daa4fe24425edf5a5e21` |
| v4 R2 方法提交 | `24ef49945cd12eccbd85792fee3c256bf3fe6d2a` |
| PR | `#67`，Draft / Open / 未合并 |
| Fast CI | success |
| Full composition | skipped |
| Product | NO-GO |
| Goal | PAUSED |

本计划不修改以上历史身份。

## 1.2 连续成本起点

```text
generation calls  = 2,994
generation tokens = 3,785,491
embedding tokens  = 21,237
```

终点账本 SHA：

```text
e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668
```

任何后续真实调用继续累计，不清零。

---

# 2. v4 应该怎样重新解释

## 2.1 已经有较强证据的能力

在同一组暴露脚本中，R1/R2 都完成：

| 能力 | 结果 |
| --- | ---: |
| 新事项形成 | 5/5 |
| 修订并保持无关内容 | 1/1 |
| 引用 / 临时 / read-only 范围 | 3/3 |
| 无假 saved | 通过 |
| 无重复事项 | 通过 |
| 无多余业务动作 | 通过 |
| 控制调用 | 0 |
| selector 调用 | 0 |

因此当前不应重新开发：

- 新 Memory writer；
- 新 State store；
- 新 revision engine；
- 新 correction loop；
- 新 A/U selector。

## 2.2 R1 是明确的当前任务消费失败

R1 `temporary`：

- 当前 user request 明确要求回复以 `BRIEF` 开头；
- 当时 memory 为空；
- 无业务 tool；
- 当前 user message 实际进入 HTTP；
- 输出没有 `BRIEF`。

这是真实的：

```text
explicit current-turn requirement
        ↓ delivered
Host
        ↓
requirement omitted
```

属于当前任务执行/回答合同问题。

## 2.3 R2 field_plan 不是同等强度的证据

R2 后续请求明确点名：

- quantity；
- destination；
- packing。

回答三项全部正确。

未复述 item identity 的失败来自离线 rubric 的 `all plan fields`。

因此 R2 应同时保留三个口径：

```text
frozen legacy strict score = fail
explicit current-message obligations = pass
full-record reproduction = incomplete
```

三个口径不能互相覆盖。

## 2.4 当前真正未解决的问题

当前问题不是“Memory 又不会用了”，而是需要区分：

1. **Current-task explicit compliance**
   - 用户明确要求的内容有没有执行？

2. **Persistent-memory correctness**
   - 该保存的是否保存？
   - 该更新的是否更新？
   - 无关内容是否保持？

3. **Memory reuse**
   - 新 session 中，用户实际问到的内容是否正确回答？

4. **Full-record completeness**
   - 如果用户明确要求“完整计划”，是否完整复述？

5. **Optional contextual completeness**
   - 用户只问部分字段时，是否还必须补充未点名字段？
   - 这不应由隐藏 rubric 自动决定。

---

# 3. v5 的核心目标

v5 不创建新的 Memory 方法。

目标是把当前 v4 方法继续作为唯一候选，解决两个基础问题：

## G1：建立正确的评价合同

做到：

> 用户明确要求什么，就明确验收什么。

以及：

> Memory 生命周期需要什么，就独立验收什么。

不把 scorer 的额外偏好混入当前任务正确性。

## G2：验证“正确 Memory → 当前任务”的真实消费稳定性

用新的、未参与 v3/v4 调试的前瞻小样本，明确写出所有被评分的当前任务要求。

只有在这种条件下发生遗漏，才认定为真正的 consumption failure。

---

# 4. 明确不改变的架构

v5 默认保留 v4 R2 的以下运行语义：

```text
Event / Source
Durable Memory
Working State
Business World
```

保留：

- strict create/update/delete/no_change；
- exact memory read；
- ordinary durable memory；
- current-task / source role 投影；
- program audit；
- real ToolMessage；
- all-first retrieval；
- Retained history contract；
- 无 C correction；
- 无 State–Attention selector；
- 无 Judge。

**第一阶段不修改 runtime。**

---

# 5. 工作包总览

| 工作包 | 目标 | 是否允许模型调用 |
| --- | --- | --- |
| V0 | 冻结 v4 与重新分类失败 | 否 |
| V1 | 重构 evaluator 合同 | 否 |
| V2 | 对冻结 HTTP 做消费链离线分析 | 否 |
| V3 | 减少已测得的输入冗余，但不改语义 | 否，先离线 |
| V4 | 创建新的前瞻小样本 | 否 |
| V5 | 当前 v4 方法一次性新样本验证 | 是 |
| V6 | 仅对真实失败做单问题修复 | 条件触发 |
| V7 | 动态世界 / assistant conflict 验证 | 条件触发 |
| V8 | State–Attention 重新准入 | 条件触发 |
| V9 | 最终研究判断 | 否 |

---

# 6. V0：冻结 v4 证据与失败分类

## 6.1 不改旧结果

必须原样保留：

```text
R1 legacy strict = 5/6
R2 legacy strict = 5/6
```

不得事后把 R2 改成 6/6。

## 6.2 增加“解释层”，不是改分

离线新增一份分析 manifest：

```text
next-development-v5-v4-reinterpretation.json
```

建议字段：

```json
{
  "case_id": "field_plan",
  "legacy_score": "fail",
  "explicit_current_obligations": {
    "quantity": "pass",
    "destination": "pass",
    "packing": "pass",
    "no_business_action": "pass"
  },
  "persistent_memory": {
    "formation": "pass",
    "record_complete": "pass"
  },
  "full_record_reproduction": "incomplete",
  "interpretation": "legacy rubric expects more than explicitly enumerated fields"
}
```

这不是重新打分，只是把失败来源拆开。

## 6.3 R1 temporary

记录：

```text
explicit_current_obligation = fail
persistent_scope = pass
later_non_leakage = pass
```

这样避免把：

> “本轮格式没做到”

误写成：

> “临时 Memory 设计失败”。

## 6.4 验收

- 六脚本都有 obligation decomposition；
- 不读取新的模型输出；
- 不修改旧 rubric；
- legacy / explicit / memory / optional 四种口径分开。

---

# 7. V1：修评价合同

## 7.1 新 rubric 必须区分四层

以后每个 case 的 rubric 至少包含：

```text
A. current_explicit_obligations
B. persistent_memory_obligations
C. later_use_obligations
D. optional_or_diagnostic_completeness
```

### A. Current explicit obligations

直接来自当前 user message。

例如：

```text
reply starts with BRIEF
do not book
state quantity
state destination
state packing
```

### B. Persistent-memory obligations

来自明确的长期请求：

```text
save ongoing plan
preserve unrelated details
do not save temporary format
```

### C. Later-use obligations

新 session 当前请求明确要求什么。

### D. Diagnostic completeness

例如：

```text
did the answer also mention item identity?
did it mention booking status?
```

如果用户没有明确要求，这些指标可以记录，但不能自动作为 task failure。

## 7.2 “完整”必须由用户可见请求定义

若希望检查完整计划，测试输入应明确写：

> “Tell me the complete plan, including item, quantity, destination, packing and booking status.”

而不是：

> 用户只点三个字段，但 scorer 在后台要求五个字段。

## 7.3 不将 rubric 送入 runtime

仍然保持：

```text
runtime_must_not_read = true
```

## 7.4 不自动从 user 文本抽取 obligation

第一阶段不新增 LLM evaluator 或 parser。

开发者在冻结 input 时同时人工声明 evaluator obligations。

这是测试协议，不是 Agent runtime。

## 7.5 交叉审查

冻结前检查：

- 每一个 task-failing obligation 是否能指向 user-visible 文字；
- 每一个持久化 obligation 是否能指向明确长期请求；
- 不能支持的要求降为 diagnostic。

---

# 8. V2：Memory-to-Action 消费链离线分析

## 8.1 目标

不用新模型调用，回答：

> 在已经失败的轨迹中，到底是哪一层开始丢信息？

## 8.2 对每个 obligation 建链

```text
obligation
    ↓
present_in_user_request
    ↓
required_memory
    ↓
memory_formed
    ↓
memory_delivered
    ↓
answer_contains
```

工具任务额外加入：

```text
tool_argument_contains
world_effect_correct
```

## 8.3 示例：R1 BRIEF

```text
present_in_user_request = yes
requires_memory = no
memory_delivered = n/a
answer_contains = no
```

归类：

```text
current-task consumption failure
```

## 8.4 示例：R2 field_plan

```text
quantity:
  request yes
  memory yes
  delivered yes
  answer yes

destination:
  yes / yes / yes / yes

packing:
  yes / yes / yes / yes

item_identity:
  request_explicit = no
  memory = yes
  delivered = yes
  answer = no
```

不能与前三项同类归因。

## 8.5 建议新增离线工具

可新增：

```text
analysis/obligation_trace.py
```

仅做：

- 读取冻结结果；
- 组合 rubric 分项；
- 输出链路表。

禁止：

- 用 LLM 判断答案；
- 修改任务分；
- 自动推导隐藏 requirement。

---

# 9. V3：先分析 v4 多出的 40%–45% 输入成本

v4 调用数与旧 B0 一样，但 tokens 增约 40%–45%。

这说明开销来自输入表达，而不是额外 controller。

## 9.1 先离线拆请求

从冻结 HTTP 中统计：

```text
system base
memory responsibility / boundary text
current-task wrapper
ordinary-memory view
authority labels
source/event metadata
tool schemas
checkpoint transcript
current user
```

## 9.2 必须回答

- 哪部分增长最大？
- 哪部分在每次模型调用中重复？
- 哪部分只是 audit 信息，而 Host 实际不需要？
- 哪部分只对 memory write 有用，但 read-only turn 仍重复交付？

## 9.3 允许删除的内容

只有确定性冗余，例如：

- 程序已经知道、模型不需要重复判断的 audit 字段；
- 相同说明在一个请求内重复；
- 空列表 / 空状态的冗余包装；
- read-only turn 中与当前工具能力无关的机械细节。

## 9.4 禁止删除

- current user request；
- actual durable memory content；
- message/source role；
- current vs historical 区分；
- strict CRUD 行为约束；
- tool actual result；
- owner/scope 必需信息。

## 9.5 第一阶段零模型

只离线生成：

```text
old_request_tokens
candidate_request_tokens
delta_by_component
semantic_fields_preserved
```

只有确认不改变信息合同后才进入模型验证。

---

# 10. V4：建立新的前瞻验证集

## 10.1 为什么必须新建

v3/v4 六脚本已经反复暴露。

继续使用它们只能做 regression，不能支持稳定性判断。

## 10.2 数量

建议：

```text
8–10 个脚本
每脚本 2–4 个 session
```

规模足够区分问题，不做大 benchmark。

## 10.3 类别

### Case A：完整计划复用

第一 session：

> 保存 item、quantity、destination、packing、booking state。

第二 session 明确要求：

> “Give me the complete current plan: item, quantity, destination, packing, and booking status.”

所有评分字段直接出现在 user request。

### Case B：部分字段复用

同样保存完整计划。

第二 session 只问：

> “What quantity and packing did I specify?”

只评分 quantity / packing。

其他字段记录为 optional completeness，不能判 task fail。

### Case C：当前临时格式

明确：

> “For this reply only, start with NOTE: ...”

下一新 session 不应继续。

### Case D：独立事项更新

两个可独立改变的事项。

更新 A，不改变 B。

### Case E：引用内容非采纳

用户引用第三方要求。

不得形成用户自己的长期偏好。

### Case F：read-only

已有持久记忆。

连续两次只读，不应写新记录。

### Case G：明确删除

先真实形成 note，再请求删除该 note。

必须真实 DELETE，其他事项保持。

### Case H：assistant-history 冲突

历史 assistant 曾说旧值。

durable memory 后来有正确新值。

新问题明确询问当前值。

### Case I：dynamic world

Memory 中保存长期计划。

真实 business state 后来改变。

当前问题要求实际状态。

必须依赖业务工具，不以 stale memory 替代。

### Case J：moderate bank

多个真实独立事项，但仍能全部放入预算。

验证普通 all/query 足够，不强制 Attention。

## 10.4 冻结原则

在真实运行前冻结：

- user messages；
- obligations；
- expected Store changes；
- business world；
- allowed tools；
- execution order；
- scorer；
- cost start。

不得看结果后修改 task failure 条件。

---

# 11. V5：当前 v4 方法的新样本验证

## 11.1 方法

首先只运行一个方法：

```text
v4 R2 current B
```

不设 B0/B1/C 多臂矩阵。

原因：

> 当前目标是判断已经实现的方法是否真正稳定，而不是找哪个候选分数最高。

## 11.2 不改代码

V4 新输入冻结后，先直接执行现有方法。

## 11.3 通过门槛

核心 gate：

```text
explicit current obligations >= 95%
persistent requested changes = all correct in this small set
no false persistence
no false save claim
no duplicate business action
no hidden-rubric-only task failure
```

小样本不做统计显著性主张。

如果出现一个失败：

- 保留失败；
- 先分类；
- 只在明确首断点后决定是否修代码。

## 11.4 失败分类

```text
INPUT_MISSING
MEMORY_FORMATION
MEMORY_TARGET
MEMORY_DELIVERY
CURRENT_TASK_CONSUMPTION
ANSWER_COMPLETENESS
TOOL_ARGUMENT
WORLD_STATE
EVALUATION_CONTRACT
```

同一轨迹可以有多个问题，但必须确定 earliest breakpoint。

---

# 12. V6：只对真实失败做单问题修复

本阶段不是预定执行；由 V5 结果触发。

## 12.1 如果 current explicit constraint 仍遗漏

例如新的 NOTE/BRIEF 类任务仍失败：

先检查：

1. 当前 user message 是否最后进入 HTTP；
2. answer schema 是否改变用户可见文本表达；
3. tool loop 续接后 current request 是否仍可见；
4. 是否是工具结果/记忆材料挤占上下文。

### 允许的最小修复

优先修：

```text
final answer envelope / rendering contract
```

而不是增加：

- 新 State writer；
- second-pass reviewer；
- self-check LLM；
- requirement classifier。

### 验收

必须用：

- 旧暴露 regression；
- 至少两个新的 current-turn constraints。

否则不能认定通用修复。

## 12.2 如果明确要求的字段从完整 Memory 中被漏答

只有新的前瞻任务中，用户明确点名字段而模型仍漏答，才成立。

### 第一诊断

检查：

```text
field in user request?
field in durable memory?
field in delivered request?
field in final answer?
```

### 最小候选

允许研究一个**回答组织接口**，但禁止直接自动补答案。

候选必须满足：

- 不改 Memory；
- 不按 gold 填字段；
- 不新增额外模型 call；
- 不要求模型重复工具 receipt；
- 同一次 generation 内完成。

如果必须让模型输出一个 coverage/checklist 字段，则该字段：

- 只能是辅助诊断；
- 不能作为“模型说覆盖了”就自动算成功；
- 必须计入额外输出/输入负担；
- 需要与无 checklist 的同条件比较。

C 已证明“自报结果”可能增加负担，因此默认不采用。

---

# 13. V7：验证 v4 尚未真实覆盖的两个设计边界

v4 工程实现了边界，但真实语义测试尚未运行。

## 13.1 Dynamic world

问题：

> Durable Memory 中的长期计划与 live business state 冲突时，Host 是否知道谁是当前权威？

要求：

```text
memory = plan / last observation
business tool = current world state
```

不能：

```text
stale memory -> 当前世界真相
```

### 测试

- 保存计划；
- 执行业务变化；
- 保留一条旧历史描述；
- 新 session 问当前业务状态；
- 要求实际业务查询；
- 检查是否重复动作。

## 13.2 Assistant-history conflict

问题：

> 旧 assistant answer 是否覆盖当前用户/Memory 的新值？

测试：

```text
assistant old answer = 3
durable current memory = 4
current user asks current value
```

共同保留真实 transcript。

不删除 assistant history。

验收：

- 最终 current value；
- 是否使用正确来源；
- 不要求 State 再存一份 4。

---

# 14. V8：State–Attention 重新准入

只有以下条件之一真实出现：

1. bank 已不能在预算内 all；
2. ordinary query 漏掉必要事项；
3. 相似事项不同 scope 发生真实冲突；
4. 多个当前合法记录造成可观察的取材错误；
5. all/query 成本明显超过可接受范围。

否则：

```text
Attention NOT_TRIGGERED
```

是正确结果。

## 14.1 重新比较时

只比较：

```text
ordinary all/query
vs
working-state query
vs
lazy State-Attention
```

共同：

- 同 bank；
- 同 history；
- 同 user request；
- 同 model；
- 同 CRUD；
- 同 business world；
- 完整计入控制费用。

## 14.2 State 合同

仍保持：

```text
goal
turn constraints
active refs
open questions
```

不恢复：

```text
第二份 durable facts
```

---

# 15. 代码修改范围

## 15.1 第一阶段：只新增分析/评估代码

建议：

```text
src/milai_lab/analysis/obligation_trace.py
```

职责：

- 读离线 rubric；
- 读结果 manifest；
- 输出 obligation → delivered → answer 链；
- 不运行 LLM；
- 不修改任务结果。

## 15.2 rubric 数据

新 v5 inputs 对应 rubric 明确：

```json
{
  "current_explicit_obligations": [],
  "persistent_obligations": [],
  "later_use_obligations": [],
  "diagnostic_completeness": []
}
```

## 15.3 Runtime

V0–V5 之前：

```text
NO CHANGE
```

只有 V5 出现真实 failure，才进入 V6/V7 的最小 runtime 修改。

---

# 16. 成本纪律

## 16.1 当前优先级

v4 最大的新工程代价不是额外 calls，而是输入 tokens 增加。

因此优化顺序：

```text
request component profiling
→ deterministic redundancy removal
→ new sample validation
→ only then algorithmic selection
```

## 16.2 不允许的成本解释

- 少写 Memory 不能称压缩；
- 少 embedding 不能称更高效；
- selector 局部输入小不能忽略 selector call；
- full-history 短任务便宜不能外推长历史；
- 已暴露 regression 不能当部署平均成本。

## 16.3 后续报告

必须继续分：

```text
generation input
generation output
embedding
Store logical calls/bytes
business calls
control calls
process wall
HTTP wall
unknown
```

---

# 17. Go / Pivot / Stop

## GO：继续当前方法

满足：

1. 新前瞻样本的 explicit current obligations 稳定；
2. requested durable save/update/delete 正确；
3. read-only / quotation / temporary 不误持久化；
4. dynamic world 不被 stale memory 覆盖；
5. assistant history 不覆盖当前有效信息；
6. 无额外 controller calls；
7. 相比 v4，输入成本经确定性精简明显下降或至少不继续增加。

这时才能称：

> 当前基础 Agent Memory 已达到稳定研究底座。

## PIVOT：只修一个层次

### Evaluation mismatch

只改未来 evaluator，不改 runtime。

### Current-task omission

只修 answer/request interface。

### Memory formation

只修 write responsibility / matter boundary。

### World-state conflict

只修 Memory vs business authority。

### Retrieval bottleneck

才研究 Attention。

## STOP：停止当前复杂化

如果：

- 新样本 B 仍在不同地方随机约 1/10 左右遗漏；
- 每修一个输出约束就出现另一个输出遗漏；
- 需要越来越长的 system prompt 才维持 regression；
- 输入 tokens 持续上涨但任务质量不变；
- 只有隐藏 rubric 才能制造失败；
- Attention 在没有真实选择瓶颈时才显示“收益”。

此时应：

> 保留 simple ordinary memory，收缩论文方法主张，研究模型的 instruction/memory consumption 边界，而不是继续增加 Memory 架构。

---

# 18. 论文研究意义

v5 的价值不在于创造新模块，而在于回答一个非常基础、此前被多层机制掩盖的问题：

> **Agent Memory 的失败究竟发生在“没有正确记住”，还是“已经正确记住但当前任务没有完整使用”？**

这两个问题需要不同方法。

如果新的严格协议显示：

```text
Memory formation stable
Delivery stable
Explicit task obligations still unstable
```

那么论文不能继续把主要问题写成 Memory retrieval。

真正问题变成：

```text
memory-conditioned task execution
```

反之，如果新样本表明：

```text
显式义务稳定
但复杂更新仍丢记忆
```

才重新回到 Memory evolution。

---

# 19. 执行顺序

严格顺序：

```text
V0 evidence freeze
  ↓
V1 evaluator contract
  ↓
V2 offline obligation trace
  ↓
V3 request cost profiling
  ↓
V4 prospective inputs + rubric freeze
  ↓
V5 current method one-shot validation
  ↓
only if failure:
    V6 targeted consumption repair
    or
    V7 authority/world repair
  ↓
only if retrieval bottleneck:
    V8 State-Attention
  ↓
V9 final report
```

不得跳过 V1/V4 直接继续改 prompt。

---

# 20. 完成判据

## 20.1 Evaluation contract 完成

- task-failing requirement 均有 user-visible 依据；
- persistent requirement 均有明确长期意图依据；
- diagnostic completeness 不自动算 task failure；
- rubric 不进入 runtime。

## 20.2 基础 Agent Memory 稳定

在新的小样本中：

- save/update/delete；
- later-session reuse；
- temporary scope；
- quote attribution；
- read-only；
- dynamic world；
- assistant conflict；

均达到预先冻结要求。

## 20.3 State–Attention 研究重新开始

必须有真实 retrieval bottleneck。

否则保持关闭。

---

# 21. 最终原则

> **当前最重要的不是继续增强 Memory，而是保证“失败”本身定义正确。**

在这个前提下：

> **如果用户明确要求的内容已经进入模型，而模型仍然漏掉，才修消费层；如果持久内容没有正确形成，才修 Memory；如果当前世界与 Memory 冲突，才修权威边界；如果候选真的超预算，才启动 Attention。**

每个问题只在它真正发生的层次解决。

这比继续增加提示、State、selector 或 correction 更接近可验证、可复现、可泛化的 Agent Memory 研究。
