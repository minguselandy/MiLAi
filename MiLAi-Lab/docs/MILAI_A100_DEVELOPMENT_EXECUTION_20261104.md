# MiLAi 双单卡开发执行记录：2026-11-04

完整目标仍在执行。依据用户指定的
[实验计划](/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_2XA100_40GB_20261104.md)，
从其指定的 `6c49bf05` 创建 `feat/a100-development-20261104`。
历史 worktree、原始失败与用户文档保持原状。没有使用子代理、SHA/内容指纹校验、新服务、第二账本或远端写入。

本轮机器可读入口为
[progress](../data/manifests/a100-development-progress-20261105-v9.json)。
原始数据、冻结运行时、权重、命令、计时和实际输出位于本 worktree 的 ignored
`artifacts/a100-development-20261104/`。本记录是现有报告体系的执行摘要。

## v9 当前状态：五方法已闭合，保留 E3 复现，D 仍待实现

DEV64 的五方法、320 个完整答案与实际输入全部完成来源作者审阅。该作者也参与实现，
并非盲审或独立评审。所有首结果和失败保留在每方法 64 族分母中。

| 方法 | 完整答案 | 工程完成 / 失败 | HTTP | Host prompt＋completion tokens | 原生字面 Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed-prefix | 25/64 | 49/15 | 143 | 528,693 | 0.0774154 |
| E1 u16 | 25/64 | 45/19 | 154 | 622,629 | 0.0802133 |
| B0 u33 | 33/64 | 59/5 | 139 | 504,911 | 0.0947629 |
| B1 u33 | 32/64 | 53/11 | 151 | 580,186 | 0.0978627 |
| 既有 E3 aggregate u32 | 40/64 | 55/9 | 135 | 461,096 | 0.0894039 |

E3 对 fixed-prefix 为 17 gains / 2 losses，+23.4375pp，描述性 95% 家族 bootstrap
区间 [10.9375,35.9375]pp；对 B0 为 12/5，+10.9375pp，区间 [-1.5625,23.4375]pp。
B1 对 B0 为 12/13，-1.5625pp，区间 [-17.1875,14.0625]pp。
将三个来源解释敏感问题 3/8/56 的完整信用对所有方法同时撤去，仍保留 64 族，
计数为 25/25/30/31/38；E3 对简单方法为 15/2，+20.3125pp，区间 [9.375,31.25]pp。
这项事后敏感性不替代主指标，也不构成独立裁决。

五方法共 722 次 HTTP、2,697,515 个已知 Host 总 tokens，新增未知用量为 0。
全部 320 个结束状态（含 59 个失败状态）的 Store/Saver/application 已只读核对；
每方法 4,343 个初始 Source 值保持，实际输入绑定 1,733 处原文字段且无 unmatched。
最终 assistant Sources 是输出，不能当事实；没有 semantic-record 写入。
原生 F1 采用实际完整回答和原生全部答案，不抽取短答案、不重写失败或 unanswerable，
其排序与来源作者完整成功不同，不能代替主指标。

所有 64 族的首个 Host provider 请求在五方法间逐字一致，但五者首轮实际检索参数列表
完全一致的族为 0/64；因此完整轨迹包含随机 Host 查询变化，不能将端点差异孤立归因于
控制器或新数据组成。E3 的旧 457 slots、128-update 调度、双卡 FP32 与新 B 配方的
528 slots、66-update 调度、单卡 BF16 也不同。实际返回 Tool.content 正文均不超过 2048 tokens。
E3 whole-child CPU 为 692.684918 秒，其中原生预测 506.823635、加载 7.990816、
剩余客户端 177.870467 各计一次；GPU 作业区间 0.5468298 小时含 Host 等待。
简单方法 CPU 为 203.499353 秒。较低 Host tokens 尚不能证明全成本占优。

E3 仅保留为开发参考。精确 seed1/2 配方已冻结并启动：复用原冻结 runtime、数据和
FP32 双卡 argv，仅 seed、输出目录、compute-phase 改变；每次仍为 128 更新、2048 draws，
评测点 0/16/32/64/128，后续自主 Host 固定评估 u32，不挑最好 seed。
这衡量同一固定 E1 u16 初始化下的训练随机性，不是完整训练链三次独立拟合。
seed1/2 预期实际训练 tokens 分别为 10,549,642、10,607,432；实际结束后核对。
当前 exec2604、seed1 child1638434，随后 seed2 串行；无并发 HTTP。

