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
M1/N0 的 CPU 6,299.58 秒、CUDA 调用段 6,005.23 秒已在原共享台账结算一次。
结算收据为 `M1-W-N0-compute-settlement.json`。

DEV 协调器在等待 B* 时接续到按检查点就绪顺序调度。B* 登记后，M0/N0、M0/N1、M1/N0
可以先用 GPU 2 评估，最后一臂就绪时加入。四臂各完成已注册的 605 个位置后计算 2×2 对照。
已就绪三臂分别在同一批 12 个不同 DEV 原生组上实际重放，均生成 12 个可提交请求。
GPU 2 上的平均本地 episode 耗时依上述顺序为 1.417、1.642、1.526 秒。该测量只包含本地
重放，Reader 请求数为 0。见 `WO-dev-ready-arms-handoff.json` 和 `early-W-DEV-replay.json`。
三臂随后在同一批 100 个 MuSiQue 位置回收实际 Reader 回复，覆盖 50 个完整原生对。
三臂相对 B* 的原生组分差依次为 −3.10、−0.40、−5.04 点。M0/N1 相对 M0/N0 的点估计为
+2.70，分组 95% 区间为 [−7.82, 13.34]。首批实际对照见 `dev-early-W-first-musiques-v1.json`。
三臂随后在全部 200 个 MuSiQue DEV 位置上完成比较，覆盖 100 个完整原生组。
相对 B* 的点估计依次为 −1.72、−5.73、−4.49 点，各区间均跨 0。
M0/N1 相对 M0/N0 的分差为 −4.01 点，95% 区间为 [−10.66, 3.07]；
两臂 Reader input token 均值分别为 1,058.19 和 1,066.27。见
`dev-early-W-MuSiQue-full-stratum-v1.json`。

M1/N1 已完成首轮 2,022 个更新并进入第二轮。首轮离线 DEV 弱证据 AP 按 MuSiQue、
QASPER、Persona 顺序为 0.1953、0.1278、0.0876。原生来源明细见
`M1-W-N1-seed11/dev-epoch-1.json`。
M1/N1 随后完成 6,066 次实际更新和 776,154 次状态曝光，头参数 L2 变化为 63.05。
编码器前向为 0，训练调用耗时 10,956.02 秒，已在原共享台账结算一次。见
`M1-W-N1-seed11/coverage.json` 和 `M1-W-N1-compute-settlement.json`。

seed 11 W 的四臂正式 DEV 各完成 605 个位置。M0/N0、M0/N1、M1/N0、M1/N1 的
三来源等权宏分依次为 27.15、23.38、26.65、24.65。N1 对 M0 的配对差为 −3.77 点，
95% 区间为 [−6.91, −0.41]，对 M1 的差为 −2.00 点，区间为 [−5.37, 1.36]。
关注模型交互的点估计为 +1.77 点，区间为 [−3.08, 6.56]。固定任务分层与资源完整收据为
`dev-weak-2x2-effect.json`。

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

三个带记忆的 DEV 基线 B1、B2、B3 各回收首 500 个位置后，1,500 次调用均有提供方用量。
MuSiQue、QASPER、PersonaMem 的实测 Reader client 吞吐分别为 1.180、1.423、1.911 次/秒。
按正式 core 的来源配额和计划的 105,600 至 132,000 次调用线性换算，Reader client
用时为 22.79 至 28.48 小时。该估算以当前实测速率为条件，量纲只覆盖 Reader client 调用。
分来源 token、延迟和估算假设见 `reader-mixed-source-throughput-v2.json`。

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

QASPER 的首 98 个登记位置已在五臂全部收回，其中 97 个任务组成 24 个完整原生组。
B2 相对 B1 的 F1 差为 +2.52 点，95% 区间为 [−5.13, 9.22]，输入 token 均值从
1,010.00 增至 2,194.21。B4 在这批组上相对 B1 高 9.19 点，区间为 [2.36, 15.94]。
B3 与 B1 的 98 个请求逐项相同，原始分差为 +1.33 点，复用实测回复后为 0。
分组和五臂成本见 `dev-qasper-first-98x5-conditional-read.json`。

Gold 材料诊断 `G` 在正式 B0 到 B4 完成并登记 B* 后，从同一 DEV605 人群发起实际 Reader
请求并独立出具原生质量和成本。协调状态见 `gold-dev-coordinator.json`。
首次调用的冻结 CLI 仅登记 B0 到 B4，G 在参数解析时退出，请求数为 0。已核对后切到
支持 G 的 `500ee850` 冻结入口，首批 100 个位置已收回。原始日志和交接见
`gold-dev-source-correction.json`。
G 随后完成全部 605 个位置。相对 B* 的三来源宏分高 13.65 点，95% 区间为
[9.76, 17.75]，MuSiQue、QASPER、PersonaMem 分别高 24.62、9.90、6.44 点。
分来源质量、实际输入 token 与固定原生配对见 `dev-gold-vs-B-star-v1.json`。

主 DEV 的 B0 到 B4 在共享 Reader 租约下分块提交。605 个任务的正式结果、B* 选择、
24,000 个 core 状态上的正式 O、12,000 个策略到达状态上的 P、参数匹配和三种子确认继续
由各自的实际训练、评分与请求收据证明。已入库的 12 个同状态诊断分支和 16 个策略到达
诊断分支用于验证执行闭环和训练消费。
03:44 已回收 2,100 个正式 DEV 位置的终态收据，B0 为 500 个，B1 到 B4 各 400 个。
04:02，所有臂均至少收回 500 个位置，B0 已收回 600 个，共 2,600 个位置。
04:22，五臂均收齐 605 个位置，共 3,025 个实际终态。公共对照包含 222 个原生组。
B1 以来源等权宏分 26.4602、平均 Reader input 1,162.03 token 冻结为 B*。
完整 DEV 上 B3 和 B1 的 605 个请求逐项相同，原始分差 −0.25 点在复用实测回复后为 0。
B2 相对 B1 增加 49.88% 输入 token，原始分差 −0.74 点，95% 区间为 [−3.24, 1.56]。
复用同请求的实测回复后，B2 的差为 −0.014 点。见 `dev-baseline-selection.json` 和
`dev-baseline-paired-full-v1.json`。
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

