# Contextual user memory v6 语义修复记录

当前结论：**SCOPED_REPAIR_VALIDATED，整体质量未确立**。已解除复核次数及累计请求／tokens 的硬停止，持续使用同一账本；没有扩大原定三个原题。最终 method v10／write v9／ingestion v25／material view v5／operation v2 的五条固定路径完成，原生评分均为 1／0／1，作答阶段均无 memory_save。限定主体、修订依赖、当前偏好／历史范围和写入边界修复已验证；下文保留全部早期失败，不能将反复开发后的通过当成独立泛化结果。

最终验证共 **43 次生成、164929 生成 tokens、21624 embedding tokens**；本轮全部开发累计 **243 次生成、969510 生成 tokens、93390 embedding tokens，unknown=0**。账本与所有 trace 相符，未清零失败费用。五份最终源码映射一致：`72f0279eae4223918fdd5869b84d75d85a3ac32800a3fbee7f66c8188ed5c312`（38 文件，与当前源码逐项匹配）。最新实际默认为 [v6-user-scope-default](../configs/contextual-memory-v6-user-scope-default.json)。

范围：[Goal v6](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v6.0_20260924.md)，仅 Lab 研究原型。v5 Goal 及其 114 次请求保持封存。以下先保留首次阶段计划与失败，文末列最终行为、成本及仍存限制；历史段落中的停止依据与 INCOMPLETE 不代表当前状态。

## 开发与验收范围

本轮必须在真实固定原题中修复主体误归属、自身旧版活动依赖及同批当前理解整理，同时保留来源接收、正常作者笔记、真实创建／修订、独立依赖失效、State消费和原任务回答。若三项目标缺陷仍复现，保持 `SEMANTIC_REPAIR_INCOMPLETE`，不能仅以接口及结构检查通过结项。

核心models／共享write合同／save由Sol xhigh实现；ingestion与公共材料由另一Sol xhigh在不重叠文件中集成；root负责Host短引用接线、配置、实际XGrammar验证和最终运行。先商定一项轻量about_ref身份绑定，不引入人物识别、主题注册表、第二模型审查或自动纠错循环。操作合同v2不变，计划method v9、write v4、ingestion v10、material view v2；最终以实际常量及冻结源码为准。

## 首次阶段固定小规模方案（历史计划；累计硬停止已解除）

| 顺序 | 配置 | 历史／答案 | 正常最大生成请求（含Judge） |
| --- | --- | --- | ---: |
| 1a | [v1003 ordinary](../configs/contextual-memory-v6-online-v1003.json) | 原顺序6批、1份答案 | 13 |
| 1b | [v1003 state](../configs/contextual-memory-v6-state-v1003.json) | 独立新建原顺序6批、1份答案 | 13 |
| 2 | [实际默认v977](../configs/contextual-memory-v6-default.json) | 自然容量计划1批、1份答案 | 8 |
| 3 | [v977 online](../configs/contextual-memory-v6-online-v977.json) | 原顺序6批、1份答案 | 13 |
| 4 | [v569 online](../configs/contextual-memory-v6-online-v569.json) | 原顺序7批、1份答案 | 14 |

共3个原题、5份历史和5个答案名额，正常上限61次，另11次仅供评分解析故障或具体代码修复后的一次局部复核。所有阶段共用新的 `artifacts/contextual-user-memory/v6-budget.json`：72次生成、350000输入＋输出tokens、80000 embedding tokens。每次摄入后检查正文主体、来源及关系，再开始答题；发生明确回归先定位，不用下一题的通过掩盖。v1003前两项预留本实例答题／评分和之后默认完整验收额度。ordinary与state写入身份不同，禁止共享或修改checkpoint标志。

Host及原生Judge沿用既有Qwen vLLM身份，embedding沿用bge-m3；每题答题最多6次，单次Judge，不扩大top-k默认值或上下文上限。数据、角色、消息顺序、原问题和rubric不变，诊断标签与gold不进入方法输入。不执行H2比较、v1002、完整STALE、未用确认集、全量测试、构建或Product迁移。当前配置为实现前草案，尚未打开新账本或调用模型。