所保留 E3 也完成 C8 原菜单诊断：8 次真实 HandoffOnly 投影后的本地 forward，
8 个选择全部复用 30 个已有绑定中的最早首次结果，新增 Reader 调用为 0，完整答案 1/8；
与其他学习模型相同，低于 fixed_context/rules 的 4/8。未发现应扩菜单的表达缺口。
该诊断不等同完整自主反馈策略；可优先保留简单材料选择职责。

D 的 9 个旧 post-REFRESH READ＋HANDOFF 机制探针已闭合，但可选增量策略、
实际 old View / known-evidence 控制、旧 8 背景全流程与新加入 D 的 32 个 TRAIN 背景
自主 Host、同信息比较仍未完成。不能从原生 View＋raw packet 推断任务提升。
新 32 已有历史 TRAIN/来源暴露；不称未见、自然实测或独立确认。

按当前 E3 对简单方法的族差值样本方差 0.2457837302，近似检测真实 +5pp 对零差异
在双侧 5% / 80% 下约需 771 个独立族；这只是条件规划，预留 256 不保证该功效。
最终方法、checkpoint、计分、预算与确认样本量仍须在 held 内容打开前冻结。
当前 64 族是已曝光开发；held 256、旧 64 query 确认内容未导出/审阅，native test 未打开。

成本仅用原账本：v8 在五方法结束后、C8 E3 之前结算 10 个计时命令 24.68 CPU 秒；
v9 在 C8/复现准备完成后、复现启动前结算 2 个计时命令 1.04 CPU 秒，均只计一次。
E3 C8 whole CPU 31.074597＝原生 15.060130＋客户端 16.014467 已另计一次；
作者及未计时 CPU 仍为 unknown，不记 0。所有第一失败和意外 A 重复调用的成本保留。

证据：`task-dev64-development-selection.json`、`task-dev64-paired-selection-progress.json`、
`task-dev64-cost-and-entry-audit.json`、`task-dev64-all5-native-agreement.json`、
`c-handoff8-e3-saved-choices.json`、`e3-retained-replication/{plan,driver}.json`。
以下分包记录保留形成过程；本节与 v9 manifest 是当前状态。

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

## A：实际暴露修复，两个完整 seed0 拟合已闭合

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
选入覆盖与完整拟合中的实际抽样均已核对；实测 tokens 和覆盖见下文完整训练记录。

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
| A0 update2805 | 0.885959 | 0.803642 | 1/8 |
| A1 update2805 | 0.824376 | 0.800519 | 5/8 |

A1减少了A0在这组诊断上的退化，但尚未超过初始化；不能凭一个检查点选择最终模型。
两臂均已完成预定2,805更新、恰好44,868行一次遍历、末窗口4行，进程正常退出。
A0/A1实际输入37,502,475/37,318,166 tokens，实际抽到原生负例条件5/9,540，
GPU作业时间2.3430/2.3810小时；每臂22,434次单卡microbatch forward。
窗口、选项置换、逐槽权重、完整输入、全部检查点、评测计量与原账本相应单次phase已核对。
预定门槛下两臂均提名2104；落盘行为与旧32族条件任务已闭合，自主Host和新来源确认仍待执行。
该表为内存模型统一FP32推理，不替代新128条件家族或自主Host。
证据为 `a-diagnostics-through-2805.json`、`a-full-fit-closeout.json`。

新的128条件DEVELOPMENT家族来自既有canonical DEV新query分配，排除旧32和已预留64查询家族，
没有跨分区重分配。原生矩阵8,744行：已知8,202、未知542、稳定对3,830、变化对0。
在新模型输出前按两种结构层各取首8个未知对应单元做来源判断：新增12个可归因标签、4个仍未知，
复核视图形成3,840稳定对、2变化对、530未知对；原生视图与gold保留不动。
判断仅为提供材料的适用性，不认证外部事实、医疗或来源可信度；歧义/可信度未决保留unknown。
这2个变化对不足以支持稳健条件泛化结论；8,744行也不等于8,744个独立家族。
三模型（初始化及两臂提名）的7个GPU3落盘评测已全部正常退出；新面板原生与复核标签共用一次实际预测，
初始化旧公共3,132个已核对的实际落盘起点预测复用，不重复模型调用。

