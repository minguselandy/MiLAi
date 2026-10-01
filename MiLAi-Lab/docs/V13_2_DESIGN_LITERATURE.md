# v13.2 设计资料索引与失败反思

2026-10-01。按用户要求，检索的论文、项目和官方SDK资料均留存，采用的方法与未采用候选分别标明，后续新增资料继续追加本索引与[机器目录](../data/manifests/v13-2-design-literature-catalog.json)。现保存11篇论文PDF/HTML/摘要和10组项目/SDK参考，682个唯一文件、85个本地索引链接通过原hash/PDF头/链接核对；Mem0论文设计参考与实际运行SDK的固定版本分别保存。

完整本地资料位于`artifacts/v13-2-design-literature/`；打开其中`index.html`可查看总结并点击PDF、网页原文和项目README。二进制论文和第三方源码快照保持ignored，GitHub发布索引、原文链接、固定commit和SHA256，便于在其他机器重新下载核对。下载/保存不等于完整复现；原benchmark问题、gold、正式holdout未读入或用于修复。

已归档的jsonschema/vLLM/JsonSchemaBench参考另用于[通用工具说明与真实结构反馈方案](V13_2_SCHEMA_COMMUNICATION_DESIGN.md)。原只读交接、48条命令及9参考原件逐hash另存；此次没有新增检索资源或实施机制，资料计数保持682/85，结构说明与语义收益分别验收。

## 论文与可借鉴内容

