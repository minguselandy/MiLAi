# 当前训练情况与发布摘要（2026-10-17）

**训练已完成，尚未证明稳定收益。研究目标当前暂停；本次按用户要求整理并提交已有结果，不启动新实验。** 最新两组各四个标签对照任务均正常结束。没有选用某个有利种子或中间 checkpoint 更新默认模型，也没有部署到线上服务。

## 训练对象与结果

主要训练对象是 Laya 读端决策模型。前期还完成了普通线性 CE、Qwen2.5-0.5B 字母输出/LoRA 等对照。Qwen3.6-35B-A3B-FP8 在 Writer 诊断中提供推理，本轮没有对该 35B 模型进行参数训练。

最新标签对照固定训练 4 epochs、种子 0/1，比较原标签与来源审阅标签。表中为固定最终 epoch 在 **22 个有来源标签的开发状态**上的接受数；该集合仅含 3 个有效家族，且已经用于开发，不能作为独立盲测。

| 实验 | 每臂训练输入 | 初始化 | 种子 0：原→审阅 | 种子 1：原→审阅 | 状态 |
|---|---|---|---:|---:|---|
| 本分支基础权重对照 | 86 状态、17 来源行、9 家族；24 更新/任务 | 原始 multilingual BASE | 9/22→11/22 | 6/22→5/22 | 4/4 正常结束 |
| 同机另一研究分支的暖启动对照，已独立核对 | 55 状态、11 来源行、7 家族；16 更新/任务 | 已有 C20 CE checkpoint | 9/22→11/22 | 10/22→10/22 | 4/4 正常结束 |

两组的数据、初始化和训练配方不同，不能把八个任务合并为可互换的重复实验。基础权重对照中，每个种子的两臂初始开发 logits 完全一致，训练后 encoder/head 参数发生变化；训练损失下降，但最终开发收益方向不一致。暖启动审阅标签模型在两个种子的“缺少互补证据”状态上都只命中 1/8。

暖启动后还检查了 5 个已暴露问题的实际策略与 Reader 输出：30 个逻辑位置对应 17 个首次 Reader 响应、13 次完全相同输入/响应复用。继续训练后的模型仍在导演问题上过早停止，并漏掉 Gyumri 问题的关键材料；没有建立稳定 QA 收益。前期 C20 共同 Reader 对照也未建立质量可比的整体成本收益。

证据：[基础权重训练结果](../data/manifests/jev-reader-source-qualified-label-pair-v1-summary.json)、[暖启动训练与策略核对](../data/manifests/jev-reader-warm-label-shared-reconciliation-20261017.json)、[C20 训练对照](../data/manifests/jev-reader-c20-trained-controls-20261017.json)、[C20 问答对照](../data/manifests/jev-reader-c20-qa-v1-summary.json)。

## 数据与 Writer 诊断

来源审阅累计覆盖 24 个训练来源行、12 个家族、123 个状态：86 个保留监督，37 个因歧义或证据问题遮罩。最新新增的 16 行均与已下载镜像中的原始对象逐项相同；尚未证明该镜像与官方归档全文等价。保留原标签、原问题和可见输入，没有用评测问题标签补充训练，也没有进行 SHA 或内容指纹校验。[来源记录](../data/manifests/jev-reader-source-qualified-v2-progress.json)

对真实形成的旧记忆进行检查时，Writer 曾把空的 `change_candidates: []` 当成不必保存新事实的理由。已有配对诊断覆盖 4 个已暴露的合成场景、2 个种子：复用另一分支的 8 个响应，本分支补充 8 个不重叠响应，共 16 个首次提案。

仅省略该空字段后，**包含新增事实的提案从 3/8 变为 5/8**。这是提案内容计数：16 个提案均通过响应 JSON Schema 检查，但均未提交到记忆库。North 场景仍全部漏存；一个原版 Luma 提案出现自身依赖支持；Nera 提案仍有多个事实合并和报告措辞变强的问题。因此不能把这项结果称为可靠的记忆状态修复。

本次提交保留一项已有的最小代码改动：`event_delta_v1` 输入只在 `change_candidates` 恰为 `[]` 时省略该字段。非空提示、来源绑定、响应 schema 和提交验证保持原样；这只是研究分支的输入清理，没有更换模型或部署服务。[16 个提案与账本核对](../data/manifests/jev-writer-empty-hints-joint-review-20261017.json)

