---
goal_id: MILAI-SEMANTIC-BOUNDARY-HARDENING
version: v14.0
date: 2026-09-26
status: PLANNED_NOT_STARTED
planning_delivery: COMPLETE
implementation_authorized_this_round: false
baseline_commit: 488a4291925c607f6d0dc313a7dcbaf1906a6fad
baseline_source_mapping_sha256: 5c92005f5e7f2b36c6716dcd8cf5ce1c05091f06fe47141c9f37474c6ff9a773
scope: MiLAi-Lab
generation_request_cap: null
generation_token_cap: null
embedding_token_cap: null
verification_count_cap: null
---

# MiLAi Lab v14 Goal：稳定普通路径的语义边界

**开发目标：让同一 ordinary Host 区分“现在能否执行、以后是否需要记住、实际执行了什么、哪些只是本轮引用”，修复 v13 已观察到的语义缺口，再判断是否具备恢复 State–Attention 研究的条件。**

用户本轮选择“先生成 Goal 与详细设计”。本文件是待实施计划，本轮未修改运行代码、生成诊断数据或调用实验模型；不能将规划交付标成 v14 开发完成。合同、字段与算法细节见 [详细设计](MILA_CONTEXTUAL_USER_MEMORY_V14_SEMANTIC_BOUNDARY_DESIGN_20260926.md)。

## 1. 基线与问题范围

已核对本地 main 为 488a429，开始时工作区干净；46 份运行文件匹配 v13 最终源码映射。复读 v13 报告、紧凑清单、首集快照及当前维护、Host、来源交付、持久库和写入合同。

| 已有能力／结果 | 本轮处理 |
| --- | --- |
| 正式 prepare／MERIT runner、原卡修订、intent/result、恢复、repair_of | 保留；无新故障不重写、不重复优化 |
| v13 最终完整 arc：native 4/5、dependent 2/2、Host／维护 7/7 | 作为历史开发证据，不能解释为所有语义正确 |
| 首集两轮均零写入，持久快照 cards 与 sources 均为空 | 首次跨轮价值判断是 P0；后续重述补建不算首次成功 |
| R1 声称已升级审批，但只有查询与消息回执 | 处理执行依据及叙述一致性；与政策／工具／checker 冲突分开 |
| R1 永久正文含会话 mN；R2 没有 | 处理引用与文字的边界，不按字符外形全局清洗 |
| v13 repair guidance 自然触发为零 | 冻结；保留窄检查，不为证明收益故意制造更多运行失败 |
| fixed contract 本地估计约占 R1 输入 49.1% | 先核对重复位置，再做不损失合同的压缩；不能认领全部可节省 |

v13 的 56 次生成、345375 generation tokens、2797 embedding tokens 保持封存；v14 未来使用新连续账本，开发代理费用另列。历史失败和原生分数不回写。

## 2. 四项验收边界

1. 暂缓执行不等于没有跨轮价值；未来约定、未履行事项和要求可需要保存。
2. 意图、确认消息、工具调用成功、业务目标完成分别表达；只有相应回执证明相应执行。
3. 结构引用与持久文字分开；真实原文中的型号或代码不能因碰巧叫 m4 而丢失。
4. native success、维护合同 complete 和记忆语义正确分别验收。

程序证明身份、可见范围、真实提交和执行记录；Host 判断未来用途、当前事项含义及表达。结构化检查不能升级成任意自然语言正确性的证明。

## 3. 实施范围

### A. 收敛两条生命周期轴与现有 frontier

不增加第二份 frontier、长期 State 或语义分类 Agent。扩展既有 semantic_frontier／semantic_finish，继续由 HostSession.maintenance 持有本轮处置，RuntimeStore 持久化原会话状态。

- 执行事实沿用现有 succeeded／failed／unknown 与原始回执；尚未尝试、用户要求等待等仍是有来源的业务说明，不自动改成执行事实。
- 未来用途使用 task_local／cross_turn／durable／none 的语义区分。cross_turn 与 durable 在现有存储中均可落 durable，但保留事项范围；不为四个词新增四套存储或 TTL 系统。
- 可信来源的 persistence_required 继续是接入约束，不能从 benchmark gold 注入，也不承担模型未来价值判断。
- 新增直接用户观察始终进入处置候选。不能只依赖 Host 主动提名，否则首次漏存仍没有机会被发现。
- 工具结果没有“例行、无未来价值”的自动语义标签。已知操作性质只可来自可信工具定义；未知不由工具名称或正文猜测。业务结果复用既有投影，避免在两个地方重复展开。
- 成功写入的事实与来源联系由程序计算。它只减少重复填报，不自动宣布整条消息中所有意义都已吸收；同一来源可含多个独立事项。
- Host 仅处置剩余候选，并在结束时确认当前相关变化是否已经处理。保存行为仍通过 memory_save，不新增反思调用或前置审批阶段。

