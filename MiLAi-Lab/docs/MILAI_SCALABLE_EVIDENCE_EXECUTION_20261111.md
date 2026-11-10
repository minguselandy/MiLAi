# 2026-11-11：规模化证据学习 v2 执行记录

执行依据是用户指定的 [v2 计划](/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20261111_2XA10040GB_v2.md)。计划所在工作树停在 10 月代码；实际开发采用与计划基线一致的 `a100-development-20261104` 工作树。本轮没有执行 SHA 或内容指纹校验。

**目标仍在进行。已完成一个可测的工程切片、来源数据发布和 I2 反馈种子编译；3k 有效操作状态、规模学习与新的 Host 比较尚未完成。**

## 已实现的正常执行路径

- `NativeDecision.prepare_batch / predict_prepared / predict_batch` 复用 SDK 编码，长度排序后恢复输入顺序，按真实菜单屏蔽 padding。缓存仅保存 tokens，不保存 logits 或隐藏状态，模型更新后继续正常推理。
- 原训练器增加 `--eval-batch-size`、`--cache-evaluation`、独立的 `--eval-precision`。开发集编码跨检查点复用，结果按行写 `predictions.jsonl`；曲线读取器兼容新分片和原逐行文件。
- `--effective-batch-rows` 参数化更新窗口；`--length-bucketed-microbatches` 保留窗口内样本与条件组；多条件对同批时分别计算组内相对损失及窗口分母。
- `--microbatch-padded-token-target` 使短输入合批、长输入减批，原子条件对不拆散。它是软目标，单个长条件对可以超过目标；不会丢弃或裁掉长例。
- `--log-every-updates` 聚合阶段同步、计时和进度写入。普通 loss 在设备端累加；数值异常检查仍保留。条件诊断及部分质量梯度统计尚可进一步减同步，不宣称 E2 全部完成。

旧默认参数和单条推理入口保留。没有修改 Product、公开 Schema/API、权限或 Canonical 行为，没有新增服务、Store、账本或自动重试。

## 实际性能与限制

FP32 同模型评估在物理 GPU 2 上以 ABBA 顺序比较，64 条固定 TRAIN 工程输入包含 126–9,869 tokens、4 条超过 8k、最多 43 个选项。逐条平均 7.881 秒，缓存后批量平均 5.853 秒，约 **1.347 倍吞吐**；计入首次编码 0.294 秒后约 **1.282 倍**。选择和选项绑定顺序均无变化，最大 logit 误差 `1.0312e-5`。CPU/CUDA trace、kernel 时间表及完整预测均已保存。

训练比较共用初始化、512 行、32 更新、有效窗口 16、BF16、学习率和条件采样。每臂实际曝光 639,380 有效 tokens。首次固定 microbatch=4 将 padding 从 1,057,788 增至 1,309,436 个总输入位置，训练仍约 107 秒；该结果保留，没有把减少前向次数等同于加速。

随后采用最大 microbatch=8、padded-token 软目标 8,192，并补做两份单卡作业同时运行的对照。最终 v2 比较的实际训练计划、样本权重、选项置换和输入长度记录一致：

| 结果 | v2 实测 |
|---|---:|
| 训练吞吐比 | 1.178× |
| 开发评估吞吐比 | 1.282× |
| 整个作业吞吐比 | 1.156× |
| 末点开发条件分类 | 两臂均 10/16 |
| 末点开发操作接受 | 两臂均 13/16 |

固定开发面板很小，各任务仅一个来源家族。上述计数只服务工程诊断，不证明训练质量等价、Host 收益或泛化。microbatch 重组会改变 dropout/浮点运算顺序，不承诺权重逐位一致。两臂分别使用物理 GPU 2、3，未做换卡交叉实验；共享 GPU 0、1 服务保持原状。训练吞吐尚未达到计划建议的 1.5×目标，但已有有益优化可用于后续学习。

## 数据与创新工作

已发布来源总体：384 个既有研究 TRAIN 论文家族、672 个请求、28,925 个原始来源单元；其中 256 家族、451 请求未进入之前两批操作采集。继承的开发池为 32 家族。继续沿用本项目来源角色，已排除既有开发与确认来源，不把原生 TRAIN 身份当作自动训练资格。“新增”仅相对已记录操作采集，不表示未被预训练见过。

这些文件目前是**来源材料，新增有效操作状态为 0**。下一步用原 Store / EvidenceOperations 执行 SEARCH、READ 和交付，记录真实初始及 post-state；从有明确监督的分片开始训练，unknown 保留在原始文件中。

I2 已通过 `prepare_handoff_feedback.py` 复用原 C8 的实际同池交付与首个读出结果：8 个 TRAIN 家族、8 个状态。保留完整原菜单和绑定；同一绑定由多个策略选中时只生成一个候选。交付关系为 6 个有方向 pair、4 个正例粗粒度平局、12 个 unknown；有方向的 fit 视图为 3 个状态。两个不足包之间不推断同等质量，失败读出不自动当答案负例。

此种子尚未拟合。它说明可直接把“已取得却丢在交付之外”的真实结果接入原 scorer，并非新增 Host 运行，也不是开发集结果。后续扩到新 TRAIN 来源的真实包比较，同时固定不同来源的开发任务；不能用这 8 个训练家族上的拟合证明泛化。

## 验证、产物与继续执行

73 项相关测试通过，包含真实双 GPU 的旧配方、BF16、条件组、多组梯度、尾批、缓存、预测分片以及 unknown 标签语义。Ruff、`git diff --check`、活动包依赖边界通过。活动 tools 边界仍报告原有 LME owner 两个文件中的 6 处动态导入解析问题；文件未改动，未把这些问题设为本轮训练前置。没有运行全仓、PostgreSQL 或产品部署测试。

最初评估 profile 因直接调用 CUDA 环境而缺少 `langchain_core`，在模型加载前失败；失败记录保留。第二次沿用项目已有 dependency/attention wrapper 完成，未升级环境。

- [精简结果 manifest](../data/manifests/scalable-evidence-progress-20261111-v1.json)
- [完整阶段结果及后续脚本](/data/milai-experiments/20261111-scalable-evidence/progress.json)
- [同并发训练命令与终态](/data/milai-experiments/20261111-scalable-evidence/engineering-training-v2.json)
- [来源发布记录](/data/milai-experiments/20261111-scalable-evidence/source-population-v1/manifest.json)
- [I2 初始反馈](/data/milai-experiments/20261111-scalable-evidence/i2-feedback-seed-v1/manifest.json)

新大文件写在持久化 `/data/milai-experiments/20261111-scalable-evidence`，因为 `/cra` 已无普通可用空间。五个工程训练作业全部 exit 0，权重和首结果保留；没有后台队列。训练阶段沿原连续账本计量，未测作者/测试/失败准备 CPU 不填零。模型作业区间不解释为 GPU kernel 忙时。

后续仍按原目标推进：约 3k 真实有效操作状态与来源外开发面板；优化器/scheduler/RNG/采样恢复及 warmup；10k/30k 嵌套来源学习曲线和计算匹配；I2 配对训练与实际 Host 开发；真实反馈、自身状态及选定条件探索；决定性比较的 seed 与新来源确认。工程切片不替代这条完整能力链。旧外部实验的未完成收尾保持历史身份，不阻塞这些新工作。

本轮回退参照是开始时的 A100 分支检查点 `47601a79`。没有推送、合并或更改共享服务；远端状态未重新核对。
