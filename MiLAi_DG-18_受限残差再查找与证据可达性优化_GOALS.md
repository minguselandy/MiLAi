# MiLAi DG-18：受限残差再查找与证据可达性优化 Goal

> Goal ID：`DG-18`  
> 文档版本：`0.2.1 PROVIDER RCA`  
> 生效日期：`2026-08-28`（Asia/Shanghai）  
> 当前状态：`DG-18 COMPLETE WITH RESIDUAL PARKED / R0–R2 PASS / R3 PROVIDER CONTRACT FAILED / R4–R5 NOT EXECUTED`  
> 产品前置：`DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE`  
> 语义读取前置：`DG-17 Candidate Acquisition A0–A6` 的真实代码与收据  
> 外部机制证据：ReFind，arXiv `2608.12888v2`，代码 commit `a80175ca0eeb52a938d7cab7a602bc780de8a577`  
> Provider：operator-owned vLLM `http://127.0.0.1:7860` / `Qwen3.6-35B-A3B-FP8`；本次兼容性探针观测版本 `vLLM 0.27.1`  
> Runtime / Schema：`CANDIDATE / EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> 研究声明：`RESEARCH CANDIDATE / NOT A NOVELTY CLAIM`

---

# 0. Goal 决定

## 0.0 终态校准与证据优先级

本版是对已封存 DG-18 执行结果的终态校准，不回写或篡改历史 receipt。执行事实以下列材料为准：

- `var/dg18/final/dg18-terminal-receipt-20260828-001.json`；
- `var/dg18/final/dg18-r1-lme-score-20260828-001.json`；
- `var/dg18/r3/dg18-r3-residual-shadow-20260828-001/receipt.json`；
- `var/dg18/r3/dg18-r3-residual-shadow-20260828-002/receipt.json`；
- `docs/dg18/runtime-architecture-and-operator-runbook.md`；
- 当前 Runtime / MCP 代码与测试。

终态必须分成三个不可混合的结论：

```text
Product result:
  R1 packing / local context                    PASS
  R2 resolve-local AcquisitionState             STRUCTURAL PASS

Provider treatment delivery:
  schema-valid residual hints                   0/10 calls
  additional acquisition passes                 0

Algorithmic result:
  bounded residual refinding effect             NOT EVALUATED
```

历史收据和 runbook 保留了：

```text
PARKED_NO_GENERALIZABLE_RESIDUAL_GAIN
```

该字符串不改写，但本文档对它的分析语义校正为：

```text
PARKED_PROVIDER_CONTRACT_INCOMPATIBLE
RESIDUAL_EFFECT_NOT_EVALUATED
```

原因是 R3-001 的 `5/5` provider 输出未通过 `ResidualSearchHint`
Schema，R3-002 的 `5/5` 调用均为
`SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT`。没有任何 hint 进入额外
acquisition，因而不能把 fail-closed 后的 `delta = 0` 解释为残差算法的
零效果。

本次单项复现进一步把两个阶段分开：

```text
R3-001
  provider 确实生成了非空 completion
  → 5/5 未通过 ResidualSearchHint 校验
  → 历史 receipt 未保存原始 completion 或 validation field path
  → 精确违反了哪个字段： [UNKNOWN]

R3-002
  当前完整 guided JSON Schema 包含 xgrammar 不支持的 uniqueItems
  → non-streaming 请求返回 HTTP 500
 → streaming 请求返回 HTTP 200 + 顶层 SSE error event + [DONE]
  → adapter 忽略无 choices 的 error event
  → 最终被误报为 SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT
```

复现到的 streaming wire 形态为：

```text
HTTP 200
data: {"error":{"message":"","type":"InternalServerError","param":null,"code":500}}
data: [DONE]
```

当前 operator-owned provider 的服务日志给出的直接错误是：

```text
ValueError: The provided JSON schema contains features not supported by xgrammar.
Grammar error: Unimplemented keys: ["uniqueItems"]
```

证据位置：

- `runtime/src/milai/application/residual_refinding.py` 的 provider Schema 使用
  `uniqueItems: true`，并同时包含 action-specific `oneOf` 与嵌套 `anyOf`；
- `runtime/src/milai/adapters/semantic_hint.py` 的 streaming parser 只消费
  `choices[0].delta.content`，没有先识别顶层 `error` event；
- 使用同一 provider、同一模型的 plain 请求、flat enum Schema、flat lexical
  Schema 在 non-streaming / streaming 探针中均能返回内容；
- 使用当前 DG-18 完整 Schema 时，non-streaming 稳定暴露 HTTP 500，streaming
  则产生上述 error event；
- 使用更平坦的 `ResidualSearchHint.model_json_schema()` 诊断 Schema 时，当前
  provider 能生成一个 Pydantic-valid hint。

因此当前可确认的根因不是“模型不知道怎样搜索”，而是：

```text
Provider guided-decoding Schema 不兼容
+
streaming transport 把 provider error 错分为 empty semantic output
+
历史 R3 scorer 将 treatment-delivery failure 合并成 no mediator gain
```

R3-001 的具体 validation mismatch 由于诊断证据没有落盘，仍必须保持
`[UNKNOWN]`；“custom Schema 未完整表达 Pydantic cross-field invariant”只能记为
`[INFERENCE]`，不能补写成历史事实。

当前 evaluator 还存在一个 disposition 语义缺口：
`evals/dg18/residual_shadow.py` 将所有 hard-gate failure 汇总为
`PARKED_NO_MEDIATOR_GAIN`。后续必须拆分：

```text
TREATMENT_NOT_DELIVERED
MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT
```

只有第二类才允许形成 residual mechanism 无增益的结论。

本校准同时冻结：

```text
Runtime                       CANDIDATE
Schema                        EXPERIMENTAL / NO-GO FOR FREEZE
Formal holdout                UNCONSUMED
Production / remote MCP       NOT AUTHORIZED
Paper / novelty claim         NOT AUTHORIZED
```

DG-18 的唯一核心目标是：

> **在 MiLA 确定性 acquisition 已执行、但仍缺少回答所需 Evidence requirement 时，允许一次有界、可追踪、由 observation 驱动的 residual refinding；模型只提出下一条搜索线索，MiLA Runtime 继续决定权限、证据接受、Binding、Sufficiency、Operator 与最终停止。**

该目标的基础设施和 shadow 边界已完成，但 residual treatment 未成功交付。因此
DG-18 的终态不是“已验证 residual refinding”，而是：

```text
local context / packing             implemented and validated
resolve-local acquisition state     implemented and structurally validated
residual provider contract          failed in shadow
live residual product behavior      not authorized and not implemented
```

DG-18 不用 ReFind 替换 MiLA，也不把所有查询改成 Agent 搜索循环。目标读取链冻结为：

```text
MCP memory.resolve
        ↓
MemoryQueryIR / AcquisitionPlan
        ↓
deterministic acquisition
        ↓
Evidence Gate → Binding → Sufficiency
        │
        ├── COMPLETE
        │      → Context
        │
        └── missing requirements
                ↓
        bounded residual refinding
                ↓
        one validated search action
                ↓
        one additional acquisition pass
                ↓
        Evidence Gate → Binding → Sufficiency
                │
                ├── COMPLETE → Context
                └── otherwise → typed PARTIAL / abstention
```

本 Goal 优先解决：

```text
初始 query 无法表达历史中的实际词汇
partial observation 暴露了新的 entity / predicate / time cue
正确 turn 尚未进入 candidate set
同一 episode 的相邻证据未被恢复
重复搜索同一局部区域浪费预算
```

本 Goal 不通过以下方式追求分数：

```text
继续追加 benchmark wording regex
让模型直接选择最终 Evidence
让模型声明 COMPLETE
让模型替换 operator 或 MemoryQueryIR
放松 Binding / Sufficiency
隐藏 fallback
默认四轮 Agent loop
扩大 scope、permission 或 authority
修改 Reader prompt 来掩盖 evidence 缺失
```

## 0.1 产品判断

终态判断冻结为：

```text
Memory Governance Plane        基本成立
Deterministic Query Planning   PARTIAL PASS
Initial Candidate Acquisition  PARTIAL / PRIMARY OPEN BOTTLENECK
Requirement Binding            SAFE BUT STARVED
Sufficiency                    SAFETY PASS
Context Packing                PASS / REQUIRED EVIDENCE LOSS = 0
AcquisitionState               STRUCTURAL PASS / LIVE EXTRA PASS UNEXERCISED
Observation-driven Refinding   PROVIDER CONTRACT FAILED / EFFECT NOT EVALUATED
General Semantic Read          PARTIAL / RELEASE BLOCKED
```

DG-18 的成功不等于“模型搜得更多”，而是：

```text
missing requirement
→ 新 cue
→ 新的 answer-bearing Evidence
→ deterministic Binding
→ requirement-specific COMPLETE
```

若新增搜索只产生更多主题相似文本，而不提高 required Evidence coverage，则该
acquisition mechanism 失败。但如果 provider 未产生一个可执行 hint，则必须记为
`TREATMENT_NOT_DELIVERED`，不得记为算法劣于 deterministic acquisition。

## 0.2 编号与职责校正

DG-17 `v0.3.1` 曾临时将 `DG-18` 预留为 lifecycle efficiency successor。该预留与当前明确指令冲突，且 batch ingest、persistent worker、watermark、projection throughput 与 cleanup 已由以下 Goal 持有：

- [`MiLAi_DG-15_受治理记忆流水线与投影效率优化_GOALS.md`](./MiLAi_DG-15_受治理记忆流水线与投影效率优化_GOALS.md)

因此从本文生效起：

```text
DG-15
  owns lifecycle / projection efficiency

DG-17
  owns typed semantic read foundation and historical A0–A6 evidence

DG-18
  owns bounded residual refinding and evidence reachability
