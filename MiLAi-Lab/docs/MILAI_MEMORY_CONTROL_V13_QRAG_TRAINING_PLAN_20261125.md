# MiLAi V13：基于 Q-RAG 的训练开发与算法创新实验计划

**日期：2026-11-25（北京时间）**  
**资源：2 × NVIDIA A100 40GB**  
**用途：直接交给 Codex 实施的开发、训练、实验与结果交付规范**  
**状态：方案与公开源码核验完成；本文没有启动新 GPU 训练，也没有宣称新方法已经有效。**

## 0. 执行摘要与本轮决策

本轮以 **Q-RAG 为唯一主学习基线**，以 **GTE-reranker 306M 为主交互控制器**。保留 MiLAi 已有数据、真实读取运行器、Reader、原生评分器与结果账本，完成以下三层证据：

1. **训练有效性**：相同预训练骨干、相同可见信息和预算，真实任务训练优于未做控制训练的相关性策略。
2. **算法贡献**：在相同反馈预算下，多粒度配对收益学习与结构化分支采样，优于直接值回归、随机采样及必要的通用主动采样对照。
3. **工程价值**：算上控制器、Reader、检索与预处理开销，质量—成本前沿仍改善。Reader token 减少不自动等于实际加速。

主研发问题是：

> 在已有证据、已交付内容、候选预览和预算给定后，训练小模型判断下一次读取、升级或停止的终局价值，并更有效地分配训练时昂贵的 Reader 反馈。

### 0.1 固定选择

| 项目 | 本轮决定 |
| --- | --- |
| 原版方法参照 | Q-RAG / PQN，固定公开源码提交 |
| 项目主学习基线 | Q-RAG-MiLAi：双塔值学习接入本项目合法环境与终局 Reader |
| 主模型 | Alibaba-NLP/gte-multilingual-reranker-base，306M，全参数微调 |
| 第二骨干 | Qwen/Qwen3-Reranker-0.6B，仅用于能力复核，不首轮铺开全矩阵 |
| 主训练路径 | 证据/合法轨迹初始化 → 完整终局值学习 → 配对目标 → 有限反馈下采样 → 策略状态补采 |
| 主动作空间 | 现有可执行 READ、R2/R3 升级及 HANDOFF；具体动作 ID 沿用运行时 |
| 主数据 | MiLAi V1 clean train：MuSiQue-Full、QASPER、PersonaMem-v2 |
| 主预算 | 记忆材料 2,048 tokens；512/1,024 为副预算；上限与总输入分开记录 |
| 最大操作数 | 起始设为 6；公共初始检索按统一规则计费 |
| 候选规模 | 粗召回 32；精排 8；需要时统一扩为 16 |
| 主探索 | 集合条件下的多粒度收益学习与结构化反馈采样 |
| 后置探索 | 149M 蒸馏、短计划、PPO/GRPO、缓存调度、写入/删除 |

### 0.2 完成范围

本文要求 Codex 完成实质训练与完整运行评估，不以一次前向/反向、通过若干测试、训练 loss 下降作为项目完成。

开发任务可以在当前授权范围内连续推进；实际训练必须使用可访问的服务器、数据与既有 Reader 配置。本文中的新模块、配置和命令契约均是**待开发规格**，没有声称它们已经存在。原始数据与模型权重继续留在实验存储，不提交到 Git。

## 1. 已核实的代码与事实基线

### 1.1 版本

2026-11-25 重新读取 MiLAi 公开分支，以下相关版本与上轮核验一致：

| 项目 | 分支或版本 |
| --- | --- |
| MiLAi 实施基底 | review/memory-control-v12-plan2-20261123 |
| MiLAi review 提交 | 7bb27c1254e0ebd49acdbdbc4b09722f93ccecb3 |
| MiLAi 最新结果报告 | report/memory-control-v12-training-20261122 |
| 结果报告提交 | 35e1803ed413fd17fb587ff1c9db32f92acd7815 |
| MiLAi main | 2b4b17383d8d892d21651b02130b9e33deab5bec |
| Q-RAG 默认分支 | pqn-qa |
| Q-RAG 参照提交 | 42358d78ac491843763b90677f07237471c97086 |

开发从已核实的 review 源码建立独立工作分支，建议名称为 feat/memory-control-v13-qrag-20261125。不要只从较旧 main 推断 V12 能力不存在。[S1–S3]

当前核验不覆盖服务器尚未推送的改动。接手时保留已有工作树变更，读取实际工作区说明即可，无须再造审批或校验体系。

### 1.2 从已有结果继承的结论

- 现有训练已经使用 CUDA/BF16，不能继续把“没有用 GPU”当作默认解释。
- M1 未证明预期的 attention 架构优势；这不等于所有预训练小模型记忆控制均无效。
- 当前较高质量伴随较高 Reader 输入与实际时延，尚不能称效率成功。
- 旧短续跑目标、正式停止行为、MuSiQue 单题训练分与原生组终评分之间有需要处理的语义差异。
- 已公开分析的旧 CONFIRM 已经暴露，不能改名为新的独立确认集。[S2]

本轮保留已有有效实现，改变学习底座、回报接口与实验归因方式。

## 2. 基线选择：必须区分原版复现与项目适配

### 2.1 Q-RAG-Reference

目的：确认公开的小模型多步检索学习方法在本机资源下能够训练，并复现基本学习趋势。

沿用原版：

- MuSiQue-Ans 或官方 HotpotQA 配置；
- 预训练 state/action 双塔；
- 支持事实反馈；
- 原 PQN、TD 回报、目标网络与训练循环；
- 原文档块动作及其终止规则。

先完成一个官方任务配置的完整训练曲线，不要求首轮重现所有论文 benchmark。按 40GB 显存调整 microbatch、梯度累积与实际 BF16，记录资源适配；不要把作者 A100 80GB 的配方表述成已在 40GB 原样验证。[S3–S5]

原版结果单独报告，不与 MiLAi-Full 原生组分数直接相减。

### 2.2 Q-RAG-MiLAi

这是新方法的**主竞争基线**：

- 保留可训练双塔和 PQN/TD 学习路线；
- 使用本项目 clean split 与合法观察；
- 具有与新方法相同的 R2/R3、HANDOFF、预算和最多操作次数；
- 只在正式终止时调用固定 Reader；
- 使用同一 native task/group scorer；
- 所有候选、预览和信息权限一致。

适配改变了环境与奖励，应明确标为 Q-RAG-MiLAi，不能称原版论文结果的完整复现。

### 2.3 同骨干控制基线

GTE 双塔约有两个 305M 可训练编码器；GTE-reranker 是 306M 交互模型，二者不是等参数实验。[S6–S7]

因此还必须有：

- 冻结 GTE-reranker 的原生相关性排序＋调好的固定预算规则；
- 同 GTE-reranker、同数据、同菜单的直接终局 Q 回归；
- 同骨干、同数据的配对目标版本。

跨骨干结果回答表示选择问题；同骨干结果回答训练和算法问题。

## 3. Q-RAG 代码中必须正确处理的迁移差异

本节来自固定提交的实际源码，而非仅按论文摘要推测。[S4–S5]