## 实际消耗与本地位置

以下为各阶段实际记录，不是整个研究项目的总成本；各组计数单位不同。

| 阶段 | 已记录工作量 | 墙钟 / CPU |
|---|---|---|
| 基础权重四任务 | 1,376 个训练序列位置、3,817,904 训练 tokens；600 次开发前向、1,557,140 开发 tokens | 681.40 / 879.01 秒；含进程启动的协调器总耗时 702.57 秒 |
| 暖启动四任务 | 1,320 次模型前向、3,638,836 token positions | 607.59 / 675.72 秒 |
| 暖启动策略 Reader | 17 个首次响应、9,431 tokens；另 13 个位置复用 | 详细计量见核对清单 |
| Writer 配对诊断 | 已有 8 响应 59,407 tokens；本分支 8 响应 56,777 tokens | 请求墙钟分别合计 159.52 / 136.58 秒 |

训练与 HTTP 用量已和原连续账本差额核对，没有重复计费或新建账本。本次仅补记已测量的预处理、暖启动核对及提案核对 CPU 工作。人工语义审阅和部分编排耗时未完整计量，不能当作零。GPU3 曾与另一训练共享，不能据此声称独占设备速度。

模型、数据、环境和缓存均留在 `/cra/memory/mx_memory`，未上传模型权重、原始数据、环境或运行日志。

| 内容 | 本地位置 |
|---|---|
| 本分支代码与文档 | `/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab` |
| 基础权重四任务 checkpoint、输出 | 上述目录下 `artifacts/jev-reader/source-qualified-label-pair-v1/runs/<seed>/<arm>/`，arm 为 `original_labels` 或 `reviewed_labels` |
| 来源审阅数据 | 上述目录下 `artifacts/jev-reader/source-qualified-v2/` |
| Python 环境 | 上述目录下 `artifacts/jev-reader/http-env/`、`cuda-env/` |
| Writer 补充诊断 | 上述目录下 `artifacts/jev-reader/writer-empty-hints-companion-v1/run-v1/` |
| 暖启动原始产物 | `/cra/memory/mx_memory/MiLAi-worktrees/jev-read-bottleneck-20261016/MiLAi-Lab/artifacts/jev-bottleneck/reader-label-ce-v1/` |
| 下载与编译缓存 | `/cra/memory/mx_memory/.cache/`、`/cra/memory/mx_memory/.uv-cache/` |

发布前检查：本分支训练和 Writer 诊断进程均已结束，无待运行任务。GPU2/3 各空闲 36,928 MiB；7862 的 `milai-unified-v8-v9-native-host-r2` 容器为 exited。BGE-m3（7861）、bge-reranker（7961）及 7860 原服务仍在运行，未作启停或配置修改。其他工作树的任务和未提交文件保持原样。

## 验证、交付与限制

- 受影响测试：`test_edit_v2_runner.py`、`test_writer_locality.py`、`test_dependency_groups.py` 共 **40 passed**；改动文件 Ruff、mypy、`git diff --check` 通过。
- 实际 `milai_lab.boundary` 包依赖检查、`milai_lab.tools_boundary` 工具边界检查通过；没有运行完整仓库或远端 CI，局部通过不代表 production ready。
- 代码改动仅影响 Lab 的 Writer 输入序列化；Product、公开 Schema/API、权限、Canonical 行为未改。回滚基点为提交 `a5bc98fa`，可撤销本次发布提交恢复此次输入改动。
- 提交到研究分支 `feat/lab-jev-read-decisions-20261016`，不合并 main。详细历史与失败证据保留在[完整报告](MILAI_JEV_READ_DECISIONS_20261016.md)和[完成度审计](../data/manifests/jev-bottleneck-review-execution-audit-20261017.json)。

尚未解决：可靠的互补证据选择和停止策略、Writer 完整状态形成、必要修改范围与只读上下文的边界、独立未暴露评测，以及质量可比的整个流程成本收益。目标保持暂停且未完成，不因本次提交而自动继续训练、扩大 Impact/RL 或宣告研究成功。