```

DG-17 中关于 “DG-18 Lifecycle Efficiency” 的文字保留为历史记录，不回写、不伪装从未存在；在后续工作归属上由本文显式取代。任何新的 lifecycle successor 必须使用新的 Goal ID。

## 0.3 与 DG-17 A7–A11 的去重规则

DG-17 已设计但尚未完整执行的以下工作与 DG-18 重叠：

```text
A7 slot-aware expansion
A8 ResidualLexicalHint shadow
A9 one-call live residual acquisition
A10 matched confirmation
A11 stratified opened-dev
```

本文生效后：

- DG-17 A0–A6 作为 DG-18 的输入证据和基础实现，不重复开发；
- slot-aware expansion、search state、residual shadow、live refinding 与后续 matched evaluation 由 DG-18 单一持有；
- 不允许 DG-17 与 DG-18 同时维护两套 residual controller、trace 或 evaluator；
- DG-17 历史收据保持只读，不能重评分或回写；
- 若同名合同存在差异，以实际已发布的公共合同为兼容边界，以 DG-18 内部合同为 successor 实现边界。

---

# 1. 当前真实开发状态

## 1.0 DG-18 已执行终态

| 阶段 | 执行结果 | 真实含义 |
| --- | --- | --- |
| R0 | `PASS_BASELINE_AND_OWNERSHIP_FROZEN` | 基线、owner、opened-dev 与 holdout 边界已绑定 |
| R1 | `PASS_PACKING_LOSS_ZERO` | Runtime local context 和 required-source reserve 已经验证 |
| R2 | `PASS_TYPED_ACQUISITION_STATE` | resolve-local state / typed note / bounded trace 通过结构和测试门禁 |
| R3 | `TREATMENT_NOT_DELIVERED / PROVIDER CONTRACT FAILED` | R3-001 校验失败字段因历史 trace 不足为 `[UNKNOWN]`；R3-002 已复现为 xgrammar `uniqueItems` 不兼容并被 streaming adapter 误报；0/10 valid hint，0 extra pass |
| R4 | `NOT_EXECUTED_NOT_AUTHORIZED` | R3 未越过 treatment-delivery / mediator 门禁 |
| R5 | `NOT_EXECUTED_PARKED_NOT_NEEDED` | 没有一轮有效 residual 后的 second-hop failure slice |

R1 最终 archive `003` 与 R3 所用 deterministic archive `002` 共同显示的
opened-dev 证据漏斗如下。两者的 required Evidence 核心 mediator 相同，但 exact
Context bytes 并不相同；后续任何复验必须绑定最终 `003` archive：

| Mediator | 结果 | 证据来源 |
| --- | ---: | --- |
| Required Evidence acquired | `11/23 = 47.826%` | R1 `003` + R3 baseline `002` |
| Required Evidence retained | `11/23 = 47.826%` | R1 `003` |
| Answer-bearing source turns | `10/21 = 47.619%` | R1 `003` |
| Required-slot candidate recall | `10/16 = 62.5%` | R3 baseline `002` |
| Binding | `8/14 = 57.143%` | R3 baseline `002` |
| Operator-ready cases | `4/10` | R1 `003` + R3 baseline `002` |
| Candidate noise | `34/44 = 77.273%` | R3 baseline `002` |
| Packing loss | `0` at 512 and 2048 | R1 `003` |
| Wrong COMPLETE | `0/N` | R1 / R3 |
| Wrong scope / authority | `0/N` | R1 / R3 |

因此当前首要瓶颈已从 packing 明确前移到：

```text
candidate acquisition / ranking
→ answer-bearing source reachability
→ Binding / OperatorReady
```

上下文效率也尚未闭合：

| Budget | 平均 Context tokens | Truncated contexts | Required Evidence retained |
| --- | ---: | ---: | ---: |
| 512 | `489.3` | `7/10` | `11/23` |
| 2048 | `2024.4` | `9/10` | `11/23` |

Observed：2048 档消耗约 `4.14×` Context tokens，但 required Evidence coverage 没有增加。
这不是 packing correctness 失败，而是 optional context 填充策略的成本与噪声问题。
后续必须把 token budget 视为上限，而不是必须填满的目标。

## 1.1 已确认基础

以下结论来自当前代码、测试与收据，不来自 Goal 状态板推测。

| 单元 | 当前真实状态 | 证据 | DG-18 处理 |
| --- | --- | --- | --- |
| DG-17 A0 | `PASS` | `var/dg17/a0/dg17-a0-acquisition-loss-20260827-002/receipt.json` | 直接继承，不重跑，除非输入身份漂移 |
| DG-17 A1 | `FACTOR PASS / CUMULATIVE PARTIAL` | A1 acquisition receipt + Runtime full gate | 继承 turn-first precursor；packing loss 仍开放 |
| DG-17 A2 | `FACTOR PASS / CUMULATIVE PARTIAL` | A2 acquisition receipt + Runtime full gate | 继承 per-slot probe/fusion；不宣称累计门禁通过 |
| DG-17 A3 | `PASS` | `dg17-a3-source-calibration-20260827-002` | 继承 structured speaker；默认 neutral、无魔法 boost |
| DG-17 A4 | `PASS / PRODUCT DEFAULT UNCHANGED` | `dg17-a4-lexical-evaluation-20260827-001` | 作为 deterministic lexical arm；不把规则扩写成语义词典 |
| DG-17 A5 | `PASS / EVENT PROJECTION PARKED` | `dg17-a5-temporal-acquisition-20260827-001` | 继承 source-observed bounded scan；event-time 缺投影时继续 fail closed |
| DG-17 A6 | `CHARACTERIZED_PARTIAL / PRODUCT DEFAULT PARKED` | focused PostgreSQL PASS；`dg17-a6-productization-20260827-001` terminal characterization | 只作为 matched backend arm；不得默认启用 |
| DG-17 local gate 024 | `PASS` | 367 tests；strict mypy / Ruff PASS；0 external model calls | 作为本 Goal 起始代码门禁 |

## 1.2 当前 mediator 基线

已确认的主要基线包括：

```text
Q6-003 typed path:
  Required Evidence coverage = 7/23
  EM / F1                    = 2/10 / 0.227338130
  Wrong COMPLETE             = 0

Q8 strong-dense diagnostic:
  acquisition coverage       = 18/23
  EM / F1                    = 2/10 / 0.277685951
  product rollout            = NOT AUTHORIZED

A1 2048:
  required atoms acquired    = 10/23
  answer-bearing turns       = 9/21
  operator-ready cases       = 4/10
  packing loss               = 1
  wrong COMPLETE             = 0

A2 2048:
  required atoms acquired    = 10/23
  answer-bearing turns       = 9/21
  operator-ready cases       = 4/10
  packing loss               = 2
  wrong COMPLETE             = 0
```

Observed：

- strong dense 显著提高 candidate recall，但没有同步关闭 Binding、packing、operator 或 answer quality；
- turn-first 与 per-slot probes 已形成可执行 precursor，但静态一次检索仍不能覆盖全部 required evidence；
- A4 的通用语言学 enrichment 只带来小幅正增益，不能承担开放域 paraphrase bridge；
- A5 已能安全区分时间轴，但没有通用 event projection；
- A6 Evidence dense 相对 baseline 多命中 1 个 answer-bearing atom、1 个 source turn，OperatorReady `+1`，同时新增 49 个 candidate noise；未达到 `OperatorReady +2` gate，因而以 `PARKED_NO_SAFE_MATCHED_MEDIATOR_GAIN` 结束产品默认接入；
- 当前没有已验证的 observation-driven residual loop。

Inference：

> `[INFERENCE]` 在 deterministic acquisition 已产生部分相关 observation 的失败 slice 上，后续 cue 可能比继续扩大第一次 Top-k 更有效；必须通过 DG-18 matched mediator 实验验证，不能由 ReFind 论文结果代替。

## 1.3 当前失败模式

```text
Question / IR 基本正确
        ↓
静态 lexical/dense probes
        ↓
只找到主题相关或半个 evidence set
        ↓
正确 turn / operand 未进入候选
        ↓
Binding 无法满足 required slot
        ↓
Sufficiency 安全返回 PARTIAL / UNKNOWN
```

DG-18 只修复这条链中：

```text
partial observation
→ next acquisition cue
→ missing Evidence reachability
```

它不将 Reader、Canonical State、Lifecycle 性能或所有 temporal modeling 问题打包进同一实现。

---

# 2. ReFind 证据与吸收边界

本地只读材料：

- [ReFind 论文与代码架构分析](../ReFind-paper/ReFind_论文与代码架构分析.md)
- [arXiv 2608.12888v2 PDF](../ReFind-paper/arxiv-2608.12888v2.pdf)
- ReFind checkout：`../ReFind/`，commit `a80175ca0eeb52a938d7cab7a602bc780de8a577`

## 2.1 ReFind 提供的机制证据

ReFind 的方法可以简化为：

```text
raw chat turns
+ session / time / adjacency
+ iterative lexical queries
+ local context
+ cross-round search state
→ evidence notes
→ separate answer model
```

其最关键的消融不是 BM25 与某个 embedding 的比较，而是 `One search`：保留首条 agent query、BM25、session RRF、local context 与 temporal control，只移除观察结果后的继续检索，LongMemEval-S/M 分别从 `93.2/89.3` 降为 `84.7/68.9`。

这支持：

> observation-conditioned reformulation 可能显著改善长历史 Evidence reachability。

它不证明：

```text
ReFind 的代码可直接成为 MiLA Runtime
多轮搜索对所有 query 都更好
模型可以决定 Evidence validity
模型可以决定 completeness
raw chat 可以替代 Canonical State
ReFind 的论文分数可作为 MiLA 的本地验收阈值
```

### 2.1.1 开源代码中的真实控制循环

ReFind 能稳定产生下一条 query，不是因为它要求模型一次生成一个复杂检索计划，
而是因为它给模型一个非常小的动作空间，并把真实搜索结果作为下一轮
`Observation` 返回：

```text
Question
  ↓
LLM chooses one action
  ├── search_chatrecord(keywords, optional date range)
  ├── take_note(indices)
  └── finish_search
  ↓
deterministic BM25 + session RRF + local ±2 context
  ↓
Observation: score / session / matched turn / surrounding turns
  ↓
LLM observes newly exposed words, entities and dates
  ↓
