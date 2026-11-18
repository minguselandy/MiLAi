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

M1/N0 于 03:39 完成三轮全覆盖、6,066 次真实更新和 776,154 次状态曝光。控制头权重
L2 变化为 51.915，训练和离线 DEV 共用 5,965.20 秒。末轮离线 AP 在 MuSiQue、
QASPER、Persona 上分别为 0.1949、0.1505、0.1150。M1/N1 已沿同一冻结训练路线
从 N1 特征缓存启动。实际覆盖和检查点见 `M1-W-N0-seed11/coverage.json` 和
`M1-W-N0-seed11/checkpoint`。

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
正式 O/P 采用 `same_before_literal_wire_pool_v2`。同一 before state、run 和 repeat 中，
完整请求相同的动作共享已执行结果的质量均值。分支原始评分、请求收据和操作成本仍按动作保存。
用上述 100 对真实 DEV 回复在内存中复放编译器，10 对标量质量差在旧规则下会生成方向监督，
新规则下为 0。此前 3 个 TRAIN 诊断状态的目标和偏好逐项一致。审计见
`outcome-supervision-wire-pooling-audit.json`。
02:54，正式 core 和 P/确认协调器在两者均等待上游、正式分支表为空时重新冻结到
`34b7888d`。交接收据为 `outcome-coordinator-v2-handoff.json`，原等待记录归入
`outcome-orchestration-before-v2`。正式 W 与 DEV 基线继续使用各自的冻结源码。
02:46，B0 到 B4 均已回收首批 100 个任务，共 500 个 Reader 收据。基线选择继续等待
三来源 605 个固定任务的完整矩阵。首批串行 client 实测速率与按规划规模换算的阶段工时
保存在 `reader-phased-throughput-estimate-v1.json`。

已完成 MuSiQue 全部 200 个正式 DEV 任务上的五臂，共 1,000 个 Reader 结果、100 个原生组。
B1 相对 B0 高 20.67 个原生组质量点，配对 95% 区间为 [13.52, 28.42]。B1、B2、B3 的
200 个请求逐项相同，报告单列重复调用波动。另在 PersonaMem 首 100 个任务的 32 个完整
原生组上，94 个任务实现 B0/B1 成对评分，B1 高 6.38 点，区间为 [2.15, 11.58]。
两个来源的实际 Reader input token 分别由 59,898 增至 214,314、由 51,147 增至 128,908。
基线仍按完整 DEV605 选取。收据为 `dev-completed-musiques-200x5.json` 与
`dev-first-persona-pairs-B0-B1.json`。

在这 100 个 MuSiQue 原生对上，B2、B3 相对 B1 的原始分差为 −2.19、+0.49 点。
新增同请求敏感性分析，在完整 Reader 请求相同的任务上，依次把两次实测回复用于两臂，
并按原规则重算 MuSiQue 原生对的充分性门控分。两项分差均为 0。B1 相对 B0 的 +20.67 点
和 B4 相对 B1 的 −4.99 点保持，两个对照的 200 个请求均有实际变化。该结果补充原始计分，
沿用原先冻结的基线选择和确认判据。收据为 `dev-musiques-shared-wire-quality-sensitivity.json`。

PersonaMem 首 200 个登记位置上，B0、B1、B2 各已提交 200 个原生评分。其中 199 个任务
组成 69 个完整原生组。B1 相对 B0 高 6.53 点，95% 区间为 [3.09, 10.33]。
B2 相对 B1 的 200 个请求均有实际变化，配对准确率差为 0.00 点，
区间为 [−3.54, 3.38]，每任务的平均 Reader input token 由 1,410.66 增至 1,961.13。
同一批 Persona 请求上，B3 与 B1 的请求逐项相同。其原始准确率差为 −1.51 点，
复用实测回复后的差为 0。
条件扩读的后续分析优先考察同一 before state 下有实际输入差异的 R2/R3 对，
并保留各预算层的全体抽样结果。收据为
`dev-persona-200-position-read-precision-sensitivity.json`。

