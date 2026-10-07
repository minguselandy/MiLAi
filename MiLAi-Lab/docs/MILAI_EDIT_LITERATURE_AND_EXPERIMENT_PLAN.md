# MiLAi-Edit：文献发表与开放性核查、开发及实验规划

> **总方向不变：Grounded Agent Memory。**
>
> 先接通真实公开 benchmark，再实现和比较条件化局部记忆编辑。以泛化性、功能可用性和真实效果为先；不以未开源系统或预印本的相似主题提前否定创新，也不忽略已公开的具体算法。删除自研 SHA／内容指纹门禁，不新增防御性校验平台、常驻 reviewer 或复杂实验审批体系。

**编制与检索日期：2026-10-04，Asia/Tokyo。**  
**文档版本：`milai-edit-plan-1.0`。** 这是研究与开发规划名称，不是已经发布的软件版本。  
**工作基线：** PR #82 合并后的 r52 功能实现及已完成的 L1–L4 报告。  
**当前状态：** r52 实验已执行完毕，功能验收 PARTIAL，Product NO_GO；本文件不提升这些状态。  
**本次实际完成：** 重新检索论文、核对部分正式发表条目、读取作者仓库及部分实现／评测代码、核对公开数据文件目录，生成本文件。没有安装并运行外部系统，没有完成数据全集下载，没有运行模型、修改 MiLAi 源码、删除已有检查或推送 GitHub。

本文将三类内容分开：**来源确认的事实**以文献编号标注；**对事实的判断**写明其含义；**拟实现的方法与实验**均为计划。所有“未核实”表示本次证据不足，不等于证明其不存在。来源与核查路径见第15节。

---

## 1. 本轮决策

### 1.1 先做什么

先接入 **HaluMem-Medium**，以其形成、更新与自然问答任务建立可运行基线；再用 **LongMemEval-S-cleaned** 检查更新后的端到端问答。MemoryAgentBench 的 Conflict Resolution 作为可选受控对照，不立即展开全量 benchmark 矩阵。[B1–B3]

在这个基础上实现一个小型 **MiLAi-Edit** 原型：模型预测要修改的语义单元和编辑操作，程序应用修改并保留未被编辑的部分；明确区分全局替换、局部范围覆盖、追加和撤销。

这不是“已经发现新算法”的宣布，而是正式投入验证的候选。是否具有贡献，比较真实计算过程、适用条件和结果，不用论文标题相似度作结论。

### 1.2 不再采用的做法

- 不把“出现过 preservation、delta、scope、grounding”等词，直接解释为本方法没有创新。
- 不要求复现没有可获得代码／模型的论文，才允许继续开发。
- 不把论文声称的性能当作已独立复现的事实；也不因其未正式发表就忽略其已公开算法。
- 不先建多假设平台、状态图、强化学习训练链和新的 reviewer 系统，再找可以支持它们的任务。
- 不用 SHA、重复全对象比对、数百项新门槛来替代正常功能测试。

### 1.3 保留原方向与已完成能力

继续使用一个逻辑 MemoryService，保留 Grounded Memory、Verified Object References、Semantic/Episodic Memory、Grounded Revision、Lifecycle Recovery。

r52 的来源保存、真实片段、同 ID 修订、历史、no_change、撤销、可见性传播和有界续办继续复用。W1 原保存请求遗漏已有限定修复证据，不再建设第二套任务恢复平台。[M1]

v13.4 的 Simplify 只结束原“复杂关系消歧选源”分支；不恢复其 T1–T3，也不把那次结论扩张成对局部编辑、范围保持等不同问题的否定。[M2]

---

## 2. 文献判断规则：发表、开放性、可运行性与创新分别判断

### 2.1 发表状态

| 本文用语 | 需要的证据 | 不代表什么 |
| --- | --- | --- |
| 正式发表已核实 | 会议论文集／出版方正式条目，作者与标题对应 | 结论必然正确、优于所有后来方法 |
| 作者确认录用／会议归属 | 作者项目、作者本人公告或论文注记；写明证据级别 | 本次已经独立核对正式论文集 |
| 预印本／审稿中 | 已公开论文；正式发表入口本次未确认 | 工作没有价值、不能作为相关工作 |
| 未核实 | 检索不足或入口受限 | 论文没有发表、作者没有发布 |

**会议关键词、ICML格式模板、OpenReview页面存在，不等于录用。** arXiv DOI 也不能替代正式会议条目。若作者宣布录用而正式入口未读到，两项同时记录，不降格为“肯定未发表”。

### 2.2 开放性与可运行性

分别记录：论文是否公开；代码是否实际可见；是否有许可；是否有论文对应的训练权重、数据和运行脚本；是否在本地跑通。

- **开源许可明确：**如仓库明确标注 MIT、Apache-2.0。具体再分发仍遵循实际许可文件及依赖条件。
- **代码公开、许可未核实：**可以确认实现存在，但不直接称为许可明确的开源软件。
- **公开但限制性许可：**如 HaluMem 标注 CC-BY-NC-ND-4.0；不能当作 MIT 数据或任意改写再发布的资源。
- **仅承诺未来发布／未找到作者实现：**不列为必须可运行的基线。
- **未实跑：**不论仓库多完整，都不写成本地复现成功。

本文列出的外部系统均未在当前 MiLAi 环境运行。代码阅读、数据文件目录可见和端到端实跑是三个层次。

### 2.3 创新判断

逐项比较：研究对象、输入信息、持久表示、编辑操作、是否训练、检索与回答过程、评价范围。

**不开源影响复现安排；正式发表影响证据成熟度；只有实质相同的算法披露才直接影响相应原创主张。**不要求“所有构件都首次出现”，但也不能把已知方法换名后称新算法。

---

## 3. 重新检索的文章及状态

### 3.1 方法论文：本次核查结果