新128族原生标签上的家族平衡准确率：初始化0.661798、A0提名0.883766、A1提名0.838801；
复核16视图分别0.661067/0.884680/0.838142。仅2个来源复核变化对的家族联合正确率为
0.5/0/0，不能从分类提升主张条件变化泛化。旧8对按其实际5个query家族聚合为
0.866667/0.1/0.4；“8对”不是8个独立家族。
落盘分析见 `a-saved-evaluation-closeout.json`。当前不扩大A20k、不自动追加seeds或A→B。
另已完成两提名模型在旧32族任务面板的31个真实完整菜单状态预测；
按实际完整绑定、同before/续行/readout匹配复用旧首结果。补核发现此前索引漏纳E3的22个闭合绑定，
导致A新增11次HTTP中有1次重复了较早E3绑定，实际新绑定为10个。
重复的WSJ状态首动作、续行和packet完全一致，较早回答因把n-gram LM误说成最佳端到端模型而qualified，
较晚回答更好；主统计恢复较早结果，不挑选后一次。两份输出、源审和全部费用都保留。
较早E1/E2/E3评分保持，缺失状态仍保留在32族分母。

| 旧32族条件任务 | raw delivery | 初始化E1-u16 | A0-u2104 | A1-u2104 |
| --- | ---: | ---: | ---: | ---: |
| 完整成功 /32，较早首结果口径 | 14 | 14 | 15 | 15 |

A0/A1相对初始化均为3 gains/2 losses，差值+3.125pp，来源族bootstrap描述性95%区间
[-9.375,+15.625]pp；两臂的完整成功指示逐族相同，A1相对A0没有新增成功。
旧16/32汇总由此次较早首结果核对取代，不能再作为权威任务结果。
该面板不提供native-priority的任务采用依据；A20k、更多seed和A→B均未触发。
完整回答中的无依据“所有标注均自动完成”“明确手工调参”等扩展保留为qualified，
没有因为核心片段正确就升级为完整成功。旧“existing approaches”的统一宽范围解释保持，
不临时收窄成四个基线名。条件readout与自主Host分别报告。
证据：`task-first-outcome-registry-v2.json`、`a-task32-closed-choices-v2.json`、
`a-task11-outcomes-for-review.json`、`a-task11-author-decisions.json`、`a-task32-results-v2.json`；
原生完整字符串F1单列于`a-task32-native-agreement-v2.json`，没有替代完整任务指标。

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

之后又在相同8个实际池上取得E1初始化、B0-u33、B1-u33的24次实际GPU3选择。
核对源码后按现有`HandoffOnlyPolicy`在编码前限制决策菜单；执行器原始完整菜单仍保留，
不是对完整菜单argmax做事后屏蔽。8个输入均与生产策略的实际投影逐值一致。
旧完整绑定复用较早首结果，新增仅6个不同HANDOFF，经既有首动作干预执行，续行0、READ0。
全部实际receipt、同wire条件与原始Source范围已绑定，5次readout完成、1次首次失败。
源审后E1/B0/B1均完整1/8，原两个简单方法各4/8；新选择仍包括空集或缺关键事实的单段。
没有菜单表达缺口或采用依据，保持失败和全部已计成本。
证据：`c-handoff8-saved-plan.json`、`c-handoff8-new6-outcomes-for-review.json`、
`c-handoff8-new6-author-decisions.json`、`c-handoff8-retained-model-results.json`。

证据：`c-handoff8-selection.json`、`c-handoff8-v2/`、`c-handoff8-bound-results.json`、
`c-handoff8-quality-review.json`。三个方法仍只是这个功能切片的比较，不作采用结论。

## 新来源的实际分配

沿既有1,169篇论文allocation，扣除实际已采集的64个TRAIN家族，从既有TRAIN分配中选取新的64家族，
保留原生问题和4,502个Source单元；每族使用第一个既有问题，实际reached states及分支已全部采集。
另从parent中尚未使用的身份元数据分配新的64任务DEVELOPMENT家族，并预留256确认家族
（185 native-dev、71 native-train），各组及旧64族核对互不交叉。
确认正文与标注尚未导出/查看；冻结候选、规则、预算后才使用。公开预训练隔离未获认证，
256也不是+5pp的功效保证。新128条件开发家族属于另一数据轨，其实际原生/复核标签结果见A节。
证据为 `source-allocation-v1.json`；分配接续parent和实际使用记录，不直接套用历史unused计数。
采集已准备为8＋56两个串行段，配置预检查完成且模型调用为0；见 `b64-collection-plan/plan.json`。
释放GPU后使用现有FP32推理路径，保留关闭reference_compile的既有初始化并记录实际设备、精度和峰值显存；
checkpoint没有持久化该encoder标志，不能仅换解释器后依赖其默认值。