| 差异 | 当前公开代码 | MiLAi 适配要求 |
| --- | --- | --- |
| GT 奖励时点 | 首次收齐支持事实时给 completion reward；可继续到步数上限 | 原版保持；项目终局目标另设明确适配 |
| Reader 反馈 | AnswerMetricFeedback 每步调用 Reader，忽略 is_final，返回当步绝对质量 | 改为正式 HANDOFF/硬终止时一次任务回报 |
| 默认 Reader 协议 | BabiLong 提示与评价 | 共用 MiLAi DatasetReader 和 scorer |
| 联合环境配置 | HotpotQA+MuSiQue 直接内联 GroundTruthFeedback | 不能只改顶层 feedback.type 就认为切换成功 |
| 数据集 | loader 读取 musique_ans_v1.0_train/dev.jsonl | 项目使用 Full 原生可答/不可答组 |
| 动作与停止 | 文本块 index；耗尽候选或 max_steps 终止 | 显式 HANDOFF 与读取动作同域评分 |
| 候选观察 | 原版编码候选正文 | 所有项目方法共用同一合法预览协议 |
| 两路 Q | 两路估计共同拟合同一回报 | 不能改名后当成质量/成本两个监督头 |
| 精度 | 入口的 BF16 示例处于注释中 | 实际启用并记录 autocast、optimizer dtype |

### 3.1 新 terminal feedback 的明确语义

1. READ/UPGRADE 过程中 task_reward=0。
2. 正式 HANDOFF、预算耗尽或实际终止时，生成正常交付包并调用 Reader。
3. 每个任务终局回报只计一次；终端状态不 bootstrap。
4. MuSiQue-Full 的组级结果在 scorer 侧聚合，见第 6 节。
5. 操作成本逐步记录，Reader 费用记在实际发生位置。
6. 基础设施失败与语义答错分开：失败调用计成本，未知质量保持 mask；有效返回但答错按正式指标计分。

不能通过每步累计绝对 QA 分数，把“多读多答”变成额外收益。

项目主目标采用有限操作上限下的未折扣终局质量，QR 适配显式设置 gamma=1；否则相同答案质量会因终止步数不同而被隐式打折，与 Direct-Q/Paired-Q 的目标不一致。成本由明确的成本项承担。REF 保留官方折扣与原始训练语义，另表报告。

正常 HANDOFF、材料预算耗尽和任务定义的操作上限均产生正式交付与终局结果。仅因采集器批次、进程时间或训练窗口而截断的轨迹不是正常终端，不能补一个零回报并禁止 bootstrap；应续跑恢复，或标成未完成、排除出完整终局监督。

## 4. 研究问题与创新边界

### 4.1 主问题

在冻结 Reader 与统一合法观察下，学习：

> 哪个对象值得读取、需要哪个粒度、是否应当继续，以及有限的训练反馈应该优先花在哪些操作比较上。

主探索由两个相互关联的部分构成：

- **多粒度条件收益学习**：对同一对象的合法粒度共享语义编码，学习当前证据集合下的质量与未来成本。
- **结构化反馈采样**：在相同 Reader 反馈额度下，优先探测可能改变实际动作选择的粒度/对象比较。

共享编码是一项公平提供给对照的工程实现；研究贡献需要由反馈效率和实际任务收益建立。

### 4.2 最接近的方法与必须超越的点

| 工作 | 已有内容 | 本项目不能直接声称的新颖点 |
| --- | --- | --- |
| Q-RAG / Plan Q-RAG，ICLR 2026 | 条件多步价值、规划、停止讨论 | 多步 Q、加 beam、学习检索 |
| RAA，2026-11 预印本 | 0.6B 重排器、教师监督、分辨率学习、单对象尺度扰动 | attention 映射记忆、小模型分配粒度 |
| FlexA-Mem，2026-10 预印本 | 按预算组织记录、片段和原文 | 多档文本表示、原始内容可恢复 |
| Mem-T，ICML 2026 | 记忆操作树和信用分配 | 树搜索、终局奖励回传 |
| SCCG，2026 期刊工作 | 生成器状态条件下的文档效用 | “相关性不等于实际收益” |
| UpliftMem，2026 预印本 | 集合执行增益与 EVSI 反馈分配 | 主动探测、集合效用本身 |

上述近邻见 [S8–S13]。首轮实现仍收敛到 Q-RAG/GTE；近邻转化为必要的机制对照，不同时重建全部系统。

### 4.3 可证伪假设

- **H1**：相同 GTE 骨干，经真实结果训练后，能优于原生相关性策略。
- **H2**：相同实际反馈预算下，结构化多粒度采样改善学习曲线，并超越随机及必要的通用采样对照。
- **H3**：算上控制器与 Reader 的实际开销后，收益仍存在，并可迁移到新原生组或未训练预算。

H2 是主创新探索，尚不是已证明的首创或成功结论。若仅 H1 成立，交付有效工程方法，论文贡献相应收缩。

## 5. 数据选择、划分和旧资产

### 5.1 V1 历史清单及含义

用户已验收 V1 为 DATA_PREP_COMPLETE，位置为 /cra/milai-datasets/memory_control_v1。历史文档记录如下；Codex 启动时从已有 SQLite/报告导出当前库存与暴露角色，不能把历史数字当作服务器实时测量。

| 来源 | 官方 train 任务 | clean train 任务 | 官方 validation 任务 | 划分单位 |
| --- | ---: | ---: | ---: | --- |
| MuSiQue-Full | 39,876 | 39,876 | 4,834 | native pair / question group |
| QASPER | 2,593 | 2,593 | 1,005 | paper_id |
| PersonaMem-v2 | 18,549 | 1,460 | 2,061 | persona_id |
| 合计 | 61,018 | 43,929 | 7,900 | 分来源原生组 |

68,918 是全库任务数，206,657 是全库决策状态数，198,079 是有已知弱证据标签的全库状态数。它们不是 206,657 个独立训练任务。

PersonaMem 的 17,089 项排除清单继续生效。1,460 个 clean 任务也不等于 1,460 个独立 persona。

### 5.2 三源职责

| 来源 | 主要训练与诊断作用 |
| --- | --- |
| MuSiQue-Full | 多跳互补、桥接、可答性、过早停止 |
| QASPER | 长文档、片段到原文升级、多参考、不同证据组合 |
| PersonaMem-v2 | 偏好、重复、版本更新、历史条件依赖 |

第一轮证据初始化可先用 MuSiQue 可答且支持事实完整的部分；正式 Reader 训练和主结果必须明确覆盖 Full，不将 Ans 成绩当 Full 成绩。

### 5.3 数据角色

- TRAIN：证据初始化、成功轨迹、真实分支、主动采样。
- TUNE：超参数、模型选择和错误分析；已曝光旧 DEV/CONFIRM 可明确转作诊断。
- CALIBRATION：固定策略族的预算/停止参数选择。
- CONFIRM_FRESH：未参与训练、选择、主动采样或逐组分析的原生组。

沿用现有 group split、排除清单、run id 和 ledger，新增角色字段或清单即可。无需新建 SHA、内容指纹或第二套审计基础设施。

当前旧 1,500-task/620-group CONFIRM 已经被分析，不能重新作为盲测。库存不足不阻塞开发训练，但最终结论必须标明证据范围；新增确认需来自真正未暴露的组或独立评估渠道。

主训练从通用 GTE 基础权重初始化。公开 MuSiQue-ft checkpoint 可能已看过本项目从官方 train 划出的组，作为外部参考时须说明暴露，不能代替干净重训。

