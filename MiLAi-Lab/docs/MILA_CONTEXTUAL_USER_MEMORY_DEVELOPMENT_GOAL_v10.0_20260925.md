---
goal_id: MILAI-EVIDENCE-GROUNDED-DECISION-STATE-V0
version: v10.0
date: 2026-09-25
status: COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT
delivery: implementation_and_scoped_validation
baseline_commit: 7247742133de888276342c48638b12c81eaeec23
baseline_source_mapping_sha256: 9854a237f583563618c45ffb59e589484f6c4dea74a8393a1b5c41aa0ce7a0b8
experiment_arm_kind: RESEARCH_PROTOTYPE
generation_request_cap: null
generation_token_cap: null
embedding_token_cap: null
verification_count_cap: null
---

# MiLAi Lab v10 Goal：证据绑定的单决策状态与选择性重核

**目标：在 v9 普通记忆和真实 ReAct 路径上，增加一个小型、可修订的决策依据。Host 在正常动作生成中声明当前判断、实际采用的材料和关键缺口；程序绑定准确版本，追踪实际变化；检索与后续维护消费这份状态。用原生小样本判断它相对强工作笔记是否有价值。**

起草时仅交付本 Goal 与[详细改造设计](MILA_CONTEXTUAL_USER_MEMORY_V10_DECISION_BASIS_DESIGN_20260925.md)。用户随后明确授权执行完整 Goal。A–D 与两次冻结的 E1 小规模比较已完成：首次 R1 候选未采用，修复提示歧义及最终回执后的 R2 建立一条真实新观察重核链，但在同一原生 arc 上质量和费用均不优于强工作笔记。受限研究状态为 `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`，ordinary 保持默认。[R1 历史结果](CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md)与[R2 终态结果](CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)分别保存失败、机制、费用及未运行项；v9 保持关闭。

## 1. 已确认基线与研究问题

本地基线提交为 7247742。v9 的最终同版本连续验证完成 MERIT 原有一个 arc 的 5 个 episode，原生 5/5、依赖 2/2、7/7 Host 与维护完成；固定文档四轮跨进程完成。文档四轮不是四个独立 benchmark 样本。

v9 默认仍为 ordinary、state_policy=off、json_action；method v14、write v13、material view v9、ingestion v30、operation v2、maintenance v3、runtime store v1。来源、准确版本、局部正文与依据增量、维护终结、业务 intent/result 和恢复均已有实现。本轮不重复开发这些能力。

最终连续成本 357435 generation tokens，相对 v8 连续基线 249148 增加约 43.5%；局部完整／增量依据对照分别 29909／15157，增量在该次减少约 49.3%，但最终谱系和元数据不完全相同。v9 全阶段 119 次生成／966332 generation tokens／4358 embedding tokens，失败和截断保留。[v9 结果](CONTEXTUAL_USER_MEMORY_V9_RESULTS_20260925.md)

当前有 State 取材控制，不等于已有完整决策控制：关注引用会跟随当前版本；coverage 变化主要整体失效；GAP 扩展主要沿同次排序继续取候选；支持组及反向维护属于独立 support 模式。新研究聚焦准确采用关系及其后续反馈。

**待检验假设：相同合法信息、CRUD 能力和执行保障下，单个可修订决策依据能否减少漏改、误改和重复核对，并保持任务完成与总成本合理。**

不主张首次统一 CRUD、首次把记忆作为执行状态、首次同次生成记忆与动作。ATMem 已在一次响应中生成更新状态和动作；StateMem、MAGE 等已有相关控制思想。文献边界与吸收方式在设计文档中列明。

## 2. V0 范围

### 2.1 本轮实现范围

