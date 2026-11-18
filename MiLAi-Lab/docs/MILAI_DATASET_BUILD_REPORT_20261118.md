# MiLAi 记忆控制数据集 V1 制作报告

`DATA_PREP_COMPLETE`。数据包位于 `/cra/milai-datasets/memory_control_v1`，构建编号为
`20261118T115703Z-3723580`。804 个官方文件共 599,107,610 字节，68,918 条原始任务全部
完成规范化。SQLite 包包含 1,242,483 个对象、2,494,698 个视图、206,657 个决策状态和同数
rollout 作业。198,079 个状态有至少一个已知的读证据辅助标签。
[逐来源计数与就绪状态](/cra/milai-datasets/memory_control_v1/reports/BUILD_REPORT.md)

## 官方数据和训练划分

| 来源 | 官方训练任务 | 官方验证任务 | 派生训练任务 | 派生验证任务 |
|---|---:|---:|---:|---:|
| MuSiQue-Full v1.0 | 39,876 | 4,834 | 39,876 | 4,834 |
| QASPER v0.3 | 2,593 | 1,005 | 2,593 | 1,005 |
| PersonaMem-v2 text 32k | 18,549 | 2,061 | 1,460 | 2,061 |
| 合计 | 61,018 | 7,900 | 43,929 | 7,900 |