正式 core 的 24,000 个已登记状态中，22,162 个已经具备 N1 编码缓存。缓存动作顺序、
向量维数和文件区间逐项对照实际数据。其余 1,838 个状态来自弱监督未知或不可行范围，
分别为 MuSiQue 4 个、QASPER 1,488 个、Persona 346 个。O 可在实际 outcome 封存后
为进入训练的新增状态追加向量。以独立缓存实测，三条已有轨迹的 354,816 字节逐项保持，
追加了因策略实际到达的四个状态，新增状态按根、任务、状态排序。见
`core-24000-frozen-feature-coverage-audit.json` 和 `outcome-feature-append-preflight.json`。

14:14，用原冻结编码器补齐了这 1,838 个状态。原 273,325 条缓存索引逐项一致，10 条旧
向量探针也按字节复核。两路 W 检查点各打开 24,000 个状态，以 18 个实际状态产生 735 个
有限动作评分，编码器前向为 0。对整个登记集合逐项扫描了 520,901,376 个有限 float32
值，并用正式的覆盖调度器核对全名单条件下每轮 188 个窗口。正式 O 的训练集合仍由封存后
实际可用评分确定。见 `core-24000-feature-prewarm/receipt.json` 和同目录的
`full-bank-read-only-schedule-check.json`。

宽 M0 从完整 W/N1 初始化，M1 从 W/N1 第一轮检查点初始化，两者使用封存的
`v11-reader-closure` 真实 outcome 做 O 缓存演练。两臂各覆盖 3 个状态、3 轮，
各完成 3 次 GPU bf16 更新，实际编码器前向均为 0。头参数 L2 变化分别为 0.3532 和
0.3080。每次更新的 value 与 pair 有效状态数为 3 和 1。收据位于
`outcome-cache-rehearsal-M0-wide/run.json` 和 `outcome-cache-rehearsal-M1/run.json`。

在 48 个已登记的真实 TRAIN 状态上，两模型分别在线编码的提案段为 25.43 秒，共 154 次
编码器前向。在线共享编码为 12.56 秒、77 次前向，推荐绑定逐项一致，最大 logit 差
为 2.38e-7。正式 CLI 在独立数据库上用实际 M0/W/N1 和 M1/W/N1 第一轮检查点再复核
24 个状态、104 条分支，两种模式的动作、种子、材料、Reader 请求和写入顺序逐项相同。
两个入口均使用四个正式分支工作进程，端到端用时分别为 40.80 和 37.90 秒。
04:55 将仍在等待上游的 core 和 P 协调器切到 `e3421cd6`，启用在线共享冻结编码器。
新入口逐项比较编码器配置、词表与实际参数张量，并各自运行原有控制头。
收据为 `core-proposal-encoding-pair-benchmark-v1.json`、`shared-proposal-cli-validation-v1.json`
和 `outcome-coordinator-shared-encoder-handoff.json`。

正式 core 的首批 3,000 个状态于 10:16 完成评分并入库，覆盖 2,964 个任务和 2,689 个
原生组。13,964 次实际调用全部计量，其中 55 个格式失败保留在评分收据里。
Reader client 用时 9,720.53 秒，合计 14,583,861 input token 和 857,634 output token。
实际 loader 为全部状态提供 value 监督，1,106 个状态有方向偏好，1,278 个有双成功成本
偏好。205 个同请求组中有 27 组出现原始质量差异，29 个偏好对在重复测量中出现方向冲突。
见 `core-first3000-supervision-and-cost-audit.json`。

在首批实际分支上，QASPER 的 R3 相对 R2 为 +0.25 质量点，原生组 95% 区间为
[−1.21, 1.64]，每个匹配状态的加权平均增加约 370 个 input token。
PersonaMem 的对应差为 −0.33 点，区间 [−2.90, 2.31]，增加约 255 个 token。
配对保留终端请求等同性，沿用固定的后续策略。见 `core-first3000-conditional-read-contrasts.json`。

在独立 SQLite 副本上逐项核对首批 3,000 个状态的入库顺序与已登记抽样，随后封存实际
首批结果并训练增量 O。M0 与 M1 均由各自完整 W/N1 初始化，各完成 3 轮、72 次更新和
9,000 次状态曝光，头参数 L2 变化分别为 2.76 和 2.24。M0 追加了首批仍需的冻结向量，
M1 直接复用实际缓存，编码器前向为 0。两个增量检查点使用从已冻结 DEV605 中按原生组
抽出的 120 个位置进行探索性读出，每来源各 40 个。正式 core 继续累计至 24,000 个状态。
训练收据见 `core-first3000-O-pilot/pilot-execution.json`，读出状态与清单见同目录
`v11-followthrough.json` 和 `dev-probe-population.json`。

core 批次续跑现保存有序状态名单、重复安排和与分支行一起提交的随机游标。
对旧入口的只读复放表明，假设首批已有 437 个状态，重新抽样的 2,563 个余量中有
2,512 个不属于原首批余量。新入口在独立副本上实际准备了 30 个状态。在提交 7 个状态后
终止进程，再从保存游标完成余量，120 条分支的绑定、材料、请求和写入顺序均逐项复现；
提前封存也被拒绝。见 `core-previous-partial-resampling-audit.json` 和
`core-preparation-interruption-rehearsal.json`。
第二批准备完成后，已落盘的 6,000 个状态及抽样来源与登记名单逐项核对。10:55 在原
协调器等待租约且没有执行子进程时交接到新入口。交接点共有 13,964 条入库分支和
13,918 条已准备分支。新协调器从第二批派发环节接续，收据为
`core-durable-batch-handoff.json`。