### 5.4 旧数据复用

| 资产 | 继续使用 | 不能直接做 |
| --- | --- | --- |
| 已知弱证据 | 初始化、示范、覆盖诊断 | 当作实际 Reader 收益 |
| 已有 Reader 返回 | 同请求/同解码/同评分语义下复用和重评分 | 因文本相似就跨协议复用 |
| 旧 h2 分支 | 明确的短程辅助与选样线索 | 改名为完整 continuation Q |
| 旧策略访问状态 | 合法观察复用，并按新策略重新续跑 | 不重放就替换后续策略标签 |
| 历史负结果 | 失败分析和工程基线 | 换名称恢复独立确认资格 |

## 6. 原生奖励：尤其处理 MuSiQue-Full

### 6.1 正式主质量

项目三源宏指标固定为：

\[
Q_{\rm macro}=100\times
\frac{Q_{\rm MuSiQue\ pair}+Q_{\rm QASPER}+Q_{\rm Persona}}{3}.
\]

各来源同时单独报告；不能让大来源的任务数量掩盖另一来源退化。

- MuSiQue-Full：正式 native pair 门控质量。
- QASPER：沿用原生多参考 answer F1 协议。
- PersonaMem-v2：冻结 MCQ 选项协议后的准确率。

### 6.2 Pair continuation 的执行办法

每轮冻结策略 pi_k。一个 before 状态属于 pair 的一个成员时：

1. 对该成员执行候选首动作并完整续跑，得到其终端 Reader 返回。
2. 对另一成员独立从其合法初始状态执行 pi_k，取得 companion 结果。
3. 在 scorer 侧结合两者，按现有 pair 规则给分。
4. 相同 group、策略、预算、Reader 和随机配置的 companion 可以按现有账本语义复用。
5. 不向控制器输入 companion 的问题、答案、gold、执行结果或不可见状态。

该标签是对冻结 pair continuation 的条件价值。最终评估时，每个候选策略必须自行运行 pair 两成员再聚合，不能沿用训练时固定的 companion。

同时保存可答题 F1、可答/不可答充分性正确率和最终 pair 分，以解释全零标签与过早停止。单题辅助目标可帮助初始化，但主结果训练不能把其均值冒充 pair 主回报。

## 7. 统一环境、信息与预算

### 7.1 在线状态

\[
x_t=(q,E^{acquired}_t,E^{delivered}_t,D_t,\ell_t,b_t,h_t).
\]

分别保留已获取、已交付、合法候选预览、当前粒度、剩余预算与操作历史。MiLAi 已有两种证据角色，不能简单把所有已获取内容视作 Reader 已使用。[S1]

序列化从 control_observation 的合法投影生成；不从数据库额外拼入未读正文或答案。

### 7.2 读取粒度

第一版只使用当前运行时真实存在的 R2/R3 与 HANDOFF。若两级给出相同交付，单列等价动作，不用它们占满粒度训练份额。

新增“记录→证据→原文”三级映射仅在有必要且当前运行时能支持时开展，并同步提供给所有主对照。抽取式嵌套跨度有利于定义新增信息；摘要不天然是原文的严格子集，不能假称信息严格单调。

候选预览是导航信息。是否将其交付 Reader 由正常执行流程决定，不得提前白读候选全文。索引构建和预览生成的成本单列摊销。

### 7.3 主资源设置

| 字段 | 默认 |
| --- | --- |
| memory_budget_tokens | 2,048 |
| 副预算 | 512、1,024 |
| max_operations | 6 |
| retrieval_candidates | 32 |
| scored_objects | 8 |
| controller_max_tokens | 2,048 |
| reader_protocol | 沿用固定 MiLAi 配置 |
| task reward timing | terminal_only |

2,048 是新增记忆材料预算，不是整个 Reader 输入；系统提示、问题、输出、缓存计价仍需实际记录。

控制器输入超长采用固定字段配额与来源明确的抽取；候选、任务和预算不得被统一右截断吞掉。2K→4K、8→16 只作共同的、预先记录的资源调整。

Host 负责确定性预算、合法动作与去重。预计时延不是硬时延保证；若设置真实超时，超时后果进入正式评价。

## 8. 控制器结构与多粒度收益面

主骨干为 GTE-reranker 306M，全参数更新；Reader 全程冻结。[S7]

对每个对象 i 一次联合编码：

\[
h_i=F_\theta(q,E^{acquired},E^{delivered},D_i,\ell_i,b,h).
\]

由 h_i 与小型粒度/成本特征输出每个合法粒度的：

\[
\widehat Q_R(x,i,\ell),\qquad
\widehat Q_{C,future}(x,i,\ell).
\]

HANDOFF 使用同一模型的状态哨兵输入。已知即时费用由运行时加回，模型不需要猜合法性和精确 token 数。

同一对象的多个粒度共享 backbone 前向，不执行 K×L 次完整交互编码。所有同骨干对照均使用这一优化。不同对象之间仍须重复处理状态；双向 cross-encoder 没有免费的通用 KV 前缀复用。

质量允许随粒度下降，未来总成本也允许因更完整读取而减少。禁止强制“更长必然更好”或“总成本必然单调增加”。

原始 GTE relevance score 可作初始化/辅助，不能直接解释为终局收益。

## 9. 完整 continuation 数据与值目标

每轮冻结一个后续策略 pi_k、Reader、环境和预算协议：

\[
Q_R^{\pi_k}(x,a)=
\mathbb E[R_{\rm final}\mid x,a,\pi_k\ {\rm until\ termination}],
\]

\[
Q_C^{\pi_k}(x,a)=
c_{\rm immediate}(x,a)+
\mathbb E[C_{\rm future}\mid x,a,\pi_k].
\]

完整续跑直到正常 HANDOFF 或同一硬上限。不能仅把旧 h2 参数设成一个大值后仍隐含强制停止，需明确 continuation_mode=full_episode。

同一后续策略允许各分支根据新观察采取不同动作。固定的是决策规则，不是强行固定一串后续动作。

### 9.1 每个根状态的结构化分支

优先覆盖：

1. HANDOFF；
2. 当前参考策略的最佳合法读取；
3. 同一对象的另一合法粒度；
4. 最有竞争力的另一个对象动作。

相同动作去重；不足四项时不填无意义副本。未执行动作保持未知。

首版统一以“一个root及上述去重动作组成的比较包P”为选样单位。包内预定义比较包括读取/HANDOFF、同对象R2/R3以及参考读取/竞争对象。各采样器共用同一包生成器，选择一个包后执行其中尚无兼容结果的分支，不因采样器不同而免费增减分支。

Uniform先按统一来源与原生组约束抽样，再在合格比较包中均匀选择；Structured、High-uncertainty和Generic EVSI-style使用相同资格集合，仅改变包的优先分。参考读取和竞争动作由该阶段冻结的共同规则生成，不能在采样机制对照中分别由两臂的最新模型更换。

### 9.2 建议追加的数据字段

复用现有表和结果实体，最少记录：

~~~yaml
root_state_id: existing_state_id
native_group_id: existing_group_id
source: musique_or_qasper_or_persona
split_role: train
collection_round: 0
continuation_policy_id: existing_checkpoint_or_run_id
continuation_mode: full_episode
first_action_id: bound_runtime_action
remaining_material_tokens: measured_integer
termination_reason: handoff_or_budget_or_max_operations
reader_quality: observed_native_score
quality_observed: true
reader_receipt_ids: []
companion_receipt_id: null
future_cost_observed: true
controller_gpu_ms: measured_value
reader_input_tokens: measured_integer
reader_output_tokens: measured_integer
acquisition_method: uniform_or_structured
mechanism_intervention: false
~~~