1. TaskState 中增加一个可空的 active_decision；只有一个当前决策槽。
2. 五项语义信息：decision、scope、adopted_evidence、critical_gap、status。
3. 通过现有可见材料句柄，将采用关系绑定为准确对象版本及已交付范围；不自动追随最新版。
4. 已采用对象变化、来源替换／撤回、受管删除和适用性变化可产生重核通知；不自动判原结论错误。
5. 新观察与当前决策一起进入正常 Host 输入，让 Host 判断无旧依赖边的语义影响。
6. critical_gap 可驱动一次新的检索请求，区别于继续展开旧排序；复用原检索器及材料预算。
7. state_delta 与普通 ReAct action 同一次生成；无变化为 null，不增加固定 State 或审核调用。
8. 接入现有 checkpoint、同轮恢复、最终回执、有效查询与成本记录。

V0 的“选择性”首先表示：某项无关记忆变化不必使唯一当前判断重核；有关变化可触发重核。**V0 不证明多个并行决策之间的选择性传播。**

### 2.2 延续的边界

- Lab-only；ordinary 保持默认，v10 候选独立配置；旧 State profile 和 H1–H6 冻结。
- 不增加 Agent、全局图、概率控制器、训练流程、新数据库或后台反思。
- 来源接收、语义记忆、决策依据、业务执行结果分开；决策状态不能授权业务或删除。
- RETRACT 是退出当前认识，DELETE 仍由可信生命周期上下文授权。V0 不新增普通路径的破坏性能力；旧普通 API 没有的操作不以设计表冒称已接通。
- 不把当前缺口直接当成持久化价值判据；当前不用的信息仍可值得 CREATE／REVISE。
- Host 与必要 LLM Judge 使用 vLLM；模型实验一个入口、并发 1。
- 累计调用、tokens 和复核次数保持 null，连续记账；单工作流容量与实际服务限制继续生效。
- 不改原题、历史、gold、评分规则或业务世界来制造机制触发；不运行全量测试或全量 benchmark。

## 3. 开发顺序与工作包

顺序为 A → B → C → D → E → F。A 是源码与参考材料准备，不运行新模型实验；B–D 完成开发及窄检查后，E 才选择并冻结小样本，F 才进行真实比较。

### A. 冻结接口与参考输入

核对基线源码、实际 vLLM/json_action 表达能力、来源可见性绑定、checkpoint 恢复和检索缓存。建立一份紧凑参考清单：论文版本、官方代码／数据地址、commit、许可证、实际使用文件与借鉴点；不复制整套外部系统进入 Lab。

| 参考 | 本轮规划时状态 | 开发前动作 |
| --- | --- | --- |
| MiLAi v9 | 本地源码、配置、结果和冻结身份已核对 | 保持旧制品，建立 v10 新身份 |
| MERIT | 本地已有固定 checkout 与既有适配器 | 复用原始 arc/world/checker，核对 hash |
| AgeMem、ProactiveMemory、MemTX | 本地参考目录已有 | 仅阅读相关接口，不接入训练／审核框架 |
| ATMem | 已核对 arXiv 2606.31612v2 的方法；未确认官方可下载实现 | 官方来源可得再下载；不能使用同名 AtMem 工程冒充 |
| StateMem／StateMemBench | 已核对论文；本地未找到相应 checkout，本轮未确认官方数据下载入口 | 核实作者发布、许可证和评分代码后再准备；目前不是已就绪测试集 |
| MAGE | 论文定位参照，本轮未下载实现 | 不依赖其运行系统，不下载 GUI／大模型环境 |

需要参照并移植的源码在对应开发开始前就位。StateMemBench 数据可用性单列，不阻塞纯接口开发；不可获得时标记相应实验未运行，不自行重造或悄悄换题并沿用其名称。既有 MERIT 回归不能替代状态机制测试。

**交付：**接口冻结说明、参考状态清单、源码身份；没有未经验证的下载 URL、虚构 commit 或“已复现”声明。

### B. 单决策依据与真实采用绑定

