# WP3/C3b：同一前态下的写入责任比较

状态：源码和协议已冻结，六条完整实际轨迹已执行并评分；该发布源码的实际远端CI已通过。承接[共同工具合同](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_CONTRACT_20260927.md)。
默认旧运行路径保持可用；本切片只有显式配方才启用新策略。

## 问题与竞争解释

Observed：历史第二次增量后State正确为四件、普通memory仍可能为三件，实际行动也用了三件。
H1：两条语义维护路径及不同完成时点造成矛盾副本；H2：即便交付相同正确前态和真实来源，
模型仍可能选错身份、重复消费增量或漏写，责任合并本身不足。WP6已表明改标题不能稳定修复。
固定当前存储表示和前态，先比较责任；不同时改成引用化State、patch、A/U或新提示词系列。

## 明确配方

- host_both：正常Host工具循环可读写两库，关闭自动语义维护。
- boundary_both：新用户观察先由边界维护两库，之后Host读取并回答；Host保留显式维护触发入口，
  返回真实维护回执。触发理由是助手提案，不自动升格为用户事实或业务成功。
- overlap：Host正常循环读写普通memory并回答，随后turn_end边界仅维护State，使用实际Host回执。
  不在每次ToolNode后重复自动维护；Host答案先于该轮State维护，作为明确时点差异报告。

三组共有严格CRUD、真实身份、相同合法原历史/事件和两库当前正文。
工程核对发现旧State视图仅正文而无ID，不能让模型凭空发现update/delete目标；新配方统一附实际
State directory（id/title/revision），旧LSA默认视图不变。这是三组共同的CRUD发现信息，
不是给候选的额外答案或新索引。完整前态是本条件诊断的
共同输入，不将额外预交付只给候选。READ/SEARCH返回真实内容后可以继续提案；空边界提案仅
表示维护NO_CHANGE，仍需Host完成回答。Host最多12次、control最多13次/公开消息，实际全部计费。
普通Host State调用不冒称具有边界batch重放保证；同文本不同真实事件仍分别处理。
Host正常完成回合后仅机械确认该回合实际处理的来源，避免下轮把旧增量继续标成新观察；
中断/失败保留pending和部分副作用。ack不证明记忆正确，评分仍独立检查内容和事件状态。

## 最小输入与评分

一个已暴露Cobalt历史arc的两个前缀：第二次真实增量、只读无变化。两者均采用各自请求之前的
实际一条memory和一条State，初始当前数量均为三；原真实ID和owner保留。
一个前缀的合法raw history短于另一个，是各自历史状态；同前缀三策略完全一致。
共享来源事件明确区分pending与已确认，不能把所有旧用户增量都当新观察。

冻结后六个job各自完整跑到回答/维护终态，读取续接次数不预设为八次生成。
第二次增量须原ID更新到四、保持目的地和包装、不生成重复计划；两库分别评分及检查一致性。
只读前缀不得改变语义正文或revision；事件ack单列，不能冒充语义变化。
两前缀均禁止业务动作，Host回答须与实际持久结果相符，不以声称已保存代替实际写入。
基础设施/格式错误、合法拒绝、错误或不完整维护、无谓改写、正确维护分别报告。

## 冻结、费用与后续决策

Root在实现/局部检查通过后冻结源码、输入/前态、scorer、各阶段合同、顺序、隔离与成本起点。
每job独立namespace/checkpoint/world，失败不换样本、不挑最佳生成；所有准备embedding、READ、
修复提案、Host及control生成入连续账本。总费用比较使用完整回答加维护终态，不能拿边界单次
NO_CHANGE提案和Host完整回答相比。角色/工具呈现/阶段时点的共同变化按系统策略比较解释。

必要更新和无变化反例同时出现可用信号，才选择一个候选与overlap进入短CRUD/owner/临时要求/
实际动作和部分失败恢复的连续验证。若三组仍失败，保留简单默认，Pivot到具体断点；不新增仲裁Agent。
本切片一个arc、六条件轨迹，无统计胜率、unseen或跨模型主张。引用化State仍非默认后续开发。