search again with a revised cue
```

公开代码的 prompt 直接规定：

```text
search → take_note → search again → take_note → finish_search
```

并要求后续搜索使用不同关键词。`ReFind/app/retriever.py::_agent_search()` 在最多
四轮内维护：

```text
excluded anchor IDs
ordered notes
last hits
search history / token / iteration counters
```

每次搜索由 `ReFind/app/bm25.py::BM25Index.search()` 执行；结果经过 session RRF、
邻接 turn 恢复后，以新的 user-role Observation 继续喂给 controller。无效 action
或缺少 keywords 也会形成可观察错误，让模型有机会在下一轮纠正。

代码证据：

- `ReFind/app/retriever.py::SYSTEM_PROMPT`：定义三个动作及显式循环指令；
- `ReFind/app/retriever.py::_agent_search()`：维护 state、解析动作并把搜索结果回送为
  Observation；
- `ReFind/app/bm25.py::BM25Index.search()`：turn BM25、session RRF、日期过滤与邻接恢复；
- `ReFind/app/config.py`：公开实现默认最多四轮；
- `ReFind/app/llm.py`：transport client 自带最多三次请求尝试，这也是 MiLA 明确不继承的
  隐式可靠性/成本行为。

因此 ReFind 的有效控制因素是：

```text
small action surface
+ actual observation feedback
+ multiple corrective turns
+ error-as-observation
+ cross-round search state
```

而不是：

```text
large one-shot JSON contract
或
模型天然知道一个完整 Evidence requirement graph
```

MiLA V0.1 仍保持“一次 controller + 一次额外 acquisition”的成本边界，但必须保留
这个因果结构：模型看到的必须是实际 initial acquisition observation 和真实 missing
requirement，而不是只看到静态 QueryIR 后生成一份重量级对象。

## 2.2 直接吸收、改造吸收与拒绝移植

| ReFind 机制 | DG-18 决定 |
| --- | --- |
| Raw turn preservation | 直接吸收；MiLA Evidence 保持 source identity、permission、retention、revoke |
| Turn-first lexical retrieval | 继承 DG-17 A1 |
| Local context | 改为 round/role-aware、query-conditioned expansion |
| Session RRF | 作为辅助 prior；保留 turn identity，并评估长度偏置 |
| Temporal filter | 使用 MiLA 的 source/event/valid/system time 语义；先过滤再排名 |
| Cross-round seen state | 吸收为 slot/region-aware `AcquisitionState` |
| Iterative reformulation | 改为 gated、一次调用、一次额外 acquisition pass |
| `take_note` | 改为 Runtime 生成的 typed Evidence references，不接受自由文本替代原证据 |
| Retrieval / answer separation | 直接吸收 |
| 每次 Search 重建 BM25 | 拒绝；使用现有 PostgreSQL projection |
| 文本 ReAct parser | 拒绝；使用 provider-compatible 的最小 typed action，业务约束留在 Runtime |
| Hidden last-hit/direct-BM25 fallback | 拒绝；所有降级进入 trace |
| 模型 `finish_search` | 拒绝；停止由 Sufficiency 或 budget 决定 |
| 所有 query 默认 agent loop | 拒绝；只在 missing-requirement slow path 激活 |
| raw log 替代 Canonical State | 拒绝 |

## 2.3 论文与开源代码差异不能被抹平

DG-18 不把开源仓库当作论文完整可执行 artifact。已观察到：

```text
论文：完整 Stage 1 retrieval + Stage 2 answer pipeline
代码：REST Add/Search leaderboard adapter，Stage 2 省略

论文：time / seen-session 先约束候选再 ranking
代码：先全局 score/RRF，后应用日期与 excluded anchor 过滤

论文：seen session
代码：seen anchor ID

论文：显式 notes
代码：无 note 时存在 last-hit/direct-BM25 隐藏 fallback
```

DG-18 采用上文定义的 MiLA 语义，不复制这些不一致行为。

## 2.4 成本边界

ReFind 完整路径平均约：

```text
2.4–2.6 searches / question
约 5 model calls / question
70K–99K tokens / question
warm timing 约 41–42 seconds / question
```

因此 ReFind 是机制证据，不是 MiLA 在线成本目标。DG-18 第一版固定：

```text
controller calls            <= 1
additional acquisition pass <= 1
automatic retry             = 0
```

---

# 3. 产品边界与不变量

## 3.1 MiLA 仍是 MCP Memory Service

MiLA 的第一产品边界保持：

```text
Any authorized MCP client
        ↓
MiLA MCP facade
        ↓
Memory Runtime
```

DG-18 不新增模型可见的低层搜索工具链。普通 Agent 仍调用粗粒度：

```text
milai_memory_resolve
```

Residual refinding 是 `memory.resolve` 内部的可选 acquisition policy，不要求 Agent 自己调用 `search_again`，也不建立 OpenWorker 专用语义。

TaskContext 仍是可选 hint；Task 缺失不得关闭 fresh memory retrieval。

## 3.2 不可破坏的不变量

```text
Evidence != Claim
Retrieval candidate != accepted Evidence
Model cue != Evidence
Evidence note != source text
Context != Canonical State
Projection != Truth
Confidence != Authority
Proposal != Commit
```

Residual controller 禁止：

- 修改 tenant、principal、permission、retention 或 scope；
- 提高 authority；
- 恢复 revoked Evidence；
- 绕过 Canonical Gate 或 Evidence Gate；
- 直接产生 `RequirementBinding`；
- 直接选择 accepted Evidence；
- 直接执行 operator；
- 直接返回最终答案；
- 声明 `COMPLETE`；
- 关闭 OpenIssue；
- 写入 Evidence、Claim、Projection 或 Context truth。

## 3.3 Raw Evidence 与 Canonical State 并存

DG-18 主要作用于 Raw Evidence Lane：

```text
Raw Evidence
→ projection candidates
→ gated EvidenceView
```

Canonical State Lane 保持：

```text
StateKey
→ ClaimHead / ClaimVersion
→ EffectiveClaimState / OpenIssue
→ Canonical Gate
```

若 query 已由 exact Canonical State 满足，Residual controller 必须保持未调用。

## 3.4 安全失败语义

模型或 provider 不可用时：

```text
deterministic result remains authoritative for this read attempt
residual_status = UNAVAILABLE / INVALID_OUTPUT / BUDGET_BLOCKED
final sufficiency remains deterministic
```

不能静默把失败解释成：

```text
Memory not needed
Evidence complete
direct BM25 accepted
previous context current
```

---

# 4. 目标架构

```text
┌──────────────────────────────────────────────────────────────┐
│ MCP Facade                                                   │
│ milai_memory_resolve                                         │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Query and Requirement Plane                                  │
│ MemoryQueryIR → EvidenceRequirement → AcquisitionPlan        │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Deterministic Acquisition                                    │
│ exact state / raw FTS / enriched FTS / temporal / dense      │
│ turn-first fusion → bounded structural expansion             │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Deterministic Decision                                       │
│ Evidence Gate → Interpretation → Binding → Sufficiency       │
└───────────────────┬──────────────────────────┬───────────────┘
                    │ COMPLETE                 │ missing slots
                    ▼                          ▼
             Context Compiler      ┌───────────────────────────┐
                                   │ Residual Refinding        │
                                   │ Observation Builder       │
                                   │ one vLLM typed hint       │
                                   │ policy validation         │
                                   │ one extra acquisition     │
                                   └─────────────┬─────────────┘
                                                 ▼
                                      Gate → Binding → Sufficiency
                                                 │
                                      ┌──────────┴───────────┐
                                      ▼                      ▼
                                   Context              PARTIAL/ABSTAIN
```

## 4.1 控制权表

| Decision | Owner | 模型可否建议 | 模型可否决定 |
| --- | --- | --- | --- |
| Query class / operator | MemoryQueryIR planner | 可在独立受控 parser lane 建议 | 否；DG-18 residual 不得修改 |
| Required Evidence slots | Runtime planner | 否 | 否 |
| Permission / scope | Runtime policy | 否 | 否 |
| Initial channels | AcquisitionPlanCompiler | 否 | 否 |
| Residual cue | Residual controller | 是 | 仅输出候选 hint |
| Cue 是否执行 | Runtime validator / policy | 否 | 否 |
| Candidate validity | Evidence/Canonical Gate | 否 | 否 |
| Requirement Binding | Runtime | 否 | 否 |
| Sufficiency | Runtime | 否 | 否 |
| Operator result | Deterministic operator or governed Reader | 否 | 否 |
| Stop | Sufficiency / budget policy | 可输出 `NO_ACTION` | 否 |

## 4.2 Fast path 与 slow path

```text
Fast path:
EXACT or deterministic acquisition is COMPLETE
→ 0 residual model calls

Slow path:
required slots remain missing
AND residual policy allows
AND provider capability available
AND budget remains
→ 1 residual call + 1 search pass
```

Residual refinding 不是新的 semantic route 枚举；它是已选 requirement 的受限执行升级。

---

# 5. 内部合同

以下合同第一版均为 Runtime 内部 typed value object，不新增公共 MCP tool，也不要求独立 wire-version。只有需要进入现有 `AccessTrace` / `ContextReceipt` 的字段才序列化。

## 5.1 `AcquisitionState v0.1`

```yaml
AcquisitionState:
  query_ir_digest:
  acquisition_plan_digest:

  missing_requirement_ids: []
  satisfied_requirement_ids: []

  prior_actions: []
  seen_anchor_ids: []
  seen_window_intervals: []
  inspected_regions: []
  exhausted_regions: []

  accepted_evidence_refs: []
  per_requirement_candidate_refs: {}
  per_requirement_coverage: {}

  remaining_budget:
    model_calls:
    acquisition_passes:
    candidate_count:
    context_tokens:
    latency_ms:
