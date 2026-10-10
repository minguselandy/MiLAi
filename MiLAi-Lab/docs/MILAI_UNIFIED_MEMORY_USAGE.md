# 统一记忆功能候选与当前执行状态

## 2026-10-10：基线对齐开发，真实比较尚未执行

用户已继续执行[基线对齐、薄适配与方法有效性规划](MILAI_BASELINE_ALIGNMENT_ADAPTATION_AND_EFFECTIVENESS_PLAN_20261010.md)，
并明确使用一名集成者和三名开发者。当前集成分支为
`feat/lab-baseline-alignment-integration-20261010`，本次接线开发以 `d1d300a` 为基线，
维护K10和原生资源闭合修复继续合流，尚未冻结最终候选；
共同设置见[本地协议卡](MILAI_BASELINE_ALIGNMENT_PROTOCOL_20261010.md)与
`configs/milai-baseline-alignment-local-v1.json`。新分支尚未推送或新建 PR，未进入原 `5019968` 运行。

| 首轮后端 | 已接通能力 | 实际结果边界 |
|---|---|---|
| RawRAG-local | 原文完整会话的本地 BM25 检索，保留实际角色和时间；直接交付共同 Reader，不经过 Editor 或 Selector | 接线和持久路径已检查；未执行 E0/E1，不称作者模型分数复现 |
| Hindsight-native-local-recall | 官方 SDK／原生 retain、recall，独立 bank 和稳定会话 document_id；确认实际原生完成状态，完整返回与共同 Reader 分开保存 | 原生服务尚未启动，内部模型请求接入原连续账本仍待完成；无实际原生闭环或 QA，未观测用量不填零 |
| MiLAi-memory-only | 薄门面复用原 Source、MemoryService、维护 recipe 和 Reader；首轮直接读取实际语义状态及已有支持 | 接线已完成，实际形成、更正和 QA 尚未在新配置运行；不经过普通 Host 业务分类，也未增加原文检索兜底 |

首轮按 source-only 在线前缀准备：四个既有开发用户各前八会话，**每臂32会话、73 QA、72原生更新机会**，
三臂共219个主 QA 输出机会。各后端／用户独立空库；每会话实际写入完成后仅答该会话问题，
persona、gold、更新标签、未来会话和测试答案不进入方法输入或回写历史。
维护候选 K10 保持原设置，与可计数后端 QA20、隔离更新评价 K10 分开；Hindsight 使用原生 token 预算，不能称 K20。
共同 Reader 为既有 Qwen，thinking=True、output32768、context65536、margin512，完整输入限额32256；
首轮不调用二次 Selector。RawRAG/Hindsight 没有真实会话抽取输出或可隔离的参考查询时，对应形成／更新指标为 N/A，
不补造输出或让参考检索改变正常方法状态。三个后端预测结束后再独立评分。
先前离线准备采用维护候选K20，实际模型调用为0；恢复K10后将在新根重新prepare，
不同配置的准备不复用，不将其当成最终候选冻结或实际实验结果。

新增适配、准备与离线检查的**实际 Qwen／BGE／Judge 调用均为0**；E0、E1及最新42消息 Host流程
尚未真实运行，也没有新语义分数。Host工具复用两条已曝光故事，各3次重复，共6故事运行／42消息，
覆盖保存→更正→历史、业务续办→只补保存→新实时查询、遗忘→重开→查询三个共享流程。
原模型候选、完整公开交付和实际操作回执分存；旧 `5019968` 两故事14消息的只读整理不算新候选验收，
COMPLETED或脚本通过均不自动授予语义通过。

