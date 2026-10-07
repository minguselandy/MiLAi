# 统一记忆功能候选：入口与实际状态

本轮按[多Agent任务卡](MILAI_MULTI_AGENT_DEVELOPMENT_TASKS.md)及用户提供的
[配套规划](MILAI_UNIFIED_MEMORY_ARCHITECTURE_AND_BUILD_PLAN.md)开发。
五个模块已合流到同一MemoryService，父版本为`5c36b28`；本提交加入中央Host、
benchmark、配置及显式整理／完整请求恢复入口。首轮真实Host结果及后续修复分列如下；
尚无最终方法选择或Product准入。原[build-first完整任务](
MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)继续有效。

2026-10-07用户要求合并相关GitHub开发内容；PR83的可选来源工作视图和提案额度接入本候选，
保留当前普通ID及旧实验边界。[整合记录](GITHUB_INTEGRATION_20261007.md)说明冲突决定、
版本和验证；工程合并不表示真实模型效果已验证，`single_verdict_v1`仍未准入。

## 13:06:36 UTC：日期输出位置澄清已集成，真实效果待验证

最新开发源码`4a2d7ba`在402d7d5上集成B的`743c2ded`，仅向既有editor prompt补14行：
applicability属于对应content／condition的assertion，binding只承载关系支持；Source的
报告时刻、角色和调用方日历不代填生效限。只在temporal_scope及conditioned开启时加入
明确标为假设的日期条件示例。公共schema、decoder、权限和实际日期故事402产物均不改。

Root检查85项既有编辑器测试通过，7个受影响文件Ruff、5个源／示例3.11mypy及真实SQLite
日期示例通过，均0真实模型／编码调用。这些检查验证合法输出与日期读取路径，不证明
模型会生成正确结构。4a自身远端CI尚未请求；新的真实效果与成本另记，下面12:58固定
报告、原首次非法属性失败与原来源绑定限制继续保留。原完整目标仍未完成。

## 12:58:48 UTC：PR90合并、完整诊断评分与两组Host检查闭合

本节固定于2026-10-07 12:58:48 UTC／北京时间20:58:48。报告版本以本节所在提交为准，
最新开发源码为`402d7d5`（C的`e9fd56a`集成为`ee0b2dc`，Root接通进度呈现）；
实际prefix8-v6预测／评分仍为`34fa5c9`，Native8两应用为`1f22097`，日期故事为402d7d5。
三条运行分别统计；工程合并、实际提交、作者标签与Root复核不互相替代。