```

语义：

- 仅在本次 `memory.resolve` 内存活；
- 不是 Canonical State；
- 不作为下一次 query 的 truth source；
- 可以作为 trace 的 bounded metadata 保存；
- `seen` 表示已检查区域，不表示 Evidence 无效；
- 同一 session 仍可能支持多个 requirement，禁止“一次看过即全 session 永久排除”。

## 5.2 `AcquisitionObservation v0.1`

```yaml
AcquisitionObservation:
  question_excerpt:
  missing_requirements:
    - requirement_id:
      semantic_description:
      known_entities: []
      known_predicates: []
      temporal_constraint:

  candidate_summaries:
    - ephemeral_candidate_ref:
      session_ref:
      speaker:
      source_observed_time:
      event_time:
      bounded_snippet:
      matched_terms: []
      matched_channels: []
      possible_requirement_ids: []

  prior_actions: []
  exhausted_regions: []
  remaining_budget:
```

约束：

- controller 只看到最小 snippet 与元数据，不接收整段历史；
- 不提供 gold label、答案、judge result 或 hidden expected output；
- snippet 仍受 principal、permission、retention 与 revoke 检查；
- `possible_requirement_ids` 是 deterministic candidate relation，不是 Binding；
- 可用 ephemeral refs 防止模型输出被误当作持久 Evidence identity。

## 5.3 `ResidualSearchHint v0.1`（R3 历史实现）

下列结构是 R3-001 / R3-002 实际尝试的历史合同，保留用于解释已封存结果，
不再作为后续 provider 重新授权的默认输出 Schema。

```yaml
ResidualSearchHint:
  requirement_id:

  action:
    SEARCH_LEXICAL
    SEARCH_TEMPORAL
    EXPAND_NEIGHBORS
    EXPAND_EPISODE
    NO_ACTION

  lexical_cues:
    terms: []
    phrases: []
    entity_aliases: []
    predicate_rephrasings: []

  temporal_cue:
    axis:
      SOURCE_OBSERVED_TIME
      EVENT_OCCURRENCE_TIME
      NO_CHANGE
    expression:
    from:
    to:

  source_preference:
    USER
    ASSISTANT
    BOTH
    NO_CHANGE

  cue_provenance:
    QUERY
    OBSERVATION
    PARAPHRASE

  rationale_code:
    LEXICAL_MISMATCH
    ENTITY_BRIDGE
    TEMPORAL_NARROWING
    LOCAL_CONTEXT_REQUIRED
    EPISODE_CONTEXT_REQUIRED
    NO_SAFE_ACTION
```

模型输出禁止包含：

```text
Evidence ID
Claim ID
final answer
COMPLETE / sufficient
replacement operator
new scope / tenant / principal
authority decision
permission decision
canonical mutation
```

### Hint validation

Runtime 只执行满足以下条件的 hint：

1. `requirement_id` 必须是当前真实 missing requirement；
2. action 必须位于当前 capability 与 policy allowlist；
3. cue 数量、长度、日期范围与候选上限必须在预算内；
4. temporal cue 必须能由 deterministic temporal parser 规范化；
5. source preference 默认仅作 soft prior；只有原 QueryIR 显式约束时才允许 hard filter；
6. scope、permission、retention 与 authority hard constraints 从原 plan 继承且不可变；
7. invalid output 产生 typed trace，并等价返回 deterministic-only 结果；
8. 不做第二种自由文本 parser、regex rescue 或隐式 retry。

模型可以从 observation 中发现原 query 未出现的新词，也可以生成语义改写；这是 residual refinding 的核心能力。安全性不依赖“禁止所有新词”，而依赖：

```text
新 cue 只能改变 candidate acquisition
所有新 candidate 仍经过既有硬过滤、Gate、Binding 与 Sufficiency
```

### 5.3.1 修订后的 provider 重新授权合同

R3 实践证明，不应要求 provider 同时满足：

```text
action-specific oneOf / anyOf guided schema
+ Pydantic action-shape validator
+ Runtime plan / capability / authority validator
```

这三层对同一 action shape 的重复表达增加了 provider 合同阻抗，但没有提高
scope、permission、revoke、Binding 或 Sufficiency 的最终保障。

当前完整 provider Schema 已确认至少使用了当前 vLLM guided-decoding backend
不支持的 `uniqueItems`。顶层 action `oneOf` 与嵌套 `anyOf` 也会扩大兼容面，但本次
日志中被直接证明为 fatal 的特性只有 `uniqueItems`；其余不得在没有独立探针时写成
已确认根因。

此外，历史合同要求 provider 同时输出：

```text
schema version
requirement ID
五种 action shape
lexical cues
temporal cue / nullable bounds
source preference
cue provenance
rationale code
```

随后 Pydantic action-shape validator 与 Runtime policy validator 又重新解释一次同一
语义。这是 provider wire contract、domain validation 和 policy enforcement 的职责
重叠。模型在这里本应只提交一个弱 cue proposal，不应替 Runtime 填满审计和控制字段。

若未来单独授权 residual provider conformance successor，模型输出应先收缩为平坦弱提议：

```yaml
ResidualCueProposal:
  requirement_id: TARGET_EVENT
  action: SEARCH_LEXICAL | SEARCH_TEMPORAL | EXPAND_NEIGHBORS | NO_ACTION
  cues: []
```

规则：

1. provider 只提供 `requirement_id`、`action` 和有界 cue；
2. 空字段、默认值、temporal inherited bound 和 source role 由 Runtime 补齐；
3. `cue_provenance` 由 Runtime 根据 query / observation overlap 计算，不信任模型自报；
4. `rationale_code` 是 trace 派生值，不作为 provider 必填控制字段；
5. authority 与 correctness 仍由原 plan 继承、Runtime validator、Evidence Gate、Binding 和 Sufficiency 保证；
6. 不为 invalid JSON 增加第二套 regex/free-text repair；无效输出继续 fail closed。
7. provider wire Schema 禁止使用当前 backend 未证明支持的 `uniqueItems`、顶层
   action `oneOf`、嵌套 semantic `anyOf`，以及为了填满旧合同而要求的空数组或 null
   scaffold；
8. Runtime 根据 `action` 构造默认值、继承 temporal bounds、限制 role、scope、
   permission、authority 和 candidate budget；provider 不拥有这些字段；
9. flat Schema 只是 transport contract，不是 Runtime business invariant 的副本。

在再次 LME shadow 之前，必须先运行独立 provider conformance micro-test：

```text
flat enum object
→ flat lexical cue
→ flat temporal action using inherited Runtime bounds
→ non-streaming transport
→ streaming transport with explicit SSE error handling
```

不得用完整 10-case LME 反复调试 Schema。调试收据只保存脱敏的 validation field path、
error type、finish reason 和 token/latency，不默认保存私密 prompt 或完整 provider 原文。

重新授权顺序冻结为：

```text
1. flat action enum conformance
2. flat lexical cue conformance
3. flat temporal cue conformance（时间边界由 Runtime 继承）
4. non-streaming HTTP status / body conformance
5. streaming SSE content / error conformance
6. Pydantic parse + Runtime acceptance
7. 才允许进入 residual shadow fixture
8. 多个有效 hint 与 accepted hint 出现后，才允许完整 LME
```

第一条正式 conformance lane 使用 non-streaming，因为该模式能够透明返回 HTTP 500；
streaming 必须作为独立 transport cell 验证，不能用“HTTP 200”代表一次成功 completion。

## 5.4 `EvidenceReferenceNote v0.1`

ReFind 的自由文本 `take_note` 不直接移植。MiLA 的 note 由 Runtime 在 Evidence 通过 Gate 并形成可验证 interpretation 后生成：

```yaml
EvidenceReferenceNote:
  requirement_id:
  evidence_id:
  source_turn_id:
  session_id:
  quote_span:
  interpretation_ref:
  observed_terms: []
  source_observed_time:
  event_time:
  note_reason:
```

该对象：

- 不替代原 Evidence；
- 不允许模型自由改写正文；
- 不能单独满足 Binding；
- 用于跨 pass 保留已接受证据与新暴露 cue；
- 必须能回到 source turn 与 exact span。

## 5.5 `ResidualRefindingTrace v0.1`

作为现有 Access/Retrieval trace 的嵌套字段：

```yaml
ResidualRefindingTrace:
  activation:
    eligible:
    activated:
    reason:

  deterministic_before:
    missing_requirement_ids: []
    coverage:
    operator_ready:

  controller:
    provider_identity:
    prompt_schema:
    output_schema_valid:
    model_call_count:
    input_tokens:
    output_tokens:
    latency_ms:

  hint:
    action:
    requirement_id:
    cue_digest:
    validation_status:
    rejection_reason:

  additional_acquisition:
    attempted:
    channel:
    candidate_count:
    new_candidate_count:
    repeated_region_count:
    latency_ms:

  deterministic_after:
    missing_requirement_ids: []
    coverage:
    operator_ready:
    sufficiency_status:

  terminal_reason:
```

不得默认记录完整 private prompt、完整 Evidence 正文或 secret。

---

# 6. Retrieval 与 Refinding 机制

## 6.1 Turn-first，Session 只作辅助结构

DG-18 延续 DG-17 A1：

```text
turn/span = primary relevance unit
session/episode = prior + expansion/provenance boundary
```

候选必须保留：

```yaml
turn_score:
turn_rank:
session_prior_score:
session_prior_rank:
fused_score:
matched_probe_ids: []
matched_requirement_ids: []
```

禁止把 session score 复制成所有 turn 的唯一主分数。

ReFind 的 session 内全部 BM25 分数求和仅作为实验 baseline，不直接冻结。DG-18 至少比较：

```text
no session prior
ReFind-style sum + RRF
top-m positive turn aggregation
top-m + length normalization
```

最终公式由 matched mediator 决定，不在实现前写死。

## 6.2 先硬过滤，再 ranking / fusion

真实执行顺序必须是：

```text
tenant / principal / permission / retention / revoke
→ requested scope
→ explicit temporal constraint
→ channel scoring
→ turn ranking
→ optional session prior / RRF
→ candidate cutoff
```

不能复制 ReFind 开源代码中“先全局 RRF、后日期/exclusion 过滤”的顺序。

## 6.3 Local context expansion

第一版支持：

```text
same turn span recovery
→ same user-assistant round
→ adjacent round ±1
→ same bounded episode when explicitly requested
```

扩展必须：

- 不跨 principal、scope、permission 或 session boundary；
- 保留每个 source turn identity；
- 去重 overlap；
- 记录 anchor 与 expansion relation；
- 由 missing requirement 与 query class 决定，不是所有 hit 固定扩 ±2；
- 先选 metadata，再 hydrate 正文；
- Context packing 优先 required-slot coverage，不优先表面 session diversity。

## 6.4 Cross-pass search state

第二次 acquisition 必须避免：

```text
重复同一 query
重复同一 anchor
重复完整相同 window
反复消耗同一 session 的同一区域
```

但不能机械排除整个 seen session。若同一 session 尚可能包含另一个 missing operand，应允许定向搜索新的 region。

Region exhaustion 至少依赖：

```text
query/action identity
inspected turn interval
covered requirement
remaining missing requirements
```

## 6.5 Temporal refinding

时间 cue 不能退化为只向 FTS 添加月份单词。应区分：

```text
SOURCE_OBSERVED_TIME
EVENT_OCCURRENCE_TIME
VALID_TIME
SYSTEM_TIME
```

DG-18 residual 仅允许操作 acquisition 已支持的 source/event axes：

- source observed time 复用 A5 bounded scan；
- event occurrence time 只有 projection ready 或 bounded deterministic extraction 可证明时才执行；
- event projection 不存在时继续 `PARTIAL/UNAVAILABLE`，不得用 Top-k 冒充完整时间扫描；
- residual cue 不能改变 Canonical State 的 valid/system-time 语义。

## 6.6 Lexical、Dense 与 Reranker 的位置

```text
FTS_RAW
FTS_ENRICHED
TEMPORAL
optional EVIDENCE_DENSE
optional small-set RERANK
```

要求：

- lexical cue 不拼入 `semantic_text`；
- dense 在 scope/time hard filter 后的 universe 中执行；
- reranker 只对小候选集排序；
- reranker 不创建 Binding 或 COMPLETE；
- DG-18 residual 第一版优先验证 cue / expansion，而不是同时更换所有 backend；
- A6 已形成 `CHARACTERIZED_PARTIAL` productization receipt，且默认接入被明确 PARK；dense 只能作为 matched arm 或后续独立证明的新 candidate capability。

---

# 7. vLLM 的职责与调用合同

## 7.1 Provider

默认复用当前 operator-owned provider：

```text
endpoint: http://127.0.0.1:7860
model:    Qwen3.6-35B-A3B-FP8
current conformance probe server: vLLM 0.27.1
```

执行时必须记录实际 `/models` identity、启动进程身份或等价 operator receipt。不得由 Goal 文档假定服务仍然相同。

`/models` 可访问或普通 completion 成功，只能证明模型服务可用，不能证明：

```text
guided JSON Schema 被当前 backend 支持
streaming error 被 client 正确分类
输出满足 Pydantic cross-field invariant
hint 能通过 Runtime policy acceptance
```

provider capability 必须通过单独的 conformance matrix 确认，不能从 model identity 推断。

禁止：

```text
重启或重配 operator-owned vLLM
自动切换模型
provider failure 后自动 retry
模型不可用时改用另一隐藏 provider
```

## 7.2 Prompt 范围

Controller prompt 只包含：

```text
原问题的 bounded excerpt
当前 missing requirements
已执行 actions 的 compact trace
少量合法 candidate snippets
剩余预算
最小、provider-compatible typed action schema
```

不包含：

```text
gold answer
gold Evidence label
judge feedback
完整历史
完整 ContextCapsule
canonical write credential
reviewer capability
```

## 7.3 调用上限

V0.1 固定：

```text
model calls                 <= 1 / memory.resolve
extra acquisition passes   <= 1
automatic retry             = 0
controller output           typed JSON only
controller completion       bounded
```

第一阶段使用 non-streaming；只有 streaming adapter 已证明能识别顶层 SSE
`{"error": ...}` 并映射为 typed provider error 后，才允许将 streaming 纳入 matched run。
adapter 必须先检查 top-level error，再读取 `choices[0].delta.content`，不得把 provider
内部错误降格为 `EMPTY_OUTPUT`。

具体 token、snippet、candidate 与 latency 数值阈值在 R3 shadow 实测后冻结，不能在没有 profile 时伪造 SLA。

## 7.4 不使用大模型完成的工作

以下继续由确定性代码执行：

```text
temporal interval normalization where grammar is known
scope / permission / retention / revoke filter
candidate dedup
Requirement Binding
completeness proof
COUNT / SUM / DIVIDE 等 operator
stop / abstain decision
trace identity
```

---

# 8. Work Packages

工作包按顺序解锁。可并行的是同一阶段内互不改变同一事实源的代码、测试、数据分析和实验 arm；单 query 的 decision chain 保持有序。

## R0 — Baseline Hydration 与 Ownership Freeze

执行状态：`PASS_BASELINE_AND_OWNERSHIP_FROZEN`。

目标：不重复 DG-17 已完成工作，把 A0–A6 的真实状态绑定为 DG-18 baseline。

交付：

1. DG-18 baseline manifest，绑定：
   - DG-17 Goal identity；
   - A0、A1、A2、A3、A4、A5 收据；
   - A6 focused gate、sealed execution plan 与 terminal characterization receipt；
   - Q6、Q8 receipts；
   - local gate 024；
2. 绑定 A6 `CHARACTERIZED_PARTIAL` disposition，禁止将已 PARK 的 dense 默认接入静默重新开启；
3. 映射 DG-17 A7–A11 到 DG-18 R1–R5，禁止双重 owner；
4. 冻结 current 10-case opened-dev identity，不消费 formal holdout；
5. 记录现有 MCP / Runtime / schema / provider identity。

退出条件：

```text
no historical artifact rewritten
no completed A0–A5 work repeated without identity drift
all baseline digests resolvable
DG15 lifecycle ownership explicitly preserved
formal holdout consumed = false
```

## R1 — Runtime Local Context 与 Slot-aware Expansion

执行状态：`PASS_PACKING_LOSS_ZERO`。R1 关闭了 required-source packing loss，不宣称
retrieval completeness 已解决。

目标：将当前 eval/adapter 中的局部窗口与 packing 行为收回 Runtime，并关闭 A1/A2 已观察到的 packing loss。

实现：

```text
turn anchor
→ same-round recovery
→ adjacent-round expansion
→ overlap dedup
→ requirement-aware packing
```

要求：

- 使用结构化 turn/session/speaker/adjacency 字段；
- 禁止正文前缀解析 speaker；
- 禁止固定字节 chunk 扩展；
- expansion policy 进入 trace；
- selected answer-bearing Evidence 因 packing 丢失必须为 `0/N`；
- 无需 expansion 的 exact/current query 不增加工作量。

退出条件：

```text
packing loss = 0/N on matched opened-dev
wrong COMPLETE = 0/N
wrong scope / authority = 0/N
current correct cases retain
Runtime, not eval adapter, owns context expansion
```

## R2 — AcquisitionState 与 Typed Evidence Notes

执行状态：`PASS_TYPED_ACQUISITION_STATE`。该 PASS 表示合同、状态转移和安全不变量已
通过；由于 R3 没有产生有效 hint，它仍未被一次真实额外 acquisition pass 端到端消费。

目标：为一次 `memory.resolve` 建立最小跨-pass状态，为 residual loop 做准备，不调用模型。

实现：

```text
seen anchors/windows
inspected/exhausted regions
prior actions
accepted Evidence refs
per-requirement coverage
missing requirements
```

同时实现 Runtime-owned `EvidenceReferenceNote`。

退出条件：

```text
same query/action repetition detected
same window repetition detected
same session different missing slot remains searchable
state is turn-local and cannot become canonical truth
trace contains no private full-text by default
0 model calls
```

## R3 — ResidualSearchHint Shadow

执行状态：`SHADOW_COMPLETE_HARD_GATE_FAILED`。

目标：验证 vLLM 能否在不影响产品结果的前提下，根据真实 partial observation 生成有用的新 cue。

Shadow 只在：

```text
deterministic acquisition finished
AND missing requirements remain
AND residual capability available
```

执行。

Shadow 必须计算“如果执行”后的离线 mediator，但不能修改当前 MCP response、candidate、Binding、Sufficiency 或 answer。

报告：

```text
activation denominator
schema-valid hints
invalid / NO_ACTION hints
cue provenance
gold-turn rank delta
RequiredSlotCandidateRecall delta
RequiredEvidenceCoverage delta
new candidate / noise delta
repeated-region delta
Binding delta
OperatorReady delta
wrong-scope candidate count
controller latency / tokens
```

进入 R4 的硬门禁：

```text
wrong COMPLETE introduced       = 0/N
scope / authority expansion     = 0/N
invalid output product change   = 0/N
already-correct case regression = 0/N
at least 2 missing-slot cases improve gold-source rank,
Binding readiness, or OperatorReady
```

若未通过，必须先区分 treatment delivery 和 mediator effect：

```text
valid hint = 0
or additional acquisition pass = 0
→ PARKED_PROVIDER_CONTRACT_INCOMPATIBLE
→ RESIDUAL_EFFECT_NOT_EVALUATED

valid hint > 0
and additional acquisition actually executed
and mediator gain gate fails
→ PARKED_NO_MEDIATOR_GAIN

R4/R5 remain disabled
```

DG-18 实际属于第一种情形：

```text
R3-001: 5/5 RESIDUAL_HINT_SCHEMA_INVALID
        provider completion 非空；精确 field mismatch [UNKNOWN]

R3-002: 5/5 historically recorded as SEMANTIC_HINT_PROVIDER_EMPTY_OUTPUT
        current reproduction: guided schema backend rejects uniqueItems
        streaming adapter ignores top-level SSE error
        corrected classification: PROVIDER_STRUCTURED_SCHEMA_UNSUPPORTED

valid hints: 0/10
additional acquisition passes: 0
```

R3-001 的 5 次 completion 均有 completion token 与约 1–2 秒调用延迟，因此不能说
provider 没有作答；只是历史 trace 不足以恢复具体校验失败字段。R3-002 则已经由当前
同模型/同 endpoint 的最小 conformance matrix 复现。plain 和 flat Schema 成功、完整
Schema 失败，证明“provider 完全不能输出 hint”不是正确结论。

未来 shadow scorer 必须先完成 manipulation check，再选择 disposition：

```text
valid hint = 0
or Runtime accepted hint = 0
or extra pass = 0
→ TREATMENT_NOT_DELIVERED