首8族实际GPU采集现已闭合：64次本地决策、395,334本地输入tokens、8次HTTP、31,730已知生成tokens，
8个首次readout均完成、新未知用量0。实际加载记录验证cuda:0/物理GPU2、FP32、4线程、MHA fastpath关闭、
reference_compile关闭；峰值allocated2.305GB、reserved7.999GB，整客户端206.85秒含Host等待。
这不是与历史CPU批次的纯硬件因果比较，也不是质量胜出结论。
剩余56族也已在相同冻结collector下正常退出。完整64族共512次本地决策、3,115,914本地输入tokens、
64个HTTP readout全部完成、237,960已知生成tokens、新未知用量0。
两段实际query/public task、完整输入及首次readout均已核对，见 `b64-full-collection-reconciliation.json`。

来源状态提名现增加可选`acquired_parameter_support`：每族最多2个实际已获材料且具备互异
argmax/baseline/alternative的状态，缺口保留。`--exact-nominations`防止准备器回填未合格状态。
旧默认初始/后续采样保持可复现；48项相关检查通过，并在旧真实捕获上零模型调用复核16状态/48绑定。
新首8族也选入16状态/48互异绑定，其中3个满足既有单剩余槽terminal READ复用协议，
保留其原始首readout；45个新绑定现已正常退出。
其余56族实际选入112状态/336绑定，其中23个同样复用首结果，313个新绑定也已正常退出。
全B64达到128个合格状态、384个真实完整绑定，358个新分支与26个原始等价末READ首结果。
B0/B1仍共用完整菜单与一次实际baseline；这些是64族而非384个独立来源。
358个新分支共358次HTTP、1,257,699已知生成tokens、新未知用量0；384个绑定中
373个readout完成、11个首次readout失败。全部1,613个Source范围、角色、完整首动作、
已执行前缀与共同续行、同一Reader wire中实际packet均已绑定，失败未重试。
26个复用readout成本保留在原64族前缀采集，不再收取；baseline实际执行128次，供两面板共享。
证据：`b64-branch-closeout.json`及两段`outcomes-for-review.json`。

## B64：配对训练与旧32族任务已闭合

384份实际交付包已逐一源审，记录充分94、部分106、不足178、不确定6。
原生标注只作来源线索：表格标题不能恢复数值，截断段落不能补全缺失实体，
实际Queensland结论95%与原生答案96%的差异原样记录，Brier/ROC的适用范围分别保留。
六份不确定材料来自同一“baseline”含义未决的来源，两状态比较保持unknown。
完整回答现已完成全部64族、384个实际首结果的来源作者审查：
107完整、199不完整、60带无依据内容或推断、1核心错误、11首次失败、6未决。
实际闭合拟合文件中的新增256个answer比较始终保持unknown，未用后续审查回填训练。
交付标注没有被转换为回答成功。部分回答在材料充分时仍误述共享组件、初始化或方法组合，
也有粗粒度材料partial但能通过合法的宽范围解释回答问题的情况，两层指标不互相替代。

| 新128状态纯delivery监督 | B0 argmax↔baseline | B1 alternative↔baseline |
| --- | ---: | ---: |
| 方向比较 | 9（左5/右4） | 23（左2/右21） |
| tie | 117 | 103 |
| unknown | 2 | 2 |

97个状态的两比较同时为tie，常见原因为双方都缺必要事实；tie并不表示任务成功。
覆盖提名得到更多方向，其中21/23偏向baseline，不能据此声称提名有效或扩大192/256族。
若下一批采集有依据，应利用真实可见请求与证据缺口改进提名，不只平衡动作类型。
交付质量按本轮TRAIN编译时固定的充分/部分/不足粗粒度比较；同为部分的tie不表示事实集合完全相同。

完整回答的B0比较为左优19/右优12/tie85/unknown12，B1为左优10/右优32/tie72/unknown14。
两面板均没有已知左右方向相反的answer/delivery比较；新增答案方向主要来自原delivery粗粒度tie，
分别23和25个。27个完整答案对应旧材料代理的partial，主要涉及宽范围问题的合法替代证明、
聚合改进值或代理要求的额外清单；不能把代理定义差异自动称为训练目标的因果缺陷。
字面相同packet的配对分别4和13个，B1其中3个仍产生不同方向的答案偏好，体现单次生成变化。
这些是TRAIN首次读出的事后诊断，没有重跑或挑选较好答案，没有启动answer-first补训或扩大样本。
来源说明及对应实际readout见`b64-answer-review-full.json`和`b64-postfit-quality-diagnosis.json`。

