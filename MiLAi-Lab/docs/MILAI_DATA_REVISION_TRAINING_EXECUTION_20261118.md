# MiLAi V1.1 数据修订和训练执行记录

实验从计划指定的 `dead0383` 开始。工作树位于
`/var/tmp/milai-memory-control-v11-20261118`，分支为
`feat/memory-control-v11-20261118`。V1 保留在 `/cra/milai-datasets/memory_control_v1`。
V1.1 的公开工作路径为 `/cra/milai-datasets/memory_control_v1_1`，实际存储在
`/data/milai-experiments/20261118-memory-control-v11/dataset`。这里使用路径、原生组、
发布版本、提交和运行编号登记来源。SHA、校验和及替代内容指纹的校验关闭。

## 数据和交付

| 来源 | TRAIN 任务 | 独立 TRAIN 组 | 修订 TRAIN 状态 | 至少一个可行已知 READ 的状态 |
|---|---:|---:|---:|---:|
| MuSiQue-Full | 39,848 | 19,924 | 239,086 | 239,029 |
| QASPER | 2,593 | 888 | 15,543 | 11,925 |
| PersonaMem-v2 | 1,460 | 65 | 8,760 | 7,764 |
| 合计 | 43,901 | 20,877 | 263,389 | 258,718 |

DEV 另有 15,420 个活动状态。总计 92,942 个 task-budget 组合、278,809 个活动状态。
两个未训练预算档 1,536 和 3,072 另完成 30,834 个 DEV 状态的真实前缀重放。
训练和主 DEV 评分继续使用各自声明的预算范围。
每个活动 TRAIN 任务以 2,048 为参考预算，并按原生组分到 1,024 或 4,096 的实际重放变体。
Persona 保留 V1 排除的 17,089 条任务和 51,267 个旧状态。14 个已注册为历史 DEV 的
MuSiQue 原生组共 28 个旧 train 任务在 V1.1 保持 DEV。保留历史确认组的身份，
新确认分配仅使用其余已知未暴露的 validation 原生组。暴露依据来自已登记的项目清单。

V1 的规范化对象、索引视图、旧状态 ID 和已登记原生身份仍可追踪。V1.1 状态有单独 ID、
父状态映射、任务角色、材料预算和观测协议。可行性与原生证据增益分别存储。
新增活动确认标签等到冻结评价读取。候选完整集指标按候选池可覆盖的原生集合计量，
另有真实预算下单步补全的统计。

- QASPER TRAIN 有 5,391 个弱正 READ 因材料预算无法交付。状态 206693 的真 READ
  返回 `material_budget_exhausted`，交付包保持原值。
- QASPER 状态 206670 的 N1 对象编码实际包含 32 个来源片段。修改离线字段后编码输入相同，
  候选顺序与父状态逐项相同。
- 同一状态依次执行跨候选 read_0 和 context_17，移除 372 个重复字符，实际包为 1,194 token。
  同候选 read_0 到 context_0 的匹配轨迹中，旧包为 1,165 token，V1.1 包为 1,185 token。
  因此区间消重的收益需要按实际序列化轨迹测量。

全量权威数据见 `dataset/reports/revision-supervision.json`，实际重放见
`dataset/reports/revision-validation.json`，原生角色登记见
`dataset/manifests/experiment-groups.json`。生成源码为 `ac52399b`。修订版 Reader 使用
现有 S02 配置解析 Qwen3.6-35B-A3B-FP8 和真实 Host tokenizer，实验读出固定为
temperature 0，最多 512 输出 token，关闭 thinking，显式保留输出容量预留。
选择该解码协议是本次执行的设置。