## 实现冻结前检查

运行常量已升级为 method v9、write v4、ingestion v10、material view v2；operation v2 保持不变。`about_ref` 绑定当前用户、准确来源说话者或 unresolved；作者独立保留。历史 CREATE/REVISE 显式声明非空来源；普通作者笔记仍可无来源；持久当前用户事实不可无来源。全文 REVISE 必须声明完整来源和依赖，自身任一旧版不可作为活动依赖，内部元数据补丁保留原有省略语义。

历史同次提案得到原角色、日期、session、source_sequence、旧来源正文及准确范围、独立依赖；所有旧材料共用原12000 bytes预算。材料显示可读主体、作者、来源角色以及 CURRENT 只表示对象版本的说明。Host只绑定实际交付的主体短句柄，State首轮仅任务理解，随后必须search消费。

部署容器的 XGrammar 0.2.3 / vLLM 0.27.1，`any_order=False`，使用raw-byte tokenizer fixture做CPU编译与字符串可达性检查，无模型请求。21项最终通过，覆盖普通及历史 CREATE/REVISE、空独立依赖、带原因NO_CHANGE、RETAIN_SOURCE、无来源作者笔记、日期及State初始分支。发现并修复旧State外层anyOf约束在编译时遗漏的问题；原12项中2项失败的输入与结果保存在 `v6-grammar-diagnostic/*-before-state-fix.json`。最终探针保存在同目录 `contract-probes.json`、`contract-result.json`，不是原生评分。

联合检查另发现历史schema对共享source_refs对象设置minItems时连带限制dependencies；现仅复制并约束source_refs，合法空依赖已通过静态及实际编译检查。最终Host／runner／ingestion窄测56通过，CLI身份2通过；核心／条件／修订41通过，材料／摄入／检索16通过（摄入有重叠，不累加为独立测试数）。8个受影响源文件mypy、受影响文件ruff通过。没有全套测试、构建或服务变更。

五配置、模型身份、原生数据散列及协议常量均在第一次请求前核对。ordinary/state历史独立。首次模型运行将冻结各目录manifest及完整source映射，之后不得在同一运行身份下改代码续跑。

## 首次真实历史与一次局部修复

v1003 ordinary 初次目录 `artifacts/contextual-user-memory/v6-online-v1003` 保留。6批12消息均接收，6次生成26401 tokens、embedding1972 tokens，unknown=0。assistant发表文章已正确标为assistant来源说话者，并非用户履历；合法用户表达也被保存。但志愿服务转向全部CREATE，0次REVISE，旧的泛化当前表达仍并列存在。该次为 `SEMANTIC_REPAIR_INCOMPLETE`，未开始答题、没有原生分数，不计为判错或通过。具体记录 `semantic-diagnosis.json`。

batch3请求确实交付旧card:2@1为r0及完整旧user正文s2，新表达s0也完整；schema允许REVISE r0及空独立依赖。针对性Sol xhigh只读判断确认：通用说明要求先memory_read，而一次历史提案不提供工具且新ordinary说明漏掉“rN已读”；此外局部p0/p1被写成持久正文人物名，前后同一当前用户选择不同主体句柄。

仅修复交付说明：已经交付正文的准确版本满足read前提，只有链接才另行读取；明确当前用户自述使用u0，局部句柄不作为姓名写进正文；同一事项的真实范围改变需在当前文本说明旧范围。未改排名、top-k、预算、数据、schema或强制指定操作。ingestion升级v11，公共prompt散列随新manifest冻结。原6次计入预留，一次复核配置为 `configs/contextual-memory-v6-online-v1003-repair-1.json`，其余未执行配置同步v11；原v10配置与冻结源码仍保留。本次重新形成完整6批，不复制旧checkpoint、不做第二次语义重试。

