# v5 V7 单一材料呈现候选与条件性验收 R2

状态：SOURCE_CHECKED_INPUTS_FIXED_NOT_RUN；尚无R2真实调用。
[17项窄检查和默认字节对照](../data/manifests/next-development-v5-authority-r2-checks-20260928.json)已通过，
Root核对源/config/log哈希；不为发布重跑。
授权来自active v5 Goal及[R1真实失败](MILAI_NEXT_DEVELOPMENT_V5_PROSPECTIVE_R1_RESULTS_20260928.md)，
不是原计划DRAFT状态或旧阶段恢复。R1完整分数和失败保持。

## 唯一候选及因果边界

Astra xhigh只处理H的具体困难冲突，Root采纳其单一最小候选，由Sol xhigh实现。
旧值同时存在于user/tool proposal/assistant，不能把因果只归某角色。
当前用户已明确要求当前durable，继续扩写权威提示依据弱，因此本次不添加时序或优先级措辞。

`memory_boundaries.memory_placement`只有`system`和`current_request`，缺省system保持旧行为。
候选从首system请求副本取出唯一`[DURABLE MEMORY]`完整块，原样放到最后一个真实user请求副本的
`[CURRENT USER REQUEST]`标签之前。只移动一份数据材料；原Human、checkpoint、历史、ToolMessage JSON、
工具catalog、Memory内容、BOUNDARY_PROTOCOL和working refs不变。材料不是新的用户声明或事实真相。

现有聊天模板不允许非首位system，所以此变更同时改变**位置和承载role**；不能宣称纯位置因果实验。
query始终来自原Human；all/query/attention/empty候选及容量检查必须使用最终实际布局。
不新增controller/reviewer/selector、持久状态、强制read、输出checklist或自动补答案。
服务、thinking、temperature、max_tokens、capacity、12调用上限不变，Root真实HTTP并发1。

[42条冻结请求离线费用](../data/manifests/next-development-v5-authority-r2-offline-cost.json)用原tokenizer核平
provider input usage；单份材料按候选算法移位后，每条token差均0，合计仍58,135。
此结果只证明这批相同字节材料的输入token开销不增，不证明新轨迹调用/输出总成本相等或语义改进。
V3 JSON空白候选仍不部署。

## 阶段一：四次小范围完整链路对照

使用原H前三条完全相同的用户输入，附加一条反向历史问题：询问本会话最初确认的旧数。
[输入、12义务及顺序](../data/diagnostics/next-development-v5-authority-r2/diagnostic-order.json)在调用前固定。
四个隔离job按`system rep1 → current_request rep1 → current_request rep2 → system rep2`串行。
每job均重新真实形成6→同ID更新9→回S1问当前9→仍在S1问原确认6。
每条最多12生成调用；可正常调用既有合法读工具，全部费用计入，不截断为虚构已完成答案。

Astra建议固定HTTP前缀的8次生成诊断；Root选择复用正式persistent runner的4次完整脚本，避免新增诊断执行器。
因此前缀、UUID和生成轨迹各自真实产生，**不是相同HTTP前缀控制**；重复不是独立样本，差异也不能唯一归为位置。
所有实际形成/更新/原历史/当前HTTP都须核查；若前段未成功激活冲突，不能把最后正确答当通过。

进入阶段二需同时满足：

- 候选两次当前值均9，两个反向历史问题均6；
- 两次持久变化、无误写/无业务动作全部通过；
- baseline当前值少于2/2通过，才有继续检验该候选改进的证据。

baseline若2/2当前也成功，本轮比较证据不足，不能据R1单次失败接受runtime改动；
候选若仍失败或破坏历史控制，不继续换词、调位置或重复直到通过。
重复的成功不覆盖原R1失败；每次首尝试、失败和所有费用都保留。

## 阶段二：预先固定的条件性完整回归与新内容

在任何R2调用前同时固定[14job顺序](../data/diagnostics/next-development-v5-authority-confirmation-r2/execution-order.json)。
只有阶段一共同门槛满足才prepare/run这些job，不为未满足条件而自动扩大实验。

先在候选上完整重跑R1十脚本（均已暴露，旧133义务不改）；然后两个新脚本分别做baseline/candidate对照，
顺序counterbalance。新内容在候选首次语义评价前撰写，与旧冲突任务族相关，不称独立用户holdout。

- `reversed_count`：新事项12→4，同ID更新后回旧session，当前回答须一句且以COUNT:开头；随后问最初确认的12。
- `revised_location`：新事项locker L-2→cupboard D-9，回旧session问当前地址；严格两行LOCATION/当前地点；随后问旧地点。

这两条新当前约束与数值反向/非数字更新一起检验接口通用性；没有在Memory中写入格式。
新问题均明确current或historical目标，不让rubric补隐藏要求。
全部样本有完整用户可见依据，Root离线评估；原10脚本133义务、新2脚本26义务，runtime均不读rubric。

候选验收须12/12完整脚本，task-failing156/156（current55、later34、persistent67），
explicit89/89，两条新当前格式2/2，既有world/assistant与临时/引用/只读/DELETE均无回归。
optional3项仍仅诊断。baseline新两脚本单列，不混入候选分母。14job共43公开消息，候选子集35消息。
这些小样本不支持统计泛化或第二模型家族结论。

若候选通过，可支持§20的小范围基础稳定；仍需V9全要求审计、成本比较/局限/复现和发布才能完成当前计划。
若任何必需类别仍失败，按首断点和预设Stop/Pivot纪律报告，不把工程通过或合并百分比当整体成功。
Attention仅真实检索瓶颈触发，本方案不自动开发它。Product仍NO-GO。

## 冻结、职责与复现

Root拥有这份协议、全部语义数据/评分、freeze与真实调用。Sol拥有唯一源码/必要测试/候选config。
Luna在Root核验窄检查、JSON/链接/哈希后发布精确文件，Root核对远端SHA。
**先发布，再以该SHA执行正式零模型prepare和freeze**，避免R1的Git身份故障。
原prepare/失败/账本不覆盖，不为发布重跑已通过检查。
每阶段freeze锁源码、相关输入/配置/工具/参数、scorer/顺序、helpers、服务只读models与连续账本起点。

各job独立run/Store namespace/checkpoint/SQLite World；H仅按脚本回访自身S1。
同一方法共享公开工具和原始信息，但不共享可变业务状态。每个started目录仅一个正式尝试，基础设施故障先诊断。
当前连续账本起点3036 generation calls /3,845,530 generation tokens /21,617 embedding tokens；实际freeze再次核对。
形成/维护/使用、generation input/output、embedding、Store逻辑观察/bytes、business、control、process/HTTP wall、unknown全列。
私密DSN仅环境注入。测试/离线tokenizer费用不冒充实验Host成本；未知物理I/O/货币成本不估造。