两臂均使用相同完整菜单、状态、旧400行、E1-u16起点及E3实际纯delivery配方：
quality-tie、component-sum、replay accepted-set权重0.25、encoder/head LR 5e-6/1e-4、
shared_actions、full参数、BF16单卡、micro2/窗口16。
每臂528个slots，两次实际暴露，1,056行、66更新，预定检查点0/17/33/66，
完整输入预算均5,756,552 tokens。最长原生输入11,882 tokens，state/head无裁剪；
这仍不是有效12k上下文的认证。两独立作业分别使用GPU2/3，原账本短写锁保持。

共同训练前评测的操作家族接受率0.778851、纯delivery方向准确率0.949554。
完整66更新均已正常退出，各实际1,056行、5,756,552 tokens；原528个slots各遍历两次。

| 检查点 | B0操作接受率 | B1操作接受率 | B0纯delivery方向 | B1纯delivery方向 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 0.778851 | 0.778851 | 0.949554 | 0.949554 |
| 17 | 0.781510 | 0.781915 | 0.713170 | 0.749851 |
| 33 | 0.786732 | 0.775427 | 0.941741 | 0.842039 |
| 66 | 0.785654 | 0.774003 | 0.910491 | 0.749107 |

按已冻结的非零提名/操作回退2pp门槛/最早tie规则，两臂均提名33；提名不表示采用。
GPU作业区间分别0.534955/0.540089小时，整子进程CPU分别3,072.901/3,097.578秒；
native及客户端残余各计一次。allocated/reserved峰值单列在两臂`compute.json`，不相加。
共同起点的实际GPU完整菜单及两提名落盘模型共93状态评测已闭合。
完整复用索引含136个有效before下较早首绑定，B仅新增5个不同绑定，均完成实际来源/输入绑定和源审。

| 旧32族条件任务 | raw delivery | 共同初始化 | B0-u33 | B1-u33 |
| --- | ---: | ---: | ---: | ---: |
| 完整成功 /32 | 14 | 14 | 13 | 13 |

两臂相对初始化均为1 gain/2 losses，差值−3.125pp，描述性95%区间[-15.625,+6.25]pp。
B1相对B0为1 gain/1 loss，差值0，区间[-9.375,+9.375]pp。
旧面板没有支持新增覆盖监督的任务收益；当前没有B候选采用，也不触发192/256扩量或额外seed。
证据为`b-full-fit-closeout.json`、`b-task32-results.json`及`b-task32-native-agreement.json`。
数据与配方见`b64-delivery-author-guide.json`、`b64-matched-training/plan.json`；
终态审计及落盘菜单准备脚本`close_b_fits.py`已对实际闭合两臂执行。

## 新64族：真实自主Host正在执行

在导出选中的64篇新DEVELOPMENT正文之前，冻结五个方法、完整请求/额度与评分协议：
最强既有简单fixed-prefix、共同E1-u16初始化、B0-u33、B1-u33及旧E3-aggregate-u32研究参考。
E3参考仍未被采用，其原128更新/457 slots与新两臂不同，不能用于隔离数据组成的因果比较。
原生dev容器由解析器读取，但只投影这64篇论文、4,279个Source单元；未导出或语义检查预留确认内容，
未打开native test。新64族从此属于方法选择开发曝光，不是确认集。

fixed-prefix先执行8族，捕获每题实际首次Host前Store/Saver，再对未执行56族按同协议首次运行。
两段均已正常退出，全64族49流程完成、15首次失败；143次HTTP、528,693已知tokens，新增未知用量0。
49个完成的最终输入、15个失败的最后已响应输入分别绑定，共252个原文范围，0未匹配。
全64完整答案已逐题源审：25完整、11不完整、9带无依据内容、1核心错误、15首次失败、3范围未决。
主指标完整25/64（39.0625%），失败与未决均留在64分母；未决问题的范围单列，不强行套用原生答案。
材料为29充分、20部分、12不足、3未决，不能把49流程完成直接当任务成功。
其余四方法使用相同64个真实初始快照，仅覆盖策略/checkpoint，保持原始任务、初始Host上下文与额度。
E1-u16已完整退出：45流程完成/19首次失败，其中15输出截断、4JSON动作格式失败。
154次HTTP、622,629已知tokens，新增未知用量0；45个完成final和19个失败最后已响应输入均已绑定，
321个原文范围、0未匹配。完整回答现已全部源审：25完整、13不完整、5带无依据内容、19失败、2未决。
B0-u33也已完整退出：59流程完成/5首次输出截断，139次HTTP、504,911已知tokens，新增未知用量0。
59个完成final和5个失败最后已响应输入共372段原文范围，0未匹配。
B0完整回答也已全部源审：33完整、14不完整、9带无依据内容、5失败、3未决。
B1已正常退出：53流程完成/11首次失败，含7输出截断、4JSON动作格式失败；
151次HTTP、580,186已知tokens，新增未知用量0；408段原文范围逐字匹配，0未匹配。
B1全部完整回答仍待源审；E3参考已接续运行。实时状态见最新progress。
没有提供检索query、强制检索或改成最后单次Reader；Host自己生成工具请求并完成任务。

