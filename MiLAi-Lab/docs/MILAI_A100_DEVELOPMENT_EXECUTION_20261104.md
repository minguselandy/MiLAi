# MiLAi 双单卡开发执行记录：2026-11-04

完整目标仍在执行。依据用户指定的
[实验计划](/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_2XA100_40GB_20261104.md)，
从其指定的 `6c49bf05` 创建 `feat/a100-development-20261104`。
历史 worktree、原始失败与用户文档保持原状。没有使用子代理、SHA/内容指纹校验、新服务、第二账本或远端写入。

本轮机器可读入口为
[progress](../data/manifests/a100-development-progress-20261104-v2.json)。
原始数据、冻结运行时、权重、命令、计时和实际输出位于本 worktree 的 ignored
`artifacts/a100-development-20261104/`。本记录是现有报告体系的执行摘要。

## P0：已取得真实运行证据

GPU 2、3 是独立的 A100 PCIe 40GB；每进程仅见一张卡，进程内为 `cuda:0`。
GPU 0、1 上的既有服务没有变动。运行环境仍为 Torch `2.7.0+cu126`、CUDA `12.6`、
Laya SDK `0.4.8` 与 `train_with_declared_attention.py` 初始化，不升级依赖。

训练入口新增 `--device`、`--parallel-mode single|legacy-dp`、`--precision float32|bf16`
和可选 allocator 份额。默认仍为 legacy-dp/FP32；BF16 限于单卡路径，显式 autocast
仅覆盖 forward，SDK 返回 FP32 logits 后计算损失，参数和 Adam 状态保留 FP32。
窗口、pair 同批、末窗口分母、学习率与目标语义沿用原实现。

两臂从同一 E2 初始化开始，各完整训练 512 条 TRAIN 数据、32 次更新。
包含全部 6 个 change pairs，最长 9,869-token 输入、最长 1,120-token head、最多 45 个候选。
两臂实际窗口、选项置换及 639,380 个训练输入 tokens 逐值一致；未丢弃输入。
前 4 更新计入全成本，稳态统计使用后 28 更新。

| 实测项 | FP32 | BF16 |
| --- | ---: | ---: |
| 训练段秒数 | 245.754 | 105.758 |
| 稳态平均秒/更新 | 7.570 | 3.229 |
| 稳态输入 tokens/秒 | 2,629 | 6,164 |
| 峰值 allocated GiB | 10.26 | 9.25 |
| 峰值 reserved GiB | 18.23 | 17.49 |
| 512 行落盘重载后首选变化 | 0 | 1 |

稳态时间比 2.345× 只描述这个 profile。其 operation 比例和长度分布不同于完整 A 面板，
不能直接承诺完整训练工期。reserved 已包含 allocated，不相加。
共同 FP32 推理下，update0 的 512 个首选全部一致，update32 两臂有 508 个一致。
两臂均完成全部 512 条保存后重载，并核对实际模型输入、tokens 与数值。
SDK 实际导出 170 个 FP16 权重 tensors，重载为 FP32；BF16 臂 index177 的首选变化前
margin 为 0.0250。保留这一变化，候选选择必须核对落盘模型，不能将内存模型分数冒充落盘行为。
9,869-token 实例已成功执行；这不证明有效 12k 上下文。

证据：`p0-plan.json`、`p0-data/preparation.json`、`p0-analysis.json`、
`p0-{float32,bf16}/` 与 `p0-{float32,bf16}-reloaded/`。
原生单卡/BF16、完整 pair、梯度累积、mask/padding、保存重载等相关 61 项测试通过；
提名和交付相关另 27 项测试通过。Ruff、包依赖与工具 Product 依赖边界通过；未声称完整仓库 CI 通过。

## A：已修复实际暴露，完整 seed0 配对已启动

同一源码分别用 `legacy` 与 `native-priority` 生成 10k 条件家族面板。
先保留原选择，再在同一实际条件的已知负例槽内替换；change 端点不可替换。
对替换优先保留可完整形成的 stable-negative 关系。

| 数据项 | A0 legacy | A1 native-priority |
| --- | ---: | ---: |
| query 家族 | 10,000 | 10,000 |
| 条件行 | 39,982 | 39,982 |
| 正例 / 负例 | 20,008 / 19,974 | 20,008 / 19,974 |
| 具备原生负例的条件 / 实际覆盖 | 9,540 / 5 | 9,540 / 9,540 |
| change pairs | 6 | 6 |
| stable-positive pairs | 80 | 80 |
| stable-negative pairs | 9,968 | 433 |
| 加入既有 replay 后有效训练行 | 44,868 | 44,868 |

共替换 9,535 条负例。正例、replay、公共 dev、每条件正负槽数及逐槽损失权重一致；
保留原 row slots，使正例和 replay 的选项随机身份不随重排变化。
stable-negative 信号同时变化，不能声称只改变了一个负例计数。
选入覆盖已经证实；实际抽到的覆盖和 tokens 待完整训练输出，不提前当作已完成。

