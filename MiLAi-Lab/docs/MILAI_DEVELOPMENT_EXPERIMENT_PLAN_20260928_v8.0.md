---
title: MiLAi 后续开发与实验规划 v8.0：从动作可靠性到长程 State–Attention 的完整收口
date: 2026-09-28
status: DRAFT_PLAN_NOT_EXECUTED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_report_commit: 77dfc2f43f2307bb649cdbee9d62a97e5863fac0
baseline_pr: 71
baseline_protocol: JSON-action / B0 / strict / retained / current_request / compact_v6
baseline_model: Qwen3.6-35B-A3B-FP8
baseline_embedding: bge-m3-1024
current_goal: V7_FIRST_SLICE_COMPLETE
long_horizon_research_goal: NOT_ACHIEVED
product_status: NO_GO
execution_authorization: NOT_STARTED
---

# MiLAi 后续开发与实验规划 v8.0

## 0. 文档目的

本计划的目标不是继续增加新的 Memory 机制，而是把当前尚未完成的研究问题按依赖关系逐项解决，并最终给出一个可以明确收口的结论：

> **MiLAi 的记忆系统是否能在真实 Agent 生命周期中，稳定完成“形成—修订—行动—回写—恢复—长程使用”，并且在普通强基线出现真实瓶颈时，State–Attention 是否有独立的质量／成本价值。**

v7 首批已经完成的内容不能重复作为“后续任务”：

- JSON-action 路径在六种合成意图结构、两个预定重复中完成 12/12 轨迹；
- 92/92 任务义务通过；
- 8 次 CREATE、2 次同 ID UPDATE、2 次 reserve-and-label、2 次 live lookup 实际执行；
- JSON/native 两协议的公共材料投影、容量检查、执行与 delivery 接线已工程统一；
- native 真实执行因为当前 vLLM 服务没有启用自动 tool parser，被明确标记为 `BLOCKED_ENVIRONMENT`；
- 没有新增 selector、correction、writer 或 reviewer；
- v7 结果不证明稳定 unseen、跨模型或 State–Attention 收益；
- Product 仍为 NO-GO。

因此，v8 必须从这些已经验证的基础继续，而不是回到旧问题重新开发。

---

# 1. v8 最终要回答的七个问题

## Q1：协议是否影响工具使用可靠性？

需要区分：

```text
JSON-action
vs
native tool calling
```

但必须保证：

- 相同合法材料；
- 相同 Memory；
- 相同工具能力；
- 相同 business world；
- 相同输出／容量约束；
- 相同执行器；
- 相同评分。

若 native 环境无法合法建立，则协议比较保持 `INCONCLUSIVE`，不把环境阻断算算法结果。

## Q2：模型为什么会漏掉明确记忆／业务动作？

v6 已真实出现：

```text
用户明确要求保存
→ Host 直接确认已保存
→ 无 CREATE
```

以及：

```text
用户明确要求查实际预约
→ Host 只搜索 Memory
→ 未调用业务查询
```

需要判断：

- 是协议表达问题；
- 是动作选择能力问题；
- 是工具目录负担；
- 是模型 reasoning 配置；
- 是当前任务／Memory 呈现竞争；
- 还是组合因素。

不能再把这些失败直接归因为 Memory Store。

## Q3：准确业务对象如何稳定进入工具参数？

v6 出现过：

```text
完整业务 key
→ Host 自行做词形变化
→ 实际工具参数错误
```

需要判断：

- 自由文本 key 是否本身就是脆弱接口；
- 对象引用是否能降低参数错误；
- 引用适配是否只是给候选增加额外能力；
- 任务中何时必须查询／消歧，而不是直接行动。

## Q4：明确记忆任务是否需要一个独立的同步维护子任务？

JSON direct 已经可以工作，但旧失败不能注销。

如果 direct 路径在更复杂任务中仍出现：

```text
零写入却确认保存
```

需要比较：

```text
Host direct memory tools
vs
bounded synchronous memory-maintenance subtask
```

重点不是“是否多一次调用”，而是：

```text
端到端质量 + 总生命周期成本
```

## Q5：真实 partial / unknown / recovery 是否可靠？

必须实际验证：

```text
intent persisted
→ external action
→ partial/unknown result
→ actual receipt
→ no duplicated successful side effect
→ memory/state maintenance
→ process reopen
→ correct continuation
```

