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
以真实策略轨迹去重，目标为 12,000 个 TRAIN 状态。P 每轮覆盖两池的全部可训练状态，
仅在较小的池内补充真实状态的重复曝光，使 core 和 P 各占一半。收据记录真实曝光和
重复次数。另从固定 605 个 DEV 任务登记各自唯一的冷 SEARCH 状态，真实 Reader 结果供
O/P 各轮检查点评分。该 outcome 角色与 TRAIN loaders 隔离。seed 11 的 O-scratch、
未训练头、宽 M0、固定停止与固定精度对照完成后冻结配方，再用同一训练公共池执行
seed 29/47。三个 seed 都有实际检查点后才登记最终确认组和 22 个比较臂。该流程的
实际执行状态记录在 `v11-followthrough.json`。

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