这是字段契约示例，不要求新造第二个数据库。没有实际测量的字段为 null/unknown，不填0伪装观测。

### 9.3 旧轮标签

Q(pi_k) 与 Q(pi_k+1) 是不同目标。默认每轮继续训练已有参数，但真实结果监督主要使用本轮目标；旧轮结果不无标记合并。

可以使用旧数据做明确的历史目标辅助、语义初始化或采用经验证的策略条件化 critic。首版不依赖后者。

## 10. 训练目标与直接对照

质量使用正式 0–1 主分；成本使用训练集确定并冻结的尺度归一。先按 root state 对动作/动作对取均值，再按原生组与来源设权，避免一个状态因动作对多而获得 O(A²) 权重。

### 10.1 Direct-Q

\[
L_{\rm direct}=
L_{\rm Huber}(\widehat Q_R,R)
+0.1L_{\rm Huber}(\widehat C_f,C_f).
\]

包含已测 HANDOFF，未测动作不产生标签。

### 10.2 Paired-Q

在完全相同的数据、骨干和有效曝光上增加：

\[
L_{\rm pair}=
L_{\rm Huber}(
\widehat Q_R(x,a)-\widehat Q_R(x,b),R_a-R_b).
\]

初始总损失：

\[
L=L_{\rm direct}+0.2L_{\rm pair}.
\]

差值很小或不稳定时降低该对权重；不将噪声强行转成确定正负偏好。可加同状态成本差辅助，但先作为单独消融，不首版同时堆叠多个排序/成功成本目标。

### 10.3 集合条件反转：条件追加

仅当模型对已读集合利用不足时，增加少量真实验证状态对：

- 问题、候选和剩余预算尽量相同；
- 一个状态已含重复事实，另一个缺失；
- 或一个状态具有桥接前提，另一个缺失；
- 每个状态都实际测候选动作与 HANDOFF 的结果。

监督两个状态的增益差，不用手写规则直接指定收益真值。占反馈额度最多10%–20%，单独标为训练干预；自然分布确认不按这种富集比例重加权。

所有相应 Reader 调用扣原反馈额度。若对照未获得同样状态包，不把效果归因于损失本身。

## 11. 预算读出与部署

在 Host 的合法动作集合内：

\[
a^*=\arg\max_a
\left[\widehat Q_R(x,a)-\lambda\widehat Q_C(x,a)\right].
\]

HANDOFF 与其他动作同尺度比较。成本头有无直接参与、lambda取值和硬预算均写入配置，不能由 weak/outcome 模式暗中决定停止权限。

lambda 初始开发候选可取归一化尺度下的 {0,0.02,0.05,0.1,0.2}；在 CALIBRATION 上按预定质量—成本目标选取。该小网格不构成创新，也不自动保证平均成本约束。

主训练保持2,048材料预算，512/1,024作零额外训练的预算迁移评价。若后续做多预算训练，预算改变造成后续行为变化时要重新采集目标，不能只改输入中的预算数并复制同一标签。

## 12. 结构化主动采样：主创新探索

### 12.1 冷启动与基本方案

前2,000次反馈先做均匀/分层采样，建立值头。后续每批：

- 25%实际反馈额度保持随机探索；
- 75%用于可能改变动作选择的对象/粒度比较；
- 每批采集前冻结模型，采集后再更新；
- 相同来源、原生组曝光约束和合法候选生成规则适用于各采样器。

四个轻量 bootstrap value heads 共享一个 GTE backbone；按 native group 分配 bootstrap 权重。四个头不是四个完整模型，也不是校准置信区间。

DQ、PQ-U、PQ-A 都保留相同的四头容量与优化曝光；正式策略用各头均值作为质量/成本估计，主动采样额外使用头间分歧。这样 PQ-A versus PQ-U 的差异不会混入额外模型容量。分歧接近零不意味着目标已确定，仍保留随机反馈覆盖。

对动作对(a,b)，第h个头的净优势为：

\[
d_h=(Q_{R,h}(a)-Q_{R,h}(b))
-\lambda(Q_{C,h}(a)-Q_{C,h}(b)).
\]

第一实现可使用透明的启发式：

\[
p(P)=
\frac{\max_{(a,b)\in\mathcal{B}(P)}
\max(0,\operatorname{IQR}(d_h)
-|\operatorname{median}(d_h)|)}
{\widehat C_{\rm feedback}(P)+\epsilon}.
\]

其中B(P)为共同包内预定义的动作比较集合。全为0时回退均匀采样。分母计整个待执行包的成本，包括所有尚未获得的终端分支、必要companion与预期重复；不能只按最有分歧的两个动作收费却实际执行四个分支。已有可兼容记录由所有方法共同复用。

这是决策分歧启发，不声称严格 EVSI 或理论最优。部署阶段不进行这些 Reader 探测。

### 12.2 必须区分两种实验

**采样机制实验**：固定相同初始权重、未标注根状态池、pi_k与预算，只改变哪些合法分支被执行。这样可单独检验采样器。

**自然在线方法实验**：各方法随更新访问自己的状态、使用自己的后续策略，在相同反馈预算下比较完整学习流程。状态分布不同是算法行为的一部分。

不能一面要求两者完全同数据，一面宣称比较了自然在线学习。报告分别标记。

首版将机制实验嵌入现有额度，避免再付一套重复标签费用：PQ-U/PQ-A 的前2k调用使用共同的均匀初始化；从2k到6k，固定共同TRAIN根状态池、规则后续策略pi_0、分支生成规则与预算，分别均匀/主动选包。6k检查点命名为 **MECH-U / MECH-A**，这一比较可以单独解释采样差异。

2k到6k期间可以更新值模型和采样分数，但所有分支续跑与MuSiQue companion始终使用共同pi_0。6k模型在相同自然DEV任务上运行完整策略并评价，不以各自选中的训练root误差作为反馈效率证据。

6k之后，各自冻结由6k模型得到的pi_1，收集自身实际访问状态，再推进12k和24k。此后的PQ-A/PQ-U比较回答完整流程的效果，不单独归因于采样器。旧pi_0标签按第9.3节处理，不混充pi_1真值。共同状态池生成所需的计算及任何Reader调用照常扣账；只从TRAIN生成，不使用确认组。

每个独立采集seed内部两臂共享同一warm包与初始化。不同seed默认重新采集warm；若跨seed复用warm，只能称为给定warm条件下的采集重复，报告中明确这一条件。

### 12.3 对照顺序

1. Uniform：必做。
2. Structured：主方法。
3. High-uncertainty：主方法初见增益后加入，检查是否仅“不确定性采样”已足够。
4. Generic EVSI-style：准备算法论文结论前加入，检查多粒度结构是否有独立价值。

UpliftMem 已研究集合效用与 EVSI 探测。[S13] 通用 EVSI-style 适配应说明其高斯假设与协方差/噪声估计，不冒称原论文完整复现。若不能超过该对照，应将主动部分定位为已有方法迁移。