一次局部复核成功：`v6-online-v1003-repair-1` 历史6次22672 tokens、embedding1952。card:1@1→@2→@3实际提交，当前主体current_user，来源arrival 2/4/8准确保留，活动依赖[]；assistant文章来源仍以assistant保留，无误归用户卡。答题search交付当前@3及新来源，随后read核对，答案采用scheduled workshops / tailored curricula；原生Judge通过（latest=1、outdated=0）。答题3次及Judge1次累计12243 tokens；该目录总10次34915 tokens、embedding4132。失败目录另计，账本共16次61316 tokens、embedding6104，无unknown。

核对真实回答材料另发现确定性投影缺陷：source_refs 的bodyless短链接被已交付正文短句柄替换时，source_roles字典键没有同步替换；本例同为user角色，答案与引用来源正确，但摘要引用不一致。只修复公共resolve_links中source_roles映射键，补已有材料测试“先解释卡、后原来源正文”的实际顺序断言；不做第二次模型复核或复跑已完成ordinary。material view升级v3；后续四份原计划配置采用新身份。此前两运行的manifest、源码、分数和失败记录保持原样，不把它们称为最终v3源码的同时运行。

## 首次阶段结论：SEMANTIC_REPAIR_INCOMPLETE

v6 **未完成，不关闭 Goal**。A/B在固定v1003获得实际修订和正确主体证据；C在v977自然一批和在线六批均得到正确当前含义，独立fan-trailer活动保留。但v569新偏好回归在历史阶段失败，旧正文被错误关联到新来源，来源数组非空没有保证正文得到支持。不能用接口通过、四份原生通过或剩余额度掩盖这个结果。

| 计划答案 | 实际机制与材料 | 答案／原生结果 |
| --- | --- | --- |
| v1003 ordinary，一次修复后 | card:1@1→@2→@3；user来源arrival 2/4/8，依赖[]；assistant自述未成为用户经历 | 已答，采用scheduled workshops / tailored curricula；latest=1、outdated=0、pass=1 |
| v1003 State，独立历史 | card:1@3及新来源进入实际State→search；角色摘要引用已对齐 | 已答，推荐有结构课后课程；1／0／1 |
| v977默认，自然一批 | card:2@1同时记起写与停写，来源4/8；fan-trailer另存card:3@1、来源6 | 已答，建议轻松观影而非写影评；1／0／1 |
| v977在线六批 | 博客card:2@1→@2表明已停止；旧版及来源4保留，新版引用8；fan-trailer未覆盖 | 已答，明确避免分析／写影评；1／0／1 |
| v569在线七批 | 新偏好已交付，但模型保留旧正文并更换为不支持它的来源 | **答题前停止；未评分，不计判错或通过** |

四份完成答案来自两个原题；本轮共接触三个既定原题，五份计划答案不能称为五个独立样本。native Judge与Host同权重，均沿用原生rubric，没有人工改分。v1003 ordinary答案使用material view v2；其他三份已完成答案和v569历史使用最终v3，不把跨源码结果冒充严格同时对照。没有H2收益比较或统计质量结论。

State首轮实际写入任务subject／uncertainty，后续search的effective_query包含它们，`state_sha256=af55937cec60b65a5452007e9bc866f22db864b7aaebbbb654c09cafd853d596`。交付m1绑定准确card:1@3，正文、user来源角色及`UNDECLARED`范围限制进入材料，回答采用新的结构性偏好。其后两次intentions写入选择了source而非interpretation，被正常拒绝，均计入6次答题调用；不能把它描述为全部State写入成功，也不因此额外重试。

四份实际答案均无memory_save调用，没有新增问题或建议冒充的持久用户事实；真实历史维护仍提交CREATE和REVISE。无来源作者笔记合法、无来源持久用户事实拒绝、自身版本依赖拒绝、独立依赖失效和局部恢复由窄确定性测试验证，不冒充本轮原题中的额外行为。在线v977部分正文仍带临时pN字符，提示依从性不完全；结构化about与准确user原来源一致，本轮未为此再次调提示。