源记录核对发现 E2 实际使用 `max_len=16384`、head 上限 `2048`、encoder LR `5e-6`，
操作 replay 使用 accepted-set likelihood。两臂共同继承这些实际值：条件单一正目标与 CE 等价，
操作 replay 保留 set 语义；不把模板中的 `12288`、`2.5e-5` 或 replay soft-CE 混入处理。
同一原 E2 起点、full 参数、BF16、micro2、窗口16、relative weight0，
各 1 次完整遍历/2,805 更新，检查点为 0/702/1403/2104/2805，末窗口4行。
profile 输出不作为初始化。预定选择规则和完整命令保存在 `a-seed0-plan.json`。

两个正式作业的共同 update0 在3,068个dev和64个feedback-dev上，首选、输入tokens及全部logits逐值一致。
702检查点已经实际落盘，已观测的诊断为：

| 检查点 | 条件家族平衡准确率 | 操作家族准确率 | 旧8对支持条件变化联合正确 |
| --- | ---: | ---: | ---: |
| 共同起点0 | 0.752563 | 0.778851 | 6/8 |
| A0 update702 | 0.890389 | 0.801943 | 1/8 |
| A1 update702 | 0.820530 | 0.801919 | 5/8 |
| A0 update1403 | 0.885107 | 0.798606 | 1/8 |
| A1 update1403 | 0.828600 | 0.782987 | 5/8 |
| A0 update2104 | 0.895039 | 0.793754 | 1/8 |
| A1 update2104 | 0.845812 | 0.799413 | 5/8 |

A1减少了A0在这组诊断上的退化，但尚未超过初始化；不能凭一个检查点选择最终模型。
两臂继续各自预定的完整2,805更新。该表为内存模型的统一FP32推理，尚非落盘模型任务效果，
也不替代新128条件家族或自主Host。最新证据为 `a-diagnostics-through-2104.json`。

## B：先补真实功能，保留原首结果

已有 57 个 TRAIN 状态的动作和完整参数 inventory 已保存。
新增可选 `parameter_coverage` 提名模式，使用合法菜单、已有执行类型覆盖和固定 seed，
排除 observe-only、分页观察与相同绑定，不查看答案或质量结果。
原 fixed_context/acquired_raw_delivery 行为保持可复现。

8 个真实后续状态均满足 argmax、baseline、alternative 三个完整绑定互异。
新执行只包括此前未执行的 8 个 alternative：2 full observed-Source READ、2 range READ、
1 context READ、3 实际材料 HANDOFF。argmax/baseline 的旧首结果不重跑。
这是一组已曝光 TRAIN 功能切片，不增加独立来源数。
原 capture 均为显式 supplied request、`host_request_generated=false`、空 known refs，
故沿既有 `--given-readout`；结果属于条件 readout，不能称为自主 Host 成绩。
8个状态现已完成Source、执行边界、完整参数、packet和readout wire绑定及来源作者质量评审。
4个observed-Source READ均实际打开并返回所选范围；全部16个返回范围匹配实际Source正文与角色。
新替代完整回答1/8、原baseline3/8；答案比较为5 tie/3 baseline更好，
交付为4 tie/3 baseline更好/1 unknown。8个新HTTP、30,879已知生成tokens、新未知用量0。
这是功能和负面监督证据，不能从“Source已读”推出质量增益。
后续提名沿既有非空材料判断排除空HANDOFF子集；已经执行的空交付及失败结果不修改、不重跑。

证据：`b-repair-inventory.json`、`b-functional8-actual-nominations.json`、
`b-functional8-branches-v2/`、`b-functional8-execution/`。
质量证据为 `b-functional8-quality-review.json`。

## C：原菜单、同已读池的真实比较已闭合

从实际捕获的8个已读状态选择每族一个状态，均有至少2份已取得材料和3个合法HANDOFF候选。
沿既有F1入口准备，8个完整菜单均与原菜单逐值相同；没有新增候选、重新取得材料或重跑前缀。
fixed_context、rules、保留的E1 delivery-only-u16分别执行一次HANDOFF及给定请求readout。
学习候选在现有CPU路径运行，4线程，2/3卡继续留给配对A拟合；这不是A100推理延迟测量。

| 方法 | 完整 /8 | readout失败 | 已知生成tokens | 已计本地模型CPU秒 |
| --- | ---: | ---: | ---: | ---: |
| fixed_context | 4 | 0 | 23,831 | 0 |
| rules | 4 | 0 | 17,011 | 0 |
| E1-u16 learned | 1 | 2 | 30,267 | 380.644 |

全部24个首次位置、62个原文范围、实际HANDOFF和readout输入已绑定；24 HTTP、71,109已知生成tokens、
新增未知用量0。两次失败保留在完整任务分母；涉及失败readout的答案偏好为unknown，交付可独立判断。
CPU表只列已经由native计量记录的模型部分；整进程447.88 CPU秒还包含客户端等工作，不能重复相加。
这组条件readout结果不是自主Host或未曝光确认，也不能从CPU成本换算A100延迟。

