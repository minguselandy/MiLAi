# MiLAi v13.1：可用性优先的开发与实验规划

日期：2026-09-30  
状态：DESIGN_ONLY / NOT_EXECUTED  
范围：MiLAi-Lab；不自动修改 Product、GitHub、服务或现有实验状态。

> 目标：基于已有 MiLAi，先交付可使用的记忆闭环，再以公开任务、强简单基线和可归因机制实验决定哪些设计值得写入首篇论文。新颖性是待验证的假设，不是保留模块的理由。

## 0. 依据、版本和本轮边界

本规划依据用户提供的 `milai.txt`、只读核查的 MiLAi 当前 main 和外部官方仓库／论文。用户材料 SHA-256 为 `115cad8d34fa84c8086d13933e38af6ebf7455cc784196139de28a7dda4348cc`。

2026-09-30 读取 GitHub main 的 commit 为 `255dfcde5d73b9fc800cdd7f866460a09908c12f`。当前状态页仍记录实验 paused、研究未完成、Product NO_GO；代码整理不能被描述为方法效果提升。[S01–S03]

本规划没有运行模型实验、安装外部 baseline、复现论文分数或审查私有原始轨迹；外部可运行性尚须在 P3 验证。文中的规模、门槛和接口均是建议，不是已完成能力。

### 0.1 保留用户 v13 的主线

Grounded Memory、Verified Object References、Semantic/Episodic、Grounded Revision、Lifecycle Recovery；保持一个逻辑 MemoryService，不增加互相竞争的长期事实系统。[S00]

保留“先找首个真实断点”“程序处理确定性事实，模型处理语义选择”“不以 gold、隐藏标签、静默模糊修复、事后答案改写和 reviewer loop 换分”“正确 Memory 存在后才考虑 Attention”等原则。[S00]

### 0.2 相对于原 v13 的显式补充

原 v13 的 ref 检查只验证存在性和 owner，不验证自由文本是否受回执支持。本规划将其保留为 **Ref-only 独立条件**，另提出 **Field-grounded 候选**：只对有限的机器可读操作字段建立确定性支持关系。不得把后者写成原方案已经包含或已经实现的功能。

新增两条实验边界：公开原生业务工具评测与 Verified Ref 扩展分表；可用性通过与论文优势通过分开。

新增开发反思协议；“反思性”首先指研发过程的竞争解释、可证伪实验和失败保留，不默认引入额外 reflection agent。

## 1. 目标、非目标与三种验收

### 1.1 使用目标

一个使用者可以自然地要求保存偏好、查询旧信息、修订偏好、继续未完成的业务任务；不必了解 UUID、source_ref 或内部状态机。系统应该对“已保存”“仅保存原始内容”“整理尚未完成”“实际业务结果未知”给出不同、真实的回执。

### 1.2 研究问题

- RQ-G：真实事件和字段支持约束是否减少无依据操作事实的持久化与传播，同时保留有效信息？
- RQ-S：类型与显式 scope 保留是否减少过度泛化、过期偏好误用，且不损害正常个性化？
- RQ-L：依据真实结果进行修订，是否提高 partial／unknown／restart 后的完整任务完成率？
- RQ-C：上述收益能否在相同可见证据、工具与计算边界下超过强简单方案？

### 1.3 三层门禁

| 门禁 | 检查什么 | 不代表什么 |
|---|---|---|
| Engineering-valid | 数据身份、真实持久化、隔离、成本、恢复和评分链条可用 | 不代表模型全对 |
| Usability-ready | 正常任务大部分可顺利完成；失败可解释并可合法继续 | 不代表显著优于 baseline |
| Research-supported | 独立样本和公平对照支持明确增益或成本—质量权衡 | 不自动构成 Product 发布验收 |

机械隔离、虚假成功回执、泄漏或评估错误是受影响实验的硬阻断。普通语义答错不是停止采集全部公开安全任务的理由。不能设置“所有任务先满分”才能开始比较。

### 1.4 首篇论文不做

不再次大规模整理目录；不重新搭 Agent 框架；不同时引入多模态、RL writer、多 agent verifier、图数据库迁移和独立 Attention。暂不声称解决任意自然语言幻觉、所有权限问题或通用 exactly-once。正式数据不能成为提示优化材料。

## 2. 可用性优先：具体要求

| 能力 | 开发验收情形 | 失败时的行为 |
|---|---|---|
| 记住 | 用户明确要求保存；工具回执与持久记录一致 | 写入失败必须说明；不能自称已记住 |
| 找到 | 新会话检索旧偏好、事件、对象 | 无结果不能推出外部世界不存在；必要时合法查询 |
| 改正 | 新偏好替代旧偏好；旧版本仍支持历史问题 | 冲突未解决时保留冲突，不默默删掉证据 |
| 用对 | 一次性群体需求不升级为个人长期偏好 | 保留范围或说明不确定，不笼统拒绝使用全部记忆 |
| 继续 | partial 后仅执行剩余步骤 | 已完成业务不重做；unknown 先 discovery |
| 重启 | 关闭真实进程并重新连接相同持久资源 | 从 journal 和已提交记录恢复，不依赖 Python 内存 |
| 解释 | 查看来源、版本、未完成操作和拒绝原因 | 不要求用户手工构造内部 ref |
| 降级 | embedding／抽取暂不可用 | 若原始事件已经成功持久化，可显式退化为原文／关键词读取；严格标记降级，不伪称语义整理完成 |

