# v13.1 P2 显式有限回执提案合同

状态：PARTIAL / 16真实消息完成；完整P0–P8仍ACTIVE，Product NO_GO。

R9实际Host的所有业务记忆fields为空，只有unchecked正文，不能用机械guard测试声称实际
字段支持收益。P3固定material进一步观察到：真实native ID旁的引用句来自系统prompt，
真实引用存在不证明其内容受支持。这个事实保留为反例，不给自由prose增添真假保证。

本轮最小合同为memory_receipt_contract=explicit_receipt_v1，旧默认optional完全保留。
对实际工具source中已有可信ApplicationWorld.reservation引用的tool_observation提案，要求
模型显式给出status/label_status两字段及声明receipt_json_v1正文。正文必须为公开定义的
有限JSON对象，只含两字段和可选unchecked notes。拒绝0/1字段、缺少声明或不合法结构，
保留requested和raw proposal；不填字段、改正文或追加免费writer。

Ref-only与Field-grounded共用这个声明结构和同一公共写入提示。Ref-only检查refs/schema，
有限claim仍unchecked；Field-grounded再检查与原观察的两字段支持和声明body的literal冲突。
notes、引文和自然语言解释均unchecked。检验范围是与真实观察一致，并不验证世界真理、
当前授权或完整自然语言。旧历史回执不能因为后来状态改变而被偷换为当前世界值。

[公共输入](../data/fixtures/v13-1-p2-typed-receipts.json)4案例×两臂×两消息，共16计划消息；
每消息独立进程。两个label服务可用、两个实际局部成功沙盒条件；不是P1正常24门槛的新分母。
源schema沿用现有公共Agent fixture格式，study_kind明确本轮P2诊断。在任何prepare/HTTP前
做了schema-kind对齐，旧预admission bytes保留；用户消息、初始world和检查内容未改变。

[配置](../configs/v13-1-p2-typed-receipts.json)使用同一R9 Host和公共状态含义提示；
[离线rubric](../data/diagnostics/v13-1-p2-typed-receipts-rubric.json)与runtime分文件；
[协议](../data/manifests/v13-1-p2-typed-receipts-protocol.json)预先记录全部分母和停止规则。
第一消息自然要求预订、标签和保存实际结果，第二消息跨进程只查询说明；用户不制造UUID/ref。
Host只得到当条自然消息、公开工具合同及已捕获的实际来源。初始fault开关只交给业务backend，
future question、offline期望字段、gold和标准动作计划都不交给writer。

验证顺序：同SDK SQLiteStore的固定提案测试与catalog/config机械检查；源码READY/HOLD后
prepare两臂0HTTP，冻结实际tool catalog、prompt、整个Source与原账本，再串行微型自由Host。
固定提案拒绝能力与实际自由Host写入/消费成绩分开；不能选择故意填入标准错误答案的提案
冒充自由Agent效果。保存成功必须有真实commit；各失败、预算耗尽、unknown和not-run仍入表。

每消息12generation/输出4096/并发1；capture/真实ref lookup/Host/写入/查询/读回按实测范围
记成本，仍不把已有局部Store I/O称为完整测量。原连续账本不重置、Judge0、不换算美元/GPU。
实际结果见下文；不宣布完整可用性或研究门禁通过。

65受影响mechanical/SDK/MockHTTP检查通过（26deselected），Ruff5文件、strict mypy3源文件和
whitespace通过；初次42API失败、2最小正文自然检索失败及静态错误保留。旧默认catalog
SHA256a8e94be08e0b4114a215289a4cd612993bddf85a59b1e3b2bae3cd43a5c30926与预编辑完全一致。
两臂实际prepare0HTTP，tool catalog/prompt/source集合一致，199src+薄CLI共200文件，
源码HOLD。没有新路径或职责变化，原Foundation/CI归属保持，未重跑全suite/远端CI。

最小receipt JSON无notes时，原记录确实不含物品自然词。opt-in新增通过同owner/hash校验/
真实工具ref的原source内容作lexical关联，保持原排名公式、限制、存储和正文，两臂相同。
真实两记录search/read/update与foreign排除通过；内部分别source各get一次（2），
正常raw查询复用已加载源额外get0。Observer记录原读回、失败读、wallCPU与查询，IO仍partial。


## 首轮真实结果与独立读回

[结果清单](../data/manifests/v13-1-p2-typed-receipts-results.json)记录8案例臂/16消息/16独立进程。
真实SDK再次打开全部8个Store/world，核对当前记录、revision1、原始工具SourceEvent/hash/
object ref与真实reservation；每臂每例只有1次预约，无后续mutation或虚假Saved。
全部8条形成记录都由实际Host明确提出两字段JSON，4条Field有限claim与原观察匹配；
4条Ref有限claim仍标unchecked。6次初始prose/单引号正文被receipt_body_invalid_json拒绝，
原requested/raw提案和随后模型付费提交的新提案同时保留。未出现实际field/body literal conflict，
所以这轮不证明Field语义拒绝收益。notes、scope、自由正文与引用仍unchecked。

预定后续说明标准：Ref2PASS/1FAIL/1UNKNOWN，Field2PASS/2FAIL。两个confirmed后续都正确；
partial1两臂与partial2 Field把“前一次操作”错称为“即本次查询”，没有报告原局部结果。
partial2 Ref仅说标签未创建或失败，原失败尝试未知，不能算通过。所有8次后续都只调用
get_reservation，没有search/read，历史bank未送达；最早断点为历史检索选择，Attention不准入。
此外Ref confirmed2虚构2023-10-27绝对时间、partial2虚构2024-12-31截止；独立事实审查另记失败，
不把预定continuation分数偷换成完整事实可靠性或归因于grounding。

新增46generation/92756generation tokens/0embedding，与每个真实response和连续账本精确核对。
连续6435generation/11880568generation tokens/420830embedding tokens，unknown0/Judge0。
独立读回wall/CPU与文件/逻辑字节有记录；总Store I/O仍partial。原失败不被后续诊断覆盖。


## 历史送达诊断：保留负结果

同一真实bank/world/checkpoints的配对副本，新s3只给原自然问题；不直接带入s2回答。
[通用历史证据提示](../data/manifests/v13-1-p2-history-delivery-results.json)4腿：control均错把查询
当先前操作，candidate均说历史不明；全部仍只GET。新增8generation/13998tokens。
[明确历史查询工具规则](../data/manifests/v13-1-p2-explicit-history-query-results.json)2腿，新s4/
原bank/原问题：实际wire包含search_memory工具和完整规则，但仍只GET，没有送达历史bank。
新增4generation/7441tokens；两腿historical result均UNKNOWN，不能当成功。
这两个提示诊断不修复原记忆/回答，不重新宣称guard收益；也不证明已经调用的普通query失败。
保持Attention不准入。停止继续堆叠此提示分支，转向其余独立baseline/恢复合同工作。
连续6447generation/11902007generation tokens/
420830embedding，unknown0；SHA256 6379511737f91cf0d44b556bcbac30fe59a0e1829d1c8038d2a00198033577f0。