以上首先检验同一比较包空间内的选样规则。如果进一步主张“多粒度比较包结构”本身创新，需要另做同一选样评分下的结构化包 versus 非结构化合法动作对；保持预算、信息、组曝光与成本计算一致，额外费用单列。仅胜过Uniform不能证明包结构的独立贡献。

## 13. 实验编号与最小矩阵

### 13.1 方法与骨干

| ID | 方法 | 数据/回报 | 主要用途 |
| --- | --- | --- | --- |
| REF | 原版 Q-RAG | 原版Ans/GT/PQN | 校准公开训练路线 |
| RULE | 现有强固定策略、BM25/原生GTE、规则预算装包 | 无新控制训练 | 工程与预训练底线 |
| QR | Q-RAG-MiLAi 双塔 | Full/native终局/PQN | 主学习基线 |
| DQ | GTE306M，Direct-Q，均匀分支 | 完整continuation | 同骨干训练对照 |
| PQ-U | GTE306M，Paired-Q，均匀分支 | 与DQ同结果包 | 配对目标贡献 |
| PQ-A | GTE306M，Paired-Q，结构化采样 | 等反馈预算 | 主方法与采样贡献 |
| MECH-U / MECH-A | PQ-U/PQ-A的6k机制检查点 | 共同状态池、共同pi_0，仅选包规则不同 | 单独识别采样器贡献 |

所有项目学习方法拥有相同菜单、停止权限、合法观察和硬预算。DQ/PQ-U共享对象单次编码、成本读出、真实结果数据、训练曝光及优化设置，只改变明示目标。

QR 保留在线PQN语义；将其改为静态MC训练的版本只能命名为受控Q-RAG-style适配，不能替代QR却仍叫原版。

### 13.2 必做机制消融

- PQ-U versus DQ：同结果包，配对目标是否有增益。
- MECH-A versus MECH-U：固定共同池与后续策略，采样器本身是否有增益。
- PQ-A versus PQ-U：相同反馈额度，含各自状态分布与后续策略的完整流程是否有增益。
- Full-level versus fixed-level：其他条件相同，粒度选择是否有增益。
- 已读证据条件诊断：在匹配长度/预算的诊断集移除或替换证据语义，检验模型是否真的使用集合条件。

最后一项的输入破坏只作为诊断；若开展训练消融，独立训练并清楚标注，不能污染主模型数据。

### 13.3 正式确认控制规模

主确认只保留两个预定比较：

1. PQ-A（或开发期冻结的最终方法）对同骨干最强对照。
2. 最终方法对DEV预选的最强实际基线。

若最终方法被简化为PQ-U或DQ，应如实改写贡献。模型与方法在确认之前冻结，不根据确认结果再次选择获胜版本。

第二骨干、学生和大量机制消融留在开发/补充研究，不首轮展开骨干×目标×预算×seed全笛卡尔积。

## 14. 训练阶段、曝光与配置

### S0：数据契约与真实批次性能测量

- 导出当前clean组库存和角色，继承排除清单。
- 验证合法输入、终端回报、group reward和真正骨干更新。
- 用64–128个真实状态测显存、吞吐与Reader持续处理速率；结果纳入训练资产。
- 完成这些必要检查后进入正式训练，不重复停留在smoke阶段。

### S1：原版参照与证据初始化

- REF选择一个官方Ans/GT任务配置，完成有验证曲线的训练。
- GTE306M使用全部符合角色要求的已知证据与合法成功路径，1–2个有效遍历。
- group-first来源抽样起点Mu/Q/P=0.50/0.35/0.15；Persona达到组曝光上限后将槽位分配给其他来源。
- 不给未知STOP伪造成功标签；完整成功示范必须合法到达。
- 原生组、任务、state、action-pair和optimizer updates分别统计。

### S2：12k反馈阶段

QR、PQ-U、PQ-A分别在累计12,000次训练反馈额度处产生可评估模型；PQ-A前2,000次为均匀初始化。

PQ-U/PQ-A在累计6k处先完成共同池/共同pi_0的MECH-U/MECH-A比较，再按第12.2节转换到各自策略状态分布。该6k已包含在12k/24k额度内，不另收费，也不因其是中间点就额外铺开超参搜索。

DQ使用PQ-U结果包训练，不再生成一份重复Reader标签。初次仅seed11选择固定配方。

采样根状态构成的起始目标：

| 来源 | 目标份额 | 原生组曝光上限 |
| --- | ---: | --- |
| MuSiQue-Full | 60% | 每轮每pair最多4个before |
| QASPER | 30% | 每轮每paper最多6个before |
| PersonaMem-v2 | 最多10% | 每轮每persona最多6个before |

份额是选样起点，不改变最终三源宏评价权重。Persona库存不足不复制补齐，余量按Mu:Q=2:1分配。

每状态最多4个主要分支只是计划上界。实际状态数量由companion、重复、失败与标签覆盖共同决定，不能承诺12k调用一定得到3k完整独立状态组。

### S3：24k反馈阶段与完整策略更新

在相同反馈预算下将QR、PQ-U、PQ-A推进到累计24,000；至少进行两轮“冻结策略→采集→更新”，不依赖永久固定旧h2目标。

记录6k/12k/24k反馈检查点的开发学习曲线；6k仅作曲线点，不另做大范围超参选择。

不同方法各自运行阶段形成的结果包保持独立。采样机制归因使用第12.2节的6k共同池/共同pi_0检查点；12k/24k的自然在线结果不混入该归因。

### S4：重复、区分与确认

- 在冻结数据包上，用seeds11/29/47复核最终同骨干方法，隔离拟合随机性。
- 若保留主动采样与反馈效率结论，至少补两次独立采集种子复核PQ-U/PQ-A，重复相同的6k机制点和12k在线点。共享数据上的三次拟合不能代替此项；24k若只有seed11，仍标为单次扩展结果。
- 有主动采样增益后，再加入High-uncertainty与Generic EVSI-style必要对照。
- 完成未暴露原生组确认与实际成本报告。

### S5：条件扩展

训练效果明确后，蒸馏到ModernBERT149M；重新执行Reader验证效果与成本，不只测动作一致率。

Qwen0.6B用于第二骨干复核或GTE能力不足时的替代。只有在正式训练仍显示明确缺口时，再研究PPO/GRPO、短计划、奖励塑形与缓存。

### 14.1 起始训练参数

| 参数 | 起点 |
| --- | --- |
| 精度 | BF16 |
| controller sequence length | 2,048 |
| 有效batch | 32个root-state group |
| microbatch | 1–2个state group，按实测调整 |
| AdamW learning rate | 1e-5 |
| 小范围候选 | 5e-6、1e-5、2e-5，仅开发期 |
| weight decay | 0.01 |
| warmup ratio | 0.05 |
| gradient clipping | 1.0 |
| 结果数据遍历 | 每轮3次，开发时最多5次 |
| scheduler | 按本轮实际更新数预先确定 |
| encoder训练 | 全参，不能只训练末端头 |
| Reader训练 | 冻结 |

同数据目标消融的遍历、窗口归一、学习率和选择机会完全一致。真实数据不足时不能靠复制状态假装新增独立样本。

## 15. Reader预算与实验总账

### 15.1 首轮主采集上限