| 新64族自主Host | fixed-prefix | E1-u16 | B0-u33 | B1-u33 | E3参考 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 来源作者确认完整 /64 | 25 | 25 | 33 | 待审 | 待执行闭合/审查 |

E1相对fixed-prefix为8收益/8退步，差值0，来源族描述性95% bootstrap区间[-12.5,+12.5]pp。
B0相对两者均为13收益/5退步，差值+12.5pp，区间[0,+25]pp；各方法仅一个首次随机轨迹、训练seed0，
尚未完成五方法选择、复现或独立确认，不能归因于单独的数据组成因素。失败与未决继续留在64分母。
收益/退步指来源作者完整认定的变化，未决项没有被宣判为已知失败。

逐题来源说明在结果后编写，作者非独立、非盲审。原文补核发现预处理论文的附加实验确有第四层，
并非初述三层与结论四层相矛盾。通用“完整、忠实且回答实际问题”原则保持；具体范围解释均有旧说明及修正记录。
对三个依赖宽范围解释的题目（模型描述、示例实验与正式benchmark、视觉语境检查与空间对齐），
另做统一不计完整认定的事后敏感性分析，所有方法仍保留64分母：B0为30/64，其余两者25/64，
差值+7.8125pp，区间[-3.125,+20.3125]pp。这不替换主指标，也不是独立复核或确认。
证据为`task-dev64/source-author-reviews.json`和`task-dev64-paired-selection-progress.json`。

既有官方QASPER evaluator另行处理三个闭合方法的原样完整字符串，Answer F1分别0.077415、0.080213、
0.094763，未提取短答案、重写unanswerable或修复失败。它只是选中开发面板的字面一致度，
不能替代完整任务成绩，也不是全量原生benchmark或原生整段Evidence F1。

首8族实际5流程COMPLETED/3FAILED，20次HTTP、84,582已知tokens，新增未知用量0。
三次输出截断保持首次失败；5个完成的最终provider输入及3个失败的最后已响应输入分别绑定，
共32个原文范围逐字匹配，0未匹配。失败请求的输入可证明材料可见，不代表完成最终回答。
成功结果显式记录语义receipt为0，失败结果省略该字段，因此另行核对实际Store/Saver/业务数据库。
fixed-prefix、E1、B0与B1共256个终态均已只读审计，包括50个失败状态；每方法4,343个初始Source值
逐值保留，含64个当前任务Source。四方法分别新增49、45、59、53个正确标为assistant的最终回答Source，
没有新语义记录，world及业务表与共同before相等，Saver末checkpoint消息与实际结果逐值相等。
临时writer输入映射、操作journal与Saver变化明确保留，不把它们称为语义提交。
这只核对独立论文任务的状态行为，不认证答案事实，也不代替D包的更新/View/业务功能实验。
证据：`task-dev64/protocol-before-body-export.json`、`task-dev64/plan.json`、
`task-dev64-answer-review-closeout.json`、四方法`SDK-state-audit.json`及完成/失败输入审查包。
来源作者并非独立或盲审；通用评分在正文投影前固定，逐题来源说明在实际运行后编写。
宽问题可接受其他有依据的证明；原生yes/no冲突、caption缺数值、全研究缺失与单包未取得分别处理。

接口诊断发现：B64的64个给定请求均为通用purpose，无required_points；
新自主首8族实际发出12个工具请求，其中9个带read_goal及共21个required_points，3个省略read_goal。
这是未配对的输入分布差异，不能解释同协议旧32族的B回归，也不证明因果。
若后续机制修复有依据，应在合法TRAIN来源取得实际Host请求及合法已知证据，而不是把新DEV状态用于拟合。
已有按请求选材规则和同before执行器继续复用。详见`request-interface-diagnosis.json`。

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

B64首次启动的fixture仍是自主请求格式，给定请求入口缺少`retrieval_request`，在任何模型/HTTP调用前退出。
协调器还因系统Python3.10不能导入StrEnum而未写完状态/成本；实际进程退出及零调用已另行核对，
已测wrapper CPU列pending，丢失的整进程/启动CPU为unknown不填0。
修正为既有native-question适配器、独立given-v2数据与输出，协调器使用项目Python3.11并在计量前
先保存实际终态；没有重试已执行任务。此次也说明“配置prepare通过”不能代替请求fixture入口兼容性验证。

