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
Reader 任务质量和资源代价。截点时 M1/N0 已接续启动，N1 特征继续生成。

主 DEV 的 B0 到 B4 在共享 Reader 租约下分块提交。605 个任务的正式结果、B* 选择、
24,000 个 core 状态上的正式 O、12,000 个策略到达状态上的 P、参数匹配和三种子确认继续
由各自的实际训练、评分与请求收据证明。当前 12 个分支只用于确认执行闭环和训练消费。
首次 3,000 状态的抽样在 Reader 派发前冻结。MuSiQue／QASPER／Persona 数量为
2,000／625／375，覆盖 2,964 个任务和 2,689 个原生组。分层得到 1,200 个代表性样本、
375 个可行 R2/R3 配对样本、600 个停止或预算边界样本、227 个探索样本，另有 598 个
按组轮转回补的样本。模型推荐与真实分支仍由 seed 11 的 W 检查点和后续执行产生。
创新方向优先检验紧预算下的条件扩读收益，并同时对照停止策略和 Reader 利用率。

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