P 和确认协调器在等待正式 O 时启用 `ecb2be49`。确认入口核对阶段初始化路径、实际优化
步序、覆盖和 checkpoint 配置，并逐项比较锁定的 roster 及 22 个臂文件绑定。
复核使用三个已完成的真 W/N1 检查点，在 DEV605 上往返重建清单并检出同名替换权重路径。
交接和实测见 `followthrough-durable-confirmation-handoff.json` 与
`confirm-literal-prerequisite-rehearsal.json`。

首批 O 的真实检查点副本复现了旧入口续训时丢失 W 初始化路径的问题。修复从原训练收据
恢复 W 路径，在改写任何训练收据前核对恢复文件中的完整训练配方和已提交步序。A100 上用
首批真实 outcome 做 M1 bf16 确定性回放，在第 26 步结束独立训练进程，从第 24 步的
持久检查点恢复到第 28 步。累计 3,512 次状态曝光，续训本次仅计 4 次更新，回滚的
两条旧日志按原字节保留。结果与连续训练的参数张量、优化器、调度器、随机状态和逐步
loss 逐项相同，第 24 步中间检查点也给出相同动作分数。错误的 W 路径在改写收据前被拒绝。
M0 的第 72 步真实恢复文件也可重建最终导出和覆盖，追加优化器更新为 0。见
`warm-outcome-legacy-resume-reproduction.json`、`warm-outcome-interruption-rehearsal.json`
和 `warm-outcome-final-step-reclosure-rehearsal.json`。

仍在等待正式 O 的 P 和确认协调器已启用 `a14ca073`。启动训练前依据进程参数绑定实际
输出目录，已有进程存活时等待其产物，已完成的训练按完整覆盖核对。中断且已有持久
恢复文件的阶段用原配方续训。P 交接实测见 `followthrough-warm-recovery-handoff.json`。
正式 core 随后在 11:27 的空闲租约边界接入同一源码，已提交的 6,000 个状态及其顺序
再次逐项核对。交接点为 13,964 条入库分支、1,800 条已收回 Reader 回复和
12,118 条已准备分支，交接后继续第二批派发。见 `core-warm-recovery-handoff.json`。

11:44 对账核对了正式 core 的 81 个已关闭派发窗口。16,164 条已完成回复均有窗口收据和
服务端 token 计量，共 16,901,850 input token、988,832 output token。该快照含首批
13,964 条入库分支和第二批 2,200 条已完成回复。见 `core-dispatch-accounting-audit.json`。
11:54 对两个已准备批次逐项核对预先登记的采样顺序、TRAIN 角色、预算及分层。每批为
3,000 个不同状态，均有 300 个状态实际准备了重复测量。两批合并后 MuSiQue、QASPER、
PersonaMem 分别覆盖 3,812、803、65 个原生组。PersonaMem 的 65 个组在两批均有任务，
后续分组分析采用原生组身份。见 `core-first6000-realized-roster-audit.json`。
12:25 的下一次对账覆盖 92 个关闭窗口，共 18,364 条服务端计量回复，其中第二批为
4,400 条。累计 19,255,900 input token、1,119,273 output token。见
`core-dispatch-accounting-92-windows.json`。
12:54 对账覆盖 101 个关闭窗口，共 20,164 条收据对应回复。打开的窗口另有 77 条
已完成回复。第二批累计收回 6,277 条。见 `core-dispatch-accounting-101-windows.json`。

第二批派发期间，使用同一冻结入口和两个 W/N1 检查点在独立副本上准备第三批。
对 3,000 个计划状态的派生标签、候选绑定、导航和原文区间逐项比较，涉及 2,954 个
TRAIN 任务、2,690 个原生组。原两批的 27,882 条分支绑定复核一致。12:50，副本已准备
958 个第三批状态。接入入口在独立副本上把 24 个实际状态的 112 条待发分支一次入库，
行内容和顺序逐项相同。改变源对象时拒绝接入，改动最后一条分支的请求种子时整批回滚。
再次运行确认没有重复写入。见 `core-9000-parallel-preparation/status.json`、同目录的
`literal-input-audit.json` 和 `adoption-rehearsal/verification.json`。

12:53 在 core 等待原 Reader 租约且无派发子进程的边界完成协调器交接。边界已有 6,000 个
状态，新进程接续第二批派发。第三批安排在第二批评分后用 `191300c6` 的工具复核与接入。
接入与继续派发沿原登记顺序执行。见
`core-9000-parallel-preparation/formal-boundary-handoff.json`。

13:16，第三批在副本中完成 3,000 个状态、14,004 条待发分支，其中 300 个状态有重复测量。
全量核对了登记顺序、TRAIN 角色和实际 Reader 请求种子。用仍在收件的正式第二批快照
做接入验证时，整批接入在前置评分条件处被拒，副本的分支数量及状态保持一致。第三批准备
用时 2,252.71 秒，与正式第二批派发重叠。见 `core-9000-parallel-preparation/receipt.json`
和同目录的 `full-staged-tranche-audit.json`。
13:20，第二批已收回 7,800 条回复。109 个关闭窗口合计 21,764 条服务端计量回复，见
`core-dispatch-accounting-109-windows.json`。

13:33，滚动准备从第三批已核对的实体副本开始第四批。以登记名单的边界确定每批大小、
状态顺序和来源配额，最多预备正式接入位置之后的两个批次。对第四批的实体 SQLite
副本逐项核对，继承的 41,886 条分支与父副本一致，首 326 个新增状态及 1,504 条待发
分支保持已登记顺序。13:39 在原 Reader 租约的空闲边界交接正式协调器。后续各批均在
上一批评分后按同一入口接入。见 `core-12000-parallel-preparation/live-prefix-audit.json`
和 `core-rolling-integration/formal-boundary-handoff.json`。
`stage-core-ahead.py` 使用 `71f8a98b` 的入口维护准备队列。每个完成的实测准备调用由
`settle-rolling-core-preparation.py` 在原台账单独结算。
13:49，正式 core 的 116 个关闭窗口合计 23,164 条回复，其中 600 条在本次交接后关闭。
当时第二批已收回 9,265 条由提供方计量的回复。见 `core-dispatch-accounting-116-windows.json`。
14:00，第二批已收回 10,073 条回复，第四批副本已准备 2,244 个状态。