- MuSiQue 的 22,355 个原生 pair 均各含两种语料版本。22,355 条不可答样本保有非空的原始
  答案字段，训练侧可答性来自显式布尔值。ZIP 中只流式读取固定的 train/dev 成员。
  [官方归档入口](https://github.com/StonyBrookNLP/musique/blob/922ac98f19a201998dbdae6d7f2887a5258dbdeb/download_data.sh)
- QASPER 保留 4,439 份标注、287 个 No 答案、82 条可答性意见不一致的任务和 174 条只有
  图表证据的任务。后者保留图表引用和 caption-only 视图，文本证据掩码保持未知。
  [官方数据卡](https://huggingface.co/datasets/allenai/qasper)
- PersonaMem 的官方验证 CSV 实读为 2,061 行，固定版本说明的约 2,600 条是作者声明值。
  两个 CSV 共引用 800 份 32k 历史。主设置按结构隔离 800 条生成用 system 消息，另外记录
  1 条源文件缺正文的消息。原始索引到处理后索引的映射和原始历史均保留。
  [固定版本数据卡](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/blob/ed956dea41521fc4499acbc63f966e0fd3c053ba/README.md)
- 官方 PersonaMem 验证集的 735 个 persona 都出现在官方训练集。派生划分保留验证集，
  逐条排除训练侧 17,089 条重叠任务和 51,267 个派生状态。原始划分仍可查询。派生训练和
  验证的原生组交集在三个来源均为零。
  [排除清单](/cra/milai-datasets/memory_control_v1/manifests/clean_train_exclusions.jsonl)

数据许可、作者归属、固定版本和文件字节数登记在来源清单。原始 MuSiQue ZIP、QASPER TGZ、
PersonaMem CSV 与 800 份 JSON 保存在 `raw/`。有歧义或未对齐的证据保留其原始标注和异常
原因。 [来源清单](/cra/milai-datasets/memory_control_v1/manifests/sources.json)
[异常清单](/cra/milai-datasets/memory_control_v1/reports/anomalies.jsonl)

## 产物和训练接口

| 产物 | 用途 |
|---|---|
| `memory_control.sqlite3` | `tasks` 和 `roots` 保存原始位置及拆分，`objects` 保存源正文，`views` 保存可重开的字符区间 |
| `annotations` 和 `weak_labels` | 原生答案、标注及训练掩码以任务或状态连接 |
| `states` 和 `rollout_jobs` | 保存真实前缀、预算、完整动作菜单和复开的视图引用 |
| `action_outcomes` | 实际收益记录表，当前 0 条 |
| `manifests/` 和 `reports/` | 来源、制作配置、异常、隔离、全量验证和真实批次收据 |

段落、章节、对话消息和块按原始边界保留。R2 打开完整原始对象或其明确分页，R3 打开真实
章节页或连续对话块页。2,494,698 个视图包含 1,242,483 种导航预览、1,149,250 个 R2 和
102,965 个扩展页。237,682 个 R2 可绑定到更大区间；6,564 个在分页预算内等价的 R2 未再
生成精度动作。每个视图用现有 Qwen3.6 Reader 和 multilingual-e5-small 编码器的 tokenizer
重算长度。状态预算使用完整 Reader 材料包的实际 token 计数。最后的 Host wire 另外做容量检查。

同一任务的搜索范围限于其原始段落池、论文或精确引用的历史。原始候选全集保存在数据库中，
现有 Unicode BM25 检索选择最多 32 个候选，排序只用可供索引的原文与导航信息。状态通过
`EvidenceOperations` 生成真实 SEARCH、READ 和 HANDOFF 绑定。rollout 还支持共享
搜索前状态，以相同继续策略准备配对的 Reader 请求。初始随机组实测占各派生来源和划分
约 35%，使用源标注选择已读前缀的状态在离线元数据标为 `annotation_seeded`。

训练入口接受 SQLite 路径或数据目录，训练时只读派生 train。每个窗口按数据源和来源组
调度，CPU 复用同根正文，模型按实际对象和动作批次编码。弱证据 loss 只读当前绑定新增的
原生证据标注；可答性和偏好离线保存。Reader、搜索、交接结果与该辅助目标单列。可选预计算
特征状态为 `not_requested`。

## 验证结果

全量核验官方成员、原始身份、正文位置、视图覆盖、状态菜单和掩码通过。八个不同根的真实
样本覆盖 MuSiQue 可答与不可答、QASPER 分页、多标注与图表、PersonaMem 更新、他人偏好与
未知片段。M0 和 M1 分别通过三来源 train/validation 的真实六行批次检查。每批为
282 个合法动作和 102 个填充位置，未知动作的梯度为零，优化器更新为 0。
[验证明细](/cra/milai-datasets/memory_control_v1/reports/validation.json)
[M0 收据](/cra/milai-datasets/memory_control_v1/reports/object_mlp/dataset-dry-run.json)
[M1 收据](/cra/milai-datasets/memory_control_v1/reports/latent_pointer/dataset-dry-run.json)

58 个相关测试、修改模块的 Ruff 和类型检查、Lab 包边界及工具依赖边界检查均通过。
训练调度另读取了 4 个真实窗口，每窗三来源各 4 个状态。旧 QASPER 开发组、QASPER 确认
组和 MuSiQue 保留组以原生身份 metadata 对照，派生训练侧三项交集均为零。
[调度收据](/cra/milai-datasets/memory_control_v1/reports/training-schedule-probe.json)
[历史划分核验](/cra/milai-datasets/memory_control_v1/reports/historical-split-metadata-audit.json)

本地 rollout 探针执行第一绑定并复开真实材料，共准备 10 个分支和对应的 Host 请求。
`executed_outcome_rows=0`，`outcome_training_ready=false`，Reader 调用为 0。
[rollout 探针](/cra/milai-datasets/memory_control_v1/reports/rollout-probe.json)

## 重建与读取

构建和验证使用 `feat/memory-compute-control-20261117` 工作树。完整命令已在以下目录
从已有阶段产物续跑并通过，分阶段命令使用同一配置和数据目录。

```bash
cd /cra/memory/mx_memory/MiLAi-worktrees/memory-compute-control-20261117/MiLAi-Lab
export PYTHONPATH=src
export RAYON_NUM_THREADS=6 OPENBLAS_NUM_THREADS=1
MILAI_V1_PY=/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python
MILAI_V1_DATA=/cra/milai-datasets/memory_control_v1

"$MILAI_V1_PY" tools/build_memory_control_dataset.py --root "$MILAI_V1_DATA" all

"$MILAI_V1_PY" tools/build_memory_control_dataset.py acquire
"$MILAI_V1_PY" tools/build_memory_control_dataset.py normalize
"$MILAI_V1_PY" tools/build_memory_control_dataset.py build
"$MILAI_V1_PY" tools/build_memory_control_dataset.py validate
"$MILAI_V1_PY" tools/build_memory_control_dataset.py probe
"$MILAI_V1_PY" tools/build_memory_control_dataset.py report

"$MILAI_V1_PY" tools/build_memory_control_dataset.py collect-outcomes \
  --state-id 134167 --action read_0 --action context_0 \
  --output "$MILAI_V1_DATA/reports/qasper-same-state-read-pair.json"
```

`probe` 用配置中当前编码器启动两次原生 `tools/run_small_memory_policy.py train --dry-run`。
实际训练沿用该入口并用 `--data "$MILAI_V1_DATA/memory_control.sqlite3"` 选包；动作 loss
仍使用绑定 ID。后续的同状态采集输出包含立即后继和最终状态、实际材料、可提交的既有
Reader 请求以及当前实测的本地成本。Reader 和任务结果字段保留待采集状态。
[制作配置](../configs/datasets/memory_control_v1.json)
[构建入口](../tools/build_memory_control_dataset.py)
[训练入口](../tools/run_small_memory_policy.py)
