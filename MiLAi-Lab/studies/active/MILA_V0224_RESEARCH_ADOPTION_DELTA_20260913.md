---
goal_id: MILA-V02-24
document_kind: RESEARCH_ADOPTION_DELTA
version: "0.2.1"
status: PRINCIPLES_ADOPTED_EXECUTION_SELECTION_PENDING
active_execution_contract_changed: false
e_matrix_selection: NOT_SELECTED
e0_status: PUBLIC_CAPABILITIES_DOCUMENTED_COMPOSITION_NOT_ADMITTED
new_model_allocation: 0
new_provider_http_allocation: 0
new_confirmation_allocation: 0
memory_status: MEMORY_NOT_ADMITTED
---

# V0224 研究采纳差异：原则采纳，矩阵前瞻选择

## 1. 效力与当前状态

依据最新用户审阅，采纳 v0.2 的研究原则，不原样替换 v0.1 全部执行设计。本文是后续合同的紧凑采纳依据，不是新执行许可。
保留[主 Goal v0.1](MILA_V0224_Gate_A至E执行有效性与持久记忆研究_总GOAL_20260913.md)与[v0.2 提案](MILA_V0224_RESEARCH_REFINEMENT_PROPOSAL_20260913.md)原文；准备下一研究子合同时，E 的唯一四根要求及相关资源解释以本差异为准。
当前 Gate A 仍由其既有 R04 合同控制，不追加20次测量、另两轮修正、profiler/cache/adapter，不改变18/60门或已运行实例。

本次只读[执行状态](MILA_V0224_EXECUTION_STATE_20260913.md)，其 frontmatter 仍为 `A_R04_V2_PREPARATION_COMPLETE_CALIBRATION_PENDING`。没有独立复算 Gate A 原始终态，也不签发 PASS；R03 authority 合同变化与 R04 同 scope 去重不能合称无语义差异的加速。
v0.1 的 NOT_STARTED 是制定时快照，本轮“新增0”不是项目历史用量0。Memory仍未再准入，A0、公开部署、Schema NO-GO不变。

## 2. 直接采纳的四项原则

1. **问题发现与机制价值分门**：N0正确、N1旧方向错误、R1正确，可以支持局部 Note 消费问题，也说明普通review优先；不能据此宣称复杂State必要。
2. **同调用 R1**：普通review默认在同一次正常决策调用完成，不强制第二Agent/额外生成；实际增加的输入、读取、后续动作和成本照实计入。
3. **Controlled consumption**：经公开接口冷读并证明实际呈现，先控制acquisition混杂；不声称自主召回、检索策略或整个Memory系统收益已成立。
4. **重激活与错误恢复分开**：A→B→A的适用条件恢复不要求先犯错；Recovery必须有错误偏离及之后的纠正机会。首轮Stable/Changed不验证conditional reactivation。

完整依赖仍为 A余量 → B新P3 16/16 → C P4 24/24 → D无旧Note自然能力 → E比较。D中无Note普通复核合格，不代表E中有Note的R1必须全部正确才准入。

## 3. E 不设唯一四根入口

### 3.1 根据 D 资格选择，必须早于首个自然 A 输出

| 模式 | 选择条件 | 正式 B 矩阵 | 能提供的证据 |
| --- | --- | --- | --- |
| `PAIR_REPEAT` | 实际具备至少两根/两family，并覆盖拟用世界；优先可行路线 | 2根×2世界×3臂×2冷遍=24 | 同根冷结果是否重复；独立lineage仅2 |
| `FOUR_ROOT_DIVERSITY` | 已有4个实际D合格根，且两family各2根，无需为凑数新增任务/接口 | 4根×2世界×3臂×1遍=24 | 异质性增加；独立lineage4，没有同根重复 |

两种模式都只是局部诊断。选择依据只能是A前已有D资格、资源和公开隔离可行性，不能用自然Note质量或N1输赢选择更有利矩阵。
模式、候选顺序、family约束、世界版本、波次、停止规则在首个A输出前冻结；A后不能从四根模式临时降为两根模式并追认完整矩阵。

