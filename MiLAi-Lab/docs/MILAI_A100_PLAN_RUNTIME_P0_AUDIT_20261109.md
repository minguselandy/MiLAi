# 原763行计划的P0与运行时要求：原始GPU证据逐项核对

本报告核对[原计划](/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_2XA100_40GB_20261104.md)中P0/运行时相关的12项具体要求，证据来自实际
训练、输入/窗口、原始预测、保存重载、显存和代码。它不把一个局部检查当成原763行
全部完成；A/B/C/D、确认、外部400×2、全成本和最终交付仍按各自完整范围审核。
本次没有新训练、模型forward、tokenizer、HTTP或原始账本调用。

## 要求到证据的映射

| 编号 | 原计划行号 | 已在P0范围内核对的要求 |
|---|---|---|
| P0-01 | 21, 82, 94, 143, 144 | 两独立单卡、逻辑cuda0、真实forward计数与相同配置 |
| P0-02 | 103, 104, 149, 164 | 沿原初始化与显式single/precision接口，不替换模型 |
| P0-03 | 105, 145, 155, 157 | 显式BF16 forward、FP32参数/关键归约、backward在外 |
| P0-04 | 106, 107, 125, 163, 169 | 独立512合法TRAIN行、32更新、16行窗口与完整micro2 pair |
| P0-05 | 112, 123, 163 | 原配置长度、最长样本、全输入与明确名义上下文范围 |
| P0-06 | 114, 164 | 同seed/顺序/选项置换；profile输出不作正式初始化 |
| P0-07 | 121, 165, 175, 433 | allocated/reserved与实际free分别记录，peak覆盖全部更新 |
| P0-08 | 165, 177, 183 | 前4仍计成本、后28稳态；吞吐范围不等于GPU忙时 |
| P0-09 | 166, 167 | update0/32完整预测与实际FP16导出后重载行为 |
| P0-10 | 147, 151, 697 | 独立output/phase且沿原预算；不增加第二账本或重试平台 |
| P0-11 | 155, 175, 528, 538 | 沿既有attention/dependency wrapper，记录Torch/CUDA/TF32/backend |
| P0-12 | 173, 505, 678 | 具体风险验证后取得真实GPU实测，不以测试摘要替代执行 |

每个条目的原文行与原始路径保存在[机器凭据](../data/manifests/a100-plan-runtime-p0-audit-20261109-v1.json)。
编号和行号用于约束证据范围；例如A训练初始化合同不因P0通过而自动关闭。

## 相同输入、完整窗口和实际运行

原数据共47,866行；按当时冻结训练器的gold-present筛选得到44,868条可训练行，
其余2,998条原始无目标记录仍保留。P0记录的位置指向可训练面板，不是原始JSONL
行号。已流式读取原文件并逐整dict核对512条所选TRAIN记录：432条件行＋80操作行，
状态、标签、metadata均相等。121个完整已知条件pair的端点及bool标签核对通过，
两端始终在实际同一个micro2内；不把无标签行补成负例。

两作业从同一E1原checkpoint出发，物理GPU2/3各自只见逻辑cuda:0，seed0、512行、
32更新、micro2、窗口16、训练顺序和选项置换一致。各256次真实device-forward，
单臂639,380输入tokens、1,057,788 padded tokens；完整lengths无state/head截断，
最大实际序列9869。原计划建议值按真实旧配置继承为max_len16384/head2048，
不能据此或数值有限性宣称超过模型配置8192的有效语义上下文。

实际冻结training_forward仅在训练forward中显式使用BF16 autocast，向原SDK传入
amp=False；SDK返回logits.float()，损失归约、backward和评测位于该autocast之外。
两臂实际parameter_dtypes均为FP32；AdamW沿FP32参数创建状态，TF32 matmul=False/
cuDNN=True、sdpa backend与Torch/CUDA记录一致。没有把SDK的FP16开关冒称BF16。
后续正式A/B及E3拟合的原始初始化路径已逐项核对，不来自P0 profile输出。