Gold 材料诊断 `G` 在正式 B0 到 B4 完成并登记 B* 后，从同一 DEV605 人群发起实际 Reader
请求并独立出具原生质量和成本。协调状态见 `gold-dev-coordinator.json`。

主 DEV 的 B0 到 B4 在共享 Reader 租约下分块提交。605 个任务的正式结果、B* 选择、
24,000 个 core 状态上的正式 O、12,000 个策略到达状态上的 P、参数匹配和三种子确认继续
由各自的实际训练、评分与请求收据证明。已入库的 12 个同状态诊断分支和 16 个策略到达
诊断分支用于验证执行闭环和训练消费。
03:44 已回收 2,100 个正式 DEV 位置的终态收据，B0 为 500 个，B1 到 B4 各 400 个。
首次 3,000 状态的抽样在 Reader 派发前冻结。MuSiQue／QASPER／Persona 数量为
2,000／625／375，覆盖 2,964 个任务和 2,689 个原生组。分层得到 1,200 个代表性样本、
375 个可行 R2/R3 配对样本、600 个停止或预算边界样本、227 个探索样本，另有 598 个
按组轮转回补的样本。模型推荐与真实分支仍由 seed 11 的 W 检查点和后续执行产生。
创新方向优先检验紧预算下的条件扩读收益，并同时对照停止策略和 Reader 利用率。

正式 core sampler 已通过 8 批只读核验。24,000 个不同 TRAIN 状态按上述三来源依次为
16,000／5,000／3,000，覆盖 11,385／888／65 个原生组。3,000 个状态进入精度层，
4,798 个状态因其余分层容量不足回补到随机轮转。41 个状态的记录菜单没有可行 READ，
仍保留原样。另在其中 119 个分层选取的 QASPER／PersonaMem 原生组各真实重放一对
R2/R3，固定续程后 104 对请求不同、15 对汇合到同一请求。该回放只准备请求。
详见 `core-sampling-24000-native-audit.json` 和 `core-focus-context-wire-contrast-audit.json`。

用三个来源各 12 个真实 TRAIN 状态验证本地分支并行准备。固定 72 条分支的本地准备从
79.75 秒降至 25.42 秒。再用两个已训练的 W 检查点，在一次性 SQLite 副本上分别运行
冻结串行入口和四进程入口。两次各生成 180 条真实准备分支，含 4 个重复状态。
除各自实测用时外，运行声明、写入顺序、动作、种子、材料、Reader 请求和可行性逐项一致。
入口墙时从 150.75 秒降至 56.03 秒，两次均未发起 Reader 请求。正式 core 和 P 的
准备入口采用四个 CPU 进程，模型推荐、采样和 SQLite 写入仍由主进程按顺序完成。
该加速测量覆盖分支准备。收据为 `branch-preparation-cpu-parallel-benchmark-v1.json` 和
`branch-preparation-cli-validation-v1.json`。
03:37 核对两条等待协调器及实际数据库后，将 core 和 P 冻结到 `4e3bb0c7`。
交接收据为 `outcome-coordinator-v3-handoff.json`，其中记录新进程及正式分支登记为空。

4 个真正由策略到达的 TRAIN 诊断状态上的 16 个分支已经全部执行并评分。Reader
计量为 15,611 input token、742 output token。随后从已有 O 检查点初始化，
在 4 个状态上完成 1 次实际参数更新，控制头 L2 变化 0.007288。宽 M0 W 和该诊断更新的
本地计算已在原台账各结算一次。这些收据分别见
`policy-closure-actual-reader-and-supervision-audit.json`、`policy-closure-M0-fit-v2/run.json`
和 `wide-and-policy-diagnostic-compute-settlement.json`。

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

运行根中的 `launch-W-seed11.sh`、`launch-dev-baselines.sh`、`launch-core-and-O.py`、
`launch-WO-dev.py` 和 `launch-G-dev.py` 保存正式调用参数。Core 协调器核对两臂 W
的完整覆盖、检查点和相同数据顺序后开始采集。运行状态由实际进程和收据确认。Reader
使用原共享台账，局部计算成本可在各段关闭后从对应收据核对。