| 资料 | 方法要点 | 对当前设计的用途与边界 |
| --- | --- | --- |
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) | 研究相关证据在长上下文不同位置时的消费差异。 | 材料进入上下文不保证答案消费。R3首先要解决旧正文未交付，再分别测交付和使用，不能把增加上下文长度当作修复。 |
| [Mem0](https://arxiv.org/abs/2504.19413) | 把新候选事实抽取与对旧记忆的操作选择分成两个阶段，包含NOOP。 | 借鉴“先判断有没有新事实，再决定维护”的职责。保留现有一次writer边界与来源/CAS，不增加后台服务；这只是修复假设，不移植论文收益。 |
| [Hindsight](https://arxiv.org/abs/2512.12818) | 保留时间/实体信息，区分事实、经历与意见；通过多路检索关联有关记忆。 | 参考实际历史关联和主张性质的表达。沿用原词法+dense与source回链，只压缩重复metadata并交付真实相关版本，不默认接新reranker、推断日期或重建大型图。 |
| [HiMem](https://arxiv.org/abs/2601.06377) | Episode与Note关联，冲突感知再整合帮助动态维护。 | 作为类型/关联机制近邻，保留可选kind及现有身份修订。当前先验证单条实际关联/更新，不据此强制双Store或宣称双类型更好。 |
| [EAL-Bench论文](https://arxiv.org/abs/2609.01836) | 分析错误权威在记忆形成和下游行动中的传播，比较来源约束与有界事件溯源。 | 提示存在来源ID仍不等于概括被支持，推断/提问不能升级成用户事实或业务授权。gold引用源gate属于诊断条件，不引入运行时隐藏授权或gold。 |
| [SimpleMem v3](https://arxiv.org/abs/2601.02553v3) | 语义结构压缩、会话内综合、意图检索规划分担不同职责。 | 核查已有Text接入的原生形成、规划/反思和全部费用。JSON载体保留原源不保证原生条目有来源ID、owner或revision/CAS；不迁移论文分数。 |

上表是对原始论文相关方法部分的概括；应用到当前系统的取舍是Root推断，尚未通过新实验。论文自报性能不作为MiLAi性能结论。HiMem和EAL的代码未作忠实复现；项目版本也不自动等于论文评测版本。

## 已保存项目版本

| 官方项目 | 保存身份 | 本地内容 |
| --- | --- | --- |
| [nelson-liu/lost-in-the-middle](https://github.com/nelson-liu/lost-in-the-middle) | `29b8a6d042ce29abccee3db1a73171a107d7e6af` | `projects/lost-in-the-middle`；12份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | `f2c33cc405023dcaa8aa8ef4c0120e1f262f05ad` | `projects/hindsight`；353份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | `94c3fe9f238f3dbf29c9ce98643bd71eb13077cd` | `projects/mem0`；171份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [Mem0实际运行SDK参考](https://github.com/mem0ai/mem0/tree/f8082a7345dadd9e042ebbc40b57b1498c8f6d63) | `f8082a7345dadd9e042ebbc40b57b1498c8f6d63`，mem0ai 2.1.0 | `projects/mem0-runtime-f808-reference`；10份固定公开接口/README/LICENSE/包定义、安装METADATA/direct_url及148模块哈希清单；六个git对象与实际安装源码分别核对 |
| [langchain-ai/langgraph Store reference](https://github.com/langchain-ai/langgraph) | `11ee185999b86bfea2d8c0e69cef9a5e37acf686` | `projects/langgraph-store-reference`；10份文件，源码/README/LICENSE或SDK版本参考，完整文件hash见目录 |
| [Apache Arrow dictionary encoding reference](https://github.com/apache/arrow) | `3ad0370a04ccdae638755b94c3c31c8760a11193`，20.0.0 | `projects/apache-arrow-dictionary-reference`；8份官方版本文档、格式源码、README/LICENSE和tag元数据；选定参考片段，不是全仓复现 |
| [aiming-lab/SimpleMem Text reference](https://github.com/aiming-lab/SimpleMem) | `db80b6a7c591e0ea730a058e9f5fc4eb06572299` | `projects/simplemem-text-reference`；21份text/core、导入入口、README/LICENSE及包定义；未复制benchmark/evaluation、multimodal或evolver内容 |

LangGraph另保留本次实际安装`langgraph-checkpoint-sqlite==2.0.11`的源码与包METADATA；官方新版本的分段匹配和实际安装版本的LIKE行为分开记录，没有升级SDK。Hindsight目录重组使首次旧路径未取到源码，随后按tree metadata找到实际路径并核对353份文件；这个归档问题不算实验失败或成功。

## R3失败给出的改进假设

实际证据见[R3全24结果](../data/manifests/v13-2-e0-r3-results.json)。四个更新查询的普通包都只送达当前正文；历史revision/source匹配菜单占据大量预算，另五个已选单元被省略。饮品/距离的Host显式读旧版后能回答历史；语言/会议未读取所需旧版或只重复读当前，最终漏旧值。这支持优先检查“元数据与正文如何分配同一预算”，不能把revision菜单存在当作历史消费成功，也不能按“以前”等语言关键词选答案。

通用读入修复候选是在固定选中record/source范围内压缩重复metadata，把真实相关旧版本和叶子片段按同一2048/6限制呈现，保留读时CAS、来源角色/hash和省略页。不改变检索排名或强行选更新目标；构造、实际HTTP送达和最终消费分别验收。

维护方面，R3在无新偏好陈述的查询边界仍发生额外修订，七条轨迹只以问题引用旧事实；团队午餐例还新增错误长期个人素食卡。抽取新主张与选择修改应先在同一writer推理中明确区分：仅查询既有信息时允许直接decline/no_change，当前事件是触发而非旧事实的全部支持；保留实际旧支持与未改字段。这个语义判断仍由模型完成，不能用固定问号/中文词或benchmark ID替代，也不声称引文匹配能验证蕴含。

下一次候选必须另列修改范围、冻结配置/源码/rubric和费用身份；共同解释规则同样提供给基线。保留R0–R3全量否定结果，不挑最好回答。此阶段仍是曝光开发诊断，完整独立来源pilot、独立评分和泛化验证未完成。

## R4复检后的取舍

[R4完整结果](../data/manifests/v13-2-e0-r4-results.json)20通过/4失败，没有达到门槛。重新查阅[Mem0原论文](https://arxiv.org/abs/2504.19413)、[Hindsight原论文](https://arxiv.org/abs/2512.12818)及[固定Mem0抽取/更新源码](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/mem0/configs/prompts.py)，来源正文和固定代码均已保存。抽取允许空候选、维护允许不变只是设计职责，不保证模型能正确区分问题前提与用户事实；不会整段照搬上游prompt、时钟推断或示例。

R4维护14次no_change说明同一writer能够选择不改，但团队素食误写、临时演示范围扩大和语言查询单问题引用仍然存在。实际引用成员验证不等于支持主张，更不等于范围正确。这些是Root结合本地证据的推断，论文收益没有迁移为MiLAi结论。

表示候选只压缩已有选中单元的重复metadata，留出真实历史/叶子正文预算；不按题目语种或关键词改变检索/更新选择。先验收工程交付，再冻结新的全量开发cohort；相同公开说明提供各基线。默认旧行为保留，索引存储性能改动独立测量，不合并为单因素收益。

SDK检查另保存官方固定Store接口与实际安装`langgraph-checkpoint==2.1.2`接口/METADATA。公开put禁止namespace分量包含句点；无效测试样例失败与修正依据保留。官方最新分段行为与实际Sqlite2.0.11前缀LIKE继续分开，没有升级SDK。新增资源和失败反思在本地SDK参考的`namespace-validation/`可查看。

## 材料压缩工程失败与表示参考

共享来源绑定后，两记录、多语种的实际Qwen tokenizer工程夹具仍只交付一份选中旧正文；失败回执保留。为减少重复字段，查阅并保存[Arrow 20.0字典编码格式](https://arrow.apache.org/docs/20.0/format/Columnar.html#dictionary-encoded-layout)与[格式说明](https://arrow.apache.org/docs/20.0/format/Intro.html)。字典保存完整值，重复处使用明确索引；字典与索引需要一起传递。

当前候选借鉴这个通用表示原则，压缩实际record ID、完全相等的scope及重复读入口，保留完整来源role/hash、版本hash/CAS、当前/历史区分和真实省略状态。表、解码说明及正文仍共同计入原2048预算。此应用是工程假设；不引入Arrow依赖，不改排名或选取范围，模型能否正确消费及完整语义收益尚未验证。小包可能因表开销变大，同样需要记录。

20.0.0发布tag实际指向第二层tag；首次只解引用一层的归档检查失败，原元数据保留，递归解析后固定到上述实际commit。归档错误与材料交付失败分开，不算模型样本。

## 已接入SimpleMem-Text的独立合同核查

原规划8.1要求已有第二外部系统另作预算/微型确认。因此检查[固定Text原生条目](https://github.com/aiming-lab/SimpleMem/blob/db80b6a7c591e0ea730a058e9f5fc4eb06572299/simplemem/core/models/memory_entry.py)与[公开VectorStore](https://github.com/aiming-lab/SimpleMem/blob/db80b6a7c591e0ea730a058e9f5fc4eb06572299/simplemem/core/database/vector_store.py)：原生字段没有source-event、owner或MiLAi整数revision/CAS，不能补造为已验证归属。trace_equal载体可保留完整原Source JSON，但这种输入关联与原生条目字段分开报告。

实际核查继续使用已存在专用环境及原固定代码，未升级或安装SDK，也不改变运行中的性能环境。原推理环境首次缺少lancedb metadata的构造失败留存；选用原专用环境后才能检查公开SDK持久化和调用入口。规划/反思、原生有限重试和闭合短flush保持原身份。离线脚本响应只证明工程合同，尚不能完成D4-07真实微型比较或宣称SimpleMem模型质量。

## 四臂恢复计数的官方设计参考

另保存[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)、[Stores](https://docs.langchain.com/oss/python/langgraph/stores)的HTML/Markdown共7文件，位于既有LangGraph参考的`recovery-documentation/`。原durable-execution URL已重定向至Persistence，原请求和最终URL均记录；这些是检索时rolling文档，不作为本地SDK版本证明，没有SDK升级。

官方说明将图状态checkpoint与图外应用Store区分，并说明replay会重新执行所选checkpoint之后的模型/API步骤；sync持久化在下一步前写入。结合只读调用链，Root推断：Host AI checkpoint计数不是所有native/summary paid callback的账本，恢复上限应依赖完整共享admission状态；缺失可信计数不能当零或仅补Host下界。此为下一opt-in工程要求，尚无实际四臂恢复故障结果，不移植新文档API或改变方法方向。

归档首次系统Python urllib未处理308，七文件成功保存后又因已有最小HTML无显式body结束标签而索引追加失败；原两份脚本和失败stdout/stderr hash保存，按hash核查并补全索引，没有重新下载覆盖或把归档问题当实验结果。

## 实际Mem0 SDK接口与恢复边界

四臂只读审计查阅实际固定[f808公开Memory接口](https://github.com/mem0ai/mem0/blob/f8082a7345dadd9e042ebbc40b57b1498c8f6d63/mem0/memory/main.py)、[vLLM调用入口](https://github.com/mem0ai/mem0/blob/f8082a7345dadd9e042ebbc40b57b1498c8f6d63/mem0/llms/vllm.py)及历史存储定义，原件已保存。它与94c3fe9设计参考是两个身份。Root核对49份带209源码前后map的只读回执和240份原始审计文件，保留两次非零路径查找及四份未封装setup失败；没有构造SDK、运行测试或调用模型。

该固定接口的get_all使用owner过滤及声明边界；get/history本身不带owner，交付前需要真实已归属ID证明。默认top_k20及过期过滤使少于20条结果也不能证明整个bank完整。历史ID、时间和正文hash保持原生意义，不赋予MiLAi整数revision/CAS。抽取transport异常与parse失败后的空结果分开，空结果不证明正确semantic no_change。

Root下一步只授权在新隔离树修复通用共享admission的持久化与恢复：12/24上限覆盖同一计数入口，恢复缺失或不可信计数时拒绝dispatch；unknown仍占reservation。默认行为、当前209源码和R5实验身份保持。B6摘要、共同reader/cache/闭合形成边界及Host记忆写权限另有未实施要求，四臂未准入。

资料库再次只读核对622个唯一文件与54个本地链接，PDF头与目录hash通过；结果保存于`artifacts/v13-2-literature-audit/current-archive.json`。这是资料可查看性核验，不是完整项目复现或模型收益。

## R5来源缺口的重新查阅

[R5完整复核](V13_2_E0_R5_RESULTS.md)24任务通过，但四更新query r3、一张正确个人否定卡和两张历史操作措辞存在直接来源缺口；7 pending与原失败均保留。再次检索既有[EAL v1方法](https://arxiv.org/html/2609.01836v1)、[Hindsight v1方法](https://arxiv.org/html/2512.12818v1)和[固定Mem0抽取/维护源码](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/mem0/configs/prompts.py)。原PDF/HTML与项目源码已保存；本次重读URL、原件hash和本地失败反思另追加机器目录与本地index，不覆盖旧资源。

EAL把记忆错误形成与下游行动分开，其有界事件溯源在外部保留不可变更新日志；源码成员存在仍不足判断scope/历史语义。Hindsight区分原事实、经历与综合观察/意见，这些综合结果不是原始证据的替代。固定Mem0允许空抽取和NONE，并将抽取与选择维护分开；这不保证问题中隐含前提正确，也不能以问句形式一律丢掉新陈述。三者只是相关设计参考，没有移植其分数、gold gate、隐藏账本、额外模型或后台机制。

结合R5实际trace，Root推断下一通用候选须区分“当前事件触发维护”与“真实叶子支持断言”，在同一模型语义选择中保留所选支持叶子和未改字段的来源关系；程序只验证owner/role/hash、选取范围、版本和提交回执，不自动证明蕴含或用固定词分类。object_ref应来自实际已声明公开string句柄，不能将结构对象当同类型输入。先验收机械合同，再另冻完整cohort检验；不通过禁用全部维护或只修曝光案例绕过来源门槛。

R5重读原件及新增总结再次核对624个唯一文件、55个本地index链接，PDF头/hash通过；前一622文件报告按原hash保留。重读没有新增论文、SDK执行或实际模型调用。

## 实际SDK串行边界资料补充

[只读串行审计](V13_2_SERIAL_HTTP_AUDIT.md)另保存22份原SDK/git参考/依赖metadata文件及一份Root新位置manifest，加入实际f8082a73/mem0ai2.1.0第七项目参考的serial-http-reference目录；不覆盖原manifest、已安装SDK或94c3fe9设计参考。原manifest的历史路径保持，Root补充清单给出当前可查看路径/hash。

结合实际固定源码，Mem0同步add的原生模型步骤顺序执行；选定四线程executor只检索本地entity store，不能据此解释模型HTTP并发。实例bridge锁与admission计数不覆盖所有client/ledger生命周期。Root据此推断应独立实施共同请求mutex与owner lease，再验收所有实际路径；方法方向、模型语义选择和既有计费保持。资料结论只是静态范围，未观察并发事故或建立运行闭包。

[共享计数工程](V13_2_SHARED_ADMISSION.md)已限定验收并合入210源码，默认关闭且未启用实际实验配置；上文授权阶段的209/R5 HOLD说明保留为历史。恢复时缺失或不可信完整计数拒绝dispatch，未知额度保留；这不替代共同HTTP锁、B6 summary或D4共同能力。

当前资料库六论文/七项目参考，647个唯一文件、56个本地index链接、PDF头与hash核对通过。此前622/624文件报告按原hash另留，不覆盖原件或第一次归档失败。补充0新增论文/SDK执行/模型HTTP；选定参考文件不代表整仓复现。

## 支持来源初次压力退化与可逆表示

隔离`direct_support_v1`实现首次压力driver把完整prepare_context state误当普通材料预算；错误driver/日志由Source保留，修正计量后实际material均≤2048、原选中ID与顺序相同。但新增四字段来源metadata有真实交付成本：小夹具legacy2047送1当前record及2Source，新初版1834只送2Source并明确省略当前record；多历史两者都不送record/history；超大多语种legacy送5Source，新初版送4Source。Source可包含截断前缀，这些夹具关闭backlinks，不能解释完整真实历史路径，也不能宣称完整来源或模型收益。Root保存原六包、driver、汇总及hash副本，后续结果不覆盖首次退化。

重新查阅已归档的[Arrow20字典布局](https://arrow.apache.org/docs/20.0/format/Columnar.html#dictionary-encoded-layout)和[完整字典消息](https://arrow.apache.org/docs/20.0/format/Columnar.html#dictionary-messages)：重复值可由完整字典和显式整数索引表示，解码需要相应字典/schema。固定20.0.0原文与3ad0370a源码保持原hash，无新论文/项目下载或依赖升级。重读URL、原文身份、第一次压力副本和可查看中文总结追加机器目录及本地index的`design-rechecks/direct-support-pressure-review.html`。

Root据此授权新profile展示的最小可逆改进：field_support仅索引同record既有完整source_bindings表；完全相等的父结构可共享，每字段完整有序leaf、mode、reuse parent record/revision/version和field hash须可恢复。完整表、解释和正文共同计入原2048/6，拒绝bool/float/负数/越界索引；存储lineage、原Source DTO、角色/hash/CAS、实际工具string参数、默认wire、排名与选取保持。这里只是通用表示推断，不移植Arrow性能或蕴含结论；正文分配与触发/cadence/伴随对象ID是联合因子。

隔离树继续补测实际backlinks的current/history、超大多语种与完整roundtrip，须保留原交付退化并列报告。源码尚未被Root验收，真实R6未运行；模型能否遵守支持选择及语义门槛仍未知。资料核验当前651个唯一文件/57本地链接、PDF头/hash通过，前647报告及目录/index按hash保留。Root第一次shell启动找不到python、未执行driver或修改归档，原exit127记录另留，改用既有python3成功；不计为模型失败或样本。

## R6参数形状失败后的新增资料

上述651文件状态保留为该阶段历史；支持来源实现后来限定验收，真实[R6完整结果](V13_2_E0_R6_RESULTS.md)为21PASS/3FAIL，来源语义门槛未过。新检索原文均保存，不只留搜索标题；新增五篇的PDF已下载，当前仅阅读primary摘要，未读取其benchmark任务、gold或数据。

| 论文 | 本次用途与阅读范围 |
| --- | --- |
| [JSONSchemaBench v3](https://arxiv.org/abs/2501.10868v3) | 摘要方法参考：将结构合规、schema能力覆盖、效率和输出质量分开审查。仅借鉴分项原则，不引入benchmark数据、约束框架或论文分数。 |
| [Experimental Settings in LLM-Based Program Repair v1](https://arxiv.org/abs/2609.17993v1) | 检索候选，原件留存；程序修复任务不等于当前记忆/工具合同，未采用。 |
| [Constrained Decoding…Semantic Gap v1](https://arxiv.org/abs/2609.23742v1) | 检索候选，原件留存；小模型预印本结果不证明当前Qwen系统语义效果，未采用。 |
| [The Constraint Tax v1](https://arxiv.org/abs/2605.26128v1) | 检索候选，原件留存；没有迁移其validity/correctness分数或变更当前provider grammar。 |
| [Gecko v2](https://arxiv.org/abs/2602.19218v2) | 检索候选，原件留存；模拟环境/额外反馈模型不适合当前真实回执与完整计费方向，未采用。 |

| 官方项目资料 | 固定身份与保存范围 |
| --- | --- |
| [guidance-ai/jsonschemabench](https://github.com/guidance-ai/jsonschemabench/tree/9a94995b9279ae3af3aed4b2629172790b968d14) | commit `9a94995b9279ae3af3aed4b2629172790b968d14`；README和原commit API，未保存/运行任务集。 |
| [vLLM v0.27.1](https://github.com/vllm-project/vllm/tree/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac) | tag对应commit `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac`；tool_calling、structured_outputs固定Markdown、官方HTML和commit原件。它是设计参考，不证明当前bdbaea18定制server构建等于tag。 |
| [python-jsonschema v4.26.0](https://github.com/python-jsonschema/jsonschema/tree/a7277432b0f7bcd0551f6e589d30457017125df4) | commit `a7277432b0f7bcd0551f6e589d30457017125df4`；README、错误文档、exceptions/validators/_keywords方法源码、官方HTML及commit原件。实际安装4.26.0另观察，未升级。 |

[vLLM官方结构输出说明](https://docs.vllm.ai/en/v0.27.1/features/structured_outputs/)要求实际提供的schema与提示配合；[tool calling说明](https://docs.vllm.ai/en/v0.27.1/features/tool_calling/)区分具体选择方式/约束范围。R6实际generation_only schema的arguments仅为object，不能把strict:true理解为已约束完整工具字段，实际执行前参数schema仍有效。不会未经新工程/冻结就启用完整provider schema、更换服务或parser。

[jsonschema官方错误结构](https://python-jsonschema.readthedocs.io/en/v4.26.0/errors/)提供instance/schema路径、validator及子错误context，message本身可能不足以定位问题。Root据实际失败推断：下一默认关闭通用候选先清楚分开真实top-level字段值与field_support对象，给出完整合法结构；校验反馈可包含原路径/keyword/原schema类型或enum，但不能填入正确业务值/来源、自动修写proposal或增加重试。元数据/说明/错误输入均继续计费，2048/max6、writer1/repair0、角色/owner/hash/CAS及旧默认不放宽。

结构合法也未解决直接来源语义：真实更正选旧叶、查询选问题源、无支持限制扩大及被拒重复操作均保存。采用方向仍是由模型选择真实证据、程序验证明确机械关系、业务回执真实，不引入case词分类、强制current-source、额外语义verifier或后台模型。此处为Root修复假设，尚未实现或取得新模型收益。

24次成功只读资源GET的原URL/最终URL/时间/status/bytes/hash在`artifacts/v13-2-literature-audit/r6-schema-research/retrieval-attempts.json`；本地`index.html`新增26链接，`design-rechecks/r6-schema-failure-review.html`可读早期失败反思。最终核验11论文/10项目参考、680唯一文件/83链接、0issue；此前651目录/index/catalog和审计按原hash保存。资料归档自身0模型HTTP/第三方执行；同时间Root授权R6的账本变化另算，不宣称并行阶段整份账本不变。

R6完整审查后另加`design-rechecks/r6-complete-review.html`，将完整失败、费用、来源限制和下一通用假设同早期检索笔记分开保存；本地入口顶部可直接打开完整诊断和逐条结果，并明确旧笔记中的“未运行”是当时历史状态。外层HTML闭合已整理，历次原文不改；此前680报告/目录/index按hash保留。当前核验682唯一文件/85本地链接、0issue，新增论文/项目/模型HTTP均0，原账本73c437ac不变。

## R7实际读取/保存失败后的新增资料

[完整R7原评审](V13_2_E0_R7_RESULTS.md)21任务PASS/3FAIL、46完成/2中断，另1虚假语义卡保存和2版直接来源缺口。两中断调用实际explicit搜索返回的游标；Root以实际付费请求和menu hash确认，冻结resolver却只取ordinary结果集。这是结果集身份/生命周期的通用缺口，不能以改游标、扩大selection或放宽Source/version guard解决。

| 新保存论文 | 固定版本、摘要阅读范围与采用状态 |
| --- | --- |
| [Memory Provenance Laundering](https://arxiv.org/abs/2607.29167v1) | 平台原来源角色/权限保留原则参考；不采用风险分类策略、firewall实现或论文分数。 |
| [From Lossy to Verified / TierMem](https://arxiv.org/abs/2602.17913v1) | 原不可变日志与provenance链接原则参考；不采用sufficiency router、verified写回或任务分数。 |
| [Reinforced Agent](https://arxiv.org/abs/2604.27233v1) | 检索候选留存，未采用额外reviewer/语义预检/优化；模型和全部费用边界保持。 |
| [RubricRefine](https://arxiv.org/abs/2605.09730v5) | 检索候选留存，未采用任务rubric评分、迭代预执行修复；原评测rubric仍仅Root离线使用。 |
| [SQL Inspection and Refinement](https://arxiv.org/abs/2408.16991v1) | 搜索返回候选留存，领域retriever/detector不替换通用记忆读取。 |
| [Learning to Rewrite Tool Descriptions](https://arxiv.org/abs/2602.20426v2) | 检索候选留存，不按暴露任务学习/优化schema或加入额外模型训练。 |

六篇均保存unversioned发现页、固定版本原摘要HTML和完整PDF，当前仅阅读primary摘要，全文供查看而未读取benchmark任务/gold或执行实验。已存Gecko候选保持，无重复下载。来源、UTC、最终URL、状态、bytes和SHA可在机器catalog及local index逐项查看。

| 新官方project参考 | 固定身份与方法阅读范围 |
| --- | --- |
| [LangGraph1.1.10](https://github.com/langchain-ai/langgraph/tree/cb328b57f1b195ddbb974953537948b6d13cb9ad) | git tag实查`cb328b57f1b195ddbb974953537948b6d13cb9ad`；保存ToolNode方法、当前官方设计HTML和实际安装prebuilt1.0.13方法副本。标签与安装文件SHA不同，独立记录，不声称字节/行为完全相同，不升级。 |
| [Google AIP158](https://google.aip.dev/158) | git master实查`23e176e7333ea3bc6b085f9950a5da03d2bbfc72`；保存固定0158.md、官方HTML及原git-ref结果。仅参考原样continuation/独立授权，不采用coercion、自动分页或取全量。 |

[LangGraph官方设计](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)将模型可恢复错误与未知程序错误区分；当前页面的≥1.2 error_handler不在实际1.1.10环境中，不采用。固定ToolNode默认只转换ToolInvocationError、普通执行异常传播；新的有限反馈须来自真实已知读取协议拒绝，不广泛catch权限/预算/CAS或未知异常。这个方向是Root根据原失败与方法作出的待工程验证推断。

[AIP158](https://google.aip.dev/158)的continuation与请求身份一致、token不授资源权限原则对应当前缺口：应解析实际已返回的owner/bank/turn/selection快照，继续核对原叶/版本，不重新检索、补来源、挑候选或改用户参数。保存承诺仍必须实际commit回执，writer pending/truncation不能升级成功；原24失败不重跑、不改答。

本地入口`artifacts/v13-2-design-literature/index.html`新增R7中文反思及完整版本/hash记录，当前17论文/12项目参考、711唯一文件/112本地链接全部核验PASS。原682/85报告和index/catalog保留为历史。首次资源GET18成功后GitHub API403、首次resume因已创建空目录失败，都保留原driver/stdout/stderr/返回和错误响应；18论文原件复用不重取，独立git ls-remote固定refs后只新增4资源GET。归档0模型HTTP/0SDK升级/0第三方执行，Source和原账本374fcef4保持；browser失败查询记录也保留，不冒充成功。
