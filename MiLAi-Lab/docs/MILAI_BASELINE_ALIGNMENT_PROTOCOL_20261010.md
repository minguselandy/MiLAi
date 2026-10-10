# 本地基线对齐协议 v1

**最新离线交付条件：工程源码dda926f6，2026-10-11北京时间01:33:34。真实实验／Judge保持停止。**
Hindsight完整native_return继续存档；hindsight_evidence_v1只把已识别的诊断分数／trace／统计留在存档，
Reader事实、主体、时间、来源、限定、实体观察和未知字段保持。删除内容逐路径登记，不改形成／召回算法。
共同读取使用实际保存快照＋materials下标；外部材料无需record_id／revision，引用不取得修改或遗忘权限。
direct可容纳时一次回答，超限时执行已有分页／原文重开；staged／state_driven使用同一材料合同。
快照在模型输入中共享一次，正文与memory_item_indices对齐，续读目录只含当页；内部完整引用和全池枚举保持。
导航目录超限且工作集为空时，也将实际全池交给原分页循环。done不能跳过待交付页。
max_calls仍默认12，预留最终回答；未交付／不可容纳／超调用额度按原缺答合同报告，不静默截断事实。

三份真实H返回的离线固定合成问题回放为185／185／184条、各4页＋一次完整原文重开，
最大完整页输入32,255≤32,256、5次脚本调用＜12；原返回与快照保持，0真实模型／HTTP／DB／Judge。
新整池direct请求76,044／76,479／76,697仍超限；不能只靠移出诊断字段宣称容量已解决。
第一次全目录包装的离线失败保留。脚本选择下标0不使用QA／gold，不构成答案或证据充分性验证。

显式score现在只要求**所选实验臂**PREDICTIONS_SAVED且resources_settled=true；
其他臂FAILED／未开始不再永久阻止完整产物的质量反馈，原服务／租约关闭要求不放宽。
同一Judge／提示／标签／机会分母保持，缺答无Judge；比较排名另要求范围和配置可比。
当前Judge仍0，用户停止继续约束实际调度。本条件不是冻结12b的全臂评分门槛，也不回填旧运行。
Host输入效果／工具／进度分块属于新的工程条件；旧42消息准备根仍739，不自动派发或复用为新源码。
Root96＋3＋6相关检查、Ruff10文件／严格类型5源码通过，实际效能／E2–E4仍待验证。
最新分析与资源复核见[统一报告](MILAI_UNIFIED_MEMORY_USAGE.md)。以下运行快照均为各自原时点。

当前终态：2026-10-10 16:28:29 UTC／北京时间10月11日00:28:29，本次E1按用户要求STOPPED；
16:32:01 UTC核验父worker／原生API／PG退出、专属UID残留0、原HTTP Owner租约FREE。
新unknown0／0、limits不变，实际效果与费用保留。H终态FAILED由KeyboardInterrupt触发，
close_error为空／resources_settled=true，是用户取消，不是本次再次出现原生完成等待超时。
Raw32会话／73答案闭合；H6会话／12题＝9答案＋3发送前容量缺答；M未开始、Judge0。
本次140生成／1,902,918 known＝charged／14,024 embedding，部分轨迹不能填零或形成三方排名。

源码仍冻结12b87716，每臂32会话／73 QA／72更新机会、12新银行、完成等待1800秒／HTTP300秒；
原Source／Reader／QA20／维护与隔离更新K10／预算及连续账本保持。缺答输入81,471–82,771＞32,256，
全部request_sent=false，null及原分母保留，不评分或恢复失败银行。

Host工程源码739deaee包含实际反馈状态修复84fac247和无损有向关系共享；
完整包装保存态重建8,548→7,731＜8192、展开相等，604项相关检查通过，未证明真实任务通过。
新Host原42消息、三重复仅离线prepare；原config／fixture／controls完整字节保持，0银行／模型。
按最新用户要求不派发Host、Judge或后续实验；E2–E4及完整Host语义／SDK验收仍未完成。
以下为各自旧时点记录；当前以本段停止及资源核验为准。