先用 6 个端到端开发故事打通闭环，再扩展为 24 个正常使用检查：保存、召回、更新、scope、对象继续、重启各 4 个。建议 **至少 22/24 成功**作为候选可用性门槛，并要求无跨 owner 暴露、无虚假保存成功回执。该数字是预先约定的工程目标，不是统计置信保证；必须同时报告完整结果，不能挑选“容易的 24 个”后声称泛化。

故障实验单独评价。错误提案可以在 sandbox 里发生以便诊断；真正会造成外部损失的工具不用于这轮实验。共同保护层可以阻断错误动作，但仍要记录模型原始提案。

用户体验可接受的额外动作是一次必要的只读查询或澄清，而不是无限重试。所有恢复、回退和附加生成都进入 trace 与成本。

## 3. 最小方法设计与接口

### 3.1 总体闭环

```text
公开用户消息／实际工具事件
  → 既有日志中的可追溯源事件
  → 可选语义形成 + 操作事实字段投影
  → 同一 MemoryService 的可检索记录
  → 普通 retrieval + 短期 working context
  → Host 提案
  → 共同业务权限／对象检查
  → 实际工具结果
  → 幂等修订／必要的 discovery
```

可把记忆逻辑表示为 `M_t = (N_t, O_t)`：`N_t` 为有来源的自然语言记忆，`O_t` 为从实际结果派生的操作事实视图。这只是一个服务内的逻辑视图，不创建另一套可任意写入的长期真相数据库。持久 journal 仍负责执行证据，不允许模型重写过去实际发生的事件。

### 3.2 建议的最小数据合同

| 对象 | 程序提供／检查 | 模型可提出 |
|---|---|---|
| SourceEvent | event_id、owner、session、来源角色、原内容哈希、真实 observed_at | 不允许编造来源身份 |
| VerifiedObjectRef | 由实际 lookup／receipt／可信应用绑定产生的对象身份 | 可选择已有 ref，不能生成新 external ID 冒充真实对象 |
| MemoryRecord | id、revision、source 关联、服务回执 | content、kind、scope 的语义提议、是否值得长期保存 |
| OperationalFact | object_ref、字段、值、来源字段路径、观察版本／时间 | 可建议关联；可执行事实字段最终须匹配实际支持 |
| RevisionReceipt | committed/no_change/pending/rejected、版本、真实效果 | 模型不能自报提交成功 |

这是概念合同，不要求一次把所有字段变成强制公共 schema。第一批优先复用已有结构，以 opt-in 元数据扩展；旧 content-only 记录仍可读，以 legacy/source-unknown 展示，不自动提升为可信操作依据，也不一次性覆盖历史数据。

### 3.3 不混淆三个维度

`kind = semantic | episodic` 表示记忆组织方式；`scope` 表示主体、群体／项目、情境和必要的时间范围；`basis` 表示用户陈述、工具观察、计划或推断。三者不能互相代替。

例如用户说“我更喜欢简短回答”，用户消息本身足以支持“用户表达了这一偏好”；不需要外部工具验证偏好。用户说“订单已经退款”，则只能先保存“用户如此陈述”，不能因此生成“业务系统已退款”的可执行事实。

### 3.4 Ref-only 与 Field-grounded

Ref-only 只检查来源和对象引用是否合法。Field-grounded 再检查有限操作字段，例如实际回执 `label_status=pending` 不能生成可信的 `label_status=completed`。

Field-grounded 不尝试证明整段自然语言为真。真实 API 也可能出错，因此保证的范围是“与指定工具合同下实际观察一致”，不是世界真理。仅在 schema／工具合同公开定义的字段上实施映射；不从 gold、hidden DB 或目标答案补全字段。

自由文本可以保留计划和解释，但不能覆盖已绑定字段。若正文和字段冲突，保留原提案作为诊断证据，明确返回冲突回执；不能事后把模型答案改成正确答案。

### 3.5 对象、权限与时间

对象存在、owner 可见、操作获授权、当前状态适用是四个检查。机器可读的用户 ID 默认是查询线索，不自动证明对象真实、归属或授权。

旧回执保留为历史观察；执行当前状态敏感动作时按工具合同进行 live discovery 或版本前置条件检查。不采用“所有任务最新永远正确”的规则，历史查询应允许检索旧版本。时间来自输入／应用；缺少绝对锚点时不把 Friday 强行转换成运行当天推导的日期。

### 3.6 写入职责：先区分捕获与语义形成

原始事件的确定性捕获不等于新加一个语义 writer。先复用已存在的日志与回执，保证事件未丢失；语义上什么值得记仍由现有 Host／writer 负责。

如果出现“用户要求保存但无写入提案”，先做指令、工具可见性和回执使用诊断；不要直接加免费后台 writer。确需回合边界形成时，建立独立 `MatchedCadence` 条件，与原自主写入条件分开比较并计费。

### 3.7 修订与恢复

至少区分 confirmed、partial、known-no-effect、unknown，另保留业务当前状态与历史观察的区别。修订是依据新结果追加或替代当前视图，而不是抹除失败历史。