valid treatment delivered
and matched mediator gain gate fails
→ MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT
```

当前 `evals/dg18/residual_shadow.py` 将两者统一映射为
`PARKED_NO_MEDIATOR_GAIN`，属于 evaluator 语义错误；历史 receipt 不修改，后续实现必须
修正该 owner 后才重新运行 shadow。

## R4 — One-call Live Residual Refinding

执行状态：`NOT_EXECUTED_NOT_AUTHORIZED`。只有新的 provider conformance 和 R3
treatment-delivery / mediator gate 通过后，才能由后续显式授权重新开启。

实现：

```text
deterministic pass
→ missing requirements
→ one vLLM ResidualCueProposal
→ runtime validation
→ one additional acquisition pass
→ deterministic Gate / Binding / Sufficiency
```

要求：

- invalid hint 明确记录并返回 deterministic-only outcome；
- 不调用 Reader 生成 search cue；
- 不调用第二个 controller；
- 不自动 retry；
- 不让模型选择 Evidence；
- 不对没有 missing requirements 的 query 调用模型；
- 同一个逻辑 MCP resolve 内完成，不要求 Agent 再发一 Turn；
- MCP client 无需知道内部 residual action 才能使用 memory。

退出条件：

```text
controller calls <= 1
extra passes <= 1
automatic retry = 0
wrong COMPLETE = 0/N
wrong scope / authority = 0/N
revoked Evidence acceptance = 0/N
required Evidence mediator improves over matched deterministic arm
ordinary MCP composition smoke passes
```

## R5 — Optional Two-round Observation-driven Refinding

默认状态：

```text
NOT_EXECUTED_PARKED_NOT_NEEDED
```

仅当 R4 产生明确 failure slice 时解锁：

```text
round 1 返回的新合法 observation
确实暴露了原 query 与初始 candidates 中不存在的关键 cue
且第二次搜索可预期补足仍缺 requirement
```

必须先做 shadow。解锁条件至少包括：

- 不少于两个 opened-dev case 有可回放的 second-hop cue chain；
- 一轮 residual 已正确执行但仍缺证据；
- second-round `MarginalEvidenceGain > 0`；
- 相比扩大第一轮 candidate cap，coverage-per-cost 更优；
- safety、scope 与 already-correct cases 不退化。

即使解锁，固定：

```text
initial acquisition
→ missing requirement
→ cue 1
→ actual search observation 1
→ deterministic Binding / Sufficiency
→ cue 2 only if requirement is still missing and budget remains
→ actual search observation 2
→ deterministic Binding / Sufficiency / stop

controller calls <= 2
additional search passes <= 2
automatic retry = 0
```

模型没有 `finish_search` authority。它可以返回 `NO_ACTION`，但最终停止原因只能由
Runtime 记录为 requirement complete、search space exhausted、budget exhausted 或
typed unavailable。无效 action 可以成为下一轮 observation，但不能触发隐藏 parser、
last-hit acceptance 或 direct-BM25 fallback。

若简单 deterministic / one-call residual 已满足质量和成本，R5 以 `PARKED_NOT_NEEDED` 正常关闭，不为架构完整而实现。

---

# 9. Matched 实验设计

## 9.1 第一阶段只测 mediator

Reader 先保持关闭，比较：

```text
GoldTurnCandidateRecall
RequiredSlotCandidateRecall
RequiredEvidenceCoverage
BindingSuccessRate
OperatorReadyRate
CandidateNoise
RepeatedRegionRate
AcquisitionLatency
ControllerTokens
```

这一步回答：

> 新机制是否真的把缺失 Evidence 带入可绑定候选集？

不能只看最终 F1。

## 9.2 四个核心 control arms

| Arm | 内容 | 回答的问题 |
| --- | --- | --- |
| `D0 STATIC_DETERMINISTIC` | 当前最强 matched deterministic acquisition | 当前产品基础 |
| `D1 GENERIC_AGENTIC` | 使用与 D3 相同的 controller/search 上限，但移除 local context/session prior/temporal/search state | 只是“让模型再搜一次”是否有效 |
| `D2 ONE_SEARCH_CHAT_NATIVE` | 同 controller 的首条 query + chat-native controls，不观察后继续 | 好的首条 query 是否足够 |
| `D3 BOUNDED_RESIDUAL` | chat-native controls + 一次 observation-driven cue | residual adaptation 的边际贡献 |

`D1` 只在隔离 experiment lane 运行，不是产品候选。D1 与 D3 必须报告相同口径的逻辑调用、搜索次数、tokens 与 latency；若实际调用量不同，不能把差异隐藏在总分中。

## 9.3 Component ablations

固定 controller 后，依次消融：

```text
turn-only vs turn + session prior
no local expansion vs round-aware expansion
no search state vs region-aware search state
no temporal control vs typed temporal control
one-search vs one residual search
lexical vs dense vs hybrid backend
```

禁止一次同时切换：

```text
controller
retrieval backend
Reader prompt
token budget
context compiler
case selection
```

## 9.4 Observation-driven mediator

每个 residual round 报告：

\[
\mathrm{MarginalEvidenceGain}_t
=
Coverage(E_t)-Coverage(E_{t-1})
\]

以及：

\[
\mathrm{EvidenceGainPerCost}_t
=
\frac{\Delta RequiredEvidenceCoverage_t}
{Latency_t+\lambda\,ControllerTokens_t}
\]

`lambda` 必须在报告中显式给出；同时保留未加权原始 latency 与 token 数，不能只报复合指标。

## 9.5 Reader 阶段

Mediator 通过后，才在固定 Reader、prompt、provider、budget、case order 下测：

```text
EM
F1
Answer Atom Recall
Abstention Correctness
Answer Shape Error
End-to-end Latency
Quality per Second
```

Reader 修正不能与 residual mechanism 同一 cell 同时发生。

## 9.6 Expanded opened-dev

current 10-case 只用于 development closure。R4 通过后，扩大到 20–50 个按 query class 分层的 opened-dev：

```text
single evidence lookup
temporal filtering
temporal order/distance
aggregation
multi-evidence arithmetic
multi-session join
preference/update
abstention
assistant-provided memory
multilingual/mixed-language
```

formal holdout 在独立授权前保持未消费。

---

# 10. Metrics 与 Gate

## 10.1 Correctness / Governance Gate

所有安全指标必须报告 `count / denominator`：

```text
WrongComplete                    = 0/N
WrongScopeAcceptance             = 0/N
UnauthorizedAuthorityExpansion   = 0/N
RevokedEvidenceAcceptance        = 0/N
PermissionUnknownAcceptance      = 0/N
CrossTenantCandidateAcceptance   = 0/N
HiddenFallback                   = 0/N
ModelSelectedFinalEvidence       = 0/N
ModelDeclaredComplete            = 0/N
```

`N=0` 不能作为 PASS；必须有有意义的负向样本。

## 10.2 Acquisition Gate

至少报告：

```text
GoldTurnCandidateRecall
AnswerBearingTurnRecall
RequiredSlotCandidateRecall
RequiredEvidenceSetCoverage
NewEvidencePerRound
RepeatedRegionRate
EvidenceJoinSuccessRate
BindingSuccessRate
OperatorReadyRate
PackingLossRate
CandidateNoise
```

对任何 model-assisted acquisition，在解读 mediator delta 前必须先通过 treatment-delivery
manipulation check：

```text
ProviderCallAttempted
ProviderSchemaAccepted
ProviderTransportMode
ProviderSSEErrorObserved
ProviderErrorClassificationCorrect
SchemaValidHintRate
RuntimeAcceptedHintRate
AdditionalAcquisitionPassExecuted
NewCandidateCount
NewGovernedCandidateCount
```

若 `SchemaValidHintRate = 0` 或 `AdditionalAcquisitionPassExecuted = 0`，实验结果只能说明
provider/contract 或 executor 失败，不得宣称算法无增益。

`HTTP 200` 不能单独使 `ProviderSchemaAccepted = true`。streaming body 中出现顶层
`error` event 时，必须同时满足：

```text
ProviderSSEErrorObserved             = true
ProviderErrorClassificationCorrect  = true
SchemaValidHintRate                  = 0
TreatmentDelivered                  = false
```

只有至少一个 hint 同时通过 provider Schema、Pydantic parse、Runtime policy acceptance
并真正触发额外 acquisition，才能把该 case 计入 mediator-effect denominator。

R4 进入 matched quality 的最低 development boundary：

- 相对同一 snapshot 的 deterministic arm，至少两个 missing-slot case 改善；
- required Evidence coverage 不退化；
- operator-ready case 数不退化；
- packing loss 为 `0/N`；
- DG-17 Q6 已正确的 case 不退化；
- 安全门禁全部通过。

不在当前 10-case 上预先写死论文级显著性或 production SLA。

## 10.3 Quality Gate

最终 10-case matched run 必须：

```text
F1 >= matched deterministic arm
EM >= matched deterministic arm
already-correct case regression = 0/N
retrieval-hit-but-answer-wrong cases separately reported
```

若 mediator 提升但 Reader quality 不提升，状态写为：

```text
ACQUISITION_MECHANISM_PASS
END_TO_END_QUALITY_NOT_CLOSED
```

不能将其合并成总 PASS。

## 10.4 Cost Gate

结构性成本合同：

```text
EXACT / already COMPLETE:
  residual model calls = 0
  additional searches  = 0

Residual V0.1:
  model calls           <= 1
  additional passes     <= 1
  automatic retry       = 0
  candidate cap         bounded
  snippet budget        bounded
  metadata-first hydrate-later
