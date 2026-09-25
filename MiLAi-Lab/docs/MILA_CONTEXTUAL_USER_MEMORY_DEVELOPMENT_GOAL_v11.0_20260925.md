---
goal_id: MILAI-SPARSE-DECISION-BASIS-AND-ATTENTION
version: v11.0
date: 2026-09-25
status: COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT
delivery: fixed_comparison_preserved_post_comparison_repairs_verified
baseline_commit: 6722c5ea3363d33e366bfadad6ae4fcd941a6588
baseline_source_mapping_sha256: 6528ff9c69a567d40afb096e7ecb1c4e81aeafb3bee0c23b4dba20c57f58e9f4
experiment_arm_kind: RESEARCH_PROTOTYPE
generation_request_cap: null
generation_token_cap: null
embedding_token_cap: null
verification_count_cap: null
---

# MiLAi Lab v11 Goal：稀疏决策依据与真正消费状态的 Attention

**目标：将 v10 的单决策依据收敛为只在存在行动分歧时启用的短期控制状态；减少重复声明、冗余投影和输出截断；让有意义的缺口在普通 search 调用中进入实际检索。完成开发后，用固定的小规模原生任务比较任务完成、机制使用与全部成本。**

本 Goal 按授权完成 A–F 的有范围开发与小比较，状态为 `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`。初次窄测、部署 decoder 与投影检查见[开发清单](../data/manifests/contextual-memory-v11-development.json)。固定六臂比较全部使用 R2 映射 `2a95dcd0fde0e90a4eff053b5875d0f6d07a3ec61961fd158201c312102d1cf4`；A2 两实例均 5/5，arc1 A0/A1 中止，arc2 A0 为 5/5、A1 为 4/5。自动 gap 检索与版本通知均未发生，arc2 Notes 同等得分且费用更低，收益未建立。之后修复缓存过度失效、检索计数及错误投影，R3 映射 `666344907d0ef59f171431ebc7e572b92bf68fae2378f82fc32dc8df4fff7c12` 通过 59 项相关窄测和静态检查，未再调用模型，不冒充 R3 未见比较。全部失败与连续 238 次生成／2453097 generation tokens／14274 embedding tokens 均保留，unknown=0、Judge=0。详见[最终结果与逐包证据](CONTEXTUAL_USER_MEMORY_V11_RESULTS_20260925.md)及[开发记录](CONTEXTUAL_USER_MEMORY_V11_DEVELOPMENT_20260925.md)。ordinary 默认、Product 与 v10 原始结果保持不变。

## 1. 核对后的出发点

本地 HEAD 为 `6722c5e`，开始核对时工作区干净。当前 47 个冻结源码文件与 v10 R2 映射全部一致；R2 两臂的 result、trace、accounting 共六份制品与已提交清单的 SHA 全部一致。本轮未额外联网核对 GitHub，也未重跑历史测试。

| R2：同一个已暴露 MERIT arc | Notes | Basis |
| --- | ---: | ---: |
| 原生任务通过 | 5/5 | 4/5 |
| Host 完成 | 7/7 | 7/7 |
| 生成请求 | 26 | 45 |
| 输入 tokens | 203165 | 407174 |
| 输出 tokens | 31667 | 121462 |
| 总 generation tokens | 234832 | 528636 |
| 截断请求 | 1 | 18 |

Basis 已出现一条真实的准确采用 → 新业务观察 → Host 重核 → 原卡修订提交链，不能继续描述为“功能完全没用过”。实际 gap-focus 查询和自动版本通知均为 0，二者收益仍未被验证。23 次 accepted delta 是事件计数，不是 23 次有价值的决策变化；3 个 null 来自 27 个完整可解析输出，另外 18 次截断不能归为 null。[历史报告](CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)

离线新核对：Basis 的 18 次截断均用满 4096 completion tokens，返回内容没有可执行 JSON，`reasoning` 字段非空。这些请求计 234437 tokens，占 Basis 全部生成费用约 44.3%。去掉截断仅作描述时，完整生成次数为 Basis 27、Notes 25；**正式成本仍包含所有失败，不能剔除后宣称效率。**

episode 3 的已提交 Decision 表达“退款需要审批”，最终回答声称“已提交审批”；实际动作只有查订单、查政策和发消息，没有审批或退款回执。此例证实执行事实与最终声明脱节，尚不能证明 Basis 将“已提交”预先写成状态后直接导致错误。