## 首次阶段 v569 失败定位与旧停止依据（后续授权已取代）

零起算batch4，trace第74行，完整交付source_sequence9的user新表达：开始新讨论组，偏爱严厉批评和激烈争论，认为比旧建设性聊天更有趣。旧card:3@1为r0，支持旧偏好的source_sequence5也完整交付；旧离开论坛记录为r1。旧材料omitted=0，REVISE生成分支可达，句柄和来源顺序正确。

实际模型提案却复制旧“more constructive and refreshing / without stress or harsh criticism”正文，对r0和r1提交REVISE，source_refs仅选s0（即新偏好来源9）。解析和提交没有修改正文，normalizations=[]，形成card:3@2和card:2@2。batch6（trace第115行）再次读到新偏好来源9，却把同一旧constructive正文修订为card:3@3，并改引来源13/11的万圣节活动。两个版本的内容与所引依据不相符；所有工具结算成功并不能使其成为有效语义修复。

root与一次针对性Sol xhigh只读判断均未发现错绑引用、漏交付、保存改写或生成合同错误。当前程序按合同负责身份、版本、关系及已交付引用；不能凭关键词自动改写语义，也不能静默换来源或关闭修订。该实例遵照Goal §8.2在答题前停止，未发出答题或Judge请求。一次模型局部复核已用于v1003；§8.3不允许因为账本尚余15次就继续调提示、反复重试。后续仍需解决“正文与来源含义不一致、忽略新偏好”的开发问题，本轮没有交付或声称已验证的修复。

失败输入、真实模型提案、绑定后arguments、提交回执及来源对应关系保存在 `artifacts/contextual-user-memory/v6-online-v569/semantic-diagnosis.json` 与其history目录。原始数据、旧checkpoint及评分均未修改。

## 首次阶段成本与源码身份

| 运行目录（均在artifacts/contextual-user-memory） | 历史请求／tokens | 答题请求／tokens | Judge请求／tokens | 总生成请求／tokens | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| v6-online-v1003，初次失败保留 | 6 / 26401 | 0 / 0 | 0 / 0 | 6 / 26401 | 1972 |
| v6-online-v1003-repair-1 | 6 / 22672 | 3 / 11173 | 1 / 1070 | 10 / 34915 | 4132 |
| v6-state-v1003 | 6 / 24536 | 6 / 32890 | 1 / 1000 | 13 / 58426 | 4374 |
| v6-default | 1 / 4905 | 6 / 24797 | 1 / 1093 | 8 / 30795 | 2223 |
| v6-online-v977 | 6 / 24605 | 6 / 25139 | 1 / 1105 | 13 / 50849 | 3624 |
| v6-online-v569，语义失败未答 | 7 / 31428 | 0 / 0 | 0 / 0 | 7 / 31428 | 2270 |
| **累计** | **32 / 134547** | **21 / 93999** | **4 / 4268** | **57 / 232814** | **18595** |

唯一新账本 `v6-budget.json` 与全部trace逐项相符：**57/72次生成、232814/350000生成tokens、18595/80000 embedding tokens，unknown=0**。失败、两次无效State调用和未评分历史全部计入；没有HTTP失败或Judge解析重试。原v5的114次账本未重开。完整阶段与身份汇总为 `v6-cost-and-identity.json`。

38文件源码映射散列（按排序JSON映射计算）：初次v1003 `4aa696c1983605d36e9d26890cb277e56177f70e38e3f0fd29c04f4689e1789f`；一次提案说明修复后ordinary `b5d4f54260d6e8715a4c166520af66541b4962b3a0bbb745fa2e7aa05aa3c275`；最终material view v3的State／默认／在线v977／v569均为 **`caa9955641ee25dafeaea7d03f263d453b94db470222b69ae2b81f23eb06e819`**，与首次阶段冻结的38个源文件逐项一致。最终method v9、operation v2、write v4、ingestion v11、material view v3。各目录manifest、sources、batches、checkpoint、chunk提案、trace与已完成原生scores独立保留。