三个状态明确存在“材料已取得、合法集合已有、学习选择却丢掉关键材料”：UAR指标、词义/句法区分、
模型参数数量。另有OpenIE和树库增量规模的上游获取缺口；TutorialVQA既丢掉已取得的部分指标，
也缺少尚未取得的tolerance accuracy。FSE/regularization仍保留原来源判断中的限定与unknown。
rules/learned在一个状态收到完全相同的packet和wire，不将其措辞变化当作选材收益。
这些证据支持优先补完整参数/集合监督，当前没有需要扩展HANDOFF菜单的证据。

证据：`c-handoff8-selection.json`、`c-handoff8-v2/`、`c-handoff8-bound-results.json`、
`c-handoff8-quality-review.json`。三个方法仍只是这个功能切片的比较，不作采用结论。

## 新来源的实际分配

沿既有1,169篇论文allocation，扣除实际已采集的64个TRAIN家族，从既有TRAIN分配中选取新的64家族，
保留原生问题和4,502个Source单元；当前只导出每族第一个既有问题，尚未采集reached states。
另从parent中尚未使用的身份元数据分配新的64任务DEVELOPMENT家族，并预留256确认家族
（185 native-dev、71 native-train），各组及旧64族核对互不交叉。
确认正文与标注尚未导出/查看；冻结候选、规则、预算后才使用。公开预训练隔离未获认证，
256也不是+5pp的功效保证。新128条件开发家族属于另一数据轨，仍需按真实标签资格处理。
证据为 `source-allocation-v1.json`；分配接续parent和实际使用记录，不直接套用历史unused计数。
采集已准备为8＋56两个串行段，配置预检查完成且模型调用为0；见 `b64-collection-plan/plan.json`。
释放GPU后使用现有FP32推理路径，保留关闭reference_compile的既有初始化并记录实际设备、精度和峰值显存；
checkpoint没有持久化该encoder标志，不能仅换解释器后依赖其默认值。

## 失败与改进

profile 准备首次引用不存在的 JSONL 写入函数，在模型调用前退出；
改用项目已有的逐行 JSON 写法，保留失败计时。
8 状态准备首次继承 initial1/post1 配额，实际选入16状态，触发精确状态核对失败；
确认 `--include` 是提名而非过滤后，使用既有 initial0/post1 配额，另建 v2，实际准确选入8状态。
保留失败目录和反思记录，没有修改捕获、放松核对或重试模型首结果。

8状态绑定最初误要求每次READ后都有下一次观察；实际step7只有一个控制槽，执行器正确地直接
返回budget_exhausted。修正分析器，核对真实opened结果、最后槽位与实际返回范围，不虚构下一观察。
C准备发现既有F1入口漏传`exclude_given_requests`，真实checkpoint配置核对因此失败。
配置保持严格相等，补齐原参数；新增SQLite回归修复前失败，修复后27项相关检查通过，
实际8个状态重新准备成功且原菜单不变。失败目录、计时和反思均保留，没有模型重试。

## 全范围剩余要求

| 里程碑 | 当前证据 | 仍需执行 |
| --- | --- | --- |
| M0 | 两单卡32更新、统一 FP32评测与落盘重载闭合 | 后续变更若引入新风险，再定向验证 |
| M1 | 条件覆盖修复、57状态inventory、8新绑定及源审闭合 | 其余缺失READ保持清单，结合决策空间决定必要补采，保留tie/loss/unknown |
| M2 | A0/A1 seed0在运行且702诊断完成；C8原菜单比较闭合 | B-64实际前缀/状态/共享三分支与两监督面板拟合；新128条件开发家族按真实标签资格分配 |
| M3 | 尚无新任务质量结论 | 对有信号的比较补 seed1/2；仅必要时20k或192/256规模实验 |
| M4 | 旧 E5失败保留 | View＋增量读取控制、同信息对照、新32更新来源族与自主 Host；有预算机制依据再补1024 |
| M5 | 新64任务开发族与256确认族身份预留，尚未冻结最终候选 | 实际使用前再核曝光；冻结确认；LME451/Mem2Act400；完整成本、论文图表与可主张边界 |

所有规模和 seed 扩展遵循原计划的信号条件，不把多问题、状态、重复或 seed 当作新来源。
最终允许简单方法获胜；局部 loss、动作准确率和材料覆盖不能代替来源族宏平均 Host 完整成功。
主比较报告 gains/losses、家族 bootstrap 区间及全部失败，不能从旧32族或这个8状态功能切片宣称独立泛化。

所有工作沿原连续账本
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`。
原 v79 的45.39秒离线 CPU 仍列 pending，不重复计已结算模型成本；
本轮有计时的准备/测试/分析以及分支客户端残余另列 pending，未测作者工作记 unknown，远端硬件与货币成本未测。
GPU单元测试未单独测量GPU-hours，不能计为0。P0拟合/重载及C的native CPU已经记录，
后续idle结算须从整客户端成本中扣除这些已计部分；不得重复计账。
训练器进程内时钟不包含解释器/依赖导入及CUDA admission，这部分尚未单独计量，不填0。
实际SDK路径、安装版本和已核对的forward/导出实现另存 `runtime-environment.json`。
本轮没有改变 Product 的公开 Schema/API、权限或 Canonical 行为；没有推送或合并。