| 工作与标识 | 发表状态／证据层级 | 代码与许可 | 本次检查程度 | 对 MiLAi 的安排 |
| --- | --- | --- | --- | --- |
| **A-Mem: Agentic Memory for LLM Agents**，arXiv:2502.12110 | **NeurIPS 2025 Main Conference 正式目录已核实** | 作者复现仓库 `WujiangXu/A-mem`，README标注MIT；另有集成系统仓库 | 读取系统README、`memory_system.py`片段与复现README；未运行 | 优先外部记忆基线；区分复现版本与系统集成版本 [R1] |
| **Hindsight: Structured Agent Memory that Retains, Recalls, and Reflects** | **ACL 2026 Volume 3: System Demonstrations 正式条目已核实**，不是ACL主会长文；对应研究系列另有arXiv:2512.12818 | `vectorize-io/hindsight`，项目明确MIT，提供API／客户端与自托管入口 | 读取正式论文条目和仓库安装／retain-recall-reflect说明；未启动服务 | 来源与记忆组织近邻；需要较强系统对照时选用 [R2] |
| **RARR: Researching and Revising What Language Models Say, Using Language Models**，arXiv:2210.08726 | **ACL 2023 Long Papers 正式发表已核实** | 作者实现 `anthonywchen/RARR` 公开；本次根目录`LICENSE`路径未取到，许可未完成确认 | 已读README、编辑模块入口和模型／搜索依赖说明；未运行 | 有依据最小编辑近邻；使用适配版时必须单独命名 [R3] |
| **HiMem: Hierarchical Long-Term Memory for LLM Long-Horizon Agents**，arXiv:2601.06377 | arXiv公开；**正式会议／期刊发表本次未核实** | `jojopdq/HiMem`代码公开；README声明核心组件Apache-2.0 | 已读构建脚本与评测入口，存在实际构建代码；未部署依赖 | 可选层次记忆基线，不因发表未核实而排除 [R4] |
| **SimpleMem: Efficient Lifelong Memory for LLM Agents**，arXiv:2601.02553 | 作者仓库标注 **ICML'26**；本次OpenReview正文遇浏览器验证，正式会议条目未独立核实 | `aiming-lab/SimpleMem`公开，仓库标注MIT；当前项目包含Text、Omni、Evolve等不同方案 | 已读README与包／复现说明；未运行；不混用各后端成绩 | 现有适配可复用，明确选Text及实际版本；不要求立即重跑 [R5] |
| **TrustMem: Learning Trustworthy Memory Consolidation for LLM Agents with Long-Term Memory**，arXiv:2606.25161 | 作者Tianyu Yang本人宣布 **EMNLP 2026录用**；正式论文集条目本次未核实，不据此断言主会／Findings轨道 | 本次未确认作者官方代码、训练权重与复现包 | 读论文方法和作者公告；未取得可运行实现 | 比较转换级核对与RL目标；**不作为必须跑通的前置基线** [R6] |
| **DeltaMem: Towards Agentic Memory Management via Reinforcement Learning**，arXiv:2604.01560 | 所查版本为预印本；正式发表本次未核实；文中ICML关键词不作录用证据 | 所查正文写明代码将在录用后开源；本次未确认实际发布 | 已读方法及代码发布表述；无本地实现 | 比较状态转换奖励；不与其他同名DeltaMem混淆，不设为必跑 [R7] |
| **MemTX: Transactional Belief Commit for Stateful Agent Memory**，arXiv:2607.23929 | 所查v2明确写 **Preprint / Under review**；之后正式发表本次未核实 | **`lxy1134/MEMTX_`实际公开代码、数据、脚本和结果目录**；根目录未见许可证文件，本次许可未核实 | 已读完整README和仓库目录；区分scripted与LLM运行；未运行 | 纠正“没有代码”的判断；先作机制比较，许可与接入可用后再选做对照 [R8] |
| **Can Agent Memory Systems Track Evolving State?（StateMem）**，arXiv:2608.19652 | arXiv公开；正式发表本次未核实 | 本次未确认该论文自己的官方实现、StateMemBench数据和scorer | 读取论文与链接线索；不能把其引用的其他STATE-Bench仓库当作作者实现 | 保留状态维护近邻；不成为下一轮实验资源依赖 [R9] |

上述“未核实”均允许以后用新证据更新。**未找到代码不等于闭源声明；仓库README宣布采用某许可与完成全部依赖许可审计也不同。**本轮不下载模型权重、不执行各论文训练或测试。

### 3.2 三项需要纠正的文献认识

**Hindsight 不是只能引用预印本的项目。**现在有明确的ACL 2026 Demo正式条目；但不能把Demo发表写成主会长文。[R2]

**MemTX 不能继续放在“未公开实现”栏。**公开仓库明确提供协议、基线重实现、数据和驱动脚本；目前欠缺的是本次许可确认与本地运行，而不是实现入口存在性。[R8]

**TrustMem 不能简单写成“未发表论文”。**作者已经宣布录用；应写“作者确认EMNLP2026录用、正式条目与代码本次未核实”。这比用单一“已发表／未发表”更准确。[R6]

A-MEM 的旧 `WujiangXu/AgenticMemory` 链接已重定向到 `WujiangXu/A-mem`。复现仓库和集成仓库不是同一个对象；实验不能静默从一个换到另一个，再声称沿用原论文方法身份。[R1]

### 3.3 与候选算法的具体比较，而不是关键词排重

| 近邻 | 本次文献支持的主要机制 | MiLAi-Edit要检验的差异 |
| --- | --- | --- |
| A-MEM | 动态笔记属性、连接与记忆演化 | 是否用明确的范围化编辑减少对未改语义的损伤，而不是再次贡献动态笔记 |
| Hindsight／HiMem | 不同记忆类型、来源组织、检索与再整合 | 内容和条件之间的关系如何在连续局部更正中保留、修改和撤销 |
| RARR | 检索证据后修正不受支持的文本，尽量少改 | 持久记忆的replace／override／append／retract，及后续多轮状态与使用结果 |
| TrustMem | 转换级coverage／preservation／faithfulness核对，以及偏好引导RL | 第一版不训练、不靠多候选核对循环；改变编辑表示与执行算子 |
| DeltaMem-RL | 单Agent记忆管理、状态变化奖励与局部词汇保真 | 显式区分局部例外与整体替换，证明收益不只是词汇保留 |
| MemTX | 提交生命周期、权限、冲突和级联处理 | 不另造提交体系，直接研究内容更正时的语义局部性 |
| StateMem | 状态替代、依赖更新和重检 | 部分自然语言更正影响范围的表达与实际编辑效果 |