| 采集臂 | 中间点 | 累计上限 |
| --- | ---: | ---: |
| QR在线训练 | 12,000 | 24,000 |
| PQ-U均匀分支 | 12,000 | 24,000 |
| PQ-A结构化分支 | 12,000 | 24,000 |
| 三臂合计 | 36,000 | 72,000 |

每臂额度包括主分支、MuSiQue companion、重复、产生费用的失败/重试，以及额外教师Reader调用。一个完整轨迹不必然只含一次有成本调用；按实际记录扣账。

若PQ-U/PQ-A共享初始已付费数据：在每臂feedback exposure中都计入，但项目真实新请求只计一次。现有兼容记录也应分别报告“可用监督量”和“本次新增成本”，避免以大量旧标签免费获得不公平优势。

### 15.2 其他费用单列

- REF主要使用支持事实训练，GPU成本单列；Reader评价另计。
- 开发Reader评价建议设12,000次的计划池，按固定检查点和候选数分配。
- 最终确认预算根据真正未暴露任务数、正式方法数、种子与重复计算，不预称1,500任务必然充分。
- 独立采集复核：对PQ-U/PQ-A各补两次12k额度，新增上限48,000。若保留主动采样或反馈效率的稳定性结论，这项是必要追加，不是可以省略的确认；若该模块无增益并删除其贡献，可以不继续花费。首轮72k加此项后的主采集计划上限为120,000，评估与额外采样器对照仍另计。
- Qwen第二骨干、149M蒸馏、通用采样区分、交互式验证分别登记，不能隐入72k。

先执行每臂12k阶段，再依据开发证据推进24k及必要重复。72k只表示首轮探索上限；停在单次采集时，不宣称已经证明采样效率的稳定性。这是控制研究投入的顺序，不把测试数量或Reader调用数量本身当成果。

### 15.3 反馈效率图

至少绘制：

1. 宏质量与分来源质量 versus 实际Reader反馈调用；
2. 同上 versus 标注输入/输出token或实际费用；
3. 同上 versus 训练GPU-hours；
4. 部署质量 versus 实际总成本；
5. 部署质量 versus 端到端p50/p95时延。

“相同调用次数”不代表相同token费用，必须同时给第二条曲线。不同模型的一枚token不能直接相加作为等价计算量。

## 16. 2×A100 40GB的资源与调度

标准混合精度Adam模型状态可按16–18字节/参数保守估算；实现可能不同。[S14]

| 参数规模 | BF16权重，GB | Adam模型训练状态，GB |
| --- | ---: | ---: |
| 149M | 0.30 | 2.38–2.68 |
| 306M | 0.61 | 4.90–5.51 |
| 600M | 1.20 | 9.60–10.80 |
| 2B | 4.00 | 32–36 |

以上不含激活、临时张量、Reader、缓存及通信。Q-RAG还含双塔与目标/策略副本，不能按一个305M估算；两卡DDP也不等于单卡80GB。

### 调度方式

- Reader单卡能容纳：一张卡负责固定Reader服务，另一张卡训练小控制器；实际共享GPU时计入争用。
- Reader占两卡：分时完成采集和训练，批量提交任务减少碎片；不重复分配同一显存。
- 可预先tokenize并批量加载；可训练encoder更新后，不能继续使用旧永久embedding缓存。
- 动态padding、批量对象编码、梯度累积优先；不因低影响包装函数引入复杂服务层。

时间按实测估计：

\[
T_{\rm fit}\approx N_{\rm updates}\times t_{\rm update}+T_{\rm eval},
\quad
T_{\rm rollout}\approx N_{\rm calls}/r_{\rm sustained}.
\]

例如6,000状态、3遍历、batch32约563次更新；2秒/更新的纯拟合约19分钟，10秒/更新约94分钟，均未含评估与采集。这个例子是算术估算，不能用训练时长直接判定充分或不足。

GPU-hours按每张卡占用时间求和；墙钟时间独立测量。正式报告必须包含真实曝光、训练曲线和端到端收益。

## 17. 开发模块与最小改动

### 17.1 复用现有能力

以下路径相对MiLAi仓库根，具体函数以已核实review版本为准。

| 文件 | 本轮使用方式 |
| --- | --- |
| MiLAi-Lab/src/milai_lab/methods/memory_control.py | 正式state/action/menu与执行；增加显式完整continuation模式 |
| MiLAi-Lab/src/milai_lab/methods/dataset_corpus_runtime.py | R2/R3、真实预算、去重与交付，不复制简化环境 |
| MiLAi-Lab/src/milai_lab/methods/control_observation.py | 合法投影与已获取/已交付角色 |
| MiLAi-Lab/src/milai_lab/methods/memory_control_dataset.py | clean组索引与token输入collator |
| MiLAi-Lab/src/milai_lab/methods/dataset_reader.py | 统一Reader请求和上下文 |
| MiLAi-Lab/src/milai_lab/runners/memory_control_episode.py | backend注册、完整episode和成本记录 |
| MiLAi-Lab/src/milai_lab/runners/memory_control_outcome_run.py | 分支执行、Reader回包和现有账本 |
| MiLAi-Lab/src/milai_lab/datasets/memory_control_outcomes.py | 已测掩码、协议标签、分支差值 |
| MiLAi-Lab/src/milai_lab/scorers/memory_control_native.py | 原生评分 |
| MiLAi-Lab/src/milai_lab/scorers/memory_control_episode_metrics.py | group聚合与正式指标 |

### 17.2 建议新增职责

| 建议文件，待开发 | 职责 |
| --- | --- |
| methods/pretrained_control.py | 双塔/交互模型、共享粒度头、保存加载 |
| methods/control_state_text.py | 有字段配额的合法状态文本 |
| runners/qrag_milai_env.py | Q-RAG到CorpusExecution的适配及terminal feedback |
| runners/pretrained_control_train.py | 初始化、Direct-Q/Paired-Q、PQN接口 |
| runners/control_policy_iteration.py | 冻结策略、采集、采样器、更新 |
| configs/memory_control_v13/ | 少量明确对照配置 |

文件可按现有仓库规范合并，以上是职责划分，不要求新造六层框架。数据账本、模型注册和实验报告尽量复用。

## 18. 开发任务与完成条件

| 任务 | 交付 | 完成条件 |
| --- | --- | --- |
| D1 数据与协议 | 当前库存、角色、原生分组报告 | 可明确区分Ans/Full、train/tune/fresh、真实反馈与弱标签 |
| D2 基线参照 | REF配置与训练曲线 | 完整训练与检索验证，记录40GB资源调整 |
| D3 环境适配 | Q-RAG-MiLAi、terminal feedback | 同合法菜单，Reader只在约定终止执行，group分正确 |
| D4 预训练控制器 | GTE306M、token collator、共享粒度头 | 骨干真实更新，可保存加载并运行完整episode |
| D5 结果训练 | DQ、PQ-U及完整continuation数据 | 同数据目标对照；未知值mask与成本正确 |
| D6 主动反馈 | PQ-A、固定池/在线两种协议 | 12k/24k等额度学习曲线，不隐藏companion或额外调用 |
| D7 主比较 | RULE/QR/DQ/PQ-U/PQ-A | 固定骨干与跨骨干贡献分开 |
| D8 确认和交付 | 新鲜组结果、成本、失败分析、可复现命令 | 结论与实际证据一致，条件探索有明确取舍 |