```

R3 shadow 必须先报告 p50/p95 后，才冻结具体 latency/token 数值阈值。

Context 同时必须报告：

```text
RequiredEvidenceRetained
OptionalEvidenceAdded
ContextTokens
RequiredEvidenceGainPerAddedToken
ContextTruncated
Reader quality / latency
```

结构性成本原则：

```text
token budget is a ceiling, not a fill target
required Evidence first
optional window only when it adds measurable query/requirement value
same Evidence coverage with materially more tokens is a cost regression
```

已观察的 512/2048 结果表明，Context compactness 应作为后续独立消融，不与
provider Schema 修复或 acquisition backend 更换在同一 cell 中修改。

## 10.5 Operability Gate

```text
one-command focused smoke
real PostgreSQL path
real MCP composition path
provider identity captured
typed provider unavailable outcome
trace complete
no eval-owned product behavior
no provider restart/reconfiguration
```

---

# 11. Tests

## 11.1 Unit

至少覆盖：

```text
AcquisitionState transitions
seen anchor/window dedup
same-session different-slot remains searchable
historical ResidualSearchHint schema
minimal ResidualCueProposal schema
provider-supported JSON Schema subset
top-level SSE error classification
non-streaming / streaming conformance separation
hint budget validation
invalid action rejection
temporal cue normalization
soft source preference
EvidenceReferenceNote source/span integrity
trace terminal reasons
```

## 11.2 Property / Invariant

```text
residual hint cannot mutate scope
residual hint cannot mutate authority
residual hint cannot select Evidence
residual hint cannot declare COMPLETE
additional pass count never exceeds policy
invalid hint result equals deterministic-only outcome
accepted Evidence always has source identity
revoked Evidence never re-enters through residual path
```

## 11.3 PostgreSQL Integration

```text
hard filters precede score/fusion
turn rank identity retained
session prior does not erase turn score
source-time bounded scan
speaker uses structured field
neighbor expansion does not cross session/scope
projection watermark respected
dense path pre-filtered when enabled
purge/revoke invalidates residual candidates
```

## 11.4 MCP E2E

至少包含：

1. deterministic COMPLETE，controller 未调用；
2. deterministic missing slot，residual 找到新 Evidence，Runtime 完成 Binding；
3. residual 只找到噪声，Runtime 保持 PARTIAL；
4. provider unavailable，返回 typed degraded result；
5. invalid structured output，无 retry、无产品结果漂移；
6. revoked / wrong-scope candidate 被 Gate 拒绝；
7. 无 TaskContext 的普通 MCP client 仍可使用；
8. OpenWorker prefetch 与 agent-visible MCP tool 使用相同 Runtime 语义。

## 11.5 泛化测试

不允许只测试当前 10 个 case 的词面。至少覆盖：

```text
unseen entity
unseen action wording
unseen word order
Chinese / English / mixed language
assistant-provided evidence
quoted speech
negation
same session multiple operands
cross-session causal/temporal cues
query and observation expose different vocabulary
```

禁止 `case_id → cue`、expected answer substring、gold session ID 或 benchmark-specific synonym table 进入产品代码。

---

# 12. 开发与调试原则

## 12.1 减少防御性编程

本 Goal 要求边界清晰，而不是层层包裹。

允许的防护集中在：

```text
MCP input boundary
provider structured output boundary
permission/scope/revoke Gate
budget boundary
database transaction boundary
```

禁止：

```text
同一 hint 多套 parser
catch-all 后静默 BM25 fallback
多层兼容 alias
无实际调用方的 abstraction
为了“也许未来需要”增加 transport/schema
失败后换模型、换 prompt、自动 retry
为每个 case 添加特殊分支
```

一个输入只走一条可解释主路径；失败必须尽早暴露为 typed state。

R3 执行后增加以下具体约束：

- provider wire schema 只表达最小 cue proposal，不复制 Runtime 的业务不变量；
- action shape 不同时在 custom JSON Schema、Pydantic validator 和 policy validator 中手工维护三份同义规则；
- scope、permission、revoke、authority、budget 与 completion 仍在 Runtime 单一 owner 处验证；
- provider conformance 先使用最小独立 probe，禁止用完整 LME 作为 Schema 调试循环；
- streaming 与 structured-output 必须分开定位，不得把 empty stream 直接当成模型语义失败。

## 12.2 单项失败调试

遇到失败时：

```text
先定位一个 first_loss_stage
→ 运行最窄 fixture/test
→ 修复唯一 owner
→ 复跑该 test
→ 再扩大到相邻 integration
→ 最后运行 matched block
```

禁止在一次提交中同时修改：

```text
QueryIR
acquisition backend
residual prompt
Binding
Sufficiency
Reader
scorer
```

若一个失败由 upstream acquisition 导致，不在 Reader 中补偿。

Provider 结构化输出失败时，调试收据至少保留：

```text
transport mode
HTTP status / stream finish state
provider version / model identity
schema name / digest
SSE top-level error type / code
validation error field path
validation error type
finish reason
completion token count
latency
```

默认不保存完整私密 prompt 或原始 completion。仅记录一个粗粒度
`SCHEMA_INVALID` 不足以支持单项调试。

最窄 provider 单项测试顺序：

```text
plain completion
→ flat enum Schema
→ flat lexical-cue Schema
→ flat temporal-cue Schema
→ full application Schema only after the previous cells pass
```

每个 cell 分开测试 non-streaming 与 streaming。若 non-streaming 为 HTTP 500，而
streaming 为 HTTP 200 + SSE error，则先修 adapter error classification，不修改 prompt、
模型、Binding 或 scorer。provider wire Schema 与 Runtime domain contract 也必须分别
定位，禁止为了让 guided decoding 通过而删除 Runtime safety invariant。

## 12.3 并行资源使用

可以并行：

```text
独立 unit/contract/static gates
不同 PostgreSQL isolation fixtures
matched lexical/dense/hybrid experiment arms
artifact aggregation与日志分析
互不改写同一代码 owner 的实现任务
```

必须串行：

```text
同一 query 的 deterministic pass
→ observation
→ residual hint
→ extra pass
→ Binding/Sufficiency
```

并行不能增加 logical attempts、provider calls、retry 或成功分母。

## 12.4 审查最小化

- R0–R3 不为每个小单元重复进行全量独立审查；
- 使用 focused tests、typed receipt 与 matched artifact 作为日常证据；
- 只有 R4 live product integration 或最终 scoped release 需要一次独立审查；
- 如需独立审查，可按 [`codex_sol_xhigh.md`](./codex_sol_xhigh.md) 调用一次 reviewer；
- reviewer 只审查冻结 bundle，不参与实现，不自动生成 PASS；
- secret scan、全仓 inventory 与 archive scan 仅在 release boundary 做一次，不在每个局部修复重复运行。

---

# 13. Non-goals

DG-18 不实现：

```text
新的 Agent Runtime
OpenWorker Task Controller
新的 public MCP tool family
Direct / HTTP transport parity
portable offline CURRENT lease
push invalidation
多轮默认 autonomous retrieval
完整 ReFind REST 服务移植
每请求重建 BM25
Neo4j / canonical graph
全局 DAG tags
自动 Claim promotion
自动 preference/persona commit
learned Task resolver
Reader fine-tuning
embedding fine-tuning
formal paper holdout
production / remote MCP release
```

Lifecycle batch、worker、watermark 与 cleanup 优化继续属于 DG-15。

---

# 14. Deliverables

## 14.1 文档与合同

1. DG-18 baseline/ownership manifest；
2. `AcquisitionState v0.1`；
3. `AcquisitionObservation v0.1`；
4. 历史 `ResidualSearchHint v0.1` 与 successor `ResidualCueProposal v0.1`；
5. `EvidenceReferenceNote v0.1`；
6. `ResidualRefindingTrace v0.1`；
7. MCP compatibility note；
8. operator runbook；
9. experiment matrix 与 metric definitions。

## 14.2 Runtime

1. Runtime-owned round/neighbor expansion；
2. requirement-aware context packing；
3. cross-pass acquisition state；
4. bounded observation builder；
5. vLLM residual controller adapter；
6. hint validator / executor；
7. one-pass residual integration；
8. trace serialization；
9. typed degraded outcomes。

## 14.3 Tests / Evals

1. unit/property tests；
2. real PostgreSQL integration；
3. MCP E2E smoke；
4. R3 shadow receipt；
5. R4 matched mediator receipt；
6. final Reader quality receipt；
7. optional expanded opened-dev report；
8. release disposition。
9. provider conformance matrix 与 typed SSE error receipt；
10. treatment-delivery / mediator-effect scorer disposition tests。

终态交付校准：

| 交付类别 | 结果 |
| --- | --- |
| Runtime local context / packing | `DELIVERED_AND_VALIDATED` |
| Structured source context / adjacency | `DELIVERED_AND_VALIDATED` |
| AcquisitionState / EvidenceReferenceNote | `DELIVERED_STRUCTURAL_PASS` |
| Residual observation / validator / shadow adapter | `DELIVERED_FAIL_CLOSED_SHADOW_ONLY` |
| Schema-valid residual hint | `NOT_DELIVERED_BY_PROVIDER_CONTRACT`；模型本身的 flat-hint capability 已由独立探针证明 |
| One-pass live residual integration | `NOT_EXECUTED_NOT_AUTHORIZED` |
| Matched residual Reader quality | `NOT_EXECUTED` |
| Expanded opened-dev | `NOT_EXECUTED` |
| Formal holdout | `UNCONSUMED` |

---

# 15. 开发状态板

| Work item | 当前状态 | 说明 |
| --- | --- | --- |
| DG-17 A0 baseline | `PASS / IMPORTED` | 10 cases、23 required Evidence、0 product label access |
| DG-17 A1 turn-first | `FACTOR PASS / CUMULATIVE PARTIAL` | 2048 coverage 10/23；packing loss 1 |
| DG-17 A2 per-slot probes | `FACTOR PASS / CUMULATIVE PARTIAL` | 2048 coverage 10/23；packing loss 2 |
| DG-17 A3 source semantics | `PASS / IMPORTED` | structured speaker；neutral default；source ranking parked |
| DG-17 A4 lexical lane | `PASS / DEFAULT UNCHANGED` | small positive mediator；不是开放域 semantic bridge |
| DG-17 A5 temporal lane | `PASS / EVENT PROJECTION PARKED` | source-time works；event-time fail closed without projection |
| DG-17 A6 Evidence dense | `CHARACTERIZED_PARTIAL / DEFAULT PARKED` | atom/turn `+1/+1`、OperatorReady `+1`、candidate noise `+49`；未达到 `+2` gate，产品默认未改变 |
| DG-18 R0 | `PASS_BASELINE_AND_OWNERSHIP_FROZEN` | 33 项 predevelopment artifact 已绑定 |
| DG-18 R1 | `PASS_PACKING_LOSS_ZERO` | 10 cases / 40 contexts；512/2048 packing loss 均为 0 |
| DG-18 R2 | `PASS_TYPED_ACQUISITION_STATE` | resolve-local state + typed notes；尚未被真实 extra pass 消费 |
| DG-18 R3 | `TREATMENT_NOT_DELIVERED / PROVIDER CONTRACT FAILED` | 0/10 valid hints；0 extra passes；R3-002 已确认为 xgrammar `uniqueItems` 不兼容并被 streaming adapter 误报；residual effect not evaluated |
| DG-18 R4 | `NOT_EXECUTED_NOT_AUTHORIZED` | provider contract / treatment-delivery 门禁未通过 |
| DG-18 R5 | `NOT_EXECUTED_PARKED_NOT_NEEDED` | 无有效 first residual pass 后的 second-hop slice |
| Formal holdout | `UNCONSUMED` | 本 Goal 不授权开启 |
| Runtime / Schema | `CANDIDATE / EXPERIMENTAL` | `NO-GO FOR SCHEMA FREEZE` |

状态板更新必须引用 executable receipt；代码存在、测试局部通过或文档写明目标都不能自动升级为 `PASS`。

---

# 16. Release Disposition

DG-18 本次没有获得 residual-refinding scoped release label。原计划的 label：

```text
DG18 = LOCAL_MCP_BOUNDED_RESIDUAL_REFINDING_VALIDATED_ON_OPENED_DEV
```

状态为 `NOT GRANTED`，因为 R3 没有交付可执行 treatment，R4 和 matched Reader quality
均未执行。

本次只允许声明：

```text
DG-18 engineering closure:
  local context packing validated
  resolve-local acquisition state validated structurally
  residual shadow failed closed at provider contract boundary
  live residual behavior not released