## Q6：普通 Memory 在自然长程下何时出现真实瓶颈？

当前所有 v7 请求都走 `all`。

在没有真实检索压力前，不能讨论 Attention 优势。

需要自然积累：

```text
20–40 sessions
10–30 independent matters
multiple revisions
historical/current questions
business results
temporary constraints
```

先测：

```text
all
→ ordinary query
```

只有普通方法真实不足，才允许进入 Attention。

## Q7：State–Attention 是否有独立价值？

最终比较目标不是：

```text
有 State
vs
没 State
```

而是：

```text
相同 Memory bank
相同 CRUD
相同业务能力
相同 query / budget
相同模型
```

只改变：

```text
是否利用当前 State 构造／选择工作视图
```

必须同时看：

- task success；
- required information coverage；
- wrong-current / wrong-history；
- business action；
- lifecycle cost；
- total input tokens；
- control calls。

---

# 2. 当前冻结基线

## 2.1 Git 身份

| 项 | 当前值 |
| --- | --- |
| v7 总体报告 | `77dfc2f43f2307bb649cdbee9d62a97e5863fac0` |
| 实际 E1 运行源码／输入提交 | `2f30c14c5e7ea82db2b0a962d3636e14de5f2391` |
| v7 runtime/source A | `37d48577bdff582f74faf2f5e663b359885350ec` |
| PR | #71，Draft / Open / 未合并 |
| 上游 PR | #70，仍未合并 |
| Product | NO-GO |

执行 v8 前必须先只读核对远端实际 SHA，不允许用本文写死的旧状态冒充最新状态。

## 2.2 连续账本起点

```text
generation calls  = 3,301
generation tokens = 4,205,203
embedding tokens  = 23,570
```

v7 新增：

```text
38 generation calls
49,456 generation tokens
10 embedding calls
294 embedding tokens
```

任何 v8 实际模型调用继续追加原权威账本，不清零。

---

# 3. 架构原则

## 3.1 保留成熟底座

继续复用：

- LangGraph ReAct；
- LangMem ordinary memory tools；
- strict CRUD wrapper；
- exact memory read；
- Postgres Store；
- SQLite checkpoint / application world；
- RequestContext / Renderer / Router；
- operation audit；
- obligation evaluator；
- continuous accounting。

不因为研究问题变化而重写基础运行时。

## 3.2 一个逻辑 MemoryService

无论是 direct Host、synchronous maintenance subtask 还是 State–Attention，都必须使用同一个 MemoryService：

- 同一 namespace；
- 同一 strict CRUD；
- 同一 record IDs；
- 同一 Store；
- 同一 exact target semantics；
- 同一 search/read；
- 同一 audit。

禁止出现多个 writer 独立维护同一 durable truth。

## 3.3 Working State 可以保存有依据的工作事实

允许：

```text
goal
current constraints
active matters
current working values
open questions
pending actions
recent actual receipts
```

但每个值必须知道：

```text
来源
scope
是否临时
是否需要刷新
```

State 不是第二套独立 durable store。

## 3.4 Business World 独立于 Durable Memory

Durable Memory 可以保存计划、偏好、历史业务观察、已执行事件和最后已知状态。

但是当前业务状态是否仍然成立，由实际可用业务查询或足够新鲜的真实回执决定。

## 3.5 程序负责执行事实，模型负责语义决定

程序负责：

```text
真实对象 ID
工具是否调用
参数是什么
返回什么
Store 是否变化
世界是否变化
当前 namespace / owner
receipt / version
```

模型负责：

```text
什么值得保存
是不是同一事项
当前任务需要什么
什么时候应查询
如何解释 actual result
如何回答
```

---

# 4. 总体阶段图

```text
D0 现场与身份冻结
 ↓
D1 native 合法环境/协议可比性
 ↓
E1 JSON vs native / thinking 诊断
 ↓
D2 精确对象引用与业务参数接口
 ↓
E2 对象参数可靠性
 ↓
D3 可选同步 Memory 子任务
 ↓
E3 direct vs maintenance-subtask
 ↓
E4 partial / unknown / recovery lifecycle
 ↓
C1 基础稳定门槛
 ↓
D4 natural long-horizon workload
 ↓
E5 all vs ordinary query
 ↓
only if real bottleneck
D5 State-Attention
 ↓
E6 query vs working-state vs attention
 ↓
M1 second-model confirmation
 ↓
R1 final research report / paper decision
```