最后的显示修复沿用37项材料／Host检查，其中一个旧v2常量断言更新为v3后单项复查通过；受影响ruff、mypy通过。提案说明修复后25项摄入／runner检查通过。语法schema随后未改变，21项实际XGrammar检查继续对应当前字段合同。未执行全套测试、完整benchmark、确认集、其他数据集或模型、Product修改、提交或推送。Goal保持未完成，不能以本报告代替语义验收。

## 解除限制后的继续修复（2026-09-24）

用户已明确“反思解决当前错误问题，移除限制”。取消一次局部复核及累计用量硬停止，保持同一个账本连续收费，原57次／232814生成tokens／18595 embedding tokens不清零；解除前快照及用户授权留在 `v6-budget-before-authorized-unlimit.json`。单次工作流仍有限，采用既有三个原题的少量诊断与回归，不扩大benchmark。

处理反思：前次确认不是错误绑定或保存改写后，过早以语义失败结束开发。真正需要继续研究的是生成时怎样先选依据、再形成新理解，避免旧卡正文被照抄后再附上新来源。当前“op→content→target/about/source”顺序在实际XGrammar下是生成顺序，而摄入输入又先给新observations、后给旧records/sources；两者是待验证的原因假设，不能仅凭观察当作已证实。接下来以最小可泛化改动验证，并保留负面结果。


## 继续开发：生成合同、摄入整理与作答边界

解除限制后首先将真实 XGrammar 生成顺序调整为 op、主体、来源／完整依赖、正文；独立历史说明明确本次新观察与旧背景，一次提案只维护发生变化的事项。旧材料在前，新观察在后，保留原消息及其内部顺序、角色、日期与范围。已取得的 user 说话者统一发布 u0，避免每条消息的局部 pN 句柄暗示不同人物。这些是共同合同和交付修复，没有根据题号或 gold 路由。

历史阶段去掉 task 持久性选项：过去发生的事实不等于只在当前任务内存活。曾出现 fan-trailer／playlist 被标记 task 并在任务结束清掉，这一实际错误已修复；普通作答工具仍保留 task 笔记能力。合并批摘要的两次诊断却丢失独立事项，未进入运行代码。来源字段的说明改用局部字典，修复共享 schema 模板别名导致说明互相污染。一次诊断 fixture 的引用域别名错误也已记录；运行 bind 本身已深复制，不将该 fixture 错误描述为服务缺陷。

继续复核中还纠正了自己的验收错误：v6-delivery-default 与 v6-unified-default 的旧博客卡 context 已明确写为历史，不能仅因卡片分开或正文单独看似当前而判定同批整理失败。两份 review-correction.json 撤回了原判断，原检查与费用保留。正确验收查看正文和 context 的整体含义，不强求一张卡。

method v9／write v8／ingestion v21／material view v4 的五份 v6-compact-* 固定路径，源码映射为 `a940ffafef478342d3043b4d24f451761b0a5a40e76ecc726dcd57500520e81d`。v1003 ordinary 和独立 State 保持正确主体、真实 REVISE 与无自身依赖；v569 新的严厉批评偏好进入当前正文并用于答案，七批来源完整。v977 两种分批均保留博客历史和停写现状、独立 fan-trailer。五份原生评分均为 1／0／1，但在线 v977 作答将当前问题中的居家／舒适需求混入持久用户卡，仅引停写来源，故该路径仍为作答写入修复未完成。原生通过不等于写入依据充分。

对冻结作答前上下文的两次单请求诊断曾返回正确答案，但全新在线执行并不稳定。v6-answer-grounding-online-v977 仍错误保存；v6-answer-task-online-v977 不再保存并通过原生评分。后一份说明复用于默认自然批时，v6-answer-task-default 又将历史 assistant 居家观影建议保存成 current_user 的持久事实，原生评分为 0／1／0。所有失败和负面诊断计费，未把重跑当成新样本或只选择成功结果。

