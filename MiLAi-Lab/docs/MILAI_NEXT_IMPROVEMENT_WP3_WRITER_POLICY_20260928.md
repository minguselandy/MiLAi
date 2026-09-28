# WP3/C3b：同一前态下的写入责任比较

状态：源码、输入与评分字节已冻结，必要局部检查和终版构建通过；尚未冻结发布后执行identity或运行。承接[共同工具合同](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_CONTRACT_20260927.md)。
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