14:10，第四批的 3,000 个状态与 14,072 条待发分支全部在副本中准备完成，准备墙时
2,173.16 秒，已在原台账结算。滚动队列等待第三批与第四批按评分边界依次接入。见
`core-12000-parallel-preparation/receipt.json`、同目录的 `compute-settlement.json` 和
`core-staging-coordinator.json`。

14:13 取得正式第二批的独立快照。用正式评分器处理了其中已返回的 11,000 条真实回复，
覆盖 2,372 个第二批状态。保留 MuSiQue 的 35 条格式失败，完成原生计量与评分映射。
原始回复、计量和待发分支逐项保持。提前封存和读取未接入第三批的对照均被拒绝。原弱
缓存缺失的 231 个第二批状态中，184 个已经取得真实可用值监督，其中 90 个有成功见证。
见 `core-second-tranche-shadow-scoring/native-score-audit.json` 和同目录的
`actual-supervision-density.json`、`early-seal-and-future-scope-guard.json`。

在同一快照的第二批内，以同一状态、绑定和重复种子配对。QASPER 有 530 对 R3/R2
两侧均已评分。R3 的平均训练质量差为 −0.15 点，分组 95% 区间 [−2.37, 2.15]，平均
多用 399 个 Reader 输入 token。PersonaMem 有 331 对，质量差为 −3.15 点，区间
[−7.09, 0.49]，平均多用 260 个输入 token。见同目录的
`registered-second-tranche-outcome-contrasts.json`。

全量缓存预备、缓存只读核对、副本原生评分和监督核对已分别在原台账结算。缓存预备
实测墙时 175.90 秒，副本原生评分墙时 13.39 秒。四个范围的新增 Reader 请求均为 0。
见 `core-readiness-compute-settlement.json`。

14:25，正式 core 对账覆盖 129 个关闭窗口，共 25,764 条回复。该快照另有当前窗口的
188 条原始回复已写入待评分队列，第二批累计收回 11,988 条。见
`core-dispatch-accounting-129-windows.json`。

21:11，第三、四、五批已按评分边界接入。正式 core 达到 15,000 个登记状态，前四批
55,958 条分支已评分入库。对三次滚动接入复核了 14,004、14,072、14,045 条实际分支的
动作绑定、随机种子、首步与终端材料以及原始 Reader 请求字段。第五批开始实际派发。
第六批已准备完毕，第七批开始滚动准备。见 `core-15000-formal-admission-audit.json`。

在前四批完整已评分状态上，QASPER 的 2,700 对 R3/R2 配对给出 +0.38 点训练质量差，
分组 95% 区间 [−0.54, 1.30]，平均多用 357.47 个 Reader 输入 token。PersonaMem 的
1,671 对给出 −0.05 点，区间 [−1.51, 1.34]，平均多用 260.87 个输入 token。
21:23 的 286 个关闭窗口合计 56,758 条实际回复。见
`core-first12000-official-outcome-contrasts.json` 和 `core-dispatch-accounting-286-windows.json`。

每轮 O/P 离线验证使用原 DEV 计划下的 605 个冷 SEARCH 状态，覆盖 222 个原生组。
提前直接登记时 SQLite 写锁拒绝了注册。随后在独立副本上用实际 W 检查点生成全部
2,990 条分支，验证原子接入、逐项保持和重复执行的幂等性。真实接入事务用时 3.73 秒，
所有分支处于待发状态。提前启动的 DEV 派发协调器等待完整 core 封存，再使用原 Reader
租约。DEV 结果保持独立角色。见 `dev-outcome-ahead-prepare` 下的 `preparation-receipt.json`、
`adoption-rehearsal.json`、`live-adoption-receipt.json` 和 `deferred-reader-status.json`。

该 DEV 集合补齐了 47 条冻结特征。两路实际 W 头的最高分动作各自与在线编码在 605 个
状态上逐项一致，每路比较了 28,583 个动作评分。双路特征与评分的实测墙时从 87.80 秒
降至 0.57 秒。后续只对已封存且登记一致的 DEV 阶段使用这个缓存。协调器首次接续因缺少
`PYTHONPATH` 退出，补齐归档源码路径后恢复等待上游。准备与缓存对照在原台账分别结算。
见 `dev-outcome-ahead-prepare/feature-cache-receipt.json`、同目录的
`followthrough-cache-handoff.json` 和 `dev-ahead-compute-settlement.json`。

首批增量 O 的 M1 读出在原台账上竞争租约后，独立读出协调器在等待且无执行子进程
时接续。沿用已登记的 120 个位置和原始台账，每轮最多 20 个请求，释放租约后让出一个
主线重试间隔。首个 M1 窗口已收回 20 个位置。见
`core-first3000-O-pilot/windowed-reader-handoff.json` 及同目录的
`windowed-dev-reader-invocations.jsonl`。

M0 随后收齐增量探索读出的 120 个位置，覆盖 43 个原生组。相对自身 W/N1，输入
token 节省 30.31%，分组 95% 区间为 [26.93%, 34.00%]，宏质量差为 −0.16 点，
区间为 [−5.00, 4.96]。相对 B* 的质量差为 −5.49 点，区间为 [−14.35, 2.29]，
输入节省点估计为 6.84%。这组读出用于首批阶段诊断，完整 O 的训练与读出沿正式矩阵进行。
见 `core-first3000-O-pilot/incremental-O-dev/M0-O3000/against-W.json` 和同目录
`against-B-star.json`。

对同一 120 题逐条核对在线读取轨迹。M0 增量 O 在 MuSiQue、QASPER、PersonaMem 的
平均成功读取数分别为 1.30、3.35、1.33，W/N1 对应为 4.00、3.83、4.00。三源的
平均 Reader 输入相对 W/N1 均降低。QASPER 相对 B* 的平均输入从 1,060 增至
1,758 token。该分来源结果与整体节省同时成立。见
`core-first3000-O-pilot/M0-O3000-reading-trajectory-audit.json`。