这些差异是**方法假设与比较计划**，不是已经完成的原创性证明。若后续读到实质相同的算子，应具体说明重叠并改进；不将不可复现系统的全部宣传能力预先视为已解决。

---

## 4. Benchmark：确认可获得，再决定接入顺序

### 4.1 发表、开放性和资源核查

| Benchmark | 发表状态 | 数据与代码 | 本次可用性结论 |
| --- | --- | --- | --- |
| **HaluMem**，arXiv:2511.03506 | 作者仓库明确宣布EMNLP2026 Main录用；正式论文集条目本次未核实 | `MemTensor/HaluMem`评测源码；`IAAR-Shanghai/HaluMem`数据；标注CC-BY-NC-ND-4.0 | 已看到Medium／Long实际文件目录，读取更新适配与评分流程；未完整下载或实跑 [B1] |
| **LongMemEval**，arXiv:2410.10813 | 作者仓库确认ICLR2025；本次未独立读到正式OpenReview录用页 | `xiaowu0162/LongMemEval`；`longmemeval-cleaned`；代码与数据页面标注MIT | 已核实cleaned文件及官方QA入口；旧数据页明确被cleaned替代；未实跑 [B2] |
| **MemoryAgentBench**，arXiv:2507.05257 | 作者仓库确认ICLR2026并给出OpenReview条目；本次条目正文受浏览器验证阻断 | `HUST-AI-HYZ/MemoryAgentBench`代码；`ai-hyz/MemoryAgentBench`数据；仓库标注MIT，子数据另保留来源许可 | 已核实Conflict Resolution的Parquet文件和评分说明；未实跑 [B3] |

**结论：**这三项具有真实公开资源，不是只有论文标题。它们尚未在当前MiLAi环境运行，因此第一项开发交付必须是数据读取、实际预测和评分端到端跑通，而不是宣布“资源检查已等于复现”。

### 4.2 首选：HaluMem-Medium

官方数据目录有 `HaluMem-Medium.jsonl`（约33.5 MB）和 `HaluMem-Long.jsonl`（约107 MB）。数据卡给出Medium为20用户、14,948记忆点和3,467问题。Medium与Long共享相应用户和语义内容，不能作为相互独立的开发／测试拆分。[B1]

运行时按原用户、会话时间、对话顺序摄入。被测形成器只得到当时已发生的对话和自身旧记忆，不得到 `memory_points`、`is_update`、`original_memories`、QA答案或未来会话。

#### 必须保留的官方协议含义

官方 `eval_memzero.py` 用标准新记忆的 `memory_content` 发起更新检索，再评价检索到的记忆。这是**参考更新内容引导的诊断查询**，不是自然用户问题。自然QA另外使用实际问题。[B1]

因此输出三类结果：

1. 官方形成指标：完整性、准确性及相应汇总。
2. 官方参考引导的更新诊断：明确查询信息条件。
3. 自然QA：不提供参考更新文本，评价真实下游效果。

诊断查询必须是只读，或在相同快照的副本上执行，不能把gold查询产生的缓存、反思和检索后写入带回后续会话。官方评分中有“更新且返回记忆非空”才进入更新评分的分支；单列总更新机会、空返回和实际评分分母，不能因返回空而让方法凭分母变化看起来更好。官方原分数保持不变，补充统计另列。

官方Mem0示例有云端账户操作和删除历史记忆的代码。接入时仅复用格式和评分协议，在独立测试bank上运行；不能把该示例直接指向已有用户数据库。

许可标注为CC-BY-NC-ND-4.0，不等于宽松软件许可。保留原文件和标识；发布自己的适配器、统计与必要标注说明时，不擅自打包分发修改后的原语料。许可与再分发问题按原发布条款处理。

### 4.3 第二项：LongMemEval-S-cleaned

官方cleaned目录包含 `longmemeval_s_cleaned.json`（约277 MB）、M版本和oracle版本。先用S，不先上2.74 GB的M。每个版本是500个评估实例；输出采用官方 `question_id / hypothesis` 格式。[B2]

`answer_session_ids`、`has_answer`、参考答案属于评测信息，不进入形成、检索或回答。oracle仅用于已声明的Reader诊断，不替代S完整历史条件。

标准knowledge-update评分允许答案同时出现旧信息，只要需要的更新答案正确。因此，官方准确率证明的是相应QA效用，不单独证明整段回答没有旧新混淆或附加错误。必要时在预先固定的子集上增加完整回答保真审查，单独报告，不覆盖官方指标。[B2]

S历史可能超过当前单次模型上下文。按原会话顺序维护记忆，不静默截断来源。FullHistory只有在实际可容纳时才作为完整历史对照；无法容纳需报告覆盖范围，不能改名后继续声称FullHistory。

### 4.4 可选：MemoryAgentBench Conflict Resolution

已核实 `data/Conflict_Resolution-00000-of-00001.parquet`。`fact_sh / fact_mh`采用增量输入，适合检查事实冲突和多跳更新。官方对应 `substring_exact_match`，不要求该子任务额外LLM Judge，但包含正确字符串不等于整段回答全部正确。[B3]

它用于补充受控机制，不承担全部范围保持与业务恢复结论。不要把其他子任务的Judge需求与该子任务混淆，也不要把从LongMemEval派生的部分当作独立外部数据。

### 4.5 接入完成的最低交付