**PR83至90均已合并。**[PR90](https://github.com/minguselandy/MiLAi/pull/90)头16f3083
自身[Fast519](https://github.com/minguselandy/MiLAi/actions/runs/37620097357)、
[Fast520](https://github.com/minguselandy/MiLAi/actions/runs/37620147498)及
[Full329](https://github.com/minguselandy/MiLAi/actions/runs/37620147442)均success，Full21/21。
12:51:28普通merge为main`e0abb07`；integration快进、干净，源码树与已检查的16f相同。
未改变workflow、业务权限或Product内容，不借main／其他提交CI证明新402源码。

**业务事实与当前执行许可分列。**ee0b2dc按实际必需步骤汇总business.status；
当前执行状态、can_execute、allowed_operations及readonly放入business.execution。
先按真实观察辨明已完成／未完成／部分完成，再决定本次可办理的阶段；保留原attempt、
实际回执、unknown及当前拒绝。402d7d5的普通业务答复分别展示“业务部分完成”和
“本次只查询／未获允许”；不把旧请求的保存要求当新许可，也不增加业务／语义重放。
47项应用、10项Host、4项包边界及5项工具边界检查通过；三个源／示例3.11mypy、Ruff和
两应用SQLite重开示例通过，以上均0真实HTTP。示例只补正确RunnableConfig／文档world类型，
不修改实际办理行为。402自己的远端CI尚未请求，不能借父16的成功冒称已通过。

**同一34fa诊断的predict与score均已闭合。**预测11:04:45退出0；评分12:19:34退出0，
terminal-score为COMPLETED_EXPERIMENT_PHASE，32/32会话按用户8／8／8／8完成。
507个Judge请求及507个确认stop响应，known1,900,646；未重做Writer、Reader或encoder。
用同一冻结源的既有汇总入口读取保存标签，0新增模型；原Omitted／None等无效判断保留。

| 用户顺序 | 更新Correct／全部；valid | QACorrect／全部；valid | formation reference／valid | formed outputs／valid |
|---|---|---|---|---|
| 第一 | 9/19；18 | 9/20；18 | 122/115 | 14/12 |
| 第二 | 5/15；15 | 5/12；11 | 102/90 | 16/12 |
| 第三 | 4/20；18 | 11/22；20 | 100/93 | 16/13 |
| 第四 | 2/18；15 | 4/19；17 | 115/112 | 7/6 |
| 合计 | 20/72；66 | 29/73；66 | 439/410 | 53/43 |

更新原标签为20Correct、44Omission、2Hallucination及3Omitted／3None无效；QA为29Correct、
21Omission、16Hallucination及7None无效。全部机会与valid分母分别保留，不把未运行对照
补零。predict的139响应／2,162,788known与score合计646生成响应／4,063,434known；编码
仍198次／70,668，新增unknown0。此前151／131／147 Judge等用户子集不重复加总。
Root已读该冻结轨迹全部73个完整自然答案，无额外数值重评分；仍有真实空维护、同目标
重叠拒绝、来源／限定缺口。没有同版本控制组或稳定方法优势，同家族Judge不算独立确认。

**冻结1f的Native8两应用已实际闭合。**2个既有case／5个消息跨进程执行，12:31:02退出0，
5次COMPLETED代表执行状态。Root读全部5个完整业务自然候选及最终答复，读取实际SQLite：
预订恰1次reserve_and_label＋1次complete_label，续办前实际查询、没有重复预订；原结果
维护因EDIT_APPEND_CONDITION_TARGET_INVALID拒绝。后续当前不允许记忆维护，业务完成但
原保存项仍pending，原完整请求incomplete；实际记忆只保留用户请求r1，不能称保存了结果。

文档第一次草稿和审批成功而发布不可用；后续实际查询后只补发布，DB恰1审批／1成功
发布，实际结果事项r1至r4。原请求提交回执闭合，语义覆盖仍另行理解。外部随后修改正文
成为版本2；只读答复区分当前未审批／未发布与历史版本1发布，0新增业务／维护，r4不变。
Host响应checkpoint仅证明Host看到反馈，不证明用户收到。此组39生成／437,000known，
23stop＋16tool_calls；29编码／4,636，Judge0、新unknown0。不是5条语义通过，也不是最终
候选冻结后的新故事；这组不在34fa的成本或方法成绩中。

**402日期故事闭合，首保存仍失败。**一空库4个新开发消息，显式声明同一名义日历，分别
传入报告时间与Reader目标；没有声明物理时区或注入理想状态。12:52:50退出0，4次执行
COMPLETED。首次editor把applicability放到condition顶层而非assertion内部，原公共schema
拒绝，0语义提交；Reader诚实区分原始捕获与保存失败，原输入／失败保持。后来的回溯
报告实际形成1事项、4unit（2content／2condition）、3关系；撤销后r2保留一般内容／原条件，
移除例外／相关关系。只读回答区分已结束区间与r1历史例外，0维护、r2不变。

这些实际unit只有日期文字，没有assertion.applicability；不能据自然答案正确称程序已形成
结构化生效限。其精确旧区间来自prior_context，而新unit均绑定后来的当前报告，不是原
早来源绑定保留的证明。Root读4个完整答案和实际前后units／来源时刻，没有Judge或另造
数值重评分；下一轮只澄清合法属性位置，不自动搬字段、放宽schema或热改该402结果。
此组19生成／174,304known，10stop＋9tool_calls；10编码／433，Judge0、新unknown0。
普通API确实保存调用方日历／报告时刻及独立query参数，实际方法质量仍有缺口。

三组的响应与连续账本差额分别核对一致。最后闭合账本42,908生成请求，known169,886,129，
charged170,077,617，embedding1,237,429，unknown5为原历史未确认项；limits未改变，旧397
未重试。此为12:58固定成本，后续新运行另记；不将不同代码的Host成本拼成同版方法结果。
详细私有采样仍在ignored的artifacts/unified，原正文、gold、HTTP、reasoning、DB与日志未上传。

原同实际前态recipe、同版B0／B1／B2／M／Append、65／277连续历史、native／drift／必要
消融／固定更紧预算、最终冻结后16保留用户、LongMemEval／外部、同候选Host135case／
192message与最终冻结后的新故事及六项交付仍未完成。16保留未用于开发，尚无最终候选，
single_verdict_v1未准入，Product NO_GO；下面旧固定报告保留原时点。

## 12:13:17 UTC：PR89已合并、日历入口与保存评分观察

本节固定于2026-10-07 12:13:17 UTC／北京时间20:13:17。开发源码为`e07644e`，
报告版本以本节所在提交为准；实际prefix8-v6预测及评分仍冻结`34fa5c9`。
代码、工程检查、原作者标签及Root开发复核分别记录，原完整任务继续。

**PR83至89均已合并。**[PR89](https://github.com/minguselandy/MiLAi/pull/89)
头`1f22097`自身[Fast516](https://github.com/minguselandy/MiLAi/actions/runs/37612639082)
及[Full328](https://github.com/minguselandy/MiLAi/actions/runs/37612639101)成功，Full21/21；
11:50:47普通merge为main`88a101f`，integration快进、干净且源码树与1f22097相同。
原31e67e0的Full327因application源码登记缺两模块失败，修复只补既有所有权列表；
不删除原失败或借其他提交CI。合并不表示真实Host验证通过，两个应用的2case／5message
原输入已用冻结1f22097准备，实际调用仍0，不称为最终冻结后的新故事。

**日历是调用方声明的坐标，未知时区保持未知。**`613a97d`在原SourceEvent增加可选
calendar_context；capture原始occurred_at不改，observed_at继续为实际UTC捕获时钟。
旧来源缺字段时不回填，重开及幂等重放保留原声明，变化声明被原捕获边界拒绝。
`cf198f9`识别ISO和英文月份时间，保存精度；日期表示整日，报告时间不能填充生效限。
明确offset之间按实际offset比较；无时区值只在双方明确同一日历时名义比较。
缺失／不同日历或混合有无offset都保持time_context_unresolved，不默认UTC。

`71ab2e0`与e07644e接通[普通Host配置v2](../configs/milai-unified-functional-v2.json)
的正常message／fixture／CLI入口：报告calendar_context与Reader query_time／
query_calendar_context分开；两种只读投影使用同一查询时刻。未提供查询时间时沿用服务时钟，
不自动使用报告时间。共同benchmark及external入口保留实际来源时间；[predict配置v2](
../configs/milai-unified-prefix8-v2.json)只增加显式history-calendar及实验／配置名称，
Qwen3.6、BGE-m3、thinking、temperature、dense K10与原预算全部不变。该配置声明仅用于
新运行，不重解释旧来源，也不代表已运行的34fa具备这些修正。

Source实际SQLite72项、editor85项、adapter6项检查通过；正常Host及共同recipe的13项窄
接线检查通过，相关八源Python3.11mypy、Ruff、CLI及真实SQLite重开示例通过，全部0真实HTTP。
包／工具边界检查通过；扩大检查及本次头的远端CI另核对，不据局部检查宣布语义通过。
Lab可选字段和调用参数改变，Product Schema/API/权限/Canonical、workflow及预算不变。
代码回滚参考1f22097；回滚不撤销实际业务、来源或成本账本。

后续扩大Host／benchmark检查为386通过、1失败：SQLite同时间行的encoder输入次序与
测试假定的插入次序不同。实际dense返回目标正确，双方完整正文都恰编码一次，库值不变。
只修测试为核对完整正文multiset，保留实际返回排名、数量、owner隔离与状态断言；74项
benchmark／external复测通过。原失败保留，不用窄复测冒称原扩大检查全部通过。

新时间描述最初使73份实际保存Reader投影中8份超过32256，最大35193；该失败采样保留。
e07644e只用既有共享metadata格式压缩逐值相同的来源／时间／实际引用；73份展开均与
完整新视图相等，最大31532，全部可容纳。不删来源、正文、字段或top10，不扩大预算，
实际旧来源的calendar字段仍缺失。以上是0HTTP容量检查，不是新Reader效果或名义日历声明
在真实模型中的验证。原输入、输出和中间失败保持ignored，未上传原文或HTTP。

**冻结34fa预测已实际闭合。**11:04:45预测退出0，terminal-predict为
COMPLETED_EXPERIMENT_PHASE；32维护记录、32预测、33来源batch、73完整自然答案。
33extract／33editor／73Reader，共139个生成响应均stop；known分别380156／730900／
1051732，合计2162788。编码198次／70668 tokens，Judge0、新闭合unknown0。
12个真实空提案；53个实际提交（45新建／8修订）、2个EDIT_OVERLAPPING_TARGET拒绝、
4个no_change；这些均不表示语义成功。四独立终态合计45事项、174content、0condition，
未生成直接关系；限定可能保留于文字，不能只据role计数判断语义。Root已读全部73个完整
自然答案，保留姓名归属、真实空维护及同目标重叠提案等缺口，没有额外数值重评分。

**作者score仍在运行。**11:09:00从同一34fa、保存预测及author retrieval启动；
固定观察27/32，按用户8／8／8／3。467个Judge请求／466个已确认stop响应，known1773040；
尚无terminal-score或process-exit，不重启Writer／Reader／encoder、不盲重试旧未知397。
前三个8会话的保存标签按原作者纯汇总，0新增模型：

| 用户顺序 | 更新Correct／全部；valid | QACorrect／全部；valid | formation reference／valid | formed outputs／valid |
|---|---|---|---|---|
| 第一 | 9/19；18 | 9/20；18 | 122/115 | 14/12 |
| 第二 | 5/15；15 | 5/12；11 | 102/90 | 16/12 |
| 第三 | 4/20；18 | 11/22；20 | 100/93 | 16/13 |

原无效Omitted／None及其他作者标签保留，不转为有效判断；没有完整M终态成绩、同版
方法排名或优势结论。同家族Judge及Root开发复核均不算独立确认。前三用户Judge响应
151／131／147，known649033／483416／539950，是当前score的子集，不再另加成本。

prefix8-v6截至固定观察共606生成请求／605确认响应，known3935828；编码仍198次／70668。
连续账本42810请求、known169147219／charged169403762、embedding1232360，unknown6
为历史5加当前1在途reservation，不能直接记成新已闭合失败。实际响应与账本known／request
差额核对一致，limits未变。这是12:13固定成本，不是随后实时成本。

原同前态recipe、同版五方法、65／277历史、native／drift／消融／更紧预算、最终冻结后
16保留用户、外部、Host135case／192message与新故事及六项交付仍未完成。保留16未用于
开发，尚无最终候选，Product仍NO_GO。下面各固定报告和旧失败保留原时点。

## 11:02:46 UTC：PR88已合并、普通Host完整请求接线与容量运行

本节固定于2026-10-07 11:02:46 UTC／北京时间19:02:46。最新开发源码为`752862b`，
报告版本以本节所在提交为准；正在运行的预测仍冻结于`34fa5c9`，不是本次Host源码。
原完整任务继续，工程检查、实际业务结果、自然答案及作者标签分别记录。

**相关PR已经合并。**[PR88](https://github.com/minguselandy/MiLAi/pull/88)头`b5992e3`
自身[Fast511](https://github.com/minguselandy/MiLAi/actions/runs/37605480212)和
[Full326](https://github.com/minguselandy/MiLAi/actions/runs/37605480313)成功，Full21/21。
Root核对远端头后转ready，于10:51:41普通merge；main为`2e1dac6`，本地integration快进且
干净，源码树与b5992e3相同。PR83至88均merged，随后远端open列表为空是当时观察。
原checkout及未跟踪用户计划保持。上述CI属于b5992e3，不借给本次752862b或合并提交。

**普通Host首次效果前登记完整业务请求。**C源码`a1e4eb5`把当前用户解释中的target／
actions／字面参数编译到既有requirements；对象ID、文档版本和完成条件由实际应用合同及
查询给出。ReceiptProgressJournal保存原session／turn／config／user source，业务效果前
已有request_state。`e0f9e51`将普通ToolNode的实际call身份及结果链接到原阶段；预订和标签
分开投影，部分成功不变成全失败。Host刷新进度时resume_request使用execute_business=False，
C仅发现实际状态、核对当前权限，实际mutation仍经同一个ToolNode／应用适配器。

Root源码`d21cd0d`新增可选current_request_native_v8和[功能配置v2](
../configs/milai-unified-functional-v2.json)。当前请求声明可单独解析原请求身份；只读查询
不因此获得保存或业务许可。旧完整请求卡片与原User片段作为专用进展／意图材料发行，
不进入普通事实dense检索。重开沿用实际已送达的解析快照，重新核对来源可见性；后续普通
Reader视图刷新不会使已接受的解析失效。请求解释来自同一个Host模型，语义覆盖仍unchecked。

实际结果保存复用共同maintain_sources，不另起Writer或事实库。C的semantic attempt及
原维护batch／source绑定在Writer之前持久化；回执必须来自包含该target全部请求完成字段
的实际Tool来源及真实commit。当前User指令、另一个target的提交、raw capture或真实空提案
不能代替结果保存。跨会话核对只读取原维护操作ID及实际operation_receipt；不盲重发未知
模型或提交。临时查不到已提交回执时保留semantic_unknown，之后只读新请求可核对为committed；
原attempt、binding和error仍在。无关来源batch不阻挡对该结果的原操作核对。

反馈记录实际provider响应对进度frame的接收，以及该AI响应进入Host checkpoint；仅在实际
业务／保存状态相符时关闭Host反馈。它不证明用户已收到，user_seen仍unchecked；原CLI本地
反馈文件依然host_seen=false。结构上的complete也不证明自然答案或持久记忆语义正确。

`752862b`修复同一target上的新明确perform要求：不同参数或新文档内容登记当前新请求，
mutation优先链接当前计划；continue_if_unfinished及同参数阶段子集保留原完整计划。
实际SQLite检查中第二文档版本真实创建／审批／发布，旧请求及回执保持；预约数量变更被
sandbox实际拒绝，原数量保持，新要求仍incomplete，没有伪造更新。旧save_result=false、
随后仅新增保存旧结果这一新要求，目前仍用普通memory-only维护与独立回执，不宣称原请求的
not_requested替代新保存，也未把新要求retrofit进原不可变requirements。

**本地验证已闭合，真实Host验证尚0。**最终受影响Host、application及共同memory adapter
检查共461项通过；Ruff、原Python3.11七个受影响源mypy、包DAG／工具依赖边界和CLI help通过。
合成transport及真实SQLite覆盖两recipe、原部分结果、当前no-save／只读、真实空保存、跨会话
提交响应丢失与回执暂不可查询、重开零重复、两个sandbox及同目标新请求。全部0真实HTTP，
未增加模型、reviewer、Store、预算或并发；Product Schema/API/权限/Canonical及workflow不变。
Lab仅增加可选请求模式与API参数。回滚源码参考b5992e3，不回滚已发生业务效果或账本。
新源码远端CI另外核对，完整真实Host135case／192message及最终冻结后新故事仍未完成。

**容量预测仍在原冻结版本运行。**prefix8-v6于10:08:13从34fa5c9启动，Root独占串行HTTP，
四个公开开发用户各前8、各自实际空库。当前PID2132391仍存在，保存预测31/32，依次
8／8／8／7；尚无terminal-predict或process-exit，不推定全部完成。配置与预算沿用原值，
只有Writer／Reader重复表示共享这一主要变化；恢复9abc783及本次752862b都不在其中。

固定快照的已确认抽取33／editor33／Reader65，共131个生成响应，全部stop；另1个Reader在途，
共132请求。known分别380,156／730,900／957,121，合计2,068,177；Judge0。编码183请求／
183响应，70,306 tokens。已确认editor中12个真实空提案，不合并为HTTP前容量失败。
Root已阅读63个完整自然答案（第一20、第二12、第三22、第四前四会话9），没有数值重评分。
首用户原0／1的5／3条抽取候选及实际User支持已送达，但editor真实返回{}，普通语义库为空；
后续部分Reader拒绝把题中姓名与User事实关联，其他答案又采用该关联。容量可容纳并未修复
这些维护选择或读取语义，尚无本次作者score、完整M成绩或方法优势结论。

连续账本为42,336请求、known167,279,568／charged167,532,472、embedding1,231,998、
unknown6＝历史5＋当前1个在途reservation；不能记成新已闭合失败。相对本次预测起点，
确认响应与账本known、请求文件及编码tokens差额均0；账本请求比确认响应多1。limits未变，
原采样及完整产物ignored；这是11:02固定成本，不是后续实时成本。10:06的f307两份保存score
已经闭合，仍只覆盖原失败32中的13；不重复相加，也不归入当前34fa预测。

原同前态recipe配对仍0真实调用；同版B0／B1／B2／M／强Append-only、65／277连续历史、
native／drift／必要消融／固定更紧预算、最终冻结后16保留用户、外部及完整Host回归和六项
交付均未完成。16保留用户未用于开发，尚无最终候选或Product准入，Product仍NO_GO。
下面保留各自原观察时点，不能把新源码检查或实时进度写回旧冻结结果。

## 10:06:37 UTC：PR87已合并、保存评分闭合与恢复接线

本节固定于2026-10-07 10:06:37 UTC／北京时间18:06:37，报告父源码`9abc783`。
PR83／84／85／86／87均已合并；main为`354807f`，本地integration快进且干净，
源码树与PR87头`34fa5c9`相同。34fa5c9自身Fast507及Full325成功，Full21/21；
不把这些检查写成合并提交354807f自身CI。用户的原checkout及未跟踪计划保持。

**同f307保存评分仅覆盖已保存13份。**第一用户8份保存预测的作者score已
COMPLETED_EXPERIMENT_PHASE，09:45:46退出0。更新Correct7/19、valid18；
QA Correct12/20、valid17；formation reference122／valid115，formed outputs16／valid14。
原更新标签为7Correct、11Omission、1无效，QA为12Correct、4Hallucination、1Omission、
3无效，原无效判断全部保留。167个Judge响应均stop，495,237 known tokens，
新增embedding／unknown均0。Root已读该用户全部20个原完整答案，没有额外数值重评分，
同家族Judge及开发复核不是独立确认。不能和旧dffc或其他源码成绩排列方法优势。

第二用户5份保存预测于09:47:11从同一冻结f307串行score，10:03:32退出0；
5/5检查点及score终态COMPLETED_EXPERIMENT_PHASE。更新Correct3/7、valid7；
QA Correct6/9、valid7；formation reference89／valid77，formed outputs19／valid16。
更新原标签3Correct／4Omission，QA为6Correct／1Hallucination／2无效，全部保留。
126个Judge响应均stop，493,202 known tokens，新增embedding／unknown均0。
没有重新调用Writer／Reader／encoder。原prefix8-v5的32会话预测仍是FAILED、13保存预测；
两份subset终态不替代32分母，后两用户未运行不记零分，不重发旧dffc未确认请求397。
两个描述性subset合计更新10/26、valid25，QA18/29、valid24；不同长度用户分列，
不是完整M成绩或同版方法对照。Root已读第二用户全部9答复，总计29答复，无新增数值重评分。

第一评分闭合账本为42,078请求、known164,718,189／charged164,909,677、
embedding1,161,692、unknown5。两份评分闭合账本为42,204请求、known165,211,391／
charged165,402,879、embedding仍1,161,692、unknown仍历史5，无新增已闭合unknown。
自prefix8-v5预测起生成348请求／348响应、1,998,492 known tokens；其中两份score
293响应／988,439 known仅相加一次，编码仍91次／33,242。原limits未变，
确认文件与账本request／known差额一致，完整采样保持ignored。此固定快照不是后续实时成本。

**恢复代码尚未做真实模型验证。**`48ae6f6`把显式选定的旧请求原范围加入共同维护
prior_context，不再受最近四来源限制；旧片段不是当前事件、独立支持或新授权。
`9dcd928`为C的resume_request增加可选semantic_attempt_binding，在memory callback前
深拷贝保存实际session／turn／config／source；原unknown尝试的binding及error不覆盖。
Root源码`9abc783`接通普通Host三处maintain_sources，重新读取已解析句柄并核对当前可见性；
当前不允许保存时不读取这些旧请求。公共CLI按原attempt绑定定位旧维护结果，恢复原公共
轮次后execute=False核对提交；同会话暂时恢复旧轮次后恢复本轮绑定，不盲重试unknown。

Root的44项Host／continuation相关检查及6项适配器／application窄检查通过，使用合成
transport、真实SQLite；Ruff、原Python3.11四个受影响源mypy及包／工具边界通过。
跨会话只读新请求能核对实际已提交而响应丢失的旧保存，原semantic_unknown尝试及错误仍在，
总体memory关闭为committed；没有重复保存、预订或补标签。选定旧语境、当前no-save及重开
零重复也已检查。这些工程检查不是真实语义效果或完整请求恢复的完成证据，源码自身CI另核对。

普通Host的v7仍未在首次业务dispatch前登记C要求的完整requirements／request_state，
当前单次maintenance或单回执不能证明全部原请求项已完成；CLI反馈仍只确认本地文件、
host_seen=false。该接点和普通Host真实完整恢复仍待开发／验证，不能因上述接线宣称闭合。
HaluMem日期没有已证实的时区，后续表示规范化不得凭空赋予UTC或推定生效时间。

容量诊断`prefix8-v6`已冻结34fa5c9，仍0真实调用；两份评分已闭合，随后由Root串行运行，
四开发用户各前8、各自空库、同预算及参数，只有Writer／Reader重复表示共享这一主要变化。
恢复9abc783不在此冻结诊断内，不热改或拼接轨迹。原同前态recipe配对也仍0真实调用。
正式五组、65／277连续历史、native／drift／消融／较紧预算、最终冻结后16保留用户、
外部基准、完整Host135case／192message及新故事与六项交付均未完成。16保留用户未用于开发，
尚无最终候选、稳定方法优势或Product准入，Product仍NO_GO。下方保留各自原快照。

## 09:26:49 UTC：PR合并、冻结诊断失败与容量修复

本节固定观察于2026-10-07 09:26:49 UTC／北京时间17:26:49。PR83／84／85／86均已合并；
main为`f89fe56`，其源码树与PR86报告头`6ab9a6e`相同。6ab9a6e自身Fast成功，
Full成功21/21；不将该检查写成合并提交自身CI。本地integration工作区已快进且干净，
原checkout的用户计划保持。新容量源码为`437b80f`，尚未执行真实模型任务，CI另核对。

**聚焦Host已经闭合。**冻结`f30722f`的`host-partial-result-v6`从一个实际空库运行原两条
业务消息，进程退出0、2COMPLETED；20次生成／213,307 known tokens（12 tool_calls、8 stop），
14次编码／1,602 tokens，Judge0／新增unknown0。业务SQLite仍仅一次预订、一次补标签；
第一条Tool实际结果能够修改至r3，整卡混合来源使用既有inference，原用户计划和限定保留，
没有旧source_role_mismatch拒绝。这不能证明自然描述正确：dispatch_started、内部receipt
状态仍被模型扩成业务发货或收货；第二条当前声明不允许记忆维护，补标签新结果未持久化，
程序反馈明确未提交。Root读完两条实际反馈及单独自然候选，不新增数值重评分。
此前两个Host加整理再加本次聚焦，分别归属613c992／4b5963f／f30722f，合计187生成／
1,662,118 known、129编码／7,992 tokens；不是同版本方法对照，不重复加其中任一子集。

**新prefix8诊断已失败退出，不再运行。**冻结`f30722f`及原参数，产物为
`artifacts/unified/prefix8-v5/M`；预测进程PID1839197退出1，terminal-predict为FAILED，
原因是第二用户原5的第一条Reader输入37,196，超过32,256输入上限。失败在Reader HTTP前；
不得热改、补记或从该终态推定32会话完成。

| 闭合预测事实 | 数量及边界 |
|---|---|
| 保存完整预测／完整自然答案 | 13/32（8／5／0／0）／29；Root已读全部29答复，不是独立确认 |
| 实际维护检查点／来源批次 | 14／14；两次编辑前容量失败，未发送editor HTTP或修改状态 |
| 完整编辑器输出 | 12次，其中首用户原4一次真实空对象；空提案不合并为容量失败 |
| 实际提交 | 28新建＋7事项修订＝35；提交不是语义通过 |
| 生成 | 14抽取＋12editor＋29Reader＝55，全部stop；1,010,053 known tokens，Judge0 |
| 编码 | 91次／33,242 tokens；新增unknown0，所有146请求都有原响应 |

生成细分known tokens为抽取167,899、editor326,534、Reader515,620；确认文件与账本差额相等。
预测结束固定账本为41,911请求、known164,222,952／charged164,414,440、embedding1,161,692、
unknown5。这是预测闭合点，不是09:26评分实时成本；预算未重置、原limits未改。

维护容量失败分别是首用户原7和第二用户原5子批次0；后者先完成抽取，但没有完整预测。
首用户原4抽取已送达、editor真实空提案，后续原5实际向旧职业／宠物事项追加，旧单元保持；
不是新建偏好事项，也不回溯改写原4结果。首用户原0的五项候选全部送达，但只形成一张
基本卡；其他候选遗漏及复合条款粒度仍保留。原7确认新工作的来源已抽取，容量失败留下
旧状态，后续答复缺少新信息。未运行的后两用户不记零分，没有完整M成绩或方法优势。

**只评分保存部分。**09:21:46从同一f307冻结入口启动第一用户8会话作者score；截至本节
仅2/8检查点、39个确认Judge响应，无score终态。第二用户5会话评分已准备但未启动。
两份明确的每用户subset配置复用原13预测、实际state与author update retrieval；原SQLite
只读备份、保存预测逐值保持。没有重新调用Writer／Reader／encoder，不去重发旧dffc请求397。
这些subset不能替代原选定32会话分母，原32会话FAILED终态永久保留。

**新容量代码只是表示修复。**Reader源码`e7b6876`在瞬时消息中共享完全相同的assertion／
temporal元数据并使用紧凑JSON；原检索快照不变，十项、正文、来源、时间及限定全部可展开
恢复。30个实际Reader输入（29已回答＋1容量失败）逐值相等，最大37,196降至25,059，均可
容纳；仅删空格的失败输入仍33,823。46项Reader／runner检查、原Python3.11源mypy、Ruff通过。
Writer源码`437b80f`移植独立提交89809cd，仅扩已有compact_prompt_schema的重复子schema
共享；生成API和decoder仍使用原内联约束。首用户原7输入32,640→25,910，第二用户原5
子批次0为33,092→26,306；九份保存view可完整展开，首用户16个原提案有效性一致。
99项编辑／runner检查、原Python3.11两源mypy、SQLite示例及边界检查通过；两组检查有交集，
不相加为独立样本。Root合流后单独检查保存预测→score接线与两项包／工具边界。
全部容量验证0真实HTTP；不能把这些新输入容量或其他提交CI归到旧f307自然答案。

原同前态recipe配对仍0真实调用；正式五组比较、65／277连续历史、native／drift／消融／
较紧预算、最终冻结后16保留用户、外部基准及完整Host135案例／192消息和新故事仍未完成。
16保留用户未用于开发，尚无最终候选、稳定优势或Product准入，Product仍NO_GO。
下方保留各自原快照；当前失败见[同一问题表](MILAI_BUILD_FIRST_ISSUES.md)。

## 第二轮真实Host、整理及混合来源修复

第二轮闭合观察：2026-10-07 08:41:49 UTC／北京时间16:41:49。实际源码冻结于
`4b5963f`，产物`artifacts/unified/host-five-flows-v5`；报告父版本`6362418`没有改变
运行源码。五个独立空库、18条原消息、模型、recipe及Host预算与首轮一致。
进程退出0，18条均执行COMPLETED，Root阅读全部18条完整送达答复，并分别阅读共同条件
修改及两条业务消息的自然候选。没有Judge、独立确认或数值重评分，不记作18条语义通过。

| 实际结果 | 仍须区分的限制 |
|---|---|
| 跨进程保存／读取成立；长度单位同一事项实际修订，原限定及历史保持 | 弱偏好的措辞仍需保留原强度；正确读取不能单独证明所有保存语义正确 |
| 一般规则、北区例外、共享通知条件及撤销均实际提交 | 初始合并的子组否定内容仍未改；末次当前／历史回答仍可能将整体次数分配给成员 |
| 遗忘选择原偏好支持及派生来源，最终答复完成，重开只读查不到旧偏好 | 可见导出为0事项／3来源／3Episode，激活为空；这是本次实际选择的结果，不推广为所有遗忘请求成功 |
| 实际业务SQLite仅一笔预订及一次补标签 | 工具结果的语义修改仍被source_role_mismatch拒绝；完整业务不表示实际结果已写入记忆 |
| 程序反馈分开实际业务与部分语义保存 | 提案仍把请求写成已报告办理，把业务调用开始误写成发货；续办编辑丢失旧数量／包装。另有一次抽取length，均保留 |

第二轮成本为100次生成、912,014 known tokens（49 tool_calls、50 stop、1 length），
73次编码、4,464 tokens，Judge0、新增已闭合unknown0。连续账本闭合至41,834请求，
known162,988,205／charged163,179,693，embedding1,126,848，unknown5；响应汇总与差额一致。
首轮与第二轮分别归属613c992及4b5963f，不能拼为同版本方法效果比较。

08:43:27 UTC后续整理观察：从同一4b5963f冻结入口选择一条实际Episode及已存事项，
使用同一bank、队列和账本；2次生成均stop、11,387 known tokens，编码／Judge0。
编辑器首次真实输出为空对象，完成无修改，原r1、原支持及两次真实Reader使用记录不变，
没有业务动作或新增独立事实支持。相同请求重开回放0HTTP，连续账本完全不变；用途反馈
仍为0，factual_probability为null。遗忘bank的公开导出／Episode／激活也未恢复旧偏好。
该次整理后的闭合账本为41,836请求，known162,999,592／charged163,191,080，
embedding1,126,848，unknown5。以上两组Host加整理合计167生成／1,448,811 known、
115编码／6,390 tokens；整理和其中任一Host子集不再重复相加。

后续源码`f30722f`修复普通适配器继承整卡user_statement／tool_observation的问题：
创建、局部编辑、全量重写均根据实际全部source_refs聚合basis；混合来源使用既有
inference，子断言仍分别保留reported／observed、原角色和原支持。类型改变时同步更新
basis字段的真实支持；exact no_change保持原值及支持。没有改业务字段、服务角色校验、
逐项断言或原模型语义错误。29项受影响既有检查、Ruff及源mypy通过；Root在原Python3.11
环境复核两项共同维护／真实SQLite集成检查和类型检查，属于该29项的子集。

该修复不在以上两组Host或整理内。新的同输入两消息业务流程冻结f30722f、从空库起跑，
于08:46:12 UTC启动`artifacts/unified/host-partial-result-v6`；该启动快照没有终态结果。
四开发用户各前8的集中M候选`prefix8-v5`仅已准备，等待此流程闭合后串行predict／score。
旧397未确认请求保持，16保留用户未读，完整对照、长历史、外部及最终Host范围未完成。

## 首轮真实Host与修复版本（原08:15:52快照）

固定观察：2026-10-07 08:15:52 UTC／北京时间16:15:52。PR83、84、85均已合并，
main为`7141340`；其源码树与已通过自身Fast及Full（21项）的`613c992`相同。
这不等于合并提交7141340自身CI已经运行。

真实运行冻结于`613c992`，产物`artifacts/unified/host-five-flows-v4`，同一Qwen3.6及
BGE-m3、原Host预算、五个独立空库、18条消息，每条以新进程打开原bank。进程退出0，
18条中12条执行COMPLETED、2条FAILED、4条因前序失败NOT_RUN。Root读完14条实际执行的
完整送达答复，另分别阅读业务自然候选；没有Judge或另造数值重评分。

| 实际观察 | 最早断点及边界 |
|---|---|
| 保存后跨进程只读能读到规则及例外，旧值保持 | 首轮已执行；弱限定的保存仍须语义复核，不能用提交次数代替 |
| 首个学校手工规则已提交，最终Reader失败 | Reader的8,192输出token全耗尽，finish_reason=length、content为空；不是编辑前容量失败 |
| 新增局部例外未提交 | 原共同限制实际存为content，编辑却将其选作shared condition；首次stop提案被正常拒绝 |
| 修改共同限制的首次提案未提交 | 合法records.r1编辑仅因缺少空creates被拒绝；后续独立事件才提交两天，不能追记前次成功 |
| 当前／历史回答仍有语义错误 | 总体频率无依据分配给子组，答复声称历史存在从未提交的例外；旧状态和首次输出均保留 |
| 遗忘已撤销一事项及所选来源，最终流程仍报错 | 当次选择的是撤销请求来源，不能声称原偏好原话和所有副本都已撤销；隐藏的最终答复继续建Episode导致EPISODE_SOURCE_UNAVAILABLE |
| 部分预订后实时查询再补标签 | 实际业务SQLite仅一笔reserve_and_label及一次complete_label；首先误用记忆ID查询失败后改用实际物品。语义工具结果提案因source_role_mismatch未提交，原用户请求不能证明办理结果 |

成本：65次生成、525,410 known tokens（31 tool_calls、33 stop、1 length），42次编码、
1,926 tokens，Judge0、新增已闭合unknown0；请求、响应与连续账本差额相等。连续账本
41,734请求，known162,076,191／charged162,267,679，embedding1,122,384，unknown5沿用
历史4及旧397未确认，不重置。退出0和12个COMPLETED均不表示12条语义通过。

后续开发源码`1847ade`在同一既有编辑边界保留实际content／condition角色，允许省略空
creates／records，编辑仍必须显式选records.r#；原content冒充shared condition仍拒绝。
有新证据时可用原append(condition, attach_to=实际目标)及retract修正表示，无自动迁移。
`4b5963f`使已隐藏的最终答复只保留原审计捕获，不生成可读Episode；不会恢复隐藏来源。
236项编辑相关检查、16项遗忘／可见性接线检查、SQLite示例及Ruff通过；原Python3.11
环境的四个受影响源模块mypy通过。另一隔离环境的NumPy类型语法与3.11冲突单列，
其3.12全包检查不能替代3.11支持。上述修复尚无真实模型复测；原613c992结果不变。

下一次使用新冻结源码、新空库和同一批输入，预算、模型、recipe及Reader不变。
随后集中预测与独立评分，再按原完整计划执行同版对照、长历史、保留／外部及完整Host。
旧dffc232评分仍中断18/32、396响应、397未确认；不能重发未知请求或补称闭合。

## 实现及证据边界

| 能力 | 正常实现／入口 | 当前证据 |
|---|---|---|
| 来源与Episode | 同Store保存原始来源和引用索引；实际维护提交后的描述保留来源、角色和解释属性 | 真实SQLite、重开和遗忘示例；没有真实模型效果结论 |
| 时间与范围修订 | 既有I2编辑器及只读关系视图；实际角色／报告／捕获／提交时间由程序填写 | 一般规则、例外、共同条件、撤销、历史和整体数量工程示例 |
| 实际对象与恢复 | 普通Host采用应用适配器；lookup／execute／observe／discover共用原业务journal | 两个沙箱、未知发现、原操作核对及当前权限检查；不是外部系统exactly-once |
| 共同维护 | 两种recipe和Append-only；真实容量预览、原文分批、实际提交后刷新当前视图 | Host与benchmark既有检查；分批调用分别保存原输入和首次响应 |
| 激活与用途 | 同Store记录实际使用／显式反馈；独立于真实性、权限和删除 | 24步隔离轨迹、5次脚本编辑、0HTTP；用途估计尚未校准 |
| 显式整理／继续 | `run_memory_operations.py`打开普通Host的同一owner bank、配置、队列和成本账本 | 普通Host部分预订→重开只读→只补标签→维护实际结果→整理的脚本传输检查 |

源文件、示例与接口分工见[一页接口约定](MILAI_UNIFIED_IMPLEMENTATION.md)。
脚本响应检查使用真实SQLite和实际沙箱副作用，但不会验证自然语言理解质量。
一个执行COMPLETED、一个提交回执和一次正确回答分别报告，不能合并成语义通过。
Root的11项集中接线检查、相关Ruff／mypy及包／工具依赖边界通过；分批汇总按实际叶批次
计数，父容器重复的回执不再重复相加。旧无效标签、失败和固定产物保持。
改动仅在Lab：增加可选来源／时间字段、profile及公共操作入口，沿用实际owner、版本、
可见性和当前许可。未改Product Schema/API/Canonical。源码回滚基线为723ceca，
不是预算或已发生业务效果回滚；远端发布和新源码CI分别记录。

## 普通Host

在Lab目录运行；`PYTHONPATH=src`。Python仍使用原Lab虚拟环境。
实际模型执行由Root串行安排，先冻结候选版本，再使用新产物目录。

```bash
python tools/run_functional.py prepare --root artifacts/unified/host-v1 \
  --config configs/milai-unified-functional-v1.json --source-version ACTUAL_SOURCE_COMMIT
python tools/run_functional.py message --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --message-id first \
  --text '请记住我现在的安排。' --occurred-at 2026-10-07T06:00:00Z
python tools/run_functional.py episodes --root artifacts/unified/host-v1 --owner example-owner
python tools/run_functional.py activation --root artifacts/unified/host-v1 --owner example-owner
python tools/run_functional.py export --root artifacts/unified/host-v1 --owner example-owner
```

公开配置是`unified_v1`、M、I2、六项EditFeatures及extract-then-edit，保持既有
Qwen3.6、BGE-m3、dense K10及容量。`answer_from_delivered_v1`只在实际读取额度耗尽后
停用额外读取，让Host用已送达材料作答或说明缺失；业务能力继续服从当前许可。
独立对象／版本／范围／游标的读取进展可由适配器`read_progress`检查。
没有扩读取次数、输出预算或并发额度。

可选v2在同一公开Host入口登记完整业务请求；它保持v1的M、I2、六特征、recipe、
模型、dense K10及容量。使用新目录，不改变旧冻结配置。例如：

```bash
python tools/run_functional.py prepare --root artifacts/unified/host-v2 \
  --config configs/milai-unified-functional-v2.json --source-version ACTUAL_SOURCE_COMMIT
python tools/run_functional.py message --root artifacts/unified/host-v2 \
  --owner example-owner --session original --message-id request \
  --text '预订并贴好一份示例包裹，保存实际完成情况。'
python tools/run_functional.py message --root artifacts/unified/host-v2 \
  --owner example-owner --session later --message-id inspect \
  --text '只查看原请求的进度，不执行也不保存。'
```

输出application_requests分别记录原业务、结果保存、Host反馈及complete；当前许可独立。
原请求身份与维护操作绑定来自实际来源／Store，记忆正文不能授权业务。真实模型执行仍由
Root串行安排；脚本传输检查通过不代表此例已完成真实效果验证。

## 显式整理及语义继续

```bash
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id organize-1 \
  --text '整理这些已保存的经历。' --episode-id ACTUAL_EPISODE_ID
```

不指定Episode／事项时最多选择20个可见、未整理Episode；可用`--record-id`指定实际事项。
整理回放不重新捕获旧原文、不产生独立支持或用途标签，也不执行业务。
旧请求未确认时保留原状态。继续时使用新的当前命令ID、完全相同的旧Episode／事项选择、
`--prior-request-id`和明确`--new-attempt-id`；没有新尝试ID只核对旧结果。
旧语义提案可能已提交时先查原操作回执，未能确认不得另写。

## 完整请求恢复

`--operation resume`调用同一应用适配器及既有请求进展journal。第一次给出实际用户任务的
可信`--requirements`文件，后续以`--resume-request-id`找到它；不是从记忆、gold或未来评价
推导业务权限。计划包含`target`、`steps`、`save_result`、`feedback`；每一步声明操作、
实际参数、完成所需的字面状态字段，可用`arguments_from_state`从实际查询取对象ID。

```bash
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id inspect-1 \
  --text '只查看当前完成情况，不执行也不保存。' \
  --operation resume --resume-request-id original-request --readonly \
  --requirements artifacts/unified/actual-request.json
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id continue-1 \
  --text '继续尚未完成的标签，并保存实际结果。' \
  --operation resume --resume-request-id original-request --allow-operation complete_label
```

每次先发现实际对象状态；已确认效果保持，只执行当前允许的剩余步骤。
`--no-save`、`--readonly`、`--no-read`分别限制当前保存、mutation与读取。
语义保存调用相同共同维护器，以实际工具来源为证据；业务完成不自动表示记忆完成。
旧模型未知／已确认未提交需要新的命令及明确新尝试；旧提交未知必须先核对原操作。
同一当前命令ID再次调用只观察／核对；要继续产生效果必须发出新当前命令ID。

反馈回执表示结果已经写入本地输出文件，明确`host_seen: false`；不声称用户已看到。
最终JSON分别包含业务、记忆、反馈进度。首次命令结果、后续观察和各次失败分别保留。
document工作流使用同一合同，需按当前许可提供实际审批／发布操作和精确版本。

## 激活、反馈和模拟

统一候选公开配置保持`memory_ranking: dense`作为共同底座。显式配置`activation`时，
排名为归一化cosine加`0.1 × sigmoid(activation)`；用途权重默认0。纯排名API先过滤
可见性／权限，保留调用方明确给出的置顶／未完成保护项。没有从自然语言猜保护或权限。
时间衰减使用秒，tau=86400、decay=0.5、epsilon=1e-6；90天冷存储建议从不授权删除。

普通Host只在包含实际Reader材料的请求获得响应后记录使用；benchmark只记录实际
Reader响应，缓存重开和gold诊断检索不增加使用。每事项／当前请求最多一次。
用途反馈用`ActivationIndex.record_feedback`显式传入可见user／tool原来源、反馈协议和
useful标签；unknown不作负例，Assistant自述和内部回放不作反馈。Beta(1,1)估计输出
样本量及未校准用途均值，`factual_probability`始终为null。

```bash
python tools/example_unified_activation.py
python tools/example_unified_revision.py
python tools/example_unified_maintenance.py
python tools/example_unified_recovery.py
python tools/example_unified_episodes.py
```

隔离模拟入口调用公共ingest／maintain／recall／consolidate／resume／forget，使用独立owner、
临时SQLite、虚拟时钟和真实沙箱；只把当前事件传给运行回调，未来事件与评价断言不进
运行材料。24步例子包括间隔、取用、更正、例外／撤销、整理、部分执行和遗忘重开。
脚本传输只证明机械接线，B的时间／关系示例另验证具体投影，不能冒充真实模型成绩。

## 迁移、导出与清理

`index-episodes`为已有可见来源建立同Store索引，不改原文／旧时间、不增加来源或HTTP。
启用新profile须使用新的准备目录和明确配置版本；已有冻结运行不改配置或热换源码。
导出包含当前可见来源、记录、允许的历史和全部可见Episode；不导出业务journal作为记忆事实，
也不把导出当权限凭证。现有`forget`继续撤销来源／事项访问，相关Episode、激活和整理输入
随原可见性不可用。`disable`只是关闭入口，不删除持久数据；清理只能处理明确指定的独立
临时／开发bank，不能删除旧实验或其他owner数据。未承诺物理擦除或跨系统事务。

## 2026-10-07 06:33 UTC固定观察

新候选真实generation／embedding／Judge均为0。原dffc232评分PID已不存在，只有
18/32评估闭合（8／8／2／0）及396个确认Judge响应；request397只有request.json，
没有响应／错误／评分终态，退出原因未知，未重启或重发。第二用户原作者更新12/15
（valid12）、QA8/12（valid12）；无效标签保留，不能据部分结果排名。

连续账本未变：41,669请求，generation known161,550,781／charged161,742,269，
embedding1,120,458，unknown5=历史4+旧未确认397。没有重置或新增上限。
723ceca仍是本次远端读取的PR头，其自身Fast／Full成功；本地新增源码的CI另核对。
04:29已提交报告、旧源码830d23a、实际dffc232预测／评分及本轮候选分别记录。

后续先固定本提交自身版本和必要检查，执行统一五条真实冒烟，按最早语义断点改进，
再集中predict／score。原同前态recipe、五方法、65／277、native／drift／消融／紧预算、
16未读保留用户、外部和Host135／192＋冻结后新故事及六项最终交付均仍未完成。
Product仍为NO_GO；PR #85保持draft，不合并。
