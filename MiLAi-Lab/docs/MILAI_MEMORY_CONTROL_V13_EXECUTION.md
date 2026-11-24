# MiLAi V13 Q-RAG 执行记录

开发分支为 `feat/memory-control-v13-qrag-20261125`，从 V12 review 版本 `7bb27c12` 建立。计划原件位于 `jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_MEMORY_CONTROL_V13_QRAG_TRAINING_PLAN_20261125.md`。以下路径相对 V13 工作树的 `MiLAi-Lab`。运行产物位于 `/cra/milai-experiments/v13-qrag`。SHA 校验已禁用。

## 数据角色与暴露

通过 V1 SQLite 逐行解码弱标签得到 206,657 个状态，其中 198,079 个至少有一个已知动作标签。17,089 个排除任务继续生效。运行器用 V1.2 的继承组注册、固定 Reader 选项及合法预览。当前 TRAIN 共 43,901 题，区别于 V1 在划分实验角色前的 43,929 题。

| 来源 | V1 clean train 题 | V13 TRAIN 题 | V13 TRAIN 原生组 |
| --- | ---: | ---: | ---: |
| MuSiQue-Full | 39,876 | 39,848 | 19,924 |
| QASPER | 2,593 | 2,593 | 888 |
| PersonaMem-v2 | 1,460 | 1,460 | 65 |

库存、组级角色和排除数见 `inventory/inventory.json` 与 `inventory/native-groups.tsv.gz`。沿用 605 题、222 组的 DEV 作为 TUNE。在这批组内固定 150 题、54 组，用于反馈学习曲线。在其余 DEV 组中预先抽取 99 题、39 组用于 CALIBRATION。每个来源独立按完整原生组选取。512、1,024、2,048 三档预算使用相同任务和 Reader 种子。

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
| 原版参考 | 单独使用 MuSiQue-Ans、双 E5-large、原版支持事实奖励与 PQN。TUNE 参考曲线起点的平均 GT 回报 0.287 | `ref/official-musique-tune300-seed42/` |
| 回归 | 带 PyTorch 的环境执行记忆控制及新增针对性测试，当前 79 项通过 | `v13-regression-current.log` |

S1 已在 GPU 3 启动。正式数据包含 119,394 个合格根状态，MuSiQue 110,133 个，QASPER 5,351 个，PersonaMem 3,910 个。所有根状态遍历一轮，共 3,732 次更新。首个正式更新检测到第 0 层注意力参数改变，逐更新曲线见 `gte/s1/curve.jsonl`。S1 的完整训练输入已固化为持久卷上的 `gte/evidence.sqlite`，复读确认覆盖两个准备阶段和全部 119,394 个根状态。初始分组排序的全轮检查发现，连续 71,516 个根状态没有 QASPER，连续 78,612 个没有 PersonaMem。该次拟合在 77 次更新、2,464 个根状态后退役，544.58 秒拟合开销计入 `gte/s1-initial-allocation/`。正式运行从相同预训练权重重新开始，按遍历窗口分散原生组，保留每条样本的一次曝光和来源权重。修正后两个最长间隔分别为 291 和 275。

QR 的实时终局 PQN 诊断已完成 48 次实付 Reader 调用，其中包含 18 次 companion。30 条主轨迹均获得原生质量和未来成本，双塔均有可测参数变化，4 次 GPU 优化更新完成，检查点重载可对实际候选菜单评分。计量见 `qr-s0/verified-48.json`。