## 显存、剩余空间及吞吐

| 实测量 | P0 FP32 | P0 BF16 |
|---|---:|---:|
| 实际更新/行数 | 32 / 512 | 32 / 512 |
| 峰值allocated bytes | 11,013,770,752 | 9,932,060,672 |
| 峰值reserved bytes | 19,570,622,464 | 18,775,801,856 |
| 结束时真实设备free bytes | 18,608,291,840 | 19,396,820,992 |
| CUDA记录total bytes | 42,404,806,656 | 42,404,806,656 |
| 后28次平均更新时间秒 | 7.570171330 | 3.228706646 |
| native完整wall秒 | 389.963971051 | 248.309373475 |

结束时free直接来自原compute的torch.cuda.mem_get_info，不由峰值反推，也不是峰值
发生时的free。reserved包含allocated，不相加。峰值在prepare之前一次reset，覆盖
全部32更新、首次Adam分配、评测与保存。原始hardware.json还记录了启动前NVIDIA
CSV的memory.free/driver_version及topology，设备为A100-PCIE-40GB。
另于2026-11-09实际执行并保存nvidia-smi -L，只补当前只读设备清单，不冒充历史GPU利用率。

前4次更新仍包含在完整成本中，后28次均值之比FP32/BF16为2.344645135。
它描述这一相同TRAIN profile的稳态更新，不是完整作业、Encoder纯推理、GPU忙时或
后续任务效果的速度比。native GPU interval和CPU已有计量边界；未测父/启动/清理
仍保持未知，未重复加进既有已付成本。

## 更新0/32、导出与重载

逐项读取两臂各更新0/32的512份TRAIN与32份DEV输出，共2176份实际head结果；
全ID顺序、有限logits/probabilities、完整argmax与未截断输入核对通过。两臂在更新0
argmax一致512/512，更新32一致508/512。记录数值差异，不把逐位相同作为BF16要求。

另读取全部1024个真实重载结果，核对每个完整model-visible输入等于原冻结
shared_actions投影。两份safetensors头均实际记录170个F16 tensors，重载运行报告
参数FP32；浮点存储舍入与推理参数dtype分别记录。FP32 profile重载无argmax翻转，
BF16 profile重载保留第177条翻转；没有选取重载后更好的结果替换原始输出。

从留存head logits及既有目标调用原冻结decision_loss，在CPU以FP32复算初始/末尾
未加权set诊断loss，均有限。这不是新模型forward，也不是训练过程中不断变化的
加权epoch loss或Host成功率；后者原始weighted_loss_mean分别为
0.660928856/0.661079539。

## 失败、未知及完整计划的边界

当时p0-plan记载相关61项检查通过，旧p0-tests GNU文件只保存wall/user/system，
未保存退出码；本报告如实保留unknown，不写成已直接证明exit0。运行时行为依靠
上述真实32更新、输入/窗口/输出/重载证据核对，测试摘要不替代它们。原生数据集
TEST在这些run中未加载；这与unit-test退出码的未知是两个不同口径。

首次本轮审计把筛选后位置当成raw行号，第二次把无退出码timer当作exit0要求，均
保留真实失败计时后修正审计解释，未修改历史训练数据/标签/窗口/模型/首结果。
旧E3的reserved峰值、TF32及分阶段时间缺项不由本次P0字段补造；它们继续按既有
训练工作表的未知范围报告。当前Mem2Act和原763行其余全部要求仍待各自完整证据，
不由本报告的12个局部条目推断整个目标完成。

复核代码为[audit_a100_plan_runtime_p0.py](../tools/audit_a100_plan_runtime_p0.py)。需使用
项目既有CUDA Python环境（4.52.3 SDK优先、HTTP依赖后追加），向不存在的新输出复算；
它只读取历史结果并作CPU数值归约，不加载权重或运行新模型。审计/报告费用等待实际idle138。