重点验证三个崩溃窗口：业务成功但回执未持久化；回执已持久化但 Memory 未修订；Memory 已修订但应答丢失。unknown 不允许盲目重复 mutation；先调用公开 discovery。只有业务后端提供合适幂等或可验证无副作用合同，才允许对应重试。不要把日志去重宣传为跨系统无条件 exactly-once。

Memory 更新使用版本检查／原子提交等既有 Store 能力；重复消费同一真实回执不产生重复事实。并发能力只声称实际测试过的范围，首批多方法按隔离资源运行。

## 4. baseline 调研、选型与身份

### 4.1 强简单对照

| ID | 方法 | 必须实现的内容 | 作用 |
|---|---|---|---|
| B0 | NoMemory | 新会话无持久记忆；合法当前业务工具仍可用 | 记忆必要性／任务泄漏检查 |
| B1 | RawDialogue / FullHistory | 原始角色、时间、工具回执；容量不足显式报告 | 完整证据参照；不声称一定是性能上界 |
| B2 | StrongRawRAG | 原文分块、BM25+dense、固定融合、共同材料预算 | 主要强简单基线 |
| B3 | RollingSummary | 同模型实际滚动摘要，同一闭合边界，不看未来问题 | 低成本维护对照 |
| B4 | Ordinary-Matched | 现有自然语言记忆，匹配形成时机和证据 | 隔离结构／写入合同；原 Ordinary 另保留 |
| B5 | Prompt-only | B4 加“保留来源／限定，不编造结果”的同一写入提示，不做新绑定 | 排除只是提示改善 |
| B6 | Receipt-RAG | 原始回执检索+简单确定性状态投影+共同保护 | 对 Field-grounded／Revision 最关键的工程对照 |

B2 不能仅用随意设置的 dense top-3 冒充“强 RAG”。在开发集给 B2、B3、Ours 同样数量的合理配置候选；冻结分块、融合、top-k、预算。FullHistory 不能静默截断后继续称完整历史。

B6 是本项目需要实现并公开的控制方法，不是声称存在同名已发表框架。它获得与 MiLAi 同样真实回执和公开 schema，不能读隐藏状态、标准计划或 evaluator。

### 4.2 外部系统

| 系统 | 本次核实的官方能力／版本注意 | 规划位置 |
|---|---|---|
| Mem0 OSS | 当前 README 明确 ADD-only、新检索和 managed/OSS 差异；不能混用 2025 论文、2026 SDK 和云端成绩。[S04–S06] | 第一外部 baseline，复用既有适配 |
| SimpleMem-Text | 文本压缩、索引和检索；当前统一包还包含 Omni 与 EvolveMem，首调 API 可能选择不同后端。[S07] | 第二外部 baseline，先通过实际容量与持久化检查 |
| Hindsight | retain/recall/reflect，区分事实、经历、总结和信念；官方提供本地／服务接口。[S08–S09] | 来源／反思／可追溯性主张的近邻；小切片优先，不随意删 reflect 后声称完整复现 |
| HiMem | Episode/Note 两层与冲突感知再整合，官方支持 note、episode、all 配置。[S10–S11] | 若双类型是主要贡献，应加入其针对性对照 |
| A-MEM | 动态笔记、链接和记忆演化；集成库 README 明确另有论文复现仓库。[S12] | 条件性替补／结构记忆对照，不第一批新接入 |

**默认公开主表：**B1/B2/B3 + Mem0 OSS + SimpleMem-Text + Ours；MERIT 增加 B0。B4、B5 为机制表。Lifecycle 以 B2、B6、Mem0-TraceEqual、Ours 为四个主臂。

Hindsight 与 HiMem 不是任意互换：操作来源／证据—推断主张选 Hindsight 做最近邻检查；双类型主张选 HiMem。无法忠实复现某近邻时说明缺口并缩小对应主张，不用不相关弱方法替代。至少已有两种外部系统不意味着可以忽略最接近工作的创新性挑战。

### 4.3 接入时的硬检查

每个 baseline 都先跑固定微型用例：存储→重启→检索；偏好变更；相对日期；工具回执携带真实角色／ID；owner 隔离；失败后成本可追溯。

每个 arm 记录 upstream commit、安装版本、依赖锁／构建来源、模型、embedding、提示哈希、摄入时间、检索 API、参数、内部反思／重试、截断和后台维护。

既有 Mem0 源码同时有仅 ingest 用户+最终助手回复的 `after_turn`，以及保存原角色和工具结果为归档数据的 `add_archive`；后者说明 pin 忽略 tool role。[S06] 不能从一个函数推断整张旧表采用哪条路径。P3 必须沿实际 runner 追踪 wire input。新 trace-equal 对照使用有标记的无损归档包，保留来源身份，不伪装成用户亲口陈述，也不偷偷修改其抽取算法。

如果 API 不支持原始角色，以公开定义的字符串数据包承载并记录映射；若格式导致事实或来源丢失，修适配器后重冻受影响臂，而不是把丢失归因于算法。

外部系统产生答案的 `ask/reflect` 路径与共同 reader 路径应分表。只调用 retain/recall 的 Hindsight 应标为 backend 对照；只用 SimpleMem 文本后端不能引用 Omni/EvolveMem 分数。禁止把升级 SDK 后的新运行拼接到旧 pin 的结果中。

