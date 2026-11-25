# MiLAi V13 Q-RAG 执行记录

开发分支为 `feat/memory-control-v13-qrag-20261125`，从 V12 review 版本 `7bb27c12` 建立。计划原件位于 `jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_MEMORY_CONTROL_V13_QRAG_TRAINING_PLAN_20261125.md`。以下路径相对 V13 工作树的 `MiLAi-Lab`。运行产物位于 `/cra/milai-experiments/v13-qrag`。SHA 校验已禁用。

## 研究问题与当前证据

| 研究问题 | 训练中已经测到的结果 | 作出结论还需取得的结果 |
| --- | --- | --- |
| 原版 Q-RAG 能否学会多步检索 | MuSiQue-Ans 固定 300 题，初始化集齐 86 题，第 1,000 次更新集齐 167 题，中间曾降到 35 题 | 10,000 次更新的完整曲线，以及初始化、最佳和最终模型在同题上的原生支持 F1 与覆盖 EM |
| H1：同骨干终局训练能否超过原生相关性策略 | S1 终态弱证据排序宏 AUC 为 0.8724，冻结 GTE 为 0.7885。Direct-Q 与 Paired-Q 已在相同 550 包上完成首次结果拟合 | 真实终局反馈训练后的 DQ、PQ 与冻结 GTE 的同组完整任务比较，以及最终方法对最强同骨干对照的独立确认 |
| H2：结构化选样能否提高反馈效率 | 已结算共同 warm 的 2,000 次实付。相同请求的跨臂复用可产生监督曝光而无新增调用 | 6k 比较共同状态池下的选样，12k/24k 比较各自在线策略。DQ 与 PQ-U 另在同一批结果上检验配对目标。保留采样优势主张时追加独立采集与通用采样对照 |
| H3：质量和成本收益能否迁移 | 完整 TUNE605 上，冻结 GTE 相对四读规则节省 32.62% 的 Reader 输入 tokens，宏质量差为 −1.86 分，95% 区间为 [−4.80, +1.05] | 已训练策略在 512、1,024 材料预算和未暴露原生组上的原生质量、实际资源与时延。整板能耗在当前共享服务器上无法独立归属 Reader |

## 数据角色与暴露

通过 V1 SQLite 逐行解码弱标签得到 206,657 个状态，其中 198,079 个至少有一个已知动作标签。17,089 个排除任务继续生效。运行器用 V1.2 的继承组注册、固定 Reader 选项及合法预览。当前 TRAIN 共 43,901 题，区别于 V1 在划分实验角色前的 43,929 题。

| 来源 | V1 clean train 题 | V13 TRAIN 题 | V13 TRAIN 原生组 |
| --- | ---: | ---: | ---: |
| MuSiQue-Full | 39,876 | 39,848 | 19,924 |
| QASPER | 2,593 | 2,593 | 888 |
| PersonaMem-v2 | 1,460 | 1,460 | 65 |

V1.2 初始库存见 `inventory/inventory.json`。合并独立评估库和 REF 暴露后的当前库存、每个原生组的角色与排除数见 `inventory-current/inventory.json` 与 `inventory-current/native-groups.tsv.gz`。沿用 605 题、222 组的 DEV 作为 TUNE。在这批组内固定 150 题、54 组，用于反馈学习曲线。在其余 DEV 组中预先抽取 99 题、39 组用于 CALIBRATION。每个来源独立按完整原生组选取。512、1,024、2,048 三档预算使用相同任务和 Reader 种子。

V12 公开结果已分析 620 个确认组，其中包括全部 75 个 QASPER 论文和 220 个 PersonaMem 人物。对剩余 295 个 MuSiQue 候选组复核时发现，REF 初次验证从 Ans dev 抽取的 300 个位置触及 44 个候选组。已扣除这些组，并将 REF 后续验证固定在 300 个已曝光 TUNE 组。全量来源交集与初始抽样重放见 `ref/mu-exposure-reconciliation.json`。独立确认的来源扩展采用 QASPER 官方 test 及 PersonaMem-v2 的 text benchmark，用组标识对历史暴露做交叉核对。

独立确认库已准备 610 个原生组、6,065 题，其中 MuSiQue 为 251 对、502 题，QASPER 为 160 篇、569 题，PersonaMem 为 199 人、4,994 题。组筛选核对了历史登记、125 个评估运行、85 个归档及原生 SQLite 结果账本。三源冷启动准备成功，确认 Reader 调用数为 0。此次核对覆盖可访问的项目历史，对公共预训练语料的暴露情况仍未知。库存和审计结果见 `fresh-sources/final-source-role-audit.json` 与 `fresh-sources/final-packet-ledger-audit.json`。

## 已执行测量

| 测量 | 实际记录 | 证据位置 |
| --- | --- | --- |
| GTE S0 | 64 个真实状态，批大小 32，2 次 AdamW 更新，306,375,945 个可训练参数，BF16 计算。22.05 秒，峰值显存 8,650,224,640 字节，重载动作分数逐项相同 | `gte/s0/run.json`、`gte/s0/encoder_update.json` |
| S0 回到实际运行器 | 在一条 TRAIN 诊断轨迹上选择 HANDOFF，终端 Reader 输入 275、输出 21 tokens，QASPER F1 为 0 | `gte/s0-train-episode/` |
| 同数据目标诊断 | DQ、PQ 使用相同 32 个已测根状态、69 个可比较动作对，各自完成全参更新和重载 | `gte/s0-objectives/` |
| 评估链路 | B1 的早期计时运行覆盖曲线集 150 题，实付 150 次，宏质量 23.90。该次运行关闭了数值预检观察，正式比较采用统一的数值观察 | `rule-curve-2048/` |
| 冻结 GTE 相关性 | R2、最多 4 读，在 99 题校准集实付 99 次，宏质量 24.54。这是预算规则选择的一个候选 | `gte-r2-reads4-cal/` |
| 原版参考 | 单独使用 MuSiQue-Ans、双 E5-large、原版支持事实奖励与 PQN。300 个 TUNE 问题的平均 GT 回报由初始化的 0.286667 到第 100 次更新的 0.340000，完整配方为 10,000 次更新。第 100 次更新的 actor 已持久化为基于 E5 基础权重的差分归档，790 个张量经恢复后逐项相等 | `ref/official-musique-tune300-seed42/` |
| 回归 | 带 PyTorch 的环境执行记忆控制及新增针对性测试，当前 101 项通过 | `v13-focused-phase-close.log` |