最新：冻结D的M15:20:43 UTC预测／资源闭合，32会话／73机会＝53答案＋20发送前容量缺答；
输入35,532–42,854＞32,256，原材料及null保留，新unknown0／0、原limits不变。H仍FAILED、
套件STOPPED，原score gate未满足，Judge0；答案数量不是正确率。Root15:22:50 UTC启动原Host42，
15:25:04 UTC因材料包装超限停止，1COMPLETED／1FAILED／40NOT_RUN；首条真实保存但回答错误，
第二条真实维护提交后失败。原D／功能配置／账本不变，新unknown0／0、limits不变，实际进程退出，
租约FREE；公开SDK独立重开确认当前rev2／旧rev1，0模型。完整Host验收仍未完成。
新1800秒三方根保持冻结12b／尚未派发；Root完成失败Host效果与资源核查后可独立串行调度，
同时离线修复Host，不重启失败根、热改输入或拼接前缀。

后续入口复用原定义：MiLAi选择单个`entrypoints.benchmark.arm`，合法B0／B1／B2／M／Append-only，
默认M；其他后端仍M占位。必要E3各臂使用独立配置／根／银行，B2／M保持同一features及读取条件。
现有配置已登记原28个LongMemEval cleaned case；实际执行配置另声明
`history_protocol=longmemeval-complete-history`，CLI显式`--benchmark longmemeval`。
prepare登记真实case机会及来源重叠组，实际bank路径／namespace使用独立opaque映射且末尾仍owner；
完整公开历史完成后才交当前问题。方法不接触has_answer／answer_session_ids／答案，QA不写回。
已确认容量／length／非文本缺答保留null、全部机会分母、官方标签null、无Judge；未知仍停止。
普通LME默认fail-fast及原路径保持，原HaluMem行为不变。集成66检查／Ruff／严格类型通过，
无真实模型／API／PG；这是薄入口验证，E3／E4实际未运行，不称28／500题成绩。

新增部署等待条件（`12b87716`）：HindsightBackend默认完成等待300秒，local-v1显式1800秒；
单次模型HTTP期限仍300秒，不改变原生算法／材料／Reader／K／额度／重试。40相关检查、
Ruff／严格类型通过、0真实调用。新源及独立空根离线prepare确认每臂32／73／72机会、12新标识、
0实际银行／模型，未派发。当前冻结D的M保持原设置，14:23:54 UTC为7完整会话／12答案，
会话35332仍存活；原H失败不变，Judge0。先闭合M、实际Host42及语义重开核查，再从全新银行
运行这项等待条件；不拼旧前缀，不把等待修复称作容量修复或完成三方比较。

最新执行状态14:02:48 UTC：冻结`d50351a8`的E1套件STOPPED、原父／worker退出。
Raw32／73答案且资源闭合；H27／63检查点＝36答案＋27发送前容量缺答，其余10题未执行。
实际retain成功后consolidation超过适配器300秒整体等待；随后在关闭阶段排空，H仍为FAILED，
API／PG关闭、UID996残留0、原租约FREE。费用285生成／3557201 known＝charged／49018 embedding、
新增unknown0／0、原limits不变、Judge0。原材料、真实效果、失败终态及成本保留。
Root于14:08:49 UTC用同一冻结入口显式单独调度未启动的M，原配置／银行标识／账本不变，
独立回执与runtime；不覆盖STOPPED或重启H。14:10:24 UTC M0完整会话／1QA答案、仍运行。
原score gate要求全部三臂PREDICTIONS_SAVED，因此未调度评分，没有完整比较或方法排名。
以下快照按其原时点解释。整体原生完成等待修复须另行冻结，不热改当前源或复用失败银行。

较新固定13:49:16 UTC：冻结`d50351a8`的E1进程／执行会话仍存活，H前三用户各8会话
已完成，24会话／54题＝27答案＋27缺答；全部为发送前容量缺答，59,259–114,828＞32,256。
原材料及null分母保留，当前冻结策略继续历史；Raw32／73且资源闭合，M未开始、Judge0。
这不是QA正确率或统一方法排名；预测与资源全部闭合后再显式评分。

较新固定13:01:28 UTC：同一冻结`d50351a8`，H全臂10完整会话／26题＝15答案＋11缺答，
首用户8会话／20题＝9答案＋11缺答；第二用户2会话／6答案。11项均为发送前容量缺答，
输入79,724–114,828＞32,256，原材料／null分母保留，不热改；M未开始，Judge0。
原生正文预算不包括全部JSON字段开销。一题完整待发消息只读重建79,758；使用现有
共享原语显式映射H字段，精确展开相等的离线体量49,326仍超限，不能称当前投影已修复。
此诊断0 API／DB／模型／gold，字段映射未进入冻结实验。全三臂预测闭合后再独立评分。