## 2. 方法范围与必须明确的取舍

### 2.1 稀疏性是语义策略，不是配额

只有当前仍有一个未解决的区别，且不同答案会改变下一项有意义的动作时，Host 才创建或继续保留 Basis。例行抄录、流程摘要、已完成动作和无行动后果的好奇问题不需要 Basis。

- 没有现存 Basis 且无行动分歧：`state_delta: null`。
- 已有 Basis 仍适用且无实质变化：`state_delta: null`，保留当前状态。
- 原分歧已经解决或当前任务不再采用该决策：同次普通响应中 `clear`。
- 仅有新信息值得长期保存：继续普通 CREATE／REVISE，不以 Basis 激活作为写入前提。

**null 表示不改变，不能拿它代替 clear。** 激活率 15%—30% 或“80% 不维护”仅是研究设想，不成为 schema 校验、自动清理阈值或通过标准。

### 2.2 主动选择缩小监测窗口

本版不保留已解决决策的隐藏监测槽。清除 Basis 后，不再为该决策持续追踪版本；新观察仍进入普通 ReAct，必要时建立新的 Basis。新 session 仍清空任务控制状态，长期规则留在 Memory。

这意味着本版检验的是**未解决决策窗口内的选择性控制**，不是跨 session 持续监测所有过去决策。MERIT 不同 episode 中规则发生变化，并不自动构成同一个 Basis 的版本重核机会。不得为增加覆盖合并原生 session 或强制采用 MemoryCard。

### 2.3 保持当前研究边界

Lab-only，ordinary 继续默认。只有 A0 Notes、A1 Sparse Basis、A2 Sparse Basis + Attention 三臂；旧 State、support 和 H1—H6 冻结。不加入 Jev、新模型、训练控制器、图数据库、多决策槽、审核 Agent 或后台反思；不重写事务／恢复系统。

沿用准确来源、已读范围、版本绑定、权限、删除、维护终结和业务 intent/result 顺序。State 不是业务回执，也不授予业务或删除权限。Host 与必要的 LLM Judge 使用 vLLM，模型运行一个入口、并发 1。

累计调用、tokens 和复核次数保持 null；所有失败连续记账。单工作流容量仍保留，不为耗尽历史预算停止新授权开发，也不通过增加重试掩盖协议缺陷。

## 3. 工作包与依赖

顺序：**A 离线定位 → B 状态合同 → C Attention 与投影 → D 计账及新任务准备能力 → E 开发冻结与旧任务接线回归 → F 冻结未见小样本并比较。** B—D 完成前不购买新模型调用。

| 包 | 实际改动 | 完成证据 |
| --- | --- | --- |
| A：现有证据诊断 | 固定 R2 身份，分离截断、完整 delta、实际状态变化；追踪 episode 3 的动作与回执 | 离线摘要；事实、推断、未知分列；旧制品不改 |
| B：状态合同 | nullable gap、稀疏提示、Host／程序状态分权、规范化等值 no-op、重核确认与语义修订分开 | 小范围 schema／转移／引用与恢复检查；无固定额外 State 调用 |
| C：实际状态消费 | 精简模型投影；search 的显式 query 优先、gap 次之、任务 query 兜底；同次 delta 后解析有效查询 | 真实 dispatch 和缓存使用同一查询投影；初始 active gap 可用；deferred 不自动取材 |
| D：成本与准备入口 | 在现有 trace 上增加小型统计；参数化当前固定 arc 的准备与 runner 身份合同 | 不关校验即可准备不同原生 arc；三臂配置只包含声明过的差异 |
| E：开发冻结与接线回归 | 受影响窄检查、decoder 表达检查；冻结后旧 arc 一次 A2 完整回归 | 无截断部分执行或业务重做；稀疏行为如实计数；没有自然 gap 时不强制制造 |
| F：新任务小比较 | 选择并冻结两个未用于开发的完整 MERIT arc，按 A0／A1／A2 运行 | 原生分数、轨迹、机会、控制成本和总成本；失败不换题，收益不足保持默认 |

两个新 arc 是首轮工作范围，不是累计请求硬停止。具体 ID／seed 在开发冻结后按事先写明的规则确定；本轮不读取未见题目来调提示、不虚构选择清单。新 seed 若只是同一模板的金额／实体替换，只能称未暴露实例，不能称新任务类型或广泛泛化。