只需要：数据可读、时间序列正确、一条方法实际产生结果、官方评分成功、样本和错误数量可解释。无需SHA清单或新的审批层级。

建议先在两个开发用户的少量完整会话前缀，以及几个LongMemEval开发问题上跑通。它们是接线测试，不能当作算法效果。随后对预先选择的开发用户使用完整历史进行配对比较。

---

## 5. 当前MiLAi问题与研究问题的连接

r52报告表明：L3形成41/57限定通过，52条记录中11条语义失败；L3读取完整合同17/30通过，但原题25题满分。新L4还有未知生效时间丢失，以及恢复后正文中的情境限定没有对应所选来源的问题。[M1]

| 已观察问题 | 当前判断 | 拟验证机制 |
| --- | --- | --- |
| 数值改对而时间、例外丢失 | 字段级update仍可能重写整段content | 不重生成未编辑部分，并保留条件与其修饰对象关系 |
| 核对误拒后删限定反而通过 | 后验核对可能诱导更差提案 | 先比较局部编辑，不默认依靠review循环 |
| 全局替换与局部例外混淆 | 简单最新值覆盖可能不足 | 将scoped override与replace区分 |
| 真引文却支持不完整 | 引文身份与语义支持不同 | 内容与条件分别关联实际来源；形成不见gold |
| 核心回答正确但附加规则错误 | Reader是独立断点 | 保持共同Reader，另做回答保真功能修复 |
| 读取未继续、提供方截断 | 接口与执行稳定性问题 | 先修正常读写，不当作编辑算法效果 |

这些是项目失败与方法假设的对应关系。**不声称全部错误都由整段重写导致，也不声称删SHA能自动改善语义。**公开benchmark需要检验哪些问题实际重复存在。

---

## 6. 方法候选：条件化局部记忆编辑

### 6.1 核心假设

**H1：局部性。**模型只生成被修改的内容，可以减少对其他有效语义的附带损坏。

**H2：条件化。**区分整体替换和局部范围覆盖，比普通文本patch更能处理“某项目／某时间／某场次例外”，同时不损害范围外状态。

**H3：可组合性。**连续执行有来源依据的替换、追加和撤销，比多次整段重写更少积累语义漂移。

不承诺通用自然语言逻辑正确性。H1可以成立而H2不成立；这时保留普通局部编辑，不强行保留条件化结构。

### 6.2 最小表示

继续使用现有记录与Store，只在需要编辑的记录中增加可定位的内容／条件单元。以下是逻辑示意，不要求另建服务或完整知识图谱：

```text
Source: source_id, revision, owner, role, observed_at, text
Memory: record_id, revision, kind, units, relations
Unit: unit_id, text, evidence_refs
Relation: source_unit, relation_type, target_unit, evidence_refs
```

`relation_type`第一版只需要表达某条件修饰哪些内容，以及某个局部安排覆盖哪个一般安排。条件正文仍是自然语言，不为每个领域发明固定本体。

无法可靠拆分的表达保留为一个较大的单元；不把分句结果当成正确语义分析。新记忆的初次形成也要单独评价，不能靠后续编辑掩盖初次丢失。

### 6.3 四种核心操作

| 操作 | 含义 | 关键边界 |
| --- | --- | --- |
| `replace` | 在明确影响范围内用新内容替代原内容 | 不自动扩大到相似但不同的主体 |
| `append` | 增加新事实或条件及其关联 | 不把另一个人的陈述并为当前用户偏好 |
| `override` | 某一子范围采用特殊安排，一般规则在其他范围仍保留 | 需要实际来源支持该范围关系，不用“更长文本更具体”代替判断 |
| `retract` | 撤销指定内容、条件或局部覆盖 | 撤销某个例外不一定等于肯定相反事实 |

`no_change`是正常结果，不是第五种复杂算法。完整记录撤销继续使用已有服务能力。

### 6.4 一次正常维护

1. 按真实新事件检索相关旧记录与来源，使用原有检索方法，不见未来问题。
2. 模型在同一维护调用中选择目标、操作、新文字和来源；不生成整张未改卡片。
3. 程序应用局部编辑，未选择部分沿原记录保留；提交新revision并记录实际操作结果。
4. 查询时将当前适用内容与必要条件交付共同Reader，旧版本保留为历史。

示意输出：

```json
{
  "target_record": "memory-17",
  "base_revision": 3,
  "edits": [
    {
      "operation": "replace",
      "target_unit": "frequency",
      "text": "试运行计划每周三次",
      "evidence": ["source-28:part-2"]
    }
  ]
}
```

示意字段不是现有CLI参数。ID与位置由服务提供，模型无需生成hash或手填字符偏移。依赖编辑先读实际记录；多个对同一旧版本的编辑一次应用，避免位置漂移。

### 6.5 连续更新示例与关键设计问题

以下是设计示例，不是新实验结果：

```text
初始：项目P试运行计划每周两次；开始周未定；节假日暂停。
更新1：次数改为每周三次，其他不变。
更新2：夜班改为每周四次，白班仍照原计划。
更新3：从下周一开始，节假日也照常。
```

更新1只改频率；更新2建立夜班局部覆盖；更新3合法修改开始时间并撤销节假日例外。必须明确更新3作用于整个项目还是某个班次；语义不明确时不能由“最新消息”自动决定所有范围。

第一版只实现**一层明确局部覆盖**。一般规则与覆盖规则均保留必要有效范围，读取时不得把一般值与例外值不加区分地同时当成当前答案。多层复杂覆盖先保留原文或询问必要澄清，不暗中作全局覆盖。

必须提前确定并测试：

- 普通值变化时，哪些已明确共享的条件仍应用于局部覆盖？
- 更正明确说“所有班次”时，旧局部覆盖应怎样处理？
- 撤销覆盖后，一般规则是否仍有效？如果不确定，不自动恢复成真。
- 主语、单位或事实性质变化可能影响多个单元，允许一次编辑多个目标，不把最少字符修改当成绝对正确。