源码进一步核对发现：memory_save 的旧说明仍鼓励“来源加正文返回分别结果”，与已分离的操作合同不一致；Host 对模型可见 JSON 统一 sort_keys，既把正文排到角色前，也使展示 schema 与实际受约束生成顺序不一致。现改为明确维护缺失历史理解或修订、答案走 answer 通道；模型可见字段保持合同顺序，仅内部缓存键使用排序。共享 save 在变更前拒绝仅有 assistant 来源的持久 current_user CREATE／REVISE，不改写提案，不隐藏 assistant 来源，也不增加语义审核模型。

该最新合同为 method v10、write v9、ingestion v22、material view v4、operation v2。旧 checkpoint 不迁移；每个新身份重新由原文形成历史。最新来源权限边界、修订与 Host／摄入窄测 72 项通过，新增的模型可见字段次序断言另单项通过；受影响 ruff／mypy 通过。实际部署 XGrammar 24 项通过，包含普通与历史写入、State、独立作者笔记，以及历史 task 分支不可达；它们不是原生评分。后续最新真实运行结果见下文。


## 最后两处来源与主体修复的真实结果

v6-source-authority-default（自然一批）作答没有 memory_save，原生评分 1／0／1。v6-source-authority-online-v977 又提出仅引用 assistant seq3 的持久 u0 记录，共享 save 实际拒绝，持久记忆未受污染；随后完成答案，原生评分为 0／1／0。Judge 将建议外语电影、允许按意愿分析视为旧偏好污染；该原分与理由完整保留，不作人工改分或为追分重跑。这个结果证明来源边界生效，不证明 Host 已不再产生错误提案。

同一版本 v1003 六批另暴露相反方向的主体问题：card:2@2 把 user seq6 的法律话题探索合入 assistant 文章经历，@3 再加入 user seq12 主持讨论组的经历；card:1@5 用户结构化志愿服务本身正确且无自身依赖。这仍属于主体修复未完成，停在答题前并保留全部成本。针对性只读复核确认：不仅旧说明单向强调 assistant 不能当用户，摄入自己的 JSON 构造也仍把正文放在主体／角色前；旧正文中临时 p0 名称与下一批权威 about=p1 相冲突。最后一批预算省略用户目标卡，但 CREATE 合法，不能借用唯一交付的其他人记录。

随后摄入 v23 用对称说明替换单向例子：第一人称自述依据本条来源的说话者解释（显式引文除外），话题连续不转移经历；合并／修订核对同人同事项，没有匹配的已交付目标时可创建独立理解。来源、旧卡及依赖均将准确身份／角色置于正文前，字段值、数组顺序与预算未改变；没有正则清洗错误旧文或主体关键词分类器。增补既有字段次序断言后，摄入／runner 26 项窄测、受影响 ruff 和 mypy 通过。生成 schema 未变，沿用 write v9 的 24 项实际 XGrammar 结果。

fan-trailer 记录仍可能把创作活动与安静观影作无依据反差，并过度标为 explicit。这是实质解释质量限制；被比较的独立卡确为准确已交付前提，且旧观影记录没有被替代、停止博客没有覆盖 fan-trailer，因此不伪称它是自身依赖错误，也不把该反差认可为用户事实。所有局部临时句柄正文及不必要的宽泛聚合继续作为质量限制披露。


v23 的真实 v1003 在第三批仍失败：旧正文写的 p0 被新批当作另一来源，触发 ABOUT_SOURCE_NOT_CITED；另一独立操作已成功提交，不能把局部失败误报成全部回滚。该未完成目录与三次请求全部保留。

摄入 v24／material view v5 随后共用稳定说话者命名：直接复用同一 memory 命名空间下 exact source 的完整 local key，添加 p 前缀，不截短重散列，不依赖可能重复的到达序号。它表示准确来源锚点，不断言两个来源是否同一个自然人。当前用户仍为 u0；只有实际交付原文才开放绑定，ABOUT_SOURCE_NOT_CITED 及正常主体纠错路径保留。没有修改旧 checkpoint 或旧正文。44 项摄入／投影／Host 窄测通过，追加反向交付、跨 Host 视图以及重复到达序号异源不混淆的断言后，相关 7 项通过；受影响 ruff／mypy 通过。


