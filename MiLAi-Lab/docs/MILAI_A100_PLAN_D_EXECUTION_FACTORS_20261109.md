# 原计划D：执行与分因素证据的补充核对（部分）

D的五个新原生任务已经核对：旧8族的两个新策略各80轮、新32族的三策略各320轮，共1120个
真实连续Host首轮；更早baseline80复用，不计为新增执行。这里关闭执行/分因素这一部分，
known-View9、旧输出42、旧8功能切片/生成View后READ探针与D逐项合同仍需合并核对。
[机器摘要](../data/manifests/a100-plan-D-execution-factors-audit-20261109-v1.json)保存实际路径；完整763行目标仍active。

## 不可变状态、实际操作和完整输入

1120轮均读取各轮真实immutable before/closed-after Store、Source、Saver与应用状态，
共19292次旧Source值比较。既有原文正文/角色/时钟不变；
890个实际完成Host答案新增Source继续保持assistant身份。
Saver消息逐字等于实际结果，应用/world无业务写入。终止HANDOFF选择与operation-result事件
分别计数，实际ToolMessage回执与原生已知准入错误不补造事件。

| 实际E3输入范围 | 真实轮数 | 已执行NN forwards | 输入tokens | 最大实际长度 |
|---|---:|---:|---:|---:|
| 旧8族 | 80 | 185 | 1051651 | 8352 |
| 新32族 | 320 | 784 | 4604680 | 9208 |

969个已存在NN输出的完整before、全部原合法动作/完整参数、投影、head ID顺序、有限logits/
probability、argmax、未截断均核对，无新模型/tokenizer/GPU/HTTP执行。旧finite验证器的
历史formal_planned_positions字段固定为320，原始新报告保留该字段；本摘要按真实bound80
报告旧8，不把它改写成320轮。不能将单次最大输入长度解释为有效长上下文语义能力。

新32族全960首结果的原配对报告已复现：view_cache67/320、增量65/320、E3 95/320。
来源族bootstrap、失败分母、外生Source正文/role/到达顺序与实际identity/捕获clock差异均保持。
这仍是条件描述性开发结果，不是严格匹配全部初始Provider请求和内生历史的单一控制因果效果。

## 三个因素的实际边界

32个既有TRAIN来源的native对话投影逐字复现，768个Source对象，
29份既有作者合同＋3份当时新作者合同，64流程/每流程5轮。所有支持Source止于相应真实user cut；
Source的未知发生时钟保持null。运行histories只有公开任务与实际来源，没有期望答案、操作或评分字段。

| 每方法实际位置 | 轮数 | 解释 |
|---|---:|---|
| initial | 64 | 第一真实native用户cut |
| same-sources | 64 | 无新增外生Source；内生Host/Tool历史仍可能增长 |
| additional-arrival | 64 | 一条明确构造、对目标无关的cable位置Source |
| intermediate-arrivals | 64 | 下一native用户cut，含相关补充/更正/状态和范围变化 |
| final-arrivals | 64 | 第三native用户cut，含计划/撤销/不确定性等语义 |

additional-arrival保持目标、支持集和答案范围，只增加一条构造无关来源；它不等于多规模历史增长曲线。
自然middle到达并非全部无关，也不是31次相同当前值翻转；A02中间到达对任务目标无关，单独保留。
两个流程中128个请求明确追加原话要求，其余公开query按预定合同保持。native容器虽携带其他
benchmark字段，投影和Host输入仅用原对话role/content/来源键；本次不以native答案重新评分。

五个实际配置均与原input-freeze逐字相同；共同extractive builder、2048返回额度、24共享调用
额度和原Host配置保持，增量路径配置一次READ。Driver完整planned顺序/真实首结果、连续历史/
自主Host、非given/native probe核对。学习轨迹里REFRESH_VIEW实际可选779次而未选择；
USE_VIEW在自身轨迹未出现可选项，不能从未选推定已经学会View复用。

增量路径三个实际USE_VIEW均位于initial，原始known refs/new/pending为空，随即HANDOFF、
没有补充READ。相应原机制报告逐字复现；这不是旧View加后来相关到达的完整任务证据，
因此known-View与旧输出控制仍单独审计，不能由这些选择计数替代。

## 版本差异、失败保留与尚未关闭内容

本次13个验证入口包含新增的旧8完整输入审计。SDK旧报告有历史audit_reflection文字差异及
增量报告额外的历史说明字段；三份早期操作报告则早于后来新增的“准入错误实际回执”字段。
已逐项验证旧报告全部科学字段，新增零错误回执字段独立验真；没有修改旧报告、删Source检查
或把元数据差异算成原实验失败。三次审计比较失败的GNU计时保留。

发现这个共同版本问题后，最后一次处理直接复用前次已完成的7份只读验证输出，并检查旧字段/
明确新增字段；只执行剩余6个入口。JSONL按物理文件行读取，反向替换能恢复原验证器完整源码，
原始Source/模型/输入/首结果均未变化。所有普通/失败/图表/报告CPU待实际idle138支付；
原Mem2Act owner运行时不离线读写账本，也不重计已付D原生/NN/load/child/parent。

完整D逐项报告、known-View9与旧输出42的实际控制、旧8功能切片/生成View后读取探针，以及
整个计划的Mem2Act400×2/全项目成本/论文图表/最终763行完成审计尚未由本补充关闭。
Source作者仍为实施助手，非独立人类或盲审；条件开发信号不能升级为采用结论。

- [原执行验证器与完整NN输入](../tools/audit_a100_plan_d_existing_execution.py)
- [Source-only时间线、真实配置与分因素](../tools/audit_a100_plan_d_factors.py)
- [既有D Source/View/操作综合](MILAI_A100_D_SOURCE_VIEW_OPERATIONS_20261107.md)
- [既有known-View与旧输出控制](MILAI_A100_D_KNOWN_VIEW_OLD_OUTPUT_CONTROLS_20261107.md)