12:01，M1 收齐同一批 120 个位置，每轮 20 次实际 Reader 请求，共六轮。相对自身 W/N1，
M1 增量 O 的宏质量差为 −6.66 点，分组 95% 区间为 [−13.05, −0.68]。输入 token 节省
6.46%，区间为 [−1.08%, 13.15%]。相对 B*，宏质量低 9.51 点，输入 token 多 26.24%。
在同一批任务上直接配对两个增量 O，M1 相对 M0 的宏质量差为 −4.03 点，区间为
[−12.05, 4.41]，输入 token 多 35.51%，区间为 [22.20%, 52.05%]。见
`core-first3000-O-pilot/incremental-O-dev/M1-O3000/against-W.json`、同目录
`against-B-star.json` 和 `core-first3000-O-pilot/M1-O3000-against-M0-O3000.json`。

M1 相对自身 W/N1 的分差在 MuSiQue、QASPER、PersonaMem 分别为 −7.51、−14.97、
+2.50 点。QASPER 的平均成功读取数从 3.90 增至 5.68，成功 R3 读取从 2.63 降至 1.03，
40 个任务中有 25 个以预算耗尽结束。增量 O 使用学习停止，W 使用固定四次读上限。
它们在这批单种子诊断上同时改变训练阶段和停止方式。见
`core-first3000-O-pilot/M1-O3000-reading-trajectory-audit.json`。

在原 120 个 DEV 任务上，用同一个 M1 增量 O 检查点执行固定停止下的学习精度、固定
R2 和可行即 R3，共准备 360 条真实在线轨迹。开场状态及实际候选菜单与原学习停止臂
逐项相同。每来源抽四个不同原生组的首个状态，移除 HANDOFF 后最佳 READ 绑定均保持，
READ 分数最大绝对差为 1.79e-7。三个固定停止条件在 QASPER 上的平均材料 token 分别
为 1,124、815、1,687。MuSiQue 的三个条件在 40 题上形成逐项相同的终端请求。见
`core-first3000-O-pilot/fixed-control-probe/preparation-receipt.json`。

在先前的完整 DEV 收据上核对了本地执行和 Reader 客户端时间。M1 增量 O 每题的平均值
分别为 2.57 秒和 1.39 秒。对 603 份真实轨迹收据以相同字段重序列化，逐项核对解析值，
各臂字节数减少 36% 至 39%。新版入口在申请原 Reader 租约前持久保存待发请求，释放后评分。
当前 episode 文件沿用相同路径和 JSON 字段，逐次保留待发、派发、已回复和评分状态。见
`static-episode-storage-and-lease-audit.json`。

正式 CLI 在 core 持有原租约时保存了首批 5 个固定停止请求。接续使用相同请求，取得
5 条服务端计量回复并评分，本次新增准备数为 0，Reader 租约用时 5.11 秒。逐项核对
请求、冷启动路径与独立预演。12:22，等待中的 P 和确认协调器接入 `c02af089`。增量
对照的下一窗新增 20 条回复，租约用时 17.07 秒，累计完成 25 个位置。360 条独立预演
和首批 5 个现场请求的本地准备成本在原台账各结算一次。后续窗口轮换三个固定停止臂。见
`core-first3000-O-pilot/fixed-control-probe/first-window-receipt.json`、同目录
`closed-windows.jsonl`、`preparation-compute-settlement.json`、`actual-control-status.json`
和 `followthrough-staged-episode-handoff.json`。

固定停止的三个精度臂均已收齐 MuSiQue 的 40 题、20 个原生对。120 次实际响应使用的
终端请求在同题上逐项相同，三臂 Reader 输入均为 40,583 token。固定 R2 与 R3 的
重复调用在 9 题上出现原生评分字段差异，其中 1 个原生对的聚合分不同。该分层提供相同
请求下的服务波动实测。见
`core-first3000-O-pilot/fixed-control-probe/musique-shared-wire-repeated-reader-audit.json`。

同一增量检查点的四个停止与精度条件也收齐了 PersonaMem 的 40 题、12 个原生组。
固定停止下，R2、学习精度和可行即 R3 的准确率分别为 15.0%、10.0%、27.5%。R3 相对
R2 高 12.50 点，分组 95% 区间为 [2.08, 26.67]，每题平均多 405.30 个实测 Reader 输入
token。学习停止与学习精度得到 15.0%。见
`core-first3000-O-pilot/fixed-control-probe/personamem-complete-fixed-control-stratum.json`。

同一 M1 检查点保留学习精度，单独改为固定停止的完整 120 题对照已收齐。相对学习停止，
宏质量差为 −3.25 点，分组 95% 区间为 [−8.64, 2.01]，Reader 输入节省 6.86%，区间为
[−0.04%, 12.62%]。QASPER 的完整交付从 7 题降至 3 题，停止时一个合法 READ 可补全的情形
由 6 次增至 24 次。见 `core-first3000-O-pilot/fixed-control-probe/completed-stop-only-contrast.json`。

13:20，三个固定停止臂均收齐 120 题。在固定停止下，可行即 R3 相对学习精度的宏质量
高 7.09 点，分组 95% 区间为 [0.85, 13.04]，Reader 输入增加 21.98%。R3 相对 R2 高
5.11 点，区间为 [−0.17, 10.77]，输入增加 33.30%。QASPER 的完整对齐证据交付在
R2、学习精度、R3 三臂分别为 1、3、11 题。将同请求上的测量差归零后，R3 相对学习精度
高 6.78 点，区间为 [0.59, 12.65]。见
`core-first3000-O-pilot/fixed-control-probe/actual-control-status.json` 和同目录的
`complete-fixed-control-native-evidence.json`。

将 QASPER 的实际差异按完整原生标注证据的交付变化分层。相对学习精度，R3 新取得完整
证据的 8 题平均质量高 34.13 点，每题多用 804 个 Reader 输入 token。两臂均未完整
交付的 23 题平均高 1.69 点，新增 527 个输入 token。有 5 题缺少可映射的完整标注，
该层平均质量差为 −26.23 点，新增 656 个输入 token。见
`core-first3000-O-pilot/fixed-control-probe/precision-evidence-and-cost-transitions.json`。