B1 早期测量和 GTE 校准测量分别来自两批预先指定的任务。两者分别消耗 181,788/7,816 和 114,127/5,123 个 Reader 输入/输出 tokens。计入策略加载摊销后的端到端 p50/p95 分别为 1.09/1.70 秒和 1.58/2.36 秒。不同任务构成限制了横向解释。原生 GTE 初次校准使用对象 microbatch 2，正式校准统一显式登记为 8，两个设置的请求全部计入开发开销。原始成本表见 `initial-readout-costs.json`。99 题 B1 四读校准累计占用 Reader 租约 126.61 秒，实测 0.78 次/秒。冻结 GTE 两读、R2、对象批次 8 的 99 题轮次为 141.18 秒、0.70 次/秒。这些数值包括窗口内预处理和策略加载，未计入等待其他运行释放租约的时间。较新运行另记 vLLM RUNNING 阶段耗时，仅接纳已完成请求数及输入/输出 token 均与同窗口原始收据相符的增量。正式矩阵、同骨干提升、反馈效率与工程节省均需等对应检查点和同组在线读出。结果允许简化到 Direct-Q 或规则策略。

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
"$P" -m milai_lab.runners.control_policy_iteration --output "$R/warm-11" --calls 2000
"$P" tools/report_memory_control_v13_feedback.py "$R/warm-11" --out "$R/warm-progress.json"
CUDA_VISIBLE_DEVICES=3 "$P" tools/calibrate_memory_control_v13_baselines.py --root "$R" --backbone "$R/staging/gte/base" --family gte
"$P" tools/calibrate_memory_control_v13_baselines.py --root "$R" --backbone "$R/staging/gte/base" --family rule --device cpu
"$P" tools/diagnose_memory_control_v13_evidence.py --output "$R/evidence-diagnostic" collect --data "$D" --population "$R/rosters/curve-2048.json"
```

完整分支从已执行的公共 SEARCH 开始，在最多六次操作、统一检索 32 个对象并保留前八个的条件下决策。每次终止登记真实 Reader 回包。MuSiQue 使用同一冻结策略独立运行另一成员，再用原生 pair 门控得分。训练未知质量保留 mask，调用账目包括 companion、重试和付费失败。

反馈组包的 Q、未来成本与预定义动作比较保存在 `packs/`。对应真实反馈放在 `receipts/`，沿用共享 Reader 账本。报告对费用未知的回包单独计数。实际 Reader 输入、输出、控制器 GPU 毫秒、检索预处理及端到端 p50/p95 分项报告。端到端 GPU 服务成本需要能归属到本次调用的服务器计量数据。

REF 与 GTE 的资源调整及具体训练命令分别见 `MILAI_MEMORY_CONTROL_V13_QRAG_REFERENCE.md` 和 `MILAI_MEMORY_CONTROL_V13_GTE.md`。服务器使用物理 GPU 2 训练 REF，GPU 3 训练项目控制器，GPU 0、1 提供既有冻结 Reader。

核心反馈矩阵使用 `configs/memory_control_v13/feedback.json`。当前 12k 调度已启动，等待完整的 2,000 次共同 warm 反馈和 S1 最终检查点。调度完成后会先产出 6k，再产出 12k。同一固定池内 PQ-U 与 PQ-A 分别选择包，两臂从相同 warm 配对参数开始，DQ 在每轮重用 PQ-U 包。在新目标轮次继续训练上一轮参数。曲线表读取真实采集收据、拟合父链与同一批 DEV 完整运行记录。

```bash
CUDA_VISIBLE_DEVICES=3 "$P" tools/run_memory_control_v13_rounds.py --config configs/memory_control_v13/feedback.json --root "$R" --weights "$R/staging/round-models" --s1 "$R/staging/gte/s1/checkpoint" --curve "$R/rosters/curve-2048.json" --until 12000
```

这条命令依赖 S1 完成与 warm 达到额度。日志 `main-12k-scheduler.log` 记录了本次调度。到达 12k 后用开发结果决定 24k 及独立采集种子；冻结数据拟合可通过 `--frozen-data --fit-seed` 复用已测的同一采集历史。

## 存储和未完成工作

开始执行时持久卷 `/cra` 的普通可用空间为 0，物理剩余约 610 MiB。模型与大型中间件写入位于 `/cra/milai-experiments/v13-qrag/staging` 的专用 36 GiB tmpfs，上限从 24 GiB 调整为 36 GiB，为训练恢复文件原子替换预留空间。该目录目前仅跨进程保留，服务器重启会清空。持久卷后来出现额外物理空间，三套基础权重已保存到实验根的 `models/`，其中 GTE 交互模型、GTE embedding、E5-large 分别可读取 140、138、392 个张量。确认库的持久副本位于 `fresh-sources/native-confirm/memory_control.sqlite3`。复读结果见 `persistent-assets.json`。小型收据、数据角色与日志持续写入持久目录。QR 正式训练的原始转移、部分大型分支采集及模型拟合中间件仍可能位于暂存卷。完整检查点归档和长期留存需要持久容量。

当前尚待完成正式 S1、REF 完整曲线、QR 和各配对臂 6k/12k/24k 学习曲线、冻结数据多种子、按结果触发的额外采样对照，以及最终独立确认。现阶段没有据此选择最终模型。
