# v13.2 执行记录

2026-10-01。状态 **ACTIVE**，完整范围为原计划D0–D5及其条件门禁，不以首批、机械测试或开发样本代替完成。

用户明确要求详细阅读并执行[589行原计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_2.md)。
原文SHA256为 `84c89a3e8dbb1f23ad4478e8a809f264c76c430b537b0ea1501671230681a79a`，
字节未改；DESIGN_ONLY保留为原设计状态，不覆盖当前执行授权。

远端main已fetch并用ls-remote独立核对为 `95bf708bfd8aac9f7855485166e3bf739928b949`。
新分支为 `feat/lab-evidence-incremental-v13-2-20261001`，工作树为
`/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-2`。
用户入口主工作树及v13.1未提交改动未动。[入口冻结](../data/manifests/v13-2-entry-freeze.json)
记录原计划、旧cohort、源码差异和真实账本。回滚基线是95bf708，尚未推送此分支或合并远端。

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
D4同能力四臂、第二工作流24新冻结开发轨迹与12/24分轨仍未运行。
D5新pilot、正式独立来源比较、公开任务、独立评分、第二家族、统计和完整复现仍未完成。
相关机制只有满足原门禁才消融或扩大；负结果要求追首断点/一般修复，不能删失败或补答案。
[开发评分标准](../data/diagnostics/v13-2-small-development-rubric.json)已在新模型输出前固定；
[配对统计草案](../data/manifests/v13-2-statistical-design.json)固定主要比较、5pp界、依赖聚类和缺失上下界。
最终正式样本数和运行身份须由新pilot精度与实际独立来源事前补齐；该草案不算正式统计完成。

## 账本与验证边界

权威连续账本仍是原checkout `MiLAi-Lab/artifacts/ser-v20/budget.json`。
v13.2入口为7,946 generation／20,341,038 charged generation tokens／717,188 embedding tokens；
生成已知20,310,651，保守未知费用30,387，unknown usage为1；embedding unknown为0。
[历史账本差额审计](../data/manifests/v13-2-historical-ledger-bridge.json)将旧快照到入口的485次生成对到484次有响应请求／4,568,357已知tokens及1次30,387保守未知费用；449次embedding／178,885 tokens也与差额一致。旧文稿44份completed回执是完成消息数，不是完整轨迹数；缺响应请求未推定完成或归零。入口表遗漏的20个源码/config差异已按两个提交的实际字节补齐并保留修订身份。入口hash只对应实验开始前，后续实际调用和快照另列。
[R0新增费用](../data/manifests/v13-2-r0-development-accounting.json)为292次generation／903,698已知tokens与143次embedding／61,122 tokens，逐trace和连续账本完全对上。其中Host237次／722,344 tokens，形成55次／181,354 tokens；新增unknown为0。R0末累计8,238次generation／21,244,736 charged、21,214,349 known、unknown1与embedding778,310、unknown0。
R1另新增124次generation／395,787已知tokens与49次embedding／21,081 tokens；其中Host98次／307,459，writer26次／88,328，全部费用对账。R1末累计8,362次generation／21,640,523 charged、21,610,136 known、unknown1；embedding799,391、unknown0。入口历史保守未知30,387仍留在账本，未宣称成本下降。价格、美元和GPU小时未测。所有新调用、失败、重启、维护及评审继续本账本，真实HTTP串行。

两个D0/source-group分析工具ruff通过，实际tools边界检查通过；现存6项grandfathered依赖未新增。
D1目标static/mypy和package边界通过，未跑全suite、build、模型质量或远端CI。
全部改动属于Lab研究opt-in合同；Product API、权限、Schema和Canonical未改，Product仍NO_GO。
没有把代码存在或局部测试通过表述为方法优势或发布就绪。
