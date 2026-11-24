# MiLAi V13 Q-RAG 执行记录

开发分支为 `feat/memory-control-v13-qrag-20261125`，从 V12 review 版本 `7bb27c12` 建立。计划原件位于 `jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_MEMORY_CONTROL_V13_QRAG_TRAINING_PLAN_20261125.md`。以下路径相对 V13 工作树的 `MiLAi-Lab`。运行产物位于 `/cra/milai-experiments/v13-qrag`。SHA 校验已禁用。

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

S1 已在 GPU 3 启动。正式数据包含 119,394 个合格根状态，MuSiQue 110,133 个，QASPER 5,351 个，PersonaMem 3,910 个。所有根状态遍历一轮，共 3,732 次更新。首个正式更新检测到第 0 层注意力参数改变，逐更新曲线见 `gte/s1/curve.jsonl`。S1 的完整训练输入已固化为持久卷上的 `gte/evidence.sqlite`，复读确认覆盖两个准备阶段和全部 119,394 个根状态。初始分组排序的全轮检查发现，连续 71,516 个根状态没有 QASPER，连续 78,612 个没有 PersonaMem。该次拟合在 77 次更新、2,464 个根状态后退役，544.58 秒拟合开销计入 `gte/s1-initial-allocation/`。正式运行从相同预训练权重重新开始，按遍历窗口分散原生组，保留每条样本的一次曝光和来源权重。修正后两个最长间隔分别为 291 和 275。

QR 的实时终局 PQN 诊断已完成 48 次实付 Reader 调用，其中包含 18 次 companion。30 条主轨迹均获得原生质量和未来成本，双塔均有可测参数变化，4 次 GPU 优化更新完成，检查点重载可对实际候选菜单评分。计量见 `qr-s0/verified-48.json`。

B1 早期测量和 GTE 校准测量分别来自两批预先指定的任务。两者分别消耗 181,788/7,816 和 114,127/5,123 个 Reader 输入/输出 tokens。计入策略加载摊销后的端到端 p50/p95 分别为 1.09/1.70 秒和 1.58/2.36 秒。不同任务构成限制了横向解释。原生 GTE 初次校准使用对象 microbatch 2，正式校准统一显式登记为 8，两个设置的请求全部计入开发开销。原始成本表见 `initial-readout-costs.json`。99 题 B1 四读校准累计占用 Reader 租约 126.61 秒，实测 0.78 次/秒。冻结 GTE 两读、R2、对象批次 8 的 99 题轮次为 141.18 秒、0.70 次/秒。这些数值包括窗口内预处理和策略加载，未计入等待其他运行释放租约的时间。较新运行另记 vLLM RUNNING 阶段耗时，仅接纳已完成请求数及输入/输出 token 均与同窗口原始收据相符的增量。正式矩阵、同骨干提升、反馈效率与工程节省均需等对应检查点和同组在线读出。结果允许简化到 Direct-Q 或规则策略。

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

完整表和区间见 `natural-tune605-baseline-costs.json`、`natural-tune605-frozen_gte-vs-rule.json`。150 题部署成本图和延迟图已生成于 `figures-dev150-baselines/`，后续 6k/12k/24k 图在同组图上标注这些冻结基线。

逐题重放还比较了完整证据集合的可达性。表中计数为在给定数量的 BM25 候选上，用全部合法 R2/R3 跨度的并集覆盖某一个完整标注集合的题数。这是施加材料预算与操作数限制前的上界。八候选一列已与 150 条实际 G 运行的逐题覆盖标记核对。其余两列只做离线检索诊断。

| 来源 | 有完整标注的题 | 前 8 | 前 16 | 前 32 | G 实际交付完整集合后原生质量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| MuSiQue | 25 | 10 | 15 | 25 | 31.01 分，10 对 |
| QASPER | 39 | 27 | 34 | 37 | 50.02 分，27 题 |
| PersonaMem | 48 | 8 | 10 | 20 | 50.00 分，8 题 |

