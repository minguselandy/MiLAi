# Unified V8/V9 U2 独立比较协议

状态：**ENGINEERING_READY；PENDING_PUBLICATION_AND_PILOT_FREEZE；NOT_RUN**。依据完整统一Goal推进U2，工程检查不能替代真实执行freeze或方法效果。
[U1原生切片](MILAI_UNIFIED_U1_NATIVE_RESULTS_20260929.md)已经发布为`74330412c938e7b8df152e472354554bccbb7c09`。
本阶段实现与必要局部检查已经完成；源码发布后先冻结已曝光pilot，再按实际接线结果冻结独立比较。Root负责协议、输入、全部真实串行调用、评分和连续账本；
Sol xhigh是唯一源码负责人，Luna high负责Git与实际缺少的依赖资源。Product仍NO_GO，研究目标NOT_ACHIEVED。

## 范围与曝光

MemSyco使用[既定选择](../data/manifests/unified-v8-v9-memsyco-subsets-20260928.json)的development：三任务各20题，共60题、54统计来源组。
离线身份核对发现60份不同dialogue SHA，因此当前选集没有跨题exact-history复用机会。source group用于隔离曝光和统计聚类，不能据此合并owner或不同历史。
不修改原题、gold、rubric或完整历史；无gold的TaskInput/ArchiveInput进入运行器，含gold原行只由prepare/离线Root scorer按既有边界处理，query运行不能再解析它们。

MERIT使用[既定选择规则](../data/manifests/unified-v8-v9-merit-selection-policy-20260928.json)的development：三域easy/hard各3条完整arc，共18 arcs、90 episodes，base seeds11—28。
规则已在看到这些运行结果之前固定；完整arc/world将在方法冻结后用官方生成器生成、运行官方leak check并保存哈希。
不按模型答案过滤或替换，不截掉难episode/后续依赖，也不把episode当作独立arc。
新种子仍来自同一公开生成器/任务模板，不能称独立任务家族。U1为已曝光smoke，U2尚未有模型结果；最终措辞按实际曝光记录限定。

第一张主表每benchmark五个实际方法：FullHistory/RawDialogue、StrongRawRAG、SlidingWindow＋真实LLM摘要、ordinary/MiLAi合并、真实Mem0。
当前ordinary与MiLAi候选没有独立启用的研究模块，不强凑两列。第二外部SimpleMem或A-MEM待首表可运行后接入，另冻结其实际合同。
不把所有方法再扩成一张MemSyco Agent查询矩阵。U1该扩展的四次无检索失败保留。

## 共同权限与任务执行

MemSyco所有后端给同一官方reader供材，保留原格式、固定日期2025-06-01、空extra instruction与同一Qwen设置。
归档形成只接原role/content/time/source/owner及有序完整历史，不接question、answer或gold；归档不是新实时业务授权。
reader查询是当前原问题，不改写成带标准答案的检索词。构建后查询只读，不把该题生成答案回写成下一题的记忆。

U2 MERIT五臂共用现有`_run_merit_arc`、LangGraph Agent、真实ToolNode、public checkpoint与原生world/tools/checker。
每个公开用户消息按原顺序进入；检索只能使用当时已出现的当前消息和合法过去，不使用官方旧`memory.read`入口提前拼入的同episode未来消息。
当前完整ReAct前缀始终保留，工具续接不重复自动检索或摘要，实际工具调用/回执与当前message关联。
全历史和ordinary拥有同一合法owner档案；其他方法可通过相同只读历史工具访问其合法来源，任何实际绕过自动投影的原文读取都单列记录。
ordinary的管理、检索、精确读取仍通过真实MCP与strict Store；baseline本地BM25/摘要计算不能冒称Host发起了MCP调用。
FullHistory、summary、RawRAG向Host提供原生业务工具和真实MCP `read_history`，不暴露指向空ordinary Store的search/exact端点。
Mem0提供自己的实际search及同一历史读取；ordinary保留strict CRUD/search/exact及历史读取。自动取材与Host工具选择分别记录。
该合同在真实调用前确定：保留空目录虽能接近统一工具token，却会把该方法已有投影与一个不承载其记忆的搜索端点混淆；因此按实际能力公开目录。

U1官方`run_episode`的NoMemory/递归FullReplay参考实现不改。新共同graph是显式系统比较配方，不能把旧原生回放改名为强FullHistory，
也不把新的调度/工具目录/系统说明差异隐藏成纯组件单变量实验。所有臂从隔离的相同初始world开始，后续各自真实动作可以产生不同反馈。

## 方法合同