**验收：**不保存首次未来约定时，必须留下可定位的语义处置；选择跨轮保存却无真实持久结果不能被全局 processed 淹没。task-only 与显式不保存要求不因“未来可能有用”自动持久化。业务等待已记住时，不误判为维护未完成。

### B. 收敛真实业务回执投影与终结引用

现有 semantic_frontier 已接收 business_outcomes。沿这一位置精简并补足事项身份、执行状态和已交付回执入口，不再增加一块内容相同的 Execution State。

- 从 RuntimeStore 的当前 turn 原始／reconciled 结果派生可用执行引用；没有持久 store 的限定接线样例从同一路径的真实 BusinessToolResult 派生。
- finish_turn 可声明 completed_action_refs 和简短 pending_actions；合法已完成引用必须指向本轮或明确展开的合法既往成功结果。
- 查询成功只证明查询发生；消息发送成功只证明消息发送，不证明退款、审批或另一动作完成。
- 对未发生的动作，程序不能凭空补“某动作 NO RECEIPT”；该动作须来自实际意图记录或 Host 明确提出的待办，后者仍标为语义提案。
- 结构字段合法不保证 answer 没有另写无依据完成声明。验证必须同时检查最终回答，不能用引用子集检查替代语义验收。
- 恢复沿用已保存的 intent/result，不因维护或终结字段失败重做已执行业务。

**验收：**不存在／失败／unknown／跨权限的回执不能被提交为已完成；真实成功动作可正常结束；无审批回执时不得在实际答案中声称已审批。政策歧义保持原生失败也可以通过这一语义边界验收。

### C. 让新写入正文自包含，并处理字面碰撞

复用实际可见／已发布的引用绑定，不建立另一套可见性账本。校验入口位于 Host 普通写入解析与提交之间，覆盖 CREATE、完整 REVISE、patch 新写片段及普通维护能走到的同类入口。

- 只识别实际协议分配的完整 token，不按所有 mN/rN/cN/pN 外形拒绝，更不能替换来源原文。
- 已分配 token 也可能是真实型号。采用显式字面用法及已交付原始内容核对的窄例外，细节见设计；不能声称 visible_handles 集合本身消除了碰撞。
- 正文中的引用用途被拒时，返回短错误与改写要求；证据留在结构字段。现有 repair_of 路径处理拒绝，不另造修复流程。
- partial patch 不能借校验重写未交付正文。区分本次引入的引用与继承的历史污染；整卡清洁与局部修改合法分别记录。
- 材料中的主体、事项、范围和当前状态尽量来自已有元数据及原始标识；不额外调用模型为每个来源生成标题。

**验收：**无出处的协议引用不能进入新持久正文；原文中的真实 m4、型号、代码与非当前分配 token 不被误删。新进程能读懂事项。旧 v13 制品不迁移，不通过静默清洗制造“新版本干净”的证据。

### D. 固定合同成本与协议身份

先分解 shared contract、工具 purpose、字段说明、frontier、业务结果和历史材料，不把重叠子集相加。v13 已有 schema-derived compact catalogue；本轮只删实测重复，不再“重新实现压缩”。

静态说明保持稳定；动态的可调用能力、可用回执与未决引用在一个位置交付，schema、文字目录和 dispatcher 使用同一可调用集合。只有权限／阶段确实不允许的分支才隐藏，不能因为看起来不需要而剥夺合法修订。

新增 finish／写入字段属于合同变化：规划使用新 maintenance 协议及独立 v14 ordinary 配置，明确记录 action／write／material 协议实际变化；旧运行身份不冒充新实验。没有必要重写 RuntimeStore 磁盘布局，恢复身份不匹配仍拒绝。

prefix cache 只作为后续可测的服务优化：先检查实际部署能力和是否已启用，不在本轮规划中假定可用；逻辑 tokens、真实延迟和服务端缓存指标分列。没有指标就写 unavailable，不估算缓存收益。

**验收：**同一工具能力下规则不重复，实际解码 schema 可表达新字段；不通过删来源、权限、CAS、原生历史边界来降低输入。新增语义字段的成本也纳入总量，不要求为达到任意压缩比例牺牲质量。

## 4. 开发顺序与文件职责

| 顺序 | 工作包 | 主要位置 | 完成后再做什么 |
| --- | --- | --- | --- |
| 0 | 冻结基线、合同样例与失败分类 | 文档、既有 v13 制品、manifests | 不调用模型；确定哪些字段是程序事实 |
| 1 | A：未来用途与剩余处置 | contextual_maintenance.py、contextual_host.py；必要的 session 扩展 | 窄合同检查后衔接 B |
| 2 | B：执行摘要与 finish 回执 | 既有 business_outcomes、finish_answer、RuntimeStore 只读接口 | 覆盖 preflight 与实际 finish 的同一判定 |
| 3 | C：持久正文与材料锚点 | material_view.py、write_contract.py、Host 写入解析 | 覆盖全量写入与 patch，保留字面碰撞正例 |
| 4 | D：合并说明与身份 | compact catalogue、profiles、prepare／runner、新模板 | 本地量化及必要的部署 schema 窄探针 |
| 5 | 冻结实现再选择有限验证输入 | 测试、紧凑 manifest、源码／配置 SHA | 进入下节验证；不同时调方法、数据和 scorer |
| 6 | 整理结果及 readiness | 结果、失败分类、费用、导航 | 通过或明确未达到；不自动重启 State 比较 |

