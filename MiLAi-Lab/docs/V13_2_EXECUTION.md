# v13.2 执行记录

2026-10-01。状态 **ACTIVE**：按最新用户指令，GitHub提交核对完成后继续原完整计划。遇到失败检索相关设计方法、反思改进，保持既定设计方向与方法通用性、泛化性。D0–D5及条件门禁仍未全部完成。

[PR #79](https://github.com/minguselandy/MiLAi/pull/79)为草稿；主快照`48b93b3`和独立WIP`795a769`已推送并逐SHA核对。此前[暂停快照](V13_2_PAUSE_STATUS_20261001.md)作为历史边界保留；[发布与恢复记录](../data/manifests/v13-2-publication-and-resume-20261001.json)明确恢复授权，不改写已冻结结果。

用户明确要求详细阅读并执行[589行原计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_2.md)。
原文SHA256为 `84c89a3e8dbb1f23ad4478e8a809f264c76c430b537b0ea1501671230681a79a`，
字节未改；DESIGN_ONLY保留为原设计状态，不覆盖当前执行授权。

远端main已fetch并用ls-remote独立核对为 `95bf708bfd8aac9f7855485166e3bf739928b949`。
新分支为 `feat/lab-evidence-incremental-v13-2-20261001`，工作树为
`/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-2`。
用户入口主工作树及v13.1未提交改动未动。[入口冻结](../data/manifests/v13-2-entry-freeze.json)
记录原计划、旧cohort、源码差异和真实账本。回滚基线是95bf708；本次按用户暂停指令提交独立分支和草稿PR，不合并main。

[完整48项验收映射](../data/manifests/v13-2-requirements.json)覆盖D0–D5、E0–E4、恢复、
预算、来源分组、正式统计、迁移、长程及条件消融。旧v13.1 P0–P8 requirements和实验结论
原样保留；新增amendment映射只修订实施路径，不把未证明项改为通过。

## 已取得的直接证据

[D0结果](V13_2_D0_PRIOR_COHORT.md)重新读取并核对139份旧回执和139份HTTP trace，
保留101回答，复核全部30完整轨迹。原60计划仍是45尝试、30完整、15中断、15未运行。
原四条反例保留，另确认一次初始操作与后续UNKNOWN的错误归属，并定位Field原卡修订失败、
额外CREATE和notes误解。Root复核只作事后开发诊断，独立语义评分仍未完成。

旧cohort逐请求费用对上543 generation／2,675,299 tokens与295 embedding／83,740 tokens。
其中126次writer／619,934 tokens。160次紧接记忆拒绝的请求／951,349 tokens是重叠子集，
不额外计费、不称全部为可消除浪费。方法、实际源、首个记忆拒绝、首个终止和原回执hash逐项留存。

D1已实现opt-in `memory_mutation_contract='event_bound_v1'`：可信runner绑定实际当前事件，
多事件必须明确选来源；user/tool/实际最终assistant保持角色与原hash，助手建议不能冒充用户决定。
search/read返回持久化候选句柄，绑定owner、record、读时revision和支持源hash；提交再核对，
交错更新返回冲突。单个相似结果不自动选择，提交前不临时填最新版本。旧默认为legacy。

D1来源/候选/交错更新/重开/实际runner脚本17项新窄测试通过；旧service/P5组87项、
旧prepare/schema/循环子集20项通过。真实安装Mem0 Memory SDK的关闭前采集、错误关闭、
独立重开及observed_events_v1载体4项通过，另实际update/get/history重开1项通过。
这些SDK检查禁止网络、使用有限向量/离线provider，只证明工程合同，不证明原生抽取或模型质量。
阶段记录在ignored `artifacts/v13-2-d1/source-checks.json`；每命令执行hash当时未保存，
其末尾source snapshot不能冒称所有检查共同使用的执行SHA。D2变更检查已逐命令保存执行前后身份及原日志。

D2确定性投影工程阶段已通过100项相关测试、四文件mypy、affected ruff和package边界。
[阶段验收](../data/manifests/v13-2-d2-observation-acceptance.json)记录各命令执行前后源码/测试身份与原stdout hash。
同源多对象/多字段、缺失与显式清除、迟到/不可比/同版本冲突、真实预订partial和文稿版本域通过。
实际持久Store部分写入失败保持pending，独立重开只重放投影；此证据不替代真实进程W2 crash或模型E1。

## 来源组与后续研究边界

[来源amendment](../data/manifests/v13-2-source-group-amendment.json)在任何新pilot内容读取前
从既有metadata-only catalog导出431个组件和成员图，原曝光及117条新pilot预留成员继续排除，
MERIT旧0–64及预留65–82不洗回未见集。没有回收预留样本，也没有打开新问题或gold。

| 任务 | 未预留行 | 独立组件 |
| --- | ---: | ---: |
| Scope | 250 | 250 |
| Valid | 7 | 2 |
| Personalized | 54 | 53 |

Valid七行只有两组件，不能支撑充分独立的更新验证或5个百分点非劣声明。
新pilot和正式规模尚未选择，须按真实独立组及pilot配对变异事前冻结，不以开发集替代正式结果。
独立Judge和第二模型家族仍不可用，按原计划继续独立工作；不默认下载、购买或部署替代服务。
已生成固定rubric、方法显式标签移除且顺序固定的审查包，但尚无独立审查结果。

## 当前工作与剩余门禁

D2工程阶段已接受；D3有界预取、source→record反链、小patch、批量语义边界和Host提交去重已通过[限定工程门禁](../data/manifests/v13-2-d3-engineering-acceptance.json)。54项reader/来源/实际SIGKILL检查通过；一个内部schema断言首次失败保留，改用真实公开tool_call_schema后的单项通过。此前137项affected属于较早API身份，不冒称当前整套共同SHA。普通recall_context与显式追加search_memory(query)已分开，后者按实际参数检索并收费。
[R0运行身份](../data/manifests/v13-2-small-development-runtime.json)在HTTP前冻结208源码/CLI文件、8配置、工具目录、rubric、环境、模型route与连续账本，执行源码为bb1b9a7；每回合普通2048/6、批量最多6动作、默认修复0。冻结时新调用0是准备阶段状态，R0现在已结束，不能继续把该快照写成未运行。源码修复后不再执行原R0根目录。

| R0开发段 | 实际执行 | Root事后诊断 |
| --- | --- | --- |
| [E0 normal24](../data/manifests/v13-2-e0-normal-results.json) | 24/24完整、48实际HTTP最终回答 | 18 PASS、5 FAIL、1 UNKNOWN；22/24门槛未通过 |
| [E1固定流](../data/manifests/v13-2-e1-development-results.json) | 16边界完整；Field8次形成生成、derived0 | 实际字段形成与来源留存；不算自由Host样本 |
| E1自由Host | 8/8完整、16实际HTTP最终回答 | 当前world/回答8通过；预取4条历史送达，自主4条未检索，原操作归属未证明 |
| [E2身份](../data/manifests/v13-2-e2-development-results.json) | 15/15尝试、13完整、2中断；40完整消息、2中断、3未运行 | 11 PASS、2 FAIL、2 INTERRUPTED；14适格原卡中11条更正边界支持完整修订 |

E0 update-1两次把source_refs嵌入patch被拒后CREATE另卡，原咖啡卡仍r1；scope-1后置writer把问题存为长期个人素食偏好。update-2/3/4虽把同ID原卡写到r2，新主张却只引用旧偏好。来源复核纠正了尚未提交的21 PASS草稿，旧草稿hash保存在private审计中；结构修订和完整语义修复分别报告，两旧update修复门禁未通过。scope-4相对时间改述仍UNKNOWN。

E2两个上限中断的首断点分别为非业务字段误用及猜造source_ref；全部12次请求、原历史和NOT_RUN留存。反链+patch的update-3也仅引用旧英里来源；旧target-query项目例最终遗漏实际存在的原格式历史。另有六个不受所引旧陈述支持的中间r2留在history，不被后置修订抹掉。没有以13完整计13成功，当前开发不能证明方法优势。

E0真实独立SQLite Store SDK重开24库；E1/E2另外只读重开23库、读取455原始items，均与最后实际回执相符，数据库SHA前后相同、0模型请求、0记忆mutation。持久化一致并非语义正确。所有104自由Host最终回答均链接实际HTTP原回包；Root审查不是独立Judge。collector对篡改、缺失、畸形回包保持未验证，不自动补答案。

负结果后的一般修复闭合opt-in公开patch/profile字段schema，并要求新revision至少关联当前可信boundary的实际来源；历史支持可共存，no_change不新写版本。32项窄检查、两文件mypy、ruff及两边界通过，四组legacy公共catalog逐字节相同。完整参数schema实际进入Host提示；现有generation_only grammar仍仅约束action外壳。当前来源成员资格不验证文字含义，f5a15c7未改变CREATE。证据见[修复工程验收](../data/manifests/v13-2-schema-source-acceptance.json)。

[R1运行身份](../data/manifests/v13-2-e0-r1-runtime.json)独立冻结完整24 E0，沿用原rubric，在writer加入Host已有的问题/相对时间规则，保持12生成admissions、2048/6与repair0。24轨迹、48消息均完成；[R1结果](../data/manifests/v13-2-e0-r1-results.json)为20 PASS、4 FAIL、0 UNKNOWN，22/24及两个旧更新修复门禁仍未通过。四个更新例各有一张非意图偏好副本；其中语言/会议原卡后来确实修订并关联当前更正，但不能掩掉Host先前另建的旧源副本。语言最终遗漏旧英文，单位原卡仍r1，饮品最终倒置当前/以前。scope两项此次通过，不与R0拼成最佳结果。另一张重复工具观察语义卡单列，真实业务效果仍仅一次。

R1实际Host六次来源拒绝、writer十三次拒绝保留；26次writer形成生成不能当26次维护成功。24库又以只读SQLite Store SDK读取418 items，最后回执与head相符、DB字节不变、0请求/0mutation。此前仅验证每份ordinary packet的metadata在2048内；同一HTTP若同时带System与旧recall ToolMessage材料，尚未证明合计2048，重复输入已计费。下一接口修复必须把当前索引与唯一ordinary材料共同计预算。

只读源码/实际wire复核确认：Host的当前user source_ref只在capture文件和trace，HumanMessage正文未含ID，历史reader明确排除当前源；追加同文本查询也不能发现该ref。业务工具回执已交付实际tool ref，writer的actual_events也已含当前ref，不能把writer语义误归属归咎于这个Host缺口。现在补公开只读trusted来源索引及新建语义卡的当前边界成员检查，原输入/角色/hash不改、无目标强选/语义修正。下一cohort在READY后另冻结；D4仍未准入。
当前接口修复已提交fd1ce596并通过[限定工程验收](../data/manifests/v13-2-source-index-acceptance.json)：首输入实际来源索引、业务batch刷新、同epoch分页/空binding、CREATE当前成员guard及逐消息位置的ordinary引用投影。最终六项窄测试、mypy、ruff、八原配置真实catalog/decoder与实际Qwen tokenizer模拟wire通过；此前47项属于另一个position修复前SHA，未冒称同一执行身份。Root最终两项边界及独立token复算通过；初始配置枚举失败和hash序列化误用保留。2048覆盖当前index、一份System ordinary包及每条当前recall引用正文；过去回合不同packet、协议schema、显式追加和真实业务材料另计完整实际输入费用。R2仅改实验身份标签，保留R1提示/12admissions/repair0。
[R2运行身份](../data/manifests/v13-2-e0-r2-runtime.json)在HTTP前另冻结208源码/CLI、同一原24/48输入、公开catalog/prompt、Rootprepare与串行parent、原rubric/collector和连续账本；执行源码fd1ce596、紧凑map SHA906d86f4。prepare禁止socket连接，实际生成/嵌入0，账本与R1末相同。R2现在全部24轨迹/48消息完成，48最终回答均链接实际HTTP；[逐例结果](../data/manifests/v13-2-e0-r2-results.json)为19 PASS、3 FAIL、2 UNKNOWN，22/24门槛及两个旧更新完整修复门禁仍未通过。R0/R1/R2独立保留，不拼接最佳结果，原运行根目录不再执行。

R2四个更新都在更正边界修订同ID原卡、引用实际当前更正、保留真实历史且未另建偏好副本。但语言例最终遗漏旧英文，writer进一步把可见材料缺失写入r3；会议例最终遗漏旧上午。项目预算例把未提供私人预算改述并持久化成个人status=not_set，仅引用当前问题，来源不支持这个缺失主张。单位例核心英里/公里及原卡维护正确，附带当前源描述仍有歧义；一个对象例业务仅一次且真实label_status=created，但最终把原操作status=label_created称作标签状态。两条按全部主张/回执忠实性规则记UNKNOWN，不计成功。另一些提问回合修订丢掉直接旧叶子引用，实际历史仍保留；这些来源完整性限制单列，不以机械成员检查冒称语义验证。

Root逐实际wire复算104次Host请求：当前索引、一份ordinary材料及全部当前recall引用正文共同计预算，最大1975 tokens、至多6条；实际当前user ref/role/hash与真实capture匹配。此界限不包括完整HTTP的schema、业务回执、显式追加读取及旧回合packet，其费用完整保留。独立只读SQLite Store SDK又重开24库、读取407 items，head/history与最后回执相符、DB字节不变、0请求/0mutation。维护为23 skipped_host_committed、13 committed、3 no_change、9 pending；六次writer拒绝均留存。

只读源码审计发现后续缺口：普通record只呈现当前revision；source回链内部保存matched revisions，公开结果却只返回当前卡。已有read_memory(id,revision)可读确切旧版，但没有实际版本枚举或明确省略入口。计划5.2/5.3及6.1要求的有界历史可发现性尚不完整；候选修复须只呈现已选卡的实际版本/匹配版本metadata、保留原预算与CAS，不用语言或案例选版本。单次writer目前只开放写工具，索引本身不会给它旧正文，也不证明上述语义错误会消失。固定fd1执行身份的[100/1k/10k Source规模基线](V13_2_SOURCE_SCALE_BASELINE.md)已完成三规模七阶段各20次，共420可控性能样本；Source与原账本字节未变、0模型HTTP。缓存仍扫描全bank且随规模明显变慢，保留全部负性能结果；actual SDK/tokenizer但离线向量、10语义卡且无业务对象/操作流，D5-10仅PARTIAL。此基线不证明方法加速或长程语义收益；随后才接受一般历史修复。
历史发现一般修复已在基线报告17d3a8f后由隔离964a53e合入1e329a4，[工程验收](../data/manifests/v13-2-history-discovery-acceptance.json)记录208运行map4fe85502。26 affected含8新历史回归、实际Qwen tokenizer三项模拟交付、四legacy目录/交付/缓存对照、mypy4、ruff5与双boundary通过；Root转入主树后另外保留MockTransport wire并独立复算共同1284/1902、writer候选1900 tokens，两主树边界通过，0真实生成/嵌入与账本不变。初始fixture、CAS seed、lint和真实metadata压力失败分别保留，未冒称同一最终身份。公开菜单最多6个实际版本、来源匹配与本次当前引用分列、stale CAS及coverage/显式补页保持预算；旧正文仅来自真实已选匹配/record快照，索引排名未改、语义仍unchecked，不能把工程通过当完整回答修复。R3候选保留R2提示/原24/rubric/12admissions/repair0，仅实验说明标签变；[R3运行身份](../data/manifests/v13-2-e0-r3-runtime.json)已在HTTP前另冻结208/原24/48、实际catalog/prompt、原rubric/collector、Rootprepare/串行parent和原连续账本；prepare禁止socket、0生成/0嵌入，入口与R2末一致。源码继续HOLD，后续完整结果另列，不复跑任何旧根目录。
D4同能力四臂、第二工作流24新冻结开发轨迹与12/24分轨仍未运行。
D5新pilot、正式独立来源比较、公开任务、独立评分、第二家族、统计和完整复现仍未完成。
公开任务另有[只读准入合同](V13_2_PUBLIC_TASK_ADMISSION.md)：MERIT作者固定commit/包闭包核对，已曝光seed0原完整五episode/七消息arc与world字节重建一致，五原生初始checker均false、world未变、0新arc/0业务/0模型请求。此限定复现不准入新任务，旧及预留seeds继续排除，D5-04仅PARTIAL。
相关机制只有满足原门禁才消融或扩大；负结果要求追首断点/一般修复，不能删失败或补答案。
[开发评分标准](../data/diagnostics/v13-2-small-development-rubric.json)已在新模型输出前固定；
[配对统计草案](../data/manifests/v13-2-statistical-design.json)固定主要比较、5pp界、依赖聚类和缺失上下界。
最终正式样本数和运行身份须由新pilot精度与实际独立来源事前补齐；该草案不算正式统计完成。
离线统计工具另有[20项合成数值验收](../data/manifests/v13-2-statistical-analysis-acceptance.json)：依赖传递连接、基础任务等权、共同抽样、缺失上下界与独立评分/二元生命周期非劣门禁均通过，CLI和工具边界也通过。实际实验样本与模型HTTP为0；[输入合同](V13_2_STATISTICAL_INPUT.md)要求事前冻结及完整账本分配，工具不能验证评分独立性或来源身份。D5统计仍为PARTIAL，未得出正式非劣结论。

## 账本与验证边界

权威连续账本仍是原checkout `MiLAi-Lab/artifacts/ser-v20/budget.json`。
v13.2入口为7,946 generation／20,341,038 charged generation tokens／717,188 embedding tokens；
生成已知20,310,651，保守未知费用30,387，unknown usage为1；embedding unknown为0。
[历史账本差额审计](../data/manifests/v13-2-historical-ledger-bridge.json)将旧快照到入口的485次生成对到484次有响应请求／4,568,357已知tokens及1次30,387保守未知费用；449次embedding／178,885 tokens也与差额一致。旧文稿44份completed回执是完成消息数，不是完整轨迹数；缺响应请求未推定完成或归零。入口表遗漏的20个源码/config差异已按两个提交的实际字节补齐并保留修订身份。入口hash只对应实验开始前，后续实际调用和快照另列。
[R0新增费用](../data/manifests/v13-2-r0-development-accounting.json)为292次generation／903,698已知tokens与143次embedding／61,122 tokens，逐trace和连续账本完全对上。其中Host237次／722,344 tokens，形成55次／181,354 tokens；新增unknown为0。R0末累计8,238次generation／21,244,736 charged、21,214,349 known、unknown1与embedding778,310、unknown0。
R1另新增124次generation／395,787已知tokens与49次embedding／21,081 tokens；其中Host98次／307,459，writer26次／88,328，全部费用对账。R1末累计8,362次generation／21,640,523 charged、21,610,136 known、unknown1；embedding799,391、unknown0。入口历史保守未知30,387仍留在账本，未宣称成本下降。价格、美元和GPU小时未测。所有新调用、失败、重启、维护及评审继续本账本，真实HTTP串行。
R2另新增129次generation／473,736已知tokens与50次embedding／20,370 tokens；Host104次／385,702，writer25次／88,034，逐trace与账本一致、新unknown0。R2末累计8,491次generation／22,114,259 charged、22,083,872 known、unknown1；embedding819,761、unknown0。R0–R2合计新增545次generation／1,773,221已知tokens与242次embedding／102,573 tokens；历史未知费用未清零，未证明节省成本。

两个D0/source-group分析工具ruff通过，实际tools边界检查通过；现存6项grandfathered依赖未新增。
D1目标static/mypy和package边界通过，未跑全suite、build、模型质量或远端CI。
全部改动属于Lab研究opt-in合同；Product API、权限、Schema和Canonical未改，Product仍NO_GO。
没有把代码存在或局部测试通过表述为方法优势或发布就绪。

## 用户暂停快照（2026-10-01）

用户要求暂停并提交GitHub，覆盖上文执行中的当前工作。R3在暂停前完成全部24轨迹/48消息，48最终回答均链接实际HTTP原回包；[只读收集结果](../data/manifests/v13-2-e0-r3-unscored-results.json)仍为NOT_SCORED，没有R3聚合通过数。完整语义评分、独立评分、只读SDK重开与全部actual-wire预算复核未完成；先前R2门禁未通过，D4/D5未完成，Product仍NO_GO。

R3新增120 generation／462,391已知tokens、49 embedding／20,342 tokens；其中按semantic_boundary分类的writer25次／91,005 tokens，其余95次／371,386 tokens保留collector分类限制。逐trace与原连续账本完全对上，新unknown0。暂停累计8,611 generation／22,576,650 charged、22,546,263 known、unknown1；embedding840,103、unknown0。账本SHA为`9ba23552d639ba4703253c5a1bbb6f8a2501eca3e77cf5fb21a8e4c090b53795`，历史保守未知30,387未清零。

暂停时208份冻结运行源码字节仍与R3一致。隔离性能WIP只有两个未验证源码文件，另存`feat/lab-v13-2-derived-index-cost-20261001`，未进入主执行分支、没有性能收益证据。后续仅保存公开摘要/hash，不提交原始私密回包、数据库或日志。恢复须有新用户指令，原冻结根目录、失败与成本继续保留。

## GitHub提交后恢复（2026-10-01）

主提交与未验证WIP分别推送并核对远端SHA，草稿PR #79创建完成。用户明确要求随后继续实验；Goal已恢复active。首先完成R3全部既有证据审计/评分，失败后查阅原设计与相关原始论文/官方文档，改进实际首断点；保持来源关联、增量维护、确定性投影与有界交付方向，不按案例特判、不泄漏未来问题/评分答案。新修复另验收冻结，旧cohort与否定结果保留，原账本继续。

## R3完整复核与资料保存

[R3完整结果](../data/manifests/v13-2-e0-r3-results.json)为20 PASS、3 FAIL、1 UNKNOWN：语言/会议漏旧值、writer新增错误个人素食；对象2附带发运措辞未被实际合同确认而UNKNOWN。22/24及两旧更新门禁仍未通过。四原卡更正边界同ID r2/真实源/历史无副本通过；七条查询维护直接来源缺口另列，不能把正常任务PASS当完整蕴含验证。Root诊断不是独立Judge，原NOT_SCORED发布快照保留。

另只读实际SQLite SDK重开24库/416items，最后回执一致、数据库hash不变、0mutation。实际95 Host请求的当前索引/唯一ordinary包/当前recall引用共同预算最大2048，48消息实际源role/hash匹配；schema、显式读取、旧packet及业务全文仍独立计完整HTTP费用。六个writer pending、五no_change、十四committed和二十三Host已提交跳过均保留，新增生成/嵌入0，原连续账本不变。

用户要求检索的论文与项目保存：[资料索引与失败反思](V13_2_DESIGN_LITERATURE.md)保存5篇论文、3项目固定源码及1份SDK参考，PDF/HTML/README/LICENSE和完整文件hash在本地ignored资料目录，公开链接/版本/hash进Git。新研究继续追加。改进沿用来源关联、增量维护、确定性投影、有界交付；先区分历史实际交付与消费、当前新增主张与问题触发，不泄漏案例/未来/gold。

## R4通用公开指令诊断事前冻结

[R4设计](../data/manifests/v13-2-e0-r4-design.json)与[运行身份](../data/manifests/v13-2-e0-r4-runtime.json)在真实调用前冻结。仅Host关于selected/omitted及菜单不等于旧正文的解释、writer关于先提取新增主张/仅查询decline/保留真实支持源的说明改变；同样规则前瞻提供基线。两个instruction因素一起变，不宣称单因素表示收益。原208运行源码4fe85502、原24/48、原rubric、12admissions、4096输出、普通2048/6与repair0不变；性能WIP未合入。准备禁socket、0生成/嵌入，连续入口仍R3末9ba23552；单候选完整24另根执行，旧运行全部保留。

## R4完整结果与下一步

[R4完整结果](../data/manifests/v13-2-e0-r4-results.json)：全部24轨迹/48消息完成，实际最终HTTP回答48/48关联；Root完整断言/来源/状态复核为20 PASS、4 FAIL，22/24未通过。饮品回答虽提到咖啡，却附带“以前具体偏好没有记录”的错误断言；会议漏旧上午。团队午餐的Host回答正确，writer仍从问题前提新增长期个人素食；演示的Host回答正确，writer却把“只为这次”扩大成一类特定演示场景。范围失败不能用回答正确掩盖。

四原卡更正边界仍同ID r2、真实来源/历史保留且无偏好副本。语言、单位的Host显式读取实际r1/r2正文后正确回答；语言查询的writer又增r3且只引用当前问题，完整来源语义门禁仍未通过。四更新首包均仅当前正文、五个已选单元被省略；菜单存在仍不等于旧正文送达。维护为24 skipped_host_committed、14 no_change、4 committed和6 pending，新增/修订失败继续保留；不能把双指令调整解释成独立表示收益。逐48份原回执hash复核纠正此前文稿的15次no_change和3次pending表述，原机器结果未改。

只读实际SDK重开24库/407items，最后回执一致、数据库hash不变；107次实际Host请求的普通材料最大2048、候选≤6。离线审计/重开/预算复核生成与嵌入均0，冻结源码及原账本未变。两条对象续接各多一张当前查询状态卡、后续writer重复消费拒绝，实际业务仍各一次预订；记忆副本与业务重复分别记录。

R4新增131 generation／537,169已知tokens，其中Host107／446,255、writer24／90,914；embedding49／20,752，trace与账本完全一致，新unknown0。累计8,742 generation／23,113,819 charged、23,083,432 known、unknown1；embedding860,855、unknown0。R0–R4新增796 generation／2,772,781已知tokens、340 embedding／143,667 tokens，历史未知30,387保留。无独立Judge、美元或GPU测量，无节省成本结论。

失败后重新检索Mem0/Hindsight原论文，并检查已保存固定Mem0源码的事实抽取/维护职责。下一项工程候选只压缩重复发现metadata，让已有选中历史版本/叶子正文在相同2048/6内实际交付；不改排名、阈值、候选选择或用语言关键词特判。与索引存储优化分别冻结/测量，来源角色/hash、读时CAS、当前/历史与省略状态继续保留。既有失败全量保留；D4/D5与完整泛化验收尚未完成。

## 索引存储独立工程验收与性能冻结

R4全部审计结束后才合入此前暂停保存的WIP。Root逐hash核对[限定工程验收](../data/manifests/v13-2-derived-index-storage-acceptance.json)的17命令原回执、执行前后208运行文件、日志、测试文件前缀与AST：13项SDK case分批通过，非一次final整文件13PASS；保留E501、无效句点namespace样例和重建时间字段误断言三次失败。Root验收脚本一次误找CLI字段的KeyError也保留，改读实际runtime_sources，未重跑已通过测试。

显式`memory_derived_index_storage=owner_bank_v1`只移动可重建raw_index的公共Store namespace；默认bank_prefix/原排序、选择、scope/来源/读时CAS不变。旧inline仍保留，其扫描成本不会自行消失。此前逻辑SDK counter不作为加速证明。

[同源码性能协议](../data/manifests/v13-2-derived-index-scale-freeze.json)事前冻结100/1000/10000、两存储臂、七阶段各20样本（共840）。每个N通过公共SDK建立并关闭一个合成bank，两臂各复制完全相同SQLite字节、使用相同208运行源码255caa86；只存储开关不同。固定逐臂顺序按N反向，保存wall/CPU/SDK逻辑rows/OS块计数与全部失败；共享机器无空闲/频率/cache控制，只作描述性结果。仍无业务object/operation stream、语义模型与泛化结论，D5-10保持PARTIAL。在隔离性能树执行，材料压缩工程在另一树进行，不修改冻结执行源码。

[阶段结果](V13_2_DERIVED_INDEX_SCALE.md)保留已完成100/1000两臂560/840样本的全部七阶段分布；原seed字节、20个首查询选中身份及7份完成进程回执已核对。10000两臂尚未完成，进程持续运行，未重启或填补样本。缓存扫描成本仍随规模增长，不作一般加速结论。Root离线审计、ruff、mypy单文件与tools边界通过；原账本不变、0生成/嵌入HTTP。

材料压缩多记录工程仍出现旧正文省略，另保存[Arrow官方字典表示参考](V13_2_DESIGN_LITERATURE.md)。总资料现在5篇论文/5项目参考，8份新参考文件hash与28个本地索引链接核查通过。字典只压缩实际重复完整值，表与说明同计2048；不改变检索/选择、scope或来源含义。此工程候选尚未验收，不冒称模型效果。

## 四臂比较的独立只读准备

[共同能力草案](../data/manifests/v13-2-d4-common-capability-draft.json)补齐两个等额候选的事前选择规则：以原六曝光故事的确认clean完整成功数为先，再依次比较native成功、完整arc、实际全部生成/嵌入费用；缺失不增加确认成功，全部原失败和费用保留。两候选选择阶段计划48条，选定24视图复用曝光输出、不是独立验证；12次共同预算另根24。当前没有D4输出，运行仍未准入。

只读固定五个实际源码身份确认：旧ComparisonRuntime每ReAct检索/匹配工具形成，不能改标签当一次回合缓存；旧B6仅raw chunks与receipt projection，B3的summary实现不代表B6+已有语义fallback。Mem0已向Host共享admission传入reserve回调，但新D4的Host/native/summary/writer合计24/12及中断重启持久上限尚需真实工程检查。此准备0模型HTTP，不升级D4状态或清除R4失败。

[R5前瞻设计](../data/manifests/v13-2-e0-r5-design.json)仍为DRAFT_NOT_READY，未冻结运行源码或开始模型HTTP。材料工程的范围已明确包含可逆共享表示与按实际token成本的正文分配；两项联合改变，不能归因纯字节压缩。保留原候选、排名、首次record顺序及2048/6，真实省略与可能少送后续current的取舍另计。原多语种压力失败/断言保留，保持R4两提示不变。Source验收及独立性能的零HTTP账本协议结束后，才另冻原全24/48；旧根目录不再执行。

## SimpleMem-Text独立工程前检

[限定SDK/callback结果](../data/manifests/v13-2-simplemem-contract-preflight.json)在现有固定db80b6a7与原专用环境执行四进程：25条合成提案经公开原生VectorStore持久化，退出后的独立SDK重开读回与退出前一致；wrapper错owner被拒。trace_equal原Source JSON实际进入原生writer请求，0admission形成返回INCOMPLETE而不伪称完成。Native条目不新增source-event/owner/revision/CAS字段。

交替MockTransport Host/native生成在共享12/24上限各自拒绝额外dispatch；一次合成未知响应先留persisted count1，新进程在limit1拒绝重发。37chat/1embedding均为模拟transport，实际实验HTTP/模型样本0、原208源码与连续账本不变。Adapter close本身为pass，独立重开使用前进程退出；不冒称已实现显式native close协议。

25条快照转换material的实际Qwen计数3091，超过共同2048，尚无新共同有界交付层，也未运行付费原生retrieval/模型语义微型。推理环境缺lancedb metadata的首次构造失败保留，随后使用既有专用环境，未安装/升级或改性能环境。D4-07仅PARTIAL，四臂总预算/实际比较仍未准入。[资料索引](V13_2_DESIGN_LITERATURE.md)另保存SimpleMem论文v3与21份固定text/core参考，现6论文/6项目参考。

## 紧凑材料合入验收与R5配置准备

[材料验收](V13_2_COMPACT_MATERIAL.md)和[原始命令索引](../data/manifests/v13-2-compact-material-acceptance.json)记录最终209源码676ad5dc、合入32项/默认双边界26项/ruff5/mypy3及五实际默认字节对照。Root核对原34回执/154产物/12失败、合入10回执/冲突失败及16方法AST，主树转入运行/测试hash一致。三固定压力独立Qwen解码复算2046/2048/2046：送1当前前缀+2完整旧正文，仍omit1当前+2Source；完整Role/Scope/version/hash未改。表示、冗余新正文hash省略及成本分配联合变化，不归因纯压缩。Root两次验收脚本字段假设错误和原脚本保存，修正审计器后通过，没有改运行实现或重标Source失败。

[R5前瞻设计](../data/manifests/v13-2-e0-r5-design.json)已从DRAFT进入ENGINEERING_ACCEPTED_CONFIG_PREPARED_NOT_RUNTIME_FROZEN；[配置](../configs/v13-2-e0-normal-r5.json)只增材料profile和实验说明，R4 Host/writer指令、原24/48、rubric、12admissions/4096输出/2048与6/repair0保持。真实模型HTTP0，账本仍R4末。只有全840隔离性能协议结束并严格审计后才另冻实际运行根目录与模型route；不会执行preview或旧cohort，不升级E0/D4/泛化结果。

R5另外完成主树catalog preview：socket/connect_ex禁止，实际209运行map与验收相同，原24/48及实际目录/prompt均生成，模型/embedding HTTP0，原账本不变。preview专用根目录永不执行，真实运行根、模型route、环境/ledger等仍未冻结，不能将内部input-freeze文件当FROZEN_READY运行准入。

## 700样本阶段审计与R5启动保护

同源码性能第五profile结束，Root原工具核对700/840、8个terminal命令的原日志/源/账本，10000默认存储七阶段全部20样本分布加入[阶段报告](V13_2_DERIVED_INDEX_SCALE.md)。最后owner_bank_v1进程仍活，未混入完成样本、未提前启动R5或重跑旧根目录。

R5实际freeze/串行parent已准备，六项纯合成隔离控制流检查通过：拒绝已有attempt、source/config/runtime字节变动；一个Mock child失败仍留24次各一次结果，child后源变即停止。一次真实prepare脚本在未完成840时按预期拒绝，未创建R5执行root/manifest；0模型HTTP、原账本不变。它们仅验证冻结/首尝试控制流，不是模型样本、完整SDK或共享24/12调用上限验收。

## 四臂实际SDK身份审计与下一有限修复

Source在独立8b38f2d只读树交付49份带完整209源码前后map的查阅/组装回执，Root逐条核对原stdout/stderr、returncode、固定源码与文档身份，并复制240份原证据；两次非零路径定位、嵌入查找错误及四个未封装setup失败均保留各自证据限制。实际模型HTTP、SDK构造及Source测试0，Root原账本SHA仍32265299。

实际Mem0固定pin是f8082a73、安装mem0ai2.1.0；Root另核对六个git对象、安装源码/METADATA/direct_url及148模块hash，保存为独立第七组项目参考，不覆盖94c3fe9论文设计参考。[资料索引](V13_2_DESIGN_LITERATURE.md)及本地54链接可查看原件；622文件的只读存储hash核查通过。

[四臂设计](../data/manifests/v13-2-d4-common-capability-draft.json)仍非运行准入。恢复风险是缺失file/key以Host checkpoint下界代替完整native/summary计数；损坏JSON当前已抛错，未伪称已运行恢复故障。下一步Source仅在新隔离树实施默认关闭的共享admission持久化与fail-closed resume，脚本化四调用路径及12/24检查不作模型样本。当前209源码、R5配置及运行中的性能树保持HOLD，B6摘要/common reader/cache/闭合形成边界/Host写工具策略尚未实施。

## R5实际wire审计准备

Root新增离线实际HTTP审计器，校验真实送达的profile/hash、current index与当前recall引用联合Qwen预算，并把current/history/Source交付及省略与原构造日志的selected inventory、读时version身份对应。既有R4完整48条消息/107实际Host请求校准通过，最大2048；10项原wire/合成篡改控制及三原compact packet解码通过。0新模型HTTP/socket，未得到任何R5包或语义消费结论，SQLite版本重开另验。

首轮Root审计器错误要求截断Source仍有完整原range，八条旧R4消息因此未验证；原脚本/结果/log均保存，修正为实际前缀、相应range终点与完整excerpt hash后通过。没有修改运行实现、旧cohort或Root原评分。具体脚本身份和证据SHA列入[R5事前设计](../data/manifests/v13-2-e0-r5-design.json)，真实运行仍须全840严格审计和新freeze。

## 全840性能测量严格收口

父子实际进程已终止，9条原命令全部returncode0，父日志记录all_profiles_terminal。Root不带allow-partial运行原审计工具，六profile/840样本、三组完全相同seed字节及每组20个首查询selected identity通过。原process-results按hash另留不可变快照；测量前后连续账本SHA均32265299，新增模型/embedding HTTP0。

10k的bank_prefix与owner_bank_v1首查询p50分别116.862秒/57.007秒，缓存35.968秒/17.248秒，dirty40.923秒/17.683秒；全部七阶段和CPU/SDK计数见[完整阶段分布](V13_2_DERIVED_INDEX_SCALE.md)。共有机器、交错工程、固定顺序与无legacy inline的限制保留；绝对成本仍高，D5-10继续PARTIAL，不升级模型/泛化或D4。

这一测量协议已结束，R5可进入fresh route/input/runtime/ledger freeze，再串行执行原24/48。此前preview、历史cohort及性能根不再执行；后续模型费用继续原权威账本，测量的ledger-before/after快照不改。

## R5独立实际运行冻结

[运行身份](../data/manifests/v13-2-e0-r5-runtime.json)已FROZEN_READY：209源码676ad5dc、原24轨迹/48消息、配置compact_v1与bank_prefix、R4两提示/rubric/12admissions/2048与6/repair0均固定，报告冻结提交49a7288与实际Source提交6514012分别记录。现有7860 Qwen和7861 bge-m3两次fresh models GET均200，未部署或换模型。

实际prepare禁止socket/connect_ex并记录0attempts/0生成/0embedding，原连续账本仍32265299。实际新root为`artifacts/v13-2-development-r5/E0-normal-r5`；preview根永不执行。工具目录、环境/SDK、CLI、input/rubric、parent、原账本及全840结果hash固定；新wire审计器及独立decoder另外复制到不可变offline-tool-freeze，旧prepare的f04身份/未完成840拒绝回执保留。下一步单parent按首尝试串行执行24，无重跑/择优拼接；尚无R5质量结论。

## R5完整任务复核与来源语义限制

[R5全部结果](V13_2_E0_R5_RESULTS.md)完成独立24轨迹/48消息，48最终回答关联原HTTP。原冻结rubric的Root完整复核24PASS/0FAIL/0UNKNOWN，正常22门槛限定通过；四原卡更正边界同IDr2/真实源/历史无副本且当前/旧值正确。四查询首个实际2048包均送完整current+完整r1，仍只有截断Source和3个Source省略；不归因纯压缩或升级泛化。

完整来源语义仍未通过：四更新query r3及一张正确个人否定卡只引用当前问题；对象1/4 r2的历史操作措辞只引用新的get_reservation。旧真实叶子/历史仍存，但当前卡直接支持有7处缺口。两旧更新核心限定通过、完整门槛未过；D4仍未准入。25 Host已提交跳过、10 no_change、6 committed、7 pending全部保存，四dict object_ref验证失败与三个查询维护拒绝不补试。

Root后检修正一项实质审计错误：原命令仍指向R4，24库/407items不能作R5证据；原脚本/结果/log/hash完整保留。真正R5只读SDK重开24库/404items最后回执一致/hash不变，95实际Host请求wire联合预算≤2048，源与原账本不变、0新增模型/embedding。首次SyntaxError及此前range假设错误同样保留；未重跑模型根目录。

R5新增118generation/492,678known（Host95/402,845，writer23/89,833）与50embedding/20,507；trace与原账本差额一致，新unknown0。累计8,860generation/23,606,497charged/23,576,110known/unknown1，embedding881,362/unknown0；R0–R5新增914generation/3,265,459known和390embedding/164,174。历史保守未知30,387不清零。最终账本SHA26f46d5f，成本下降、独立评分与泛化未证实。

已重新查阅EAL/Hindsight方法和固定Mem0抽取/NONE源码，原PDF/HTML/项目文件及新失败总结可经资料索引查看。下一步只做通用支持叶子/触发职责与有限共享admission/串行闭包工程；保持设计方向和现有合同，不按问题类型特判、不启新服务或读取新holdout。完整计划仍active。

## 共享额度合入与串行只读审计

[共享admission限定验收](V13_2_SHARED_ADMISSION.md)接受默认关闭durable_shared_v1：Source090901b推送并远端精确核对，Root552e014转入；原15回执、209产物及四失败完整保存。最终33新/17默认检查与六AST/实际默认字节对照通过。主树50相关检查、ruff4/mypy3/package及tools边界通过，前后210源码b010a107/测试/配置均匹配Source最终map。实际配置尚未启用；历史R5仍固定209/676ad5dc，不能重标旧样本。Root发布辅助UTC import/read_files类型错误也保留，修正审计器，没有改运行实现。

[HTTP串行只读验收](V13_2_SERIAL_HTTP_AUDIT.md)核对58查阅尝试、57实际subprocess、1dispatch前helper失败及两非零回执；31文件快照/9installed-git匹配/13AST/354原产物，Root首次KeyError与恢复map来源各自明确。native实例锁覆盖自身callback，当前所有client及跨root ledger没有共同整请求mutex/owner lease。未执行实际并发事故，没有把SDK本地entity检索线程当模型HTTP并行。

22份实际固定SDK/依赖原件及Root补充manifest加入[资料库](V13_2_DESIGN_LITERATURE.md)，现六论文/七项目参考、647文件/56本地链接通过hash核验。以上新增真实模型/embedding HTTP0，连续账本SHA26f46d5f不变；合成测试使用独立局部账本。D4共同reader/cache/形成/B6/Host写策略及HTTP闭包仍未实施，来源语义门槛未通过，Product NO_GO/full plan active。

## 支持来源通用方案的只读验收与隔离实施

[方案](V13_2_DIRECT_SUPPORT_DESIGN.md)区分trusted实际public-turn trigger与model显式支持叶、只允许实际read candidate上整字段严格等值复用、按trigger查Host成功回执，并仅在新profile增加同Source实际string object ID伴随投影。继承旧整版引用不伪造子句归因，改写仍选真实叶；联合cadence/展示变化单列，不禁用query维护、不加语义verifier/案例分支/额外writer，不放宽2048/6或CAS。

Root逐hash核对41索引/39原完整maps/四失败/12快照/11原R5 trace/17请求对并复制262产物；两个恢复回执缺原after/一个也缺before，未知命令参数和误猜路径均留真实来源限制及独立勘误。finite草稿未执行，Root后续missing-file读另留，0新运行/机制测试或SDK构造。全部原R5/source-family与post-R5 admission210身份区分、账本SHA26f46d5f不变。

同一既有Source owner获授权在新direct-support树、87f74c6基线上实施默认关闭profile，原所有树HOLD；Root配置/rubric/实际HTTP仍归Root。尚未接受源码或运行R6，后续须限定工程检查、实际token/wire审计和新的完整冻结；新方法的语义结果与泛化仍未知，完整计划active。

## 新支持来源压力反思与R6事前控制

隔离首组真实material计量≤2048，但新增四字段metadata造成小夹具当前卡片省略及超大夹具Source交付减少；最早full-state误计driver、第一组交付包和退化结果分别保持。该组未开backlinks，不作为实际完整历史路径验证。重读已保存Arrow20完整字典/索引原则，Root只授权新profile的完整binding与parent结构可逆共享，字段全部leaf/mode/hash/version身份不删、表/解码说明计入2048/6。触发/cadence/对象ID/表示及正文分配是联合因子，不改变工具string、Source DTO、CAS、存储或排名选择。实际backlinks及多语种压力继续检查；Root尚未验收源码或启动R6。

新增中文反思与原URL/版本/hash可经[资料库](V13_2_DESIGN_LITERATURE.md)查看；当前651文件/57链接通过，前647报告/index按原hash另留。归档shell第一次exit127未执行Python、未修改资源，恢复为既有python3；原失败记录保持。新增模型/embedding HTTP0，原连续账本SHA26f46d5f不变。

Root事前R6 parent在隔离stdlib假CLI/局部账本上九项控制通过，覆盖完整24且有一子失败、旧尝试拒绝、前后源/配置/冻结身份变化、源path增加及错误profile；0SDK构造/socket/model。实际prepare因缺源码acceptance在导入Lab SDK或创建实验root前拒绝；两原拒绝和SDK重开/后检脚本事前冻结要求保存。没有R6实际配置、runtime或质量样本。下一步先完整Source原件/限定工程验收，再做新route/input/runtime/ledger冻结和原24/48首尝试串行运行，不重跑旧root，任务与支持来源门槛分别报告。

## 新支持来源实现限定验收

[实现验收](../data/manifests/v13-2-direct-support-acceptance.json)接受默认关闭direct_support_v1；Source33a72b3远端核对、Root2eeb7b7转入211源码8c466，实际D0入口和P5共享验证/传参。Root逐hash核对1775索引文件/113原subprocess/前后版本并复制1777原件，11非零回执/非subprocess限制和最初D0范围遗漏各自保存。38新profile＋32默认主树检查、六源码ruff/mypy和双边界通过，314配置及原连续账本SHA26f46d5f未变，0真实generation/embedding。

12压力包全部真实material≤2048/max6且选择ID/次序相等，元数据造成的history/current/Source交付减少与空胶囊仍明确。Root独立解码完整有序叶/父版身份，最终新审计器对95原R5 wire原字段一致；13解码控制、11合成metadata控制、九parent控制仅为工程证据。Root空胶囊重复计数/发布SyntaxError原失败及未执行Python≥3.12草稿的静态纠正保持。实际R6配置/冻结/HTTP/SDK/任务与支持来源评分仍未执行，D4不准入、Product NO_GO，完整计划active。

## R6新运行事前冻结

[R6冻结](V13_2_E0_R6_FREEZE.md)完成原24/48与原rubric的新空root，211源码8c466、原3.11.13/SDK、既有两模型route及原连续账本26f46d5f。只新增direct_support_v1联合profile与实验说明，原R5 Host/writer提示、2048/max6、bank_prefix和Host12/writer1/repair0保持，admission仍legacy。实际prepare禁socket0HTTP，前后源码/测试/315配置相等；新wire/解码/SDK/后检在任何模型调用前各自复制固定。此前缺acceptance拒绝/静态错误/失败各保留；冻结提交核对后按完整24首尝试串行执行，尚无R6质量结果。

## R6首次完整分母与失败后研究

[R6逐条结果](V13_2_E0_R6_RESULTS.md)现已完成24首次子命令：23正常/1返回失败，45完整消息/1中断/2NOT_RUN，原分母48保持。Root原rubric完整主张/范围/授权审查21PASS/3FAIL，22门槛未过：初次参数形状失败耗尽额度；素食被扩大为所有动物制品限制；一个已完成标签仍被尝试complete_label且业务guard拒绝。正确最终答复、实际副作用0和被拒尝试分别报告，未删失败或补试。

三原卡同ID更正/历史及当前旧值回答正确，但改动明确只选旧来源；两个旧update的支持更正和完整gate失败。三查询新revision只引问题，共5轨迹/6版本直接支持缺口。另保留scope.source_refs结构误用及“常用”被标preference的metadata偏移。26 Host成功跳过/14no_change/4committed/1pending与1未到维护/2未运行分开；实际显式whole-field reuse未执行，工程检查不升级为模型复用。

Root只读SQLite Store SDK重开24bank/458items与最后真实回执一致，DB SHA不变。150已观察Host HTTP逐包检查最大ordinary2044/max6、完整field_map/trigger/version/叶hash与SDK匹配；45完成消息通过，update-1末准备与两缺消息仍UNVERIFIED，原冻结后检失败不改。单独原collector补齐全分母，Source及连续账本未变；cap文件12、错误回执和冻结project→reserve顺序另佐证末准备未dispatch，没有补造trace或重跑模型。

R6 +169generation/958,878known（Host150/856,495，writer19/102,383）和45embedding/19,279，trace与原账本差额一致，新unknown0。累计9029generation/24,534,988known/24,565,375charged/unknown1，embedding900,641/unknown0；历史保守未知30,387保持，末SHA73c437ac。R0–R6累计+1083generation/4,224,337known、435embedding/183,453。没有成本下降、单因素收益或泛化声明。

失败后新检索五论文/三固定project资料均已保存；[可查看资料目录](V13_2_DESIGN_LITERATURE.md)现11论文/10项目参考、682文件/85本地链接通过hash/头/链接核验，方法参考与未采用候选区分，早期检索笔记和完整R6诊断分别可读。只授权同一既有Source做通用参数说明/原validator路径反馈的READ_ONLY方案，不改当前211源码和所有冻结cohort。完整plan ACTIVE，来源/同能力/D4与D5门禁仍未完成、Product NO_GO。

## 通用工具说明方案的Root核验与新隔离范围

[新范围](V13_2_SCHEMA_COMMUNICATION_DESIGN.md)限定默认关闭shape_feedback_v1，联合呈现公开参数层级、三类真实错误来源与trigger元数据/Source正文说明。Root核对280索引原件/48回执、原17→19文件maps、19快照/9归档参考，精确复制282文件；47返回0/一rg返回2及Source初始metadata覆盖限制原样保留。Root新鲜211 map仍8c466、连续账本73c437ac不变，核验器首执行0且无机制测试/新模型HTTP；两次Root只读查阅失败的原工具来源另列，不补造当时map。

范围只允许一个新增helper与六现有源码、三相关测试，D0实际入口、recipe、Host/基线/M、writer及P5恢复同flag闭包。旧默认/catalog/wire、实际grammar/参数、Source/CAS、12/2048/6/writer1/repair0保持；不补来源、问句分类、业务规则或语义verifier，不增加付费repair。独立cap可观测提案未纳入。先发布核对此范围，再由同一既有Source在新隔离树实现，旧树HOLD；实现和Root有限工程验收之前不建实际新cohort或启HTTP。资料682/85、R6失败、48验收项状态及完整plan ACTIVE/Product NO_GO保持。

Root已单独准备后续R7 parent/SDK/wire/postcheck草稿：11项冻结/no-replay/一致错误profile拒绝及8项后检失败保留控制在纯合成文件和mock子命令上通过，0真实SDK/模型。wire失败不再使独立完整collector跳过，原非零、错误artifact与完整分母分别保留；源码或账本变动立即停止。首Path monkeypatch harness失败的原driver/log与独立修正均留存，未修改运行实现。实际R7配置/root/冻结/HTTP尚无，profile-specific wire校准须等待实现；211/8c466与账本73c437ac保持。

48项验收状态不变，D5-10另追加当前840/六profile/九terminal的已发布完成证据，旧“10k仍在运行”qualification原样保留并标明历史阶段。当前PARTIAL缘于方法/自然长程/对象流等剩余要求，不再由旧未完成性能阶段解释。另一次Root只读导航rg路径失败保存工具来源与当时map缺失限制；所有这些工作0新增实验模型HTTP。

## 通用工具说明的限定工程验收

[验收记录](V13_2_SCHEMA_COMMUNICATION_ACCEPTANCE.md)保留1844索引原件/143回执/15非零并复制1853文件。Source d6bb0a2精确转入410e02f，212/36338eb5；Root最终86受影响测试、ruff/mypy与双boundary通过。8默认/原错误字节对照、6压力原包及Qwen全请求成本、6主树实际Mock Host/writer冻结呈现对应均核验；原阶段和正文交付退化保留。原R6 150wire/48行与原失败完整保持，最终9合成wire guards通过。0真实新HTTP，连续账本73c437ac不变；所有48验收状态/R6失败/完整plan ACTIVE/Product NO_GO保持。允许准备R7，实际配置/root/冻结/模型样本尚无。

R7已完成默认关闭机制验收后的新配置/真实路由GET-only检查及无socket prepare：212/36338eb5，原3.11.13/SDK/Host7860与embed7861/原rubric/连续ledger73c437ac，原24轨迹48消息。冻结profile=shape_feedback_v1+direct_support_v1，原schemaSHA与新catalog/guide/反馈policy另存；旧base指令/ordinary2048/max6/Host12/output4096/temp0/writer1/repair0/legacy admission保持。SDK/wire/decoder/postcheck原driver字节独立冻结，普通audit失败仍继续完整collector。此阶段0gen/embed，未开始实际模型样本；先核对Github冻结提交再Root串行首次执行。48验收状态/历史R6/完整plan ACTIVE/Product NO_GO不变。

## R7实际完整结果、硬门槛与资料归档

[R7结果](V13_2_E0_R7_RESULTS.md)在GitHub预运行冻结b6e3301核对后首次串行执行原24/48：22命令0、2命令1，46消息完成/2中断/0未运行。Root原全部断言/范围/授权审查21PASS/3FAIL，22门槛失败，另发现1虚假持久语义卡保存答复。两个旧update原ID/更正叶/历史/当前旧值限定gate本轮通过，cohort来源门槛仍失败：update-4旧来源支持新值、scope-1查询问题支持新revision，共2轨迹/2提交版本。R0–R6历史失败不升级。

两中断使用的是实际explicit search返回且实际送入HTTP的完整游标；冻结分页解析仅取ordinary packet，错误比较不同menu，Root以原请求/参数/hash及静态路由独立佐证，没有重放。一个初次Host final称结果已保存但卡数0，闭合writer的mixed role/user_statement被source_role_mismatch拒绝；原Source与确定性观察存在不替代语义保存承诺。此硬门槛在24均terminal后的完整离线评审才发现，诚实记录检测阶段；之后没有启动新实际模型cohort，先做通用机制再评估。scope-2混淆usual详细/特定demo简短；restart-3/4唯一writer截断pending但实际原卡和正确reader保持。

冻结SDK/wire/collector三个原后检均0，Source/原账本不变。只读24bank/471SDK items均匹配最后receipt且DB hash不变；151 Host/171通信逐条mechanical wire PASS，ordinary最大2048/max6，不能把两中断当最终任务成功。维护26Host跳过/14no_change/2committed/4pending，另2未到维护。4对象各授权业务一次，重复完成label提案0，实际额外副作用0，owner泄漏未观察；一虚假保存独立失败。

R7 +171generation/1,222,370known（Host151/1,085,579，writer20/136,791）、52embedding/20,202，新unknown0，原trace/连续ledger差额精确匹配。累计9200gen/25,757,358known/25,787,745charged/历史unknown1/保守30,387，embed920,843/unknown0，末SHA374fcef4。R0–R7累计+1254generation/5,446,707known、487embedding/203,655，未声称成本下降。

失败后保存6篇新primary摘要/固定PDF与2组官方project方法资料，累计17论文/12项目参考、711唯一文件/112本地链接核验PASS。GitHub未认证API的403原资源失败和一次空目录resume失败都保存；18论文原件未重复下载，独立git refs固定LangGraph1.1.10/AIP158，仅四次新方法资源GET，不升级/执行第三方。LangGraph标签源码与安装prebuilt1.0.13字节不同，两者独立留存，不宣称完全相同实现。方法参考与未采用reviewer/任务rubric/SQL detector/工具说明学习候选区分。下一通用候选先修正实际结果集快照身份及有限真实读取错误反馈，保留owner/turn/Source/版本/12/2048/6/writer1/repair0，不加语义verifier、案例分支或自动重试。所有48验收状态保持，D4未准入、完整原plan ACTIVE/Product NO_GO。