程序只能保证未编辑的结构被保留；是否该编辑、条件是否仍适用、关系解释是否正确，仍是模型与实验要解决的问题。

### 6.6 来源、语义和权限保持分工

情境限制可以来自用户，业务结果来自实际工具；来源可以组合，但必须逐项有实际依据。历史请求说明当时要做什么，不证明业务已经成功。修改来源引用不会自动增加语义可信度。

Verified Object References仍由真实应用对象与工具结果产生；记忆编辑不创造业务权限。Semantic/Episodic只组织长期约定与具体经历，不作为正确性的证明。

---

## 7. 工程安排：不用SHA，不发展防御性校验体系

### 7.1 共用清理先于算法比较，但不拖延benchmark接线

数据加载、官方评分接线可以先完成。随后把旧入口中阻碍正常运行的自研SHA门禁移除，形成各方法共用的轻量底座；算法对比在同一底座上进行，避免把清理开销减少误归因于新编辑算法。

| 删除 | 采用 |
| --- | --- |
| 源码／配置／SDK／fixture逐文件摘要检查 | 普通版本名称、配置副本、依赖版本与实际运行记录 |
| 原文／片段多重内容指纹与重算 | 不覆盖的source revision、普通ID、原文区间 |
| 响应／核对／分页内容摘要绑定 | 已持久化的attempt_id、proposal_id、snapshot_id |
| tokenizer文件摘要门禁 | 实际加载、实际模板和上下文计数 |
| 业务operation按参数hash去重 | 首次执行前保存的operation_id；正常重启复用原ID |
| 文稿digest审批 | 不可变document_version，审批／发布关联具体版本 |
| SHA清单、文件树一致性作为实验门槛 | 正常功能测试、数据来源与结果记录 |

不改成MD5、CRC或另一种指纹；不把全对象相等检查复制到每个内部函数。Git内部标识、TLS和第三方实现不是本次去除目标。

### 7.2 必要业务语义只在对应边界处理

外部参数入口解析一次；内部用明确类型。owner访问、读取revision冲突、事务提交与真实副作用由服务／应用边界负责，不在各层重复守卫。

去掉内容摘要前，先让不可变版本与数据库引用承担身份。审批过的旧文档不能用于发布新版本。原有未知效果不能被异常包装成“没有发生”。这是功能含义，不是再加一个防御平台。

旧报告和原始结果不删；旧hash形态ID可作为普通字符串继续使用，不重新计算它。旧缓存可重建，实际记忆和业务记录不能因此丢失。历史r52配置仍可作为存档，不要求新入口保留全部旧策略开关。

### 7.3 不新增常驻审核链

默认候选先比较一次编辑提案＋实际提交，不叠加新的reviewer、投票和循环。现有r52核对作为历史方法对照；是否保留同模型核对，通过独立消融决定。

正常调用可以有明确、有限的格式纠正与提供方重试，但不允许重试覆盖首失败、只保留成功答案，或为补最终回答重做已成功业务。次数按可用性需要预先确定，不以成本最低为目标。

---

## 8. 先后顺序与开发工作包

| 阶段 | 交付 | 完成判断 |
| --- | --- | --- |
| **P0：benchmark接线** | HaluMem-Medium、LongMemEval-S-cleaned读取；简洁适配；至少一种普通方法预测与评分 | 真数据可读、真实输出可评分；区分接线样本与效果样本 |
| **P1：共用底座减负** | 移除自研SHA门禁，普通ID／版本；保留已有保存、历史、恢复 | 正常故事通过；代码清理与算法变更分开 |
| **P2：最小编辑原型** | 普通局部编辑、条件化编辑、共同Reader | replace／append／override／retract各有正反用例，不新增服务 |
| **P3：公开数据pilot** | 三主方法与一项归因控制；固定开发来源配对结果 | 明确收益来自编辑还是表示；不依赖自建题目才有效 |
| **P4：正式比较与泛化** | 未调参来源、官方指标、局部机制分析和第二模型确认 | 有完整分母与不确定性，主张和覆盖能力匹配 |
| **P5：功能回归与稿件** | 一个候选回归已完成L1–L4体系，保留历史身份，整理复现说明 | 功能与研究分别结论；无优势也可交付更简单的可用实现 |

不要求在P0之前完成全部产品修复，不要求所有外部框架均可运行。避免“基础平台持续扩大，方法一直没有公共结果”。

---

## 9. Baseline与归因设计

### 9.1 方法主表：最少三臂

| 编号 | 方法 | 变化 |
| --- | --- | --- |
| B0 | 普通语义记忆更新 | 生成受影响记录的完整新正文 |
| B1 | 普通局部文本编辑 | 选定文本单元replace／insert／delete，其余原样保留 |
| M | 条件化局部记忆编辑 | 区分局部覆盖与整体替换，维护内容—条件—适用范围关系 |

三组使用同样的真实来源、形成边界、模型、检索预算、Reader与工具权限。不把参考记忆提供给任何Writer；不允许M独享更长历史或更多正确候选。

### 9.2 一个不可省略的归因控制

加入 **B2：与M相同的结构表示，但整段／整记录重写**。

这样可以区分：

- B0→B1：局部编辑本身的作用。
- B0→B2：表示与条件分离的作用。
- B2→M：在同表示下，条件化局部算子的作用。

有预算时形成“普通／结构表示 × 整体／局部编辑”四格；第一轮可先三主臂接线，正式声称算子贡献前补B2。语义编辑与读取渲染变更必须登记，不能同时暗改Reader。

### 9.3 外部系统主表与机制表分开

外部系统优先选 **A-MEM**；Hindsight或HiMem按接入成本和论文主张选其中一个，不全接。现有Mem0适配可保留为软件对照，但明确OSS／云端、维护方式、版本与观察范围，不把云端结果当OSS复现。

公开主结果可采用：**原文RAG、Rolling Summary、一个忠实接入的外部记忆系统、M**。r52完整配置另列为项目回归对照。没有必要给每个小消融重复全部系统。