## 5. 保持创新性：最近邻与可证伪主张

HiMem 已有两层记忆与再整合；Hindsight 已区分证据与推断并支持反思；EAL-Bench 已研究记忆产生虚假权限以及来源门禁／事件溯源。[S09–S11,S15] 因此这些组件名称本身不是 MiLAi 的独立新颖性。

可争取的贡献是一个较窄的命题：**把真实执行结果与可使用的操作记忆绑定，并在普通任务和跨会话恢复中，以较少语义损失抑制错误事实传播。**它能否超越普通回执投影仍需实验。

| 可能的贡献 | 最直接的替代解释 | 必须安排的反证对照 |
|---|---|---|
| Grounding 减少错误记忆 | 只是提示更严／拒绝更多 | Prompt-only；有效事实保留；clean 任务效用 |
| Field-grounded 改善动作 | 只是多了工具 guard | 共同 guard 与对象接口；分别记错误提案和实际效果 |
| Semantic/Episodic 改善 scope | 只是文本更长或 scope 明确 | Type-only / Flat+Scope / Type+Scope，同预算 |
| Revision 改善恢复 | 简单 reducer 就足够 | Receipt-RAG；相同真实日志和 discovery |
| Attention 有用 | working-state 查询增强已经够用 | Q/W/A，同总计算预算 |

不预设每个模块都必须有正收益。若新模块没有可测的独立价值，保留简单工程实现或移除该模块的论文贡献地位。

## 6. 公平实验合同：三条轨道

### T1：公开任务的受控后端比较

保留官方输入、业务 schema、工具行为和原 scorer；使用共同 Host／reader 与明确的记忆后端。若 Agent loop 或记忆接口偏离原生，称“使用官方任务与评分器的受控后端比较”，不冒称完整 native 方法复现。

所有方法只接收当前已经发生的事件。未来用户消息不能被拼进检索 query；gold、rubric、hidden world、任务标准执行计划不进入 Host、writer 或 memory adapter。

### T2：机制实验

冻结同一份观察流或同一份 bank，只改变一项形成／呈现／修订变量。它可以低成本定位原因，但固定提案回放不能被说成真实 Agent 行为收益。

构建 source exposure registry：旧失败、旧 pilot、读过的题、用于写提示的历史都列为 development。test 按来源组划分，而不是按问题行打散。

### T3：Lifecycle 扩展

允许 Verified Ref、故障注入、重启与查询恢复；所有比较方法获得同样接口和保护。结果单列为 MiLAi 扩展，不能算官方 MERIT 原生分数。

### 6.1 两种历史访问设置

系统设置允许各方法按声明方式查询归档，全部成本入账；机制设置不额外给其他方法免费完整 checkpoint。StrongRawRAG 的原文库与 FullHistory 的完整回放本来就是它们的方法，不应人为删除。

NoMemory 保留正常 live lookup。若它也能完成任务，就报告记忆在该任务不是必要条件或只提供成本优势，不通过禁止正常工具制造依赖。

### 6.2 原生节奏与匹配节奏

系统表保留框架原生维护策略；机制表给各臂同一事件边界和同一证据。自动语义形成、自主写入、只读检索属于不同变量，不能打包后声称只比较结构化表示。

### 6.3 配置与预算

首模型复用实际已部署且工具链可用的配置；P0 读取实际服务与 prompt template，不凭历史记录假定服务在线。记录模型 revision、量化、tokenizer、chat template、thinking、sampling、上下文与输出上限。

官方 Judge 与本地诊断 Judge 分开；采用非官方配置时明确标为非 leaderboard 复现。第二模型家族在固定候选后进行，不为修单例盲目切模型。

先做相对宽裕的质量设置，再做联合 token/call 预算设置。记忆内部生成不能免费，也不应不透明地耗尽所有 Host 容量。各方法共同冻结 Host 和 memory 子预算及总上限；按实际花费报告成本—质量。预算耗尽属于该设置的系统结果，不能自动等同于记忆内容错误。

## 7. Benchmark 与证据映射

| 测试集 | 必做内容 | 能支持的主张 | 不能替代 |
|---|---|---|---|
| MemSyco | scope / valid selection / personalized use | 正确适用范围、更新、正常记忆效用 | 实际业务执行与重启恢复 |
| MERIT | 三领域、完整 arcs、dependent 与 updated-fact 分层 | 记忆对真实工具任务的效用及成本 | 新增 partial／unknown 的原生结论 |
| MiLAi-Lifecycle | clean+5种异常／变化结果；真实持久化和重启 | 操作事实保真、剩余任务与副作用 | 一般自然故障发生率 |
| EAL-Bench，条件性 | 仅当方法支持授权语义时跑原生对应 track | 授权记忆形成与行动传播 | 从自然语言授权凭空构造实际业务回执 |

MemSyco 官方提供 1,550 个样本；本轮选择的 scope 300、valid selection 350、personalized use 300，采用开放式判断，三任务分开报告。[S13] MERIT 提供三领域有状态任务和原生 checker。[S14] 本轮不为凑评测数量接入所有新 benchmark。

EAL 的 gold source gate／faithful memory 是诊断信息权限，不能作为可部署条件；授权合法使用与未授权提交分别报告。方法不支持授权语义时明确不适用，而不是另造一套 oracle 方法。[S15]