### A. 离线诊断

沿已保存的 R2 requests／receipts 统计截断时的输入、输出上限、Basis 大小、是否已有可执行动作、前后工具与有效状态；不从缺失 JSON 猜截断请求准备执行什么。现有数据只能定位混合推理耗尽输出，不足以将每个截断归因于 State。

核对字面相同的 set、真实绑定后的相同状态、重核确认三者。本轮离线发现 24 份可解析 set 中有 8 对相邻文本完全相同；其中包含被拒提案，且同样文本可能确认了新观察。它是规范化优化的线索，不是“八次无用更新”的结论。

### B. 状态合同

`critical_gap` 接受 JSON null 或具体非空信息需求；Host 只提出 active／deferred，程序根据真实未确认变化产生 needs_recheck。先绑定准确引用，再比较语义字段；相同状态不增加语义 revision、不失效缓存。确认已交付变化但保持判断，应记录为 review acknowledgement，不伪装成新的语义修订，也不能被 no-op 吞掉。

只保留 set／clear／null。暂不引入 State patch；没有证据证明完整 set 仍是主要剩余成本前，不安排 v11.2 实现。

### C. Attention 与交付

有效查询顺序为 **非空显式 query > 合法 action-sensitive gap > 当前任务 query**。三种 focus 是程序解析结果，不要求 Host 每次再作一遍模式分类。A2 的普通无 query search 自动使用 gap；不需要额外规划调用，不自动发起 search。

首次 active gap 也可检索，不能仅允许 needs_recheck；否则未发生版本变化前的缺口永远无法消费。deferred 表示当前暂缓，不能因旧 gap 仍在就自动覆盖普通检索。gap 可能需要业务查询或向用户澄清，不保证 Memory 中有答案。

投影只提供当前判断、范围、短依据句柄、gap、有效状态及必要变化。完整版本、范围与恢复数据仍在内部。固定来源说明只写进一份公共 system 指令；它随每次请求传输的费用照计，不能称“一次说明就不再花 tokens”。

### D. 计账与未见任务入口

优先扩展现有 trace、summary、manifest，不建立评估平台。当前 `prepare_contextual_v9.py` 与 `run_contextual_merit.py` 均写死 `arc0-000`，必须先增加从冻结选择清单取得原生生成参数与目标身份的能力；原始源、arc、world、消息、checker、配置和源码 hash 检查保留。旧重现实例的默认选择保持可解释，不把替换常量当作新任务支持。

### E. 有限接线验证

复用相关单测文件，新增断言集中于：nullable gap、真正 no-op、变化确认、精确旧版本保留、无关变化、query 优先级、同参不同有效 query、deferred／clear、持久恢复和已执行业务不重做。不要扩为笛卡尔积大测试。

冻结后，旧 R2 arc 只运行一次 A2 接线回归；不要求打败历史 Notes，不用历史 Notes 充当新版本匹配对照。若自然未发生 gap／版本变化，报告未覆盖，确定性检查只证明路径可执行。若发现实质 bug，可在新身份下做问题驱动的定向复核并记账，不循环完整旧 arc 直到 5/5。

### F. 未见小样本与三臂

| Arm | 工作控制 | 自动版本反馈 | 自动 gap 检索 |
| --- | --- | --- | --- |
| A0 | 强工作笔记，可自主查询、更新与澄清 | 无 Basis 通知 | 关 |
| A1 | Sparse Basis | 开 | 关；Host 可显式改写 query |
| A2 | 同 A1 | 与 A1 相同 | 开 |

A0→A1 比较的是稀疏结构、引用绑定与反馈的整体，不独占归因为“表示”。A1→A2 仅改变无显式 query 时的取材规则，可以评估 Attention 的增量；若同时改重核配置，只能报告联合控制效果。本轮不增加第四臂来单独估计通知收益。

三臂从同样合法历史和独立初始业务世界开始，共享 CRUD、工具、维护合同、模型、上下文、输出容量、恢复和评分。完整 arc 内保留原始到达与 session；独立 arc 不继承前一 arc 的记忆或业务状态。

