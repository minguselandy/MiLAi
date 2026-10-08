# 统一记忆功能候选：入口与实际状态

本轮按[多Agent任务卡](MILAI_MULTI_AGENT_DEVELOPMENT_TASKS.md)及用户提供的
[配套规划](MILAI_UNIFIED_MEMORY_ARCHITECTURE_AND_BUILD_PLAN.md)开发。
五个模块已合流到同一MemoryService，首次集成父版本为`5c36b28`；中央Host、
benchmark、配置及显式整理／完整请求恢复入口已接通。真实结果及后续修复分列如下；
尚无最终方法选择或Product准入。原[build-first完整任务](
MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)继续有效。

2026-10-07用户要求合并相关GitHub开发内容；PR83的可选来源工作视图和提案额度接入本候选，
保留当前普通ID及旧实验边界。[整合记录](GITHUB_INTEGRATION_20261007.md)说明冲突决定、
版本和验证；工程合并不表示真实模型效果已验证，`single_verdict_v1`仍未准入。

## 2026-10-08 14:02:51 UTC：两项运行已闭合，保存分类仍未改善

基础main为`e1424cc0f2a7fc2bbc9c6213827a4ad3bf80151a`；[PR115](
https://github.com/minguselandy/MiLAi/pull/115)已合并。受测源码`b6d03c6`的Fast
`37784334748`及合并main的Fast `37785621886`成功，未观察这两头Full。
报告、开发和以下两项实际冻结运行分开记录；下面旧时间块保持历史原样。

**保存意图列表简化尚未解决真实断点。** 冻结`35628d7`、原已曝光四消息故事、独立空库的
Host复核退出0，四次执行COMPLETED。Root读完四个实际交付答案；没有Judge或独立语义确认。
实际业务只有一次预订、一次标签完成；另一次标签journal身份被拒、executed=false、
effect=none，不能计为第二次业务效果。

第一次User请求形成r1，但Tool结果维护先遇到`EDIT_CHANGED_ASSERTION_REQUIRES_NEW_EVIDENCE`、
`EDIT_APPEND_CONDITION_TARGET_INVALID`，再遇到一个Editor截断响应。后来标签完成，
明确“只补保存实际结果、不再办理业务”的全文实际送达分类器，却仍返回`memory_requests=[]`，
maintenance=[]、没有Editor，当前记忆仍为r1的原要求。最后只读回答能分开业务结果与旧保存内容，
但把包装配置也说成已经办理，不能称四条语义通过。正式结果和旧失败未回填。

分类器四次实际请求均temperature=0、thinking=false、tool_choice=required；这是既有
declaration专项配置，普通Host为temperature=1、thinking=true。二者任务和输入不同，
没有隔离证据证明采样设置或服务端导致误分类。后续Agent获得实际材料后理解需要补存，
但执行边界已被分类关闭；不能把模型误判表述为用户禁止保存。

| 已闭合运行 | 实际范围 | 已确认成本／边界 |
|---|---|---|
| 冻结356 Host | 1 case／4 message；4执行COMPLETED，保存未闭合 | 26生成、293730 known／charged tokens；14 tool_calls＋11 stop＋1 length；8 embedding／354 tokens；Judge0、新unknown0 |
| 冻结721 staged五方法连续历史 | B0保存32/277会话、85个问题预测；33维护、88个完整Reader响应 | FAILED／exit1；274生成均stop、2878867 known tokens；219 embedding／14835 tokens；其他四法未运行、score未开始 |

721最早实际异常是作者retrieval统计的SQLite搜索中`database or disk is full`；finally的
COMMIT将终态异常覆盖成`cannot commit - no transaction is active`。根分区／默认tmp已满，
/cra仍有空间。这是运行失败，不是失败Reader HTTP或方法语义结论。最后3个Reader回答已产生，
但该会话没有完整预测；不将88响应全部当成已保存预测。Root完整读取该队列17个答案，
来源审计仍不完整。原失败根、源码、配置及终态保留，不重启或拼接成完整轨迹。
新Host运行使用/cra上的TMPDIR与SQLITE_TMPDIR；未改变算法或扩展预算。

闭合全局账本：47381 requests、206277711 known、206554407 charged，
embedding1938233 tokens；unknown6均为历史量，新增0。721启动前47081请求至其闭合47355，
增量274／2878867；再至356闭合，增量26／293730、embedding354，与确认文件完全一致。
这两项成本不能重复计入旧报告。固定观察时没有真实模型runner在运行。

**下一候选只接通既有参考输入。** fresh Host v8在同一次分类调用中复用最多12张可见原
应用请求卡，投递原要求、分项状态及实际User片段；不投递旧execution权限或完整运行日志。
参考正文沿用ordinary_material_tokens，优先容纳近期完整卡、保留所选原顺序，并明确省略数。
当前全文单独交付并决定请求与限制，原任务不能授权当前业务；既有有界续办仍核对实际身份。
已保存六／七字段v8决定0模型原样重放，v7不变，输出schema与维护合同不变。
此入口覆盖已登记应用原请求，不能声称已覆盖所有纯语义保存待办。

本候选真实HTTP为0，分类及语义改善未验证。直接受影响检查与正常续办／只读流程只验证
接线、可见性及权限：14项既有检查通过，额度改动后复查2项直接流程；另一个无HTTP机械
probe确认省略正文不送达、当前全文不变、合法[]及缓存0调用。Ruff、单源mypy和包依赖
边界通过；三位subagent分工只读／机械核对，Root集成。不追认356或旧e978成功。
读取目的、复合条款保持、正式空输出及条件
操作仍是独立工作。完整同版五方法／65与277连续历史、native／drift／recovery、消融与紧预算、
最终冻结后16保留用户、外部任务、完整Host135case／192message与新增故事及六项交付仍未完成。
任务active，16保留用户未用，无最终候选／方法优势，Product NO_GO。

## 2026-10-08 12:09:27 UTC：当前问题、已修边界与连续历史进度

**当前主要瓶颈是保存意图分类、正式变化落实、来源与限定保持，以及后续读取是否使用了
必要主体和正确历史。** 五条主线已接入一个逻辑MemoryService；工程集成、业务闭合、
合法输出和正常stop均不能代替语义成功。以下是固定观察，之后的运行进度不回写这个时点。

| 身份 | 固定版本与状态 |
|---|---|
| 本报告基础 | main `039bcad2ed779167bb69b7a1ad0778ccf2322dcd`；本次另作仅文档提交 |
| 最近已合并开发 | [PR #112](https://github.com/minguselandy/MiLAi/pull/112)，11:55:22 UTC合并；受测头 `72179e382208967430231861868b3dea21a75c20` |
| 最近Host真实故事 | `e9788910e7d7b709e71ed8f5843af8f7c5d87853`；四次执行闭合，保存分类和首条条件目标拒绝仍在 |
| 已闭合M预测／评分 | `d62f0b457b8b497146b7bd96b043124597e3c912`；32会话、更新16/72（valid63）、QA30/73（valid70） |
| 已闭合有限视图比较 | `9a59832d05e6898bc52788764b5b981be1e22a07`；固定Reader四题及Writer四前态，不与d62轨迹拼接 |
| 正在运行的五方法 | 冻结 `72179e382208967430231861868b3dea21a75c20`、staged、extract_then_edit／I2；新空库连续历史，未热改 |

PR112受测头自身Fast `37772066720`成功；合并main自身Fast `37773282422`成功。
未观察到这两个头的Full运行，不借用较早提交的Full，也不把CI作为方法效果证据。
远端main、PR合并身份及本地干净基础已核对。此次没有修改源码、测试、配置或workflow。

当前问题的直接证据和后续最小改进集中在[最新问题表](MILAI_BUILD_FIRST_ISSUES.md)：

- **保存意图在维护之前丢失。** e978的明确“只补保存”正式分类为none，maintenance=[]、
  无Editor、r2未更新。ce14与e978该分类HTTP请求整体JSON相同，temperature=0、
  thinking=false；ce14返回none＋resolve_prior_explicit后解析原请求并维护，e978全none。
  不能把差异归因于operation_call_started更名，也没有证据认定服务端根因。
  当前两个记忆意图字段存在职责重叠；以单一意图推导已有内部续办标志只是待验证的简化建议，
  **尚未实施**，不自动恢复旧权限或重做业务。
- **发现候选仍不保证正式变化。** d62的40次Editor有24次真实空结果，其中7次新建可用；
  9a的13次Editor有8次空结果。空结果当时均可合法，不把全部空结果等同于漏写。
  显式返回creates／records且允许两者为空，只是候选格式因素；尚未修改或运行。
  e978三次Editor原输出分别只含creates／records／records，原合同合法，Host HTTP没有
  response_format；收紧字段可能增加拒绝。旧checkpoint按保存schema发送而解析时重建
  schema，变更须保留旧输出和原合同，不能补字段后追认成功。
- **提交后仍有来源与保持问题。** 9a D1原7的新行业归属缺乏所选证据；d62及9a有未重述
  目标、复合条款的其他有效内容没有稳定延续的案例。其他卡和旧版本仍保留部分内容，
  不扩大成全库删除。主体、来源角色、可能性与完成状态必须分别判断；Append-only仍是强对照。
- **更少正文不等于更好读取。** D1偏好题未打开池内身份卡；D2首轮协调身份而D0也做到。
  D2第二轮四题都没有新增正文；Writer原7／4的D1与D2选择及Editor请求整体相同却输出不同。
  这不是多轮机制优势的因果证据。来源历史、实际保存历史和事实有效历史仍需按问题选取。
- **业务、保存和交付继续分项。** e978业务恰一次预订＋一次补标签，但原结果保存未完成。
  最后只读答案区分业务成功和已存初始失败，利用先前可见来源，本轮没有再次实时业务查询。
  前三条自然候选未交付、最终反馈另存；最后条自然答案实际保留。Host有文本不证明用户收到。

operation_call_started呈现修复已经合并；在e978这一个暴露故事中未再误存发货，
旧错误记忆不回填，不称全面修复。旧支持继承、Reader容量投影、完整请求登记、保存历史、
日历和实验副本授权等已接通，不重新列作待建模块；其效果只按实际冻结运行证明。
原505 B2低于B0的负结果仍成立，关系收益、条件接口负担和共同维护断点未被分离。

### 正在运行：同版本五方法、四用户完整连续历史

实际配置为[configs/milai-staged-four-dev-v1.json](../configs/milai-staged-four-dev-v1.json)，
四用户会话数65／77／62／73，共277；首用户65属于277，不能另算一轮。
B0／B1／B2／M／Append-only按既有入口串行、各方法／用户独立空库，沿各自自然历史运行。
使用既有Qwen3.6-35B-A3B-FP8与BGE-m3 dense cosine K10，六项EditFeatures、
thinking=true／temperature=1；context65536、输出预留32768、余量512、输入上限32256、
source4096／source_body8192、working_sets=false，原12次生成额度沿用。
采用staged是当前待评价候选选择，不宣称有限D1随机结果已证明优势。

12:09:27 UTC／北京时间20:09:27核对PID4027428仍为Sl、已运行23分10秒；
输出为artifacts/state-view/four-dev-staged-72179e3-v1，源码为source-72179e3/MiLAi-Lab。

| 方法 | 已保存会话预测／277 | 四用户分布 | 完整最终答案 | 预测终态／评分 |
|---|---:|---|---:|---|
| B0 | 9/277 | 9／0／0／0 | 23 | 无terminal-predict；score未开始 |
| B1 | 未开始 | — | — | 不是零分 |
| B2 | 未开始 | — | — | 不是零分 |
| M | 未开始 | — | — | 不是零分 |
| Append-only | 未开始 | — | — | 不是零分 |

Root此前完整阅读新队列3个答案，未完成23个答案或完整来源审计，没有新评分和排名。
本次三位subagent只读核对既有证据和报告，0新增模型调用；属于开发复核，不是独立确认。
PID、终态和产物须重新观察后再调度，不根据本固定快照重启或并发另起真实模型任务。

| 当前队列固定成本 | 请求／确认响应 | known tokens |
|---|---:|---:|
| 生成，全部已确认响应为stop | 73/72，另1在途 | 671649 |
| BGE编码 | 57/57 | 4190 |
| Judge | 0/0 | 0 |

对启动前闭合账本47081 requests／203105114 known／203381810 charged／embedding1923044，
固定差额为73 requests、671649 known、753748 charged、4190 embedding tokens，与请求、
确认响应文件的已知量一致。charged差额含82099在途reservation，不能当作已闭合消耗。
固定全局账本为47154 requests／203776763 known／204135558 charged／embedding1927234；
unknown7＝历史6＋本轮1在途reservation，不称新增已闭合失败。未重置预算、未增加上限。
这是现有队列继续执行产生的成本，本次报告核对没有启动新的模型任务。

### 后续范围与交付边界

先利用已有产物收敛少量通用断点：意图分类、变化到操作的映射、未改含义保持和读取目的。
格式因素、单意图和关系机制诊断尚未实施，不新增审核Agent、领域补写规则、来源门禁或
恢复平台。当前冻结队列保持原样；后续改动另作版本，工程检查不能追认旧实验效果。

原完整范围仍未完成：同版五方法及强Append-only的65／277连续历史；native32机会／
12会话／4用户、drift与recovery、必要消融和固定更紧预算；最终候选冻结后16保留用户；
LongMemEval28描述性问题／1354历史出现、原10完整答案审计及RawRAG／RollingSummary／
实际A-MEM callback适配；同最终候选Host135case／192message和冻结后新实质故事；
实际断点、共同实现、同版对照、保留与外部、真实功能、复现与成本限制六项交付。
16保留用户未用于开发；尚无最终候选、稳定方法优势或Product准入，Product仍NO_GO。
任务active而未完成，本次提交不表示暂停。下方报告和旧问题表均保留原固定时间。

## 2026-10-08 11:41:12 UTC：操作调用呈现修复，保存分类失败单列

新源码 `e9788910e7d7b709e71ed8f5843af8f7c5d87853` 仅把普通业务查询的公开
operation_history.dispatch_started更名为operation_call_started，仍取原executed值。
它表示原工具调用已开始，业务效果继续由effect／result_status表示。内部journal、原native_result、
业务身份、权限及unknown不改变；新查询的公开JSON子键改变，原已保存回执／错误记忆不自动重写。
这是Lab候选呈现修复，Product API／Schema及编辑算子不变。父版本main471ee1a，回滚该源码提交即可。

复用已有业务故事全部四条原消息、标签服务恢复control、新空库和原state_driven配置，跨四个
CLI进程运行；仅改上述呈现，原ce14结果保留。四次执行均COMPLETED，进程退出0，不是四条
语义通过。实际业务恰一次预订＋一次补标签，最终标签成功，没有发货业务效果；实际r1→r2保存
原要求与初次部分失败，此后r2逐值不变。新来源、保存内容和最终反馈在此已曝光故事中均未再
把调用开始当成发货。一次随机故事不能证明普遍消除此类误解。

首条EDIT_APPEND_CONDITION_TARGET_INVALID仍保留。“只补保存”消息本次仍未保存：最早断点
是请求分类的正式输出将memory_write_request／memory_continuation_request均判为none，程序
随后按声明关闭维护。该消息maintenance=[]，没有Editor调用，不能归为Editor空提案，也不能
通过自动恢复旧写权限使其completed。最后只读答案准确区分实际标签成功与仅存初次失败；本轮
只调用read_memory，利用先前已可见来源／反馈，没有再次实时查询。前两条及保存条的自然执行
候选未交付，最终反馈另存；最后一条自然答复实际保留。Host保存文本不证明用户已经收到。

Root读完四条完整最终反馈并检查实际记录与业务DB；两位subagent只读核对实际HTTP投递、
分类、回执及成本，新增HTTP0，非独立确认。真实流程22生成／210516known与charged tokens，
finish_reason为10 stop＋12 tool_calls、0length；BGE10次／678tokens，Judge0、新unknown0。
连续账本固定闭合为47081 requests、203105114 known、203381810 charged、embedding1923044、
历史unknown6，与该流程前固定账本差额一致。未重置预算或扩大上限，原件继续ignored。

三项既有受影响SQLite检查、该源strict mypy、Ruff、包与工具依赖边界通过；mock检查不代替
真实语义证据。新源码自身远端CI发布后另核，不借用父main或旧候选CI。后续共同五方法配置
采用staged，沿用原recipe、六Features、K10及预算，各自空库起跑四开发用户连续历史；D2仍可选，
不称D1随机结果已证明优势。既有proposal-list与record容器还改变生成引用范围和执行顺序，
不拿该Feature当作只隔离显式空输出的单一因素。分类／变化落实／支持／非目标保持仍需改进。
16保留用户未用，最终方法与Product准入均未确定；原完整范围继续未完成。下方固定历史不改。

## 2026-10-08 11:17:10 UTC：当前问题与真实交付比较闭合

实际候选仍冻结 `d62f0b457b8b497146b7bd96b043124597e3c912`：M／extract_then_edit／I2，
六项既有EditFeatures，state_driven，普通BGE-m3 dense cosine K10。只使用既有
Qwen3.6-35B-A3B-FP8，thinking=true／temperature=1；context65536，输出预留32768、
余量512，输入上限32256，source4096／source_body8192，working_sets=false，每题／来源
沿用12次生成上限。733新建能力与9a共同来源范围修复不在此候选中。

terminal-predict与terminal-score均为COMPLETED_EXPERIMENT_PHASE，两个原进程退出0；
四个开发用户各8会话，32预测／32评分、73完整答案。原作者口径完整汇总如下：

| 四用户前8会话，同冻结M | 更新Correct／全部机会 | 更新valid | QA Correct／全部问题 | QA valid |
|---|---:|---:|---:|---:|
| 第一用户 | 10/19 | 17 | 12/20 | 18 |
| 第二用户 | 1/15 | 12 | 4/12 | 12 |
| 第三用户 | 2/20 | 18 | 7/22 | 21 |
| 第四用户 | 3/18 | 16 | 7/19 | 19 |
| 合计 | 16/72（22.22%） | 63 | 30/73（41.10%） | 70 |

更新原标签为Correct16／Omission46／Hallucination1／Omitted2／null7；后两类9项无效原样保留，
不改名成Omission或真实错误。QA为Correct30／Omission25／Hallucination15／null3。valid口径
分别16/63（25.40%）、30/70（42.86%）。formation reference439／valid412，原始468行中的
29条interference不算reference；formed outputs40／valid32。原作者recall(all)31.44%、
weighted accuracy(all)71.25%、extraction F1=0.4783，含各自全部分母。
单臂没有同版方法优势或条件机制因果结论，同家族Judge及开发团队复核均非独立确认。
完整闭合包含4个incomplete Source root和3个incomplete Editor leaf，不能称全部维护成功。

| 候选阶段，互斥累计成本 | 生成请求／确认响应 | known tokens |
|---|---:|---:|
| 预测（抽取／选择／Editor／Reader） | 357/357 | 3310034 |
| 保存产物评分，只有Judge | 426/426 | 1239622 |
| 候选合计 | 783/783 | 4549656 |

全部783生成stop，embedding183次／11273tokens，新增unknown0。所有966生成／embedding HTTP
请求与响应配对，差额0。固定评分闭合账本（10:48:56 UTC、后续比较前）为46979 requests、
201960438 known、202237134 charged、embedding1913903、历史unknown6；对预测前闭合账本的
请求／known／charged／embedding差额与上述文件一致。没有重置预算或扩大上限。
这是闭合候选成本，不是之后比较期间的实时账本。

有限交付比较单独冻结 `9a59832d05e6898bc52788764b5b981be1e22a07`，不与d62轨迹拼接。
Reader固定同一实际持久状态、四个已声明问题与原saved pool、同模型与每题12次生成额度；
不重新搜索、维护、抽取或编码，不给D2增加来源。四题涉及未知中间名、计划与完成、
带日期偏好及缺失历史工资；每模式4个完整回答，共12份。Root及subagent阅读完整答案，
保留效果分析，不另造数值评分或套用原73题标签。

| 固定池Reader | 生成请求／响应 | known tokens | 峰值输入 |
|---|---:|---:|---:|
| D0 legacy，一次性交付 | 4/4 | 36341 | 12178 |
| D1 staged，一次选择后完成 | 8/8 | 32362 | 4344 |
| D2 state_driven | 12/12 | 63415 | 8880 |

24生成均stop、合计132118known，embedding／Judge0、新unknown0。D1与D2四题第一次选择request
逐值相同；D2第二次均没有新增／替换正文，两次保留同卡完成、两次空选择完成。D1偏好题只打开
偏好卡，未协调姓名；D2首轮选到身份卡而协调，D0也做到。这个差异不能归因多轮探索。
三种回答均保留未知中间名、计划不等于完成、工资材料不足；D2工资答复把“没有特定工资”扩成
“没有就业历史”过宽，实际输入另有新角色转变。未发现越池或实际投递差异，完整来源独立审计
仍非全部完成。四个暴露案例的一次随机运行不能证明广泛优势。

Writer比较同样从9a冻结源码运行，使用原B0真实历史的原3／6／7／4，实际before为
16／20／20／16事项，各模式独立副本，固定原K10 pool与共同旧来源范围；当前原文、角色及
引用范围实际完整送达。Editor共用B0／I2／五项既有Features／single_pass，共同legacy Reader
依据各自实际after正常检索，11题／模式、33份完整答案；该读取与状态编码照实计费。
没有新Writer检索、抽取、Judge或理想旧卡；协议不等于d62 M候选，也不是旧recipe比较。

| 固定前态Writer | Editor次数／真实空提案 | 新建／重写提交 | 全阶段生成 | known tokens | Editor／全阶段峰值输入 |
|---|---:|---:|---:|---:|---:|
| D0 legacy | 4/3 | 0/1 | 15 | 210969 | 20389/20389 |
| D1 staged | 4/0 | 1/4 | 19 | 284888 | 16155/21485 |
| D2 state_driven | 5/5 | 0/0 | 22 | 306185 | 15401/21485 |

各模式4case／11答案齐，进程退出0；56生成均stop、802042known，embedding42次／8463tokens，
新增unknown0，实际请求／响应一致。维护为10次选择＋13次Editor，8个空提案、6提交，
0拒绝／no_change／重放／容量失败；共同Reader33次。操作数不是语义通过数。
Editor峰值减小但选择阶段使D1／D2全阶段峰值高于D0，不能只拿Editor输入宣传整体节约。

D0原3／6／7无状态变化，原4保存新日期偏好，四条旧宠物正文及支持逐句保留，Reader协调新旧；
不因它采用追加含义而判无效。D1原3新增变化计划并保持旧目标，原6保存真实收到面试／offer，
保留旧计划，但本次他人帮助事件仍漏写；原7落实换岗与健康改善并进入答案，却将未明确的新
行业写成本人报告，重写也未显式延续部分旧目标。那些目标仍在其他卡／旧版本中，不能称全库
删除。原4保存新偏好、保留非目标宠物及否定；偏好正文未显式保留互动联系，但原始互动片段
仍通过revision_evidence实际送达共同Reader，朋友姓名问题中已被读取，不属于来源完全不可读。
共同Reader的未知中间名、朋友姓名、血型及兄弟信息边界保留；旧任职背景与本次来源日期
仍有过度概括，维护未形成的事件不怪到Reader。

D2原6确实打开两组事项、两次Editor仍空；所有旧值未变。尤其原7与原4，D1／D2首次选择
及Editor的request.json整体值完全相同（含messages／schema／prompt_tokens），却分别产生
修改和空输出。temperature=1下这次输出分歧不能归为视图或多轮机制的因果收益。D2四个case
均未保存新变化，Reader在实际缺材料时保留未知；不把这种谨慎回答当端到端任务成功。

两项9a比较合计80生成／934160known、42embedding／8463tokens、Judge0，全部闭合。
比较后固定账本47059 requests、202894598 known、203171294 charged、
embedding1922366、历史unknown6；与候选评分闭合账本的差额逐项一致。两版本的候选与诊断
合计成本为863生成／5483816known、225embedding／19736tokens，不能合成总体准确率。
Root阅读12＋33份新完整答案，三位subagent并行核对成本、来源与状态、实际投递及语义效果，
分析本身新增HTTP0；完整原始来源独立审计未全部完成，未另造通过率。原件、私有配置、
HTTP／reasoning／DB／日志及subagent分析保持ignored，不上传GitHub。

目前没有证据支持把多轮D2当效果更佳默认；后续优先复用简单交付与一次选择，保留D2作为
确实需要继续读时的可选路径，不扩大读取或审核框架。该次有限随机观察尚未选定最终候选，
也未更改公开Host配置或编辑算子。最急迫的问题仍是正式变化落实、支持强度和未改语义保持，
完整清单见[当前问题](MILAI_BUILD_FIRST_ISSUES.md)。16保留用户未用于开发；同版五方法、
65／277连续历史、native／drift／recovery、消融及更紧预算、冻结后保留／外部／完整Host
与六项交付继续未完成，Product NO_GO。

本次提交仅更新三个既有报告，不修改源码、测试、workflow、私有配置或冻结实验。
发布父版本main f71ab3e40edf890466ed25b35fa0403fdf9f63b5／[PR109](
https://github.com/minguselandy/MiLAi/pull/109)，其受测头eacc6d0自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37763634584)及main自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37764055884)成功，未观察到eacc Full。
d62自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37746491786)成功、[Full](
https://github.com/minguselandy/MiLAi/actions/runs/37746491914)skipped；9a源码包含在PR108受测头97a71f3，
没有观察到9a单独的workflow结果，不借用其他提交CI。新报告提交的自身CI在PR中另外核对，
CI不是方法效果验证。原505的B2低于B0这一负结果继续保留，不能用本轮单臂或修复洗掉。
复现入口为既有[run_edit_change_pairs.py](../tools/run_edit_change_pairs.py)的reader-views／writer-views，
使用绝对输入／配置路径和新输出目录；同冻结输入首次结果不覆盖、不重试unknown。
下方固定历史观察及原无效标签全部保留。

## 2026-10-08 10:24:17 UTC：三位subagent并行复核，语义断点与正式评分分开

用户明确要求subagent并行测试效果。复用三位开发Agent，只读核查实际模型产物及保存状态；
新增模型／encoder／Judge调用0，没有改变运行输入或重新评分。Root继续串行调度真实HTTP。
这是同开发团队的补充复核，不是独立确认。[PR108](https://github.com/minguselandy/MiLAi/pull/108)
已于10:11:45 UTC合并，main2d9baa05b5a4f7963cb89d9226fbcebed31dae72；受测头97a71f3自身
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37760353122)及合并main自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37761866635)均成功；该头未观察到Full结果。
候选评分仍冻结d62／PID3552053，18/32[8,8,2,0]，273Judge响应／795622known，另1在途，
尚无terminal-score。修复后的Writer和Reader有限比较均未开始真实调用。

| 已闭合用户，原作者标签 | 更新Correct／全部机会 | 更新valid | QA Correct／全部问题 | QA valid |
|---|---:|---:|---:|---:|
| 第一用户前8会话 | 10/19 | 17 | 12/20 | 18 |
| 第二用户前8会话 | 1/15 | 12 | 4/12 | 12 |

第二用户更新中的2个Omitted和1个null按原无效标签保留，不改名为Omission。表为当前运行子集，
不发布四用户总体分数或跨版本优势。形成指标沿用既有interference过滤，不能直接用原记录行数。

Writer机械覆盖全部33来源batch／40编辑work，来源语义复核15个batch。初始姓名在用户1／3／4
实际保存、用户2未保存；首次就业有的先被导航关闭新建，有的新建可用仍为空。实际局部损伤：
第一用户原3整条change_value丢失旧百万目标；原4修改犬种时丢失同条款中的其他宠物，另一条
否定内容仍保留。零单元删除不能证明非目标语义保持。第二用户原3的提案把Assistant精确金额
归给User并丢季节限定，但整项被拒，旧r1完全不变，不能称错误落库。后期换岗／健康实际落实、
旧单元逐值保留也有正例；部分可能性被加强为明确计划仍保留。40个Editor最大输入17428，
本轮无Writer容量失败。7次新建可用的空提案不能因733修复就记为解决。

Reader复核全部73份完整答案与161次选择：所选正文均实际进入后续输入，未发现越池、选后未开
或版本错配。34题最后打开整个非空池；另有换出／重装，重复选择不自动算浪费。第一用户原4 q0
身份卡在池内却未选；第三用户原7的历史问题把后来的计划写进主答案再补时间限定；第一用户原7
旧版动机存在于保存历史，但当前pool只有新版，属于固定材料缺口，不能靠目录补出历史。
维护123生成／1820056known与Reader234生成／1489978known是357生成总成本的互斥子集，
不重复加账。Reader复核曾显示一条已曝光作者evidence，已丢弃；未用于输入、补充证据、预声明
案例选择或新标签，完整原始来源独立审计仍未完成。

Host复核d475的18结果／17自然候选及ce14的8执行，真实业务仍恰一次预订和一次补标签。
ce14纯保存r3只修改续办要求，实际query来源使r4才更新标签结果；r4继承了无业务依据的发货
断言。操作历史dispatch_started表示调用开始，被抽取／编辑解释成运输发货；后续最小改进应
明确呈现操作进度，保留原journal、身份和权限。原Tool拒绝与旧query零回执各自仍在，
结构completed／coverage unchecked不能代表所有保存完成。部分自然文本是未交付候选，
不得当逐字最终反馈；原Host报告据此补充边界。ce14未跑撤销／历史结尾及遗忘，不能称其已修复。

四个Writer实际前态离线预览全部fit，最大20389tokens，共同旧范围没有预算省略；原声明固定
池及来源仍保留。先完成当前评分和D0／D1／D2比较，再依据实际质量与累计调用做减法；不因
这些复核扩展常驻审核器、主体平台或编辑算子。16保留未用，完整目标active，Product NO_GO。

## 2026-10-08 09:55:23 UTC：冻结预测闭合，同源范围比较入口修正

本节为固定观察。[PR107](https://github.com/minguselandy/MiLAi/pull/107)已于09:01:29 UTC合并，
合并main为16763b5140de8099aa9d08199414ec7886f0d2da。受测头d5a0c88自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37752254276)成功、[Full](
https://github.com/minguselandy/MiLAi/actions/runs/37752254300)skipped；合并main自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37753781615)成功，不称Full 21/21通过。
新比较源码9a59832d05e6898bc52788764b5b981be1e22a07；实际预测和当前评分仍冻结d62f0b4，
733新建能力及9a来源范围修复均不回填该运行。

预测PID3145901已退出0，terminal-predict为COMPLETED_EXPERIMENT_PHASE：四用户各8份，
共32/32预测、33个来源batch、73个完整自然答案。Root读完全部73个答案，选定来源、
正式输出和回执审计仍为部分；没有另造数值重评分或独立审计全部HTTP／reasoning。
正常stop与进程闭合不表示语义通过。40个编辑工作中24次真实空提案；46个实际回执为
40提交（31新建、9局部编辑）、1 no_change、5拒绝，无重放。4个来源batch维护不完整，
选择阶段1次EDIT_VIEW_CREATE_SCOPE_ALREADY_PROCESSED单列；空提案以编辑工作为单位，
不能与来源batch或该选择失败合并。拒绝含2次EDIT_APPEND_CONDITION_TARGET_INVALID及
3次EDIT_EVIDENCE_LINK_NOT_SELECTED，原失败保留。本段计数勘误：初稿将分析器的3个不完整
编辑leaf误写成来源batch数；33个来源根结果实际29 completed／4 incomplete，包含另1个
导航阶段失败。原始结果和checkpoint一致，未改实验或标签。

| 闭合预测，阶段互斥 | 确认响应 | known tokens |
|---|---:|---:|
| 抽取 | 33 | 385299 |
| Writer选择 | 50 | 834344 |
| Editor | 40 | 600413 |
| Reader选择 | 161 | 1019093 |
| 完整Reader | 73 | 470885 |
| 合计生成 | 357 | 3310034 |

357请求／357响应均stop，embedding183次／11273tokens，预测Judge0、新unknown0。
预测闭合／评分前连续账本46553 requests、200720816 known、200997512 charged、
embedding1913903、历史unknown6；生成known／charged差额均3310034，embedding差额11273，
与实际确认文件一致。未重置预算、未增加上限。评分约09:46 UTC从同一冻结源码和保存产物启动，
Python PID3552053／session61454；固定本时点2/32会话[2,0,0,0]闭合，75个Judge响应／
208582 known，另1请求在途，无terminal-score。没有重跑Writer／Reader／encoder，也无完整分数。

补充定位：第三用户原1有3条新候选，Editor输入5529tokens，但旧导航create=false禁用新建，
正式响应为空；与首用户能力限制同类。第二用户原0旧库为空、5条候选、Editor输入5461tokens，
新建可用却正式返回{}。后者说明733只能消除已确认的导航限制，不能据此解释或解决所有空输出。
第二用户后期3项提案的evidence_links包含实际送达别名，但未同时选入本条evidence，按既有合同
拒绝；不放宽算子或把离线可修提案记为成功。主体关联、限定保持、未来计划与历史问题的协调
仍有语义缺口。最终回答还出现内部证据标签直接呈现的问题，Root发现与原作者标签分别保留。

尚未运行的Writer比较原先按每次打开的事项重分配旧来源正文额度，可能使D1／D2取得D0完整池
预算已排除的来源。9a仅修正有限writer-views：每case先按实际完整固定池确定共同可读旧范围，
后续工作只取该范围的子集，实际当前来源继续保留；保存allowed_support_ranges及原预览计划。
三种展示仍共用B0／I2、single_pass、实际前态、模型／额度及legacy Reader，原recipe compare
协议沿用。扩展原一项SQLite检查，验证被共同预算排除的旧正文不能因选小子集而新增，
相同前态／范围、非目标保持、原prepared字节不变；52次累计合成生成全部计量。
检查、两文件Ruff、包／工具边界及CLI帮助通过，工具strict mypy仍为四项原错误，无新增。
0真实HTTP；新冻结source-9a59832及v2配置／声明已准备，原733未运行声明保留。
Reader固定池四题及Writer实际四前态比较继续等待评分释放串行资源，均无方法效果结论。

方法反思限于假设：[Grammar-Aligned Decoding摘要](https://arxiv.org/abs/2405.21047v4)提示
语法约束可改变采样分布，不能证明本部署空输出的原因。[vLLM官方说明](
https://docs.vllm.ai/en/stable/features/reasoning_outputs/)区分reasoning与正式content；
不执行推理草稿、不强制非空、不改当前解码部署。先完成交付方式比较，再决定是否需要有限的
输出表达诊断。原长历史、同版本强简单／Append-only、保留／外部、完整Host和六项交付未完成；
16保留用户未用，完整目标active，Product NO_GO。

## 2026-10-08 08:46:08 UTC：导航误限新建已定位，候选保持原冻结版本运行

本节为固定观察。main64f006f；[PR107](https://github.com/minguselandy/MiLAi/pull/107)
已ready、open、尚未合并。最新开发源码733fa7227fddac7b15eded76899af906b48fc8bd，
实际集中预测仍冻结d62f0b457b8b497146b7bd96b043124597e3c912，不热改、不重启。
Python PID3145901／session15141仍运行，产物artifacts/state-view/prefix8-d62f0b4-v1；
15/32份预测，四用户[8,7,0,0]，32个完整Reader答案，尚无terminal-predict／score或Judge。

Root已读首用户20个、第二用户12个完整答案；选定来源、选择、正式输出和回执审计部分，
没有独立审计全部HTTP／reasoning，没有新增数值重评分。首用户原1的五条新候选实际送达，
Editor输入5533tokens；选择器只打开旧基本资料并返回create=false，程序因此将creates设为
maxItems=0。正式结果是空creates及旧事项no_change，不是空HTTP对象，也不能直接归因于
Editor未落实已识别的新事实。候选目录、实际打开的正文与可用编辑能力应分别观察。
两用户中也有Reader无法将泛称User与问题姓名对应、已保存偏好未被稳定使用的现象；
不从owner或问题中的姓名构造主体关联，后续按实际可见来源定位。

733fa72将导航选择收敛为record_ids／done。首次工作保留既有编辑器的新建机会，后续工作
沿用已处理来源状态，不重复开放新建；选空旧事项仍可让编辑器返回合法空结果，不强制写入。
已保存的旧选择和已发工作保留原创建决定／映射，unknown不自动重试。编辑算子、当前写权限、
来源、模型、窗口、调用上限与旧legacy合同沿用。此前D0允许新建而D1／D2可被导航禁用，
不能将其效果差直接归为展示方式；修复后才能用同一编辑能力开展有限比较。
复用五项直接检查，实际SQLite覆盖首次能力、后续不重复、提交后重开、合法空结果、
原unknown保留、完整Host纯保存及固定池CLI；源strict mypy、四文件Ruff和包／工具边界通过。
修复本身0真实HTTP，尚无修复后方法效果。[54b2aaf自身Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37749073531)成功，
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37749073574)skipped；733自身CI待发布核对。

当前冻结首用户8份预测闭合，维护含9个编辑工作：16次提交、1次no_change、1次拒绝，
另2次真实空提案；选择阶段另有1个EDIT_VIEW_CREATE_SCOPE_ALREADY_PROCESSED，
父维护不完整，不能并为空提案或称8次维护语义通过。拒绝为EDIT_APPEND_CONDITION_TARGET_INVALID。
完整候选保留这些失败，评分使用同一冻结版本；新修复不回填其预测。

| 固定08:46:08累计，阶段互斥 | 确认响应 | known tokens |
|---|---:|---:|
| 抽取 | 16 | 183908 |
| Writer选择 | 21 | 376029 |
| Editor | 18 | 278876 |
| Reader选择 | 65 | 364402 |
| 完整Reader | 32 | 130902 |
| 合计生成 | 152 | 1334117 |

153生成请求，另1Editor在途；确认响应均stop。embedding78次／5170tokens，Judge0。
连续账本46349 requests、198744899 known、199102123 charged、embedding1907800；
unknown7＝历史6＋在途reservation1，不直接认定为新增已闭合失败。与候选前账本及已确认
文件的request／known／embedding差额均为0；未重置预算或增加上限。
采样文件artifacts/state-view/observation-20261008-084608.json保持ignored。
Writer／Reader固定池比较尚0真实调用；先闭合候选，再比较D0／D1／D2。原长历史、
强简单与Append-only、保留／外部、完整Host与六项交付未完成，16未用，Product NO_GO。

## 2026-10-08 08:00:24 UTC：受影响续办闭合，冻结共同M候选开始集中预测

最新开发源码为d62f0b457b8b497146b7bd96b043124597e3c912；PR107仍open draft、main64f006f。
ce14dd7受影响复核在07:50:41 UTC闭合8次执行，Root阅读8个完整答案并核对实际状态及回执，
不称8次语义通过。旧来源拒绝未复现；整体和北区例外的通知均实际改为两天，次数和季度保留。
只补保存被解释为explicit／resolve_prior_explicit，business_action_request为none、operations空；
实际新提交r3／r4，业务仍恰一次预订和一次补标签，之后只读没有维护。
50生成／529,361 known、30embedding／1,473tokens，新unknown0、Judge0，21 tool_calls＋29 stop。
原首次条件目标拒绝、部分维护不完整仍保留；已存“启动发货”缺少业务证据，后续更正标签时继承，
整体次数仍被推给南区。有效提交和已登记请求闭合不能据此称保存语义完全正确。

有限[配对入口](../tools/run_edit_change_pairs.py)现在同时提供`writer-views`与`reader-views`。
Writer复用原四个实际前态及原delivery记录的K10候选，三种展示均用同一B0／I2编辑器、
single_pass和既有legacy Reader；固定池是可选择目录，不被误当已经打开的工作。
原来源与目标支持在相同合法范围内可读，初始Writer无新检索／抽取，提交后Reader仍按实际状态
使用共同检索、所有HTTP与encoder记费。原prepare／execute／两recipe compare协议保留。
Reader比较固定实际已保存池；这两项均尚未执行真实比较，不是方法对照成绩。
复用一项SQLite配对检查：实际before和候选池相同、非目标保持、prepared字节不变；
合成transport的52次累计生成全部计量。原分项提交中断检查也通过；共同维护源strict mypy、
三文件Ruff及CLI帮助通过。工具strict mypy剩四项原错误；移除重构后冗余cast，没有新增类型错误。

集中候选从独立冻结d62f0b4源码、新空库启动，仅M／extract_then_edit／I2／state_driven，
四个已曝光开发用户各前八会话；原Qwen3.6、BGE-m3、dense K10、窗口／输出预算不变。
产物artifacts/state-view/prefix8-d62f0b4-v1，Python PID3145901，tool session15141；
固定观察时0/32预测、2个完整Reader响应，尚无terminal-predict／score或Judge。
不要由此快照重启；以实际PID、产物和终态为准。旧4e中断队列不恢复，原件及unknown保留。
d62f0b4自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37746491786)仍in_progress，
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37746491914)skipped；上次报告8785510自身
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37745079867)成功，不借给d62。

本轮反思参考原始方法：[MemGPT v2](https://arxiv.org/html/2310.08560v2)明确要求外部内容进入
当前上下文后才能使用；[Mem0 v1 §2.1](https://arxiv.org/html/2504.19413v1)将候选映射为
ADD／UPDATE／DELETE／NOOP；[SimpleMem v3](https://arxiv.org/abs/2601.02553v3)将内容压缩与
按意图规划检索分列。对本项目的推断是：可达性、实际交付和语义动作落实须分别观察；
这些论文不证明MiLAi当前语义已正确，也不为新增常驻审核器或关系平台提供效果证据。
先完成一个候选，再用固定池比较判断是否保留D2；原全部长历史、强简单／Append-only、
保留／外部、完整Host及六项交付继续未完成。16保留未用于开发，Product NO_GO。

## 2026-10-08 07:40 UTC：三条真实Host链闭合，保留语义失败并修复续办接线

本节为固定观察。main仍为64f006f；[PR107](https://github.com/minguselandy/MiLAi/pull/107)
为open draft，最新开发ce14dd7dd11bc065b75dfb854ed05d8d38c07884，完整三链实际冻结d4756a0。
三链在07:29:36 UTC完成18次尝试，17 COMPLETED、1 FAILED；执行闭合不是语义通过数。
Root阅读17个完整最终答案，并核对选定来源、前后状态和实际回执；未独立审计全部HTTP／reasoning，
没有另造数值重评分。这些是已曝光的开发故事，不是最终冻结后的新故事或保留集。

| d4756a0实际链路 | 已观察行为 | 保留的失败 |
|---|---|---|
| 两事项保存／切换／跨进程重开／原文重装，6次执行闭合 | 两个事项真实提交；只读查询及原User话术可用 | “尽量”被强化为“严格”；仅存偏好却声称提醒已设置 |
| 局部例外／更正／撤销／当前与保存历史，5次闭合、1次失败 | 北区例外r2实际保存，后续撤销形成r3 | 更正时只提供旧来源目录，解析器却无读取工具，选中当前片段后被正确拒绝；两天要求未保存；Reader将要求当成已保存历史，并把整体次数推给南区；撤销后另有一次editor截断 |
| 部分业务／补标签／只补保存／只读／遗忘，6次执行闭合 | 业务库恰有一次reserve_and_label、一次complete_label；遗忘回执撤销一事项及六来源，重开记录仍visibility_revoked，业务保留 | 部分结果被存成整体失败；“只补保存”误判none、零维护；业务完成不能替代原结果保存完成 |

ce14dd7只补两项实际合同：续办解析器在原材料额度内取得候选池中可见的旧User片段，
保留实际角色、时间、句柄和权限；当前意图的限制按所指工作范围表达，排除业务或已保存部分
不会自动排除另行请求的未完成保存。仍由模型解释当前意图，不强行授权、写入或重做业务。
同请求原件、旧unknown、失败输出不改写。新空库、独立冻结ce14dd7已启动两个直接受影响
片段共8消息，观察时尚无终态；不把此代码修复归给d4756a0成绩。

另在既有[配对入口](../tools/run_edit_change_pairs.py)增加有限`reader-views`：显式指定实际保存的
HTTP key，固定同一retrieval池、状态、问题、日期、模型与Reader，只改变legacy／staged／state_driven
的材料交付。没有新检索、encoder、Writer、来源捕获或Judge，选择与最终回答全部记费。
实际模型调用仍为0。两项窄检查覆盖相同池／原件不变／所有选择计费和跨会话旧来源交付；
Ruff、两源strict mypy、工具边界、CLI帮助及diff检查通过。工具单独strict mypy仍有与父版本
相同的五项既有错误，不称完整工具类型检查通过。Writer同前态视图比较尚未接入此命令。

| 已闭合试验，分别计量 | 确认生成／known tokens | embedding／tokens | 新unknown／Judge |
|---|---:|---:|---:|
| 18e3935工程失败后的两条试验 | 8／48,473 | 2／37 | 0／0 |
| d4756a0三条完整Host链 | 97／898,449 | 49／2,118 | 0／0 |

d4756a0的97响应为54 tool_calls、42 stop、1 length；这不是全部正常stop。
原账本差额与逐条HTTP usage一致。三链闭合时连续账本为46,146 requests、196,881,421 known、
197,158,117 charged、generation unknown6、embedding1,901,157；此为07:29:36闭合值，
不含正在进行的ce14dd7复核。原预算未重置、上限未增加。
d4756a0自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37742073430)成功，
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37742073455)skipped；最新ce14dd7自身
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37744739546)仍in_progress，
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37744739545)skipped，不能借用其他提交CI。

下一步收敛一个共同完整候选并闭合其开发集，再做固定实际状态的D0／D1／D2比较；
不继续扩大架构。原65／277连续历史、五方法与Append-only、保留与外部、完整Host回归和
六项最终交付均未完成。旧505负结果与4e中断保留，16保留用户未用于开发，Product NO_GO。

## 2026-10-08 07:15 UTC：恢复视图任务，接通共同Reader与纯保存续办

用户“继续”恢复状态视图目标，原完整研究范围保留。main仍为64f006f；[PR107](https://github.com/minguselandy/MiLAi/pull/107)
为open draft，当前开发头及真实新运行冻结源码均为d4756a030c460ece705eeb45664ff5641267ddf9。
本节为固定观察，不将下方06:30暂停交接当作当前执行状态；旧4e中断实验仍未恢复。

共同benchmark Reader现在沿实际固定K10池选择完整事项、替换／保留驻留正文、重装并最终回答；
原Source、保留状态、历史与支持由原Reader呈现，QA不成为新来源。选择调用和最终调用共用
原模型、真实窗口、调用额度与连续费用账本。普通Host的纯保存续办关联实际pending checkpoint
和旧User片段，原session只用于核对旧回执，新尝试使用当前请求的权限、身份及trigger；
已完成事项不重做，complete但零提交的显式保存仍可以明确续办，unknown原件保留。
最终反馈读取本次新尝试回执，不再误取旧空输出。分析器按实际calls manifest分列抽取、选择、
分项editor，父容器重复回执不重复计数。前八配置标记为DEVELOPMENT_STATE_VIEW_CANDIDATE_UNVALIDATED，
未启动，尚无方法成绩或准入。

Root九项直接检查覆盖普通Host跨会话纯保存、只读重开、同请求重放、原业务续办、实际SQLite
事项维护与unknown、Reader切换／重装／比较及统计；均通过。八源strict mypy、既有Core
52源mypy、Ruff、包／工具边界及verification matrix通过。它们是合成transport与真实SQLite。
首个远端a4da1b1 Fast因新增working_set.py遗漏既有源码登记失败，已补齐；18e3935 Fast又暴露
Core统计测试错误地依赖可选LangGraph，已改用标准SQLite，不扩依赖或CI。d4756a0自身
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37742073430)在观察时仍in_progress；
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37742073455)为skipped，不称为成功。

首次真实18e3935试验保留两次消息及原件：第一条editor截断、无语义提交，Host却声称记住；
第二条实际提交午休提醒r1，随后驻留刷新改变隐式目标选择，回执读取报EDIT_MAINTENANCE_REQUEST_CHANGED。
这批按工程错误停止，余16条未运行；8生成／48,473 known、2embedding／37tokens，新unknown0、Judge0。
d4756a0仅固定原checkpoint的首次选择绑定；实际SQLite回归证明提交后的读取／重放不重新选目标，
没有放宽绑定检查，未热改或重放旧试验。

新的三个连续流程从d4756a0独立冻结副本、新空库串行执行，产物为
artifacts/state-view/host-three-flows-d4756a0-v2；观察时仅第一条闭合并真实提交，余流程尚在运行。
第一条自然回答将“尽量”强化成“严格”，不称语义通过。流程复用已曝光故事，检查切换／重开、
更正／例外／历史、实际业务／只补保存／遗忘。首次旧试验与新流程成本分别计量，交叉子集不相加。

当前仍未完成：三个真实流程闭合与Root复核、一个完整开发候选、同实际状态／候选池的D0／D1／D2
效果比较及原65／277连续历史、保留用户、外部任务、完整Host和六项最终交付。视图接线不能证明
已消除空输出、来源错归属、主体关联或限定损坏；保持合法no-op与强简单／Append-only对照。
旧505负结果、无效标签及原4e中断unknown保留。16保留用户未用于开发，Product NO_GO。

## 2026-10-08 06:30:20 UTC：状态视图阶段提交，发布后按用户要求暂停

本节固定于06:30:20 UTC／北京时间14:30:20，区分新开发源码、旧实验和发布状态。
发布基线main为`64f006ffd690f3a16d7a93fb39f7087a88aabb8f`，PR83–106已合并。
[PR106](https://github.com/minguselandy/MiLAi/pull/106)于06:11:58 UTC合并，受测头
`8155d2c2f8426af2c7df60ca81ea55071be21d31`自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37731193509)成功；不把其CI归给本批新源码。
本批集成源码为`230ed2b043c7d57b989868ea8fdfe03a6f139bb0`，分支
`feat/lab-state-driven-view-20261008`；作为独立draft发布，新源码尚未合并main，
自己的远端CI待发布后观察。用户最新要求“提交完成后暂停任务执行”，因此本次只完成
当前批次合流、必要检查和交接，不启动真实模型试验，不把暂停记作完整目标完成。

**新开发按[状态视图计划](MILAI_STATE_DRIVEN_MEMORY_VIEW_BUILD_PLAN.md)及其引用的
[逐步披露计划](MILAI_PROGRESSIVE_DISCLOSURE_MEMORY_DEVELOPMENT_PLAN.md)推进。**两份输入
按原文保存，canonical checkout中的用户原件没有修改。一个逻辑MemoryService、实际来源、
记录版本、读取权限、旧编辑器、业务回执及连续账本继续共用；默认`legacy`，新增的唯一
公开模式项为`memory_view_mode: legacy | staged | state_driven`。

| 本批模块 | 已接通的行为 | 当前证据和边界 |
|---|---|---|
| 读取工作集 | 轻量实际候选目录；focus／read_goal／resident_refs／pending_refs仅存实际引用；事项切换、续页、显式保留、重装和遗忘复用原读取工具 | SQLite目录→读取→切换→重开→重装→遗忘例通过；目录不是已读正文或事实支持 |
| 模型输入与Writer | 每次Host调用前投影当前驻留正文；直接I2写入只映射实际读完的当前目标；当前User／真实Tool来源保留；提交刷新当前版本，已交付历史版本仍可定位 | 原持久消息和已读存档保留；临时旧读取正文换为读取身份，工具调用／结果配对及业务回执保留；真实模型效果未验证 |
| 共同维护 | 两种原recipe、五种原编辑方法共用maintain_event；新模式一次抽取，先定位再打开完整事项和支持；工作项身份先持久化，再经原提交边界执行 | 实际SQLite两事项例在首次提交后中断，重开核对原回执，仅继续另一事项，各版本1→2；未知调用保留、不自动重发 |
| 中央入口与配置 | 普通Host接入模式及每轮投影；共同benchmark Writer接入模式，selection／分项editor使用独立HTTP日志路径和原费用账本；当前明确保存意图可标记原checkpoint | 普通Host新模式接线检查通过；benchmark Reader仍是既有一次完整K10输入，尚未接入新工作集导航；不能宣称共同D2候选已完成 |

本批添加[普通Host配置](../configs/milai-state-driven-functional-v1.json)和
[仅准备的M前八会话配置](../configs/milai-state-driven-prefix8-v1.json)。沿用Qwen3.6生成家族、
BGE-m3普通dense、既有K10、上下文／输出／读取／调用额度、原I2及抽取配方。后者明确标记
`DEVELOPMENT_WRITER_VIEW_ONLY_READER_PENDING`，未启动；配置出现不等于最终候选冻结或准入。
D1与D2的选择次数／工作项策略已经有代码，尚无同实际前态的效果对照。

**必须保留的未完成接线与断点：**

- benchmark Reader的新视图、共同选择调用的结果分析／完整成本展示、同前态D0／D1／D2
  比较入口尚未完成。已保存HTTP与连续费用计量不能替代分析器对全部新增stage的闭合审计。
- `pending_maintenance`仅定位当前owner可见的原显式保存checkpoint与来源引用，不携带旧写权限。
  中央Host已可显示这些引用；跨会话纯保存续办的原session／新权限绑定仍未证明接通。
- 显式保存若正式输出为空，原checkpoint可能为complete、实际未提交；现有
  `resume_maintenance`会在该phase提前返回。列出pending不表示“继续保存”已能补办。
  有回执的部分提交恢复例通过，不覆盖这个语义空输出分支。
- 计划要求的三个真实连续Host故事、完整开发候选和同前态视图／编辑比较均未执行。
  当前没有新方法分数或“更短输入提高正确率”的证据，空提案仍合法，不强制非空。

Root合流后运行10项直接检查：工作集正常链、分项维护中断／unknown、驻留／修订／历史，
以及普通Host原五种设置和新M／unified／state_driven接线；均通过。六个受影响源文件
strict mypy、九个改动Python文件Ruff、包依赖边界、git diff检查通过。首次Ruff仅发现
Root新增共享helper的import顺序，已修正。两个配置JSON可读，两份计划与原件逐字相同。
这些检查使用脚本化transport与实际SQLite；本批真实generation／encoder／Judge均为0。
Worker C曾扩大到整文件检查时遇到/tmp所在根盘满（Errno28），未完成该套检查；随后
一次整文件重跑在14项通过后主动中断，均不记整套通过。最终只保留窄检查，Root临时库
位于本分支ignored artifacts，没有清理别人的临时目录或旧实验。各模块单独检查与Root
合流检查范围重叠，不把其计数相加为独立确认。

**旧4e运行已按此前用户暂停要求停止，不是仍在途。**冻结源码为
`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`，新日期、Episode、空维护反馈和本批视图
均未进入它。PID1675659于05:15:53.207085 UTC退出，实际exit_code=-2；暂停观察记录
保留在ignored区域。本次再核对没有活跃实验客户端，没有重启或覆盖结果。

| 旧4e各自连续独立历史 | 保存预测／分布 | 当前终态和评分 |
|---|---|---|
| B0／B1／B2 | 各32／32，[8,8,8,8]，各73完整答案 | 各预测COMPLETED_EXPERIMENT_PHASE，尚未评分 |
| M | 23／32，[8,8,7,0] | 未有整臂终态；第三用户原7的qa/8只有保存请求，没有确认响应 |
| Append-only | 未启动 | 不记零分，未有终态或评分 |

三闭合臂417生成／6,360,293 known，628embedding／220,725 tokens，是旧4e总费用的
子集；Root已读263完整答案、来源审计部分，没有新数值重评分。下方05:10时点M22及
“PID仍存活”保留为历史，不再作为实时情况。旧505三闭合臂的原作者负结果也保留：
更新B0／B1／B2为31／27／26 Correct（各72机会），QA为43／33／34（各73问题），
原无效标签保留；B2当前实现落后与条件机制的因果作用未分离，不能因新工程模块而回填。

连续账本仍为原ser-v20；暂停后至本节观察没有变化：46,041生成请求，195,934,499 known，
196,211,195 charged，generation unknown6（此前5＋本次中断未确认1）；embedding
known／charged均1,899,002，unknown0。从旧4e启动前到暂停的账本差额为518请求、
517确认响应、8,029,491 known、8,114,699 charged及275,779 embedding tokens。
这些是旧运行成本，本批开发真实调用为0，三闭合臂及人工复核子集不重复计费。
未知请求保持原件，不盲重试，不重置预算，也不把全局unknown称为本批模型失败。

**反思与续办顺序。**此次将“已读存档”与“下一轮驻留正文”分开，是处理一次呈现和
变化落实的工程准备；它尚未证明能消除正式空输出、主体关联、来源错归属或限定损坏。
恢复任务后先补齐上述少数转换断点和三个正常用户链，再冻结一个完整候选，完成有区分力
的同前态D0／D1／D2诊断；保留共同简单与Append-only强对照。不要在暂停期间自动启动
旧运行、新配置或新增审核Agent。65／277连续历史、native／drift／recovery、必要消融
及固定更紧预算、16保留、外部描述性任务及实际适配器、同一候选Host135case／192message
与冻结后新故事、六项交付继续未完成。16保留用户未用于开发，Product仍为NO_GO。

## 2026-10-08 05:10:24 UTC：三臂预测闭合，空维护反馈与语义断点分开

本节固定于05:10:24 UTC／北京时间13:10:24，发布前main为`bafced5`，PR83–105已合并。
[PR105](https://github.com/minguselandy/MiLAi/pull/105)的受测头f9796e3自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37727194406)成功，按既有分类不要求Full；
未观察到该头Full，不借用其他提交。实际五方法仍冻结于`4e46099`，新日期／Episode
修复及本节的反馈修复均未进入该运行；原505负结果、无效标签和固定历史快照保留。

| 同一4e源码、独立空库prefix8 | 已保存预测 | 预测终态 | 评分 |
|---|---|---|---|
| B0／B1／B2 | 各32／32 | 各COMPLETED_EXPERIMENT_PHASE | 均未运行 |
| M | 22／32，[8,8,6,0] | 尚无整臂终态 | 未运行 |
| Append-only | 尚未启动 | 尚无终态 | 未运行，不记零分 |

PID1675659仍存活，整个套件尚无process-exit，新Judge0。三个预测臂闭合不等于五方法
评分或语义成功。Root已读本次263个完整答案：三个闭合臂各73，M首两用户32及第三用户
原0／1／2／4的12；来源审计部分，没有新增数值评分或独立确认。

**B2实际预测已闭合。**32维护、33来源batch、73完整自然答案；33抽取／33editor／
73Reader＝139生成，全部stop，2,242,991 known tokens；212embedding／72,674 tokens。
49份成功提交、14次真实空维护，0拒绝／unprocessed／不完整batch／编辑前容量缺口。
14次空维护的原始正式content均为`{}`，不是客户端吞掉非空提案。四用户最终事项／
content／condition分别为11／46／2、12／54／2、8／61／0、10／18／0，合计41／179／4。
B0／B1／B2预测合计417生成／6,360,293 known、628embedding／220,725 tokens；此前
子集已包含其中，不重复相加，M在途和旧505费用不并入。当前没有新评分或方法排名。

**旧支持修复的实际分支尚未得到本轮验证。**逐份检查B2的33次正式输出，没有发现
`from_unit`与`assertion.keep`指向同一旧单元、但省略`keep_support`的条款；14条保留
条款显式填写了它。因此零拒绝不能证明PR98的省略支持继承分支改善了本轮效果。
已有代码／检查证据仍有效，旧拒绝不回填；支持继承和非目标语义保持分别判断。

**M的有界复核同时保留实际改善和失败。**首两用户分别36／28生成、583,521／511,113
known，合计64／1,094,634，为在运行M的子集。第二用户身份已实际保存，七组偏好形成
后Reader能够使用；原3仍有十五条候选、22,963输入tokens、旧库15事项，正式`{}`、
记录值全不变。身份已形成、容量可容纳并不能消除变化落实断点。原4两次局部提交保留
四条旧健康单元、六条旧目标单元及十三条其他记录值，但新健康分类只由Assistant提出，
editor仍写成“User reports”；持久角色正确为assistant，不证明文本归属正确。首用户
宠物局部替换也有三条完整旧单元及十六条其他记录值保持，但新解释的引用选择和限定
仍有缺口。第三用户已实际形成姓名关联，早期读取可使用；后续餐饮变化仍有空维护。
这些实际前态不同、单次随机历史的观察不构成同前态优势，也不新增作者标签。

**完整请求与本轮反馈分开核查。**已登记业务请求的`save_result=true`仍要求相关实际
Tool来源、可读提交与完整batch；空维护没有语义回执时，原保存项为
`failed / result_save_unconfirmed`，完整请求保持incomplete。既有跨会话SQLite示例中
业务恰一次预订、一次补标签，三个空维护batch正常结束，不能称保存完成。纯memory-only
当前不登记这种application请求项，不能声称它已有完整保存恢复状态。

新源码`a43b5a7`只修正普通Host的回执汇总：已完成但无回执的维护显示“未提交”，
避免无依据地渲染“已有记录，无需变更”；有实际记录／版本回执的no_change及原提交
重放保持原义。17项直接相关检查、受影响源strict mypy、Ruff、包依赖边界及上述正常
SQLite例通过，0真实模型HTTP／encoder。不改变持久状态、权限、维护格式、模型选择
或自动重试；自己的远端CI尚待发布核对，真实模型效果未验证，回退基点bafced5。

当前仍优先闭合有限五方法预测／评分，再围绕一个已证实断点做通用改进。格式因素诊断
仅准备、实际0调用；合法空提案保留，不执行私有推理草稿或增加审核Agent。一个最终
候选的65／277、native／drift／recovery、必要消融及更紧预算、16保留、外部任务和完整
Host135case／192message及冻结后新故事、六项交付均未完成；Product NO_GO。

## 2026-10-08 04:21:12 UTC：普通Host的Episode描述召回接通

新源码`136328e61a8fa64c179061c69a5e416cff0d51a1`在main e4906dc之后补齐任务卡中的
“正常查询从Episode回到真实来源”：unified_v1普通查询用已有description.text的词法
匹配定位该描述自身的source_refs，再经既有raw_events／fragment／read_source路径交付
实际原文。相同来源的重复描述取最大匹配分数，不累加；索引描述仍为unchecked，
不是新的事实、独立支持或自动主体关联。查询只读取，不生成语义记录或扩大权限。

没有增加公共Schema／DTO／工具、Store命名空间、encoder调用或另一事实库。现有owner、
来源可见性、Assistant独立raw过滤和遗忘路径沿用；任一关联来源撤回后，原Episode仍
整体隐藏。semantic-record的dense排序、预算及benchmark include_raw=False保持原合同。
正常Host的来源召回行为改变，旧profile不启用此入口，不将这项变化归入旧冻结成绩。

116项既有功能记忆文件检查、两项受影响源strict mypy、三文件Ruff及包依赖边界通过。
实际普通M／I2工具与SQLite示例验证：重开后用仅存在于描述的查询词找到原文，显式读取
原文，遗忘后重开不可访问；空语义库不调用encoder、语义记录仍为0，真实模型HTTP0。
首次示例手工传入与已绑定请求不同的query被既有PUBLIC_QUERY_CHANGED拒绝；改用正常
请求绑定后通过，没有放宽该检查。自己的远端CI尚待发布核对，真实语义效果未验证。

本节固定04:21:12 UTC／北京时间12:21:12：PID1675659仍在执行冻结4e五方法预测，
B0／B1各32预测闭合，B2为[8,8,8,1]、25/32，M／Append未启动，无整个process-exit或
新评分、Judge0。新源码没有进入该运行。Root已读这次B0／B1共146及B2前三用户54个
完整答案，合计200；来源审计部分、无新增数值评分或独立确认。B2已有身份仍会出现
候选送达后的正式空输出，当前变化落实的语义断点尚未解决。五方法评分、候选65／277、
保留／外部／完整Host与六项最终交付仍未完成；16保留未用，Product NO_GO。
原快照、原505负结果与原始无效标签保留；本次源码回退基点e4906dc。

## 2026-10-08 03:42:06 UTC：B1预测闭合，日期合同修复与来源转换断点

本节固定于2026-10-08 03:42:06 UTC／北京时间11:42:06。发布前main为
`6b719f0b4005a00f66c485143ce67f447f83bf0d`。[PR102](
https://github.com/minguselandy/MiLAi/pull/102)的报告头3202a17自身Fast成功、Full按文档范围
跳过，已合并；[PR103](https://github.com/minguselandy/MiLAi/pull/103)于03:40:31 UTC合并。
其受测源码头为`5e20511ae0e1c6fd28b3e31e195322a9779d407d`，自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37722599291)成功，未观察到该头Full运行。
实际五方法仍冻结于`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`；日期修复不在该运行中，
旧505原作者结果及下方固定快照保留。本次仅更新三个报告文档。

| 同一4e源码、各自空库的prefix8 | 已保存预测 | 预测终态 | 评分 |
|---|---|---|---|
| B0 | 32／32 | COMPLETED_EXPERIMENT_PHASE | 未运行 |
| B1 | 32／32 | COMPLETED_EXPERIMENT_PHASE | 未运行 |
| B2 | 4／32 | 尚无整臂终态 | 未运行 |
| M／Append-only | 各自未启动 | 尚无终态 | 未运行，不记零分 |

固定观察时PID1675659存活、状态Sl、运行2小时00分38秒，整个套件没有process-exit；
Judge0。两个预测臂闭合不表示评分、全部五方法或整个进程完成。

**B1预测成本和操作已按原件闭合。**32维护记录、33来源batch、32预测及73完整自然答案；
33抽取＋33editor＋73Reader＝139生成响应，全部stop、1,950,971 known tokens，与
terminal计数一致；197个embedding响应／71,910 tokens，已保存请求均有响应，新增闭合
transport unknown0、Judge0。84份成功提交回执、13次真实空维护；另有1个非空提案被拒，
1条unprocessed及1个不完整batch。拒绝不并入真实空维护，没有editor前容量缺口。

| B1用户顺序 | 预测／完整答案 | 真实空维护原序号 | 成功回执／拒绝 | 最后事项／content／condition |
|---|---|---|---|---|
| 首用户 | 8／20 | 0、1、5、6 | 18／0 | 17／73／0 |
| 第二用户 | 8／12 | 0、1、6、7 | 21／1 | 21／47／0 |
| 第三用户 | 8／22 | 0、2 | 20／0 | 15／40／0 |
| 第四用户 | 8／19 | 1、5、7 | 25／0 | 21／94／0 |

四库合计74事项、254 content、0 condition，普通条款表示不以condition节点数评价限定。
B0与B1预测合计278生成／4,117,302 known、416embedding／148,051 tokens；各用户和
此前子集已包含其中，不重复相加。B2在途费用不在这个已闭合两臂合计内；旧505闭合费用
另列，连续账本没有重置。Root已读两臂全部146个完整答案，来源审计部分、无数值重评分
或独立确认。正常stop、成功回执、条款数量及预测终态均不等于语义成功。

**实际来源复核同时保留正例与断点。**

- B1第三用户原3的职业局部替换提交成功；同一记录的两条财务单元完整对象，包括文本、
  原支持、时间及证据均未改变，另外两条记录值也不变。其他当前计划候选未全部落实。
  这是有界的非目标保持证据；B0与B1实际前态不同，不能写成同前态的方法优势。
- B1第四用户原3的第二batch中，只有Assistant提供新的冲突金额，当前User没有作相应
  更正；editor仍把先前User明确金额替换，并写成“User reports”。持久断言的role确为
  assistant，说明确定性角色填写正确仍不能保证文本归属及证据选择正确。后续完整回答
  使用新金额，同时注明来自Assistant、支持不足；免责声明未恢复原User陈述的当前值。
  同batch还将Assistant建议的解释加到旧偏好中。两batch分别审计，不用首batch正例代替
  整事件；以上不新增作者标签，也不把来源问题归为条件机制独有。
- 初始身份或就业正式空输出后，后续泛称User记录与问题中姓名的关联仍不稳定。实际
  来源支持的owner／speaker／subject区分继续适用，未开发新的强制姓名保存规则。

**明确日期误拒已修合同，原运行失败保留。**B1第二用户原5有非空正式输出、正常stop，
原公共JSON schema验证合法，实际日期为完整英文月名、日、年；原4e解析只接受ISO日期
或带完整时钟的英文日期，编译返回EDIT_EXPLICIT_TIME_REQUIRED，原21份记录值全部不变。
PR103只让既有英文日期分支的时钟可选：完整或三字母月名日期保持day精度，完整时刻
保持second，原文字串保留；缺年份、非法日期及部分时钟不补齐，未知时区不设UTC，
事件时间不从报告时间推断。14项直接日期／Calendar／普通Reader检查、Ruff、受影响源
strict mypy、包边界及SQLite重开例通过。Root对原日期只做新解析验证，0新增模型HTTP，
未执行整个旧提案或回填旧成功；其中计划措辞仍可能强化，接受格式不证明语义正确。

当前共同断点仍为正式变化落实、主体关联、支持／范围保持及维护结果的后续使用。
旧505 B2整体负结果、形成覆盖与持续使用差异、总体与用户等权口径、无效标签及条件
接口负担的因果边界见紧随其后的原报告。旧支持、容量和保存续办无需重新建设。
格式因素诊断仍仅准备、实际0调用；不热改4e，不强制非空、执行私有草稿或新增审核Agent。
先闭合这次有限五方法预测／评分与复核，再收敛一个通用因素、选择一个候选完成自身
65／277连续历史；保留集、外部、native／drift／recovery、必要消融／固定更紧预算、
完整Host135case／192message及冻结后新故事、六项最终交付仍未完成。16保留用户未用，
single_verdict_v1未准入，无最终候选或稳定方法优势，Product NO_GO。

本次无源码、Schema／API／权限／Canonical或实验配置变动；发布核对闭合计数、成本子集、
相对链接、原快照保留、ignored边界及diff，报告头自身所选CI另核对。文档回退基点6b719f0。

## 2026-10-08 03:04:31 UTC：B0预测闭合，新增来源复核与五方法进度

本节固定于2026-10-08 03:04:31 UTC／北京时间11:04:31。发布前main为
`7f6ffef6b2f13286473729e5265b10e1dd9dc581`；上一报告[PR101](
https://github.com/minguselandy/MiLAi/pull/101)已于02:18:15 UTC合并，其最终报告头
`4d0f493c728cf0a9ce644923b6372ffd69019937`自身[Fast](
https://github.com/minguselandy/MiLAi/actions/runs/37717088335)成功、[Full](
https://github.com/minguselandy/MiLAi/actions/runs/37717088327)按文档范围跳过。
这些检查只属于该报告。实际五方法运行仍冻结于
`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`，源码自身Fast／Full21成功的工程证据见
下方原报告；原505三臂分数没有变成4e结果。本次仅补充三个文档。

**五条主线已经接通，新增进展来自预测闭合与实际来源复核。**共同MemoryService、普通
Host、保存版本历史、完整请求分项、Tool结果保存绑定和整理pending回执核对沿用已合并
实现。当前主要断点仍是变化落实、非目标支持保持，以及当前／历史／来源解释；没有新
框架或最终方法选择。

**旧505的整体负结果明确保留，条件机制的因果作用尚未分离。**本轮只读核对原作者聚合，
未新增评分；所有三臂均为同一505源码、各自自然历史，以下不是新4e分数。

| 505已闭合的原作者指标 | B0普通全量重写 | B1普通局部编辑 | B2条件表示＋全量重写 |
|---|---|---|---|
| 形成memory_integrity.recall(all)，439参考点 | 38.5% | 39.4% | 46.9% |
| 更新Correct／72全部机会 | 31／43.1% | 27／37.5% | 26／36.1% |
| QA Correct／73全部问题 | 43／58.9% | 33／45.2% | 34／46.6% |
| 作者形成输出数 | 63 | 59 | 52 |

形成召回表示参考记忆点覆盖，不能解释成生成更多卡；更高覆盖没有同步形成更好的持续
更新与QA。全部机会比例表示已获Correct标签的比例，无效判断既不静默转为错误，也不
删出主分母；valid分母、原无效标签及具体计数继续在下方01:43原报告分列。

B2减B0的总体更新差为−5/72＝−6.94百分点，QA差为−9/73＝−12.33百分点；按用户等权
的描述性差分别−6.73及−7.92百分点，口径不同。四用户QA题数差为[0,+3,−9,−3]，
第三用户贡献全部净差，其余三用户两臂均29/51；不删除第三用户或据第二用户提升宣布
机制有效。更新正确数差为[−1,−1,−3,0]，三个用户下降、一个持平。仅保持有效标签并
考虑无效QA的边界算术：即便B2四个无效都正确也为38，仍少于B0已获Correct的43；
这不是补评分，也不把同家族Judge变成独立确认。

同版自然历史比较回答整体实现表现，不是仅加入关系的单因素实验。可见schema、任务
说明、生成负担、已形成状态与后续检索都会变化；终态未形成条件边只能排除对那些未存
关系的实际推理解释，不能排除条件接口负担。B1也下降，新4e B0仍有正式空输出，不能
把全部负结果归为条件关系有害；关系收益、接口负担与共同维护断点仍需分别定位。

| 同一4e冻结源码、各自空库的prefix8 | 已保存预测；四用户分布 | 预测终态 | 评分 |
|---|---|---|---|
| B0 | 32；[8,8,8,8] | COMPLETED_EXPERIMENT_PHASE | 未运行 |
| B1 | 14；[8,6,0,0] | 尚无整臂终态 | 未运行 |
| B2／M／Append-only | 各自未启动 | 尚无终态 | 未运行，不记零分 |

固定观察时Python PID1675659实际存活，状态Sl、已运行1小时23分03秒；整个串行套件
没有process-exit或最终终态，Judge0。B0整臂预测闭合不能写成整个进程退出0，也不能
代替评分。03:04之后的进展需另行观察，不改本固定快照。

**B0闭合成本与实际维护行为。**02:44:17的闭合核对确认32次维护记录、33个来源batch、
32份预测及73个完整自然答案；33抽取＋33editor＋73Reader＝139个生成响应，全部stop，
2,166,331 known tokens，与terminal计数一致。219个embedding响应／76,141 tokens，
已保存请求均有响应，新增闭合transport unknown0，Judge0。93份成功提交回执、
unprocessed0、7次真实空维护、无不完整batch；没有editor前容量缺口。

| B0用户顺序 | 预测／完整答案 | 真实空维护原序号 | 成功提交回执 | 最后事项／content／condition |
|---|---|---|---|---|
| 首用户 | 8／20 | 0、1、5、7 | 16 | 15／46／0 |
| 第二用户 | 8／12 | 1 | 24 | 20／82／0 |
| 第三用户 | 8／22 | 3、5 | 28 | 26／97／0 |
| 第四用户 | 8／19 | 无 | 25 | 19／75／0 |

四个独立终态合计80事项、300 content、0 condition。B0采用普通条款表示，节点数不能
单独判断限定是否丢失，也不证明条件机制有效。成功提交、正常stop和闭合均非语义通过。
Root已阅读全部73个完整答案，来源审计仅覆盖选定断点，没有另造数值重评分或独立确认。
首两用户64生成／896,432 known是这139个响应的子集，不再相加。新B0费用与下方截至旧
505 B2评分结束的2,002生成／14,062,204 known闭合总成本分开，连续账本未重置。

**B1首用户子集也已闭合，整个B1仍在运行。**8预测／20完整答案、18份成功提交回执、
unprocessed0、最后17事项，原0／1／5／6真实空维护。该用户36生成全部stop、553,877
known，属于在运行B1预测的子集；此处没有汇总其encoder费用或整个B1成本。Root读完
20条完整答案，并复核原0／1及6／7的选定来源；与B0合计93条完整答案阅读，仍无完整
来源审计或数值重评分。B1原0／1分别5／6条候选实际送达，输入4,350／4,349低于32,256，
正式editor均为`{}`、无提交／拒绝、空库前后相同；不能直接归因结构化生成或模型选择。

**新复核把正常执行之后的语义问题分开记录。**

- B0第三用户原3／5分别9／4条结构化变化实际送达，职业与健康旧事项都在实际K10中，
  editor输入19,066／18,775低于32,256，均stop且正式`{}`；15份旧记录值全部不变。
  本次来源有明确新进展，但决定、考虑与完成仍需按实际角色区分。一个抽取候选将偏好
  对比强化成没有来源支持的过去经历，说明不能强制所有候选写入。兼容字段
  extracted_memories为空不表示没有抽取变化，实际交付的是change_candidates。
- B0第四用户原3的首batch及最终收入回答采用User实际报告，未跟随Assistant反复提供
  的冲突数值，这是有界的来源归属正例。但复合条款重写后，未重述的旧值和旧职业信息
  被放在新来源及新时间之下；文本值保留不等于先前支持和时间保留。该事件有两个batch，
  首batch的操作不能代表另一batch或整事件语义通过。
- B1首用户原6的当前来源明确报告社会支持与求职进展，5候选和实际K10送达，输入
  23,115、editor stop且`{}`，所有记录值不变。原7的后续来源明确报告新角色转换，3候选
  送达后实际新建一条带日期记录。后来的保存不能追认较早事件已保存；追加可以支持
  当前解释，缺少UPDATE本身不判失败，来源未明确的具体职位也不能由参考答案补写。

上述均为开发期Root定性复核，选定来源、实际输出、回执、前后状态和完整答案分别核对，
不生成新的作者标签。原始正文及HTTP等原件保持本地ignored。

**当前工程修复与待验证语义分开。**[PR98](https://github.com/minguselandy/MiLAi/pull/98)
已合并旧支持继承：from_unit与assertion.keep明确指向同一已交付旧单元、未显式指定
keep_support时继承其已有支持。改变断言、新内容和新关系仍需实际支持；该修复解决
冗余表达造成的误拒，不决定哪些旧内容仍有效，也不保证复合条款重写保留全部限定。
不能离线放行旧提案后回填旧成功。Reader278份容量投影及两个实际输入诊断、新Host两条
保存续办分别已有有界证据，仍不是完整自然历史／功能语义验证；这些入口无需重新建设。

当前单记录输出schema允许creates及records均省略，`{}`是合法no-op；合法性与本次
维护完成分别判断。后续只隔离一个输出表达因素，例如显式no-op／修改结果的等价表达，
保持不写入合法，不强制非空、盲重试或另设审核Agent；评价同时看有支持变化的落实、
合理不写入及错误新增。下述格式诊断仍只是准备，不能同时改多个因素后声称机制因果。

身份遗漏的后续影响也需按链路分析：owner是访问归属、speaker是来源说话者、subject是
断言主体，不能自动互换。只有实际来源支持才能关联姓名／别名与自我主体；后续补齐或
按权限回读实际可见Episode不能借owner字符串、gold或问题中的姓名推断。当前报告只记录
早期形成失败与后续回答缺口，不声称已开发或验证新的主体机制。

自然历史仍是主结果。必要时沿已有真实前态入口做有限机制诊断，将相同来源／条件的
Reader表示与实际前态的编辑算子分别比较；机制诊断不替代整体可用性，也不新增大矩阵、
来源门禁、SHA检查或概率／图平台。模型选择断言含义与真实支持，程序沿现有入口提供
已知角色、时间、引用身份和实际回执；合法引用与关系两端有来源不自动证明关系成立。

**方法调查仍用于隔离一个因素，尚无因果结论或默认改动。**实际client使用Chat Completions，
vLLM0.27.1／Qwen3.6、thinking=true；正式输出问题与语义选择仍未分离。
[官方结构化输出说明](https://docs.vllm.ai/en/v0.27.1/features/structured_outputs/#reasoning-outputs)
及[Qwen部署文档](https://qwen.readthedocs.io/en/stable/deployment/vllm.html)提供格式合同；
[上游另一故障](https://github.com/vllm-project/vllm/issues/44012)使用0.21的Responses API及
不同thinking／reasoning配置，不能直接解释本轮Chat Completions的正式空对象。
[Grammar-Aligned Decoding](https://arxiv.org/html/2405.21047v1)仅作为隔离格式因素的研究思路。

已预选四个曝光开发输入，其中三个原空输出、一个实际非空控制；保持原来源、前态、消息、
模型、thinking、temperature和预算，只对比json_schema／json_object。准备项最多8次生成、
0Reader／Judge／encoder／记忆提交，**实际调用0**，仍须待当前五方法诊断、评分及复核闭合
后占用串行资源。单次随机观察不能证明因果、实际状态改善或泛化优势；旧505的四次格式
诊断单独保留，不跨版本拼接，不改变默认格式或执行私有草稿。

下一步按原规划收敛一个通用维护因素，再选择一个候选完成自身65／277连续历史，65为
277子集；长历史准备尚未准入。同版五方法完整评分、必要消融、native／drift／recovery、
固定更紧预算、最终冻结后16保留用户、外部28描述性问题／1,354次历史出现及原10完整
答案审计、同候选Host135case／192message与冻结后实质性新故事、六项最终交付仍未完成。
保留用户尚未用于开发，`single_verdict_v1`未准入，无最终候选或稳定方法优势，Product NO_GO。

本次Schema／API／权限／Canonical行为均未改变，模型任务及冻结配置未改。发布检查限于
实际闭合计数与子集算术、相对链接、历史快照保留、ignored边界、diff和当前叙述文档的CI
路径分类；未重跑源码包测试或模型实验，新报告提交自身所选CI另外核对。文档回退基点
为7f6ffef，源码无需回退。

## 2026-10-08 02:11:38 UTC：当前开发整理与新运行的实际断点

本节固定于2026-10-08 02:11:38 UTC／北京时间10:11:38，补充用户要求的当前开发
整理。发布前main仍为`32c4584a93704436aba41618612cdbc394b2aa0c`，相关PR83至100已合并；
本报告通过[PR101](https://github.com/minguselandy/MiLAi/pull/101)提交。报告提交与运行源码
分别记录：正在运行的五方法预测冻结于`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`，
原三臂闭合分数仍归属505；当前文档更新不改变源码、配置、模型任务或原固定快照。

**五条主线已经接入同一MemoryService和普通Host，当前工作是收敛语义与完整请求可靠性。**

| 主线 | 已有实现及实际证据 | 尚未形成的结论 |
|---|---|---|
| Grounded Memory | 来源角色／时间、Episode、共同维护及实际提交回执；Host与benchmark共用 | 来源存在不能保证主体、限定与计划／完成状态正确 |
| Verified Object References | 两应用对象核对、查询／执行／观察／发现；业务进度与当前许可分列 | 业务完成不等于结果记忆或整个请求完成 |
| Semantic／Episodic Memory | 语义事项、来源Episode、显式整理、Append-only及可选激活原语 | 尚无同版完整五方法优势；激活用途均值不是事实概率 |
| Grounded Revision | 局部修订、实际版本历史入口、查询日历和范围；真实历史复核已有改善 | 更新选择、非目标保持、结构化时间及Reader解释仍不稳定 |
| Lifecycle Recovery | 完整请求分项、原attempt绑定、实际Tool保存回执与整理pending核对 | 结构completed与semantic_coverage／用户收到反馈分别判断 |

近期4e Reader修复只压缩相同的派生元数据，278份实际输入离线展开等价，原两份超限
投影均可容纳；这属于容量证据，0新增HTTP，不证明自然答案正确。4e普通Host从原pending
实际库进行两消息续办／只读重开：实际Tool批次r3绑定原保存attempt，旧failed保留，
业务仍只有1次预订与1次补标签；只读重开记录值及业务行不变。两条10生成／110,544
known、embedding1,372 tokens已包含在下节原闭合总成本内，不再相加；结构闭合不表示
semantic_coverage已验证，只读回答依据已送达快照，不是新增实时业务查询。

**新的4e预测在运行，没有整臂或五方法终态。**PID1675659在固定观察时实际存活；B0
保存18/32预测，四用户为[8,8,2,0]。B1／B2／M／Append-only尚未启动，不记零分；各臂
均无terminal-predict，Judge0。Root已读首两用户的32条完整自然答案，来源审计未完整，
没有另造数值重评分或独立确认。01:43:03的1/32观察保持为下节历史快照。

| 4e B0已闭合的用户子集 | 预测／完整答案 | 真实空维护原序号 | 成功提交回执 | 最后事项数 | 已确认生成子集成本 |
|---|---|---|---|---|---|
| 首用户 | 8／20 | 0、1、5、7 | 16 | 15 | 36响应／481,157 known，均stop |
| 第二用户 | 8／12 | 1 | 24 | 20 | 28响应／415,275 known，均stop |

两子集共64生成／896,432 known，属于正在运行的B0预测，不是额外任务或完整B0费用；
这里没有汇总encoder费用，也不并入下节截至旧B2结束的2,002生成闭合成本。首用户初始
身份和就业信息没有形成，后续姓名、收入及归属回答受影响；第二用户初始身份能够保存
并读取，但第二次空维护后职业信息缺失。后续偏好及带日期变化可被保存和使用；不是
整个提交链失效，也不能据此称这些子集语义通过。

**已核对的最早断点在来源／候选送达之后、正式编辑输出之前。**首用户原0／1的当前
来源分别12／8片段，User与Assistant分别6+6／4+4；抽取候选5／4条均实际送达editor，
前态为空，输入4,826／4,792 tokens低于32,256。抽取与editor均stop，原始HTTP正式
content均为`{}`，没有提交、拒绝或容量失败，前后记录值均为空；原2随后有8次新建提交。
HTTP收据保留在本地，client没有把非空正式编辑转换成空对象。

正式输出选择、结构化约束以及reasoning／content转换的贡献仍未确定。已核对本地
vLLM0.27.1，并检索[该版本官方结构化输出说明](https://docs.vllm.ai/en/v0.27.1/features/structured_outputs/#reasoning-outputs)
及[官方通道合同](https://github.com/vllm-project/vllm/blob/main/docs/features/reasoning_outputs.md)。
[作者报告的另一故障](https://github.com/vllm-project/vllm/issues/50948)采用不同触发条件，
不能作为本轮故障归因。已有[Grammar-Aligned Decoding研究](https://arxiv.org/html/2405.21047v1)
仅提供隔离格式因素的思路，没有引入新解码器／模型／审核Agent，也没有更改运行格式
或将私有草稿作为正式提交。调查新增真实HTTP0、保留用户读取0。

下一步先闭合当前同版五方法预测、评分和来源复核，再按最早断点选择一个通用因素做
受控改进；空提案保持合法，不强制写入或按gold补事实。随后依规划14.2选择一个候选
完成自身65／277连续历史，65为277子集；长历史配置只是准备，尚未准入。必要消融、
native／drift／recovery、固定更紧预算、最终冻结后16保留用户、外部任务、同候选完整
Host回归和六项交付均未完成。当前没有最终候选或泛化优势，`single_verdict_v1`未准入，
Product仍NO_GO；原始正文、gold、HTTP、reasoning、数据库、私有配置和日志继续ignored。

本次只修改三个文档，Schema／API／权限及Canonical行为均未改变。旧报告提交17973e0
自身两Fast已成功，其Full在02:10观察为19个作业成功、1个进行中；不借给补充后的新
报告头。按现有CI路径分类，三个叙述文档不选Lab包测试、full_required=false；撤去本次
主动添加的可选full-composition标签，旧已启动运行保留，新报告头单独核对所选Fast。
链接、算术、ignored边界和diff检查随发布记录；文档回退基点17973e0，源码无需回退。

## 2026-10-08 01:43:03 UTC：三组原评分完整闭合，新五方法预测已启动

本节固定于2026-10-08 01:43:03 UTC／北京时间09:43:03。报告版本以所在提交为准；
发布前main为`32c4584a93704436aba41618612cdbc394b2aa0c`，PR83至100已合并，远端open
列表在本轮核对时为空。[PR100](https://github.com/minguselandy/MiLAi/pull/100)于前日23:58:06
UTC合并，其实际受测头99a的[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37702216803)
与[Full](https://github.com/minguselandy/MiLAi/actions/runs/37702216877)成功，Full21/21作业通过。
本地canonical main已快进到32c；17份与远端正文相同的原untracked计划在可恢复备份后
成为tracked，另一个用户计划仍保留为untracked。运行源码及连续账本没有被替换或重置。

**原505 B0／B1／B2的预测和评分分别完整闭合。**实际源码均为
`505cefaee8c25cac0670fb1d3a38f7c2fae33165`，每臂四用户各八会话、32检查点及评分终态
COMPLETED_EXPERIMENT_PHASE，进程均退出0。B1评分从前日23:15:33至00:21:56 UTC，B2从
00:27:41至01:40:11 UTC；均只读原预测、状态和author retrieval，没有重跑Writer／Reader／
encoder。原M／Append-only仍是部分预测失败，不补零分，也没有完整五方法终态。

| 臂 | 更新Correct／全部机会；valid | 更新其他原标签 | QA Correct／全部机会；valid | QA其他原标签 |
|---|---|---|---|---|
| B0 | 31/72；61 | 29 Omission、1 Hallucination、4 Omitted、7 null | 43/73；67 | 9 Omission、15 Hallucination、6 null |
| B1 | 27/72；62 | 33 Omission、2 Hallucination、9 Omitted、1 null | 33/73；69 | 15 Omission、21 Hallucination、4 null |
| B2 | 26/72；64 | 38 Omission、4 Omitted、1 Omitted Update、3 null | 34/73；69 | 14 Omission、21 Hallucination、4 null |

全部机会更新正确率分别43.1%、37.5%、36.1%；QA分别58.9%、45.2%、46.6%。valid正确率
另以31/61、27/62、26/64和43/67、33/69、34/69计算；不把Omitted／Omitted Update重命名
为合法Omission。formation非interference参考均439，valid分别394／416／407；实际formed
输出63／59／52，valid51／47／41。作者离线聚合均无异常，原无效判断仍存在。

| 按既定四用户顺序的Correct／全部机会 | B0 | B1 | B2 |
|---|---|---|---|
| 更新 | 11/19、7/15、7/20、6/18 | 10/19、3/15、12/20、2/18 | 10/19、6/15、4/20、6/18 |
| QA | 12/20、7/12、14/22、10/19 | 8/20、8/12、10/22、7/19 | 12/20、10/12、5/22、7/19 |

既有分析器读取三臂终态，状态为COMPLETED_PAIRED_SOURCE_ANALYSIS，仅限这三臂。
按用户等权、四个来源簇的描述性95%区间，B1减B0的更新为−7.29百分点
[−24.44,+13.19]、QA为−11.41[−19.09,+1.70]；B2减B0更新为−6.73[−12.57,−1.67]、
QA为−7.92[−30.68,+14.80]。本轮B2更新标签落后于B0；这里只有四个曝光用户、各方法
单条随机历史及同家族Judge，不能推广为稳定的总体结论，没有独立确认。Root先前已读
三臂及M／Append部分共276条完整答案，来源审计未完整，没有另造数值重评分。

**最早语义断点仍是已识别变化没有落实。**同一曝光事件中，B0／B1的当前来源与相关旧
事项均实际送达，抽取和editor正常stop，但editor为空、没有提交，记录值不变。B2实际
修改一条职业事项并新建计划，另一个财务事项仍保持原值；M新建四条，但相关旧事项未
在其实际K10中，不能声称修订了它。这些臂此前状态不同，不是同前态recipe比较。来源的
决定／考虑仍可能被强化为完成／计划；参考要求中未获当前来源明确支持的更强事实不能
由程序补写。原作者标签与Root的来源复核分别保留。B2原首用户4／7两次editor前容量
失败覆盖五个更新，原标签3 Omission、1 Correct、1 Omitted；它们没有editor HTTP／语义
提交，不能合并成真实空提案，也不能把该Correct当成本次提交成功。

**费用截止B2闭合，与新运行在途费用分开。**B0 Judge479／1,510,929 known，B1
446／1,408,572，B2 514／1,772,308；合计1,439响应／4,691,809 known，全部stop，
新增unknown及embedding均0。子用户费用全部包含在相应整臂内。自原505预测启动前
闭合账本起，包含部分五臂预测、格式诊断、两批Host、独立Reader及这三臂评分的累计为
2,002闭合生成／14,062,204 known、embedding292,092 tokens。B2结束的连续账本为
45,523 requests、187,905,008 known、188,096,496 charged、embedding1,623,223、
unknown5；请求和known差额核对一致，unknown5为原历史值，预算未重置、上限未新增。
原B0报告及各评分子集不再重复计入。本段没有计入随后新五方法的在途请求。

**新4e五方法已真实启动，尚未完成。**01:41:28 UTC，确认旧B2退出及串行HTTP lease
空闲后，从冻结`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`运行既有
`tools/run_edit_suite.py CONFIG OUTPUT --benchmark halumem --phase predict`。
配置为ignored的`artifacts/unified/prefix8-five-arm-4e46099-v3-config.json`，产物为同目录
`prefix8-five-arm-4e46099-v3`，实际PID1675659。B0／B1／B2／M／Append-only依次串行，
各方法／用户独立空库；只改版本及实验元信息，模型、dense K10、输入／输出预算、
recipe及方法参数与原505配置相同。4e自身CI已在上节核验，源码内容与当前main相同。
固定观察时仅B0保存1/32预测，其余未启动，各臂无predict终态，score0；这不是完整结果
或新Reader语义成功。旧准备、失败及日志保留，不热改或覆盖。

完整任务继续active。依配套规划14.2，先完成共同底座五方法诊断，再选择一个候选沿
自己的连续历史取得65／277观察；已准备的长历史配置尚未准入，不自动启动全臂长跑。
native／drift／recovery、必要消融与固定更紧预算、冻结后的16保留用户、外部任务、同候选
Host135case／192message及实质新故事、六项交付仍未完成。16未用于开发，
single_verdict_v1未准入，Product NO_GO。原始正文、gold、HTTP、reasoning、数据库、
私有配置及日志仍ignored。以下固定快照保留。

## 23:15:33 UTC：PR99合并，原B0评分闭合，真实保存续办与只读重开闭合

本节固定于2026-10-07 23:15:33 UTC／北京时间2026-10-08 07:15:33。报告版本以所在
提交为准。main为`eedd26c5455811d9e3b30624249e205467410268`，PR83至99已合并。
PR99实际受测头及本次Host源码为`4e4609917c1b0ce6e3aa14b3f885df6854c364c1`；
原B0评分及刚启动的B1评分仍冻结`505cefaee8c25cac0670fb1d3a38f7c2fae33165`。
当前main源码内容与受测4e相同；这不把新修复归入原505预测或评分。

**PR99自身CI成功后合并，首失败保留。**[PR99](https://github.com/minguselandy/MiLAi/pull/99)
于23:01:58 UTC普通merge。其4e头的[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37696067124)
及[Full](https://github.com/minguselandy/MiLAi/actions/runs/37696067365)成功，Full21/21作业通过。
首81d头的[Full foundation](https://github.com/minguselandy/MiLAi/actions/runs/37693982093)
因旧日历测试读取Reader已省去的外层派生time_values而失败。后续只修正既有测试，分别
核对API及保存检索保留秒精度／未知时区、Reader保留原始时刻／名义日历／实际有效限，
并检查指令不从日历名推断时区；未补回重复字段或改变源码／workflow／运行配置。
工程CI不等于语义效果验证。合并后远端open列表为空是该时点观察。

**原505 B0预测及评分均闭合。**评分从21:56:17至23:04:56 UTC，32/32会话检查点、
terminal-score为COMPLETED_EXPERIMENT_PHASE、进程退出0。没有重跑Writer、Reader或
encoder，也没有重启原预测。作者原标签如下，不重命名Omitted或补评null：

| 原B0标签 | 全部机会 | 有效判断 | Correct | 其他原标签 |
|---|---|---|---|---|
| 更新 | 72 | 61 | 31 | 29 Omission、1 Hallucination、4 Omitted、7 null |
| QA | 73 | 67 | 43 | 9 Omission、15 Hallucination、6 null |

更新Correct为31/72（43.1%），valid分母为31/61；QA为43/73（58.9%），valid为43/67。
formation非interference参考439／valid394；实际formed输出63／valid51。原作者聚合没有
异常，但无效判断仍存在。479个Judge响应全部stop，1,510,929 known、新增unknown0、
embedding0。B0预测139加评分479，共618生成／3,963,465 known，embedding仍219次／
74,992 tokens。各用户及先前部分评分成本属于这479的子集，不能再次相加。
Root先前已读73完整自然答案，来源审计未完整，没有另造数值重评分或独立确认。

**新Host从原1f实际pending状态独立复制，两次执行闭合。**不是续写已运行main1af的库，
原run_id、owner、request、业务对象和配置保留，使用既有普通message入口，不注入理想
事项或业务回执。23:07:07至23:08:54 UTC第一消息只授权查询业务及续办原结果保存。
User来源维护实际提交r2，但不能证明业务结果保存，原attempt仍为failed／
result_save_unconfirmed；本次不是旧1af的Writer length失败。随后真实get_reservation的
Tool来源维护提交r3，新attempt关联该批次及实际回执，原memory变为committed，
request结构状态completed。旧failed保留，semantic_coverage仍unchecked，反馈仅确认
Host收到checkpoint，user_seen仍unchecked。当前记录保留预订编号、数量、目的地／包装
配置、首次标签失败及后续标签完成历史；未写成实际物理送达。程序最终反馈引用实际
已送达的r3正文，分别列出业务查询、记忆提交及原请求进度。

23:11:39至23:12:01 UTC第二消息跨进程／会话只读重开，memory及business写权限均false，
maintenance及显式记忆修改均0。实际公开records的值与第一消息之后相同；业务DB所有
reservation／attempt行也相同，始终恰有1预订／1补标签。该消息用已送达快照与先前真实
回执回答，走agent_response_retained，没有新业务工具调用；不能宣称再次实时发现了
外部变化，或直接复现旧1af第二消息的程序回执分支。Root读完两条完整候选／送达答复，
并核对实际提交、来源及业务行；这是已曝光故事的改进复核，不是未见故事或完整Host准入。
第一消息8生成／96,115 known、embedding1,196 tokens；第二2生成／14,429 known、
embedding176。两条共10生成／110,544 known、embedding1,372，Judge0、新增unknown0。

**只汇总已经闭合的费用，B1在途另列。**自17:09预测启动前账本起，上节五臂部分预测、
格式诊断、旧1af Host和独立Reader共553生成／9,259,851 known；新增B0 Judge479及新Host10，
共1,042闭合生成／10,881,324 known，embedding292,092 tokens。B1开始前连续账本为
44,563 requests、184,724,128 known、184,915,616 charged、embedding1,623,223、
unknown5，差额核对一致；unknown5是原历史值。没有重置预算或新增上限。旧报告、各臂
预测、子用户评分与这段累计费用不再重复相加。

23:15:33 UTC原505 B1从32份保存预测启动纯score，PID1052682；此固定节不计其未闭合
成本。其后B2待串行评分；原M／Append失败部分不补零。新的4e五方法独立空库prefix8
配置及源码已准备，真实调用仍0，保持原K10、预算、模型、recipe及方法配置；旧81准备
已标为执行前替换，未运行输出不存在。原278份离线容量检查和两条独立Reader诊断仍按
原版本及范围归属，不能当新的完整五方法结果。

完整任务继续active：同版五方法、65／277连续历史、native／drift／recovery、必要消融／
一个固定更紧预算、最终冻结后16保留用户、外部任务、Host135case／192message及新增
故事、六项交付尚未完成。16未用于开发，single_verdict_v1未准入，Product NO_GO；原始
正文、gold、HTTP、reasoning、数据库、私有配置及日志继续ignored。下面各固定快照保留。

## 21:58:44 UTC：三臂预测闭合、两臂部分失败；读取与保存续办按实际断点修复

本节固定于2026-10-07 21:58:44 UTC／北京时间2026-10-08 05:58:44。报告版本以所在
提交为准。远端main为`1af2585012990e0df21d18b54df68c1b87bf0d8a`，PR83至98已合并；
发布前集成源码为`c2a5900`（Reader880、恢复4bfc及反馈c2），自己的远端CI尚未请求。下面五臂预测及B0评分仍冻结
`505cefaee8c25cac0670fb1d3a38f7c2fae33165`；Host两消息实际冻结main `1af2585`；
新Reader诊断冻结`1f1022def0d4e98bfe9dd362c18875dbba4ea36f`。各运行不互相补成绩。

**后续工程已合并到main，原运行没有热改。**PR96减少容量预览的重复schema复制；
PR97只缩短生成的解释性定义名称，保留原共享选择和fallback；PR98在同一旧unit同时
显式指定from_unit与assertion.keep且未指定keep_support时沿用其已有支持。旧文本、角色、
断言、来源可见性、关系支持及版本检查继续适用，改变断言仍需实际新证据。PR98自身
[Full337](https://github.com/minguselandy/MiLAi/actions/runs/37683448942)成功21/21。
两个原B2容量失败用合并后的实际提示离线投影为31,821及32,078，低于32,256；尚未
真实复跑。工程修复不能改记原505的拒绝、容量失败或语义问题。

**505原suite已退出1，Append-only独立后续也退出1。**原suite于21:08:17 UTC退出，
B0／B1／B2各自预测32/32闭合；M在第三用户原7首问题的Reader输入45,933超限后失败，
保存23份预测，第四用户未运行。随后仍用同一冻结505源码及原参数，从该臂自己的空库
单独执行Append-only；首用户原7 QA0已有完整答案，QA1输入34,646超限，最终只保存7份
预测。两次失败均发生在对应Reader HTTP前；旧输出和终态保留，不续写成COMPLETED。

| 505实际预测范围 | 保存预测／完整自然答案 | 生成响应／known tokens | embedding响应／tokens |
|---|---|---|---|
| B0 | 32／73 | 139／2,452,536 | 219／74,992 |
| B1 | 32／73 | 139／2,306,194 | 200／68,175 |
| B2 | 32／73 | 137／2,332,611 | 212／73,209 |
| M，部分失败 | 23／44 | 92／1,486,884 | 142／53,421 |
| Append-only，部分失败 | 7／13 | 29／456,691 | 43／19,761 |
| 操作成本合计，不是方法总分 | 126／276 | 536／9,034,916 | 816／289,558 |

全部536生成响应均stop，预测Judge0、新增unknown0。M及Append分别有24／8次维护记录，
不能按保存预测数量推导其bank终态。B0有11个真实空提案、57新建／6修订／1拒绝；
B1有16个真实空提案、53新建／6编辑；B2有8个真实空提案、47新建／5重写／4拒绝／
4no_change，另2个编辑前容量失败；M有10个真实空提案、49新建／7编辑、0拒绝；
Append有2个真实空提案、20新建／1明确时间拒绝。空提案、no_change、拒绝和调用前
容量失败分列，实际提交不定义语义成功。

Root已读这276个完整自然答案，完整来源审计未完成，没有另造数值重评分。实际选定
来源复核仍见：身份与姓名关联遗漏、Assistant金额被归为User、已抽取且旧目标送达之后
仍漏写，以及“考虑／可能”被强化为计划。B2第二用户原0的部分普通事实被生成成条件
关系；端点来源存在不证明关系本身。没有完整五方法分数或方法优势结论。

**原保存B0开始纯评分。**21:56:17 UTC从冻结505目录，用原B0 actual-config及单臂CLI
执行既有单臂入口：

```bash
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python -u tools/run_edit_benchmarks.py \
  --config /cra/memory/mx_memory/MiLAi-worktrees/development-milai-edit-v2/MiLAi-Lab/artifacts/unified/prefix8-five-arm-505cefa-v2-B0-config.json \
  --output /cra/memory/mx_memory/MiLAi-worktrees/development-milai-edit-v2/MiLAi-Lab/artifacts/unified/prefix8-five-arm-505cefa-v2/B0 \
  --benchmark halumem --phase score
```

PID728144存在；固定观察已确认22个Judge响应／53,427 known，完整评估
0/32，尚无terminal-score或进程终态。Writer／Reader／encoder不重跑；B1、B2评分待串行
排队，M及Append失败部分不补零。此在途观察不能用于重启或并发占用真实HTTP。

**Reader修复选择语义投影，停止继续枚举格式。**仅增加重复值共享后，原M超限输入
仍为45,937；试验性列式／数字引用仍为36,084，未提交这些codec。新1f1022d在现有
Reader函数内按实际source_ref继承相同来源元数据、从外层继承相同查询与版本时间，省去
这些重复值及可重新计算的相同时间解析；不同值、显式null、精度／时区差异、实际有效
限、条件关系、原文本与来源片段继续送达。保留全部K10、预算及存储原件。它是有明确
继承语义的只读呈现，不能再称所有内部字段逐字段无损压缩。

21:53:15至21:53:36 UTC，原M和Append失败检索各完成一次独立Reader诊断，新prompt
分别28,506／24,744，2stop／54,860 known；Writer、提交、embedding、Judge均0，
新增unknown0。Root读完两答案并核对相关实际来源：退休动机及月收入能够从材料中
回答，但第一答案仍把“考虑旅行”列为退休动机。只证明这两条已曝光材料可以读取；
不续写旧预测，不记语义全面通过或独立确认。发布前追加离线检查覆盖505全部278份
实际检索：B0／B1／B2各73、M45、Append14，276份用原保存请求，另2份为上述HTTP前
失败输入。超限2→0，最大45,933→28,506，每项实际K、正文及单位数量差异0，原文本及
来源证据保留，0HTTP；不证明未来所有容量或回答效果。3项受影响Reader检查、类型／格式／
边界及SQLite示例通过，新实现的远端CI另行核对。

**普通Host显式只补保存，发现回执绑定与反馈的真实断点。**21:40起，以原1f业务完成／
保存pending实际数据库的独立备份，在main1af源码执行save-only及跨会话只读两消息。
两条均COMPLETED，11生成／125,504 known、embedding1,162 tokens、Judge0、新增unknown0；
真实业务始终恰有1预订／1补标签，没有重复执行。首次User维护为已确认length失败，
后续实际get_reservation来源共同维护已提交r2；旧request却仍memory.failed，因为新
Tool批次未登记到下一语义attempt。第二消息已实际读到r2，但程序反馈仅显示本轮未写，
遗漏已保存内容。两条执行闭合不等于原完整请求闭合或内容正确。

新9496416（集成为4bfcf5a）只在当前允许保存且原请求已选中时，按实际Tool调用、原
回执、来源和已验证对象关联新批次，在Writer前登记原请求下一attempt，再收取这些批次
的实际回执。旧failed／unknown保留，只读不登记、不认领提交，业务不重放。
11项受影响Host检查、Ruff、Python3.11 mypy及包／工具边界通过，0真实HTTP；新的真实
效果待串行复核。新4ecbd67（集成为c2a5900）在现有renderer仅引用实际送达的保存正文及
版本，保留本轮未写；未送达原request进度时明确未核对完整闭合。14项直接检查、SQLite
重开只读例子、Ruff、3.11 mypy及边界通过，0真实HTTP；没有额外读取或借用模型最终声明。
原r2将目的地配置
写成已送达，仍是独立语义缺口，不能借新回执绑定称其事实已经正确。

**四次Writer格式诊断闭合，但不据此改默认。**同505两个已曝光实际输入各用原json_schema
与json_object一次，4stop／44,571 known、无提交／embedding／Judge／新增unknown。
第一输入两次均3新建；第二输入分别真实空与5新建，四次均通过原schema。json_object的
一条提案错配恋爱状态主体；更多提案不等于忠实。旧reasoning里的草稿不被当作实际
输出或提交，四个随机观察不建立格式导致漏写的因果结论。

**闭合成本与在途成本分开。**上表预测536，加独立格式4、Host11、Reader2，共553个
闭合生成／9,259,851 known，自17:09预测启动前账本差额一致；embedding为290,720 tokens。
21:53 Reader闭合／B0评分启动前连续账本为44,074 requests、183,102,655 known、
183,294,143 charged、embedding1,621,851、unknown5。此处不包含随后在途B0评分，
unknown5仍是原历史值；没有重置预算或新增上限。子集与上表不再重复相加。

方法借鉴与推断见[原始方法核对](MILAI_EDIT_RELATED_WORK.md)。完整目标继续active：
同版五方法、65／277连续历史、native／drift／recovery、消融／固定更紧预算、最终冻结后
16保留用户、外部任务、完整Host135case／192message及新增故事、六项交付仍未完成。
不拼接跨版本轨迹，16未用于开发，single_verdict_v1未准入，Product NO_GO。全部原始正文、
gold、HTTP、reasoning、数据库、私有配置与日志继续ignored。下面旧固定快照保留原时点。

## 17:12:00 UTC：PR94合并，旧23份保存评分闭合，新五方法从空库运行

本节固定于2026-10-07 17:12:00 UTC／北京时间2026-10-08 01:12:00。报告版本以所在
提交为准；main为`2cedc371`，最新Reader实现为`588260e`，实际新运行冻结报告头
`505cefaee8c25cac0670fb1d3a38f7c2fae33165`。旧预测及下面23份评分仍冻结`ec37d38`，
不包含Reader表示压缩或整理回执修复。下方16:04及更早快照保留原时点。

**PR83至94已合并。**[PR94](https://github.com/minguselandy/MiLAi/pull/94)于16:45:09 UTC
普通merge为main`2cedc371`，integration快进、干净，源码内容与受测头`505cefa`相同。
该头自身[Fast534](https://github.com/minguselandy/MiLAi/actions/runs/37649602069)及
[Full333](https://github.com/minguselandy/MiLAi/actions/runs/37649602205)成功，Full21/21；
[main push](https://github.com/minguselandy/MiLAi/actions/runs/37654504196)成功。
PR93的整理中断核对已在父版本合入；这些CI与工程闭合不证明记忆语义正确。

**ec实际保存的23份B0预测评分已闭合。**16:08:14至17:03:48 UTC，三个明确子队列分别
评分第一用户8、第二用户8、第三用户7会话，均有`COMPLETED_EXPERIMENT_PHASE`评分
终态且退出0。使用原预测、状态快照及保存的作者更新检索，未重跑Writer、Reader或编码器。
第三用户的复制bank包含原第8次维护；它不是7会话bank终态，评分读取逐会话保存材料。
原32会话预测仍FAILED，第四用户没有预测，其他四方法原队列未启动，均不补零分。

| ec保存子集 | 更新Correct／全部机会；valid | QA Correct／全部机会；valid | Judge响应／known tokens |
|---|---|---|---|
| 第一用户8会话 | 9/19；18 | 11/20；20 | 157／523,098 |
| 第二用户8会话 | 8/15；12 | 12/12；12 | 145／435,922 |
| 第三用户7会话 | 5/12；10 | 11/12；12 | 146／461,097 |
| 合计23会话 | 22/46；40 | 34/44；44 | 448／1,420,117 |

原更新标签为22 Correct、17 Omission、1 Hallucination、3非标准`Omitted`及3空标签；
后两类共6个无效判断原样保留，不映射成Omission。QA为34 Correct、5 Omission、
5 Hallucination，全部44有效。formation reference324／valid284，formed outputs56／
valid44。Root已读全部44完整自然答案，完整来源审计未完成，没有另造数值重评分；
同家族Judge与Root开发复核不算独立确认。此子集不是完整32或同版本五方法成绩。

**闭合成本单列。**448个Judge响应全部stop，新增编码0、unknown0。评分后连续账本为
43,520 requests、173,809,046 known、174,000,534 charged、embedding1,331,131、unknown5；
与原预测闭合账本差额一致。ec首预测92生成加这次448 Judge合计540响应／3,025,818 known，
编码仍151次／55,488 tokens；上表用户小计不再重复相加，预算没有重置或提高。

**原超限Reader输入在505实际完成一次调用。**17:06:20至17:06:38 UTC，保留原实际K10、
问题和只读视图，仅使用已合并的引用表表示；实际prompt31,787低于32,256，completion1,971，
合计33,758 known，finish_reason=stop。Writer／encoder／Judge均0、新增unknown0。
Root已读完整回答：它将退休动机标为未知，将后续计划与退休原因分开；未作数值重评分，
完整来源审计未完成，不宣称语义通过或所有未来输入均可容纳。原ec失败不改记成功。
此独立调用结束后账本为43,521 requests、173,842,804 known、174,034,292 charged，
embedding与unknown均不变；这是17:06闭合成本，不是17:12新队列的实时账本。

**新五方法集中预测已启动。**17:09:18 UTC从冻结`source-505cefa/MiLAi-Lab`运行：

```bash
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python -u tools/run_edit_suite.py \
  /cra/memory/mx_memory/MiLAi-worktrees/development-milai-edit-v2/MiLAi-Lab/artifacts/unified/prefix8-five-arm-505cefa-v2-config.json \
  /cra/memory/mx_memory/MiLAi-worktrees/development-milai-edit-v2/MiLAi-Lab/artifacts/unified/prefix8-five-arm-505cefa-v2 \
  --benchmark halumem --phase predict
```

按B0→B1→B2→M→Append-only串行，每臂每用户各自空库；四开发用户各前八会话。
只更改相对ec配置的experiment_name、config_version、source_version。共同两阶段、I2、
BGE-m3 dense cosine K10、Qwen3.6 thinking=true／temperature1、context65,536／输出32,768／
余量512、source4,096／body8,192、working_sets=false及全部EditFeatures保持。
Root独占真实HTTP，旧产物和冻结源未改，16保留用户未进入运行。

本固定观察PID3757265存在；B0维护2/32、保存预测1/32，8生成响应均stop／71,493 known，
8编码响应／915 tokens。其余四臂未启动，无任何臂预测终态、进程退出或score。
这是在途观察，不是闭合成本；不得根据旧PID快照重启或同时另起模型任务。

**继续按实际断点收敛。**漏写发生在候选与旧目标已送达之后时，优先检验变化如何落实；
keep支持的旧文本被改写则保留为来源选择问题，不放宽边界。参考现有[方法核对](
MILAI_EDIT_RELATED_WORK.md)，后续只选择一个通用维护因素，固定实际来源、旧库、预算与
Reader评价新要求、非目标保持及后续任务。保持空提案、追加事件和未知的合法性，
不增加抽取器、审核循环或case规则；当前冻结对照不中途改方法。

同版五方法尚未闭合。65／277连续历史、native／drift／recovery、必要消融与更紧预算、
最终候选后的16保留用户、外部任务、完整Host回归及六项交付继续未完成；65不另算独立
子集，不跨版本拼接轨迹。无最终候选、稳定方法优势或独立确认，single_verdict_v1未准入，
Product NO_GO。原始正文、gold、HTTP、reasoning、数据库及私有配置继续ignored。

## 16:04:07 UTC：PR93合并，五组首预测失败，Reader无损压缩仅离线验证

本节固定于2026-10-07 16:04:07 UTC／北京时间2026-10-08 00:04:07。最新源码为
`588260e`，基于main`9775a47`；下面真实预测仍冻结`ec37d38`，不含整理修复或本次
Reader压缩。旧15:24及15:04快照保留，不能继续把当时的运行状态当作实时状态。

**PR93已合并。**[PR93](https://github.com/minguselandy/MiLAi/pull/93)头`ffce48d`自身
两Fast及[Full332](https://github.com/minguselandy/MiLAi/actions/runs/37644210255)成功，
Full21/21。普通merge为main`9775a47`，integration快进且干净；
[main push](https://github.com/minguselandy/MiLAi/actions/runs/37648742589)成功，六个重复
测试job按现有workflow跳过。整理层与普通CLI的回执衔接工程闭合，不代替业务结果保存或
模型语义正确。新588自己的远端CI尚未请求，不借用PR93的检查。

**ec五组首预测已失败并退出1。**14:59:07至15:39:22 UTC，B0完成24次维护记录、23份
预测、44个完整自然答案，用户分布为维护8／8／8／0、预测8／8／7／0。第三用户原7的
首个Reader实际检索10事项，输入32,900超过既有32,256上限，在HTTP前失败；该问题没有
生成响应。B1／B2／M／Append-only未启动，不记零分；无整个预测终态或score。原冻结源、
配置、数据库、预测、检索和失败终态均保留，没有热改或续跑覆盖。

| 闭合成本／行为 | ec首预测实际数量 |
|---|---|
| 生成响应 | 24抽取＋24editor＋44Reader＝92，全部stop；1,605,701 known tokens |
| dense embedding | 151次，55,488 tokens；Judge0、新增unknown0 |
| 提案与实际回执 | 62提案／62回执，61提交／1拒绝，6个真实空输出；另1不完整维护batch |
| 连续账本 | 43,072 requests，172,388,929 known，172,580,417 charged，embedding1,331,131，unknown5 |

成本与启动前账本的requests／known／embedding差额一致，原limits不改、预算不重置。
实际提交或正常stop均不定义语义成功。Root已读全部44完整答案，完整来源审计未完成，
没有另造数值重评分。首用户原4抽取已识别变化、旧事项实际送达，editor仍为空，Reader缺新
偏好；第三用户原6把旧句轻微改写却保留旧keep支持，1提案遭既有来源边界拒绝，同时其他
提案已经提交。这些语义／支持问题与后来Reader容量失败分开，不因输入压缩而称为解决。

**只压缩现有重复值的表示。**原JSON已经没有多余空格。短编号单独只把失败输入降至
32,752，仍超限；短路径的中间方案32,268，也不足。本次使用原引用表的顺序数组和
`#/shared/数字`路径，实际字段和值在展开后不变，不删除来源、角色、时间、限定或事项。
44个已发Reader输入加1个HTTP前失败输入均用原本地tokenizer投影，45份逐字段展开等价，
最大31,787、全部低于32,256，合计少26,145输入tokens；没有扩大预算或减少K10。
这是0HTTP的离线容量验证，没有证明模型能稳定解释新表示，也没有证明未来完整历史均可容纳。

47项既有Reader／runner检查及6项包／工具边界检查通过；两文件Ruff、受影响源Python3.11
mypy和diff通过。原来源历史输入无引用表时仍完整保留；没有新schema、业务权限、模型、
排序、来源初始化或恢复平台。失败驱动的方法参考见[方法核对](MILAI_EDIT_RELATED_WORK.md)，
仍按通用维护机制和实际后续任务判断，不用case规则强制写入或扩大架构。

后续先评分实际保存预测，再冻结新源码、使用新空库完成同版五组集中评测；不把不同版本
轨迹拼成方法优势。原65／277历史、native／drift／recovery／消融及更紧预算、最终候选的
16保留用户、外部与完整Host验证、六项交付均未完成。16保留未用于开发，无最终方法
选择或独立确认，single_verdict_v1未准入，Product NO_GO。

## 15:24:02 UTC：整理中断回执核对接入，集中预测保持原冻结版本

本节固定于2026-10-07 15:24:02 UTC／北京时间23:24:02。本次源码为`188c80a`，
整理层`bb4c7a9`来自C的`2e0d4cf`，基于main`7f755bac`；自己的远端CI尚待发布。
下面仍在运行的五组预测冻结`ec37d38`，不含这项修复，15:04固定成本也不改成实时成本。

**实际复现并修复整理层中断窗口。**既有SQLite示例先经共同维护真实提交一条记忆，
在外层保存结果前中断，留下`maintenance_pending`；关闭并重开后，同一请求仅核对原
维护身份和已有回执，更新外层完成状态及Episode整理标记。核对前仍检查原选择、来源和
指定记录的可见性；正常completed不再次核对，缺失收尾标记可补齐。unknown或没有确认
结果时保持未完成，不调用原生成回调、不重发HTTP、不提交新提案或新增独立来源。

普通`tools/run_memory_operations.py`的consolidate入口复用原session/request维护绑定，
通过既有`maintain_delivery(..., execute=False, new_attempt_id=None)`核对，不重新组成
编辑材料。既有CLI集成用例的两个参数分支也复现内层完成后丢回包，再用同命令重开；
合成transport调用数、实际记录及Source集合均不增加。此入口验证的是同session/request
重开，不据此宣称跨session的任意整理续办已完成，也不替代原业务结果保存pending的续办。

Root串行合流检查：上述2项CLI检查、跨重开SQLite示例、四文件Ruff、三源Python3.11
mypy、包DAG与工具依赖边界、diff检查通过；0真实模型／编码调用。示例同时验证未知
模型结果不重生成、选择变化及记录／来源撤回优先，正常偏好撤销保留会议历史。
公共schema、业务权限、模型配置、实验冻结源及既有预算不改；工程闭合不证明语义正确。

**开发重心收敛到完整用户链路。**五条主线已基本贯通，当前重点是已识别变化的落实、
未改限定保持、三种历史的正确选择，以及业务／保存／反馈分别闭合。依据实际断点参考
[方法核对](MILAI_EDIT_RELATED_WORK.md)，只采用能接入现有维护器的有限改动；
保持空提案与Append-only的合法性，用实际后续任务判断，不以更多UPDATE证明成功。

此时PID3237374仍存在，B0维护及预测均14/32（8／6／0／0），其余四组尚未开始；
无预测终态、进程退出或score。Root已读当前B0首用户20个完整答案，原8会话的真实空提案
及记录缺口保留；完整来源审计未完成，无数值重评分。同版集中预测及评分继续，原完整
验证范围仍未完成；16保留用户未用于开发，single_verdict_v1未准入，Product NO_GO。

## 15:04:41 UTC：PR92合并，同前态比较闭合，五组预测开始

本节固定于2026-10-07 15:04:41 UTC／北京时间23:04:41。报告版本以所在提交为准；
实际Host复测、recipe比较及新五组队列均冻结`ec37d38`，实现为`4b3501b`。
main为`7f755bac`，与该已验证头的源码内容一致；下面14:16及更早观察保留原时点。

**PR83至92均已合并。**[PR92](https://github.com/minguselandy/MiLAi/pull/92)自身
[Fast527](https://github.com/minguselandy/MiLAi/actions/runs/37635708699)、
[Fast528](https://github.com/minguselandy/MiLAi/actions/runs/37635725210)及
[Full331](https://github.com/minguselandy/MiLAi/actions/runs/37635725032)成功，Full21/21。
14:52:37普通merge为main7f755bac；其
[push检查](https://github.com/minguselandy/MiLAi/actions/runs/37640400728)也成功。
main检查复用已测试PR内容，部分测试job按原workflow跳过，不声称全部重跑。
integration快进、干净；14:52远端open列表为空是当时观察。

**新历史入口真实复测已闭合。**同一已曝光日期故事采用独立空库，14:30:57至14:34:11
退出0，4次执行COMPLETED、3次实际提交r1／r2／r3。只读核对历史与各次实际保存逐值相同，
r3恢复原状态，最后只读消息没有维护或业务动作。Agent在撤销时调用既有history及exact-r2
工具，收到已提交的绿色例外；最后只读消息没有再调历史工具。末答能区别当前已过期与过去
曾保存绿色，但把绿色称为initial save，且混淆原Source与修订正文；撤销答复仍暴露内部标识。
Root已读4个完整答复，不记4条语义通过。r1仅原条件带typed applicability，r2绿色的一日
限定仍为文字；随机生成的表示差异不能全部归因于历史入口。18生成／184,931known，
16编码／597token，Judge0、新unknown0；不把Agent finish子集当成全部生成均stop。

**同一实际旧状态的两recipe首次完整比较已闭合。**14:37:49至14:48:26退出0，两条recipe
各4case；before均逐值等于保存的原实际B0库，事项数16／20／20／16。独立SQLite副本中的
旧未来授权冲突未再出现；原962首次失败、原输入和旧库均保留。

| 原case | single_pass实际结果 | extract_then_edit实际结果 |
|---|---|---|
| 3 | 真实空提案，原16事项不变 | 新建5事项，原16值不变；选定复合子句引用范围过窄 |
| 6 | 真实空提案，20事项不变 | 抽取8候选后editor返回{}，20事项不变 |
| 7 | 修订3事项，Reader得到新职业变化；部分措辞强化、支持事实遗漏 | 抽取4候选后editor返回{}，20事项不变，Reader遗漏新事件 |
| 4 | 修订1事项，保留无关旧内容但丢比较方向 | 修订1事项，保留明确比较方向及无关旧内容 |

原6新来源明确报告已获得面试／工作邀请，实际before全部事项都没有该进展；两组空提案
不能由“状态不变”判成功。原7两组实际top10都送达相关职业／健康事项，空提案发生在
抽取和检索之后，不是容量失败。原3部分新子句合并不同User轮次，却只引用一个较窄片段；
这属于引用范围观察，不把所有跨句事实自动判为虚构。Root读完22个完整自然答案及全部8个
editor输出，核对实际前后状态与选定来源；完整原文审计仍未完成，未另造数值评分或Judge。

single_pass为15生成／215,346known、23编码／17,977token；extract_then_edit为
19生成／274,878known、22编码／6,165token。合计34生成均stop／490,224known、
45编码／24,142token，Judge0、新unknown0，与连续账本差额一致。上述Host＋比较合计
52生成／675,155known、61编码／24,739token，子集不重复相加。比较只有4个已曝光前态，
同一随机模型首次输出不同，不能得出整体recipe优势或独立确认。

**同版五组集中预测已经启动。**14:59:07从冻结ec37d38启动PID3237374，依次B0／B1／
B2／M／Append-only；各组、各用户从独立空库开始。共同extract_then_edit、I2、dense cosine
K10、Reader、Qwen3.6 thinking／temperature1及既有预算；32会话、72更新机会、73QA每组。
从公开模板`configs/milai-unified-prefix8-v2.json`复制本地配置，只声明五arms与本次普通
版本／运行标识；服务及数据路径仍按本地环境保存，实际配置保持ignored。
CLI沿用`tools/run_edit_suite.py CONFIG NEW_OUTPUT --benchmark halumem --phase predict`，
预测完整闭合后同配置、同输出`--phase score`，不重新运行Writer／Reader／encoder。

本快照B0维护3／32、预测3／32、16个生成响应、17个编码响应；无B0预测终态或suite终态，
其余四组未开始，不能记零分。Root仅已读首两会话6个完整答复，未评分。本阶段Judge0。
启动前闭合账本42980请求／170783228known／170974716charged／embedding1275643／
unknown5；本快照42997请求／170983787known／171355536charged／embedding1282888／
unknown6含一个在途reservation，不是新增已闭合失败。limits未改、预算未重置。

原完整目标继续：当前五组预测与评分、同版长历史65／277、native32／drift／recovery、
必要入口与认知消融及固定更紧预算、最终冻结后16保留用户、LongMemEval28题／1354历史及
原10完整答案、RawRAG／RollingSummary／实际A-MEM callback、最终同候选Host135case／
192message及新增实质故事、六项最终交付尚未完成。16保留用户未用于开发；无最终方法
选择、稳定优势或独立确认，single_verdict_v1未准入，Product仍为NO_GO。

## 14:16 UTC：PR91合并，真实历史答复错误与配对分支失败已保留

本节固定于2026-10-07 14:16 UTC／北京时间22:16。报告版本以本节所在提交为准；
最新实现为`4b3501b`，普通历史入口`bd4bf51`来自D的`fd69ae8`，说明压缩`8cc4def`
来自`3a66662`。下面两条真实运行都冻结`962beaa`（实现`4a2d7ba`），没有采用这些新修复。

**PR83至91已合并。**[PR91](https://github.com/minguselandy/MiLAi/pull/91)实际头962beaa的
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37627853728)与
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37626176881)成功，Full21/21；
13:41:39普通merge为main`2cf0c739`。其
[main push检查](https://github.com/minguselandy/MiLAi/actions/runs/37630543098)也成功，
integration快进、干净，源码树与已检查PR头相同。14:03只读观察时open PR为空。
本次新4b源码自己的远端CI尚未请求，不能借962的CI证明其通过。

**962日期复测执行闭合，历史答复仍错。**同一已曝光开发故事采用新独立空库，
13:45:19启动、13:48:25退出0，4次COMPLETED、3次实际维护提交r1／r2／r3；
不是4条语义通过。r1的原内容与条件都实际带有assertion.applicability，原User来源、
报告时刻和名义日历保留；物理时区未知。r2保留原两unit并追加两unit的一日绿色例外，
其限定仅为文字，没有新typed applicability；r3撤销例外，原两unit和关系值不变。

Root读完4个完整自然答案，并只读核对真实SQLite：历史r1／r2／r3逐值等于各次保存结果，
当前为r3，只读消息没有维护／业务调用且记录不变。最后答复正确识别查询日在原区间外，
却称过去只实际保存了蓝色，未读取已提交r2中的绿色例外。Agent已有历史工具但未调用，
原Source请求不能替代已提交修订；这是当前撤销与过去保存内容的混淆。前三次自然答复
与对应实际保存／撤销相符，仍有暴露内部operation／revision名称的表达限制。
17生成响应／150,654known、17编码响应／720token、Judge0、新unknown0。
仅Agent消息可核对4stop＋3tool_calls，不把这一子集说成全部生成均stop。

**首次真实recipe比较在第三case提交后观察失败。**仍从原B0实际旧库复制，
14:05:28启动、14:07:32退出1。single_pass原3真实空提案／无修改，原6新建1事项；
原7实际修订2事项后，service.records遇到V13_CANDIDATE_HANDLE_COLLISION。
原准备恢复了旧值／历史，但复制库还含旧轨迹的未来读取授权；新分支同一修订号的
真实支持与该未来句柄冲突。已保存2个完整case行，第三个部分case的实际提交留在DB，
0自然答案；原4及extract_then_edit未运行，不能记零分或做流程优势结论。
3生成stop／71,290known、8编码／12,755token、Judge0、新unknown0；首次HTTP、失败、
DB和原准备输入保留，未重试未知请求。新4b驱动只在各独立runtime副本移除超出实际
before修订或不存在事项的读取授权，保留实际过去授权；维护结果先保存，再做after观察。
新完整比较实际调用仍0，须新源码及新输出，不覆盖这条失败轨迹。

**普通读取接通实际保存历史。**当前record片段增加实际committed_at及一次有界
stored_history入口，最多显示既有6个修订ID、真实总数／遗漏数量、索引游标和既有工具参数。
历史正文仍经原history／exact-revision工具按额度分页读取，标为historical_exact_revision；
提交钟不代替报告或生效时刻，索引cursor不冒充正文cursor。所有者、可见性、显式遗忘和
既有读取额度保持。最初新增说明使原2600额度的首正文页2827而为空；仅压缩说明后2518，
原100字符正文及55个遗漏单元仍送达，原预算／正文／测试不改。

Root完整受影响检查247通过（两份adapter218、runner29），7文件Ruff、三个源码／示例
Python3.11mypy、包DAG和工具依赖边界通过；重开SQLite的保存→例外→撤销→普通历史读取
及显式遗忘示例通过，均0真实HTTP。驱动单独严格mypy仍有5项既有错误，已对照父main2cf
相同的缺第三方stub／未标注调用／Optional访问／冗余cast；不宣称该驱动全量类型通过。
实际Agent选择工具和正确回答仍须新真实验证，这些工程检查不表示方法效果。

两条新运行合计20生成响应／221,944known、25编码／13,475token；分别与连续账本差额
一致，不重复计入旧402、Native8或34fa结果。14:07闭合账本42,928生成请求、known170,108,073、
charged170,299,561、embedding1,250,904、unknown5，limits未改变，旧397未重试。
此固定观察时真实资源已释放；未来进程以实际PID和终态检查为准。原同版五方法、65／277
连续历史、native／drift／消融／更紧预算、最终冻结后16保留用户、外部、同候选Host135／192
及冻结后新故事和六交付仍未完成；16未用于开发，无最终候选，Product NO_GO。

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