稳定句柄版本 ordinary v1003 获得 card:1@6、全 user 来源和正确答案（1／0／1），但独立 State 历史仍把 user seq6 合入 assistant 文章卡。该结果再次证明稳定引用不等于语义正确；State 路径停在答题前，六批费用保留。摄入 v25 因此进一步明确用户记忆的任务范围：其他说话者的无关个人传记不因出现在对话中就另行总结，其原文继续保留并可检索；与当前用户有关的关系、限制、语境仍可维护。这不是隐藏 assistant、禁用作者笔记或按角色过滤全部信息。失败批次的一次冻结诊断仅 REVISE 用户记录，没有创建无关 biography（3684 tokens，无记忆提交）；完整路径的实际结果另列。


## 最终限定验收与明确的质量边界

最终五份运行目录均以 `v6-user-scope-` 开头。摄入前冻结配置和源码，由未修改原文重新构建；ordinary 与 State 没有共享或编辑 checkpoint 身份。五份历史全部覆盖原消息，操作错误和未完成维护均为 0。五份答案均完成，历史仍真实 CREATE／REVISE，作答没有将问题或建议写入持久记忆；不是通过禁用写入获得这一结果。

| 路径／配置 | 历史／答题／Judge 生成请求 | 生成 tokens | embedding tokens | 原生 latest／outdated／pass |
| --- | ---: | ---: | ---: | --- |
| [v1003 ordinary，6 批](../configs/contextual-memory-v6-user-scope-online-v1003.json) | 6 / 2 / 1 | 34717 | 5377 | 1／0／1 |
| [v1003 State，独立 6 批](../configs/contextual-memory-v6-user-scope-state-v1003.json) | 6 / 3 / 1 | 38135 | 4984 | 1／0／1 |
| [v977 默认自然一批](../configs/contextual-memory-v6-user-scope-default.json) | 1 / 2 / 1 | 14020 | 2197 | 1／0／1 |
| [v977 在线 6 批](../configs/contextual-memory-v6-user-scope-online-v977.json) | 6 / 3 / 1 | 38868 | 4212 | 1／0／1 |
| [v569 在线 7 批](../configs/contextual-memory-v6-user-scope-online-v569.json) | 7 / 2 / 1 | 39189 | 4854 | 1／0／1 |
| **最后一组有限验证** | **26 / 12 / 5 = 43** | **164929** | **21624** | **五路径完成；仅三个原题** |

- **主体与修订**：v1003 ordinary 的 current_user card:1@6 与 State 的独立 card:1@5 均使用新的结构化课后法律课程／workshops 偏好，活动依赖为空，没有自身版本依赖。assistant seq5 的住房／环境文章自述仅作为原文保留，未成为用户经历；State 路径也不再把 user seq6 合入 assistant 传记。ordinary 来源为 2/4/6/8/10/11/12（含 assistant seq11 的对话语境），State 为 user 2/4/6/8/12。程序仍允许真实跨角色引用，不机械以来源角色代替正文主体判断。
- **同批与在线范围**：默认 v977 card:2@1 引 4/8，在正文同时表达起写博客和后来的停写；fan-trailer 独立 card:3@1 引 6，退订新闻博客单独引 10。在线 card:1@6 聚合 2/4/6/8/10/12，但仍明确博客已停止、fan-trailer 为另一项保留的正面创作经历，没有将停止影评套到后者。不同分批不要求相同卡数。
- **原失败 v569**：card:2@5 正文引用旧 3/5、新 9 及后续活动 11/13，明确从建设性聊天转向严厉批评和激烈讨论；新偏好没有在万圣节活动到达后丢失。独立播放列表 card:3@1 引 7、改编兴趣 card:1@1 引 1 保留。实际答案选择新偏好，原生 1／0／1。
- **State 真实消费**：首次 memory_state 后 memory_search 的有效查询包含任务 subject／uncertainty，交付当前 card:1@5、user seq8 等实际材料及范围限制。`state_sha256=472a3fa344f27499c5aaefd6d52f3e61b1cb1d6e34fa22e2546015c14ed52324`。最终 State 调用均成功。ordinary／State 历史 cache_id 分别为 `70f4c260092d2b30480f7de845a1e9c847aeaa1575e32014b92c4b6aeacd2541` 和 `5265cd49b80a19de717d8a2ca8b7445e32667c691a7063aae96727fd2f44eb84`。
- **确定性写入边界**：此前 source-authority 在线路径已真实观察 assistant-only durable current_user 提案被拒绝而无污染；新主体命名没有改变该 core/save 边界。无来源作者笔记、正确归属的 assistant 记录、真实独立依赖失效、准确版本／CAS 和局部恢复由受影响窄检查保留。没有第二语义 Judge、自动改写提案或全局关键词分类器。

