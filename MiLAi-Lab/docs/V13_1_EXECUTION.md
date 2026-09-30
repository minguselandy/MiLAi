# v13.1 执行记录

日期：2026-09-30。状态：ACTIVE / R9正常门槛22/24；B0–B6真实微型与NoMemory当前工具已验收，P5机械恢复有限通过；完整P0–P8未完成。

## 授权与原始范围

用户明确要求详细阅读并执行 [原始规划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_1.md)。
原规划481行已完整阅读，原文 bytes 保持，SHA256
`e67cc5253cbe6967d935cc5c9b9f4453c731665d1937d9049e323c10e54dc9ca`。
DESIGN_ONLY 是原始设计快照，当前用户授权允许执行。旧v10暂停只描述其历史范围。
完整目标保持P0–P8；第16节只界定首批P0/P1/P2，不能以完成首批替代完成全部计划。
[60项要求清单](../data/manifests/v13-1-requirements.json)记录所需直接证据，未证明的要求不计完成。

## 当前身份与盘点

隔离分支 `feat/lab-usability-v13-1-20260930`，工作树
`/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-1`；基于实际fetch核对的
main `255dfcde5d73b9fc800cdd7f866460a09908c12f`。原入口checkout落后103提交，保持其
未跟踪草稿原样。未重新运行历史实验，未覆盖历史冻结或错误记录。

[P0原始身份核查](../data/manifests/v13-1-p0-freeze.json)包含实际容器、HTTP模型目录、
启动参数、挂载的模型配置/tokenizer/template哈希。7860、7862分别是既有JSON-action和
native-tools Qwen3.6-35B-A3B-FP8服务；7861为bge-m3。均实际GET200，上下文分别65536/8192。
`server_info`返回404，不能声称从该接口取得完整运行配置；改用实际容器参数与本地文件核对。
[完整权重身份](../data/manifests/v13-1-model-weights.json)已流式核查43个实际挂载权重文件，
合计39734807990 bytes，逐文件SHA256及前后size/mtime稳定；读取耗时121.84秒。
本地完整内容身份不等于可推断的upstream revision标签。