不是所有阶段都自动执行。每个阶段有独立 gate。

---

# 5. D0：现场、身份与失败冻结

开始任何开发前，固定：

- 当前 PR / branch / HEAD；
- v7 report；
- actual runtime commit；
- model service；
- tokenizer/template；
- vLLM flags；
- embedding service；
- continuous ledger；
- v6/v7 真实失败链。

必须保留：

1. 零 CREATE 假保存；
2. exact-key 改写；
3. 明确 live lookup 遗漏；
4. partial 未激活；
5. current/history presentation 冲突；
6. compact/full 首响应不稳定。

产物：

```text
docs/MILAI_V8_D0_BASELINE_20260928.md
data/manifests/v8-d0-baseline.json
```

模型调用：0。

---

# 6. D1：建立合法 native 对照环境

## 6.1 当前阻断

现部署：

```text
vLLM 0.27.1
未开启 --enable-auto-tool-choice
未配置 tool-call-parser
```

所以 native E1 未运行。

## 6.2 原则

不能直接修改当前共享服务并把前后结果混在一起。

允许：

### 方案 A：隔离新服务

使用相同：

- model weights；
- tokenizer；
- template；
- context；
- dtype；
- temperature；
- output limit；

只增加 native tool parsing 所需 flags。

### 方案 B：现服务合法支持显式 named/required tool choice

若实际 API 能合法执行 native call，则另冻协议。

必须确认：

- provider 真正返回 `tool_calls`；
- 客户端没有伪造；
- final text 不会被误解析成 call。

## 6.3 不允许

- 同时改模型；
- 改 prompt；
- 改 business schema；
- 同时启用 thinking；
- 改 Memory 内容；
- 放宽失败校验。

## 6.4 Gate

只有合法 native 环境冻结完成，才进入 E1。

否则保持：

```text
NATIVE_PROTOCOL = BLOCKED_ENVIRONMENT
```

---

# 7. E1：工具协议与推理模式校准

## 7.1 第一比较

```text
J0 = JSON-action / thinking=false
N0 = native / thinking=false
```

若资源允许且第一比较完成，再可选：

```text
J1 = JSON-action / thinking=true
N1 = native / thinking=true
```

thinking 是独立变量。

## 7.2 数据

### Regression

v7 六结构，各一份：

- save；
- update；
- live query；
- read-only；
- quoted imperative；
- temporary。

### New diagnostics

新增 8–10 条：

- save + unrelated business tool；
- save + immediate answer；
- explicit live lookup；
- exact-key action；
- current vs historical；
- no-write；
- two memory operations；
- business action + memory update。

## 7.3 七层指标

1. intent/action selection；
2. tool arguments；
3. execution；
4. persistent result；
5. current answer；
6. later use；
7. total cost。

## 7.4 强制 tool choice

可以作为诊断 arm，但不能作为主任务成绩。

## 7.5 Gate

若 native 改善 required action reliability，且 no-write precision 与参数不退化，可进入下一阶段候选。

若 JSON/native 类似，则停止协议研究，保留更简单、环境更稳定的一条。

---

# 8. D2：准确对象引用

## 8.1 目标

减少模型重新生成已知业务 key 引起的参数漂移。

## 8.2 轻量对象引用

```text
BusinessObjectRef {
  ref
  kind
  display_name
  exact_external_key
  source_receipt
}
```

不是新数据库。

## 8.3 模型接口

模型选择：

```text
object_ref
```

执行器解析成：

```text
exact_external_key
```

## 8.4 公平性

- baseline 也获得相同引用能力；
- 不注入 gold；
- 只有已取得对象才能形成 ref；
- 多候选需实际选择／查询；
- 不做模糊自动修正。

---

# 9. E2：业务参数可靠性

覆盖：

- exact plural key；
- punctuation-sensitive key；
- numeric code；
- similar objects；
- updated object；
- missing ref requires lookup；
- stale historical ref；
- owner-specific same display name。

Arms：

```text
T0 = free-text key
T1 = typed object ref
```

指标：

```text
target selection
argument exactness
business success
wrong-object side effect
clarification correctness
lookup count
tokens/calls
```

Typed ref 只有在降低参数错误且不增加错误对象选择时保留。

---

# 10. D3：有限同步 Memory 子任务

仅当后续 direct 路径仍真实漏存时触发。