选择后不根据谁得分高而换 seed、删 episode 或修评分。原生 checker 优先；额外机制标签不回写原生分数，也不进入 Host。需要语义 Judge 才调用 vLLM，费用单列；没有标签就报告 unknown，不强行给 precision。

## 4. 指标与完成标准

| 维度 | 必须报告 | 不能替代的结论 |
| --- | --- | --- |
| 任务 | 原生分数、完整轨迹、实际动作、Host／维护完成 | complete 不等于任务正确 |
| 稀疏性 | 请求前占用率、动作消费时占用率、激活次数、清除次数、生命周期长度 | accepted delta 数不等于激活率；不追求固定 20% |
| 稳定性 | 实质修订、等值 no-op、review ack、churn | 合理重核后不改动作也可有价值 |
| 重核 | 真实通知、Host 消费、需要重核的独立机会、unknown | 不从 Host 自己写的 gap 生成 gold |
| Attention | 有效 query 来源、实际检索、新增相关证据、后续使用 | 调用过 gap 不等于有效，证据 ID 变化不等于有用 |
| 成本 | 输入／输出、失败、embedding、Judge；State 投影／历史／合同／sidecar 估算 | 共享推理和额外请求不能精确全部归因于 State |
| 截断 | 截断数／全部生成数、消耗、连续失败位置、业务影响 | 不剔除失败再称效率提升 |

工程完成要求合同、缓存、持久恢复、三臂准备入口与窄检查成立；方法完成要求真实小样本产生可解释结果。负面／不确定效果可研究结项；未发生的 gap、自动通知保留 NOT_OBSERVED，不用机械用例充当真实方法收益。

若三臂均无自然机会，结束本轮小比较并说明适用性不足，不自动扩题。若普通路径仍占优，保留 ordinary 和 Notes 作为强基线，不追加候选掩盖结果。总体质量—成本改善至少需在同一新冻结身份、同样原生任务上成立；一次局部省 token 不够。

## 5. 代码组织与开发安排

| 位置 | v11 责任 |
| --- | --- |
| `contextual_memory/decision_basis.py` | nullable gap、状态所有权、转移结果、精简投影；纯函数为主 |
| `contextual_memory/query_context.py` | 唯一有效查询解析；供执行和缓存共用 |
| `contextual_user_memory.py` | 应用状态、真实变化通知、检索与 checkpoint 的窄接线 |
| `runners/contextual_host.py` | 同次 delta＋action、变化可见性、提示和请求投影；不新增语义审核 |
| `contextual_session.py`／`contextual_runtime_store.py` | 复用现有交付与恢复；仅在新合同需要处改动 |
| `contextual_capacity.py`／现有 accounting | 本地 tokenizer 计量和 provider 真实用量分开 |
| `prepare_contextual_v9.py`／`run_contextual_merit.py` | 从冻结清单准备不同原生 arc，增加三臂身份，不复制 runner |

不按文件行数进行大重构，不迁移整套 State，不新建第二份可见性／执行账本。基线反馈、材料压缩和方法干预分别形成可识别的修改与协议身份。

Sol xhigh 负责核心／Host／查询集成；明确窄任务可交 Luna max，已授权下载和发布可用 Luna high；Astra xhigh 只用于具体难题。实际并行开发需有明确分工：纯状态函数与只读成本统计可并行，Host、存储、缓存及运行身份由一个集成人改动。本轮文档核对未启动子代理。

## 6. 交付与结项

实施时产物：v11 协议与三臂配置、窄检查记录、冻结源码与选择清单、小规模结果及连续费用。原始模型请求、业务世界、权重、数据库和完整 benchmark 留在 ignored 目录；Git 只收源码、模板、紧凑清单及报告。

v11 新账本引用已封存的 v10：122 次生成、1216124 generation tokens、8148 embedding tokens，unknown=0、Judge=0；旧 v9 费用单列。不得重置旧费用或将不同模型的 tokens 混成精确货币成本。

状态按证据推进：`PLANNED_NOT_STARTED` → `IMPLEMENTED_PENDING_SMALL_VALIDATION` → 有范围的小验证结果；效果不足时用 `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`，适用机会不足时说明缺口。**本轮按负面／不确定效果结项：R2 六臂原生证据与 R3 定向工程修复分开，未证明 Attention、自动版本通知或总体质量—成本收益。全部失败、未评分轨迹和费用保留，不扩题、不循环重跑，ordinary 继续默认。**
