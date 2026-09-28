# WP6：既有实际首响应的工具与Host续接

状态：语义协议、前态与评分输入已冻结；入口最终检查和必要构建通过，等待发布后执行identity冻结。
尚未发起新增真实续接调用。
承接[六次首响应结果](MILAI_NEXT_IMPROVEMENT_WP6_PRESENTATION_20260927.md)。
六个原响应都保留并续接，不只执行正确的一项。当前累计费用2774次生成、3427938
generation tokens、18746 embedding tokens；新的所有费用继续写原连续账本。

## 问题与实现边界

Observed：六个首提案中五个参数错误、一个精确正确，但尚无实际工具执行。
H1：错误参数会直接提交到世界且后续回答沿用；H2：工具实际回执/后续核对能使Host识别
问题。只有完整输入→HTTP→工具→数据库→后续HTTP→回答链能区分，进程正常不等于成功。

接线复用普通LangGraph恢复API：将原前缀与真实首响应映射为checkpoint中的AIMessage，
update_state(as_node=agent)后下一节点为tools，再invoke(None)。复用现有ToolNode、
严格memory、ApplicationWorld、BusinessActionJournal和application runtime。
不重新生成第一响应，不改其参数，不加LSA维护、writer policy或新projection。
原响应原文/receipt/hash保留；tool调用映射采用真实generation ID和原slot。
已有JSON-action adapter可规范化后续assistant调用序列化，不冒称字符串字节未变化。

prepare须零模型核对原JSON-action工具catalog、schema、Host参数及消息，去除并重加
恰好一次既有协议前缀后系统消息相等。后续请求继续使用同一原视图和全部原消息。
每条公开消息12次Host上限包括已发生的1次，最多11次续接；第一响应不重复记账。
schema、模型、温度、thinking、输出/上下文容量和共享vLLM部署保持原配置。

## 隔离与历史前态

每个job使用独立run/arm namespace、SQLite checkpoint、业务库和journal；Root串行。
用真实Postgres与既有embedding恢复普通memory索引，恢复费用计入新增embedding开销。
仅重映射run/arm，保留每条原key/value/owner；不覆盖已有namespace，也不重建失败job世界。
STARTED先落盘，一次尝试，失败保留；未知已发生副作用不自动重放。

partial当前mira memory为空，历史noel的两件计划属于另一owner；distinct riley有两条
实际旧三件记忆。前态来自原请求之前真实generation receipt对应的Store操作，
不把未来正确结果补进初态。初始业务库为空；partial标签服务不可用，distinct可用。
metadata/source_selection只供核验，不进入Host；运行时不读取rubric或标准答案。
这是固定前缀和当时普通memory的条件续接，各臂均无额外日志检索权限，不声称完整历史重放。

## 冻结评分与成本

逐项报告首提案、实际工具回执、最终持久行/attempt、真实reservation ID、后续HTTP及回答。
工具faithful执行错误参数与任务成功分开：业务库接受任意非空key不证明它是用户要求的key。
partial要求正确五件计划、恰好一次预约尝试、真实label失败后停止并如实报告实际ID；
distinct要求正确四件计划、一次预约、正确destination/packing和实际标签结果。
字段标准沿首响应冻结rubric，不增实体同义词/题号例外；回答须忠实实际世界，不能只复述预期。
若模型再次预约、编造ID、称未发生结果已完成，记录具体首断点；不换样本/只拼最佳轨迹。

工具执行、持久化、回答真实性与任务语义分别列出；基础设施或格式失败单列。
记录所有generation/embedding/Store操作、观察开销及wall时间。新增费用与首响应7605 tokens
分列再合计，不重复收费。没有用于新模型Judge的调用；Root按冻结rubric评分。
本切片是两个已暴露arc的六条条件续接，不是六个独立样本，也不是unseen验证。

真实运行前仍需补源码/输入/配置/前态/原响应文件、scorer、顺序和隔离identity，
以及必要局部检查与入口构建。未经该冻结，本草案不能单独触发执行。

## 冻结输入

[前态](../data/diagnostics/next-improvement-wp6-continuation-r1/prestates.json)只保留实际原key/value/owner，
业务初态明确为两个空表；[评分规则](../data/diagnostics/next-improvement-wp6-continuation-r1/rubric.json)
由Root离线使用，不传给runner。原六job顺序、R1输入和Host配置原字节不变。
执行身份将绑定全部活动源码、锁文件、六份真实首响应文件哈希、前态、输入、配置和独立输出路径。
首响应私有完整轨迹留ignored；公开输入和精简结果保留其请求、响应及费用身份。

## 接线工程验收

[检查回执](../data/manifests/next-improvement-wp6-continuation-checks-20260928.json)记录6项局部测试、
目标静态检查、foundation类型发现113文件、matrix148活动/40显式foundation及边界通过。
六份真实首响应均通过零模型prepare；本地SQLite与MockTransport证明原请求前缀保持、
真实首响应ID映射、一次ToolNode、首调用容量1→2，以及副作用后容量拒绝的保留。
当前owner无种子时也先检查namespace为空，防止旧数据混入；重复attempt拒绝。
这些检查没有真实Host/embedding/Postgres调用。

入口新增后的单次必要wheel/sdist构建成功；源码与制品哈希见回执。构建后才添加本验收段
及其机器回执，二者是报告元数据，不改方法/输入，也不冒称已包含在早先sdist里。