本次核对[现有已开放根目录](../../configs/v0220-v2-selection-v1.json)：4根分别属于real_estate、investment_analyst、hr、hr，分布为**2＋1＋1**，不是2＋2。
这是V0220已暴露目录，不是当前D合格证书；本次不选择具体E根。不能重命名family凑四根方案，也不因此扩任务或消费C。

### 3.2 自然 A 机会失败与继续规则

- `PAIR_REPEAT` 保留v0.1的前瞻候选方案：在最多4个**已D合格**根内先冻顺序，每根至多一次A；按固定规则接纳首个合格根及首个不同family的合格根。全部M0选择在B开始前结束。
- 对预先列明候选的顺序递进不是事后补题；禁止在A结果后扩池、重生成、修Note、改变资格或用B结果挑根。候选只有两根也可以冻结，不能假装有四个机会。
- `FOUR_ROOT_DIVERSITY` 固定四根，各一次A；局部失败不替换根、不反复生成合格Note。

| 现象 | 停止单位 | 其他预定根与报告 |
| --- | --- | --- |
| NO_WRITE、相关命题t0已错、无法裁定曾正确 | 该根的“曾正确Note”比较不运行 | 只要公共边界有效，允许继续其余预定根；PAIR模式只能按既定候选队列递进 |
| 单根公开读取/来源资格不成立，且可证明影响仅限该隔离根 | 该根后续位置NOT_RUN | 继续其他已授权根，保留机会/取得失败，不算Memory惯性 |
| scope污染、账务/Provider用量未知、共享接口或证据完整性失守 | 停受影响批；影响边界不明时停当前波 | 先反思/核验，不继续积累效果分数；不自动重试未知写入 |
| E中N0/N1/R1普通业务失败，但输入/执行/真值链有效 | 不因答案错删除配对 | 结果及计划后续位置保留；N0错不等于整个配对无效 |

PAIR模式接纳不足两根两family时，允许按A前规则保留已形成根的局部配对；四根模式部分合格时，也可运行其余预定根。两者都必须报告 `PARTIAL_MATRIX / MEMORY_OPPORTUNITY_INSUFFICIENT`，不冒充完整24会话矩阵或完整Gate E PASS。
首波若仅有局部机会失败，不自动阻断另一预定根/波；能继续的完整配对按预冻结顺序运行，不能只重复阳性或避开失败臂。系统性失败则按上表停止。

## 4. D2 世界覆盖：只补一张表，不造准入框架

新增[逐位置覆盖表](MILA_V0224_D2_WORLD_COVERAGE_20260913.csv)：`root × world × policy × repeat × existing evidence`，另列具体world绑定、等价审阅与当前证书。
已按现有4根展开Stable/Changed、N0-exec/R0-exec、两冷遍，共32个**潜在需求位置**。它是离线计划表，不是32次执行分配，不是新的Runtime schema。
当前world版本尚未绑定，未核验任何对应当前revision的D2合格终态，故明确标为 `NOT_BOUND / NONE_VERIFIED_IN_THIS_REVIEW / NOT_ADMITTED`；不把“本次未核验”写成历史从未运行。

在A–C有效、D任务冻结后，为每个拟用E根：

1. 绑定Stable/Changed的实际world/source/action/checker/presentation版本，而不是仅写一个条件名字。
2. 逐行填已有terminal证据与冷身份；检查策略、事实、事件、合法目标、执行边界是否等价。B/C的INTENT_ORACLE成绩不算D2证据，其他root/family也不能代替。
3. 同一份证据只能覆盖实际相同的需求；不同世界若有可证明的观察与行为合同等价，可以显式复用，但不能无说明填两次。两个repeat仍须两个真实独立冷运行，不能一条轨迹重复计数。
4. 只对没有有效等价证据的位置列增量，连同成本及新范围冻结；不得默认原16个episode已经覆盖两个世界，也不得默认必然缺16个。

若每世界都要求每政策两冷遍，m个拟用根需 `m×2×2×2=8m` 个D2 positions，每位置≤16生成：
两根完整双世界=16 episodes/256生成；四根完整双世界=32/512。原4根单世界16/256与两根双世界16/256数量相同，**并不代表覆盖相同**。
D1仍按其恢复场景证书检查适用性；如需额外事件校准，单独列增量，不把未知扩展藏入D2重算。

## 5. 完整资源账，而非仅“24 B”