建议以约10–15个工作日组织D1–D8：前2日环境与数据，随后2日REF与初始化，中段完成正式反馈训练，后段完成重复与确认。此为工程排程，Reader吞吐和fresh组库存会改变墙钟时间；用第16节实测公式更新，不承诺固定日期必出正结果。

## 19. 建议配置契约

以下YAML用于Codex实现配置解析与实验清单；当前仓库尚未承诺已有这些字段。不得直接宣称下面的新训练入口已能运行。

~~~yaml
experiment:
  family: memory_control_v13_qrag
  method: paired_uniform
  optimization_seed: 11
  acquisition_seed: 11

data:
  dataset_root: /cra/milai-datasets/memory_control_v1
  split_role: train
  group_first: true
  source_weights: {musique: 0.60, qasper: 0.30, personamem: 0.10}
  max_before_per_group: {musique: 4, qasper: 6, personamem: 6}

environment:
  observation: existing_legal_projection
  distinguish_acquired_and_delivered: true
  action_menu: existing_r2_r3_handoff
  memory_budget_tokens: 2048
  max_operations: 6
  retrieval_candidates: 32
  scored_objects: 8
  task_reward_timing: terminal_only
  quality_discount_gamma: 1.0
  native_group_reward: true

model:
  backbone: Alibaba-NLP/gte-multilingual-reranker-base
  train_backbone: true
  dtype: bfloat16
  max_input_tokens: 2048
  encode_once_per_object: true
  bootstrap_heads: 4

training:
  objective: paired_full_continuation
  effective_state_batch: 32
  microbatch_states: 1
  epochs_per_round: 3
  lr: 0.00001
  weight_decay: 0.01
  warmup_ratio: 0.05
  grad_clip: 1.0
  loss_weights: {quality: 1.0, future_cost: 0.1, pair_delta: 0.2}
  old_round_outcomes: do_not_relabel_as_current_q

acquisition:
  continuation_mode: full_episode
  policy_frozen_within_batch: true
  sampler: uniform
  mechanism_stage_fixed_pool_until_calls: 6000
  mechanism_continuation_policy: common_pi_0
  random_fraction_after_warm: 0.25
  uniform_warm_feedback_calls: 2000
  feedback_checkpoints: [6000, 12000, 24000]
  max_feedback_calls: 24000
  include_companion_repeat_paid_failures: true

evaluation:
  reader: existing_frozen_reader_config
  material_budgets: [512, 1024, 2048]
  report_native_groups: true
  include_controller_cost: true
  primary_quality_noninferiority_pp: 1.0
  engineering_cost_reduction_target: 0.15
~~~

配置派生规则：

- DQ：与PQ-U共用结果包，pair_delta=0，其余不变。
- PQ-A：sampler=structured_disagreement，其余与PQ-U相同。
- QR：替换为GTE双塔/PQN，保持环境、回报、预算与反馈上限；双Q估计与质量/成本分量分别实现。
- REF：单独官方配置，不继承Full奖励；不可与项目主表混同。
- fixed-level：仅限制合法粒度，保持HANDOFF权限与其他配置。

source标签、Reader配置路径和实际动作ID以现有数据与运行时为准；示例标签不授权重命名或复制官方数据。

## 20. 必要验证

只新增会影响训练真实性或科学结论的验证：

1. 真批次骨干有梯度并更新，optimizer覆盖预训练参数，Reader保持冻结。
2. 未读正文哨兵不会进入控制输入，已获取/已交付角色正确。
3. HANDOFF/硬终止任务奖励只计一次，终端不bootstrap。
4. 两三条人工可算轨迹验证TD边界与lambda=0/1；不以复制实现的测试当正确性。
5. 完整continuation使用同policy，各分支可响应新观察；旧h2可继续重放。
6. R2/R3实际增量、去重、预算与companion评分正确。
7. microbatch梯度与整state目标权重一致；参数更新后不复用陈旧训练embedding。
8. 保存加载后动作评分一致，正式评估确实包含控制器成本。

不按测试数量验收，不新增内容校验和体系、重复审批或大量包装层。

## 21. 主结果、统计与验收

### 21.1 工程主目标

建议预设：相对DEV冻结的最强实际基线，宏质量退化不超过1个百分点，实际总成本降低目标15%。

15%是工程目标，不是已有数据保证的效果或功效。固定材料预算下质量提高可以作为另一个预先定义的结果，不能在看完测试后任意更换主命题。

总成本先选可解释共同单位：本地GPU-seconds或可靠实际费用；若无法可靠折算，则分别报告Reader费用/输入输出、控制器GPU-ms与实际墙钟，不强行把它们加成虚假的单一指标。

若声明加速，必须有实际端到端时延改善；只节省token时，结论限于token或相应费用。

### 21.2 确认方法

- 原生组为重采样单位，MuSiQue pair、QASPER paper、Persona persona不拆。
- 来源分别配对重采样后再宏平均。
- 两个主比较处理多重选择；其他消融作为解释性结果。
- 拟合seed、采集seed与Reader随机性分别说明。
- 样本规模依据DEV组级方差、最小有意义效应和fresh库存计算，不将任意任务数当充分证明。
- 某来源库存不足时不能靠增加另一来源补足该来源的泛化证据。

### 21.3 机制指标

- 已执行有限动作池上的action regret；该oracle不是全局最优。
- 改变已读证据后的实际增益排序反转。
- 重复读取率、无益升级率、过早停止率、桥接补齐率。
- 不同粒度实际交付差异率。
- 候选支持证据可达性与Reader给定充分证据时的表现。
- 不同预算的质量、动作数量与控制器成本。

机制指标解释主结果，不能代替真实任务表现。

## 22. 算法证明与创新结论的边界

### 22.1 配对目标的统计解释

若Y_a=mu(x)+g(x,a)+epsilon_a，则Y_a-Y_b消除了共同任务难度mu(x)。差值噪声方差为：

\[
\operatorname{Var}(\epsilon_a)+\operatorname{Var}(\epsilon_b)
-2\operatorname{Cov}(\epsilon_a,\epsilon_b).
\]

因此配对可能降低噪声，但取决于相关性；相同随机种子不保证不同prompt的噪声正相关。这是已有统计性质的应用，不是新的理论发现。

### 22.2 值估计的条件性质

在一个给定状态与合法候选集合上，若所有估计Q与同一完整continuation真值的误差均不超过epsilon，按估计Q选最大动作的局部损失不超过2epsilon。

推广到整条新策略需要覆盖它可达的状态和完整后续价值。验证集平均RMSE、bootstrap头分歧和三个训练seed都不能推出统一误差界。

### 22.3 论文贡献成立的证据

| 主张 | 必需结果 |
| --- | --- |
| 小模型训练有效 | 同骨干训练后优于未训练/相关性策略 |
| 配对粒度学习有效 | 同结果包优于Direct-Q |
| 反馈更高效 | 等真实反馈成本学习曲线优于Uniform |
| 结构化采样有独立贡献 | 超过High-uncertainty和必要Generic EVSI-style |
| 集合条件机制成立 | 真实分支支持的条件反转，且破坏证据语义会损害该能力 |
| 工程优化成立 | 控制器成本计入后，预设质量—成本目标通过 |
| 完整记忆能力 | 另有写入、更新、跨轮使用的交互验证 |

不能声称首次使用attention、主动探测、多粒度或反事实。不能假设更高粒度必然改善质量，也不能对互补多跳不加条件地套次模保证。

