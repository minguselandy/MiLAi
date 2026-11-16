# MiLAi 训练数据、泛化诊断与开发实验规划

日期：2026-10-21。状态：**本地功能修复与公开数据准备已完成；新训练和模型效果验证未运行。**

本次重新读取的研究分支为 feat/host-intent-retrieval-20261019，远端提交为
[248aa05dc1aa0f6438dfd3d95425cb5a80d51270](https://github.com/minguselandy/MiLAi/commit/248aa05dc1aa0f6438dfd3d95425cb5a80d51270)，
提交时间为 2026-10-21 14:17:40 UTC+8。本地修复位于 fix/host-intent-evidence-continuity-20261021。
提交号只用于注明来源版本；本次没有推送、合并、访问开发机、启动训练或操作共享服务。

本规划接续 [当前研究状态](HOST_INTENT_RETRIEVAL_STATUS_20261021.md)、
[执行记录](HOST_INTENT_RETRIEVAL_EXECUTION.md)和
[View v4 计划](MILAI_HOST_INTENT_VIEW_DEVELOPMENT_EXPERIMENT_PLAN_20261020_v4.md)。
上一轮证据连续性修复见 [代码审查记录](MILAI_GITHUB_REVIEW_AND_FIXES_20261021.md)，旧分数保持原样。

## 1. 结论与本轮决策

用户关于数据少和泛化差的担忧有实测支持。当前问题包括：**独立操作来源少、真实中间状态覆盖窄、反馈有效监督少、训练与新目标开发评估脱节**。扩大数据应优先增加能够改变下一步取证决策的经验，同时用学习曲线确定优化强度。

目前不能直接宣称“训练轮次太多已经造成主任务开发集持续退化”。T1 主操作 dev 在后半段仍上升；明显的 train/dev gap 也可能包含来源分布差异、标签目标与真实任务不一致。更不能把 W5 的 37 条反馈状态误写成整个 T1 只有 37 个样本。

本轮落实四类功能：

1. 新增独立反馈 dev 的准备、保存和训练期评价入口，使 answer/delivery 目标有自己的开发集分母。
2. 增加中间评估计划、检查点留存、encoder/head 学习率和冻结 encoder 控制，支持真正的学习曲线与小数据对照。
3. 接入公开 Promptriever train 数据，并实际下载前 2,000 行，生成 3,979 条 train / 961 条内部 dev 辅助候选，再接入既有 mixture 准备工具。
4. 用这批真实数据复现并修复 JSONL 的 Unicode 分隔符读取故障，保证合法文档能进入准备、训练和评估路径。

这些改变解决了数据接入和诊断能力的缺口。**尚未证明模型的泛化或 Host 成功率已提升。**

## 2. 当前训练究竟有多少有效信息

### 2.1 T1：行数、来源组与抽样次数分别计算

来源：[T1 fitting plan](../data/manifests/host-intent-retrieval-v3-t1-fitting-plan-v1.json)、
[主配方完成记录](../data/manifests/host-intent-retrieval-v3-t1-seed0-fitting-complete.json)、
[操作对照完成记录](../data/manifests/host-intent-retrieval-v3-t1-control-seed0-fitting-complete.json)。

| 训练组成 | 原始 train 行 | 有监督 train 行 |
|---|---:|---:|
| 历史操作 | 1,955 | 1,499 |
| 互补证据操作 | 2,137 | 1,263 |
| 操作合计 | 4,092 | **2,762** |
| FollowIR 适用性辅助 | 1,427 | 1,427 |
| 主配方合计 | **5,519** | **4,189** |

操作来源分配为 128 train / 32 dev，有操作标签的 train 来源组实际为 **126**。FollowIR 为 965 train / 241 dev 连通组，不能把它们加成 965 个操作记忆场景。

| 实际优化暴露 | 主配方 | 操作对照 |
|---|---:|---:|
| 更新次数 | 524 | 524 |
| 总 row draws | 8,384 | 8,384 |
| 操作 draws | **5,527** | **8,384** |
| 输入训练 tokens | **28,392,562** | **41,804,889** |

当前是等更新、等总抽样次数，不是等操作暴露、等 tokens 或等 FLOPs。主配方约两遍完整混合池，操作对照约三遍操作池。辅助损失权重不等于抽样配额：现有工具按行均匀打乱，再按 component/family/event 归一化损失。

### 2.2 泛化差距真实存在，过拟合原因尚需分辨

| T1 seed0 指标 | Train | Dev | 差距 |
|---|---:|---:|---:|
| 主配方全部操作 | 2505/2762 = 90.70% | 446/616 = 72.40% | 18.29 个百分点 |
| 主配方互补证据 | 1247/1263 = 98.73% | 219/307 = 71.34% | **27.40 个百分点** |
| 操作对照全部操作 | 2676/2762 = 96.89% | 472/616 = 76.62% | 20.26 个百分点 |
| 操作对照互补证据 | 1257/1263 = 99.52% | 232/307 = 75.57% | 23.95 个百分点 |
| 主配方 FollowIR | 1426/1427 = 99.93% | 316/349 = 90.54% | 9.39 个百分点 |

主配方操作 dev 在 0、262、524 更新分别为 206、436、446 / 616；FollowIR 为 204、319、316 / 349。最终训练集近饱和与开发集差距较大，但现有检查点不足以推断最佳训练长度，更不支持一律减少 epoch 的结论。

操作来源组宏平均也应保留：主配方 train/dev 为 92.73% / 75.39%，操作对照为 98.11% / 78.77%。上表是有标签状态准确率，不是 Host 成功率。

### 2.3 W5 的问题更接近“小状态池、少方向监督”

来源：[反馈结果](../data/manifests/host-intent-view-v4-c-feedback-results-v1.json)、
[三臂训练结果](../data/manifests/host-intent-view-v4-three-fits-results-v1.json)、
[最终保存重载结果](../data/manifests/host-intent-view-v4-persisted-final-results-v1.json)。

- 8 个训练来源组、37 个真实初始状态、112 个执行分支、114 个比较 pair。
- Host readout 为 89 completed / 23 failed；失败或不完整 readout 不是负标签。
- answer：15/37 状态有方向，27 directional / 27 tie / 60 unknown pairs。
- delivery：26/37 状态有方向，56 directional / 36 tie / 22 unknown pairs。
- 每臂 37 feedback + 37 replay，10 更新、160 draws。
- 旧操作 dev 是 860 输入、616 有标签；历史新 feedback dev 的 pair counts 为空。

最终保存重载的旧操作 dev：continued CE 450/616，answer 447/616，delivery **439/616**。
三臂训练结果中的 delivery 440/616 是进程内历史值，不回填覆盖。

answer/delivery 的 sampled directional pairs 为 59 / 121，但现有 pair loss 对每个状态内部的方向 pair 取均值。不能把这个数量比解释成梯度简单翻倍；需要同时看有方向状态、每态监督和目标方向。

### 2.4 原料储备与操作经验是两个瓶颈

现有 MuSiQue 原料并非只收集了很少问题：

- [reader preparation](../data/manifests/jev-bounded-reader-preparation-v1.json) 记录 MuSiQue-Full train 镜像 39,876 行、896 个连通 family。
- [全局来源总体](../data/manifests/milai-global-training-population-v1.json) 记录两套既有划分都保留为 train 的 444 族、17,975 行。这是当时的候选总体，不是当前已审核可直接全部训练的许可清单。
- T1 最终继承的是 64 个 MuSiQue train 族、13 个 dev 族；其他操作来源另计。
- 原料来自 train 镜像，作者原归档全文等价当时未证实。另一路 public DEV mirror 是评估候选，不可混进梯度训练。

因此第一优先级是把已有可用训练来源转成更丰富的实际决策状态，再引入新的领域。简单重下载同一数据集或多造前缀，并没有按比例增加独立信息。

本轮从作者 raw train 取得 32 条记录，复用了现有 public-source adapter，生成 32 个请求和 640 个段落出现。按原生单跳 IDs 已发现至少一条连接到既有 T1 train；raw 的 double__ 与处理版 2hop__ 名称不同，不能凭完整字符串不同宣称未见。完整历史 family metadata 不在本地 clone，所以其余记录也不宣称未见。此次是导入验收，新增操作标签数为 0。

## 3. 研究架构与当前能力缺口

Host 继续表达 query、用途、证据要求、对象/时间、已知证据和预算。Jev/Laya 在工具内部给实际动作和绑定参数排序；工具返回证据，Host 完成任务。

当前训练对象是编码器加有限选择决策头。开放 Laya multilingual 模型卡给出的底座约 322M 参数；不是生成式 Agent，softmax 也不是自动校准后的成功概率。参见 [官方模型卡](https://huggingface.co/convaiinnovations/laya-multilingual) 和 [SDK](https://github.com/NandhaKishorM/laya)。

新数据需要覆盖以下变化，而且必须保留实际 offered actions 和参数：

| 决策条件 | 应观察的行为 | 所需数据 |
|---|---|---|
| 只拿到部分互补证据 | 继续 SEARCH/READ 获得缺失支持 | 多跳材料与真实执行后状态 |
| 证据已经充分 | 及时交接，避免无收益调用 | 完整证据状态及真实交付反馈 |
| query 相同、用途不同 | 选择适用材料和读取范围 | 意图对照与条件相关负例 |
| Host 已知不同证据 | 下一步选择改变，少重复交付 | 相同任务、不同 known evidence |
| View 可用但适用性不同 | 复用、读原文或刷新随条件改变 | 实际 View 与来源版本 |
| 源更新或历史时间请求 | 返回正确版本及可追溯材料 | 同对象跨版本真实记录 |
| 搜索空、预算不足或调用失败 | 保留证据不足与未完成状态 | 真实失败回执；unknown 不改成负例 |

公开 QA 的答案和 supporting facts 只能用于离线构造与评分。特别是 MuSiQue 的 answerable=false 只限定给定上下文；真实 SEARCH 若可补齐支持，就不应直接标 HANDOFF。

T1 新增收集中的 View 操作覆盖不足，W5 又集中在少量初始状态。后续采集应优先覆盖执行后的状态和参数选择，不只重复初始“查不查”。

还要保持全局视角：最新 D 中固定上下文与 delivery 均为 21/64 完整正确，没有学得控制器胜出。若 Host 没调用记忆工具，Jev 根本没有决策机会；该类问题应在 Host 接口实验中单列，不能靠更多 READ 标签解释或修复。参见 [当前状态与分层结果](HOST_INTENT_RETRIEVAL_STATUS_20261021.md)。

## 4. 已公开训练数据的选择

只列已能取得代码或数据的来源；不同许可证分别记录。

| 来源 | 已发布规模与许可 | MiLAi 中的用途 | 关键限制 |
|---|---|---|---|
| [MuSiQue](https://github.com/StonyBrookNLP/musique) | Ans train 19,938；Full train 39,876；CC BY 4.0 | 多跳互补、缺失支持、READ 与继续取证 | Full 是同题配对，不是近 4 万独立题；已存在项目暴露 |
| [Promptriever train](https://huggingface.co/datasets/samaya-ai/msmarco-w-instructions) | 980,250 行，约 490,125 base-query 配对；非商业研究用途 | 意图适用性辅助、条件相关干扰 | 不提供记忆操作标签；生成材料和继承相关性标签未独立复审 |
| [STATE train trajectories](https://github.com/microsoft/STATE-Bench/tree/main/datasets/train_task_trajectories) | 3 域各 100，共 300 轨迹；仓库 MIT | 工具反馈、对象状态变化、可用/失效 View 的环境材料 | 合成环境轨迹；原任务工具属于 Host，不能改名为 Jev 动作 |
| [HotpotQA](https://hotpotqa.github.io/) | train 90,447；CC BY-SA 4.0 | MuSiQue 之外的数量与多跳形式后备 | 仍偏 Wiki；不补来源版本分布，distractor/fullwiki 不是独立双份数据 |

MuSiQue 统计依据 [原始论文 Table 2](https://aclanthology.org/2022.tacl-1.31.pdf)。官方也提供 dev/test 单跳题 ID 排除信息；加入 SQuAD、NQ、T-REx 等种子语料时沿用这份原生 ID 信息和现有 exposure 记录。

Promptriever 的 [官方代码](https://github.com/orionw/promptriever)、模型和训练数据均已公开，但其数据卡明确限制为非商业研究用途，并沿用 MS MARCO 与生成模型条款。研究配方可单列使用，实际产品配方应保留不用该数据的对照。

FollowIR 已是现有辅助源；扩大重复抽样不是新来源。InstructIR 继续作为已有暴露的意图鲁棒性诊断；不能将 corpus 文档数当作独立训练题数。Mem-α 的公开 train 只有 567 行且混合已有来源，本阶段不将它作为主要增量。

### 4.1 本轮实际准备的数据

Promptriever 固定取官方 train 的前 2,000 行，无内容挑选、无重试。20 个成功请求，响应体合计 28,930,519 字节，合并 raw JSONL 29,251,421 字节。

| 口径 | 全部 | Train | 内部 dev |
|---|---:|---:|---:|
| 原始行 | 2,000 | 1,612 | 388 |
| Base queries | 1,002 | 807 | 195 |
| 完整 query-only / instruction 配对 | 998 | 805 | 193 |
| 连通来源组 | 912 | 730 | 182 |
| 导出的适用性候选 | **4,940** | **3,979** | **961** |

原始候选出现 64,241 次，literal 文档 34,102 个，native docids 34,103 个。默认每 raw row 保留全部 positive、最多 1 个普通负例和 1 个 instruction negative；没有将全部 30 个普通负例灌入训练。

分组先使用所有原始候选，再应用负例上限。原生 base query、重复 query、共享 docid 或 literal 文档连接同一 family。最大 component 为 25 raw rows / 13 base queries，没有拆 component 凑 dev。在本次前 2,000 行范围内，跨分区上述四类身份交集均为 0；不等于全量语料或预训练隔离。4 个只有 query-only 的题保留原状，没有越过预声明前缀补抓。

已经用既有 prepare_retrieval_mixture 工具生成 state IDs、component 和 mixture，逐条确认 state/questions/gold 不变。内部 dev 是公开 train 的离线开发分区，不能称未暴露外部测试。当前原始前缀也不代表全量分布。

产物目录：**artifacts/promptriever-intake-20261021/first2000/**。
可训练输入在 **trainable-applicability/**；原始、分组和下载记录保留在同目录。
这些是辅助任务数据，**新增真实操作轨迹仍为 0**。

### 4.2 数据引入顺序

1. 先从现有允许训练的 MuSiQue/2Wiki 来源扩大实际操作覆盖，继承原 family 和 split。
2. 用新的 Promptriever 辅助入口测试表示是否改善 Host 意图条件下的取证；它不自动进入主配方，也不以辅助分数替代操作效果。
3. 将 STATE train 的实际对象变更装入现有记忆环境，由真实 View 构建和刷新生成状态。
4. 用较大训练源形成候选池后，沿用自身轨迹入口收集模型实际到达的错误与成功状态。

避免同时加入多套高度相似 Wiki QA，却继续缺少版本变化、已知证据和停止条件。

## 5. 已实现的功能与实际行为

### 5.1 独立反馈开发集

修改：

- **tools/prepare_view_feedback_branches.py**：增加 --split train/dev，默认 train。
- **tools/prepare_retrieval_feedback.py**：编译时显式指定 split；原 metadata 不符时不重标。
- **tools/prepare_feedback_training.py**：增加 --feedback-dev，向 feedback 与 continued-ce 两臂分别写 feedback-dev.jsonl。
- **tools/train_bounded_laya.py**：增加 --feedback-dev-data，用同一批预测分别报告 answer/delivery。

训练 rows、抽样、旧 dev 分母和 replay 不受新增 dev 影响。新 feedback dev 与全部传入 old_train（包括无 gold 行）及反馈 train 的 family 分离；与旧 dev 的重合会单列，原 exposure metadata 保留。unknown/tie、真实 before、实际动作及绑定继续沿用原语义。

本轮没有真实采集新的反馈 dev；历史 W5 的新目标 dev 覆盖仍是零。现在是入口可用，后续要用真实开发来源填充它。

### 5.2 学习曲线与参数更新范围

新增 --eval-every-updates 或 --eval-at-updates。要求显式 optimizer update budget，自动包含终点；不传则仍 half/final。

评估点只切分同一条已生成的优化窗口序列，不改变 row draws、data pass 或选项排列种子。自定义计划的中间权重保存在 checkpoints/update-N；最终权重仍在 checkpoint。

新增 --encoder-lr、--head-lr、--freeze-encoder。默认沿用 2.5e-5 / 1e-4、全参数更新。冻结时 encoder 不参与优化且保持 eval 模式。没有新增 LoRA 或自动早停系统。

做曲线时启用现有 --evaluate-train，并不使用 --train-eval-final-only。区间 weighted_loss_mean 不等于固定训练集 loss；固定 train/dev 诊断应同步记录。

### 5.3 大训练源辅助适配

新增 **src/milai_lab/datasets/promptriever.py** 和 **tools/prepare_promptriever_applicability.py**，复用 FollowIR 的既有 schema。

模型输入只有 only_query、only_instruction 和 passage.text。原解释、教师分数、joint_id 和离线标签不进入 state。正负标签来自公开 passage membership，保留其“未独立复审”的性质；不生成 SEARCH/READ/HANDOFF 标签。

这是本地 JSONL 转换器，不是全量 4.85 GB parquet 的流式连通图平台。后续扩大前缀或分片必须在完整拟采用范围内统一分组；不能分片独立编号再宣称全局隔离。

### 5.4 用真实数据修复 JSONL 读取

实际新 train 有 3,979 个物理 JSONL 记录，但旧 str.splitlines 会得到 3,980 个片段，因为一个文档包含 Unicode 行分隔符。后续 json.loads 因字符串被截断而失败。

在现有 **harness/artifact_io.py** 增加按物理行读取的 read_jsonl，接入 mixture 准备、bounded trainer、bounded evaluator 与反馈数据准备。文档原文保持不变，没有删除或转义掉其语义内容。新增 CLI 回归覆盖 U+0085、U+2028、U+2029；真实 4,940 条候选已完整通过 mixture 准备。

## 6. 下一轮严谨训练设计

以下是待执行实验方案；数据量和更新点是预先声明的设计选择，不是已证明最佳配方。

### 6.1 先把“多来源”和“多重复”拆开

建立同一固定来源池上的嵌套子集，以完成实际轨迹的来源组数为横轴。首轮建议 64、128、256 组；不足的档位明确报告不足，不靠同一来源造更多状态凑数。现有 444 个历史候选族只是可核对的上限线索，须继承现有角色和后续暴露，不能直接全部纳入。

同一来源组保留多种真实已知证据和执行后状态，用于提高状态覆盖；统计时另列，不算新独立来源。保持固定开发来源和评估输入，不能每个数据档位重新抽 dev。

更新预算采用同一 524-update 计划，记录例如 32、64、128、262、393、524 的同步 train/dev 检查点。作为诊断，先用 seed0 确定可行区间，再对决定性比较确认 seed0/1/2。总预算可根据真实吞吐调整一次并提前记录。

不要把独立 64-update cosine 运行与 524-update 运行的第 64 步当作相同优化轨迹；学习率的总周期不同。

### 6.2 最小对照矩阵

| 比较 | 保持一致 | 改变因素 | 回答的问题 |
|---|---|---|---|
| 来源规模曲线 | 任务接口、dev、初始化、更新预算 | 独立来源组数 | 增加经验是否降低泛化差距 |
| 训练强度曲线 | 同一长计划及抽样序列 | 检查点位置 | 欠拟合、平台或后段过拟合 |
| 参数更新范围 | 数据、seed、操作 draws | 当前全参 / 冻结 encoder / 较低 encoder LR | 小数据是否需要减小表示漂移 |
| 辅助预训练后同操作训练 | 最终操作数据、draw 顺序、预算和 dev | 有无辅助阶段 | 意图表示的增量是否迁移到操作 |
| 自身轨迹 + replay | 数据格式、来源分层、训练强度 | 旧规则状态 / 新实际到达状态 | 状态分布覆盖能否改善继续取证 |
| 反馈目标 | 相同真实 before、分支和 continuation | answer / delivery / continued CE | 哪个目标提供可泛化信号 |

辅助阶段建议先作为独立短阶段，再让两臂使用完全相同的操作训练文件和抽样种子。这样能明确控制最终操作暴露；额外辅助计算单列。此设计回答辅助初始化的价值，不等同证明当前联合训练存在负迁移。

原有联合配方可以保留为复现臂，但不要因新增几千条辅助候选而让操作抽样进一步被稀释。若继续研究 joint mixing，必须另外报告固定操作暴露和固定总资源两种比较；损失质量与抽样质量分别解释。

冻结 encoder 是诊断选项，不是预设赢家；不同时铺开几十个学习率与 dropout 组合。首轮保留当前值、一个较低 encoder LR（例如 5e-6）及 head-only，依据固定 dev 再收敛。

### 6.3 反馈数据扩充与选择

将 W5 的 8 个来源组扩展到拟定的 32、64、128 组，实际组数以可执行环境为准。每组包含初始和执行后状态；不只采错误例，也保留“已经足够”和“继续行动无收益”的状态。

从训练来源运行固定规则、当前策略和简单基线，收集实际 reached states。状态采集策略、随机种子、回放比例和每组最大采集量预先固定，避免只收某个模型特有错误。

在可重建的同 before 上执行少量真实 offered actions/参数分支，保留共同 continuation 和结果。第一版沿用现有初始状态可重建入口；执行后分支重建若尚未支持，应作为一个明确开发项实现和验收，不能声称当前已经任意状态可回放。

未知、并列和未执行动作保留原状态。不能把 114 个 pair 算成 114 个独立任务，也不能把 readout 失败算成动作差。

主反馈实验保留全池现实监督差异；另做 common-support 诊断，只比较两目标都有方向的同一 pair、相同抽样与权重。若交集 pair 的方向全相同，就说明当前池没有足够目标分歧信号，不应据此强讲信用分配优越性。

### 6.4 长上下文与语义迁移

当前 T1 上限为 12,288、W5 为 16,384，而公开 multilingual 模型卡给出的常规支持范围是 8,192。没有截断不意味着长输入语义可靠；也不能仅由长度超出就断言所有失败来自编码器。

第一轮按实际长度、支持证据位置、候选数分桶。分别报告 8K 内与更长完整输入的结果。若为资源原因压缩，应使用已有 shared_request_text 或其他已定义投影并明确为新的输入条件，保持各臂相同；不静默截断关键证据。

E3 等信息文本对照已有入口，应继续完成，用来分辨收益来自更多信息、不同表示，还是更好的策略。

### 6.5 检查点、统计与成本

操作阶段以固定来源组宏平均为主要 dev 选择指标，READ/互补/过早交接分项同时报告。反馈阶段使用独立 feedback dev 排序与覆盖，旧操作 dev 是保留能力指标。选择规则在训练前写清，不从最终 Host 测试反向挑 checkpoint。

确认阶段以来源组为统计单元做配对比较，报告组级 bootstrap 区间及跨 seed 变化。同一题的多个请求、多个状态或多个种子不能当成相互独立样本增加显著性。小集合上的差一两题保持不确定，不以 p 值包装方向。

主要终点为固定 Host、固定任务材料、固定预算下的来源忠实完整成功率；并列报告：

1. 工具调用覆盖：Host 是否实际调用。
2. 操作合法性和静态偏好。
3. 实际材料交付与互补支持是否完整。
4. Host 最终成功。
5. 编码训练与评估 tokens、GPU 时间、真实调用与失败成本、离线建 View、在线检索和维护成本。

相同更新数不是等 FLOPs；相同 tokens 也不足以等同注意力计算量。先给实际测量的多轴成本，再谈效率。

### 6.6 实验结果怎样改变后续方向

| 观察 | 下一步决策 |
|---|---|
| 来源增加后 train/dev 差距缩小，Host 也改善 | 优先扩展有效来源和状态覆盖，再验证成本拐点 |
| Train 继续上升而固定 dev 持续下降 | 在已保存检查点中按预声明规则选择；比较较低 encoder LR 或冻结，减少重复暴露 |
| Train 和 dev 都低 | 先检查输入是否提供可判定信息、标签是否与实际动作相符，再判断优化不足 |
| 静态偏好提高，实际交付没有提高 | 检查动作参数、补搜、版本和完整返回路径，不能继续把静态准确率当主终点 |
| 交付提高，Host 最终任务没改善 | 单列 Host 未调用、未使用证据和任务推理问题，保留无条件总成功率 |
| 强固定上下文或简单规则更好 | 保留简单方案为默认候选，研究复杂方法的适用范围，不追加题目专用规则保住排名 |

当前模型是预训练编码器，不能仅按“参数量除以样本量”判定必然过拟合。数据规模、有效独立性、任务覆盖和参数更新范围应由这些对照共同判断。

## 7. 基于 MiLAi 架构的创新主线

建议将主线收敛为：**给定 Host 目的、已有证据和预算，学习下一步取证能补上什么，以及何时值得继续。**

### 7.1 证据的增量价值，而非动作名称拟合

用同一 query 的 known-evidence 条件变化构造真正的取证对照：

- 还缺关键支持时，READ/SEARCH 是否补上它。
- 同一材料已经交付时，重复读取是否仍有任务价值。
- 支持齐全时，HANDOFF 是否减少成本且保持任务成功。

收益要来自执行后的证据变化和 Host 结果。若用即时交付目标，第一步 READ 的价值可能因为后续还需另一跳而被低估；因此同时记录局部证据增量和共同 continuation 后的最终结果。第一步无最终答案不自动是负例。

这是可检验假设，不能先命名为已经实现的强化学习算法。当前有限选择头和 pair/replay 机制足以开始，不必先建设通用 RL 平台。

### 7.2 意图、证据和来源版本的组合泛化

同一个 View 在摘要概览、逐字核验、历史版本或当前事实请求下，最优取证方式可能不同。训练只见部分组合，确认时保留新的组合，并将来源迁移与组合迁移分开报告。

用至少一组完整组合因子实验验证：Host 意图、known evidence、View 新鲜度、资源预算。每次只改变实验声明的条件；动作次数由实际需要决定，不规定每题必须多调用。

新颖性要由相对现有方法的效果和机制证据支持。已有 E2 同请求同 before、E3 等信息文本、T2 自身轨迹入口应作为实验基础，不重新造另一套控制框架。

### 7.3 View 的价值必须包含维护成本

对比强固定上下文、简单规则、Jev、Jev 去 View，以及现有等信息文本条件。多次请求下计算创建、刷新、复用、原文读取的总成本，观察何时得到稳定收益。

如果原文固定检索在某类任务更好，就把该类任务作为简单方案适用范围。即使 Jev 不胜出，界定“何时意图条件和持久视图有增益”仍是可解释的研究结论。

开放 [laya-browser](https://huggingface.co/cklxx/laya-browser) 的作者报告中，多步真实任务仍大量过早 DONE，增加终止数据等尝试未明显超出噪声。这是对“只补终止标签即可解决问题”的外部反例，不是 MiLAi 的效果证据，也不据此照搬其浏览器专用运行时规则。

## 8. 外部评测的保留方式

| 已开放 benchmark | 用来判断 | 使用边界 |
|---|---|---|
| [LongMemEval-V2](https://github.com/xiaowu0162/LongMemEval-V2) | 长历史状态、流程、历史陷阱和前提错误下的证据交付 | 451 问题、1,870 轨迹；已暴露子集只作诊断，原任务不变 |
| [Mem2ActBench](https://github.com/Cantaloupe-M/Mem2ActBench) | 记忆能否支持正确工具和参数 | 2,029 是 session 数，不是题数；QA 与 grounding 不用于生成训练目标 |
| [STATE Learning Track](https://github.com/microsoft/STATE-Bench/blob/main/docs/AGENT_LEARNING_TRACK.md) | 从 train 轨迹提取的记忆能否改善新任务 | 300 train 与 150 test 分开；test oracle 不用于学习 |

LongMemEval-V2 数据卡为 Apache 2.0。Mem2Act 仓库 README 声明 MIT，但未见独立数据许可文件；准确记录，不把上游混合数据自动重新许可。

STATE 的官方计分协议锁定 simulator/judge 与多次运行；若改用全开源模型，命名为 MiLAi 的修改协议实验，不冒充官方可比成绩。用户要求忽略未开源工作，本规划仅采用其已发布的代码、训练轨迹和任务资产，不依赖未发布方法。

## 9. 执行顺序与交付物

| 优先级 | 工作 | 本轮状态 | 下一个可验收结果 |
|---|---|---|---|
| P0 | 真实数据接入、Unicode JSONL 修复 | 已完成 | 新 raw 到 mixture 输入可完整读取，内容不变 |
| P0 | 独立反馈 dev 与学习曲线接口 | 已完成 | 新来源实际反馈填入独立 dev，不混旧分母 |
| P1 | MuSiQue/2Wiki 合法 train 来源扩容 | 方案已给，未新采集 | 嵌套来源集、实际状态覆盖、现有 exposure 接线 |
| P1 | STATE train 转记忆来源与 View 状态 | 已选来源，未新采集 | 对象变化的真实工具执行及证据交付 |
| P2 | 规模 × 更新曲线，辅助与冻结对照 | 未训练 | 可复核学习曲线和完整训练成本 |
| P2 | 自身轨迹与执行后分支 | 现有入口接续，覆盖待扩 | 独立反馈 dev 与同 before 分支结果 |
| P3 | 固定 Host 下与简单基线确认 | 未运行 | 来源忠实成功、成本及失败分层 |
| P3 | 外部分布与多 seed 确认 | 未运行 | 保护集合上的最终结果，不反向调参 |

当前最先要完成的模型实验是：在继承边界的新操作来源上，确认扩来源与改善状态覆盖是否减少互补证据的过早交接。单独把适用性 train/dev 做高，不足以完成目标。

## 10. 复用命令与验证边界

以下离线命令已在本地执行。输出目录存在时应指定新的目录：

~~~bash
PYTHONPATH=src .venv/bin/python tools/prepare_promptriever_applicability.py +  artifacts/promptriever-intake-20261021/first2000/train-first2000-obtained.raw.jsonl +  artifacts/promptriever-intake-20261021/first2000/prepared +  --ordinary-negatives 1 --instruction-negatives 1 --seed 0 --dev-fraction 0.2

PYTHONPATH=src .venv/bin/python tools/prepare_retrieval_mixture.py +  artifacts/promptriever-intake-20261021/first2000/trainable-recipe.json +  artifacts/promptriever-intake-20261021/first2000/trainable-applicability
~~~

下面只展示下一轮训练如何使用新接口，本轮未执行：

~~~bash
PYTHONPATH=src .venv/bin/python tools/train_bounded_laya.py +  path/to/operation-data path/to/existing-checkpoint path/to/new-run +  --budget path/to/existing-budget.json +  --task memory_operation --optimizer-updates 524 +  --eval-at-updates 32 64 128 262 393 524 +  --evaluate-train --shuffle-options +  --feedback-dev-data path/to/feedback-dev.jsonl +  --encoder-lr 2.5e-5 --head-lr 1e-4 +  --max-len 12288
~~~

该 trainer 沿用现有双 GPU 分配约定；命令不表示本地已具备 GPU、模型或预算文件。长度值复用现有条件便于对照，8K/长输入分桶另报。

验证记录位于 **artifacts/training-generalization-20261021/**；最终检查数量和实际准备摘要见
[本轮开发结果](../data/manifests/training-generalization-development-20261021.json)。
当前环境缺 torch/Laya，相关 tensor/GPU 测试跳过；没有用纯函数通过代替真实训练通过。

本轮完成的是可复用的数据入口与训练诊断功能，以及真实公开样本的离线接入。泛化是否改善，需要按上述来源、反馈和 Host 终点分别验证。