| 阶段 | 既有计划包络 | D2确需完整四根双世界时 |
| --- | ---: | ---: |
| B | 16 | 16 |
| C | 96 | 96 |
| D1 | 80 | 80 |
| D2 | 256 | 512 |
| E，含≤4自然A及≤24冷B | 448 | 448 |
| **合计生成上界** | **896** | **1,152** |
| 其中E前的B–D | 448 | 704 |

这是待选计划包络，不是当前allocation，也不是已耗费或必须耗尽的次数。两根方案也可沿用≤4A的候选上界；若实际只冻2A，须在具体合同下调，不将未分配额度挪去新诊断。
实际下一合同用量应由覆盖表的未覆盖位置计算，不把896/1152当成应追加的余额。已运行失败/校准/准备成本另保留；Note增量校准、HTTP探针、模型Judge、额外世界、重复和机制臂另列，当前新增额度均0。
累计raw-token上限继续未设，但请求/会话/阶段deadline、并发、服务、输出预约和停止条件保持有界，不借文档更新延长R04期限。

## 6. E0 公共能力存在性审阅：现在看文档，不运行探针

以下只读取当前工作树公开合同、导出的接口Schema和历史报告，未启动服务、HTTP、测试或实际配对；不是当前执行pin验证。

| 依赖 | 本地公开证据 | 本次结论/剩余缺口 |
| --- | --- | --- |
| Note真实提交、版本与操作回执 | [ADR-051](../../../MiLAi-Product/docs/adr/ADR-051-host-notes-and-mcp-contract-repair.md)、[compact合同](../../../MiLAi-Product/contracts/mcp/compact-memory-v1.md) | 公共save/status路径有定义；当前隔离实例、功能与有效pin未验 |
| 精确ID/version读取、正文与来源各自分页 | [0.1.15工具Schema](../../../MiLAi-Product/contracts/mcp/compact-memory-v1.release-0.1.15.tools.json)、[使用手册](../../../MiLAi-Product/docs/runbooks/compact-memory.md) | NOTE target有version，默认null不能当成固定旧版本；应显式传commit版本并逐页核验 |
| 跨会话/历史版本行为 | [历史0.1.15验收](../../../MiLAi-Product/docs/releases/MCP_0.1.15_FINAL_ACCEPTANCE_20260908.md)、[V0218决策](MILA_V0218_INNOVATION_DECISION_20260911.md) | 历史报告提供先例；本轮未复算原始回执，不能借用为新E证书 |
| 同源Note与各臂新写入隔离 | ADR-051的server-bound principal/private project；compact只按所属scope授权 | 同一ID不能直接跨project读取；文档不自动提供跨臂共享或fork能力，组合方案待验 |
| 冷读确实进入输入 | [既有公开读辅助代码](../../tools/v0218_memory.py)最终返回`presented=False` | 精确读与实际呈现明确分开；后续必须绑定实际wire，不能拿工具返回替代 |
| 公共testkit可否复制记忆世界 | [retrieval trace testkit](../../../MiLAi-Product/docs/reference/retrieval-trace-testkit.md)只定义读取比较 | 未在这些已查接口中核验到通用Note/数据库fork；不能借其名字直接克隆私有表 |

**存在性结论：public save/read/status有明确路径；同源隔离组合仍为候选，不是E0 PASS。**
可优先审阅两个不改Product的组合，再只选择一种进入以后的有界机械验证：

- 原始commit方案：受信Host使用已授权的只读来源连接取得A的同一ID/version；各臂业务World、新Note写入使用各自绑定。必须证明N0不能读到A Note、B不能改写/删除来源Note、其他臂产物不可见。接口身份不能让模型自行选择。
- 公开派生方案：公开冷读原始A，再经普通公开save建立各臂有来源映射的副本，B新Host公开冷读各自副本。完整内容/metadata/source eligibility均需满足，不能删除引用来绕权限；标`DERIVED_NOTE_COPY`，不能声称读取的是同一原ID。原始commit冷读与派生链分报。