11 月 25 日 07:57，GPU 3 上的 seed11 证据初始化完成一轮实际遍历，共 3,732 次更新。持久训练输入为 `gte/evidence.sqlite`。三源合计 43,183 题、20,806 个原生组、119,394 个根状态，包含 894,356 个已知证据动作标签和 28,446 步合法示范。当前 TRAIN 中另有 557 个 QASPER 任务、161 个 PersonaMem 任务未提供可用于 S1 的根状态。

| 来源 | S1 实际任务 | S1 原生组 | 遍历的根状态 |
| --- | ---: | ---: | ---: |
| MuSiQue-Full | 39,848 | 19,924 对 | 110,133 |
| QASPER | 2,036 | 817 篇 | 5,351 |
| PersonaMem-v2 | 1,299 | 65 人 | 3,910 |

最终模型含 306,375,945 个参数。156 个保存张量均为有限 FP32，重载后动作分数与训练结束现场逐项相等。拟合进程占用单卡的墙钟为 24,626.12 秒（6.84 小时），其中登记过的 Reader 轮转停放为 3,480.79 秒，扣除后为 5.87 小时。优化循环记录为 24,608.63 秒，含同一次停放。峰值 CUDA 分配为 8,666,696,704 字节。[完成收据](/cra/milai-experiments/v13-qrag/weights/s1/run.json) · [权重与样本复核](/cra/milai-experiments/v13-qrag/gte/s1/final-verification.json)

首次分组排序曾导致连续 71,516 个根状态没有 QASPER、连续 78,612 个没有 PersonaMem。该次拟合在 77 次更新、2,464 个根状态后退役，544.58 秒开销另计入 `gte/s1-initial-allocation/`。正式运行从相同预训练权重重新开始，按遍历窗口分散原生组，保留每条样本的一次曝光和来源权重。修正后两个最长间隔分别为 291 和 275。逐更新曲线见 `gte/s1/curve.jsonl`。

QR 的实时终局 PQN 诊断已完成 48 次实付 Reader 调用，其中包含 18 次 companion。30 条主轨迹均获得原生质量和未来成本，双塔均有可测参数变化，4 次 GPU 优化更新完成，检查点重载可对实际候选菜单评分。计量见 `qr-s0/verified-48.json`。

B1 早期测量和 GTE 校准测量分别来自两批预先指定的任务。两者分别消耗 181,788/7,816 和 114,127/5,123 个 Reader 输入/输出 tokens。计入策略加载摊销后的端到端 p50/p95 分别为 1.09/1.70 秒和 1.58/2.36 秒。不同任务构成限制了横向解释。原生 GTE 初次校准使用对象 microbatch 2，正式校准统一显式登记为 8，两个设置的请求全部计入开发开销。原始成本表见 `initial-readout-costs.json`。99 题 B1 四读校准累计占用 Reader 租约 126.61 秒，实测 0.78 次/秒。冻结 GTE 两读、R2、对象批次 8 的 99 题轮次为 141.18 秒、0.70 次/秒。这些数值包括窗口内预处理和策略加载，未计入等待其他运行释放租约的时间。较新运行另记 vLLM RUNNING 阶段耗时，仅接纳已完成请求数及输入/输出 token 均与同窗口原始收据相符的增量。后续原生窗口还支持相同完成请求的排队、prefill、decode 时间及实际计算/缓存的 prompt tokens；各分项均独立核对服务端完成数量并报告覆盖。早期无记录的分项保持未知。正式矩阵、同骨干提升、反馈效率与工程节省均需等对应检查点和同组在线读出。结果允许简化到 Direct-Q 或规则策略。

**Reader 设备能耗的测量边界。** 2026-11-25 对现有服务做了两次只读 NVML 观察。TP0/TP1 位于 A100 卡 0/1，两卡均支持自驱动加载起累计的毫焦计数。第一窗 8.130675706 秒，两卡分别增加 288,031 与 296,190 mJ，合计 584.221 J（71.85 W）；复测 8.092028460 秒，分别增加 291,494 与 296,075 mJ，合计 587.569 J（72.61 W）。两窗各五次 GPU 利用率采样均为 0%，项目原生账本从 413216 到 413216。复测前后 TP worker PID 2165299、2165610 及两张卡上的 bge-m3、bge-reranker 进程均在。记录包含原始时钟、板卡 UUID、mJ、设备功率、PID/容器归属及账本边界，见 `runtime-validation/reader-tp2-nvml-observation.json`。