B64面板编译首次直接使用CUDA Python，漏用原依赖/attention wrapper，因缺少langchain_core在
导入阶段退出，尚未创建输出或调用模型。修正为现有`train_with_declared_attention.py`后编译成功，
未升级环境或更换backend；失败日志、计时和`b64-preparation-import-reflection.json`保持。

本轮复用索引遗漏E3的22个已完成绑定，导致一次不必要的A重复，已按更早首结果修正统计；
这也验证相同材料的单次生成变化能使完整成功计数上浮，不能选择较好后答。
新自主输入分析最初混用了条件读出字段、成功结果receipt字段和“完成final输入”定义；
按已存在的自主格式及E4失败输入补充协议修正，保留三份失败日志/计时，未重跑任何模型。

SDK审计首次把结果导出的`sources`当成原始Store行直接比较，发现实际`sources()`会按语义历史
派生`formation_status`。改为按原生投影核对，同时继续逐值检查原始Source未变；失败计时保留。
安装的serializer构造参数与导入警告所提参数不一致，按实际签名使用原有默认构造，未升级依赖。
B64事后join首次误把两段的局部record_index当全局下标，改用384个唯一完整readout路径及来源匹配。
进度写入器首次读到自己尚未闭合的GNU计时文件；改为在该计时结束后写入摘要，保留失败成本，
没有将缺失用量补0。以上均为离线分析失败，没有模型重试或原结果替换。
另一次B0状态审计被提前并行发出，所依赖的绑定结果清单尚未写出，因此缺文件退出。
改为等待绑定正常完成后串行审计，所有64个状态核对通过；失败计时保留，未增加模型调用。

## D：先核对来源资格

旧E5继续保留8个已曝光开发族、两流程各5请求的来源与首次结果。现已按原有两份背景划分，
预留32个本次D实验尚未使用的TRAIN背景：14个Update、18个TrajectoryOps，与旧8族不重合。
选择只使用既有operation_type与背景身份，没有因答案或方法表现筛选；新选正文尚未投影，方法和请求时序未冻结。
这些背景已有TRAIN及来源审查/训练曝光，MemOps本身为生成的基准对话，不能称为全新、自然采集或独立确认数据。
没有重分配calibration/test，也没有为凑数量打开预留确认内容。下一步先检查旧8族真实合法菜单与
View后继续READ的功能切片，再固定三方法、2048预算与同一来源到达/请求时序，复用已有来源切点并逐项核对自然更新。
来源身份及曝光边界见`d-update32/source-reservation.json`；当前没有D新模型执行。

已在旧generated-2048实际捕获中找到9个成功REFRESH_VIEW后的状态，分属5个旧背景。
原CacheMemoryPolicy源码与旧运行时逐字相同，9次均选择HANDOFF，但现有菜单仍允许READ。
按已有`source_relevance`对控制器实际已见内容提名，每状态仅选一个现有READ绑定，
在原冻结运行时的真实before副本中执行READ，再按既有首动作干预终止为HANDOFF；没有新建View、
重跑前缀或生成Host回答。9个首packet均为View＋原文，材料拒绝0，新增HTTP/本地模型调用0。
9段原文均逐字绑定到未改变的Source，原View解释文本不变；定位别名和共享capture metadata按
原生`project_packs`投影核对，没有将导航位置当作已打开的原文。

这些READ中3段是user、6段是assistant，角色保持原状；词汇相关不等于用户原话或已证实事实。
这个功能切片没有证明View事实正确、Host任务收益或旧View的USE_VIEW复用；仍需实现可选增量策略，
核对实际已知证据与clean/pending旧View，再固定三方法共同builder、2048预算和请求时序。
旧8完整流程与32个新增TRAIN背景的正式执行、来源审查及同信息对照均未由此完成。
实际packet与边界记录见`d-update32/old8-native-read-probe-closeout.json`。

初次把原始缓存的绑定/metadata直接与packet比较时得到不同；补核原生投影后确认其会精简引用别名、
改为当前原文短标签或`support_not_opened`，并拆分共享metadata。现已分别验证解释文本不变和
定位/角色/时钟投影一致，旧比较报告保留，没有重跑读取或模型。

## 全范围剩余要求