```

若 successor 在未来满足 16.1 的全部条件并正式获得上述 scoped release label，
该 label 的语义才限定为：

```text
local MCP
deidentified/synthetic/opened-development data
bounded one-call residual refinding
typed trace
deterministic safety authority
matched mediator and quality evidence
```

即使未来获得该 label，它也不表示：

```text
Production ready
remote MCP ready
real personal data approved
Schema frozen
formal holdout passed
paper claim established
novelty established
all query classes solved
```

## 16.1 Release 必需条件

1. R0–R4 全部有 terminal receipt；
2. R5 明确 `PARKED_NOT_NEEDED` 或单独通过；
3. Runtime、PostgreSQL、MCP composition tests 通过；
4. strict mypy 与 Ruff 通过；
5. correctness/governance gate 通过；
6. matched deterministic vs residual mediator 通过；
7. final quality 不劣于 matched deterministic；
8. controller/provider/token/latency identity 闭合；
9. formal holdout 未被意外消费；
10. 一次独立 release review 为 `ACCEPT/PASS`；
11. release-boundary secret scan 通过；
12. 明确保留 `Runtime CANDIDATE / Schema EXPERIMENTAL / NO-GO FOR FREEZE`。
13. flat provider conformance 在 non-streaming 与 streaming 分别通过；
14. SSE 顶层 error 能被识别为 typed provider error，不再映射为 empty semantic output；
15. scorer 明确区分 `TREATMENT_NOT_DELIVERED` 与
    `MEDIATOR_GAIN_NOT_OBSERVED_AFTER_VALID_TREATMENT`。

## 16.2 可接受的终止状态

若 treatment 已真正交付，且 R3 或 R4 不证明稳定 mediator 增益，可以以：

```text
DG18 = PARKED_NO_GENERALIZABLE_RESIDUAL_GAIN
```

结束。这不是工程失败，而是证明：

```text
在当前 Runtime、数据、provider 与成本约束下，
bounded residual refinding 没有优于 deterministic acquisition。
```

但必须同时满足：

```text
schema-valid hints > 0
Runtime-accepted hints > 0
additional acquisition passes > 0
mediator delta measured on executed passes
```

若上述 treatment-delivery 条件不成立，只能以：

```text
PARKED_PROVIDER_CONTRACT_INCOMPATIBLE
RESIDUAL_EFFECT_NOT_EVALUATED
```

结束。DG-18 已执行结果属于此类。历史 receipt 中更强的 disposition 字符串保留为
不可变证据，但不用作算法劣于 deterministic acquisition 的研究结论。

不得为了取得正结论而扩大模型权限、增加隐藏轮次或修改 scorer。

---

# 17. 停止条件

满足以下任一条件时立即停止当前实验单元并定位：

```text
wrong COMPLETE > 0
scope / authority expansion > 0
revoked Evidence re-entry > 0
model output directly selects accepted Evidence
model output changes operator or requirement
automatic retry > 0
hidden fallback detected
gold label accessed by product path
already-correct cases regress
provider identity changes during matched run
formal holdout accidentally opened
```

满足以下任一条件时停止扩大 residual 架构：

```text
deterministic path已满足质量和成本
R3未交付 schema-valid / Runtime-accepted treatment
有效 treatment 已执行但 matched mediator 无增益
R4新增 candidate 但不提高 Binding / OperatorReady
第二轮 refinding 不优于扩大第一轮有界候选
controller tokens/latency抵消质量收益
收益只存在于当前 case wording
```

前一种情况归因为 provider contract / treatment delivery，后一种情况才允许归因为
residual mechanism 在当前约束下没有 matched mediator gain；两者不得合并。

原开发顺序的已执行结果冻结为：

```text
R0 baseline / ownership freeze                 PASS
        ↓
R1 Runtime local context + packing             PASS
        ↓
R2 cross-pass AcquisitionState                 STRUCTURAL PASS
        ↓
R3 one-call residual shadow                    PROVIDER CONTRACT FAIL
        ↓
R4 one-call live residual                      NOT EXECUTED
R5 two-round residual                          NOT EXECUTED
```

DG-18 完成后停止，不自动进入 Graph、multi-agent retrieval、training 或 formal paper experiment。

下一个后续 Goal 不应默认继续扩大 residual agent loop。建议优先级是：

```text
1. deterministic acquisition matched repair
   - 将 Q8 strong-dense diagnostic 通过最终 R1 compiler 和 Binding/Sufficiency 复验
   - 同时控制 candidate noise，不直接开启 product default

2. Context compactness ablation
   - required-only vs required-plus-optional
   - 比较 Evidence coverage、Reader quality、tokens 和 latency

3. provider conformance micro-lane
   - flat schema
   - non-streaming first
   - streaming separately，必须覆盖顶层 SSE error
   - provider Schema 不含未经当前 backend conformance 证明的 uniqueItems / oneOf / anyOf
   - Pydantic 与 Runtime policy 继续保留完整业务验证
   - 不运行 LME，直到最小合同连续产生有效 hint
```

只有同时满足以下条件，才能在新的显式授权下重开 R3/R4：

```text
minimal provider conformance passes
non-streaming and streaming error classification passes
minimal wire schema uses only verified provider-supported features
final R1 archive 003 is the exact shadow input
schema-valid and Runtime-accepted hints > 0
additional acquisition is actually executed in shadow
shadow scorer distinguishes treatment delivery from mediator effect
at least two missing-requirement cases improve
wrong COMPLETE / scope / authority remain 0/N
cost is reported separately from mediator gain
```

---

# 18. 最终原则

DG-18 冻结以下原则：

1. **先执行确定性 acquisition，再对真实 missing requirement 做 residual refinding。**
2. **模型生成搜索 cue，不选择最终 Evidence，也不决定完成。**
3. **Turn/span 负责 relevance；session/episode 负责 prior、邻接与 provenance。**
4. **Search state 必须记住已检查区域，但不能机械排除仍可能包含 missing operand 的整个 session。**
5. **时间、scope、permission 与 revoke 是结构化硬约束，不是 prompt 建议。**
6. **新 cue 可以来自 observation，也可以是语义改写；其权限始终小于 Runtime Gate。**
7. **找到更多文本不是成功，补齐可绑定 required Evidence 才是成功。**
8. **已经 COMPLETE 的查询不调用 controller。**
9. **一次模型调用、一次额外搜索是 V0.1 的默认成本上限。**
10. **若没有稳定泛化收益，应停止并 PARK，而不是堆叠更多 regex、轮次或 fallback。**
11. **未交付有效 treatment 时，不得将 fail-closed 的零变化解释为算法零效果。**
12. **Provider 输出应是最小弱提议；权限、有效性和完成性继续由 Runtime 单一 owner 决定。**
13. **Context budget 是上限，不是填满目标；无 Evidence 增益的 optional context 必须计入成本回归。**
14. **Provider JSON Schema 是 transport capability contract，不是 Runtime business invariant 的复制品。**
15. **有效 treatment 是评估 mediator gain 的前置条件；未执行额外 acquisition 时，零变化没有算法解释力。**
16. **ReFind 的关键是“小动作—真实 Observation—修正 cue”的闭环，不是复杂 one-shot plan；MiLA 吸收闭环，但不吸收隐藏 fallback 或模型停止权。**

一句话总结：

> **DG-18 已将 ReFind 风格的 observation-driven refinding 建模为 MiLA Raw Evidence Lane 的有界 slow-path candidate，并完成了 local context、packing 和 resolve-local state 基础；但完整 guided Schema 被当前 vLLM/xgrammar backend 拒绝，streaming error 又被 adapter 误报为空输出，因此 residual treatment 从未真正执行，Evidence reachability 增益仍未被评估。后续应以最小 typed cue 恢复“小动作—Observation”闭环，同时把 Evidence validity、Binding、Sufficiency 和 Canonical authority 始终保留在 Runtime。**