证据诊断从已结束的实际 episode 读取成功 READ、原文区间和已送出的 Reader 请求，再核对
标注集覆盖。开场可达性使用逐个可行 READ 的区间并集。停止机会使用实际 HANDOFF 菜单中
一个合法 READ 的增量。120 题诊断中，QASPER 有 34 题提供完整对齐的文本标注集。
M1 的 W/N1 和增量 O 开场均有 32 题的菜单并集覆盖标注，最终完整交付从 18 题降至
7 题，配对中有 13 题仅 W 完整交付、2 题仅增量 O 完整交付。对应一个合法 READ 可补全的
HANDOFF 分别为 7 和 6 次。见 `core-first3000-O-pilot/dev120-native-evidence-audit.json`。

相同入口核对了完整 DEV605 的五个基线、四个 W 观测条件及单列的 G。PersonaMem 的
187 个有映射片段的任务中，部署臂的开场菜单并集有 86 个可覆盖片段。M0 的 N0 和 N1
完整交付为 22、11 个，M1 为 24、8 个。QASPER 的 G 完整交付标注集 155 次，其中
45 个实际结果训练质量为零。PersonaMem 的 G 完整交付参考片段 86 次，其中 45 个结果
得零分。这一分层保留各来源标注定义和实际评分。见 `dev605-native-evidence-audit.json`
与 `dev605-gold-native-evidence-audit.json`。

未训练预算诊断沿用同一 120 个登记任务、B* 和两个增量 O 检查点。实际训练状态和首批
3,000 个已评分 core 状态只覆盖 1,024、2,048、4,096。1,536 和 3,072 使用真实冷启动
重建候选可行菜单、动作和交付。每个预算以原 2,048 结果配对。同一任务、同一策略臂的
完整请求逐项一致时绑定既有实际回复，改变的请求使用原 Reader 租约。报告单列各回复的
采集来源，并按原生组计算配对区间。见 `core-first3000-O-pilot/held-budget-generalization`
中的 `design.json`、`train-role-and-outcome-budget-audit.json` 和 `paired-scorer-parity.json`。

未训练预算的 720 条轨迹全部准备完成。逐题比较完整请求后，567 个位置可共用同一请求
的回复，其中 563 个绑定 2,048 的回复，4 个绑定另一未训练预算的回复。153 条请求进入
送读，分别为 M0 增量 O 的 51 条、M1 增量 O 的 100 条和 B* 的
2 条。QASPER 的 40 题开场合法菜单逐项相同。M0 的 34 个有完整映射标注的任务中，
1,536、2,048、3,072 的完整交付分别为 10、14、16 题。这些是实际轨迹和材料结果。
逐回复的配对来自随后独立的 Reader 读出。见同运行目录的 `preparation-receipt.json`、
`local-decision-and-evidence-audit.json` 和 `reader-status.json`。

首窗的 20 个 M0、1,536 请求均返回服务端计量结果并完成评分。请求与准备结果逐项相同，
与同题 2,048 请求逐题不同。合计 29,063 input token、1,429 output token，队列接续时
新增模型准备为 0。见同运行目录的 `first-fresh-window-verification.json`。

B* 的 120 题跨预算配对已收齐。1,536 预算改变了两道 PersonaMem 题的请求。两条新
请求均完成原生评分，两题各自的质量与 2,048 参考预算一致，实测输入分别少 44 和
439 token。3,072 的 120 条请求均与参考预算逐项相同，使用同请求的真实回复。见
`complete-baseline-held-budget-readout.json`。

逐题追踪共同读取前缀后的首次分歧。M0 在 QASPER 上各有 25 条轨迹随预算改变。在
1,536 预算下，其中 24 条的首次分歧发生在参考动作已离开合法菜单时。在 3,072 预算下，
24 条的首次分歧来自更高预算才允许的动作。这一核对使用实际冷启动轨迹和完整动作绑定。
见 `first-budget-divergence-audit.json`。

M0 的 1,536 预算完成 120 题配对，其中 26 条新请求、94 条逐项相同的参考请求。相对
2,048，宏质量差为 −2.20 点，分组 95% 区间 [−6.32, 0.26]。Reader 输入节省 11.57%，
区间 [8.02%, 15.34%]。QASPER 平均实际输入由 1,758 降至 1,382 token，四题失去完整
标注证据。见 `complete-paired-arms/M0-O3000-1536.json` 和
`qasper-evidence-quality-M0-O3000-1536.json`。

M0 的 3,072 预算也完成全 120 题配对。相对 2,048，宏质量差为 −1.49 点，分组 95%
区间 [−5.36, 0.86]，Reader 输入增加 16.64%。直接比较两个未训练预算，3,072 相对
1,536 的宏质量高 0.71 点，区间 [−0.25, 2.30]，Reader 输入增加 31.90%，区间
[21.42%, 41.17%]。见 `complete-paired-arms/M0-O3000-3072.json` 和
`M0-direct-3072-versus-1536.json`。

14:00，两个增量模型和 B* 的六个跨预算对照全部完成，各覆盖 120 题和 43 个原生组。
M1 的 1,536 预算相对 2,048 的宏质量差为 −0.84 点，分组 95% 区间 [−5.58, 3.00]，
Reader 输入节省 11.31%。3,072 预算的宏质量差为 +0.32 点，区间 [−4.02, 4.95]，
Reader 输入增加 10.15%。M1 和 M0 的质量预算响应差在两个未训练预算上分别为
+1.36 和 +1.81 点，区间均跨零。见 `readout-report.json` 和 `model-budget-interaction.json`。

153 条新请求均已完成原生评分与提供方计量，合计 322,430 input token、7,072 output
token。逐臂复算结果与完整报告的配对统计逐项相同。563 个相同请求绑定 2,048 的真实回复，
4 个绑定另一未训练预算的真实回复。见 `complete-readout-audit.json`。

第三批 core 与未训练预算重放的本地准备在原台账分别结算一次。计量范围为实际准备的
CPU 时间及 CUDA 分配墙时。见 `third-core-and-held-preparation-settlement.json`。