## 8. 开发工作包与文件归属

沿用 v12 的 ownership；以下新文件名是拟议位置，实施前检查现有模块，能扩展就不重复建文件。[S03]

| 阶段 | 交付 | 建议路径／归属 | 验收与下一步 |
|---|---|---|---|
| P0 冻结与盘点 | baseline identity、暴露清单、实际能力／成本配置 | contracts、harness、data/manifests | 可区分旧数据与新候选；原账本不清零 |
| P1 最小可用闭环 | 保存／查找／更新／来源回执；6故事 | memory、现有 Agent/MCP | 真实持久化及新进程读取；不等全部算法完成 |
| P2 Grounding 核心 | source/object refs、Ref-only、可选字段支持 | contracts/memory.py；application/refs.py（拟新增）；memory/strict_tools.py；methods | 合法引用不能掩盖错误字段；普通偏好仍可保存 |
| P3 baseline 对齐 | 强简单组、Mem0、SimpleMem、trace/cost 适配 | integrations/memory；现有 benchmark harness | 每臂固定微型验收；不能用缺依赖 skip 当成功 |
| P4 scope 形成 | flat/type/scope 因素分离 | methods；memory/presentation.py 只负责呈现 | MemSyco 开发诊断；不与 grounding/retrieval 同时改 |
| P5 结果修订／恢复 | 幂等投影、pending/unknown、三个崩溃窗口 | memory/revision_store.py；application/journal.py/recovery.py | 完整真实生命周期；保留未知／失败 |
| P6 未见 pilot／冻结 | 方差、成本、公平性和样本量决定 | runners/harness/data/manifests | 不看正式集；只冻结一个主方法版本 |
| P7 正式比较 | 三主评测、消融、第二家族固定切片 | runners 与离线 analysis/scorers | 所有预定失败与超限入表 |
| P8 收口 | 统计、反例、复现包、论文初稿 | docs/studies/analysis | 主张与证据逐条对应；Product 单独评审 |

P1/P2 是应用主线。P3 的 baseline 工程可与不同负责人独立推进，但不平行修改同一方法或同时耗用未冻结的推理服务。P4 在只读问答条件下不需要等待 P5 故障恢复满分。P5 复用已有 journal，不重写整个平台。

providers 保持通用；方法策略放 methods；runner 只组合。源码、评分器、工具合同的修改必须各自有身份，不能把修 scorer 当作方法提升。

### 8.1 机械测试最小集合

保存回执与实际 Store 一致；不存在／跨 owner／过期来源；真实 ref+错误字段；重复 receipt；revision 冲突；partial 子效果；unknown 查询路径；进程重开；降级路径；预算耗尽；未来消息不入 query；gold 只在离线 scorer；结构化输出与真实 HTTP 一致。

先单元／合同测试，再真实 SDK 与临时数据库的集成测试，最后少量真实模型 smoke。Mock 只能证明机械链路，不能证明语义质量。

### 8.2 使用门禁与发布边界

P1/P2 达到 24例正常使用门槛，可继续公开问答和 sandbox 工具比较；不是强制从此不准出现任何错误。若出现跨 owner、隐藏答案输入、评分器不可信、真实外部越权，暂停受影响路径并保持其他独立安全工作。

所有新策略 opt-in。旧方法冻结可回滚。持久数据迁移先在隔离副本验证，旧失败记录和历史报告不删除。Product 正式迁移、SLO、安全和兼容验收不作为首篇论文必须全部完成的前置，但必须单列状态。

## 9. 分阶段实验矩阵与规模

所有数字是预算起点，正式样本在 pilot 后、查看 test 前冻结。重复次数不增加独立场景数。

### 9.1 开发与 pilot

| 批次 | 数据 | 方法 | 主要目的 |
|---|---|---|---|
| D0 | 6 个端到端故事，继而24个正常检查 | 当前方法→候选 | 可用性，不计独立论文效果 |
| D1 | 旧 MemSyco 来源与 R2 原案例 | Ordinary、Prompt-only、候选 | 找首断点，保留已曝光身份 |
| Pilot-S | 60个新开发样本，每任务20 | Raw、StrongRawRAG、Summary、Mem0、Ours | 300个方法×问题评估；估方差和预算 |
| Pilot-M | 18个新 arc，领域／难度分层 | FullHistory、StrongRawRAG、Summary、Mem0、Ours | 90个方法×arc；不把 episode 当独立样本 |
| Pilot-L | 12个生命周期条件轨迹 | RAG、Receipt-RAG、Mem0-TraceEqual、Ours | 48条方法轨迹；验证真实链和副作用 |

NoMemory 的能力／信息泄漏诊断另以小固定切片执行，正式 MERIT 必须包含。SimpleMem 工程通过后用相同 pilot 来源试跑，不在已经看见某方法成绩后挑有利样本。

### 9.2 第一版正式规模

| 表 | 规模 | 方法数 | 计划执行单元 |
|---|---|---:|---:|
| MemSyco | 300个未曝光问题，3任务各100，按来源组去重划分 | 6 | 1,800个方法×问题；形成按唯一历史缓存 |
| MERIT | 90个新 arc，3领域×3难度×10 | 7 | 630个方法×arc；若原配置每arc5个episode，约3,150个episode |
| Lifecycle | 60个基础任务，每个 clean + 1个预先平衡分配的异常／变化条件 | 4 | 120个条件实例×4=480条完整轨迹 |