## 输入冻结

[六job输入](../data/diagnostics/next-improvement-wp3-writer-policy-r1/inputs.json)、
[共享配置](../data/diagnostics/next-improvement-wp3-writer-policy-r1/config.json)和
[离线评分](../data/diagnostics/next-improvement-wp3-writer-policy-r1/rubric.json)已固定。
明确初始业务库为空且标签不可用，两种当前任务都禁止业务动作；若错误调用仍执行并记录实际副作用。
新增字段将隐含默认前态写清，不用预期答案回填历史。正式prepare和源码/工具/顺序identity须在实现及检查后冻结。
运行时只用inputs/config，rubric与metadata评分条件不交给Host或controller。

## 工程冻结与验收

[精简检查回执](../data/manifests/next-improvement-wp3-writer-policy-checks-20260928.json)
固定11个源码/CI/配置文件哈希及输入、配置和rubric哈希。终版定向16项通过；此前受影响相邻109项、
core协议71项通过，准确源码阶段分列，不能将重叠测试相加为独立场景。目标静态、149源码归属矩阵、
两个边界与diff/新文件EOF检查通过。离线mock及本地SQLite检查没有真实Host、embedding或共享Postgres调用。

初轮构建本身成功，随后发现同回合再次触发维护时未交付先前boundary执行回执；最小修复使原构建
不再是终版，已保留其身份并执行第二次必要构建。终版wheel为
`2d2ca88da91b5eff94695f7220a76a4f8e304f8e5107d85aa8fa03242850d23e`，sdist为
`e7512a07133bf36014e90e36686d67921a54018daea6c0969cd92c1393d55bea`。
本段及公开回执是在终版构建后补齐的元数据，不声称较早分发包已包含这些新增文字。

边界的真实成功/错误回执在同一回合后续自动/显式维护中保留；这是有限回合上下文，
不保证跨进程续接，也不保证普通memory写入严格一次性或两库事务。
预发布零模型prepare六job通过；其HEAD仍是父提交，正式实验将在发布后的独立detached checkout
重新prepare并冻结identity，不能直接沿用预发布身份。实际远端CI另记，不冒充已完成。

## R1实际结果（07aaa3c，2026-09-28）