增加小类型及少量纯函数，区分 Host 语义字段与程序维护的决策代次、准确引用、失效原因。复用 MaterialView／HostSession 的真实交付信息，模型选择已发布句柄，不手写字符偏移或系统版本。

采用旧版形成的判断不得在记录更新后无声重新绑定最新版。重复材料不是独立证据；范围继承不等于本轮重新阅读。scope 保留自然语言说明，不扩建条件语言，不把字符串相等当成语义相同。

V0 状态只有 active、needs_recheck、deferred；无当前决策使用 null。移除业务前 resolved 示例：判断可用与业务完成分别记录。任务切换和单槽替换采用明确生命周期，未完成业务及持久维护仍由原系统持有。

**验收：**不存在未见材料／未来工具结果采用、最新版指针漂移、跨任务静默沿用或决策状态伪造业务成功。

### C. 同次生成、顺序执行与恢复

在现有 json_action 外壳加入 state_delta，继续保留 tool／arguments；不把 sidecar 字段传给原生业务工具。V0 只支持该传输，native 保持旧行为，新配置不支持组合时明确拒绝。

先完整解析并校验 state_delta 与 action，再保存本次判断、执行原动作。动作实际回执产生后，再反馈采用对象变化和新观察。finish_turn 的快捷分支同样消费 state_delta，不绕过验证。

保持业务执行前 intent、执行后先落真实 result 的顺序。恢复后只接续未完成部分，不能重放已结算业务来“同步 State”。状态和外部业务不是跨系统原子事务。

**验收：**同一次生成可更新依据并 SEARCH／REVISE／执行合法业务／终结；无变化不要求额外 state 调用；截断输出没有局部副作用；执行失败不会自动标记完成；真实结果保存后故障仍能续接。

### D. 选择性重核与缺口取材

已声明采用关系由程序比较准确版本、合法范围及现有生命周期变化。V0 只扫描一个决策的小引用集合，不新建全局反向索引。变化触发 needs_recheck，原因来自真实事件，清除标记需要 Host 重新声明判断和实际依据。

无旧边的新观察不经过排除式主题过滤：唯一当前决策随正常新观察可见，由同一次 Host 推理决定保留、调整、暂缓或新查询。程序不自动补语义边，也不新增候选审核模型。

缺口检索是显式工具动作：程序从 critical_gap 与已知事项 anchor 生成有限查询焦点，运行一次已有检索器。与“展开旧候选”区分并分别记录。检索焦点变化必须影响 read cache、expansion 身份和真实材料，不能只改变 trace 文案。

**验收：**有关变化触发、无关变化不强制全重核、新观察可改变旧判断、重新查询实际发生、同参数新焦点不命中旧缓存。字段出现或工具调用次数不算效果成功。

### E. 开发冻结后选择原生小样本

保留既有 MERIT 一个完整已暴露 arc 作真实业务回归；文档四轮仅在受影响路径需要时复用，不为增加通过数量重复运行。

StateMemBench 作为优先候选，取得官方数据后选择少量完整原生场景，初始建议 4 个，覆盖应变、应保持及需重算。具体 ID、原始文件 hash、完整会话边界、原评分入口和适用事件在开发完成后冻结，当前不伪造清单。若这 4 个场景没有目标机会，先记录机会缺失；不改题、不强迫模型制造先错后改。

开发诊断集与未暴露确认集分开。原题历史不删减，不改变到达顺序；检索分块规则各臂相同，来源范围保持真实。oracle 与事后事件标注均不得进入 Host。

**交付：**小样本 manifest、合法输入／评分分离、机会审计和运行身份。无法取得数据或没有适用事件，写清证据不足，不扩大到其他 benchmark 补分。

### F. 四个研究问题，按阶段执行