Lifecycle 的5个异常／变化条件为 partial、known-no-effect、unknown-effect-happened、unknown-no-effect、stale-observation。每种约12个实例；clean共60个。实际独立基础任务为60，而不是120，更不是480。跨条件分析按基础任务配对／聚类。若只使用极少数模板，必须披露，并对模板共享做敏感性分析，不声称跨任意工作流泛化。

这套生命周期设计是为了正常效用和故障鲁棒性配对，clean 与故障比例是研究设计，不代表真实生产概率。两个工作流至少各30个基础任务，目标、约束、对象关系应有实质差异，不能只有 ID 替换。

MERIT／MemSyco 的官方旧来源若已经暴露，正式样本须排除；“未见”只表示对本项目开发流程未见，不代表模型预训练绝对未见。公开数据可能有训练污染，该限制需披露。

### 9.3 第二模型家族与复现波动

主方法冻结后，在预先选定的60个MemSyco问题、18个MERIT arc、20个Lifecycle基础任务×2条件上确认。默认比较 StrongRawRAG、对应强简单近邻、Ours 三臂；Lifecycle 的近邻为 Receipt-RAG。

先区分 writer 固定、换 reader 的传播测试，与重新形成记忆、writer+reader 都换的端到端测试，两者不混称“跨模型复现”。不在新家族上调提示后仍叫独立确认。

对固定20%代表性切片增加预定重复，报告采样／服务波动；不能从多个结果选最好的一次。是否扩大为全量多 seed 由事前功效与预算决定，不以 test p 值临时加样本。

## 10. 关键消融与因果定位

### E-G：来源存在 vs 内容支持

同一批冻结的真实可见轨迹，比较 Ordinary-Matched、Prompt-only、Ref-only、Field-grounded。检验不存在对象、真实对象错误字段、过期回执、计划误写为完成等。再把各方法实际生成的 bank 固定给同一 reader，测端到端传播。

另设相同提案的 commit 检查实验，用于测 guard 行为；不能拿这组固定提案的结果代替自由 Agent 任务效果。

### E-S：类型 vs scope，最小2×2

| | 无显式 scope 字段 | 有显式 scope 字段 |
|---|---|---|
| Flat | Flat | Flat+Scope |
| Typed | Type-only | Type+Scope |

输入、模型、写入边界和材料预算相同；scope 由公开历史形成，不由 gold 填充。若 Flat+Scope≈Type+Scope，应把收益归为 scope 保留，而非双类型架构。可在容量允许时比较 all-delivered 与 retrieved，以定位形成和消费。

### E-L：Revision 的边际作用

固定共同 refs/guard/discovery，比较不开启结果投影、简单回执投影（Receipt-RAG）、完整候选。必须记录第一次任务原始结果，不能在重启后补造成功对象。

unknown 的世界实际结果只有 evaluator 与业务 world 知道，Agent 不得获知“该次已成功”的注入标签。后续用户请求使用中性表述“查看实际状态并完成仍获授权的未完成部分”，避免原 R2 那种先失败、下一句却预设已成功的混杂。

### E-A：仅条件启用的 Attention

只有正确记忆确已提交且普通查询在真实容量／适用范围下失效，才比较 Q=普通query、W=query+确定性working state、A=独立selector。预算计入selector生成；W≈A则删除独立selector。不能用随机噪声制造优势。[S00]

## 11. 指标与统计合同

### 11.1 主要指标

| 指标 | 计算与解释 |
|---|---|
| Unsupported operational claims | 无依据操作断言的接受比例；分被评价提案与最终记忆两个分母 |
| Supported-fact retention | 当前可见且任务相关的有依据事实中，被正确保留的比例；防止空记忆取巧 |
| Native task success | 原生 scorer 的原始成功定义；dependent、updated-fact、完整arc分开 |
| Wrong proposals | 错对象／重复／未授权或额外副作用提案；即便被guard挡住也记录 |
| Wrong effects | world实际发生的错误副作用；不与提案混为一谈 |
| Clean utility | 正常条件下完整成功、过度拒绝、额外查询与延迟 |
| Lifecycle success | 正确终态+正确剩余操作+无禁止副作用+最终回答不虚报 |
| Cost | memory与Host的全生命周期实际tokens/calls、embedding、冷启动、延迟、可测存储 |

“有依据”限定为对当时允许信息源与公开工具合同的支持，不把任何真实消息中的断言都当客观事实。自由文本由盲审辅助，无法判定保留 unknown；不能因为不易结构化就当没有错误。

### 11.2 配对与区间

按原始历史／arc／基础场景聚类做配对bootstrap，建议10,000次；报告差值、95%区间、分母。不同任务不合成无定义总分。预先指定少数主要比较，多个次要检验使用合适的多重比较控制；其余探索性分析明确标注。

“错误更少且没有明显伤害效用”不能用 p>0.05 代替。需要在开发后、测试前定非劣界，例如正常成功率下降不超过5个百分点；若样本无法支持该界，结论写“尚未证实非劣”，不写“无损”。5个百分点只是建议决策阈值，不是通用科研标准。