上述组合是根据公共原语提出的设计路径，尚未证明当前Host绑定支持；不能为使其成立临时扩权、换pin或调用私有clone。若目标estimand必须同一原commit而仅派生可行，则保持该条件未准入，不能静默换口径。
版本pin不能绕过删除、撤销或当前来源授权。跨臂共用principal下的tags/filter也不等于安全隔离；若其他臂写入可被搜索取得，配对无效。
[Lab product.lock](../../product.lock.json)仍列`0.1.0-candidate`；这本身不是已证明不兼容，但也不能用0.1.15文档或当前SDK源码代替所选执行pin证书。本轮不改lock；E前须按已有公开接口pin流程核对实际组合。

在已有R04计时实例旁不启动新负载。仅做本存在性检查以提前暴露依赖；组合测试、grant/连接绑定与Note工具增量校准仍等待明确范围。

## 7. 锁住呈现、分母与两种成本账

### 呈现差异

冻结共同任务、当前证据、工具合同的区块hash、角色与相对顺序；仅预定义Note槽、review政策槽有处理差异。
N0无A Note，N1加入固定Note，R1再加入固定同调用review。不在R1中挪动当前任务到更强角色、缩短干扰来源、重排证据或注入答案。
新增文字必然可能改变绝对token位置/总长度，应实录差异而不宣称完全同位置；无额外负控时只识别“提供Note/复核政策”的整体效应，不直接分解为惯性或角色机制。

### 分母

全候选、A机会失败、每臂分配/尝试/未运行、有效输入执行真值链、业务结果并列；资格不按N0当次成败或N1旧方向错误重新筛。
N0当次答错但输入/执行/真值有效的配对必须保留；“N0正确条件下N1表现”若另报只能是标明选择条件的诊断切片，不取代全配对结果。
单根NO_WRITE不算无惯性，双呈现不等于因果，Shared A的一个版本不算多个独立Note。

### 成本

- **实际实验账单**：每个真实A、B、失败、校准、工具、CPU准备只按唯一事件记一次；共享A不因N1/R1或重复世界再次计费。
- **策略生命周期账**：分别列业务经验获取、Note写入、维护、冷读取、复核与后续行动；共享A的归属、假定复用次数k和摊销敏感性显式说明。实验臂/世界分叉不是实际用户的复用频率。
- 当前N0是不提供A Note的消费对照，不是独立跑过完整no-memory生命周期；不能据共享A宣称已测得端到端策略成本差。尚未测得的反事实成本标UNMEASURED，不能以0填补。

## 8. 后继研究与本轮交付

先完成有效N0/N1/R1比较。AdaptiveMem仍是下一公开使用政策候选，许可/输入公平性/当前栈运行资格未齐备不放行；CUPMem/TEPA只做近邻对照，不提前接系统或开发State。
随本差异提供[公开基线审计](MILA_V0224_PUBLIC_BASELINE_AUDIT_20260913.md)与[六文件hash清单](MILA_V0224_PUBLIC_BASELINE_SOURCE_AUDIT_20260913.json)，弥补附件不完整的阅读缺口；本轮不把原文存在解释为MiLAi效果准入，也不改历史同名MemTrap制品HOLD。

首轮E只回答Note局部影响、适应与普通review是否足够；conditional reactivation需要另冻A→B→A及再次冷边界。允许在已开放discovery反思、调整候选、放弃无增益方案，但不能把前两阶段结果提前升级为重激活证据。
如普通review足够则KEEP SIMPLE；只有强简单策略反复不足或实际成本存在可证实改进空间，才选择最小候选及同信息普通Note/review消融，再考虑未打开确认。

下一单步仍是**当前R04 terminal的取得与验收**，不是新增A设计。其后按门依赖更新D覆盖、E0组合资格，最后在A自然Note输出前锁E模式和有界合同。
本轮仅新增本差异与覆盖表；不修改旧Goal、R04、动态执行状态、索引、Product或实验代码/配置；未消费C或启动模型/HTTP/实验进程。只做文档、矩阵算术、公共Schema存在性与已有hash一致性检查，不并发运行工程全回归或借历史测试数宣称本轮Gate通过。

交付校验：16个本地链接可解析；覆盖表32个潜在位置唯一，root/family与既有目录一致；两种E矩阵和896/1152条件资源账复算一致。5份既有Goal/状态/合同/pin文件hash未变，6份已归档公开制品hash复核一致。该检查不签发D2、E0或任何执行Gate PASS。