| 方法 | 实际处理 | 限制与费用 |
| --- | --- | --- |
| FullHistory / RawDialogue | 全部合法历史，每条源一次；不把先前model material或`memory shown`递归写回档案 | 超完整请求容量就报告失败，不静默截成窗口 |
| Window summary | 最近2个完整completed turns＋完整当前前缀；更旧部分由真实LLM以prior summary＋新移出前缀更新 | 更新输出2048 tokens、正文上限16000字符；失败/fallback单列，不用字符截断冒充摘要 |
| StrongRawRAG | 原文2048字符块、步长1792；真实BM25(k1=1.2,b=.75)＋同bge-m3 dense，RRF60，固定顺序打破并列，top10 | 完整chunk按序装入16000字符材料预算，记录省略；初建/增量/query embedding全部收费；无reranker |
| Ordinary/MiLAi | 现有strict CRUD/MCP＋完整合法历史＋实际ordinary内容，研究性State/Attention关闭 | 可合法零写；必须报告记录数、原文交付和实际维护，不能凭答对证明形成 |
| Mem0 OSS pinned | 实际`f8082a7345dadd9e042ebbc40b57b1498c8f6d63` SDK，infer=True的add/search与持久ID；top20/threshold0.1/rerank=False | 该pin自动抽取为ADD-only，不证明同ID更新；完整内部LLM/embedding/空提取/失败计费 |

MERIT摘要每个公开消息最多一次，只在新完成前缀离开窗口且尚未覆盖时更新；成功才提交summary/cursor。
已知模型timeout/truncation/无效输出将标记degraded，并退回完整合法原历史，再走同一最终容量检查；Store/权限错误不能吞掉。
MemSyco以完整原有role回合构造归档，窗口外前缀按固定顺序做真实summary更新；批次装载规则将随实现显式冻结，不从中挑选gold相关片段。
不完整历史前缀按原样保留，不能伪装为已完成摘要覆盖。工具续接复用该公开消息已经选择的材料。

Mem0的MemSyco形成输入为完整归档、不含问题。MERIT在公开回合闭合后ADD完整标注的过去回合数据，包括实际工具参数/结果和来源，
不把工具回执伪装成用户新命令。原v26的user/final-assistant入口及身份保留；新benchmark归档表示单列。
SDK忽略某些来源与适配器没有交付来源是两种不同失败，需核对实际ADD请求和读回结果。未知ADD结果保留部分状态，不自动再ADD。
不承诺跨Qdrant/SQLite事务或通用exactly-once。
该源码的`ADDITIVE_EXTRACTION_PROMPT`产生ADD-only抽取；保留这一真实系统合同，不另加人工update/delete来冒充原生自动维护。

## 构建、缓存与公开消息容量

prepare输出脱敏tasks、形成unit和查询→unit引用。缓存键包含method/code/model/config/owner/source/完整有序历史身份，不含question/answer/gold。
同组不同历史、同文本不同owner/source不能命中。各unit构建只尝试一次，保留STARTED/COMPLETED/FAILED/unknown和实际snapshot/hash。
query只引用已完成的正确unit；失败形成仍保留计划查询机会与分母，不伪造空成功或静默换题。RawDialogue机械归档没有模型形成费用。

单个MERIT公开消息最多12次generation，包含任务Host续接、摘要及该回合同步Mem0摄取内部LLM请求。
同一真实RunBudget/串行客户端收费，不能复制旧内存账本覆盖新增成本，也不能借用未生效的历史control字段扩大12次容量。
若业务已完成而维护中容量耗尽，保留真实world/回答、部分记忆、已付费用及maintenance incomplete/unknown；不自动重放副作用。
MemSyco归档build不是新实时用户消息：每个完整summary批一次尝试，ordinary形成最多12次，Mem0每archive ADD内部最多12次generation。
SDK若吞掉容量异常又返回部分结果，适配层仍根据实际异常/拒绝记录标明partial或incomplete；未发出的请求不捏造usage，已发生的费用/副作用保留。
reader/业务Host仍max_tokens4096，真实模型HTTP并发1。

共同模型延用Qwen3.6-35B-A3B-FP8@7862、temperature0、thinking=false、上下文65536；embedding为bge-m3@7861、1024维。
完整请求含schema、工具目录、历史/材料、输出与512 safety后检查容量。本阶段不调整服务、下载新模型或部署第二家族。
复用现有foundation及external环境，最终prepare记录实际解释器、全部包、模型小资产、源码/参数/tool catalog哈希。
Root已完成[external环境只读身份核对](../data/manifests/unified-v8-v9-u2-external-environment-20260929.json)：
现Python3.11.13环境中的149个Mem0源码/JSON文件与固定commit一致，记录139个包；20个BM25资产及26个spaCy资产与历史锁一致。
这只证明现有依赖身份，不代替Sol的真实SDK/MockHTTP路径检查；没有初始化SDK、下载、安装或模型调用。
历史v26的Python3.12.11回执不冒充本次实际解释器身份。

## 实施检查、pilot与正式冻结

Sol先完成集成，只运行改动需要的机械窄检查：未来消息隔离；完整历史/当前前缀无重复；两次真实MockHTTP摘要更新与失败cursor；
BM25与dense各自影响排序；exact-history缓存和不同owner/source隔离；同reader字节；shared预算/调用容量；原生Mem0实际SDK配临时Qdrant/SQLite与MockHTTP。
实际SDK检查不等同于真实模型效果。缺失依赖不能skip冒充通过；已有已通过且未变检查不为发布重跑。只有包装/入口/依赖变更才做必要构建。