每条件12个Lifecycle故障样本只能支持有限精度的分类描述；不得把单个类别0次错误称为零风险。通过pilot估效应、方差与预算决定是否增大样本；不能固定宣称300题或90arc必然够发表。

### 11.3 故障分母

区分 completed-correct、completed-wrong、budget-exhausted、provider-error、not-run。任务预算耗尽进入对应预算实验的完成率。提供方故障按预注册同一规则重试或单列；保留首次调用和总成本。未完成项不能删掉后只报条件正确率；给完整计划分母、覆盖率和必要的上下界。

### 11.4 Scorer 与人工复核

MERIT原生checker不改；可补充动作审计而不覆盖原分。MemSyco保持任务专属Judge合同；同族Judge诊断与官方／独立Judge结果分开。建议盲审固定分层样本，覆盖所有方法的成功、失败和不确定，并报告标注协议与分歧；只审自家失败不合格。

## 12. 成本与执行顺序

现有连续账本不得重置。当前状态页记录累计6,145次generation、11,407,086 generation tokens、416,930 embedding tokens；这些是历史成本，不是本规划预算。[S02]

总成本必须覆盖 capture相关I/O、形成、embedding、检索、重排／反思、Host、revision、恢复和重试。Judge作为评测成本另列。不能把token差直接称为GPU小时或美元节约；未实测就标未测。

每类任务用pilot测每方法的中位与尾部tokens/calls、wall time、失败比例，再冻结预算；不直接搬用作者声称的整套benchmark美元价格。模型价格、资源单价和总可用预算未知，因此 accompanying YAML 保留待填字段，不伪造可执行数值。

质量设置允许合理完成算法；预算设置在共同总tokens和阶段容量下画质量—成本曲线。方法执行顺序按场景分块随机化／交错，固定服务并发；不要让一种方法总在系统空闲时跑，另一种总在拥塞时跑。

按方法+source hash+模型+配置缓存 question-free formation。复用bank可减少下游重复，但冷启动完整成本、后续边际成本和实际本次账单分别记录，不隐藏离线形成开销。

## 13. 反思协议：每次失败只定位最早断点

必看链路：

`source/event → proposal → committed memory → delivered material → business action → final answer`

| 最早观察到的断点 | 优先检查 | 不应直接做 |
|---|---|---|
| 没有生成写入提案 | 当前义务、工具描述、形成时机 | 增加第二套Memory DB |
| 提案有来源但提交错 | schema/ref/owner、原子性、回执 | 增加Attention |
| 已提交内容丢scope | 形成输入、压缩与范围表达 | 增加top-k假装修复 |
| 正确记录未交付 | 检索、权限、材料预算、截断 | 改原始事实bank |
| 已交付却误用 | 当前/历史区分、reader工具决策 | 继续增加writer数量 |
| 动作正确但回答错误 | 实际回执消费和生成 | 事后强改答案 |
| 任务失败只因预算 | 阶段容量、方法内部调用 | 把容量失败说成语义无效 |

每轮必须填写：观察到什么；最早断点；仍有证据支持的竞争解释（若已唯一定位，不硬造第二种）；最小区分实验；哪些变量不变；什么结果会否定当前解释；费用上限；停止／缩小主张条件。没有可区分的解释就不立即改大架构。

开发日志中的“反思”不进入运行时、也不读入测试答案。若以后验证模型自我反思，设独立0次/1次边界反思消融，同一Host、无额外judge、计入预算；反思只能提出解释或策略，不得创造源事件、回执或授权。它不是首批必需功能。

## 14. Go / Pivot / Stop

| 观察 | 决策 |
|---|---|
| 引用／隔离机械正确但正常任务经常不能用 | 先修发现、回执和交互，不加更强拦截或新算法 |
| 只比旧Ordinary好，强RAG/摘要不差 | 作为工程修复，暂不升级成新方法优势 |
| Prompt-only达到同样效果 | 收缩机制创新；检查是否有更窄稳定收益 |
| Ref-only挡住假ID，真实ID错误状态仍通过 | 保留Ref-only边界，检验Field-grounded而非夸大grounding |
| Receipt-RAG同样或更好 | 接受简单方案；删除不必要语义环节或改论文问题 |
| 安全改善，正常任务明显退化 | 报告权衡、优化可用性；不称全面优越 |
| Scope完整但reader仍错 | 做冻结bank消费诊断，之后才考虑working state |
| Q/W已足够 | 不开发独立Attention |
| 独立集／第二家族不复现 | 披露失败并缩小范围；不回流test继续调参 |
| 必须依靠gold／隐藏DB／静默修复才能工作 | 停止该方案，修实验合同 |

“负结果也能投稿”不是质量保证。无稳定收益时应重新审视问题、方法和论文定位，不能自动把每次失败包装成贡献。

## 15. 首篇论文收口与复现包

方法部分只保留实验证明有作用的机制。建议三项贡献：清晰可复现的失败机制；最小干预方法；普通效用与生命周期错误的公平验证。不是把5个模块命名为5个创新。

建议结果资产：

- 公开任务主表：MemSyco三任务、MERIT各层与成本。
- Lifecycle主表：clean、各故障、提案/效果、完整恢复与成本。
- 消融表：Prompt-only、Ref-only、Field-grounded、scope2×2、Receipt-RAG。
- 成本—质量与失败链图：明确冷启动、后续成本和unknown。
- 第二家族固定确认与反例；所有未完成／非劣不成立如实列出。