4 个真正由策略到达的 TRAIN 诊断状态上的 16 个分支已经全部执行并评分。Reader
计量为 15,611 input token、742 output token。随后从已有 O 检查点初始化，
在 4 个状态上完成 1 次实际参数更新，控制头 L2 变化 0.007288。宽 M0 W 和该诊断更新的
本地计算已在原台账各结算一次。这些收据分别见
`policy-closure-actual-reader-and-supervision-audit.json`、`policy-closure-M0-fit-v2/run.json`
和 `wide-and-policy-diagnostic-compute-settlement.json`。

条件扩读报告使用已入库的实际分支，按同 before state、重复编号、绑定及种子配对。
同一绑定的重复和同一原生组的多个状态依次取均值。独立原生组支持分组重采样。
报告保留各预算的实际可用配对、原始分支质量、相同终端请求贡献归零的敏感性结果、
重复方向冲突和两侧都由提供方计量的 token 差。已在两次诊断的全部 28 条入库分支上执行。
一个 QASPER R2/R3 对的分支质量差为 +67.35 点，增加 88 个 Reader input token。
一个 PersonaMem 对的分差为 0，增加 190 个 token。这两项各来自一个原生组。
四个 MuSiQue 策略到达状态上有 12 个 READ 与 HANDOFF 配对，等原生组权重的分支质量
差为 −33.33 点。收据为 `v11-reader-closure-conditional-read-contrasts.json` 和
`v11-policy-closure-conditional-read-contrasts.json`。

后续协调器以已结束的 seed 11 O 训练和整任务 DEV 结果为依赖。公共 P 池按来源轮转原生组，
以真实策略轨迹去重，目标为 12,000 个 TRAIN 状态。

枚举 43,901 个合格 TRAIN 任务时，旧全局策略轮转与来源权重的周期叠加，导致 1,460 个
PersonaMem 任务中规则策略分配为 0。新的 P 采集入口在各来源内部轮转 M0、M1、规则和随机策略，
完整名单为 PersonaMem 分配 146 个规则和 146 个随机策略任务。任务及原生组顺序逐项保持一致。
用增量 O 的实际检查点在独立副本上执行相同的 120 个 TRAIN 任务，分别于第 60 个任务续跑。
旧轮转收集 326 个去重状态，取其中前 24 个准备 119 个分支。新轮转收集 332 个去重状态，
取前 24 个准备 117 个分支，三个来源均运行了四种策略。按 M0、M1、规则、随机顺序，
尝试任务数为 48、48、13、11，去重后状态数为 86、140、48、58。另用旧入口登记并执行
一个真实任务，再由新入口续跑，核对原全局轮转和登记配置。以上预演共发起 0 次 Reader
请求。见
`policy-arrival-preflight/preflight-receipt.json`、
`policy-arrival-by-source-preflight/train-task-roster-audit.json` 和同目录 `preflight-receipt.json`。

P 每轮覆盖两池的全部可训练状态，仅在较小的池内补充真实状态的重复曝光，使 core 和 P
各占一半。对独立副本中 8 个已评分 core 状态与 4 个已评分策略到达状态，从实际增量 O
检查点完成 3 次优化更新。两池各实际曝光 24 次，重复曝光分别为 16 和 20 次。见
`policy-mixed-exposure-rehearsal/rehearsal-receipt.json`。11:51 核对正式 P 与冷 DEV 分支登记
为空后，等待中的 P 和确认协调器启用 `4a5a1475`。core 在原进程中继续派发。见
`followthrough-source-policy-rotation-handoff.json`。

另从固定 605 个 DEV 任务登记各自唯一的冷 SEARCH 状态，真实 Reader 结果供
O/P 各轮检查点评分。该 outcome 角色与 TRAIN loaders 隔离。seed 11 的 O-scratch、
未训练头、宽 M0、固定停止与固定精度对照完成后冻结配方，再用同一训练公共池执行
seed 29/47。三个 seed 都有实际检查点后才登记最终确认组和 22 个比较臂。该流程的
实际执行状态记录在 `v11-followthrough.json`。

以冻结 B* 通过实际确认组分配器只读核对名额。1,500 个位置包含 MuSiQue 650 题／325 组、
QASPER 266 题／75 组、PersonaMem 584 题／220 组，保留了每个入选组的全体任务。
按 22 个臂计算为 33,000 个计划位置。这次核对只访问角色和原生组元数据。见
`v11-confirm-roster-capacity-audit.json`。

## 外部静态转移评估

LongMemEval S 的 500 题与历史评估暴露清单逐项核对。原始会话 ID 的重叠关系把它们连成
一个历史组。本轮将该来源用于已暴露的外部回归。适配器复用原会话排序、角色、字面区间
和实际日期，用相同的 R2/R3、可行性与 Reader 交付入口运行。读取公开会话时仅取原始文本、
角色和日期。一个真实问题的离线答案、答案会话和 `has_answer` 变更后，公开历史和最终
Reader 请求逐项复现。评分在 Reader 结果封存后使用项目原 Reader 部署的模型执行 LongMemEval
题型判分规则。回归身份来自 `data/manifests/jev-longmemeval-exposure-final-v1-20261017.json`。