605 个固定 DEV 任务分别用 B1 和 B2 产生了 1,210 条实际读路径。在 1,173 条两版均可执行
的路径中，V1.1 材料包平均少 28.1 token，本地重放均值由 11.0 升至 23.1 毫秒。
另外 37 条路径在 V1 的交付约束下失败。该批固定策略的原始包没有跨候选区间重叠，
token 减少反映序列化变化。单独选取的 48 条真实重叠路径来自 48 个 DEV 原生组，
原始选读区间平均合并 595 个重复字符，实际序列化包平均少 10.1 token。
详见 `fixed-delivery-comparison-v1.json` 和 `fixed-delivery-overlap-diagnostic.json`。
在 1,536 和 3,072 预算下分别再执行 1,210 条固定路径。V1 分别无法交付 91 条和 2 条
V1.1 路径。QASPER DEV 的超预算弱正 READ 数在 1,536、2,048、3,072 下依次为
1,022、329、35。评估端将用各预算的实际 Reader 结果检验这些可行性差异。

## 已运行的训练与 Reader 诊断

- A100 上的 M1 诊断完成 2 次真实优化更新。第一次更新后保存并退出，另一个进程从恢复点
  完成第二次更新。两次各曝光 8 个状态。
- 同状态 Reader 诊断覆盖 3 个 TRAIN 状态、3 个原生组、12 次真实请求。12 个结果已评分和
  入库。QASPER 的一条 R2 分支 F1 为 0.327，对应 R3 分支为 1.0。两者使用同一 before
  state、Reader、继续策略和种子。另两个状态的所有分支均为 0。
- 另一次 M1 诊断从上述弱监督检查点初始化，实际读取这 12 个 outcome，完成 1 次更新。
  该更新的 value 分母为 3 个状态，pair 分母为 1 个状态。
- M0 从相同 outcome 起步也完成 1 次诊断更新。两臂实际策略在 TRAIN 上运行，
  和规则策略共同提供了 4 个此前未收入公共池的 before states。交付轨迹已逐步重放验证。
- 12 次分支的本地 Host 输入 token 计数与提供方计数逐次一致。提供方合计返回
  12,345 input token 和 440 output token。该批客户端耗时合计 6.89 秒，
  包括计量和交互。正式阶段服务吞吐随共享租约、任务分布及并发变化。
- B0、B1 和第 1 次更新的 M1 中间检查点各完成同一固定 DEV 小样本的 7 个完整任务。
  B0、B1、M1 的来源等权宏分分别为 27.78、22.22、22.22。相对 B1，M1 的平均 Reader
  输入 token 增加 44.3%。这些是小样本开发轨迹，正式效果须使用冻结确认矩阵。
- QASPER 和 MuSiQue 的答分各与锁定版官方实现比较 100 个输入对。MuSiQue 另比较四种
  原生配对可答性取值。最大差均为 0。

诊断收据位于运行根的 `coverage-recovery-M1-v2`、`outcome-closure-M1`、
`dev-closure-*` 及数据库报告目录的 `outcomes/v11-reader-closure`。正式 DEV 固定为
605 个任务，MuSiQue 200、QASPER 203、Persona 202。正式矩阵的决策由实际任务结果和
成本驱动。

## 正式执行状态

已启动两条 seed 11 路线，分别在物理 GPU 2 和 GPU 3 准备冻结特征并执行 M0/M1。
正式弱监督按 258,718 个可训练状态无放回覆盖 3 轮，有效 batch 128，
每臂计划 6,066 个更新。M0 微批为 16，M1 微批为 8，float32 特征按实际序列长度
保存在 `/dev/shm/milai-v11-features-N{0,1}`，训练使用 bf16 与微批内补齐。
该特征目录依赖当前主机的 tmpfs。运行收据和检查点写入持久运行根。
同一批 9 个真实状态的长度分桶探针保持 200,759 个有效编码 token，将 padded token
从 300,672 降至 212,672，最大分差为 2.8e-9。
实测可训练参数为 M0 的 2,165,889、M1 的 10,654,849，以及宽度匹配 M0 的
10,655,649。三个计划种子的覆盖顺序均实际检查过，每轮包含 2,022 批，尾批保留 30 个状态。