当前运行固定观察12:31:19 UTC：完整新E1冻结`d50351a876c98260b8e60a4f4481a98b8bab0ef3`，
12:15:22 UTC在全新12银行启动，Raw32完整会话／73答案／0缺答且资源已闭合，
H1完整会话／4答案仍运行，M未开始。原连续账本，三臂成功闭合后统一评分，当前Judge0。
Raw阶段73生成／1060772 known＝charged／embedding0／新unknown0／0，limits不变。
该源码自身Fast38051194461成功、Full38051194427 skipped；不是QA正确率或方法优势证据。
Host同源码新根已准备原42消息，尚未执行；Host／Editor原功能额度与thinking保持。
下列接通、失败和部署观察保留各自原时点含义，不是当前运行的实时状态。

首次E1冻结`9a9b84b`于11:58:52 UTC停止：Raw15答案，第16实际Reader stop却contentnull、
usage完整；H／M未开始、资源闭合、Judge0。原失败及195662 known＝charged费用保留。
既有record_known_readonly_failure现也记录这种完整非文本stop响应，usage须整数非负且相加一致；
保留null及全部机会、无Judge，不使用reasoning补答案。其余旧策略和unknown仍停止。
修订版全新银行运行，输入／来源／Reader／预算／K不变，不拼接旧前缀。

当前E0接通闭环11:55:06 UTC完成：主预测`28bf2410`，独立实际重开查询`9a9b84b`，同一银行、
新检索日志，无Source／维护／Reader重放；Raw原文、H10事实ID／来源时间、M5记录／版本／Source核对。
验证脚本的原时间格式误读失败保留，修正0HTTP／账本不变／查询重放0，非模型补跑。
E1实际预测已启动，冻结`9a9b84b`，每臂32会话／73 QA／72更新机会，12独立空银行，父546823／worker546828。
仍用原连续账本，三臂及资源闭合后另行评分；接通不等于QA正确或方法优势。

最新实际E0主预测冻结`28bf2410`，11:44:12 UTC三臂各3答案／全部资源闭合；13生成／
80220 known＝charged／1046 embedding／新增unknown0／0。M5条实际revision1记录，Judge0。
重开及来源时间验收未完成；恢复入口另补模型ID绑定，主预测原源码不变，不称QA正确或方法排名。

首次实际E0（冻结`fa86b95`）11:24:29 UTC停止：RawRAG3答案，Hindsight retain实际BGE400，
M未开始、Judge0，资源真实闭合；失败根和embedding unknown1／charged1243保留，不退款或重放。
当前配置省略原生OpenAI DIMENSIONS；官方0.10.3启动发现实际维度，后续不发送dimensions，
其每次启动的真实BGE调用纳入原账本。新配置必须使用新根／银行，不能拼接首次RawRAG前缀。
E0重开证据使用成功闭合的同一DB／schema／银行与独立日志、新bridge，只查询、不再次retain／Reader。

执行范围为计划 E0–E4 与现有 Host 连续流程；本卡记录新配置，不改变冻结 5019968。Root 负责公共合同、配置、串行资源与最终结果，三个开发者分别负责 RawRAG/Hindsight、MiLAi 纯记忆/交付、Host/结果。

| 项目 | 首轮共同条件 |
|---|---|
| 数据 | 既有 HaluMem-Medium 四开发用户前八会话，32 会话/73 QA/72 更新机会；不读保留用户 |
| 时间 | 每个独立后端/用户/重复按时间写入一会话，实际完成后仅答该会话问题；无未来来源 |
| 信息 | 现有 ObservedSession：session_id、公开 date、role/content/timestamp；source-only，无 persona/gold/更新标签 |
| 臂 | RawRAG-local、Hindsight-native-local-recall、MiLAi-memory-only；原生答案另列 |
| QA | 可计数后端请求 20 项；Hindsight 保留原 max_tokens 并记录实际数量，不称 K20 |
| 维护 | MiLAi 写入候选保持原 K10；QA20 显式传参，不改变维护池 |
| 更新评价 | 参考查询仅在冻结的只读会话视图，K10；不支持隔离或真实会话输出则 N/A |
| Reader | 既有 Qwen3.6-35B-A3B-FP8，temperature=1、output=32768、thinking=True、context=65536、margin=512；实际完整输入上限 32256 |
| 交付 | 冻结12b首轮direct；新dda条件可容纳时一次Reader，超限才分页／原文重开；staged另列，不改池与原文 |
| 来源 | 各后端按原生输出交付；原文与 retrieved_memory 分开。MiLAi 主臂采用实际语义状态及其已有支持，不增加独立原文搜索兜底 |
| 持久/隔离 | 各后端/用户/重复独立 bank；会话 ID 稳定，Hindsight document_id 对应会话；问题/答案不写回 |
| 失败/评分 | 逐题保存；已知缺答保留全部机会，unknown不重试；新入口允许完整且资源闭合的所选臂显式评分，旧冻结全臂门槛保留历史含义；可比结果才能排名 |
| 费用/资源 | 原连续账本、Root 串行 Qwen/BGE/Judge；外部内部用量缺失记未观测，不填零 |