源码、方法与工程回执发布后，Root先对新增路径用已曝光U1输入做最小真实pilot；不启动完整development矩阵来调试未完成代码。
已前瞻选择[一题MemSyco](../data/manifests/unified-v8-v9-u2-pilot-memsyco-selection-20260929.json)和[原`arc5-000`完整MERIT arc](../data/manifests/unified-v8-v9-u2-pilot-merit-selection-20260929.json)，
均为各自U1清单首项；[pilot合同](../data/diagnostics/unified-v8-v9-u2/pilot-contract.json)固定每benchmark五方法和构建/查询顺序。
共10个Host jobs，MERIT每方法保留5 episodes/6公开消息。pilot不另发MemSyco Judge来把模型答对率作为工程门槛；正式U2的完整原生评分仍必须执行。
pilot的具体方法/输入/顺序/预算另冻，正常低分不成为工程失败。真实bug需要记录受影响范围、至少两种解释、最小修复与新方法身份，
不能只重跑候选失败题。修复后再冻结U2完整输入、源码、参数、scorer、组顺序和状态隔离，才运行独立比较。
当前具体运行身份尚未冻结；工程检查使用MockHTTP与本地临时Store，不是模型实验。最终10份零模型prepare全部成功，
包括MemSyco五臂各1题/1历史/0复用，以及MERIT五臂的实际工具目录。首次失败及修复均留存，未新增依赖、包装配置或独立CLI，未做额外构建。
详见[工程回执](../data/manifests/unified-v8-v9-u2-engineering-checks-20260929.json)：26个去重目标通过、0skip；
Root核对15个工程文件、57个检查制品及10份prepare源码身份，无重复测试或真实调用。
本协议及参数随源码发布；实际执行freeze另绑定发布提交、全部输入字节、命令顺序、服务与账本。

入口继续使用`tools/run_unified_benchmarks.py`。共同参数为`--benchmark`、`--arm`、`--selection`、`--group`、
`--config`、`--run`、`--runtime-root`；先`prepare --output <receipt>`。
MemSyco再按prepare生成的history顺序调用`run-history --history <history_id> --prepared <receipt> --output <build_result>`，
查询用`run-job --job <job_id> --prepared <receipt> --output <query_result>`；MERIT只有完整arc的`run-job`。
pilot每方法只有一个history，顺序为构建后查询；development按每方法全部history构建后、全部查询执行，方法间不复用状态。
Mem0使用现external解释器，其余使用foundation；实际解释器路径、离线环境、输入字节和每次完整命令进入执行freeze/回执。
所有MERIT臂及MemSyco ordinary需要Root从原树ignored文件注入私密DSN；值不进入命令、日志或Git。
prepare无模型调用；上述命令合同不替代源码发布后的具体执行freeze。

## 评分、成本、统计与Gate

MemSyco所有方法回答先冻结，再由Root按同一原生rubric单次评分；沿用本地同族Qwen Judge及1024输出，偏差和解析未知明确报告。
MERIT主分为原生world/checker，保留pre_satisfied、dependent、整arc、Host与维护状态；严格文本/参数原分不改。
不合并不同benchmark为无定义总准确率。分类/域/难度/长度、实际分母与失败首断点分别报告；不把未运行或不可评分从计划分母抹去。
对比较差异按MemSyco来源组和MERIT arc做配对/聚类不确定性分析，具体统计程序在回答前冻结；不凭建议样本量声称统计功效。
拟定[评分及统计合同](../data/diagnostics/unified-v8-v9-u2/scoring-contract.json)：FullHistory/RawDialogue作参照，配对cluster bootstrap 10,000次、seed20260929、95%百分位区间；
MemSyco按三任务分别统计，MERIT按episode/dependent/整arc分别统计。任何配对端点有不可评分项时保留原分母及成功率上下界、该端点CI记不可用，不做静默complete-case删题。

连续预算权威仍为原树`artifacts/ser-v20/budget.json`，U1结束为3627 generation calls/4,825,845 generation tokens/24,962 embedding tokens。
全部构建、滚动更新、检索、维护、任务Host、Judge、失败、空提取与观察开销继续追加；实际调用总数/输入输出tokens、冷建和warm增量分列。
缓存仅按真实合法使用次数摊销；本development 60份历史预期0跨题复用，不从54组推算节省。MCP inclusive时延不与底层重复相加，未计量的物理I/O/GPU小时/净Store CPU保持unknown。

U2目标为G2可解释比较，不预设候选胜出。参数精确性、写入、恢复或取材出现实际问题时分别判断U3/U4条件；不把所有失败归于Memory Store。
只有真实信号与已冻结方法才能支持U5独立确认/自然长程，第二模型资源仍需实际核对。最终U6必须覆盖全部适用需求、未触发原因、成本和发布证据；
U2主表也不是整个Goal的自动结束点。