原连续账本仍位于原checkout `MiLAi-Lab/artifacts/ser-v20/budget.json`，核对SHA256
`7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。
起始累计6145次generation/11407086 generation tokens/416930 embedding tokens，unknown0。
只读GET、源码核查和开发代理消耗不记作实验generation；本批R1已新增28generation/35132tokens。
最新连续6173generation/11442218tokens/416930embedding，unknown0；详见[R1结果](V13_1_D0_R1_RESULTS.md)。
随后[R2固定bank对照](V13_1_RETRIEVAL_R2_RESULTS.md)新增4generation/4908tokens，原代码不能召回、
通用Unicode分词正确交付并回答；最新连续6177generation/11447126tokens/416930embedding，unknown0。
随后[R3更新对照](V13_1_UPDATE_R3_RESULTS.md)新增14generation/23053tokens；通用指令实现及时
修订、无重复卡，两组最终答案均正确。该轮终态连续6191generation/11470179tokens，unknown0。
随后[R4](V13_1_SCOPE_R4_RESULTS.md)形成提案虚构绝对截止日期，门禁失败，两组reader均NOT_RUN。
新增2generation/2214tokens；该轮终态连续6193generation/11472393tokens，unknown0。
随后[R5](V13_1_TEMPORAL_R5_RESULTS.md)相对时间通用提示保留本周/团队scope；原指令再次虚构日期。
新增4generation/4500tokens，该轮终态连续6197generation/11476893tokens，unknown0。
随后[R6](V13_1_SCOPE_R6_RESULTS.md)候选实际读取完整否定源和scoped卡后正确使用；原指令未读取，
两组最终均未错误推断，因此不宣称reader准确率优势。新增3generation/4046tokens；终态
连续6200generation/11480939tokens，unknown0。R7组合候选和正常24协议已冻结，先执行原六故事。
[R7实际六故事](V13_1_D0_R7_RESULTS.md)为5/6；对象lookup正确但最终回答矛盾，余18例NOT_RUN。
新增26generation/38144tokens，R7终态连续6226generation/11519083tokens，unknown0；R8单独
检验公开回执字段含义的消费，不修改原回答或bank。
[R8](V13_1_RECEIPT_R8_RESULTS.md)在相同实际lookup回执下，通用字段含义说明修复最终矛盾回答；
两组都无新业务效果。新增4generation/5314tokens；R8终态连续6230generation/11524397tokens，
unknown0。R9组合正常24协议已冻结，仍先检查原六故事，未宣布门槛通过。
[R9完整正常检查](V13_1_D0_R9_RESULTS.md)原六故事6/6后执行余18例；最终22/24，两个更新
版本失败仍计入分母。48消息/48实际进程及独立SDK全24读回，正常开发门槛通过。新增
107generation/170905tokens；R9终态连续6337generation/11695302tokens/416930embedding，unknown0。
后续每次形成、Host、embedding、恢复和失败重试继续原账本，不建立零起点替代账本。
价格与总费用上限未知，保持null；正式预算由pilot的实际分布决定。

[暴露清单](../data/manifests/v13-1-source-exposure.json)组合旧v8/v9、v10、LSA和contextual历史
来源，并从11个历史registry/selection/audit元数据计算保守并集：90个case ID、61个原source ID、
120个来源组引用、66个完整历史hash及65个MERIT seed。按source ID、完整历史hash及来源组
排除；MERIT0–4已曝光，5–64旧规划reserved不能
凭假设重新当未见。正式集未选；新增pilot仅预留60题及seed65–82的身份，未读取其问题或gold。

## 第一批固定开发输入

[D0运行输入](../data/fixtures/v13-1-d0-normal.json)在看到新候选成绩前冻结24例，保存、召回、
更新、scope、对象继续、重启各4例。每类第1例组成预定6故事。新公共消息由新进程读取相同
持久资源；更新同时检查历史版本，scope覆盖群体/一次性/项目/无日期锚点，业务检查原始
物品key、同一预订和无重复效果。这些是开发样本，不能转为独立论文测试。

[离线rubric](../data/diagnostics/v13-1-d0-rubric.json)与运行输入分文件，runtime不可读取。
语义是否正确需要核查原始回答、来源/版本和真实world，不能只用关键词命中宣告成功。
使用门槛预定>=22/24，同时owner泄漏0、虚假保存成功0；所有失败/未知仍留在分母。
正常检查不隐藏注入故障：对象组起始label服务可用，另外的partial/unknown真实故障归入P5。

P1/P2实现复用SDK Store/checkpointer、ApplicationWorld与既有模型/工具组合。Source由实际用户
或工具事件确定性捕获，模型只选来源/内容；Ref-only与Field-grounded独立，先只绑定公开回执
status、label_status。正文保留原提案且无语义真值保证；真实ref不等于正确字段。SQLite第一批
只声称实测范围，不能宣称通用跨系统exactly-once、Postgres CAS或生产并发。

## 外部baseline当前核查

[baseline核查](../data/manifests/v13-1-baseline-audit.json)记录源码、依赖pin和实际调用路径。
主foundation环境缺少外部依赖，已找到既有专用环境：Mem0安装版本2.1.0、commit
f8082a7345dadd9e042ebbc40b57b1498c8f6d63；SimpleMem环境含LanceDB0.25.3/pylance0.39.0，其实际159个源码文件已核对固定commit
db80b6a7c591e0ea730a058e9f5fc4eb06572299；Mem0实际149个文件也已核对安装源码身份。这些只证明安装/源码身份，不计作六项微型行为验收通过。

Mem0旧after_turn只摄入用户+最终助手；新的MERIT completed路径实际从checkpoint截取闭合回合，
保留role/id/content/tool_calls/tool_call_id/name/status后调用add_archive。该函数使用明确标记为
历史数据的JSON包，不改其原生抽取算法；实际HTTP wire与保留效果待P3固定微型运行验证。
不能由after_turn一个函数推断全部历史表，也不能把静态调用路径称为实测模型保真。

SimpleMem旧默认speaker保留role、工具字段和timestamp，原event/id只在trace source_mapping。
[P3微型检查](V13_1_P3_BASELINE_MICRO.md)新增独立opt-in lossless trace_equal_v1载体，
固定SDK MockHTTP检查12项通过；原生抽取与检索不改。完整原ID到达writer输入与原生持久保留
分开验收，真实外部微型两臂各5/6限定通过，回执局部结果消费失败保留；两臂原始SourceEvent ID均未进入
形成记录。Mem0首次离线BM25缺缓存0调用失败，既有缓存环境修正独立冻结并保留原分母。
新增48generation/88014tokens/3900embedding，逐响应核对连续6385generation/11783316tokens/
420830embedding，unknown0。固定各臂实际交付material的[公共合同诊断](V13_1_P3_BASELINE_MICRO.md)
新增4generation/4496tokens，两候选业务局部状态均正确，但Mem0候选虚构记忆引文，仍失败；
不改原micro结论，不归因于guard/结构。连续6389generation/11787812tokens/420830embedding，
unknown0。没有新增安装、下载或服务部署。

## 门禁与待办

| 阶段 | 当前证据 | 状态 |
|---|---|---|
| P0 | main/服务/ledger/基线安装/暴露引用有直接只读核查 | PARTIAL；完整候选身份和正式分组还未冻结 |
| P1 | R1六故事3/6、R7为5/6保留；R9六故事6/6，完整24为22/24 | NORMAL_GATE_PASS；两个版本更新失败，完整P1仍PARTIAL |
| P2 | 新显式合同65机械检查；真实16消息/SDK8臂读回，8条完整字段形成 | PARTIAL；有限合同成立，历史未送达/后续错误，未证明语义guard收益 |
| P3 | 外部两臂各5/6限定通过；B0–B6有238真实进程/42SDK读回与B0当前工具 | PARTIAL；旧计数bug保留并已独立对账；实际等额配置试跑待做，最近邻主张有限 |
| P4 | 四已曝光源×2×2、64真实形成/读取，独立SDK全16 bank再读 | SCOPED因素诊断完成；类型独立收益未证明，首轮列混淆保留 |
| P5 | 两种真实W1结果、W2及独立原资源W3 UPDATE/SIGKILL/replay | 机械原语PASSED_SCOPED；原完整Agent6故事失败保留，四臂比较待实跑 |
| P6–P8 | pilot身份预留；正式矩阵/第二家族/统计/复现/初稿要求完整保留 | pilot模型NOT_RUN；nominal正式来源题量不足；其余待执行 |

R9预定正常开发门槛已通过；完整Engineering-valid、Usability-ready全部配套要求和Research-supported
仍有未满足项，不能把局部门槛当完整规划完成。Product保持NO_GO。
完整计划不能因负结果或预算耗尽自动改写为较小目标；后续按实际证据更新每项要求。

## 反思记录 0：已有字段真实性断点

观察：v10 R2错误业务ID和错误完成正文曾真实持久化；当前v12整理只保留旧语义。
最早断点：没有把业务操作字段与真实工具观察建立受限支持关系。竞争解释：引用合法性、
字段支持和正文推断可能各自不同；仅提示严谨也可能解释改进，不能预设新结构独立有效。
最小区分实验：同一真实ref+错误status/label_status提案在Ref-only与Field-grounded分别提交，
保留原提案与拒绝回执；后续实际Agent与Prompt-only对照另冻，不以固定提案回放代替Agent收益。
不变：旧默认、公开工具合同、来源/owner、两字段支持范围；不增加Attention或reviewer。
否定条件：合法字段被大量误拒或Ref-only同等减少传播，必须修合同或缩小贡献。
本次零模型机械诊断不发生generation；真实D0每消息最大12调用/4096输出/并发1，全部计费。


[P2显式回执实际运行](V13_1_P2_TYPED_RECEIPTS.md)8案例臂/16独立进程全部完成；8条实际Host
提出两字段JSON，Field4条有限claim匹配，Ref4条unchecked。6次初次不合法JSON拒绝和付费新提案保留。
后续两臂各2/4符合预定说明，Ref另1FAIL/1UNKNOWN、Field2FAIL；全部只GET，历史未检索送达。
Ref另外2条scope虚构绝对日期，完整fact review不通过。新增46generation/92756tokens，连续
6435generation/11880568tokens/420830embedding，unknown0。有限字段不保护scope/notes/引文；完整P2仍PARTIAL。

P2历史送达提示诊断4+2腿仍无memory query，原失败/unknown保留，Attention不准入。新增合计12generation/21439tokens；最新连续6447generation/11902007tokens/420830embedding，unknown0。[直接证据](V13_1_P2_TYPED_RECEIPTS.md)。

[来源容量核查](V13_1_SOURCE_AVAILABILITY.md)：旧来源组全部解析并排除后，valid剩63题/15来源组、personalized剩95题/79来源组，新pilot前已不足各100正式题。用户确认无额外来源。新增pilot按整组件预留117行后，三任务剩250/7/54题；官方HEAD未变化。正式集未选、不复用曝光题，nominal缺口保持，完整目标继续ACTIVE并执行其余阶段。

[P4类型×scope诊断](V13_1_P4_TYPE_SCOPE.md)首轮开放scope混入类型，保留；R2清洁列因素下Flat2/4、Type-only2/4、Flat+Scope3/4、Type+Scope2/4另1UNKNOWN。无类型独立收益；来源引用存在仍可能错归用户意图。两轮新增64generation/102299tokens，最新连续6511generation/12004306tokens/420830embedding，unknown0。

[P5结果与恢复](V13_1_P5_LIFECYCLE.md)保留R1/R2全部原始失败。真实两种W1结果通过独立实际query区别；W2重新打开相同资源。
另以未改R2 clean资源副本完成真实UPDATE2→3/W3硬退出/精确receipt replay，原record/history仍为3。
这是一个workflow、协作串行SQLite的机械原语；R2完整Agent六故事仅1/6有限成功，不能改称完整P5质量通过。

[强简单实际验收](V13_1_P3_CONTROLS.md)执行七臂共238不同进程：224完成、7owner拒绝、7真实容量拒绝；42份SDK资源读回一致。
四次真实rolling summary、原始角色/ID/时间/工具正文、无未来query入writer、拒绝前后bank不变均有直接证据。
原runner调用计数监听错误保留，Root由完整response/error wire核对91generation/73310tokens/5005embedding，未改原结果。
另NoMemory实际当前get查询成功，长期记忆仍为空，world未变，新增2generation/1252tokens；该当前任务不需要历史记忆。
历史问题35答案有26有限正确、9能力范围内未知；未知不计语义成功，不由固定开发故事声称泛化。
最新连续账本6762generation/12788273generationtokens/425835embeddingtokens，unknown0、Judge0。
两套B2/B3/Ours配置共48个旧开发题对尚待执行；新pilot仅身份预留，完整目标与发布边界不变。