| 实验 | 匹配条件与干预 | 解释边界 |
| --- | --- | --- |
| E1 表示与整体价值 | 强 ReAct 工作笔记 vs 单决策依据；相同材料、工具、预算、日志与恢复 | 若同时启用反馈，是整体比较；不能独占归因为表示 |
| E2 缺口 Attention | 相同决策表示和反馈，普通显式查询 vs gap focus | 普通臂也允许 Host 改写查询；需排除仅提示更好的解释 |
| E3 自动重核 | 相同表示、取材和新观察，仅关闭／开启依据变化自动通知 | 关闭的是候选通知，不关闭权限、删除、版本和来源有效性 |
| E4 持续维护 | 按需重建 vs 持续保存依据，共享信息可访问性与执行保障 | 计算完整历史输入及维护费用，不用调用次数替代成本 |

首先执行 E1 的小样本比较；如果真实采用、定向查询和重核机会仍未出现，先定位代码／输入／Host 行为，不盲目跑齐四组。E2/E3 复用同一冻结样本与适用前态；E4 仅在原生轨迹确有持续复用机会时开展。这是证据驱动的顺序，不是新增累计调用硬停止。

N=1、2、4、8 等只作为自然连续前缀的汇总点；不能重复同一问题、增加合成问题或跨重置副本冒充连续复用。原始任务只有较短序列时如实报告可得前缀。

未执行的实验保留 PLANNED／NOT_RUN；负面结果允许研究结项，但工程未接通不能标成工程通过。

## 4. 代码结构与状态所有权

| 边界 | 主要位置 | 约束 |
| --- | --- | --- |
| 小类型与纯状态变化 | contextual_memory/models.py、新 decision_basis.py | 唯一当前槽；不复制 memory store 或 visibility ledger |
| 主存储与变化反馈 | contextual_user_memory.py | 复用真实写入、生命周期和 checkpoint；不做大类整体搬迁 |
| Host 动作封装 | runners/contextual_host.py | 同次 delta＋action；普通与 finish 统一消费；保持业务参数原样 |
| 引用绑定与模型视图 | contextual_memory/material_view.py、runners/contextual_session.py | 精确采用和可见范围共用现有绑定 |
| 查询与缓存 | contextual_memory/query_context.py、Host read cache | 焦点投影为真实请求，不把全部 State 拼入 query |
| 持久恢复 | contextual_runtime_store.py、contextual_agent_tasks.py | 新字段显式恢复；业务日志顺序及任务身份保持 |
| 配置与冻结 | 现有准备／冻结工具和新候选配置 | 新源码文件纳入 hash；不复用 v9 方法身份装载不兼容库 |
| 评估 | 现有 MERIT runner、必要原生数据适配器 | 模型输入不带 gold；不另造 benchmark 平台 |

详细字段、动作顺序、缓存和失败语义以[设计文档](MILA_CONTEXTUAL_USER_MEMORY_V10_DECISION_BASIS_DESIGN_20260925.md)为准。

## 5. 必要窄检查

优先复用既有检查，只补 benchmark 无法观察的边界：

1. 准确版本／已读范围绑定；仅链接、未交付新结果和跨用户引用不能成为新采用依据。
2. 被采用对象变化、无关对象变化、独立支持仍在；重核不等于自动撤回。
3. state_delta 与动作同次执行，非法包不产生部分执行；finish 走同一合同。
4. 同参数但焦点变更的检索缓存；有效 query 和结果集合可核对。
5. checkpoint 恢复、task 切换及受管删除清理；State 不恢复已删除正文。
6. 业务结果已保存后中断，恢复只完成维护和决策续接，不重做业务。

对新 schema 使用现有部署 vLLM／xgrammar 做必要窄表达探针；不以 JSON 类型检查代替真实 Host 使用。运行受影响静态检查；只有包边界或打包改变才扩大相应检查。不运行全量 pytest、构建或大规模随机测试。

## 6. 指标与因果边界

每个真实机会记录：材料合法可见 → Host 声明采用 → 程序准确绑定 → 变化／新观察 → 重核或保留 → 后续查询／写入／业务动作。用户要求或源码强制出现字段不算方法收益。