## 10.1 不建立第二个 Writer

仍使用同一 MemoryService。

## 10.2 输入

```text
current observations
relevant current records
actual receipts
owner/scope
```

不提供 rubric、gold、未来任务或全部历史。

## 10.3 输出

```text
CREATE / UPDATE / DELETE / NO_CHANGE
```

## 10.4 触发

允许：

- 应用显式 memory intent；
- Host 明确提出 maintenance request；
- 可信入口提供 save-command 类型。

不允许：

- 关键词强制写入；
- scorer 告诉 runtime 必须保存。

---

# 11. E3：Direct vs Maintenance Subtask

任务必须同时包含：

### Positive

- explicit save；
- explicit update；
- explicit delete；
- business result changes plan；
- two independent matters。

### Negative

- quoted instruction；
- temporary format；
- read-only；
- suggestion not adopted；
- one-off result with no future value。

Arms：

```text
D = direct Host memory tools
M = bounded maintenance subtask
```

重点评分：

```text
necessary writes
false writes
correct target
unrelated preservation
duplicate matters
later reuse
generation tokens
extra calls
```

如果 direct 已稳定，则不增加 subtask。

---

# 12. E4：真实 partial / unknown / recovery

## 12.1 Partial

例如：

```text
reservation created
label creation failed
```

## 12.2 Unknown

例如：

```text
request may have reached external system
local result unknown
```

若当前 ApplicationWorld 无法表达 unknown，只增加最小 deterministic fixture。

## 12.3 要求

Agent 必须：

- 保留真实 side effect；
- 不把 partial 说成完整成功；
- 不重复已成功动作；
- 新进程查询实际状态；
- Memory/State 保存未完成部分；
- 恢复后继续剩余工作；
- owner 隔离。

## 12.4 评分

分别记录：

```text
business side effect
memory update
answer
recovery
duplicate action
actual ID
partial state
unknown state
```

---

# 13. C1：基础稳定门槛

进入长程前至少要求：

- explicit save/update/delete 不再频繁零写入；
- quoted/temporary/read-only 不误存；
- 业务对象没有系统性参数漂移；
- live world 不被旧 Memory 替代；
- 至少一个真实 partial 生命周期完整；
- 没有无限反思、重复搜索或反复业务动作。

不满足：

```text
STOP long-horizon expansion
```

---

# 14. D4：自然长程任务

建议：

```text
2–3 owners
20–40 sessions / owner
15–30 durable matters / owner
```

事项包括：

- stable preferences；
- scoped preferences；
- plans；
- project conventions；
- notes；
- business objects；
- historical changes；
- completed/failed actions；
- temporary exceptions；
- third-party information。

禁止随机插入无任务意义噪声制造 Attention 优势。

---

# 15. E5：All vs Ordinary Query

只要 all 仍在容量内，就保留 all。

自然满足：

```text
candidate_count > threshold
or candidate_tokens > threshold
or all request exceeds capacity
```

后才进入 query。

指标：

```text
required record coverage
wrong scope
current/history
task success
business action
input tokens
embedding cost
extra search calls
```

如果 ordinary query 已经足够：

> Stop，不进入独立 Attention。

---

# 16. D5：State–Attention

只有 E5 出现真实缺口才开发。

推荐 State：

```text
TaskState {
  goal
  scope
  current constraints
  active matters
  working values with provenance
  open questions
  pending actions
  recent actual receipts
}
```

不保存第二份 durable cards。

Attention 只回答：

- 当前任务该看什么；
- 哪些是历史；
- 哪个 scope 适用；
- 还缺什么。

---

# 17. E6：State–Attention 独立价值

Arms：

```text
Q = ordinary query
W = query + deterministic working-state augmentation
A = query + State-Attention selection
```

共同：

- bank；
- Memory；
- CRUD；
- business tools；
- history；
- model；
- token budget；
- permissions。

完整计入 selector 成本。

保留 A 的条件：

```text
质量改善
或
质量不下降 + 明显生命周期成本优势
```

若 W / Q 足够：

```text
删除独立 selector
```

---

# 18. M1：第二模型确认

在 E1、E3 或 E6 出现明确正信号后即可触发。

不必等所有阶段完成。

规模：

```text
6–10 representative scripts
```

要求不同模型家族。

不针对第二模型单独调 prompt 后宣称泛化。

---

# 19. Failure Taxonomy