截至 11 月 19 日 02:00，`M0-W-N0-seed11` 已完成 3 轮全覆盖和 6,066 次真实更新。
累计曝光 776,154 条状态，控制头权重 L2 变化 32.685，正式训练和离线 DEV 的实测耗时
826.24 秒。N0 缓存一次编码 273,325 个 TRAIN 和 DEV 状态，占 19.32 GB，
准备耗时 4,370.27 秒。各来源的实际离线 DEV 弱证据 AP 如下。

| 来源 | 初始 | 第 1 轮 | 第 2 轮 | 第 3 轮 |
|---|---:|---:|---:|---:|
| MuSiQue-Full | 0.05858 | 0.19937 | 0.19652 | 0.19770 |
| QASPER | 0.09230 | 0.14357 | 0.13921 | 0.13831 |
| PersonaMem-v2 | 0.02489 | 0.09144 | 0.08974 | 0.08812 |

三个来源的离线 AP 在本臂第 1 轮达到最高值，三轮检查点均保留。正式策略评价分别记录
Reader 任务质量和资源代价。M1/N0 已接续启动。02:04，N1 的 273,325 个特征也全部就绪，
其中 33,779 个复用前一段生成的向量，M0/N1 随即进入正式训练。

M0/N1 于 02:18 完成相同的 6,066 次更新和 776,154 次状态曝光。末轮离线 DEV 弱 AP
在 MuSiQue、QASPER、Persona 上分别为 0.1834、0.1257、0.0614。对两个末轮检查点
再次评分，逐条验证 14,607 个 DEV 状态的可行菜单相同。在存在可行正 READ 的状态中，
N1 相对 N0 的来源等权 Top-1 命中差为 −6.32 个百分点，按来源内原生组配对重采样的
95% 区间为 [−7.95, −4.68]。该信号来自一次种子的弱证据排序。真实 Reader 效果和注意力
交互由后续同任务 2×2 对照测量。原始配对结果见 `m0-navigation-weak-paired-result.json`。
冷 SEARCH 后三个来源的 Top-1 差为 −10.11、−7.66、−8.55 点，按上述来源顺序排列。
交换两个冻结 M0 头的输入观测也在这 14,607 个状态上执行。交换后的离线 AP 留在
`m0-weak-cross-*/result.json`，供定位训练观测与推理观测不一致的影响。

宽 M0/N1 已完成三轮、6,066 次更新和 776,154 次状态曝光。M0/N0 末轮头与其初始化头
在固定停止和相同合法候选下，各完成 7 个 DEV 任务和 7 次 Reader 请求。训练头在该小样本
的来源等权宏分高 16.67 点，等权 Reader input token 高 24.2%。质量差全部来自 MuSiQue
的一个完整配对。三个来源各只有一个原生组，这组诊断的分组区间无法体现真实抽样精度。
整任务对照收据见 `dev-closure-W0-U0-N0-comparison.json`。

共享 Reader 于 02:32 开始正式 B0。首批 100 个 MuSiQue 任务全部入账，共 29,834 input
token 和 9,609 output token，调用段墙时 83.08 秒。7 个达到 512 token 截断的首答记为
格式失败。现有台账在这个已结束的调用段记录请求与 token 的上限均为空。三段缓存准备和
两个已结束的正式 M0 训练各结算一次，CPU 合计 15,793.06 秒，CUDA 调用段占用墙时合计
12,716.92 秒。台账回读见 `first-five-compute-settlement.json`。