重核分为结构通知、Host 实际重核、重核后的行为三个层次。通知次数不能当成执行次数；无动作改变也可能是正确重核。Precision／Recall 的分母必须来自独立的“需要重新判断”标注，不能由方法自己的 critical_gap 或最终动作是否变化定义。没有足够原生标注时报告机会表与 unknown，不制造精确分数。

同时记录原生任务结果、过时判断复用、不当修改、有效信息保留、未完成项，以及新观察纠正错误 State 的实际案例。假定正确 State 的机械测试不证明语义能力。

费用分离摄入／作答／决策维护／评分，分列输入、输出、embedding、缓存、失败与重试；同次生成依然计入 State 字段和反复注入的 tokens。v10 新账本从零记录本轮新增量并引用历史总量，不覆盖或清零旧费用。公平比较共享源码配置约束，但不强迫两臂调用数相等。

## 7. 开发安排与性价比

常规开发 Sol xhigh；窄而明确的机械任务可用 Luna max，下载／用户指定发布沿用 Luna high；Astra xhigh 仅处理具体难题，如动作前后状态顺序或实验不可识别问题。不安排常驻审核代理。

若开发轮明确采用并行代理：B 的纯类型／转移与 E 的只读数据适配准备可分工；Host、核心存储、会话持久化由一个集成人统一改动。先约定接口再集成，不让多个代理同时改主类和 Host。模型运行继续由单一控制入口调度。

起草阶段的“仅文档”约束由用户本次执行指令取代。常规代码由单一 Sol xhigh 集成，Luna high 负责必要的官方参考下载；模型调用由根控制器串行调度。已有用户授权的 Git 发布仍由 Luna high 执行。检查由具体问题驱动，不为了清零负面结果反复运行同一配置。

## 8. 完成条件与停止扩大范围的条件

| 维度 | 所需证据 |
| --- | --- |
| 工程完成 | B–D 真实接通，必要窄检查通过，新配置可准备和恢复 |
| 真实可操作 | 同一 Host 在正常 ReAct 响应中生成并消费依据，非额外强制状态仪式 |
| 机制可达 | 至少可核对一条准确采用 → 变化 → 重核 → 后续使用链；适用机会和失败保留 |
| 任务行为 | 原生评分、实际动作与维护状态分别报告；未完成不混入判错分母 |
| 方法收益 | 与强基线在相同信息条件下比较质量和完整成本；未占优就保持 ordinary 默认 |
| 范围控制 | 无新候选堆叠、数据修改、Product 迁移或全量测试 |
| 交接 | 最终源码／配置／输入身份明确，失败及费用可追溯，待运行项如实列出 |

状态依次区分 PLANNED_NOT_STARTED、IMPLEMENTED_PENDING_SMALL_VALIDATION、SCOPED_VALIDATED_EFFECT_UNESTABLISHED、COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT。只有实现、运行与对照各自的证据成立，才可提升对应结论；任何状态都不等于 SOTA 或一般可靠性。

**当前状态：`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`。A–D 完成并通过窄检查；R1 的 notes 5/5、basis 3/5 且 basis 全 null 作为历史失败保留。R2 在同一已暴露原生 arc、另一冻结身份下为 notes 5/5、basis 4/5，两臂均 7/7 Host complete；basis 实际完成准确采用→退款新观察→同 decision 重核→读旧卡→REVISE 提交的一条链，但自动旧版本通知仍无真实触发。basis 的 generation 费用高于 notes 约 125.11%，故不能据此主张方法收益或改动 ordinary 默认。E2／E3 未做匹配消融、E4 无自然持续窗口、StateMemBench 官方数据／许可／scorer 未取得，均为 NOT_RUN；完整费用、拒绝和截断保存于[R2 结果](CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)。此状态仅表示受限目标已诚实结项，不表示一般可靠性或 SOTA。**