目录名称是对当前模块的指示，详细设计提供真实文件链接。小纯函数可抽出，但不按行数重构主类，不增加通用事件框架、调度器或数据库。

Sol xhigh 作为唯一核心／Host owner；Luna max 可并行做窄的离线 token 清点、数据身份及冻结文档，文件不重叠。一个主控制器执行所有真实模型请求，并发为 1。Astra xhigh 只用于明确无法收敛的合同／语义难题，不设常驻 reviewer。发布沿用 Luna high；本轮仅规划不因此启动实现代理。

## 5. 小规模验证次序

所有运行均在开发和相关窄检查之后。累计预算与复核次数仍为 null；以下是计划样本范围，不是阻止有依据修复的硬停止线。

| 验证 | 输入与用途 | 约束 |
| --- | --- | --- |
| V0 确定性合同 | 现有测试中覆盖未处置 frontier、真实提交、回执身份、错误状态、句柄／字面碰撞、patch、恢复 | 只跑受影响用例；不把 scripted Host 正确操作算成真实语义成功 |
| V1 语义诊断 | 9 个“now/later/conditional × task-local/cross-turn/durable”实例，加最多 3 个负例／碰撞控制 | 独立自建诊断集，明确不算 MERIT 成绩；先冻结文本与评分标准，标签不进 Host |
| V2 暴露 arc 回归 | 现有 arc0-000，最终冻结源码从原始世界／空记忆完整运行 | 只检查首次保存、执行措辞和正文；不以 native 5/5 为目标，不用它选择 prompt |
| V3 小型新原生验证 | V1/V2 满足语义门槛后，按已冻结规则选两条未暴露完整 MERIT arcs，仅 ordinary | 至少排除已暴露 seeds 0/1/2；按实际 exposure 清单核对，不提前读题挑样本，不改数据／checker |

V1 不是新 benchmark，也不是为原生任务增补历史。诊断中的 expected future use、判分条件不得写入 TaskTurn.persistence_required 或工具元数据。需要 LLM Judge 时只使用独立 vLLM 评分请求，冻结 rubric，保存费用与分歧；能用真实回执、状态及小规模人工核对解决的项目不另加 Judge。

V2 出现政策／工具／checker 冲突可保留 4/5，但无回执完成声明仍是失败。若发现新的语义反例，记录定位后修改相应机制；已见题自动转开发集，不换 seed 隐藏失败，也不机械循环直到全部通过。

## 6. Baseline Readiness Gate

门槛针对已冻结、有限范围的可观察合同，不是自然语言 100% 正确的承诺。

| 项目 | PASS 需要的实际证据 | 不能替代它的指标 |
| --- | --- | --- |
| G1 首次保留 | 未来需要的信息在首次出现后可跨声明边界恢复，且暂缓的业务没有提前执行 | Host 说 saved、后续重述后创建、单纯 source_refs 存在 |
| G2 不过度保留 | task-only／明确不保存的正反例保持限定范围 | 把所有输入都保存换 recall |
| G3 执行依据 | 结构回执有效，实际回答也无未执行却声称完成的动作；业务成功后恢复不重复 | completed_action_refs 是合法子集、native 任务分数 |
| G4 正文自包含 | 当前新卡无协议指代，真实字面 token 正常保留，局部 patch 不损坏其他内容 | blanket regex、自动替换、只检查创建不查修订 |

G1—G4 在声明验证范围内通过且没有该范围中未关闭的已知反例，才标记 BASELINE_READY_FOR_SMALL_RESEARCH。若只有工程和结构检查通过，状态只能是 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES；不能把 pending／拒答本身当作通过。维护 overhead、拒绝次数、tokens 与成功数同时报告。

通过后再单独设计 matched Notes／Sparse Basis／Sparse Basis＋Attention。三个臂必须共享本轮语义合同、回执、来源、业务工具与恢复保障；v13 旧成本不能冒充新基线对照。v14 本身不恢复三臂实验，不认领 State–Attention 创新收益。

## 7. 交付和本轮状态

未来实施交付包括：必要源码和窄检查、独立 v14 模板与冻结、语义诊断规范及隔离标签、原生 exposure 清单、分阶段报告、失败分类、连续费用和最小复现入口。原始数据、模型、trace 和数据库继续 ignored，Product 不动。

本轮仅交付本 Goal 与详细设计，并更新导航。运行代码与 v13 冻结保持原样；pytest、vLLM、Judge、benchmark 选择／生成均未执行。实施需要下一次明确的开发指令，不因文件名含 Goal 就自行开启。