RARR只在实际需要比较“通用检索后编辑”时接入；若把其开放网络搜索改成受限档案检索，并更换原模型，应称 **RARR式档案编辑适配**，不能声称完整原生复现。绝不启用仓库中的生成虚构证据选项。

TrustMem、DeltaMem-RL和StateMem在作者实现／权重未获得前，只做机制比较；MemTX虽有代码，但先确认许可、脚本任务含义和LLM接入，不把作者自建protocol套件当作唯一独立评测。

---

## 10. 实验安排：规模、数据隔离与阶段结果

### 10.1 E0：接线试验

名称仅是本文局部实验索引，不改写MiLAi历史E0状态。

- HaluMem：两个预先选定开发用户的少量连续会话；必要更新保留全部旧前缀。
- LongMemEval：数个已指定开发问题，完整顺序摄入其历史。
- 一种普通记忆方法产生输出，实际跑官方评分。

只报告成功读取、摄入、输出与评分，不报告“方法有效”。不下载或部署新模型作为默认动作；用当前可用模型和明确配置即可。费用实际记录。

### 10.2 E1：HaluMem开发比较

先按用户划分，而不是随机分散同一用户的会话。建议20用户中指定4个开发用户，其余16个保留；这是待执行划分，需核对既有曝光。已读过或用来调参的来源不能重新称未见。

接线后对开发用户的完整历史比较B0、B1、M；补B2后确定一版方法。主评分直接使用官方流程，另列每次记忆更新前后的实际状态及所选来源。

20用户是来源簇的数量级，不因有数千QA就声称拥有数千独立长期用户。Medium／Long不跨划分混用。

### 10.3 E2：更新局部性机制切片

从开发用户的真实更新中，按预先写好的标准选择约24–40个更新机会，并记录来自多少用户／原历史。覆盖普通值更新、条件保持、局部覆盖、明确取消、历史纠错与不可确定情形。

没有足够原生局部覆盖案例，就如实报告缺项。可以另外制作少量有真实来源依据的受控测试或合法标注，但必须与官方主结果分开；不能为满足配额捏造“官方样本”。

每个机会同时测试：新要求是否落实、未改条件是否保持、合法撤销是否成功、范围外是否受到影响。NeverWrite和“全部保留旧条件”是退化控制，不能靠保守不更新获得成功。

第一版机制测试不要用gold旧记忆初始化并混入主表。需要理想旧状态诊断时单列；主表从模型自己的形成状态出发，以免隐藏初次形成的错误。

### 10.4 E3：LongMemEval外部验证

可用约50个开发问题调整适配，其余作为候选冻结后的测试起点；最终分母取决于原历史重叠与曝光检查，不机械承诺450个全部独立。相同底层会话进入同一划分。

知识更新、时间推理、普通回忆、拒答分别报告。只跑knowledge-update子集应明确“子集结果”，不能说整个LongMemEval得分。全500题若包含调参数据，可作为全量描述性结果另外列出，不能替代未调参结果。

标准评分之外，对事先确定的子集审查完整回答是否混入旧规则或无支持说明，避免方法只命中答案词却损害解释。

### 10.5 E4：连续编辑与泛化

保留原顺序，观察每次更新后的损坏是否积累。额外顺序交换试验仅用于已判断互不依赖的两项更新；不能要求所有时间事件可交换。

泛化至少区分：未调参用户／来源、不同更正措辞、中文／英文混合、第二模型家族。第一版不声称所有工具领域都零样本泛化。跨语言变体属于同源簇，不算新增独立历史。

第二模型先选择固定确认切片，只比较B1、M及必要外部基线。重新形成记忆并换Reader才是端到端跨模型；仅换Reader应单列为消费端迁移。

### 10.6 E5：功能集成回归

方法确定后，使用一个新候选完成旧L1、L2、L3、旧L4回归，并创作少量新功能故事。已封存r52结果原样保留，本轮不是补跑未执行r52。

覆盖保存确认、同ID更正、范围外不变、撤销、历史、遗忘、当前业务查询、partial、W1–W3、原保存续办以及失败不重复业务。普通语义失败如实记录，不为了凑全通过而删任务；安全或实际数据损坏问题停止受影响操作。

---

## 11. 指标与评价

### 11.1 两张主表

**公开任务主表：**HaluMem官方形成／更新／QA；LongMemEval分类与总分；若运行MemoryAgentBench则用其原指标。Judge失败、空返回与实际评分分母一起给出。

**语义编辑机制表：**

| 指标 | 要回答的问题 |
| --- | --- |
| 新要求完成率 | 应改变的内容是否正确更新 |
| 非目标语义损坏率 | 仍有效且此次不应改变的内容是否丢失、强化、错绑 |
| 局部覆盖正确率 | 范围内新规则与范围外原规则是否同时正确 |
| 合法撤销成功率 | 明确取消的条件是否真正退出当前状态 |
| 无依据新增率 | 是否添加原来源未支持的新事实、因果或规范 |
| 连续编辑漂移 | 随更新次数增加，正确要求保留与损坏如何变化 |
| 后续QA／行动 | 更新是否改善实际任务，而非只改善内部表示 |
| 可用性 | 未提交、误拒、截断、必要澄清、多余动作和恢复结果 |

对仍然可用但不确定的信息，评价恰当不确定性；不支持某命题不能自动推导其否定。

### 11.2 原提案、核对与终态分开

核对消融另列：无额外核对、现有同模型核对、必要时一次比较核对。不要把常驻核对作为新算法默认依赖。

分别报告初始正确→最终错误的破坏率，以及初始错误→最终正确的修复率。核对器自身的supported不能作为最终标注。若仍由开发者或同家族模型审查，要明确，不能称独立Judge。

### 11.3 统计与样本含义

按原用户／历史来源簇做配对分析，报告原始计数、配对差值与95%区间。小来源数下的区间可能很宽，应保留，不把多次调用当独立样本。机制切片是选择性诊断，不推断自然总体错误发生率。