复现包应包含源码身份、依赖锁、baseline身份、公开数据抽样清单、原始合法输入、prompt/schema哈希、匿名trace或可公开等价资产、评分脚本、成本账本、模型服务配置和运行说明。凭证、私人对话、完整私有DB不得提交；公开与私有可复现边界分开说明。不可提供的数据不能被描述为完全公开复现。

CCF分类、投稿窗口、篇幅和学校认定需要提交前按当时官方要求核实，本规划不把未经核实的会议或截止时间当作既定目标，也不保证录用。

## 16. 下一批最小工作单

下一批只交付 P0、P1 与 P2 的最小合同：

1. 冻结真实main/环境/来源暴露与历史成本。
2. 保留旧方法，打通6个真实保存—读取—更新—重启故事。
3. 实现／复用SourceEvent和VerifiedObjectRef；将Ref-only独立成候选。
4. 对两个公开schema字段实现有限的Field-grounded原型，不做全自然语言verifier。
5. 运行零模型机械检查和少量真实链路诊断；保留所有失败。
6. 在baseline分支核对Mem0/SimpleMem实际摄入与成本路径，尚不启动大矩阵。

不在这一批同时引入Attention、第二模型、多个新外部框架、全量benchmark或Product迁移。第一份结果报告必须同时回答“用户能否正常使用”和“哪个假设尚未成立”。

## 17. 文献与核查来源

以下为本规划实际使用的原始来源；官方README的营销性性能与云端分数未作为本项目预期收益。外部仓库正文读取日期为2026-09-30；其main尚未作为实验依赖冻结。

- [S00] 用户附件 `milai.txt`，SHA-256 见第0节。Grounded Memory v13设计、历史结果和开发原则。
- [S01] MiLAi main分支元数据：`https://api.github.com/repos/minguselandy/MiLAi/branches/main`。
- [S02] MiLAi当前状态：`https://github.com/minguselandy/MiLAi/blob/255dfcde5d73b9fc800cdd7f866460a09908c12f/MiLAi-Lab/docs/LAB_CURRENT_STATUS.md`。
- [S03] MiLAi项目地图：`https://github.com/minguselandy/MiLAi/blob/255dfcde5d73b9fc800cdd7f866460a09908c12f/MiLAi-Lab/docs/PROJECT_MAP.md`。
- [S04] Mem0 README，blob `9a81e74effacbd7433e91b6c1fcc907f110d4773`：`https://github.com/mem0ai/mem0/blob/main/README.md`。
- [S05] Mem0原论文：`https://arxiv.org/abs/2504.19413`。仅作论文版本与当前SDK区别依据。
- [S06] MiLAi Mem0 adapter，blob `91f63296d95d30c05ba4a652d767bd4f88679ca2`：`https://github.com/minguselandy/MiLAi/blob/255dfcde5d73b9fc800cdd7f866460a09908c12f/MiLAi-Lab/src/milai_lab/integrations/memory/mem0.py`。
- [S07] SimpleMem README，blob `7fbd7d8ea0acb4735b8e994af1915e696852f181`：`https://github.com/aiming-lab/SimpleMem/blob/main/README.md`；论文：`https://arxiv.org/abs/2601.02553`。
- [S08] Hindsight README，blob `250a2e8eca4fccae242a9b7c90ba5d17fe8f8919`：`https://github.com/vectorize-io/hindsight/blob/main/README.md`。
- [S09] Hindsight论文：`https://arxiv.org/abs/2512.12818`。
- [S10] HiMem README，blob `7a894eb1bf5488e64c04c83cdd696cf58a4073c7`：`https://github.com/jojopdq/HiMem/blob/main/README.md`。
- [S11] HiMem论文：`https://arxiv.org/abs/2601.06377`。
- [S12] A-MEM集成仓库README，blob `c2c7eb0f255dab75eed8e3e3bdaa6ec0ca61bda0`：`https://github.com/agiresearch/A-mem/blob/main/README.md`；该README明确指向论文复现仓库 `https://github.com/WujiangXu/AgenticMemory`，本轮未审计该复现仓库全部代码。
- [S13] MemSyco README，blob `9fccf132ef315b1383cd1177e3f9e21ce16c4ffd`：`https://github.com/XMUDeepLIT/MemSyco-Bench/blob/main/README.md`；论文：`https://arxiv.org/abs/2607.01071`。
- [S14] MERIT README，blob `397fdb623209f23dd5b706eda75fb1acfbb05d3c`：`https://github.com/smshweta/merit-bench/blob/main/README.md`。
- [S15] EAL论文与方法细节：`https://arxiv.org/abs/2609.01836`；`https://arxiv.org/html/2609.01836v1`。本规划仅借鉴其原生定义和诊断边界，不声称已运行其作者实验。

## 18. 总结

先做可使用、可解释、能恢复的最小闭环；在同样真实信息和工具条件下对照强RAG、摘要、Mem0、SimpleMem和简单回执投影。将提示、类型、scope、来源存在、字段支持、结果修订逐项区分。不能证明独立价值的模块，不应为“保持创新”而强行保留。