Root最终受影响合组139项通过（9项公共入口＋4项后端＋35项wiring＋91项evaluator）；
先前133项及Root／Native复查含重叠，不另行相加。8个源码严格类型、全Lab Ruff、
267源码／6 packages／80 optional登记矩阵及active-package DAG通过。
Tools边界发现新Host helper的动态导入有3个unresolved，正改为静态可解析的原评价器导入，边界仍待复查，未放宽规则。
上述均为工程检查，不是语义样本或真实模型验收。
原 `5540ac8` 的 [Fast 38028952446](https://github.com/minguselandy/MiLAi/actions/runs/38028952446)
成功，[Full 38028952475](https://github.com/minguselandy/MiLAi/actions/runs/38028952475) skipped，
只属于该旧 head，不能转作当前新代码的 CI 结果。

原五方法固定观察为 **2026-10-10 07:53:54.506308 UTC／北京时间15:53:54.506308**：
PID1854770匹配、原 HTTP 租约 OWNED、源码仍为 `5019968`；B0 保存98个完整会话，
242题检查点＝240答案＋2已知缺答，其他四臂 NOT_STARTED、Judge0。
维护97 completed＋2 incomplete，205笔唯一确认提交，`current_boundary_source_required`拒绝3次。
生成780请求、9628792 known＝charged、embedding104963 tokens；该观察时点在途和新增 unknown 均为0。
这些是运行前缀和固定时点成本，阶段仍未闭合，没有本轮方法排名。原缺答、拒绝和费用保留，不热改、重启或拼接新源码。

资源释放且 Root 明确调度后优先 E0／E1，普通 Host 功能线可继续；全部旧科研待办不再成为新任务的永久前置。
真实调用仍由 Root 在原连续账本串行调度，未知结果不盲重试。新候选尚未冻结确认，E2主要断点诊断、
必要E3对比、长历史／保留用户／外部迁移及真实Host功能结果仍待完成；没有方法优势或 Product ready 结论。
原生失败若已确认 drained，记录 FAILED／resources_settled=true；超时或状态未知则保留 RESOURCE_UNSETTLED，
不把失败写成成功，也不在资源未确认释放时推进下一臂。

## 先前功能优先协议与固定观察（保留）

以下内容保留原时点结果；当前执行顺序以上述新规划与协议为准。

当前按用户提供的[全局修复与功能优先规划](MILAI_GLOBAL_REPAIR_AND_FUNCTION_FIRST_PLAN_20261009.md)
执行，集成分支为 `feat/lab-global-function-first-20261009`。第一版源码 `bbe77e9`
的真实 Host20 已闭合；历史修复候选 `milai-global-function-first-v2` 冻结源码为 `1cfb400`。
当前选择 `milai-global-function-first-v3`，冻结源码为`5019968`。
最新交互收敛开发基于已发布的 `263bc787`，仍在同一集成分支；运行中的
`5019968` 归档不包含这些后续改动。当前问题入口已同步到
[Build-first 问题表](MILAI_BUILD_FIRST_ISSUES.md)，不再把共同投影和逐题保存列为未实现。
本次三项交互改动集成提交为 `40bf7aa`，见下方实现及验证范围；它不是本轮实验源码。
后续容量续读提交为 `dc4f182`：开发树已在超限时实际发送整事项页面，并在最终回答前
重开真实正文；原 `5019968` 仍只保存分页计划。这一新协议尚无真实模型验收结果。
2026-10-09 23:12:49 UTC从空库开始复验原Host20，23:33:00 UTC已闭合并对账；
输出`artifacts/global-function-first/host20-5019968-v3`，runtime为`host20-5019968-runtime-v3`。
同版五方法完整预测已调度，实际PID1854770，输出`five-dev277-5019968-v3`，
配置`five-dev277-5019968-v3-prepared/config.json`，runtime为`five-dev277-5019968-runtime-v3`。
按B0/B1/B2/M/Append-only串行，各277会话/705QA/595更新，合计1385/3525/2975；
各方法/用户新空库，旧前缀不拼接，全部预测保存后再单独统一评分。
运行时看最新PID与原生execution终态，本文RUNNING只描述这个固定时点。
2026-10-10 01:50:36 UTC（北京时间09:50:36）固定观察为B0已保存37个完整会话（100QA），
逐题检查点100，已知缺答0，其他四方法尚未开始；
进程匹配、推理租约持有。真实预测/评分与后续阶段仍未闭合，不能据此比较方法质量。
逐阶段用量核对脚本为ignored `inspect_five_dev277_5019968_usage.py`，只读既有响应用量、
请求计数与原账本，不调用模型、数据集或银行。01:50:07 UTC固定快照：312生成响应
3440007known、259embedding响应36120tokens，与该时点账本known差额分别一致；
另1生成请求在途，不能把这份部分统计当阶段闭合成本或新unknown终态。
312份生成的模板预计算输入数均等于服务端prompt_tokens，均stop，无缺失usage或计数不符。
观察峰值：Extract13781、Writer-select25711、Editor32223、Reader-select2942、Reader28511；
完整输入限额仍32256。快照为`five-dev277-5019968-usage-20261010T015007Z.json`，
这些峰值只描述已返回请求，不证明后续容量、全部语义或方法优势。
01:50:36 UTC后续账本观察已有313生成请求、3471370 known=charged，embedding仍36120tokens；
此时新增unknown为0。两个固定时点分别保留，不能把较早在途预留写成失败或阶段终态。

最新固定观察 **2026-10-10 05:48:46 UTC／北京时间13:48:46**：进程、源码与租约匹配，
B0 保存67个完整会话、170题检查点，其中168份答案、2个已知缺答；其他四方法未开始，Judge0。
两个缺答分别为原session index 56/qa1的32957 tokens及64/qa0的35279 tokens，
均大于32256，均在HTTP前拒绝；原hypothesis=null、容量回执、未交付计划和分母保留。
维护66 completed＋1 incomplete，122笔唯一确认语义提交，原边界拒绝1次。
账本543生成请求、6536501 known／6612322 charged、embedding68165 tokens；另1生成预留
在途，这仍非闭合成本。新分页代码没有进入该运行，不补写或重试这两个已知缺答。

先前已发布的固定观察 **2026-10-10 05:09:22 UTC／北京时间13:09:22**：进程与租约仍匹配，
B0 保存62个完整会话、156题检查点，其中155份答案、1个已知缺答；其他四方法未开始，Judge0。
新增缺答是第56会话 qa1 的完整输入32957>32256，`ReadCapacityUnavailable`、HTTP前拒绝，
最终请求未发送；原题保留hypothesis=null、容量回执和未交付计划，不重试、不移出分母。
这验证了冻结缺答策略能够继续运行，也表明共同投影没有解决所有长期容量问题；
冻结benchmark仍不执行该分页计划，不能把计划生成写作该题完成。
此时维护61 completed＋1 incomplete，109笔唯一确认语义提交；拒绝
`current_boundary_source_required` 1次。这些计数不证明语义通过。
账本502生成请求、6120523 known／6237254 charged、embedding61840 tokens；
另有1个生成预留在途，尚非unknown闭合失败或阶段结算。

本轮实验汇总（2026-10-10固定观察；版本之间不组成方法排名）：

| 实验与源码 | 实际状态 / 结果 | 成本与结论边界 |
|---|---|---|
| 原八事项共同投影 / `bbe77e9` | 原完整输入32446降至30520，低于32256；8事项及原证据保留。另一次真实只读Reader返回stop | 独立Reader1次、32686 known；离线可容纳与一次返回不证明答案全面正确 |
| Host20 v1 / `bbe77e9` | 20条各尝试一次；17 COMPLETED、3 FAILED | 99生成、784557 known；35 embedding、1532 tokens；保留更正、遗忘及恢复失败 |
| Host20 v2 / `1cfb400` | 原13条及未尝试7条分段闭合，合计18 COMPLETED、2 FAILED；原STOPPED不改写 | 102生成、902072 known；50 embedding、1856 tokens；业务纯保存误分类等仍失败 |
| 四用户前8会话M / `1cfb400` | 32会话、73QA、72更新预测闭合；QA44/73 Correct（有效71），更新48/72 Correct（有效67） | 预测237生成、2159360 known；Judge含补充677请求/676响应、2812589 known、2859968 charged；1未知项保留invalid且未重试。不是完整277会话结果 |
| Editor thinking来源对照 / `1cfb400` | 固定7来源×两模式×两次=28提案全部保留；来源审查闭合，无Store提交 | 28生成、527243 known；True仍有语义错误，4/14输出超过Host8192。只支持本次benchmark配置选择 |
| Host20 v3 / `5019968` | 20条各尝试一次，20执行COMPLETED，成本对账闭合；存在明确语义失败 | 122生成、1666232 known；63 embedding、3571 tokens；0新增unknown。业务遗忘零撤销，COMPLETED不等于语义通过 |
| 五方法完整开发 / `5019968` | 05:48:46 UTC固定观察RUNNING：B0 67/277会话、170/705题检查点（168答案＋2缺答）；其他四方法未开始，Judge0 | 当前543生成、6536501 known／6612322 charged，另1生成预留在途，非闭合成本。总计划1385会话/3525QA/2975更新，全部预测后统一评分 |
| Native/drift、紧预算、保留16用户、外部及完整Host | 准备或待执行；不计入任何实际通过数 | 相关准备0模型调用；必要M消融、最终冻结、外部28题/10题完整答案审查、Host135案例/192消息及冻结后新故事仍待完成 |

表中五方法行采用05:48:46观察；前文两份早期观察保留，三者都不是阶段终态。

目前已确认共同投影、独立保存恢复和真实回执接线可运行，尚未证明一个方法在完整历史中优于
强简单对照。Host20v3的业务恢复只创建一笔预订，标签续办未重复预订，纯保存确实写入r3；
但业务遗忘10次目标选择均遭已知无效果拒绝，正文/历史仍可见；规则例外、非目标保持、
历史读取和实时业务查询也有失败。普通语义失败保留并继续既定实验，不能据冒烟宣布功能全过。
本轮提交包含Lab实现、配置、必要检查和整理后的文档，另调整共享CI中的Lab测试归属；
Product/Archive实现未修改。原始Source、QA/gold、Reasoning、HTTP/trace、银行与本地运行产物
保持ignored。Product仍为NO_GO，六项最终交付仍未完成。

本轮已推送开发分支并创建叠加在PR119之上的[草稿PR120](https://github.com/minguselandy/MiLAi/pull/120)，
首份汇总提交为`62afc649b5519ab26da8ae4eb527cdd0f7aa6b6b`，远端head及正文已核对。
首轮Fast `38014947469` 的Lab gate因新增`reader_projection.py`未进入既有源码登记清单而失败；
已补充该一项登记。修复后本地矩阵覆盖262源码/6个canonical package，15项既有源码所有权/
请求架构检查、全Lab Ruff与该文件严格类型检查通过；远端后续CI按自身运行身份另行确认，
不借用旧CI或宣称Full全部通过。登记改变仅用于发布树的身份/验证覆盖，未回填旧请求身份，
正在执行的源码归档、配置与实际结果仍冻结在`5019968`。
第二轮Fast `38015194385`已通过登记、边界、Ruff与Core类型检查，随后在收集投影SQLite测试时
发现Core环境没有该测试所需的`langchain_core`。已将`test_reader_projection.py`登记到
既有Foundation测试组，并同时更新Fast/Full的Core分组及Foundation实际pytest命令；
三项投影测试全部保留且仍执行，不用skip或放宽依赖边界绕过检查。更新后的矩阵已通过，
optional测试归属78项；此改动不改变方法、模型、预算或正在运行的归档。
对应既有SQLite/投影/外部适配测试组首次143通过、1失败：旧状态视图用例直接比较共享元数据
引用和完整断言。现解出共享表后仍严格比较全部断言字段，原重开、历史、非目标和状态不变
断言均保留；该单项复查通过，首次失败仍保留，不将重复检查计作新样本。没有模型HTTP调用。
第三轮Fast `38015684756`的Core及外部适配通过，Foundation在既有Host→离线评价组中
556通过、4失败：新增`request_failures_appended`及`memory_receipts_appended`字段未被旧
retained-agent评价合同识别。评价器现仅接受三个明确布尔反馈标记；任一True时分别核对
原候选实际HTTP与完整公开交付的捕获证据，不把追加程序文本当模型生成。旧缺省合同兼容，
非布尔值、候选缺失、HTTP/trace/捕获不匹配仍不能通过；语义仍UNREVIEWED。
对应88项评价证据链检查、8项既有Host→评价器正常SQLite/scripted流程、Ruff和严格类型
通过，0真实模型调用；未改旧输出/标签/终态，未对当前完整预测进行提前评分。

原Host20新空库运行在2026-10-09 17:56:46 UTC停止：13 COMPLETED、7 NOT_RUN。
两次遗忘拒绝回执缺少effect字段，汇总保守标成unknown；独立代码边界及只读数据库核对
确认仅这两次属于写入前无效果拒绝，原STOPPED结果保持原样。18:04:32 UTC启动单独补充运行，
仅处理尚未尝试的7条新输入，仍使用同一冻结源码，已于18:11:41 UTC闭合：5 COMPLETED、2 FAILED。
原20条输入各尝试一次，分段总计18 COMPLETED、2 FAILED。四用户前缀M于18:14 UTC启动，
19:19 UTC已核对预测闭合：32/32会话、73/73回答、72原生更新机会，无已知只读缺答。
源码仍为`1cfb400`，输出`artifacts/global-function-first/prefix8-1cfb400-v2/M`；
原Judge评分进程在最后会话中消失，22:38 UTC核验为31/32会话已评分；
655份Judge响应均stop，第656请求有请求/账本预留、无响应，原终态缺失，不能标成完成。
22:42 UTC单独启动评分补充，只发送从未尝试的657—677项，22:47 UTC已闭合并对账；
第656项保留invalid/unconfirmed，不重试、不猜标签，原中断输出和费用完整保留。
补充目录为`artifacts/global-function-first/prefix8-1cfb400-v2-score-supplement/M`，
同一冻结源码/配置，重用全部原预测和31份已完成评价，不重做Writer、Reader或embedding。
实际结果位于 ignored `artifacts/global-function-first/host20-1cfb400-v2`，原运行与补充运行
各自保留execution/results/accounting；调度前核对实际终态与PID。
旧失败、费用和历次运行观察完整保留在[历史状态页](MILAI_UNIFIED_MEMORY_USAGE_HISTORY_THROUGH_20261009.md)，
其中“RUNNING”均为原时点快照，不作为当前进程状态。

## 本次交互收敛：实现范围与验收边界

根据本次核查，保留一个 MemoryService 及 Grounded Memory、Verified Object References、
Semantic/Episodic Memory、Grounded Revision、Lifecycle Recovery 五条方向。
当前增量减少模型在已确认失败的操作环节中重构身份、混用证据和遗漏受影响旧语义的负担；
不新增 Planner、摘要 Agent、检索模块、写后审核循环或配置开关。

- 非 legacy 工作视图的既有 Reader 和 forget 使用请求内短 `target`。映射限定在实际
  bank/owner/session/message/config/Source 上；实际正文目标仍绑定原精确凭据，候选、
  历史索引及后续页只取得导航目标，凭据为空，不能用来遗忘或修订未读正文。
  旧目标、伪造目标、变更版本和撤销后的引用仍拒绝。I2 修订沿用已交付的 `r/u/e/h`。
- read_goal 支持旧字符串和明确的 `{purpose, evidence}`，区分当前解释、保存历史、
  原始来源和实时业务观察。reading_requirement 表达实际取得类型、缺失类型和真实续页；
  它只统计交付，不判定目标版本、全部条件或答案证据已经充分。历史索引、正文及原文
  导航均回到既有实际读取，续页目标与读取状态中的下一步一致。
- 已交付 Tool Source 中的真实 VerifiedObjectRef 可直接交给原 `get_reservation` 或
  `get_document_status`，无需模型重拼 external ID。原公共查找参数仍可用于别的对象；
  两种选择互斥。新查询保留原 Host generation/call/thread、权限、journal 和恢复路径，
  只有本次实际执行并交付的查询回执才记作新观察；旧回执及仅提供工具不算实时核对。
- 原 Editor 与 Host 共享受影响语义指令：对完整已交付事项检查条件、例外及旧总述；
  在同一提案中同步修订受影响部分，保留仍有效范围。新更正需要当前依据，必要旧含义
  需要实际重交付 Source；`h` 本身仍不能支持新措辞，旧肯定来源仍不能证明本次撤销。
- 正常 Host 集成还修复目录刷新挤掉刚选中旧 Source 的问题；刷新当前输入保持实际读取
  的工作集，不代替用户选择新事项。原读取成功回执先落盘，再登记交付和短引用；
  回执未知不能登记成已送达证据，未知重放不补签目标。

这些是 Lab 非 legacy 模型工具 API 的实际变化；legacy 读取参数保持兼容，Product 的
公开 Schema/API/权限/Canonical 未修改。遗忘仍是可见性撤销，审计与检查点字节保留，
不宣称取消业务对象或物理清除日志。新交互实现未进入运行中的 `5019968`。
脚本/SQLite 接线通过与模型语义稳定性分别验收；后续真实模型首先复验保存→更正→历史、
业务完成→只补保存→实时查询、明确遗忘→重开→查询，不能由程序检查宣布已解决模型选择错误。
冻结 `5019968` 的超限分页计划仍未执行，当前完整实验保持原缺答策略和全部分母。

交互增量本地验证：记忆/Editor/应用既有受影响组378项通过；Host/工作视图/投影组
首轮350项通过、2项旧投影预期失败。旧预期现先绑定实际交付目标再解出共享元数据，
仍逐字段比较全部语义、正文、范围和原Source导航身份，未删断言或预填未交付目标；
三项投影复查通过。三条正常Host连续流程最终3项检查通过；六项既有legacy/普通入口检查通过，
另11项实际历史/导航/视图与读取回执检查复查通过，重复项不计作独立实验样本。
8个受影响源码严格类型、Ruff、262源码登记矩阵及两项依赖边界检查通过，
0新增真实HTTP/模型调用。脚本首轮失败保留；所暴露的目录刷新丢失Source已修复。
每次推送的CI以自身commit核对，旧`263bc787`的Fast成功、Full skipped不移用于新head。
汇总提交 `2d32dc1` 自身的 Fast `38026697455` 已成功，Full `38026697450` 为 skipped；
该结果不转移给其后的分页源码或汇总提交，新head以自己的CI核对。

## 容量续读：开发实现与冻结运行分开

`dc4f182` 复用同一个 Reader、原选择schema及固定实际检索快照；不新增Agent、检索模块、
事实摘要或配置开关。正常 staged 仍一次选择、一次回答。只有下一次完整选择请求或最终
请求超限时，才用原调用额度继续读取；每页成本包含问题、用途、完整事项、目录、状态及
输出说明，thinking参数与该次实际请求一致，始终预留最终调用。

原选中范围保留，`done=true`不能跳过尚未处理页。模型可在原固定池选择最终要重开的
真实事项，`done=false`可在剩余额度内再次重开。原选中引用、确认交付的页、有效选择
步骤和最终重开引用分别保存；确认交付类型不证明答案充分，引用及导航不携带遗漏正文。
最终回答只收到重新投影的实际正文，不接收上一页草稿作为事实依据。

页请求使用确定性缓存键；原响应已保存但进度未保存时，只重新应用原选择结果。
原request存在而response缺失仍按unknown停止，不更换键重发。确认length记录实际输入
交付，保留未完成状态，不采纳截断选择；统一评分定位真实页响应。
单事项不可容纳或读取额度耗尽用 `ReadDeliveryIncomplete` 记录原原因，不能伪造为token
超限；最终重开仍超限则保留真实容量回执。已声明缺答策略将这些缺答保留为null及原分母，
不会调用Judge猜标签，fail-fast策略仍停止。

本地Reader接线、工作集及投影39项通过，其中9种新场景覆盖真实分页、最终重开、
后续选择继续、最终仍超限、单事项超限、预算耗尽、缓存恢复、unknown及length；
重复检查不计作模型样本。受影响源码严格类型、Ruff、262源码登记矩阵及两项依赖边界通过。
SQLite记忆、Source和原检索快照保持不变；仅本地HTTP mock，0新增真实模型调用。
这是新的读取协议开发证据，不补写冻结实验、不解决全部长期容量或语义充分性，
也不替代三个真实模型连续流程与完整研究范围的验收。

## 当前实现与入口

当前一个配置文件 `configs/milai-global-function-first.json` 提供 functional 和 benchmark
两个入口。Host 维持原 JSON v9 当前请求、staged/record、8192 输出、24 次消息调用额度；
benchmark 维持 staged/record_units、K10、65536 上下文、32768 输出、512 余量；
v3只将benchmark Editor thinking开启，Host Editor仍关闭。两入口其他阶段配置不变。
两入口共用既有 Qwen3.6/BGE 服务和原连续账本，保持各自原来的读取权限。

- `memory/reader_projection.py` 是纯投影。实际单元替代整版正文必须有精确渲染证明；
  不可证明时保留正文。重复完整元数据共用一张单层表，不推断缺失信息或继承默认值。
  benchmark 的原 `revision_evidence` 正文和范围仍直接交付；Host 保持原文和历史工具。
- 完整请求容量使用部署的真实 Qwen 模板和阶段 thinking。逐条成本只作提示，
  联合容量另算。超限保留全部所选引用、未交付状态及整事项页面计划；
  benchmark 当前不执行该页面计划，已知 HTTP 前超限记录缺答后继续自然历史。
- 已确认 CURRENT 业务 schema 或 length 失败且用量已知时，只有独立明确的当前保存范围才继续记忆工作，
  业务分支不取得执行许可。纯保存恢复不发现或重办业务；当前只读不继承旧写权限。
- 完成信息累积实际保存回执，每个已返回批次立即进入 trace；原文捕获、语义提交、
  未完成业务和遗忘分项表达。原始模型答案与程序附加反馈分别保存。
- Extractor/Editor 保留考虑、愿望、计划、说话者与主体；候选仅作线索，Source 才是依据。
  既有引用 keep、原文 Episode 和局部算子继续复用。

正常使用入口示例（从 MiLAi-Lab 执行；使用已安装的Lab环境）：

```bash
MILAI_PYTHON=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime prepare \
  --config configs/milai-global-function-first.json \
  --root artifacts/global-function-first/personal
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime message \
  --root artifacts/global-function-first/personal --bank personal --owner example \
  --session example --message-id save-1 --text '请记住，我的午休提醒用静音模式。'
```

解释器路径可替换为已安装Lab依赖的环境。runtime目录在导入SQLite等模块前设定；
当前机器的系统`python`不可用、默认临时盘已满，工作树复用原checkout的`.venv`。
prepare只准备；message是真实功能调用，会使用现有服务和账本。原实验配置与
默认 fail-fast 保持兼容，不把旧请求重新解释成新策略。

## 已闭合验证与旧实验

原失败八事项经实际 Qwen thinking 模板、原问题和 read_goal 独立复算：
**32446 → 30520 input tokens，限额仍为 32256**。8/8 有整版渲染证明，
56 个单元、39 段原证据正文/范围、14 项正条件及562项时间字段通过还原核对。
该材料检查为 0 HTTP。另在第一版冻结源码上执行一次真实只读 Reader：
正式 stop，实际输入30520，输出2166（含thinking），合计32686 known/charged；
0 embedding、0 Judge、新unknown0。原始模型答案已保存，语义正确性尚未统一评分。

第一版原三链20消息在2026-10-09 17:19:01 UTC闭合，20/20实际尝试，
17 COMPLETED / 3 FAILED。逐响应核对为99 generation / 784557 known=charged，
35 embedding / 1532 tokens；stop53、tool_calls44、length2，新unknown0，Judge0。
fixture/control不变，每个新消息单独CLI进程；失败消息未重试，旧运行未热改。

| 原链 | 结构完成 | 真实断点与范围 |
|---|---:|---|
| 保存、切换、重开6消息 | 6/6 | 两项实际保存，后续只读无语义或业务写入；不据此推出完整语义验收 |
| 更正、历史、遗忘8消息 | 6/8 | 两次确认length；Editor首次补造起效日期、漏改明确通知值；Reader错误继承未规定分组频率、误解查询缺失 |
| 业务、结果保存、遗忘6消息 | 5/6 | 首请求在多余旧请求解析阶段schema失败、尚无业务效果；故未验证原本的部分业务续办链。后续确实撤销8个来源可见性 |

更正链当前读第一页实际送4/5单元，第5加入后约8922>8192；首单元已送达，
历史17项确为三个版本5+7+5语义单元。共用元数据补丁的完整当前页为6593/6587，
历史首版完整5单元为6027/6020，均包含表及说明；历史仍需分页。零HTTP还原检查保持所有字段，
不改变页额度、正文、范围、实际选择器或原文权限。
当前补丁还处理已知截断的独立保存、无issued旧请求时的确定空选择，以及真实保存回执反馈。
Source提示将明确值与实际状态比对，未知起效日期保持未知。第二版前13条实际调用为
71 generation / 565201 known=charged、1246 embedding tokens、新unknown0、Judge0。
补充段另31 generation / 336871 known=charged、610 embedding tokens。合计逐响应核对为
102 generation / 902072 known=charged、50 embedding / 1856 tokens；stop61、tool_calls39、length2，
新增unknown0、Judge0，原停止和补充终态分别保留。更正链首次仍补造季度日期并被拒绝；
后续明确通知值实际提交，但Reader仍把整体频率
错误赋给未单独规定的分组。有效遗忘实际撤销一个事项及9个来源；未形成事项的初始Source
仍可见，不能据此宣称全部关联原话已遗忘。补充链已实际形成一次部分预订和一次单独补标签，
只有一份预订、两次业务尝试；其纯保存请求却被CURRENT误解成业务续办，未取得保存许可。
业务遗忘在已确认length前提交r3语义撤销，未调用forget_memory或撤销可见性；原话/历史仍可读。
重开模型把retracted误报成已清除，不能算成功遗忘。上述普通语义
失败保留，不以COMPLETED冒充验收。原始答案和附加回执分存；前表费用仍仅描述第一版。

旧 M36 (`36b0401`) 仍为 FAILED：21 个完整会话预测/46 答案，末会话另有2个实际响应，
qa2 在 HTTP 前因32446输入终止。22份维护结果中17 completed/5 incomplete，
43去重提交、6 current_boundary_source_required 拒绝。旧数据不补成新候选轨迹。
旧闭合成本为162生成/1748782 known tokens、140 encoder/18648 tokens，新增unknown0。
原全局账本固定闭合值49574请求/227101922 known/227378618 charged、2042879 embedding，
历史 generation unknown6；不重置或把后续实时账本差额误记成旧 M 成本。

第一版集成后29项受影响正常 SQLite/模拟 HTTP 检查通过；受影响文件 Ruff、严格类型检查
及 package/tools 依赖边界通过。检查记录在本地 ignored 验证产物中保存。
模拟调用不计真实模型样本，也不宣称完整仓库或远端 Full 通过。
第二版请求修复19项检查、合流后的共同投影及正常Host10项检查通过（包含重叠复查）；
三项新Reader检查与Source开发者12项既有检查另有闭合记录。六个受影响源码严格类型、
Ruff、依赖边界及旧八事项真实模板复算通过。没有把重复检查累加为新样本。
开发分支另合入`e41787a`：仅两处已知写入前遗忘拒绝返回effect=none，验证及异常路径不变。
开发者5项窄检查和Root合流后1项真实SQLite检查通过（重叠）；写入后回执丢失仍为unconfirmed，
裸旧rejected回执仍为unknown。该补丁未进入冻结`1cfb400`，不改写实验身份或历史结果。
开发分支又合入`0d297ad`：仅澄清既有CURRENT提示，纯补存仍是记忆续办，查询/跳过已存
是执行限制，禁止应用动作时业务为空；纯遗忘不额外要求新语义保存。schema与授权程序未改。
16项既有mock/SQLite检查、Ruff/类型通过；Root合流后复查1项纯保存恢复通过（重叠）。
合流时实际模型语义尚未复验；历史`1cfb400`对照不含该补丁，v3已纳入上述两个工程修复，
其实际结果见下段。

v3原三链Host20实际全部尝试、20 COMPLETED，仅表示结构结束。122生成/1666232 known=charged、
63 embedding/3571 tokens；61stop、61tool_calls、无length，新增unknown0、Judge0。
原20逐消息用量、20完整trace与固定账本逐项相符；Root已阅读正式答案并核对实际回执。
纯保存续办正确取得continue_prior保存范围、业务写权限为false，实际提交r3并确认原请求结果保存；
始终一份预订/两次业务尝试，标签从失败变为created，后续保存/只读/遗忘未增加业务效果。
更正链纯遗忘没有新语义保存；三次已知无效果拒绝、两次实际可见性撤销，重开未返回被撤销正文。
业务纯遗忘虽声明正确，却十次选择无效/未发出的引用，零撤销，事项及历史仍可见；不能算通过。
其他失败包括：整体频率继承到未规定分区，旧“南北均无单独次数”未随新增北区规则更正，
历史只读10/24项漏撤销前两天通知阶段，答错当前版本号，把查询found当预订状态；
一次只读实际业务查询只读了记忆/来源，没有新应用查询。原模型答案与程序反馈分别保存。
结果及限定判断见本地`root-semantic-observations.json`和`closed-response-reconciliation.json`，
不把费用/结构核对当语义认证；普通语义失败按规划11.1保留并继续主实验。

## 下一项工作与仍未完成范围

原三链20输入及两段成本已核对，实际限制、原恢复control与失败均保留。四用户前缀预测已闭合，
逐响应与固定账本核对为237生成/2159360 known=charged、214 embedding/36847tokens；
237响应均stop，Reader峰值输入28778，新unknown0，原历史unknown6/0不变。
32份维护结果为23 completed/9 incomplete，82去重实际提交、12拒绝，普通语义失败保留。
全部32会话/73回答及逐题检查点先保存，另备份完整aggregate。原评分中断固定差额为
656生成请求/2716058 known/2763437 charged tokens、0 embedding，新增unknown1。
其中655已保存响应用量完全对应known；未知第656项保留47379预留tokens，原历史unknown6
因此成为7。服务运行/排队均0，日志没有可恢复答案或精确用量，不据此改写unknown。
单独评分补充21生成/96531 known=charged、21stop、新unknown0、0 embedding；
起点等于原中断固定账本，全部32预测/73答案与评分前备份相同，原检查点未变。
合计Judge实际677请求、676保存响应、2812589 known/2859968 charged、新unknown1；
原中断不因补充完成改成原生COMPLETED，未知项没有重试。

统一结果为QA **44/73 Correct（有效71）**、更新 **48/72 Correct（有效67）**。
QA另19 Hallucination、8 Omission、2 invalid；更新另19 Omission、2原标签Omitted和3空标签，
后两种均保留invalid，不改写成Omission。540原生记忆点分成468形成/72更新记录，
另82准确性记录；作者形成主分母439另排除29 interference，不能用439替代原540机会。
同家族Judge和开发者来源核查不是独立确认。一处实际用户原话收入为18000，而参考答案为20000；
Reader按原话回答被作者Judge判Hallucination。保留原标签，同时单列参考/来源冲突，
不以gold纠正Source。Editor此前把同一用户证据改为20000仍是另一项来源忠实性错误。
预先固定7个已完成来源切片的thinking单变量对照已于23:01 UTC核对闭合，
每设置各两次、28提案全部保留：28gen/527243 known=charged、28stop、新unknown0、0emb/0Judge。
False14份220425 known/6683 output，True14份306818 known/93104 output；
True峰值输出9747，4份超过Host8192额度，不能直接据此变更Host模式。
输出`artifacts/global-function-first/editor-thinking-1cfb400-matched-v1`，来源审查已闭合28/28。
不运行Store或提交，不把28/28 wire schema合法当正式编译通过，不自动选最好答案或采用配置。
工程错误与普通语义失败分别定位；unknown HTTP、未知写入/业务效果和 Store 故障停止相关路径，
不盲重试。新 benchmark 预先声明按题保存成功及已知只读缺答，缺答保留在全部机会分母。

四开发用户前8会话已从各自空库形成，实际分母为32会话/73QA/72原生更新；
统一评分补充及来源提案对照、全部提案审查已闭合，不用于跨版本排名。
Root选择benchmark Editor thinking=True作为v3唯一模型配置变更：初始形成两次均覆盖五类原话，
金额冲突两次均使用用户e3的18000，False两次都把assistant e2的20000写成用户报告。
这项选择依据已曝光Source切片，不依据参考答案；True仍有空提案、非目标计划替换、
跨单元keep、模态增强、主体及时间问题，不能宣称全面改善或正式编译通过。
Host保持False，避免将32768输出对照直接套入8192入口；Reader、温度、预算和Source提示不变。
v3同时纳入已闭合工程检查的CURRENT提示与两处写入前拒绝回执修复。
新冻结源码已复用原Host20输入/control闭合并保留全部失败；同版五方法完整预测已启动，
待五方法预测全存后统一评分。旧v2完整主实验准备仍为0 HTTP，不复用其银行或结果。
固定Native32的原选择与Root来源审查已逐字节复制到`native32-5019968-v3-prepared`，
drift配置位于`drift277-5019968-v3-prepared`；两者仍0 HTTP、无BenchmarkRun/银行构造，
待全部同版预测和评分闭合再调度，不把准备文件当实际结果。
Native/drift入口静态核对已保存在`native-drift-runner-review-5019968-v3.json`：
9份相关代码与冻结源码逐字节一致，两配置的30项共同设置与本次主实验一致；
固定选择/来源审查再次对应32事项、12会话、4用户，未构造runner、未读取银行、0 HTTP。
Native使用各方法真实维护前后状态，Actual/NeverWrite/RetainAll为退化控制；
后续实际成本包含隔离状态Reader、embedding及Judge，不新增Editor形成调用。
隔离Reader复制原银行并还原实际保存版本，原主实验银行不写入；完整复制仍含原轨迹数据，
这次静态核对不能代替后续实际读取包/来源范围核验。漂移沿各方法自己的完整会话顺序读取维护结果。
全部五方法预测及统一评分闭合后才调度；该核对不是Native/drift结果或独立研究确认。
原固定LongMemEval28题及作者callback适配配置保存在`external28-5019968-v3-prepared`，
既有相关语言/措辞/独立顺序控制在`controlled-5019968-v3-prepared`；两者均0 HTTP，
待开发证据与最终候选冻结，若最终源码改变则另建配置，不能把当前准备当确认结果。
原定10题完整答案审查的配置与原选择manifest已准备在
`external-full-answer10-5019968-v3-prepared`：题目仍为原28题中的固定10题，四外部方法共40审查行。
保留原评价器temperature=0、thinking=False、8192输出及上下文/数据设置，
与形成/Reader候选的32768输出模式分别计量；评价现成完整答案与原完整历史，不重跑Reader/Editor。
仅复制选择metadata，未加载LongMemEval正文、问题或参考答案；0 HTTP、无runner/银行构造。
全部外部预测与官方统一评分闭合后才调度，不替换官方标签；同家族Judge及重叠来源不构成独立确认。
原16保留用户的UUID与配置已复制到`reserved16-5019968-v3-prepared`，仅准备，
未调用数据加载器或读取保留用户语义；原B1/B2/M范围暂存，最终方法和比较范围尚未选定。
固定紧预算协议位于`m-tight-context-5019968-v3-prepared`：M同四开发用户前8会话，
上下文65536降为49152，输出32768与余量512保持，完整输入上限32256降为15872。
该协议仍0 HTTP；基线仅取同版完整主实验M已运行的对应子集，不另跑基线或拼接银行。
两项均待完整主实验与统一评分、必要开发评价闭合；最终源码变化时保留准备身份并另建配置。
五组原Host公开输入与原评价control已逐字节复制到`host135-historical-inputs-prepared-v1`，
逐组核对合计135案例/192消息/145原文Source/1064有序候选；0 HTTP、未初始化银行。
该输入准备未选择最终Host方法，control仍仅用于评价，不提供给方法开发者；
冻结后新故事尚未生成，旧输入复制和离线兼容性检查不能当真实模型通过。
Root另将Host20两条遗忘请求的实际工具schema、参数、已交付读取凭据和无正文状态
交给恢复开发者隔离审查，目录为`host-forget-contract-5019968-source-only`，`review.json`已闭合。
逐条核对15次遗忘：更正链2次真实可见性撤销、3次写入前无效果拒绝；业务链10次全部拒绝，
零实际遗忘。没有一次read_handle参数等于已交付凭据；更正参数增加字面反斜杠，业务参数
使用record ID或自造组合等。业务唯一read_source是第4次共享读取，实际`read_limit_exhausted`、
limit=3。已确认模型选择器误用及预期额度耗尽，未证明正常合同接线缺陷，因此无源码补丁。
开发者11项JSON机械断言通过；0 HTTP、0运行时Store/backend写入、0输入重放，未跑pytest。
该Source-only审查不是模型重跑或独立研究确认，原失败及主实验冻结源码保持不变。
Root进一步核对业务链只读消息的真实目录，保存在
`host-readonly-business-query-contract-5019968-v3.json`：8次目录均交付`get_reservation`，
内存读取耗尽后最后目录仍仅保留该公开查询；正式调用仅4次记忆读取，没有一次实时业务查询。
断点是模型漏调用已交付能力，未证明目录/查询权限接线缺陷，未改源码或重放输入；
原实际办理状态和旧查询Source不能替代这次实时查询成功，COMPLETED仍不表示该要求已完成。
四开发用户的实际元数据已复核为每法277会话/705QA/595更新，均无generated-QA会话。
Root的一次元数据命令在uuid过滤前解码了所有JSONL行，只输出四开发用户计数；
未对未选用户语义审查/调参、未传入方法Worker。该程序解析事实和随后仅选中行加载的复核
保存在`development-metadata-validation.json`，不宣称保留用户从未被程序解析。
最终仍需同版五方法各277会话（合计1385）、
原 native32/12会话/4用户、drift/recovery、必要 M 消融与紧预算、最终冻结后的16保留用户、
LongMemEval、RawRAG/RollingSummary/A-MEM真实适配，以及 Host135case/192message 和新故事。
六项最终交付和方法选择均未完成，Product 仍为 NO_GO。工程可用、模型语义与科研优势分开判断。