该数值给出采样窗口内两块整板的毛能量，含驻留、空闲与外部活动。对于完全落在同一观测窗口、同两板上的 Reader 工作，整板总量可作上界；本次项目请求数为零，因此两窗仅提供背景参考。主机和另一张控制器卡的能量在此范围之外。两卡 accounting mode 均关闭，查询 TP worker accounting stats 返回 Not Found；利用率环形样本和 vLLM 请求用时仅提供采样比例或服务时间。H3 继续分别报告可观测 Reader 用量、控制器时间与端到端时延，Reader 独占能量、累计 GPU 忙时和货币费用保持未知。[NVML 设备计数接口](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html) · [NVML 进程统计语义](https://docs.nvidia.com/deploy/nvml-api/latest/api/structnvmlAccountingStats__t.html)

## 原版训练曲线与 S1 的留出读出

REF 在固定的 300 个 TUNE 问题上逐题验证。初始化到第 1,000 次更新，每 100 步分别有 **86、102、66、35、45、73、101、132、149、146、167 题**集齐全部支持块。预热结束时集齐率为 55.67%，比初始化多完成 81 题。中段曾连续四次低于初始化，之后五次验证均高于初始化。第 1,000 次验证时累计 96,012 条 critic 转移，训练回报为 0.6426，TD 损失为 0.0648，骨干探针相对初始化最大改变量为 5.21e−4。训练环境会扣除多余读取的奖励。验证环境按是否集齐支持块给 0 或 1。均匀无放回读取四块的解析完成率为 1.89%。所有 300 题均可在四步内集齐。

最佳权重按新的开发集纪录滚动保存。持久索引在恢复并逐一核对 790 个张量后更新，另留第 100 次更新的早期对照。训练中的曲线随验证点更新，终评另在这 300 题比较初始化、最佳与最终模型的原生支持 F1 和覆盖 EM。[训练曲线](/cra/milai-experiments/v13-qrag/ref/official-musique-tune300-seed42/Nov25_00-48-23_QRAG_musique/reference-learning-curve-progress.png)

S1 第 256 步和第 3,732 步分别在自然 DEV150 冷启动后对相同 R2 菜单评分。1,200 个可行候选中，115 个为已知正例，949 个为已知负例，136 个保持未知。75 题、42 个原生组提供 677 个正负对。以任务 AUC 处理平局，再按原生组、来源等权平均。终态评分的 150 题均与早期冻结来源重放的候选、合法输入和弱标签逐项吻合，两套固定基线的逐动作分数差均为零。

| 来源 | 提供正负对的任务 / 原生组 | BM25 AUC | 冻结 GTE AUC | S1 第 256 步 AUC | S1 终态 AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| MuSiQue-Full | 43 / 24 | 0.7768 | 0.9532 | 0.8697 | 0.9341 |
| QASPER | 18 / 8 | 0.7728 | 0.7307 | 0.7495 | 0.8948 |
| PersonaMem | 14 / 10 | 0.6137 | 0.6815 | 0.6101 | 0.7881 |
| 等来源平均 | 75 / 42 | 0.7211 | 0.7885 | 0.7431 | 0.8724 |

终态相对第 256 步的 AUC 差为 +0.1292，按来源配对重采样原生组的 95% 区间为 [+0.0776, +0.1794]。相对 BM25 为 +0.1513 [+0.0914, +0.2113]，相对冻结 GTE 为 +0.0839 [+0.0220, +0.1465]。QASPER 和 PersonaMem 的终态点估计均超过冻结 GTE，各自有 8 篇论文、10 个 persona 提供可比较标签。MuSiQue 仍以冻结 GTE 排序最高。该结果支持将完整 S1 作为共同初始化。两次 DEV150 诊断均未发出 Reader 请求。[终态配对读出](/cra/milai-experiments/v13-qrag/gte/dev150-weak-s1-final/PAIRED-READOUT.md) · [分来源 AUC 与配对区间图](/cra/milai-experiments/v13-qrag/gte/dev150-weak-s1-final/s1-weak-evidence-auc.pdf)

逐题连接实际首读可见，冻结 GTE 在 25 个 MuSiQue 可答成员上有 23 次首读命中弱正例，其中 20 对终局 pair 质量为零，17 对未通过充分性门控。B1 的对应计数是 16、13、10。单对象检索与完整证据组合之间的缺口可在 `musique-dev150-first-read-vs-pair.json` 中复查。终局答案质量的结论仍须由完整策略交付与原生 Reader 评分给出。

在第 1,024 步持久恢复点，实际曝光数为 MuSiQue 30,232、QASPER 1,465、PersonaMem 1,071。重放精确根顺序与每步实际梯度范数后，906 次更新触发了梯度裁剪。根损失系数在裁剪前按来源约为 50.0% / 35.0% / 15.0%，乘上实际批次裁剪因子后为 81.7% / 10.2% / 8.0%。这些系数描述每个根梯度进入 AdamW 之前受到的缩放；实际参数变化还取决于梯度的大小、方向和优化器状态。该诊断为不同来源的学习表现提供了一个可检验的解释，本轮继续既定配方。见 `gte/s1/clip-coefficients-1024.json`。

## 已执行的证据条件诊断

在 TUNE 预先指定的 36 个原生组中，每来源 12 组。对同一问题先读两个不同的 R2 对象，匹配剩余预算，然后测同一个候选相对 HANDOFF 的真实终局收益。每组四个主分支，另有 12 次 MuSiQue companion，实付 156 次。两状态的材料预算差中位数分别是 MuSiQue 5、QASPER 2、PersonaMem 3 tokens。全部 36 组的两个收益差都有观测。

QASPER 出现 1 次严格反转，即一个状态中读取优于停止，另一个状态中读取劣于停止。MuSiQue 和 PersonaMem 各为 0 次。含零收益在内，两个状态的收益值发生变化的组数依次为 MuSiQue 2、QASPER 2、PersonaMem 0。结果位于 `evidence-diagnostic/native-reversals.json`。此次读侧菜单下主要变化的是已交付证据；未交付的已获取正文单独保留了字段，其独立作用仍缺少覆盖。这批样本中的反转稀少，对集合条件机制的判断需结合正式模型的诊断误差及自然任务表现。

## 已冻结的规则基线

四个规则候选各执行 99 题 CALIBRATION，共实付 396 次。预先约定在距本族最高宏质量 1 个百分点内的候选中，选择三来源端到端 p50 平均值最低者。B1 的四读规则入选。下表为同组实测，时延含策略加载摊销。冻结后的自然 DEV 评价另行计量。

| 方法 | 宏质量，分 | 全题 p50，毫秒 | 全题 p95，毫秒 |
| --- | ---: | ---: | ---: |
| B1-2 | 20.97 | 955 | 1582 |
| B1-4 | 28.03 | 1107 | 1935 |
| B2-4 | 24.94 | 1105 | 1948 |
| B3-4 | 27.47 | 1541 | 2139 |

同一 99 题上，固定 GTE 相关性策略的四个候选也各付费 99 次。冻结配置为 R2、两次读取、对象批次 8，校准宏质量 30.36 分。GTE 的候选成本见 `gte-calibration-costs.json`。对两次 R2 两读的完整校准读出做了逐题复核，全部 99 个请求的 payload 与 seed 相同，5 个任务的单题得分仍发生变化。正式评估将 Reader 随机性与拟合、采集种子分别处理。此处两表仅用于校准；最终效果由相同自然 DEV 和新确认组读出。

每个来源的得分、用量、覆盖数见 `rule-calibration-costs.json`。选择依据见 `baselines/rule-selection.json`。

## 共同 2k 反馈闭合

初始训练数据含 550 个完整根状态，2,035 个逻辑测量回执。原生 Reader 账本对应 **2,000 次互不重叠的新请求**，其中 1,670 次为首动作分支、330 次为 MuSiQue companion。另有 35 次相同请求的兼容复用。所有实付回执均已绑定，未完成包占用、未知收费和未归属回执均为 0。DQ 与 PQ-U 后续可以复用同一套观测；对 PQ-U 和 PQ-A，各自计入这 2,000 次监督曝光，项目物理开销计一次。

| 来源 | 完整根状态 | 不同原生组 | 实付反馈 | 有多个已测动作的根 | 终局质量随首动作改变的根 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MuSiQue-Full | 330 | 330 | 1,320 | 330 | 45 |
| QASPER | 166 | 160 | 469 | 132 | 56 |
| PersonaMem | 54 | 35 | 211 | 53 | 9 |

PersonaMem 占根状态 9.82%。三源每个原生组被选取的最大根状态数依次为 1、2、3。首批费用修正前的回执和前缀完整保留，修正后的 352 个包中，预计本臂曝光和预计新增调用均与逐包实扣吻合。已冻结两条机制臂共同的未标注 TRAIN 状态池，并扣除了 warm 占用的原生组名额。

截至此阶段，整个 V13 目录结算 **5,104 次物理 Reader 请求**。其中 2,000 次属于共同 warm，48 次属于 QR 的 S0 试验，1 次属于 GTE S0 完整 episode，3,055 次属于开发读出、校准、机制诊断及前期运行。累计 provider 输入 5,643,485 tokens，输出 289,525 tokens；22 次格式失败保留了费用和对应原生评分。项目结算表为 `project-after-warm.json`，采集明细为 `warm-2000.json`，原生账本复核见 `runtime-validation/warm-2k-closure.json`。

## 冻结策略在自然 DEV 上的表现

在与 CALIBRATION 原生组互斥的 150 题曲线集上，B1 四读和冻结 GTE 两读各运行 150 个完整 episode。下表使用原生 MuSiQue pair、QASPER answer F1 和 PersonaMem MCQ 准确率。时延包含实际策略加载摊销。

| 策略 | MuSiQue | QASPER | PersonaMem | 三源宏质量 | Reader 输入 tokens | 全题 p50 / p95 秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B1 四读 | 16.00 | 29.27 | 24.00 | 23.09 | 181,788 | 1.59 / 2.32 |
| 冻结 GTE 两读 R2 | 12.00 | 25.79 | 16.00 | 17.93 | 122,269 | 1.00 / 1.55 |
| 标注证据诊断策略 G | 23.07 | 37.57 | 22.00 | 27.55 | 91,061 | 0.70 / 1.95 |

G 的读取选择使用离线证据标注，仅用于定位质量损失。对两个部署候选按来源配对重采样 5,000 次，冻结 GTE 相对 B1 的宏质量差为 −5.16 分，95% 区间 [−10.44, −0.31]；Reader 输入节省 32.74%，区间 [30.34%, 34.99%]。选择 2 次读取的冻结 GTE 在校准集上质量更高，在这批自然 DEV 题上则以质量换取较低 Reader 成本。605 题 TUNE 完整读出用于核对较大开发集上的基线表现。结果见 `natural-dev150-baseline-costs.json`、`natural-dev150-frozen_gte-vs-rule.json`。

扩展到完整 TUNE 的 605 题、222 个原生组后，B1 宏质量为 25.57，冻结 GTE 为 23.71。GTE 相对 B1 的质量差为 −1.86 分，组配对 95% 区间 [−4.80, +1.05]。分来源差异主要出现在 MuSiQue（13.80 对 19.30）；QASPER 为 32.59 对 32.17，PersonaMem 为 24.75 对 25.25。此 TUNE 含上表的 150 题，对应原生组扩展读出。

B1 与 GTE 的实付请求各 605 次，分别消耗 702,896 和 473,673 个 Reader 输入 tokens。GTE 节省 32.62%，区间 [31.54%, 33.65%]。其端到端 p50 从 1.079 秒降至 1.039 秒，p95 从 1.578 秒升至 1.791 秒，实际总墙钟也受评估期间负载影响。两种策略各有 1 个格式失败，均已计费并按原生协议处理。后续同骨干学习增益以冻结 GTE 为对照，实际基线还包括 B1 与独立训练的 QR。

两种策略在 100 个 MuSiQue pair 上有 81 个同分，GTE 有 7 个更高、12 个更低。仅看可答成员，GTE 与 B1 的平均 answer F1 分别为 24.93、29.53；两个成员均判对充分性的比例分别为 26%、29%。计入 pair 门控后分别为 13.80、19.30。QASPER 有 41 题 GTE 更高、37 题更低，PersonaMem 有 8 题更高、9 题更低。按正、负差异分别保存绝对差最大和靠近中位数的原生组及其实际读序列，见 `natural-tune605-error-examples.json`。

完整 TUNE605 表和区间见 `natural-tune605-baseline-costs.json`、`natural-tune605-frozen_gte-vs-rule.json`。150 题部署图与 CSV 来自同一批实际读出。CSV 的每行对应一个策略和检查点，来源质量以百分点记录，输入输出 tokens、控制器 GPU 毫秒、检索预处理耗时分别列出观测总量与覆盖题数。空单元格表示该值缺测。冻结基线的训练栏为零，仅代表本轮无需新增控制训练。后续 6k/12k/24k 绘图调用会从同组的实测检查点生成相同格式的成本表。[DEV150 冻结基线实测成本表](/cra/milai-experiments/v13-qrag/figures-dev150-baselines/checkpoint-costs.csv)

逐题重放还比较了完整证据集合的可达性。表中计数为在给定数量的 BM25 候选上，用全部合法 R2/R3 跨度的并集覆盖某一个完整标注集合的题数。这是施加材料预算与操作数限制前的上界。八候选一列已与 150 条实际 G 运行的逐题覆盖标记核对。其余两列只做离线检索诊断。

| 来源 | 有完整标注的题 | 前 8 | 前 16 | 前 32 | G 实际交付完整集合后原生质量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MuSiQue | 25 | 10 | 15 | 25 | 31.01 分，10 对 |
| QASPER | 39 | 27 | 34 | 37 | 50.02 分，27 题 |
| PersonaMem | 48 | 8 | 10 | 20 | 50.00 分，8 题 |

在 48 道具备完整标注的 PersonaMem 题中，40 道的证据在八候选时不可达。QASPER 在八候选时有 27 道可达，B1 实际交付了其中 12 道的完整集合，冻结 GTE 交付了 8 道。由此可以分开考察召回缺口、控制器选择及给定已交付证据后的 Reader 表现。后续同骨干和采样主表沿用共同的八候选设置。重放产物见 `natural-dev150-reachability.json`。

**固定 G 策略的材料预算见证。** 三份自然 DEV150 清单仅有材料预算字段不同。对同一 54 个原生组、每来源 50 题，在限额 512、1,024 和 2,048 下，分别使用正式标注引导策略 G、合法菜单和最多六步的 Host 执行与交付。表格各预算列给出完整交付题数 / 有完整标注的题数，括号内为该来源全部 50 题的平均材料 tokens。计量对象是 Host 按固定 Reader 分词器序列化的 memory 交付包，包含包包装，系统提示、问题和输出另计。

| 来源 | 原生组 | 有完整标注题 / 无完整标注题 | 完整标注集合总数 | 512 | 1,024 | 2,048 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MuSiQue-Full | 25 对 | 25 / 25 | 25 | 4/25（214.02） | 10/25（270.92） | 10/25（270.92） |
| QASPER | 12 篇 | 39 / 11 | 61 | 16/39（180.32） | 24/39（329.94） | 27/39（441.80） |
| PersonaMem-v2 | 17 人 | 48 / 2 | 48 | 4/48（151.28） | 8/48（185.98） | 8/48（185.98） |

逐题配对的 0→1 / 1→0 指同一题由未完整交付转为完整交付 / 相反变化。512→1,024 时，MuSiQue 为 6/0、QASPER 为 8/0、PersonaMem 为 4/0。1,024→2,048 时分别为 0/0、3/0、0/0。因此相等计数确实对应相同的 10 道 MuSiQue 题和相同的 8 道 PersonaMem 题。MuSiQue 另有 25 个原生不可答成员，QASPER 有 4 个不可答、3 个仅图示、4 个证据对齐不完整的任务，PersonaMem 有 2 题位置未知；这些题的完整集合交付标签保留为未知。

三档共得到 450 个可用 Host 交付包。2,048 档的 150 题逐一核对了原有付费返回的身份、动作、材料包、来源别名、覆盖标记、材料用量及完整 wire。本次在禁用网络的 CPU 进程中重放，新增 Reader 请求为零。512 与 1,024 的完整交付给出了该策略的可行实例；其他合法动作序列仍可能送达更多集合。小预算答案质量和学习策略的预算迁移效果仍待相应读出。见 `natural-dev150-G-budget-witnesses.json`；复现入口为 `tools/diagnose_memory_control_v13_recall.py --data DATA --gold-run G_RUN --budget-rosters ROSTER_DIR --output REPORT`。

在 550 个 warm TRAIN 根上，同对象的 R2、R3 都有真实结果的样本包括 82 个 QASPER 对象和 51 个 Persona 对象。133 个对象的首步交付全部改变。QASPER 有 40 对在后续读取后交给 Reader 的最终请求相同。若将首步增量、后续材料和 Reader 输入输出都计入，R3 更贵且原生质量未提高的对象在两个来源分别为 36/82 和 49/51。330 个 MuSiQue 根均无同时合法的两个粒度，无法由这批数据量出其升级收益。不同粒度的均值适用于已执行的对象与冻结续跑策略。

自然 DEV150 的 25 个 MuSiQue 原生组中，有 21 组的首个桥接段落完整落在前八候选内。B1 和冻结 GTE 分别通过 READ 实际补足了其中 18 组和 19 组。全部支持段落都在前八的仅有 10 组，两臂各交付了 5 个完整集合，其中 3 个组相同。GTE 较常在首读交付桥接段落（16/25，B1 为 8/25），该优势未扩大完整证据覆盖。各组原生答案、区间交付和实际请求的对应关系保存在 `runtime-validation/warm-550-dev150-read-effects.json`。

## 采集、计量与复现

GTE 的优化循环耗时保存在每个拟合的 `run.json`。正式反馈曲线的训练 GPU 小时另按单卡作业时段计量，涵盖输入准备、模型加载、优化、保存与回读，并累计有结束时刻的失败重试。后续拟合在取得运行权后开始计时；已运行的 S1 用原 PID 的内核启动时刻至退出事件计时，保留期间登记过的 Reader 轮转等待。每份时段的口径及覆盖保存在相应权重目录的 `fit-windows/`，缺少历史时段时，完整拟合小时保留未知。与采集阶段的控制器驻留时长相加后，可比较各方法占用单卡的实测时间；跨方法同时驻留的区间会重合。部署时的控制器前向 GPU 毫秒、Reader 服务时长和端到端时延另算。

```bash
export PYTHONPATH=src
export R=/cra/milai-experiments/v13-qrag
export P=/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python
export D=/cra/milai-datasets/memory_control_v1_2
export HF_HOME="$R/staging/gte/hf-cache"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1
"$P" tools/run_memory_control_v13_evaluation.py register --data "$D/memory_control.sqlite3" --tune /data/milai-experiments/20261119-memory-control-v12/dev-population-v12.json --output "$R/rosters"
"$P" tools/report_memory_control_v13_inventory.py --parent /cra/milai-datasets/memory_control_v1/memory_control.sqlite3 --derived "$D/memory_control.sqlite3" --historical-run '/data/milai-experiments/20261119-memory-control-v12/confirmation/primary/B*' --rosters "$R/rosters" --output "$R/inventory"
HF_HUB_OFFLINE=1 "$P" tools/calibrate_memory_control_v13_cost_unit.py --output "$R/frozen-host-cost-scale.json"
"$P" -m milai_lab.runners.control_policy_iteration --output "$R/warm-11" --calls 2000
"$P" tools/report_memory_control_v13_feedback.py "$R/warm-11" --out "$R/warm-progress.json"
CUDA_VISIBLE_DEVICES=3 "$P" tools/calibrate_memory_control_v13_baselines.py --root "$R" --backbone "$R/staging/gte/base" --family gte
"$P" tools/calibrate_memory_control_v13_baselines.py --root "$R" --backbone "$R/staging/gte/base" --family rule --device cpu
"$P" tools/diagnose_memory_control_v13_evidence.py --output "$R/evidence-diagnostic" collect --data "$D" --population "$R/rosters/curve-2048.json"
```

正式 QR/DQ/PQ 的共同成本尺度来自 TRAIN 终端请求的 Host 计数。三源各预先均匀抽取最多 64 个不同原生组，每组选一个任务，用四读规则及 2,048 材料预算构建完整 Reader 请求，取其 prompt tokens 中位数。实测 192 个请求全部可计数，共同尺度为 **1,912 tokens**，见 `frozen-host-cost-scale.json`。该标量在无网络命名空间内生成，读取 Reader 回复的次数为 0。这样独立训练 QR 时无需读取 PQ 的付费分支数据。各已执行分支的实测未来成本标签和 0.1 损失权重继续按计划使用。早期 S0 诊断的旧成本尺度随原试验保留。

完整分支从已执行的公共 SEARCH 开始，在最多六次操作、统一检索 32 个对象并保留前八个的条件下决策。每次终止登记真实 Reader 回包。MuSiQue 使用同一冻结策略独立运行另一成员，再用原生 pair 门控得分。训练未知质量保留 mask，调用账目包括 companion、重试和付费失败。

反馈组包的 Q、未来成本与预定义动作比较保存在 `packs/`。对应真实反馈放在 `receipts/`，沿用共享 Reader 账本。报告对费用未知的回包单独计数。实际 Reader 输入、输出、控制器 GPU 毫秒、检索预处理及端到端 p50/p95 分项报告。端到端 GPU 服务成本需要能归属到本次调用的服务器计量数据。

REF 与 GTE 的资源调整及具体训练命令分别见 `MILAI_MEMORY_CONTROL_V13_QRAG_REFERENCE.md` 和 `MILAI_MEMORY_CONTROL_V13_GTE.md`。服务器使用物理 GPU 2 训练 REF，GPU 3 训练项目控制器，GPU 0、1 提供既有冻结 Reader。启动阶段曾在四张物理 GPU 上并行进行训练和采集，此阶段墙钟和时延反映了实际共享服务条件。S1 第 256 次更新完成持久恢复点后，轮转调度在第 265 次更新处保存了两个训练进程的现场，转入 Reader 采集时段。`initial-schedule.json` 记录初始 Reader 阶段持续 3,480.79 秒。2026-11-25 02:31（北京时间）两个原进程已恢复，S1 沿同一次拟合从第 265 步实际继续更新。工作进程驻留的显存、等待时间和活跃计算分别披露。`phase/phase.json` 当前为训练时段，先完成 REF 完整曲线和 S1。两者结算后，`tools/schedule_memory_control_v13_initial.py --advance` 会自动接纳正式 QR、DQ/PQ 及检查点评估，按任务单元分时执行。

核心反馈矩阵使用 `configs/memory_control_v13/feedback.json`。seed11 的两份 warm 拟合均已完成。它们从同一 S1 权重出发，在 2,000 次共同反馈产生的 550 个包上各遍历 3 次，根状态曝光各为 1,650 次。两份拟合的训练合同逐项比较，仅监督模式与配对损失权重不同。它们对相同末尾探针的输出有别，各自重载后的输出与现场完全相等。

| seed11 warm 模型 | 更新 | 有质量/成本标签的动作曝光 | 可比较的动作对曝光 | 纳入配对损失的动作对曝光 | 配对权重 | 单卡拟合作业秒数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct-Q | 54 | 5,115 / 5,115 | 3,465 | 0 | 0 | 339.61 |
| Paired-Q | 54 | 5,115 / 5,115 | 3,465 | 3,465 | 0.2 | 354.33 |

新的 6k、12k 采集等待原版参照完整曲线。PQ-U 与 PQ-A 将从同一个已训练的 warm Paired-Q 模型出发，在固定池内分别选包；DQ 后续继续重用 PQ-U 包。成本表分别记录监督曝光与新增收费调用。[2k 同数据拟合明细](/cra/milai-experiments/v13-qrag/warm-11/matched-controller-fits.json)

反馈效率按两种横轴读出。累计监督曝光包括从其他臂沿用的已付且请求一致的结果；新增实付调用与 provider 输入、输出 tokens 只计该臂数据目录实际发生的账位。两种口径都包含共同 warm，项目总账跨臂只计一次。DQ 沿用 PQ-U 整套结果包，额外生成标签的费用为零。后采集的臂可沿用先采集的请求，因此两臂新增费用的差异也受执行顺序影响。实际复读中，warm 的 2,000 次实付对应 2,483,899 个输入和 139,144 个输出 tokens，QR 试验的 48 次对应 47,146 个输入和 3,269 个输出 tokens。一组来自其他臂的已有回执提供了 4 次监督曝光，新增实付和 tokens 均为零。无法归属账位、仅有本地估算或一次回包不能覆盖全部收费尝试时，对应的实付统计保留未知。见 `runtime-validation/training-reader-billing.json`。

```bash
CUDA_VISIBLE_DEVICES=3 "$P" tools/run_memory_control_v13_rounds.py --config configs/memory_control_v13/feedback.json --root "$R" --weights "$R/staging/round-models" --s1 "$R/staging/gte/s1/checkpoint" --curve "$R/rosters/curve-2048.json" --until 12000
```

这条命令依赖 S1 完成与 warm 达到额度。独立研究进程的状态与交接记录在 `main-study-status.json`、`main-study-handoff.json`。该进程核对实际 S1 及持久 checkpoint，再启动 12k 主矩阵。QR 在线训练器与 6k/12k 曲线任务各自保有原生 lease。四种方法取得相同自然 DEV 组的 6k/12k 结果后，程序按组计算配对差异和实际候选动作的收益及费用，接续第二次冻结策略更新到 24k。随后绘制按反馈调用、tokens、训练 GPU 小时、部署资源和时延计量的曲线，在同一个 CALIBRATION 上对四个 24k 控制器使用相同的五点 λ 网格，各自选定 λ 后读出 TUNE。见 `tools/settle_memory_control_v13_round.py`。截至分时训练阶段，该续作业尚未追加 Reader 调用。

冻结数据拟合可通过 `--frozen-data --fit-seed` 复用同一采集历史，`--refit-method` 只拟合最终选入比较的家族，`--refit-only` 保留各轮参数更新，把 Reader 调用留给指定的正式评估。独立采集种子的费用和拟合种子分开结算。

## 拟合重复、粒度消融与未训练预算

08:10，两份 seed11 warm 模型均已闭合，正式分支采集正在等待 Reader 时段。GPU 3 在这一训练空窗开始预计算种子 29、47 的共享证据初始化。两次按顺序从原生 GTE 出发，各使用相同冻结 SQLite 及 seed11 的完整证据配方。种子 29 已产生真实更新。这里只提前执行会被最终家族共用的证据训练，方法选择只使用 seed11。终局结果包的重复拟合及泛化读出仍在 24k 选择后进行。若最终未采用某份初始化，其计算量列为已发生的试验开销。[空窗运行声明](/cra/milai-experiments/v13-qrag/gte/evidence-prefix-residency.json)

24k 校准关闭后，`tools/repeat_memory_control_v13_finalists.py` 在同一完整 TUNE605 上选择拟合复核家族。最终候选由 DQ、PQ-U、PQ-A 中宏质量下界最高者担任，精确同分依次优先 DQ、PQ-U、PQ-A。与之对比的同骨干控制从其余训练方法及冻结 GTE 中按同一质量规约预选，实际基线从 RULE、冻结 GTE、QR 中选择。各方法均使用已登记的校准机会。选择只读取开发数据，并保存全部候选的原生质量和选择依据。

对种子 29、47，重复相同冻结 S1 证据数据的完整拟合，再按原采集种子 11 的冻结 warm、机制、两轮在线结果拟合入选的终局方法。每个种子沿用 seed11 在校准集选定的停止代价，分别记录拟合变异和在线表现。三种子方差/功效比较使用相同有序 TUNE 原生组；开发预算允许时使用完整 605 题，其余情形在保留全 605 题首种子选强证据后，按剩余开发额度分来源抽取完整原生组，并保持父 TUNE 的推理顺序。真实已付回执与拟合重复所需臂数决定该子集。以实付的 3,055 次初期开发调用为起点，预留主矩阵 1,800 次、24k λ 校准和 TUNE 4,400 次、粒度与预算查验 900 次。若需复核两套可训练家族，且两种续跑各新增 84 次语义诊断调用，这组预算情景会为每份额外拟合读出选择 408 题、148 组，总计 11,955 次。实际组数在对应开发测量关闭后确定。若同骨干对照为冻结模型，两个额外拟合种子均可在完整 605 题上测量。这些是调度上界推演，见 `s4-budget-planning-scenarios.json`。独立采集种子产生的学习曲线评价单列。

每个最终候选在冻结的自然 DEV150 上测试严格固定 R2、固定 R3、512 与 1,024 材料预算，预选实际基线在相同任务上也测两个未训练预算。2,048 锚点从已付完整 TUNE 运行中提取，逐项核验策略、Reader、种子、预算及完整组成员；费用仍归原运行。允许忽略仅用于展示的臂名称；实际 checkpoint 和行为配置须一致。

证据语义交换的正式误差以对应模型训练目标的冻结续跑为准。DQ 与 PQ-U 重用同一个均匀采集目标，PQ-A 单独使用其冻结策略；同一份完整请求的单题返回可以沿用，MuSiQue 在每种新 continuation 下重新取得 companion 后评分。质量与部署净效用分别报告有限动作池遗憾和误停。作为已完成的诊断，已有 pi₀ 36 组在共同尺度 1,912、λ=0.05 下，MuSiQue、QASPER、PersonaMem 各有 1、2、0 组发生严格净效用反转，额外 Reader 调用为 0。

上述 24k 选择、S4 新拟合和正式盲测均依赖真实后续结果。已付的源报表引用见 `natural-tune605-baseline-costs.json` 和 `tune605-matched-curve-subset.json`；独立采集及噪声校准的条件协议见 `MILAI_MEMORY_CONTROL_V13_S4_PROBE_PREREGISTRATION.md`。

## 存储和未完成工作

11 月 25 日 06:06，`/cra` 的物理余量为 57.34 GiB，普通账户可用 7.32 GiB。按实际权重大小、单个拟合进程的临时峰值及 4 GiB 余量估算，seed11 的 12 个 GTE、3 个 QR 正式模型可容纳。若 S4 选入一个学习家族，估计还余 2.16–6.65 GiB。若两个入选家族均需拟合，保守情景的缺口为 0.38–7.16 GiB，取决于共享的 warm 拟合种类与最后的 REF 压缩量。独立采集等条件支出另列。该缺口会在正式选择后按实测文件与当时可用空间复核。[容量推算](/cra/milai-experiments/v13-qrag/storage-projection-20261125.json)

精确复跑 S1 可直接使用冻结的 `gte/evidence.sqlite`。如果从原生数据重建 SQLite，插入顺序可能改变训练遍历。另存的 `gte/frozen-native-root-order.jsonl.gz` 用原生任务标识和已执行动作前缀定位根状态，大小为 1,476,130 字节。在单独的行地址表中反转全部 119,394 个地址后，原训练入口读回的完整监督载荷及 seed11 遍历顺序逐项一致。此验证复用冻结的文本载荷。对独立重建库进行逐行比较的命令及其适用范围见 `MILAI_MEMORY_CONTROL_V13_GTE.md`。

开始执行时持久卷 `/cra` 的普通可用空间为 0，物理剩余约 610 MiB。模型与大型中间件写入位于 `/cra/milai-experiments/v13-qrag/staging` 的专用 36 GiB tmpfs，上限从 24 GiB 调整为 36 GiB，为训练恢复文件原子替换预留空间。该目录目前仅跨进程保留，服务器重启会清空。持久卷后来出现额外物理空间，三套基础权重已保存到实验根的 `models/`，其中 GTE 交互模型、GTE embedding、E5-large 分别可读取 140、138、392 个张量。确认库的持久副本位于 `fresh-sources/native-confirm/memory_control.sqlite3`。复读结果见 `persistent-assets.json`。小型收据、数据角色与日志持续写入持久目录。REF 第 100 次更新时的最佳 actor 保存于 `ref/actor-archives/first-trained-best.zip`，恢复需同一持久目录下的 E5 基础模型。S1 训练路径已绑定到持久目录 `weights/s1`，DQ/PQ 的结果包及正式模型已分别指定持久目录 `collection`、`weights/round-models`。QR 正式训练原始收据与检查点已在首个正式账位前绑定到持久目录 `qr-11/native-receipts` 和 `weights/qr-11`。REF 工作检查点继续使用暂存卷，已发布 actor 的持久副本以及仍在进程内的状态分别记录。QR 48 调用试验模型也已持久化在 `weights/qr-s0/checkpoint-48`，280 个训练张量与原件逐项相等。独立挂载命名空间中隐藏整个 staging 后，`tools/restore_memory_control_v13_paths.py --root "$R"` 重建了所需别名，复读得到 119,394 个训练根状态、S1 第 256 步及全部 QR 试验张量，未调用 Reader。记录见 `restored-controller-paths.log`。完整检查点归档和长期留存仍按实测容量调度。

当前尚待 REF 完整曲线、QR 和各学习臂 6k/12k/24k 的实际学习曲线、冻结数据多种子、按结果触发的额外采样对照，以及最终独立确认。最终模型将在对应的完整开发读出后按预先确定的规则选择。