方法内部检查题不兼作最终效果题。评估题、答案和人工标签不传给运行时编辑器；额外标注审查人员在可能情况下匿名看到方法输出。

不临时改变主指标、删去失败或用“没有显著下降”宣称非劣已被证明。需要非劣结论时先确定允许差异和分析方法。

---

## 12. 创新主张与决策

### 12.1 可以积极推进的候选贡献

1. **条件化编辑算子：**在同一记忆中区分局部覆盖与整体替换，并支持合法撤销。
2. **少生成而非多审核：**未编辑内容不反复进入重写过程，测试其对非目标语义损坏的影响。
3. **连续编辑可组合性：**观察多轮更新中保留、替代和撤销的语义效果，而非只测一次最终问答。

暂不使用“首次”“普遍保证”“彻底解决幻觉”。也不因某预印本讨论preservation就自动取消上述研究；应比较其具体实现与本方法是否相同。

### 12.2 用结果决定方法，不用发表状态决定方法

| 观察 | 决定 |
| --- | --- |
| B1与M相近，条件化结构无独立收益 | 采用B1交付功能，缩小算法贡献 |
| B2与M相近，表示有用而编辑无额外收益 | 主张表示／组织收益，不误称新编辑算子胜出 |
| M减少损坏，但明显损害合法更正与撤销 | 修订操作范围，不能以保守为由宣布成功 |
| M在真实形成、未调参来源和下游任务中稳定改善 | 继续形成方法论文与更完整消融 |
| 只有gold表示或人工完美来源选择下有效 | 说明抽取／定位瓶颈，诊断不替代部署成绩 |
| 公共数据不能评价局部覆盖 | 保留官方结果，补充明确命名的机制测试，限制对应泛化主张 |
| 不可运行近邻发布了代码 | 更新对照表，按实际价值补比较，不自动推翻已有结果 |

创新判断不打主观分数。论文可以由一个明确方法、一个失败机制和一套可复现证据构成，不需要每个模块都是新理论。

---

## 13. 实施文件与配置示意

### 13.1 优先修改位置

| 位置 | 工作 |
| --- | --- |
| 现有benchmark适配层 | HaluMem／LongMemEval loader、方法输出映射；避免重建实验框架 |
| `methods/` | 普通编辑、条件化编辑、共同输入和渲染；不是放进provider |
| `memory/` | 单元定位、普通ID／revision、一次提交、来源关联与历史 |
| `application/` | 继续保持真实对象、当前许可、业务回执和续办 |
| `providers/` | 模板、调用、容量、截断、实际用量，不解释业务语义 |
| `runners/` | 运行顺序和结果保存，减少提示与算法堆积 |
| `analysis/` | 官方指标适配、分母、配对分析和机制标注，不参与实时决策 |

### 13.2 普通配置示例

以下是设计示意，尚未承诺当前CLI已经接受：

```yaml
experiment_name: halumem_dev_local_edit
method: conditional_local_edit
model: existing_local_model
model_parameters:
  temperature: 0.2
  max_output_tokens: 8192
dataset:
  name: HaluMem-Medium
  path: data/HaluMem-Medium.jsonl
  split_file: data/user_split.json
memory:
  backend: existing_memory_service
  source_reference: id_revision_span
  edit_scope: single_level_override
  extra_reviewer: false
evaluation:
  official_metrics: true
  supplemental_preservation_audit: true
output_dir: results/halumem_dev_local_edit
```

温度及额度只是待选择值，不能将它们当成已验证最优配置。所有比较臂使用相同公开条件；正式运行前保存实际配置与方法版本名称，不执行SHA检查。

### 13.3 仅保留有用运行记录

```text
run_id / method / model / dataset_release / split
实际输入与顺序 / 原提案与编辑 / 来源ID
旧记录与新记录 / 实际工具结果 / 最终回答
官方评分 / 补充审查 / 失败阶段 / 调用与用量
```

运行途中改变方法就另起实验名称；日志不覆盖。结果文件和环境说明足够支撑本轮复查，不生成逐文件验真清单。成本按实际调用追加，不重新清零。

---

## 14. 本轮交付清单

1. 两个公开benchmark适配器，其中至少一个完成真实预测与评分接线。
2. 一个共用、无自研SHA门禁的正常运行底座。
3. 普通局部编辑与条件化局部编辑原型；同表示重写控制。
4. 一张配对开发结果表、一份误差分析和必要的外部系统对照。
5. 一个未调参来源与跨模型确认结果包，含尚未解决问题。
6. 功能回归结论和论文贡献草稿；不因功能交付自动改为Product可发布。

**第一步是P0 benchmark接线，第二步是共用底座和最小编辑器。不要再为追求“研究周全”先扩建另一套平台。**

---

## 15. 来源与核查入口

以下链接为本次检索／读取依据。发布日期与开源状态取决于查到的具体证据；访问失败只代表本次未读到。文档不附SHA或校验值。

### 方法论文与作者实现