必须保留的质量限制：模型仍会把多个事项汇成较宽的一张卡，正文可能残留 batch-local sN 引用，个别解释强于来源（例如把 AI 兴趣进一步说成最初志愿工作的动机）。State 未读取前曾写“No prior history exists”，实际应是尚未知晓；这一任务态过强表达没有阻止基线搜索，也没有成为持久事实。先前 fan-trailer 与安静观影的无依据反差、错误主体提案、两份原生 0／1／0 及所有未评分失败均保留，不能称为全程通过。最终语义边界与原生答案达到本轮限定要求，并不证明所有生成理解可靠。

本轮只有三个已暴露原题；多版本诊断与回归高度相关，Host 和原生 Judge 同模型。自然语言评分存在解释差异，未改 rubric、gold、原文、排名或模型。没有 H2 收益复跑、统计显著性／创新性结论、完整 benchmark、未用确认集、全套测试、构建、Product 修改、提交或推送。

## 全部费用、失败留存与开发反思

| 所有版本的阶段 | 生成请求 | 生成 tokens | embedding 请求／tokens |
| --- | ---: | ---: | ---: |
| 冻结上下文诊断 | 9 | 43890 | 0 / 0 |
| 历史摄入（含未答与局部失败） | 136 | 564375 | 207 / 46169 |
| 答题（含被拒操作） | 77 | 336522 | 43 / 47221 |
| 原生 Judge | 21 | 24723 | 0 / 0 |
| **累计** | **243** | **969510** | **250 / 93390** |

首次阶段为 57／232814／18595；继续开发为 186／736696／74795，均使用同一个 `v6-budget.json`。累计限制为 null，只记账，不清除历史收费。HTTP 收据均有明确用量，unknown=0；已拒绝的本地提交与语义失败仍是失败，不因 HTTP 成功计为通过。完整按运行目录、阶段、源码身份及原生分数汇总位于 `v6-final-cost-and-identity.json`；九份诊断为 `v6-local-diagnostics.json`；最终五份当前源码核对为 `v6-final-validation.json`，均在 ignored 的 `artifacts/contextual-user-memory/` 下。

这次开发成本高于最初计划，不能把最后五条路径的通过描述为廉价或一次成功。主要失误有三点：过早以语义错误及复核次数停止开发；把显式历史 context 的分卡误判为失败；将单请求诊断有效误推成完整执行必然有效。后续具体修复转向共同合同和交付：先主体／来源再正文、历史与任务信息分工、稳定准确说话者句柄、明确当前用户记忆目的，以及提交前的一条 assistant-only 来源边界。原始证据和负面结果使这些修复可核对，但没有进行独立消融，不能把收益归因给单一提示句或声称普遍成本优势。

源码冻结后只核对五份配置、38 文件散列、原生数据 manifest 与文档链接；没有追加模型调用或扩大测试。相关窄测试、ruff／mypy 及实际 XGrammar 结果已在上文分阶段列明，不把重复运行次数累加为独立测试覆盖。