| 里程碑 | 当前证据 | 仍需执行 |
| --- | --- | --- |
| M0 | 两单卡32更新、统一 FP32评测与落盘重载闭合 | 后续变更若引入新风险，再定向验证 |
| M1 | 条件覆盖修复、57状态inventory、8新绑定及源审闭合 | 其余缺失READ保持清单，结合决策空间决定必要补采，保留tie/loss/unknown |
| M2 | A/B旧32、C8、B64全部384答案闭合；新64三方法全审25/25/33，B1执行及四方法状态闭合 | B1/E3各64答案审查、E3执行闭合；完整五方法任务/成本选择 |
| M3 | 旧A15/15、B13/13无组成收益；新64有B0开发候选信号，解释范围及随机性未隔离 | 完整比较后决定保留的seed1/2及必要机制检查；不自动扩量或采用 |
| M4 | 旧E5首结果保留；9个原生View＋READ packet闭合；32个D新增TRAIN背景仅预留 | 可选增量策略、旧View/已知证据、同信息对照、旧8和新32正式流程；有预算机制依据再补1024 |
| M5 | 新64任务开发族已导出并执行；256确认族仍仅身份预留，最终候选未冻结 | 完成开发选择；冻结确认；LME451/Mem2Act400；完整成本、论文图表与可主张边界 |

所有规模和 seed 扩展遵循原计划的信号条件，不把多问题、状态、重复或 seed 当作新来源。
最终允许简单方法获胜；局部 loss、动作准确率和材料覆盖不能代替来源族宏平均 Host 完整成功。
主比较报告 gains/losses、家族 bootstrap 区间及全部失败，不能从旧32族或这个8状态功能切片宣称独立泛化。

所有工作沿原连续账本
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`。
两训练进程退出且无模型HTTP活动后，原v79的75项45.39CPU及本轮38项残余458.5458CPU已各结算一次；
C已计native380.6442CPU先行扣除，P0及A拟合/重载模型成本没有重复计账。
2026-11-05在实际模型空闲后，新增13条离线计时共159.4CPU秒另行结算一次，见
`idle-cost-settlement-v2.json`；此前计时和模型/客户端成本未重复收取。
后续实际空闲边界v3/v4/v5又分别仅结算新增5.63/14.99/5.10 CPU秒；
原生拟合、落盘评测及Host客户端费用由各自owner记录并扣除已计native部分，没有重复收取。
此后新增离线计时仍pending，活动模型期间不结算。B64客户端按动态模型load/predict两个phase
扣除已计部分后记录残余，避免另一卡评测phase污染归属；未测作者工作记unknown，远端硬件/货币成本未测。
GPU单元测试未单独测量GPU-hours，不能计为0。P0拟合/重载及C的native CPU已经记录，
后续idle结算须从整客户端成本中扣除这些已计部分；不得重复计账。
P0/A训练器进程内时钟之外的解释器/依赖导入及CUDA admission未单独计量，不填0。
新B拟合owner测量整子进程CPU，并在终态扣除其本臂已计native CPU后仅记录客户端残余。
E1新DEV64整子进程CPU587.1393秒，含已计本地预测405.1912及加载8.6032秒；
客户端残余173.3448秒另计一次。GPU作业占用区间0.731988小时，包含等待Host的时间；
它与HTTP已知tokens分别报告，不等于纯GPU计算时间。新增审查/SDK审计计时仍pending，
活动模型期间不离线结算；作者阅读与未测命令CPU保持unknown非0。
B0整子进程CPU697.7689秒，已计预测512.1397及加载8.2139秒，客户端残余177.4153秒各计一次；
GPU作业占用区间0.564241小时。实际E1/B0均退出后、B1启动前，将新增27条闭合离线计时共15.05CPU秒
结算至原账本一次，见`idle-cost-settlement-v6.json`；失败分析计时包括在内，模型/客户端费用未重复收取。
B1整子进程CPU651.0116秒，含已计预测446.1397和加载8.7188秒，客户端残余196.1530秒另计一次；
GPU作业占用区间0.786338小时。B1及D的9个无生成读取全部退出后、E3启动前，新增14条闭合计时
共59.9CPU秒已在`idle-cost-settlement-v7.json`结算一次。D重放保留旧前缀的逻辑调用/trace，
新增用量由原账本差值确认为0，不能把拷贝的旧vllm响应再次计费。后续计时在E3活动期间保持pending。
实际SDK路径、安装版本和已核对的forward/导出实现另存 `runtime-environment.json`。
本轮没有改变 Product 的公开 Schema/API、权限或 Canonical 行为；没有推送或合并。

开发诊断的独立PNG/SVG/PDF及范围说明位于 `development-figures/`，已完成图面检查；
它们不代表最终论文/确认结果已经完成。