**[R1] A-MEM**
- [论文：arXiv 2502.12110](https://arxiv.org/abs/2502.12110)
- [NeurIPS 2025正式论文目录，含A-Mem条目](https://proceedings.neurips.cc/paper_files/paper/2025/vol38-main-conference)
- [OpenReview记录](https://openreview.net/forum?id=FiM0M8gcct)；本次直接打开受浏览器验证阻断，正式发表以NeurIPS目录为依据。
- [当前论文复现仓库](https://github.com/WujiangXu/A-mem)；旧AgenticMemory链接已重定向。
- [系统集成仓库](https://github.com/agiresearch/A-mem)
- [已读取的系统实现片段](https://github.com/agiresearch/A-mem/blob/main/agentic_memory/memory_system.py)

**[R2] Hindsight**
- [ACL 2026 Demo正式条目](https://aclanthology.org/2026.acl-demo.27/)
- [早期研究系列arXiv 2512.12818](https://arxiv.org/abs/2512.12818)
- [作者代码与MIT声明](https://github.com/vectorize-io/hindsight)

**[R3] RARR**
- [ACL 2023 Long Paper正式条目](https://aclanthology.org/2023.acl-long.910/)
- [作者实现与编辑流程](https://github.com/anthonywchen/RARR)
- README使用历史模型与搜索API示例；本次未验证原依赖在当前环境直接可用。

**[R4] HiMem**
- [论文](https://arxiv.org/abs/2601.06377)
- [作者仓库、Apache-2.0声明与操作说明](https://github.com/jojopdq/HiMem)
- [已读取的构建入口](https://github.com/jojopdq/HiMem/blob/main/experiment/memory_construction.py)

**[R5] SimpleMem**
- [论文](https://arxiv.org/abs/2601.02553)
- [作者仓库、ICML'26标注及不同版本说明](https://github.com/aiming-lab/SimpleMem)
- [OpenReview记录](https://openreview.net/forum?id=oYHelQ3Edd)；本次直接访问受浏览器验证阻断。

**[R6] TrustMem**
- [论文及转换级核对／训练方法](https://arxiv.org/html/2606.25161v1)
- [作者宣布EMNLP2026录用](https://www.linkedin.com/posts/tianyu-yang-55654b246_trustmem-learning-trustworthy-memory-consolidation-activity-7496673552490745856-x5xw)
- 对论文链接与作者公开线索进行了代码检索；本次未确认官方代码、模型权重或复现入口。

**[R7] DeltaMem-RL**
- [论文：Towards Agentic Memory Management via Reinforcement Learning](https://arxiv.org/html/2604.01560v1)
- 所查版本摘要附有录用后开源的说明；本次未确认更新后的实际发布或正式会议条目。

**[R8] MemTX**
- [论文v2：Preprint／Under review声明](https://arxiv.org/html/2607.23929v2)
- [代码与数据仓库](https://github.com/lxy1134/MEMTX_)
- [已读取README](https://github.com/lxy1134/MEMTX_/blob/main/README.md)
- [已读取根目录](https://api.github.com/repos/lxy1134/MEMTX_/contents/)；代码、脚本、数据、结果和tests可见，根目录未见许可证文件；不是穷尽许可审计。

**[R9] StateMem／StateMemBench**
- [论文：Can Agent Memory Systems Track Evolving State?](https://arxiv.org/abs/2608.19652)
- 本次未确认论文自己的官方运行仓库、数据和scorer；不以其参考文献里的其他STATE-Bench冒充。

### Benchmark

**[B1] HaluMem**
- [论文：HaluMem: Evaluating Hallucinations in Memory Systems of Agents](https://arxiv.org/abs/2511.03506)；仓库使用另一较长展示标题，按同一论文标识对应。
- [作者仓库及EMNLP2026 Main录用公告](https://github.com/MemTensor/HaluMem)
- [官方数据卡](https://huggingface.co/datasets/IAAR-Shanghai/HaluMem)
- [Medium／Long实际文件目录](https://huggingface.co/datasets/IAAR-Shanghai/HaluMem/tree/main)
- [官方评测说明](https://github.com/MemTensor/HaluMem/blob/main/eval/README.md)
- [更新诊断使用参考memory_content的适配代码](https://github.com/MemTensor/HaluMem/blob/main/eval/eval_memzero.py)
- [分项评分与聚合入口](https://github.com/MemTensor/HaluMem/blob/main/eval/evaluation.py)

**[B2] LongMemEval cleaned**
- [论文](https://arxiv.org/abs/2410.10813)
- [作者仓库及ICLR2025声明](https://github.com/xiaowu0162/LongMemEval)
- [cleaned数据卡](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- [实际文件目录](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/main)
- [官方QA评分](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)

**[B3] MemoryAgentBench**
- [论文](https://arxiv.org/abs/2507.05257)
- [作者仓库、ICLR2026声明与指标对应](https://github.com/HUST-AI-HYZ/MemoryAgentBench)
- [OpenReview记录](https://openreview.net/forum?id=DT7JyQC3MR)；本次直接访问受浏览器验证阻断。
- [实际Parquet目录](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/tree/main/data)
- [官方字符串评分实现](https://github.com/HUST-AI-HYZ/MemoryAgentBench/blob/main/utils/eval_other_utils.py)

### MiLAi原始依据

**[M1] 当前r52结果**
- [开发实验终态](https://github.com/minguselandy/MiLAi/blob/main/MiLAi-Lab/docs/V13_5_R52_TERMINAL_REPORT.md)
- [L3明细](https://github.com/minguselandy/MiLAi/blob/main/MiLAi-Lab/docs/V13_5_R52_L3_RESULTS.md)
- [L4明细](https://github.com/minguselandy/MiLAi/blob/main/MiLAi-Lab/docs/V13_5_R52_L4_RESULTS.md)

**[M2] 已提供的v13.4退出报告**
- 对应附带文件 `V13_4_T0_RESULTS_AND_EXIT.md`，重点是第“G1与研究主张”节：退出复杂关系消歧选源，不作其他方法的全局否定。

**[M3] 已提供的方向与轻量开发规划**
- 项目原方向说明：Grounded Memory、Verified Object References、Semantic/Episodic、Grounded Revision、Lifecycle Recovery，一个MemoryService。
- `MILAI_FUNCTION_FIRST_DEVELOPMENT_EXPERIMENT_PLAN.md`：去除自研SHA、简化正常路径、保留实际业务语义。本文件将研究顺序进一步调整为benchmark先接线，然后局部方法开发。

---

## 最终执行口径

**以公开数据和可运行基线建立效果，再用局部编辑与条件化操作检验创新。**发表状态、代码开放性和方法重叠分开判断；未开源／未正式发表不自动否决，已有明确算法也不忽略。先交付可用实现，论文贡献由可复现结果决定，不再通过堆叠校验、哈希或审查循环来制造可靠性。
