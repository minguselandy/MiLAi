# WP6：既有实际首响应的工具与Host续接

状态：六条真实工具/持久化/后续Host续接全部完成并逐链核验。
工程源码为`ec34c89d96ecbf6030777b8b23c5dc9773d27ac4`，已发布[PR56](https://github.com/minguselandy/MiLAi/pull/56)。
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

## 实际结果与首断点

[执行freeze](../data/manifests/next-improvement-wp6-continuation-freeze-20260928.json)身份
`cbe6cd028fb70797d78652a75610c38cd3336e31dd0b009fe54c923141a89527`，原freeze文件SHA
`fae5f6ed2712fc87fe182486df270a1d57c84d91f09670e76b66d9ba7eb51912`。
[逐项结果](../data/manifests/next-improvement-wp6-continuation-results-20260928.json)保留实际参数、
ID、回执、最终回答、trace/database哈希和Root离线评分。六条都只有一次预约和一次后续Host调用；
无重试/替换/基础设施或格式失败，每条消息容量从已发生1到2。

| 冻结顺序 | 实际持久错误 | 严格任务成功 | 首响应＋续接generation tokens |
| --- | --- | --- | --- |
| partial/original | item_key单数crate | 否 | 2566 |
| distinct/source_title | quantity=3，应为4 | 否 | 3230 |
| partial/raw_sources | 无；五件、正确完整key，真实预约后标签失败 | 是 | 2171 |
| distinct/original | quantity=3，destination=S-2缺storage | 否 | 3231 |
| partial/source_title | item_key附加计划括号 | 否 | 2605 |
| distinct/raw_sources | quantity=3，应为4 | 否 | 2648 |

Observed：错误五提案均忠实提交，后续回答未纠正；唯一正确提案完成要求的部分成功处理。
Expected：按原约定精确对象/数量/目的地执行，真实副作用后正确停止并报告。
实际因果链为冻结输入→原真实HTTP参数→同generation/tool ID的ToolNode→实际SQLite预约和attempt→
原工具回执进入下一次HTTP→最终回答。Root独立只读数据库确认snapshot、journal和receipt逐字段相同，
原完整请求前缀/参数保持，原首响应不重发。这里是合成业务世界的真实工具/数据库执行，不是Product业务。

首断点仍在首响应生成错误动作参数；其后接线没有改错参数或串用户。六条执行忠实不等于任务成功，
严格成功1/6。三条标签不可用均真实保留预约、未重试；六条答案都引用真实ID并报告实际数量与标签结果。
distinct/original的答案把存储S-2写成storage S-2，完整回答忠实性保守记否（5/6），此判断不影响
已因世界字段错误失败的任务分数。其余自然语言复数/描述缩写按冻结rubric接受，但不能修复错误数据库key。
ToolMessage传输status=success也不代表业务ok=true，partial的结构化结果明确ok=false/已有预约。

H1错误参数会直接保留到世界，本切片的五条错误轨迹支持这一观察；H2后续真实回执会促使Host
识别并纠正旧提案，本切片未见支持。仍不能单独区分标题锚定、旧助手/普通memory干扰与来源增量消费；
raw_sources同时改呈现header和去掉派生State，两个arc共享历史，均已暴露，temperature=0也非重复确定性保证。

决定：停止把标题替换当可用修复，Pivot到已独立开发的写入责任诊断；不继续同题措辞微调，
不加实体同义词/gold key规则。保持严格CRUD和实际回执接线，下一最小比较为一个第二增量加一个
无变化前缀的三种责任配方。仅该WP6条件诊断完成，未证明稳定unseen收益，也不关闭整个计划。

## 完整费用与复现边界

本次续接新增6次Host、8846 generation tokens；9次前态索引embedding共327 tokens。
327全部属于恢复输入前态，运行阶段没有memory搜索/写入；各owner种子保持不变。
首响应已付6次/7605 tokens只合计一次：本切片共12次/16451 generation tokens、327 embedding tokens。
按两arc合并，original为5797，source_title为5835，raw_sources为4819 generation tokens；
这不是压缩效果或单一State消融的因果费用收益。没有Judge或第二模型调用。

连续账本现在2780次生成、3436784 generation tokens、19073 embedding tokens，SHA
`0caa21c1e6e483af4863808c382d97057e5d473b985ef783dc35c4e058e5d52d`，历史sealed成本未清零。
实际Host HTTP wall合计4.908764秒、embedding0.565357秒；独立进程启动和SQLite观察开销另保留。
observer transactions/CPU/wall在机器结果逐条给出；前态/快照的未绑定Store操作不是Host语义工具操作，
此切片未测它们的独立Store CPU/wall，不用observer统计冒充完整数据库性能。

复现使用上述提交的`tools/run_frozen_action_continuation.py prepare/run-job`，原R1的config/inputs和
保存的`run/jobs/*.json`，本目录公开prestates，独立新run/arm/runtime-root，原绝对连续budget路径。
prepare后按六job顺序run-job；仅通过环境注入已忽略DSN。具体原参数与全部源码/锁/响应文件哈希见freeze。
精确重放同一首响应需要保存的ignored实际job文件；重新生成R1会产生新的实际响应/ID，属于新执行，
不能冒称字节复现。原完整私有轨迹、数据库和build仍不进Git；本结果公开精简实际字段和证据身份。

## 该入口提交的实际CI

[Fast36333288437](https://github.com/minguselandy/MiLAi/actions/runs/36333288437)及最终gate108661104754成功，
测试merge `99d6d036daced715ea5e3f3fcf452104706c7c16`。core5114 passed/142 skipped/14 deselected，
606.42秒；独立71项包含在5114内。foundation168 passed/1 deselected，其中新6项续接测试真实执行；
external、边界、conformance及远端wheel/sdist构建成功。未选任务的skip不算通过，main未合并。
这些是ec34c89工程检查；后续结果文档是实际实验结束后补写，不能冒称已包含在该提交制品中。