已发布[PR57](https://github.com/minguselandy/MiLAi/pull/57)，head
`07aaa3cfc0bec3f914df00a614812aafec967b41`，base为ec34c89；未合并main。
Root使用独立detached源码完成六条轨迹，源码与[执行冻结](../data/manifests/next-improvement-wp3-writer-policy-freeze-20260928.json)
一致。prepare identity为`e57a3558d82c4744c54def792fbe52dfb172abbc3df9d8c339d4e730145f4ea2`，
freeze SHA为`3fdf37be3a7ee19e1b2894fb82ac606a5cff216c14289aa76267f7595f28d5f0`。
[逐例结果、实际费用和核验](../data/manifests/next-improvement-wp3-writer-policy-results-20260928.json)
保留失败、回执、pending及各层测量；运行时未读取rubric，无Judge。

| 策略 | 无变化 / 第二增量严格通过 | Host calls/tokens | Control calls/tokens | 合计generation tokens | embedding tokens |
| --- | --- | --- | --- | --- | --- |
| host_both | 是 / 是 | 4 / 11629 | 0 / 0 | 11629 | 75 |
| boundary_both | 是 / 否 | 3 / 8179 | 3 / 9349 | 17528 | 50 |
| overlap | 是 / 是 | 3 / 7185 | 2 / 6236 | 13421 | 75 |

严格合计5/6，但单位仍是一个已暴露arc的两个前缀、六条件完整轨迹，不是六独立样本。
三组无变化均保持原State正文/revision及普通memory，回答三件/S-2/fiber正确。
Host双写与overlap增量均把原两条实际ID更新到四，State revision2→3，来源保持且没有重复记录。
所有业务SQLite reservations/attempts实际为空，无业务调用。

每条实际Host请求均核对了工作视图字节，全部control请求保留同一前缀raw history/真实源事件；
Host provider receipt ID与instrumentation SQLite请求记录一致，所有HTTP 200且usage已知。
两种维护职责虽具有同样当前前态和合法来源，仍有角色、工具呈现和时点差异，是系统策略比较。

## 失败链与最小后续

Observed：boundary增量的首次实际HTTP回答只给两个update的action/id，均缺content。
普通memory接口把默认None实际写入原ID并回updated；State接口拒绝缺正文更新。
Expected：两库都准确改为四；不完整更新不得擦除原正文，也不能以局部成功声称全部完成。
首个语义断点是缺正文提案，首个破坏性程序断点是接受默认None写入。

Host实际收到了PARTIAL_REJECTED、原回执及当前null memory后调用maintain_records。
后续control确实收到先前success/error回执与null记录，却只修State为四；普通memory仍null。
Host最终声称计划已增加一件，未满足冻结评分中的普通memory实际保存要求。
用户增量事件被ack，但新维护ToolMessage仍pending；两者单列，ack不证明语义正确。
没有HTTP/进程/容量失败；这次显式修复调用和失败写入全部保留计费。

竞争解释包括：可选schema允许模型只生成action/id；或者adapter/parser丢了正文。
实际原始HTTP字节排除了后一解释。实际局部成功及正确State可能影响后续修复选择，
但一条轨迹不能证明这种认知归因。该缺口与职责比较混杂，不将其简单归为boundary天然较差。

最小通用修复另立严格CRUD后续提交：create/update缺失或null正文返回错误且不写，
delete仍允许省略，native默认模式保留；同步/异步及Host/boundary共享入口做机械复现。
不据本题微调提示词，不替换或重跑六条R1。继续选择host_both作为最小职责候选，与overlap做
后续形成、临时要求、owner、复用、真实动作与部分失败恢复比较。boundary此轮Pivot。
这不是稳定质量、跨模型或完整方法收益结论。

## 成本与测量边界

新增15次生成、42578 generation tokens、8次embedding共200 tokens；其中150为六份前态索引恢复，
50为两次实际普通memory正文更新。Host为10次/26993 tokens，control为5次/15585 tokens。
HTTP wall合计generation16.282259秒、embedding0.490770秒；不等于独立进程启动或完整服务计算成本。
连续账本为2795次生成、3479362 generation tokens、19273 embedding tokens，SHA
`fea3eca7e56946cf09ea9b044255d31e76ee1269081994fcc7f66307e726ec54`；旧sealed history逐字段未变。

两前缀合计host_both比overlap少1792 tokens（约13.4%）；只看增量时却更贵9045对8200。
这体现任务组合与维护时点影响，不是生命周期20%节约，更不能当压缩收益。
当前接续既有前态，不含原始形成费用；完整C_build+C_maint+ΣC_use须由X5另测。

State bank计数含seed/事件/meta/观察；普通memory扫描与observer各自CPU/wall/逻辑字节单列，
重叠时间不能直接相加。自动boundary和turn_end操作不一定有绑定的Host observer记录，
实际工具回执与后续Store读回仍保留；普通memory写入的独立CPU/wall尚未单测，不补零。
逻辑序列化字节不等于物理I/O；没有新增持久索引或依据调用数猜GPU成本。

复现使用该commit的`tools/run_writer_policy.py prepare/run-job`及公开inputs/config，注入已忽略DSN，
新run根与namespace、相同冻结顺序、真实HTTP并发1。原attempt禁止重放；后续验证须独立新run并披露曝光。

## 实际远端CI

[Fast36335918071](https://github.com/minguselandy/MiLAi/actions/runs/36335918071)与最终gate108667751104成功，
实际测试merge为`62e0f607f9395b1b601a94a274c5cf36e29fc110`，并非合并main。
core5114 passed/142 skipped/14 deselected，350.48秒，71协议已包含在5114中，wheel/sdist通过；
foundation184 passed/1 deselected，含16项新writer-policy检查，external成功。
未选中的Product/archive/tree identity显式skip，不算通过。原预发布回执及构建身份继续保留。