MemoryAgentBench 使用官方 Accurate Retrieval 发布中 `eventqa_full` 的全部五个原始
上下文和 500 个问题位置。同名题号在不同上下文重复，运行按发布行号和原生题号共同绑定。
读取时使用发布的原始文本、实际换行和题目自带选项，沿用普通检索及区间交付。
适配协议评估已形成的静态来源上的选读能力。EventQA 从 Reader 的结构化答复取答案文本，
按官方归一化的子串精确匹配计分，并按五个上下文报告。发布身份为
`7ea066982b140a19337e17e60d45d4076e042faf`。
[发布数据](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/tree/7ea066982b140a19337e17e60d45d4076e042faf)
[官方评分定义](https://github.com/HUST-AI-HYZ/MemoryAgentBench/blob/main/utils/eval_other_utils.py)。

| 来源 | 登记位置 | 原生上下文组 | 完整材料 token 范围 | 完整材料超预算 | 实测完整 Host 请求超限 |
|---|---:|---:|---:|---:|---:|
| LongMemEval S | 500 | 1 | 133,732–152,150 | 500/500 | 500/500 |
| EventQA 全文版 | 500 | 5 | 693,761–1,440,826 | 500/500 | 5/5，每个上下文一题 |

材料预算为 2,048 token，容量核验覆盖登记队列，并保留所有超限位置的实际计数。
B1 和 M0/W/N1 的匹配诊断均完成请求准备。LongMemEval 每个原生题型取最前两个位置，
共 12 题每臂。EventQA 每个上下文取最前两个位置，共 10 题每臂，20 个真实 Reader 请求均
已回收。外部运行使用原共享台账，容量、匹配准备和运行状态见运行根的 `external`。
Reader 执行源码冻结为 `03171d94`。

EventQA 匹配诊断中，B1 与 M0/W/N1 分别命中 7/10 和 5/10，Reader 输入 token 分别为
13,799 和 23,780。所有调用均有提供方用量，20 个回复通过结构化解析。十个任务的
两臂请求均有实际差异。逐上下文得分和成本见 `external/eventqa-pilot-matched.json`。

LongMemEval 两臂各有 12 个实际回答和判分，B1 与 M0/W/N1 各答对 4 个。Reader 输入 token
分别为 16,790 和 25,911，判分输入 token 分别为 2,267 和 2,127。两臂的 24 次判分在
同一次原共享台账租约内完成，写入原定输出路径。实际外部诊断的 44 个回答与 24 个判分、
EventQA 的固定文本评分均已收齐。配对分层和成本见 `external/longmemeval-pilot-matched.json`，
原租约结算与终态见 `external/longmemeval-single-lease.json` 和 `external/pilot-coordinator.json`。

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
"$MILAI_PY" tools/report_memory_control_outcome_contrasts.py --data "$MILAI_DB" \
  --run-id v11-reader-closure --output "$MILAI_RUN/v11-reader-closure-conditional-read-contrasts.json"
"$MILAI_PY" tools/report_memory_control_outcome_contrasts.py \
  --data /dev/shm/milai-v11-second-core-score-probe/scored/memory_control.sqlite3 \
  --run-id v11-core-shared-seed11 --roster "$MILAI_RUN/core-sampling-24000-native-audit.json" \
  --block 2 --output "$MILAI_RUN/core-second-tranche-shadow-scoring/replay-outcome-contrasts.json"

CUDA_VISIBLE_DEVICES=2 "$MILAI_PY" tools/prepare_memory_control_registered_features.py \
  --data "$MILAI_RUN/dataset/memory_control.sqlite3" \
  --roster "$MILAI_RUN/core-sampling-24000-native-audit.json" \
  --feature-store /dev/shm/milai-v11-features-N1 --output "$MILAI_RUN/core-feature-prewarm-replay" \
  --checkpoint "$MILAI_RUN/M0-W-N1-seed11/checkpoint" \
  --checkpoint "$MILAI_RUN/M1-W-N1-seed11/checkpoint"

MILAI_O_PILOT="$MILAI_RUN/core-first3000-O-pilot"
"$MILAI_PY" tools/report_memory_control_episode_evidence.py --data "$MILAI_DB" \
  --run "$MILAI_O_PILOT/dev-probe-reference/M1-W-N1-seed11-DEV" \
  --run "$MILAI_O_PILOT/incremental-O-dev/M1-O3000" \
  --run "$MILAI_O_PILOT/dev-probe-reference/M0-W-N1-seed11-DEV" \
  --run "$MILAI_O_PILOT/incremental-O-dev/M0-O3000" \
  --run "$MILAI_O_PILOT/dev-probe-reference/dev-main-B1" \
  --output "$MILAI_O_PILOT/dev120-native-evidence-audit.json"
"$MILAI_PY" tools/report_memory_control_budget_transfer.py \
  --root "$MILAI_O_PILOT/held-budget-generalization" \
  --output "$MILAI_O_PILOT/held-budget-generalization/readout-report.json"
```

运行根中的 `launch-W-seed11.sh`、`launch-dev-baselines.sh`、`launch-core-and-O.py`、
`launch-WO-dev.py` 和 `launch-G-dev.py` 保存正式调用参数。Core 协调器核对两臂 W
的完整覆盖、检查点和相同数据顺序后开始采集。运行状态由实际进程和收据确认。Reader
使用原共享台账，局部计算成本可在各段关闭后从对应收据核对。

外部运行根中的 `external/launch-external-v11-pilots.py` 保存两个来源的实际 Reader
和评分调用。以下入口可重建 EventQA 的独立输入、参考和容量记录。

```bash
MILAI_EXT="$MILAI_RUN/external"
MILAI_PARQUET_PY=/data/miniconda3/envs/langgraph/bin/python
"$MILAI_PARQUET_PY" tools/extract_memory_control_eventqa.py \
  --parquet "$MILAI_EXT/memoryagentbench/Accurate_Retrieval-00000-of-00001.parquet" \
  --source-revision 7ea066982b140a19337e17e60d45d4076e042faf \
  --public "$MILAI_EXT/replay/eventqa-public.json" \
  --references "$MILAI_EXT/replay/eventqa-references.json"
"$MILAI_PY" tools/run_memory_control_external.py --data "$MILAI_DB" --source eventqa \
  --input "$MILAI_EXT/replay/eventqa-public.json" \
  --output "$MILAI_EXT/replay/eventqa-full-capacity.json" capacity --workers 3
"$MILAI_PY" tools/run_memory_control_external.py --data "$MILAI_DB" --source longmemeval \
  --input /cra/memory/mx_memory/benchmarks/LongMemEval/data/longmemeval_s_cleaned.json \
  --exposure data/manifests/jev-longmemeval-exposure-final-v1-20261017.json \
  --output "$MILAI_EXT/replay/longmemeval-capacity.json" capacity --workers 4
```