## 23. 失败后的确定处理

| 现象 | 下一步 |
| --- | --- |
| REF无法学习 | 检查数据、真实encoder更新、PQN与终止；不继续叠加新方法 |
| 原生GTE很强，控制训练无增益 | 保留强语义基线，检查结果标签与有效优势覆盖 |
| 分支oracle也无空间 | 调整候选/动作/任务，停止延长同一目标 |
| oracle强，合法输入模型弱 | 区分预览瓶颈、噪声与容量；用Qwen0.6B复核 |
| 离线拟合好，运行差 | 检查状态分布、continuation与停止，补采真实访问状态 |
| Paired-Q不优于Direct-Q | 采用Direct-Q，删除配对贡献 |
| 主动不优于Uniform | 保留均匀采样，删除反馈效率贡献 |
| Structured不优于Generic EVSI | 定位为已有主动方法迁移 |
| 质量改善，实际成本恶化 | 减K/输入长度、蒸馏或选择性调用，分别报告质量与效率 |
| 固定粒度同样好 | 收缩粒度控制主张 |
| 仅某来源有效 | 报告该领域有效，不用宏平均掩盖其他来源退化 |

这些转向不是停止研究的审批门，而是下一步研发决策。失败模块可以删除，已有效模块继续推进。

## 24. 第二阶段探索

只有第一阶段训练与控制证据成立后开展：

1. ModernBERT149M蒸馏，验证收益保留和真实控制成本。
2. 更大候选库下的粗筛/精排分级；相同候选可达性条件下测损失。
3. 缓存稳定的记忆视图：稳定前缀、增量追加、阶段边界重整。
4. AMemGym等交互环境中的跨轮事实更新、冲突与记忆维护。[S15]
5. 合法短计划或PPO/GRPO，仅在多步信用或探索缺口有实际证据时加入。

当前单题末尾一次Reader调用的设置，不足以证明跨轮缓存优化。静态QA读侧结果也不足以证明完整写入/遗忘算法。

## 25. Codex执行指令

> 从MiLAi已核实review版本建立独立开发工作区，保留现有数据、运行器、Reader、原生评分器和ledger。固定Q-RAG参照提交，先完成一个Ans/GT官方配置的真实训练曲线。建立明确命名的Q-RAG-MiLAi适配：同合法预览、R2/R3/HANDOFF与预算，终端一次Reader，Full原生组回报。原版每步Reader反馈不得直接作为本项目终局目标。
>
> 接入GTE-reranker306M全参控制器，保留已获取/已交付角色；每对象一次交互编码，输出合法粒度的质量和未来成本，所有同骨干对照共用该工程实现。使用已知证据与合法成功轨迹初始化，然后按完整冻结continuation采集真实结果。建立DQ/PQ-U同数据对照，再做PQ-A等反馈预算比较。
>
> QR、PQ-U、PQ-A各在12k和24k累计反馈额度检查点评估，companion、重复及付费失败均扣账。DQ复用PQ-U包，不另造标签。先1 seed确定配方，再做冻结数据拟合种子；采集效率另做独立采集复核。用真实未暴露组确认，不复用旧CONFIRM作为盲测。
>
> 训练目标和数据不足的诊断要指向下一项实质实验；不要用测试数量、训练时间或更多开关替代任务收益。报告同骨干学习增益、强基线比较、反馈学习曲线、总成本、分来源结果和失败案例。若某创新模块无增益，删除其贡献，保留有效工程实现。

### 必交付文件

- 当前数据角色、原生组库存和暴露统计；
- 原版参照与MiLAi适配差异说明；
- 少量可运行训练/采集/评估配置及完整重建命令；
- 已实现代码与必要测试结果；
- 12k/24k反馈学习曲线和真实成本表；
- 同骨干目标消融、强基线比较与独立确认结果；
- 最终模型选择理由、未成立主张及后续决定。

报告必须区分已执行、建议、失败和未知。不提供并不存在的zip、checkpoint或“已可运行”命令。

## 26. 一手来源与项目依据

### 项目与源码

- [S1] MiLAi review源码：<https://github.com/minguselandy/MiLAi/tree/7bb27c1254e0ebd49acdbdbc4b09722f93ccecb3>
- [S2] MiLAi V12最终结果：<https://github.com/minguselandy/MiLAi/blob/35e1803ed413fd17fb587ff1c9db32f92acd7815/MiLAi-Lab/docs/MILAI_MEMORY_CONTROL_V12_PLAN2_FINAL_RESULTS.md>
- [S3] Q-RAG官方仓库：<https://github.com/griver/Q-RAG>；固定实现：<https://github.com/griver/Q-RAG/tree/42358d78ac491843763b90677f07237471c97086>
- [S4] Q-RAG反馈代码：<https://github.com/griver/Q-RAG/blob/42358d78ac491843763b90677f07237471c97086/rl/feedback/feedback.py>；<https://github.com/griver/Q-RAG/blob/42358d78ac491843763b90677f07237471c97086/rl/feedback/llm_feedback.py>
- [S5] Q-RAG MuSiQue loader：<https://github.com/griver/Q-RAG/blob/42358d78ac491843763b90677f07237471c97086/envs/dataloaders/musique.py>；联合配置：<https://github.com/griver/Q-RAG/blob/42358d78ac491843763b90677f07237471c97086/configs/envs/hotpotqa+musique.yaml>

### 模型

- [S6] GTE embedding：<https://huggingface.co/Alibaba-NLP/gte-multilingual-base>
- [S7] GTE reranker：<https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base>
- Qwen0.6B重排器：<https://huggingface.co/Qwen/Qwen3-Reranker-0.6B>
- ModernBERT149M：<https://huggingface.co/answerdotai/ModernBERT-base>
- Mem-T公开权重：<https://huggingface.co/EdwinYue/Mem-T-4B>

### 方法

- Q-RAG，ICLR2026：<https://proceedings.iclr.cc/paper_files/paper/2026/hash/372dee09e0c3c17df69d990b4735adac-Abstract-Conference.html>
- [S8] RAA，预印本：<https://arxiv.org/abs/2611.24422>；全文<https://arxiv.org/pdf/2611.24422>
- [S9] FlexA-Mem，预印本：<https://arxiv.org/abs/2610.33274>
- [S10] Mem-T，ICML2026：<https://proceedings.mlr.press/v306/yue26b.html>
- [S11] SCCG，出版社页面：<https://www.sciencedirect.com/science/article/pii/S0031320326022120>
- [S12] U-RAG，作者机构保存的正式论文：<https://oro.open.ac.uk/112304/1/1-s2.0-S0306457326005765-main.pdf>。2026年在线、2027卷期，非顶会论文。
- [S13] UpliftMem，预印本：<https://arxiv.org/abs/2609.36805>。本次核验了其集合收益与决策价值采样机制；不将其公开摘要/结果直接当MiLAi效果。
- [S14] Hugging Face训练内存说明：<https://huggingface.co/docs/transformers/en/model_memory_anatomy>
- [S15] AMemGym，ICLR2026：<https://proceedings.iclr.cc/paper_files/paper/2026/hash/0856bc553d3e3b9827e5140d0ad3bf8d-Abstract-Conference.html>

V1数据历史数字来自本项目已验收构建信息及本会话已有2026-11-18数据规划；服务器当前库存以执行时导出的原生组统计为准。