在正式 DEV 的首 50 个完整 MuSiQue 对上，B0、B1、B2 的原生配对分依次为
0.07、23.69、19.24，累计 input token 分别为 29,834、108,372、108,372。
B1 和 B2 的 100 个请求逐项相同，含种子和解码参数。独立调用时，64 个输出正文不同，
28 个原生评分记录不同。该配对差量化了 Reader 的重复调用波动。后续精度归因也会报告
实际改动 Reader 输入的任务。首批结果和请求等同性分别见
`dev-first-musiques-paired-cost-and-quality.json` 和 `first-musiques-b1-b2-wire-equivalence.json`。
02:46，B0 到 B4 均已回收首批 100 个任务，共 500 个 Reader 收据。基线选择继续等待
三来源 605 个固定任务的完整矩阵。首批串行 client 实测速率与按规划规模换算的阶段工时
保存在 `reader-phased-throughput-estimate-v1.json`。

主 DEV 的 B0 到 B4 在共享 Reader 租约下分块提交。605 个任务的正式结果、B* 选择、
24,000 个 core 状态上的正式 O、12,000 个策略到达状态上的 P、参数匹配和三种子确认继续
由各自的实际训练、评分与请求收据证明。当前 12 个分支只用于确认执行闭环和训练消费。
首次 3,000 状态的抽样在 Reader 派发前冻结。MuSiQue／QASPER／Persona 数量为
2,000／625／375，覆盖 2,964 个任务和 2,689 个原生组。分层得到 1,200 个代表性样本、
375 个可行 R2/R3 配对样本、600 个停止或预算边界样本、227 个探索样本，另有 598 个
按组轮转回补的样本。模型推荐与真实分支仍由 seed 11 的 W 检查点和后续执行产生。
创新方向优先检验紧预算下的条件扩读收益，并同时对照停止策略和 Reader 利用率。

后续协调器以已结束的 seed 11 O 训练和整任务 DEV 结果为依赖。公共 P 池按来源轮转原生组，
以真实策略轨迹去重，目标为 12,000 个 TRAIN 状态。P 每轮覆盖两池的全部可训练状态，
仅在较小的池内补充真实状态的重复曝光，使 core 和 P 各占一半。收据记录真实曝光和
重复次数。另从固定 605 个 DEV 任务登记各自唯一的冷 SEARCH 状态，真实 Reader 结果供
O/P 各轮检查点评分。该 outcome 角色与 TRAIN loaders 隔离。seed 11 的 O-scratch、
未训练头、宽 M0、固定停止与固定精度对照完成后冻结配方，再用同一训练公共池执行
seed 29/47。三个 seed 都有实际检查点后才登记最终确认组和 22 个比较臂。该流程的
实际执行状态记录在 `v11-followthrough.json`。

## 重放入口

在本工作树的 `MiLAi-Lab` 中执行以下命令。源码冻结版目录与运行脚本记录在运行根。

```bash
export PYTHONPATH=src TOKENIZERS_PARALLELISM=false OPENBLAS_NUM_THREADS=1
MILAI_PY=/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python
MILAI_RUN=/data/milai-experiments/20261118-memory-control-v11
MILAI_DB=/cra/milai-datasets/memory_control_v1_1/memory_control.sqlite3
MILAI_CONFIG=configs/datasets/memory_control_v1_1.json

"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" revise \
  --roles "$MILAI_RUN/historical-groups.json"
"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" \
  --state-workers 18 build-observations --budget-scope all
"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" report

"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" prepare-outcomes \
  --run-id v11-reader-closure --state-id 206670 --state-id 206724 --state-id 206838
"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" execute-outcomes \
  --run-id v11-reader-closure --limit 16
"$MILAI_PY" tools/build_memory_control_dataset.py --config "$MILAI_CONFIG" score-outcomes \
  --run-id v11-reader-closure --seal
```

启动脚本 `launch-W-seed11.sh`、`launch-dev-baselines.sh`、`launch-core-and-O.py`
和 `launch-WO-dev.py`
保存正式调用参数。Core 协调器核对两臂 W 的完整覆盖、检查点和相同数据顺序后才开始采集。
运行中的
既有作业由其真实进程和收据确认。Reader 仍使用原共享台账，记录的局部计算成本可在各段
关闭后从对应收据核对。