每条失败记录 earliest breakpoint：

```text
INTENT_RECOGNITION
ACTION_SELECTION
MEMORY_TARGET
MEMORY_CONTENT
TOOL_SELECTION
TOOL_ARGUMENT
EXECUTION
WORLD_STATE
MEMORY_MAINTENANCE
DELIVERY
CONSUMPTION
ANSWER
RECOVERY
EVALUATION
```

禁止只写：

```text
memory failed
```

---

# 20. 成本口径

继续分列：

```text
Host generation
maintenance generation
selector generation
embedding
business calls
memory calls
Store logical reads/writes
HTTP wall
process wall
CPU
unknown
```

未运行阶段必须标：

```text
NOT_RUN
NOT_TRIGGERED
BLOCKED_ENVIRONMENT
```

不能将 0 调用解释成成本优势。

---

# 21. Git / PR 开发组织

每个行为变量独立身份。

推荐：

```text
P0 baseline
P1 protocol
P2 object refs
P3 maintenance
P4 lifecycle
P5 long-horizon/query
P6 attention
P7 final report
```

不要单个 PR 同时改变协议、对象引用、writer policy 和 Attention。

每阶段遵循：

```text
protocol + inputs
→ source commit
→ zero-model prepare/freeze
→ run
→ results commit
```

---

# 22. Stop / Pivot / Go

## GO

如果动作选择、参数、partial recovery、no-write precision 稳定，且自然长程开始出现真实 query pressure，则进入 query / Attention。

## PIVOT

- 协议无差异：停止协议研究；
- object ref 无收益：保留自由文本；
- maintenance 只有成本：删除；
- query 足够：不开发 Attention；
- Attention 无净收益：保留 working-state engineering，不认领算法收益。

## STOP

如果：

- 明确意图下仍随机漏基本工具；
- native/thinking/object/subtask 均不能稳定；
- 正确性只能靠强制工具或隐藏标签；
- 每修一类失败就产生同等严重误存；
- 长程成本远高于简单 retrieval 且无质量收益；

则停止复杂 Agent Memory 算法主张，保留工程底座和负面结果。

---

# 23. Product Gate

Product 保持 NO-GO，直到至少具备：

1. 新任务 formation/update/delete 稳定；
2. false write 低；
3. business side effects 安全；
4. partial/unknown 恢复；
5. owner 隔离；
6. live world 与 Memory 边界；
7. long-horizon 可用；
8. 成本合理；
9. 第二模型或独立确认；
10. 删除／权限边界明确。

---

# 24. 推荐的最小执行批次

如果下一次只授权一个批次，建议：

## Batch 1

```text
D0
D1
E1
```

目标：解决协议未定。

## Batch 2

```text
D2
E2
```

目标：解决 exact-key / object argument。

## Batch 3

条件触发：

```text
D3
E3
```

目标：解决真实漏存。

## Batch 4

```text
E4
```

目标：完成 partial / unknown lifecycle。

之后才判断是否进入自然长程。

---

# 25. 整体完成判据

## 成功收口

需要证据支持：

```text
基础形成/动作可靠
+
生命周期可靠
+
强 ordinary query 基线
+
State–Attention 有独立净价值
+
第二模型确认
```

## 负面收口

如果：

```text
simple ordinary memory
+
good tool interface
+
ordinary query
```

已经足够，或者 State–Attention 无净收益：

> 接受结果，收缩算法主张。

如果基础动作可靠性本身无法稳定：

> 将贡献定位为工程／诊断研究，不继续叠加复杂记忆算法。

---

# 26. 最终架构目标

最终 MiLAi 应保持：

```text
真实 Source / Event
        ↓
一个 MemoryService
        ↓
普通 Retrieval
        ↓
带依据的 Working State
        ↓
必要时 State–Attention
        ↓
同一 ReAct Host
        ↓
准确 Business Object / Tools
        ↓
真实 Result / Recovery
```

需要额外维护时：

```text
同一 MemoryService
+
一次有界 maintenance subtask
```

而不是第二个长期真相系统。

---

# 27. 一句话开发策略

> **先让 Agent 稳定地做对该做的动作，再让 Memory 帮它长期记住；先让普通检索在真实长程里遇到瓶颈，再让 State–Attention 证明自己的价值。**

这样 v8 无论得到正面还是负面结果，都可以形成可信、可复现、可收口的开发与研究结论。