Hindsight本地原生配置：官方0.10.3，Qwen/BGE通过原VLLMClient与同一RunBudget转接；
retain temperature0.1、consolidation0.0、两阶段输出32768、thinkingTrue、embedding1024／batch16、
原生rrf重排。这些本地配置差异另列，不能称作者默认crossencoder或同模型纯算法比较。
实际部署使用公开MemoryEngine/OpenAIEmbeddings/create_app，明确embedding SDK max_retries=0；
该版本环境factory遗漏这个参数，不能仅凭EMBEDDINGS_MAX_RETRIES=0宣称生效。
见[准确部署约定](MILAI_BASELINE_ALIGNMENT_NATIVE_DEPLOYMENT_20261010.md)。Root持有原租约后才
启动专属非root用户的新pg0实例，核对实际API监听PID／UID及关闭后残留进程；没有新预算或记忆模块。
本地用户／解释器已准备；10:06:04 UTC 实际空实例API／DB健康、监听归属正确，
10:06:05 UTC关闭后UID残留0，两类模型URL为拒绝全部请求的本地probe，实际模型请求0。
通过公开pg0 query将Unix socket目录放到短的专属`/cra`路径，解决实际`/tmp`锁文件无空间失败；
未送Source、未开原账本，E0共同Reader与E1仍未运行。

RawRAG在既有开发用户的第一真实会话完成实际入库、关闭、重开和原文查询：1来源会话、
1实际返回，角色／日期／逐轮时间和完整正文保持。仅原生持久／查询路径确认、0模型；
共同Reader／Judge未运行，不记为三后端E0闭环完成或QA语义通过。

薄接口只需 ingest/retrieve/close。所有后端复用既有 ObservedSession 或结构等价的字段接口；retrieve返回materials（Reader证据视图）、native_return（完整实际后端存档）、returned_count、source_mapping、usage。H新视图仅分离已识别诊断字段；原文／限定／来源／顺序保持，不增加抽取或摘要Agent。共同Reader的显式分页按实际快照下标续读和重开，可选session_output仅来自实际会话原生输出。公共类型由Root管理。

历史调度：07:05:31 UTC原五方法PID1854770运行、HTTP租约占用。用户随后明确要求
“取消退出原实验”；11:15:01 UTC原运行STOPPED、两进程消失、原租约FREE、新增unknown0／0。
原预测／费用／状态保留且不重启或拼接。资源阻碍已解除；Root按冻结`fa86b95`和已核对配置
优先执行E0／E1，无须将全部旧科研待办作为永久前置。

最新固定观察与当前开发范围见[现有报告](MILAI_UNIFIED_MEMORY_USAGE.md)。恢复维护K10后的新根准备
确认每臂32／73／72机会、12个独立bank标识，网络禁用且0实际模型；它不是最终确认冻结。
socket配置加入后再次使用独立空根：`e1-local-v1-socket-prepared`与
`e0-one-source-socket-v1-prepared`，分别确认每臂32／73／72与1／3／0机会、12与3独立标识，
均未创建bank或客户端、未开账本、未启动API／DB，不复用旧配置准备。
预测／评分成功终态在实际后端和原资源正常关闭后发布；已drained失败仍为FAILED，
闭合未知保留RESOURCE_UNSETTLED和原错误，Root确认原生服务停止或完成前不调度下一方法。

能力接通、机械检查和真实模型语义结果分别记录。四开发用户与共享 Host 故事用于描述性比较；独立性、费用和未完成项沿计划原样报告。