在 48 道具备完整标注的 PersonaMem 题中，40 道的证据在八候选时不可达。QASPER 在八候选时有 27 道可达，B1 实际交付了其中 12 道的完整集合，冻结 GTE 交付了 8 道。由此可以分开考察召回缺口、控制器选择及给定已交付证据后的 Reader 表现。后续同骨干和采样主表沿用共同的八候选设置。重放产物见 `natural-dev150-reachability.json`。

## 采集、计量与复现

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

核心反馈矩阵使用 `configs/memory_control_v13/feedback.json`。共同的 2,000 次 warm 反馈已闭合。12k 调度等待 S1 及原版参照阶段完成。调度完成后会先产出 6k，再产出 12k。同一固定池内 PQ-U 与 PQ-A 分别选择包，两臂从相同 warm 配对参数开始，DQ 在每轮重用 PQ-U 包。在新目标轮次继续训练上一轮参数。曲线表读取真实采集收据、拟合父链与同一批 DEV 完整运行记录。

```bash
CUDA_VISIBLE_DEVICES=3 "$P" tools/run_memory_control_v13_rounds.py --config configs/memory_control_v13/feedback.json --root "$R" --weights "$R/staging/round-models" --s1 "$R/staging/gte/s1/checkpoint" --curve "$R/rosters/curve-2048.json" --until 12000
```

这条命令依赖 S1 完成与 warm 达到额度。日志 `main-12k-scheduler.log` 记录了本次调度。12k 后续作业已绑定实际运行中的 QR 与配对训练前置进程。见 `tools/settle_memory_control_v13_round.py`。在四种方法都取得相同自然 DEV 组的 6k/12k 结果后，按组计算配对差异并记录实际候选动作之间的实测收益差和费用，接续第二次冻结策略更新到 24k。随后生成五组曲线图，并在同一个 CALIBRATION 上对四个 24k 控制器使用相同的五点 λ 网格，选择后各自读出 TUNE。该续作业尚未开始追加 Reader 调用。

冻结数据拟合可通过 `--frozen-data --fit-seed` 复用同一采集历史，`--refit-method` 只拟合最终选入比较的家族，`--refit-only` 保留各轮参数更新，把 Reader 调用留给指定的正式评估。独立采集种子的费用和拟合种子分开结算。

## 存储和未完成工作

开始执行时持久卷 `/cra` 的普通可用空间为 0，物理剩余约 610 MiB。模型与大型中间件写入位于 `/cra/milai-experiments/v13-qrag/staging` 的专用 36 GiB tmpfs，上限从 24 GiB 调整为 36 GiB，为训练恢复文件原子替换预留空间。该目录目前仅跨进程保留，服务器重启会清空。持久卷后来出现额外物理空间，三套基础权重已保存到实验根的 `models/`，其中 GTE 交互模型、GTE embedding、E5-large 分别可读取 140、138、392 个张量。确认库的持久副本位于 `fresh-sources/native-confirm/memory_control.sqlite3`。复读结果见 `persistent-assets.json`。小型收据、数据角色与日志持续写入持久目录。REF 第 100 次更新时的最佳 actor 保存于 `ref/actor-archives/first-trained-best.zip`，恢复需同一持久目录下的 E5 基础模型。S1 训练路径已绑定到持久目录 `weights/s1`，DQ/PQ 的结果包及正式模型已分别指定持久目录 `collection`、`weights/round-models`。QR 正式训练原始收据与检查点已在首个正式账位前绑定到持久目录 `qr-11/native-receipts` 和 `weights/qr-11`。REF 工作检查点继续使用暂存卷，已发布 actor 的持久副本以及仍在进程内的状态分别记录。QR 48 调用试验模型也已持久化在 `weights/qr-s0/checkpoint-48`，280 个训练张量与原件逐项相等。独立挂载命名空间中隐藏整个 staging 后，`tools/restore_memory_control_v13_paths.py --root "$R"` 重建了所需别名，复读得到 119,394 个训练根状态、S1 第 256 步及全部 QR 试验张量，未调用 Reader。记录见 `restored-controller-paths.log`。完整检查点归档和长期留存仍按实测容量调度。

当前尚待完成正式 S1、REF 完整曲线、QR 和各配对臂 6k/12k/24k 学习曲线、冻结数据多种子、按结果触发的额外采样对照，以及最终独立确认。现阶段没有据此选择最终模型。
